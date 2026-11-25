"""The editor of the Markdown reader (and of axross): what an independent review of axross-markdown 0.17.4
found in it - a long line pasted, F4 on a big file, the preview that followed the typing once, Find Previous,
Replace All and a regular expression on the window's thread, a save over a read-only file, without a sync,
through a link with ``..`` in it; Esc, Shift+Enter and Ctrl+0 in the editor, its names for a screen reader.

Each test here failed before.
"""

from __future__ import annotations

import os
import random
import re
import stat
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets", reason="PyQt6 not installed")
pytest.importorskip("markdown_it")

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt  # noqa: E402
from PyQt6.QtGui import QTextCursor  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox, QTabBar  # noqa: E402

from axross_markdown._ax.core.local_fs import LocalFS  # noqa: E402
from tests import markdown_heartbeat as HB  # noqa: E402
from tests import markdown_timing as TB  # noqa: E402
from tests.test_markdown_reader_bugs11 import pump, until  # noqa: E402

APP = QApplication.instance() or QApplication([])

YES, NO = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No


@pytest.fixture
def window():
    from axross_markdown._ax.ui.editor_window import EditorWindow

    made = EditorWindow()
    made.resize(1200, 720)
    made.show()
    # (an error's box would wait for a click no test makes: it fails the test instead)
    with mock.patch("axross_markdown._ax.ui.editor_window.QMessageBox.critical", side_effect=AssertionError("an error was shown")), \
            mock.patch("axross_markdown._ax.ui.editor_window.QMessageBox.warning", side_effect=AssertionError("a warning was shown")):
        yield made
    for tab in made._tabs():  # (closed without its question: a modal dialog no test leaves)
        tab.editor.finish_now() if hasattr(tab.editor, "finish_now") else None
        tab.editor.document().setModified(False)
    made.close()
    made.deleteLater()
    pump(0.05)


def _focus(window, tab) -> None:
    """The window active, the keys in the tab's text (a shortcut needs both)."""
    window.activateWindow()
    tab.editor.setFocus()
    APP.processEvents()


def _idle(tab) -> bool:
    return not getattr(tab, "loading", False) and not getattr(tab.editor, "busy", False)


def _measured(action, done=lambda: True, settle: float = 0.3) -> tuple[float, float]:
    """(the longest turn, the longest gap) of the window while *action()* runs and until *done()*."""
    beat = HB.Heartbeat()
    pump(0.02)
    action()
    assert until(done, TB.READY_SECONDS)
    pump(settle)
    return beat.stop()


def _lines(tab) -> str:
    return "\n".join(tab.blocks())


def _paste(tab, text: str) -> tuple[float, float]:
    APP.clipboard().setText(text)
    editor = tab.editor
    return _measured(lambda: QTest.keyClick(editor, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier),
                     lambda: _idle(tab))


def _key(tab, key, modifiers=Qt.KeyboardModifier.NoModifier) -> tuple[float, float]:
    editor = tab.editor
    return _measured(lambda: QTest.keyClick(editor, key, modifiers), lambda: _idle(tab))


# -- a long line pasted; a big paste ----------------------------------------------------------------------------

@pytest.mark.parametrize("line", ["a" * 5_000_000, "word " * 300_000], ids=["no space", "words"])
def test_sad_a_long_line_pasted_holds_no_turn_nor_does_the_key_after_it(window, line):
    """A line of 5,000,000 characters pasted: one turn of 1.5 to 1.8 s, and so was every key typed after it,
    and the redo of the paste - the guard for long lines looked at a file opened only."""
    tab = window.new_tab()
    tab.editor.setPlainText("# Title\n\nsome text\n")
    tab.editor.moveCursor(QTextCursor.MoveOperation.End)
    turn, _gap = _paste(tab, line)
    HB.assert_turn(turn, "the paste")
    assert _lines(tab) == "# Title\n\nsome text\n" + line  # (all of it is the tab's text - what a save writes)
    turn, _gap = _key(tab, Qt.Key.Key_X)
    HB.assert_turn(turn, "the key after the paste")
    assert _lines(tab) == "# Title\n\nsome text\n" + line + "x"
    turn, _gap = _key(tab, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    HB.assert_turn(turn, "undo of the key")
    turn, _gap = _key(tab, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    HB.assert_turn(turn, "undo of the paste")
    assert _lines(tab) == "# Title\n\nsome text\n"
    turn, _gap = _measured(tab.editor.redo, lambda: _idle(tab))
    HB.assert_turn(turn, "redo of the paste")
    assert _lines(tab) == "# Title\n\nsome text\n" + line


def test_sad_a_big_paste_its_undo_and_redo_go_in_slices(window):
    """5 MB of lines pasted were one turn of 0.16 to 0.9 s (20 MB: 0.7 to 4 s), its undo 0.2 s and its redo
    0.3 s (20 MB: 0.9 and 1.5 s)."""
    pasted = "".join(f"line {n} lorem ipsum dolor sit amet\n" for n in range(150_000))  # (5.5 MB)
    tab = window.new_tab()
    tab.editor.setPlainText("first\nlast")
    cursor = tab.editor.textCursor()
    cursor.setPosition(6)
    tab.editor.setTextCursor(cursor)
    turn, _gap = _paste(tab, pasted)
    HB.assert_turn(turn, "the paste")
    assert _lines(tab) == "first\n" + pasted + "last"
    assert tab.editor.textCursor().position() == 6 + len(pasted)  # (the cursor after what was pasted)
    turn, _gap = _key(tab, Qt.Key.Key_Q)
    HB.assert_turn(turn, "the key after the paste")
    assert _lines(tab) == "first\n" + pasted + "qlast"
    for label in ("undo of the key", "undo of the paste"):
        turn, _gap = _key(tab, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        HB.assert_turn(turn, label)
    assert _lines(tab) == "first\nlast"  # (one Ctrl+Z took all of the paste back)
    turn, _gap = _measured(tab.editor.redo, lambda: _idle(tab))
    HB.assert_turn(turn, "redo of the paste")
    assert _lines(tab) == "first\n" + pasted + "last"
    # (typed over all of it selected: taken out in slices too)
    tab.editor.selectAll()
    turn, _gap = _key(tab, Qt.Key.Key_K)
    HB.assert_turn(turn, "a key over all of the text selected")
    assert _lines(tab) == "k"
    turn, _gap = _key(tab, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    HB.assert_turn(turn, "undo of that key")
    assert _lines(tab) == "first\n" + pasted + "last"


def test_happy_a_folded_line_is_one_mark_that_is_saved_copied_cut_and_undone_whole(window, tmp_path):
    """(the long line pasted is kept beside the document, one character in its place) whatever leaves the
    editor has the line itself: a save, a copy, the preview's text - and the mark is a character like any
    other to typing, undo, cut and paste."""
    from axross_markdown._ax.ui import editor_text as ET

    long = "x" * (ET.FOLD_LINE_CHARS + 7)
    path = tmp_path / "long.md"
    path.write_bytes(("top\r\n" + long + "\r\nend\r\n").encode())
    tab = window.open_file(LocalFS(), str(path))
    editor = tab.editor
    assert editor.document().characterCount() < 100  # (one mark, not 200,007 characters)
    assert tab.blocks() == ["top", long, "end", ""]
    assert editor.plain_text() == "top\n" + long + "\nend\n"
    assert editor.folded_lines() == [(2, len(long))]
    pump(0.05)
    assert not tab.long_line_note.isHidden() and "2" in tab.long_line_label.text()
    # (typed before and after the mark, and a line joined to it: the line grows by what was typed)
    cursor = QTextCursor(editor.document().findBlockByNumber(1))
    editor.setTextCursor(cursor)
    QTest.keyClicks(editor, "ab")
    editor.moveCursor(QTextCursor.MoveOperation.EndOfBlock)
    QTest.keyClicks(editor, "yz")
    assert tab.blocks() == ["top", "ab" + long + "yz", "end", ""]
    editor.moveCursor(QTextCursor.MoveOperation.StartOfBlock)
    QTest.keyClick(editor, Qt.Key.Key_Backspace)
    assert tab.blocks() == ["topab" + long + "yz", "end", ""]
    assert window.save_tab(tab)
    assert path.read_bytes() == ("topab" + long + "yz\r\nend\r\n").encode()  # (its line ends kept)
    # (copied: the line itself is on the clipboard; cut and pasted back: the same text again)
    editor.selectAll()
    assert editor.createMimeDataFromSelection().text() == "topab" + long + "yz\nend\n"
    QTest.keyClick(editor, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
    assert until(lambda: _idle(tab), TB.READY_SECONDS)
    assert tab.blocks() == [""]
    QTest.keyClick(editor, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert until(lambda: _idle(tab), TB.READY_SECONDS)
    assert tab.blocks() == ["topab" + long + "yz", "end", ""]
    for _ in range(2):
        editor.undo()
        assert until(lambda: _idle(tab), TB.READY_SECONDS)
    assert tab.blocks() == ["topab" + long + "yz", "end", ""]  # (the cut undone: the line is back whole)
    assert editor.document().characterCount() < 100


def test_edge_a_line_grown_past_the_limit_by_typing_or_small_pastes_is_folded(window):
    """(the guard at every change of the text, not at a paste only) a line that grows too long piece by
    piece - small pastes, typing, the line break before it deleted - is folded then; one undo step with the
    edit that made it that long."""
    tab = window.new_tab()
    editor = tab.editor
    editor.fold_limit = 3000
    editor.setPlainText("head\n" + "a" * 2000 + "\n" + "b" * 2000 + "\ntail")
    assert editor.folded_lines() == []
    cursor = QTextCursor(editor.document().findBlockByNumber(2))
    editor.setTextCursor(cursor)
    QTest.keyClick(editor, Qt.Key.Key_Backspace)  # (two lines of 2000 are one of 4000 now)
    pump(0.05)
    assert editor.folded_lines() == [(2, 4000)]
    assert tab.blocks() == ["head", "a" * 2000 + "b" * 2000, "tail"]
    editor.undo()
    assert tab.blocks() == ["head", "a" * 2000, "b" * 2000, "tail"] and editor.folded_lines() == []
    editor.moveCursor(QTextCursor.MoveOperation.End)
    for _ in range(3):
        APP.clipboard().setText("c" * 1200)
        QTest.keyClick(editor, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        pump(0.03)
    assert tab.blocks()[-1] == "tail" + "c" * 3600
    assert editor.folded_lines() == [(4, 3604)]
    QTest.keyClick(editor, Qt.Key.Key_Exclam)
    assert tab.blocks()[-1] == "tail" + "c" * 3600 + "!"


@pytest.mark.parametrize("seed", range(4))
def test_edge_the_long_lines_of_a_text_are_found_without_reading_every_line(seed):
    """(ui.editor_text.long_lines and pieces: pure) the lines over the limit as a look at each line finds
    them, every kind of line end; the steps a text goes in by, put together, are the text."""
    from axross_markdown._ax.ui import editor_text as ET

    rng = random.Random(seed)
    ends = ["\n", "\r\n", "\r", "\u2029", "\ufdd0", "\ufdd1"]
    for _ in range(60):
        limit = rng.choice([3, 8, 20, 64])
        text = "".join(rng.choice("ab ") * rng.choice([0, 1, 2, limit - 1, limit, limit + 1, 3 * limit])
                       + rng.choice(ends + [""]) for _ in range(rng.randint(0, 25)))
        want, at = [], 0
        for part in re.split("(\r\n|\r|\n|\u2029|\ufdd0|\ufdd1)", text)[0::1]:
            if not re.fullmatch("\r\n|\r|\n|\u2029|\ufdd0|\ufdd1", part) and len(part) > limit:
                want.append((at, at + len(part)))
            at += len(part)
        assert ET.long_lines(text, limit) == want, (limit, text)
        steps = list(ET.pieces(text, limit, ET.Pace(rng.choice([1, 2, 5, 50]))))
        assert "".join(text[start:end] for _kind, start, end in steps) == text
        assert [(start, end) for kind, start, end in steps if kind == "fold"] == want
        for kind, start, end in steps:  # (no step ends between a CR and its LF: that were two line ends)
            assert not (text[end - 1:end] == "\r" and text[end:end + 1] == "\n"), (text, steps)


# -- F4: the file read off the window's thread, its text set in slices ------------------------------------------

def _sections(count: int) -> str:
    return "".join(f"## S{n}\n\nPara {n} words words words words.\n\n" for n in range(count))


F4_DOCUMENTS = {
    "1 MB": lambda: _sections(26_000),
    "5 MB of paragraphs": lambda: "".join(f"Paragraph {n} " + "lorem ipsum dolor sit amet " * 8 + "\n\n"
                                          for n in range(22_000)),
    "5 MB with a 1 MB code block": lambda: "".join(
        f"Paragraph {n} " + "lorem ipsum dolor " * 8 + "\n\n" for n in range(25_000))
    + "```\n" + "x = 1  # code line\n" * 55_000 + "```\n\ntail\n",
    "one line of 390,000 characters": lambda: "# T\n\n" + "word " * 78_000 + "\n\nend\n",
}


@pytest.mark.parametrize("name", list(F4_DOCUMENTS))
def test_sad_f4_reads_the_file_off_the_window_s_thread_and_sets_its_text_in_slices(name, tmp_path):
    """F4 in axross-markdown read the file, split it twice, found its language and set its text in one turn
    of the window: 0.12 s at 1 MB, 0.22 to 0.29 s at 5 MB and for one line of 390,000 characters."""
    from axross_markdown._ax.ui import markdown_app as MA

    text = F4_DOCUMENTS[name]()
    path = tmp_path / "doc.md"
    path.write_text(text, encoding="utf-8")
    program = MA.MarkdownApp()

    def ready() -> bool:
        window = program.editor_window
        tab = window.current_tab() if window is not None else None
        return tab is not None and _idle(tab)

    try:
        turn, _gap = _measured(lambda: program.edit(LocalFS(), str(path)), ready, settle=1.0)
        tab = program.editor_window.current_tab()
        HB.assert_turn(turn, f"F4 on {name}")
        assert _lines(tab) == text
        assert tab.previewing and not tab.is_modified() and not tab.read_only
        assert not tab.editor.document().isUndoAvailable()  # (a file opened is no step to undo)
    finally:
        window = program.editor_window
        if window is not None:
            for tab in window._tabs():
                tab.editor.document().setModified(False)
            window.close()
            window.deleteLater()
        pump(0.1)


def test_guard_a_tab_whose_text_is_still_going_in_is_not_saved(window, tmp_path):
    """(the text set in slices) a save before the last slice would write a part of the file over it: it is
    refused and said so; when the text is all there the tab saves, edits and undoes as ever."""
    from axross_markdown._ax.core.text_document import TextDocument
    from axross_markdown._ax.ui.editor_window import EditorTab

    text = _sections(40_000)
    path = tmp_path / "big.md"
    path.write_text(text, encoding="utf-8")
    document = TextDocument(LocalFS(), str(path))
    assert document.load() == text
    tab = window._add_tab(EditorTab(LocalFS(), str(path), text, document, False, slices=True))
    assert tab.loading and not tab.is_modified()
    assert window.save_tab(tab) is False
    assert "still" in window.statusBar().currentMessage()
    assert path.read_text(encoding="utf-8") == text
    QTest.keyClick(tab.editor, Qt.Key.Key_X)  # (no key changes a text that is still going in)
    assert until(lambda: not tab.loading, TB.READY_SECONDS)
    assert _lines(tab) == text and not tab.is_modified()
    assert tab.editor.textCursor().position() == 0
    QTest.keyClick(tab.editor, Qt.Key.Key_X)
    assert tab.is_modified() and window.save_tab(tab)
    assert path.read_text(encoding="utf-8") == "x" + text


def test_happy_a_file_opened_in_the_background_is_coloured_and_reloads_in_slices(window, tmp_path):
    """(the text set in slices) the file's language is found on the reader's thread, its colours are painted
    a part a turn; Reload sets the text the same way."""
    text = "".join(f"def f{n}(x):\n    return x + {n}  # comment\n" for n in range(20_000))
    path = tmp_path / "code.py"
    path.write_text(text)
    opened = []
    window.opened.connect(opened.append)
    turn, _gap = _measured(lambda: window.open_file(LocalFS(), str(path), background=True),
                           lambda: bool(opened) and _idle(opened[0])
                           and not opened[0].editor.highlighter.lexing, settle=0.3)
    tab = opened[0]
    HB.assert_turn(turn, "a Python file of 0.8 MB opened and coloured")
    assert tab.editor.language == "Python" and _lines(tab) == text
    formats = tab.editor.document().findBlockByNumber(39_999).layout().formats()
    assert formats, "the last line has no colours"
    path.write_text("# changed\n" + text)
    turn, _gap = _measured(window.reload_current, lambda: _idle(tab), settle=0.3)
    HB.assert_turn(turn, "Reload")
    assert _lines(tab) == "# changed\n" + text and not tab.is_modified()


def test_sad_a_save_and_a_search_of_a_big_text_read_it_in_slices(window, tmp_path):
    """Ctrl+S asked each of a big text's lines for its text on the window's thread (12 MB: 0.2 s and more),
    twice - once to write it, once to see whether it was edited meanwhile; the first search read all of it
    in one call."""
    text = "".join(f"line {n} lorem ipsum dolor\n" for n in range(450_000))  # (12 MB)
    path = tmp_path / "big.txt"
    path.write_text(text)
    opened = []
    window.opened.connect(opened.append)
    window.open_file(LocalFS(), str(path), background=True)
    assert until(lambda: bool(opened) and _idle(opened[0]), TB.READY_SECONDS)
    tab = opened[0]
    QTest.keyClick(tab.editor, Qt.Key.Key_X)
    saved = []
    turn, _gap = _measured(lambda: saved.append(window.save_tab(tab)))
    HB.assert_turn(turn, "a save of 12 MB")
    assert saved == [True] and not tab.is_modified()
    assert path.read_text() == "x" + text
    window.show_find(False)
    bar = window.find_bar
    bar.find_edit.setText("line 449999 lorem")
    found = []
    turn, _gap = _measured(lambda: found.append(bar.find_next()))
    HB.assert_turn(turn, "the first search in 12 MB")
    assert found == [True] and tab.editor.textCursor().selectionStart() == 1 + text.index("line 449999 lorem")


def test_guard_a_key_typed_while_the_file_is_written_keeps_the_tab_modified(window, tmp_path):
    """(the text is no longer read a second time after a save) whether the tab's text is still what was
    written is told by the editor's count of edits: one that came while the file was written is not in the
    file - the tab stays modified; the colours painted anew are no edit."""
    path = tmp_path / "typed.py"
    path.write_text("x = 1\n")
    tab = window.open_file(LocalFS(), str(path))
    QTest.keyClick(tab.editor, Qt.Key.Key_A)
    real = tab.document.save

    def save_and_type(*args, **kwargs):
        out = real(*args, **kwargs)
        typed.append(1)
        return out

    typed = []
    with mock.patch.object(tab.document, "save", save_and_type):
        stamp = tab.editor.changes
        assert window.save_tab(tab) and typed and not tab.is_modified()
        assert path.read_text() == "ax = 1\n"
        tab.editor.highlighter.relex()
        assert until(lambda: not tab.editor.highlighter.lexing, TB.READY_SECONDS)
        assert tab.editor.changes == stamp  # (painted anew: no edit)
        QTest.keyClick(tab.editor, Qt.Key.Key_B)
        window._mark_saved(tab, stamp)  # (as a save that read the text before that key)
        assert tab.is_modified()
        assert window.save_tab(tab) and not tab.is_modified()
    assert path.read_text() == "abx = 1\n"


@pytest.mark.parametrize("seed", range(3))
def test_edge_a_text_read_in_slices_is_the_text(window, monkeypatch, seed):
    """(BigTextEditor.read_text: the document's text a slice a turn) what is read is what the blocks hold -
    no-break spaces, U+2028, emoji, a folded line whole or as its mark; edited while it is read, it is read
    from its start again."""
    from axross_markdown._ax.ui import editor_text as ET

    rng = random.Random(seed)
    monkeypatch.setattr(ET, "READ_CHARS", rng.choice([1, 7, 40]))
    monkeypatch.setattr(ET, "TURN_SECONDS", 0.0)  # (a slice a turn)
    tab = window.new_tab()
    editor = tab.editor
    editor.fold_limit = 30
    lines = ["".join(rng.choice(["a", " ", "\u00a0", "\u2028", "\U0001f600", "\ufffc", "b" * 9])
                     for _ in range(rng.randint(0, 12))) for _ in range(rng.randint(1, 30))]
    editor.setPlainText("\n".join(lines))
    assert tab.blocks() == lines
    got = []
    editor.read_text(got.append)
    editor.read_text(got.append, "\n", False)
    assert until(lambda: len(got) == 2, TB.READY_SECONDS)
    assert got[0].split("\u2029") == lines
    assert got[1] == editor.raw_text()
    # (edited while it is read: what comes is the text after the edit - or None, edited all the while)
    got = []
    editor.read_text(got.append)
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.insertPlainText("!")
    assert until(lambda: len(got) == 1, TB.READY_SECONDS)
    assert got[0].split("\u2029") == tab.blocks() == [*lines[:-1], lines[-1] + "!"]
    got = []
    editor.read_text(got.append)
    for _ in range(ET.READ_TRIES + 1):  # (edited before every try: given up, said with None)
        editor.insertPlainText("?")
        APP.processEvents()
    assert until(lambda: len(got) == 1, TB.READY_SECONDS) and got[0] is None


# -- the preview follows every edit ------------------------------------------------------------------------------

def _preview_tab(window, tmp_path, sections: int):
    text = "".join(f"## Section {n}\n\nParagraph of section {n} with words words words.\n\n"
                   for n in range(sections))
    path = tmp_path / "follow.md"
    path.write_text(text)
    window.preview_new_tabs = True
    tab = window.open_file(LocalFS(), str(path))
    assert until(lambda: tab.preview._readable, TB.READY_SECONDS)
    pump(1.0)
    return tab


def _section_shown(preview) -> int | None:
    """The section in the middle of the preview's view."""
    block = preview.browser.cursorForPosition(preview.browser.viewport().rect().center()).block()
    for _ in range(40):
        found = re.search(r"ection (\d+)", block.text())
        if found:
            return int(found.group(1))
        block = block.previous()
        if not block.isValid():
            break
    return None


def _type_in_section(tab, section: int) -> None:
    tab.editor.setTextCursor(QTextCursor(tab.editor.document().findBlockByNumber(section * 4 + 2)))
    QTest.keyClick(tab.editor, Qt.Key.Key_Z)


#: How long a test waits for the preview to show the place typed at (a readiness wait, no budget: the
#: preview is made anew after a pause in the typing, and a page that never follows fails after it).
FOLLOWED_SECONDS = 45


@pytest.mark.parametrize("sections", [500, 40])
def test_sad_the_preview_follows_every_edit_not_the_first_only(window, tmp_path, sections):
    """Typed in section 400 of 500, the preview went there; typed in section 100 after that, it stayed at
    400 - and at every edit after: a page shown again at the place read before never said it was shown."""
    tab = _preview_tab(window, tmp_path, sections)
    preview = tab.preview
    places = [400, 100, 250, 30, 480, 5] if sections == 500 else [35, 4, 20, 38]
    for count, section in enumerate(places, 1):
        _type_in_section(tab, section)
        assert until(lambda: preview.markdown.count("z") == count and preview._readable, TB.READY_SECONDS)
        # (no budget: a preview that does not follow never comes there)
        assert until(lambda: abs((_section_shown(preview) or -99) - section) <= 12, FOLLOWED_SECONDS), \
            (section, _section_shown(preview))


def test_sad_a_pause_in_the_typing_renders_the_preview_once_and_never_shows_its_top_first(window, tmp_path):
    """Each pause in the typing made the preview twice (the text set again when its colours were painted),
    and the page's top was painted before the place read; a key in a big text read all of the text."""
    tab = _preview_tab(window, tmp_path, 300)
    preview = tab.preview
    _type_in_section(tab, 200)
    assert until(lambda: abs((_section_shown(preview) or -99) - 200) <= 12, FOLLOWED_SECONDS)
    pump(0.5)
    renders, tops = [], []
    real = preview.render
    preview.render = lambda *a, **kw: (renders.append(1), real(*a, **kw))[1]

    class Paints(QObject):
        def eventFilter(self, _watched, event) -> bool:  # noqa: N802 - Qt
            if event.type() == QEvent.Type.Paint:
                tops.append(preview.browser.cursorForPosition(QPoint(5, 5)).block().text())
            return False

    paints = Paints()
    preview.browser.viewport().installEventFilter(paints)
    reads = []
    for name in ("toPlainText", "plain_text"):  # (whichever reads all of the text)
        if hasattr(tab.editor, name):
            setattr(tab.editor, name, lambda real=getattr(tab.editor, name): (reads.append(1), real())[1])
    try:
        for count, section in enumerate((205, 190), 2):
            del renders[:], tops[:], reads[:]
            tab.editor.setTextCursor(QTextCursor(tab.editor.document().findBlockByNumber(section * 4 + 2)))
            QTest.keyClicks(tab.editor, "zq")
            assert reads == []  # (the text is read after the pause, not at each key)
            assert until(lambda: preview.markdown.count("zq") == count - 1 and preview._readable,
                         TB.READY_SECONDS)
            assert until(lambda: abs((_section_shown(preview) or -99) - section) <= 12, FOLLOWED_SECONDS)
            pump(1.2)  # (the colours of what was typed are painted meanwhile)
            assert len(renders) == 1, renders
            assert not [top for top in tops if "ection 0" in top or top.startswith("Section 1 ")], tops[:5]
    finally:
        preview.browser.viewport().removeEventFilter(paints)


# -- Find Previous, Replace All, a regular expression --------------------------------------------------------------

def _big_text() -> str:
    return "".join(f"Paragraph {n} " + "lorem ipsum dolor sit amet " * 8 + "\n\n" for n in range(22_000))


def test_sad_find_previous_and_replace_all_in_5_mb_hold_no_turn(window):
    """Find Previous of "a" in 5 MB listed every match on the window's thread (0.4 to 0.57 s), Replace All
    replaced there and set all of the text anew (0.14 to 0.16 s)."""
    text = _big_text()
    tab = window.new_tab()
    tab.editor.setPlainText(text)
    tab.editor.document().setModified(False)
    pump(0.3)
    window.show_find(True)
    bar = window.find_bar
    bar.find_edit.setText("a")
    tab.editor.moveCursor(QTextCursor.MoveOperation.End)
    found = []
    turn, _gap = _measured(lambda: found.append(bar.find_next(backwards=True)))
    HB.assert_turn(turn, "Find Previous")
    cursor = tab.editor.textCursor()
    assert found == [True] and cursor.selectedText() == "a"
    assert cursor.selectionStart() == text.rindex("a")
    turn, _gap = _measured(lambda: found.append(bar.find_next(backwards=True)))
    HB.assert_turn(turn, "Find Previous again")
    assert tab.editor.textCursor().selectionStart() == text.rindex("a", 0, text.rindex("a"))
    bar.find_edit.setText("nowhere in it")
    turn, _gap = _measured(lambda: found.append(bar.find_next(backwards=True)))
    HB.assert_turn(turn, "Find Previous of what is not there")
    assert found[-1] is False and bar.message.text() == "Not found"
    bar.find_edit.setText("Paragraph")
    bar.replace_edit.setText("Section\\1")  # (no Regex: the replacement as it is written)
    counted = []
    turn, _gap = _measured(lambda: counted.append(bar.replace_all()), lambda: _idle(tab))
    HB.assert_turn(turn, "Replace All")
    assert counted == [22_000] and bar.message.text() == "22000 replaced"
    assert _lines(tab) == text.replace("Paragraph", "Section\\1")
    turn, _gap = _measured(tab.editor.undo, lambda: _idle(tab))
    HB.assert_turn(turn, "undo of Replace All")
    assert _lines(tab) == text  # (one step back)
    turn, _gap = _measured(tab.editor.redo, lambda: _idle(tab))
    HB.assert_turn(turn, "redo of Replace All")
    assert _lines(tab) == text.replace("Paragraph", "Section\\1")


@pytest.mark.parametrize("action", ["next", "previous", "replace all", "replace"])
def test_sad_a_regular_expression_that_backtracks_without_end_is_stopped_and_said(window, monkeypatch, action):
    """Regex ticked, ``(\\w+\\s?)+$X`` on a file of 210 bytes: the search ran on the window's thread and never
    came back. It runs in a process of its own now (a thread would not do: one match holds Python's lock),
    ended after REGEX_SECONDS - the window answers meanwhile, the bar says the search was stopped."""
    from axross_markdown._ax.ui import editor_window as EW

    monkeypatch.setattr(EW, "REGEX_SECONDS", 1.0)
    monkeypatch.setattr(EW, "REPLACE_SECONDS", 1.0)
    text = "word " * 42
    assert len(text) == 210
    tab = window.new_tab()
    tab.editor.setPlainText(text)
    window.show_find(True)
    bar = window.find_bar
    bar.regex.setChecked(True)
    bar.find_edit.setText(r"(\w+\s?)+$X")
    bar.replace_edit.setText("-")
    if action == "replace":
        tab.editor.selectAll()
    call = {"next": bar.find_next, "previous": lambda: bar.find_next(backwards=True),
            "replace all": bar.replace_all, "replace": bar.replace_one}[action]
    out = []
    turn, gap = _measured(lambda: out.append(call()))
    assert not out[0]
    assert "stopped" in bar.message.text(), bar.message.text()
    assert _lines(tab) == text
    HB.assert_turn(turn, action)
    HB.assert_responsive(gap, action)  # (the window answered while the search ran)
    # (and the next search is answered as ever: by another child)
    bar.find_edit.setText(r"w(or)d\s")
    tab.editor.moveCursor(QTextCursor.MoveOperation.Start)
    assert bar.find_next() and tab.editor.textCursor().selectedText() == "word "


FIND_TEXT = "alpha Beta\nbeta gamma\n\U0001f600 beta\xa0gamma end\nThe beta.\n"


@pytest.mark.parametrize("regex", [False, True], ids=["as typed", "regex"])
def test_happy_find_and_replace_find_what_they_found_before(window, regex):
    """(searched off the window's thread: a window of the text at a time, or in the child) next and previous
    with their wrap, Case, Whole word, a match after an emoji, a replacement's groups - as ``re`` on all of
    the text finds them."""
    tab = window.new_tab()
    tab.editor.setPlainText(FIND_TEXT)
    window.show_find(True)
    bar = window.find_bar
    bar.regex.setChecked(regex)
    bar.find_edit.setText("b[e]ta" if regex else "beta")
    starts = [match.start() for match in re.finditer("beta", FIND_TEXT, re.IGNORECASE)]
    units = [start + (1 if start > FIND_TEXT.index("\U0001f600") else 0) for start in starts]
    tab.editor.moveCursor(QTextCursor.MoveOperation.Start)
    seen = []
    for _ in range(len(starts) + 1):
        assert bar.find_next()
        seen.append(tab.editor.textCursor().selectionStart())
        assert tab.editor.textCursor().selectedText().lower() == "beta"
    assert seen == units + units[:1]  # (and around to the first)
    back = []
    for _ in range(len(starts)):
        assert bar.find_next(backwards=True)
        back.append(tab.editor.textCursor().selectionStart())
    assert back == [units[-1], *reversed(units[1:-1]), units[0]][:len(starts)] or back == list(reversed(units))
    bar.case.setChecked(True)
    tab.editor.moveCursor(QTextCursor.MoveOperation.Start)
    assert bar.find_next() and tab.editor.textCursor().selectedText() == "beta"
    assert tab.editor.textCursor().selectionStart() == FIND_TEXT.index("beta")
    bar.case.setChecked(False)
    bar.whole_word.setChecked(True)
    bar.find_edit.setText("bet")
    assert not bar.find_next() and bar.message.text() == "Not found"
    bar.whole_word.setChecked(False)
    bar.find_edit.setText("(b)eta" if regex else "beta")
    bar.replace_edit.setText(r"<\1>" if regex else r"<\1>")
    assert bar.replace_all() == 4
    want = re.sub("(b)eta", r"<\1>", FIND_TEXT, flags=re.I) if regex else re.sub("(?i)beta", lambda _m: r"<\1>",
                                                                                 FIND_TEXT)
    assert _lines(tab) == want  # (the no-break space and the emoji as they were)
    tab.editor.undo()
    assert _lines(tab) == FIND_TEXT
    if regex:
        bar.replace_edit.setText(r"\9")
        assert bar.replace_all() == 0 and "Bad replacement" in bar.message.text()
        assert _lines(tab) == FIND_TEXT
        bar.find_edit.setText("(")
        assert not bar.find_next() and "Bad regex" in bar.message.text()
        bar.find_edit.setText("^")  # (an empty match is none)
        assert not bar.find_next() and bar.replace_all() == 0
    # (Replace: the match selected becomes the replacement, the next is found)
    bar.find_edit.setText("gam+a" if regex else "gamma")
    bar.replace_edit.setText("G")
    tab.editor.moveCursor(QTextCursor.MoveOperation.Start)
    assert bar.find_next() and bar.replace_one()
    assert _lines(tab) == FIND_TEXT.replace("gamma", "G", 1)
    assert tab.editor.textCursor().selectedText() == "gamma"


@pytest.mark.parametrize("seed", range(3))
def test_edge_a_search_in_windows_finds_what_one_search_of_all_the_text_finds(seed, monkeypatch):
    """(core.text_search: pure) a needle searched a window at a time - next, previous, every replacement -
    is the same as ``re`` over all of the text: a match across two windows, a word's end at a window's end."""
    from axross_markdown._ax.core import text_search as TS

    rng = random.Random(seed)
    for _ in range(150):
        monkeypatch.setattr(TS, "WINDOW", rng.choice([1, 2, 3, 7, 16]))
        monkeypatch.setattr(TS, "JOIN_GAP", rng.choice([0, 2, 96]))
        monkeypatch.setattr(TS, "PIECE_CHARS", rng.choice([1, 5, 32_000]))
        text = "".join(rng.choice(["ab", "a", "b", " ", "\n", "Ab", "aba", "\ufffc"]) for _ in range(rng.randint(0, 50)))
        needle = rng.choice(["a", "ab", "aba", "b a", "a\nb", "B"])
        case, whole = rng.random() < 0.5, rng.random() < 0.3
        pattern = TS.compiled(needle, regex=False, case=case, whole_word=whole)
        every = [m for m in pattern.finditer(text) if "\ufffc" not in m.group()]
        spans = [(m.start(), m.end()) for m in every]
        start = rng.randint(0, len(text))
        after = [(m.start(), m.end()) for m in pattern.finditer(text, start) if "\ufffc" not in m.group()]
        assert TS.find_next(pattern, text, start, len(needle)) == (after[0] if after else (spans[0] if spans else None))
        got = TS.find_previous(pattern, text, start, len(needle))
        if needle in ("a", "B", "a\nb", "b a"):  # (a needle that cannot overlap itself: the very same matches)
            before = [span for span in spans if span[1] <= start]
            assert got == (before[-1] if before else (spans[-1] if spans else None)), (text, needle, start)
        elif got is not None:
            assert pattern.fullmatch(text, got[0], got[1]) or whole
        pieces, count = TS.replacements(pattern, text, None, "<x>", len(needle))
        assert count == len(spans)
        want, at = [], 0
        for m in every:
            want += [text[at:m.start()], "<x>"]
            at = m.end()
        assert TS.replaced(text, pieces) == "".join(want) + text[at:], (text, needle)
        assert all(a[1] <= b[0] for a, b in zip(pieces, pieces[1:]))


def test_edge_replace_all_that_joins_the_lines_into_one_folds_it(window):
    """(a line too long is never laid out) every line break replaced by nothing makes one line of all the
    text: it is folded, not laid out - and one undo step back are the lines."""
    tab = window.new_tab()
    editor = tab.editor
    editor.fold_limit = 4000
    text = "\n".join(f"line {n} of the text" for n in range(400))
    editor.setPlainText(text)
    window.show_find(True)
    bar = window.find_bar
    bar.regex.setChecked(True)
    bar.find_edit.setText(r"\n")
    bar.replace_edit.setText("")
    assert bar.replace_all() == 399
    assert until(lambda: _idle(tab), TB.READY_SECONDS)
    assert tab.blocks() == [text.replace("\n", "")]
    assert editor.folded_lines() == [(1, len(text) - 399)] and editor.document().characterCount() == 2
    # (what a folded line holds is not searched, and never replaced by its mark's match)
    bar.find_edit.setText(".")
    bar.replace_edit.setText("!")
    assert bar.replace_all() == 0 and tab.blocks() == [text.replace("\n", "")]
    editor.undo()
    assert until(lambda: _idle(tab), TB.READY_SECONDS)
    assert _lines(tab) == text


# -- saving ------------------------------------------------------------------------------------------------------

def test_sad_a_read_only_file_is_asked_about_before_it_is_replaced_and_keeps_its_mode(window, tmp_path):
    """A file marked read-only (0444) in a folder that can be written was replaced by Ctrl+S without a word:
    "Saved ro.md", another inode."""
    path = tmp_path / "ro.md"
    path.write_text("old\n")
    os.chmod(path, 0o444)
    inode = os.stat(path).st_ino
    tab = window.open_file(LocalFS(), str(path))
    QTest.keyClicks(tab.editor, "new ")
    with mock.patch("axross_markdown._ax.ui.editor_window.QMessageBox.question", return_value=NO) as asked:
        assert window.save_tab(tab) is False
    assert asked.call_count == 1 and "read-only" in asked.call_args.args[2]
    assert path.read_text() == "old\n" and os.stat(path).st_ino == inode and tab.is_modified()
    _focus(window, tab)
    with mock.patch("axross_markdown._ax.ui.editor_window.QMessageBox.question", return_value=YES) as asked:
        QTest.keyClick(tab.editor, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert asked.call_count == 1
    assert path.read_text() == "new old\n" and not tab.is_modified()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o444  # (it stays read-only)
    # (a file that can be written is saved without a question, as ever)
    plain = tmp_path / "rw.md"
    plain.write_text("a\n")
    other = window.open_file(LocalFS(), str(plain))
    QTest.keyClicks(other.editor, "b")
    with mock.patch("axross_markdown._ax.ui.editor_window.QMessageBox.question", return_value=NO) as asked:
        assert window.save_tab(other)
    assert asked.call_count == 0 and plain.read_text() == "ba\n"


def test_edge_a_read_only_file_is_told_through_its_links_only_on_this_machine(tmp_path):
    """(core.atomic_io.read_only_target) the file a link leads to is the one asked about; a file that is
    not there, a folder, another backend's path are none."""
    from axross_markdown._ax.core.atomic_io import read_only_target

    fs = LocalFS()
    target = tmp_path / "target.md"
    target.write_text("x")
    os.chmod(target, 0o444)
    os.symlink("target.md", tmp_path / "link.md")
    assert read_only_target(fs, str(target)) and read_only_target(fs, str(tmp_path / "link.md"))
    os.chmod(target, 0o644)
    assert not read_only_target(fs, str(target)) and not read_only_target(fs, str(tmp_path / "link.md"))
    assert not read_only_target(fs, str(tmp_path / "nothing.md")) and not read_only_target(fs, str(tmp_path))
    assert not read_only_target(object(), str(target))


def test_sad_a_save_syncs_the_new_file_and_its_folder(tmp_path, monkeypatch):
    """An ordinary Ctrl+S made one call that mattered, ``rename``: the new file's bytes were not synced
    before it, the folder not after it - a power loss right after "Saved" could leave an empty file."""
    from axross_markdown._ax.core import atomic_io

    path = tmp_path / "note.md"
    path.write_text("old")
    steps = []
    real_fsync, real_rename = os.fsync, os.rename

    def fsync(fd):
        mode = os.fstat(fd).st_mode
        steps.append(("sync folder", os.readlink(f"/proc/self/fd/{fd}")) if stat.S_ISDIR(mode)
                     else ("sync file", os.fstat(fd).st_size))
        return real_fsync(fd)

    def rename(src, dst, **kwargs):
        steps.append(("rename", os.path.basename(str(dst))))
        return real_rename(src, dst, **kwargs)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "rename", rename)
    atomic_io.atomic_write(LocalFS(), str(path), b"new text")
    assert path.read_bytes() == b"new text"
    assert steps == [("sync file", 8), ("rename", "note.md"), ("sync folder", str(tmp_path))], steps
    # (a file system that cannot sync does not fail the save)
    monkeypatch.setattr(os, "fsync", mock.Mock(side_effect=OSError(22, "Invalid argument")))
    atomic_io.atomic_write(LocalFS(), str(path), b"again")
    assert path.read_bytes() == b"again"
    # (one that fails for another reason does: the bytes may not be there - and no temp file stays)
    monkeypatch.setattr(os, "fsync", mock.Mock(side_effect=OSError(5, "Input/output error")))
    with pytest.raises(OSError):
        atomic_io.atomic_write(LocalFS(), str(path), b"never")
    assert path.read_bytes() == b"again" and sorted(os.listdir(tmp_path)) == ["note.md"]


def _temps(*folders) -> list[str]:
    return sorted(name for folder in folders for name in os.listdir(folder) if name.startswith(".tmp-"))


def test_sad_a_link_whose_target_holds_dotdot_is_saved_through_and_leaves_no_temp_file(window, tmp_path):
    """``sub/l2.md -> ../target.md``: the save's temp file went to ``sub/../``, its rename and its removal
    were refused for the ``..`` - the file could never be saved, and every try left a ``.tmp-<hex>.tmp`` with
    the text beside the target."""
    (tmp_path / "sub").mkdir()
    target = tmp_path / "target.md"
    target.write_text("old\n")
    os.chmod(target, 0o640)
    link = tmp_path / "sub" / "l2.md"
    os.symlink("../target.md", link)
    tab = window.open_file(LocalFS(), str(link))
    QTest.keyClicks(tab.editor, "new ")
    assert window.save_tab(tab)
    assert target.read_text() == "new old\n" and os.path.islink(link)
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o640
    assert _temps(tmp_path, tmp_path / "sub") == []


def test_guard_dotdot_is_taken_one_link_at_a_time_and_the_guard_still_refuses_it(tmp_path):
    """(core.atomic_io._without_parent_steps) ``..`` after a link to a folder is the folder above the link's
    target, not the one the link lies in: taken by name it would save into another file. A loop of links is
    ELOOP; a path that still leaves its start is refused before a temp file is written; rename and remove
    of a path with ``..`` are refused as ever (core.backend_guard is as it was)."""
    import errno

    from axross_markdown._ax.core import atomic_io

    fs = LocalFS()
    (tmp_path / "real" / "deep").mkdir(parents=True)
    (tmp_path / "sub").mkdir()
    os.symlink("real/deep", tmp_path / "ld")
    inner, outer = tmp_path / "real" / "x.md", tmp_path / "x.md"
    inner.write_text("inner")
    outer.write_text("outer")
    # (sub/../ld/.. is real/, not the folder ld lies in)
    os.symlink("../ld/../x.md", tmp_path / "sub" / "l3.md")
    assert atomic_io._without_parent_steps(fs, str(tmp_path / "sub" / ".." / "ld" / ".." / "x.md")) == str(inner)
    atomic_io.atomic_write(fs, str(tmp_path / "sub" / "l3.md"), b"through the link")
    assert inner.read_text() == "through the link" and outer.read_text() == "outer"
    assert os.path.realpath(tmp_path / "sub" / "l3.md") == str(inner)
    # (a path given with ``..`` is saved where the system would open it)
    atomic_io.atomic_write(fs, str(tmp_path / "ld" / ".." / "x.md"), b"again")
    assert inner.read_text() == "again" and outer.read_text() == "outer"
    assert atomic_io._without_parent_steps(fs, "/a/../../b") == "/b"
    assert atomic_io._without_parent_steps(fs, str(tmp_path / "sub" / "plain.md")) == str(tmp_path / "sub" / "plain.md")
    # (links in a loop)
    os.symlink("loop2/..", tmp_path / "loop1")
    os.symlink("loop1/..", tmp_path / "loop2")
    with pytest.raises(OSError) as loop:
        atomic_io.atomic_write(fs, str(tmp_path / "loop1" / ".." / "y.md"), b"y")
    assert loop.value.errno == errno.ELOOP
    # (a relative path above its start: refused, nothing written anywhere)
    with pytest.raises(PermissionError):
        atomic_io.atomic_write(fs, os.path.join("..", "..", "escape.md"), b"no")
    # (a failure after the temp file was written: it is gone)
    with mock.patch.object(LocalFS, "rename", side_effect=OSError(5, "Input/output error")):
        with pytest.raises(OSError):
            atomic_io.atomic_write(fs, str(tmp_path / "sub" / "l3.md"), b"never")
    assert inner.read_text() == "again"
    assert _temps(tmp_path, tmp_path / "sub", tmp_path / "real", tmp_path / "real" / "deep") == []
    # (the guard: as it was)
    for call in (lambda: fs.remove(str(tmp_path / "sub" / ".." / "x.md")),
                 lambda: fs.rename(str(tmp_path / "sub" / ".." / "x.md"), str(tmp_path / "z.md")),
                 lambda: fs.rename(str(outer), str(tmp_path / "sub" / ".." / "z.md"))):
        with pytest.raises(PermissionError):
            call()
    assert outer.read_text() == "outer"


def test_guard_a_link_that_leads_out_of_the_folders_allowed_is_refused_as_before(tmp_path):
    """(``..`` in a link's target is taken hop by hop now) a file system kept beneath its folders (the MCP
    server's: core.confined_fs) still refuses a link that leads out of them - nothing is written outside, no
    temp file stays; a link with ``..`` that stays inside is saved through."""
    from axross_markdown._ax.core import atomic_io
    pytest.importorskip("axross_markdown._ax.core.confined_fs", reason="a tool exported without the confined folders")
    from axross_markdown._ax.core.confined_fs import ConfinedLocalFS

    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    outside, inside = tmp_path / "outside.md", root / "target.md"
    outside.write_text("outside")
    inside.write_text("old")
    os.symlink("../../outside.md", root / "sub" / "out.md")
    os.symlink("../target.md", root / "sub" / "in.md")
    os.symlink(str(outside), root / "sub" / "absolute.md")
    fs = ConfinedLocalFS([str(root)])
    for name in ("out.md", "absolute.md"):
        with pytest.raises(OSError):
            atomic_io.atomic_write(fs, str(root / "sub" / name), b"new")
        assert os.path.islink(root / "sub" / name)
    assert outside.read_text() == "outside"
    atomic_io.atomic_write(fs, str(root / "sub" / "in.md"), b"new")
    assert inside.read_text() == "new" and os.path.islink(root / "sub" / "in.md")
    assert _temps(tmp_path, root, root / "sub") == []


def test_sad_a_file_deleted_while_it_is_edited_is_asked_about_before_it_is_made_again(window, tmp_path):
    """A file deleted (or moved) while its tab was open was made again by Ctrl+S without a question."""
    path = tmp_path / "gone.md"
    path.write_text("text\n")
    tab = window.open_file(LocalFS(), str(path))
    QTest.keyClicks(tab.editor, "more ")
    path.unlink()
    with mock.patch("axross_markdown._ax.ui.editor_window.QMessageBox.question", return_value=NO) as asked:
        assert window.save_tab(tab) is False
    assert asked.call_count == 1 and "no longer there" in asked.call_args.args[2]
    assert not path.exists() and tab.is_modified()
    with mock.patch("axross_markdown._ax.ui.editor_window.QMessageBox.question", return_value=YES) as asked:
        assert window.save_tab(tab)
    assert asked.call_count == 1 and path.read_text() == "more text\n" and not tab.is_modified()


# -- keys, zoom, names -------------------------------------------------------------------------------------------

def test_sad_esc_closes_the_find_bar_and_shift_enter_searches_backwards(window):
    """Esc did nothing in the editor's find bar, Shift+Enter searched forwards as Enter does."""
    tab = window.new_tab()
    tab.editor.setPlainText("one two\none two\none two\n")
    _focus(window, tab)
    QTest.keyClick(tab.editor, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    bar = window.find_bar
    assert not bar.isHidden()
    bar.find_edit.setText("two")
    QTest.keyClick(bar.find_edit, Qt.Key.Key_Return)
    QTest.keyClick(bar.find_edit, Qt.Key.Key_Return)
    assert tab.editor.textCursor().selectionStart() == 12
    QTest.keyClick(bar.find_edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert tab.editor.textCursor().selectionStart() == 4
    QTest.keyClick(bar.find_edit, Qt.Key.Key_Enter, Qt.KeyboardModifier.ShiftModifier)
    assert tab.editor.textCursor().selectionStart() == 20  # (around, to the last)
    QTest.keyClick(bar.find_edit, Qt.Key.Key_Escape)
    assert bar.isHidden() and tab.editor.textCursor().selectedText() == "two"
    window.show_find(True)
    QTest.keyClick(bar.replace_edit, Qt.Key.Key_Escape)
    assert bar.isHidden()
    window.show_find(False)
    QTest.keyClick(bar.regex, Qt.Key.Key_Escape)  # (the focus on one of the bar's boxes)
    assert bar.isHidden()


def test_sad_ctrl_0_resets_the_zoom_and_the_preview_is_zoomed_with_the_text(window):
    """Ctrl+0 did nothing in the editor, and Zoom In / Out never reached the preview beside the text."""
    tab = window.new_tab()
    tab.editor.setPlainText("# Title\n\ntext\n")
    tab.set_preview(True)
    preview = tab.preview
    assert until(lambda: preview._readable, TB.READY_SECONDS)
    pump(0.2)

    def sizes() -> tuple[float, float]:
        return tab.editor.font().pointSizeF(), preview.browser.document().defaultFont().pointSizeF()

    base = sizes()
    _focus(window, tab)
    for _ in range(3):
        window._zoom(1)
    bigger = sizes()
    assert bigger[0] == base[0] + 3 and bigger[1] > base[1]
    window._zoom(-1)
    assert base[1] < sizes()[1] < bigger[1]
    QTest.keyClick(tab.editor, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
    assert sizes() == base
    # (a preview first shown after the zoom has the text's size)
    other = window.new_tab()
    other.editor.setPlainText("# Other\n")
    window._zoom(1)
    window._zoom(1)
    other.set_preview(True)
    assert until(lambda: other.preview._readable, TB.READY_SECONDS)
    assert other.preview.browser.document().defaultFont().pointSizeF() > base[1]


@pytest.mark.parametrize("program", ["axross-markdown", "axross"])
def test_sad_the_previews_hint_names_no_pane_in_a_program_without_one(window, program):
    """A link clicked in the preview said "Links open in the Markdown viewer (F3 in the pane)." - axross-markdown
    has no pane (axross has, and keeps its hint)."""
    from PyQt6.QtCore import QUrl

    name = APP.applicationName()
    APP.setApplicationName(program)
    try:
        tab = window.new_tab()
        tab.editor.setPlainText("[a link](https://example.org/)\n")
        tab.set_preview(True)
        tab.preview.link.emit(QUrl("https://example.org/"))
        hint = tab.preview.status.text()
        assert "Markdown viewer" in hint
        assert ("F3" in hint and "pane" in hint) == (program == "axross")
    finally:
        APP.setApplicationName(name)


def test_sad_a_file_that_is_not_utf_8_says_it_is_shown_as_latin_1_and_keeps_its_bytes(window, tmp_path):
    """A file with bytes that are no UTF-8 opened as Latin-1 without a word (the bytes are kept by a save)."""
    raw = b"caf\xe9 \xff\xfe ok\nline \x80\n"
    path = tmp_path / "latin.md"
    path.write_bytes(raw)
    tab = window.open_file(LocalFS(), str(path))
    assert not tab.encoding_note.isHidden()
    assert "UTF-8" in tab.encoding_note.text() and "Latin-1" in tab.encoding_note.text()
    assert "Latin-1" in window.statusBar().currentMessage()
    QTest.keyClicks(tab.editor, "x")
    assert window.save_tab(tab)
    assert path.read_bytes() == b"x" + raw
    plain = tmp_path / "utf8.md"
    plain.write_text("café\n", encoding="utf-8")
    assert window.open_file(LocalFS(), str(plain)).encoding_note.isHidden()


def test_sad_the_find_fields_the_text_and_a_tab_s_close_button_have_names(window, tmp_path):
    """A screen reader had no name for the editor's Find and Replace fields, its text and a tab's close
    button."""
    path = tmp_path / "named.md"
    path.write_text("text\n")
    tab = window.open_file(LocalFS(), str(path))
    bar = window.find_bar
    assert bar.find_edit.accessibleName() == "Find"
    assert bar.replace_edit.accessibleName() == "Replace with"
    assert bar.close_button.accessibleName()
    assert "named.md" in tab.editor.accessibleName()
    index = window.tabs.indexOf(tab)
    buttons = [window.tabs.tabBar().tabButton(index, side)
               for side in (QTabBar.ButtonPosition.RightSide, QTabBar.ButtonPosition.LeftSide)]
    buttons = [button for button in buttons if button is not None]
    assert buttons and all("named.md" in button.accessibleName() for button in buttons)
    # (Save As: the names follow the file's)
    with mock.patch("axross_markdown._ax.ui.editor_window.QFileDialog.getSaveFileName", return_value=(str(tmp_path / "other.md"), "")):
        assert window.save_as(tab)
    assert "other.md" in tab.editor.accessibleName()
    assert all("other.md" in button.accessibleName() for button in buttons)
