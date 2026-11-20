"""Every test run gets a home of its own; the package is this checkout's src/
when it is not installed."""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
    os.environ["PYTHONPATH"] = os.pathsep.join(p for p in (str(SRC), os.environ.get("PYTHONPATH", "")) if p)
_home = tempfile.mkdtemp(prefix="axross-test-home-")
atexit.register(shutil.rmtree, _home, ignore_errors=True)
os.environ["HOME"] = _home
for _name, _sub in (("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", ".local/share"),
                    ("XDG_CACHE_HOME", ".cache"), ("XDG_STATE_HOME", ".local/state")):
    os.environ[_name] = os.path.join(_home, _sub)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_collection_modifyitems(config, items):
    """axross's tests of its own export of the tool (test_packaging_*) need axross."""
    import pytest

    for item in items:
        if item.name.startswith("test_packaging_"):
            item.add_marker(pytest.mark.skip(reason="tests axross's export of the tool: run in axross"))
