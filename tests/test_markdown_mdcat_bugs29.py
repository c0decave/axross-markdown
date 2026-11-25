"""The terminal view (axross-mdcat) after axross-markdown 0.17.4: muted text was dimmed as well (SGR 2) and
fell to 2.0 to 3.8:1 in every theme; h4 to h6 were underlined like links; a closed standard input ended in
a traceback; 60,000 small code blocks took 108 s and a paragraph of 4 MB of emphasis marks 1.5 GB; --help
and the errors stayed English under a German locale.

Each test here failed before.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tracemalloc
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("markdown_it")

from axross_markdown._ax.core import markdown_cli as C  # noqa: E402
from axross_markdown._ax.core import markdown_doc as MD  # noqa: E402
from axross_markdown._ax.core import markdown_term as T  # noqa: E402
from axross_markdown._ax.core import markdown_themes as MT  # noqa: E402

#: A page with every kind of text the terminal view colours: headings, links with their address, a note's
#: number, an image that is not there, front matter, alerts, a table, code with and without a language,
#: math, raw HTML's small and struck text.
SAMPLE = """---
title: a sample
---

# One `code` [link](https://example.org/a)

## Two

### Three

#### Four

##### Five

###### Six

Text *em* **strong** ~~struck~~ `inline` [a link](https://example.org/page) and <small>small print</small>
<mark>marked</mark> <kbd>Ctrl</kbd> <del>gone</del> <ins>new</ins> $x^2$ and a note[^1].

![missing](nope.png) ![data](data:text/plain;base64,AAAA) ![remote](https://example.org/x.png)

> quote **bold**

> [!NOTE]
> note text

> [!WARNING]
> warned

> [!CAUTION]
> careful

- item
  - [ ] open
  - [x] done

| a | b |
|---|---|
| [cell](https://example.org/cell) | 2 |

```python
def f(x):  # comment
    return "s" + 1
```

```
plain code
```

Term
: definition

[^1]: The note.
"""

_SGR = re.compile(r"\x1b\[([0-9;]*)m|\x1b\]8;;[^\x1b]*\x1b\\")


def _emitted(out: str):
    """[(foreground, ground, faint, character)] of every character *out* shows that is no space, as a
    terminal reads its SGR sequences (24-bit colours): what is emitted, not what a palette says."""
    fg = bg = None
    faint = False
    shown, at = [], 0
    for found in _SGR.finditer(out):
        shown += [(fg, bg, faint, ch) for ch in out[at:found.start()] if not ch.isspace()]
        at = found.end()
        if found.group(1) is None:  # (a hyperlink's OSC 8)
            continue
        values = found.group(1).split(";") if found.group(1) else ["0"]
        index = 0
        while index < len(values):
            value = values[index]
            if value in ("38", "48") and values[index + 1:index + 2] == ["2"]:
                colour = tuple(int(v) for v in values[index + 2:index + 5])
                fg, bg = (colour, bg) if value == "38" else (fg, colour)
                index += 5
                continue
            if value in ("", "0"):
                fg, bg, faint = None, None, False
            elif value == "2":
                faint = True
            elif value == "22":
                faint = False
            elif value == "39":
                fg = None
            elif value == "49":
                bg = None
            index += 1
    return shown + [(fg, bg, faint, ch) for ch in out[at:] if not ch.isspace()]


def _render(theme_id: str, text: str = SAMPLE) -> str:
    try:
        return T.render(text, T.Options(width=90, depth="truecolor", theme=theme_id, background=True,
                                        images="none"))
    finally:
        MD.close_code_pools()


# -- muted text ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("theme_id", list(MT.THEMES))
def test_sad_no_theme_colour_is_dimmed_and_every_emitted_pair_is_aa(theme_id):
    """Muted text - a link's address, the front matter, a note's number, an image's note - was written
    with SGR 2 (faint) as well: half its colour, 2.04:1 (Solar Light) to 3.77:1 (High Contrast Dark) on
    the theme's ground, while the contrast report measured the undimmed colour. Now no SGR 2 is written,
    and every letter and digit as emitted (--color=truecolor, the theme's ground) is at AA's 4.5:1 - the
    High Contrast themes' body text and links at AAA's 7:1, as the README says."""
    theme = MT.THEMES[theme_id]
    out = _render(theme_id)
    assert "‹https://example.org/page›" in T._strip_ansi(out) and "front matter" in out
    shown = _emitted(out)
    assert not [ch for _fg, _bg, faint, ch in shown if faint], "SGR 2 with a theme's colour"
    assert not re.search(r"\x1b\[(?:[0-9;]*;)?2(?:;(?!5;|2;)[0-9;]*)?m", _SGR.sub(
        lambda m: m.group(0) if not re.search(r"[34]8;[25];", m.group(0)) else "", out))
    text = [(fg, bg, ch) for fg, bg, _faint, ch in shown if ch.isalnum()]
    assert len(text) > 300
    unset = sorted({ch for fg, bg, ch in text if fg is None or bg is None})
    assert not unset, f"text in the terminal's own colours on a painted ground: {unset}"
    low = {(fg, bg, round(MT.contrast(fg, bg), 2)) for fg, bg, _ch in text if MT.contrast(fg, bg) < 4.5}
    assert not low, (theme_id, low)
    muted = MT.rgb(theme.term["muted"])
    assert muted in {fg for fg, _bg, _ch in text}  # (the muted colour is used - and measured above)
    if theme.aaa:
        body = {MT.rgb(theme.term["text"]), MT.rgb(theme.term["link"])}
        low = {(fg, bg, round(MT.contrast(fg, bg), 2)) for fg, bg, _ch in text
               if fg in body and MT.contrast(fg, bg) < 7.0}
        assert not low, (theme_id, low)


def test_sad_the_terminal_s_own_ground_gets_no_faint_text_either():
    """--theme auto (no ground painted), 256 and 16 colours: no SGR 2 there either - on a light terminal
    the faint grey of a link's address could not be read."""
    for options in (T.Options(depth="truecolor", dark=False, images="none"),
                    T.Options(depth="256", dark=True, images="none"),
                    T.Options(depth="16", dark=True, images="none"),
                    T.Options(depth="256", theme="sepia", background=True, images="none")):
        try:
            out = T.render(SAMPLE, options)
        finally:
            MD.close_code_pools()
        assert not [ch for _fg, _bg, faint, ch in _emitted(out) if faint], options
        for params in re.findall(r"\x1b\[([0-9;]*)m", out):
            plain = re.sub(r"[34]8;(?:2;\d+;\d+;\d+|5;\d+)", "", params)
            assert "2" not in plain.split(";"), (options.depth, params)


def test_happy_small_print_is_muted_not_faint():
    """Raw HTML's <small> was the one other user of SGR 2: now the theme's muted colour (measured)."""
    out = _render("light", "big <small>small print</small> big\n")
    theme = MT.THEMES["light"]
    colours = {ch: fg for fg, _bg, _faint, ch in _emitted(out)}
    assert colours["p"] == MT.rgb(theme.term["muted"]) and colours["b"] == MT.rgb(theme.term["text"])
    assert not hasattr(T.Style(), "dim")


def test_happy_the_toc_s_anchors_are_muted_not_faint(tmp_path, capsys):
    """--toc wrote each heading's anchor faint as well."""
    page = tmp_path / "t.md"
    page.write_text("# One\n\n## Two\n", encoding="utf-8")
    assert C._main(["--toc", "--color=truecolor", "--theme", "paper", "--no-pager", str(page)]) == 0
    out = capsys.readouterr().out
    assert "#two" in out and not [ch for _fg, _bg, faint, ch in _emitted(out) if faint]


# -- headings ------------------------------------------------------------------------------------------


def _styles(out: str, word: str) -> set[str]:
    """The SGR attributes (1 bold, 3 italic, 4 underlined) the line of *word* is written with."""
    line = next(line for line in out.split("\n") if word in T._strip_ansi(line))
    found = set()
    for params in re.findall(r"\x1b\[([0-9;]*)m", line):
        plain = re.sub(r"[34]8;(?:2;\d+;\d+;\d+|5;\d+)", "", params)
        found |= {value for value in plain.split(";") if value in ("1", "3", "4", "9")}
    return found


def test_sad_small_headings_are_not_underlined_like_links():
    """h4 to h6 were bold and underlined - the look of a link (underlined, in the link's colour). Now
    bold (h5, h6 in italics too), never underlined; a link in one keeps its underline."""
    out = _render("dark", "#### Four\n\n##### Five\n\n###### Six\n\ntext [a link](https://example.org/)\n\n"
                          "#### With [inside](https://example.org/i) it\n")
    assert _styles(out, "Four") == {"1"}
    assert _styles(out, "Five") == {"1", "3"} and _styles(out, "Six") == {"1", "3"}
    assert "4" in _styles(out, "a link") and "4" in _styles(out, "inside")
    for level in range(1, 7):
        assert not T.Renderer.heading_style(level).underline and T.Renderer.heading_style(level).bold
    theme = MT.THEMES["dark"].term  # (each level still its own colour)
    colours = {ch: fg for fg, _bg, _faint, ch in _emitted(out)}
    assert colours["F"] != colours["S"] and colours["S"] == MT.rgb(theme["h6"])


def test_edge_small_headings_without_colour_keep_their_mark():
    out = T.render("#### Four\n\ntext\n", T.Options(width=60, depth="none"))
    assert "· Four" in out and "\x1b" not in out


# -- standard input closed ---------------------------------------------------------------------------


#: Where the modules and their catalogues are: axross's tree - or the package of an export of the reader.
TREE = Path(C.__file__).resolve().parent.parent
_PROGRAM = "import sys\nfrom axross_markdown._ax.core.markdown_cli import main\nsys.exit(main())\n"


def _mdcat(*args: str, env: dict | None = None, **kwargs):
    """axross-mdcat run as a program of its own (English unless *env* names another locale)."""
    path = os.pathsep.join(p for p in (str(ROOT), os.environ.get("PYTHONPATH", "")) if p)
    environ = {**os.environ, "PYTHONPATH": path, "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8",
               "LC_MESSAGES": "C.UTF-8", "AXROSS_MARKDOWN_NO_UPDATE_CHECK": "1", **(env or {})}
    return subprocess.run([sys.executable, "-c", _PROGRAM, *args], capture_output=True, text=True,
                          timeout=120, cwd=str(ROOT), env=environ, **kwargs)


@pytest.mark.skipif(os.name != "posix", reason="a closed descriptor 0")
@pytest.mark.parametrize("args", [["-"], [], ["--no-pager", "-"], ["--toc", "-"]])
def test_sad_a_closed_standard_input_is_said_not_a_traceback(args):
    """``axross-mdcat - <&-``: sys.stdin is None, and the program ended in "AttributeError: 'NoneType'
    object has no attribute 'buffer'" (exit 1 by the traceback). Now a line on standard error, exit 1."""
    out = _mdcat(*args, preexec_fn=lambda: os.close(0))
    assert out.returncode == 1 and out.stdout == ""
    assert out.stderr.strip() == "axross-mdcat: -: standard input is closed: nothing to read"


def test_edge_a_standard_input_that_cannot_be_read_is_said(monkeypatch, capsys):
    """A descriptor that is open but gives an error (a folder as standard input): its error, exit 1."""
    class Broken:
        buffer = None

        def __init__(self):
            class Raw:
                def read(self, _count):
                    raise IsADirectoryError(21, "Is a directory")

            self.buffer = Raw()

    monkeypatch.setattr(sys, "stdin", Broken())
    assert C._read("-") == ("", "Is a directory")
    monkeypatch.setattr(sys, "stdin", None)
    assert C._read("-") == ("", C.NO_INPUT)


def test_happy_an_empty_and_a_piped_standard_input_still_work():
    out = _mdcat("--no-pager", "--color=never", "-", input="# Piped\n")
    assert out.returncode == 0 and "Piped" in out.stdout and out.stderr == ""
    out = _mdcat("-", input="")
    assert out.returncode == 0 and out.stderr == ""


# -- many code blocks -------------------------------------------------------------------------------


def test_sad_a_text_of_small_code_blocks_makes_one_formatter_and_ends_its_colouring(monkeypatch):
    """60,000 small ``js`` blocks (1.9 MB) took 108 s: Pygments' formatter was made anew for every block
    (half of the time) and each block was a question to the lexing child and its answer (the other half,
    0.3 to 0.9 ms each). Now the formatter is made once a text, and once more than CODE_BLOCKS blocks
    were lexed and that took CODE_SECONDS the rest are plain - said once, where the colours end."""
    import pygments.formatters as PF

    made = []
    original = PF.TerminalTrueColorFormatter.__init__

    def counted(self, **options):
        made.append(1)
        original(self, **options)

    monkeypatch.setattr(PF.TerminalTrueColorFormatter, "__init__", counted)
    asked = []

    def tokens(code, lang, style="default", seconds=None):
        from pygments.token import Keyword, Text

        asked.append(code)
        return [(Keyword, code[:3]), (Text, code[3:])]

    monkeypatch.setattr(MD, "code_tokens", tokens)
    monkeypatch.setattr(T, "CODE_BLOCKS", 40)
    ticks = iter(range(0, 10_000_000))
    monkeypatch.setattr(T.time, "monotonic", lambda: next(ticks) * 0.05)  # (each block "takes" 0.05 s)
    monkeypatch.setattr(T, "CODE_SECONDS", 3.0)
    text = "".join(f"```js\nlet x{i} = {i};\n```\n\n" for i in range(400))
    out = T.render(text, T.Options(width=80, depth="truecolor", theme="dark", background=True))
    assert len(made) == 1, "a formatter a block"
    assert len(asked) == 60  # (40 always, then until 3 s were spent: 60 x 0.05 s)
    plain = T._strip_ansi(out)
    assert plain.count("code blocks took more than 3 s: the rest are shown plain") == 1
    assert all(f"let x{i} = {i};" in plain for i in (0, 59, 60, 399)), "a block is missing"
    lines = out.split("\n")
    note = next(i for i, line in enumerate(lines) if "the rest are shown plain" in line)
    before = next(line for line in lines[:note] if "let x59 " in T._strip_ansi(line))
    after = next(line for line in lines[note:] if "let x60 " in T._strip_ansi(line))
    keyword = re.compile(r"\x1b\[[0-9;]*m" + "let")
    assert len(set(re.findall(r"38;2;\d+;\d+;\d+", before))) > len(set(re.findall(r"38;2;\d+;\d+;\d+", after)))
    assert keyword.search(before)


def test_happy_a_text_of_few_code_blocks_is_coloured_whatever_it_takes(monkeypatch):
    """The bound is for texts of thousands of blocks: up to CODE_BLOCKS are coloured however slow the
    machine is (a first block that waits for its child to start does not end the colours)."""
    monkeypatch.setattr(MD, "code_tokens", lambda code, lang, style="default", seconds=None: [
        (__import__("pygments.token").token.Keyword, code)])
    ticks = iter(range(0, 10_000_000))
    monkeypatch.setattr(T.time, "monotonic", lambda: next(ticks) * 60.0)  # (a minute a block)
    text = "".join(f"```js\nlet x{i};\n```\n\n" for i in range(30))
    out = T.render(text, T.Options(width=80, depth="truecolor", dark=True))
    assert "shown plain" not in out and out.count("\x1b[") > 60
    assert T.CODE_BLOCKS >= 200 and 1.0 <= T.CODE_SECONDS <= 10.0


def test_sad_the_same_block_again_is_not_lexed_again(monkeypatch):
    """One snippet 300 times: lexed 300 times. Now once (blocks of up to CODE_KEPT_CHARS characters are
    kept, CODE_KEPT of them) - across the parts a long text is rendered in, too."""
    asked = []

    def tokens(code, lang, style="default", seconds=None):
        from pygments.token import Name

        asked.append((lang, code))
        return [(Name, code)]

    monkeypatch.setattr(MD, "code_tokens", tokens)
    monkeypatch.setattr(T, "STREAM_ROWS", 200)  # (in parts of some 100 lines, as a long text is)
    monkeypatch.setattr(T, "STREAM_LINES", 100)
    text = "".join("```js\nsame();\n```\n\n```py\nsame();\n```\n\npara\n\n" for _ in range(300))
    parts = list(T.render_parts(text, T.Options(width=80, depth="truecolor", dark=True)))
    assert len(parts) > 1 and "".join(parts).count("same();") == 600
    assert sorted(asked) == [("js", "same();\n"), ("py", "same();\n")]
    asked.clear()
    big = "x = 1\n" * 1000  # (past CODE_KEPT_CHARS: not kept - lexed each time)
    T.render(f"```py\n{big}```\n\n```py\n{big}```\n", T.Options(width=80, depth="truecolor", dark=True))
    assert len(asked) == 2


# -- a paragraph of emphasis marks -------------------------------------------------------------------


def _marks_text(count: int) -> str:
    return ("**" + "a_" * 30 + "~~b**c~~ ") * count


def test_sad_a_paragraph_of_emphasis_marks_is_read_within_bounds():
    """``("**" + "a_"*30 + "~~b**c~~ ") * 60000`` (4.1 MB, one paragraph) peaked at 1.5 GB in axross-mdcat
    and in the window, 36 s before anything showed: markdown-it makes a token of every "*", "_" and "~"
    before it pairs them - 4 million tokens. Now a line's first LINE_MARKS marks are read as marks, the
    rest is text as written: the tokens and the memory of the parse no longer grow with the text."""
    small, large = _marks_text(1500), _marks_text(6000)  # (106 KB and 426 KB: the large one took 148 MB)
    peaks = []
    for text in (small, large):
        tracemalloc.start()
        try:
            doc = MD.parse(text)
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
        children = next(t for t in doc.tokens if t.type == "inline").children
        assert len(children) < 4 * MD.LINE_MARKS, len(children)
        assert "".join(c.content for c in children if c.type == "text").count("b") == text.count("b")
    assert peaks[1] < 40 << 20, f"{peaks[1] >> 20} MB for 426 KB"
    assert peaks[1] < 2 * peaks[0] + (8 << 20), peaks  # (four times the text: not four times the memory)


def test_happy_the_marks_after_the_bound_are_shown_as_written_and_nothing_is_lost():
    text = _marks_text(3000)
    out = T.render(text, T.Options(width=100, depth="none"))
    flat = out.replace("\n", " ")
    assert flat.count("b") == text.count("b") and flat.count("c") == text.count("c")
    assert "a_a_a_" in flat and "~~b**c~~" in flat  # (past the bound: as written)
    ordinary = "one *em* and **strong** and ~~struck~~ and ~one~ " * 50
    doc = MD.parse(ordinary)
    kinds = [c.type for c in next(t for t in doc.tokens if t.type == "inline").children]
    assert kinds.count("em_open") == 50 and kinds.count("strong_open") == 50 and kinds.count("s_open") == 100


@pytest.mark.parametrize("mark", ["*", "_", "~"])
def test_edge_one_run_of_marks_longer_than_the_bound_is_one_piece_of_text(mark):
    """A run of 300,000 "*" around a letter was 300,000 tokens in one call of the rule."""
    text = "x " + mark * 150_000 + "a" + mark * 150_000 + "\n"  # (not at the line's start: a fence, a rule)
    doc = MD.parse(text)
    children = next(t for t in doc.tokens if t.type == "inline").children
    assert len(children) < 50 and "".join(c.content for c in children).count(mark) == 300_000


def test_edge_marks_in_a_link_s_text_and_in_a_table_s_cells_count_by_line():
    """The bound is a line's (a paragraph, a cell, a heading): 30,000 short cells keep their emphasis."""
    rows = "| a | b |\n|---|---|\n" + "".join(f"| *e{i}* | **s{i}** |\n" for i in range(15_000))
    doc = MD.parse(rows)
    kinds = [c.type for t in doc.tokens if t.type == "inline" for c in t.children]
    assert kinds.count("em_open") == 15_000 and kinds.count("strong_open") == 15_000
    doc = MD.parse("[*label* and **more**](https://example.org/) ~~x~~\n")
    kinds = [c.type for c in next(t for t in doc.tokens if t.type == "inline").children]
    assert {"link_open", "em_open", "strong_open", "s_open"} <= set(kinds)


# -- the language of what the program says ---------------------------------------------------------------


GERMAN = {"LC_ALL": "", "LC_MESSAGES": "", "LANG": "de_DE.UTF-8"}


def test_sad_help_is_german_under_a_german_locale():
    """LANG=de_DE.UTF-8: the window's strings were German, ``axross-mdcat --help`` English. Now through
    tr() as the window's - the options keep their names."""
    out = _mdcat("--help", env=GERMAN)
    assert out.returncode == 0 and out.stderr == ""
    assert "Zeigt Markdown-Dateien im Terminal, in Farbe." in out.stdout
    assert out.stdout.startswith("Aufruf: axross-mdcat") and "\nOptionen:\n" in out.stdout
    for option in ("--width", "--color", "--theme NAME", "--list-themes", "--images", "--no-pager", "--toc",
                   "--watch", "--version", "--check-update", "--update-mode"):
        assert option in out.stdout, option
    assert "nur die Überschriften auflisten" in out.stdout and "list the headings only" not in out.stdout
    english = _mdcat("--help")
    assert english.stdout.startswith("usage: axross-mdcat") and "list the headings only" in english.stdout
    assert "Show Markdown files in the terminal, in colour." in english.stdout and "\noptions:\n" in english.stdout


def test_sad_errors_are_german_under_a_german_locale(tmp_path):
    binary = tmp_path / "b.bin"
    binary.write_bytes(b"\x00\x01\x02" * 100)
    out = _mdcat(str(tmp_path), str(binary), env=GERMAN)
    assert out.returncode == 1
    assert f"axross-mdcat: {tmp_path}: ein Ordner ohne README" in out.stderr
    assert "keine Textdatei (sie enthält Binärdaten) – nicht angezeigt" in out.stderr
    out = _mdcat("--bogus", env=GERMAN)
    assert out.returncode == 2 and "axross-mdcat: Fehler: unbekannte Argumente: --bogus" in out.stderr
    out = _mdcat("-w", "abc", "x.md", env=GERMAN)
    assert out.returncode == 2 and "Argument -w/--width: keine Spaltenzahl: abc" in out.stderr
    out = _mdcat("--theme", "nope", "x.md", env=GERMAN)
    # (the choices as the standard library lists them: quoted - "'sepia'" - on Python 3.11, not on 3.12)
    assert out.returncode == 2 and re.search(r"axross-mdcat: Fehler: Argument --theme: ungültige Auswahl: 'nope' "
                                             r"\(möglich: ('?)auto\1, \1light\1, .*\1sepia\1", out.stderr), out.stderr
    out = _mdcat("--watch", "-", env=GERMAN)
    assert out.returncode == 2 and "--watch zeigt eine Datei (nicht die Standardeingabe)" in out.stderr
    if os.name == "posix":
        out = _mdcat("-", env=GERMAN, preexec_fn=lambda: os.close(0))
        assert out.returncode == 1 and "die Standardeingabe ist geschlossen" in out.stderr


def test_happy_errors_stay_english_without_a_german_locale(tmp_path):
    """The words programs and the tests read stay as they were: English under C, POSIX and en_US, and
    --version and --self-test in every language."""
    for env in ({}, {"LC_ALL": "POSIX"}, {"LC_ALL": "en_US.UTF-8"}, {"LC_ALL": "", "LANG": "fr_FR.UTF-8"}):
        out = _mdcat(str(tmp_path), "--bogus", env=env)
        assert out.returncode == 2 and "axross-mdcat: error: unrecognized arguments: --bogus" in out.stderr, env
        out = _mdcat(str(tmp_path), env=env)
        assert out.returncode == 1 and "a folder without a README" in out.stderr, env
    for args in (["--version"], ["--self-test"]):
        german, english = _mdcat(*args, env=GERMAN), _mdcat(*args)
        assert german.returncode == 0 and german.stdout == english.stdout and german.stdout.startswith("axross-mdcat ")


def test_edge_lc_all_outranks_lang_and_the_language_goes_back(tmp_path):
    """LC_ALL=de over LANG=en; LC_ALL=C leaves LANG its say (POSIX's neutral locale names no language).
    A program that runs main() in its own process keeps the language it had."""
    out = _mdcat(str(tmp_path), env={"LC_ALL": "de_AT.UTF-8", "LANG": "en_US.UTF-8"})
    assert "ein Ordner ohne README" in out.stderr
    from axross_markdown._ax.core import i18n

    before = i18n.active().language
    restore = C._language({"LANG": "de_DE.UTF-8"})
    try:
        assert i18n.active().language == "de" and i18n.tr("a folder without a README") == "ein Ordner ohne README"
    finally:
        restore()
    assert i18n.active().language == before
    assert C._language({"LANG": "C"})() is None and i18n.active().language == before


def test_guard_every_text_the_terminal_program_says_has_its_german():
    """Every text core.markdown_cli hands to tr() - as a literal, through a name (BINARY, NO_INPUT) or its
    table of argparse's complaints - and the About dialog's (five were missing: "About {name}…" and the
    licence texts stayed English) is in the German catalogue, with the same placeholders."""
    import ast
    import json

    german = json.loads((TREE / "resources" / "i18n" / "de.json").read_text(encoding="utf-8"))
    wanted = {C.BINARY, C.NO_INPUT, *(text for _pattern, text in C._ARGPARSE_ERRORS)}
    for rel in ("core/markdown_cli.py", "ui/markdown_about.py", "ui/markdown_app.py"):
        tree = ast.parse((TREE / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "tr" and node.args \
                    and isinstance(node.args[0], ast.Constant):
                wanted.add(node.args[0].value)
    assert len(wanted) > 50 and "About {name}…" in wanted and "About {name}" in wanted
    missing = sorted(text for text in wanted if not german.get(text, "").strip())
    assert not missing, missing
    fields = re.compile(r"\{[a-z_]*\}")
    wrong = [text for text in wanted if sorted(fields.findall(text)) != sorted(fields.findall(german[text]))]
    assert not wrong, wrong
    assert german["About {name}…"] == "Über {name}…"


def test_guard_the_editor_s_menus_have_their_german():
    """The editor's menus (F4) hand their texts to tr() through a helper (``self._action(menu, "&Save",
    ...)``) and a table: sixteen of them - "&New", "&Open…", "&Save", "&Undo", "&Find…" - were in no
    catalogue and stayed English in a German window. Every one has its German now, and no two entries
    of a menu share their Alt letter."""
    import ast
    import json

    german = json.loads((TREE / "resources" / "i18n" / "de.json").read_text(encoding="utf-8"))
    tree = ast.parse((TREE / "ui" / "editor_window.py").read_text(encoding="utf-8"))
    menus: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "_action" and len(node.args) > 1 \
                and isinstance(node.args[1], ast.Constant) and isinstance(node.args[0], ast.Name):
            menus.setdefault(node.args[0].id, []).append(node.args[1].value)
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple):  # (the Edit menu's table)
            menus.setdefault("edit", []).extend(
                item.elts[0].value for item in node.iter.elts
                if isinstance(item, ast.Tuple) and item.elts and isinstance(item.elts[0], ast.Constant)
                and isinstance(item.elts[0].value, str) and "&" in item.elts[0].value)
    texts = [text for entries in menus.values() for text in entries]
    assert {"&New", "&Save", "&Close Tab", "&Undo", "Select &All", "&Find…", "&Wrap Lines"} <= set(texts)
    missing = sorted(text for text in texts if not german.get(text, "").strip())
    assert not missing, missing
    for menu, entries in menus.items():
        letters = [german[text][german[text].index("&") + 1].lower() for text in entries if "&" in german[text]]
        assert len(letters) == len(set(letters)), (menu, [german[text] for text in entries])
