"""Live measurement screen — plot, statistics, recording.

Key distinction: as soon as the screen opens, readings start streaming from
the device into the plot (MONITORING mode), but none of it is written to the
database until "Start certification" is pressed. Without this distinction,
every warm-up fluctuation would end up in the record.
"""

import collections

from .. import audit, db, points as points_svc, stability, theme
from ..acquisition import AcquisitionWorker, Statistics
from ..stats import verdict_ok
from ..qt import Qt, QtCore, QtGui, QtWidgets, Signal
from .util import fit_table, PAGE_MARGIN, PAGE_SPACING

MAX_PLOT_POINTS = 20000
MAX_TABLE_ROWS = 300

#: Compliance criterion labels (shared with setup_page)
CRITERIA_LABELS = {
    "mean": "ortalama ± U",
    "minmax": "tüm okumalar",
}

#: Time window options — (label, seconds). 0 = all, -1 = keep current zoom
TIME_WINDOWS = (
    ("Son 10 sn", 10), ("Son 30 sn", 30), ("Son 1 dk", 60),
    ("Son 5 dk", 300), ("Son 15 dk", 900),
    ("Tümü", 0), ("Yakınlaştırmayı koru", -1),
)


def export_plot(plot_widget, path):
    """Writes the pyqtgraph plot to disk as PNG or SVG.

    For PNG, pyqtgraph's own exporter is tried first: it produces an image
    that's independent of screen resolution and large enough for a report.
    The exporter crashes on some Qt versions; in that case a screen grab of
    the widget itself is used — lower resolution, but better than nothing
    and better than telling the user "couldn't save".
    """
    if path.lower().endswith(".svg"):
        from pyqtgraph.exporters import SVGExporter
        SVGExporter(plot_widget.getPlotItem()).export(path)
        return path
    try:
        from pyqtgraph.exporters import ImageExporter
        exporter = ImageExporter(plot_widget.getPlotItem())
        exporter.parameters()["width"] = 1600
        exporter.export(path)
    except Exception:
        if not plot_widget.grab().save(path):
            raise
    return path


class AcquirePage(QtWidgets.QWidget):

    session_finished = Signal(int)

    def __init__(self, app_state, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.state = app_state
        self.session_id = None
        self.session = None
        self.worker = None
        self.driver = None
        self.recording = False

        self.stats = Statistics()
        self._xs = collections.deque(maxlen=MAX_PLOT_POINTS)
        self._ys = collections.deque(maxlen=MAX_PLOT_POINTS)
        self._pending = []
        self._saved_count = 0
        self._last_t = 0.0

        # The stability window only looks at the last N readings; keeping
        # the whole series would waste memory on long sessions.
        self._interval_s = 1.0
        self._recent = collections.deque(maxlen=stability.DEFAULT_WINDOW)
        self._flagged = {}          # seq -> table row (outlier, not yet excluded)
        self._excluded_seqs = set()
        self._out_of_band = 0

        # Measurement plan: in a single-point session the list is a single
        # row and the panel is hidden.
        self.points = []
        self.point_index = 0

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGIN)
        root.setSpacing(PAGE_SPACING)

        root.addWidget(self._header_bar())
        root.addWidget(self._plot_controls())
        root.addWidget(self._plot_widget(), 3)
        root.addWidget(self._stats_bar())
        root.addWidget(self._stability_bar())

        split = QtWidgets.QSplitter(Qt.Horizontal)
        split.addWidget(self._plan_box())
        split.addWidget(self._table())
        split.addWidget(self._notes_box())
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 1)
        root.addWidget(split, 2)

        root.addLayout(self._buttons())

        self._flush_timer = QtCore.QTimer(self)
        self._flush_timer.setInterval(1000)
        self._flush_timer.timeout.connect(self._flush)

    # --- UI components ---------------------------------------------------
    def _header_bar(self):
        w = QtWidgets.QFrame()
        w.setProperty("card", True)
        self.header_label = QtWidgets.QLabel("")
        self.header_label.setWordWrap(True)
        self.target_label = QtWidgets.QLabel("")
        self.target_label.setWordWrap(True)
        self.rec_label = QtWidgets.QLabel("İZLEME")
        self.rec_label.setMinimumWidth(84)
        self.rec_label.setAlignment(Qt.AlignCenter)
        text = QtWidgets.QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(self.header_label)
        text.addWidget(self.target_label)

        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.addLayout(text, 1)
        lay.addWidget(self.rec_label)
        return w

    def _plot_controls(self):
        w = QtWidgets.QFrame()
        w.setProperty("card", True)
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(10)

        lay.addWidget(QtWidgets.QLabel("Pencere"))
        self.window_combo = QtWidgets.QComboBox()
        for label, seconds in TIME_WINDOWS:
            self.window_combo.addItem(label, seconds)
        # The longest option ("Keep zoom") forced a base width over 300px on
        # the closed combo box; this determined the narrowest the page could
        # be drawn, and the window didn't fit on 1366px screens. The text
        # still shows in full in the dropdown list — only the closed state
        # is shortened.
        self.window_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.window_combo.setMinimumContentsLength(12)
        self.window_combo.setCurrentIndex(2)          # Son 1 dk
        self.window_combo.currentIndexChanged.connect(self._refresh_view)
        lay.addWidget(self.window_combo)

        self.follow_chk = QtWidgets.QCheckBox("Takip et")
        self.follow_chk.setChecked(True)
        self.follow_chk.setToolTip(
            "Açıkken grafik en son okumayı izlemeye devam eder.\n"
            "Yakınlaştırdıktan sonra da çalışır: pencere genişliği korunur,\n"
            "görünüm veriyle birlikte kayar.")
        self.follow_chk.toggled.connect(self._refresh_view)
        lay.addWidget(self.follow_chk)

        self.autoscale_chk = QtWidgets.QCheckBox("Y otomatik")
        self.autoscale_chk.setChecked(True)
        self.autoscale_chk.setToolTip(
            "Y ekseni gelen veriye göre kendini ölçekler.\n"
            "Kapatınca fare tekerleğiyle yaptığınız ölçek korunur.")
        self.autoscale_chk.toggled.connect(self._refresh_view)
        lay.addWidget(self.autoscale_chk)

        self.grid_chk = QtWidgets.QCheckBox("Izgara")
        self.grid_chk.setChecked(True)
        self.grid_chk.toggled.connect(
            lambda on: self.plot.showGrid(x=on, y=on, alpha=theme.colors()["grid"]))
        lay.addWidget(self.grid_chk)

        self.tol_chk = QtWidgets.QCheckBox("Tolerans bantları")
        self.tol_chk.setChecked(True)
        self.tol_chk.toggled.connect(self._draw_tolerance)
        lay.addWidget(self.tol_chk)

        lay.addStretch(1)

        export_btn = QtWidgets.QPushButton("Grafiği kaydet")
        export_btn.setToolTip(
            "Görünen grafiği PNG ya da SVG olarak kaydeder.\n"
            "Rapora veya e-postaya koymak için — sertifikanın grafiği\n"
            "ayrıca üretilir, bu dosya onun yerine geçmez.")
        export_btn.clicked.connect(self._export_plot)
        lay.addWidget(export_btn)

        reset_btn = QtWidgets.QPushButton("Görünümü sıfırla")
        reset_btn.setToolTip("Takip ve otomatik ölçeklemeyi açar, "
                             "yakınlaştırmayı kaldırır.")
        reset_btn.clicked.connect(self._reset_view)
        lay.addWidget(reset_btn)
        return w

    def _plot_widget(self):
        import pyqtgraph as pg

        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "Süre", units="s")
        self.plot.setMouseEnabled(x=True, y=True)
        self.plot.setMenuEnabled(True)

        # Auto range is off so the user can drag-zoom with the mouse; the
        # view is managed by _refresh_view instead.
        self.plot.getViewBox().setAutoVisible(y=True)

        self.curve = self.plot.plot()
        self.mean_line = pg.InfiniteLine(angle=0, movable=False)
        self.plot.addItem(self.mean_line)

        self._tol_lines = []
        # ignoreBounds is required: the crosshair label initially sits at
        # (0, 0), and if included in autoscaling it stretches the Y axis
        # down to zero.
        self._crosshair = pg.TextItem(anchor=(0, 1))
        self.plot.addItem(self._crosshair, ignoreBounds=True)
        self.plot.scene().sigMouseMoved.connect(self._on_mouse_moved)

        self.apply_plot_theme()
        return self.plot

    def apply_plot_theme(self):
        """Applies the app's theme colors to the plot.

        pyqtgraph doesn't use the Qt palette; MainWindow calls this again
        whenever the theme changes.
        """
        import pyqtgraph as pg

        c = theme.colors()
        self.plot.setBackground(QtGui.QColor(c["surface"]))
        for name in ("left", "bottom"):
            axis = self.plot.getAxis(name)
            axis.setPen(pg.mkPen(c["border_strong"]))
            axis.setTextPen(pg.mkPen(c["text_muted"]))
        self.plot.showGrid(x=self.grid_chk.isChecked(),
                           y=self.grid_chk.isChecked(), alpha=c["grid"])
        self.curve.setPen(pg.mkPen(c["curve"], width=1.6))
        self.mean_line.setPen(pg.mkPen(c["mean"], width=1, style=Qt.DashLine))
        self._crosshair.setColor(QtGui.QColor(c["text_muted"]))
        for line in self._tol_lines:
            line.setPen(pg.mkPen(c["guide"], width=1, style=Qt.DotLine))

    def _stats_bar(self):
        w = QtWidgets.QFrame()
        w.setProperty("card", True)
        grid = QtWidgets.QGridLayout(w)
        grid.setContentsMargins(14, 10, 14, 10)
        self._stat_labels = {}
        fields = [
            ("last", "Anlık"), ("n", "n"), ("mean", "Ortalama"),
            ("std", "Std sapma"), ("u_a", "u (A tipi)"),
            ("min", "En küçük"), ("max", "En büyük"),
            ("dev", "Sapma"), ("verdict", "Durum"),
        ]
        for col, (key, label) in enumerate(fields):
            cap = QtWidgets.QLabel(label)
            cap.setProperty("statcap", True)
            val = QtWidgets.QLabel("—")
            val.setProperty("stat", True)
            grid.addWidget(cap, 0, col)
            grid.addWidget(val, 1, col)
            grid.setColumnStretch(col, 1)
            self._stat_labels[key] = val
        return w

    def _stability_bar(self):
        """Stability indicator, autostop condition and alert strip.

        When a measurement ends used to be the operator's judgment call;
        showing the condition on screen keeps the same measurement from
        taking a different amount of time depending on who runs it.
        """
        w = QtWidgets.QFrame()
        w.setProperty("card", True)
        grid = QtWidgets.QGridLayout(w)
        grid.setContentsMargins(14, 8, 14, 8)
        grid.setHorizontalSpacing(10)

        cap = QtWidgets.QLabel("Kararlılık")
        cap.setProperty("statcap", True)
        self.stability_label = QtWidgets.QLabel("—")
        self.stability_label.setMinimumWidth(120)
        self.stability_label.setToolTip(
            "Son %d okumaya bakılır.\n\n"
            "kararlı — biriken yönlü değişim gürültünün altında\n"
            "oturuyor — okuma hâlâ bir yöne kayıyor\n"
            "saçılım geniş — okumalar tolerans bandından geniş saçılıyor"
            % stability.DEFAULT_WINDOW)

        self.target_spin = QtWidgets.QSpinBox()
        self.target_spin.setRange(0, 100000)
        self.target_spin.setValue(0)
        self.target_spin.setSpecialValueText("sınırsız")
        self.target_spin.setToolTip(
            "Bu kadar okuma kaydedilince kayıt kendiliğinden durur.\n"
            "Oturum kapanmaz — sonucu görüp 'Oturumu bitir' dersiniz.")
        self.target_spin.valueChanged.connect(self._update_progress)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setMinimumWidth(120)
        self.progress.setTextVisible(True)
        self.progress.setFormat("%v okuma")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)

        self.autostop_chk = QtWidgets.QCheckBox("Kararlı olunca durdur")
        self.autostop_chk.setToolTip(
            "Kararlılık göstergesi 'kararlı' olduğunda kaydı durdurur.\n"
            "En az %d okuma alınmadan tetiklenmez." % stability.DEFAULT_WINDOW)
        self.beep_chk = QtWidgets.QCheckBox("Sesli uyar")
        self.beep_chk.setToolTip(
            "Okuma tolerans bandının dışına çıktığında sesli uyarı.\n"
            "Grafiğe bakılmadığında sapma geç fark ediliyor.")

        grid.addWidget(cap, 0, 0)
        grid.addWidget(self.stability_label, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Hedef okuma"), 0, 2)
        grid.addWidget(self.target_spin, 0, 3)
        grid.addWidget(self.progress, 0, 4)
        grid.addWidget(self.autostop_chk, 0, 5)
        grid.addWidget(self.beep_chk, 0, 6)
        grid.setColumnStretch(4, 1)

        self.alert_label = QtWidgets.QLabel("")
        self.alert_label.setWordWrap(True)
        self.alert_label.setVisible(False)
        self.flag_btn = QtWidgets.QPushButton("Aykırı okumaları dışla…")
        self.flag_btn.setVisible(False)
        self.flag_btn.clicked.connect(self._exclude_flagged)
        grid.addWidget(self.alert_label, 1, 0, 1, 6)
        grid.addWidget(self.flag_btn, 1, 6)
        return w

    def _table(self):
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["#", "Süre (s)", "Saat", "Değer", "Durum"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        # So multiple readings can be excluded with a single reason
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        # The button below only offers exclusion; there was no other way to
        # undo an exclusion or to copy readings to the clipboard.
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        fit_table(self.table, stretch_column=4)
        return self.table

    def _plan_box(self):
        """Measurement plan panel — **never shown** in a single-point session.

        Showing an operator measuring a single point a panel that says
        "1/1 point" would do nothing but take up space.
        """
        self.plan_box = QtWidgets.QGroupBox("Ölçüm planı")
        lay = QtWidgets.QVBoxLayout(self.plan_box)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self.plan_table = QtWidgets.QTableWidget(0, 4)
        self.plan_table.setHorizontalHeaderLabels(["#", "Nokta", "n", "Durum"])
        self.plan_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.plan_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.plan_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.plan_table.setAlternatingRowColors(True)
        self.plan_table.verticalHeader().setVisible(False)
        lay.addWidget(self.plan_table, 1)

        self.plan_note = QtWidgets.QLabel("")
        self.plan_note.setProperty("hint", True)
        self.plan_note.setWordWrap(True)
        lay.addWidget(self.plan_note)
        self.plan_box.setVisible(False)
        return self.plan_box

    def _notes_box(self):
        box = QtWidgets.QGroupBox("Oturum notları")
        self.notes_edit = QtWidgets.QPlainTextEdit()
        self.notes_edit.setPlaceholderText(
            "Ölçüm sırasındaki gözlemler. Kayda geçer, sertifikaya eklenmez.")
        lay = QtWidgets.QVBoxLayout(box)
        lay.addWidget(self.notes_edit)
        return box

    def _buttons(self):
        row = QtWidgets.QHBoxLayout()
        self.start_rec_btn = QtWidgets.QPushButton("Sertifikasyonu başlat")
        self.start_rec_btn.setProperty("primary", True)
        self.start_rec_btn.setMinimumHeight(38)
        self.start_rec_btn.clicked.connect(self._start_recording)

        self.pause_btn = QtWidgets.QPushButton("Duraklat")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._toggle_pause)

        self.exclude_btn = QtWidgets.QPushButton("Seçili okumaları dışla")
        self.exclude_btn.setToolTip(
            "Ctrl veya Shift ile birden fazla satır seçebilirsiniz.\n"
            "Dışlanan okumalar silinmez, sertifika hesabından çıkarılır.")
        self.exclude_btn.clicked.connect(self._exclude_selected)
        self.exclude_btn.setEnabled(False)

        self.next_point_btn = QtWidgets.QPushButton("Sonraki nokta")
        self.next_point_btn.setToolTip(
            "Bu noktayı tamamlar ve plandaki sıradaki noktaya geçer.\n"
            "Cihaz yeni fonksiyona ayarlanır; okumalar ayrı ayrı saklanır.")
        self.next_point_btn.clicked.connect(self._next_point)
        self.next_point_btn.setVisible(False)

        self.finish_btn = QtWidgets.QPushButton("Oturumu bitir")
        self.finish_btn.setProperty("danger", True)
        self.finish_btn.clicked.connect(self._finish)

        row.addWidget(self.start_rec_btn)
        row.addWidget(self.next_point_btn)
        row.addWidget(self.pause_btn)
        row.addWidget(self.exclude_btn)
        row.addStretch(1)
        row.addWidget(self.finish_btn)
        return row

    # --- session lifecycle ------------------------------------------------
    def begin(self, session_id, driver, interval_s=1.0):
        # Tear down any thread left over from a previous session first;
        # otherwise two reading loops run at once and pause only affects
        # the latest one.
        self._teardown_worker()

        self.session_id = session_id
        self.driver = driver
        self.session = db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
        self.recording = False
        self._saved_count = 0
        self._last_t = 0.0
        self._interval_s = interval_s or 1.0
        self.stats.reset()
        self._xs.clear()
        self._ys.clear()
        self._recent.clear()
        self._flagged = {}
        self._excluded_seqs = set()
        self._out_of_band = 0
        self._clear_alert()
        self._update_stability()
        self._update_progress()
        self._pending = []
        self.table.setRowCount(0)
        self.notes_edit.clear()
        self._reset_controls()
        for key in self._stat_labels:
            self._stat_labels[key].setText("—")

        dut = db.query_one("SELECT * FROM duts WHERE id = ?", (self.session["dut_id"],))
        inst = db.query_one("SELECT * FROM instruments WHERE id = ?",
                            (self.session["instrument_id"],))
        sim = (" &nbsp;·&nbsp; <b style='color:%s'>SİMÜLASYON</b>"
               % theme.colors()["warn"] if self.session["is_simulated"] else "")
        self.header_label.setText(
            "<b>%s %s</b> (SN %s) &nbsp;·&nbsp; %s &nbsp;·&nbsp; Referans: %s %s "
            "&nbsp;·&nbsp; Operatör: %s%s" % (
                dut["manufacturer"], dut["model"], dut["serial_no"],
                self.session["function"], inst["brand"], inst["model"],
                self.state.user["full_name"], sim))

        self.points = points_svc.ensure_default(session_id)
        self.point_index = 0
        self._apply_point()
        self._reset_view()

        self.worker = AcquisitionWorker(self.driver, interval_s=interval_s, parent=self)
        self.worker.reading.connect(self._on_reading)
        self.worker.error.connect(self._on_error)
        self.worker.start()
        self._flush_timer.start()

    # --- measurement plan ---------------------------------------------------
    @property
    def current_point(self):
        if 0 <= self.point_index < len(self.points):
            return self.points[self.point_index]
        return None

    def _apply_point(self, reconfigure=False):
        """Sets up labels, plot and device for the current point."""
        point = self.current_point
        multi = len(self.points) > 1
        self.plan_box.setVisible(multi)
        self.next_point_btn.setVisible(multi)

        if point is None:
            return
        self._update_target_label()
        self.plot.setLabel("left", "%s (%s)" % (point["function"], point["unit"]))
        self._draw_tolerance()
        self._fill_plan_table()

        if reconfigure and self.worker is not None:
            settings = {"channel": point["channel"]} if point["channel"] else {}
            # The point's nominal value is also sent to the simulation
            # driver (the setup screen does the same): otherwise every
            # point in the plan would read the single value entered at
            # the start of the session.
            if getattr(self.driver, "is_simulated", False):
                settings["nominal"] = point["nominal"]
            self.worker.request_configure(point["function"], **settings)

        if multi:
            self.plan_note.setText(
                "%d / %d nokta · %s"
                % (self.point_index + 1, len(self.points),
                   points_svc.label(point)))

    def _fill_plan_table(self):
        c = theme.colors()
        self.plan_table.setRowCount(0)
        for i, p in enumerate(self.points):
            r = self.plan_table.rowCount()
            self.plan_table.insertRow(r)
            n = db.query_one(
                "SELECT COUNT(*) AS n FROM readings WHERE session_id = ?"
                " AND (point_id = ? OR (point_id IS NULL AND ? = 1))",
                (self.session_id, p["id"], 1 if i == 0 else 0))["n"]
            state = points_svc.STATUS_TR.get(p["status"], p["status"])
            if i == self.point_index and self.recording:
                state = "ölçülüyor"
            cells = [str(p["seq"]), points_svc.label(p), str(n), state]
            for col, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(text)
                if i == self.point_index:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                elif p["status"] == points_svc.DONE:
                    item.setForeground(QtGui.QColor(c["text_muted"]))
                self.plan_table.setItem(r, col, item)
        fit_table(self.plan_table, stretch_column=1)

    def _next_point(self):
        """Finishes this point, advances to the next one."""
        point = self.current_point
        if point is None or self.point_index + 1 >= len(self.points):
            return
        nxt = self.points[self.point_index + 1]
        ans = QtWidgets.QMessageBox.question(
            self, "Sonraki nokta",
            "%d. nokta (%s) tamamlanacak ve %d. noktaya (%s) geçilecek.\n\n"
            "Kaynağı yeni değere ayarladıktan sonra 'Sertifikasyonu başlat'a "
            "basın. Devam edilsin mi?"
            % (point["seq"], points_svc.label(point), nxt["seq"],
               points_svc.label(nxt)),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if ans != QtWidgets.QMessageBox.Yes:
            return

        self._flush()
        if self.recording:
            self._stop_recording("sonraki noktaya geçildi")
        points_svc.finish(point["id"])
        audit.log("session.point_done", user_id=self.state.user["id"],
                  entity="session", entity_id=self.session_id,
                  detail={"point": point["seq"], "readings": self.stats.n})

        self.points = points_svc.list_for(self.session_id)
        self.point_index += 1
        # A new point is a new measurement: stats, table and alerts reset.
        self.stats.reset()
        self._recent.clear()
        self.table.setRowCount(0)
        self._clear_alert()
        self._update_stats()
        self._update_stability()
        self._update_progress()
        self._apply_point(reconfigure=True)
        self._reset_controls()
        self.state.status("%d. noktaya geçildi: %s"
                          % (self.current_point["seq"],
                             points_svc.label(self.current_point)))

    def _reset_controls(self):
        """Returns the buttons and badge to monitoring mode.

        Called both when a new session starts and when a session ends:
        otherwise the button would still read "Certification in progress"
        after the session was over.
        """
        self.recording = False
        self.start_rec_btn.setText("Sertifikasyonu başlat")
        self.start_rec_btn.setProperty("primary", True)
        self.start_rec_btn.style().polish(self.start_rec_btn)
        self.start_rec_btn.setEnabled(True)
        self.exclude_btn.setEnabled(False)
        self.pause_btn.setChecked(False)
        self._set_recording_badge(False)

    def _target(self):
        """Target of the current point: (nominal, tolerance, unit, criterion).

        Falls back to the session's own columns when there's no point — for
        code paths that request a redraw without `begin()` having been
        called (e.g. a theme change).
        """
        point = self.current_point
        if point is not None:
            mode = point["tolerance_mode"]
            return (point["nominal"], point["tolerance"], point["unit"],
                    mode if mode in ("mean", "minmax") else "mean")
        if self.session is None:
            return None, None, "", "mean"
        mode = self.session["tolerance_mode"]
        return (self.session["nominal"], self.session["tolerance"],
                self.session["unit"],
                mode if mode in ("mean", "minmax") else "mean")

    def _update_target_label(self):
        """The nominal value, tolerance and compliance criterion the operator entered."""
        c = theme.colors()
        nominal, tol, unit, _mode = self._target()
        point = self.current_point
        prefix = ""
        if len(self.points) > 1 and point is not None:
            prefix = "<b>%d/%d. nokta</b> &nbsp;·&nbsp; " % (
                self.point_index + 1, len(self.points))

        if nominal is None:
            self.target_label.setText(
                "%s<span style='color:%s'>Nominal değer girilmedi — uygunluk "
                "kararı verilmez.</span>" % (prefix, c["text_muted"]))
            return

        parts = ["%s<b>Hedef:</b> %g %s" % (prefix, nominal, unit)]
        if tol:
            parts.append("<b>± %g %s</b>" % (tol, unit))
            parts.append("(%g … %g %s)" % (nominal - tol, nominal + tol, unit))
            parts.append("· Kriter: %s" % CRITERIA_LABELS[self._tolerance_mode()])
        else:
            parts.append("<span style='color:%s'>· tolerans girilmedi</span>"
                         % c["text_muted"])
        self.target_label.setText(" &nbsp; ".join(parts))

    def _tolerance_mode(self):
        return self._target()[3]

    def _draw_tolerance(self):
        import pyqtgraph as pg

        for line in self._tol_lines:
            self.plot.removeItem(line)
        self._tol_lines = []
        if self.session is None or not self.tol_chk.isChecked():
            return

        nominal, tol, _unit, _mode = self._target()
        if nominal is None:
            return
        pen = pg.mkPen(theme.colors()["guide"], width=1, style=Qt.DotLine)
        for y in ([nominal] if not tol else [nominal, nominal + tol, nominal - tol]):
            line = pg.InfiniteLine(pos=y, angle=0, pen=pen)
            self.plot.addItem(line)
            self._tol_lines.append(line)

    # --- view management ---------------------------------------------------
    def _window_seconds(self):
        return self.window_combo.currentData()

    def _refresh_view(self):
        """Aligns the plot to the latest data according to the follow setting."""
        vb = self.plot.getViewBox()

        if self.autoscale_chk.isChecked():
            vb.enableAutoRange(axis="y")
        else:
            vb.disableAutoRange(axis="y")

        if not self.follow_chk.isChecked():
            vb.disableAutoRange(axis="x")
            return

        win = self._window_seconds()
        t = self._last_t
        if win == 0:                       # all
            vb.enableAutoRange(axis="x")
        elif win == -1:                    # keep current zoom
            (x0, x1), _ = vb.viewRange()
            width = max(1e-3, x1 - x0)
            vb.setXRange(t - width, t, padding=0)
        else:
            vb.setXRange(max(0.0, t - win), max(win, t), padding=0)

    def _reset_view(self):
        self.follow_chk.setChecked(True)
        self.autoscale_chk.setChecked(True)
        self.plot.getViewBox().enableAutoRange(axis="xy")
        self._refresh_view()

    def _on_mouse_moved(self, pos):
        """A small label so the time/value at the cursor position can be read."""
        if not self.plot.sceneBoundingRect().contains(pos):
            self._crosshair.setText("")
            return
        pt = self.plot.getViewBox().mapSceneToView(pos)
        unit = self.session["unit"] if self.session else ""
        self._crosshair.setText("%.2f s   %.7g %s" % (pt.x(), pt.y(), unit))
        self._crosshair.setPos(pt.x(), pt.y())

    # --- data flow ----------------------------------------------------------
    def _on_reading(self, seq, ts, value, raw, elapsed):
        self._last_t = elapsed
        self._xs.append(elapsed)
        self._ys.append(value)
        self._recent.append(value)
        self.curve.setData(list(self._xs), list(self._ys))
        self._refresh_view()

        if self.recording:
            # Outlier status is checked **before** the reading enters the
            # statistics: comparing against a mean that already includes
            # the value itself makes the deviation look smaller than it is.
            flagged = stability.is_outlier(value, self.stats.mean,
                                           self.stats.std, self.stats.n)
            self.stats.add(value)
            point = self.current_point
            self._pending.append((self.session_id,
                                  point["id"] if point else None, seq, ts,
                                  value, point["unit"] if point
                                  else self.session["unit"], raw, elapsed))
            self.mean_line.setValue(self.stats.mean)
            row = self._add_table_row(seq, elapsed, ts, value,
                                      "AYKIRI" if flagged else "kayıt",
                                      warn=flagged)
            if flagged:
                self._flagged[seq] = row
            self._update_stats()
            self._check_band(value)
            self._update_progress()
        else:
            self._add_table_row(seq, elapsed, ts, value, "izleme")
            self._stat_labels["last"].setText(self._fmt(value))

        # Also shown during monitoring: this indicator is itself the answer
        # to "when should I start recording?".
        self._update_stability()
        self._refresh_alert()
        if self.recording:
            self._maybe_autostop()

    def _add_table_row(self, seq, elapsed, ts, value, status, warn=False):
        """Adds a row to the table and returns the row number.

        The row number is needed to find outliers again later; since rows
        get removed from the top once the table exceeds `MAX_TABLE_ROWS`,
        it isn't fixed and is kept in sync via `_shift_rows`.
        """
        if self.table.rowCount() >= MAX_TABLE_ROWS:
            self.table.removeRow(0)
            self._shift_rows()
        r = self.table.rowCount()
        self.table.insertRow(r)
        cells = (str(seq), "%.2f" % elapsed, ts[11:19], self._fmt(value), status)
        warn_color = QtGui.QColor(theme.colors()["warn"])
        for col, text in enumerate(cells):
            item = QtWidgets.QTableWidgetItem(text)
            if col == 0:
                item.setData(Qt.UserRole, seq)
            if warn:
                item.setForeground(warn_color)
            self.table.setItem(r, col, item)
        self.table.scrollToBottom()
        return r

    def _shift_rows(self):
        """Shifts stored row numbers when a row is removed from the top of the table."""
        self._flagged = {seq: row - 1 for seq, row in self._flagged.items()
                         if row - 1 >= 0}

    def _update_stats(self):
        s = self.stats
        self._stat_labels["last"].setText(self._fmt(s.last))
        self._stat_labels["n"].setText(str(s.n))
        self._stat_labels["mean"].setText(self._fmt(s.mean))
        self._stat_labels["std"].setText(self._fmt_spread(s.std))
        self._stat_labels["u_a"].setText(self._fmt_spread(s.u_a))
        self._stat_labels["min"].setText(self._fmt(s.min))
        self._stat_labels["max"].setText(self._fmt(s.max))

        nominal, tol, _unit, mode = self._target()
        if nominal is None:
            self._stat_labels["dev"].setText("—")
            self._stat_labels["verdict"].setText("—")
            return
        dev = s.mean - nominal
        self._stat_labels["dev"].setText(self._fmt_spread(dev, digits=3))

        if not tol:
            self._stat_labels["verdict"].setText("—")
            return
        ok = verdict_ok(mode, nominal, tol, s.mean, s.u_a, s.min, s.max)
        c = theme.colors()
        self._stat_labels["verdict"].setText("UYGUN" if ok else "UYGUN DEĞİL")
        self._stat_labels["verdict"].setStyleSheet(
            "font-size:17px; font-weight:600; color:%s;"
            % (c["ok"] if ok else c["bad"]))

    def _fmt(self, v):
        return "—" if v is None else "%.7g" % v

    def _fmt_spread(self, v, digits=2):
        """Short display for spread magnitudes (s, u, deviation).

        Every digit of a measurement value is meaningful, but not every
        digit of a standard deviation: `%.7g` would print something like
        "0.0001875474" that the eye can't parse, and the column width would
        shift with every reading. The GUM also says expanded uncertainty
        should be given with at most two significant digits.
        """
        if v is None:
            return "—"
        return "%.*g" % (digits, v)

    # --- stability, outlier readings, tolerance alert ----------------------
    def _update_stability(self):
        tol = self._target()[1]
        info = stability.assess(self._recent, interval_s=self._interval_s,
                                tolerance=tol)
        self._stability = info
        c = theme.colors()
        text = stability.STATE_TR[info["state"]]
        if info["state"] != stability.UNKNOWN:
            text += "  (s = %s)" % self._fmt_spread(info["std"])
        self.stability_label.setText(text)
        self.stability_label.setStyleSheet(
            "font-weight:600; color:%s;" % c[stability.STATE_COLOR[info["state"]]])

    def _update_progress(self):
        target = self.target_spin.value()
        n = self.stats.n
        if target > 0:
            self.progress.setRange(0, target)
            self.progress.setFormat("%v / %m okuma")
            self.progress.setValue(min(n, target))
        else:
            # Filling the bar with no target would be misleading: we print
            # the count and leave the bar empty.
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.progress.setFormat("%d okuma" % n)

    def _check_band(self, value):
        """Whether a reading fell outside the tolerance band — warns, doesn't block."""
        if self.session is None:
            return
        nominal, tol, _unit, _mode = self._target()
        if nominal is None or not tol:
            return
        if abs(value - nominal) <= abs(tol):
            return
        self._out_of_band += 1
        if self.beep_chk.isChecked():
            QtWidgets.QApplication.beep()

    def _refresh_alert(self):
        c = theme.colors()
        parts = []
        if self._flagged:
            parts.append(
                "<span style='color:%s'><b>%d aykırı okuma işaretlendi</b> "
                "(|x − x̄| &gt; %g s). Kayıttan çıkarılmadı — dışlama kararı "
                "sizin.</span>" % (c["warn"], len(self._flagged),
                                   stability.OUTLIER_K))
        if self._out_of_band:
            parts.append(
                "<span style='color:%s'><b>%d okuma tolerans bandının dışında."
                "</b></span>" % (c["bad"], self._out_of_band))
        self.flag_btn.setVisible(bool(self._flagged))
        self.alert_label.setText(" &nbsp;·&nbsp; ".join(parts))
        self.alert_label.setVisible(bool(parts))

    def _clear_alert(self):
        self._flagged = {}
        self._out_of_band = 0
        self.flag_btn.setVisible(False)
        self.alert_label.setText("")
        self.alert_label.setVisible(False)

    def _maybe_autostop(self):
        """Stops recording if the autostop condition is met."""
        target = self.target_spin.value()
        if target and self.stats.n >= target:
            self._stop_recording("hedef okuma sayısına ulaşıldı (%d)" % target)
            return
        info = getattr(self, "_stability", None)
        if (self.autostop_chk.isChecked() and info
                and info["state"] == stability.STABLE
                and info["n"] >= stability.DEFAULT_WINDOW):
            self._stop_recording("okuma kararlı hale geldi")

    def _stop_recording(self, reason):
        """Stops recording — does NOT close the session.

        If autostop also ended the session, the screen would change before
        the operator saw the result, and there would be no chance to
        exclude an outlier reading either. The button isn't re-enabled: a
        second round of recording in the same session would end up in the
        same certificate as the first.
        """
        if not self.recording:
            return
        self.recording = False
        self._flush()
        self._set_recording_badge(False)
        self.start_rec_btn.setText("Kayıt durduruldu")
        audit.log("session.recording_stop", user_id=self.state.user["id"],
                  entity="session", entity_id=self.session_id,
                  detail={"reason": reason, "readings": self.stats.n})
        self.state.status("Kayıt durduruldu — %s. %d okuma kaydedildi."
                          % (reason, self.stats.n))

    def _flush(self):
        """Writes accumulated readings to the database in a batch."""
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        conn = db.connect()
        conn.executemany(
            "INSERT INTO readings (session_id, point_id, seq, ts_utc, value,"
            " unit, raw, elapsed_s) VALUES (?,?,?,?,?,?,?,?)", batch)
        conn.commit()
        self._saved_count += len(batch)
        # The "n" column in the plan panel is read from the database; if
        # refreshed before the buffer is flushed it stayed at 0 throughout
        # the measurement.
        if len(self.points) > 1:
            self._fill_plan_table()

    def _on_error(self, message):
        self.state.status(message)
        QtWidgets.QMessageBox.warning(self, "Cihaz uyarısı", message)

    # --- user actions -------------------------------------------------------
    def _start_recording(self):
        if self.recording:
            return
        self.recording = True
        self.stats.reset()
        self.table.setRowCount(0)
        self._clear_alert()
        self._update_progress()
        self.start_rec_btn.setText("Sertifikasyon sürüyor")
        self.start_rec_btn.setProperty("primary", False)
        self.start_rec_btn.setEnabled(False)
        # Qt doesn't automatically reapply the stylesheet when a property changes
        self.start_rec_btn.style().polish(self.start_rec_btn)
        self.exclude_btn.setEnabled(True)
        self._set_recording_badge(True)
        point = self.current_point
        if point is not None:
            points_svc.start(point["id"])
            self.points = points_svc.list_for(self.session_id)
            self._fill_plan_table()
        audit.log("session.recording_start", user_id=self.state.user["id"],
                  entity="session", entity_id=self.session_id,
                  detail={"point": point["seq"] if point else None})

    def _set_recording_badge(self, on):
        c = theme.colors()
        if on:
            self.rec_label.setText("● KAYIT")
            self.rec_label.setStyleSheet(
                "color:#FFFFFF; background:%s; font-weight:600; padding:5px 12px;"
                "border-radius:6px;" % c["bad"])
        else:
            self.rec_label.setText("İZLEME")
            self.rec_label.setStyleSheet(
                "color:%s; background:%s; font-weight:600; padding:5px 12px;"
                "border-radius:6px; border:1px solid %s;"
                % (c["text_muted"], c["surface_alt"], c["border"]))

    def _toggle_pause(self, paused):
        if self.worker:
            self.worker.set_paused(paused)
        self.pause_btn.setText("Devam et" if paused else "Duraklat")

    def _selected_pairs(self):
        """(table row, seq) pairs for the selected rows."""
        pairs = []
        for r in self.table.selectionModel().selectedRows():
            seq = self.table.item(r.row(), 0).data(Qt.UserRole)
            if seq is not None:
                pairs.append((r.row(), seq))
        return pairs

    def _mark_row(self, table_row, seq, text, color_key=None):
        """Updates the row's status cell — if the row still is that reading.

        Rows get removed from the top once the table exceeds
        `MAX_TABLE_ROWS`, so a stored row number may now point at a
        different reading.
        """
        head = self.table.item(table_row, 0)
        if head is None or head.data(Qt.UserRole) != seq:
            return
        cell = self.table.item(table_row, 4)
        if cell is None:
            return
        cell.setText(text)
        if color_key:
            color = QtGui.QColor(theme.colors()[color_key])
            for col in range(self.table.columnCount()):
                item = self.table.item(table_row, col)
                if item is not None:
                    item.setForeground(color)

    def _exclude_selected(self):
        """Excludes selected readings — the reading is NOT deleted, just marked excluded."""
        pairs = self._selected_pairs()
        if not pairs:
            QtWidgets.QMessageBox.information(
                self, "Seçim yok",
                "Önce tablodan bir veya birden fazla okuma seçin.\n"
                "Ctrl ile tek tek, Shift ile aralık seçebilirsiniz.")
            return
        self._ask_and_exclude(pairs)

    def _exclude_flagged(self):
        """Excludes all flagged outlier readings with a single reason.

        The prompt isn't a modal dialog at the moment a reading comes in:
        opening a window for every outlier while a measurement is running
        would break the flow and stall the device. Instead it's asked once,
        after flags have accumulated.
        """
        pairs = sorted((row, seq) for seq, row in self._flagged.items())
        if not pairs:
            return
        self._ask_and_exclude(
            pairs, default_reason="Aykırı okuma (|x − x̄| > %g s)"
            % stability.OUTLIER_K)

    def _ask_and_exclude(self, pairs, default_reason=""):
        reason, ok = QtWidgets.QInputDialog.getText(
            self, "Okumaları dışla",
            "%d okuma dışlanacak. Gerekçe (kayda geçer, okumalar silinmez):"
            % len(pairs), QtWidgets.QLineEdit.Normal, default_reason)
        if not ok or not reason.strip():
            return

        self._flush()   # make sure the selected readings are in the database
        reason = reason.strip()
        excluded, missing = [], 0
        for table_row, seq in pairs:
            row = db.query_one(
                "SELECT id FROM readings WHERE session_id = ? AND seq = ?",
                (self.session_id, seq))
            if row is None:
                missing += 1
                continue
            db.execute(
                "INSERT OR IGNORE INTO reading_exclusions (reading_id, user_id,"
                " reason, ts_utc) VALUES (?,?,?,?)",
                (row["id"], self.state.user["id"], reason, db.utc_now()))
            self._mark_row(table_row, seq, "dışlandı", "text_muted")
            self._flagged.pop(seq, None)
            self._excluded_seqs.add(seq)
            excluded.append(seq)

        if excluded:
            # Single audit entry: a batch operation with the same reason is one event
            audit.log("reading.exclude", user_id=self.state.user["id"],
                      entity="session", entity_id=self.session_id,
                      detail={"seqs": excluded, "count": len(excluded),
                              "reason": reason})
        self._refresh_alert()
        msg = "%d okuma dışlandı. Kayıttan silinmedi." % len(excluded)
        if missing:
            msg += " %d okuma henüz kaydedilmemişti." % missing
        self.state.status(msg)

    def _include_selected(self):
        """Undoes an exclusion. The reading was never deleted, only the mark is lifted."""
        pairs = self._selected_pairs()
        if not pairs:
            return
        reason, ok = QtWidgets.QInputDialog.getText(
            self, "Dışlamayı kaldır",
            "%d okuma yeniden hesaba katılacak.\nGerekçe (kayda geçer):"
            % len(pairs))
        if not ok or not reason.strip():
            return

        reason = reason.strip()
        restored = []
        for table_row, seq in pairs:
            row = db.query_one(
                "SELECT r.id AS rid, e.id AS eid FROM readings r"
                " LEFT JOIN reading_exclusions e ON e.reading_id = r.id"
                " WHERE r.session_id = ? AND r.seq = ?", (self.session_id, seq))
            if row is None or row["eid"] is None:
                continue
            db.execute("DELETE FROM reading_exclusions WHERE id = ?",
                       (row["eid"],))
            self._mark_row(table_row, seq, "kayıt", "text")
            self._excluded_seqs.discard(seq)
            restored.append(seq)

        if restored:
            audit.log("reading.include", user_id=self.state.user["id"],
                      entity="session", entity_id=self.session_id,
                      detail={"seqs": restored, "count": len(restored),
                              "reason": reason})
        self.state.status("%d okumanın dışlanması kaldırıldı." % len(restored))

    def _copy_selected(self):
        """Copies the selected rows to the clipboard, tab-separated."""
        rows = sorted(r.row() for r in self.table.selectionModel().selectedRows())
        if not rows:
            return
        header = [self.table.horizontalHeaderItem(c).text()
                  for c in range(self.table.columnCount())]
        lines = ["\t".join(header)]
        for r in rows:
            lines.append("\t".join(
                (self.table.item(r, c).text() if self.table.item(r, c) else "")
                for c in range(self.table.columnCount())))
        QtWidgets.QApplication.clipboard().setText("\n".join(lines))
        self.state.status("%d okuma panoya kopyalandı." % len(rows))

    def _table_menu(self, pos):
        index = self.table.indexAt(pos)
        if index.isValid() and not self.table.selectionModel().isRowSelected(
                index.row(), QtCore.QModelIndex()):
            self.table.selectRow(index.row())
        has = bool(self.table.selectionModel().selectedRows())

        menu = QtWidgets.QMenu(self)
        act_exclude = menu.addAction("Seçili okumaları dışla…")
        act_include = menu.addAction("Dışlamayı kaldır…")
        menu.addSeparator()
        act_copy = menu.addAction("Panoya kopyala")
        for act in (act_exclude, act_include, act_copy):
            act.setEnabled(has)
        # Exclusion only makes sense for readings that were recorded: rows
        # from monitoring mode have no counterpart in the database.
        for act in (act_exclude, act_include):
            act.setEnabled(has and self.session_id is not None)

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is act_exclude:
            self._exclude_selected()
        elif chosen is act_include:
            self._include_selected()
        elif chosen is act_copy:
            self._copy_selected()

    def _export_plot(self):
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Grafiği kaydet", "olcum-grafik.png",
            "PNG görüntü (*.png);;SVG çizim (*.svg)")
        if not path:
            return
        try:
            export_plot(self.plot, path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Kaydedilemedi", str(exc))
            return
        self.state.status("Grafik kaydedildi: %s" % path)

    def _finish(self):
        if self.recording and self.stats.n == 0:
            QtWidgets.QMessageBox.information(
                self, "Kayıt yok", "Henüz kaydedilmiş okuma yok.")
        # If there's a flagged but not-yet-excluded outlier, it's asked
        # about here: the measurement is over, the operator can look at
        # the table, and the decision doesn't interrupt the flow.
        if self._flagged:
            ans = QtWidgets.QMessageBox.question(
                self, "Aykırı okumalar",
                "%d okuma aykırı olarak işaretlendi ve hesaba dahil.\n\n"
                "Şimdi dışlamak ister misiniz? (Okumalar silinmez, gerekçesi "
                "kayda geçer.)" % len(self._flagged),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if ans == QtWidgets.QMessageBox.Yes:
                self._exclude_flagged()
        ans = QtWidgets.QMessageBox.question(
            self, "Oturumu bitir", "Ölçüm oturumu sonlandırılsın mı?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if ans != QtWidgets.QMessageBox.Yes:
            return
        self.stop(status="completed")
        self.session_finished.emit(self.session_id)

    def _teardown_worker(self):
        """Stops the reading thread and device connection, flushes the buffer.

        Doesn't touch the session state in the database — that's stop()'s job.
        """
        self._flush_timer.stop()
        if self.worker:
            self.worker.stop()
            self.worker.wait(3000)
            self.worker = None
        self._flush()
        if self.driver:
            try:
                self.driver.close()
            except Exception:
                pass
            self.driver = None

    def stop(self, status="aborted"):
        """Closes the session. The device is released in every case.

        A database write failure isn't passed over silently: the device is
        already closed, so the user is told the status. Otherwise it would
        look like "finish session doesn't work".
        """
        self._teardown_worker()
        self._reset_controls()
        if not self.session_id:
            return
        # Points that were reached are closed as completed; points whose
        # turn never came stay "pending" — if the plan was left half done,
        # the certificate should show it as half done too.
        for i, p in enumerate(self.points):
            if i <= self.point_index:
                points_svc.finish(p["id"])
        try:
            db.execute(
                "UPDATE sessions SET ended_at = ?, status = ?, notes = ? WHERE id = ?",
                (db.utc_now(), status, self.notes_edit.toPlainText().strip() or None,
                 self.session_id))
            audit.log("session.%s" % status, user_id=self.state.user["id"],
                      entity="session", entity_id=self.session_id,
                      detail={"readings": self._saved_count})
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Oturum kapatılamadı",
                "Ölçüm durduruldu ve cihaz bağlantısı kapatıldı, ancak oturum "
                "durumu veritabanına yazılamadı:\n\n%s\n\n"
                "Alınan okumalar kayıtta duruyor." % exc)
