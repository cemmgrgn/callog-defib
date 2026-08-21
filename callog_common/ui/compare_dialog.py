"""Session comparison — two or more measurements on the same plot.

The visual answer to "how does this year's measurement differ from last
year's". The data already existed, only the view was missing.

Comparison is done at the **measurement point** level, not the session
level: in a multi-point session, plotting 10 V and 1 kΩ on the same Y
axis would make both unreadable. Points whose unit differs from the
first series aren't plotted, and the reason is noted below.

X axis is reading order (1..n), not elapsed time: two sessions may have
used different reading intervals, and a seconds axis would make the
curves drift artificially.
"""

from .. import chart, db, points, sessions, theme
from ..qt import QtGui, QtWidgets
from .util import empty_state, fit_table

#: Color order for series — keys from the theme palette are used cyclically
_SERIES_KEYS = ("curve", "bad", "ok", "warn", "mean", "guide")


class CompareDialog(QtWidgets.QDialog):

    def __init__(self, session_ids, parent=None):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle("Oturum karşılaştırma")
        self.resize(980, 700)
        self.session_ids = list(session_ids)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        import pyqtgraph as pg

        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "Okuma sırası")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.addLegend(offset=(-10, 10))
        lay.addWidget(self.plot, 3)

        self.table = QtWidgets.QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Oturum", "Tarih", "Nokta", "n", "Ortalama", "s", "U (k=2)",
             "Sapma"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 2)

        self.note = QtWidgets.QLabel("")
        self.note.setProperty("hint", True)
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        save_btn = buttons.addButton("Grafiği kaydet",
                                     QtWidgets.QDialogButtonBox.ActionRole)
        save_btn.clicked.connect(self._save_plot)
        lay.addWidget(buttons)

        self._draw()

    # --- drawing ------------------------------------------------------------
    def _draw(self):
        import numpy as np
        import pyqtgraph as pg

        c = theme.colors()
        self.plot.setBackground(QtGui.QColor(c["surface"]))
        for name in ("left", "bottom"):
            axis = self.plot.getAxis(name)
            axis.setPen(pg.mkPen(c["border_strong"]))
            axis.setTextPen(pg.mkPen(c["text_muted"]))

        base_unit = None
        skipped = []
        drawn = 0
        self.table.setRowCount(0)

        for session_id in self.session_ids:
            row = db.query_one("SELECT * FROM sessions WHERE id = ?",
                               (session_id,))
            if row is None:
                continue
            try:
                summaries = points.collect(session_id)
            except Exception:
                continue
            for i, p in enumerate(summaries):
                if p["n"] == 0:
                    continue
                if base_unit is None:
                    base_unit = p["unit"]
                    self.plot.setLabel("left", p["unit"])
                if p["unit"] != base_unit:
                    skipped.append("#%d %s (%s)" % (session_id,
                                                    points.label(p), p["unit"]))
                    continue

                included, _excluded = chart.load_series(
                    session_id, p["point"], is_first=(i == 0))
                if not included:
                    continue
                ys = np.array([v for _x, v in included], dtype=float)
                xs = np.arange(1, len(ys) + 1, dtype=float)
                color = c[_SERIES_KEYS[drawn % len(_SERIES_KEYS)]]
                name = "#%d · %s · %s" % (
                    session_id, (row["started_at"] or "")[:10],
                    points.label(p))
                self.plot.plot(xs, ys, pen=pg.mkPen(color, width=1.5),
                               name=name)
                self._add_row(session_id, row, p, color)
                drawn += 1

        self.plot.getViewBox().autoRange()
        fit_table(self.table, stretch_column=2)
        empty_state(self.table, "Karşılaştırılacak okuma bulunamadı.")

        parts = ["%d seri çizildi." % drawn]
        if skipped:
            parts.append("Birimi farklı olduğu için alınmayanlar: %s."
                         % ", ".join(skipped))
        parts.append("X ekseni okuma sırası — oturumlar farklı okuma "
                     "periyodu kullanmış olabilir.")
        self.note.setText("  ".join(parts))

    def _add_row(self, session_id, session_row, p, color):
        r = self.table.rowCount()
        self.table.insertRow(r)
        unit = p["unit"]

        def f(v):
            return "—" if v is None else "%.7g %s" % (v, unit)

        cells = [
            "#%d %s" % (session_id, sessions.display_name(session_row)),
            (session_row["started_at"] or "")[:10],
            points.label(p), str(p["n"]), f(p["mean"]), f(p["std"]),
            f(p["U"]), f(p["deviation"]),
        ]
        for col, text in enumerate(cells):
            item = QtWidgets.QTableWidgetItem(text)
            if col == 0:
                item.setForeground(QtGui.QColor(color))
            self.table.setItem(r, col, item)

    def _save_plot(self):
        from .acquire_page import export_plot

        path, _f = QtWidgets.QFileDialog.getSaveFileName(
            self, "Karşılaştırma grafiğini kaydet", "karsilastirma.png",
            "PNG görüntü (*.png);;SVG çizim (*.svg)")
        if not path:
            return
        try:
            export_plot(self.plot, path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Kaydedilemedi", str(exc))
