"""UI helpers."""

from datetime import date, timedelta

from ..qt import Qt, QtCore, QtGui, QtWidgets, Signal


def compact_rows(view):
    """Tightens row height to match the font size.

    Fusion style's default row height (30 px) is too generous for
    12px text: a ten-row table wastes 60-70 px. Height is computed from
    the font metrics rather than fixed, so rows grow too when the font is
    enlarged for accessibility, and **text doesn't get clipped**.
    """
    header = view.verticalHeader()
    # Floor of 22 px: in some environments (headless runs, before the
    # stylesheet is applied yet) `fontMetrics()` returns a value smaller
    # than the font actually in use, low enough to clip row text.
    height = max(22, view.fontMetrics().height() + 8)
    header.setMinimumSectionSize(height)
    header.setDefaultSectionSize(height)


def fit_table(table, stretch_column=None):
    """Shrinks columns to their content, stretches one column to fill the rest.

    resizeColumnsToContents() alone isn't enough: combined with
    setStretchLastSection, the last column also shrinks to its content and
    leaves empty space on the table's right side.
    """
    compact_rows(table)
    header = table.horizontalHeader()
    # Header text is centered by default; since cells are left-aligned,
    # the header looks disconnected from the data in wide columns.
    header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    count = header.count()
    if count == 0:
        return
    if stretch_column is None:
        stretch_column = count - 1
    for i in range(count):
        mode = (QtWidgets.QHeaderView.Stretch if i == stretch_column
                else QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(i, mode)


#: Page margin and spacing between elements — shared by all pages.
#: Windowed full screen on a 1920x1080 display is the target: generous
#: margins eat 60-80 px on a page with six stacked boxes and push the
#: bottom box off screen.
PAGE_MARGIN = (10, 8, 10, 8)
PAGE_SPACING = 7


def page_layout(widget):
    """Vertical layout with the shared page margin and spacing."""
    lay = QtWidgets.QVBoxLayout(widget)
    lay.setContentsMargins(*PAGE_MARGIN)
    lay.setSpacing(PAGE_SPACING)
    return lay


def scroll_body(page):
    """Makes the page vertically scrollable; returns the content widget.

    On long pages (new session, waveform capture), when the total height
    doesn't fit the screen, Qt widgets get squeezed **below their minimum
    size**: text gets clipped inside boxes, table rows show only half.
    A scroll area prevents this structurally — content that doesn't fit
    is scrolled, not squeezed.

    Usage::

        body = scroll_body(self)
        root = page_layout(body)
        root.addWidget(...)
    """
    outer = QtWidgets.QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    body = QtWidgets.QWidget()
    area = QtWidgets.QScrollArea()
    area.setWidget(body)
    area.setWidgetResizable(True)
    area.setFrameShape(QtWidgets.QFrame.NoFrame)
    # The horizontal scrollbar should only appear when truly needed:
    # it shouldn't show up at all at 1920 px.
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    outer.addWidget(area)
    return body


class _EmptyOverlay(QtWidgets.QLabel):
    """Explanatory text centered over an empty table.

    Adding a fake row to the table would be easier, but that row becomes
    selectable, leaks into exports, and misleads anything that counts rows
    with `rowCount()`. So this lives in the view layer instead, on top of
    the viewport.
    """

    def __init__(self, parent):
        QtWidgets.QLabel.__init__(self, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setProperty("hint", True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)


def empty_state(view, text):
    """Shows explanatory text in the center when a table/list is empty."""
    viewport = view.viewport()
    overlay = viewport.findChild(_EmptyOverlay)
    if overlay is None:
        overlay = _EmptyOverlay(viewport)
        # The filter is a child of the overlay: when the overlay is
        # deleted the filter goes with it, no separate bookkeeping needed.
        viewport.installEventFilter(_Resizer(overlay))
    overlay.setText(text)
    overlay.setGeometry(viewport.rect())

    model = view.model()
    overlay.setVisible(model is None or model.rowCount() == 0)


class _Resizer(QtCore.QObject):
    """Filter that resizes the overlay along with the viewport."""

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.Resize:
            self.parent().setGeometry(obj.rect())
        return False


class DateRangeFilter(QtWidgets.QWidget):
    """Date range filter: presets + custom range.

    "What was done last month" is the most common question; there was a
    device, reference, and status filter but no date filter.

    Comparison is done on the ISO **text** (``started_at >= ?``): since
    timestamps are stored as `YYYY-MM-DDThh:mm:ss+00:00`, lexicographic
    order matches chronological order and no date parsing is needed.

    The limitation is deliberate: timestamps are UTC, the selected day is
    local. In Turkey the difference is three hours — a measurement taken
    near midnight can fall on a neighboring day. Acceptable for day-level
    filtering; the audit log is used when second-level precision matters.
    """

    changed = Signal()

    #: (label, mode). Number = last N days, "year" = year-to-date.
    PRESETS = (
        ("Tüm zamanlar", None),
        ("Son 7 gün", 7),
        ("Son 30 gün", 30),
        ("Son 90 gün", 90),
        ("Bu yıl", "year"),
        ("Özel aralık", "custom"),
    )

    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.combo = QtWidgets.QComboBox()
        for label, value in self.PRESETS:
            self.combo.addItem(label, value)
        self.combo.currentIndexChanged.connect(self._on_preset)

        today = date.today()
        self.start = self._date_edit(today - timedelta(days=30))
        self.end = self._date_edit(today)
        self.dash = QtWidgets.QLabel("–")

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self.combo)
        lay.addWidget(self.start)
        lay.addWidget(self.dash)
        lay.addWidget(self.end)
        self._show_custom(False)

    def _date_edit(self, value):
        widget = QtWidgets.QDateEdit()
        widget.setCalendarPopup(True)
        widget.setDisplayFormat("yyyy-MM-dd")
        widget.setDate(QtCore.QDate(value.year, value.month, value.day))
        widget.dateChanged.connect(lambda _d: self.changed.emit())
        return widget

    def _show_custom(self, visible):
        for widget in (self.start, self.dash, self.end):
            widget.setVisible(visible)

    def _on_preset(self):
        self._show_custom(self.combo.currentData() == "custom")
        self.changed.emit()

    @staticmethod
    def _to_date(qdate):
        return date(qdate.year(), qdate.month(), qdate.day())

    def range(self):
        """``(start, end)`` ISO date text. End is **exclusive**.

        Advancing the end by one day and comparing with ``<`` avoids the
        bug of excluding that day's timestamps, which carry a time
        component: ``<= '2026-08-11'`` would miss every measurement from
        that day.
        """
        mode = self.combo.currentData()
        if mode is None:
            return None, None
        today = date.today()
        if mode == "custom":
            start = self._to_date(self.start.date())
            end = self._to_date(self.end.date())
            if end < start:
                start, end = end, start
            return start.isoformat(), (end + timedelta(days=1)).isoformat()
        if mode == "year":
            start = date(today.year, 1, 1)
        else:
            start = today - timedelta(days=int(mode) - 1)
        return start.isoformat(), (today + timedelta(days=1)).isoformat()

    def describe(self):
        """Human-readable summary of the selected range."""
        start, end = self.range()
        if start is None:
            return "tüm zamanlar"
        last = (date(*[int(x) for x in end.split("-")]) - timedelta(days=1))
        return "%s – %s" % (start, last.isoformat())


def brand_mark(size):
    """The logo badge on the login screen and nav rail.

    Shows a scaled version of the logo if one has been uploaded on the
    admin page, otherwise the organization name's initials
    (`branding.initials`) — so an installation without a logo still isn't
    left without a brand mark.
    """
    from .. import branding

    mark = QtWidgets.QLabel()
    mark.setObjectName("brandMark")
    mark.setFixedSize(size, size)
    mark.setAlignment(Qt.AlignCenter)
    data = branding.logo_bytes()
    pixmap = None
    if data:
        candidate = QtGui.QPixmap()
        if candidate.loadFromData(data) and not candidate.isNull():
            pixmap = candidate
    if pixmap is not None:
        inner = max(1, size - 6)
        mark.setPixmap(pixmap.scaled(
            inner, inner, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    else:
        mark.setText(branding.initials())
    return mark
