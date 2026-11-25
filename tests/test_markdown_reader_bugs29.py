"""The twenty-ninth round of the Markdown reader (axross-markdown 0.17.4's open ends): the place read kept by a
zoom out, the window answering on a raw HTML table, a page of images and an emphasis run, Export HTML's
cleaning off the GUI thread, the page's picture held through a theme switch and a reload, the first screen
shown before the rest is prepared, the toolbar reached with Tab.

Each test here failed before.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets", reason="PyQt6 not installed")
pytest.importorskip("markdown_it")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from tests import markdown_heartbeat as HB  # noqa: E402
from tests import markdown_timing as TB  # noqa: E402
from tests.test_markdown_reader_bugs11 import pump, until  # noqa: E402

APP = QApplication.instance() or QApplication([])


@pytest.fixture(params=[True, False], ids=["markdown-it", "qt"])
def full(request, monkeypatch):
    """Both parsers: markdown-it's page, and Qt's own (what the window uses without markdown-it)."""
    if not request.param:
        from axross_markdown._ax.core import markdown_doc

        monkeypatch.setattr(markdown_doc, "available", lambda: False)
    return request.param


def _ready(view) -> bool:
    return bool(view._readable and view.markdown and not view._scheduled)


def _shown_file(tmp_path, text: str, name: str = "page.md"):
    """The viewer of a real file holding *text*, its first part laid out."""
    from axross_markdown._ax.core.local_fs import LocalFS
    from axross_markdown._ax.ui.markdown_viewer import MarkdownViewerDialog

    page = tmp_path / name
    page.write_text(text, encoding="utf-8")
    viewer = MarkdownViewerDialog(LocalFS(), str(page))
    viewer.resize(1100, 800)
    viewer.show()
    assert until(lambda: _ready(viewer.view), TB.READY_SECONDS), "the page never came"
    pump(0.3)
    return viewer


class _Opening:
    """A viewer opened as _shown_file does, under a heartbeat begun before the window is made: its longest turn
    (the GUI thread's CPU time in one event-loop turn) and gap while the file was read, the page made and
    its first part laid out."""

    def __init__(self, tmp_path, text: str):
        beat = HB.Heartbeat()
        try:
            self.viewer = _shown_file(tmp_path, text)
        finally:
            self.turn, self.gap = beat.stop()


def _during(view, action, settled=None, seconds: float = 0.4) -> tuple[float, float]:
    """(the longest turn, the longest gap) while *action()* runs and the page settles after it."""
    beat = HB.Heartbeat()
    action()
    until(settled or (lambda: _ready(view)), TB.READY_SECONDS)
    pump(seconds)
    return beat.stop()


def _calm(view, seconds: float = 0.6) -> bool:
    """The page shown and not made anew for *seconds* (a resize, a zoom and a theme chosen make it anew a
    moment later: a timer's, a worker's)."""
    for _ in range(400):
        assert until(lambda: _ready(view), TB.READY_SECONDS)
        generation = view._page_generation
        pump(seconds)
        if _ready(view) and view._page_generation == generation:
            return True
    return False


def _read_to_the_end(view) -> None:
    """All of the page laid out - of the page as it is in the end, were it made anew meanwhile."""
    for _ in range(20):
        assert _calm(view)
        generation = view._page_generation
        view.load_rest()
        assert until(lambda: view._page_generation != generation or (
            _ready(view) and not view.more() and not view._gaps), TB.READY_SECONDS * 5)
        if view._page_generation == generation:
            return
    raise AssertionError("the page was made anew again and again")


def _sections(count: int, letter: str = "H") -> str:
    return "".join(f"## {letter}{i}\n\nPara *{i}* with `code` and [link](#{letter.lower()}{i}).\n\n- item\n- item\n\n"
                   f"> quote\n\n" for i in range(count))


def _heading_on_top(view, letter: str = "H") -> str:
    """The first heading ("H123") at or below the view's top."""
    from PyQt6.QtCore import QPoint

    block = view.browser.cursorForPosition(QPoint(0, 0)).block()
    for _ in range(12):
        text = block.text().strip()
        if text[:1] == letter and text[1:].isdigit():
            return text
        block = block.next()
        if not block.isValid():
            break
    return "?"


def _section_on_top(view) -> str:
    """The number of the section at the view's top: every block of a section of the page below holds it, but its table's heading."""
    import re

    from PyQt6.QtCore import QPoint

    block = view.browser.cursorForPosition(QPoint(0, 0)).block()
    for _ in range(12):
        found = re.search(r"\d+", block.text())
        if found:
            return found.group(0)
        block = block.next()
        if not block.isValid():
            break
    return "?"


# -- a zoom out keeps the place read ---------------------------------------------------------------------------

def _zoom(view, steps: int, wait: float) -> None:
    view.zoom_by(steps)
    until(lambda: _ready(view), TB.READY_SECONDS)
    pump(wait)
    until(lambda: _ready(view), TB.READY_SECONDS)


@pytest.mark.parametrize("first", [1, -1])
def test_sad_a_zoom_out_keeps_the_place_read(tmp_path, full, first):
    """Before (both parsers; 4,000 sections read to their end, at H2400): a zoom in kept H2400, each zoom out
    after it showed H2591, then H2813; Ctrl+0 H3318 - whenever the zoom before was more than three seconds
    ago. The page's height shrank under the scroll bar's value, which then lay far into the stand-in for what
    is not laid out: read as the thumb dropped there. Now every step, in both directions and back to 100 %,
    keeps the heading on the view's top."""
    viewer = _shown_file(tmp_path, _sections(4000))
    view = viewer.view
    try:
        _read_to_the_end(view)
        view.go_to_anchor("h2400")
        assert until(lambda: _heading_on_top(view) == "H2400" and not view._scheduled, 60)
        pump(0.3)
        seen = []
        for steps in (first, -1, -1, 1, 0, -1):
            _zoom(view, steps, 3.3)  # (past the three seconds a zoom holds its place for)
            seen.append((steps, _heading_on_top(view)))
        assert [top for _steps, top in seen] == ["H2400"] * len(seen), seen
    finally:
        viewer.close()


def test_sad_a_zoom_out_keeps_the_place_on_a_page_not_read_to_its_end(tmp_path, full):
    """Before: a page of tables, code and quotes scrolled to 60 % of what is laid out - one zoom out moved it
    from section 746 to 794 (markdown-it), from 1251 to 1370 (Qt's own parser)."""
    text = "".join(f"## S{i}\n\nText {i} with **words** and `code`.\n\n| a | b |\n|---|---|\n| {i} | x |\n\n"
                   f"```\ncode {i}\n```\n\n> quote {i}\n\n" for i in range(1500))
    viewer = _shown_file(tmp_path, text)
    view = viewer.view
    try:
        for _ in range(12):  # (some of it laid out: the reader scrolling on)
            bar = view.browser.verticalScrollBar()
            bar.setValue(bar.maximum())
            pump(0.2)
            until(lambda: not view._scheduled, 30)
        bar = view.browser.verticalScrollBar()
        bar.setValue(int(view._content_end() * 0.6))
        pump(0.5)
        until(lambda: not view._scheduled, 30)
        before = _section_on_top(view)
        assert before != "?"
        seen = []
        for steps in (-1, -1, 0, 1, -1):
            _zoom(view, steps, 3.3)
            seen.append((steps, _section_on_top(view)))
        assert [top for _steps, top in seen] == [before] * len(seen), (before, seen)
    finally:
        viewer.close()


# -- a raw HTML table, a page of images, an emphasis run: no long turn -----------------------------------------

def _choose_theme(theme_id: str) -> None:
    from axross_markdown._ax.ui import markdown_theme_ui as T

    T.hub().choose(theme_id, keep=False)


def _actions(viewer) -> dict:
    """The longest turn of a zoom, a resize and a theme switch of *viewer*'s page, each settled."""
    view = viewer.view
    turns = {}
    turns["zoom"], _gap = _during(view, lambda: view.zoom_by(1))
    turns["resize"], _gap = _during(view, lambda: viewer.resize(820, 700))
    generation = view._page_generation  # (a theme chosen is applied after a short pause: the page made anew)
    turns["theme"], _gap = _during(view, lambda: _choose_theme("dark"),
                                   lambda: view._page_generation > generation and _ready(view))
    return turns


def test_sad_a_raw_html_table_holds_no_turn_as_it_is_opened(tmp_path, full):
    """Before: a raw <table> of 50,000 rows (2.3 MB) held the window 0.17 s as it was opened, one of 150,000
    rows 0.55 s (both parsers); a missing anchor on that page 0.52 s. Python's full collection of the page
    just made ran in the GUI thread's next turn - over the 1.6 million events of the table the sanitizer of
    raw HTML still held, in a cycle only the collector frees. Now it keeps none of them."""
    text = "<table>\n" + "<tr><td>a</td><td><a href='x'>b</a></td></tr>\n" * 50000 + "</table>\n"
    opening = _Opening(tmp_path, text)
    viewer, turn = opening.viewer, opening.turn
    try:
        view = viewer.view
        missing, _gap = _during(view, lambda: view.go_to_anchor("nope-nothere"))
        assert "a" in view.browser.document().toPlainText()
    finally:
        viewer.close()
    HB.assert_turn(turn, "open")
    HB.assert_turn(missing, "a missing anchor")


@pytest.mark.parametrize("full", [True, False], ids=["markdown-it", "qt"])
def test_sad_a_page_s_making_leaves_no_heap_for_the_collector(full):
    """The cause of the turns above, without a clock: what a making leaves behind that only Python's
    collector can free. The sanitizer of raw HTML kept the events of the block it read last (and its text),
    in a cycle with its parser: 4 tuples a row of a raw table - 80,000 for 20,000 rows, 1.6 million for
    150,000 - walked by the next full collection, in the GUI thread's turn as a rule."""
    import gc

    from axross_markdown._ax.core import markdown_doc as MD
    from axross_markdown._ax.ui import markdown_view as MV

    text = "<table>\n" + "<tr><td>a</td><td><a href='x'>b</a></td></tr>\n" * 20000 + "</table>\n"
    gc.collect()
    with MV.collector_held():  # (as the window makes a page: no full collection meanwhile)
        if full:
            made = MV._page(MD.clean(MV.renderable(text, MV.TABLE_CELLS)[0]), None, frozenset())
        else:
            made = MV._md4c_page(MD.clean(MV.renderable(text, MV.MD4C_TABLE_CELLS)[0]), frozenset(), {})
        assert made
    left = gc.collect()
    assert left < 5000, left
    reader = MD.sanitizer()
    events = reader.feed("<table><tr><td>a</td></tr></table>", MD.HTML_BLOCK)
    assert ("start", "table", {}) in events and reader.events == [] and reader._source == ""


@pytest.mark.parametrize("named", ["each its own", "one for all"])
def test_sad_a_page_of_many_images_holds_no_turn(tmp_path, named):
    """Before (markdown-it; 20,000 images, ten a paragraph, 240 KB): open 0.13 s, zoom 0.195 s, resize 0.16 s
    of one turn; 100,000 of them 0.36 s at every zoom and resize, 0.31 s a part read on. The page paused
    after 2,200 blocks - of 22,000 images, each asked for its size when its line is laid out; each part put
    in took longer the more images the page held (Qt's object number on each image of an HTML part). Now an
    image counts as a block in every bound, and goes into the page without that number."""
    from PyQt6.QtGui import QImage

    if named == "one for all":
        folder = tmp_path / "img"
        folder.mkdir()
        picture = QImage(64, 64, QImage.Format.Format_RGB32)
        picture.fill(0x336699)
        assert picture.save(str(folder / "p.png"))
    text = "".join((f"![alt{i}](img/p{i}.png)\n" if named == "each its own" else f"![alt{i}](img/p.png)\n")
                   + ("\n" if i % 10 == 9 else "") for i in range(20000))
    opening = _Opening(tmp_path, text)
    viewer, turn = opening.viewer, opening.turn
    view = viewer.view
    try:
        assert view._weight() in range(2 * 4000 + 1)  # (not 22,000 images laid out before the page pauses)
        turns = _actions(viewer)
        # (read on: a part put in costs no more with 20,000 images in the page than with 2,000)
        beat = HB.Heartbeat()
        _read_to_the_end(view)
        turns["read on"], _gap = beat.stop()
        shown = view.browser.document().toPlainText().count("\ufffc")
        assert shown == 20000, (shown, view._part_count(), view._rest, len(view._gaps), view._scheduled,
                                dict(view._page or {}).get("loading"), view._page_generation,
                                view.status.text())  # (every image is in the page)
    finally:
        viewer.close()
        _choose_theme("auto")
    HB.assert_turn(turn, "open")
    for label, took in turns.items():
        HB.assert_turn(took, label)


def test_sad_an_image_of_an_html_part_goes_into_the_page_without_qt_s_object_number():
    """What made each part slower than the one before: Qt's HTML reader numbers every image as an object, and
    a fragment with numbered objects goes into a document in time growing with those it holds. _plain_images
    takes the number off and keeps the image's name, size, alt text and link."""
    from PyQt6.QtGui import QTextCursor, QTextDocument, QTextDocumentFragment

    from axross_markdown._ax.ui import markdown_view as MV

    part = QTextDocument()
    part.setHtml('<p>a <a href="http://x.y/"><img src="one.png" alt="first" width="30"></a> b '
                 '<img src="two.png" alt="second"> c <img src="three.png" style="float: right"></p>')
    def images(document) -> list:
        found, block = [], document.begin()
        while block.isValid():
            pieces = block.begin()
            while not pieces.atEnd():
                fmt = pieces.fragment().charFormat()
                if fmt.isImageFormat():
                    image = fmt.toImageFormat()
                    found.append((fmt.objectIndex(), image.name(), image.property(0x5002), image.width(),
                                  fmt.anchorHref()))
                pieces += 1
            block = block.next()
        return found

    assert all(number != -1 for number, *_rest in images(part))  # (Qt's HTML reader numbers each)
    MV._plain_images(part)
    after = images(part)
    assert after[:2] == [(-1, "one.png", "first", 30.0, "http://x.y/"), (-1, "two.png", "second", 0.0, "")]
    assert after[2][0] != -1 and after[2][1] == "three.png"  # (one that floats: its frame's number kept)
    page = QTextDocument()
    QTextCursor(page).insertFragment(QTextDocumentFragment(part))
    assert [number != -1 for number, *_rest in images(page)] == [False, False, True]  # (... nor in the page)
    assert " ".join(part.toPlainText().split()) == "a \ufffc b \ufffc c \ufffc"


@pytest.mark.parametrize("sign", ["*", "_"])
def test_sad_an_emphasis_run_around_one_letter_holds_no_turn(tmp_path, full, sign):
    """Before: 30,000 "*" (or "_"), a letter, 30,000 more (60 KB). Qt's own parser showed them as written, one
    paragraph that Qt laid out again with every change to its block: turns of 0.75 s at open, 0.8 s at a zoom,
    0.5 s at a resize, 0.9 s at a theme switch. markdown-it's page showed the letter after 34 s. Now a run
    longer than EMPHASIS_RUN is cut (said in the notice); both show the letter."""
    text = sign * 30000 + "a" + sign * 30000 + "\n"
    began = time.monotonic()
    opening = _Opening(tmp_path, text)
    viewer, turn = opening.viewer, opening.turn
    took = time.monotonic() - began
    view = viewer.view
    try:
        assert view.browser.document().toPlainText().split() == ["a"]
        assert view.notice.isVisible() and "*" in view.notice.text()
        turns = _actions(viewer)
        assert view.browser.document().toPlainText().split() == ["a"]
    finally:
        viewer.close()
        _choose_theme("auto")
    HB.assert_turn(turn, "open")
    for label, one in turns.items():
        HB.assert_turn(one, label)
    TB.budget(took < 10, f"shown after {took:.1f} s")


@pytest.mark.parametrize("text, shown", [
    ("*" * 400 + "a" + "*" * 400 + "\n", "a"),  # (under the bound: as it was)
    ("x " + "*" * 601 + "a" + "*" * 601 + " y\n", "x a y"),
    ("x " + "*" * 603 + "a" + "*" * 600 + " y\n", "x ***a y"),  # (three more to the left: left as written)
    ("_" * 700 + "a" + "_" * 700 + "\n", "a"),
    ("a " + "\\*" * 700 + " b\n", "a " + "*" * 700 + " b"),  # (escaped: no run of signs - none cut)
])
def test_edge_a_cut_emphasis_run_pairs_as_the_whole_one_did(full, text, shown):
    """A run is cut to EMPHASIS_RUN and what its length leaves of six: what it opens and closes pairs as
    before, and what was left over as text still is."""
    from axross_markdown._ax.ui import markdown_view as MV

    view = MV.MarkdownView(None)
    view.full = view.full and full
    view.resize(900, 700)
    view.show()
    try:
        view.render(text)
        assert until(lambda: view._readable and not view._scheduled, TB.READY_SECONDS)
        # (without its spaces: Qt breaks the line around a span nested hundreds deep, whatever its parser)
        assert "".join(view.browser.document().toPlainText().split()) == shown.replace(" ", "")
    finally:
        view.close()
        view.deleteLater()


# -- Export HTML: the text cleaned on the worker ---------------------------------------------------------------

def test_sad_export_html_cleans_the_text_on_its_worker(tmp_path, monkeypatch):
    """Before: Export HTML cleaned all of the text (core.markdown_doc.clean) in the turn that began the
    export, before its worker started - 0.14 to 0.25 s of the GUI thread for a page of 7 MB."""
    import threading

    from axross_markdown._ax.core import markdown_doc as MD

    viewer = _shown_file(tmp_path, "# Title\n\ntext with a\x07 bell\n\n" + "para\n\n" * 50)
    threads, real = [], MD.clean

    def clean(text, *rest, **more):
        if "bell" in text and len(text) > 200:
            threads.append(threading.current_thread() is threading.main_thread())
        return real(text, *rest, **more)

    monkeypatch.setattr(MD, "clean", clean)
    try:
        target = tmp_path / "out.html"
        assert viewer.export_html(str(target)) == str(target)
        written = target.read_text(encoding="utf-8")
    finally:
        viewer.close()
    assert threads and not any(threads), threads  # (cleaned, and never on the GUI thread)
    assert "Title" in written and "\x07" not in written


# -- the toolbar is reached with Tab ---------------------------------------------------------------------------

def _tabbed(viewer, presses: int, backward: bool = False) -> list:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    seen = []
    for _ in range(presses):
        widget = APP.focusWidget()
        seen.append(widget)
        QTest.keyClick(widget, Qt.Key.Key_Backtab if backward else Qt.Key.Key_Tab,
                       Qt.KeyboardModifier.ShiftModifier if backward else Qt.KeyboardModifier.NoModifier)
        pump(0.01)
    return seen


def test_sad_tab_reaches_the_toolbar_from_the_page(tmp_path):
    """Before: Tab went from the page to the corner's Maximize, Dock, Close and back to the page, for good -
    Outline, Reload, Edit, Export, zoom, View, Find and the outline's list were reached with Shift+Tab only
    (the window's focus proxy was the page). Export and the outline's button have no key of their own."""
    viewer = _shown_file(tmp_path, "# T\n\ntext\n\n## U\n\nmore\n")
    try:
        viewer.activateWindow()
        pump(0.1)
        view = viewer.view
        assert APP.focusWidget() is view.browser  # (the page first: Space and the arrows scroll it at once)
        seen = _tabbed(viewer, 24)
        wanted = [viewer.outline_button, viewer.reload_button, viewer.edit_button, *viewer._zoom,
                  viewer.export_button, viewer.view_button, viewer.find_field, view.outline]
        places = [seen.index(widget) for widget in wanted]  # (each reached ...)
        assert places == sorted(places), places  # (... in the order the toolbar reads)
        assert view.browser in seen[places[-1]:]  # (... then the page again)
        back = _tabbed(viewer, 24, backward=True)
        assert viewer.export_button in back and viewer.outline_button in back
        viewer.setFocus()  # (the window itself asked to take the focus: the page has it)
        pump(0.05)
        assert APP.focusWidget() is view.browser
    finally:
        viewer.close()


# -- a theme switch and a reload never show the page's top before the place read -------------------------------

class _Painted:
    """The heading on the view's top at each paint of its viewport (what the reader saw)."""

    def __init__(self, view):
        from PyQt6.QtCore import QEvent, QObject

        self.view, self.seen = view, []
        painted = self

        class Filter(QObject):
            def eventFilter(self, _watched, event):  # noqa: N802 - Qt
                if event.type() == QEvent.Type.Paint:
                    painted.seen.append(_heading_on_top(painted.view))
                return False

        self.filter = Filter()
        view.browser.viewport().installEventFilter(self.filter)

    def stop(self) -> list:
        self.view.browser.viewport().removeEventFilter(self.filter)
        return self.seen


@pytest.mark.parametrize("action", ["theme", "reload"])
def test_sad_a_theme_switch_or_a_reload_never_shows_the_page_s_top_first(tmp_path, full, action):
    """Before (markdown-it's page of 2,000 sections read to its end, far on): a theme chosen painted the
    page's top for 0.3 to 0.56 s before the place read was shown again, F5 for 0.16 to 0.27 s (Qt's own
    parser: F5 only, 0.03 to 0.08 s). The view's picture is now held until the place is shown, as it is
    through a resize and a zoom."""
    viewer = _shown_file(tmp_path, _sections(2000))
    view = viewer.view
    try:
        _read_to_the_end(view)
        view.go_to_anchor("h1136")
        assert until(lambda: _heading_on_top(view) == "H1136" and not view._scheduled, 60)
        pump(0.3)
        painted = _Painted(view)
        generation = view._page_generation
        try:
            if action == "theme":
                _choose_theme("sepia")
            else:
                viewer.reload()
            assert until(lambda: view._page_generation > generation, TB.READY_SECONDS)
            assert until(lambda: _ready(view) and _heading_on_top(view) == "H1136"
                         and view.browser.viewport().updatesEnabled(), TB.READY_SECONDS)
            pump(0.6)
        finally:
            seen = painted.stop()
        assert seen, "nothing painted"
        assert set(seen) == {"H1136"}, seen
    finally:
        viewer.close()
        _choose_theme("auto")


# -- a file that grows without a pause is shown anew all the same ----------------------------------------------

def test_sad_a_file_written_to_without_a_pause_is_still_shown_anew(tmp_path):
    """Before: every change to the file put the reload off by 0.3 s again - a file appended to every few
    milliseconds for 20 s showed nothing new until its writer stopped. Now a look is due WATCH_AT_MOST
    seconds after the first change at the latest."""
    from axross_markdown._ax.ui import markdown_viewer as VM

    viewer = _shown_file(tmp_path, "# Log\n\nline 0\n")
    page = tmp_path / "page.md"
    try:
        assert "line 0" in viewer.view.markdown
        count = 0
        with page.open("a", encoding="utf-8") as fh:
            # (written to every 20 ms, no pause, for well over WATCH_AT_MOST seconds - unless shown before)
            for count in range(1, int((VM.WATCH_AT_MOST + 4) / 0.02)):
                fh.write(f"\nline {count}\n")
                fh.flush()
                pump(0.02)
                if "line 5\n" in viewer.view.markdown:
                    break
            shown_while_written = "line 5\n" in viewer.view.markdown
        assert shown_while_written, "nothing new shown while the file was written to"
        assert until(lambda: f"line {count}\n" in viewer.view.markdown, TB.READY_SECONDS)  # (... and its end, once it rests)
    finally:
        viewer.close()


# -- the first screen before the rest of a long text is prepared -----------------------------------------------

def _parts(text: str) -> list[str]:
    from axross_markdown._ax.core.markdown_term import text_parts_at

    return [part for part, _line in text_parts_at(text)]


def test_sad_a_text_of_code_blocks_is_cut_between_them():
    """Before: 60,000 small code blocks, an empty line between them (1.9 MB), were one part - a part was
    cut only at a line outside code, and those were all empty: 90 s before markdown-it's page showed
    anything. Now a part may begin with a code block of the top level, and code counts as any line."""
    from axross_markdown._ax.core import markdown_term as MT

    text = "".join(f"```js\nlet a{i} = {i};\n```\n\n" for i in range(12000))
    parts = _parts(text)
    assert len(parts) > 10, len(parts)
    assert max(map(len, parts)) < 3 * MT.STREAM_PART_CHARS
    assert all(part.startswith("```js\n") for part in parts)  # (each begins with a block's opening line)
    assert all(part.count("```") % 2 == 0 for part in parts)  # (... and holds only whole blocks)
    assert "".join(part.strip("\n") + "\n\n" for part in parts) == text  # (nothing lost, nothing twice)
    # (in a list or a quote, or after a line of text: no part begins there)
    inside = "- item\n\n  ```\n  code\n  ```\n\n" * 3000 + "text\n```\ncode\n```\n" * 3000
    for part in _parts(inside):
        assert not part.startswith(("```", "  ```")), part[:40]


def test_sad_a_paragraph_of_links_a_line_is_cut_in_parts():
    """Before: 500,000 lines of a link each were one paragraph and one part (a line that begins with "[" was
    never one a part may begin at): 40 s before the page showed anything. A link's text or address that goes
    on in the next line still keeps its lines together; a definition is no such line."""
    text = "".join(f"[l{i}](http://e.x/{i})\n" for i in range(30000))
    parts = _parts(text)
    assert len(parts) > 3, len(parts)
    assert "".join(part if part.endswith("\n") else part + "\n" for part in parts) == text
    broken = "".join(f"[l{i}\nmore](http://e.x/{i})\n" for i in range(30000))
    for part in _parts(broken)[1:]:
        assert part.startswith("[l"), part[:30]  # (never between a link's two lines)


@pytest.mark.parametrize("line, least", [
    ("&amp; &lt; &#x41; &copy; " * 60000, 5),  # (character references: 400,000 of them were 18 s)
    (("**" + "a_" * 30 + "~~b**c~~ ") * 20000, 50),  # (emphasis marks: 36 s and 1.4 GB)
])
def test_sad_a_long_line_of_references_or_emphasis_is_cut_in_parts(line, least):
    """Before: one line of 7.3 MB of character references, or of 4.1 MB with one character in two a mark of
    emphasis, was one part - parsed whole before anything showed (the second: each of its pieces began
    with "**", taken for a block's begin and put together again). A piece dense with emphasis is a part of
    its own, of LINE_MARKS marks."""
    from axross_markdown._ax.core import markdown_term as MT

    parts = _parts(line + "\n")
    assert len(parts) >= least, len(parts)
    assert " ".join(" ".join(parts).split()) == " ".join(line.split())  # (cut at its spaces only)
    if "**" in line:
        assert max(sum(part.count(mark) for mark in "*_~") for part in parts) < 3 * MT.LINE_MARKS


def test_sad_markdown_it_s_page_shows_the_first_of_60_000_code_blocks_at_once(tmp_path):
    """The window: the first code blocks are on the page while the others are still parsed (it was empty
    until all of them were: 90 s)."""
    from axross_markdown._ax.ui import markdown_view as MV

    text = "".join(f"```js\nlet a{i} = {i};\n```\n\n" for i in range(60000))
    view = MV.MarkdownView(None)
    view.resize(1000, 800)
    view.show()
    try:
        view.render(text)
        assert TB.until_within(until, lambda: view._readable and "let a0 = 0" in view.browser.toPlainText(), 15)
        assert view.more() or view._page.get("loading")  # (shown before all of it is parsed)
    finally:
        view.close()
        view.deleteLater()


def _slow_whole_page(monkeypatch, seconds: float) -> list:
    """Qt's own parser's page of a text over 200,000 characters takes *seconds* longer to make: the calls."""
    from axross_markdown._ax.ui import markdown_view as MV

    calls, real = [], MV._md4c_page

    def made(text, *rest, **more):
        calls.append(len(text))
        if len(text) > 200_000:
            time.sleep(seconds)
        return real(text, *rest, **more)

    monkeypatch.setattr(MV, "_md4c_page", made)
    return calls


def _code_sections(count: int) -> str:
    return "".join(f"## H{i}\n\nPara *{i}* with `code` and [link](#h{i}).\n\n- item\n- item\n\n> quote\n\n"
                   f"```py\ndef f{i}(x):\n    return x + {i}\n```\n\n" for i in range(count))


def test_sad_qt_s_own_parser_shows_a_long_text_s_first_part_before_the_rest_is_made(monkeypatch):
    """Before: every pass over the text and the colours of all of its code came before the first screen -
    1 MB of sections with a code block each 9 s, 7 MB 54 s of an empty window. Now the first part is a page
    of its own, shown while the whole page is made; that takes its place, the reader where they were."""
    from axross_markdown._ax.ui import markdown_view as MV

    text = _code_sections(4000)
    assert len(text) > MV.MD4C_HEAD_CHARS
    calls = _slow_whole_page(monkeypatch, 1.5)
    view = MV.MarkdownView(None)
    view.full = False
    view.resize(1000, 800)
    view.show()
    try:
        view.render(text)
        assert until(lambda: view._readable and view._page is not None and view._page.get("head"),
                     TB.READY_SECONDS)
        # (the head's page: the text's first sections, the whole not made yet)
        assert len(calls) >= 1 and calls[0] < len(text) // 2, calls
        assert "H0" in view.browser.toPlainText() and "def f0(x)" in view.browser.toPlainText()
        assert view.status.text().startswith(MV.tr("Rendering…"))
        head_parts = view._part_count()
        assert until(lambda: not view._scheduled, 60)
        view.go_to_anchor("h20")  # (the reader moves on in it)
        assert until(lambda: _heading_on_top(view) == "H20", TB.READY_SECONDS)
        pump(0.2)
        # (the whole page takes its place: the reader stays where they were)
        assert until(lambda: view._readable and view._page is not None and not view._page.get("head"),
                     TB.READY_SECONDS)
        assert until(lambda: not view._scheduled and _heading_on_top(view) == "H20", 60), _heading_on_top(view)
        assert view._part_count() > head_parts
        assert len(calls) == 2 and max(calls) == calls[1] != calls[0]  # (the head, then the whole text)
        view.go_to_anchor("h3999")  # (... and all of the text is there)
        assert until(lambda: _heading_on_top(view) == "H3999", TB.READY_SECONDS)
        assert until(lambda: not view._scheduled and not view.status.text().startswith(MV.tr("Rendering…")),
                     TB.READY_SECONDS), view.status.text()
    finally:
        view.close()
        view.deleteLater()


@pytest.mark.parametrize("why", ["footnotes", "a fold", "an anchor to go to", "a short text"])
def test_edge_the_whole_page_first_where_its_first_part_alone_would_show_it_wrong(monkeypatch, why):
    """Footnotes are numbered across the text, a fold may close past the first part, a link's anchor may be
    anywhere: then the whole page is made first, as before - and a text under MD4C_HEAD_CHARS always."""
    from axross_markdown._ax.ui import markdown_view as MV

    text = _code_sections(1600)
    if why == "footnotes":
        text = "A note[^1].\n\n" + text + "\n[^1]: The note.\n"
    elif why == "a fold":
        text = "<details><summary>More</summary>\n\n" + text + "\n</details>\n"
    elif why == "a short text":
        text = _code_sections(200)
    calls = _slow_whole_page(monkeypatch, 0.0)
    view = MV.MarkdownView(None)
    view.full = False
    view.resize(1000, 800)
    view.show()
    try:
        if why == "an anchor to go to":
            view.show_text(text, anchor="h1500")
        else:
            view.render(text)
        assert until(lambda: view._readable and not view._scheduled, TB.READY_SECONDS)
        assert until(lambda: not view.status.text().startswith(MV.tr("Rendering…")), TB.READY_SECONDS)
        assert not view._page.get("head")
        assert len(calls) == 1 and calls[0] > len(text) // 2, calls  # (made once, whole)
        if why == "an anchor to go to":
            assert until(lambda: _heading_on_top(view) == "H1500", TB.READY_SECONDS)
        if why == "footnotes":
            view.load_rest()
            assert until(lambda: not view.more() and not view._scheduled, TB.READY_SECONDS)
            assert "The note." in view.browser.toPlainText()
    finally:
        view.close()
        view.deleteLater()


# -- a list nested past LIST_DEPTH: its innermost items in parts -----------------------------------------------

def test_sad_a_tight_list_deep_in_a_list_is_cut_between_its_items():
    """Before (Qt's own parser): a list each of whose items is one level deeper than the last - 8 MB of
    indentation - is shown flatter, 2,900 items in its innermost list; that was one part of the page (a part
    was cut inside a container only after a line that is no paragraph's, and a tight list has none): one
    turn of 0.2 s at open, at a theme switch, at each export and each pause of the preview. Now a part may
    begin with an item of its own. Every item is shown once, in its order."""
    import re

    from axross_markdown._ax.ui import markdown_view as MV

    text = "- a\n  - b\n    - c\n" + "".join(f"      - item {i}\n" for i in range(1000))
    assert MV.container_pieces(text).count("\u200b") >= 3  # (cut between items: it was never)
    made = MV._md4c_page(text, frozenset(), {})
    assert len(made[0]) > 3, len(made[0])
    view = MV.MarkdownView(None)
    view.full = False
    view.resize(900, 700)
    view.show()
    try:
        view.render(text)
        assert until(lambda: view._readable and not view._scheduled, TB.READY_SECONDS)
        view.load_rest()
        assert until(lambda: not view.more() and not view._scheduled, TB.READY_SECONDS)
        shown = view.browser.document().toPlainText()
        assert [int(number) for number in re.findall(r"item (\d+)", shown)] == list(range(1000))
        assert shown.split()[:3] == ["a", "b", "c"]
    finally:
        view.close()
        view.deleteLater()


# -- a long paragraph in an HTML block its page never ends: in parts --------------------------------------------

@pytest.mark.parametrize("text", [
    "<p>\n" + ("plain words here and there " * 4 + "\n") * 2500,  # (never ended: the page ends it)
    "<p>\n" + ("plain words here and there " * 4 + "\n") * 2500 + "</p>\n\nafter\n",
    "<div>\n" + ("<b>bold</b> and <i>it</i> words here \n") * 4000 + "\nafter\n",
    "<p>\nintro *not em* line\n" + ("word " * 20 + "\n") * 3000,
], ids=["never ended", "ended", "a div of spans", "with marks"])
def test_sad_a_long_paragraph_in_an_html_block_is_laid_out_in_parts(text):
    """Before: "<p>" over 2,000 lines of text, never ended (the page ends it), was one piece - an element
    was cut in pieces only when its block ended it. The first part of the page was that paragraph, 218,000
    characters: one turn of 0.13 s as the page was shown, and at each pause of the preview. Now it is cut
    as an element that is ended; the page holds the same words as the paragraph laid out in one piece."""
    from axross_markdown._ax.ui import markdown_html as MH
    from axross_markdown._ax.ui import markdown_view as MV

    def page(pieces: bool):
        events = MH.HTML_PIECE_EVENTS
        MH.HTML_PIECE_EVENTS = events if pieces else 10 ** 9
        view = MV.MarkdownView(None)
        view.resize(600, 800)
        view.show()
        pump(0.05)
        try:
            beat = HB.Heartbeat()
            view.render(text)
            assert until(lambda: view._readable and not view._scheduled, TB.READY_SECONDS)
            pump(0.1)
            turn, _gap = beat.stop()
            first = len(view._page["parts"][0])  # (what the page's first turn lays out)
            view.load_rest()
            assert until(lambda: not view.more() and not view._scheduled, TB.READY_SECONDS)
            return view.browser.document().toPlainText().split(), first, turn
        finally:
            MH.HTML_PIECE_EVENTS = events
            view.close()
            view.deleteLater()

    words, first, turn = page(True)
    whole, first_whole, _turn = page(False)
    assert words == whole  # (nothing lost, nothing twice, in its order)
    assert first < first_whole // 4, (first, first_whole)  # (the first part: a piece of it, not all)
    HB.assert_turn(turn, "the page's first part")


# -- a page of headings by the hundred thousand, shown a second time --------------------------------------------

def test_sad_a_page_of_150_000_headings_shown_again_holds_no_turn():
    """Before: 300,000 lines of "=" - each second one a heading's underline, 150,000 headings - shown again
    after a pause in the typing: the titles of all of them read as the page was shown, the page before
    freed and the new one walked by Python's collector, all in that turn - 0.17 s. Now the titles are made
    with the page, the collector runs on the page's worker, and the page before is let go of on a thread
    of its own."""
    import threading

    from axross_markdown._ax.ui import markdown_view as MV

    text = "=\n" * 300000
    view = MV.MarkdownView(None)
    view.resize(600, 800)
    view.show()
    pump(0.05)
    collected = []
    real = MV._collected_here
    MV._collected_here = lambda size: (collected.append(threading.current_thread() is threading.main_thread()),
                                       real(size))[1]
    try:
        turns = []
        for typed in ("", "x"):
            beat = HB.Heartbeat()
            view.render(text + typed)
            assert until(lambda: view._readable and view.markdown.endswith("=\n" + typed)
                         and not view._scheduled and not view.status.text().startswith("Rendering"),
                         TB.READY_SECONDS)
            pump(0.05)
            turns.append(beat.stop()[0])
        assert len(view._page["titles"]) > 1000  # (its headings' titles: there, made with the page)
        assert collected and not any(collected)  # (the collector's pass over the new page: never the window's)
    finally:
        MV._collected_here = real
        view.close()
        view.deleteLater()
    HB.assert_turn(max(turns), turns)


def test_sad_find_while_only_the_first_part_is_there_looks_in_the_whole_page(monkeypatch):
    """While Qt's own parser's page of a long text is its first part only, Find of a word further down said
    there was none. It waits for the whole page now and looks there (find_match's *again*)."""
    from axross_markdown._ax.ui import markdown_view as MV

    text = _code_sections(4000) + "\nThe last word is zebraquux here.\n"
    _slow_whole_page(monkeypatch, 1.0)
    view = MV.MarkdownView(None)
    view.full = False
    view.resize(1000, 800)
    view.show()
    found: list = []
    try:
        view.render(text)
        assert until(lambda: view._readable and view._page is not None and view._page.get("head"),
                     TB.READY_SECONDS)

        def look() -> None:
            got = view.find_match("zebraquux", again=look)
            if got is not None:
                found.append(got)

        assert view.find_match("zebraquux", again=look) is None  # (not "none": looked for in the whole page)
        assert view._page.get("head") and not found
        assert until(lambda: bool(found), TB.READY_SECONDS)
        assert found == [True] and not view._page.get("head")
        assert view.browser.textCursor().selectedText() == "zebraquux"
        assert view.find_match("H3", again=look) in (True, None)  # (a word of the page: found as ever)
    finally:
        view.close()
        view.deleteLater()


def test_edge_find_past_the_first_part_s_matches_goes_on_after_them_on_the_whole_page(monkeypatch):
    """Find had gone through the matches of the first part shown and waited for the whole page for the next:
    on it, it began at the page's top again - the first match selected once more, not the one further down."""
    from axross_markdown._ax.ui import markdown_view as MV

    text = "kiwi one\n\nkiwi two\n\n" + _code_sections(4000) + "\nkiwi three at the end.\n"
    _slow_whole_page(monkeypatch, 1.0)
    view = MV.MarkdownView(None)
    view.full = False
    view.resize(1000, 800)
    view.show()
    found: list = []
    try:
        view.render(text)
        assert until(lambda: view._readable and view._page is not None and view._page.get("head"),
                     TB.READY_SECONDS)

        def look() -> None:
            got = view.find_match("kiwi", again=look)
            if got is not None:
                found.append((got, view.browser.textCursor().block().text()))

        for _press in range(4):  # (two found in the first part; the third and fourth wait - one goes on)
            look()
        assert found == [(True, "kiwi one"), (True, "kiwi two")] and view._page.get("head")
        assert until(lambda: len(found) == 3, TB.READY_SECONDS)
        pump(0.3)
        assert found[2] == (True, "kiwi three at the end.") and len(found) == 3
        assert not view._page.get("head")
    finally:
        view.close()
        view.deleteLater()
