"""Every Markdown test that passes or fails by elapsed time carries the marker ``timing``
(tests/markdown_timing.py): the standalone's CI runs those in a job of their own that does not block a
release - a shared runner about twice as slow failed 133 of them in 0.17.0's CI without a bug - and the
rest, which do block, with ``-m "not timing"``.

The scan here finds what asserts a duration: a call of the heartbeat or a turn meter (tests/
markdown_heartbeat.py, the _Turns / Turns / within_turn / turn_for helpers, _quick), of time.process_time,
thread_time or perf_counter, of a module's own helper that calls one, a wait asserted with a timeout of
at most 30 s (``assert until(..., 5)``) and a deadline of at most 30 s in a test (``time.monotonic() + 5``).
A helper that only waits for a page to be ready waits long enough (READY_SECONDS): it is no budget.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests import markdown_timing as MT  # noqa: E402

#: What measures elapsed time, by name (a call of it, or of an attribute of that name).
SEEDS = {"Heartbeat", "assert_responsive", "gap_budget", "within_turn", "turn_for", "_Turns", "Turns",
         "_longest_turn", "_quick", "measure_again", "gaps_since", "thread_time", "process_time",
         "perf_counter"}
#: The waits whose timeout, asserted, is a budget.
WAITS = ("until", "wait_until", "_until")
#: The longest timeout or deadline that still counts as a budget (a readiness wait is longer).
SHORT = 30


def _modules() -> dict[str, ast.Module]:
    files = sorted((ROOT / "tests").glob("test_markdown*.py")) + [ROOT / "tests" / "test_open_as_markdown.py"]
    return {p.stem: ast.parse(p.read_text(encoding="utf-8")) for p in files if p.is_file()}


def _names(node) -> set[str]:
    found = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            found.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            found.add(sub.attr)
    return found


def _short(value) -> bool:
    return isinstance(value, ast.Constant) and isinstance(value.value, (int, float)) and value.value <= SHORT


def _asserted_wait(node) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assert):
            for call in ast.walk(sub.test):
                if isinstance(call, ast.Call) and getattr(call.func, "id", getattr(call.func, "attr", "")) in WAITS:
                    if any(_short(arg) for arg in [*call.args[1:], *(k.value for k in call.keywords)]):
                        return True
    return False


def _deadline(node) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Add) and isinstance(sub.left, ast.Call) \
                and getattr(sub.left.func, "attr", "") == "monotonic" and _short(sub.right):
            return True
    return False


def scan() -> tuple[set[str], set[str], int]:
    """(the tests that measure elapsed time, the helpers that do, how many tests there are)."""
    modules = _modules()
    helpers = set(SEEDS)
    for tree in modules.values():  # (a helper that waits a few seconds and goes on: a budget too)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("test_") and _deadline(node):
                helpers.add(node.name)
    grew = True
    while grew:  # (helpers calling helpers, across the modules: they import each other's)
        grew = False
        for tree in modules.values():
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("test_") \
                        and node.name not in helpers and _names(node) & helpers:
                    helpers.add(node.name)
                    grew = True
    found, count = set(), 0
    for module, tree in modules.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                count += 1
                if _names(node) & helpers or _asserted_wait(node) or _deadline(node):
                    found.add(f"{module}::{node.name}")
    return found, helpers, count


def test_sad_no_test_that_asserts_a_duration_is_missing_the_marker():
    found, _helpers, count = scan()
    missing = sorted(found - MT.TIMING)
    assert not missing, "add to tests/markdown_timing.py TIMING:\n" + "\n".join(missing)
    assert count > 700 and len(found) > 100  # (the scan saw the tests: none lost to a rename)


def test_sad_every_listed_test_is_there():
    modules = _modules()
    tests = {f"{module}::{node.name}" for module, tree in modules.items() for node in ast.walk(tree)
             if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")}
    gone = sorted((MT.TIMING | set(MT.BY_HAND)) - tests)
    assert not gone, gone
    assert all(why.strip() for why in MT.BY_HAND.values())
    assert not set(MT.BY_HAND) & MT.TIMING  # (the scan finds it: no reason by hand needed)


def test_happy_the_readiness_helpers_wait_for_the_page_not_a_budget():
    """view_of, dialog_of, _dialog, jumped: a wait of 10 s that went on with a half-made page made
    typography tests fail on a slow runner - they wait up to READY_SECONDS and go on when ready."""
    _found, helpers, _count = scan()
    assert not {"view_of", "dialog_of", "_dialog", "jumped"} & helpers


def test_happy_the_conftest_marks_them_and_not_timing_leaves_them_out(tmp_path):
    pytest.importorskip("PyQt6.QtWidgets")
    target = "tests/test_markdown_reader_bugs25.py"

    def collected(expression: str) -> list[str]:
        out = subprocess.run([sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:cacheprovider",
                              "-m", expression, target], cwd=ROOT, capture_output=True, text=True, timeout=300,
                             env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
        return [line for line in out.stdout.splitlines() if "::" in line]

    timing, rest = collected("timing"), collected("not timing")
    assert timing and rest and not set(timing) & set(rest)
    listed = {name.split("::", 1)[1] for name in MT.TIMING if name.startswith("test_markdown_reader_bugs25::")}
    assert {line.split("::", 1)[1].split("[", 1)[0] for line in timing} == listed
