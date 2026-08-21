"""In-app PDF preview.

So that noticing an incorrectly generated certificate doesn't require
sending the file to an external viewer and closing it again. Also useful
in the approval queue: an approver shouldn't sign without seeing the
document itself.

Uses Qt 6's `QtPdf` module. The module isn't bundled in some Qt
installations; in that case `is_available()` returns False and the caller
hands the file off to the OS — a missing preview is a limitation, not an
error.
"""

import os

from ..qt import QtWidgets


def is_available():
    try:
        from PySide6 import QtPdf, QtPdfWidgets  # noqa: F401
    except Exception:
        return False
    return True


class PdfPreviewDialog(QtWidgets.QDialog):
    """Simple viewer with page navigation + zoom."""

    def __init__(self, path, parent=None, title=None):
        QtWidgets.QDialog.__init__(self, parent)
        from PySide6 import QtPdf, QtPdfWidgets

        self.setWindowTitle(title or os.path.basename(path))
        self.resize(900, 1000)
        self.path = path

        self.document = QtPdf.QPdfDocument(self)
        self.document.load(path)

        self.view = QtPdfWidgets.QPdfView(self)
        self.view.setDocument(self.document)
        # Continuous flow instead of a single page: when a certificate
        # spills onto a second page, there shouldn't be a button to hunt
        # for just to see it.
        self.view.setPageMode(QtPdfWidgets.QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QtPdfWidgets.QPdfView.ZoomMode.FitToWidth)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        lay.addWidget(self._toolbar())
        lay.addWidget(self.view, 1)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        open_btn = buttons.addButton("Dış uygulamada aç",
                                     QtWidgets.QDialogButtonBox.ActionRole)
        open_btn.clicked.connect(self._open_external)
        lay.addWidget(buttons)

        self._update_status()

    def _toolbar(self):
        bar = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        zoom_out = QtWidgets.QPushButton("−")
        zoom_out.setToolTip("Uzaklaştır")
        zoom_out.clicked.connect(lambda: self._zoom(1 / 1.25))
        zoom_in = QtWidgets.QPushButton("+")
        zoom_in.setToolTip("Yakınlaştır")
        zoom_in.clicked.connect(lambda: self._zoom(1.25))
        fit = QtWidgets.QPushButton("Sayfaya sığdır")
        fit.clicked.connect(self._fit)

        self.status = QtWidgets.QLabel("")
        self.status.setProperty("hint", True)

        row.addWidget(zoom_out)
        row.addWidget(zoom_in)
        row.addWidget(fit)
        row.addSpacing(10)
        row.addWidget(self.status, 1)
        return bar

    def _zoom(self, factor):
        from PySide6 import QtPdfWidgets

        self.view.setZoomMode(QtPdfWidgets.QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(max(0.2, min(6.0, self.view.zoomFactor() * factor)))

    def _fit(self):
        from PySide6 import QtPdfWidgets

        self.view.setZoomMode(QtPdfWidgets.QPdfView.ZoomMode.FitToWidth)

    def _update_status(self):
        from PySide6 import QtPdf

        state = self.document.status()
        if state == QtPdf.QPdfDocument.Status.Error:
            self.status.setText("Belge okunamadı: %s" % self.path)
            return
        size = os.path.getsize(self.path) if os.path.isfile(self.path) else 0
        self.status.setText("%d sayfa · %.0f KB · %s"
                            % (self.document.pageCount(), size / 1024.0,
                               os.path.basename(self.path)))

    def _open_external(self):
        try:
            os.startfile(self.path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Açılamadı", str(exc))


def show(path, parent=None, title=None):
    """Previews the PDF; hands the file off to the OS if no preview is available.

    Returns True if the preview window was opened.
    """
    if not path or not os.path.isfile(path):
        QtWidgets.QMessageBox.warning(
            parent, "Dosya bulunamadı",
            "Belge yerinde değil:\n%s" % (path or "—"))
        return False
    if not is_available():
        try:
            os.startfile(path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(parent, "Açılamadı", str(exc))
        return False
    PdfPreviewDialog(path, parent, title).exec()
    return True
