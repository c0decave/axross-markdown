"""The editor window: every file opened for editing, as tabs (item 48).

One window per main window. A tab is a file on any backend (core.
text_document keeps the bytes faithful) or an untitled one (New); the
window has New, Open… (the local file system - remote files open from
their pane), Save, Save As… (a local tab picks a local file, a remote tab a
path on its own backend), Save All, find and replace (regex, case, whole
word), go to line, wrap, zoom, the language, line endings and encoding of a
tab, and read-only tabs. Closing a modified tab or the window asks Save /
Discard / Cancel; Save on an untitled tab asks where first.
"""

from __future__ import annotations

import bisect
import logging
import os
import posixpath
import re

from PyQt6 import sip
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QTextCursor, QTextOption
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from axross_markdown._ax.core import text_search
from axross_markdown._ax.core.i18n import format_count, tr
from axross_markdown._ax.core.remote_name import sanitize_for_display as _shown
from axross_markdown._ax.core.text_document import TextDocument
from axross_markdown._ax.ui.code_editor import TEXT_ONLY, language_for
from axross_markdown._ax.ui.editor_text import FOLD_LINE_CHARS, BigTextEditor, long_lines
from axross_markdown._ax.ui.scan_job import ScanJob
from axross_markdown._ax.ui.icon_provider import set_window_icon
from axross_markdown._ax.ui.plain_text import as_written

log = logging.getLogger(__name__)

#: The languages offered in the status bar (any Pygments one works).
LANGUAGES = (TEXT_ONLY, "Python", "Bash", "JavaScript", "TypeScript", "JSON", "YAML", "TOML", "INI",
             "XML", "HTML", "CSS", "Markdown", "C", "C++", "Go", "Rust", "Java", "SQL", "PHP",
             "Perl", "Ruby", "Lua", "PowerShell", "Dockerfile", "Makefile", "Nginx configuration file",
             "Diff")
#: A line longer than this is folded into one mark (ui.editor_text) - shown
#: all the same (Show Anyway) it is wrapped: not wrapped, Qt lays the whole
#: line out again and again (a 6 MB one held the window 30 s).
WRAP_LINE_CHARS = FOLD_LINE_CHARS
#: A line longer than this, shown all the same, makes the tab read-only as
#: well (Edit Anyway makes it writable): each keypress in it costs most of
#: a second, a 6 MB one 4 s.
READ_ONLY_LINE_CHARS = 1_000_000
#: The preview's picture is kept at most this long while its page is made
#: anew after typing (then shown whatever it is), and this long after the
#: place typed at was asked for (its part may be laid out a turn later).
PREVIEW_HELD_MS = 1500
PREVIEW_SETTLE_MS = 60


#: What ends a block of the text widget (core.text_document._LINE_BREAK,
#: not captured).
_BLOCK_BREAKS = re.compile("\r\n|\r|\n|\u2029|\ufdd0|\ufdd1")


def _longest_line(text: str) -> tuple[int, int]:
    """(length, 1-based number) of the longest line of *text*; (0, 0)
    without looking when no line can be WRAP_LINE_CHARS long."""
    if len(text) <= WRAP_LINE_CHARS:
        return 0, 0
    best, number = 0, 0
    # (every line end the widget breaks a block at: a CR-only file split at
    # LF only was one line of all its characters, and opened read-only)
    for index, line in enumerate(_BLOCK_BREAKS.split(text)):
        if len(line) > best:
            best, number = len(line), index + 1
    return best, number


ENCODINGS = (("UTF-8", "utf-8", False), ("UTF-8 BOM", "utf-8", True), ("Latin-1", "latin-1", False),
             ("UTF-16", "utf-16", True))

#: What QTextDocument.toPlainText() - the text find searches - shows for the
#: characters QTextCursor.selectedText() keeps: block and line breaks as "\n",
#: a no-break space as a space. One character for one, so offsets agree.
_AS_PLAIN_TEXT = str.maketrans({"\u2029": "\n", "\u2028": "\n", "\ufdd0": "\n",
                                "\ufdd1": "\n", "\u00a0": " "})


#: A character outside the BMP: one Python index, two QTextCursor positions.
_ASTRAL = re.compile("[\U00010000-\U0010ffff]")
#: A text up to this long is searched at once on the GUI thread when the
#: needle is no regular expression (a few milliseconds).
INLINE_SEARCH_CHARS = 200_000
#: Seconds a regular expression's search may take before it is stopped;
#: Replace All of one (every match is expanded) gets longer.
REGEX_SECONDS = 3.0
REPLACE_SECONDS = 20.0
#: A selection up to this long is what Find… looks for.
FIND_FROM_SELECTION_CHARS = 1000


class _Offsets:
    """Python string indexes of a text and QTextCursor positions in it.

    Qt counts UTF-16 code units, so every character outside the BMP (an
    emoji) is two positions there and one index here; used as each other,
    find selected the wrong text after the first emoji."""

    def __init__(self, text: str, same: bool | None = None) -> None:
        """*same*: whether no character of *text* is outside the BMP, when
        the caller knows (the document counts as many positions as the text
        has characters) - the text is not encoded to find out, nor at all."""
        self._text = text
        if same:
            self._same, self._astral = True, []
            return
        #: The indexes of the characters outside the BMP, in order.
        self._astral = [match.start() for match in _ASTRAL.finditer(text)]
        self._same = not self._astral

    def to_qt(self, index: int) -> int:
        if self._same:
            return index
        return index + bisect.bisect_left(self._astral, index)

    def to_py(self, position: int) -> int:
        if self._same:
            return position
        # The k-th astral character (index a) begins at the position a + k;
        # a position inside its pair counts as the character's start.
        low, high = 0, len(self._astral)
        while low < high:
            middle = (low + high) // 2
            if self._astral[middle] + middle < position:
                low = middle + 1
            else:
                high = middle
        if low and self._astral[low - 1] + low - 1 == position - 1:
            return self._astral[low - 1]  # (inside the pair of the one before)
        return position - low


def language_of(path: str, text: str) -> str:
    """The language of the file *path* with the text *text* - its lexer's
    module loaded with it. The first one asked for costs 0.1 to 0.5 s
    (Pygments reads its lexers' file name patterns): a file opened in the
    background asks on its worker thread."""
    from axross_markdown._ax.ui.code_editor import _lexer

    language = language_for(posixpath.basename(path.replace("\\", "/")), text)
    _lexer(language)
    return language


class EditorTab(QWidget):
    """One file in the editor; *backend* None and *path* "" for an untitled
    tab (New) that has no file until its first save. *slices*: the text
    goes in a slice an event-loop turn (ui.editor_text: a file of some MB
    set at once held the window 0.1 to 0.3 s) - ``loading`` until it is
    all there, then ``loaded``."""

    modified_changed = pyqtSignal(bool)
    #: Edit Anyway on the note of a very long line: the window makes the
    #: tab writable.
    edit_anyway = pyqtSignal()
    #: The tab's text is all there (see *slices*).
    loaded = pyqtSignal()
    #: What the window shows of the tab changed (read-only after Show Anyway).
    changed = pyqtSignal()

    def __init__(self, backend, path: str, text: str, document: TextDocument, read_only: bool,
                 untitled_name: str = "", *, slices: bool = False, language: str | None = None) -> None:
        super().__init__()
        self.backend = backend
        self.path = path
        self.document = document
        self.untitled_name = untitled_name
        #: A line too long to show unwrapped is shown all the same (Show
        #: Anyway): the tab stays wrapped.
        self.long_line = False
        self.read_only = read_only
        self.loading = False
        #: Steps the text was zoomed by (the preview follows them).
        self.zoom_steps = 0
        self.editor = BigTextEditor(self)
        self.editor.setAccessibleName(tr("Text of {name}").format(name=self.name))
        if path:
            # The language before the text: set after it, the whole text
            # was painted once more. (*language*: found already, off this thread.)
            self.editor.set_language(language if language is not None else language_of(path, text))
        self.editor.setReadOnly(read_only)
        self.editor.document().modificationChanged.connect(self._modification_changed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        #: Said above the text: the file was not Unicode (shown as Latin-1).
        self.encoding_note = QLabel(tr(
            "{name} is not valid UTF-8: shown as Latin-1. A save keeps every byte that was not "
            "changed as it is.").format(name=_shown(self.name)))
        self.encoding_note.setWordWrap(True)
        self.encoding_note.setContentsMargins(6, 2, 6, 2)
        self.encoding_note.setHidden(not getattr(document, "not_unicode", False))
        layout.addWidget(self.encoding_note)
        self.long_line_note = QWidget(self)
        note = QHBoxLayout(self.long_line_note)
        note.setContentsMargins(6, 2, 6, 2)
        self.long_line_label = QLabel("")
        self.long_line_label.setWordWrap(True)
        self.show_anyway_button = QPushButton(tr("Show Anyway"))
        self.show_anyway_button.clicked.connect(self.show_long_lines)
        self.edit_anyway_button = QPushButton(tr("Edit Anyway"))
        self.edit_anyway_button.clicked.connect(self.edit_anyway.emit)
        note.addWidget(self.long_line_label, stretch=1)
        note.addWidget(self.show_anyway_button)
        note.addWidget(self.edit_anyway_button)
        self.long_line_note.hide()
        layout.addWidget(self.long_line_note)
        # The text and, beside it on request, its Markdown rendering
        # (set_preview): made only when first shown.
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(self.editor)
        layout.addWidget(self.split)
        self.preview = None
        self._typed = False
        #: The preview is made anew after a pause in the typing.
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._render_preview)
        #: The preview's picture is kept while its page is made anew.
        self._thaw_timer = QTimer(self)
        self._thaw_timer.setSingleShot(True)
        self._thaw_timer.timeout.connect(self._thaw_preview)
        self._folds_timer = QTimer(self)
        self._folds_timer.setSingleShot(True)
        self._folds_timer.setInterval(0)
        self._folds_timer.timeout.connect(self._say_folds)
        self.editor.folds_changed.connect(self._folds_timer.start)
        self.editor.busy_changed.connect(self._busy_changed)
        if slices:
            self.loading = True
            self.editor.load_text(text, self._text_loaded)
        else:
            self.editor.setPlainText(text)
            self.editor.document().setModified(False)
        # (the document's own signal: the widget's textChanged also comes when the text's colours
        # are painted, 0.2 s after every key - the preview was made a second time for it)
        self.editor.document().contentsChange.connect(self._contents_changed)

    def _modification_changed(self, modified: bool) -> None:
        if not self.loading:  # (a text going in is no change of the user's)
            self.modified_changed.emit(modified)

    def _text_loaded(self) -> None:
        self.loading = False
        self.editor.document().setModified(False)
        self.modified_changed.emit(False)
        if self.previewing:
            self._render_preview()
        self.loaded.emit()

    def _busy_changed(self, busy: bool) -> None:
        """(a paste, an undo ... in slices is over) the preview follows it now -
        not every slice of it."""
        if not busy and not self.loading:
            self._text_changed()

    @property
    def previewing(self) -> bool:
        return self.preview is not None and not self.preview.isHidden()

    def set_preview(self, on: bool) -> None:
        """Show (or hide) the text rendered as Markdown beside it, following
        the typing (ui.markdown_view: no HTML, nothing loaded from the
        network, images only from beside the file)."""
        if on and self.preview is None:
            from axross_markdown._ax.ui import markdown_view as MDV

            source = MDV.ImageSource(self.backend, self.path) if self.backend is not None else None
            self.preview = MDV.MarkdownView(source, outline=False, parent=self)
            # (axross-markdown has no pane: the hint named "F3 in the pane" there)
            hint = (tr("Links open in the Markdown viewer (F3 in the pane).") if program_name() == "axross"
                    else tr("Links open in the Markdown viewer, not in the preview."))
            self.preview.link.connect(lambda _url: self.preview.status.setText(hint))
            self.preview.shown.connect(self._follow_typing)
            self.preview.returned.connect(self._follow_typing)
            self.split.addWidget(self.preview)
            self.split.setSizes([1, 1])
            for _step in range(abs(self.zoom_steps)):  # (the size the text was zoomed to)
                self.preview.zoom_by(1 if self.zoom_steps > 0 else -1)
        if self.preview is None:
            return
        self.preview.setHidden(not on)
        if on and not self.loading:
            self._render_preview()

    def zoom(self, steps: int) -> None:
        """The text - and its preview - *steps* bigger; 0: the size they began with."""
        self.zoom_steps = self.zoom_steps + steps if steps else 0
        self.editor.zoom(steps)
        if self.preview is not None:
            self.preview.zoom_by(steps)

    def _contents_changed(self, _position: int, _removed: int, _added: int) -> None:
        self._text_changed()

    def _text_changed(self) -> None:
        """(the text changed) the preview made anew after a pause in the
        typing - the text is read then, not at every key: toPlainText() of
        20 MB at every key was 0.07 s of each."""
        if self.previewing and not self.editor.busy and not self.loading:
            self._typed = True
            self._preview_timer.start(self.preview.timer.interval())

    def _render_preview(self) -> None:
        if not self.previewing or self.editor.busy or self.loading:
            return
        if self.editor.big:
            # (a big text: read a slice a turn - all of 20 MB read at once was 0.085 s of the turn)
            self.editor.read_text(self._preview_read, "\n")
        else:
            self._preview_read(self.editor.plain_text())

    def _preview_read(self, text: str | None) -> None:
        """(the text read for the preview) its page made anew - unless it is the page's text already."""
        if sip.isdeleted(self) or not self.previewing or self.editor.busy or self.loading:
            return
        if text is None or self._preview_timer.isActive():
            if text is None:
                self._preview_timer.start(self.preview.timer.interval())  # (edited all the while: after the next pause)
            return
        preview = self.preview
        if text == preview.markdown and (getattr(preview, "_page", None) is not None
                                         or not getattr(preview, "_readable", True)):
            # Nothing of the text changed (its colours were painted: Qt says the text changed then too):
            # the page stays - or is on its way. The place typed at is still to be shown when this came
            # between the page's making and its showing: shown now, or by the page when it is readable.
            if self._typed and getattr(preview, "_readable", False):
                self._follow_typing()
            return
        self._show_preview(text)

    def _show_preview(self, text: str) -> None:
        """(the text read after a pause in the typing) its page made."""
        if sip.isdeleted(self) or not self.previewing or self._preview_timer.isActive():
            return  # (typed on meanwhile: the next pause's text is shown)
        preview = self.preview
        if self._typed:
            # The page is shown at the place typed at (_follow_typing), not back
            # where it was read before - and its picture stays until then: its
            # top was painted first, every time.
            preview.pending = ("scroll", preview.browser.verticalScrollBar().value())
            preview.browser.viewport().setUpdatesEnabled(False)
            self._thaw_timer.start(PREVIEW_HELD_MS)
        preview.render(text)

    def _thaw_preview(self) -> None:
        self._thaw_timer.stop()
        if self.preview is None or sip.isdeleted(self.preview):
            return
        viewport = self.preview.browser.viewport()
        if not viewport.updatesEnabled():
            viewport.setUpdatesEnabled(True)
            viewport.update()

    def _follow_typing(self) -> None:
        """The preview at the place typed (once it shows the text as it is now) - it stayed where it was:
        typed at line 170, the preview showed the top; and from the second edit on, where the first was."""
        if not self._typed or not self.previewing:
            return
        if self._preview_timer.isActive():  # (a page of the text before the typing, just shown - a long table's
            return  # first page: followed then, the typed one's never was - the next page follows the typing)
        self._typed = False
        self.preview.show_source_line(self.preview.markdown, self.editor.textCursor().blockNumber())
        # (the place is shown in this turn, or once its part is laid out: the picture back soon after)
        self._thaw_timer.start(PREVIEW_SETTLE_MS)

    @property
    def untitled(self) -> bool:
        return self.backend is None

    @property
    def name(self) -> str:
        if self.untitled:
            return self.untitled_name
        return posixpath.basename(self.path.replace("\\", "/")) or self.path

    def is_modified(self) -> bool:
        return not self.loading and self.editor.document().isModified()

    def set_read_only(self, read_only: bool) -> None:
        self.read_only = read_only
        self.editor.setReadOnly(read_only)
        if not read_only:
            self.edit_anyway_button.hide()
            if self.long_line:
                self.long_line_note.hide()

    def mark_modified(self) -> None:
        self.editor.document().setModified(True)

    def blocks(self) -> list[str]:
        """The text's lines as the file is to hold them (a folded line whole)."""
        return self.editor.blocks()

    # -- lines too long to lay out -----------------------------------------------------------

    def _say_folds(self) -> None:
        """The note above the text: which line is folded, and Show Anyway."""
        if self.long_line or sip.isdeleted(self.editor):
            return
        folded = self.editor.folded_lines()
        if not folded:
            self.long_line_note.hide()
            return
        line, chars = max(folded, key=lambda entry: entry[1])
        self.long_line_label.setText(tr(
            "Line {line} is {chars} characters long: folded into one mark – laid out, a line that "
            "long holds the window at every key. It is saved as it is; Find does not look into "
            "it.").format(line=line, chars=format_count(chars)))
        self.show_anyway_button.show()
        self.edit_anyway_button.hide()
        self.long_line_note.show()

    def show_long_lines(self) -> None:
        """Show Anyway: every line as it is, wrapped - the window is held
        while Qt lays a long one out, and at every key typed in it; a line
        longer than READ_ONLY_LINE_CHARS makes the tab read-only (Edit
        Anyway). The undo steps are gone."""
        editor = self.editor
        editor.finish_now()
        blocks = editor.blocks()
        modified = self.is_modified()
        longest, line = max(((len(block), number + 1) for number, block in enumerate(blocks)),
                            default=(0, 0))
        self.long_line = True
        editor.fold_limit = None
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        # Anywhere, not at a word boundary first: a line with no place
        # to break (a hex dump, a long token) was searched for one from
        # every character on - 1 MB held the window 145 s.
        editor.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        editor.setPlainText("\n".join(blocks))
        editor.document().setModified(modified)
        self.show_anyway_button.hide()
        if longest > READ_ONLY_LINE_CHARS:
            self.set_read_only(True)
            self.long_line_label.setText(tr(
                "Line {line} is {chars} characters long: shown wrapped and read-only – "
                "typing in it is slow.").format(line=line, chars=format_count(longest)))
            self.edit_anyway_button.show()
            self.long_line_note.show()
        else:
            self.long_line_note.hide()
        self.changed.emit()


class _FindEdit(QLineEdit):
    """The find bar's fields: Enter searches on, Shift+Enter back, Esc
    closes the bar (Enter with Shift searched forwards, Esc did nothing)."""

    #: Enter: True with Shift (backwards).
    submitted = pyqtSignal(bool)
    escaped = pyqtSignal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.submitted.emit(bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.escaped.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _SearchStopped(Exception):
    """A search of the find bar was ended past its time."""


class FindBar(QWidget):
    """Find and replace in the current tab.

    A search never runs on the GUI thread but for a short text: what the
    user typed as it is (no Regex) is searched a window at a time on a
    worker thread (core.text_search), a regular expression in a child
    process that is ended past REGEX_SECONDS (core.lex_worker.find) - one
    that backtracks without end froze the window for good. The window is
    painted meanwhile (ui.off_gui); keys and clicks wait."""

    def __init__(self, window: "EditorWindow") -> None:
        super().__init__(window)
        self._window = window
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self.find_edit = _FindEdit()
        self.find_edit.setPlaceholderText(tr("Find"))
        self.find_edit.setAccessibleName(tr("Find"))
        self.find_edit.submitted.connect(lambda back: self.find_next(backwards=back))
        self.find_edit.escaped.connect(self.close_bar)
        self.replace_edit = _FindEdit()
        self.replace_edit.setPlaceholderText(tr("Replace with"))
        self.replace_edit.setAccessibleName(tr("Replace with"))
        self.replace_edit.submitted.connect(lambda _back: self.replace_one())
        self.replace_edit.escaped.connect(self.close_bar)
        self.regex = QCheckBox(tr("Regex"))
        self.case = QCheckBox(tr("Case"))
        self.whole_word = QCheckBox(tr("Whole word"))
        previous = QPushButton(tr("Previous"))
        previous.clicked.connect(lambda: self.find_next(backwards=True))
        following = QPushButton(tr("Next"))
        following.clicked.connect(lambda: self.find_next())
        replace = QPushButton(tr("Replace"))
        replace.clicked.connect(self.replace_one)
        replace_all = QPushButton(tr("Replace All"))
        replace_all.clicked.connect(self.replace_all)
        close = QPushButton("×")
        close.setFlat(True)
        close.setAccessibleName(tr("Close the find bar"))
        close.setToolTip(tr("Close the find bar (Esc)"))
        close.clicked.connect(self.close_bar)
        self.close_button = close
        self.message = QLabel("")
        self.replace_widgets = (self.replace_edit, replace, replace_all)
        for widget in (self.find_edit, previous, following, self.replace_edit, replace, replace_all,
                       self.regex, self.case, self.whole_word, self.message, close):
            layout.addWidget(widget)
        #: (the document, its revision, the text searched, its offsets): the
        #: text is read once for all the searches of a text unchanged.
        self._read: tuple | None = None

    def close_bar(self) -> None:
        """Esc, or the bar's x: the bar gone, the keys back in the text."""
        self.hide()
        self._read = None  # (the text read for the searches: let go of)
        tab = self._window.current_tab()
        if tab is not None:
            tab.editor.setFocus()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt
        if event.key() == Qt.Key.Key_Escape:  # (the focus on one of the bar's buttons or boxes)
            self.close_bar()
            event.accept()
            return
        super().keyPressEvent(event)

    def _pattern(self) -> re.Pattern | None:
        needle = self.find_edit.text()
        if not needle:
            return None
        # MULTILINE: ^ and $ are each line's start and end, as in every
        # editor - without it "^#include" was not found past line 1, and
        # Replace All of "\s+$" removed only the final newline.
        try:
            return text_search.compiled(needle, regex=self.regex.isChecked(), case=self.case.isChecked(),
                                        whole_word=self.whole_word.isChecked())
        except re.error as exc:
            self.message.setText(tr("Bad regex: {error}").format(error=exc))
            return None

    def _text_of(self, editor) -> tuple[str, "_Offsets"]:
        """The text find searches (toPlainText(): a no-break space is a
        space there) and its offsets - read once per state of the document."""
        document = editor.document()
        read = self._read
        if read is not None and read[0] is document and read[1] == editor.changes:
            return read[2], read[3]
        stamp, count = editor.changes, document.characterCount() - 1
        if editor.big:
            # (a big text: read a slice a turn, made what find searches off this thread)
            def shape(raw: str):
                text = raw.replace("\u2028", "\n").replace("\u00a0", " ")
                return text, _Offsets(text, same=len(text) == count)

            text, offsets = self._window._read(self._window.current_tab(), shape, "\n", False)  # noqa: SLF001
        else:
            text = editor.toPlainText()
            offsets = _Offsets(text, same=len(text) == count)
        self._read = (document, stamp, text, offsets)
        return text, offsets

    def _ask(self, op: str, pattern: re.Pattern, text: str, **more):
        """One search: ``op`` "next" / "previous" (a span or None), "all"
        (pieces, count) or "one" (the replacement or None). Raises
        _SearchStopped (said in the bar already) and re.error (a bad
        replacement)."""
        from axross_markdown._ax.ui.off_gui import run_off_gui

        literal = not self.regex.isChecked()
        width = len(self.find_edit.text()) if literal else None
        template = more.get("template")

        def here():
            if op == "next":
                return text_search.find_next(pattern, text, more["start"], width)
            if op == "previous":
                return text_search.find_previous(pattern, text, more["start"], width)
            if op == "all":
                return text_search.replacements(pattern, text, None, template, width)
            return text_search.replace_one(pattern, text, None, template)

        if literal:
            # (a short text at once: a thread and an event loop of its own cost more than the search)
            return here() if len(text) <= INLINE_SEARCH_CHARS else run_off_gui(here)
        request = {"op": op, "source": self.find_edit.text(), "case": self.case.isChecked(),
                   "whole_word": self.whole_word.isChecked(), "text": text, **more}
        seconds = REPLACE_SECONDS if op == "all" else REGEX_SECONDS

        def child():
            from axross_markdown._ax.core import lex_worker

            try:
                return lex_worker.find(request, seconds)
            except lex_worker.FindTooSlow:
                raise _SearchStopped from None
            except lex_worker.LexError as exc:
                # (no child could be started, or it ended: said, never run here - it could not be stopped)
                log.warning("The search could not be run: %s", exc)
                return {"error": "child", "text": str(exc)}

        try:
            answer = run_off_gui(child)
        except _SearchStopped:
            self.message.setText(tr("The search took longer than {n} s and was stopped.").format(
                n=format(seconds, "g")))
            raise
        if answer.get("error") == "template":
            raise re.error(answer.get("text") or "bad replacement")
        if "error" in answer:
            self.message.setText(tr("The search could not be run: {error}").format(
                error=answer.get("text") or answer["error"]))
            raise _SearchStopped
        if op == "all":
            return [tuple(piece) for piece in answer["pieces"]], answer["count"]
        if op == "one":
            return answer.get("new")
        span = answer.get("span")
        return tuple(span) if span else None

    def find_next(self, backwards: bool = False) -> bool:
        tab = self._window.current_tab()
        pattern = self._pattern()
        if tab is None or pattern is None:
            return False
        self.message.setText("")
        editor = tab.editor
        try:
            text, offsets = self._text_of(editor)
        except OSError as exc:
            self.message.setText(tr("The search could not be run: {error}").format(error=exc))
            return False
        cursor = editor.textCursor()
        try:
            if backwards:
                span = self._ask("previous", pattern, text, start=offsets.to_py(cursor.selectionStart()))
            else:
                span = self._ask("next", pattern, text, start=offsets.to_py(cursor.selectionEnd()))
        except _SearchStopped:
            return False
        if sip.isdeleted(self) or sip.isdeleted(editor):
            return False
        now = self._text_of(editor)[0]
        if span is None or (now is not text and now != text):  # (the text changed meanwhile: not its place)
            self.message.setText(tr("Not found"))
            return False
        cursor = editor.textCursor()
        cursor.setPosition(offsets.to_qt(span[0]))
        cursor.setPosition(offsets.to_qt(span[1]), QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        return True

    def replace_one(self) -> bool:
        tab = self._window.current_tab()
        pattern = self._pattern()
        if tab is None or pattern is None or tab.read_only or tab.editor.busy:
            return False
        cursor = tab.editor.textCursor()
        # As find saw it: a match across a line break is "\n" there, U+2029 here.
        selected = cursor.selectedText().translate(_AS_PLAIN_TEXT)
        if selected:
            try:
                new = self._ask("one", pattern, selected, template=self._replacement())
            except _SearchStopped:
                return False
            except re.error as exc:
                self.message.setText(tr("Bad replacement: {error}").format(error=exc))
                return False
            if new is not None and not sip.isdeleted(tab.editor):
                tab.editor.textCursor().insertText(new)
        return self.find_next()

    def _replacement(self) -> str:
        """The replacement: as it is without Regex, else ``re``'s template."""
        return self.replace_edit.text()

    def replace_all(self) -> int:
        """Replace every match as one undo step; returns the count (of a big
        text: the matches found - they are put in a part a turn of the
        event loop, the bar says when it is done)."""
        tab = self._window.current_tab()
        pattern = self._pattern()
        if tab is None or pattern is None or tab.read_only or tab.editor.busy:
            return 0
        editor = tab.editor
        # The blocks' own text, not toPlainText(): that one turns no-break
        # spaces into spaces and U+2028 into "\n", and what is between two
        # matches near each other is written back with them.
        stamp = editor.changes
        try:
            text = self._window._read(tab, lambda raw: raw, "\n", False)  # noqa: SLF001 - the window reads its tabs
        except OSError as exc:
            self.message.setText(tr("The search could not be run: {error}").format(error=exc))
            return 0
        offsets = _Offsets(text, same=len(text) == editor.document().characterCount() - 1)
        limit = editor.fold_limit
        try:
            pieces, count = self._ask("all", pattern, text, template=self._replacement())
            whole = None
            if count and limit is not None:
                # (lines joined into one too long to lay out - every line break replaced by
                # nothing: the text is set anew, that line folded)
                from axross_markdown._ax.ui.off_gui import run_off_gui

                def joined():
                    new = text_search.replaced(text, pieces)
                    return new if long_lines(new, limit) else None

                whole = joined() if len(text) <= INLINE_SEARCH_CHARS else run_off_gui(joined)
        except _SearchStopped:
            return 0
        except re.error as exc:
            self.message.setText(tr("Bad replacement: {error}").format(error=exc))
            return 0
        if sip.isdeleted(self) or sip.isdeleted(editor):
            return 0
        if not count:
            self.message.setText(tr("{n} replaced").format(n=0))
            return 0
        if editor.busy or editor.changes != stamp:
            self.message.setText(tr("The text changed meanwhile: nothing replaced."))
            return 0

        def done() -> None:
            if not sip.isdeleted(self):
                self.message.setText(tr("{n} replaced").format(n=count))

        self.message.setText(tr("Replacing {n}…").format(n=count))
        if whole is not None:
            whole = editor.unfold_marks(whole)  # (a folded line is its mark there: put back whole)
            if whole is None:
                self.message.setText(tr("The text changed meanwhile: nothing replaced."))
                return 0
            editor.replace_range(0, editor.document().characterCount() - 1, whole, done)
        else:
            editor.apply_edits([(offsets.to_qt(start), offsets.to_qt(end), new) for start, end, new in pieces],
                               done)
        if len(text) <= INLINE_SEARCH_CHARS:
            editor.finish_now()  # (a short text: replaced when this returns)
        return count


def program_name() -> str:
    """The program the editor is a window of: axross - or a program of its
    own made of axross's tools (axross-markdown: its editor was "Editor —
    axross")."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    name = app.applicationName() if app is not None else ""
    return name if name.startswith("axross-") else "axross"


class EditorWindow(QMainWindow):
    #: (backend, path) after a save: the panes showing its folder refresh.
    saved = pyqtSignal(object, str)
    #: A tab was added (the main window shows the editor then).
    opened = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        set_window_icon(self, "edit")
        # Files being read in the background: (backend, path, job).
        self._loads: list[tuple[object, str, ScanJob]] = []
        #: Loads started read-only (View) that an Edit asked for meanwhile.
        self._edit_wanted: list[tuple[object, str, ScanJob]] = []
        self.setWindowTitle(tr("Editor") + " — " + program_name())
        self.resize(1000, 720)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(lambda _i: self._update_status())
        self.find_bar = FindBar(self)
        self.find_bar.hide()
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.find_bar)
        self.setCentralWidget(central)
        self.position_label = QLabel("")
        self.encoding_label = QLabel("")
        self.eol_label = QLabel("")
        self.language_combo = QComboBox()
        self.language_combo.addItems(LANGUAGES)
        self.language_combo.setEditable(True)
        self.language_combo.activated.connect(lambda _i: self._language_chosen())
        for widget in (self.position_label, self.encoding_label, self.eol_label, self.language_combo):
            self.statusBar().addPermanentWidget(widget)
        self._untitled_count = 0
        #: Markdown files open with their preview beside them (axross-markdown).
        self.preview_new_tabs = False
        self._build_menus()
        self._add_corner()

    def _add_corner(self) -> None:
        """The menu bar is the title bar: the name and ``_ [] x`` at its right
        end, as every window has them (ui/close_corner.py). The [x] is
        close(), so unsaved tabs ask as always."""
        from axross_markdown._ax.ui.close_corner import add_title_bar

        add_title_bar(self)

    # -- menus ---------------------------------------------------------------------------

    def _action(self, menu, text, slot, shortcut=None, checkable=False) -> QAction:
        action = menu.addAction(tr(text))
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.setCheckable(checkable)
        # A checkable action also changes by setChecked, which emits toggled only.
        (action.toggled if checkable else action.triggered).connect(slot)
        return action

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu(tr("&File"))
        self._action(file_menu, "&New", lambda: self.new_tab(), "Ctrl+N")
        self._action(file_menu, "&Open…", lambda: self.open_dialog(background=True), "Ctrl+O")
        file_menu.addSeparator()
        self._action(file_menu, "&Save", lambda: self.save_current(), "Ctrl+S")
        self._action(file_menu, "Save &As…", lambda: self.save_as(), "Ctrl+Shift+S")
        # Ctrl+Shift+S is Save As everywhere; Save All takes Kate's key.
        self._action(file_menu, "Save A&ll", lambda: self.save_all(), "Ctrl+L")
        self._action(file_menu, "&Reload", lambda: self.reload_current())
        file_menu.addSeparator()
        self._action(file_menu, "&Close Tab", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
        edit = bar.addMenu(tr("&Edit"))
        for text, name, shortcut in (("&Undo", "undo", "Ctrl+Z"), ("&Redo", "redo", "Ctrl+Y"),
                                     ("Cu&t", "cut", "Ctrl+X"), ("&Copy", "copy", "Ctrl+C"),
                                     ("&Paste", "paste", "Ctrl+V"), ("Select &All", "selectAll", "Ctrl+A")):
            action = edit.addAction(tr(text))
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(lambda _c=False, n=name: self._editor_call(n))
        edit.addSeparator()
        self._action(edit, "&Find…", lambda: self.show_find(False), "Ctrl+F")
        self._action(edit, "R&eplace…", lambda: self.show_find(True), "Ctrl+H")
        self._action(edit, "Find &Next", lambda: self.find_bar.find_next(), "F3")
        self._action(edit, "&Go to Line…", lambda: self._ask_line(), "Ctrl+G")
        view = bar.addMenu(tr("&View"))
        self.wrap_action = self._action(view, "&Wrap Lines", lambda on: self._set_wrap(on), checkable=True)
        self._action(view, "Zoom &In", lambda: self._zoom(1), "Ctrl++")
        self._action(view, "Zoom &Out", lambda: self._zoom(-1), "Ctrl+-")
        self._action(view, "&Actual Size", lambda: self._zoom(0), "Ctrl+0")
        view.addSeparator()
        self.preview_action = self._action(view, "&Markdown Preview", lambda on: self._set_preview(on),
                                           "Ctrl+Shift+M", checkable=True)
        fmt = bar.addMenu(tr("F&ormat"))
        endings = fmt.addMenu(tr("Line &Endings"))
        for label, newline in (("LF (Unix)", "\n"), ("CRLF (Windows)", "\r\n"), ("CR (old Mac)", "\r")):
            self._action(endings, label, lambda _c=False, n=newline: self.set_newline(n))
        encodings = fmt.addMenu(tr("En&coding"))
        for label, codec, bom in ENCODINGS:
            self._action(encodings, label, lambda _c=False, c=codec, b=bom: self.set_encoding(c, bom=b))

    def _editor_call(self, name: str) -> None:
        tab = self.current_tab()
        if tab is not None:
            getattr(tab.editor, name)()

    # -- tabs ----------------------------------------------------------------------------

    def current_tab(self) -> EditorTab | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, EditorTab) else None

    def _tabs(self) -> list[EditorTab]:
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    @staticmethod
    def _same_backend(a, b) -> bool:
        """Whether *a* and *b* show the same files: the same object, or two
        plain LocalFS - every local pane has one of its own, and the same
        file opened from two of them became two tabs with separate edits.
        A LocalFS subclass (an MTP device) is a filesystem of its own."""
        from axross_markdown._ax.core.local_fs import LocalFS

        return a is b or (type(a) is LocalFS and type(b) is LocalFS)

    @staticmethod
    def _is_local(backend) -> bool:
        """A plain local file system: saved and opened through the local
        file dialog. Anything else (a LocalFS subclass such as an MTP
        device included) is a backend of its own."""
        from axross_markdown._ax.core.local_fs import LocalFS

        return type(backend) is LocalFS

    def _tab_of(self, backend, path: str, *, besides: EditorTab | None = None) -> EditorTab | None:
        """The open tab showing *path* on *backend* (other than *besides*)."""
        for tab in self._tabs():
            if (tab is not besides and not tab.untitled and tab.path == path
                    and self._same_backend(tab.backend, backend)):
                return tab
        return None

    def is_loading(self, backend, path: str) -> bool:
        """Whether *path* on *backend* is being read for a tab."""
        return any(self._same_backend(b, backend) and p == path for b, p, _job in self._loads)

    def open_file(self, backend, path: str, *, read_only: bool = False,
                  background: bool = False) -> EditorTab | None:
        """The tab of *path* on *backend*, opened now or already open.

        With *background* a file not open yet is read off the GUI thread -
        a slow remote file freezes no window - and None is returned; the
        tab follows with the ``opened`` signal (an unreadable file: a
        message instead)."""
        tab = self._tab_of(backend, path)
        if tab is not None:
            if not read_only:
                self._make_writable(tab)
            self.tabs.setCurrentWidget(tab)
            return tab
        if background:
            self._load_in_background(backend, path, read_only)
            return None
        document = TextDocument(backend, path)
        try:
            text = document.load()
        except OSError as exc:
            self._report_unreadable(path, exc)
            return None
        return self._add_tab(EditorTab(backend, path, text, document, read_only))

    def new_tab(self) -> EditorTab:
        """File > New: an empty untitled tab (UTF-8, LF); its first save
        asks where."""
        self._untitled_count += 1
        name = tr("Untitled-{n}").format(n=self._untitled_count)
        return self._add_tab(EditorTab(None, "", "", TextDocument.untitled(), False, name))

    def open_dialog(self, background: bool = False) -> list[EditorTab]:
        """File > Open…: files picked on the local file system, each in its
        tab. A remote file opens from its pane (Edit / F4): the pane is that
        backend's file browser, axross has no remote file dialog. With
        *background* (the menu) each is read off the GUI thread and its tab
        follows (open_file): none is returned for those."""
        from axross_markdown._ax.core.local_fs import LocalFS

        tabs = []
        for path in self._ask_open_paths():
            tab = self.open_file(LocalFS(), path, background=background)
            if tab is not None:
                tabs.append(tab)
        return tabs

    def _start_folder(self) -> str:
        """Where the local file dialogs start: the current local tab's
        folder, else the home folder."""
        tab = self.current_tab()
        if tab is not None and not tab.untitled and self._is_local(tab.backend):
            return os.path.dirname(tab.path)
        return os.path.expanduser("~")

    def _ask_open_paths(self) -> list[str]:
        paths, _filter = QFileDialog.getOpenFileNames(self, tr("Open"), self._start_folder())
        return list(paths)

    def _report_unreadable(self, path: str, exc: BaseException) -> None:
        QMessageBox.warning(
            self, tr("Open"), tr("Cannot open {path}:\n{error}").format(path=path, error=exc))

    def _load_in_background(self, backend, path: str, read_only: bool) -> None:
        if self.is_loading(backend, path):
            # The tab is on its way; an Edit while a View reads it wants
            # it writable.
            if not read_only:
                self._edit_wanted.extend(
                    e for e in self._loads
                    if self._same_backend(e[0], backend) and e[1] == path)
            return
        document = TextDocument(backend, path)
        job = ScanJob(self)
        entry = (backend, path, job)
        self._loads.append(entry)
        job.finished.connect(
            lambda kind, value, _cancelled, e=entry, d=document, ro=read_only:
            self._background_loaded(e, d, ro, kind, value)
        )
        self.statusBar().showMessage(tr("Opening {path}…").format(path=path))
        def read(_cancel, _progress) -> tuple[str, str]:
            text = document.load()
            return text, language_of(path, text)

        job.start(read)

    def _background_loaded(self, entry, document: TextDocument, read_only: bool,
                           kind: str, value) -> None:
        if entry not in self._loads:
            return  # dropped: the window closed meanwhile
        self._loads.remove(entry)
        if entry in self._edit_wanted:
            self._edit_wanted.remove(entry)
            read_only = False
        backend, path, job = entry
        job.deleteLater()
        if not self._loads:  # another file may still be on its way
            self.statusBar().clearMessage()
        if kind != "done":
            log.info("Cannot open %s: %s", path, value)
            self._report_unreadable(path, value)
            return
        tab = self._tab_of(backend, path)
        if tab is not None:  # opened meanwhile without the background
            if not read_only:
                self._make_writable(tab)
            self.tabs.setCurrentWidget(tab)
            return
        # (its text a slice a turn: set at once, 1 MB and more held the window 0.12 to 0.29 s)
        text, language = value
        self._add_tab(EditorTab(backend, path, text, document, read_only, slices=True, language=language))

    def _add_tab(self, tab: EditorTab) -> EditorTab:
        tab.modified_changed.connect(lambda _m, t=tab: self._update_title(t))
        tab.editor.cursorPositionChanged.connect(self._update_status)
        tab.editor.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth if self.wrap_action.isChecked() or tab.long_line
            else QPlainTextEdit.LineWrapMode.NoWrap)
        tab.edit_anyway.connect(lambda t=tab: self._make_writable(t))
        tab.changed.connect(lambda t=tab: self._tab_changed(t))
        tab.loaded.connect(lambda t=tab: self._tab_changed(t))
        index = self.tabs.addTab(tab, "")
        self._update_title(tab)
        if getattr(tab.document, "not_unicode", False):
            self.statusBar().showMessage(tab.encoding_note.text(), 8000)
        if self.preview_new_tabs and tab.path.lower().endswith((".md", ".markdown", ".mdown", ".mkd")):
            tab.set_preview(True)
        self.tabs.setCurrentIndex(index)
        self._update_status()
        tab.editor.setFocus()
        self.opened.emit(tab)
        return tab

    def _make_writable(self, tab: EditorTab) -> None:
        """Edit (F4) of a file a View (F3) opened read-only: the same tab,
        writable now - not the read-only one back, whose Save refused."""
        if not tab.read_only:
            return
        tab.set_read_only(False)
        self._update_title(tab)
        self._update_status()

    def _tab_changed(self, tab: EditorTab) -> None:
        if not sip.isdeleted(self) and not sip.isdeleted(tab):
            self._update_title(tab)
            self._update_status()

    def _update_title(self, tab: EditorTab) -> None:
        index = self.tabs.indexOf(tab)
        if index < 0:
            return
        name = _shown(tab.name)  # as the pane shows names
        tab.editor.setAccessibleName(tr("Text of {name}").format(name=name))
        for side in (QTabBar.ButtonPosition.RightSide, QTabBar.ButtonPosition.LeftSide):
            button = self.tabs.tabBar().tabButton(index, side)
            if button is not None:  # (the tab's x: it had no name a screen reader could say)
                button.setAccessibleName(tr("Close {name}").format(name=name))
                button.setToolTip(tr("Close {name}").format(name=name))
        title = (tr("{name} [read-only]").format(name=name) if tab.read_only else name) \
            + (" *" if tab.is_modified() else "")
        self.tabs.setTabText(index, title)
        if tab.untitled:
            tip = tr("{name} (not saved yet)").format(name=name)
        else:
            tip = f"{_shown(tab.path)} [{getattr(tab.backend, 'name', '')}]"
        self.tabs.setTabToolTip(index, tip)

    def _update_status(self) -> None:
        tab = self.current_tab()
        if tab is None:
            for label in (self.position_label, self.encoding_label, self.eol_label):
                label.setText("")
            return
        cursor = tab.editor.textCursor()
        self.position_label.setText(tr("Ln {line}, Col {col}").format(
            line=cursor.blockNumber() + 1, col=cursor.positionInBlock() + 1))
        self.encoding_label.setText(tab.document.encoding_name)
        self.eol_label.setText(tab.document.newline_name)
        self.language_combo.setCurrentText(tab.editor.language)
        # (only shown as it is: its toggled signal set the tab's preview again - a move of the cursor, a tab
        # chosen, made the preview of all of the text anew, 0.012 s of the turn and a parse on a worker)
        blocked = self.preview_action.blockSignals(True)
        try:
            self.preview_action.setChecked(tab.previewing)
        finally:
            self.preview_action.blockSignals(blocked)

    def _set_preview(self, on: bool) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.set_preview(on)

    def _language_chosen(self) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.editor.set_language(self.language_combo.currentText())
            self.language_combo.setCurrentText(tab.editor.language)

    # -- saving --------------------------------------------------------------------------

    def rebind_backend(self, old, new) -> int:
        """Tabs opened through the session *old* (dropped, then replaced by
        an automatic reconnect) save through *new* from now on - not the
        dead one, where every Save failed with "Not connected". How many."""
        moved = 0
        for tab in self._tabs():
            if tab.backend is old:
                tab.backend = new
                if getattr(tab.document, "backend", None) is old:
                    tab.document.backend = new
                moved += 1
        return moved

    def save_tab(self, tab: EditorTab) -> bool:
        if tab.read_only:
            self.statusBar().showMessage(tr("{name} is open read-only").format(name=tab.name), 4000)
            return False
        if self._still_going_in(tab):
            return False
        if tab.untitled:
            return self.save_as(tab)
        stamp = tab.editor.changes
        try:
            blocks = self._blocks_of(tab)  # the text, read here: the widget is the GUI thread's
        except OSError as exc:
            self.statusBar().showMessage(tr("{name} was not saved: {error}").format(name=tab.name, error=exc), 6000)
            return False
        if self._gone(tab):
            return False
        # What the user said yes to so far: each question is asked once, and
        # nothing is written before the last of them is answered.
        said = {"force": False, "ask_gone": True, "ask_read_only": True}
        questions = {
            "conflict": ("force", True, tr("File Changed"), tr(
                "{path} was changed since it was opened. Overwrite it with your version?")),
            "gone": ("ask_gone", False, tr("File Gone"), tr(
                "{path} is no longer there: it was deleted or moved since it was opened. "
                "Create it again?")),
            "read-only": ("ask_read_only", False, tr("Read-Only File"), tr(
                "{path} is marked read-only. Replace it anyway? It stays read-only.")),
        }
        try:
            while True:
                result = self._io(tab, lambda: tab.document.save(blocks, **said))
                if self._gone(tab):
                    # The window or tab went meanwhile: no question to ask.
                    return result == "saved"
                if result not in questions:
                    break
                option, value, title, text = questions[result]
                answer = QMessageBox.question(
                    self, title, as_written(text.format(path=tab.path)),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return False
                said[option] = value
        except UnicodeEncodeError as exc:
            QMessageBox.critical(self, tr("Save"), tr(
                "The text holds characters {encoding} cannot store; nothing was written. Choose "
                "another encoding (Format → Encoding).\n{error}").format(
                encoding=tab.document.encoding_name, error=exc))
            return False
        except Exception as exc:  # noqa: BLE001 - any failure is "not saved", never "saved"
            # (an OSError, or a library error of a backend: escaping, it
            # left Save-on-close accepted and the tab's edits were lost)
            log.warning("Saving %s failed", tab.path, exc_info=not isinstance(exc, OSError))
            if self._gone(tab):
                return False
            QMessageBox.critical(self, tr("Save"), tr("Cannot save {path}:\n{error}").format(
                path=tab.path, error=exc))
            return False
        self._mark_saved(tab, stamp)
        self._update_title(tab)
        self._update_status()
        self.statusBar().showMessage(tr("Saved {name}").format(name=tab.name), 3000)
        self.saved.emit(tab.backend, tab.path)
        return True

    def _read(self, tab: EditorTab, shape, between: str = "\u2029", whole: bool = True):
        """*shape(text)* of *tab*'s text as its blocks hold it (*between*
        two of them; a folded line whole - not *whole*: its mark, as in the
        document) - of a big text read a slice a
        turn, *shape* run off the GUI thread, the window painted meanwhile
        (ui.off_gui: keys and clicks wait): all of 20 MB read and split
        into its lines at once was a turn of 0.13 s. OSError when the text
        was edited all the while."""
        editor = tab.editor
        if not editor.big:
            editor.finish_now()
            raw = editor.document().toRawText()
            if whole and editor.has_folds:
                raw = editor.unfold_marks(raw)
            return shape(raw if between == "\u2029" else raw.replace("\u2029", between))
        import threading

        from axross_markdown._ax.ui.off_gui import run_off_gui

        box: dict = {}
        ready = threading.Event()
        editor.read_text(lambda text: (box.update(text=text), ready.set()), between, whole)

        def work():
            while not ready.wait(0.2):
                if sip.isdeleted(editor):
                    raise OSError("the tab was closed while its text was read")
            if box["text"] is None:
                raise OSError("the text was changed while it was read")
            return shape(box["text"])

        return run_off_gui(work)

    def _blocks_of(self, tab: EditorTab) -> list[str]:
        """*tab*'s lines as its file is to hold them (EditorTab.blocks(), a big text's off the GUI thread)."""
        return self._read(tab, lambda raw: raw.split("\u2029"))

    def _still_going_in(self, tab: EditorTab) -> bool:
        """Whether *tab*'s text is not all there yet (a file being put in, a
        paste, an undo in slices) - said in the status bar: a save now wrote
        a part of it."""
        if not (tab.loading or tab.editor.busy):
            return False
        self.statusBar().showMessage(
            tr("{name} is still being put in; save it in a moment.").format(name=tab.name), 4000)
        return True

    def save_as(self, tab: EditorTab | None = None) -> bool:
        """File > Save As…: *tab* (the current one) written to a file the
        user picks - on the local file system for a local or untitled tab,
        on the tab's own backend otherwise. An existing file asks before it
        is replaced; the tab then is the new file."""
        tab = tab if tab is not None else self.current_tab()
        if tab is None:
            return False
        if tab.read_only:
            self.statusBar().showMessage(tr("{name} is open read-only").format(name=tab.name), 4000)
            return False
        if self._still_going_in(tab):
            return False
        target = self._ask_save_path(tab)
        if target is None:
            return False
        backend, path = target
        if not tab.untitled and path == tab.path and self._same_backend(backend, tab.backend):
            return self.save_tab(tab)  # its own file: the conflict check of a plain save
        if self._tab_of(backend, path, besides=tab) is not None:
            QMessageBox.warning(self, tr("Save As"), tr(
                "{path} is open in another tab. Close that tab first, or save under another "
                "name.").format(path=path))
            return False
        def look() -> tuple[bool, bool]:
            there = backend.exists(path)
            return there, bool(there and backend.is_dir(path))

        try:
            exists, folder = self._io(tab, look, "Checking")
            if self._gone(tab):
                return False
        except OSError as exc:
            # Unknown is not "free": writing now could replace a file the
            # user was never asked about.
            QMessageBox.critical(self, tr("Save As"), tr(
                "Cannot check whether {path} already exists; nothing was written.\n"
                "{error}").format(path=path, error=exc))
            return False
        if folder:
            QMessageBox.warning(self, tr("Save As"), tr(
                "{path} is a folder. Choose a file name.").format(path=path))
            return False
        if exists and QMessageBox.question(
                self, tr("Save As"),
                as_written(tr("{path} already exists. Replace it?").format(path=path)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        stamp = tab.editor.changes
        try:
            blocks = self._blocks_of(tab)
        except OSError as exc:
            self.statusBar().showMessage(tr("{name} was not saved: {error}").format(name=tab.name, error=exc), 6000)
            return False
        if self._gone(tab):
            return False
        try:
            self._io(tab, lambda: tab.document.save_as(backend, path, blocks))
            if self._gone(tab):
                return True
        except UnicodeEncodeError as exc:
            QMessageBox.critical(self, tr("Save"), tr(
                "The text holds characters {encoding} cannot store; nothing was written. Choose "
                "another encoding (Format → Encoding).\n{error}").format(
                encoding=tab.document.encoding_name, error=exc))
            return False
        except OSError as exc:
            QMessageBox.critical(self, tr("Save"), tr("Cannot save {path}:\n{error}").format(
                path=path, error=exc))
            return False
        tab.backend, tab.path = backend, path
        # Before the language changes: highlighting anew counts as a change
        # of the document (its revision), not of the text.
        self._mark_saved(tab, stamp)
        # The language follows the new name, unless the name says nothing.
        language = language_for(posixpath.basename(path.replace("\\", "/")), "")
        if language != TEXT_ONLY:
            tab.editor.set_language(language)
        self._update_title(tab)
        self._update_status()
        self.statusBar().showMessage(tr("Saved {name}").format(name=tab.name), 3000)
        self.saved.emit(tab.backend, tab.path)
        return True

    def _ask_save_path(self, tab: EditorTab):
        """``(backend, path)`` to save *tab* as, or None (cancelled). A local
        or untitled tab: the local file dialog (it does not ask about
        overwriting - save_as() does, for every backend alike). A remote
        tab: a path on its backend; a relative one is below the tab's
        folder."""
        from axross_markdown._ax.core.local_fs import LocalFS

        if tab.untitled or self._is_local(tab.backend):
            start = tab.path or os.path.join(self._start_folder(), tab.name)
            path, _filter = QFileDialog.getSaveFileName(
                self, tr("Save As"), start, options=QFileDialog.Option.DontConfirmOverwrite)
            if not path:
                return None
            return (tab.backend if not tab.untitled else LocalFS()), path
        label = tr("Path on {backend}:").format(backend=getattr(tab.backend, "name", ""))
        text, ok = QInputDialog.getText(self, tr("Save As"), label, text=tab.path)
        path = text.strip() if ok else ""
        if not path:
            return None
        if not re.match(r"[/\\]|[A-Za-z]:[/\\]", path):
            path = tab.backend.join(tab.backend.parent(tab.path), path)
        return tab.backend, path

    @staticmethod
    def _mark_saved(tab: EditorTab, stamp: int) -> None:
        """The tab is unmodified - unless its text was edited since it was
        read for the save (*stamp*: the editor's count of edits then): a
        change that reached it while the file was being written is not in
        the file. By the editor's own count, not by the document's
        revision: highlighting anew counts as a revision too, and a save
        during it stayed "modified" (nor by reading the text again: all of
        20 MB read twice for a save)."""
        if tab.editor.changes == stamp:
            tab.editor.document().setModified(False)

    def _io(self, tab: EditorTab, fn, verb: str = "Writing"):
        """*fn()* - a read or write of *tab*'s file - off the GUI thread
        (ui.off_gui): the window keeps painting while a server answers,
        keys and clicks wait until the file is written. Save still
        answers True / False, which closing a tab depends on."""
        from axross_markdown._ax.ui.off_gui import run_off_gui

        def status(text: str) -> None:
            if sip.isdeleted(self):
                return
            if text:
                self.statusBar().showMessage(text)
            else:
                self.statusBar().clearMessage()

        texts = {"Reading": tr("Reading {name}…"), "Checking": tr("Checking {name}…")}
        text = texts.get(verb, tr("Writing {name}…")).format(name=tab.name)
        return run_off_gui(fn, text=text, status=status)

    def _gone(self, tab: EditorTab) -> bool:
        """After a wait (_io): the window or *tab* was deleted meanwhile.
        run_off_gui holds a close of the window until the wait is over;
        this is the guard for whatever else may delete them."""
        return sip.isdeleted(self) or sip.isdeleted(tab) or sip.isdeleted(tab.editor)

    def save_current(self) -> bool:
        tab = self.current_tab()
        return self.save_tab(tab) if tab is not None else False

    def save_all(self) -> bool:
        return all([self.save_tab(t) for t in self._tabs() if t.is_modified() and not t.read_only])

    def reload_current(self) -> None:
        tab = self.current_tab()
        if tab is None or tab.untitled:
            return  # an untitled tab has no file to read again
        if tab.is_modified() and QMessageBox.question(
                self, tr("Reload"),
                as_written(tr("Discard your changes to {name}?").format(name=tab.name)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            text = self._io(tab, tab.document.load, "Reading")
        except OSError as exc:
            if not self._gone(tab):
                QMessageBox.warning(self, tr("Reload"), str(exc))
            return
        if self._gone(tab):
            return
        tab.loading = True  # (a slice a turn, as it was opened)
        tab.editor.load_text(text, tab._text_loaded)  # noqa: SLF001 - the tab's own end of a load
        self._update_status()

    def _confirm_close(self, tab: EditorTab) -> bool:
        if not tab.is_modified():
            return True
        answer = QMessageBox.question(
            self, tr("Unsaved Changes"),
            as_written(tr("Save the changes to {name}?").format(name=tab.name)),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_tab(tab)
        return answer == QMessageBox.StandardButton.Discard

    def close_tab(self, index: int) -> bool:
        """Close the tab at *index* (asking for unsaved changes); the last
        tab takes the window with it - an empty editor window has nothing
        to show - unless a file is still being read for a tab. Close Tab in
        an empty window closes the window."""
        tab = self.tabs.widget(index)
        if tab is None and self.tabs.count() == 0:
            return self.close()
        if not isinstance(tab, EditorTab) or not self._confirm_close(tab):
            return False
        self.tabs.removeTab(index)
        tab.deleteLater()
        self._update_status()
        if self.tabs.count() == 0 and not self._loads:
            # Nothing left to ask about: closes at once. A file still being
            # read keeps the window - closing it would drop that read.
            self.close()
        return True

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt
        for tab in self._tabs():
            if not self._confirm_close(tab):
                event.ignore()
                return
        while self.tabs.count():
            widget = self.tabs.widget(0)
            self.tabs.removeTab(0)
            widget.deleteLater()
        for _backend, _path, job in self._loads:
            job.abandon()  # a read still running opens no tab later
        self._loads.clear()
        self._edit_wanted.clear()
        event.accept()

    # -- view and format -------------------------------------------------------------------

    def show_find(self, replace: bool = False) -> None:
        self.find_bar.show()
        for widget in self.find_bar.replace_widgets:
            widget.setVisible(replace)
        tab = self.current_tab()
        if tab is not None and tab.editor.textCursor().hasSelection():
            cursor = tab.editor.textCursor()
            # (a word or a phrase selected is what to find - not a page: all of 20 MB
            # selected went into the field, and held the window while it was laid out)
            if cursor.selectionEnd() - cursor.selectionStart() <= FIND_FROM_SELECTION_CHARS:
                self.find_bar.find_edit.setText(cursor.selectedText())
        self.find_bar.find_edit.setFocus()
        self.find_bar.find_edit.selectAll()

    def go_to_line(self, line: int) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        document = tab.editor.document()
        block = document.findBlockByNumber(max(0, min(line, document.blockCount()) - 1))
        cursor = QTextCursor(block)
        tab.editor.setTextCursor(cursor)
        tab.editor.centerCursor()
        self._update_status()

    def _ask_line(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        line, ok = QInputDialog.getInt(self, tr("Go to Line"), tr("Line:"),
                                       tab.editor.textCursor().blockNumber() + 1, 1,
                                       tab.editor.document().blockCount())
        if ok:
            self.go_to_line(line)

    def _set_wrap(self, on: bool) -> None:
        mode = QPlainTextEdit.LineWrapMode.WidgetWidth if on else QPlainTextEdit.LineWrapMode.NoWrap
        for tab in self._tabs():
            if not tab.long_line:  # unwrapped, its line holds the window
                tab.editor.setLineWrapMode(mode)

    def _zoom(self, steps: int) -> None:
        """Zoom In / Out / Actual Size (0): the tab's text and its preview."""
        tab = self.current_tab()
        if tab is not None:
            tab.zoom(steps)

    def set_newline(self, newline: str) -> None:
        tab = self.current_tab()
        if tab is None or tab.read_only:
            return
        tab.document.set_newline(newline)
        tab.mark_modified()
        self._update_status()

    def set_encoding(self, codec: str, *, bom: bool | None = None) -> None:
        tab = self.current_tab()
        if tab is None or tab.read_only:
            return
        tab.document.set_encoding(codec, bom=bom)
        tab.mark_modified()
        self._update_status()

