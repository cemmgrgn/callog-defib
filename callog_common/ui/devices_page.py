"""Register of calibrated devices.

Devices that come into the lab keep coming back. This page gathers each
device's whole history in one place: measurement sessions, certificates,
PDF reports left over from before the app existed, and the drift of the
same measurement point over the years.
"""

import os

from .. import (certificate, db, documents, perms, testmodes, theme, trend,
                waveform)
from ..qt import Qt, QtGui, QtWidgets, Signal
from .util import empty_state, fit_table, PAGE_MARGIN, PAGE_SPACING

RESULT_COLOR = {"pass": "ok", "fail": "bad", "info": "text_muted"}


def _days_since(origin, timestamp):
    """Days elapsed since `origin`; 0 if the date can't be parsed."""
    day = trend.parse_day(timestamp)
    if origin is None or day is None:
        return 0
    return (day - origin).days


class DevicesPage(QtWidgets.QWidget):

    new_session_for = Signal(int)      # dut_id

    def __init__(self, app_state, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.state = app_state
        self._current_dut = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGIN)
        root.setSpacing(PAGE_SPACING)

        title = QtWidgets.QLabel("Kalibre edilen cihazlar")
        title.setProperty("h1", True)
        root.addWidget(title)

        hint = QtWidgets.QLabel(
            "Bir kez gelen cihaz genelde tekrar gelir. Buradan cihazın tüm "
            "ölçüm geçmişini görebilir, eski dönemden kalan PDF raporları "
            "kaydına iliştirebilirsiniz.")
        hint.setProperty("hint", True)
        hint.setWordWrap(True)
        root.addWidget(hint)

        root.addLayout(self._filters())

        split = QtWidgets.QSplitter(Qt.Horizontal)
        split.addWidget(self._device_list())
        split.addWidget(self._detail())
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        # The left side starts out wider so the seven-column device list
        # fits on a 1920px screen without a horizontal scrollbar.
        split.setSizes([800, 880])
        root.addWidget(split, 1)

        root.addLayout(self._buttons())

    # --- left side ------------------------------------------------------------
    def _filters(self):
        row = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Ara: seri no, model, üretici veya şirket")
        self.search.textChanged.connect(self.reload)
        row.addWidget(self.search, 2)

        self.company_filter = QtWidgets.QComboBox()
        self.company_filter.currentIndexChanged.connect(self.reload)
        row.addWidget(QtWidgets.QLabel("Şirket"))
        row.addWidget(self.company_filter, 1)
        return row

    def _device_list(self):
        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Cihaz", "Seri no", "Şirket", "Ölçüm", "Dalga", "Belge",
             "Son ölçüm"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._show_detail)
        return self.table

    # --- right side -----------------------------------------------------------
    def _detail(self):
        self.detail_tabs = QtWidgets.QTabWidget()
        self.detail_tabs.setObjectName("innerTabs")
        self.detail_tabs.addTab(self._summary_tab(), "Özet ve ölçümler")
        self.detail_tabs.addTab(self._waveform_tab(), "Dalga ölçümleri")
        self.detail_tabs.addTab(self._drift_tab(), "Seyir")
        self.detail_tabs.addTab(self._documents_tab(), "Belgeler")
        return self.detail_tabs

    def _summary_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)

        self.summary = QtWidgets.QTextBrowser()
        self.summary.setMaximumHeight(120)
        lay.addWidget(self.summary)

        self.session_table = QtWidgets.QTableWidget(0, 7)
        self.session_table.setHorizontalHeaderLabels(
            ["#", "Tarih", "Fonksiyon", "Nominal", "Operatör", "Sertifika", "Sonuç"])
        self.session_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.session_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows)
        self.session_table.setAlternatingRowColors(True)
        self.session_table.verticalHeader().setVisible(False)
        lay.addWidget(self.session_table, 1)
        return w

    def _waveform_tab(self):
        """The device's waveform series measurements and certificates.

        In a separate tab from sessions: the columns don't overlap (one has
        function/nominal, this one has shock count/energy), and cramming
        them into a single table would produce rows that are half empty.
        """
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)

        self.wave_table = QtWidgets.QTableWidget(0, 8)
        self.wave_table.setHorizontalHeaderLabels(
            ["Tarih", "Test modu", "Şok", "Ayarlanan", "Operatör",
             "Sertifika", "Sonuç", "Durum"])
        self.wave_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.wave_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows)
        self.wave_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection)
        self.wave_table.setAlternatingRowColors(True)
        self.wave_table.verticalHeader().setVisible(False)
        self.wave_table.itemSelectionChanged.connect(self._on_wave_selected)
        self.wave_table.doubleClicked.connect(self._open_wave_report)
        lay.addWidget(self.wave_table, 1)

        row = QtWidgets.QHBoxLayout()
        self.open_wave_btn = QtWidgets.QPushButton("Raporu aç (PDF)")
        self.open_wave_btn.clicked.connect(self._open_wave_report)
        row.addWidget(self.open_wave_btn)
        self.summary_btn = QtWidgets.QPushButton("Toplu değerlendirme (PDF)")
        self.summary_btn.setToolTip(
            "Cihazın bütün enerji kademelerini tek belgede değerlendirir.")
        self.summary_btn.clicked.connect(self._make_summary_report)
        row.addWidget(self.summary_btn)
        row.addStretch(1)
        lay.addLayout(row)

        note = QtWidgets.QLabel(
            "Seri şok ölçümleri sertifika defterine işlenir: onay, silme ve "
            "geri alma işlemleri Geçmiş → Sertifikalar sekmesinden yapılır. "
            "Uygunluk kararı yalnızca cihazda ayarlanan enerji kaydedilmişse "
            "verilir. <b>Toplu değerlendirme</b>, silinmemiş sertifikası olan "
            "bütün kademeleri tek belgede toplar.")
        note.setProperty("hint", True)
        note.setWordWrap(True)
        lay.addWidget(note)
        return w

    def _drift_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Ölçüm noktası"))
        self.series_combo = QtWidgets.QComboBox()
        self.series_combo.currentIndexChanged.connect(self._draw_drift)
        row.addWidget(self.series_combo, 1)
        lay.addLayout(row)

        self.trend_chk = QtWidgets.QCheckBox("Eğilim ve tolerans bandı")
        self.trend_chk.setChecked(True)
        self.trend_chk.setToolTip(
            "Doğrusal eğilim çizgisi, tolerans bandı ve — bant dışına doğru\n"
            "bir eğilim varsa — sınırın ne zaman aşılacağı tahmini.")
        self.trend_chk.toggled.connect(self._draw_drift)
        row.addWidget(self.trend_chk)

        import pyqtgraph as pg

        self.drift_plot = pg.PlotWidget()
        # The X axis is **days**, not measurement order: two calibrations
        # could be six months or six days apart, and a sequence number
        # hides that difference and makes the trend line meaningless.
        self.drift_plot.setLabel("bottom", "İlk ölçümden bu yana", units="gün")
        self.drift_plot.showGrid(x=True, y=True, alpha=0.25)
        lay.addWidget(self.drift_plot, 1)

        self.drift_note = QtWidgets.QLabel()
        self.drift_note.setProperty("hint", True)
        self.drift_note.setWordWrap(True)
        lay.addWidget(self.drift_note)
        return w

    def _documents_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)

        self.doc_table = QtWidgets.QTableWidget(0, 6)
        self.doc_table.setHorizontalHeaderLabels(
            ["Başlık", "Tür", "Belge tarihi", "Dosya", "Ekleyen", "Durum"])
        self.doc_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.doc_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.doc_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.doc_table.setAlternatingRowColors(True)
        self.doc_table.verticalHeader().setVisible(False)
        self.doc_table.doubleClicked.connect(self._open_document)
        self.doc_table.itemSelectionChanged.connect(self._on_doc_selected)
        lay.addWidget(self.doc_table, 1)

        row = QtWidgets.QHBoxLayout()
        self.add_doc_btn = QtWidgets.QPushButton("Belge ekle")
        self.add_doc_btn.clicked.connect(self._add_document)
        self.open_doc_btn = QtWidgets.QPushButton("Aç")
        self.open_doc_btn.clicked.connect(self._open_document)
        self.remove_doc_btn = QtWidgets.QPushButton("Bağlantıyı kaldır")
        self.remove_doc_btn.setProperty("danger", True)
        self.remove_doc_btn.clicked.connect(self._remove_document)
        for b in (self.add_doc_btn, self.open_doc_btn, self.remove_doc_btn):
            row.addWidget(b)
        self.remove_doc_btn.setVisible(self.state.can(perms.DOC_REMOVE))
        row.addStretch(1)
        lay.addLayout(row)

        note = QtWidgets.QLabel(
            "Eklenen dosya uygulamanın kendi klasörüne kopyalanır ve SHA-256 "
            "özeti alınır; kaynak dosya taşınsa bile kayıt kırılmaz. "
            "Bağlantı kaldırılsa da kopya diskte kalır.")
        note.setProperty("hint", True)
        note.setWordWrap(True)
        lay.addWidget(note)
        return w

    def _buttons(self):
        row = QtWidgets.QHBoxLayout()
        self.add_device_btn = QtWidgets.QPushButton("Yeni cihaz ekle")
        self.add_device_btn.setProperty("primary", True)
        self.add_device_btn.clicked.connect(self._new_device)
        self.new_session_btn = QtWidgets.QPushButton("Bu cihaz için yeni ölçüm")
        self.new_session_btn.clicked.connect(self._start_session)
        self.edit_btn = QtWidgets.QPushButton("Cihaz bilgilerini düzenle")
        self.edit_btn.clicked.connect(self._edit_device)
        row.addWidget(self.add_device_btn)
        row.addWidget(self.new_session_btn)
        row.addWidget(self.edit_btn)
        row.addStretch(1)
        return row

    # --- data -------------------------------------------------------------
    def showEvent(self, event):
        self.reload()
        QtWidgets.QWidget.showEvent(self, event)

    def reload(self):
        self._reload_company_filter()

        sql = (
            "SELECT d.*,"
            " (SELECT COUNT(*) FROM sessions s WHERE s.dut_id = d.id) AS n_sessions,"
            " (SELECT COUNT(*) FROM dut_documents dc WHERE dc.dut_id = d.id) AS n_docs,"
            " (SELECT COUNT(DISTINCT w.series_id) FROM waveform_captures w"
            "   WHERE w.dut_id = d.id AND w.series_id IS NOT NULL) AS n_series,"
            # Last-activity date is the max of two sources: if only
            # sessions were considered, a device that had only waveform
            # measurements would drop to the bottom as if "never measured".
            " MAX(COALESCE((SELECT MAX(s.started_at) FROM sessions s"
            "                WHERE s.dut_id = d.id), ''),"
            "     COALESCE((SELECT MAX(w.captured_at) FROM waveform_captures w"
            "                WHERE w.dut_id = d.id), '')) AS last_at"
            " FROM duts d"
        )
        where, params = [], []
        term = self.search.text().strip()
        if term:
            like = "%" + term + "%"
            where.append("(d.serial_no LIKE ? OR d.model LIKE ?"
                         " OR d.manufacturer LIKE ? OR d.company LIKE ?)")
            params += [like, like, like, like]
        if self.company_filter.currentData():
            where.append("d.company = ?")
            params.append(self.company_filter.currentData())
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY (last_at IS NULL), last_at DESC LIMIT 500"

        previous = self._current_dut
        rows = db.query(sql, tuple(params))
        self.table.setRowCount(0)
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            cells = ["%s %s" % (r["manufacturer"], r["model"]), r["serial_no"],
                     r["company"], str(r["n_sessions"]), str(r["n_series"]),
                     str(r["n_docs"]),
                     (r["last_at"] or "—")[:16].replace("T", " ") or "—"]
            for col, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(text)
                if col == 0:
                    item.setData(Qt.UserRole, r["id"])
                self.table.setItem(i, col, item)
        fit_table(self.table)
        empty_state(self.table,
                    "Kayıtlı cihaz yok. 'Yeni cihaz ekle' ile başlayın ya da\n"
                    "ilk ölçüm oturumu açıldığında cihaz otomatik eklenir.")

        if previous is not None:
            for i in range(self.table.rowCount()):
                if self.table.item(i, 0).data(Qt.UserRole) == previous:
                    self.table.selectRow(i)
                    break
        self._show_detail()

    def _reload_company_filter(self):
        previous = self.company_filter.currentData()
        self.company_filter.blockSignals(True)
        self.company_filter.clear()
        self.company_filter.addItem("Tüm şirketler", None)
        for r in db.query("SELECT DISTINCT company FROM duts ORDER BY company"):
            self.company_filter.addItem(r["company"], r["company"])
        idx = self.company_filter.findData(previous)
        self.company_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self.company_filter.blockSignals(False)

    def focus_dut(self, dut_id, tab=None):
        """Selects the device in the list; opens the `tab` sub-tab if given.

        Reached from global search: if the search box is filled in, the
        device being looked for might not be in the list because of the
        filters, so the filters are reset here.
        """
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.company_filter.blockSignals(True)
        self.company_filter.setCurrentIndex(0)
        self.company_filter.blockSignals(False)
        self._current_dut = dut_id
        self.reload()
        if tab is not None:
            for i in range(self.detail_tabs.count()):
                if tab in self.detail_tabs.tabText(i):
                    self.detail_tabs.setCurrentIndex(i)
                    break
        return self.selected_dut_id() == dut_id

    def selected_dut_id(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.table.item(rows[0].row(), 0).data(Qt.UserRole)

    def _show_detail(self):
        dut_id = self.selected_dut_id()
        self._current_dut = dut_id
        enabled = dut_id is not None
        for b in (self.new_session_btn, self.edit_btn, self.add_doc_btn):
            b.setEnabled(enabled)
        self.open_doc_btn.setEnabled(False)
        self.remove_doc_btn.setEnabled(False)

        if dut_id is None:
            self.summary.clear()
            self.session_table.setRowCount(0)
            self.wave_table.setRowCount(0)
            self.doc_table.setRowCount(0)
            self.series_combo.clear()
            self.drift_plot.clear()
            self.open_wave_btn.setEnabled(False)
            return

        info = documents.dut_summary(dut_id)
        waves = waveform.series_for_dut(dut_id)
        self._fill_summary(info, waves)
        self._fill_sessions(info["sessions"])
        self._fill_waveforms(waves)
        self._fill_documents(info["documents"])
        self._load_series(dut_id)

    def _fill_summary(self, info, waves=()):
        d, counts = info["dut"], info["counts"]
        # The certificate count comes from two sources: session
        # certificates are in `counts`, waveform series certificates are in
        # `waves`. Showing only the former would make a device with a
        # generated series report look "uncertified".
        wave_certs = sum(1 for s in waves
                         if s["cert_no"] and not s["cert_deleted_at"])
        html = [
            "<b>%s %s</b><br>Seri no: %s<br>" % (
                d["manufacturer"], d["model"], d["serial_no"]),
            "Şirket: %s<br>" % d["company"],
            "Cihaz tipi: %s<br>" % (d["device_type"] or "—"),
            "İlk kayıt: %s<br><br>" % (d["created_at"] or "")[:10],
            "Ölçüm: <b>%d</b> &nbsp; Dalga serisi: <b>%d</b> &nbsp; "
            "Sertifika: <b>%d</b> &nbsp; Belge: <b>%d</b>"
            % (counts["sessions"], len(waves),
               counts["certificates"] + wave_certs, counts["documents"]),
        ]
        if d["notes"]:
            html.append("<br><br><b>Not:</b> %s" % d["notes"])
        self.summary.setHtml("".join(html))

    def _fill_sessions(self, sessions):
        c = theme.colors()
        self.session_table.setRowCount(0)
        for s in sessions:
            i = self.session_table.rowCount()
            self.session_table.insertRow(i)
            nominal = "—" if s["nominal"] is None else "%g %s" % (s["nominal"],
                                                                 s["unit"])
            cert = s["cert_no"] or "—"
            if s["cert_no"] and s["cert_deleted_at"]:
                cert += " (silinmiş)"
            result = (certificate.VERDICT_TR.get(s["cert_result"], "—")
                      if s["cert_result"] else "—")
            cells = [str(s["id"]), (s["started_at"] or "")[:16].replace("T", " "),
                     s["function"], nominal, s["operator_name"], cert, result]
            for col, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(str(text))
                if col == 6 and s["cert_result"]:
                    item.setForeground(
                        QtGui.QColor(c[RESULT_COLOR[s["cert_result"]]]))
                if s["is_simulated"]:
                    item.setForeground(QtGui.QColor(c["warn"]))
                self.session_table.setItem(i, col, item)
        fit_table(self.session_table, stretch_column=5)
        empty_state(self.session_table, "Bu cihaz için kayıtlı ölçüm yok.")

    def _fill_documents(self, docs):
        c = theme.colors()
        self.doc_table.setRowCount(0)
        for doc in docs:
            i = self.doc_table.rowCount()
            self.doc_table.insertRow(i)
            state, _msg = documents.verify(doc["id"])
            state_tr = {"ok": "dosya yerinde", "missing": "DOSYA YOK",
                        "changed": "DEĞİŞMİŞ", "unknown": "bilinmiyor"}[state]
            cells = [doc["title"], documents.DOC_TYPE_TR[doc["doc_type"]],
                     doc["doc_date"] or "—",
                     os.path.basename(doc["file_path"]),
                     doc["added_by_name"], state_tr]
            for col, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(str(text))
                if col == 0:
                    item.setData(Qt.UserRole, doc["id"])
                if col == 5 and state != "ok":
                    item.setForeground(QtGui.QColor(c["bad"]))
                self.doc_table.setItem(i, col, item)
        fit_table(self.doc_table)
        empty_state(self.doc_table,
                    "İliştirilmiş belge yok. Eski PDF raporları\n"
                    "'Belge ekle' ile bu cihaza bağlanabilir.")
        self._on_doc_selected()

    def _on_doc_selected(self):
        has = bool(self.doc_table.selectionModel().selectedRows())
        self.open_doc_btn.setEnabled(has)
        self.remove_doc_btn.setEnabled(has and self.state.can(perms.DOC_REMOVE))

    # --- waveform measurements --------------------------------------------
    def _fill_waveforms(self, series):
        c = theme.colors()
        self.wave_table.setRowCount(0)
        for s in series:
            i = self.wave_table.rowCount()
            self.wave_table.insertRow(i)
            cert = s["cert_no"] or "—"
            if s["cert_no"] and s["cert_deleted_at"]:
                cert += " (silinmiş)"
            result = (certificate.VERDICT_TR.get(s["cert_result"], "—")
                      if s["cert_result"] else "—")
            if not s["cert_no"]:
                state = "rapor üretilmedi"
            elif s["cert_deleted_at"]:
                state = "silinmiş"
            elif s["approved_at"]:
                state = "onaylandı"
            else:
                state = "onay bekliyor"
            nominal = ("%g J" % s["nominal_energy_j"]
                       if s["nominal_energy_j"] else "—")
            shots = "%d" % s["n"]
            if s["series_size"] and s["series_size"] != s["n"]:
                shots += " / %d" % s["series_size"]
            cells = [(s["first_at"] or "")[:16].replace("T", " "),
                     testmodes.get(s["test_mode"]).label, shots, nominal,
                     s["operator_name"], cert, result, state]
            for col, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(str(text))
                if col == 0:
                    item.setData(Qt.UserRole, s["series_id"])
                if col == 6 and s["cert_result"]:
                    item.setForeground(
                        QtGui.QColor(c[RESULT_COLOR[s["cert_result"]]]))
                if s["is_simulated"]:
                    item.setForeground(QtGui.QColor(c["warn"]))
                self.wave_table.setItem(i, col, item)
        fit_table(self.wave_table, stretch_column=5)
        empty_state(self.wave_table,
                    "Bu cihaz için kayıtlı dalga seri ölçümü yok.\n"
                    "Dalga sekmesinden seri yakalama yapıldığında burada görünür.")
        self._on_wave_selected()

    def _selected_series(self):
        rows = self.wave_table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.wave_table.item(rows[0].row(), 0).data(Qt.UserRole)

    def _on_wave_selected(self):
        series_id = self._selected_series()
        cert = certificate.for_series(series_id) if series_id else None
        self.open_wave_btn.setEnabled(bool(cert and cert["pdf_path"]))

    def _open_wave_report(self):
        series_id = self._selected_series()
        cert = certificate.for_series(series_id) if series_id else None
        if cert is None or not cert["pdf_path"]:
            return
        if not os.path.isfile(cert["pdf_path"]):
            QtWidgets.QMessageBox.warning(
                self, "Dosya bulunamadı",
                "Rapor dosyası yerinde değil:\n%s" % cert["pdf_path"])
            return
        try:
            os.startfile(cert["pdf_path"])
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Açılamadı", str(exc))

    def _make_summary_report(self):
        """Evaluates all of the device's energy levels in a single document."""
        if not self.state.can(perms.CERT_CREATE):
            QtWidgets.QMessageBox.warning(
                self, "Yetki yok", perms.denial_message(perms.CERT_CREATE))
            return
        dut_id = self._current_dut
        if dut_id is None:
            QtWidgets.QMessageBox.information(
                self, "Cihaz seçilmedi", "Önce listeden bir cihaz seçin.")
            return

        # Local, optional import: this report type is produced only by
        # callog-defib, a separate repo/install — see the identical note in
        # approvals_page.py's `_series_detail`.
        try:
            from callog_defib import summaryreport
        except ImportError:
            QtWidgets.QMessageBox.information(
                self, "Kullanılamıyor",
                "Bu rapor türü bu kurulumda üretilemiyor — "
                "callog-defib yüklü değil.")
            return
        try:
            rows, _dut, _inst = summaryreport.collect(dut_id)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Rapor üretilemedi", str(exc))
            return
        if not rows:
            QtWidgets.QMessageBox.information(
                self, "Değerlendirilecek kademe yok",
                "Bu cihaz için silinmemiş seri sertifikası bulunamadı.\n\n"
                "Toplu değerlendirme, sertifikası olan kademeleri toplar.")
            return

        energies = ", ".join(
            "%g J" % r["nominal"] for r in rows if r["nominal"])
        answer = QtWidgets.QMessageBox.question(
            self, "Toplu değerlendirme raporu",
            "%d kademe tek belgede değerlendirilecek:\n\n%s\n\n"
            "Toplam %d şok. Belge üretilsin mi?"
            % (len(rows), energies, sum(r["n_shocks"] for r in rows)),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Yes)
        if answer != QtWidgets.QMessageBox.Yes:
            return

        try:
            path, report_no, result = summaryreport.build_pdf(
                dut_id=dut_id, issued_by=self.state.user["id"])
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Rapor üretilemedi", str(exc))
            return

        self.state.status("%s üretildi — %s"
                          % (report_no, certificate.VERDICT_TR.get(result, result)))
        answer = QtWidgets.QMessageBox.question(
            self, "Rapor hazır",
            "%s üretildi.\nSonuç: %s\n\nDosya açılsın mı?"
            % (report_no, certificate.VERDICT_TR.get(result, result)),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes)
        if answer == QtWidgets.QMessageBox.Yes and os.path.isfile(path):
            try:
                os.startfile(path)
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Açılamadı", str(exc))

    # --- drift ------------------------------------------------------------
    def _load_series(self, dut_id):
        self.series_combo.blockSignals(True)
        self.series_combo.clear()
        self._series = documents.measurement_series(dut_id)
        # We don't store the tuple in the combo box data: Qt converts it to
        # a QVariantList and returns it as a list, which then doesn't match
        # as a dict key.
        self._series_keys = sorted(self._series.keys())
        for i, key in enumerate(self._series_keys):
            function, nominal, unit = key
            self.series_combo.addItem(
                "%s @ %g %s  (%d ölçüm)" % (function, nominal, unit,
                                            len(self._series[key])), i)
        self.series_combo.blockSignals(False)
        self._draw_drift()

    def _draw_drift(self):
        import pyqtgraph as pg

        self.drift_plot.clear()
        c = theme.colors()
        self.drift_plot.setBackground(QtGui.QColor(c["surface"]))
        for name in ("left", "bottom"):
            axis = self.drift_plot.getAxis(name)
            axis.setPen(pg.mkPen(c["border_strong"]))
            axis.setTextPen(pg.mkPen(c["text_muted"]))

        index = self.series_combo.currentData()
        keys = getattr(self, "_series_keys", [])
        if index is None or not keys or index >= len(keys):
            self.drift_note.setText(
                "Bu cihaz için nominal değeri girilmiş tamamlanmış ölçüm yok.")
            return

        import numpy as np

        function, nominal, unit = keys[index]
        points = self._series[keys[index]]
        origin = trend.parse_day(points[0][0])
        # ErrorBarItem does arithmetic on arrays; passing a Python list
        # raises a TypeError during drawing and the plot is silently left
        # empty.
        xs = np.array([_days_since(origin, p[0]) for p in points], dtype=float)
        ys = np.array([p[1] for p in points], dtype=float)
        errs = np.array([p[2] for p in points], dtype=float)
        # Tolerance may have changed over time; the band uses the tolerance
        # of the most recent measurement — that's today's acceptance
        # criterion.
        tolerance = next((p[5] for p in reversed(points) if p[5]), None)

        self.drift_plot.setLabel("left", "%s (%s)" % (function, unit))
        self.drift_plot.addItem(pg.InfiniteLine(
            pos=nominal, angle=0,
            pen=pg.mkPen(c["guide"], width=1, style=Qt.DashLine)))

        info = None
        if self.trend_chk.isChecked():
            if tolerance:
                band = QtGui.QColor(c["guide"])
                band.setAlpha(38)
                region = pg.LinearRegionItem(
                    values=(nominal - abs(tolerance), nominal + abs(tolerance)),
                    orientation="horizontal", movable=False,
                    brush=pg.mkBrush(band), pen=pg.mkPen(None))
                region.setZValue(-10)
                self.drift_plot.addItem(region)
            info = trend.analyse([(p[0], p[1]) for p in points],
                                 nominal=nominal, tolerance=tolerance)

        # Beam width scales with the axis range: a fixed 0.12 would be
        # invisible on a day axis.
        beam = max(0.4, (xs[-1] - xs[0]) / 60.0) if len(xs) > 1 else 0.4
        bars = pg.ErrorBarItem(x=xs, y=ys, height=2 * errs,
                               beam=beam, pen=pg.mkPen(c["text_muted"]))
        self.drift_plot.addItem(bars)
        self.drift_plot.plot(xs, ys, pen=pg.mkPen(c["curve"], width=1.6),
                             symbol="o", symbolSize=7,
                             symbolBrush=pg.mkBrush(c["curve"]))

        if info is not None:
            self._draw_trend_line(info, xs, c)
        # Auto range isn't triggered automatically after clear()
        self.drift_plot.getViewBox().autoRange()

        first, last = points[0], points[-1]
        drift_total = last[1] - first[1]
        note = ("Nominal %g %s · %d ölçüm · ilk: %s (%.7g %s) · son: %s "
                "(%.7g %s) · toplam değişim: %+.3g %s. Hata çubukları U (k=2)."
                % (nominal, unit, len(points), (first[0] or "")[:10], first[1],
                   unit, (last[0] or "")[:10], last[1], unit, drift_total, unit))
        if self.trend_chk.isChecked():
            note += "  " + trend.summary_tr(info, unit)
            if not tolerance:
                note += ("  Tolerans girilmemiş — bant çizilmedi, sınır aşım "
                         "tahmini yapılamadı.")
        self.drift_note.setText(note)

    def _draw_trend_line(self, info, xs, c):
        """Trend line; extended to the day it crosses the limit, if projected."""
        import numpy as np
        import pyqtgraph as pg

        x0 = float(xs[0])
        x1 = float(xs[-1])
        crossing = info["crossing"]
        if crossing and not crossing["already_out"]:
            cross_x = (crossing["date"] - info["origin"]).days
            # The projected extension is capped at twice the observation
            # span: a line stretching ten years out would cram the
            # measurement points into the left edge of the plot and make
            # it unreadable.
            x1 = min(max(x1, cross_x), x1 + 2 * max(1.0, x1 - x0))
        line_x = np.array([x0, x1], dtype=float)
        line_y = np.array([info["intercept"] + info["slope_per_day"] * x
                           for x in (x0, x1)], dtype=float)
        style = Qt.DashDotLine if info["reliable"] else Qt.DotLine
        self.drift_plot.plot(line_x, line_y,
                             pen=pg.mkPen(c["warn"], width=1.6, style=style))

    # --- actions ------------------------------------------------------------
    def _start_session(self):
        dut_id = self.selected_dut_id()
        if dut_id is not None:
            self.new_session_for.emit(dut_id)

    def _new_device(self):
        """Opens device registration directly from this screen.

        Matching on the same manufacturer/model/serial no follows the rule
        set in oturum_page._get_or_create_dut(): if a match exists, no new
        record is opened — the existing one is used.
        """
        dlg = _NewDeviceDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        company = dlg.company()
        manufacturer = dlg.manufacturer()
        model = dlg.model()
        serial = dlg.serial()
        device_type = dlg.device_type()
        notes = dlg.notes()

        missing = [label for label, value in (
            ("Şirket / müşteri", company), ("Üretici firma", manufacturer),
            ("Model", model), ("Seri no", serial)) if not value]
        if missing:
            QtWidgets.QMessageBox.warning(
                self, "Eksik bilgi",
                "Zorunlu alanlar boş: %s" % ", ".join(missing))
            return

        existing = db.query_one(
            "SELECT id FROM duts WHERE serial_no = ? AND manufacturer = ?"
            " AND model = ?", (serial, manufacturer, model))
        if existing:
            QtWidgets.QMessageBox.information(
                self, "Cihaz zaten kayıtlı",
                "Aynı üretici, model ve seri numarasıyla bir cihaz zaten "
                "var — yeni kayıt açılmadı, listede o cihaz seçildi.")
            self._current_dut = existing["id"]
            self.reload()
            return

        from .. import audit
        dut_id = db.execute(
            "INSERT INTO duts (company, manufacturer, model, serial_no,"
            " device_type, notes, created_at) VALUES (?,?,?,?,?,?,?)",
            (company, manufacturer, model, serial, device_type, notes,
             db.utc_now()))
        audit.log("dut.create", user_id=self.state.user["id"], entity="dut",
                  entity_id=dut_id,
                  detail={"serial_no": serial, "model": model,
                          "company": company})
        self._current_dut = dut_id
        self.reload()
        self.state.status("Cihaz eklendi: %s %s — %s"
                          % (manufacturer, model, serial))

    def _edit_device(self):
        dut_id = self.selected_dut_id()
        if dut_id is None:
            return
        d = db.query_one("SELECT * FROM duts WHERE id = ?", (dut_id,))

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Cihaz bilgileri")
        dlg.setMinimumWidth(420)
        company = QtWidgets.QLineEdit(d["company"])
        device_type = QtWidgets.QLineEdit(d["device_type"] or "")
        notes = QtWidgets.QPlainTextEdit(d["notes"] or "")
        notes.setMaximumHeight(90)

        form = QtWidgets.QFormLayout()
        form.addRow("Üretici / model", QtWidgets.QLabel(
            "%s %s" % (d["manufacturer"], d["model"])))
        form.addRow("Seri no", QtWidgets.QLabel(d["serial_no"]))
        form.addRow("Şirket / müşteri", company)
        form.addRow("Cihaz tipi", device_type)
        form.addRow("Not", notes)

        hint = QtWidgets.QLabel(
            "Üretici, model ve seri no değiştirilemez — geçmiş ölçümlerin "
            "hangi cihaza ait olduğu belirsizleşir.")
        hint.setProperty("hint", True)
        hint.setWordWrap(True)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addWidget(buttons)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        from .. import audit
        db.execute("UPDATE duts SET company = ?, device_type = ?, notes = ?"
                   " WHERE id = ?",
                   (company.text().strip(), device_type.text().strip() or None,
                    notes.toPlainText().strip() or None, dut_id))
        audit.log("dut.update", user_id=self.state.user["id"], entity="dut",
                  entity_id=dut_id, detail={"company": company.text().strip()})
        self.reload()
        self.state.status("Cihaz bilgileri güncellendi.")

    def _add_document(self):
        dut_id = self.selected_dut_id()
        if dut_id is None:
            return
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Cihaza iliştirilecek belgeler", "",
            "Belgeler (*.pdf *.docx *.doc *.xlsx *.xls *.jpg *.jpeg *.png);;"
            "Tüm dosyalar (*.*)")
        if not paths:
            return

        dlg = _DocumentDialog(self, count=len(paths),
                              default_title=os.path.basename(paths[0]))
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        added, failed = 0, []
        for path in paths:
            title = dlg.title() if len(paths) == 1 else os.path.basename(path)
            try:
                documents.add(dut_id, path, title, dlg.doc_type(),
                              self.state.user["id"], doc_date=dlg.doc_date(),
                              notes=dlg.notes())
                added += 1
            except Exception as exc:
                failed.append("%s: %s" % (os.path.basename(path), exc))

        self._show_detail()
        self.reload()
        if failed:
            QtWidgets.QMessageBox.warning(
                self, "Bazı belgeler eklenemedi", "\n".join(failed))
        self.state.status("%d belge cihaz kaydına iliştirildi." % added)

    def _selected_document(self):
        rows = self.doc_table.selectionModel().selectedRows()
        if not rows:
            return None
        doc_id = self.doc_table.item(rows[0].row(), 0).data(Qt.UserRole)
        return documents.get(doc_id)

    def _open_document(self):
        doc = self._selected_document()
        if doc is None:
            return
        state, msg = documents.verify(doc["id"])
        if state == "missing":
            QtWidgets.QMessageBox.warning(self, "Dosya bulunamadı", msg)
            return
        if state == "changed":
            QtWidgets.QMessageBox.warning(
                self, "Dosya değişmiş",
                "%s\n\nDosya yine de açılacak." % msg)
        try:
            os.startfile(doc["file_path"])
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Açılamadı", str(exc))

    def _remove_document(self):
        doc = self._selected_document()
        if doc is None:
            return
        reason, ok = QtWidgets.QInputDialog.getText(
            self, "Bağlantıyı kaldır",
            "'%s' cihaz kaydından kaldırılacak.\n"
            "Dosyanın kopyası diskte kalır.\n\nGerekçe (zorunlu):" % doc["title"])
        if not ok:
            return
        try:
            documents.remove(doc["id"], self.state.user["id"], reason)
        except (ValueError, PermissionError) as exc:
            QtWidgets.QMessageBox.warning(self, "Kaldırılamadı", str(exc))
            return
        self._show_detail()
        self.reload()
        self.state.status("Belge bağlantısı kaldırıldı.")


class _NewDeviceDialog(QtWidgets.QDialog):
    """Asks for company/manufacturer/model/serial no for a new device record."""

    def __init__(self, parent=None):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle("Yeni cihaz")
        self.setMinimumWidth(420)

        self._company = QtWidgets.QLineEdit()
        self._manufacturer = QtWidgets.QLineEdit()
        self._model = QtWidgets.QLineEdit()
        self._serial = QtWidgets.QLineEdit()
        self._type = QtWidgets.QLineEdit()
        self._notes = QtWidgets.QPlainTextEdit()
        self._notes.setMaximumHeight(80)

        self._company.setPlaceholderText("Örnek Devlet Hastanesi")
        self._manufacturer.setPlaceholderText("Physio-Control")
        self._model.setPlaceholderText("LIFEPAK 15")
        self._serial.setPlaceholderText("SN-2024-0871")
        self._type.setPlaceholderText("Defibrilatör")

        form = QtWidgets.QFormLayout()
        form.addRow("Şirket / müşteri *", self._company)
        form.addRow("Üretici firma *", self._manufacturer)
        form.addRow("Model *", self._model)
        form.addRow("Seri no *", self._serial)
        form.addRow("Cihaz tipi", self._type)
        form.addRow("Not", self._notes)

        hint = QtWidgets.QLabel(
            "Aynı üretici, model ve seri numarasıyla bir cihaz zaten varsa "
            "yeni kayıt açılmaz — mevcut cihaz kullanılır.")
        hint.setProperty("hint", True)
        hint.setWordWrap(True)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Ekle")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("Vazgeç")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addWidget(buttons)

    def company(self):
        return self._company.text().strip()

    def manufacturer(self):
        return self._manufacturer.text().strip()

    def model(self):
        return self._model.text().strip()

    def serial(self):
        return self._serial.text().strip()

    def device_type(self):
        return self._type.text().strip() or None

    def notes(self):
        return self._notes.toPlainText().strip() or None


class _DocumentDialog(QtWidgets.QDialog):
    """Dialog asking for type, date and title when adding a document."""

    def __init__(self, parent=None, count=1, default_title=""):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle("Belge bilgileri")
        self.setMinimumWidth(420)

        self._title = QtWidgets.QLineEdit(default_title)
        self._type = QtWidgets.QComboBox()
        for key, label in documents.DOC_TYPES:
            self._type.addItem(label, key)
        self._date = QtWidgets.QLineEdit()
        self._date.setPlaceholderText("2023-05-14  (YYYY-AA-GG, boş bırakılabilir)")
        self._notes = QtWidgets.QLineEdit()

        form = QtWidgets.QFormLayout()
        if count == 1:
            form.addRow("Başlık", self._title)
        else:
            form.addRow(QtWidgets.QLabel(
                "%d dosya eklenecek — başlık olarak dosya adları kullanılacak."
                % count))
        form.addRow("Belge türü", self._type)
        form.addRow("Belge tarihi", self._date)
        form.addRow("Not", self._notes)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Ekle")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("Vazgeç")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

    def title(self):
        return self._title.text().strip()

    def doc_type(self):
        return self._type.currentData()

    def doc_date(self):
        return self._date.text().strip() or None

    def notes(self):
        return self._notes.text().strip() or None
