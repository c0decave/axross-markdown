# axross-markdown

axross's Markdown viewer on its own: GitHub Markdown with an outline, footnotes, highlighted code and local images - shown, never run.

A Markdown file rendered in a window of its own - or in the terminal. The full set:
CommonMark, GitHub's tables (aligned as written), task lists, strike-through and
autolinks, footnotes, definition lists, YAML / TOML front matter; the headings as an
outline beside the text, fenced code coloured by Pygments, the images beside the file
(clickable when linked), colours for light and dark themes, find (Ctrl+F), zoom
(Ctrl + / - / 0), Reload (F5). Edit (F4) opens an editor with the rendering beside the text, following the
typing. A link to another Markdown file opens it; a web link opens in the browser only
after a question that shows its real address.

What a file holds is shown, never run: raw HTML is kept to a safe subset (no scripts,
styles, frames, forms or event handlers - what is left of it shown as its text), nothing is loaded from
the network (a remote image is a box naming its address), images are read only relative
to the file - regular files, never a secret file such as an SSH key, bounded in size,
pixels and count; an SVG that names other files is not shown.

```sh
axross-markdown README.md docs/*.md     # a window for each
axross-markdown                         # a window with Open... (Ctrl+O)
axross-mdcat README.md                  # in the terminal, in colour (no Qt needed)
axross-mdcat --toc README.md            # the headings only
cat notes.md | axross-mdcat -
```

In the terminal: headings, emphasis, inline and fenced code (coloured), quotes, nested
and task lists, tables drawn with box characters (wrapped to fit), definition lists and
footnotes; links are terminal hyperlinks (OSC 8) with their address beside them;
images are drawn with kitty's or iTerm2's picture protocol where the terminal has one,
else in coloured half-blocks. Colours follow NO_COLOR / FORCE_COLOR / COLORTERM
(`--color`), the theme the background (`--theme`), long texts go through `less -R`
(`--no-pager`). Nothing in a file can send the terminal an escape sequence of its own.

The Markdown view started as the Markdown viewer of
[sandbox-ai](https://github.com/c0decave/sandbox-ai)'s Files page (MIT, the same
author), ported to PyQt6 and axross's backends.

It is the same code as in [axross](https://github.com/c0decave/axross), written out by
axross's `scripts/export_standalone.py markdown`; its settings are axross's
(`~/.config/axross`), so both share the language, the theme and the tool's state.

## Install and run

```sh
pip install axross-markdown      # or, from this folder: pip install .
axross-markdown
```

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

## Tests

```sh
python -m pytest tests
```

## Licence

Apache-2.0, as axross.
