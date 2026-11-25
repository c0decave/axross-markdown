"""The editor window's text widget: a big text goes in, out and back a slice
an event-loop turn, and a line too long to lay out is folded into one mark.

What Qt does in one go holds the window for as long as it takes: a paste of
20 MB was one turn of 4 s, its undo 0.9 s, its redo 1.5 s; a file's text
set at once 0.1 to 0.3 s from 1 MB on. :class:`BigTextEditor` does these in
steps, each a few milliseconds, between which the window answers:

* :meth:`BigTextEditor.load_text` - a file's text (no undo step);
* :meth:`BigTextEditor.replace_range` - a paste, a big selection removed
  or typed over, Replace All of a whole text;
* :meth:`BigTextEditor.apply_edits` - many small replacements;
* undo and redo of what one of them did (its steps are undo steps of Qt's,
  remembered as one group).

While one runs the widget takes no typing (:attr:`BigTextEditor.busy`).

A line of a text document is one block, and Qt lays a block out whole: a
line of 5,000,000 characters pasted held the window 1.5 s, and so did every
key after it. Such a line (longer than :data:`FOLD_LINE_CHARS`) is not put
into the document: one character (U+FFFC, drawn as a mark that says how
long the line is) stands for it, its text kept beside the document
(:meth:`BigTextEditor.blocks` and :meth:`BigTextEditor.plain_text` give it
back, so does a copy to the clipboard). The mark is an ordinary character to
undo, redo, cut and paste; what it stands for is not searched or replaced
by Find.
"""

from __future__ import annotations

import logging
import re
import time

from PyQt6.QtCore import QObject, QSizeF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QFontMetricsF,
    QKeySequence,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
    QTextObjectInterface,
)
from PyQt6.QtWidgets import QPlainTextEdit

from axross_markdown._ax.core.i18n import format_count, tr
from axross_markdown._ax.ui.code_editor import MAX_HIGHLIGHT_CHARS, CodeEditor

log = logging.getLogger(__name__)

#: A line longer than this is folded into one mark: laid out, 200,000
#: characters take 0.04 s - at every key typed in the line.
FOLD_LINE_CHARS = 200_000
#: Characters put into (or taken out of) the document in one step - up to a
#: line more: a step ends before a line break.
SLICE_CHARS = 48_000
#: (a step's size follows what the last took: Pace)
MIN_SLICE_CHARS = 2_000
MAX_SLICE_CHARS = 96_000
#: The GUI thread's time a step should take.
STEP_SECONDS = 0.006
#: The GUI thread's time one turn of a job may take before it lets the
#: event loop go on (its last step may end a little after).
TURN_SECONDS = 0.015
#: A selection of more characters than this is removed in steps.
BIG_SELECTION = 200_000
#: Characters read from the document in one step (read_text), and how often
#: a reading begins again because the text was edited meanwhile.
READ_CHARS = 400_000
READ_TRIES = 4
#: A document of more characters than this is read a slice a turn where its
#: caller can wait (a save, a search, the preview): all of 20 MB read in one
#: call took 0.085 s, split into its lines 0.13 s.
BIG_READ_CHARS = 3_000_000
#: The character that stands for a folded line.
FOLD = "\ufffc"

#: What ends a block of the text widget (ui.editor_window._BLOCK_BREAKS).
_BREAKS = re.compile("\r\n|\r|\n|\u2029|\ufdd0|\ufdd1")
_BREAK_CHARS = "\n\r\u2029\ufdd0\ufdd1"
_OBJECT = QTextFormat.ObjectTypes.UserObject.value + 0x2A
_FOLD_ID = QTextFormat.Property.UserProperty.value + 0x2A
_PLAIN = QTextCharFormat()


def long_lines(text: str, limit: int) -> list[tuple[int, int]]:
    """(start, end) of every line of *text* longer than *limit*, in order -
    without a look at each line: a line that long holds a whole window of
    ``limit // 2`` characters at a multiple of that, so only windows without
    a line break are looked at closer."""
    size = len(text)
    if size <= limit:
        return []
    half = max(1, limit // 2)
    search = _BREAKS.search
    found = []
    floor = 0  # (lines that begin before it are judged)
    at = 0
    while at + half <= size:
        if at < floor:
            at += ((floor - at + half - 1) // half) * half
            continue
        if search(text, at, at + half) is None:
            start = max(floor, max(text.rfind(char, floor, at) for char in _BREAK_CHARS) + 1)
            ends = search(text, at + half)
            end = ends.start() if ends else size
            if end - start > limit:
                found.append((start, end))
            if ends is None:
                break
            floor = ends.end()
        at += half
    return found


def pieces(text: str, limit: int | None, pace: "Pace | None" = None):
    """*text* as the steps it is put into a document in, one after the
    other: ``("text", start, end)`` - about ``pace.chars`` characters (read
    anew for each step), on to the next line break (a step never ends
    inside a line, so each begins a new block and Qt lays none of them out
    before it is seen; nor between CR and LF) - and ``("fold", start,
    end)``, a line longer than *limit* (None: no line is)."""
    pace = pace or Pace()
    size = len(text)
    at = 0
    for start, end in (long_lines(text, limit) if limit else []) + [(size, size)]:
        while at < start:
            cut = min(start, at + max(1, pace.chars))
            if cut < start:
                if text[cut] == "\n" and text[cut - 1] == "\r":
                    cut -= 1
                ends = _BREAKS.search(text, cut, start)
                cut = ends.start() if ends else start
                if cut == at:  # (a break right at its start: with the next line's text)
                    more = _BREAKS.search(text, ends.end(), start)
                    cut = more.start() if more else start
            yield "text", at, cut
            at = cut
        if end > start:
            yield "fold", start, end
            at = end


class Pace:
    """How many characters a step takes: as many as take STEP_SECONDS of
    the GUI thread - a text of short lines costs several times what one of
    long lines does (each block has its price), so the count follows what
    the steps before took."""

    def __init__(self, chars: int = SLICE_CHARS) -> None:
        self.chars = chars
        self._began = 0.0

    def begin(self) -> None:
        self._began = time.thread_time()

    def end(self, done: int) -> None:
        """A step of *done* characters is over."""
        took = time.thread_time() - self._began
        if done < 1000:
            return  # (too short to tell)
        fit = int(done * STEP_SECONDS / max(took, 1e-4))
        # (half way to what would fit, at most doubled: one step's time is a noisy measure)
        self.chars = max(MIN_SLICE_CHARS, min(MAX_SLICE_CHARS, 2 * self.chars, (self.chars + fit) // 2))


class _FoldMark(QObject, QTextObjectInterface):
    """Draws the character that stands for a folded line: a box with the
    line's length in it."""

    def __init__(self, editor: "BigTextEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def _label(self, fmt) -> str:
        chars = len(self._editor.fold_text(fmt))
        return tr("{chars} characters, folded").format(chars=format_count(chars))

    def intrinsicSize(self, document, _position, fmt) -> QSizeF:  # noqa: N802 - Qt
        metrics = QFontMetricsF(document.defaultFont())
        return QSizeF(metrics.horizontalAdvance(self._label(fmt)) + 14, metrics.ascent())

    def drawObject(self, painter, rect, document, _position, fmt) -> None:  # noqa: N802 - Qt
        palette = self._editor.palette()
        painter.save()
        try:
            colour = palette.highlight().color()
            colour.setAlpha(60)
            painter.setPen(palette.placeholderText().color())
            painter.setBrush(colour)
            painter.drawRoundedRect(rect.adjusted(1, 0, -1, 0), 3, 3)
            painter.setPen(palette.text().color())
            painter.setFont(document.defaultFont())
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._label(fmt))
        finally:
            painter.restore()


class _Read(QObject):
    """One reading of a document's text, a slice an event-loop turn
    (BigTextEditor.read_text)."""

    def __init__(self, editor: "BigTextEditor", done, between: str, whole: bool) -> None:
        super().__init__(editor)
        self._editor, self._done, self._between, self._whole = editor, done, between, whole
        self._tries = READ_TRIES
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._step)
        self._begin()
        self._timer.start(0)

    def _begin(self) -> None:
        self._seen = self._editor.changes
        self._parts: list[str] = []
        self._at = 0

    def _finish(self, text: str | None) -> None:
        done, self._done = self._done, None
        self.deleteLater()
        if done is not None:
            done(text)

    def _step(self) -> None:
        editor = self._editor
        if editor.busy:  # (a text going in: read when it is all there)
            self._begin()
            self._timer.start(30)
            return
        if editor.changes != self._seen:  # (typed in meanwhile: from the start, a few times)
            self._tries -= 1
            if self._tries <= 0:
                self._finish(None)
                return
            self._begin()
        document = editor.document()
        end = document.characterCount() - 1
        cursor = QTextCursor(document)
        began = time.thread_time()
        first = True
        while self._at < end and (first or time.thread_time() - began < TURN_SECONDS):
            first = False
            cut = min(end, self._at + READ_CHARS)
            if cut < end:
                # (at a block's start: never inside a character of two code units)
                block = document.findBlock(cut)
                cut = block.position() if block.position() > self._at \
                    else min(end, block.position() + block.length())
            cursor.setPosition(self._at)
            cursor.setPosition(cut, QTextCursor.MoveMode.KeepAnchor)
            part = cursor.selectedText()
            if self._whole and editor.has_folds and FOLD in part:
                part = editor._unfolded(part, self._at, cut)  # noqa: SLF001 - the editor's own reading
            self._parts.append(part if self._between == "\u2029" else part.replace("\u2029", self._between))
            self._at = cut
        if self._at < end:
            self._timer.start(0)
            return
        self._finish("".join(self._parts))


class BigTextEditor(CodeEditor):
    #: A job (a text loaded, pasted, undone ... in steps) began (True) or is over.
    busy_changed = pyqtSignal(bool)
    #: A line was folded, or the text was set anew (its folded lines may differ).
    folds_changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        #: Lines longer than this are folded; None: every line as it is
        #: (Show Anyway - the window is held for as long as Qt lays it out).
        self.fold_limit: int | None = FOLD_LINE_CHARS
        self._folds: dict[int, str] = {}
        self._fold_ids = 0
        self._mark = _FoldMark(self)
        self.document().documentLayout().registerHandler(_OBJECT, self._mark)
        self._job = None
        self._job_done = None
        self._held_read_only = False
        self._turns = QTimer(self)
        self._turns.setSingleShot(True)
        self._turns.setInterval(0)
        self._turns.timeout.connect(self._turn)
        #: What a job did, as undo positions (QTextDocument.availableUndoSteps
        #: before and after): undone and redone as one, in steps.
        self._groups: list[tuple[int, int]] = []
        self._undo_seen = 0
        #: The undo position before the user's last edit (a line it made
        #: too long is folded: undone with it).
        self._undo_before = 0
        self._stepping = False
        self._folding = False
        #: How often the text was edited (its colours painted anew is no edit).
        self.changes = 0
        self._grown: list[QTextCursor] = []
        self._grown_timer = QTimer(self)
        self._grown_timer.setSingleShot(True)
        self._grown_timer.setInterval(0)
        self._grown_timer.timeout.connect(self._fold_grown)
        self.document().undoCommandAdded.connect(self._undo_added)
        self.document().contentsChange.connect(self._content_changed)

    # -- jobs --------------------------------------------------------------------------------

    @property
    def busy(self) -> bool:
        """A job is under way: the text is not all there (or not all gone) yet."""
        return self._job is not None

    def setReadOnly(self, read_only: bool) -> None:  # noqa: N802 - Qt
        if self.busy:
            self._held_read_only = read_only  # (as asked, once the job is over)
            return
        super().setReadOnly(read_only)

    def _start(self, job, done=None) -> None:
        self.finish_now()
        self._job, self._job_done = job, done
        self._held_read_only = self.isReadOnly()
        QPlainTextEdit.setReadOnly(self, True)  # (no key, paste or drop meanwhile; the steps use cursors of their own)
        highlighter = self.highlighter
        self._was_loading, highlighter.loading = highlighter.loading, True  # (lexed once, at the end)
        self.busy_changed.emit(True)
        self._turn()

    def _turn(self, to_the_end: bool = False) -> None:
        job = self._job
        if job is None:
            return
        began = time.thread_time()
        try:
            while to_the_end or time.thread_time() - began < TURN_SECONDS:
                next(job)
        except StopIteration:
            self._over()
            return
        except Exception:  # noqa: BLE001 - a step that failed ends the job, the widget usable again
            log.exception("A step of the editor's job failed")
            self._over()
            return
        self._turns.start()

    def _over(self) -> None:
        done, self._job, self._job_done = self._job_done, None, None
        self._turns.stop()
        QPlainTextEdit.setReadOnly(self, self._held_read_only)
        highlighter = self.highlighter
        highlighter.loading = self._was_loading
        highlighter.edited_in_bulk()
        self._undo_seen = self.document().availableUndoSteps()
        self.busy_changed.emit(False)
        if done is not None:
            done()

    def finish_now(self) -> None:
        """The job under way done to its end at once (a caller that needs the
        whole text now: a test, a text set while another goes in)."""
        while self._job is not None:
            self._turn(to_the_end=True)

    # -- folded lines ------------------------------------------------------------------------

    def fold_text(self, fmt) -> str:
        """The line the mark with the character format *fmt* stands for."""
        return self._folds.get(fmt.property(_FOLD_ID), "")

    def _fold_format(self, text: str) -> QTextCharFormat:
        self._fold_ids += 1
        self._folds[self._fold_ids] = text
        fmt = QTextCharFormat()
        fmt.setObjectType(_OBJECT)
        fmt.setProperty(_FOLD_ID, self._fold_ids)
        return fmt

    def _fold_texts(self, start: int, end: int, same: bool, text: str) -> list[str]:
        """What each U+FFFC between the positions *start* and *end* stands for
        (itself, when it is a character of the text), in order. *text*: the
        document's text from *start* on; *same*: its indexes are positions."""
        document = self.document()
        out = []

        def of(position: int) -> str:
            probe = QTextCursor(document)
            probe.setPosition(position + 1)
            fmt = probe.charFormat()  # (of the character before the cursor)
            return self._folds.get(fmt.property(_FOLD_ID), FOLD) if fmt.objectType() == _OBJECT else FOLD

        if same:
            index = text.find(FOLD)
            while index >= 0 and start + index < end:
                out.append(of(start + index))
                index = text.find(FOLD, index + 1)
            return out
        found = document.find(FOLD, start)
        while not found.isNull() and found.selectionEnd() <= end:
            out.append(of(found.selectionStart()))
            found = document.find(FOLD, found.selectionEnd())
        return out

    def _unfolded(self, text: str, start: int, end: int) -> str:
        """*text* (the document's between *start* and *end*) with every mark
        replaced by the line it stands for."""
        parts = text.split(FOLD)
        texts = self._fold_texts(start, end, end - start == len(text), text)
        if len(texts) != len(parts) - 1:  # pragma: no cover - the document changed under the count
            log.warning("Folded lines could not be counted: %d marks, %d found", len(parts) - 1, len(texts))
            return text
        out = [parts[0]]
        for folded, part in zip(texts, parts[1:]):
            out.append(folded)
            out.append(part)
        return "".join(out)

    def _whole(self, text: str) -> str:
        if self._folds and FOLD in text:
            return self._unfolded(text, 0, self.document().characterCount() - 1)
        return text

    @property
    def has_folds(self) -> bool:
        return bool(self._folds)

    @property
    def big(self) -> bool:
        """The text is long enough that reading all of it at once holds the window."""
        return self.document().characterCount() > BIG_READ_CHARS

    def read_text(self, done, between: str = "\u2029", whole: bool = True) -> None:
        """The document's text as its blocks hold it - *between* two blocks
        (U+2029 as Qt has it; "\n" for a text to show or search), a folded
        line whole (not *whole*: its mark, one character as in the document) -
        read a slice a turn of the event loop: *done(text)*, or *done(None)*
        when it was edited again and again meanwhile. A job under way is
        waited for."""
        _Read(self, done, between, whole)

    def unfold_marks(self, new: str) -> str | None:
        """*new* - a text made from raw_text(), its marks kept in their order -
        with each mark replaced by the line it stands for; None when it has
        not as many marks as the document."""
        if not (self._folds and FOLD in new):
            return new
        raw = self.document().toRawText()
        texts = self._fold_texts(0, self.document().characterCount() - 1,
                                 len(raw) == self.document().characterCount() - 1, raw)
        parts = new.split(FOLD)
        if len(parts) - 1 != len(texts):
            return None
        out = [parts[0]]
        for folded, part in zip(texts, parts[1:]):
            out.append(folded)
            out.append(part)
        return "".join(out)

    def blocks(self) -> list[str]:
        """The text's lines as the file holds them: each block's text (no
        character changed: toPlainText() rewrites no-break spaces and U+2028),
        a folded line whole."""
        return self._whole(self.document().toRawText()).split("\u2029")

    def plain_text(self) -> str:
        """toPlainText() with the folded lines whole (the preview's text)."""
        return self._whole(self.toPlainText())

    def raw_text(self) -> str:
        """The text as its blocks hold it, a line feed between them; a folded
        line is its mark (one character, as in the document: indexes are
        positions but for characters outside the BMP)."""
        return self.document().toRawText().replace("\u2029", "\n")

    def folded_lines(self) -> list[tuple[int, int]]:
        """(line number from 1, characters) of each folded line, in order."""
        if not self._folds:
            return []
        document = self.document()
        out = []
        found = document.find(FOLD, 0)
        while not found.isNull():
            fmt = found.charFormat()
            if fmt.objectType() == _OBJECT:
                out.append((found.blockNumber() + 1, len(self.fold_text(fmt))))
            found = document.find(FOLD, found.selectionEnd())
        return out

    def _content_changed(self, position: int, _removed: int, added: int) -> None:
        """(the document changed) a line grown past the limit by typing or by
        small pastes is folded as soon as the event loop goes on."""
        self.changes += 1
        if self.busy or self._stepping or self.fold_limit is None:
            return
        document = self.document()
        for at in (position, position + added):
            block = document.findBlock(at)
            if block.isValid() and block.length() - 1 > self.fold_limit:
                self._grown.append(QTextCursor(block))
                self._grown_timer.start()

    def _fold_grown(self) -> None:
        grown, self._grown = self._grown, []
        if self.busy or self.fold_limit is None:
            return
        before = self._undo_before
        self._folding = True
        try:
            for cursor in grown:
                block = cursor.block()
                if block.isValid() and block.length() - 1 > self.fold_limit:
                    self._fold_block(block)
        finally:
            self._folding = False
        # (the edit and the fold it led to: one step to undo and to redo)
        self._group(min(before, self.document().availableUndoSteps()))

    def _fold_block(self, block) -> None:
        """The line of *block* folded: its text (marks in it whole) kept
        beside the document, one mark in its place."""
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        text = cursor.selectedText()
        if self._folds and FOLD in text:
            text = self._unfolded(text, cursor.selectionStart(), cursor.selectionEnd())
        here = self.textCursor().block() == block
        cursor.beginEditBlock()
        cursor.insertText(FOLD, self._fold_format(text))
        cursor.endEditBlock()
        if here:
            self.setTextCursor(cursor)
        self.folds_changed.emit()

    def _fold_at(self, *positions: int) -> None:
        """(a job's end) the lines at *positions* folded when they are too long."""
        if self.fold_limit is None:
            return
        document = self.document()
        seen = set()
        for position in positions:
            block = document.findBlock(position)
            if block.isValid() and block.blockNumber() not in seen and block.length() - 1 > self.fold_limit:
                seen.add(block.blockNumber())
                self._fold_block(block)

    # -- a text set ---------------------------------------------------------------------------

    def setPlainText(self, text: str) -> None:  # noqa: N802 - Qt
        """The text set at once (the caller has it at once: a small text, a
        test); load_text() sets a big one without holding the window."""
        self.finish_now()
        if self.fold_limit is not None and long_lines(text, self.fold_limit):
            self.load_text(text)
            self.finish_now()
            return
        self._folds, self._groups, self._grown = {}, [], []
        super().setPlainText(text)
        self._undo_seen = 0
        self.folds_changed.emit()

    def load_text(self, text: str, done=None) -> None:
        """*text* as the widget's text, a slice a turn: no undo step, the
        document unmodified at its end; *done()* then."""
        self.finish_now()
        highlighter = self.highlighter
        if highlighter.document() is None or len(text) > MAX_HIGHLIGHT_CHARS or highlighter.gave_up:
            highlighter.detach()  # (above the cap, or no language: Qt paints no line)
        highlighter.gave_up = False
        highlighter.forget()
        document = self.document()
        document.setUndoRedoEnabled(False)
        self._folds, self._groups, self._grown = {}, [], []
        self._start(self._load(text), self._after_load(done))

    def _load(self, text: str):
        document = self.document()
        cursor = QTextCursor(document)
        yield from self._remove(cursor, 0, document.characterCount() - 1)  # (the text it had: Reload)
        first = True
        for step in self._insert(cursor, text):
            if first:  # (the widget's cursor stays at the start: at the end it followed every step)
                first = False
                home = self.textCursor()
                home.setPosition(0)
                self.setTextCursor(home)
            yield step

    def _after_load(self, done):
        def after() -> None:  # (also when a step failed: the widget is usable, with what went in)
            document = self.document()
            document.setUndoRedoEnabled(True)
            document.setModified(False)
            self._undo_seen = 0
            self.folds_changed.emit()
            if done is not None:
                done()

        return after

    def _remove(self, cursor: QTextCursor, start: int, end: int):
        """(a job's steps) the text between *start* and *end* taken out from
        its end, each step one undo step."""
        pace = Pace()
        while end > start:
            cut = max(start, end - pace.chars)
            pace.begin()
            cursor.setPosition(cut)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.beginEditBlock()
            cursor.removeSelectedText()
            cursor.endEditBlock()
            pace.end(end - cut)
            end = cut
            yield None

    def _insert(self, cursor: QTextCursor, text: str):
        """(a job's steps) *text* put in at *cursor*, each step one undo step."""
        pace = Pace()
        for kind, start, end in pieces(text, self.fold_limit, pace):
            pace.begin()
            cursor.beginEditBlock()
            if kind == "fold":
                cursor.insertText(FOLD, self._fold_format(text[start:end]))
            else:
                cursor.insertText(text[start:end], _PLAIN)
            cursor.endEditBlock()
            if kind == "text":
                pace.end(end - start)
            yield None

    # -- edits in steps -----------------------------------------------------------------------

    def replace_range(self, start: int, end: int, text: str, done=None) -> None:
        """The text between the positions *start* and *end* replaced by
        *text*, in steps, the cursor after it at the end; one group to undo."""
        if self.busy:
            return
        self._start(self._replace(start, end, text), done)

    def _replace(self, start: int, end: int, text: str):
        document = self.document()
        before = document.availableUndoSteps()
        cursor = QTextCursor(document)
        yield from self._remove(cursor, start, end)
        cursor.setPosition(start)
        yield from self._insert(cursor, text)
        self._fold_at(start, cursor.position())
        self._group(before)
        cursor.setPosition(min(cursor.position(), document.characterCount() - 1))
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def replace_selection(self, text: str, done=None) -> None:
        """The selection replaced by *text* (none: *text* put in at the cursor)."""
        cursor = self.textCursor()
        self.replace_range(cursor.selectionStart(), cursor.selectionEnd(), text, done)

    def apply_edits(self, edits: list[tuple[int, int, str]], done=None) -> None:
        """*edits* - (start, end, text): the positions *start* to *end* become
        *text*; in ascending order, none overlapping - made from the last to
        the first (the positions before it stay), as many a turn as fit; one
        group to undo."""
        if self.busy:
            return
        self._start(self._edit(edits), done)

    def _edit(self, edits):
        document = self.document()
        before = document.availableUndoSteps()
        cursor = QTextCursor(document)
        index = len(edits) - 1
        while index >= 0:
            began = time.thread_time()
            cursor.beginEditBlock()
            while index >= 0 and time.thread_time() - began < TURN_SECONDS / 2:
                start, end, text = edits[index]
                cursor.setPosition(start)
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                cursor.insertText(text, _PLAIN)
                index -= 1
            cursor.endEditBlock()
            yield None
        self._group(before)

    def _big_selection(self) -> bool:
        cursor = self.textCursor()
        return cursor.selectionEnd() - cursor.selectionStart() > BIG_SELECTION

    def insertFromMimeData(self, source) -> None:  # noqa: N802 - Qt
        """A paste or a drop: a big text (or over a big selection) in steps."""
        if self.busy or self.isReadOnly():
            return
        if not source.hasText():
            super().insertFromMimeData(source)
            return
        text = source.text()
        if len(text) <= SLICE_CHARS and not self._big_selection():
            super().insertFromMimeData(source)  # (as Qt does it; a line grown too long is folded after)
            return
        self.replace_selection(text)

    def createMimeDataFromSelection(self):  # noqa: N802 - Qt
        """The selection for the clipboard - a folded line in it whole."""
        data = super().createMimeDataFromSelection()
        if self._folds and data is not None and data.hasText():
            text = data.text()
            if FOLD in text:
                cursor = self.textCursor()
                data.setText(self._unfolded(text, cursor.selectionStart(), cursor.selectionEnd()))
        return data

    def cut(self) -> None:
        if self.busy or self.isReadOnly():
            return
        if not self._big_selection():
            super().cut()
            return
        self.copy()
        self.replace_selection("")

    def delete_selection(self) -> None:
        if self.busy or self.isReadOnly():
            return
        if self._big_selection():
            self.replace_selection("")
        else:
            self.textCursor().removeSelectedText()

    # -- undo and redo -------------------------------------------------------------------------

    def _group(self, before: int) -> None:
        """What the job did since the undo position *before* is one group."""
        after = self.document().availableUndoSteps()
        self._groups = [group for group in self._groups if group[1] <= before]
        if after > before:
            self._groups.append((before, after))
        self._undo_seen = after

    def _undo_added(self) -> None:
        """(an edit of the user's) the groups it made impossible to redo are forgotten."""
        if self.busy or self._folding:
            return
        seen = self._undo_seen
        self._groups = [group for group in self._groups if group[1] <= seen]
        self._undo_before = seen
        self._undo_seen = self.document().availableUndoSteps()

    def _step(self, call) -> None:
        self._stepping = True
        try:
            call()
        finally:
            self._stepping = False
            self._undo_seen = self.document().availableUndoSteps()

    def undo(self) -> None:
        """Undo: a job's group in steps (the paste of 20 MB undone at once
        held the window 0.9 s), anything else as Qt does it."""
        if self.busy or self.isReadOnly():
            return
        document = self.document()
        at = document.availableUndoSteps()
        group = next((g for g in self._groups if g[1] == at), None)
        if group is None:
            self._step(super().undo)
            return
        self._start(self._walk(group[0], back=True))

    def redo(self) -> None:
        if self.busy or self.isReadOnly():
            return
        document = self.document()
        at = document.availableUndoSteps()
        group = next((g for g in self._groups if g[0] == at), None)
        if group is None or not document.isRedoAvailable():
            self._step(super().redo)
            return
        self._start(self._walk(group[1], back=False))

    def _walk(self, goal: int, back: bool):
        """(a job's steps) undo down to the undo position *goal*, or redo up to it."""
        document = self.document()
        cursor = QTextCursor(document)
        moved = False
        while True:
            at = document.availableUndoSteps()
            if (at <= goal) if back else (at >= goal):
                break
            if not (document.isUndoAvailable() if back else document.isRedoAvailable()):
                break
            self._stepping = True
            try:
                if back:
                    document.undo(cursor)
                else:
                    document.redo(cursor)
            finally:
                self._stepping = False
            if document.availableUndoSteps() == at:
                break  # (nothing moved: no way on)
            moved = True
            yield None
        if moved and not cursor.isNull():
            cursor.clearSelection()
            self.setTextCursor(cursor)
            self.ensureCursorVisible()

    # -- keys and the menu ---------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt
        if self.busy:
            event.accept()  # (a text going in: no key changes it meanwhile)
            return
        if self.isReadOnly():
            super().keyPressEvent(event)
            return
        if event.matches(QKeySequence.StandardKey.Undo):
            self.undo()
            return
        if event.matches(QKeySequence.StandardKey.Redo):
            self.redo()
            return
        if self._big_selection():
            # (a big selection typed over, cut or deleted: taken out in steps)
            if event.matches(QKeySequence.StandardKey.Cut):
                self.cut()
                return
            key = event.key()
            modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                self.replace_selection("")
                return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.replace_selection("\n")
                return
            text = event.text()
            typed = bool(text) and text.isprintable() and (
                not modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
                or bool(modifiers & Qt.KeyboardModifier.AltModifier))
            if typed:
                self.replace_selection(text)
                return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt
        """The standard menu - its Undo, Redo, Cut and Delete this widget's
        own (Qt's undo one step of a group, and take a big selection out at once)."""
        menu = self.createStandardContextMenu()
        own = {"edit-undo": self.undo, "edit-redo": self.redo, "edit-cut": self.cut,
               "edit-delete": self.delete_selection}
        for action in menu.actions():
            slot = own.get(action.objectName())
            if slot is not None:
                try:
                    action.triggered.disconnect()
                except TypeError:  # (nothing connected)
                    pass
                action.triggered.connect(lambda _checked=False, call=slot: call())
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(event.globalPos())
