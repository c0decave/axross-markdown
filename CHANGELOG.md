# Changelog

What changed in each release of axross-markdown. The code is axross's
Markdown viewer (https://github.com/c0decave/axross), written out by axross's
`scripts/export_standalone.py markdown`.

## 0.16.0 - 2026-11-19

The first public release.

- **A Markdown file in a window of its own:** CommonMark with GitHub's tables
  (aligned as written), task lists, strike-through, autolinks, footnotes,
  definition lists and YAML / TOML front matter; the headings as an outline
  beside the text, fenced code coloured by Pygments, local images beside the
  file, light and dark themes, find (Ctrl+F), zoom (Ctrl + / - / 0), Reload
  (F5), Edit (F4) with the rendering beside the text.
- **Formulas:** TeX in `$...$` and `$$...$$` (and GitHub's `` $`...`$ ``) in
  display style - fractions, roots, matrices, large operators with limits,
  stacked `\overset` / `\underset` / `\cfrac` in display formulas; Copy takes a
  formula as its TeX.
- **In the terminal:** `axross-mdcat FILE.md` (or `axross-markdown --term`)
  draws tables with box characters, coloured code, hyperlinks (OSC 8) and
  images (kitty, iTerm2 or half-blocks), `--toc` lists the headings, `--watch`
  follows a file; `axross-markdown --html FILE` writes a page for a web
  browser. Neither starts Qt.
- **Shown, never run:** raw HTML is kept to a safe subset, nothing is loaded
  from the network, images are read only beside the file (never a secret file,
  bounded in size and count), a web link opens only after a question that
  shows its real address, look-alike host names are shown in punycode.
- **Downloads:** one-file programs for Linux (also as an AppImage), macOS
  (also as a disk image with an app) and Windows, besides the Python package
  on PyPI.

Known limitations: a few large documents still pause the window for about a
quarter of a second while a part is laid out; inline and in the terminal,
`\overset`, `\underset`, `\stackrel` and `\cfrac` are written side by side,
not stacked. The macOS and Windows programs are not notarized or signed.
