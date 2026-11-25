"""Backend-agnostic atomic write helper.

Writes bytes to ``path`` on ``backend`` so that concurrent readers
either observe the old content or the new content — never a partial
or mixed state. Implementation strategy depends on what the backend
supports:

* **Native-atomic backends** (S3, Azure Blob, Dropbox, GDrive,
  OneDrive, IMAP): a single PUT / upload is server-side atomic; the
  previous object is replaced exactly at response-commit time.
  Strategy → plain ``open_write`` + ``close``. Azure Files is NOT one:
  its upload resets the file (Create File) and then writes ranges.

* **Rename-capable backends** (LocalFS, SFTP, NFS, iSCSI, SMB,
  WebDAV, FTP, FTPS, Rsync, Telnet, SCP): write to a sibling temp
  file, then finalize it into place. Strategy →
  ``open_write(tmp)`` + ``close`` + rollback-safe finalization. If
  the backend cannot overwrite via ``rename`` directly, the existing
  destination is backed up, the temp is moved into place, and the
  backup is restored on commit failure.

* **Backends without rename** (TFTP): there is no temp-file route, so
  the write goes straight to the target - not atomic, because the
  protocol offers nothing that is. Read from the registry's
  ``can_rename``, so a new backend gets this without touching this
  module.

Unknown backend classes take the temp-file route.

A LOCAL file is written in place instead when a rename would lose
something the user did not ask to lose (vim's ``backupcopy=auto`` rule):
other hard links (they would keep the old text), a folder the user may
not create files in (the save would fail although the file is
writable), another owner, or extended attributes / a group the new file
cannot be given. In place keeps the old bytes recoverable - a backup
copy beside the file when the folder is writable, otherwise in memory -
and writes them back when the save fails part-way. It is not atomic
against a crash; that is the price of keeping the file's identity.
``atomic_write_stream`` (transfers, restores) keeps the rename route.
"""

from __future__ import annotations

import errno
import io
import logging
import os
import secrets
import stat as stat_module
from typing import TYPE_CHECKING

from axross_markdown._ax.core import backend_registry
from axross_markdown._ax.core.path_policy import safe_join

if TYPE_CHECKING:  # pragma: no cover
    pass

log = logging.getLogger(__name__)


# Backends whose SINGLE open_write -> close is already atomic at the
# protocol level — so temp-file-then-rename is wasteful and sometimes
# not even possible (no rename semantics).
_NATIVE_ATOMIC_PROTOCOLS = frozenset(
    {
        "s3",
        "azure_blob",
        # Not "azure_files": ShareFileClient.upload_file sends Create File
        # (the existing file reset to the new length, zero-filled) before
        # uploading ranges, so a failure part-way destroys the old file.
        "dropbox",
        "gdrive",
        "onedrive",
        "sharepoint",
        "imap",
        "rsync",  # rsync itself uses temp + rename internally
    }
)


def _is_native_atomic(backend) -> bool:
    """Ask the registry whether writes to this backend class are
    already atomic without help from us."""
    try:
        from axross_markdown._ax.core.db_fs_base import DbFsBackend

        if isinstance(backend, DbFsBackend):
            return True
    except Exception:
        pass
    class_name = type(backend).__name__
    for info in backend_registry.all_backends():
        if info.class_name == class_name:
            return info.protocol_id in _NATIVE_ATOMIC_PROTOCOLS
    # Unknown backend: assume we need rename-safety
    return False


def _cannot_rename(backend) -> bool:
    """Whether the registry says this backend class has no rename (TFTP):
    there is no temp-file route, a single open_write is all the protocol
    offers - the transfer engine writes such backends directly too."""
    class_name = type(backend).__name__
    for info in backend_registry.all_backends():
        if info.class_name == class_name:
            return not info.capabilities.can_rename
    return False


def _finish_journal(op_id: str, operation: str, **fields) -> None:
    if not op_id:
        return
    try:
        from axross_markdown._ax.core.operation_journal import finish_operation

        finish_operation(op_id, operation, **fields)
    except Exception as exc:  # noqa: BLE001
        log.debug("%s: journal finish failed: %s", operation, exc)


def _temp_sibling(backend, path: str) -> str:
    """Return a sibling temp path in the same dir as *path*, using the
    backend's own separator conventions.

    The name is deliberately generic (``.tmp-<hex>.tmp``) so server-side
    observers can't attribute it back to Axross specifically. The hex
    suffix is still long enough (``secrets.token_hex(6)`` = 12 chars)
    to uniquely identify the write, and ``atomic_recovery`` matches
    that exact 12-hex shape plus an older ``.axross-atomic-`` prefix
    for backward compatibility with pre-scrub installs.
    """
    parent = backend.parent(path) if hasattr(backend, "parent") else os.path.dirname(path)
    suffix = secrets.token_hex(6)
    name = f".tmp-{suffix}.tmp"
    if hasattr(backend, "join"):
        return safe_join(backend, parent, name)
    return os.path.join(parent, name)


#: Symlinks followed before a save gives up with ELOOP (Linux MAXSYMLINKS).
MAX_LINK_HOPS = 40


def _link_destination(backend, link: str, target: str, hops: list[int] | None = None) -> str:
    """The path a symlink at *link* with content *target* names: *target*
    itself, or below the link's folder - its ``..`` steps taken one at a
    time (:func:`_without_parent_steps`)."""
    sep = backend.separator() if hasattr(backend, "separator") else "/"
    if target.startswith(sep) or (sep == os.sep and os.path.isabs(target)):
        return _without_parent_steps(backend, target, hops)
    parent = backend.parent(link) if hasattr(backend, "parent") else os.path.dirname(link)
    if hasattr(backend, "join"):
        return _without_parent_steps(backend, backend.join(parent, target), hops)
    return _without_parent_steps(backend, os.path.join(parent, target), hops)


def _has_parent_step(path: str, sep: str) -> bool:
    if ".." not in path:
        return False
    names = path.replace("\\", "/").split("/") if sep == "\\" else path.split(sep)
    return ".." in names


def _without_parent_steps(backend, path: str, hops: list[int] | None = None) -> str:
    """*path* without its ``..`` components, each taken where it really
    leads: the folder before a ``..`` is asked about first, and when it is
    a link, the link is followed (one hop at a time, :data:`MAX_LINK_HOPS`
    in all) before the step up - ``link/..`` is the folder above the
    link's target, not the one the link lies in. A path without ``..`` comes
    back as it is.

    A save to ``sub/l2.md -> ../target.md`` went to ``sub/../target.md``:
    the write of the temp file there worked, its rename and its removal
    were refused (a rename or remove never takes a ``..``, core.backend_guard),
    so the file could never be saved through that link and every try left
    a temp file beside it."""
    sep = backend.separator() if hasattr(backend, "separator") else "/"
    if not _has_parent_step(path, sep):
        return path
    hops = [0] if hops is None else hops
    if sep == "\\":
        path = path.replace("/", sep)
    names = path.split(sep)
    kept, floor = _rooted(names[:1])
    for name in names[floor:]:
        if name in ("", "."):
            continue
        if name != "..":
            kept.append(name)
        elif len(kept) > floor and kept[-1] != "..":
            kept, floor = _folder_itself(backend, kept, sep, hops, path)
            if len(kept) > floor:
                kept.pop()
        elif not floor:
            kept.append(name)  # (above a relative path's start: left as written, for the backend to refuse)
        # (above the root is the root)
    if kept == [""]:
        return sep
    return sep.join(kept) or "."


def _rooted(names: list[str]) -> tuple[list[str], int]:
    """(*names* to go on from, how many of them are the root - "" before the
    first separator, or a drive - which no ``..`` goes above)."""
    if names and (names[0] == "" or names[0].endswith(":")):
        return list(names), 1
    return [], 0


def _folder_itself(backend, kept: list[str], sep: str, hops: list[int], path: str) -> tuple[list[str], int]:
    """(the names of the folder *kept* names, its root's length) - the folder
    a link there leads to, followed to its end."""
    floor = _rooted(kept[:1])[1]
    while len(kept) > floor:
        folder = sep.join(kept)
        target = _link_target(backend, folder)
        if target is None:
            break
        hops[0] += 1
        if hops[0] > MAX_LINK_HOPS:
            raise OSError(errno.ELOOP, os.strerror(errno.ELOOP), path)
        # (the link's own target may hold ``..`` again: taken the same way)
        kept = _link_destination(backend, folder, target, hops).split(sep)
        if len(kept) > 1 and kept[-1] == "":
            kept.pop()
        floor = _rooted(kept[:1])[1]
        if not floor and kept[:1] == [".."]:
            break  # (a relative link above its start: nothing more to ask about)
    return kept, floor


def _link_target(backend, path: str) -> str | None:
    """What the link at *path* holds; None when *path* is no link, is not
    there, or cannot be asked about (the step up is then taken by name)."""
    try:
        info = backend.stat(path)
    except OSError:
        return None
    if getattr(info, "is_link", False) is not True:
        return None
    try:
        return backend.readlink(path) or None
    except (OSError, AttributeError, NotImplementedError):
        return None


def _is_absent(backend, path: str, exc: OSError) -> bool:
    """Whether the stat failure *exc* means *path* is not there. RamFS
    and some shell backends raise a plain OSError for a missing path, so
    anything but FileNotFoundError asks exists(), which says False only
    for "not found" (and raises otherwise)."""
    if isinstance(exc, (FileNotFoundError, NotADirectoryError)):
        return True
    if isinstance(exc, PermissionError) or not hasattr(backend, "exists"):
        return False
    return not backend.exists(path)


def _resolve_destination(backend, path: str) -> tuple[str, int | None] | None:
    """The file a save to *path* replaces, and its permission bits.

    The temp-file route renames a fresh file over the destination. Over
    a symlink that replaced the LINK with a regular file, left the real
    target untouched and gave the new file the link's lstat mode (0777),
    so a symlink is followed to the file it names first.

    The mode is ``None`` both for "the file is new" (it should get the
    default mode, not an inherited one) and for "this backend does not
    report a mode" — S3, IMAP and the cloud stores have no such concept,
    and inventing one would be worse than leaving it alone.

    Returns ``None`` for a link the backend reports but cannot read; the
    caller writes through it then instead of replacing it. A chain longer
    than :data:`MAX_LINK_HOPS` (a loop) raises ``ELOOP``. No ``..`` is left
    in the path returned (:func:`_without_parent_steps`).
    """
    hops = [0]
    current = _without_parent_steps(backend, path, hops)
    for _hop in range(MAX_LINK_HOPS + 1):
        try:
            info = backend.stat(current)
        except OSError as exc:
            if _is_absent(backend, current, exc):
                return current, None
            # A stat that failed is no "new file": the temp file would get
            # the default mode (a 0600 secret came back 0644) and replace a
            # link with a regular file. Nothing is written yet.
            raise OSError(
                f"cannot read the mode of {current} before saving it: {exc}"
            ) from exc
        # ``is not True``: FileItem.is_link is a bool; anything else
        # (a stand-in object) is no link to follow.
        if getattr(info, "is_link", False) is not True:
            mode = getattr(info, "permissions", 0)
            return current, (int(mode) & 0o7777 if mode else None)
        try:
            target = backend.readlink(current)
        except (OSError, AttributeError, NotImplementedError) as exc:
            log.debug("atomic_write: cannot read the link %s: %s", current, exc)
            return None
        if not target:
            return None
        current = _link_destination(backend, current, target, hops)
    raise OSError(errno.ELOOP, os.strerror(errno.ELOOP), path)


def _restore_mode(backend, path: str, mode: int) -> None:
    """Best effort: a backend without chmod must not fail the save."""
    try:
        backend.chmod(path, mode)
    except (OSError, AttributeError, NotImplementedError) as exc:
        log.debug("atomic_write: could not restore mode %04o on %s: %s", mode, path, exc)


def _precreate_with_mode(backend, tmp: str, mode: int) -> None:
    """Create *tmp* empty and give it *mode* BEFORE any data lands.

    Chmod-after-write leaves a window in which a 0600 secret sits in a
    umask-mode (typically 0644) temp file next to its target. Truncating
    re-open keeps the mode the file already has.
    """
    with backend.open_write(tmp):
        pass
    _restore_mode(backend, tmp, mode)


#: Added to the temp file's mode while the data goes in: a read-only
#: target (0444) gave its temp 0444 before the write, and the write was
#: refused. Only the owner gains a bit; the final mode is restored after.
_OWNER_WRITE = 0o200


def _is_local(backend) -> bool:
    try:
        from axross_markdown._ax.core.local_fs import LocalFS
    except Exception:  # noqa: BLE001
        return False
    return isinstance(backend, LocalFS)


def _private_local(backend) -> bool:
    """LocalFS with its own open_write (core.local_fs.LocalFS.private_writes):
    its temp file is created exclusively, never through a link, and written
    through that one descriptor."""
    check = getattr(backend, "private_writes", None)
    try:
        return bool(callable(check) and check())
    except Exception:  # noqa: BLE001 - a stand-in without the method's state
        return False


class _ModeLeftToSet:
    """A writer opened with the file's mode as the server took it (its umask
    applies): the exact mode is set once the data is in."""

    def __init__(self, fh) -> None:
        self._fh = fh

    def __getattr__(self, name):
        return getattr(self._fh, name)

    def __enter__(self):
        self._fh.__enter__()
        return self

    def __exit__(self, *exc):
        return self._fh.__exit__(*exc)


def _mode_left_to_set(f, written, previous_mode) -> bool:
    return written is None and previous_mode is not None and (
        not previous_mode & _OWNER_WRITE or isinstance(f, _ModeLeftToSet))


def _open_new_with_mode(backend, path: str, mode: int):
    """*path* created with *mode* from its first byte by a backend that can
    (``open_write_new``: SFTP sends the mode with its OPEN request), else
    None. Precreated empty and chmod-ed after, a file sat in the server's
    default mode (0644) for a moment: anyone who opened it then could read
    what was written into it later through that handle."""
    # Defined by the backend's class: an attribute a stand-in makes up on
    # request (a MagicMock) is no such promise.
    if not callable(getattr(type(backend), "open_write_new", None)):
        return None
    opener = backend.open_write_new
    try:
        return opener(path, mode)
    except (NotImplementedError, AttributeError, TypeError) as exc:
        log.debug("cannot create %s with its mode at once: %s", path, exc)
        return None


def _open_temp(backend, tmp: str, previous_mode: int | None, group: int | None = None):
    """``(handle, its fstat or None)`` of the new temp file *tmp*.

    On the local file system it is created exclusively (O_EXCL, no link
    followed), 0600, and given *previous_mode* through its descriptor
    before a byte lands - created with the umask's 0644 and chmod-ed by name
    afterwards, anyone could open a secret's temp file in between and read
    it later through that descriptor, and a link swapped in under the name
    took the chmod and the bytes (review round 9). Elsewhere: precreated
    with the mode, then opened by name, as before."""
    if _private_local(backend):
        from axross_markdown._ax.core.local_fs import create_private_file

        fh = create_private_file(tmp, previous_mode, group=group)
        try:
            return fh, os.fstat(fh.fileno())
        except BaseException:
            fh.close()
            raise
    if previous_mode is not None:
        fh = _open_new_with_mode(backend, tmp, previous_mode | _OWNER_WRITE)
        if fh is not None:
            # The server's umask may have narrowed it: given exactly after
            # the write (_mode_left_to_set).
            return _ModeLeftToSet(fh), None
        _precreate_with_mode(backend, tmp, previous_mode | _OWNER_WRITE)
    return backend.open_write(tmp), None


def _refuse_swapped_temp(tmp: str, written) -> None:
    """OSError when the local temp file *tmp* is no longer the file written
    through its descriptor (*written*): the rename would put what was put
    there in the target's place."""
    if written is None:
        return
    from axross_markdown._ax.core.local_fs import same_entry

    if not same_entry(tmp, written):
        raise OSError(errno.EIO, f"the temp file {tmp} was replaced while it was written", tmp)


def _keep_identity_reason(backend, path: str) -> str | None:
    """Why a save to the local file *path* must write INTO the file
    instead of renaming a new one over it; ``None`` when a rename loses
    nothing. Paths of any other backend are not paths on this machine."""
    if not _is_local(backend):
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None  # a new file: nothing to keep
    if not stat_module.S_ISREG(st.st_mode):
        return None
    if st.st_nlink > 1:
        return "the file has other hard links"
    folder = os.path.dirname(os.path.abspath(path))
    if not os.access(folder, os.W_OK):
        return "its folder is not writable"
    if hasattr(os, "geteuid") and st.st_uid != os.geteuid():
        return "it belongs to another user"
    return None


def _carry_local_attributes(backend, src: str, dst: str) -> bool:
    """Give the local temp *dst* the group and extended attributes of
    *src*. False when one of them cannot be carried over: the rename
    would drop it, so the caller writes in place instead."""
    if not _is_local(backend):
        return True
    try:
        st_src, st_dst = os.stat(src), os.stat(dst)
    except OSError:
        return True  # a new file: nothing to carry
    if hasattr(os, "chown") and st_src.st_gid != st_dst.st_gid:
        try:
            os.chown(dst, -1, st_src.st_gid)
        except OSError as exc:
            log.debug("atomic_write: cannot give %s the group of %s: %s", dst, src, exc)
            return False
    if not hasattr(os, "listxattr"):
        return True
    try:
        names = os.listxattr(src)
    except OSError:
        return True  # the file system has no xattrs
    for name in names:
        try:
            value = os.getxattr(src, name)
            try:
                if os.getxattr(dst, name) == value:
                    continue  # e.g. the security label the folder gave it
            except OSError:
                pass
            os.setxattr(dst, name, value)
        except OSError as exc:
            log.debug("atomic_write: cannot carry xattr %s to %s: %s", name, dst, exc)
            return False
    return True


def _carry_remote_owner(backend, src: str, dst: str) -> bool:
    """Give the remote temp *dst* the owner and group of *src* (a backend
    with owner_ids() and chown(): SFTP). False when they differ and cannot
    be set: renamed over it, the new file would belong to the login (as
    root over SFTP, www-data's 0640 config.php came back as root:root and
    the web server could no longer read it)."""
    if _is_local(backend):
        return True
    owner_ids = getattr(backend, "owner_ids", None)
    chown = getattr(backend, "chown", None)
    if owner_ids is None or chown is None:
        return True
    try:
        want = owner_ids(src)
    except OSError:
        return True  # a new file: nothing to keep
    try:
        have = owner_ids(dst)
    except OSError:
        have = None
    if want is None or want == have:
        return True
    try:
        chown(dst, *want)
    except (OSError, NotImplementedError) as exc:
        log.debug("atomic_write: cannot give %s the owner of %s: %s", dst, src, exc)
        return False
    return True


def _write_through(backend, op_id: str, path: str, data: bytes, reason: str) -> None:
    """Write *data* into the remote file *path* itself (it keeps its owner,
    group and links) - with its old bytes put back when the write fails."""
    log.info("atomic_write: writing %s in place: %s", path, reason)
    with backend.open_read(path) as fh:
        old = fh.read()
    try:
        with backend.open_write(path) as f:
            f.write(data)
    except BaseException as exc:
        try:
            with backend.open_write(path) as f:
                f.write(old)
        except Exception as undo_exc:  # noqa: BLE001 - the original error is raised
            log.error("atomic_write: could not restore %s after a failed save: %s", path, undo_exc)
        _finish_journal(op_id, "atomic_write", status="error", dest=path, bytes_total=len(data),
                        error=str(exc))
        raise
    _finish_journal(op_id, "atomic_write", status="done", dest=path, bytes_total=len(data),
                    bytes_done=len(data), details={"in_place": reason})


def _overwrite_local(path: str, data: bytes) -> None:
    """Write *data* into the existing local file *path* (same inode)."""
    with open(path, "r+b") as fh:
        fh.write(data)
        fh.truncate()
        fh.flush()
        os.fsync(fh.fileno())


def _private_backup(path: str, backup: str) -> None:
    """Copy *path* to the new file *backup*, made O_EXCL and never readable
    by more than the file itself (its mode, 0600 at most while it is
    written): shutil.copyfile made it 0666 less the umask, and a 0600
    file's old content was readable by anyone for the save - for good
    when the restore failed. A copy that fails leaves no part of it."""
    import shutil

    from axross_markdown._ax.core.local_fs import create_private_file

    mode = (os.stat(path).st_mode & 0o600) | 0o400  # the owner reads it back
    try:
        with open(path, "rb") as src, create_private_file(backup, mode) as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
    except BaseException:
        try:
            os.remove(backup)
        except OSError:
            pass
        raise


def _write_in_place(path: str, data: bytes) -> None:
    """Overwrite the local file *path*, keeping inode, links, owner and
    attributes, with the old bytes recoverable until the write is done."""
    from axross_markdown._ax.core.path_policy import hidden_sibling_name

    if not os.access(path, os.W_OK):
        # Refused before anything is touched (a read-only file in a
        # read-only folder): the same error a direct open would give.
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), path)
    folder = os.path.dirname(os.path.abspath(path))
    backup = None
    old = None
    if os.access(folder, os.W_OK):
        backup = os.path.join(
            folder,
            hidden_sibling_name(os.path.basename(path), f".{secrets.token_hex(6)}.bak"),
        )
        _private_backup(path, backup)
    else:
        with open(path, "rb") as fh:
            old = fh.read()
    try:
        _overwrite_local(path, data)
    except BaseException:
        try:
            if backup is not None:
                with open(backup, "rb") as fh:
                    old = fh.read()
            _overwrite_local(path, old)
        except Exception as undo_exc:  # noqa: BLE001 - the original error is raised
            kept = f"; the old content is in {backup}" if backup else ""
            log.error(
                "atomic_write: could not restore %s after a failed save%s: %s",
                path,
                kept,
                undo_exc,
            )
        else:
            if backup is not None:
                os.remove(backup)
        raise
    if backup is not None:
        os.remove(backup)


def _in_place_journaled(op_id: str, path: str, data: bytes, reason: str) -> None:
    log.info("atomic_write: writing %s in place: %s", path, reason)
    try:
        _write_in_place(path, data)
    except BaseException as exc:
        _finish_journal(
            op_id,
            "atomic_write",
            status="error",
            dest=path,
            bytes_total=len(data),
            error=str(exc),
        )
        raise
    _finish_journal(
        op_id,
        "atomic_write",
        status="done",
        dest=path,
        bytes_total=len(data),
        bytes_done=len(data),
        details={"in_place": reason},
    )


def _refuse_parent_steps(backend, path: str) -> None:
    """PermissionError before anything is written when *path* still holds a
    ``..`` (one above a relative path's start, or written the Windows way
    on a backend that splits on a backslash): the temp file could be
    written there, but neither renamed nor removed (core.backend_guard
    refuses both), so every try left one behind."""
    try:
        from axross_markdown._ax.core.backend_guard import has_parent_component
    except ImportError:  # pragma: no cover - the guard is part of every build
        return
    try:
        refused = has_parent_component(backend, path)
    except Exception:  # noqa: BLE001 - a stand-in backend the guard cannot ask
        refused = False
    if refused:
        raise PermissionError(errno.EPERM, "refusing to save to a path with '..' in it", path)


def _sync_written(backend, f) -> None:
    """The local temp file's bytes on the disk before it is renamed into
    place: without it a power loss right after the rename could leave the
    name with an empty file - the old text gone, the new one never written.
    Only a local file has a descriptor to sync."""
    if not _is_local(backend):
        return
    try:
        f.flush()
        os.fsync(f.fileno())
    except (AttributeError, ValueError, io.UnsupportedOperation):
        return  # (a writer without a descriptor: a LocalFS subclass with its own)
    except OSError as exc:
        if exc.errno not in (errno.EINVAL, errno.ENOTSUP, errno.EROFS):
            raise
        log.debug("atomic_write: this file system does not sync %s: %s", getattr(f, "name", ""), exc)


def _sync_folder(backend, path: str) -> None:
    """The rename itself on the disk: the folder of the local file *path*
    synced (best effort - Windows and some file systems cannot). Only for
    the plain local file system: a LocalFS that confines its paths (the MCP
    server's) opens nothing by name here."""
    if not _private_local(backend) or os.name != "posix":
        return
    folder = os.path.dirname(os.path.abspath(path)) or os.sep
    try:
        fd = os.open(folder, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        log.debug("atomic_write: cannot open %s to sync it: %s", folder, exc)
        return
    try:
        os.fsync(fd)
    except OSError as exc:
        log.debug("atomic_write: cannot sync %s: %s", folder, exc)
    finally:
        os.close(fd)


def _drop_temp(backend, tmp: str, what: str = "atomic_write") -> None:
    """The temp file *tmp* gone after a save that failed (best effort, the
    save's own error is the one raised). A local one this module made itself
    is unlinked by name when the backend will not remove it (a name the
    guard refuses): it held the text and stayed beside the file."""
    try:
        if backend.exists(tmp):
            backend.remove(tmp)
        return
    except Exception as cleanup_exc:  # noqa: BLE001
        log.debug("%s: cleanup of %s failed: %s", what, tmp, cleanup_exc)
    if _private_local(backend):
        try:
            os.unlink(tmp)
        except OSError as cleanup_exc:
            log.debug("%s: cleanup of %s failed: %s", what, tmp, cleanup_exc)


def read_only_target(backend, path: str) -> bool:
    """Whether a save to the local file *path* would replace a file marked
    read-only (through its links: the file itself): no write bit for the
    one who saves, in a folder that lets the file be replaced all the same -
    the rename route gives the new file the old one's mode, so a 0444 file
    was replaced without a word. The editor asks first. False for a file
    that is not there, for another backend's, and when nothing can be said."""
    if not _is_local(backend):
        return False
    try:
        resolved = _resolve_destination(backend, path)
    except OSError:
        return False
    if resolved is None:
        return False
    try:
        st = os.stat(resolved[0])
    except OSError:
        return False
    if not stat_module.S_ISREG(st.st_mode):
        return False
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        # (root may write any file: read-only is what the mode says to everyone)
        return not st.st_mode & 0o222
    return not os.access(resolved[0], os.W_OK)


def atomic_write(backend, path: str, data: bytes, *, new_mode: int | None = None) -> None:
    """Write *data* to *path* atomically.

    Raises :class:`OSError` on I/O failure. On failure the target path
    is left untouched (either its previous content or non-existent).
    *new_mode*: the mode a NEW file gets (from its first byte on: the
    clear text of a decrypted file is 0600); an existing one keeps its own.
    """
    op_id = ""
    try:
        from axross_markdown._ax.core.operation_journal import start_operation

        op_id = start_operation(
            "atomic_write",
            dest=path,
            backend=getattr(backend, "name", type(backend).__name__),
            bytes_total=len(data),
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("atomic_write: journal start failed: %s", exc)
    direct = _is_native_atomic(backend) or _cannot_rename(backend)
    if not direct:
        try:
            resolved = _resolve_destination(backend, path)
        except BaseException as exc:
            _finish_journal(
                op_id,
                "atomic_write",
                status="error",
                dest=path,
                bytes_total=len(data),
                error=str(exc),
            )
            raise
        if resolved is None:
            # A link we cannot read: open_write follows it, renaming
            # over it would replace it.
            direct = True
        else:
            path, previous_mode = resolved
            try:
                _refuse_parent_steps(backend, path)
            except PermissionError as exc:
                _finish_journal(op_id, "atomic_write", status="error", dest=path, bytes_total=len(data),
                                error=str(exc))
                raise
            if previous_mode is None and new_mode is not None and not backend.exists(path):
                previous_mode = new_mode & 0o7777
            reason = _keep_identity_reason(backend, path)
            if reason is not None:
                _in_place_journaled(op_id, path, data, reason)
                return
    if direct:
        try:
            with backend.open_write(path) as f:
                f.write(data)
            log.debug("atomic_write: direct write for %s", path)
            _finish_journal(
                op_id,
                "atomic_write",
                status="done",
                dest=path,
                bytes_total=len(data),
                bytes_done=len(data),
            )
        except BaseException as exc:
            _finish_journal(
                op_id,
                "atomic_write",
                status="error",
                dest=path,
                bytes_total=len(data),
                error=str(exc),
            )
            raise
        return

    tmp = _temp_sibling(backend, path)
    # The commit below renames a FRESH file over the target, so the
    # target's mode does not survive on its own — the replacement
    # carries whatever the umask gave the temp file. For an executable
    # that is not cosmetic: saving ~/.xinitrc at 0755 handed it back as
    # 0644 and the next X session would not start. ``previous_mode``
    # comes from _resolve_destination, i.e. from the file, not a link.
    carried = True
    group = None
    if _is_local(backend) and previous_mode is not None:
        try:
            group = os.stat(path).st_gid  # the file's group, from the temp's first byte
        except (OSError, AttributeError):
            group = None
    try:
        f, written = _open_temp(backend, tmp, previous_mode, group)
        # A remote temp file gets the owner and group of the file it
        # replaces while it is still empty: given after the data, the
        # login's group could read a 0640 file for the time of the write.
        owned = _carry_remote_owner(backend, path, tmp)
        with f:
            if owned:
                f.write(data)
                _sync_written(backend, f)
        if owned and _mode_left_to_set(f, written, previous_mode):
            _restore_mode(backend, tmp, previous_mode)
        _refuse_swapped_temp(tmp, written)
        carried = owned and _carry_local_attributes(backend, path, tmp)
        if carried:
            _finalize_temp_destination = _temp_commit()
            _finalize_temp_destination(backend, tmp, path)
            _sync_folder(backend, path)
            log.debug("atomic_write: rename-based commit for %s", path)
            _finish_journal(
                op_id,
                "atomic_write",
                status="done",
                dest=path,
                bytes_total=len(data),
                bytes_done=len(data),
                details={"temp": tmp},
            )
    except BaseException:
        # Best-effort cleanup — if the write didn't complete, remove the
        # temp so we don't leak. Swallow errors from the cleanup
        # itself; the original exception is re-raised below.
        _drop_temp(backend, tmp)
        _finish_journal(
            op_id,
            "atomic_write",
            status="error",
            dest=path,
            bytes_total=len(data),
            error="write failed",
            details={"temp": tmp},
        )
        raise
    if not carried:
        # The rename would drop the file's group or an extended attribute.
        _drop_temp(backend, tmp)
        if not _is_local(backend):
            _write_through(backend, op_id, path, data, "its owner would not survive a rename")
            return
        _in_place_journaled(op_id, path, data, "an attribute would not survive a rename")


def atomic_write_stream(
    backend,
    path: str,
    reader,
    *,
    chunk_size: int = 1024 * 1024,
    on_chunk=None,
    new_mode: int | None = None,
    before_commit=None,
) -> int:
    """Atomically stream bytes from ``reader`` into ``path``.

    ``reader`` must expose ``read(size)``. Returns bytes written. The
    optional ``on_chunk(bytes_done)`` callback is invoked after each
    successful chunk write. *new_mode* as in :func:`atomic_write`: the
    mode a NEW file gets from its first byte on. *before_commit(temp)*, on
    the temp-file route only, runs once the temp file is complete and
    before it takes the file's place: it may check the temp file and
    prepare the place; an exception from it removes the temp file and
    leaves the file as it was.
    """
    bytes_done = 0
    direct = _is_native_atomic(backend) or _cannot_rename(backend)
    previous_mode = None
    if not direct:
        resolved = _resolve_destination(backend, path)
        if resolved is None:
            direct = True  # a link we cannot read: write through it
        else:
            path, previous_mode = resolved
            _refuse_parent_steps(backend, path)
            if previous_mode is None and new_mode is not None and not backend.exists(path):
                previous_mode = new_mode & 0o7777
    if direct:
        with backend.open_write(path) as f:
            while True:
                chunk = reader.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                bytes_done += len(chunk)
                if on_chunk:
                    on_chunk(bytes_done)
        return bytes_done

    tmp = _temp_sibling(backend, path)
    group = None
    if _is_local(backend) and previous_mode is not None:
        try:
            group = os.stat(path).st_gid  # the file's group, from the temp's first byte
        except (OSError, AttributeError):
            group = None
    try:
        f, written = _open_temp(backend, tmp, previous_mode, group)
        # The owner and group of the file it replaces, while it is still
        # empty (best effort here: a stream cannot be written in place).
        if not _carry_remote_owner(backend, path, tmp):
            log.info("atomic_write_stream: %s gets a new owner (it could not be kept)", path)
        with f:
            while True:
                chunk = reader.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                bytes_done += len(chunk)
                if on_chunk:
                    on_chunk(bytes_done)
        if _mode_left_to_set(f, written, previous_mode):
            _restore_mode(backend, tmp, previous_mode)
        _refuse_swapped_temp(tmp, written)
        if not _carry_local_attributes(backend, path, tmp):  # best effort: xattrs
            log.info("atomic_write_stream: %s loses a group or extended attribute", path)
        if before_commit is not None:
            before_commit(tmp)
        _finalize_temp_destination = _temp_commit()
        _finalize_temp_destination(backend, tmp, path)
        return bytes_done
    except BaseException:
        _drop_temp(backend, tmp, "atomic_write_stream")
        raise


def _temp_commit():
    """core.server_ops' commit of a temp file to its place (a backup of the
    file there first) - or, in a program exported without axross's transfers
    (axross-markdown's editor: local files only), the backend's rename,
    which replaces the file there. Its import unguarded, the editor's Save
    always failed there."""
    try:
        from axross_markdown._ax.core.server_ops import _finalize_temp_destination
    except ImportError:
        def _finalize_temp_destination(backend, temp_path: str, dst: str) -> None:
            backend.rename(temp_path, dst)
    return _finalize_temp_destination
