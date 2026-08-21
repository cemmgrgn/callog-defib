"""Left navigation rail.

A left rail is used instead of a tab bar. Three reasons:

* Tab labels ("Kalibre edilen cihazlar", "Geçmiş kayıtlar") are long;
  a horizontal bar either truncated them or took up half the screen.
* The number of pages varies by role. A missing tab in a horizontal bar
  raises the question "why don't I have it?"; it goes unnoticed in a
  vertical list.
* Who is logged in and what role they're in must stay constantly
  visible — recording a measurement under the wrong account can't be
  undone.

The class mimics as much of `QTabWidget` as we use (`count`,
`setCurrentIndex`, `setTabEnabled`, `currentChanged`, ...) so the caller
doesn't need to know it's different from the tabbed version.
"""

from .. import branding, perms, theme
from ..qt import Qt, QtCore, QtGui, QtWidgets
from . import icons
from .util import brand_mark


class NavRail(QtWidgets.QWidget):

    currentChanged = QtCore.Signal(int)

    def __init__(self, user, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.user = user
        self._pages = []          # (key, button, widget)
        self._keys = {}           # key -> index

        self.sidebar = QtWidgets.QFrame()
        self.sidebar.setObjectName("navSidebar")
        self.sidebar.setFixedWidth(212)
        side = QtWidgets.QVBoxLayout(self.sidebar)
        side.setContentsMargins(12, 14, 12, 12)
        side.setSpacing(3)

        side.addWidget(self._brand())
        side.addSpacing(12)

        self.button_area = QtWidgets.QVBoxLayout()
        self.button_area.setSpacing(3)
        side.addLayout(self.button_area)
        side.addStretch(1)
        side.addWidget(self._user_card())

        self.stack = QtWidgets.QStackedWidget()

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.sidebar)
        root.addWidget(self.stack, 1)

        self.stack.currentChanged.connect(self._on_stack_changed)

    # --- rail parts ---------------------------------------------------
    def _brand(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 0, 0)
        lay.setSpacing(9)

        mark = brand_mark(30)
        lay.addWidget(mark)

        col = QtWidgets.QVBoxLayout()
        col.setSpacing(0)
        name = QtWidgets.QLabel("DataLog")
        name.setObjectName("brandName")
        sub = QtWidgets.QLabel(branding.department() or branding.org_name())
        sub.setProperty("hint", True)
        col.addWidget(name)
        col.addWidget(sub)
        lay.addLayout(col, 1)
        return w

    def _user_card(self):
        self.card = QtWidgets.QFrame()
        self.card.setObjectName("userCard")
        lay = QtWidgets.QVBoxLayout(self.card)
        lay.setContentsMargins(10, 9, 10, 9)
        lay.setSpacing(7)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(9)
        self.avatar = QtWidgets.QLabel(_initials(self.user["full_name"]))
        self.avatar.setObjectName("avatar")
        self.avatar.setFixedSize(32, 32)
        self.avatar.setAlignment(Qt.AlignCenter)
        top.addWidget(self.avatar)

        col = QtWidgets.QVBoxLayout()
        col.setSpacing(1)
        name = QtWidgets.QLabel(self.user["full_name"])
        name.setObjectName("userName")
        # Truncated with an ellipsis so a long name doesn't widen the rail
        name.setMinimumWidth(0)
        role = QtWidgets.QLabel(perms.label(self.user["role"]))
        role.setProperty("pill", self.user["role"])
        role.setObjectName("rolePill")
        role.setAlignment(Qt.AlignCenter)
        col.addWidget(name)
        col.addWidget(role, 0, Qt.AlignLeft)
        top.addLayout(col, 1)
        lay.addLayout(top)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        self.theme_btn = QtWidgets.QToolButton()
        self.theme_btn.setObjectName("cardBtn")
        self.theme_btn.setToolTip("Temayı değiştir")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.logout_btn = QtWidgets.QToolButton()
        self.logout_btn.setObjectName("cardBtn")
        self.logout_btn.setToolTip("Uygulamadan çık")
        self.logout_btn.setCursor(Qt.PointingHandCursor)
        row.addWidget(self.theme_btn)
        row.addWidget(self.logout_btn)
        row.addStretch(1)
        lay.addLayout(row)

        self._name_label = name
        return self.card

    # --- pages ---------------------------------------------------------
    def add_page(self, key, widget, label, icon_name, tooltip=None):
        btn = QtWidgets.QToolButton()
        btn.setObjectName("navButton")
        btn.setText("  " + label)
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                          QtWidgets.QSizePolicy.Fixed)
        btn.setMinimumHeight(36)
        btn.setIconSize(QtCore.QSize(19, 19))
        if tooltip:
            btn.setToolTip(tooltip)
        index = len(self._pages)
        btn.clicked.connect(lambda _c=False, i=index: self.setCurrentIndex(i))

        self.button_area.addWidget(btn)
        self.stack.addWidget(widget)
        self._pages.append([key, btn, widget, icon_name])
        self._keys[key] = index
        if index == 0:
            btn.setChecked(True)
        return index

    def index_of(self, key):
        return self._keys.get(key, -1)

    def page(self, key):
        i = self.index_of(key)
        return self._pages[i][2] if i >= 0 else None

    # --- QTabWidget-compatible surface -----------------------------------
    def count(self):
        return len(self._pages)

    def setCurrentIndex(self, index):
        if 0 <= index < len(self._pages) and self._pages[index][1].isEnabled():
            self.stack.setCurrentIndex(index)

    def currentIndex(self):
        return self.stack.currentIndex()

    def currentWidget(self):
        return self.stack.currentWidget()

    def setTabEnabled(self, index, enabled):
        if 0 <= index < len(self._pages):
            self._pages[index][1].setEnabled(enabled)

    def isTabEnabled(self, index):
        return (0 <= index < len(self._pages)
                and self._pages[index][1].isEnabled())

    def setTabToolTip(self, index, text):
        if 0 <= index < len(self._pages):
            self._pages[index][1].setToolTip(text)

    def setCurrentWidget(self, widget):
        self.stack.setCurrentWidget(widget)

    # --- appearance ---------------------------------------------------------
    def _on_stack_changed(self, index):
        for i, (_key, btn, _w, _icon) in enumerate(self._pages):
            btn.setChecked(i == index)
        self.currentChanged.emit(index)

    def refresh_theme(self):
        """Icon colors depend on the palette; must be redrawn when the theme changes."""
        c = theme.colors()
        for _key, btn, _w, icon_name in self._pages:
            btn.setIcon(icons.dual_icon(icon_name, c["text_muted"], c["accent"]))
        self.theme_btn.setIcon(icons.icon("theme", c["text_muted"], 17))
        self.logout_btn.setIcon(icons.icon("logout", c["text_muted"], 17))
        self._elide_name()

    def resizeEvent(self, event):
        QtWidgets.QWidget.resizeEvent(self, event)
        self._elide_name()

    def _elide_name(self):
        label = getattr(self, "_name_label", None)
        if label is None:
            return
        full = self.user["full_name"]
        metrics = QtGui.QFontMetrics(label.font())
        label.setText(metrics.elidedText(full, Qt.ElideRight, 118))
        if label.text() != full:
            label.setToolTip(full)


def _initials(full_name):
    parts = [p for p in (full_name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()
