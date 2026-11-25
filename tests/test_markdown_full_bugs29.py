"""The twenty-ninth round of the Markdown reader, markdown-it's page, the themes and accessibility: a "$"
amount before a code span read as a formula, right-to-left text laid out left-to-right, links told from
text by their colour alone, the colours inside a <mark>, the selection of a theme chosen while "auto" showed
it, a dark page's light scroll bar and window, a link in a <summary>, Find across Unicode's normal forms
and soft hyphens, names for the toolbar's signs, an image's alt text, and four small GFM items.

Each test named test_sad_ here failed before.
"""

from __future__ import annotations

import os
import sys
import time
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets", reason="PyQt6 not installed")
pytest.importorskip("markdown_it")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QPalette, QTextCursor, QTextDocument, QTextFormat  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from axross_markdown._ax.core import markdown_doc as MD  # noqa: E402
from axross_markdown._ax.core import markdown_themes as MT  # noqa: E402
from tests import markdown_heartbeat as HB  # noqa: E402
from tests import markdown_timing as TB  # noqa: E402
from tests.test_markdown_reader_bugs11 import pump, until  # noqa: E402
from tests.test_markdown_reader_bugs22 import PARSERS  # noqa: E402
from tests.test_markdown_reader_bugs24 import _opened, _viewer  # noqa: E402
from tests.test_markdown_reader_bugs28 import _shown, _view  # noqa: E402
from axross_markdown._ax.ui import markdown_html as H  # noqa: E402

APP = QApplication.instance() or QApplication([])

ARABIC = "مرحبا بالعالم."
HEBREW = "שלום עולם."


def _fragments(document) -> list:
    """(text, char format, block) of every fragment of *document*, in its order."""
    found, block = [], document.begin()
    while block.isValid():
        at = block.begin()
        while not at.atEnd():
            fragment = at.fragment()
            found.append((fragment.text(), fragment.charFormat(), block))
            at += 1
        block = block.next()
    return found


def _blocks(document) -> dict:
    """{a block's text: the block} of *document* (the first of each text)."""
    found, block = {}, document.begin()
    while block.isValid():
        found.setdefault(block.text(), block)
        block = block.next()
    return found


def _html(text: str, theme=False) -> str:
    return H.to_html(MD.parse(text), theme)


def _kinds(text: str) -> tuple[list, list]:
    """(the code spans, the formulas) markdown-it reads in *text*."""
    children = [child for token in MD.parse(text).tokens for child in (token.children or ())]
    return ([child.content for child in children if child.type == "code_inline"],
            [child.content for child in children if child.type in ("math_inline", "math_inline_double")])


@pytest.fixture
def themes():
    """The theme hub at "auto" before and after, nothing kept in any settings file."""
    from axross_markdown._ax.ui import markdown_theme_ui as TU

    kept, TU.store_theme = TU.store_theme, lambda theme_id: None
    hub = TU.hub()

    def reset() -> None:
        hub._timer.stop()
        hub._pending, hub._applied, hub._theme = None, float("-inf"), "auto"

    reset()

    def choose(theme_id: str) -> None:
        hub._applied = float("-inf")
        hub.choose(theme_id, keep=False)

    try:
        yield choose
    finally:
        reset()
        hub.changed.emit("auto")
        pump(0.05)
        TU.store_theme = kept
        for widget in APP.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        pump(0.05)


def _in_theme(viewer, theme_id: str) -> bool:
    view = viewer.view
    return until(lambda: view.theme is MT.THEMES[theme_id] and view._ground is MT.THEMES[theme_id]
                 and view._readable and not view._scheduled and not view.timer.isActive(), TB.READY_SECONDS)


# -- a "$" amount before a code span that begins with "$" ---------------------------------------------------------

MONEY_AND_CODE = [
    # (text, what the page shows, its code spans, its formulas)
    ("pay $5 or `$HOME` and $PATH\n", "pay $5 or $HOME and $PATH", ["$HOME"], []),
    ("$5 `$A` and `$B`\n", "$5 $A and $B", ["$A", "$B"], []),
    ("[cost $5](http://x.y/) and `$z`\n", "cost $5 and $z", ["$z"], []),
    ("- item $9 `$x`\n- next `$y` $8\n", "item $9 $x next $y $8", ["$x", "$y"], []),
]


@pytest.mark.parametrize("text, shown, code, math", MONEY_AND_CODE)
def test_sad_a_code_span_wins_over_a_formula(text, shown, code, math):
    """"pay $5 or `$HOME` and $PATH" showed "pay 5 or `HOME` and $PATH": the formula "5 or `" from the amount to
    the "$" inside the code span, the "$" signs gone, the code span lost. A formula never ends inside a code
    span that opens after its "$" now (nor past the link's text it is in)."""
    assert _kinds(text) == (code, math), _kinds(text)
    assert _shown(text, True) == shown


@pytest.mark.parametrize("text, code, math", [
    ("$x^2$ then `$HOME` then $y_1$\n", ["$HOME"], ["x^2", "y_1"]),
    ("| a | b |\n|---|---|\n| $x^2$ | `$a` |\n", ["$a"], ["x^2"]),
    ("$`x^2`$ and `$y`\n", ["$y"], ["x^2"]),  # (GitHub's other way of writing a formula in a line)
    ("$a `b` c$\n", [], ["a `b` c"]),  # (a code span that ends before the formula does: the formula's)
    ("`$a` $x$ `$b` $$y$$\n", ["$a", "$b"], ["x", "y"]),
    ("[the sum $a+b$](http://x.y/) and `$z`\n", ["$z"], ["a+b"]),
    # (no formula before: two code spans, an amount a closing "$" cannot follow, a cell of its own)
    ("use `$A` and `$B` now $C\n", ["$A", "$B"], []),
    ("costs $5 to `echo $1` and `echo $2`\n", ["echo $1", "echo $2"], []),
    ("| a | b |\n|---|---|\n| $5 | `$b` |\n", ["$b"], []),
])
def test_happy_a_formula_beside_a_code_span_is_still_a_formula(text, code, math):
    """What was read rightly before is read so still: a formula before and after a code span, in a table's
    cell beside one, around one, in a link's text."""
    assert _kinds(text) == (code, math), _kinds(text)


def test_happy_two_amounts_are_no_formula():
    """"$5 and $6" is text, as GitHub reads it (a closing "$" after a space, before a digit)."""
    assert _kinds("$5 and $6\n") == ([], [])
    assert _shown("it costs $5 and $6 or $7\n", True) == "it costs $5 and $6 or $7"


def test_guard_code_before_math_is_found_in_linear_time():
    """The code spans of a line are found once a line, whatever its "$" signs: twice the text, about twice
    the time."""
    shapes = [lambda n: "$5 and `$x`\n" * n, lambda n: "$a ` b$ " * n, lambda n: "$a `` b$ ` " * n,
              lambda n: "[c $5](u) `$z` " * n, lambda n: "\\`$a ` b$" * n,
              lambda n: "".join("$a " + "`" * (i % 200 + 1) + " b$ " for i in range(n // 20))]
    for shape in shapes:
        took = []
        for count in (20_000, 40_000):
            text = shape(count)
            began = time.thread_time()
            MD.parse(text)
            took.append(time.thread_time() - began)
        TB.budget(took[1] < 3.2 * took[0] + 0.05, (shape(40)[:40], took))


def test_guard_100_000_lines_of_amounts_and_code_hold_no_turn(tmp_path):
    turn, gap = _opened(tmp_path, "pay $5 and `$x` then $PATH\n" * 100_000, True)
    HB.assert_turn(turn, "amounts and code")
    HB.assert_responsive(gap, "amounts and code")


# -- right-to-left text ---------------------------------------------------------------------------------------------

RTL_PAGE = (f"# {ARABIC}\n\n{ARABIC}\n\nAn English paragraph.\n\n- {HEBREW}\n- item in English\n\n"
            f"> {ARABIC} quoted\n\n| {ARABIC} | b | c |\n|---|---|---|\n| {HEBREW} | x | 3 |\n\n"
            f"```\ncode {ARABIC}\n```\n\n1. {ARABIC} first\n\n| a | {HEBREW} cell |\n|---|---|\n| 1 | 2 |\n")


def test_sad_each_block_takes_its_direction_from_its_text():
    """Every block was left-to-right: an Arabic or a Hebrew paragraph and heading on the left, a list's bullets
    on the left, the full stop at the wrong end. Each block's direction is its first strong character's now,
    as HTML's dir="auto"; an English paragraph and a code block stay left-to-right."""
    view = _view(RTL_PAGE, True)
    document = view.browser.document()
    blocks = _blocks(document)
    rtl, ltr = Qt.LayoutDirection.RightToLeft, Qt.LayoutDirection.LeftToRight
    for text in (ARABIC, f"{HEBREW}", f"{ARABIC} quoted", f"{ARABIC} first", f"{HEBREW} cell"):
        assert blocks[text].textDirection() == rtl, text
        assert blocks[text].blockFormat().layoutDirection() == rtl, text
    for text in ("An English paragraph.", "item in English", f"code {ARABIC}", "b", "x", "a"):
        assert blocks[text].textDirection() == ltr, text
    # (the heading: the first block of that text; the paragraph the next one of it)
    heading = document.begin()
    assert heading.text() == ARABIC and heading.blockFormat().headingLevel() == 1
    assert heading.textDirection() == rtl
    # (laid out at the right: its line ends at the text's right edge - it began at the left one)
    line = blocks[ARABIC].next().next().layout().lineAt(0) if not blocks[ARABIC].next().text() \
        else blocks[ARABIC].layout().lineAt(0)
    paragraph = next(block for text, _format, block in _fragments(document)
                     if text == ARABIC and not block.blockFormat().headingLevel())
    line = paragraph.layout().lineAt(0)
    assert line.naturalTextRect().right() > line.width() - 4 and line.naturalTextRect().left() > 100
    english = blocks["An English paragraph."].layout().lineAt(0)
    assert english.naturalTextRect().left() < 4
    # (a list item: its bullet on the right - the item's text ends before the list's indentation there)
    item = blocks[HEBREW]
    assert item.textList() is not None
    item_line = item.layout().lineAt(0)
    assert item_line.naturalTextRect().right() < item_line.width() + 1
    assert item.layout().position().x() + item_line.naturalTextRect().right() \
        < document.textWidth() - view.browser.document().indentWidth() / 2
    view.close()


def test_sad_a_right_to_left_quote_has_its_bar_on_the_right_and_a_table_is_mirrored():
    """A quote's bar stays on the side its text begins at; a table whose first text is right-to-left has its
    first column on the right (Qt lays a table's columns out from the left whatever its direction) and stands
    at the right - a left-to-right table with one Hebrew cell stays as written."""
    view = _view(RTL_PAGE, True)
    document = view.browser.document()
    blocks = _blocks(document)
    quote = QTextCursor(blocks[f"{ARABIC} quoted"]).currentTable()
    assert quote is not None and quote.columns() == 2
    bar = quote.cellAt(0, 1)  # (the narrow cell in the rule's colour: the second, at the right)
    assert bar.format().background().color().name() == MT.LIGHT_PAGE["rule"]
    assert quote.cellAt(blocks[f"{ARABIC} quoted"].position()).column() == 0
    table = QTextCursor(blocks["b"]).currentTable()
    row = [table.cellAt(0, column).firstCursorPosition().block().text() for column in range(3)]
    assert row == ["c", "b", ARABIC]
    assert [table.cellAt(1, column).firstCursorPosition().block().text() for column in range(3)] == ["3", "x", HEBREW]
    assert table.format().alignment() & Qt.AlignmentFlag.AlignRight
    other = QTextCursor(blocks["a"]).currentTable()
    assert [other.cellAt(0, column).firstCursorPosition().block().text() for column in range(2)] \
        == ["a", f"{HEBREW} cell"]
    assert not other.format().alignment() & Qt.AlignmentFlag.AlignRight
    plain = _view("> an English quote\n", True)
    cursor = plain.browser.document().find("an English quote")
    table = cursor.currentTable()
    assert table.cellAt(0, 0).format().background().color().name() == MT.LIGHT_PAGE["rule"]
    assert table.cellAt(cursor.selectionStart()).column() == 1
    plain.close()
    view.close()


def test_edge_what_is_in_a_right_to_left_item_or_quote():
    """In an Arabic list item: an English paragraph is left-to-right, a code block too, a line of digits takes
    the item's direction; in an English quote an Arabic paragraph is right-to-left; an alert's bar follows
    its text; nested items each their own."""
    page = _html(f"- {ARABIC}\n\n  English in the item.\n\n  12345\n\n  ```\n  code\n  ```\n\n  - {HEBREW}\n"
                 f"  - nested English\n\n> English quote\n>\n> {ARABIC}\n\n> [!NOTE]\n> {HEBREW}\n")
    assert f'<li dir="rtl">\n<p>{ARABIC}</p>' in page
    assert '<p dir="ltr">English in the item.</p>' in page
    assert "<p>12345</p>" in page
    assert '<td dir="ltr"><pre dir="ltr"' in page
    assert f"<li>{HEBREW}</li>" in page and '<li dir="ltr">nested English</li>' in page
    assert f'<p dir="rtl">{ARABIC}</p>' in page and "<p>English quote</p>" in page
    alert = page[page.index("bgcolor=\"" + MT.LIGHT_PAGE["alert_bg"]):]
    assert alert.index('<td dir="rtl" style="padding-right: 12px">') < alert.index(f'bgcolor="{MT.LIGHT_PAGE["note"]}"')
    view = _view(f"- {ARABIC}\n\n  English in the item.\n\n  ```\n  code\n  ```\n", True)
    blocks = _blocks(view.browser.document())
    assert blocks[ARABIC].textDirection() == Qt.LayoutDirection.RightToLeft
    assert blocks["English in the item."].textDirection() == Qt.LayoutDirection.LeftToRight
    assert blocks["code"].textDirection() == Qt.LayoutDirection.LeftToRight
    view.close()


def test_happy_a_left_to_right_page_says_nothing_of_directions():
    """A page of left-to-right text is made as before: no dir attribute, no table mirrored."""
    text = ("# Title\n\nText *with* `code` and café.\n\n- a\n- b\n\n> quote\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
            "```\ncode\n```\n\n1. one\n\n你好世界\n\n12345\n")
    page = _html(text)
    assert " dir=" not in page
    assert page.index("<th align=\"left\">a</th>") < page.index("<th align=\"left\">b</th>")
    assert H.text_direction("12 + 3 = 15") == "" and H.text_direction("你好") == "ltr"
    assert H.text_direction("123 " + HEBREW) == "rtl" and H.text_direction("\ue05d\ue05a 12") == ""  # (this module's own marks: none)


def test_happy_the_exported_page_says_each_block_s_direction():
    """Export HTML: the same directions, on the blocks themselves - a browser mirrors the table and puts the
    quote's bar and a list's bullets at the right by them (the style sheet's sides are the blocks' own:
    border-inline-start)."""
    page = H.export_html(MD.parse(RTL_PAGE))
    assert f'<p dir="rtl">{ARABIC}</p>' in page and "<p>An English paragraph.</p>" in page
    assert page.count('<h1 id="') == 1 and ' dir="rtl">' in page[page.index("<h1 "):page.index("</h1>")]
    assert f'<li dir="rtl">{HEBREW}</li>' in page
    assert '<blockquote dir="rtl">' in page and '<table dir="rtl">' in page
    assert page.index(f">{ARABIC}</th>") < page.index(">b</th>") < page.index(">c</th>")  # (as written)
    assert "border-inline-start: 4px solid" in page and "border-left: 4px" not in page
    assert "direction: ltr" in page  # (code)


def test_guard_directions_are_found_in_one_pass():
    """A block's direction is read from its first characters, a container's decided once: twice the blocks,
    about twice the time - 20,000 quotes in one another's lists too."""
    shapes = [lambda n: f"{ARABIC}\n\n" * n, lambda n: f"- {ARABIC}\n" * n, lambda n: "12345 67890\n\n" * n,
              lambda n: "".join(f"> - {HEBREW}\n>\n" for _ in range(n)),
              lambda n: f"| {ARABIC} | b |\n|---|---|\n" + f"| {HEBREW} | 1 |\n" * n]
    for shape in shapes:
        took = []
        for count in (10_000, 20_000):
            tokens = MD.parse(shape(count)).tokens
            began = time.thread_time()
            H._directions(tokens)
            H._mirrored(tokens)
            took.append(time.thread_time() - began)
        TB.budget(took[1] < 3.2 * took[0] + 0.05, (shape(1)[:30], took))


def test_guard_100_000_arabic_paragraphs_hold_no_turn(tmp_path):
    turn, gap = _opened(tmp_path, f"{ARABIC} {HEBREW}\n\n" * 100_000, True)
    HB.assert_turn(turn, "100,000 Arabic paragraphs")
    HB.assert_responsive(gap, "100,000 Arabic paragraphs")


# -- links are underlined ---------------------------------------------------------------------------------------

LINKS_PAGE = ("A [plain](http://x.y/p) link and a note[^1].\n\n# Head [heading](http://x.y/h)\n\n"
              "| a |\n|---|\n| [cell](http://x.y/c) |\n\n<mark>marked [inmark](http://x.y/m)</mark>\n\n"
              "> [!NOTE]\n> [alert](http://x.y/a)\n\n> [quote](http://x.y/q)\n\n- [item](http://x.y/i)\n\n"
              "https://bare.example/x and ~~[struck](http://x.y/s)~~\n\n[^1]: The note.\n")
LINK_TEXTS = ("plain", "heading", "cell", "inmark", "alert", "quote", "item", "https://bare.example/x", "struck")


@pytest.mark.parametrize("theme_id", list(MT.THEMES))
def test_sad_links_are_underlined_in_every_theme(theme_id):
    """Links were told from the text by their hue alone (Solar Dark's link is as light as its text: 1.00:1).
    Every link of the page is underlined now - in a heading, a table, a <mark>, an alert, a quote, a list - in
    every theme; a heading's own anchor is no link and has no line; a footnote's mark stays a raised number in
    brackets without one."""
    theme = MT.THEMES[theme_id]
    document = QTextDocument()
    document.setDefaultStyleSheet(H.style_sheet(theme))
    document.setHtml(H.to_html(MD.parse(LINKS_PAGE), theme))
    fragments = _fragments(document)
    links = {text: fmt for text, fmt, _block in fragments if fmt.anchorHref()}
    for text in LINK_TEXTS:
        assert links[text].fontUnderline(), (theme_id, text)
        assert links[text].foreground().color().name() in (theme.page["link"], theme.page["mark_link"])
    assert links["struck"].fontStrikeOut()
    for text, fmt, block in fragments:
        if not fmt.anchorHref():
            assert not fmt.fontUnderline(), (theme_id, text)  # (the heading's anchor, plain text)
    marks = [fmt for text, fmt, _block in fragments if fmt.anchorHref().startswith("#fn")]
    assert marks and not any(fmt.fontUnderline() for fmt in marks)


def test_sad_links_are_underlined_in_the_window():
    view = _view(LINKS_PAGE, True)
    links = {text: fmt for text, fmt, _block in _fragments(view.browser.document()) if fmt.anchorHref()}
    assert all(links[text].fontUnderline() for text in LINK_TEXTS), [t for t in LINK_TEXTS if not links[t].fontUnderline()]
    view.close()


def test_guard_200_000_underlined_links_hold_no_turn(tmp_path):
    turn, _gap = _opened(tmp_path, "".join(f"[link {n}](http://x.y/{n}) and text\n" + ("\n" if n % 5 == 4 else "")
                                          for n in range(200_000)), True)
    HB.assert_turn(turn, "200,000 links")  # (the turn: what the underline could cost - laying it out)


def test_sad_the_exported_page_underlines_its_links():
    """Export HTML said "a { text-decoration: none }" and showed the line under the pointer only."""
    page = H.export_html(MD.parse(LINKS_PAGE), dark=MT.THEMES["solar-dark"])
    style = page[page.index("<style>"):page.index("</style>")]
    assert "text-decoration: underline; }" in style and "text-decoration: none; } a:hover" not in style
    assert ".footnote-ref a, a.footnote-backref { text-decoration: none; }" in style


# -- the colours inside a <mark>, a formula in a table's header -------------------------------------------------

MARK_PAGE = ("<mark>marked [inmark](http://x.y/m) and ~~struck~~ and $x^2$ and ~~[both](http://x.y/b)~~</mark>\n\n"
             "| $y_h$ | [th](http://x.y/t) |\n|---|---|\n| $z$ | ~~cell~~ |\n| $w$ | b |\n\n> $q$ quote\n\n"
             "> [!TIP]\n> $t$ tip\n")


def _rendered(theme):
    from axross_markdown._ax.ui.markdown_theme_ui import rendered_contrasts

    document = QTextDocument()
    document.setDefaultStyleSheet(H.style_sheet(theme))
    document.setHtml(H.to_html(MD.parse(MARK_PAGE), theme))
    return rendered_contrasts(document, theme)


@pytest.mark.parametrize("theme_id", list(MT.THEMES))
def test_sad_a_link_struck_text_and_a_formula_in_a_mark_reach_aa(theme_id):
    """Measured on the rendered page, each fragment's colour against the ground it is drawn on: a link in a
    <mark> was 3.60:1 in Dark, 3.81 in Retro, 4.45 in Arctic, 4.47 in Slate, 6.44 in High Contrast Dark (below
    its AAA); struck text 3.83 in Dark, 4.07 in Slate, 4.32 in Solar Light, 4.34 in Solar Dark, 4.46 in
    Arctic, 4.48 in Retro; a formula 3.56 in Retro. Each has a colour of its own in a mark now, the page's
    where that reaches AA (AAA in a High Contrast theme)."""
    theme = MT.THEMES[theme_id]
    least = 7.0 if theme.aaa else 4.5
    rows = _rendered(theme)
    marked = {text: (fg, bg, ratio) for text, fg, bg, ratio in rows if bg == theme.page["highlight_bg"]}
    assert {"inmark", "struck", "x", "both"} <= set(marked), sorted(marked)
    for text, (fg, bg, ratio) in marked.items():
        floor = least if text in ("inmark", "struck", "both") or text.startswith("marked") else 4.5
        assert ratio >= floor, (theme_id, text, fg, bg, round(ratio, 2))
    assert marked["inmark"][0] == theme.page["mark_link"] and marked["struck"][0] == theme.page["mark_muted"]
    assert marked["x"][0] == theme.page["mark_math"]


@pytest.mark.parametrize("theme_id", list(MT.THEMES))
def test_sad_a_formula_in_a_table_s_header_reaches_aa(theme_id):
    """A formula in a table's header was 4.41:1 in Arctic and 4.23 in Retro (the formula's colour on the
    header's ground); on a row's tint, in a quote and in an alert it is measured too - on the rendered page."""
    theme = MT.THEMES[theme_id]
    rows = _rendered(theme)
    formulas = {text: (fg, bg, ratio) for text, fg, bg, ratio in rows if text in ("y", "z", "w", "q", "t")}
    assert formulas["y"][1] == theme.page["th_bg"] and formulas["w"][1] == theme.page["zebra"]
    assert formulas["t"][1] == theme.page["alert_bg"]
    for text, (fg, bg, ratio) in formulas.items():
        assert fg == theme.page["math"] and ratio >= 4.5, (theme_id, text, fg, bg, round(ratio, 2))
    low = [(text, fg, bg, round(ratio, 2)) for text, fg, bg, ratio in rows if ratio < 4.5]
    assert not low, (theme_id, low)


def test_happy_the_contrast_report_holds_the_mark_s_pairs():
    for theme in MT.THEMES.values():
        report = {(fg, bg): (ratio, least) for fg, bg, ratio, least in MT.contrast_report(theme)}
        least = 7.0 if theme.aaa else 4.5
        assert report[("mark_link", "highlight_bg")][1] == least and report[("mark_muted", "highlight_bg")][1] == least
        assert report[("mark_math", "highlight_bg")][1] == 4.5 and report[("math", "th_bg")][1] == 4.5
        assert all(ratio >= floor for ratio, floor in report.values()), theme.id
        # (the page's own colour where it reaches the floor: Light's link in a mark is Light's link)
        for key, role in MT.MARK_ROLES.items():
            floor = least if key != "mark_math" else 4.5
            if MT.contrast(theme.page[role], theme.page["highlight_bg"]) >= least:
                assert theme.page[key] == theme.page[role], (theme.id, key)
            assert MT.contrast(theme.page[key], theme.page["highlight_bg"]) >= floor
    assert MT.readable("#777777", "#ffffff", 4.5, "#000000") != "#777777"
    assert MT.readable("#000000", "#ffffff", 4.5, "#000000") == "#000000"


# -- a theme chosen while "auto" showed it; the scroll bar; the window around the page -------------------------------

LONG_PAGE = "# Title\n\n" + "A paragraph of the page with a [link](http://x.y/).\n\n" * 120


def test_sad_light_chosen_while_auto_shows_light_takes_its_selection_colours(tmp_path, themes):
    """With "auto" showing Light (a light window), View > Theme > Light changed nothing - the page's theme was
    the same - and the page kept Qt's own selection colours (#308cc6 under white: 3.69:1) until another theme
    had been chosen in between. The theme's ground and selection are painted now; "auto" gives the window's
    back."""
    viewer = _viewer(tmp_path, LONG_PAGE, True)
    view = viewer.view
    if view.theme is not MT.THEMES["light"]:
        pytest.skip("the window is not light here")
    assert view._ground is None
    themes("light")
    assert until(lambda: view._ground is MT.THEMES["light"], TB.READY_SECONDS)
    palette = view.browser.palette()
    assert palette.color(QPalette.ColorRole.Highlight).name() == MT.LIGHT_PAGE["selection_bg"]
    assert palette.color(QPalette.ColorRole.HighlightedText).name() == MT.LIGHT_PAGE["selection_fg"]
    assert MT.contrast(MT.LIGHT_PAGE["selection_fg"], MT.LIGHT_PAGE["selection_bg"]) >= 4.5
    themes("auto")
    assert until(lambda: view._ground is None, TB.READY_SECONDS)
    viewer.close()


@pytest.mark.parametrize("theme_id", ["dark", "retro", "high-contrast-dark", "sepia"])
def test_sad_a_page_s_scroll_bar_is_in_its_theme(tmp_path, themes, theme_id):
    """A dark page's scroll bar kept the window's colours: a white handle beside it (Dark, Retro, High
    Contrast Dark). Its groove is the page's ground now, its handle the theme's muted colour - no pixel of
    the bar lighter (in a dark theme) than that."""
    viewer = _viewer(tmp_path, LONG_PAGE, True)
    themes(theme_id)
    assert _in_theme(viewer, theme_id)
    pump(0.2)
    theme, bar = MT.THEMES[theme_id], viewer.view.browser.verticalScrollBar()
    assert bar.isVisible() and bar.maximum() > 0
    image = bar.grab().toImage()
    colours = {image.pixelColor(x, y).name() for x in range(0, image.width(), 2) for y in range(0, image.height(), 3)}
    assert theme.page["page_bg"] in colours and theme.page["muted"] in colours, sorted(colours)[:8]
    lights = [MT.luminance(colour) for colour in colours]
    low, high = sorted((MT.luminance(theme.page["page_bg"]), MT.luminance(theme.page["muted"])))
    assert min(lights) >= low - 0.01 and max(lights) <= high + 0.01, (theme_id, sorted(colours))
    assert MT.contrast(theme.page["muted"], theme.page["page_bg"]) >= 3.0  # (the handle against its groove)
    themes("auto")
    assert until(lambda: viewer.view._ground is None, TB.READY_SECONDS)
    assert bar.styleSheet() == ""
    viewer.close()


def test_sad_axross_markdown_s_window_follows_the_page_s_theme(tmp_path, themes, monkeypatch):
    """Beside a dark page the toolbar, the find field and the outline stayed in the window's light colours. In
    axross-markdown they take the page's theme with the page (View > Theme), and the window's own again with
    "Automatic"."""
    from axross_markdown._ax.ui import markdown_theme_ui as TU

    monkeypatch.setattr(TU, "standalone", lambda: True)
    viewer = _viewer(tmp_path, LONG_PAGE, True)
    assert viewer.styleSheet() == ""
    themes("dark")
    assert _in_theme(viewer, "dark")
    assert until(lambda: viewer.styleSheet() != "", TB.READY_SECONDS)
    pump(0.3)
    page = MT.DARK_PAGE
    def most(widget) -> str:  # (the colour most of *widget* is drawn in)
        image, seen = widget.grab().toImage(), {}
        for x in range(0, image.width(), 2):
            for y in range(0, image.height(), 2):
                name = image.pixelColor(x, y).name()
                seen[name] = seen.get(name, 0) + 1
        return max(seen, key=seen.get)

    assert most(viewer) == page["page_bg"]
    assert most(viewer.reload_button) == page["code_bg"] and most(viewer.back_button) == page["code_bg"]
    assert viewer.view.outline.isVisible() and most(viewer.view.outline) == page["page_bg"]
    assert most(viewer.find_field) == page["page_bg"]
    bar = viewer.grab().toImage()  # (the toolbar's row, left of the first button: the window's ground)
    assert bar.pixelColor(3, viewer.reload_button.mapTo(viewer, viewer.reload_button.rect().center()).y()).name() \
        == page["page_bg"]
    themes("auto")
    assert until(lambda: viewer.view._ground is None and viewer.styleSheet() == "", TB.READY_SECONDS)
    viewer.close()


def test_happy_in_axross_the_application_s_theme_rules_the_window(tmp_path, themes, monkeypatch):
    """axross's built-in viewer: its window is the application's (axross's own theme) - only the page and its
    scroll bars take the page's theme."""
    from axross_markdown._ax.ui import markdown_theme_ui as TU

    monkeypatch.setattr(TU, "standalone", lambda: False)
    viewer = _viewer(tmp_path, LONG_PAGE, True)
    themes("dark")
    assert _in_theme(viewer, "dark")
    pump(0.2)
    assert viewer.styleSheet() == ""
    assert viewer.view.browser.verticalScrollBar().styleSheet() != ""
    viewer.close()


def test_guard_the_window_s_theme_on_a_big_page_holds_no_turn(tmp_path, themes, monkeypatch):
    """The window's style sheet with a page of 10,000 sections laid out: no turn of the switch over the
    budget."""
    from tests.test_markdown_reader_bugs25 import _sections
    from axross_markdown._ax.ui import markdown_theme_ui as TU

    monkeypatch.setattr(TU, "standalone", lambda: True)
    viewer = _viewer(tmp_path, _sections(10000), True)
    viewer.view.load_rest_now()
    assert until(lambda: not viewer.view.more() and not viewer.view._scheduled, 10 * TB.READY_SECONDS)
    pump(0.3)
    beat = HB.Heartbeat()
    themes("slate")
    assert _in_theme(viewer, "slate")
    assert until(lambda: viewer.styleSheet() != "", TB.READY_SECONDS)
    pump(0.3)
    turn, gap = beat.stop()
    viewer.close()
    HB.assert_turn(turn, "the window's theme")
    HB.assert_responsive(gap, "the window's theme")


def test_sad_a_link_in_a_summary_is_a_link():
    """A link inside a folded <details>' <summary> was bold text: its address gone, a click folded. It is a
    link of its own between the two halves of the summary's fold now."""
    text = ('<details><summary>Sum <a href="http://x.y/s">the link</a> tail</summary>\n\nbody\n\n</details>\n\n'
            '<details open><summary><a href="http://x.y/o">first</a></summary>\n\nshown\n\n</details>\n')
    view = _view(text, True)
    fragments = {fragment: fmt for fragment, fmt, _block in _fragments(view.browser.document())}
    assert fragments["the link"].anchorHref() == "http://x.y/s" and fragments["the link"].fontUnderline()
    assert fragments["the link"].fontWeight() >= 600
    assert fragments["first"].anchorHref() == "http://x.y/o"
    fold = H.FOLD
    assert fragments["▸ Sum "].anchorHref() == f"#{fold}1" and fragments[" tail"].anchorHref() == f"#{fold}1"
    assert not fragments["▸ Sum "].fontUnderline()
    assert "body" not in view.browser.document().toPlainText() and "shown" in view.browser.document().toPlainText()
    view.close()


# -- Find: Unicode's normal forms, characters no reader sees -----------------------------------------------------

COMPOSED = "caf\u00e9"
DECOMPOSED = "cafe\u0301"
FIND_PAGE = (f"One {COMPOSED} and one {DECOMPOSED} and a third {DECOMPOSED.upper()}.\n\n"
             "They co\u00adoperate and cooperate; zero\u200bwidth here.\n\n"
             f"한글 and {unicodedata.normalize('NFD', chr(0xd55c) + chr(0xae00))} written in parts.\n\n"
             + "filler words \n\n" * 40 + f"The last {DECOMPOSED} of the page.\n")


@PARSERS
def test_sad_find_matches_across_normal_forms_and_soft_hyphens(tmp_path, full):
    """"café" typed (composed) found one of two where the page had it once composed and once with a combining
    accent; a soft hyphen inside a word hid it from Find. Find compares the text in one normal form and
    without the characters no reader sees - and every selection and mark is the page's own characters of the
    match, the accent and the soft hyphen with them."""
    viewer = _viewer(tmp_path, FIND_PAGE, full)
    browser = viewer.view.browser
    for typed in (COMPOSED, DECOMPOSED):
        cursor = browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        browser.setTextCursor(cursor)
        viewer.find_field.setText(typed)
        assert until(lambda: browser.textCursor().hasSelection() and getattr(viewer, "_marks", None), TB.READY_SECONDS)
        pump(0.05)
        seen = []
        for _press in range(5):
            seen.append(browser.textCursor().selectedText())
            viewer.find_next()
            pump(0.05)
        assert seen == [COMPOSED, DECOMPOSED, DECOMPOSED.upper(), DECOMPOSED, COMPOSED], (typed, seen)
        assert viewer.find_count.text() == "2 of 4"
        assert [mark.cursor.selectedText() for mark in viewer._marks] \
            == [COMPOSED, DECOMPOSED, DECOMPOSED.upper(), DECOMPOSED]
        viewer.find_next(backward=True)
        pump(0.05)
        viewer.find_next(backward=True)
        pump(0.05)
        assert browser.textCursor().selectedText() == DECOMPOSED and viewer.find_count.text() == "4 of 4"
        viewer.find_field.setText("")
        pump(0.2)
    for typed, wanted in (("cooperate", ["co\u00adoperate", "cooperate"]), ("co\u00adoperate", ["co\u00adoperate", "cooperate"]),
                          ("zerowidth", ["zero\u200bwidth"]),
                          ("한글", ["한글", unicodedata.normalize("NFD", "한글")])):
        cursor = browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        browser.setTextCursor(cursor)
        viewer.find_field.setText(typed)
        assert until(lambda: browser.textCursor().hasSelection() and getattr(viewer, "_marks", None), TB.READY_SECONDS)
        pump(0.05)
        assert [mark.cursor.selectedText() for mark in viewer._marks] == wanted, typed
        assert browser.textCursor().selectedText() == wanted[0]
        viewer.find_field.setText("")
        pump(0.2)
    viewer.find_field.setText("cafe")  # (no accent typed: "café" is another word, written either way)
    assert until(lambda: viewer.find_count.text() == "no match", TB.READY_SECONDS)
    viewer.close()


def test_edge_a_match_is_the_page_s_own_characters():
    """The skeleton Find looks in and the page's text: every match's place gives back, compared the same way,
    the needle - across the pieces the text is read in, with accents at a piece's end, a letter of thousands
    of marks, emoji joined by joiners; a text read on from where it changed is the text read anew."""
    from axross_markdown._ax.ui import markdown_view as MV

    piece = MV.SKELETON_PIECE
    texts = [
        ("x" * (piece - 3) + DECOMPOSED + " and " + COMPOSED + "y" * piece + DECOMPOSED) * 3,
        ("ab\u00ad" * piece) + "co\u00adop " + DECOMPOSED,
        "a" + "\u0301" * 5000 + " café " + "e\u0323\u0301 " * 300 + DECOMPOSED,
        "\U0001f468\u200d\U0001f469\u200d\U0001f467 fam ❤\ufe0f " * 700 + DECOMPOSED,
        "Å and a\u030a and å " * 500 + "שׁ\u05b8 " * 40 + DECOMPOSED,
        "plain ascii only " * 500,
        "café composed only " * 500,
    ]
    needles = [COMPOSED, "e\u0301", "co\u00adop", "coop", "ab", "å", "\U0001f469", "❤", "fam", "y" + DECOMPOSED,
               "a\u0301", "ệ", "composed", "ש"]
    for text in texts:
        folded = text.lower()
        skeleton = MV._Skeleton()
        skeleton.update(folded, 0)
        while not skeleton.more(0.005):
            pass
        key = skeleton.text()
        assert key == MV._find_key(folded) or len(key) == len(MV._find_key(folded))
        for needle in needles:
            wanted = MV._find_key(needle.lower())
            at, found = key.find(wanted), 0
            while at >= 0 and found < 50:
                begin, end = skeleton.span(at, at + len(wanted))
                assert 0 <= begin < end <= len(folded)
                if needle == "ש":  # (a letter written as one character with its dot: all of that character)
                    assert MV._find_key(folded[begin:end]).startswith(wanted)
                else:
                    assert MV._find_key(folded[begin:end]) == wanted, (needle, folded[begin:end])
                assert skeleton.index_of(begin) == at
                found += 1
                at = key.find(wanted, at + len(wanted))
            assert (found > 0) == (wanted in key)
        # (the text grown at its end, read on from there: as read anew)
        grown = folded + " and more " + DECOMPOSED + " at the end"
        skeleton.update(grown, len(folded) - 5)
        while not skeleton.more(0.005):
            pass
        fresh = MV._Skeleton()
        fresh.update(grown, 0)
        fresh.more(60)
        assert skeleton.text() == fresh.text() and skeleton.pieces == fresh.pieces
    plain = MV._Skeleton()
    plain.update("only ascii", 0)
    assert plain.done and plain.text() == "only ascii" and plain.span(5, 10) == (5, 10)


def test_guard_find_on_5_mb_written_with_combining_accents_holds_no_turn(tmp_path):
    """Find on a page of 5 MB whose every accent is a combining one (the text Find compares differs from the
    page's everywhere): typed, next, back, a needle that is nowhere - no turn of the window over the budget.
    A text this long is read for Find in turns of its own; the find waits for it and goes on."""
    para = unicodedata.normalize("NFD", "Päragraph {n} café déjà vu naïve text co\u00adoperate here.\n\n")
    count = 5_000_000 // len(para.encode("utf-8"))
    viewer = _viewer(tmp_path, "".join(para.replace("{n}", str(n)) for n in range(count)), True)
    view = viewer.view
    view.load_rest_now()
    assert until(lambda: not view.more() and not view._scheduled, 10 * TB.READY_SECONDS)
    pump(0.3)
    beat = HB.Heartbeat()
    viewer.find_field.setText("zzz-nowhere")
    assert until(lambda: viewer.find_count.text() == "no match", TB.READY_SECONDS)
    assert until(lambda: view._skeleton_kept.done, TB.READY_SECONDS)  # (read in turns of its own: Find waits)
    viewer.find_field.setText(COMPOSED)
    assert until(lambda: view.browser.textCursor().selectedText() == DECOMPOSED, TB.READY_SECONDS)
    first = view.browser.textCursor().selectionStart()
    viewer.find_next()
    pump(0.2)
    assert view.browser.textCursor().selectedText() == DECOMPOSED and view.browser.textCursor().selectionStart() > first
    viewer.find_next(backward=True)
    pump(0.2)
    assert view.browser.textCursor().selectionStart() == first
    viewer.find_field.setText("cooperate")
    assert until(lambda: view.browser.textCursor().selectedText() == "co\u00adoperate", TB.READY_SECONDS)
    viewer.find_field.setText("nowhere-" + COMPOSED)
    assert until(lambda: viewer.find_count.text() == "no match", TB.READY_SECONDS)
    pump(0.2)
    turn, gap = beat.stop()
    viewer.close()
    HB.assert_turn(turn, "Find on 5 MB of combining accents")
    HB.assert_responsive(gap, "Find on 5 MB of combining accents")


# -- names for the toolbar's signs, an image's alt text ------------------------------------------------------------

def test_sad_the_toolbar_s_signs_and_the_find_field_have_names(tmp_path):
    """"←", "→", "−" and "+" were named by their sign alone, the find field had no name (its placeholder goes
    with the first letter typed): each has an accessible name in words and a tooltip."""
    from PyQt6.QtWidgets import QPushButton

    viewer = _viewer(tmp_path, "# T\n\ntext\n", True)
    signs = {button.text(): button for button in viewer.findChildren(QPushButton)
             if button.text() in ("←", "→", "−", "+")}
    assert len(signs) == 4
    for sign, button in signs.items():
        assert len(button.accessibleName()) > 3 and sign not in button.accessibleName(), sign
        assert button.toolTip().startswith(button.accessibleName()), sign
    assert len({button.accessibleName() for button in signs.values()}) == 4
    assert viewer.find_field.accessibleName() and viewer.find_field.toolTip()
    assert viewer.zoom_reset.accessibleDescription()
    viewer.close()


def test_sad_an_image_s_alt_text_is_its_tooltip_and_its_format_s():
    """An image said nothing of itself but its picture (U+FFFC in the text): its alt text is its tooltip now -
    its title where it has one - and the image format's alt text; a raw <img>'s too."""
    text = ('Before ![A red square](pic.png) after.\n\n![alt two](two.png "The title")\n\n![](none.png)\n\n'
            '[![linked](l.png)](http://x.y/)\n\n<img src="raw.png" alt="raw alt">\n')
    page = _html(text)
    assert '<img src="pic.png" alt="A red square" title="A red square" />' in page
    assert 'alt="alt two" title="The title"' in page and '<img src="none.png" alt="" />' in page
    assert 'alt="raw alt" title="raw alt"' in page
    assert ' title="A red square"' not in H.export_html(MD.parse(text))  # (a browser shows the alt text itself)
    document = QTextDocument()
    document.setHtml(page)
    images = {fmt.toImageFormat().name(): fmt for _text, fmt, _block in _fragments(document) if fmt.isImageFormat()}
    assert images["pic.png"].toolTip() == "A red square"
    assert images["pic.png"].property(QTextFormat.Property.ImageAltText) == "A red square"
    assert images["two.png"].toolTip() == "The title"
    assert images["two.png"].property(QTextFormat.Property.ImageAltText) == "alt two"
    assert images["none.png"].toolTip() == ""
    assert images["l.png"].toolTip() == "linked" and images["l.png"].anchorHref() == "http://x.y/"
    assert images["raw.png"].toolTip() == "raw alt"


# -- GFM's small items ---------------------------------------------------------------------------------------------

def test_sad_a_bare_ftp_address_is_a_link():
    """GFM's extended autolinks: "ftp://foo.bar.baz" was text."""
    page = _html("ftp://foo.bar.baz\n\nsee ftp://foo.bar.baz/x?y=1. And ftp://nohost and sftp://a.b/c.\n")
    assert '<a href="ftp://foo.bar.baz">ftp://foo.bar.baz</a>' in page
    assert '<a href="ftp://foo.bar.baz/x?y=1">ftp://foo.bar.baz/x?y=1</a>.' in page
    assert "ftp://nohost and sftp://a.b/c" in page
    assert _kinds("`ftp://foo.bar.baz`\n")[0] == ["ftp://foo.bar.baz"]


def test_sad_a_struck_link_is_struck():
    """"~~www.a.org/s~~" was a link without the strike (the link's "no decoration" took it)."""
    view = _view("~~www.a.org/s~~ and ~~[text](http://x.y/)~~ and ~~plain~~ and [link](http://x.y/l)\n", True)
    fragments = {text: fmt for text, fmt, _block in _fragments(view.browser.document())}
    for text in ("www.a.org/s", "text"):
        assert fragments[text].fontStrikeOut() and fragments[text].fontUnderline() and fragments[text].anchorHref()
    assert fragments["plain"].fontStrikeOut() and not fragments["plain"].fontUnderline()
    assert not fragments["link"].fontStrikeOut() and fragments["link"].fontUnderline()
    view.close()


@pytest.mark.parametrize("text, numbers", [
    ("1. foo\n2.\n3. bar\n", ["1.", "2.", "3."]),
    ("5. x\n6.\n7.\n8. y\n", ["5.", "6.", "7.", "8."]),
    ("- foo\n-\n- bar\n", None),
])
def test_sad_an_empty_list_item_is_drawn(text, numbers):
    """An item of nothing was not drawn, and an ordered list numbered on without it: "1. foo / 2. / 3. bar"
    showed 1 and 2."""
    view = _view(text, True)
    block, items = view.browser.document().begin(), []
    while block.isValid():
        if block.textList() is not None:
            items.append((block.textList().itemText(block), block.text().strip()))
        block = block.next()
    assert len(items) == text.count("\n"), items
    if numbers is not None:
        assert [number for number, _text in items] == numbers
    assert [shown for _number, shown in items if shown] == [word for word in ("foo", "x", "bar", "y") if word in text]
    view.close()


def test_sad_a_raw_ordered_list_begins_at_its_start():
    """Raw HTML's <ol start="3"> began at 1 (the attribute was not kept); what is no number is still dropped."""
    view = _view('<ol start="3">\n<li>a</li>\n<li>b</li>\n</ol>\n', True)
    block, items = view.browser.document().begin(), []
    while block.isValid():
        if block.textList() is not None:
            items.append((block.textList().itemText(block), block.text().strip()))
        block = block.next()
    assert items == [("3.", "a"), ("4.", "b")]
    view.close()
    assert '<ol start="42">' in _html('<ol start="42"><li>a</li></ol>\n')
    for bad in ('start="x"', 'start="-1"', 'start="1e3"', 'start="12345678901"', "start='3\" onclick=\"x'"):
        assert "<ol>" in _html(f"<ol {bad}><li>a</li></ol>\n"), bad
