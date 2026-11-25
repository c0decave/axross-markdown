"""axross-markdown: axross's Markdown viewer as a program of its own -
``axross-markdown [FILE.md ...]``; ``axross-markdown --term FILE.md`` (or
``axross-mdcat``) shows them in the terminal instead (core.markdown_cli);
``axross-markdown --html FILE.md > page.html`` writes the page for a web
browser (ui.markdown_html.export_html: the images beside the file in it,
nothing it may load from elsewhere) - no window either.

Each file opens rendered in a window of its own (ui.markdown_viewer: the
outline, footnotes, highlighted code, images beside the file, find, zoom);
without a file a window explains itself and offers Open… (Ctrl+O). Edit
(F4) opens axross's editor with the Markdown preview beside the text
(ui.editor_window, View > Markdown Preview). What a file holds is shown,
never run: raw HTML kept to a safe subset (no scripts, styles, frames,
forms or event handlers), nothing from the network (ui.markdown_view).
``--help`` says all of it; ``--term``, ``--html``, ``--help`` and
``--version`` never start Qt (nor import it).

View > Theme chooses the page's theme (ui.markdown_theme_ui, twelve of them),
View > Window Theme the window's (axross's themes). Help > Check for Updates…
and Help > Updates: the one-file programs update themselves from the signed
releases (core.markdown_update, ui.markdown_update_ui); ``--check-update``,
``--update`` and ``--update-mode`` do it without a window, ``--self-test`` is
what the updater runs a new program with before it replaces this one.
"""

from __future__ import annotations

import os
import sys

from axross_markdown._ax.core.markdown_cli import folder_page as _folder_page  # (a folder given: its README, as a link opens it)
from axross_markdown._ax.ui.standalone_app import run, smoke_ms_from_env

NAME = "axross-markdown"
TITLE = "Markdown Viewer"
#: What Open… offers first.
FILTER = "Markdown (*.md *.markdown *.mdown *.mkd);;All files (*)"


class MarkdownApp:
    """The program's windows: viewers, and one editor window (made when
    Edit is first used)."""

    def __init__(self) -> None:
        from axross_markdown._ax.core.local_fs import LocalFS

        self.backend = LocalFS()
        self.editor_window = None
        self.viewers: list = []

    def open_paths(self, paths: list[str], parent=None) -> list:
        """A viewer for each of *paths* (made absolute); a viewer without a
        file when there are none."""
        from axross_markdown._ax.ui.markdown_viewer import open_markdown_viewer

        opened = []
        for path in paths or [""]:
            full = _folder_page(os.path.abspath(os.path.expanduser(path))) if path else ""
            viewer = open_markdown_viewer(self.backend, full, parent, opener=self.ask_open,
                                          editor=self.edit, view_menu=self.view_menu, help_menu=self.help_menu)
            self.viewers.append(viewer)
            opened.append(viewer)
        return opened

    def ask_open(self, viewer) -> list:
        """Open…: the files chosen, each in a viewer; a viewer that showed no
        file yet is replaced by the first of them."""
        from PyQt6.QtWidgets import QFileDialog

        from axross_markdown._ax.core.i18n import tr

        start = os.path.dirname(viewer.path) if viewer.path else os.path.expanduser("~")
        paths, _chosen = QFileDialog.getOpenFileNames(viewer, tr("Open Markdown files"), start, FILTER)
        if not paths:
            return []
        opened = self.open_paths(paths)
        if not viewer.path:
            viewer.close()
        return opened

    def view_menu(self, menu) -> None:
        """View > Window Theme (after the page's Theme, which the viewer adds): axross's themes ("Modern
        (follow system)" the first), the choice kept in the program's own settings
        (ui.standalone_app.settings_file)."""
        from PyQt6.QtGui import QActionGroup
        from PyQt6.QtWidgets import QApplication

        from axross_markdown._ax.core.i18n import tr
        from axross_markdown._ax.ui.standalone_app import fill_theme_menu

        themes = menu.addMenu(tr("Window Theme"))
        themes.setObjectName("window_theme")

        def refill() -> None:  # (the one in use checked - another window may have chosen one)
            for group in themes.findChildren(QActionGroup):
                group.deleteLater()
            themes.clear()
            fill_theme_menu(themes, QApplication.instance(), NAME)

        themes.aboutToShow.connect(refill)
        refill()
        self.language_menu(menu)

    def language_menu(self, menu) -> None:
        """View > Language: Automatic (axross's choice, else the locale's) or one of the languages the
        program has; kept in its own settings (core.markdown_settings), spoken from the next start on -
        said when one is chosen. (There was none: the language was axross's session's, or the locale's.)"""
        from PyQt6.QtGui import QActionGroup

        from axross_markdown._ax.core import i18n
        from axross_markdown._ax.core.i18n import tr
        from axross_markdown._ax.core.markdown_settings import SETTING_LANGUAGE, read_setting, write_setting

        languages = menu.addMenu(tr("Language"))
        languages.setObjectName("language")

        def choose(code) -> None:
            try:
                write_setting(SETTING_LANGUAGE, code)
            except OSError as exc:
                self._language_said = str(exc)
                return
            self._language_said = tr("The language changes the next time {name} starts.").format(name=NAME)
            window = menu.parentWidget()
            view = getattr(window.window() if window is not None else None, "view", None)
            if view is not None:
                view.say(self._language_said)

        def refill() -> None:
            for group in languages.findChildren(QActionGroup):
                group.deleteLater()
            languages.clear()
            group = QActionGroup(languages)
            now = i18n.normalise_language(read_setting(SETTING_LANGUAGE))
            for code, name in ((None, tr("Automatic")), *i18n.available_languages().items()):
                action = languages.addAction(name)
                action.setCheckable(True)
                action.setChecked(code == now)
                action.setData(code)
                group.addAction(action)
                action.triggered.connect(lambda _checked=False, code=code: choose(code))

        languages.aboutToShow.connect(refill)
        refill()

    def help_menu(self, menu) -> None:
        """Help: Check for Updates… and Updates (Off / Tell me / Install automatically) - the checks run
        off the window's thread (ui.markdown_update_ui)."""
        from axross_markdown._ax.ui.markdown_update_ui import controller

        controller().fill_help_menu(menu)
        menu.addSeparator()
        from axross_markdown._ax.core.i18n import tr

        menu.addAction(tr("About {name}…").format(name=NAME), lambda: self.about(menu.parentWidget()))

    def about(self, parent=None):
        """The About window (ui.markdown_about)."""
        from axross_markdown._ax.ui.markdown_about import show_about

        return show_about(parent.window() if parent is not None else None)

    def edit(self, backend, path: str):
        """Edit: the file in the editor window, the preview beside it."""
        from PyQt6 import sip

        from axross_markdown._ax.ui.editor_window import EditorWindow

        if self.editor_window is None or sip.isdeleted(self.editor_window):
            self.editor_window = EditorWindow()
        window = self.editor_window
        window.preview_new_tabs = True
        # (read off the window's thread, its text put in a slice a turn: read and set here,
        # a file of 1 MB and more held the window 0.12 to 0.29 s)
        window.open_file(backend, path, background=True)
        window.show()
        window.raise_()
        window.activateWindow()
        return window


def build(app, args: list[str]):
    """The windows for *args* (files; none: a viewer without one)."""
    from axross_markdown._ax.core.markdown_settings import window_state_path
    from axross_markdown._ax.ui import viewer_window

    # (the window's size in the program's own state: it was written into axross's ~/.config/axross/session.json)
    viewer_window.STATE_FILE = window_state_path()
    speak_chosen_language(app)
    program = MarkdownApp()
    program.open_paths(list(args))
    app._ax_markdown = program  # noqa: SLF001 - kept with the application
    from axross_markdown._ax.ui.markdown_update_ui import controller
    from axross_markdown._ax.ui.standalone_app import smoke_ms_from_env

    if smoke_ms_from_env() is None:  # (a build's start test asks no network)
        controller().start()  # (the checks at the start and every 24 hours, on a thread of their own)
    return None


def speak_chosen_language(app) -> str:
    """The program's own language (View > Language, $LANGUAGE - core.markdown_settings.chosen_language) set
    before its first window, and Qt's own texts in it: the catalogue's (ui.qt_translations: the standard
    buttons) and Qt's translation files where they are there (qtbase_LANGUAGE.qm - a file dialog's and a
    print dialog's words stayed English). Returns the language spoken."""
    from PyQt6.QtCore import QLibraryInfo, QTranslator

    from axross_markdown._ax.core import i18n
    from axross_markdown._ax.core.markdown_settings import chosen_language

    chosen = chosen_language()
    if chosen and chosen != i18n.active().language:
        i18n.install(chosen)
        from axross_markdown._ax.ui.qt_translations import install_qt_translator

        old = getattr(app, "_ax_qt_translator", None)
        if old is not None:
            app.removeTranslator(old)
            app._ax_qt_translator = None  # noqa: SLF001
        install_qt_translator(app)
    language = i18n.active().language
    for old in getattr(app, "_ax_qt_own", ()):
        app.removeTranslator(old)
    app._ax_qt_own = []  # noqa: SLF001 - kept with the application
    if language != i18n.DEFAULT_LANGUAGE:
        folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        for name in ("qtbase", "qt"):
            own = QTranslator(app)
            if own.load(f"{name}_{language}", folder):
                # (before the catalogue's translator: Qt asks the one installed last first - ours wins)
                app.installTranslator(own)
                app._ax_qt_own.append(own)  # noqa: SLF001
                break
        catalogue = getattr(app, "_ax_qt_translator", None)
        if catalogue is not None and app._ax_qt_own:  # noqa: SLF001
            app.removeTranslator(catalogue)
            app.installTranslator(catalogue)
    return language


def _said(status: int) -> int:
    """*status* once what was printed is written - or 1, said, when it cannot be ("--help > /dev/full" ended
    with Python's own complaint at the exit and status 120)."""
    try:
        if sys.stdout is not None:
            sys.stdout.flush()
    except OSError as exc:
        from axross_markdown._ax.core.markdown_cli import _quiet_stdout

        _quiet_stdout()
        print(f"{NAME}: cannot write the output: {exc.strerror or exc}", file=sys.stderr)
        return 1
    return status


def export_html_main(args: list[str]) -> int:
    """``--html FILE``: the page of *FILE* ("-": standard input) for a web
    browser on standard output - its images (beside the file, as the
    terminal reads them: core.markdown_term.read_picture) in it; of
    standard input's only the images the text holds itself."""
    from axross_markdown._ax.core import markdown_doc as MD

    if args[:1] == ["--"]:  # ("--html -- -x.md": a file whose name begins with a dash)
        args = args[1:]
    if len(args) != 1:
        print("axross-markdown: --html takes one file (- for standard input)", file=sys.stderr)
        return 2
    if not MD.available():
        print("axross-markdown needs markdown-it-py and mdit-py-plugins", file=sys.stderr)
        return 2
    from axross_markdown._ax.core.markdown_cli import _read

    name = args[0]
    text, why = _read(name)
    if why:
        print(f"axross-markdown: {MD.clean(name)}: {why}", file=sys.stderr)
        return 1
    from axross_markdown._ax.ui.markdown_html import export_html

    doc = MD.parse(MD.clean(text))
    # (text from a pipe has no folder: "![x](notes.png)" in it embedded that file of the folder the command
    # happened to run in - only the images held in the text itself are in its page)
    piped = name == "-" or not os.path.isfile(name)  # (a pipe given as a path - "<(...)" - is one too)
    folder = os.path.dirname(os.path.abspath(name)) if not piped else None
    title = os.path.basename(name) if not piped else ""
    page = export_html(doc, title=title, images=_images_of(doc, folder))
    from axross_markdown._ax.core.markdown_cli import OutputGone, _write

    try:
        _write(page, NAME)  # (piped into head: it ends quietly - a BrokenPipeError's traceback was printed)
    except OutputGone as gone:  # (... "> /dev/full": said, exit 1)
        return gone.status
    return 0


def _images_of(doc, folder: str | None) -> dict[str, str]:
    """``{src: "data:image/png;base64,…"}`` of the images of *doc* beside
    the file and held in it (read as the terminal reads them: bounded, never
    a secret, never above *folder*) - the only ones the page shows. No
    *folder* (standard input): those held in the text only, no file read."""
    import base64
    import io

    from axross_markdown._ax.core import markdown_doc as MD
    from axross_markdown._ax.core import markdown_term as T

    names = []
    for token in doc.tokens:
        for child in [token, *(token.children or ())]:
            if child.type == "image":
                names.append(str(child.attrGet("src") or ""))
            elif child.type in ("safe_html_block", "safe_html_inline"):
                names += [event[2].get("src", "") for event in MD.html_events(child)
                          if event[0] == "start" and event[1] == "img"]
    found, left = {}, T.IMAGES_PIXELS
    for name in dict.fromkeys(names):
        if len(found) >= T.IMAGES:
            break
        if name[:5].lower() == "data:":  # (held in the file: decoded and checked as the terminal's)
            data, _why = T.data_image(name)
            image = T.decode_picture(data, left) if data is not None else "not an image"
        elif folder is None:
            continue
        else:
            path, why = T.locate(name, folder)
            if why or not path:
                continue
            image = T.read_picture(path, left, folder)
        if isinstance(image, str):
            continue
        left -= image.width * image.height
        out = io.BytesIO()
        image.save(out, format="PNG")
        found[name] = "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")
    return found


TERMINAL = ("--term", "-t", "--cat")


def _parser():
    """The window's command line (``--term`` and ``--html`` have their own:
    main)."""
    import argparse

    from axross_markdown._ax.core.markdown_cli import program_version

    parser = argparse.ArgumentParser(
        prog=NAME, description="Show Markdown files rendered in a window: an outline, footnotes, "
        "highlighted code, images beside the file - shown, never run.",
        epilog="--term FILE ... shows them in the terminal instead (the options of axross-mdcat: "
        f"{NAME} --term --help); --html FILE writes the page for a web browser to standard output "
        "(- for standard input). Neither starts Qt.")
    parser.add_argument("files", nargs="*", metavar="FILE", help="Markdown files, each in a window of its own")
    parser.add_argument("-t", "--term", "--cat", action="store_true",
                        help="show the files in the terminal (axross-mdcat)")
    parser.add_argument("--html", metavar="FILE", help="write FILE's page for a web browser to standard output")
    parser.add_argument("--version", action="version", version=f"{NAME} {program_version()}")
    parser.add_argument("--check-update", action="store_true",
                        help="ask GitHub whether a newer release is out, and exit (no window; asked for here, so "
                             "also with AXROSS_MARKDOWN_NO_UPDATE_CHECK=1 - that stops the window's own checks only)")
    parser.add_argument("--update", action="store_true",
                        help="install a newer release - the one-file programs (pip: says the command) - and exit")
    parser.add_argument("--update-mode", choices=("off", "notify", "auto"),
                        help="the window's checks for updates: off, notify (the default) or auto (install), kept")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    """The program: windows for the files - or (``--term``) the terminal,
    (``--html``) a page on standard output, ``--help``, ``--version``: none
    of those starts Qt or imports it. An option it does not know is an
    error (exit 2), not a file."""
    args = list(sys.argv if argv is None else argv)
    rest = args[1:]
    if rest[:1] == ["--svg-worker"]:
        # A document's SVG drawn in a child process (core.svg_worker): a
        # frozen build has no python -c, the program itself answers.
        from axross_markdown._ax.core.svg_worker import _child_main

        return _child_main()
    if rest[:1] == ["--lex-worker"]:  # (the editor's highlighting lexed in a child: core.lex_worker - as main.py)
        from axross_markdown._ax.core.lex_worker import _child_main as lex_main

        return lex_main()
    if rest[:1] == ["--image-worker"]:  # (a picture decoded in a child: core.image_worker - as main.py)
        from axross_markdown._ax.core.image_worker import _child_main as image_main

        return image_main()
    if any(a in TERMINAL for a in rest):
        # The terminal view (core.markdown_cli, axross-mdcat): no Qt is started.
        from axross_markdown._ax.core.markdown_cli import main as terminal

        return terminal([a for a in rest if a not in TERMINAL], prog=NAME)
    if rest[:1] == ["--script"]:  # (a build's check: ui.standalone_app.bundle_check)
        return run(NAME, TITLE, "markdown", build, argv, smoke_ms=smoke_ms_from_env())
    for at in range(len(rest) - 2):  # ("--html -- -x.md": a file whose name begins with a dash)
        if rest[at] == "--html" and rest[at + 1] == "--":
            rest[at:at + 3] = ["--html=" + rest[at + 2]]
            break
    try:
        options = _parser().parse_args(rest)
    except SystemExit as stop:  # (--help, --version: said; an unknown option: said, exit 2)
        return _said(int(stop.code or 0))
    if options.self_test:
        return self_test()
    if options.update_mode or options.check_update or options.update:
        from axross_markdown._ax.core.markdown_cli import PROG, update_main

        PROG[0] = NAME
        try:
            return update_main(options)
        finally:
            PROG[0] = "axross-mdcat"
    if options.html is not None:
        if options.files:
            print(f"{NAME}: --html takes one file (- for standard input)", file=sys.stderr)
            return 2
        return export_html_main([options.html])
    try:
        return run(NAME, TITLE, "markdown", build, [args[0] if args else NAME, *options.files],
                   smoke_ms=smoke_ms_from_env())
    except ImportError as exc:  # (a system library Qt needs is missing: said, not a traceback)
        said = missing_library(exc)
        if said is None:
            raise
        print(f"{NAME}: {said}", file=sys.stderr)
        return 1


def self_test() -> int:
    """``--self-test``: the program runs here - a page rendered, Qt's libraries loaded (no window: a
    missing system library fails it) - and says ``axross-markdown X.Y.Z ok`` (core.markdown_update runs a
    new program so before it replaces this one)."""
    from axross_markdown._ax.core import markdown_cli

    try:
        from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401 - their libraries loaded is the test

        from axross_markdown._ax.ui import markdown_html  # noqa: F401
    except ImportError as exc:
        print(f"{NAME}: {missing_library(exc) or exc}", file=sys.stderr)
        return 1
    markdown_cli.PROG[0] = NAME
    try:
        return markdown_cli.self_test()
    finally:
        markdown_cli.PROG[0] = "axross-mdcat"


#: The packages that bring a system library Qt's window needs (Debian and
#: Ubuntu / Fedora and RHEL / Arch).
_PACKAGES = {
    "libEGL.so.1": "libegl1 / mesa-libEGL / libglvnd",
    "libGL.so.1": "libgl1 / mesa-libGL / libglvnd",
    "libOpenGL.so.0": "libopengl0 / libglvnd-opengl / libglvnd",
    "libxkbcommon.so.0": "libxkbcommon0 / libxkbcommon / libxkbcommon",
    "libxkbcommon-x11.so.0": "libxkbcommon-x11-0 / libxkbcommon-x11 / libxkbcommon-x11",
    "libfontconfig.so.1": "libfontconfig1 / fontconfig / fontconfig",
    "libfreetype.so.6": "libfreetype6 / freetype / freetype2",
    "libdbus-1.so.3": "libdbus-1-3 / dbus-libs / dbus",
    "libxcb-cursor.so.0": "libxcb-cursor0 / xcb-util-cursor / xcb-util-cursor",
}


def missing_library(error: ImportError) -> str | None:
    """What to say when *error* is a system library that is not there (the
    window cannot start: which library, which package brings it, what works
    without it) - None for any other ImportError."""
    import re

    found = re.search(r"(?<![\w.+-])([\w.+-]+\.so(?:\.\d+)*): cannot open shared object file", str(error))
    if found is None:
        return None
    library = found.group(1)
    package = _PACKAGES.get(library)
    where = (f" - install the package {package} (Debian or Ubuntu / Fedora or RHEL / Arch)" if package
             else " - install the package of your system that has it")
    return (f"the window needs the system library {library}, which is not installed{where}. "
            f"Without it, {NAME} --term FILE shows the file in the terminal and "
            f"{NAME} --html FILE writes it as a web page.")


if __name__ == "__main__":
    sys.exit(main())
