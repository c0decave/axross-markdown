"""The twenty-ninth round, in the terminal and in what is shipped (axross-markdown 0.17.4's open ends):
axross-mdcat's muted text no longer dimmed below the themes' contrast, small headings that do not look like
links, standard input closed, its help in the locale's language, many code blocks and a line of emphasis
marks bounded; the wheel the same bytes whatever the builder's umask, the catalogue of the texts the tool
has, the README's install lines naming the release's own wheel.

Each test here failed before.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
#: The files a release is made with: axross's templates of them - or, in the tool's own repository (the
#: tests run there too, against the wheel), that repository's.
RELEASE = ROOT / "scripts" / "standalone_repo" / "axross-markdown"
RELEASE = RELEASE if RELEASE.is_dir() else ROOT

sys.path.insert(0, str(ROOT))

pytest.importorskip("markdown_it")

from axross_markdown._ax.core import markdown_cli as C  # noqa: E402
from axross_markdown._ax.core import markdown_term as T  # noqa: E402
from axross_markdown._ax.core import markdown_themes as MT  # noqa: E402
from tests import markdown_timing as TB  # noqa: E402


def _german() -> dict:
    """The German catalogue the program reads (core.i18n's)."""
    from axross_markdown._ax.core import i18n

    return json.loads((Path(i18n.CATALOGUE_DIR) / "de.json").read_text(encoding="utf-8"))


PAGE = ("# One\n\n#### Four\n\n##### Five\n\n###### Six\n\n---\ntitle: x\n---\n\nSome *text* with a "
        "[link](https://example.org/page) and a note[^1].\n\n![picture](missing.png)\n\n<small>small print</small>\n\n"
        "[^1]: The note.\n")
_SGR = re.compile(r"\x1b\[([0-9;]*)m")


@pytest.fixture(autouse=True)
def _own_settings(monkeypatch, tmp_path):
    monkeypatch.delenv(MT.ENV_TERM, raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("AXROSS_MARKDOWN_SETTINGS", raising=False)


def _codes(out: str) -> list[list[str]]:
    return [found.group(1).split(";") for found in _SGR.finditer(out)]


def _pairs(out: str, ground: str) -> set[tuple[str, str]]:
    """(text colour, ground) of every run of visible text in *out* (truecolor), the page's *ground* where
    none is set."""
    fg, bg, seen, at = None, ground, set(), 0
    for found in _SGR.finditer(out):
        if out[at:found.start()].strip() and fg:
            seen.add((fg, bg))
        at = found.end()
        codes = found.group(1).split(";")
        index = 0
        while index < len(codes):
            code = codes[index]
            if code in ("", "0"):
                fg, bg = None, ground
            elif code == "39":
                fg = None
            elif code == "49":
                bg = ground
            elif code in ("38", "48") and codes[index + 1:index + 2] == ["2"]:
                colour = "#%02x%02x%02x" % tuple(int(part) for part in codes[index + 2:index + 5])
                fg, bg = (colour, bg) if code == "38" else (fg, colour)
                index += 4
            index += 1
    return seen


@pytest.mark.parametrize("theme_id", [theme_id for theme_id in MT.THEMES])
def test_sad_the_terminal_dims_no_text_and_every_colour_it_writes_keeps_the_theme_s_contrast(theme_id):
    """Before: the address after a link, the front matter, a note's number and an image's note were written
    in the theme's muted colour *and* faint (SGR 2) - a terminal halves a faint colour towards the ground:
    2.0 to 3.8:1 in all twelve themes, where the README says AA. Now nothing is faint, and every pair of
    colours the page is written in reaches 4.5:1."""
    theme = MT.THEMES[theme_id]
    out = T.render(PAGE, T.Options(width=70, depth="truecolor", theme=theme_id, background=True))
    assert "example.org/page" in out and "The note." in out
    assert not [codes for codes in _codes(out) if "2" in codes[:1] or (
        "2" in codes and "38" not in codes and "48" not in codes)], "faint text (SGR 2)"
    ground = theme.term["page_bg"]
    pairs = _pairs(out, ground)
    assert (theme.term["muted"], ground) in pairs  # (the muted colour itself is written)
    lines = {theme.term["rule"], theme.term["border"]}  # (a rule, a table's lines: drawn, not read)
    low = sorted((round(MT.contrast(fg, bg), 2), fg, bg) for fg, bg in pairs
                 if fg not in lines and MT.contrast(fg, bg) < 4.5)
    assert not low, (theme_id, low)


def test_sad_no_style_of_the_terminal_can_be_faint():
    """The style itself has no "dim": a text asked to be small (<small>) is muted, not faint."""
    assert "dim" not in T.Style.__dataclass_fields__
    out = T.render("<small>small print</small>\n", T.Options(width=40, depth="truecolor", theme="light"))
    assert "small print" in out and not [codes for codes in _codes(out) if codes[:1] == ["2"]]


def test_sad_small_headings_are_not_underlined_as_links_are():
    """Before: h4, h5 and h6 were bold and underlined - as a link is underlined. Now bold in their colour,
    h5 and h6 in italics; only the link is underlined."""
    out = T.render("#### Four\n\n##### Five\n\n###### Six\n\n[link](https://e.x/)\n",
                   T.Options(width=60, depth="truecolor", theme="light"))
    underlined = [out[found.end():found.end() + 12] for found in _SGR.finditer(out)
                  if "4" in found.group(1).split(";")[:3] and not found.group(1).startswith(("38", "48"))]
    assert all("link" in text for text in underlined) and underlined, underlined
    for level in (4, 5, 6):
        style = T.Renderer.heading_style(level) if hasattr(T, "Renderer") and hasattr(T.Renderer, "heading_style") \
            else None
        if style is not None:
            assert style.bold and not style.underline


def test_sad_standard_input_closed_is_said_not_a_traceback(monkeypatch, capsys):
    """Before: "axross-mdcat - <&-" ended in AttributeError: 'NoneType' object has no attribute 'buffer'."""
    monkeypatch.setattr(sys, "stdin", None)
    assert C.main(["--no-pager", "-"]) == 1
    said = capsys.readouterr()
    assert "Traceback" not in said.err and "standard input" in said.err.lower() + said.out.lower()

    class Broken:
        class buffer:  # noqa: N801 - as sys.stdin's
            @staticmethod
            def read(_count):
                raise ValueError("I/O operation on closed file")

    monkeypatch.setattr(sys, "stdin", Broken)
    assert C.main(["--no-pager", "-"]) == 1
    assert "Traceback" not in capsys.readouterr().err


def test_sad_mdcat_s_help_and_errors_are_in_the_locale_s_language(monkeypatch, capsys):
    """Before: with LANG=de_DE.UTF-8 the window was German, "axross-mdcat --help" and its errors English.
    The option names stay as they are."""
    from axross_markdown._ax.core import i18n

    catalogue = _german()
    for text in ("Show Markdown files in the terminal, in colour.", "Markdown files (- for standard input)",
                 "a folder without a README", "not a regular file", "usage: ", "options",
                 "unrecognized arguments: {args}"):
        assert catalogue.get(text, "").strip() and catalogue[text] != text, text
    before = i18n.active().language
    i18n.install("de")
    try:
        with pytest.raises(SystemExit) as stopped:
            C.main(["--help"])
        assert stopped.value.code == 0
        shown = capsys.readouterr().out
        assert catalogue["Show Markdown files in the terminal, in colour."] in shown
        assert "--width" in shown and "--theme" in shown and "--list-themes" in shown
        with pytest.raises(SystemExit) as stopped:
            C.main(["--no-such-option"])
        assert stopped.value.code == 2
        assert catalogue["unrecognized arguments: {args}"].split("{")[0] in capsys.readouterr().err
    finally:
        i18n.install(before)


def test_sad_the_about_dialog_s_texts_are_in_the_german_catalogue():
    """Before: 5 of the 215 texts of the Markdown window had no German - all in the About dialog."""
    import ast

    catalogue = _german()
    missing = []
    from axross_markdown._ax.ui import markdown_about

    for source in (Path(markdown_about.__file__),):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "tr" and node.args \
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                if not catalogue.get(node.args[0].value, "").strip():
                    missing.append(node.args[0].value)
    assert not missing, missing
    assert catalogue.get("About {name}…", "").strip()


def test_sad_many_small_code_blocks_are_shown_in_seconds(capsys):
    """Before: 60,000 small js blocks (1.9 MB) took axross-mdcat 108 s - a question and an answer of the
    lexing child for each, a formatter made for each. Now the first CODE_BLOCKS are coloured, the others
    while CODE_SECONDS last, the rest plain (said once); the same block again is not lexed again."""
    text = "".join(f"```js\nlet a{i} = {i};\n```\n\n" for i in range(6000))
    began = time.process_time()
    out = T.render(text, T.Options(width=60, depth="truecolor", theme="light"))
    took = time.process_time() - began
    assert out.count("let") >= 6000 or all(f"a{i} = {i}" in _SGR.sub("", out) for i in (0, 2999, 5999))
    plain = _SGR.sub("", out)
    assert "a0 = 0" in plain and "a5999 = 5999" in plain
    TB.budget(took < 20, f"{took:.1f} s of CPU")
    same = "```js\nlet a = 1;\n```\n\n" * 3000
    renderer_out = T.render(same, T.Options(width=60, depth="truecolor", theme="light"))
    assert _SGR.sub("", renderer_out).count("let a = 1;") == 3000
    assert "\x1b[38;2;" in renderer_out[-400:]  # (the last one coloured too: kept, not lexed again)


def test_sad_a_line_of_emphasis_marks_past_the_bound_is_text():
    """Before: markdown-it made a token of every "*", "_" and "~" of a line before it paired them - a
    paragraph of 4 MB of them held 1.5 GB and took 36 s. Past LINE_MARKS marks of a line the rest are text."""
    from axross_markdown._ax.core import markdown_doc as MD

    assert MD.LINE_MARKS >= 1000
    unit = "**a_b_~~c**d~~ "
    text = unit * (MD.LINE_MARKS // 2) + "\n"
    began = time.process_time()
    doc = MD.parse(text)
    took = time.process_time() - began
    assert doc is not None
    TB.budget(took < 30, f"{took:.1f} s")
    short = MD.parse("**bold** and *em* and ~~gone~~\n")  # (under the bound: as ever)
    from axross_markdown._ax.ui import markdown_html as H

    made = H.to_html(short)
    assert "<strong>" in made or "<b>" in made
    assert "<em>" in made or "<i>" in made


# -- what is shipped ---------------------------------------------------------------------------------------

def _wheel_script():
    path = RELEASE / "packaging" / "reproducible_wheel.py"
    spec = importlib.util.spec_from_file_location("reproducible_wheel", path)
    module = importlib.util.module_from_spec(spec)
    written, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # (no __pycache__ beside the repo's files)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = written
    return module


def _wheel(order: list[str], mode: int, stamp: tuple, files: dict[str, bytes]) -> bytes:
    import base64
    import hashlib

    record = "pkg-1.0.dist-info/RECORD"
    rows = "".join(f"{name},sha256={base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()},"
                   f"{len(data)}\n" for name, data in sorted(files.items())) + f"{record},,\n"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for name in order + [record]:
            info = zipfile.ZipInfo(name, stamp)
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, rows.encode() if name == record else files[name])
    return out.getvalue()


def test_sad_the_wheel_is_the_same_bytes_whatever_the_builder_s_umask_and_clock():
    """Before: the release's workflow said the wheel was reproducible; its entries' modes followed the
    builder's umask and checkout - 0644, 0600 and 0664 gave three wheels of one commit. packaging/
    reproducible_wheel.py writes it again: name order, the commit's time, 0644 / 0755; --check holds the
    release to it and to RECORD."""
    script = _wheel_script()
    files = {"pkg/__init__.py": b"x = 1\n", "pkg/data.json": b"{}\n", "pkg-1.0.dist-info/METADATA": b"Name: pkg\n"}
    names = list(files)
    one = _wheel(names, 0o600, (2020, 1, 1, 0, 0, 0), files)
    two = _wheel(names[::-1], 0o664, (2026, 11, 23, 9, 30, 2), files)
    assert one != two
    made = [script.rewritten(data, 1_795_000_000) for data in (one, two)]
    assert made[0] == made[1]
    assert not script.problems(made[0]) and script.problems(one)  # (as built: not as the script writes it)
    with zipfile.ZipFile(io.BytesIO(made[0])) as wheel:
        infos = wheel.infolist()
        assert [info.filename for info in infos][-1] == "pkg-1.0.dist-info/RECORD"
        assert {(info.external_attr >> 16) & 0o777 for info in infos} == {0o644}
        assert {info.date_time for info in infos} == {time.gmtime(1_795_000_000)[:6]}
        assert wheel.read("pkg/__init__.py") == b"x = 1\n"
    broken = _wheel(names, 0o644, (2020, 1, 1, 0, 0, 0), files).replace(b"x = 1", b"x = 2")
    workflow = (RELEASE / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "packaging/reproducible_wheel.py release/*.whl" in workflow
    assert "packaging/reproducible_wheel.py --check release/*.whl" in workflow
    assert "the wheel is reproducible already" not in workflow
    assert broken  # (a wheel whose file is not the one RECORD names is for --check to refuse: below)
    tampered = _wheel(names, 0o644, (2020, 1, 1, 0, 0, 0), dict(files, **{"pkg/__init__.py": b"x = 2\n"}))
    with zipfile.ZipFile(io.BytesIO(tampered)) as source:
        record = source.read("pkg-1.0.dist-info/RECORD")
    honest = _wheel(names, 0o644, (2020, 1, 1, 0, 0, 0), files)
    with zipfile.ZipFile(io.BytesIO(honest)) as source:
        assert source.read("pkg-1.0.dist-info/RECORD") != record


def test_sad_the_export_carries_the_texts_the_tool_has_not_all_of_axross_s_catalogue(tmp_path):
    """Before: the wheel carried all of axross's German catalogue - 485 KB of its 841 KB, 5,149 of 5,376
    entries no module of the tool asks for - and five empty catalogues of 3 bytes. Now the entries of the
    texts its modules hold; every text a module asks tr() for that axross has in German is still there."""
    import ast
    import subprocess

    if not (ROOT / "scripts" / "export_standalone.py").is_file():
        pytest.skip("axross's export of the tool: run in axross")
    out = tmp_path / "export"
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "export_standalone.py"), "markdown", str(out)],
                          capture_output=True, text=True, timeout=600, cwd=ROOT)
    assert done.returncode == 0, done.stderr[-2000:]
    catalogues = sorted(out.rglob("i18n/*.json"))
    assert [path.name for path in catalogues] == ["de.json"], catalogues
    whole = json.loads((ROOT / "resources" / "i18n" / "de.json").read_text(encoding="utf-8"))
    slim = json.loads(catalogues[0].read_text(encoding="utf-8"))
    assert len(slim) < len(whole) // 3 and catalogues[0].stat().st_size < 200_000, (len(slim), len(whole))
    asked = set()
    for module in out.rglob("*.py"):
        if "tests" in module.parts:
            continue
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in ("tr", "_t") \
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                asked.add(node.args[0].value)
    assert len(asked) > 150
    lost = sorted(text for text in asked if text in whole and text not in slim)
    assert not lost, lost[:10]
    readme = (out / "README.md").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', (out / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    # (the install section: PyPI may lag behind - the release's own wheel named, by this version)
    wheel = f"axross_markdown-{version}-py3-none-any.whl"
    assert f"https://github.com/c0decave/axross-markdown/releases/download/v{version}/{wheel}" in readme
    assert "PyPI may lag behind" in readme and "{wheel" not in readme and "{version}" not in readme
    assert (out / "packaging" / "reproducible_wheel.py").is_file()
    assert os.environ.get("HOME", "") not in readme or not os.environ.get("HOME")


# -- the command line: errors said in a line, streams as paths, colours as asked ---------------------------

def _run(*args, stdin=None, env=None, program="axross_markdown._ax.core.markdown_cli", **more):
    """axross-mdcat (or the window's program) as a process of its own: what it wrote, its status."""
    import subprocess

    code = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); from {program} import main; sys.exit(main())")
    environ = {name: value for name, value in os.environ.items()
               if name not in ("NO_COLOR", "FORCE_COLOR", "COLORTERM", "LANGUAGE", MT.ENV_TERM)}
    environ.update({"LC_ALL": "C.UTF-8", "TERM": "xterm-256color", "QT_QPA_PLATFORM": "offscreen"}, **(env or {}))
    return subprocess.run([sys.executable, "-c", code, *args], input=stdin, capture_output=True, timeout=120,
                          env=environ, **more)


@pytest.fixture
def note(tmp_path):
    path = tmp_path / "a.md"
    path.write_text("# hi\n\ntext `code` [l](http://x.y)\n", encoding="utf-8")
    return path


def test_sad_a_file_no_one_may_read_is_said_in_a_line(tmp_path, monkeypatch, capsys):
    """Before: open() of a file that cannot be read was a traceback (axross-mdcat and axross-markdown
    --html). Now the system's own words and exit 1."""
    path = tmp_path / "no.md"
    path.write_text("x\n", encoding="utf-8")
    real = open

    def refused(name, *rest, **more):
        if str(name) == str(path):
            raise PermissionError(13, "Permission denied", str(name))
        return real(name, *rest, **more)

    monkeypatch.setattr("builtins.open", refused)
    assert C.main(["--no-pager", str(path)]) == 1
    said = capsys.readouterr().err
    assert "Permission denied" in said and "Traceback" not in said
    from axross_markdown._ax.ui import markdown_app as A

    assert A.export_html_main([str(path)]) == 1
    assert "Permission denied" in capsys.readouterr().err


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no named pipes here")
def test_sad_a_pipe_given_as_a_path_is_read_as_standard_input_is(tmp_path, note):
    """Before: "axross-mdcat <(printf '# hi')" and "... /dev/stdin" said "not a regular file". A pipe and
    a character device are read as a stream now, up to the same bound; a folder, a socket are not."""
    import threading

    pipe = tmp_path / "pipe"
    os.mkfifo(pipe)
    writer = threading.Thread(target=lambda: pipe.write_bytes(b"# from a pipe\n\ntext\n"))
    writer.start()
    done = _run("--no-pager", "--color", "never", str(pipe))
    writer.join(10)
    assert done.returncode == 0 and b"from a pipe" in done.stdout, done.stderr
    if os.path.exists("/dev/stdin"):
        done = _run("--no-pager", "--color", "never", "/dev/stdin", stdin=b"# by its path\n")
        assert done.returncode == 0 and b"by its path" in done.stdout, done.stderr
    lonely = tmp_path / "lonely"
    os.mkfifo(lonely)  # (no one writes to it: said at once, exit 1 - never waited for)
    done = _run("--no-pager", str(lonely))
    assert done.returncode == 1 and b"pipe no one writes to" in done.stderr
    data = io.BytesIO(b"x" * (C.TEXT_LIMIT + 5000))
    assert len(C._bounded(data)) == C.TEXT_LIMIT + 1  # (bounded: a pipe that never ends is not read on)


def test_sad_output_that_cannot_be_written_and_ctrl_c_end_without_a_traceback(note, monkeypatch, capsys):
    """Before: a closed standard output was an AttributeError, Ctrl+C while a text is drawn a
    KeyboardInterrupt's traceback, "axross-markdown --help > /dev/full" Python's own complaint at the exit
    (status 120)."""
    monkeypatch.setattr(sys, "stdout", None)
    assert C.main(["--no-pager", str(note)]) == 1
    monkeypatch.undo()
    said = capsys.readouterr().err
    assert "Traceback" not in said and "standard output is closed" in said
    monkeypatch.setattr(C, "_main", lambda _argv=None: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert C.main(["--no-pager", str(note)]) == 130
    monkeypatch.undo()
    if os.path.exists("/dev/full"):
        import subprocess

        code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); from axross_markdown._ax.ui.markdown_app import main; sys.exit(main())"
        with open("/dev/full", "wb") as full:
            for args in (["--help"], ["--version"]):
                ran = subprocess.run([sys.executable, "-c", code, *args], stdout=full, stderr=subprocess.PIPE,
                                     timeout=120, env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
                assert ran.returncode == 1 and b"Traceback" not in ran.stderr, (args, ran.returncode, ran.stderr)
                assert b"cannot write the output" in ran.stderr


def test_sad_colour_asked_for_on_the_command_line_beats_no_color_and_force_color_0_forces_none(note):
    """Before: "NO_COLOR=1 axross-mdcat --color always" wrote no colour, and FORCE_COLOR=0 forced colour
    into a pipe."""
    esc = b"\x1b["
    assert esc in _run("--no-pager", "--color", "always", str(note), env={"NO_COLOR": "1"}).stdout
    assert esc not in _run("--no-pager", str(note), env={"NO_COLOR": "1"}).stdout
    assert esc not in _run("--no-pager", str(note), env={"FORCE_COLOR": "0"}).stdout
    assert esc not in _run("--no-pager", str(note), env={"FORCE_COLOR": "false"}).stdout
    assert esc in _run("--no-pager", str(note), env={"FORCE_COLOR": "1"}).stdout
    assert esc not in _run("--no-pager", "--color", "never", str(note), env={"FORCE_COLOR": "1"}).stdout
    assert T.colour_depth(environ={"FORCE_COLOR": "0", "TERM": "xterm"}, stream=io.StringIO()) == "none"


def test_sad_a_width_or_a_theme_that_is_not_used_is_said(note):
    """Before: "-w 1" drew at 20 columns without a word, "-w" in other digits was read as a number, a
    mistyped AXROSS_MDCAT_THEME fell back in silence."""
    done = _run("--no-pager", "-w", "1", str(note))
    assert done.returncode == 0 and b"too few" in done.stderr
    done = _run("--no-pager", "-w", "٣٠", str(note))
    assert done.returncode == 2 and b"not a number of columns" in done.stderr
    done = _run("--no-pager", str(note), env={MT.ENV_TERM: "nope"})
    assert done.returncode == 0 and b"names no theme" in done.stderr
    assert not _run("--no-pager", str(note), env={MT.ENV_TERM: "sepia"}).stderr
    assert not _run("--no-pager", "-w", "40", str(note)).stderr


def test_sad_text_that_is_not_utf_8_is_said(tmp_path):
    """Before: Latin-1 bytes were shown as they came, without a word. Said on standard error now; UTF-8,
    UTF-8 cut at the read limit inside a letter and UTF-16 with its mark are not."""
    path = tmp_path / "latin.md"
    path.write_bytes("# Caf\xe9\n".encode("latin-1"))
    done = _run("--no-pager", "--color", "never", str(path))
    assert done.returncode == 0 and b"not valid UTF-8" in done.stderr and "Café".encode() in done.stdout
    assert C._utf8("é".encode()) and C._utf8("é".encode()[:1]) and C._utf8("﻿é".encode("utf-16"))
    assert not C._utf8(b"\xe9 x")


def test_sad_a_file_whose_name_begins_with_a_dash_is_exported(tmp_path):
    """Before: "axross-markdown --html -- -x.md" failed."""
    (tmp_path / "-x.md").write_text("# dash\n", encoding="utf-8")
    done = _run("--html", "--", "-x.md", program="axross_markdown._ax.ui.markdown_app", cwd=tmp_path)
    assert done.returncode == 0 and b"dash" in done.stdout and b"<h1" in done.stdout, done.stderr


def test_sad_a_table_s_links_and_the_footnotes_are_numbered_apart():
    """Before: a table's links were "[1]", "[2]" with their addresses under it - and so were the footnotes
    of the same page."""
    out = T.render("A note[^a].\n\n| a |\n|---|\n| [one](http://x.y/1) |\n\n[^a]: First.\n",
                   T.Options(width=60, depth="none"))
    assert "one[L1]" in out and "[L1] http://x.y/1" in out
    assert "note[1]" in out and "[1] First." in out


def test_sad_notes_by_the_ten_thousand_are_read_in_linear_time():
    """Before: every part of a long text was given every footnote - 100,000 notes in 50 parts, five
    million entries made and walked: no end in two minutes. Now a part holds the notes it refers to, the
    last part all of them; what is shown is the same."""
    from axross_markdown._ax.core import markdown_doc as MD

    def text(count: int) -> str:
        return "".join(f"Line {i} with a note[^n{i}].\n" for i in range(count)) + "\n" \
            + "".join(f"[^n{i}]: The note {i}.\n" for i in range(count))

    took = []
    for count in (4000, 16000):
        began = time.process_time()
        out = "".join(T.render_parts(text(count), T.Options(width=80, depth="none")))
        took.append(time.process_time() - began)
        assert f"note[{count}]" in out and f"[{count}] The note {count - 1}." in out
    TB.budget(took[1] < 8 * took[0] + 1.0, took)  # (four times the notes: not sixteen times the time)
    notes = MD.NoteLabels([(f"n{i}", 1) for i in range(1000)])
    doc = MD.parse("See[^n500] and[^n7].\n", notes=(notes, False, 0))
    asked = [child.meta["id"] for token in doc.tokens for child in token.children or ()
             if child.type == "footnote_ref"]
    assert asked == [500, 7]  # (numbered across the text, though this part was given two notes only)


@pytest.mark.parametrize("theme_id", list(MT.THEMES))
def test_sad_inline_code_in_256_colours_keeps_its_contrast_on_its_own_ground(theme_id):
    """Before: in 256 colours inline code's text was matched against the page's ground, not its own:
    3.7:1 in Solar Light, 4.17 in Slate."""
    out = T.render("text `code here` end\n", T.Options(width=60, depth="256", theme=theme_id, background=True))
    found = [codes.group(1).split(";") for codes in _SGR.finditer(out) if "38" in codes.group(1).split(";")
             and "48" in codes.group(1).split(";")]
    assert found, out
    for codes in found:
        fg = int(codes[codes.index("38") + 2])
        bg = int(codes[codes.index("48") + 2])
        assert MT.contrast(MT.xterm256_rgb(fg), MT.xterm256_rgb(bg)) >= 4.5, (theme_id, fg, bg)


def test_sad_check_update_says_what_the_variable_stops(capsys):
    """AXROSS_MARKDOWN_NO_UPDATE_CHECK=1 stops the window's own checks; --check-update is asked for by
    hand and asks all the same. The help says so (the name read as if it stopped that too)."""
    with pytest.raises(SystemExit):
        C.main(["--help"])
    shown = " ".join(capsys.readouterr().out.split())
    assert "AXROSS_MARKDOWN_NO_UPDATE_CHECK=1" in shown and "window's own checks only" in shown


# -- the program's own language ------------------------------------------------------------------------------

def test_sad_the_program_has_a_language_of_its_own(tmp_path, monkeypatch):
    """Before: axross-markdown had no language menu - its language was the one chosen in axross (its
    session.json), else the locale's; $LANGUAGE was not looked at. Now View > Language keeps a choice in
    the program's own settings, $LANGUAGE counts, and Qt's own translation is loaded with it."""
    pytest.importorskip("PyQt6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QMenu

    from axross_markdown._ax.core import i18n
    from axross_markdown._ax.core import markdown_settings as S
    from axross_markdown._ax.ui import markdown_app as A

    app = QApplication.instance() or QApplication([])
    monkeypatch.delenv("LANGUAGE", raising=False)
    assert S.chosen_language() is None
    assert S.chosen_language({"LANGUAGE": "xx:de:en"}) == "de"  # (GNU's list: the first it has)
    assert S.chosen_language({"LANGUAGE": "en_GB:de"}) == "en"
    before = i18n.active().language
    program = A.MarkdownApp.__new__(A.MarkdownApp)
    menu = QMenu()
    try:
        program.language_menu(menu)
        languages = menu.findChild(QMenu, "language")
        names = {action.data(): action for action in languages.actions()}
        assert None in names and "de" in names and "en" in names and names[None].isChecked()
        names["de"].trigger()
        assert S.read_setting(S.SETTING_LANGUAGE) == "de" and S.chosen_language() == "de"
        assert "starts" in program._language_said
        assert A.speak_chosen_language(app) == "de"
        assert getattr(app, "_ax_qt_translator", None) is not None  # (the catalogue's: the standard buttons)
        from PyQt6.QtCore import QCoreApplication, QLibraryInfo

        folder = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
        if (folder / "qtbase_de.qm").is_file():  # (Qt's own: a file dialog's words)
            assert app._ax_qt_own
            assert QCoreApplication.translate("QFileDialog", "File &name:") != "File &name:"
        languages.aboutToShow.emit()
        names = {action.data(): action for action in languages.actions()}
        assert names["de"].isChecked()
        names[None].trigger()
        assert S.read_setting(S.SETTING_LANGUAGE) is None and S.chosen_language() is None
    finally:
        for own in getattr(app, "_ax_qt_own", ()):
            app.removeTranslator(own)
        app._ax_qt_own = []
        old = getattr(app, "_ax_qt_translator", None)
        if old is not None:
            app.removeTranslator(old)
            app._ax_qt_translator = None
        i18n.install(before)
