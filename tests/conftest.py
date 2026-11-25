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
if os.environ.get("AXROSS_MARKDOWN_TEST_INSTALLED"):  # (the release's tests: of the wheel built, installed - not
    import importlib.util  # this checkout's src/)

    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != SRC]
    for _package in (init.parent.name for init in SRC.glob("*/__init__.py")):
        _found = importlib.util.find_spec(_package)
        if _found is None or SRC in Path(_found.origin).resolve().parents:
            raise SystemExit(f"tests/conftest.py: {_package} is not installed - pip install the wheel first")
elif SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
    os.environ["PYTHONPATH"] = os.pathsep.join(p for p in (str(SRC), os.environ.get("PYTHONPATH", "")) if p)
_home = tempfile.mkdtemp(prefix="axross-test-home-")
atexit.register(shutil.rmtree, _home, ignore_errors=True)
os.environ["HOME"] = _home
for _name, _sub in (("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", ".local/share"),
                    ("XDG_CACHE_HOME", ".cache"), ("XDG_STATE_HOME", ".local/state")):
    os.environ[_name] = os.path.join(_home, _sub)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# (the tests read what the programs say in English: axross-mdcat follows the locale - a German one is no test's)
os.environ.update({"LC_ALL": "C.UTF-8", "LC_MESSAGES": "C.UTF-8", "LANG": "C.UTF-8"})
os.environ.setdefault("AXROSS_MARKDOWN_NO_UPDATE_CHECK", "1")  # (no test asks GitHub: the updater's use a fake)
os.environ.pop("AXROSS_MARKDOWN_SETTINGS", None)  # (a settings file of the user's is no test's)


@pytest.fixture(autouse=True)
def _own_configuration(tmp_path_factory, monkeypatch):
    """Every test its own home, settings and state - a choice one test makes and keeps (a theme, an update
    mode) is no later test's starting point: HOME, XDG_CONFIG_HOME and XDG_STATE_HOME a fresh folder each
    (the caches - fonts - and data stay the run's), and the page's theme back to "auto" after it."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    yield
    _reset_theme()


def _reset_theme():
    """The process's ThemeHub (ui.markdown_theme_ui) as a new one is: "auto", nothing pending."""
    import time

    for name, module in list(sys.modules.items()):
        if name.endswith("ui.markdown_theme_ui") and getattr(module, "_HUB", None):
            hub = module._HUB[0]
            try:
                hub._timer.stop()
            except RuntimeError:  # (deleted with its application)
                module._HUB.clear()
                continue
            hub._pending, hub._theme, hub._applied, hub.clock = None, "auto", float("-inf"), time.monotonic


@pytest.fixture(autouse=True)
def _collector_settled():
    """Before each test: the windows the tests before it closed are deleted
    (tests/markdown_heartbeat.py's settle_collector) - a test's turns and gaps are the window's own, not
    the leavings of the 2,000 tests one process runs."""
    from tests.markdown_heartbeat import settle_collector

    settle_collector()
    yield


def pytest_configure(config):
    """The markers ``timing`` and ``budgets`` (tests/markdown_timing.py); under ``-m "not timing"`` (the
    blocking job) a duration over its budget is a warning, its test's content still asserted."""
    from tests.markdown_timing import configure

    configure(config)


def pytest_collection_modifyitems(config, items):
    """axross's tests of its own export of the tool (test_packaging_*) need axross; the tests that pass or
    fail by elapsed time only get the marker ``timing``, those that assert their content and a duration
    ``budgets`` (tests/markdown_timing.py): the CI runs ``-m "not timing"`` as the blocking job (a budget
    missed a warning there) and ``-m "timing or budgets"`` strictly in a job that does not block. Locally:
    all, strictly."""
    import pytest

    for item in items:
        if item.name.startswith("test_packaging_"):
            item.add_marker(pytest.mark.skip(reason="tests axross's export of the tool: run in axross"))
    from tests.markdown_timing import mark

    mark(items)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """A stress test whose heartbeat froze (tests/markdown_heartbeat.py's Frozen) is run once more before it
    fails: a second job beside it can take its few tenths of a second now and then - a freeze of the
    window's own fails both times. And no heartbeat a test stopped saw a turn of the GUI thread over the
    gate (gate_turns: CPU time, whatever the machine's load - it fails in every job)."""
    heartbeat = sys.modules.get("tests.markdown_heartbeat")
    mark = len(heartbeat.STOPPED) if heartbeat is not None else 0
    result = None
    try:
        result = yield
    except AssertionError as error:
        heartbeat = sys.modules.get("tests.markdown_heartbeat")
        if heartbeat is None:
            raise
        mark = heartbeat.after_failure(item, error) or mark
    heartbeat = sys.modules.get("tests.markdown_heartbeat")
    if heartbeat is not None:
        heartbeat.gate_turns(item, mark)
    return result
