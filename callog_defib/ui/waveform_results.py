"""waveform_results -- WaveformPage mixin, moved out of waveform_page.py to keep
that file to a manageable size.
"""

from callog_common import drivers
from callog_common import perms
from callog_common import theme
from callog_common import waveform
from callog_common.qt import Qt
from callog_common.qt import QtWidgets
from callog_common.ui.waveform_common import MAX_PLOT_POINTS
from callog_common.ui.waveform_common import MIN_ANALYSIS_ROWS
from callog_common.ui.waveform_common import _open_path
from callog_common.ui.waveform_common import _thin
import os


class _ResultsMixin:

    def _table_box(self):
        box = QtWidgets.QGroupBox("Yakalamalar")
        lay = QtWidgets.QVBoxLayout(box)

        self.table = QtWidgets.QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            ["#", "Zaman", "Osiloskop", "Kanallar", "Nokta", "Δt", "Seri",
             "Dosya", "Rapor", "Durum"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._show_selected)
        lay.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        self.show_btn = QtWidgets.QPushButton("Grafikte göster")
        self.show_btn.clicked.connect(self._show_selected)
        self.report_btn = QtWidgets.QPushButton("Şok raporu (PDF)")
        self.report_btn.setProperty("primary", True)
        self.report_btn.clicked.connect(self._make_report)
        self.report_btn.setToolTip(
            "Çözümleme, kayıttan çizilen dalga grafiği ve cihazın ekran "
            "görüntüsü tek belgede.")
        self.series_report_btn = QtWidgets.QPushButton("Seri raporu (PDF)")
        self.series_report_btn.setProperty("primary", True)
        self.series_report_btn.clicked.connect(self._make_series_report)
        self.series_report_btn.setToolTip(
            "Serideki bütün şokları tek belgede toplar: bindirmeli grafik + "
            "ortalama dalga, ortalama/sapma/belirsizlik/en küçük/en büyük "
            "tablosu, uygunluk kararı, ölçüm ölçüm sonuçlar ve her şokun "
            "ekran görüntüsü.\n\n"
            "Rapor sertifika defterine de işlenir; onay ve silme işlemleri "
            "Geçmiş → Sertifikalar sekmesinden yapılır.")
        self.open_file_btn = QtWidgets.QPushButton("CSV'yi aç")
        self.open_file_btn.clicked.connect(self._open_selected)
        # Short labels: with six items in the bottom row, the page's
        # minimum width was 1331 px and it hugged the edge on the 1366 px
        # lab screen. Details are in the tooltips.
        self.open_shot_btn = QtWidgets.QPushButton("Görüntüyü aç")
        self.open_shot_btn.clicked.connect(self._open_selected_shot)
        self.only_mine_chk = QtWidgets.QCheckBox("Yalnızca bu cihaz")
        self.only_mine_chk.setToolTip(
            "Yalnızca seçili osiloskopla alınan yakalamaları listeler.")
        self.only_mine_chk.setChecked(True)
        self.only_mine_chk.toggled.connect(lambda _o: self.reload())
        row.addWidget(self.report_btn)
        row.addWidget(self.series_report_btn)
        row.addWidget(self.show_btn)
        row.addWidget(self.open_file_btn)
        row.addWidget(self.open_shot_btn)
        row.addWidget(self.only_mine_chk)
        row.addStretch(1)
        lay.addLayout(row)

        self.table.itemSelectionChanged.connect(self._on_capture_selected)
        self._on_capture_selected()
        return box

    def _on_capture_selected(self):
        row = self._selected_capture()
        has = row is not None
        self.show_btn.setEnabled(has)
        self.report_btn.setEnabled(has)
        self.open_file_btn.setEnabled(has)
        # Series report only makes sense for records that belong to a series.
        series_id = waveform.series_of(row) if has else None
        self.series_report_btn.setEnabled(bool(series_id))
        if series_id:
            n = len(waveform.series_captures(series_id))
            self.series_report_btn.setToolTip(
                "%s serisindeki %d ölçümü tek belgede toplar: bindirmeli "
                "grafik + ortalama dalga, istatistik tablosu ve her şokun "
                "ekran görüntüsü." % (series_id, n))
        else:
            self.series_report_btn.setToolTip(
                "Seçili yakalama bir seriye ait değil. Seri raporu için "
                "'Ölçüm sayısı (seri)' alanını 1'den büyük yapıp başlatın.")

        # A disabled button that doesn't explain why looks "broken".
        if not has:
            for btn in (self.show_btn, self.report_btn, self.open_file_btn,
                        self.open_shot_btn):
                btn.setToolTip("Önce listeden bir yakalama seçin.")
        else:
            self.show_btn.setToolTip("Seçili yakalamayı yukarıdaki grafiğe çizer.")
            self.report_btn.setToolTip(
                "Çözümleme, kayıttan çizilen dalga grafiği ve cihazın ekran "
                "görüntüsü tek belgede.")
            self.open_file_btn.setToolTip("Seçili yakalamanın CSV dosyasını açar.")

        # Not every capture has a screenshot: some old firmware versions
        # don't have :DISPlay:DATA?, and the capture is still saved in that case.
        has_shot = (has and bool(row["screenshot_path"])
                    and os.path.isfile(row["screenshot_path"] or ""))
        self.open_shot_btn.setEnabled(has_shot)
        if has and not has_shot:
            self.open_shot_btn.setToolTip(
                "Bu yakalamada ekran görüntüsü yok.")
        elif has_shot:
            self.open_shot_btn.setToolTip("Cihazdan alınan PNG'yi açar.")

    def _update_buttons(self):
        running = self.worker is not None
        scanning = (self._scan_thread is not None
                    and self._scan_thread.isRunning())
        inst = self._current_instrument()
        has_instrument = inst is not None
        is_sim = drivers.is_simulated(inst["driver"]) if has_instrument else True
        can_capture = self.state.can(perms.WAVEFORM_CAPTURE)
        self.start_btn.setEnabled(not running and has_instrument and can_capture)
        self.stop_btn.setEnabled(running)
        self.test_btn.setEnabled(not running and has_instrument)
        self.shot_btn.setEnabled(has_instrument)
        self.grab_csv_btn.setEnabled(
            not running and has_instrument and can_capture)
        self.apply_setup_btn.setEnabled(not running and has_instrument)
        self.autoscale_btn.setEnabled(not running and has_instrument)
        self.scan_addr_btn.setEnabled(
            not running and not scanning and has_instrument and not is_sim)
        self.mode_combo.setEnabled(not running)
        self.instrument_combo.setEnabled(not running)
        for w in (self.points_spin, self.count_spin, self.timeout_spin,
                  self.dut_combo, self.auto_chan_chk):
            w.setEnabled(not running)

    def _selected_capture(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        cid = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        return waveform.get(cid)

    def _show_selected(self):
        row = self._selected_capture()
        if row is None:
            return
        state, msg = waveform.verify(row["id"])
        if state == "missing":
            QtWidgets.QMessageBox.warning(self, "Dosya yok", msg)
            return
        try:
            times, columns = waveform.read_csv(row["file_path"],
                                               max_points=MAX_PLOT_POINTS)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Okunamadı", str(exc))
            return
        self._plot(times, columns)
        stored = waveform.analysis_of(row)
        if stored:
            self.analysis_box.setVisible(True)
            self._show_analysis(stored)
        note = "" if state == "ok" else "  ⚠ %s" % msg
        self.status_label.setText(
            "%s gösteriliyor (%d nokta).%s"
            % (os.path.basename(row["file_path"]), len(times), note))

    def _open_selected(self):
        row = self._selected_capture()
        if row is not None and os.path.isfile(row["file_path"]):
            _open_path(row["file_path"])

    def _open_selected_shot(self):
        row = self._selected_capture()
        if row is not None and row["screenshot_path"] \
                and os.path.isfile(row["screenshot_path"]):
            _open_path(row["screenshot_path"])

    def _make_report(self):
        row = self._selected_capture()
        if row is None:
            return

        state, message = waveform.verify(row["id"])
        if state == "missing":
            QtWidgets.QMessageBox.warning(self, "Dosya yok", message)
            return
        if state == "changed":
            # A report can still be generated, but the document will note
            # it; the operator must knowingly proceed.
            answer = QtWidgets.QMessageBox.warning(
                self, "Dosya değişmiş",
                "%s\n\nRapor yine de üretilsin mi? Belgeye bütünlük denetimi "
                "sonucu olduğu gibi yazılır." % message,
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Cancel)
            if answer != QtWidgets.QMessageBox.Yes:
                return

        from .. import shockreport
        try:
            path, report_no = shockreport.build_pdf(
                row["id"], self.state.user["id"])
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Rapor üretilemedi", str(exc))
            return

        self.reload()
        self.status_label.setText("Şok raporu üretildi: %s" % report_no)
        self.state.status("Rapor: %s" % path)
        _open_path(path)

    def _make_series_report(self):
        """Produces a single report from the entire series the selected record belongs to."""
        row = self._selected_capture()
        series_id = waveform.series_of(row)
        if not series_id:
            return

        members = waveform.series_captures(series_id)
        broken = [m for m in members if waveform.verify(m["id"])[0] == "missing"]
        if broken:
            answer = QtWidgets.QMessageBox.warning(
                self, "Eksik dosya",
                "Serideki %d kaydın dosyası bulunamıyor. Bunlar istatistiğe "
                "girmez ve rapora eksik olarak yazılır.\n\nDevam edilsin mi?"
                % len(broken),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Cancel)
            if answer != QtWidgets.QMessageBox.Yes:
                return

        from .. import seriesreport
        try:
            path, report_no = seriesreport.build_pdf(
                series_id, self.state.user["id"])
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Seri raporu üretilemedi",
                                           str(exc))
            return

        self.reload()
        # Show the result in the status bar too: before the report was
        # opened, this was the only thing the operator saw, and just
        # saying "generated" hid the pass/fail verdict until the PDF was opened.
        from callog_common import certificate
        cert = certificate.for_series(series_id)
        verdict = (certificate.VERDICT_TR.get(cert["result"], "—")
                   if cert else "—")
        self.status_label.setText(
            "Seri raporu üretildi: %s — %d ölçüm · Sonuç: %s"
            % (report_no, len(members), verdict))
        self.state.status("Seri raporu: %s" % path)
        _open_path(path)

    def _plot_box(self):
        import pyqtgraph as pg

        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "Zaman", units="s")
        self.plot.setLabel("left", "Gerilim", units="V")
        self.plot.addLegend(offset=(-10, 10))
        # Trigger point: on the device, t = 0 is the moment of trigger.
        self._trigger_line = pg.InfiniteLine(angle=90, movable=False, pos=0.0)
        self.plot.addItem(self._trigger_line)
        self.apply_plot_theme()

        # The analysis panel sits to the right of the plot: if the numbers
        # don't stay next to the waveform, the operator has to read the two
        # separately and combine them mentally.
        self.analysis_box = QtWidgets.QGroupBox("Şok çözümlemesi")
        self.analysis_box.setFixedWidth(260)
        alay = QtWidgets.QVBoxLayout(self.analysis_box)
        self.analysis_table = QtWidgets.QTableWidget(0, 2)
        self.analysis_table.horizontalHeader().setVisible(False)
        self.analysis_table.verticalHeader().setVisible(False)
        self.analysis_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.analysis_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        # A biphasic shock produces 14 rows; at the default row height only
        # two were visible in the panel. Tight rows + scrolling make them
        # all reachable.
        self.analysis_table.verticalHeader().setDefaultSectionSize(21)
        self.analysis_table.setStyleSheet("QTableWidget { font-size: 12px; }")
        # At least MIN_ANALYSIS_ROWS rows should be visible without
        # scrolling — even if the panel is shrunk with the splitter it
        # won't go below this, otherwise even the most important value,
        # energy, could end up hidden without scrolling.
        self.analysis_table.setMinimumHeight(MIN_ANALYSIS_ROWS * 21 + 4)
        alay.addWidget(self.analysis_table, 1)
        self.analysis_note = QtWidgets.QLabel("")
        self.analysis_note.setProperty("hint", True)
        self.analysis_note.setWordWrap(True)
        alay.addWidget(self.analysis_note)
        self.analysis_box.setVisible(False)

        wrapper = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(self.plot, 1)
        lay.addWidget(self.analysis_box)
        return wrapper

    def _plot(self, times, columns):
        import pyqtgraph as pg

        c = theme.colors()
        names = list(columns.keys())
        for name in list(self._curves):
            if name not in names:
                self.plot.removeItem(self._curves.pop(name))
        for i, name in enumerate(names):
            if name not in self._curves:
                self._curves[name] = self.plot.plot(
                    name=name, pen=pg.mkPen(c["curve"] if i == 0 else c["warn"],
                                            width=1.4))
            xs, ys = _thin(times, columns[name], MAX_PLOT_POINTS)
            self._curves[name].setData(xs, ys)
        self.plot.enableAutoRange()

    def _buttons(self):
        row = QtWidgets.QHBoxLayout()
        self.test_btn = QtWidgets.QPushButton("Bağlantıyı test et")
        self.test_btn.clicked.connect(self._test_connection)
        self.start_btn = QtWidgets.QPushButton("Yakalamayı başlat")
        self.start_btn.setProperty("primary", True)
        self.start_btn.setMinimumHeight(38)
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QtWidgets.QPushButton("Durdur")
        self.stop_btn.clicked.connect(self._stop)
        self.shot_btn = QtWidgets.QPushButton("Ekran görüntüsü al")
        self.shot_btn.clicked.connect(self._grab_screenshot)
        self.shot_btn.setToolTip(
            "Osiloskop ekranının o anki görüntüsünü PNG olarak kaydeder "
            "(yakalama sürmese de çalışır).")
        self.grab_csv_btn = QtWidgets.QPushButton("CSV al")
        self.grab_csv_btn.clicked.connect(self._grab_csv)
        self.grab_csv_btn.setToolTip(
            "Ekranda o an duran dalgayı tetikleme beklemeden okur; CSV ve "
            "ekran görüntüsü olarak kaydeder.\n"
            "Tetiklemeyi beklemek için 'Yakalamayı başlat' kullanın.")
        self.open_dir_btn = QtWidgets.QPushButton("Klasörü aç")
        self.open_dir_btn.clicked.connect(self._open_dir)

        row.addWidget(self.test_btn)
        row.addWidget(self.start_btn, 1)
        row.addWidget(self.stop_btn)
        row.addWidget(self.shot_btn)
        row.addWidget(self.grab_csv_btn)
        row.addWidget(self.open_dir_btn)

        self.rec_label = QtWidgets.QLabel("BEKLEMEDE")
        self.rec_label.setProperty("badge", "warn")
        self.rec_label.setAlignment(Qt.AlignCenter)
        self.rec_label.setMinimumWidth(120)
        row.addWidget(self.rec_label)
        return row
