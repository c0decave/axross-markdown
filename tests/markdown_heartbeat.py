"""The Markdown window's responsiveness as its user sees it: a heartbeat on the GUI thread.

A QTimer ticks every few milliseconds on the GUI thread while something is done (a document opened and
laid out, an export, a zoom). Two things are measured between two ticks:

- the GUI thread's own CPU time (``turn``) - what the window itself spends in one event-loop turn;
- the wall-clock time (``gap``) - how long the window did not answer, whatever held it.

The second catches what the first cannot: a worker thread that holds Python's lock (the GIL) in one long
C call - a regular expression's search, which never lets it go - freezes the window although the GUI
thread spends no CPU time at all (review 23's N1: a line of 1,200 backticks in a big file, the window
frozen 12.6 s while the per-turn CPU meter read 0.08 s). Every stress test that measures turns measures
the gap too (tests/test_markdown_reader_bugs20.py's _Turns, bugs16/17/18's Turns, bugs22's within_turn):
over GAP the test fails.
"""

from __future__ import annotations

import os
import time

#: The longest wall-clock gap between two heartbeats a stress test allows, in seconds, on the machine the
#: budgets were measured on (as much longer on a slower one: gap_budget). Above the 0.1 s a turn may take:
#: what else the machine does (a second pytest beside it) can delay a tick now and then - a test whose gap
#: is over it is measured again (Frozen: the conftest runs it once more, the machine timed anew), a lock
#: held by a worker, a wait for a child process fail both. (It was 0.5 s: review 24's 0.30 s heading line
#: and 0.15 s paragraphs passed.)
GAP = 0.15
#: Every heartbeat stopped since the last look: (gap, turn) - for the assertions after the measure.
STOPPED: list[tuple[float, float]] = []


#: What Qt took to lay out the calibration page on the machine the budgets were measured on (as
#: tests/test_markdown_reader_bugs22.py's CALIBRATION_SECONDS).
CALIBRATION_SECONDS = 0.014
_FACTOR: list[float] = []


def machine_factor() -> float:
    """How much slower than the calibration machine this one lays out a page - 1 to 3 (measured once: the
    least of five layouts of the same page, as bugs22's machine_factor)."""
    if not _FACTOR:
        from PyQt6.QtGui import QTextDocument

        text = "\n\n".join(f"Paragraph {n} with *some* `code`, **strong** words and [a link](x)." for n in range(600))
        took = []
        for _ in range(5):
            document = QTextDocument()
            began = time.thread_time()
            document.setMarkdown(text)
            document.setTextWidth(800)
            document.documentLayout().documentSize()
            took.append(time.thread_time() - began)
        _FACTOR.append(min(3.0, max(1.0, min(took) / CALIBRATION_SECONDS)))
    return _FACTOR[0]


def gap_budget() -> float:
    """GAP on this machine: as much longer as it lays out a page more slowly (machine_factor)."""
    return GAP * machine_factor()


class Frozen(AssertionError):
    """A heartbeat's gap over its budget (assert_responsive): the window did not answer. The conftest runs
    a test that raises it once more (measure_again) before it fails - what else the machine did then (a
    second pytest beside it, a collection of its garbage) is not the window's."""


#: How often a test whose window froze is run again before it fails (measure_again).
AGAIN = 1


def measure_again(run, first: Frozen):
    """*run()* (the test) once more after *first* - what earlier tests left gone first, the machine timed
    anew (machine_factor): its result when the window answered in time; else what it froze for, both
    times."""
    import gc

    from PyQt6.QtCore import QCoreApplication, QEvent

    failed = [first]
    for _ in range(AGAIN):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        gc.collect()
        _FACTOR.clear()
        try:
            return run()
        except Frozen as again:
            failed.append(again)
    raise Frozen(" - measured again: ".join(str(error) for error in failed))


class _Waited:
    """The calling thread's time spent waiting for a CPU so far (seconds; Linux's schedstat - its run
    queue's wait), read again and again from one descriptor; 0 where there is none. A gap the window spent
    waiting for a CPU that something else on the machine had (another job beside the tests, a build) is the
    machine's, not the window's: the heartbeat leaves it out. Waiting for Python's lock is no CPU's wait (a
    thread asleep on the lock): a worker holding it is counted in full."""

    def __init__(self):
        try:
            self.fd = os.open("/proc/thread-self/schedstat", os.O_RDONLY)
        except OSError:
            self.fd = None

    def __call__(self) -> float:
        if self.fd is None:
            return 0.0
        try:
            return int(os.pread(self.fd, 128, 0).split()[1]) / 1e9
        except (OSError, ValueError, IndexError):
            return 0.0

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class Heartbeat:
    """A heartbeat on the GUI thread (a QTimer of *interval* ms) from now to stop(): the longest turn
    (the GUI thread's CPU time between two ticks) and the longest gap (the wall-clock time between them -
    and from the last tick to stop() - but the GUI thread's own wait for a CPU the machine gave elsewhere:
    _Waited; *raw* the longest with it). *blocked*: the longest time between two ticks the GUI thread was
    neither on a CPU nor waiting for one, past a tick's interval - asleep on Python's lock a worker held
    (a worker's hold as the window feels it, measured without a thread of its own: a probe's own wake-ups
    cost the GUI thread a hand-over of the lock each on a busy machine)."""

    def __init__(self, interval: int = 5):
        from PyQt6.QtCore import QTimer

        self.waited = _Waited()
        self.cpu, self.wall, self.queued = time.thread_time(), time.monotonic(), self.waited()
        self.turn = self.gap = self.raw = self.blocked = 0.0
        self.interval = interval / 1000
        self.turns: list[float] = []
        self.timer = QTimer()
        self.timer.setInterval(interval)
        self.timer.timeout.connect(self._beat)
        self.timer.start()

    def _beat(self) -> None:
        cpu, wall, queued = time.thread_time(), time.monotonic(), self.waited()
        self.turns.append(cpu - self.cpu)
        self.turn = max(self.turn, cpu - self.cpu)
        self._gaps(wall, queued, cpu)
        self.cpu, self.wall, self.queued = cpu, wall, queued

    def _gaps(self, wall: float, queued: float, cpu: float) -> None:
        own = wall - self.wall - (queued - self.queued)  # (the machine's wait for a CPU left out)
        self.raw = max(self.raw, wall - self.wall)
        self.gap = max(self.gap, own)
        # (off its CPU and not waiting for one: asleep on Python's lock a worker holds - or idle, a tick's
        # interval at most)
        self.blocked = max(self.blocked, own - (cpu - self.cpu) - self.interval)

    def stop(self) -> tuple[float, float]:
        """(the longest turn, the longest gap) - the heartbeat stopped."""
        if self.timer.isActive():
            self.timer.stop()
            self._gaps(time.monotonic(), self.waited(), time.thread_time())
            self.waited.close()
            STOPPED.append((self.gap, self.turn))
        return self.turn, self.gap


#: While above 0, assert_responsive only records (a measure that is asked again when it fails: within_turn).
DEFERRED = [0]


def assert_responsive(gap: float, label=None) -> None:
    """*gap* (a heartbeat's longest) within gap_budget() - else the window froze, what held it aside (under
    markdown_timing.SOFT a warning: a budget). Not while a caller measures again before it judges (DEFERRED:
    bugs22's within_turn)."""
    if DEFERRED[0]:
        return
    budget = gap_budget()
    if gap >= budget:
        from tests import markdown_timing as TB

        # (the blocking job: a duration is a warning there - tests/markdown_timing.py's budget())
        TB.budget(False, (label, f"the window did not answer for {gap:.3f} s (at most {budget:.3f} s)"),
                  error=Frozen)


#: The longest turn (the GUI thread's CPU time in one event-loop turn) the window may take, in seconds, on the
#: machine the budgets were measured on: over it a duration's budget is missed (a warning in the blocking job).
TURN = 0.1
#: The turn no release goes out with: a turn is CPU time, so what else the machine does cannot lengthen it -
#: only a slower machine can (machine_factor). Over it assert_turn fails in every job, the blocking one too.
TURN_GATE = 0.25


class Held(AssertionError):
    """A turn over TURN_GATE (assert_turn): the GUI thread itself worked that long in one go - the window was
    frozen whatever the machine's load. Never a warning."""


def turn_gate() -> float:
    """TURN_GATE on this machine (as much longer as it lays out a page more slowly: machine_factor)."""
    return TURN_GATE * machine_factor()


def assert_turn(turn: float, label=None) -> None:
    """*turn* (a heartbeat's longest, CPU time) judged twice: over turn_gate() it fails in every job (Held:
    the release gate - a turn does not depend on the machine's load); over TURN it misses a budget
    (tests/markdown_timing.py's budget(): a warning in the blocking job, a failure in the timing job and
    locally)."""
    gate = turn_gate()
    if turn >= gate:
        raise Held((label, f"one turn of the GUI thread took {turn:.3f} s of CPU time (the gate: {gate:.3f} s)"))
    from tests import markdown_timing as TB

    bound = TURN * machine_factor()
    TB.budget(turn < bound, (label, f"one turn of the GUI thread took {turn:.3f} s (at most {bound:.3f} s)"))


#: The marker of a test that keeps the GUI thread busy on purpose (it tests the meters themselves): its turns
#: are not gated (gate_turns).
LONG_TURN_MARKER = "long_turn"
LONG_TURN_HELP = "long_turn: holds the GUI thread on purpose (a test of the meters) - its turns are not gated"


def turns_since(mark: int) -> float:
    """The longest turn of the heartbeats stopped since STOPPED had *mark* entries."""
    return max((turn for _gap, turn in STOPPED[mark:]), default=0.0)


def gate_turns(item, mark: int) -> None:
    """(the conftests, after a test's call) no heartbeat the test stopped saw a turn over turn_gate() - else
    Held, in every job: the release gate. Whatever the test itself asserted, and however it judged its
    durations - a turn that long is the window frozen by its own work."""
    if item.get_closest_marker(LONG_TURN_MARKER) is not None or len(STOPPED) <= mark:
        return  # (meant to be long - or no heartbeat at all: nothing to time the machine for)
    longest = turns_since(mark)
    if longest < TURN_GATE:
        return
    gate = turn_gate()
    if longest >= gate:
        raise Held(f"{item.nodeid}: one turn of the GUI thread took {longest:.3f} s of CPU time "
                   f"(the gate: {gate:.3f} s)")


def after_failure(item, error: AssertionError) -> int:
    """(the conftests) what a failed test's *error* comes to. Frozen: the test is measured once more
    (measure_again) and fails only if it freezes again. A test that passes or fails by elapsed time only
    (the marker timing) in the gating run (tests/markdown_timing.py's GATE): its assertion is a duration's -
    a warning there, never Held. Anything else is raised again. Returns the mark its turns are gated from
    (those of the last run)."""
    from tests import markdown_timing as TB

    mark = len(STOPPED)
    if isinstance(error, Frozen):
        measure_again(item.runtest, error)
        return mark
    if TB.GATE and item.get_closest_marker(TB.MARKER) is not None and not isinstance(error, Held):
        text = f"{item.nodeid}: {str(error).splitlines()[0][:300] if str(error) else type(error).__name__}"
        TB.MISSED.append(text)
        import warnings

        warnings.warn(TB.TimingBudgetWarning(text), stacklevel=2)
        return 0  # (every turn of the run counts: the gate is all this job asks of it)
    raise error


def settle_collector() -> None:
    """(the conftests, before a test that may measure the window) what earlier tests of this process left
    is gone first: their windows and pages - closed, not yet deleted - are collected and deleted now. One
    process runs every test, and a window's deferred deletion is done by whatever event loop runs next: an
    export's own, in the test after it. Export PDF after three other test files had "a turn" of 0.6 to
    0.7 s so, after the whole suite 2.3 to 5 s, and passed alone: the suite's own leavings, not the
    window's work."""
    import gc
    import sys

    gc.collect()
    core = sys.modules.get("PyQt6.QtCore")
    if core is not None and core.QCoreApplication.instance() is not None:
        core.QCoreApplication.sendPostedEvents(None, core.QEvent.Type.DeferredDelete.value)
        gc.collect()  # (what those deletions let go of)


def gaps_since(mark: int) -> float:
    """The longest gap of the heartbeats stopped since STOPPED had *mark* entries."""
    return max((gap for gap, _turn in STOPPED[mark:]), default=0.0)
