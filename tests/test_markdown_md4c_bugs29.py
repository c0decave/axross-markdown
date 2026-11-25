"""Qt's own parser (the fallback without markdown-it-py) shows what markdown-it's page shows: a raw table's
cells around a code block, headings that begin with a span, tables and lists GFM reads otherwise than Qt's
Markdown reader, links over lines, right-to-left quotes and tables, underlined links, a leaner Export HTML.

Each test here failed before; the expectations are what markdown-it's page shows (compared in the tests).
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

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QTextCursor, QTextFormat  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from tests.test_markdown_reader_bugs11 import pump, until  # noqa: E402
from tests import markdown_heartbeat as HB  # noqa: E402
from tests import markdown_timing as TB  # noqa: E402

APP = QApplication.instance() or QApplication([])

SIDES = Qt.AlignmentFlag.AlignHorizontal_Mask


def _view(text: str, full: bool):
    from axross_markdown._ax.ui import markdown_view as MV

    view = MV.MarkdownView(None)
    view.full = view.full and full
    view.resize(900, 700)
    view.show()
    view.render(text)
    assert until(lambda: view._readable, TB.READY_SECONDS)
    until(lambda: not view._scheduled, 30)
    return view


def _closed(view) -> None:
    view.close()
    view.deleteLater()


def _shown(text: str, full: bool) -> str:
    view = _view(text, full)
    shown = " ".join(view.browser.document().toPlainText().split())
    _closed(view)
    return shown


def _side(block) -> str:
    side = block.blockFormat().alignment() & SIDES
    if side & Qt.AlignmentFlag.AlignHCenter:
        return "center"
    return "right" if side & Qt.AlignmentFlag.AlignRight else ""


def _data_table(block):
    """The table with borders *block* is in (a quote's or a code block's box has none), or None."""
    table = QTextCursor(block).currentTable()
    return table if table is not None and table.format().border() > 0 else None


def _rows(text: str, full: bool) -> list[tuple]:
    """What the page of *text* shows, block by block (the empty ones left out): (its text, its heading
    level, whether it is a list's item, its cell "rows x columns @ row,column" in a table, its alignment,
    its links (text, address))."""
    view = _view(text, full)
    rows, block = [], view.browser.document().begin()
    while block.isValid():
        if block.text().strip():
            table, where = _data_table(block), ""
            if table is not None:
                cell = table.cellAt(block.position())
                where = f"{table.rows()}x{table.columns()}@{cell.row()},{cell.column()}"
            links, pieces = [], block.begin()
            while not pieces.atEnd():
                piece = pieces.fragment()
                pieces += 1
                href = piece.charFormat().anchorHref()
                if href and links and links[-1][1] == href:
                    links[-1] = (links[-1][0] + piece.text(), href)
                elif href:
                    links.append((piece.text(), href))
            rows.append((" ".join(block.text().split()), block.blockFormat().headingLevel(),
                         block.textList() is not None, where, _side(block), tuple(links)))
        block = block.next()
    _closed(view)
    return rows


def _pieces(text: str, full: bool) -> list[list[dict]]:
    """Each block of *text*'s page that holds text: its pieces' text and format."""
    view = _view(text, full)
    found, block = [], view.browser.document().begin()
    while block.isValid():
        if block.text().strip():
            row, pieces = [], block.begin()
            while not pieces.atEnd():
                piece = pieces.fragment()
                pieces += 1
                fmt = piece.charFormat()
                row.append({"text": piece.text(), "weight": fmt.fontWeight(), "href": fmt.anchorHref(),
                            "step": fmt.intProperty(QTextFormat.Property.FontSizeAdjustment),
                            "points": fmt.hasProperty(QTextFormat.Property.FontPointSize),
                            "family": (fmt.fontFamilies() or [""])[0], "colour": fmt.foreground().color().name(),
                            "underline": fmt.fontUnderline(), "struck": fmt.fontStrikeOut(),
                            "image": fmt.isImageFormat(), "level": block.blockFormat().headingLevel()})
            found.append(row)
        block = block.next()
    _closed(view)
    return found


# -- a raw table whose cell holds a code block, a raw table never closed ---------------------------------------

RAW_TABLES = [
    "<table><tr><td>\n\nfirst para\n\n```\ncode\n```\n\n</td></tr></table>\n",
    "<table>\n<tr><th>Before</th><th>After</th></tr>\n<tr><td>\n\nOld way:\n\n```js\nfoo()\n```\n\n</td><td>\n\n"
    "New way:\n\n```js\nbar()\n```\n\n</td></tr>\n</table>\n",
    "<table><tr><td>\n\nfirst para\n\nsecond\n",
    # (two code blocks in a cell)
    "<table><tr><td>\n\none\n\n```\nc1\n```\n\ntwo\n\n```\nc2\n```\n\nthree\n\n</td></tr></table>\n\nafter\n",
    # (a cell never closed, a row never closed, no end tag at all)
    "<table><tr><td>cell one<td>cell two</tr><tr><td>three</table>\n\nafter\n",
    "<table><tr><td>open cell\n",
    "before\n\n<table><tr><th>h\n\npara in th\n\n```\nx\n```\n",
    # (a table in a cell)
    "<table><tr><td>outer <table><tr><td>inner</td></tr></table> tail</td></tr></table>\n\nafter\n",
    # (in a quote, in a list item)
    "> <table><tr><td>\n>\n> quoted para\n>\n> ```\n> code\n> ```\n>\n> </td></tr></table>\n\nafter\n",
    "- item\n\n  <table><tr><td>\n\n  in item\n\n  ```\n  code\n  ```\n\n  </td></tr></table>\n\nafter\n",
    # (text after a table whose end tag is missing, indented code after it)
    "<table><tr><td>a</td></tr>\n\ntext after open table\n\n    indented code\n\nlast\n",
    "<TABLE><TR><TD>\n\nupper\n\n~~~\ncode\n~~~\n\n</TD></TR></TABLE>\n",
    "<table><tr><td>a</td></tr></table>\n\n<table><tr><td>\n\nb\n\n```\nc\n```\n\n</td></tr></table>\n",
    # (Markdown after an empty line in a cell: read as Markdown)
    "<table>\n<tr><td>\n\n*em* text\n\n</td></tr>\n</table>\n",
]


@pytest.mark.parametrize("text", RAW_TABLES)
def test_sad_no_text_of_a_raw_table_vanishes(text):
    """Before: the text of a raw <table>'s cell before a code block was not shown ("first para" gone,
    "Old way:" of a Before / After table), a cell never closed lost its text ("<td>one<td>two"), and a table
    never closed showed an empty page. Now every word markdown-it's page shows is there."""
    full, own = _shown(text, True), _shown(text, False)
    assert sorted(own.split()) == sorted(full.split()), (text, full, own)


def test_edge_a_list_in_a_raw_table_s_cell_keeps_its_items():
    """A cell that holds a list after an empty line: its items lines of the cell, behind a bullet each (the
    cell showed "- a - b" in one line)."""
    own = _shown("<table><tr><td>\n\n- a\n- b\n\n</td><td>x</td></tr></table>\n", False)
    assert own.replace("\u2022", "").split() == ["a", "b", "x"], own
    assert "- a" not in own


def test_happy_a_raw_table_that_is_whole_stays_a_table():
    """A raw table closed in its text is a table as before - and the rows before a cell with a code block
    stay one: "Before | After" is the table's header."""
    rows = _rows("<table><tr><th>h1</th><th>h2</th></tr><tr><td>a</td><td>b</td></tr></table>\n", False)
    assert [(row[0], row[3]) for row in rows] == [("h1", "2x2@0,0"), ("h2", "2x2@0,1"), ("a", "2x2@1,0"),
                                                  ("b", "2x2@1,1")]
    rows = _rows(RAW_TABLES[1], False)
    assert [(row[0], row[3]) for row in rows[:3]] == [("Before", "1x2@0,0"), ("After", "1x2@0,1"), ("Old way:", "")]


def test_sad_the_raw_table_passes_stay_linear():
    """The passes over a raw table - whole, never closed, its cells never closed, its rows with <br> - read
    it once: twice the rows about twice the time (on a worker thread, texts up to 8 MiB)."""
    from axross_markdown._ax.ui import markdown_view as MV

    shapes = [lambda n: "<table>\n" + "<tr><td>a</td><td><a href='x'>b</a></td></tr>\n" * n + "</table>\n",
              lambda n: "<table>\n" + "<tr><td>a</td><td>b</td></tr>\n" * n,
              lambda n: "<table>\n" + "<tr><td>a<td>b\n" * n,
              lambda n: "<table><tr><td>\n\n" + "para\n\n<td>x\n\n" * n,
              lambda n: "<table><tr><td>para\n\n" * n,
              lambda n: "<table><tr><td>a</td></tr>\n" * n,
              lambda n: "| a | b |\n|---|---|\n" + "| l1<br>l2 | x<br> |\n" * n,
              lambda n: "<br>" * (4 * n) + " | x\n"]
    for shape in shapes:
        took = []
        for count in (20_000, 40_000):
            text = shape(count)
            began = time.thread_time()
            shown = MV.fallback_text(text)
            took.append(time.thread_time() - began)
            assert max(shown.count("a"), shown.count("para"), shown.count("l1")) >= count \
                or shown.count("\ue099") == MV.ROW_BREAKS  # (a row's line breaks: so many at most)
        TB.budget(took[1] < 3.2 * took[0] + 0.05, (shape(1), took))
        assert took[1] < 60, (shape(1), took)


# -- a heading that begins with a span -------------------------------------------------------------------------

SPAN_HEADINGS = [
    "# `code` first\n", "## *em* first then more\n", "# [link](http://x.y/)\n", "## plain then `code`\n",
    "### **bold** and `code` and [a link](http://x.y/) end\n", "#### `c` four\n", "##### `c` five\n",
    "###### [l](http://a.b/) six **b**\n", "`code` setext\n===\n", "*em* two\n---\n",
    "[link](http://x.y/) under\n---\n",
]


@pytest.mark.parametrize("text", SPAN_HEADINGS)
def test_sad_a_heading_that_begins_with_a_span_is_a_heading(text):
    """Before: "# `code` first", "## *em* first" and "# [link](…)" were the text's size and weight (400) in
    Qt's own parser's page - its size and weight were taken from the heading's first piece. Now every piece
    is bold and of the size markdown-it's page gives the level; code keeps its letters, a link its colour."""
    from axross_markdown._ax.ui.markdown_html import colours

    full, own = _pieces(text, True), _pieces(text, False)
    assert len(own) == 1 and own[0][0]["level"] == full[0][0]["level"] > 0
    step = full[0][0]["step"]
    assert all(piece["step"] == step for piece in full[0])
    for piece in own[0]:
        assert piece["weight"] == 700 and piece["step"] == step and not piece["points"], (text, piece)
    for piece in own[0]:
        if piece["text"].strip() in ("code", "c"):
            assert piece["family"] == "monospace", piece
        if piece["href"]:
            assert piece["colour"] == colours(False)["link"], piece


def test_sad_the_fifth_and_sixth_heading_levels_are_as_big_as_markdown_it_s():
    """Before: h5 and h6 were one step smaller in Qt's own parser's page than in markdown-it's (9 and 7.9
    points against 11.2 and 9: the sixth smaller than the small print). All six levels now agree."""
    text = "".join(f"{'#' * level} level {level}\n\n" for level in range(1, 7))
    full, own = _pieces(text, True), _pieces(text, False)
    assert [(row[0]["level"], row[0]["step"]) for row in own] == [(row[0]["level"], row[0]["step"]) for row in full] \
        == [(1, 3), (2, 2), (3, 1), (4, 0), (5, 0), (6, -1)]
    assert all(piece["weight"] == 700 for row in own for piece in row)


# -- tables --------------------------------------------------------------------------------------------------

TABLES = [
    "para\n| a | b |\n|---|---|\n| 1 | 2 |\n",
    "> para\n> | a | b |\n> |---|---|\n> | 1 | 2 |\n",
    "- item\n  | a | b |\n  |---|---|\n  | 1 | 2 |\n- next\n",
    "line one\nline two\na | b\n--|--\n1 | 2\n",
    "# head\n| a | b |\n|---|---|\n| 1 | 2 |\ntail | x\n\nafter\n",
    # (no table to GFM: a header of other cells than its delimiter row; a line under a list item's)
    "para\n| a | b |\n|---|\n| 1 | 2 |\n",
    "- item\n| a | b |\n|---|---|\n| 1 | 2 |\n",
    # (a table's own rows are no paragraph before a "header")
    "| h | i |\n|---|---|\n| a | b |\n|---|---|\n| c | d |\n",
    # (<br> in a cell)
    "| a | b |\n|---|---|\n| line1<br>line2 | x |\n| n | m |\n",
    "| a | b |\n|---|---|\n| one<br/>two<br>three | x<br> |\n",
    "<table><tr><td>l1<br>l2</td><td>x</td></tr></table>\n",
    "a | b<br>c\n\ntext<br>more\n",
]


def _cells_of(rows: list[tuple]) -> list[tuple]:
    return [(row[0], row[1], row[2], row[3]) for row in rows]


@pytest.mark.parametrize("text", TABLES)
def test_sad_tables_are_read_as_gfm_reads_them(text):
    """Before, in Qt's own parser's page: a table right under a paragraph's line was text ("para | a | b |
    |---|---| | 1 | 2 |"), and a <br> in a cell ended its row (a table of 4 rows, "line1 |" and "line2 | x").
    Now the same cells as markdown-it's page."""
    assert _cells_of(_rows(text, False)) == _cells_of(_rows(text, True)), text


def test_sad_a_table_s_header_cells_are_aligned_as_their_columns():
    """Before: ":-:" and "--:" aligned the rows under the header only; the header's cells stayed on the
    left."""
    text = "| a | b | c |\n|:-:|--:|:--|\n| 1 | 2 | 3 |\n"
    full, own = _rows(text, True), _rows(text, False)
    assert [row[4] for row in own] == [row[4] for row in full] == ["center", "right", "", "center", "right", ""]


def _boxes_of(text: str, full: bool) -> list[tuple]:
    """(a block's text, how many tables it is in, whether one of them has borders) for each block of the
    page of *text* that holds text."""
    view = _view(text, full)
    found, block = [], view.browser.document().begin()
    while block.isValid():
        if block.text().strip():
            depth, table, data = 0, QTextCursor(block).currentTable(), False
            while table is not None:
                depth += 1
                data = data or table.format().border() > 0
                frame = table.parentFrame()
                table = frame if hasattr(frame, "cellAt") else None
            found.append((" ".join(block.text().split()), depth, data))
        block = block.next()
    _closed(view)
    return found


QUOTED = [
    "> text0\n> # head\n> text\n\nafter\n",
    "> intro\n>\n> | a | b |\n> |:-:|--:|\n> | 1 | 2 |\n>\n> text\n\nafter\n",
    "> | a | b |\n> |---|---|\n> | 1 | 2 |\n\nafter\n",
    "> Head one\n> ========\n> text\n>\n> ## two\n> more\n\nafter\n",
    "> intro\n> | a | b |\n> |---|---|\n> | 1 | 2 |\n> # head\n> last\n",
]


@pytest.mark.parametrize("text", QUOTED)
def test_sad_a_heading_and_a_table_in_a_quote_are_in_its_box(text):
    """Before: Qt's own parser's page drew a quote's heading and a quote's table outside the quote's box -
    the box ended before them and another began after them. Now they are in it, as in markdown-it's page."""
    full, own = _boxes_of(text, True), _boxes_of(text, False)
    assert own == full, (text, full, own)
    assert all(depth >= 1 for words, depth, _data in own if words != "after")


def test_edge_a_heading_after_a_quote_is_not_in_its_box():
    """A heading under a quote (not in it) stays outside its box, a table too."""
    text = "> quote\n\n# head\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    own = _boxes_of(text, False)
    assert own == _boxes_of(text, True)
    assert own[0] == ("quote", 1, False) and own[1] == ("head", 0, False) and own[2] == ("a", 1, True)


# -- links -----------------------------------------------------------------------------------------------------

LINKS = [
    '[m1](http://a.b/ "multi\nline") z\n',
    '[m2](\n  http://a.b/x\n  "t") z\n',
    "[m3](http://a.b/y\n'one\ntwo') and [m4](http://a.b/z (three\nfour)) end\n",
    # (an empty line in a title: no link)
    '[m5](http://a.b/ "multi\n\nline") z\n',
    # (GFM's examples of a reference definition over lines)
    "   [foo]: \n      /url  \n           'the title'  \n\n[foo]\n",
    "[foo]: /url '\ntitle\nline1\nline2\n'\n\n[foo]\n",
    '[foo]: /url  \n  "title"\n\n[foo] and\n[bar]:\n/other\n\n[bar]\n',
    "[foo]:\n/url\n\n[foo]\n",
    # (character references in a destination)
    '[m3](http://a.b/?a=1&amp;b=2) [m4](http://a.b/f&ouml;&ouml;) [m5](/p&quot;q "t&amp;t")\n',
    "[r]: http://a.b/?x=1&amp;y=&#50;\n\n[ref][r]\n",
    # (an image in a link)
    "[![moon](moon.jpg)](http://a.b/uri) tail\n",
    '[![moon](moon.jpg "t")](http://a.b/uri "lt") and [![b](b.png)](c.md)\n',
    # ("www." addresses and what ends them)
    "see www.a.org/x: and www.a.org/(x) and www.b.org/y, (www.c.org/z) www.d.org/a_b. www.e.org/q?x=1;\n",
    "www.commonmark.org/a.b. www.google.com/search?q=Markup+(business))) and www.google.com/search?q=commonmark&hl;\n",
]


@pytest.mark.parametrize("text", LINKS)
def test_sad_links_lead_where_markdown_it_s_lead(text):
    """Before, in Qt's own parser's page: a link whose title or destination was on another line had the
    address "[http://a.b/](http://a.b/)"; a definition's destination on its own line with two spaces after it
    kept a private-use character (U+E099) in the address; "&amp;" stayed in an address; a local image in a
    link had no link; "www.a.org/x:" and "www.a.org/(x)" were no links. Now every link's text and address
    are markdown-it's page's."""
    full, own = _rows(text, True), _rows(text, False)
    assert [(row[0], row[5]) for row in own] == [(row[0], row[5]) for row in full], (text, full, own)
    for _text, _level, _item, _cell, _side_of, links in own:
        assert all(0xE000 > ord(char) or ord(char) > 0xF8FF for _shown_text, href in links for char in href), links


def test_guard_a_www_link_shows_a_look_alike_host_in_punycode():
    """A "www." address with a look-alike letter (a Cyrillic "\u0430") is shown and followed in punycode, as
    in markdown-it's page - never as written."""
    text = "A www.p\u0430ypal.com/x: and www.m\u00fcnchen.de.\n"
    own, full = _rows(text, False), _rows(text, True)
    assert own[0][5][0] == full[0][5][0] == ("www.xn--pypal-4ve.com/x", "http://www.xn--pypal-4ve.com/x")
    assert [shown for shown, _href in own[0][5]] == [shown for shown, _href in full[0][5]]
    assert "\u0430" not in own[0][0]


def test_sad_an_image_in_a_link_is_the_link_s():
    """The image's own piece carries the link's address (a click on a badge did nothing); no mark of the
    pass is left in the page."""
    pieces = _pieces("before [![moon](moon.jpg)](http://a.b/uri) after\n", False)[0]
    image = [piece for piece in pieces if piece["image"]]
    assert len(image) == 1 and image[0]["href"] == "http://a.b/uri", pieces
    assert "".join(piece["text"] for piece in pieces) == "before \ufffc after"


# -- list items that begin with a block ------------------------------------------------------------------------

ITEMS = [
    "1. ```\n   foo\n   ```\n\n   bar\n", "- ```\n  foo\n  ```\n- two\n", "-     indented code\n\n  para\n",
    "- > q1\n  >\n  > q2\n\n  tail\n", "- a\n  > q1\n  >\n  > q2\n- b\n", "1. > quote\n2. next\n",
    "> - a\n>   > inner\n> - b\n", "- ```\n  one\n  ```\n\n  ```\n  two\n  ```\n",
    "10. ```py\n    x = 1\n    y = 2\n    ```\n11. b\n", "- a\n  ```\n  code\n  ```\n  > q\n\n  > q2\n",
    "1.     indented code\n\n   paragraph\n\n       more code\n", "> 1. > Blockquote\ncontinued here.\n",
    # (as before)
    "1. foo\n\n   ```\n   bar\n   ```\n\n   baz\n\n   > bam\n", "- a\n\n  > q\n  > - x\n  > - y\n\n- b\n",
]


def _items(text: str, full: bool) -> list[str]:
    """The text of each list item of the page of *text* (a block with a bullet or a number)."""
    view = _view(text, full)
    found, block = [], view.browser.document().begin()
    while block.isValid():
        if block.textList() is not None:
            found.append(block.text().strip())
        block = block.next()
    shown = view.browser.document().toPlainText()
    _closed(view)
    assert not any(0xE000 <= ord(char) <= 0xF8FF for char in shown), shown
    return found


@pytest.mark.parametrize("text", ITEMS)
def test_sad_a_list_item_s_blocks_are_no_items_of_their_own(text):
    """Before: Qt's Markdown reader made a list item of each block after an item that began with a code
    block or a quote, and of a quote or a fence right under an item's line - "1. ```" over "foo" and "bar"
    drew "1. foo", "2. bar", each line of a code block its own number. Now the items markdown-it's page
    has: the item's bullet on a line of its own, the block under it."""
    assert _items(text, False) == _items(text, True), text
    # (the line Qt's own parser's page keeps between two code blocks is no word)
    assert sorted(_shown(text, False).replace("\u200b", "").split()) == sorted(_shown(text, True).split())


# -- small things of GFM -----------------------------------------------------------------------------------------

def test_sad_an_alert_without_text_shows_no_backslash():
    """Before: "> [!NOTE]" with nothing under it showed its title and a "\\" (the hard break after the
    title, with no line to break to)."""
    assert _shown("> [!NOTE]\n\nafter\n", False).split()[-2:] == ["Note", "after"]
    assert "\\" not in _shown("> [!TIP]\n>\n> body\n", False)
    own = _shown("> [!TIP]\n> body\n", False)
    assert own.endswith("Tip body") and "\\" not in own


STRUCK = ["a~b~c and ~~two~~ and ~one~ x\n", "H~2~O ~a b~ ~~~x~~~\n", "a~b~ c\n", "a ~b~c\n", "a~~b~~c\n",
          "x~ y~ z\n", "a~b~c~d~e\n", "(~b~) .~b~. a~*b*~c\n", "a~b~~c~d\n", "~~a~b~~ a~b\n",
          "| a~b~c | d~e |\n|---|---|\n| 1 | 2 |\n", "costs ~5 or ~6\n"]


@pytest.mark.parametrize("text", STRUCK)
def test_sad_struck_text_inside_a_word_is_struck(text):
    """Before: "a~b~c" was shown as written by Qt's own parser (it strikes only what stands between spaces
    or punctuation); markdown-it's page strikes "b"."""
    def struck(full: bool) -> tuple[str, str]:
        rows = _pieces(text, full)
        return ("".join(piece["text"] for row in rows for piece in row if piece["struck"]),
                "".join(piece["text"] for row in rows for piece in row))

    assert struck(False) == struck(True), text


def test_edge_a_tilde_in_an_address_strikes_nothing():
    """A "~" in a bare address is the address's (markdown-it's page strikes a part of the line there)."""
    pieces = _pieces("see http://x.org/~user/~b and c~d\n", False)[0]
    assert not any(piece["struck"] for piece in pieces)
    assert [piece["href"] for piece in pieces if piece["href"]] == ["http://x.org/~user/~b"]
    # (nor one in a code span, with a "~" before it)
    pieces = _pieces("costs ~5 or ~6 and `a~b~c`\n", False)[0]
    assert not any(piece["struck"] for piece in pieces)
    assert "".join(piece["text"] for piece in pieces) == "costs ~5 or ~6 and a~b~c"


# -- right-to-left text ------------------------------------------------------------------------------------------

ARABIC = "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645"
HEBREW = "\u05e9\u05dc\u05d5\u05dd \u05e2\u05d5\u05dc\u05dd"


def _places(text: str) -> dict:
    """Where Qt's own parser's page of *text* draws each block: {its text: (left, right) of its first
    line}, "bars": the left edges of the quotes' bars, "width": the page's."""
    view = _view(text, False)
    document = view.browser.document()
    layout, places, bars = document.documentLayout(), {}, []
    block = document.begin()
    while block.isValid():
        rect = layout.blockBoundingRect(block)
        table = QTextCursor(block).currentTable()
        if block.text().strip():
            line = block.layout().lineAt(0).naturalTextRect()
            places[block.text().strip()] = (rect.x() + line.x(), rect.x() + line.x() + line.width())
        elif table is not None and table.format().border() == 0 and table.columns() == 2 \
                and table.cellAt(block.position()).format().background().style() != Qt.BrushStyle.NoBrush:
            bars.append(rect.x())
        block = block.next()
    places["bars"], places["width"] = bars, document.size().width()
    _closed(view)
    return places


def test_sad_a_right_to_left_quote_has_its_bar_on_the_right():
    """Before: the bar of a quote of Arabic or Hebrew text stayed on the left, where its lines end."""
    places = _places(f"> {HEBREW} {HEBREW}\n> {HEBREW}\n\n> english quote\n")
    hebrew = places[f"{HEBREW} {HEBREW} {HEBREW}"]
    english = places["english quote"]
    assert len(places["bars"]) == 2
    assert places["bars"][0] >= hebrew[1] and places["bars"][0] > places["width"] / 2, places
    assert places["bars"][1] <= english[0] and places["bars"][1] < 20, places


def test_sad_a_right_to_left_table_begins_on_the_right():
    """Before: a table of Arabic text had its first column on the left and its header's cells aligned
    left. Now the first column is the rightmost, each cell's lines begin on the right - a number's too -,
    and a table of left-to-right text is as it was."""
    wide = "x" * 40
    places = _places(f"| {ARABIC} | {HEBREW} |\n|---|---|\n| \u0661 | \u0662 |\n| {wide} | {wide} |\n\n"
                     "| a | b |\n|---|---|\n| 1 | 2 |\n")
    first, second = places[ARABIC], places[HEBREW]
    assert first[0] >= second[1], places  # (the first column right of the second)
    assert places["\u0661"][0] >= places["\u0662"][1]
    assert abs(first[1] - places["\u0661"][1]) < 2  # (header and number end at the same right edge)
    assert places["a"][1] <= places["b"][0] and places["a"][0] < 40


def test_edge_a_right_to_left_raw_table_and_a_quoted_one_begin_on_the_right_too():
    places = _places(f"<table><tr><th>{ARABIC}</th><th>{HEBREW}</th></tr><tr><td>1</td><td>2</td></tr></table>\n")
    assert places[ARABIC][0] >= places[HEBREW][1], places
    places = _places(f"> {ARABIC}\n>\n> | {ARABIC} {ARABIC} | {HEBREW} |\n> |---|---|\n> | 1 | 2 |\n")
    assert places[f"{ARABIC} {ARABIC}"][0] >= places[HEBREW][1], places
    assert places["bars"] and places["bars"][0] > places[f"{ARABIC} {ARABIC}"][1]


def test_guard_a_mirrored_table_keeps_every_cell_and_no_mark():
    """The cells of a right-to-left table are all there, a row with too few cells too."""
    text = f"| {ARABIC} | b | c |\n|:--|:-:|--:|\n| 1 | 2 | 3 |\n| only |\n"
    rows = _rows(text, False)
    assert [(row[0], row[3]) for row in rows] == [("c", "3x3@0,0"), ("b", "3x3@0,1"), (ARABIC, "3x3@0,2"),
                                                  ("3", "3x3@1,0"), ("2", "3x3@1,1"), ("1", "3x3@1,2"),
                                                  ("only", "3x3@2,2")]


# -- links underlined ------------------------------------------------------------------------------------------

LINKED_PAGE = ("A [named link](https://a.example/x), <https://auto.example/>, https://bare.example/y and "
               "www.w.example/z, a note[^1].\n\n# A [link](https://h.example/) in a heading\n\n"
               "> quote with [its link](q.md)\n\n- item [in a list](l.md)\n\n| [cell](c.md) | b |\n|---|---|\n"
               "| 1 | 2 |\n\n[^1]: the note's text\n")


def test_sad_links_are_underlined_in_every_theme():
    """Before: a link was told from the text around it by its hue alone - no underline on its piece -, and
    in some themes the two hues are as light as each other. Now every link's piece in Qt's own parser's
    page is underlined, in each of the themes; the text beside it is not."""
    from PyQt6.QtGui import QTextDocument

    from axross_markdown._ax.core import markdown_themes as MT
    from axross_markdown._ax.ui import markdown_view as MV

    written = "".join(MV._md4c_page(LINKED_PAGE)[0])
    assert len(MT.THEMES) >= 12
    for name, theme in MT.THEMES.items():
        document = QTextDocument()
        document.setMarkdown(written, MV.FEATURES)
        MV.apply_marks(document, 0, theme)
        MV._style_md4c(document, 0, theme, False)
        links, plain, block = [], [], document.begin()
        while block.isValid():
            pieces = block.begin()
            while not pieces.atEnd():
                piece = pieces.fragment()
                pieces += 1
                (links if piece.charFormat().anchorHref() else plain).append(piece)
            block = block.next()
        shown = {piece.text() for piece in links}
        assert {"named link", "https://auto.example/", "https://bare.example/y", "www.w.example/z", "link",
                "its link", "in a list", "cell"} <= shown, (name, shown)
        for piece in links:
            assert piece.charFormat().fontUnderline() == (piece.text() != "\u21a9"), (name, piece.text())
            assert piece.charFormat().foreground().color().name() == theme.page["link"], (name, piece.text())
        assert not any(piece.charFormat().fontUnderline() for piece in plain), name


def test_happy_the_page_s_links_are_underlined_and_a_fold_s_summary_is_not():
    """In the window: links underlined; a <details>' summary (a link that folds it) is not, nor the sign
    that leads back from a footnote."""
    rows = _pieces(LINKED_PAGE + "\n<details><summary>Fold</summary>\n\nin it\n\n</details>\n", False)
    links = [piece for row in rows for piece in row if piece["href"]]
    assert len(links) >= 9
    for piece in links:
        fold = piece["href"].startswith("#axross-details-") or piece["text"] == "\u21a9"
        assert piece["underline"] == (not fold), piece
    assert not any(piece["underline"] for row in rows for piece in row if not piece["href"])


# -- Export HTML -----------------------------------------------------------------------------------------------

def _export_of(tmp_path, text: str, full: bool) -> str:
    from axross_markdown._ax.core.local_fs import LocalFS
    from axross_markdown._ax.ui.markdown_viewer import open_markdown_viewer

    page = tmp_path / ("full.md" if full else "own.md")
    page.write_text(text, encoding="utf-8")
    viewer = open_markdown_viewer(LocalFS(), str(page))
    if not full:
        viewer.view.full = False
        viewer.view.render(text)
    assert until(lambda: viewer.view._readable, TB.READY_SECONDS)
    pump(0.2)
    target = str(tmp_path / ("full.html" if full else "own.html"))
    assert viewer.export_html(target) == target
    written = Path(target).read_text(encoding="utf-8")
    viewer.close()
    pump(0.1)
    return written


def test_sad_a_closed_fold_is_in_qt_s_own_parser_s_exported_page(tmp_path):
    """Before: Export HTML of Qt's own parser's page left out what a closed <details> holds - 654 KB of
    sections in one fold gave a file of 1,356 bytes whose summary linked to "#axross-details-1", an anchor
    that file did not hold. Now the fold is written open: its summary, then all of it."""
    text = "<details><summary>Fold</summary>\n\n" + "".join(
        f"## H{number}\n\nPara *{number}* in the fold.\n\n" for number in range(60)) + "</details>\n\nafter\n"
    written = _export_of(tmp_path, text, False)
    assert "Fold" in written and "H0<" in written and "H59<" in written and "in the fold" in written
    assert "axross-details" not in written
    assert written.index("Fold") < written.index("H0<") < written.index("H59<") < written.index("after")
    # (the page in the window keeps it closed)
    assert "H59" not in _shown(text, False)


def test_sad_qt_s_own_parser_s_exported_page_writes_a_style_once(tmp_path):
    """Before: Qt's toHtml wrote every block's and every span's whole style into its tag - the export of
    Qt's own parser's page was 6.6 times markdown-it's for these sections (4.4 times in the review's page).
    Now each style is a class of the page's style sheet: under 2.5 times, the text and the links as
    before."""
    text = "".join(f"## H{number}\n\nPara *{number}* with `code` and [link](#h{number}).\n\n- item\n- item\n\n"
                   f"> quote\n\n" for number in range(300))
    own, full = _export_of(tmp_path, text, False), _export_of(tmp_path, text, True)
    assert len(own) < 2.5 * len(full), (len(own), len(full))
    assert own.count('href="#h') == 300 and "H299" in own and own.count("<li") == 600
    assert own.count(' style="') < 100, own.count(' style="')
    assert "text-decoration: underline" in own and "line-height:calc(" in own  # (in the sheet, a browser's)
    assert "-qt-line-height-type" not in own


def test_guard_the_leaner_export_keeps_styles_past_its_classes():
    """More distinct styles than the sheet takes classes: the rest stay in their tags, none is lost."""
    from axross_markdown._ax.ui import markdown_view as MV

    head = "<html><head><title>t</title></head><body>"
    bodies = ["".join(f'<p style=" margin-top:{n}px;">x</p>' for n in range(MV.LEAN_CLASSES + 5)),
              '<p style=" margin-top:1px;">y</p><span>z</span>']
    new_head, new_bodies = MV.lean_qt_html(head, bodies)
    assert new_head.count("margin-top:") == MV.LEAN_CLASSES and new_head.endswith("</style></head><body>")
    assert new_bodies[0].count(' style="') == 5 and new_bodies[0].count(' class="q') == MV.LEAN_CLASSES
    assert new_bodies[1] == '<p class="q1">y</p><span>z</span>'
    assert MV.lean_qt_html("no head", ["<p>x</p>"]) == ("no head", ["<p>x</p>"])


# -- nothing here holds the window ---------------------------------------------------------------------------------

def _opened(text: str) -> tuple[float, float, str]:
    """(the longest turn, the longest gap, the page's first words) of Qt's own parser's page of *text*
    while it is made and its first parts are laid out."""
    from axross_markdown._ax.ui import markdown_view as MV

    view = MV.MarkdownView(None)
    view.full = False
    view.resize(900, 700)
    view.show()
    pump(0.1)
    beat = HB.Heartbeat()
    view.render(text)
    assert until(lambda: view._readable, TB.READY_SECONDS)
    pump(1.0)
    turn, gap = beat.stop()
    shown = " ".join(view.browser.document().toPlainText().split())[:200]
    _closed(view)
    pump(0.1)
    return turn, gap, shown


BIG_PAGES = {
    "raw table": lambda: "<table>\n" + "<tr><td>a</td><td><a href='x'>b</a></td></tr>\n" * 12_000 + "</table>\n",
    "raw table never closed": lambda: "<table>\n" + "<tr><td>a</td><td>b</td></tr>\n" * 12_000 + "<tr><td>\n\nlast\n",
    "headings that begin with code": lambda: "".join(f"## `c{n}` head {n}\n\ntext\n\n" for n in range(20_000)),
    "a long quote with headings and tables": lambda: "".join(
        f"> text {n} [l](x.md) a~b~c www.a.org/x:\n> # head {n}\n> | a | b |\n> |:-:|---|\n> | 1<br>2 | 3 |\n>\n"
        for n in range(8_000)),
    "items that begin with code": lambda: "".join(
        f"{n + 1}. ```\n   code {n}\n   ```\n\n   after\n" for n in range(10_000)),
    "right-to-left tables": lambda: "".join(
        f"| {ARABIC} | {HEBREW} |\n|---|---|\n| 1 | 2 |\n\n> {HEBREW}\n\n" for _n in range(6_000)),
}


@pytest.mark.parametrize("name", list(BIG_PAGES))
def test_sad_the_new_passes_hold_no_turn_on_a_big_page(name):
    """The passes over Qt's own parser's text run on a worker, the ones over its page a part at a time:
    opening 300 to 700 KB of what they read holds no turn of the window."""
    turn, gap, shown = _opened(BIG_PAGES[name]())
    assert shown, name
    HB.assert_turn(turn, name)
    HB.assert_responsive(gap, name)


def test_sad_the_text_passes_stay_linear():
    """Each new pass over the text reads it once: twice the lines about twice the time."""
    from axross_markdown._ax.ui import markdown_view as MV

    shapes = [lambda n: "para\n| a | b |\n|---|---|\n| 1 | 2 |\n\n" * n,
              lambda n: "> text\n> # head\n> | a | b |\n> |---|---|\n" * n,
              lambda n: "- > quote\n- ```\n  code\n  ```\n-      code\n" * n,
              lambda n: "a~b~c ~d~ e~~f~~g ~ \n" * n,
              lambda n: "~a " * (4 * n) + "\n",
              lambda n: "[a](b \"c\n" * n,
              lambda n: "[a](\n" * n,
              lambda n: "[![alt](i.png)](http://a.b/?x&amp;y) www.a.org/(x): \n" * n,
              lambda n: "[![" * (4 * n) + "\n",
              lambda n: "[foo]:\n/url  \n'title'  \n" * n,
              lambda n: f"| {ARABIC} | b |\n|---|---|\n| 1 | 2 |\n\n" * n,
              lambda n: "> [!NOTE]\n\n" * n]
    for shape in shapes:
        took = []
        for count in (10_000, 20_000):
            text = shape(count)
            began = time.thread_time()
            MV.fallback_text(text)
            took.append(time.thread_time() - began)
        TB.budget(took[1] < 3.2 * took[0] + 0.05, (shape(1), took))
        assert took[1] < 60, (shape(1), took)
