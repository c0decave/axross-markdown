"""The Markdown reader's theme in the window: View > Theme, kept, and every open page told.

One :class:`ThemeHub` a process holds the chosen theme (core.markdown_themes: an id, or "auto" - the
page follows the window: axross's theme in axross, the desktop's light or dark scheme in
axross-markdown) and says when it changes (``changed``); each ui.markdown_view.MarkdownView makes its page
anew in the new colours and shows it in one change - the old page stays, in its colours, until the new
one is there (no flash of a page half in one theme and half in the other, no blank page between).

Rapid switching is rate-limited: a choice applies at once when the last one is at least
:data:`MIN_INTERVAL_MS` old, else the latest of them a moment later - never more than one change of the
page's colours in that time, whatever chose (a click, the keyboard, a script).

The choice is kept in axross's settings (``markdown_theme``) in axross, in
``~/.config/axross-markdown/settings.json`` (``page_theme``) in axross-markdown.
"""

from __future__ import annotations

import logging
import sys
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from axross_markdown._ax.core import markdown_themes as MT

log = logging.getLogger(__name__)

#: The least time between two changes of the page's colours.
MIN_INTERVAL_MS = 400
#: The setting in axross's settings.json.
AXROSS_SETTING = "markdown_theme"


def standalone() -> bool:
    """Whether this is axross-markdown (its own package) - not axross's built-in viewer."""
    return "axross_markdown" in sys.modules


def stored_theme() -> str:
    """The theme kept ("auto" when none is)."""
    try:
        if standalone():
            from axross_markdown._ax.core.markdown_settings import read_setting

            return MT.normalize(read_setting(MT.SETTING_PAGE, MT.AUTO))
        try:
            from axross_markdown._ax.core import open_limits
        except ImportError:  # (an export without axross's settings)
            return MT.AUTO
        return MT.normalize(open_limits.read_setting(AXROSS_SETTING, MT.AUTO))
    except Exception:  # noqa: BLE001 - unreadable settings: the window's
        return MT.AUTO


def store_theme(theme_id: str) -> None:
    try:
        if standalone():
            from axross_markdown._ax.core.markdown_settings import write_setting

            write_setting(MT.SETTING_PAGE, theme_id)
            return
        try:
            from axross_markdown._ax.core import open_limits
        except ImportError:
            return
        open_limits.write_setting(AXROSS_SETTING, theme_id)
    except Exception:  # noqa: BLE001 - not kept: said in the log, the choice still applies
        log.warning("The Markdown theme could not be kept", exc_info=True)


class ThemeHub(QObject):
    """The chosen theme of the process; ``changed(theme_id)`` once a change applies."""

    changed = pyqtSignal(str)

    def __init__(self, parent=None, *, clock=time.monotonic) -> None:
        super().__init__(parent)
        self._theme = stored_theme()
        self._pending: str | None = None
        self._applied = float("-inf")
        self.clock = clock
        self.applied_count = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._apply_pending)

    def theme_id(self) -> str:
        """The theme in use: an id, or "auto"."""
        return self._theme

    def theme(self) -> MT.Theme | None:
        """The chosen Theme - None for "auto"."""
        return MT.get(self._theme)

    def choose(self, theme_id: str, *, keep: bool = True) -> None:
        """*theme_id* chosen (kept with *keep*): applied now, or - another change less than
        MIN_INTERVAL_MS ago - the latest choice once that time is over."""
        theme_id = MT.normalize(theme_id)
        if keep:
            store_theme(theme_id)
        self._pending = theme_id
        wait = MIN_INTERVAL_MS - (self.clock() - self._applied) * 1000
        if wait <= 0 and not self._timer.isActive():
            self._apply_pending()
        elif not self._timer.isActive():
            self._timer.start(max(1, int(wait)))

    def _apply_pending(self) -> None:
        theme_id, self._pending = self._pending, None
        if theme_id is None or theme_id == self._theme:
            return
        self._theme = theme_id
        self._applied = self.clock()
        self.applied_count += 1
        self.changed.emit(theme_id)


_HUB: list[ThemeHub] = []


def hub() -> ThemeHub:
    """The process's ThemeHub (made at first use, owned by the application)."""
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication

    if _HUB and not sip.isdeleted(_HUB[0]):
        return _HUB[0]
    _HUB[:] = [ThemeHub(QCoreApplication.instance())]
    return _HUB[0]


def auto_label() -> str:
    from axross_markdown._ax.core.i18n import tr

    return tr("Automatic (as the window)") if standalone() else tr("Automatic (as axross)")


def fill_theme_menu(menu) -> None:
    """*menu*: "Automatic" and every theme, the one in use checked - a choice applied to every open page
    and kept."""
    from PyQt6.QtGui import QActionGroup

    from axross_markdown._ax.core.i18n import tr

    group = QActionGroup(menu)
    group.setExclusive(True)
    current = hub().theme_id()
    for theme_id in MT.CHOICES:
        label = auto_label() if theme_id == MT.AUTO else tr(MT.THEMES[theme_id].label)
        action = menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(theme_id == current)
        action.setData(theme_id)
        group.addAction(action)
    group.triggered.connect(lambda action: hub().choose(action.data()))

    def checked() -> None:  # (another window may have chosen one)
        now = hub().theme_id()
        for action in group.actions():
            action.setChecked(action.data() == now)

    menu.aboutToShow.connect(checked)


def page_palette(theme: MT.Theme, base):
    """*base* (a QPalette) with the page roles of *theme*: its ground, text, links and selection."""
    from PyQt6.QtGui import QColor, QPalette

    palette = QPalette(base)
    page = theme.page
    roles = ((QPalette.ColorRole.Base, page["page_bg"]), (QPalette.ColorRole.Window, page["page_bg"]),
             (QPalette.ColorRole.Text, page["text"]), (QPalette.ColorRole.WindowText, page["text"]),
             (QPalette.ColorRole.Highlight, page["selection_bg"]),
             (QPalette.ColorRole.HighlightedText, page["selection_fg"]),
             (QPalette.ColorRole.Link, page["link"]), (QPalette.ColorRole.LinkVisited, page["link"]),
             (QPalette.ColorRole.PlaceholderText, page["muted"]))
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        for role, colour in roles:
            palette.setColor(group, role, QColor(colour))
    return palette


def rendered_contrasts(document, theme: MT.Theme) -> list[tuple[str, str, str, float]]:
    """(text, its colour, the ground it is drawn on, their contrast) of every fragment of text of *document*
    (a QTextDocument of a page in *theme*) - measured on the page as rendered, not from the theme's roles: a
    fragment's own colour (the theme's text where it has none) against its own ground, else its block's, its
    table cell's, its table's, a table's around that, the page's. What core.markdown_themes.contrast_report
    lists by role - a link in a <mark>, a formula in a table's header - is checked here as it is drawn."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QTextCursor, QTextTable

    def ground_of(fmt) -> str | None:
        brush = fmt.background()
        return brush.color().name() if brush.style() != Qt.BrushStyle.NoBrush and brush.color().alpha() else None

    def around(block) -> str:
        found = ground_of(block.blockFormat())
        frame, place = QTextCursor(block).currentFrame(), block.position()
        while found is None and frame is not None:
            if isinstance(frame, QTextTable):
                cell = frame.cellAt(place)
                found = (ground_of(cell.format()) if cell.isValid() else None) or ground_of(frame.format())
            place = frame.firstPosition() - 1
            frame = frame.parentFrame()
        return found or theme.page["page_bg"]

    rows, block = [], document.begin()
    while block.isValid():
        at, behind = block.begin(), None
        while not at.atEnd():
            fragment = at.fragment()
            fmt, text = fragment.charFormat(), fragment.text().strip()
            if text and not fmt.isImageFormat():
                if behind is None:
                    behind = around(block)
                ground = ground_of(fmt) or behind
                brush = fmt.foreground()
                colour = brush.color().name() if brush.style() != Qt.BrushStyle.NoBrush else theme.page["text"]
                rows.append((text, colour, ground, MT.contrast(colour, ground)))
            at += 1
        block = block.next()
    return rows


def scroll_bar_style(theme: MT.Theme) -> str:
    """The style sheet of a scroll bar beside a page of *theme*: its groove the page's ground, its handle the
    theme's muted colour (the text's when the pointer is on it) - a dark page kept the window's bar, a white
    handle beside it."""
    page = theme.page
    return (f"QScrollBar {{ background: {page['page_bg']}; border: none; margin: 0px; }}"
            "QScrollBar:vertical { width: 14px; } QScrollBar:horizontal { height: 14px; }"
            f"QScrollBar::handle {{ background: {page['muted']}; border: 3px solid {page['page_bg']}; "
            "border-radius: 7px; }"
            "QScrollBar::handle:vertical { min-height: 32px; } QScrollBar::handle:horizontal { min-width: 32px; }"
            f"QScrollBar::handle:hover, QScrollBar::handle:pressed {{ background: {page['text']}; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; border: none; "
            "background: none; }"
            "QScrollBar::add-page, QScrollBar::sub-page { background: none; }")


def window_style(theme: MT.Theme) -> str:
    """The style sheet of the reader's window around a page of *theme* (axross-markdown: its toolbar, its find
    field, the outline and the status line - they stayed in the window's light colours beside a dark page):
    the page's ground and text, buttons and fields outlined in its muted colour, what is chosen in its
    selection's colours, the focus in its link's."""
    page = theme.page
    ground, text, muted, raised = page["page_bg"], page["text"], page["muted"], page["code_bg"]
    chosen, chosen_text = page["selection_bg"], page["selection_fg"]
    return (
        f"QDialog {{ background-color: {ground}; color: {text}; }}"
        f"QLabel {{ color: {text}; background: transparent; }}"
        f"QPushButton, QToolButton {{ background-color: {raised}; color: {text}; border: 1px solid {muted}; "
        "border-radius: 4px; padding: 3px 8px; }"
        f"QPushButton:hover, QToolButton:hover {{ background-color: {page['th_bg']}; border-color: {text}; }}"
        f"QPushButton:pressed, QPushButton:checked, QToolButton:pressed {{ background-color: {chosen}; "
        f"color: {chosen_text}; }}"
        f"QPushButton:focus, QToolButton:focus, QLineEdit:focus {{ border: 2px solid {page['link']}; }}"
        f"QPushButton:disabled, QToolButton:disabled {{ color: {muted}; border-color: {page['rule']}; }}"
        f"QLineEdit {{ background-color: {ground}; color: {text}; border: 1px solid {muted}; border-radius: 4px; "
        f"padding: 2px 4px; selection-background-color: {chosen}; selection-color: {chosen_text}; "
        f"placeholder-text-color: {muted}; }}"
        f"QListWidget {{ background-color: {ground}; color: {text}; border: 1px solid {page['rule']}; }}"
        f"QListWidget::item:selected {{ background-color: {chosen}; color: {chosen_text}; }}"
        f"QListWidget::item:hover {{ background-color: {raised}; }}"
        f"QSplitter::handle {{ background-color: {page['rule']}; }}"
        f"QMenu {{ background-color: {ground}; color: {text}; border: 1px solid {muted}; }}"
        f"QMenu::item:selected {{ background-color: {chosen}; color: {chosen_text}; }}"
        f"QMenu::item:disabled {{ color: {muted}; }}"
        f"QToolTip {{ background-color: {raised}; color: {text}; border: 1px solid {muted}; }}"
        + scroll_bar_style(theme))


def add_theme_menu(menu):
    """A "Theme" submenu of *menu* (View): :func:`fill_theme_menu`. The submenu."""
    from axross_markdown._ax.core.i18n import tr

    themes = menu.addMenu(tr("Theme"))
    themes.setObjectName("markdown_page_theme")
    fill_theme_menu(themes)
    return themes


__all__ = ["MIN_INTERVAL_MS", "ThemeHub", "add_theme_menu", "auto_label", "fill_theme_menu", "hub",
           "page_palette", "rendered_contrasts", "scroll_bar_style", "standalone", "store_theme", "stored_theme", "window_style"]
