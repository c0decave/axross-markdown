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
- [Updates](#updates)
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
| Alt+V | The View menu: the page's theme, the window's theme |
| Alt+H | The Help menu: Check for Updates…, Updates |
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

*View > Theme* (Alt+V) colours the page - its ground, text, headings, links, code and the
code's syntax, quotes, tables, alerts, formulas and the selection - in one of twelve
themes, or **Automatic**: Light or Dark as the window is.

| Theme | Ground | Text | Links |
|---|---|---|---|
| Light | light `#ffffff` | 15.8:1 | 5.2:1 |
| Dark | dark `#0d1117` | 16.0:1 | 6.1:1 |
| Sepia | light `#f4ecd8` | 11.1:1 | 6.6:1 |
| Solar Light | light `#fdf6e3` | 5.9:1 | 5.8:1 |
| Solar Dark | dark `#002b36` | 6.7:1 | 6.7:1 |
| Arctic | dark `#2e3440` | 10.3:1 | 6.2:1 |
| Retro | dark `#282828` | 10.7:1 | 5.5:1 |
| Night Violet | dark `#282a36` | 13.4:1 | 10.3:1 |
| High Contrast Light | light `#ffffff` | 21.0:1 | 11.5:1 (AAA) |
| High Contrast Dark | dark `#000000` | 21.0:1 | 12.8:1 (AAA) |
| Slate | dark `#282c34` | 8.4:1 | 6.4:1 |
| Paper | light `#f8f6f0` | 15.9:1 | 7.5:1 |

Every theme's body text and links reach WCAG AA (4.5:1) on its ground, the High Contrast
ones AAA (7:1); the numbers are the contrast ratios (a test measures every theme, and every
other text colour of it). The names say what a theme looks like: Solar is Solarized-like,
Arctic Nord-like, Retro a warm Gruvbox-like palette, Night Violet Dracula-like and Slate
One-Dark-like. Every open window changes with the choice, kept in
`~/.config/axross-markdown/settings.json` (`page_theme`). A switch is one change: the page
stays in its old colours until it is made anew in the new ones (no flash, no blank page
between), and switches faster than one in 0.4 s are taken together - the last of them
counts.

*View > Window Theme*: the window's own colours - **Modern (follow system)** (light or dark
as the desktop's colour scheme is, and anew when it changes; light when the desktop does
not say), Modern Light, Modern Dark, Classic, Light Mode (the desktop's own palette),
Hacker and Amber - kept in the same file (`theme`); without one, the theme chosen in
axross is taken, if axross is installed.

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
| `--theme NAME` | A theme of the window's (`--list-themes`), its ground painted behind the text; `auto` (the default): the terminal's own ground, colours for dark or light (COLORFGBG, else dark). Default: `$AXROSS_MDCAT_THEME`, else `terminal_theme` in the settings |
| `--list-themes` | The themes, with the contrast of their text and links and a sample |
| `--background auto/on/off` | Paint the theme's ground (auto: for a theme, not for `auto`) |
| `--images auto/kitty/iterm/blocks/none` | Pictures with kitty's or iTerm2's protocol, in coloured half-blocks, or none |
| `--image-width N` | Columns a picture may take |
| `--no-links` | No terminal hyperlinks (OSC 8) |
| `--pager` / `--no-pager` | Always / never page with `less -R` |
| `--toc` | The headings only, with their anchors |
| `--watch` | Draw the file anew whenever it changes (Ctrl+C ends); a file not there yet is said and waited for |
| `--version` | The version |
| `--check-update`, `--update`, `--update-mode off/notify/auto` | The updates ([below](#updates)) |

With 256 colours a theme's colours are the nearest that keep their contrast on the
nearest ground; with 16 the terminal's own colours are used and no ground is painted;
`NO_COLOR` (or `--color never`) means none at all.

Headings, emphasis, inline and fenced code (coloured), quotes and alerts, nested and task
lists, tables drawn with box characters (wrapped to fit; a long one drawn as it goes, a
row after the other when it cannot fit), definition lists, footnotes, math as text;
links are terminal hyperlinks with their address beside them. A long text is drawn a
part at a time - the first part at once, inline footnotes (`^[...]`) or not. Nothing in
a file can send the terminal an escape sequence of its own.

- At most 200 pictures a text, as in the window; then a line says the rest are not drawn.
- It stops as soon as the program it writes into has ended (`axross-mdcat big.md | head`).
- Output that cannot be written (a full disk) is said; the exit status is 1.

## Updates

The one-file programs - the Linux binary and the AppImage, the macOS binary, Windows'
`axross-markdown.exe` and `axross-mdcat.exe` - update themselves from the GitHub releases.
*Help > Updates*: **Off**, **Tell me about new versions** (the default) or **Install new
versions automatically**; the window asks GitHub at its start and every 24 hours, always on a
thread of its own - it never waits for the network. *Help > Check for Updates…* asks at once.
Without a window:

```sh
axross-markdown --check-update          # is a newer release out?
axross-markdown --update                # install it (axross-mdcat --update on Windows)
axross-markdown --update-mode off       # or notify, auto
```

A pip or pipx install is never replaced: it is told `pip install -U axross-markdown`. The
terminal view asks no network itself; it says (on standard error, in a terminal) when the
last check found a newer version. `AXROSS_MARKDOWN_NO_UPDATE_CHECK=1` keeps the automatic
checks off whatever the setting says.

Before anything is replaced:

- every request and every redirect goes over https to GitHub's hosts only (`api.github.com`,
  `github.com`, `release-assets.githubusercontent.com`, `objects.githubusercontent.com`),
  each answer bounded in size (the program at most 400 MiB);
- the release is strictly newer than the running program - and the file has the release's
  version in its name (`axross-markdown-0.17.1-linux-x86_64`): an older release's file can
  never stand for a newer one;
- `SHA256SUMS.sig` is a valid Ed25519 signature of `SHA256SUMS` by the release key whose
  public half the program pins (no signature, another key: refused before the program is
  fetched); the file has its entry there, the size the release states and that SHA-256;
- no archive is fetched or unpacked: the files are the bare programs.

The new program is written beside the running one, hashed again and run once
(`--self-test`: it must start here and say its version - a release that cannot run on this
system never replaces this one), then put in place with one rename; the old one stays as
`axross-markdown.previous` for a minute of the new one's running. On Windows the running
program is renamed aside first (it may be renamed, not overwritten). The AppImage file
itself (`$APPIMAGE`) is replaced, never by the plain binary. Should the program in place
not be the file checked, the old one is put back. It takes effect at the next start. The
macOS app (`axross Markdown.app`) is not changed in place - its program is part of its
signed seal: the notice points to the release's disk image.

How a release is signed: the release workflow makes a draft; the maintainer signs its
`SHA256SUMS` on their own machine and publishes it (`scripts/sign_release.py release
vX.Y.Z --key KEY --publish`) - the key never comes near CI.

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
- Updates: tried against a fake GitHub (its API, its redirects, signed and badly signed
  releases) and on Linux; the Windows replacement and the macOS binary's are not tried on
  those systems yet. A release before 0.17.0 has no signature: 0.16.x is updated by hand once.
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
(`~/.config/axross`) for the language and - until View → Window Theme chooses one in
`~/.config/axross-markdown/settings.json` - the window's theme. The page's theme (View → Theme), the terminal's (`terminal_theme`) and the updates (`update_mode`) are kept in that file too.

## The exact, reviewed dependencies

`requirements.lock.txt` pins every dependency (extras included) to one version and the
SHA-256 of its files. Each pin passed axross's supply-chain gate - PyPI, OSV advisories
and malicious-package entries, a minimum age of 14 days, typosquatting, provenance, and a
review of the files' content recorded in axross's baseline - and the CI runs the gate
again on every push (`supply-chain-gate.toml`). To install exactly those files:

```sh
pip install --require-hashes -r requirements.lock.txt
pip install --no-build-isolation --no-deps .
```

