"""The twenty-first round of the Markdown reader (the twentieth review): each
stall fixed for its whole class - a stress test puts the hostile shape into
every container (top level, a table's cell, a heading, a list, a quote, an
alert, a footnote, a definition, a <details>) - YAML coloured again, the
editor's preview in long texts, display math in an alert, the release's
children checked, and the small things. Each test failed before, with the
dependencies of the shipped lock.
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

from tests.test_markdown_reader_bugs11 import pump, until  # noqa: E402
from tests.test_markdown_reader_bugs20 import _settle, _Turns  # noqa: E402

APP = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _closed_after():
    yield
    for widget in APP.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    _settle()


def _view(text: str, full: bool = True, size=(1000, 800)):
    from axross_markdown._ax.ui import markdown_view as MV

    view = MV.MarkdownView(None)
    view.full = view.full and full
    view.resize(*size)
    view.show()
    view.render(text)
    assert until(lambda: view._readable and view.markdown, 120)
    until(lambda: not view._scheduled and not view.status.text().startswith("Rendering"), 120)
    pump(0.2)
    return view


# -- M1. every common language coloured (a token type its style leaves out: its parent's) ----------

SAMPLES = {
    "yaml": "name: build\non:\n  push:\n    branches: [main]\nretries: 3\n",
    "python": "def f(x):\n    return x + 1  # one\n",
    "json": '{"a": [1, 2.5, true, null], "b": "text"}\n',
    "toml": '[tool.x]\nname = "y"\ncount = 3\n',
    "bash": 'for f in *.md; do echo "$f"; done\n',
    "javascript": "const a = 1;\nfunction g() { return a; }\n",
    "typescript": "let n: number = 4;\n",
    "html": '<a href="x">t</a>\n',
    "css": "body { color: #fff; }\n",
    "c": "int main(void) { return 0; }\n",
    "cpp": "#include <vector>\nint x = 1;\n",
    "java": "public class A { int x = 1; }\n",
    "go": "package main\nfunc main() { x := 1 }\n",
    "rust": "fn main() { let x: u8 = 3; }\n",
    "sql": "SELECT a FROM t WHERE b = 1;\n",
    "ruby": "def f; puts 'x'; end\n",
    "php": "<?php echo $x; ?>\n",
    "diff": "--- a\n+++ b\n-old\n+new\n",
    "ini": "[s]\nkey = value\n",
    "dockerfile": "FROM python:3.12\nRUN pip install x\n",
    "makefile": "all:\n\techo hi\n",
    "xml": '<a b="c">d</a>\n',
}


@pytest.mark.parametrize("lang", sorted(SAMPLES))
def test_sad_every_common_language_is_coloured_in_the_reader(lang):
    """A YAML block was never coloured - window, --html, axross-mdcat: the lexing child's style lookup
    raised KeyError for Token.Literal.Scalar.Plain (a type the style leaves out), the block fell back
    to plain."""
    from axross_markdown._ax.core import markdown_doc as MD
    from axross_markdown._ax.core import markdown_term as T
    from axross_markdown._ax.ui import markdown_html as H

    code = SAMPLES[lang]
    tokens = MD.code_tokens(code, lang)
    assert tokens is not None, lang
    html = H._highlight(code, lang, False)
    assert html and 'style="color: #' in html, (lang, html)
    terminal = T.render(f"```{lang}\n{code}```\n", T.Options(depth="truecolor"))
    assert "\x1b[38;2;" in terminal, lang


def _colour_at(view, word: str) -> str:
    """The colour *word* is drawn in: the highlighter's (Qt's own parser) or its text's own."""
    found = view.browser.document().find(word)
    assert not found.isNull(), word
    block, at = found.block(), found.selectionStart() - found.block().position()
    for piece in block.layout().formats():
        if piece.start <= at < piece.start + piece.length:
            return piece.format.foreground().color().name()
    return found.charFormat().foreground().color().name()


@pytest.mark.parametrize("full", [True, False], ids=["markdown-it", "md4c"])
def test_sad_a_yaml_block_is_coloured_in_the_window(full):
    view = _view("```yaml\n" + SAMPLES["yaml"] + "```\n", full)
    assert _colour_at(view, "retries") != _colour_at(view, "build")  # (a key coloured, a plain scalar not)


@pytest.mark.parametrize("lang", ["yaml", "python", "toml", "json"])
def test_sad_the_editor_colours_every_common_language(lang):
    """axross's editor (ui.code_editor) had the same lookup: a YAML file was never coloured."""
    from pygments.lexers import get_lexer_by_name
    from pygments.styles import get_style_by_name
    from pygments.token import Token

    from axross_markdown._ax.core.lex_worker import style_of
    from axross_markdown._ax.ui import code_editor as CE

    assert style_of(get_style_by_name("default"), Token.Literal.Scalar.Plain) is not None
    editor = CE.CodeEditor()
    try:
        editor.set_language(get_lexer_by_name(lang).name)
        editor.setPlainText(SAMPLES[lang] * 3)
        assert until(lambda: any(block.layout().formats() for block in _blocks(editor.document())), 30), lang
    finally:
        editor.deleteLater()


def _blocks(document):
    block = document.begin()
    while block.isValid():
        yield block
        block = block.next()
