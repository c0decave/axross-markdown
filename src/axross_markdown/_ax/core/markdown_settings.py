"""axross-markdown's own settings file, without Qt: ~/.config/axross-markdown/settings.json
(``$XDG_CONFIG_HOME`` when set; ``$AXROSS_MARKDOWN_SETTINGS`` names another file - a test's, a portable
setup's) - the window's and the terminal's theme (core.markdown_themes) and the updates' mode
(core.markdown_update). ui.standalone_app keeps the window theme of axross's in the same file.

The file is written only when the user chooses something (a menu, ``--update-mode``): what the program
notes by itself - when it last asked for updates, the newer version it found - is its state, in
:func:`state_path` (``$XDG_STATE_HOME``), never here.

The file is hand-editable: every value is checked where it is read. A file that is no JSON object (a
typo: a trailing comma, a comment) is read for what can still be read (salvaged: each top-level key whose
value parses), never taken for empty - and the next write keeps that file aside first
(``settings.json.broken``, never one kept before) and writes what was salvaged with the new choice, so a typo
loses no setting.

The updates' mode is read more strictly than the rest (:func:`update_mode`), because a wrong guess there
downloads and installs programs: "off" wins whenever the file leaves a doubt. A file that is there but is
no clean JSON object gives its mode only when every ``update_mode`` written anywhere in it - in a comment,
in a nested object, twice - says the same valid one; a file that cannot be read at all (no permission, no
regular file, larger than :data:`MAX_BYTES`) and a value of no meaning give "off": the updater then does
nothing by itself - no request, no download, no install - until the file is repaired (said once in the
log). "off" is the fallback because it is the one mode that cannot do what the user did not ask for: a
check missed is made up for with Help > Check for Updates…, an install is not undone. Such a file is never
written over either: writing another setting to it fails (an OSError) instead of replacing what may hold
the user's "off".

Reads are bounded: a regular file only (a FIFO or a device at the path is not opened for reading: it would
block the start for good), at most :data:`MAX_BYTES`, salvaged in one pass and only up to
:data:`SALVAGE_BYTES`, and a file that did not change is not read again (the window's start read it for
each of its settings, on the GUI thread).

Writes keep every other key, are private (0600) and atomic (a temporary file of a random name made anew -
never one that is there, never through a link -, fsync, rename), one at a time across threads and
processes (a file lock beside it, a link planted there not followed), and go through a symlink to its
target (a dotfiles manager's link stays a link) - when that target is a regular file or none yet: nothing
is made beside a device.
"""

from __future__ import annotations

import contextlib
import errno
import json
import logging
import os
import re
import secrets
import stat
import threading
import time
from pathlib import Path

try:
    import fcntl as _fcntl
except ImportError:  # (Windows)
    _fcntl = None

log = logging.getLogger(__name__)

NAME = "axross-markdown"
#: Names the settings file instead of ~/.config/axross-markdown/settings.json (the state goes beside it).
ENV = "AXROSS_MARKDOWN_SETTINGS"
#: The most of the file that is read (a hand-edited file is no reason to read gigabytes).
MAX_BYTES = 1 << 20
#: The most of a file that is no JSON object that is still read for what it holds (a settings file is a few
#: hundred bytes): a larger one gives no setting, and the updates' mode "off".
SALVAGE_BYTES = 32 << 10
#: The updates' mode: its key, its values (core.markdown_update's SETTING_MODE, MODES) and the default.
MODE_KEY = "update_mode"
MODES = ("off", "notify", "auto")
DEFAULT_MODE = "notify"
_LOCK = threading.Lock()


def settings_path(name: str = NAME) -> Path:
    override = os.environ.get(ENV, "").strip()
    if override and name == NAME:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / name / "settings.json"


def state_path(name: str = NAME) -> Path:
    """What the program notes by itself (the update checks): ~/.local/state/axross-markdown/state.json
    (``$XDG_STATE_HOME``) - beside ``$AXROSS_MARKDOWN_SETTINGS``'s file when that is set."""
    override = os.environ.get(ENV, "").strip()
    if override and name == NAME:
        settings = Path(override).expanduser()
        return settings.with_name(settings.stem + ".state.json")
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / name / "state.json"


def window_state_path(name: str = NAME) -> Path:
    """Where the window's size and place are kept: ~/.local/state/axross-markdown/window.json - the program's
    own (it wrote them into axross's ~/.config/axross/session.json)."""
    state = state_path(name)
    return state.with_name(state.stem + ".window.json") if state.name != "state.json" \
        else state.with_name("window.json")


_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)

#: (_scanned) the pieces of a text that should be a JSON object, in one pass: a string in double or single
#: quotes (ended by its quote - or by the line's end: never closed), a // or /* */ comment, a bracket, comma
#: or colon, anything else up to the next of those. No alternative can fail after it began, so no place is
#: read twice (a megabyte of escaped quotes took the pattern before 2.2 s: each quote was tried to the end).
_TOKEN = re.compile(r'''"(?P<dq>(?:[^"\\\n]|\\[^\n])*)(?P<dqe>")?'''
                    r"""|'(?P<sq>(?:[^'\\\n]|\\[^\n])*)(?P<sqe>')?"""
                    r"""|(?P<comment>//[^\n]*|/\*.*?(?:\*/|\Z))"""
                    r"""|(?P<mark>[{}\[\],:])"""
                    r"""|(?P<word>[^"'/{}\[\],:\s]+|/)""", re.DOTALL)
#: (_mentions) an update mode written anywhere in a text - quoted or not, "=" for ":", in a comment, nested -
#: with what follows it as its value.
_MENTION = re.compile(r"""update[\s_-]?mode["']?[ \t]*(?:[:=][ \t]*(?:"([^"\n]{0,40})"?|'([^'\n]{0,40})'?"""
                      r"""|([^\s,;}\]"']{0,40})))?""", re.IGNORECASE)
#: (_mode_of) what a value that is no mode may hold and still not mean "off": it reads as the default.
_ON_WORDS = frozenset({"auto", "automatic", "notify", "tell", "on", "true", "yes", "1", "install", "enabled"})


class _Object(dict):
    """A JSON object as json.loads made it - *conflict*: it holds the update mode twice, not the same."""

    conflict = False


def _pairs(pairs) -> _Object:
    """(json's object_pairs_hook) the object of *pairs* - the last of a key twice, as json reads it - the
    update mode written twice with two meanings noted."""
    made = _Object()
    for key, value in pairs:
        if key == MODE_KEY and key in made and _mode_of(made[key]) != _mode_of(value):
            made.conflict = True
        made[key] = value
    return made


def _valid_mode(value) -> str | None:
    """*value* as a mode, however cased and with spaces round it ("Off", " off ") - None: it is none."""
    if isinstance(value, str) and value.strip().lower() in MODES:
        return value.strip().lower()
    return None


def _mode_of(value) -> str:
    """The update mode *value* stands for: itself when it is one (_valid_mode); the default for a value of no
    meaning that can only mean "on" (``true``, ``["auto"]`` - never "auto": nothing is installed without the
    word); "off" for everything else (``false``, ``0``, ``null``, "never", a typo: it could have been "off")."""
    valid = _valid_mode(value)
    if valid is not None:
        return valid
    try:
        words = re.findall(r"[a-z0-9]+", json.dumps(value).lower())
    except (TypeError, ValueError, RecursionError):
        return "off"
    return DEFAULT_MODE if words and all(word in _ON_WORDS for word in words) else "off"


def _mentions(text: str) -> list[str | None]:
    """The value of every update mode written in *text* (lower case, no spaces round it; None: none follows)."""
    found = []
    for match in _MENTION.finditer(text):
        value = next((group for group in match.groups() if group is not None), None)
        found.append(None if value is None else value.strip().lower())
    return found


def _scanned(text: str) -> list[tuple[str, object]]:
    """The pieces of *text* without its comments: ("s", the string), ("u", an unclosed or unreadable string's
    text), ("m", a bracket, comma or colon), ("w", anything else)."""
    pieces: list[tuple[str, object]] = []
    for match in _TOKEN.finditer(text):
        kind = match.lastgroup
        if kind == "comment":
            continue
        if kind == "mark":
            pieces.append(("m", match.group()))
        elif kind == "word":
            pieces.append(("w", match.group()))
        else:
            double = match.group("dq") is not None
            body = match.group("dq") if double else match.group("sq")
            if match.group("dqe" if double else "sqe") is None:
                pieces.append(("u", body))
                continue
            if not double:  # (a string in single quotes has no JSON form: its quotes turned)
                body = re.sub(r'(?<!\\)"', r'\\"', body.replace("\\'", "'"))
            try:
                pieces.append(("s", json.loads(f'"{body}"', strict=False)))
            except (ValueError, RecursionError):
                pieces.append(("u", body))
    return pieces


def _no_constant(name: str):
    raise ValueError(name)


def _repaired(pieces) -> _Object | None:
    """The JSON object *pieces* make once the comments are gone, single quotes are double ones and no comma
    stands before a closing bracket or another comma - None: they make none."""
    parts: list[str] = []
    for index, (kind, value) in enumerate(pieces):
        if kind == "u":
            return None
        if kind == "s":
            parts.append(json.dumps(value))
        elif value == "," and (index + 1 == len(pieces) or pieces[index + 1] in (("m", ","), ("m", "}"), ("m", "]"))):
            continue
        else:
            parts.append(value)
    try:
        made = json.loads(" ".join(parts), object_pairs_hook=_pairs)
    except (ValueError, RecursionError):
        return None
    return made if isinstance(made, _Object) else None


def _top_pairs(pieces) -> tuple[dict, list]:
    """(what cannot be repaired) each "key": value of the outermost object whose value is a string, a number,
    true, false or null - the first of a key twice - and every value the update mode has there. A pair inside
    a nested object is that object's, never the file's."""
    found: dict = {}
    modes: list = []
    depth, index, count = 0, 0, len(pieces)
    while index < count:
        kind, value = pieces[index]
        if kind == "m":
            depth = depth + 1 if value in "{[" else max(0, depth - 1) if value in "}]" else depth
        elif kind == "s" and depth <= 1 and index + 2 < count and pieces[index + 1] == ("m", ":"):
            what, held = pieces[index + 2]
            taken = what == "s"
            if what == "w":
                try:
                    held = json.loads(held, parse_constant=_no_constant)
                    taken = True
                except (ValueError, RecursionError):
                    pass
            if taken:
                found.setdefault(value, held)
                if value == MODE_KEY:
                    modes.append(held)
                index += 3
                continue
        index += 1
    return found, modes


def _salvaged(text: str) -> dict:
    """What can still be read of a settings file that is no JSON object: the object without its comments and
    stray commas, else each top-level "key": value pair whose value is a plain JSON value.

    Its update mode is the file's own only when nothing in *text* says otherwise: the top-level one is a
    valid mode and every update mode written anywhere in the text - a line commented out, a nested object, a
    second one - is the same. No update mode anywhere in an object that could be repaired: none here (the
    default). Everything else is a doubt, and gives "off" (the module's text says why)."""
    pieces = _scanned(text)
    made = _repaired(pieces)
    if made is not None:
        found = dict(made)
        modes = [found[MODE_KEY]] if MODE_KEY in found else []
        conflict = made.conflict
    else:
        found, modes = _top_pairs(pieces)
        conflict = False
    written = _mentions(text)
    own = _valid_mode(modes[0]) if modes else None
    if own is not None and not conflict and all(_valid_mode(mode) == own for mode in modes) \
            and all(mode == own for mode in written):
        found[MODE_KEY] = own
    elif made is not None and not modes and not written:
        found.pop(MODE_KEY, None)
    else:
        found[MODE_KEY] = "off"
    return found


def _decoded(data: bytes, errors: str = "strict") -> str:
    """*data* as text: UTF-8 (a byte order mark, an editor's on Windows, is none of it) or, with its mark,
    UTF-16."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors)
    return data.decode("utf-8-sig", errors)


#: (_load) what the files read last held, by their path: (the file's identity, size and times; what _load
#: gave). Only a file not written in the last seconds is kept (its times tell a later change for sure).
_READ: dict[str, tuple[tuple, tuple]] = {}
_READ_FILES = 8
_SETTLED_SECONDS = 2.0
#: (_load) the files a warning was logged for (once each).
_SAID: set[tuple[str, str]] = set()


def _load(path: Path) -> tuple[dict, bytes | None, str]:
    """(the settings of *path*; the file's bytes when it is there but no JSON object - else None; how it was
    read: "none" - there is no file -, "ok", "broken" - no JSON object: salvaged -, "unreadable" - no
    permission, no regular file - or "large" - more than MAX_BYTES). The last two hold nothing but the
    update mode "off"."""
    key = os.fspath(path)
    try:
        # (not waited for: a FIFO opened for reading waits for its writer - the program's start, for good)
        fd = os.open(key, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0) | _CLOEXEC)
    except (FileNotFoundError, NotADirectoryError):
        return {}, None, "none"
    except OSError:
        return _doubtful(key, "unreadable")
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return _doubtful(key, "unreadable")
        if st.st_size > MAX_BYTES:
            return _doubtful(key, "large")
        sign = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
        kept = _READ.get(key)
        if kept is not None and kept[0] == sign:
            return dict(kept[1][0]), kept[1][1], kept[1][2]
        try:
            with os.fdopen(os.dup(fd), "rb") as handle:
                data = handle.read(MAX_BYTES + 1)
        except OSError:
            return _doubtful(key, "unreadable")
    finally:
        os.close(fd)
    if len(data) > MAX_BYTES:  # (it grew meanwhile)
        return _doubtful(key, "large")
    loaded = _parsed(key, data)
    if time.time() - max(st.st_mtime, st.st_ctime) > _SETTLED_SECONDS:
        if len(_READ) >= _READ_FILES:
            _READ.clear()
        _READ[key] = (sign, loaded)
    return dict(loaded[0]), loaded[1], loaded[2]


def _doubtful(key: str, how: str) -> tuple[dict, bytes | None, str]:
    """A file that is there and cannot be read (*how*: "unreadable", "large"): no setting of it known - its
    update mode may be "off", so it is."""
    if (key, how) not in _SAID:
        _SAID.add((key, how))
        log.warning("%s %s: its settings are not used, and no update is looked for until it can be read again",
                    key, f"is larger than {MAX_BYTES} bytes" if how == "large" else "cannot be read")
    return {MODE_KEY: "off"}, None, how


def _parsed(key: str, data: bytes) -> tuple[dict, bytes | None, str]:
    """(_load) the settings of a file's bytes."""
    if not data.strip() or data.strip() in (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff"):
        return {}, None, "ok"  # (an empty file: no setting yet)
    try:
        value = json.loads(_decoded(data), object_pairs_hook=_pairs)
        clean = True
    except (ValueError, UnicodeDecodeError, RecursionError):  # (nested past the limit: salvaged too)
        value, clean = None, False
    if isinstance(value, _Object):
        found = dict(value)
        if value.conflict:
            found[MODE_KEY] = "off"  # (written twice, two meanings: json reads the last one)
        return found, None, "ok"
    if clean or len(data) > SALVAGE_BYTES:  # (JSON, but no object - or too much to look through)
        found = {MODE_KEY: "off"}
    else:
        found = _salvaged(_decoded(data, "replace"))
    if found.get(MODE_KEY) == "off" and (key, "broken") not in _SAID:
        _SAID.add((key, "broken"))
        log.warning("%s is no JSON object, and the update mode in it is not plain: taken for \"off\" - no "
                    "update is looked for until the file is repaired", key)
    return found, data, "broken"


def read_settings(path: Path | None = None) -> dict:
    """The settings as a dict - {} when there are none; what can still be read of a file that is no JSON object
    (_salvaged). (Its values are not to be changed in place: a file that did not change is not read again.)"""
    return _load(settings_path() if path is None else Path(path))[0]


def read_setting(key: str, default=None, path: Path | None = None):
    return read_settings(path).get(key, default)


def update_mode(path: Path | None = None, default: str = DEFAULT_MODE) -> str:
    """The updates' mode the settings give - "off", "notify" or "auto": *default* when no file is there or it
    names none; the file's own, however cased; "off" whenever the file leaves a doubt (_salvaged, _mode_of,
    and a file that cannot be read): never "auto" or "notify" where "off" may have been set."""
    data, _broken, _how = _load(settings_path() if path is None else Path(path))
    if MODE_KEY not in data:
        return default
    return _mode_of(data[MODE_KEY])


#: The setting of the program's own language (View > Language): a language's code, absent for "Automatic".
SETTING_LANGUAGE = "language"


def chosen_language(environ=None, path: Path | None = None) -> str | None:
    """The language axross-markdown itself was told to speak, or None (then axross's own choice, else the
    locale's): the setting "language" of its settings.json (View > Language), else the first language
    of $LANGUAGE that it has (GNU's list, "de:en": it was not looked at)."""
    from axross_markdown._ax.core import i18n

    offered = i18n.available_languages()
    try:
        chosen = i18n.normalise_language(read_setting(SETTING_LANGUAGE))
    except Exception:  # noqa: BLE001 - settings that cannot be read: nothing chosen
        chosen = None
    if chosen in offered:
        return chosen
    environ = os.environ if environ is None else environ
    for name in str(environ.get("LANGUAGE", "")).split(":"):
        language = i18n.normalise_language(name)
        if language in offered:
            return language
    return None


def write_setting(key: str, value, path: Path | None = None) -> None:
    """*key* = *value* (None: the key removed), the rest kept."""
    write_settings({key: value}, path)


@contextlib.contextmanager
def _file_lock(target: Path):
    """One write of *target* at a time across processes: an exclusive lock on ``<target>.lock`` (0600) - a
    regular file made or opened there, never what a link planted at that name leads to. No lock to be had (a
    link there, a folder that cannot be written): the write goes on under the process's own lock."""
    fd = -1
    if _fcntl is not None:
        try:
            fd = os.open(os.fspath(target) + ".lock", os.O_RDWR | os.O_CREAT | _NOFOLLOW | _CLOEXEC, 0o600)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError(errno.EINVAL, "not a regular file")
            _fcntl.flock(fd, _fcntl.LOCK_EX)
        except OSError as exc:
            log.warning("No file lock for %s: %s", target, exc.strerror or exc)
            if fd != -1:
                os.close(fd)
                fd = -1
    try:
        yield
    finally:
        if fd != -1:
            os.close(fd)


def write_settings(values: dict, path: Path | None = None) -> None:
    """Every key of *values* set (a None removes it), the rest kept - written privately and atomically, to a
    symlink's target. A file that is no JSON object is kept aside first (_kept_aside) and what can still be read
    of it kept (_salvaged). OSError: the file is no regular file (a link to a device: nothing is made beside
    it), or it is there and cannot be read or is too large - it is left as it is, it may hold the user's
    "off"."""
    path = settings_path() if path is None else Path(path)
    target = Path(os.path.realpath(path))  # (a symlink - a dotfiles manager's - written through, kept a link)
    try:
        regular = stat.S_ISREG(os.lstat(target).st_mode)
    except OSError:
        regular = True  # (none yet)
    if not regular:
        raise OSError(errno.EINVAL, "the settings are no regular file - not written", os.fspath(target))
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _LOCK, _file_lock(target):
        data, broken, how = _load(target)
        if how in ("unreadable", "large"):
            raise OSError(errno.EFBIG if how == "large" else errno.EACCES,
                          "the settings cannot be read - left as they are, not written", os.fspath(target))
        if broken is not None:
            _kept_aside(target, broken)
        for key, value in values.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        # (a name no one can know before, made anew: never a file - or a link - that is there already)
        temp = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise
        _READ.pop(os.fspath(target), None)


def _kept_aside(path: Path, data: bytes) -> Path:
    """A copy of the file *path* that is no JSON object (*data*: its bytes), beside it - settings.json.broken,
    else .broken-2, -3 …: never one kept before overwritten. Said in the log."""
    for number in range(1, 1000):
        aside = path.with_name(path.name + (".broken" if number == 1 else f".broken-{number}"))
        try:
            fd = os.open(aside, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600)
        except FileExistsError:
            try:
                if aside.read_bytes() == data:
                    break  # (this one kept already)
            except OSError:
                pass
            continue
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        break
    log.warning("%s could not be read as JSON (a typo?): it is kept as %s, and what could still be read of "
                "it is written back with the new choice", path, aside)
    return aside


__all__ = ["DEFAULT_MODE", "ENV", "MAX_BYTES", "MODES", "MODE_KEY", "NAME", "SALVAGE_BYTES", "read_setting",
           "read_settings", "settings_path", "state_path", "update_mode", "window_state_path", "write_setting",
           "write_settings"]
