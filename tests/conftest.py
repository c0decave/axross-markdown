"""Every test run gets a home of its own; the package is this checkout's src/
when it is not installed."""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

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
os.environ.setdefault("AXROSS_MARKDOWN_NO_UPDATE_CHECK", "1")  # (no test asks GitHub: the updater's use a fake)


def pytest_collection_modifyitems(config, items):
    """axross's tests of its own export of the tool (test_packaging_*) need axross."""
    import pytest

    for item in items:
        if item.name.startswith("test_packaging_"):
            item.add_marker(pytest.mark.skip(reason="tests axross's export of the tool: run in axross"))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """A stress test whose heartbeat froze (tests/markdown_heartbeat.py's Frozen) is run once more before it
    fails: a second job beside it can take its few tenths of a second now and then - a freeze of the
    window's own fails both times."""
    try:
        return (yield)
    except AssertionError as error:
        heartbeat = sys.modules.get("tests.markdown_heartbeat")
        if heartbeat is None or not isinstance(error, heartbeat.Frozen):
            raise
        return heartbeat.measure_again(item.runtest, error)
