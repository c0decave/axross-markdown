"""axross-markdown's own settings file, without Qt: ~/.config/axross-markdown/settings.json
(``$XDG_CONFIG_HOME`` when set; ``$AXROSS_MARKDOWN_SETTINGS`` names another file - a test's, a portable
setup's) - the window's and the terminal's theme (core.markdown_themes) and the updates' mode
(core.markdown_update). ui.standalone_app keeps the window theme of axross's in the same file.

The file is written only when the user chooses something (a menu, ``--update-mode``): what the program
notes by itself - when it last asked for updates, the newer version it found - is its state, in
:func:`state_path` (``$XDG_STATE_HOME``), never here.

The file is hand-editable: every value is checked where it is read; a file that is no JSON object reads
as empty. Writes keep every other key, are private (0600) and atomic (a temporary file, fsync, rename),
one at a time in this process.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

NAME = "axross-markdown"
#: Names the settings file instead of ~/.config/axross-markdown/settings.json (the state goes beside it).
ENV = "AXROSS_MARKDOWN_SETTINGS"
#: The most of the file that is read (a hand-edited file is no reason to read gigabytes).
MAX_BYTES = 1 << 20
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


def read_settings(path: Path | None = None) -> dict:
    """The settings as a dict - {} when there are none or they are no JSON object."""
    path = settings_path() if path is None else Path(path)
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return {}
        value = json.loads(data.decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):  # (nested past the limit: none)
        return {}
    return value if isinstance(value, dict) else {}


def read_setting(key: str, default=None, path: Path | None = None):
    return read_settings(path).get(key, default)


def write_setting(key: str, value, path: Path | None = None) -> None:
    """*key* = *value* (None: the key removed), the rest kept."""
    write_settings({key: value}, path)


def write_settings(values: dict, path: Path | None = None) -> None:
    """Every key of *values* set (a None removes it), the rest kept - written privately and atomically."""
    path = settings_path() if path is None else Path(path)
    with _LOCK:
        data = read_settings(path)
        for key, value in values.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise


__all__ = ["ENV", "NAME", "read_setting", "read_settings", "settings_path", "state_path", "write_setting",
           "write_settings"]
