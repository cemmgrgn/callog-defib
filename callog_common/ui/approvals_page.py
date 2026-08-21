"""Approval queue — the lab manager's daily work.

Finding a certificate awaiting approval used to require going into the
history records and setting up a filter; approving it meant opening the
document separately too. Here the queue, the measurement summary, and the
chart sit side by side: everything needed for the decision is on one screen.

The queue is sorted **oldest to newest** (see `certificate.pending`) — the
longest-waiting document is at the top of the list.

"Reject" doesn't add a separate status, it soft-deletes the certificate
along with a reason: the measurement and audit trail stay in place, no gap
opens up in the number series, and a corrected document can be regenerated.
Adding a third "rejected" status to the schema would create an in-between
state where the certificate exists but is considered invalid; whereas an
unapproved certificate is already not an official document.
"""

import os
import zipfile

from .. import audit, certificate, db, perms, testmodes, theme, waveform
from ..qt import Qt, QtGui, QtWidgets, Signal
from .util import empty_state, fit_table, PAGE_MARGIN, PAGE_SPACING


class ApprovalsPage(QtWidgets.QWidget):

    #: So the main window can refresh its counters after an approval/rejection
    queue_changed = Signal()

    def __init__(self, app_state, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.state = app_state

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGIN)
        root.setSpacing(PAGE_SPACING)

        title = QtWidgets.QLabel("Onay kuyruğu")
        title.setProperty("h1", True)
        root.addWidget(title)

        self.hint = QtWidgets.QLabel(
            "Onaylanmamış sertifika resmî belge değildir. Soldan bir kayıt "
            "seçin; ölçüm özeti ve grafiği sağda görünür.")
        self.hint.setProperty("hint", True)
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        split = QtWidgets.QSplitter(Qt.Horizontal)
        split.addWidget(self._queue_table())
        split.addWidget(self._detail())
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setSizes([520, 700])
        root.addWidget(split, 1)

        root.addLayout(self._buttons())

    # --- UI ----------------------------------------------------------
    def _queue_table(self):
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Sertifika no", "Tür", "Tarih", "Cihaz", "Sonuç", "Üreten"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._show_detail)
        self.table.doubleClicked.connect(self._open_pdf)
        return self.table

    def _detail(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.summary = QtWidgets.QTextBrowser()
        lay.addWidget(self.summary, 2)

        import pyqtgraph as pg

        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setMinimumHeight(180)
        lay.addWidget(self.plot, 3)

        self.plot_note = QtWidgets.QLabel("")
        self.plot_note.setProperty("hint", True)
        self.plot_note.setWordWrap(True)
        lay.addWidget(self.plot_note)
        return w

    def _buttons(self):
        row = QtWidgets.QHBoxLayout()
        self.approve_btn = QtWidgets.QPushButton("Onayla")
        self.approve_btn.setProperty("primary", True)
        self.approve_btn.setMinimumHeight(36)
        self.approve_btn.clicked.connect(self._approve)

        self.reject_btn = QtWidgets.QPushButton("Geri çevir…")
        self.reject_btn.setProperty("danger", True)
        self.reject_btn.setToolTip(
            "Sertifika gerekçesiyle birlikte silinmiş olarak işaretlenir.\n"
            "Ölçüm verisi ve denetim izi durur; düzeltilmiş belge yeniden "
            "üretilebilir.")
        self.reject_btn.clicked.connect(self._reject)

        self.preview_btn = QtWidgets.QPushButton("Önizle")
        self.preview_btn.setToolTip(
            "Belgeyi uygulama içinde gösterir. Onaylayan belgenin kendisini "
            "görmeden imzalamamalı.")
        self.preview_btn.clicked.connect(self._preview_pdf)

        self.open_btn = QtWidgets.QPushButton("PDF'i aç")
        self.open_btn.clicked.connect(self._open_pdf)

        self.zip_btn = QtWidgets.QPushButton("Dosyaları zip indir")
        self.zip_btn.setToolTip(
            "Seçili dalga serisindeki her şokun osiloskop ekran görüntüsünü "
            "(PNG) ve ham veri dosyasını (CSV) tek bir zip dosyasında "
            "indirir.")
        self.zip_btn.clicked.connect(self._export_zip)

        refresh_btn = QtWidgets.QPushButton("Yenile")
        refresh_btn.clicked.connect(self.reload)

        for b in (self.approve_btn, self.reject_btn, self.preview_btn,
                  self.open_btn, self.zip_btn, refresh_btn):
            row.addWidget(b)
        row.addStretch(1)
        self.count_label = QtWidgets.QLabel("")
        row.addWidget(self.count_label)
        return row

    # --- data -------------------------------------------------------------
    def showEvent(self, event):
        self.reload()
        QtWidgets.QWidget.showEvent(self, event)

    def reload(self):
        c = theme.colors()
        rows = certificate.pending()
        self.table.setRowCount(0)
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            cells = [
                r["cert_no"], certificate.KIND_TR.get(r["kind"], r["kind"]),
                (r["issued_at"] or "")[:16].replace("T", " "),
                certificate.device_label(r),
                certificate.VERDICT_TR[r["result"]], r["issued_by_name"],
            ]
            for col, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(str(text))
                if col == 0:
                    item.setData(Qt.UserRole, r["id"])
                if col == 4 and r["result"] == "fail":
                    item.setForeground(QtGui.QColor(c["bad"]))
                self.table.setItem(i, col, item)
        fit_table(self.table, stretch_column=3)
        empty_state(self.table, "Onay bekleyen sertifika yok.")
        self.count_label.setText(
            "%d belge onay bekliyor" % len(rows) if rows else "Kuyruk boş")
        self._show_detail()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        cid = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        return db.query_one("SELECT * FROM certificates WHERE id = ?", (cid,))

    def _show_detail(self):
        cert = self._selected()
        can = self.state.can(perms.CERT_APPROVE)
        self.approve_btn.setEnabled(cert is not None and can)
        self.reject_btn.setEnabled(cert is not None
                                   and self.state.can(perms.CERT_DELETE))
        self.open_btn.setEnabled(bool(cert and cert["pdf_path"]))
        self.preview_btn.setEnabled(bool(cert and cert["pdf_path"]))
        self.zip_btn.setEnabled(bool(cert and cert["session_id"] is None))
        self.plot.clear()
        self.plot_note.setText("")

        if cert is None:
            self.summary.setHtml(
                "<p style='color:%s'>Kuyruktan bir sertifika seçin.</p>"
                % theme.colors()["text_muted"])
            return
        try:
            if cert["session_id"] is not None:
                self._session_detail(cert)
            else:
                self._series_detail(cert)
        except Exception as exc:
            self.summary.setHtml("<p>Özet okunamadı: %s</p>" % exc)

    # --- measurement session certificate ---------------------------------------
    def _session_detail(self, cert):
        d = certificate.collect(cert["session_id"])
        s, dut, inst = d["session"], d["dut"], d["instrument"]
        unit = s["unit"]
        c = theme.colors()

        def f(v):
            return "—" if v is None else "%.7g %s" % (v, unit)

        tol = ("± %g %s" % (d["tolerance"], unit)) if d["tolerance"] else "—"
        html = [
            "<h3>%s</h3>" % cert["cert_no"],
            "<b>%s %s</b> (SN %s) · %s<br>" % (
                dut["manufacturer"], dut["model"], dut["serial_no"],
                dut["company"]),
            "Referans: %s %s (SN %s)<br>" % (inst["brand"], inst["model"],
                                             inst["serial_no"]),
            "Operatör: %s<br><br>" % d["operator"]["full_name"],
            "Fonksiyon: %s · n = %d (dışlanan: %d)<br>" % (
                s["function"], d["n"], d["excluded"]),
            "Nominal: %s · Tolerans: %s · Kriter: %s<br>" % (
                f(d["nominal"]), tol, certificate.CRITERION_TR[d["mode"]]),
            "Ortalama: %s · s: %s · U (k=2): %s<br>" % (
                f(d["mean"]), f(d["std"]), f(d["U"])),
            "Sapma: %s<br><br>" % f(d["deviation"]),
            "<b>Sonuç: <span style='color:%s'>%s</span></b>" % (
                c["bad"] if d["result"] == "fail" else c["ok"],
                certificate.VERDICT_TR[d["result"]]),
        ]
        if s["is_simulated"]:
            html.append("<br><span style='color:%s'>Simülasyon verisi — "
                        "filigranlı belge.</span>" % c["warn"])
        if s["notes"]:
            html.append("<br><br><b>Not:</b> %s" % s["notes"])
        self.summary.setHtml("".join(html))
        self._plot_readings(cert["session_id"], d, unit)

    def _plot_readings(self, session_id, d, unit):
        """The session's readings; excluded ones marked separately.

        The average isn't the only thing the approver needs to see: why a
        reading was excluded is only clear from looking at the shape of the series.
        """
        import numpy as np
        import pyqtgraph as pg

        c = theme.colors()
        self.plot.setBackground(QtGui.QColor(c["surface"]))
        for name in ("left", "bottom"):
            axis = self.plot.getAxis(name)
            axis.setPen(pg.mkPen(c["border_strong"]))
            axis.setTextPen(pg.mkPen(c["text_muted"]))
        self.plot.setLabel("bottom", "Okuma sırası")
        self.plot.setLabel("left", unit)

        rows = db.query(
            "SELECT r.seq, r.value, e.id AS excluded FROM readings r"
            " LEFT JOIN reading_exclusions e ON e.reading_id = r.id"
            " WHERE r.session_id = ? ORDER BY r.seq", (session_id,))
        if not rows:
            self.plot_note.setText("Bu oturumda kayıtlı okuma yok.")
            return

        xs = np.array([r["seq"] for r in rows], dtype=float)
        ys = np.array([r["value"] for r in rows], dtype=float)
        self.plot.plot(xs, ys, pen=pg.mkPen(c["curve"], width=1.4))

        dropped = [(r["seq"], r["value"]) for r in rows if r["excluded"]]
        if dropped:
            self.plot.plot(np.array([p[0] for p in dropped], dtype=float),
                           np.array([p[1] for p in dropped], dtype=float),
                           pen=None, symbol="x", symbolSize=9,
                           symbolPen=pg.mkPen(c["bad"], width=2))

        nominal, tol = d["nominal"], d["tolerance"]
        if nominal is not None:
            self.plot.addItem(pg.InfiniteLine(
                pos=nominal, angle=0,
                pen=pg.mkPen(c["mean"], width=1, style=Qt.DashLine)))
            if tol:
                for y in (nominal - abs(tol), nominal + abs(tol)):
                    self.plot.addItem(pg.InfiniteLine(
                        pos=y, angle=0,
                        pen=pg.mkPen(c["guide"], width=1, style=Qt.DotLine)))
        self.plot.getViewBox().autoRange()
        self.plot_note.setText(
            "%d okuma · %d dışlanmış (çarpı işaretli) · kesikli çizgi nominal, "
            "noktalı çizgiler tolerans sınırları."
            % (len(rows), len(dropped)))

    # --- waveform series certificate ----------------------------------------
    def _series_detail(self, cert):
        # Local, optional import: waveform-series certificates are produced
        # only by callog-defib, a separate repo/install. The approval queue
        # is shared (same database, same certificates table), so an approver
        # running callog-seshizi alone may still see one of these rows in
        # the queue — just not be able to render its detail, since the
        # defib-specific report code isn't installed here.
        try:
            from callog_defib import seriesreport
        except ImportError:
            self.summary.setHtml(
                "<p>Bu sertifika türü (dalga serisi) bu kurulumda "
                "görüntülenemiyor — <b>callog-defib</b> yüklü değil.</p>")
            return

        rows = waveform.series_captures(cert["series_id"])
        if not rows:
            self.summary.setHtml(
                "<p>Bu seriye ait yakalama bulunamadı: %s</p>" % cert["series_id"])
            return
        analyses = [waveform.analysis_of(r) for r in rows]
        nominal = next((r["nominal_energy_j"] for r in rows
                        if r["nominal_energy_j"]), None)
        result, detail = seriesreport.energy_verdict(analyses, nominal)
        stats = detail["stats"]
        head = rows[0]
        c = theme.colors()

        def j(v):
            return "—" if v is None else "%.4g J" % v

        device_line = (
            "<b>%s %s</b> (SN %s) · %s<br>" % (
                head["manufacturer"], head["model"], head["serial_no"],
                head["company"])
            if head["manufacturer"] else
            "<b>Cihaza bağlanmadı</b><br>")
        html = [
            "<h3>%s</h3>" % cert["cert_no"],
            device_line,
            "Osiloskop: %s %s (SN %s)<br>" % (
                head["inst_brand"], head["inst_model"], head["inst_serial"]),
            "Operatör: %s<br><br>" % head["operator_name"],
            "Test modu: %s · %d şok<br>" % (
                testmodes.get(head["test_mode"]).label, len(rows)),
            "Ayarlanan enerji: %s · Tolerans: %s<br>" % (
                j(nominal), j(detail["tolerance"])),
        ]
        if stats:
            html.append("Ortalama: %s · s: %s · U (k=2): %s<br>"
                        % (j(stats["mean"]), j(stats["std"]), j(stats["U"])))
            html.append("En küçük / en büyük: %s / %s<br><br>"
                        % (j(stats["min"]), j(stats["max"])))
        else:
            html.append("<br>Çözümlenebilen şok yok.<br><br>")
        html.append("<b>Sonuç: <span style='color:%s'>%s</span></b>" % (
            c["bad"] if result == "fail" else c["ok"],
            certificate.VERDICT_TR[result]))
        if result != cert["result"]:
            # If the set energy changed after the report was generated, the
            # verdict on the document diverges from the one calculated now;
            # the approver shouldn't sign without seeing this.
            html.append("<br><span style='color:%s'>Belgedeki sonuç: %s — "
                        "kayıt rapor üretildikten sonra değişmiş olabilir."
                        "</span>" % (c["warn"],
                                     certificate.VERDICT_TR[cert["result"]]))
        self.summary.setHtml("".join(html))
        self._plot_series(rows, analyses, nominal, detail["tolerance"])

    def _plot_series(self, rows, analyses, nominal, tolerance):
        """Energy shock by shock — the shape of the distribution says more than the average."""
        import numpy as np
        import pyqtgraph as pg

        c = theme.colors()
        self.plot.setBackground(QtGui.QColor(c["surface"]))
        for name in ("left", "bottom"):
            axis = self.plot.getAxis(name)
            axis.setPen(pg.mkPen(c["border_strong"]))
            axis.setTextPen(pg.mkPen(c["text_muted"]))
        self.plot.setLabel("bottom", "Şok sırası")
        self.plot.setLabel("left", "Aktarılan enerji (J)")

        points = [(i + 1, a.get("energy_j")) for i, a in enumerate(analyses)
                  if a and a.get("found") and a.get("energy_j") is not None]
        if not points:
            self.plot_note.setText("Çözümlenebilen şok yok.")
            return
        xs = np.array([p[0] for p in points], dtype=float)
        ys = np.array([p[1] for p in points], dtype=float)
        self.plot.plot(xs, ys, pen=pg.mkPen(c["curve"], width=1.4), symbol="o",
                       symbolSize=7, symbolBrush=pg.mkBrush(c["curve"]))
        if nominal:
            self.plot.addItem(pg.InfiniteLine(
                pos=float(nominal), angle=0,
                pen=pg.mkPen(c["mean"], width=1, style=Qt.DashLine)))
            if tolerance:
                for y in (float(nominal) - tolerance, float(nominal) + tolerance):
                    self.plot.addItem(pg.InfiniteLine(
                        pos=y, angle=0,
                        pen=pg.mkPen(c["guide"], width=1, style=Qt.DotLine)))
        self.plot.getViewBox().autoRange()
        self.plot_note.setText(
            "%d şokun aktarılan enerjisi · kesikli çizgi ayarlanan enerji, "
            "noktalı çizgiler IEC 60601-2-4 toleransı." % len(points)
            if nominal else
            "%d şokun aktarılan enerjisi · ayarlanan enerji girilmediği için "
            "tolerans çizilmedi." % len(points))

    # --- actions ---------------------------------------------------------
    def _approve(self):
        cert = self._selected()
        if cert is None:
            return
        ans = QtWidgets.QMessageBox.question(
            self, "Onay",
            "%s numaralı sertifika onaylansın mı?\n\n"
            "Onaydan sonra sertifika kilitlenir ve değiştirilemez."
            % cert["cert_no"],
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if ans != QtWidgets.QMessageBox.Yes:
            return
        try:
            certificate.approve(cert["id"], self.state.user["id"])
        except (ValueError, PermissionError) as exc:
            QtWidgets.QMessageBox.warning(self, "Onaylanamadı", str(exc))
            return
        self.reload()
        self.queue_changed.emit()
        self.state.status("Sertifika %s onaylandı." % cert["cert_no"])

    def _reject(self):
        cert = self._selected()
        if cert is None:
            return
        reason, ok = QtWidgets.QInputDialog.getText(
            self, "Geri çevir",
            "%s geri çevrilecek.\n\nKayıt veritabanından çıkmaz, silinmiş "
            "olarak işaretlenir; ölçüm verisi durur ve düzeltilmiş belge "
            "yeniden üretilebilir.\n\nGerekçe (zorunlu):" % cert["cert_no"])
        if not ok:
            return
        try:
            certificate.soft_delete(cert["id"], self.state.user["id"], reason)
        except (ValueError, PermissionError) as exc:
            QtWidgets.QMessageBox.warning(self, "Geri çevrilemedi", str(exc))
            return
        self.reload()
        self.queue_changed.emit()
        self.state.status("%s geri çevrildi." % cert["cert_no"])

    def _preview_pdf(self):
        from . import pdf_preview

        cert = self._selected()
        if cert is None:
            return
        pdf_preview.show(cert["pdf_path"], self, title=cert["cert_no"])

    def _open_pdf(self):
        cert = self._selected()
        if cert is None or not cert["pdf_path"]:
            return
        if not os.path.isfile(cert["pdf_path"]):
            QtWidgets.QMessageBox.warning(
                self, "Dosya bulunamadı",
                "Sertifika dosyası yerinde değil:\n%s" % cert["pdf_path"])
            return
        try:
            os.startfile(cert["pdf_path"])
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Açılamadı", str(exc))

    def _export_zip(self):
        """Downloads the screenshots and CSVs of the selected waveform series.

        Session certificates (multimeter readings) have no file counterpart
        on disk, so this is only active for waveform series certificates.
        """
        cert = self._selected()
        if cert is None or cert["session_id"] is not None:
            return
        rows = waveform.series_captures(cert["series_id"])
        files = []
        for r in rows:
            for key in ("file_path", "screenshot_path"):
                p = r[key]
                if p and os.path.isfile(p):
                    files.append(p)
        if not files:
            QtWidgets.QMessageBox.information(
                self, "Dosya yok",
                "Bu seriye ait diskte kayıtlı ekran görüntüsü ya da CSV "
                "bulunamadı.")
            return

        default_name = "%s-dosyalar.zip" % cert["cert_no"]
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Zip olarak kaydet", default_name, "Zip (*.zip)")
        if not path:
            return

        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                seen = set()
                for p in files:
                    arcname = os.path.basename(p)
                    base, ext = os.path.splitext(arcname)
                    n = 1
                    while arcname in seen:
                        arcname = "%s_%d%s" % (base, n, ext)
                        n += 1
                    seen.add(arcname)
                    zf.write(p, arcname)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Kaydedilemedi", str(exc))
            return

        audit.log("certificate.export_zip", user_id=self.state.user["id"],
                  entity="certificate", entity_id=cert["id"],
                  detail={"cert_no": cert["cert_no"], "path": path,
                          "count": len(files)})
        self.state.status(
            "%d dosya %s içine kaydedildi." % (len(files), os.path.basename(path)))
        QtWidgets.QMessageBox.information(
            self, "Tamamlandı",
            "%d dosya zip olarak kaydedildi:\n%s" % (len(files), path))
