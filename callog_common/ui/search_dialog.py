"""Global search window (Ctrl+K).

A single box, a live result list, Enter to jump to the relevant page.
Results are grouped by type; group headers aren't selectable, otherwise
Enter would look like it does nothing.
"""

from .. import search, theme
from ..qt import Qt, QtCore, QtGui, QtWidgets

#: Delay (ms) so search runs when typing pauses, not on every keystroke.
#: Running a query on every character makes typing feel jerky with long
#: lists.
DEBOUNCE_MS = 180


class SearchDialog(QtWidgets.QDialog):

    #: (target, record id)
    chosen = QtCore.Signal(str, object)

    def __init__(self, parent=None):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle("Ara")
        self.setModal(True)
        self.resize(720, 480)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        self.edit = QtWidgets.QLineEdit()
        self.edit.setPlaceholderText(
            "Seri no, sertifika no, firma, model ya da oturum adı")
        self.edit.setClearButtonEnabled(True)
        self.edit.textChanged.connect(self._schedule)
        # Up/down keys navigate the list while focus is in the box: the
        # hand shouldn't need to reach for the mouse while searching.
        self.edit.installEventFilter(self)
        lay.addWidget(self.edit)

        self.list = QtWidgets.QListWidget()
        self.list.itemActivated.connect(self._activate)
        self.list.itemDoubleClicked.connect(self._activate)
        lay.addWidget(self.list, 1)

        self.note = QtWidgets.QLabel(
            "En az iki karakter yazın. Enter seçili kaydı açar, Esc kapatır.")
        self.note.setProperty("hint", True)
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._run)

        self.edit.setFocus()

    # --- behavior ---------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() == QtCore.QEvent.Type.KeyPress:
            if event.key() in (Qt.Key_Down, Qt.Key_Up):
                self._move(1 if event.key() == Qt.Key_Down else -1)
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                item = self.list.currentItem()
                if item is not None:
                    self._activate(item)
                return True
        return QtWidgets.QDialog.eventFilter(self, obj, event)

    def _move(self, delta):
        count = self.list.count()
        if not count:
            return
        row = self.list.currentRow()
        for _ in range(count):
            row = (row + delta) % count
            if self.list.item(row).data(Qt.UserRole) is not None:
                self.list.setCurrentRow(row)
                return

    def _schedule(self):
        self._timer.start()

    def _run(self):
        c = theme.colors()
        term = self.edit.text()
        self.list.clear()
        try:
            hits = search.find(term)
        except Exception as exc:
            self.note.setText("Arama başarısız: %s" % exc)
            return

        if not hits:
            self.note.setText(
                "En az iki karakter yazın. Enter seçili kaydı açar, Esc kapatır."
                if len(term.strip()) < 2 else
                "'%s' için sonuç yok." % term.strip())
            return

        last_kind = None
        for hit in hits:
            if hit["kind"] != last_kind:
                header = QtWidgets.QListWidgetItem(
                    search.KIND_TR.get(hit["kind"], hit["kind"]))
                header.setFlags(Qt.NoItemFlags)
                font = header.font()
                font.setBold(True)
                header.setFont(font)
                header.setForeground(QtGui.QColor(c["text_muted"]))
                self.list.addItem(header)
                last_kind = hit["kind"]
            item = QtWidgets.QListWidgetItem(
                "    %s\n    %s" % (hit["title"], hit["subtitle"]))
            item.setData(Qt.UserRole, (hit["target"], hit["id"]))
            self.list.addItem(item)

        self.note.setText("%d sonuç. Enter açar, Esc kapatır." % len(hits))
        self._move(1)

    def _activate(self, item):
        payload = item.data(Qt.UserRole)
        if payload is None:
            return
        target, ident = payload
        self.chosen.emit(target, ident)
        self.accept()
