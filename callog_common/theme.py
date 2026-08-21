"""Application theme: palette + stylesheet.

Default is the white (light) theme. Windows' theme setting is not followed —
lab PCs have inconsistent settings from machine to machine, and the
measurement screen needs to look the same on every one of them.

There's a third mode: **high contrast**. Lab screens are small and are often
read from a distance; the gray text and thin lines in the normal theme
disappear at that range. High contrast isn't the light theme with more
contrast — it's a separate palette: gray tones removed entirely, borders
thickened.

Font size scales with a single multiplier (`font_scale`). Every
`font-size: Npx` in the stylesheet is rewritten with that multiplier;
instead of adjusting sizes one by one, this guarantees the proportions
between them stay intact.

Choices are tied to the **user** (`prefs`); when no user is known, it falls
back to the machine's setting.
"""

import re

from . import prefs
from .qt import QtCore, QtGui

LIGHT = "light"
DARK = "dark"
CONTRAST = "contrast"

MODE_TR = {LIGHT: "Beyaz", DARK: "Koyu", CONTRAST: "Yüksek kontrast"}

#: Font size multiplier options — (label, multiplier)
FONT_SCALES = (
    ("Küçük (%90)", 0.9),
    ("Normal (%100)", 1.0),
    ("Büyük (%115)", 1.15),
    ("Daha büyük (%130)", 1.3),
    ("En büyük (%150)", 1.5),
)

MIN_SCALE, MAX_SCALE = 0.8, 1.6

#: `QSettings` storage-path identifiers — see prefs.py
_ORG = "CalLog"
_APP = "CalLog"

#: Which user preferences get written to. None until login.
_user_id = None


def bind_user(user_id):
    """Binds preferences to this user. Called right after login."""
    global _user_id
    _user_id = user_id

# --- color tokens ---------------------------------------------------------
TOKENS = {
    LIGHT: {
        "window": "#F4F3EF", "surface": "#FFFFFF", "surface_alt": "#FAF9F6",
        "sidebar": "#EDEBE5", "nav_active": "#E2ECFB",
        "text": "#1A1A18", "text_muted": "#6B6A65", "border": "#DEDCD5",
        "border_strong": "#C6C4BC", "accent": "#2E6FD0", "accent_hover": "#2A63BA",
        "on_accent": "#FFFFFF", "curve": "#185FA5", "mean": "#0F6E56",
        "guide": "#9A9993", "ok": "#0F6E56", "bad": "#A32D2D", "warn": "#8A5209",
        "ok_bg": "#E1F5EE", "bad_bg": "#FCEBEB", "warn_bg": "#FAEEDA",
        "grid": 0.22,
    },
    DARK: {
        "window": "#1F1F1E", "surface": "#282827", "surface_alt": "#2E2E2C",
        "sidebar": "#191918", "nav_active": "#23344B",
        "text": "#ECECE8", "text_muted": "#9C9B95", "border": "#3C3C3A",
        "border_strong": "#4E4E4B", "accent": "#5C9BEE", "accent_hover": "#6FA8F2",
        "on_accent": "#10233C", "curve": "#85B7EB", "mean": "#5DCAA5",
        "guide": "#77766F", "ok": "#5DCAA5", "bad": "#F09595", "warn": "#EF9F27",
        "ok_bg": "#123329", "bad_bg": "#3A1A1A", "warn_bg": "#3A2A10",
        "grid": 0.30,
    },
    # High contrast: no gray. Muted text is also pure black — "hint" text is
    # set apart by a smaller font, not by color. Borders are dark so they
    # stay visible, and the grid is more prominent.
    CONTRAST: {
        "window": "#FFFFFF", "surface": "#FFFFFF", "surface_alt": "#F0F0F0",
        "sidebar": "#FFFFFF", "nav_active": "#CFE2FF",
        "text": "#000000", "text_muted": "#000000", "border": "#000000",
        "border_strong": "#000000", "accent": "#0B3FA8", "accent_hover": "#082F80",
        "on_accent": "#FFFFFF", "curve": "#0B3FA8", "mean": "#006040",
        "guide": "#000000", "ok": "#006040", "bad": "#9E0000", "warn": "#6A3B00",
        "ok_bg": "#D6F0E5", "bad_bg": "#FBDDDD", "warn_bg": "#FAEBCF",
        "grid": 0.55,
    },
}


def _settings():
    return QtCore.QSettings(_ORG, _APP)


def current_mode():
    mode = str(prefs.get(_user_id, prefs.THEME, LIGHT) or LIGHT).lower()
    return mode if mode in TOKENS else LIGHT


def set_mode(mode):
    prefs.set(_user_id, prefs.THEME, mode if mode in TOKENS else LIGHT)


def font_scale():
    value = prefs.get_float(_user_id, prefs.FONT_SCALE, 1.0)
    return max(MIN_SCALE, min(MAX_SCALE, value))


def set_font_scale(scale):
    prefs.set(_user_id, prefs.FONT_SCALE,
              "%.2f" % max(MIN_SCALE, min(MAX_SCALE, float(scale))))


def colors(mode=None):
    return TOKENS[mode or current_mode()]


# --- palette ---------------------------------------------------------------
def _palette(mode):
    t = TOKENS[mode]
    c = QtGui.QColor
    p = QtGui.QPalette()
    role = QtGui.QPalette.ColorRole
    grp = QtGui.QPalette.ColorGroup

    p.setColor(role.Window, c(t["window"]))
    p.setColor(role.WindowText, c(t["text"]))
    p.setColor(role.Base, c(t["surface"]))
    p.setColor(role.AlternateBase, c(t["surface_alt"]))
    p.setColor(role.Text, c(t["text"]))
    p.setColor(role.Button, c(t["surface"]))
    p.setColor(role.ButtonText, c(t["text"]))
    p.setColor(role.ToolTipBase, c(t["surface"]))
    p.setColor(role.ToolTipText, c(t["text"]))
    p.setColor(role.Highlight, c(t["accent"]))
    p.setColor(role.HighlightedText, c(t["on_accent"]))
    p.setColor(role.Link, c(t["accent"]))
    p.setColor(role.PlaceholderText, c(t["text_muted"]))
    for r in (role.WindowText, role.Text, role.ButtonText):
        p.setColor(grp.Disabled, r, c(t["text_muted"]))
    return p


# --- stylesheet -------------------------------------------------------------
def stylesheet(mode):
    t = TOKENS[mode]
    return """
* { outline: 0; }

QWidget {
    font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
    color: %(text)s;
}

QMainWindow, QDialog { background: %(window)s; }

/* --- sekme cubugu (ana gezinme) --- */
QTabWidget::pane {
    border: none;
    background: transparent;
}
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab {
    background: transparent;
    color: %(text_muted)s;
    padding: 6px 14px;
    margin-right: 2px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 12px;
}
QTabBar::tab:hover { color: %(text)s; }
QTabBar::tab:selected {
    color: %(accent)s;
    border-bottom: 2px solid %(accent)s;
    font-weight: 600;
}

/* --- menu cubugu --- */
QMenuBar { background: %(window)s; border-bottom: 1px solid %(border)s; padding: 1px; }
QMenuBar::item { padding: 4px 10px; border-radius: 6px; background: transparent; }
QMenuBar::item:selected { background: %(surface_alt)s; }
QMenu { background: %(surface)s; border: 1px solid %(border)s; border-radius: 8px; padding: 6px; }
QMenu::item { padding: 5px 20px 5px 12px; border-radius: 6px; }
QMenu::item:selected { background: %(accent)s; color: %(on_accent)s; }
QMenu::separator { height: 1px; background: %(border)s; margin: 5px 8px; }

/* --- kart / grup kutusu --- */
QGroupBox {
    background: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: 10px;
    margin-top: 13px;
    padding: 10px 11px 8px 11px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 5px;
    color: %(text_muted)s;
    font-size: 11px;
    font-weight: 600;
}

QFrame[card="true"] {
    background: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: 10px;
}

/* --- girisler --- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: %(surface)s;
    border: 1px solid %(border_strong)s;
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 17px;
    selection-background-color: %(accent)s;
    selection-color: %(on_accent)s;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid %(accent)s;
}
QLineEdit:disabled, QComboBox:disabled {
    background: %(surface_alt)s; color: %(text_muted)s;
}
/* Yuvarlatılmış kenarlık, varsayılan spinbox düğmelerini kırpıyor */
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    width: 16px; border: none; background: transparent; margin-right: 3px;
}

QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow {
    image: none;
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid %(text_muted)s;
    margin-right: 7px;
}
QComboBox QAbstractItemView {
    background: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: %(accent)s;
    selection-color: %(on_accent)s;
}

/* --- dugmeler --- */
QPushButton {
    background: %(surface)s;
    border: 1px solid %(border_strong)s;
    border-radius: 6px;
    padding: 5px 12px;
    min-height: 17px;
    font-weight: 500;
}
QPushButton:hover { background: %(surface_alt)s; border-color: %(accent)s; }
QPushButton:pressed { background: %(border)s; }
QPushButton:disabled { color: %(text_muted)s; border-color: %(border)s; background: %(surface_alt)s; }
QPushButton:checked { background: %(accent)s; color: %(on_accent)s; border-color: %(accent)s; }

QPushButton[primary="true"] {
    background: %(accent)s; color: %(on_accent)s; border: 1px solid %(accent)s;
    font-weight: 600;
}
QPushButton[primary="true"]:hover { background: %(accent_hover)s; border-color: %(accent_hover)s; }
QPushButton[danger="true"] { color: %(bad)s; border-color: %(bad)s; }

/* --- tablolar --- */
QTableWidget, QTableView, QListWidget, QTreeWidget {
    background: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: 10px;
    gridline-color: transparent;
    alternate-background-color: %(surface_alt)s;
    selection-background-color: %(accent)s;
    selection-color: %(on_accent)s;
}
QTableWidget::item, QListWidget::item { padding: 3px 6px; border: none; }
QHeaderView::section {
    background: %(surface_alt)s;
    color: %(text_muted)s;
    border: none;
    border-bottom: 1px solid %(border)s;
    padding: 4px 6px;
    font-weight: 600;
    font-size: 11px;
}
QHeaderView::section:first { border-top-left-radius: 10px; }
QHeaderView::section:last { border-top-right-radius: 10px; }
QTableCornerButton::section { background: %(surface_alt)s; border: none; }

/* --- kaydirma cubugu --- */
QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar::handle:vertical { background: %(border_strong)s; border-radius: 5px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: %(text_muted)s; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle:horizontal { background: %(border_strong)s; border-radius: 5px; min-width: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* --- diger --- */
/* Onay kutusunun göstergesi kasıtlı olarak biçimlendirilmiyor: arka planı
   ezmek Fusion'ın çizdiği tik işaretini de siliyor ve kutu boş görünüyor. */
QCheckBox, QRadioButton { spacing: 7px; }
QStatusBar { background: %(window)s; border-top: 1px solid %(border)s; color: %(text_muted)s; }
QStatusBar::item { border: none; }
QSplitter::handle { background: transparent; width: 6px; }
QToolTip {
    background: %(surface)s; color: %(text)s;
    border: 1px solid %(border)s; border-radius: 6px; padding: 6px 8px;
}
QLabel[hint="true"] { color: %(text_muted)s; font-size: 11px; }
QLabel[h1="true"] { font-size: 18px; font-weight: 600; }
QLabel[h2="true"] { font-size: 15px; font-weight: 600; }
QLabel[stat="true"] { font-size: 19px; font-weight: 600; }
QLabel[statcap="true"] { color: %(text_muted)s; font-size: 10px;
    text-transform: uppercase; letter-spacing: 0.4px; }

/* --- sol gezinme seridi --- */
#navSidebar {
    background: %(sidebar)s;
    border: none;
    border-right: 1px solid %(border)s;
}
#brandMark {
    background: %(accent)s;
    color: %(on_accent)s;
    border-radius: 8px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
}
#brandName { font-size: 14px; font-weight: 600; }

QToolButton#navButton {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 5px 9px;
    color: %(text_muted)s;
    text-align: left;
    font-size: 12px;
    font-weight: 500;
}
QToolButton#navButton:hover { background: %(surface_alt)s; color: %(text)s; }
QToolButton#navButton:checked {
    background: %(nav_active)s;
    color: %(accent)s;
    font-weight: 600;
}
QToolButton#navButton:disabled { color: %(border_strong)s; background: transparent; }

#userCard {
    background: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: 10px;
}
#avatar {
    background: %(accent)s;
    color: %(on_accent)s;
    border-radius: 16px;
    font-size: 12px;
    font-weight: 700;
}
#userName { font-size: 12px; font-weight: 600; }
QToolButton#cardBtn {
    background: transparent; border: 1px solid transparent;
    border-radius: 6px; padding: 4px;
}
QToolButton#cardBtn:hover { background: %(surface_alt)s; border-color: %(border)s; }

/* --- rol / durum rozetleri --- */
QLabel#rolePill {
    font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 7px;
    text-transform: uppercase; letter-spacing: 0.3px;
    background: %(surface_alt)s; color: %(text_muted)s;
}
QLabel#rolePill[pill="admin"]    { background: %(bad_bg)s;  color: %(bad)s; }
QLabel#rolePill[pill="approver"] { background: %(warn_bg)s; color: %(warn)s; }
QLabel#rolePill[pill="operator"] { background: %(ok_bg)s;   color: %(ok)s; }

QLabel[badge="ok"]   { background: %(ok_bg)s;   color: %(ok)s;
    border-radius: 7px; padding: 1px 8px; font-weight: 600; font-size: 11px; }
QLabel[badge="warn"] { background: %(warn_bg)s; color: %(warn)s;
    border-radius: 7px; padding: 1px 8px; font-weight: 600; font-size: 11px; }
QLabel[badge="bad"]  { background: %(bad_bg)s;  color: %(bad)s;
    border-radius: 7px; padding: 1px 8px; font-weight: 600; font-size: 11px; }

/* --- ic sekmeler (sayfa icinde) --- */
QTabWidget#innerTabs::pane { border: none; }
QTabWidget#innerTabs > QTabBar::tab {
    background: %(surface_alt)s;
    border: 1px solid %(border)s;
    border-radius: 7px;
    padding: 4px 12px;
    margin-right: 5px;
    color: %(text_muted)s;
    font-weight: 500;
}
QTabWidget#innerTabs > QTabBar::tab:selected {
    background: %(accent)s; color: %(on_accent)s; border-color: %(accent)s;
    font-weight: 600;
}
""" % t


_FONT_SIZE_RE = re.compile(r"font-size:\s*([0-9.]+)px")


def scale_stylesheet(sheet, scale):
    """Rewrites every `font-size` value in the stylesheet with the multiplier.

    A single multiplier instead of adjusting sizes one by one: the ratios
    between them (heading / body / hint) grow without being thrown off. At
    1.0 the text passes through untouched, so the default look is preserved
    exactly.
    """
    if abs(scale - 1.0) < 1e-6:
        return sheet
    return _FONT_SIZE_RE.sub(
        lambda m: "font-size: %dpx" % max(8, round(float(m.group(1)) * scale)),
        sheet)


def apply(app, mode=None, scale=None):
    """Applies the theme and font size; returns the mode that was chosen."""
    mode = mode or current_mode()
    scale = font_scale() if scale is None else scale
    # The Fusion style applies the palette consistently across platforms;
    # the native Windows style ignores some colors and corner radii.
    app.setStyle("Fusion")
    app.setPalette(_palette(mode))
    app.setStyleSheet(scale_stylesheet(stylesheet(mode), scale))
    set_mode(mode)
    set_font_scale(scale)
    return mode


def toggle(app):
    """White <-> dark. Switches high contrast back to white: the toggle is
    binary, the third mode has to be chosen from the menu."""
    return apply(app, DARK if current_mode() == LIGHT else LIGHT)
