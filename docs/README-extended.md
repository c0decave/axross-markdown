# axross-markdown: the extended README

Everything on one page; the short version, with the screenshots, is the [README](../README.md) - installing, the tests and the licence are there.

axross's Markdown viewer on its own: GitHub Markdown with an outline, footnotes, highlighted code and local images - shown, never run.

A Markdown file rendered in a window of its own - or in the terminal. The full set:
CommonMark, GitHub's tables (aligned as written), task lists, strike-through and
autolinks, footnotes, alerts, definition lists, YAML / TOML front matter, math; the
headings as an outline beside the text, fenced code coloured by Pygments, the images
beside the file (clickable when linked). Edit (F4) opens an editor with the rendering
beside the text, following the typing. A link to another Markdown file opens it; a web
link opens in the browser only after a question that shows its real address.

- [The window: keys](#the-window-keys)
- [Export and print](#export-and-print)
- [Themes](#themes)
- [In the terminal: axross-mdcat](#in-the-terminal-axross-mdcat)
- [The security model](#the-security-model)
- [Limits](#limits)
- [Install options](#install-options)
- [Where it comes from](#where-it-comes-from)
- [The exact, reviewed dependencies](#the-exact-reviewed-dependencies)

## The window: keys

| Key | What it does |
|---|---|
| Ctrl+O | Open Markdown files, each in a window of its own |
| Ctrl+F | Find - every match marked, their count beside the field |
| Enter / Shift+Enter, F3 / Shift+F3 | The next / the previous match (into a folded `<details>` too) |
| Esc | End the find |
| Alt+Left / Alt+Right | Back / Forward through the files and headings visited |
| Ctrl++ / Ctrl+- / Ctrl+0 | Larger / smaller / the original size (the button between − and + shows the size in per cent; a click: the original size) |
| Ctrl+Home / Ctrl+End | The page's start / its end (a long page laid out up to there first) |
| Ctrl+A, Ctrl+C | Select all, copy - tables a row a line, their cells apart by tabs; a formula as its TeX |
| F5 | Read the file and its images again (a file changed on disk is read again by itself) |
| F4 | Edit: the file in an editor, the rendering beside the text - after a pause at the line typed at |
| Ctrl+P | Print |
| Alt+V | The View menu: the theme |
| Ctrl+M | Maximise the window, or back |

A right click on a code block copies the block as written; on a heading, a link to it as
GitHub writes it (`#the-heading`). The outline (the button *Outline*) jumps to a heading;
a window narrower than 700 pixels hides it until asked for.

## Export and print

*Export* (the button) saves the page as **HTML** - one file of its own: the images beside
the Markdown file put inside it, every other image a box naming it, a Content Security
Policy that lets it load nothing, relative links (`notes.md`) kept, any other link that is
no http(s), mailto or `#anchor` link its text - or as **PDF** (A4, light colours), or
**prints** it. A box that crosses a page break (an alert, a code block) is drawn between
the page margins on both pages. A long page is made a part at a time off the window's thread, with a
progress window and *Cancel*. From the command line, without a window:

```sh
axross-markdown --html notes.md > notes.html
```

## Themes

*View > Theme* (Alt+V): **Modern (follow system)** - light or dark as the desktop's
colour scheme is, and anew when it changes; light when the desktop does not say - Modern
Light, Modern Dark, Classic, Light Mode (the desktop's own palette), Hacker and Amber.
The choice is kept in `~/.config/axross-markdown/settings.json` (`$XDG_CONFIG_HOME` when
set); without one, the theme chosen in axross is taken, if axross is installed. The
page, its code and its formulas follow the theme.

## In the terminal: axross-mdcat

```sh
axross-mdcat README.md                  # in colour, through less -R when it is long
axross-mdcat --toc README.md            # the headings only
cat notes.md | axross-mdcat -           # standard input
axross-markdown --term README.md        # the same, from the window's program
```

| Option | What it does |
|---|---|
| `-w N`, `--width N` | Columns (default: the terminal's, at most 100; at least 20) |
| `--color auto/always/never/truecolor/256/16` | Colours (auto follows NO_COLOR, FORCE_COLOR, COLORTERM and whether it is a terminal) |
| `--theme auto/dark/light` | Colours for a dark or a light background (auto: COLORFGBG, else dark) |
| `--images auto/kitty/iterm/blocks/none` | Pictures with kitty's or iTerm2's protocol, in coloured half-blocks, or none |
| `--image-width N` | Columns a picture may take |
| `--no-links` | No terminal hyperlinks (OSC 8) |
| `--pager` / `--no-pager` | Always / never page with `less -R` |
| `--toc` | The headings only, with their anchors |
| `--watch` | Draw the file anew whenever it changes (Ctrl+C ends); a file not there yet is said and waited for |
| `--version` | The version |

Headings, emphasis, inline and fenced code (coloured), quotes and alerts, nested and task
lists, tables drawn with box characters (wrapped to fit; a long one drawn as it goes, a
row after the other when it cannot fit), definition lists, footnotes, math as text;
links are terminal hyperlinks with their address beside them. A long text is drawn a
part at a time - the first part at once, inline footnotes (`^[...]`) or not. Nothing in
a file can send the terminal an escape sequence of its own.

- At most 200 pictures a text, as in the window; then a line says the rest are not drawn.
- It stops as soon as the program it writes into has ended (`axross-mdcat big.md | head`).
- Output that cannot be written (a full disk) is said; the exit status is 1.

## The security model

What a file holds is shown, never run:

- **Raw HTML** is kept to a safe subset - no scripts, styles, frames, forms, event
  handlers or `javascript:` / `vbscript:` / `file:` / `data:` links (but data: images);
  what is left of it is shown as its text.
- **Nothing from the network**: a remote image is a box with its alt text (its address in
  the box's tooltip); no page, font or style sheet is fetched.
- **Images** are read only relative to the file, regular files only, never a secret file
  (an SSH key, a keyring, a password store), bounded in bytes (8 MiB), pixels (40 million
  one, 100 million a page) and count (200); an SVG that names other files is not shown,
  and an SVG is drawn in a process of its own that is ended after 10 seconds. A PDF or
  PostScript file is never taken for a picture.
- **Links**: a Markdown file opens in the window; any other link asks first, showing
  the real address (a host of look-alike letters in punycode, as it really is).
- **The terminal** gets no control character of the file: no escape sequence of its own.
- A text that would hold the window up (a table of a million cells, lists nested
  thousands deep, a formula nested a thousand deep) is shown as written or flatter,
  said in a notice - never a frozen window, never a blank page.

## Limits

- 8 MiB of a file are read (the rest: said at the end).
- Math is drawn as text and tables - fractions, roots, sums and integrals with their
  limits, matrices, cases, aligned lines, colours, accents - not by TeX: what it does not
  know is shown as written; a formula nested more than 64 groups deep is shown as
  written, with a note.
- A table of more than 64 columns is shown as written (in the window also one of more
  than 300,000 cells); lists nested more than 16 levels and quotes more than 8 are shown
  flatter.
- Mermaid, PlantUML, GeoJSON and STL blocks are shown as their source.
- Code is coloured in a process of its own; a block that takes longer than 5 seconds is
  shown without colours.
- An emoji short code (`:tada:`) of an emoji no installed font has stays as written.
- A file that is no text (a picture, a program) is said to be one, not shown.
- What would hold the window up is laid out shorter: a line of more than 100,000
  characters without a space is not laid out (a note says so; the editor shows it); a
  heading's or a table cell's text past 2,000 characters is cut, with "…"; a footnote's
  ways back to its references are shown for the first 20 ("and 99,980 more").

## Install options

```sh
pip install axross-markdown              # or: pipx install axross-markdown
pip install "axross-markdown[linkify]"   # bare addresses linked as GitHub links them
```

- **Python 3.11 or newer** with PyQt6 6.6 to 6.11, markdown-it-py, mdit-py-plugins,
  Pygments and Pillow (installed with it).
- **One-file programs without Python** from the
  [latest release](https://github.com/c0decave/axross-markdown/releases/latest): Linux
  x86-64 (also as an AppImage), macOS arm64 (also as a disk image with the app) and
  Windows x64, with `SHA256SUMS`. On Windows the viewer is a window program (no console
  window beside it) and the terminal view a console program of its own, `axross-mdcat.exe`
  (or `axross-markdown --term` from a console).
- **The exact, reviewed dependencies**: `requirements.lock.txt` (below).
- On Linux the window needs Qt's system libraries (EGL, xkbcommon, fontconfig, D-Bus,
  xcb-cursor); a missing one is named with the package that brings it. `axross-mdcat`
  and `--html` need none of them.

The Markdown view started as the Markdown viewer of
[sandbox-ai](https://github.com/c0decave/sandbox-ai)'s Files page (MIT, the same
author), ported to PyQt6 and axross's backends.

## Where it comes from

It is the same code as in [axross](https://github.com/c0decave/axross), written out by
axross's `scripts/export_standalone.py markdown`; it reads axross's settings
(`~/.config/axross`) for the language and - until View → Theme chooses one in
`~/.config/axross-markdown/settings.json` - the theme.

## The exact, reviewed dependencies

`requirements.lock.txt` pins every dependency (extras included) to one version and the
SHA-256 of its files. Each pin passed axross's supply-chain gate - PyPI, OSV advisories
and malicious-package entries, a minimum age of 14 days, typosquatting, provenance, and a
review of the files' content recorded in axross's baseline - and the CI runs the gate
again on every push (`supply-chain-gate.toml`). To install exactly those files:

```sh
pip install --require-hashes -r requirements.lock.txt
pip install --no-deps .
```

