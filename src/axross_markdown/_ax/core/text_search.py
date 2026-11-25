"""The editor's find and replace over a text, in bounded pieces.

Pure Python, no Qt. Two callers: the editor's window for what the user
typed as it is (a literal needle: the text is searched a window at a time
on a worker thread - one call of ``re`` holds Python's lock for all of it,
and a search of 5 MB in one call held the window 0.4 s), and the lexing
child (core.lex_worker) for a regular expression of the user's - a pattern
that backtracks without end can only be stopped by ending its process.

A match that is empty, or holds the mark of a folded line
(ui.editor_text.FOLD - one character that stands for a line kept beside the
document), is none: replacing it would drop the line.
"""

from __future__ import annotations

import re

#: Characters searched in one call of ``re`` (a literal needle).
WINDOW = 1 << 17
#: Matches nearer than this are replaced as one piece of the text (each
#: piece is one edit of the document: thousands of small ones cost more
#: than a few longer ones).
JOIN_GAP = 96
#: A piece of joined replacements grows to about this many characters.
PIECE_CHARS = 32_000
FOLD = "\ufffc"


def compiled(source: str, *, regex: bool, case: bool, whole_word: bool) -> re.Pattern:
    """The pattern of what the find bar holds (re.error for a bad one).
    MULTILINE: ``^`` and ``$`` are each line's start and end."""
    if not regex:
        source = re.escape(source)
    if whole_word:
        source = rf"\b(?:{source})\b"
    return re.compile(source, re.MULTILINE | (0 if case else re.IGNORECASE))


def _counts(text: str, match, folds: bool) -> bool:
    return match.end() > match.start() and not (folds and text.find(FOLD, match.start(), match.end()) >= 0)


def _windows(pattern, text: str, begin: int, end: int, width: int | None):
    """The matches of *pattern* that begin in ``[begin, end)``, in order.
    *width* (a literal needle's length): searched a window at a time, each
    with room behind it for a match that begins at its end and for the
    character after it (a word's end is judged with it); None: one call."""
    if width is None:
        for match in pattern.finditer(text, begin):
            if match.start() >= end:
                return
            yield match
        return
    size = len(text)
    at = begin
    while at < end:
        stop = min(end, at + WINDOW)
        last = at
        for match in pattern.finditer(text, at, min(size, stop + width + 1)):
            if match.start() >= stop:
                break
            last = match.end()
            yield match
        at = max(stop, last)


def find_next(pattern, text: str, start: int, width: int | None = None) -> tuple[int, int] | None:
    """The first match at or after *start* - else the first of the text."""
    folds = FOLD in text
    for begin, end in ((start, len(text)), (0, min(len(text), start))):
        for match in _windows(pattern, text, begin, end, width):
            if _counts(text, match, folds):
                return match.start(), match.end()
    return None


def find_previous(pattern, text: str, start: int, width: int | None = None) -> tuple[int, int] | None:
    """The last match that ends at or before *start* - else the last of the text."""
    folds = FOLD in text
    size = len(text)
    if width is None:
        best = last = None
        for match in pattern.finditer(text):
            if not _counts(text, match, folds):
                continue
            last = match
            if match.end() <= start:
                best = match
        found = best or last
        return (found.start(), found.end()) if found else None
    for high, low, limit in ((start, 0, start), (size, max(0, start - width), size)):
        top = high
        while top > low:
            bottom = max(low, top - WINDOW)
            best = None
            for match in _windows(pattern, text, bottom, top, width):
                if match.end() <= limit and _counts(text, match, folds):
                    best = match
            if best is not None:
                return best.start(), best.end()
            top = bottom
    return None


def replacements(pattern, text: str, template: str | None, literal: str | None = None,
                 width: int | None = None) -> tuple[list[tuple[int, int, str]], int]:
    """Replace All as pieces of *text* to rewrite: ``([(start, end, new
    text)], matches)`` in order, none overlapping - neighbouring matches
    joined into one piece. *template*: ``re``'s replacement template;
    *literal*: the replacement as it is (then *template* is not read).
    re.error for a bad template."""
    folds = FOLD in text
    pieces: list[tuple[int, int, str]] = []
    count = 0
    start = end = -1
    parts: list[str] = []
    plain = literal if literal is not None else (template if "\\" not in (template or "") else None)
    for match in _windows(pattern, text, 0, len(text), width):
        if not _counts(text, match, folds):
            continue
        new = plain if plain is not None else match.expand(template)
        count += 1
        if start >= 0 and match.start() - end < JOIN_GAP and end - start < PIECE_CHARS \
                and not (folds and text.find(FOLD, end, match.start()) >= 0):
            parts.append(text[end:match.start()])
            parts.append(new)
        else:
            if start >= 0:
                pieces.append((start, end, "".join(parts)))
            start, parts = match.start(), [new]
        end = match.end()
    if start >= 0:
        pieces.append((start, end, "".join(parts)))
    return pieces, count


def replaced(text: str, pieces: list[tuple[int, int, str]]) -> str:
    """*text* with *pieces* (replacements()) put in."""
    out = []
    at = 0
    for start, end, new in pieces:
        out.append(text[at:start])
        out.append(new)
        at = end
    out.append(text[at:])
    return "".join(out)


def replace_one(pattern, selected: str, template: str | None, literal: str | None = None) -> str | None:
    """What *selected* becomes when all of it is one match - else None."""
    match = pattern.fullmatch(selected)
    if match is None or FOLD in selected:
        return None
    return literal if literal is not None else match.expand(template)


def answer(request: dict) -> dict:
    """(the child) one request of the editor's find bar answered: ``op``
    "next", "previous", "all" or "one" on ``text`` with the pattern
    ``source`` (``case``, ``whole_word``; always a regular expression
    here)."""
    try:
        pattern = compiled(str(request.get("source", "")), regex=True, case=bool(request.get("case")),
                           whole_word=bool(request.get("whole_word")))
    except re.error as exc:
        return {"error": "pattern", "text": str(exc)}
    text = str(request.get("text", ""))
    op = request.get("op")
    try:
        if op == "next":
            return {"span": find_next(pattern, text, int(request.get("start", 0)))}
        if op == "previous":
            return {"span": find_previous(pattern, text, int(request.get("start", 0)))}
        if op == "all":
            pieces, count = replacements(pattern, text, str(request.get("template", "")))
            return {"pieces": pieces, "count": count}
        if op == "one":
            return {"new": replace_one(pattern, text, str(request.get("template", "")))}
    except (re.error, IndexError) as exc:  # (a bad replacement template: "\\9", "\\g<x>")
        return {"error": "template", "text": str(exc)}
    return {"error": "op"}
