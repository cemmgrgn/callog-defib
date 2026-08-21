"""Session setup screen: DUT info, instrument connection, measurement settings."""

import json

from .. import audit, db, drivers, points as points_svc, sessions, templates, theme
from ..drivers import discovery
from ..qt import Qt, QtCore, QtWidgets, Signal
from .util import empty_state, fit_table, page_layout, scroll_body

#: Compliance criterion labels (shared with acquire_page)
CRITERIA_TR = {"mean": "ortalama ± U", "minmax": "tüm okumalar"}


def _point_text(point):
    unit = point.get("unit") or ""
    if point["nominal"] is None:
        return point["function"]
    return "%g %s (%s)" % (point["nominal"], unit, point["function"])


class ScanThread(QtCore.QThread):
    """Device scan — runs in a separate thread so it doesn't block the UI."""

    progress = Signal(str)
    done = Signal(list)

    def run(self):
        try:
            found = discovery.scan(progress=self.progress.emit)
        except Exception as exc:
            self.progress.emit("Tarama hatası: %s" % exc)
            found = []
        self.done.emit(found)


class SetupPage(QtWidgets.QWidget):

    session_started = Signal(int, object)   # session_id, driver

    def __init__(self, app_state, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.state = app_state
        self._scan_thread = None
        self._found = []

        # The page is long: six boxes stack vertically, and on small screens
        # once the total height was exceeded Qt used to squeeze the boxes
        # below their minimum size and clip the text. The scroll area
        # prevents this structurally.
        body = scroll_body(self)
        root = page_layout(body)

        title = QtWidgets.QLabel("Yeni kalibrasyon oturumu")
        title.setProperty("h1", True)
        root.addWidget(title)

        cols = QtWidgets.QHBoxLayout()
        cols.setSpacing(8)
        cols.addWidget(self._dut_box(), 3)
        cols.addWidget(self._instrument_box(), 2)
        root.addLayout(cols, 1)

        root.addWidget(self._name_box())
        root.addWidget(self._measurement_box())
        root.addWidget(self._plan_box())
        root.addWidget(self._env_box())
        root.addLayout(self._actions())

        self._reload_instruments()
        self._reload_templates()

    # --- DUT ------------------------------------------------------------
    def _dut_box(self):
        box = QtWidgets.QGroupBox("Kalibre edilecek cihaz")
        lay = QtWidgets.QVBoxLayout(box)

        self.dut_tabs = QtWidgets.QTabWidget()
        self.dut_tabs.addTab(self._dut_form(), "Yeni cihaz")
        self.dut_tabs.addTab(self._dut_history(), "Geçmiş cihazlar")
        lay.addWidget(self.dut_tabs)
        return box

    def _dut_form(self):
        w = QtWidgets.QWidget()
        self.dut_company = QtWidgets.QLineEdit()
        self.dut_manufacturer = QtWidgets.QLineEdit()
        self.dut_model = QtWidgets.QLineEdit()
        self.dut_serial = QtWidgets.QLineEdit()
        self.dut_type = QtWidgets.QLineEdit()

        self.dut_company.setPlaceholderText("Örnek Devlet Hastanesi")
        self.dut_manufacturer.setPlaceholderText("Fluke")
        self.dut_model.setPlaceholderText("175")
        self.dut_serial.setPlaceholderText("SN-2024-0871")
        self.dut_type.setPlaceholderText("El tipi multimetre")

        # The default session name is generated from company + serial number;
        # update the hint live as the user types
        for widget in (self.dut_company, self.dut_serial):
            widget.textChanged.connect(self._update_name_hint)

        form = QtWidgets.QFormLayout(w)
        form.addRow("Şirket / müşteri *", self.dut_company)
        form.addRow("Üretici firma *", self.dut_manufacturer)
        form.addRow("Model *", self.dut_model)
        form.addRow("Seri no *", self.dut_serial)
        form.addRow("Cihaz tipi", self.dut_type)

        hint = QtWidgets.QLabel(
            "Aynı seri numarasıyla daha önce ölçüm yapıldıysa yeni kayıt "
            "açılmaz, mevcut cihaza bağlanır.")
        hint.setProperty("hint", True)
        hint.setWordWrap(True)
        form.addRow(hint)
        return w

    def _dut_history(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)

        self.dut_search = QtWidgets.QLineEdit()
        self.dut_search.setPlaceholderText("Ara: seri no, model, üretici veya şirket")
        self.dut_search.textChanged.connect(self._reload_dut_history)
        lay.addWidget(self.dut_search)

        self.dut_table = QtWidgets.QTableWidget(0, 5)
        self.dut_table.setHorizontalHeaderLabels(
            ["Üretici / model", "Seri no", "Şirket", "Ölçüm", "Son ölçüm"])
        self.dut_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.dut_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.dut_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.dut_table.setAlternatingRowColors(True)
        self.dut_table.verticalHeader().setVisible(False)
        self.dut_table.horizontalHeader().setStretchLastSection(True)
        self.dut_table.itemSelectionChanged.connect(self._on_dut_selected)
        self.dut_table.doubleClicked.connect(self._use_selected_dut)
        lay.addWidget(self.dut_table, 1)

        row = QtWidgets.QHBoxLayout()
        self.dut_pick_label = QtWidgets.QLabel("")
        self.dut_pick_label.setProperty("hint", True)
        self.dut_pick_label.setWordWrap(True)
        row.addWidget(self.dut_pick_label, 1)
        self.use_dut_btn = QtWidgets.QPushButton("Bu cihaz için yeni sertifikasyon")
        self.use_dut_btn.setEnabled(False)
        self.use_dut_btn.clicked.connect(self._use_selected_dut)
        row.addWidget(self.use_dut_btn)
        lay.addLayout(row)
        return w

    def _reload_dut_history(self):
        sql = (
            "SELECT d.*, COUNT(s.id) AS n, MAX(s.started_at) AS last_at,"
            " (SELECT COUNT(*) FROM certificates c"
            "   JOIN sessions s2 ON s2.id = c.session_id"
            "   WHERE s2.dut_id = d.id) AS cert_count"
            " FROM duts d LEFT JOIN sessions s ON s.dut_id = d.id"
        )
        params = []
        term = self.dut_search.text().strip()
        if term:
            like = "%" + term + "%"
            sql += (" WHERE d.serial_no LIKE ? OR d.model LIKE ?"
                    " OR d.manufacturer LIKE ? OR d.company LIKE ?")
            params = [like, like, like, like]
        sql += " GROUP BY d.id ORDER BY (last_at IS NULL), last_at DESC LIMIT 300"

        rows = db.query(sql, tuple(params))
        self.dut_table.setRowCount(0)
        for r in rows:
            i = self.dut_table.rowCount()
            self.dut_table.insertRow(i)
            cells = [
                "%s %s" % (r["manufacturer"], r["model"]),
                r["serial_no"], r["company"], str(r["n"]),
                (r["last_at"] or "—")[:16].replace("T", " "),
            ]
            for c, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(text)
                if c == 0:
                    item.setData(Qt.UserRole, r["id"])
                self.dut_table.setItem(i, c, item)
        fit_table(self.dut_table, stretch_column=2)
        empty_state(self.dut_table,
                    "Geçmiş cihaz yok — aşağıdaki formu doldurun.")

    def _selected_dut(self):
        rows = self.dut_table.selectionModel().selectedRows()
        if not rows:
            return None
        did = self.dut_table.item(rows[0].row(), 0).data(Qt.UserRole)
        return db.query_one("SELECT * FROM duts WHERE id = ?", (did,))

    def _on_dut_selected(self):
        dut = self._selected_dut()
        self.use_dut_btn.setEnabled(dut is not None)
        if dut is None:
            self.dut_pick_label.setText("")
            return
        last = db.query_one(
            "SELECT s.started_at, s.function, s.nominal, s.unit, c.cert_no, c.result"
            " FROM sessions s LEFT JOIN certificates c ON c.session_id = s.id"
            " WHERE s.dut_id = ? ORDER BY s.id DESC LIMIT 1", (dut["id"],))
        if last is None:
            self.dut_pick_label.setText("Bu cihaz için henüz ölçüm yapılmamış.")
            return
        self.dut_pick_label.setText(
            "Son ölçüm: %s · %s%s%s" % (
                (last["started_at"] or "")[:16].replace("T", " "),
                last["function"],
                "" if last["nominal"] is None else " · nominal %g %s" % (
                    last["nominal"], last["unit"]),
                "" if not last["cert_no"] else " · %s" % last["cert_no"]))

    def load_dut(self, dut_id):
        """Loads the device coming from the Devices page into the form."""
        dut = db.query_one("SELECT * FROM duts WHERE id = ?", (dut_id,))
        if dut is None:
            return
        self._fill_dut_form(dut)
        self.dut_tabs.setCurrentIndex(0)

    def _use_selected_dut(self):
        """Fills the form with a past device and suggests its previous measurement settings."""
        dut = self._selected_dut()
        if dut is None:
            return
        self._fill_dut_form(dut)
        self.dut_tabs.setCurrentIndex(0)

    def _fill_dut_form(self, dut):
        """Writes the device info and its previous measurement settings into the form."""
        self.dut_company.setText(dut["company"])
        self.dut_manufacturer.setText(dut["manufacturer"])
        self.dut_model.setText(dut["model"])
        self.dut_serial.setText(dut["serial_no"])
        self.dut_type.setText(dut["device_type"] or "")

        # The same device is usually calibrated at the same points — bring back the previous settings
        last = db.query_one(
            "SELECT function, nominal, tolerance, tolerance_mode FROM sessions"
            " WHERE dut_id = ? ORDER BY id DESC LIMIT 1", (dut["id"],))
        if last:
            idx = self.function_combo.findData(last["function"])
            if idx >= 0:
                self.function_combo.setCurrentIndex(idx)
            if last["nominal"] is not None:
                self.nominal_edit.setText("%g" % last["nominal"])
            if last["tolerance"] is not None:
                self.tolerance_edit.setText("%g" % abs(last["tolerance"]))
            idx = self.criterion_combo.findData(last["tolerance_mode"] or "mean")
            if idx >= 0:
                self.criterion_combo.setCurrentIndex(idx)

        self.state.status("%s %s (SN %s) forma alındı." % (
            dut["manufacturer"], dut["model"], dut["serial_no"]))

    # --- templates --------------------------------------------------------
    def _reload_templates(self):
        """Refreshes the template dropdown; keeps the selected template."""
        previous = self.template_combo.currentData()
        inst = self._current_instrument()
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        self.template_combo.addItem("— şablon seçin —", None)
        for row in templates.list_all(inst["driver"] if inst else None):
            n = len(templates.points_of(row))
            self.template_combo.addItem("%s  (%d nokta)" % (row["name"], n),
                                        row["id"])
        idx = self.template_combo.findData(previous)
        self.template_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.template_combo.blockSignals(False)
        has = self.template_combo.count() > 1
        self.apply_tpl_btn.setEnabled(has)
        self.del_tpl_btn.setEnabled(has)

    def _apply_template(self):
        tid = self.template_combo.currentData()
        if tid is None:
            QtWidgets.QMessageBox.information(
                self, "Şablon seçilmedi", "Önce listeden bir şablon seçin.")
            return
        row = templates.get(tid)
        plan = templates.points_of(row)
        if not plan:
            QtWidgets.QMessageBox.warning(
                self, "Şablon boş",
                "Bu şablonda ölçüm noktası yok ya da kaydı bozuk.")
            return
        if self.plan_table.rowCount():
            ans = QtWidgets.QMessageBox.question(
                self, "Planı değiştir",
                "Mevcut plandaki %d nokta silinip şablondaki %d nokta "
                "yüklenecek. Devam edilsin mi?"
                % (self.plan_table.rowCount(), len(plan)),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if ans != QtWidgets.QMessageBox.Yes:
                return

        self.plan_table.setRowCount(0)
        unknown = []
        for point in plan:
            # If the template was prepared for a different driver, the function
            # may not exist on this instrument; loading it silently would turn
            # into a confusing error at "start".
            if self.function_combo.findData(point.get("function")) < 0:
                unknown.append(point.get("function"))
                continue
            self._append_point(dict(point))
        if row["interval_s"]:
            self.interval_spin.setValue(float(row["interval_s"]))
        if row["nplc"]:
            self.nplc_combo.setCurrentText(str(row["nplc"]))
        if unknown:
            QtWidgets.QMessageBox.warning(
                self, "Bazı noktalar atlandı",
                "Seçili referans cihazda bulunmayan fonksiyonlar atlandı:\n\n%s"
                % ", ".join(sorted(set(unknown))))
        self.state.status("Şablon uygulandı: %s (%d nokta)"
                          % (row["name"], self.plan_table.rowCount()))

    def _save_template(self):
        plan = self.plan()
        if not plan:
            QtWidgets.QMessageBox.information(
                self, "Plan boş",
                "Önce en az bir nokta ekleyin. Şablon, plandaki noktaları "
                "okuma periyodu ve NPLC ile birlikte saklar.")
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Şablon olarak kaydet",
            "Şablon adı (aynı ad varsa üzerine yazılır):",
            QtWidgets.QLineEdit.Normal,
            "%s · %d nokta" % (self.dut_model.text().strip() or "Şablon",
                               len(plan)))
        if not ok:
            return
        inst = self._current_instrument()
        try:
            templates.save(name, plan,
                           driver=inst["driver"] if inst else None,
                           interval_s=self.interval_spin.value(),
                           nplc=self.nplc_combo.currentText(),
                           user_id=self.state.user["id"])
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Kaydedilemedi", str(exc))
            return
        self._reload_templates()
        self.state.status("Şablon kaydedildi: %s" % name.strip())

    def _delete_template(self):
        tid = self.template_combo.currentData()
        if tid is None:
            return
        row = templates.get(tid)
        ans = QtWidgets.QMessageBox.question(
            self, "Şablonu sil",
            "'%s' şablonu silinsin mi?\n\nBu şablondan üretilmiş oturumlar "
            "etkilenmez — plan oturuma kopyalanıyor." % row["name"],
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if ans != QtWidgets.QMessageBox.Yes:
            return
        templates.delete(tid, self.state.user["id"])
        self._reload_templates()
        self.state.status("Şablon silindi: %s" % row["name"])

    # --- reference instrument --------------------------------------------------
    def _instrument_box(self):
        box = QtWidgets.QGroupBox("Referans cihaz")
        self.instrument_combo = QtWidgets.QComboBox()
        self.instrument_combo.currentIndexChanged.connect(self._on_instrument_changed)

        self.address_edit = QtWidgets.QLineEdit()
        self.address_edit.setPlaceholderText("örn. GPIB0::22::INSTR")

        self.baud_combo = QtWidgets.QComboBox()
        self.baud_combo.setEditable(True)
        for b in discovery.BAUD_CANDIDATES:
            self.baud_combo.addItem(str(b))
        self.baud_label = QtWidgets.QLabel("Baud rate")

        self.scan_btn = QtWidgets.QPushButton("Cihazları tara")
        self.scan_btn.clicked.connect(self._scan)
        self.test_btn = QtWidgets.QPushButton("Bağlantıyı test et")
        self.test_btn.clicked.connect(self._test_connection)

        self.scan_log = QtWidgets.QPlainTextEdit()
        self.scan_log.setReadOnly(True)
        self.scan_log.setMaximumHeight(84)

        form = QtWidgets.QFormLayout(box)
        form.addRow("Cihaz", self.instrument_combo)
        form.addRow("VISA adresi", self.address_edit)
        form.addRow(self.baud_label, self.baud_combo)
        btns = QtWidgets.QHBoxLayout()
        btns.addWidget(self.scan_btn)
        btns.addWidget(self.test_btn)
        form.addRow(btns)
        form.addRow(self.scan_log)
        return box

    def _measurement_box(self):
        box = QtWidgets.QGroupBox("Ölçüm ayarları")
        self.function_combo = QtWidgets.QComboBox()
        self.nominal_edit = QtWidgets.QLineEdit()
        self.nominal_edit.setPlaceholderText("10.0")
        self.tolerance_edit = QtWidgets.QLineEdit()
        self.tolerance_edit.setPlaceholderText("0.002")
        self.tolerance_edit.setToolTip(
            "Tolerans her zaman ± olarak uygulanır; işaret girmenize gerek yok.")

        self.criterion_combo = QtWidgets.QComboBox()
        self.criterion_combo.addItem("Ortalama ± U tolerans içinde", "mean")
        self.criterion_combo.addItem("Tüm okumalar tolerans içinde", "minmax")
        self.criterion_combo.setToolTip(
            "Uygunluk kararının neye bakacağı.\n\n"
            "Ortalama ± U: |ortalama − nominal| + 2u ≤ tolerans.\n"
            "Kalibrasyonda yaygın karar kuralı budur.\n\n"
            "Tüm okumalar: tek bir okuma bile bandın dışına çıkarsa uygun değil.\n"
            "Kararsız cihazlarda ortalamanın gizlediği sapmaları yakalar.")
        self.interval_spin = QtWidgets.QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 600.0)
        self.interval_spin.setValue(1.0)
        self.interval_spin.setSuffix(" s")
        self.nplc_combo = QtWidgets.QComboBox()
        for v in ("0.02", "0.2", "1", "10", "100"):
            self.nplc_combo.addItem(v)
        self.nplc_combo.setCurrentText("10")
        self.nplc_label = QtWidgets.QLabel("NPLC")

        # Channel is only meaningful on multi-channel instruments (oscilloscope);
        # NPLC only on a multimeter. Both share the same grid cell and one is
        # shown depending on the instrument — instead of leaving an irrelevant
        # field grayed out.
        self.channel_combo = QtWidgets.QComboBox()
        self.channel_label = QtWidgets.QLabel("Kanal")
        self.channel_combo.setVisible(False)
        self.channel_label.setVisible(False)

        grid = QtWidgets.QGridLayout(box)
        grid.addWidget(QtWidgets.QLabel("Fonksiyon"), 0, 0)
        grid.addWidget(self.function_combo, 0, 1)
        grid.addWidget(self.nplc_label, 0, 2)
        grid.addWidget(self.nplc_combo, 0, 3)
        grid.addWidget(self.channel_label, 0, 2)
        grid.addWidget(self.channel_combo, 0, 3)
        grid.addWidget(QtWidgets.QLabel("Okuma periyodu"), 0, 4)
        grid.addWidget(self.interval_spin, 0, 5)
        grid.addWidget(QtWidgets.QLabel("Nominal değer"), 1, 0)
        grid.addWidget(self.nominal_edit, 1, 1)
        grid.addWidget(QtWidgets.QLabel("Tolerans (±)"), 1, 2)
        grid.addWidget(self.tolerance_edit, 1, 3)
        grid.addWidget(QtWidgets.QLabel("Uygunluk kriteri"), 1, 4)
        grid.addWidget(self.criterion_combo, 1, 5)
        for c in (1, 3, 5):
            grid.setColumnStretch(c, 1)
        return box

    # --- measurement plan ------------------------------------------------------
    def _plan_box(self):
        """Multiple measurement points — e.g. 10 V, 100 V, 1 kOhm in one session.

        The plan **can be left empty**: in that case the fields above form a
        single-point plan and the flow stays the same as before. Forcing an
        operator who only measures one point to build a plan would cost more
        than it gains.
        """
        box = QtWidgets.QGroupBox("Ölçüm planı")
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        self.plan_table = QtWidgets.QTableWidget(0, 5)
        self.plan_table.setHorizontalHeaderLabels(
            ["#", "Fonksiyon", "Nominal", "Tolerans (±)", "Kriter"])
        self.plan_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.plan_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.plan_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.plan_table.setAlternatingRowColors(True)
        self.plan_table.verticalHeader().setVisible(False)
        self.plan_table.setMaximumHeight(126)
        lay.addWidget(self.plan_table)

        row = QtWidgets.QHBoxLayout()
        self.add_point_btn = QtWidgets.QPushButton("Noktayı plana ekle")
        self.add_point_btn.setToolTip(
            "Yukarıdaki fonksiyon, nominal, tolerans ve kriter değerlerini\n"
            "plana bir nokta olarak ekler.")
        self.add_point_btn.clicked.connect(self._add_point)
        self.del_point_btn = QtWidgets.QPushButton("Kaldır")
        self.del_point_btn.clicked.connect(self._remove_point)
        self.up_point_btn = QtWidgets.QPushButton("↑")
        self.up_point_btn.setToolTip("Seçili noktayı yukarı taşı")
        self.up_point_btn.clicked.connect(lambda: self._move_point(-1))
        self.down_point_btn = QtWidgets.QPushButton("↓")
        self.down_point_btn.setToolTip("Seçili noktayı aşağı taşı")
        self.down_point_btn.clicked.connect(lambda: self._move_point(1))
        for b in (self.add_point_btn, self.del_point_btn, self.up_point_btn,
                  self.down_point_btn):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(QtWidgets.QLabel("Şablon"))
        self.template_combo = QtWidgets.QComboBox()
        self.template_combo.setMinimumWidth(180)
        row.addWidget(self.template_combo)
        self.apply_tpl_btn = QtWidgets.QPushButton("Uygula")
        self.apply_tpl_btn.clicked.connect(self._apply_template)
        self.save_tpl_btn = QtWidgets.QPushButton("Şablon olarak kaydet")
        self.save_tpl_btn.clicked.connect(self._save_template)
        self.del_tpl_btn = QtWidgets.QPushButton("Şablonu sil")
        self.del_tpl_btn.clicked.connect(self._delete_template)
        for b in (self.apply_tpl_btn, self.save_tpl_btn, self.del_tpl_btn):
            row.addWidget(b)
        lay.addLayout(row)

        self.plan_hint = QtWidgets.QLabel("")
        self.plan_hint.setProperty("hint", True)
        self.plan_hint.setWordWrap(True)
        lay.addWidget(self.plan_hint)
        self._update_plan_hint()
        return box

    def plan(self):
        """Points in the plan: a list of dicts. Defaults to a single point if empty."""
        rows = []
        for r in range(self.plan_table.rowCount()):
            rows.append(self.plan_table.item(r, 0).data(Qt.UserRole))
        return rows

    def _current_point(self):
        """Builds a point dict from the fields in the form."""
        key = self.function_combo.currentData()
        if not key:
            return None
        inst = self._current_instrument()
        cls = drivers.REGISTRY.get(inst["driver"]) if inst else None
        fn = cls.function_by_key(key) if cls else None
        channel = (self.channel_combo.currentData()
                   if self.channel_combo.count() else None)
        return {
            "function": key,
            "unit": fn.unit if fn else "",
            "nominal": self._parse_float(self.nominal_edit.text()),
            "tolerance": self._tolerance(),
            "tolerance_mode": self.criterion_combo.currentData(),
            "channel": channel,
            "label": self.function_combo.currentText(),
        }

    def _add_point(self):
        point = self._current_point()
        if point is None:
            QtWidgets.QMessageBox.warning(
                self, "Fonksiyon yok", "Önce ölçüm fonksiyonu seçin.")
            return
        self._append_point(point)
        self.state.status("Plana eklendi: %s" % _point_text(point))

    def _append_point(self, point):
        r = self.plan_table.rowCount()
        self.plan_table.insertRow(r)
        self._fill_plan_row(r, point)
        self._renumber_plan()

    def _fill_plan_row(self, r, point):
        unit = point.get("unit") or ""
        cells = [
            "", point.get("label") or point["function"],
            "—" if point["nominal"] is None else "%g %s" % (point["nominal"], unit),
            "—" if not point["tolerance"] else "%g %s" % (point["tolerance"], unit),
            CRITERIA_TR.get(point["tolerance_mode"], point["tolerance_mode"]),
        ]
        for c, text in enumerate(cells):
            item = QtWidgets.QTableWidgetItem(text)
            if c == 0:
                item.setData(Qt.UserRole, point)
            self.plan_table.setItem(r, c, item)

    def _renumber_plan(self):
        for r in range(self.plan_table.rowCount()):
            self.plan_table.item(r, 0).setText(str(r + 1))
        fit_table(self.plan_table, stretch_column=1)
        self._update_plan_hint()

    def _remove_point(self):
        rows = self.plan_table.selectionModel().selectedRows()
        if not rows:
            return
        self.plan_table.removeRow(rows[0].row())
        self._renumber_plan()

    def _move_point(self, delta):
        rows = self.plan_table.selectionModel().selectedRows()
        if not rows:
            return
        r = rows[0].row()
        target = r + delta
        if not (0 <= target < self.plan_table.rowCount()):
            return
        here = self.plan_table.item(r, 0).data(Qt.UserRole)
        there = self.plan_table.item(target, 0).data(Qt.UserRole)
        self._fill_plan_row(r, there)
        self._fill_plan_row(target, here)
        self._renumber_plan()
        self.plan_table.selectRow(target)

    def _update_plan_hint(self):
        n = self.plan_table.rowCount()
        if n == 0:
            self.plan_hint.setText(
                "Plan boş — yukarıdaki değerlerle tek noktalı ölçüm yapılır. "
                "Birden çok nokta ölçecekseniz her birini plana ekleyin; "
                "hepsi tek oturumda ölçülür ve tek sertifikada toplanır.")
        else:
            self.plan_hint.setText(
                "%d nokta planlandı. Ölçüm ekranında sırayla ölçülür; "
                "sertifikada her nokta kendi bölümünü alır." % n)

    def _env_box(self):
        box = QtWidgets.QGroupBox("Ortam şartları")
        self.env_temp = QtWidgets.QLineEdit()
        self.env_rh = QtWidgets.QLineEdit()
        self.env_pressure = QtWidgets.QLineEdit()

        row = QtWidgets.QHBoxLayout(box)
        for label, widget, unit in (
            ("Sıcaklık", self.env_temp, "°C"),
            ("Nem", self.env_rh, "%RH"),
            ("Basınç", self.env_pressure, "kPa"),
        ):
            row.addWidget(QtWidgets.QLabel(label))
            widget.setMaximumWidth(90)
            row.addWidget(widget)
            row.addWidget(QtWidgets.QLabel(unit))
            row.addSpacing(14)
        note = QtWidgets.QLabel(
            "Şu an elle giriliyor. Ağ üzerindeki sensörün API bilgisi "
            "netleştiğinde bu alanlar otomatik dolacak.")
        note.setProperty("hint", True)
        note.setWordWrap(True)
        row.addWidget(note, 1)
        return box

    def _name_box(self):
        box = QtWidgets.QGroupBox("Oturum adı")
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText(
            "Boş bırakılırsa: Firma · Seri no · tarih saat")
        self.name_edit.setToolTip(
            "Geçmiş kayıtlarda oturumu bu adla bulursunuz.\n"
            "Boş bırakırsanız firma adı, seri no ve tarih-saatten üretilir.")
        self.name_hint = QtWidgets.QLabel("")
        self.name_hint.setProperty("hint", True)
        self.name_hint.setWordWrap(True)

        lay = QtWidgets.QHBoxLayout(box)
        lay.addWidget(self.name_edit, 2)
        lay.addWidget(self.name_hint, 3)
        return box

    def _update_name_hint(self):
        """Shows live how the default name will look."""
        if not hasattr(self, "name_hint"):
            return          # DUT form is built before the name box
        company = self.dut_company.text().strip() or "Bilinmeyen firma"
        serial = self.dut_serial.text().strip() or "seri no yok"
        stamp = db.utc_now().replace("T", " ")[:16]
        self.name_hint.setText(
            "Varsayılan: %s · %s · %s" % (company, serial, stamp))

    def _actions(self):
        row = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        row.addWidget(self.status_label, 1)
        self.start_btn = QtWidgets.QPushButton("Bağlan ve ölçüme başla")
        self.start_btn.setProperty("primary", True)
        self.start_btn.setMinimumHeight(38)
        self.start_btn.clicked.connect(self._start)
        row.addWidget(self.start_btn)
        return row

    # --- behavior -------------------------------------------------------
    def showEvent(self, event):
        self._update_name_hint()
        self._reload_dut_history()
        QtWidgets.QWidget.showEvent(self, event)

    def _reload_instruments(self):
        self.instrument_combo.clear()
        for row in db.query("SELECT * FROM instruments WHERE is_active = 1 ORDER BY id"):
            label = "%s %s — %s" % (row["brand"], row["model"], row["serial_no"])
            if drivers.is_simulated(row["driver"]):
                label = "[SİMÜLASYON] " + label
            self.instrument_combo.addItem(label, row["id"])

    def _current_instrument(self):
        iid = self.instrument_combo.currentData()
        if iid is None:
            return None
        return db.query_one("SELECT * FROM instruments WHERE id = ?", (iid,))

    def _on_instrument_changed(self):
        inst = self._current_instrument()
        if inst is None:
            return
        self.address_edit.setText(inst["address"] or "")
        is_sim = drivers.is_simulated(inst["driver"])
        self.address_edit.setEnabled(not is_sim)
        self.scan_btn.setEnabled(not is_sim)
        self.test_btn.setEnabled(not is_sim)

        cfg = json.loads(inst["serial_cfg"]) if inst["serial_cfg"] else {}
        if cfg.get("baud"):
            self.baud_combo.setCurrentText(str(cfg["baud"]))
        serial_visible = (inst["address"] or "").upper().startswith("ASRL")
        self.baud_combo.setVisible(serial_visible and not is_sim)
        self.baud_label.setVisible(serial_visible and not is_sim)

        cls = drivers.REGISTRY.get(inst["driver"])
        self.function_combo.clear()
        if cls:
            for f in cls.FUNCTIONS:
                self.function_combo.addItem("%s (%s)" % (f.label, f.unit), f.key)

        channels = list(getattr(cls, "CHANNELS", ()) or ())
        self.channel_combo.clear()
        for name, label in channels:
            self.channel_combo.addItem(label, name)
        has_channels = bool(channels)
        self.channel_combo.setVisible(has_channels)
        self.channel_label.setVisible(has_channels)
        self.nplc_combo.setVisible(not has_channels)
        self.nplc_label.setVisible(not has_channels)

        self._check_calibration(inst)
        if hasattr(self, "template_combo"):
            self._reload_templates()

    def _check_calibration(self, inst):
        """Whether the reference instrument's calibration is valid — warns, doesn't block."""
        c = theme.colors()
        if drivers.is_simulated(inst["driver"]):
            self.status_label.setText(
                "<span style='color:%s'>Simülasyon modu — üretilecek sertifika "
                "filigranlı ve SIM- serisinden numaralı olur.</span>" % c["warn"])
            return
        due = inst["cal_due"]
        if not due:
            self.status_label.setText(
                "<span style='color:%s'>Referans cihazın kalibrasyon geçerlilik "
                "tarihi girilmemiş.</span>" % c["warn"])
            return
        from datetime import date
        try:
            d = date(*[int(x) for x in due.split("-")])
        except Exception:
            self.status_label.setText("Kalibrasyon tarihi okunamadı: %s" % due)
            return
        remaining = (d - date.today()).days
        if remaining < 0:
            self.status_label.setText(
                "<span style='color:%s'><b>Referans cihazın kalibrasyonu %d gün "
                "önce dolmuş.</b> Bu cihazla alınan ölçüm geçersizdir.</span>"
                % (c["bad"], abs(remaining)))
        elif remaining < 30:
            self.status_label.setText(
                "<span style='color:%s'>Kalibrasyon geçerliliğine %d gün kaldı."
                "</span>" % (c["warn"], remaining))
        else:
            self.status_label.setText("Kalibrasyon geçerli (%d gün)." % remaining)

    # --- scan ---------------------------------------------------------
    def _scan(self):
        self.scan_log.clear()
        self.scan_btn.setEnabled(False)
        self.scan_log.appendPlainText("Tarama başladı...")
        self._scan_thread = ScanThread(self)
        self._scan_thread.progress.connect(self.scan_log.appendPlainText)
        self._scan_thread.done.connect(self._scan_done)
        self._scan_thread.start()

    def _scan_done(self, found):
        self.scan_btn.setEnabled(True)
        self._found = found
        if not found:
            self.scan_log.appendPlainText(
                "Cihaz bulunamadı. NI-VISA kurulu mu ve USB-GPIB adaptörü bağlı mı "
                "kontrol edin.")
            return
        for f in found:
            mark = "TANINDI" if f.recognized else "tanınmadı"
            self.scan_log.appendPlainText("[%s] %s → %s" % (mark, f.address, f.idn))

        inst = self._current_instrument()
        if inst is None:
            return
        for f in found:
            if f.serial_no and f.serial_no.strip() == inst["serial_no"].strip():
                self.address_edit.setText(f.address)
                if f.serial_cfg.get("baud"):
                    self.baud_combo.setCurrentText(str(f.serial_cfg["baud"]))
                self.scan_log.appendPlainText(
                    "Envanterdeki cihaz bulundu: %s" % f.address)
                self._persist_address(inst["id"], f)
                return
        self.scan_log.appendPlainText(
            "Uyarı: bulunan cihazların seri numarası envanterdeki %s ile "
            "eşleşmiyor." % inst["serial_no"])

    def _persist_address(self, instrument_id, found):
        cfg = json.dumps(found.serial_cfg) if found.serial_cfg else None
        iface = "serial" if found.address.upper().startswith("ASRL") else "gpib"
        db.execute(
            "UPDATE instruments SET address = ?, iface = ?, serial_cfg = ? WHERE id = ?",
            (found.address, iface, cfg, instrument_id))
        audit.log("instrument.address_update", user_id=self.state.user["id"],
                  entity="instrument", entity_id=instrument_id,
                  detail={"address": found.address, "idn": found.idn})

    def _test_connection(self):
        inst = self._current_instrument()
        if inst is None:
            return
        drv = self._build_driver(inst)
        try:
            idn = drv.connect()
            QtWidgets.QMessageBox.information(
                self, "Bağlantı başarılı", "Cihaz yanıtı:\n\n%s" % idn)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Bağlantı kurulamadı", str(exc))
        finally:
            try:
                drv.close()
            except Exception:
                pass

    def _build_driver(self, inst, nominal=None):
        """Builds the driver. `nominal` is only meaningful in simulation.

        If a plan exists, the nominal of its first point is passed: the value
        in the field can belong to whichever point was most recently added to
        the plan, and the simulator would then read the first point at the
        wrong value.
        """
        kwargs = {}
        if not drivers.is_simulated(inst["driver"]):
            addr = self.address_edit.text().strip()
            if addr.upper().startswith("ASRL"):
                kwargs["serial_cfg"] = {"baud": int(self.baud_combo.currentText())}
        else:
            addr = "SIM"
            if nominal is None:
                nominal = self._parse_float(self.nominal_edit.text())
            if nominal:
                kwargs["nominal"] = nominal
        return drivers.create(inst["driver"], addr, **kwargs)

    def _tolerance(self):
        """Tolerance is always treated as ±; any sign entered is ignored."""
        value = self._parse_float(self.tolerance_edit.text())
        return abs(value) if value is not None else None

    @staticmethod
    def _parse_float(text):
        text = (text or "").strip().replace(",", ".")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    # --- session start -------------------------------------------------
    def _get_or_create_dut(self):
        """Keeps a single DUT record for the same device.

        Opening a new row on every session made the history list unusable;
        if serial no + manufacturer + model match, the existing record is used.
        """
        serial = self.dut_serial.text().strip()
        manufacturer = self.dut_manufacturer.text().strip()
        model = self.dut_model.text().strip()
        company = self.dut_company.text().strip()
        device_type = self.dut_type.text().strip() or None

        row = db.query_one(
            "SELECT * FROM duts WHERE serial_no = ? AND manufacturer = ?"
            " AND model = ? LIMIT 1", (serial, manufacturer, model))
        if row:
            if row["company"] != company or row["device_type"] != device_type:
                db.execute(
                    "UPDATE duts SET company = ?, device_type = ? WHERE id = ?",
                    (company, device_type, row["id"]))
                audit.log("dut.update", user_id=self.state.user["id"],
                          entity="dut", entity_id=row["id"],
                          detail={"company": company, "device_type": device_type})
            return row["id"]

        dut_id = db.execute(
            "INSERT INTO duts (company, manufacturer, model, serial_no, device_type,"
            " created_at) VALUES (?,?,?,?,?,?)",
            (company, manufacturer, model, serial, device_type, db.utc_now()))
        audit.log("dut.create", user_id=self.state.user["id"], entity="dut",
                  entity_id=dut_id,
                  detail={"serial_no": serial, "model": model, "company": company})
        return dut_id

    def _start(self):
        missing = [n for n, w in (
            ("Şirket / müşteri", self.dut_company),
            ("Üretici firma", self.dut_manufacturer),
            ("Model", self.dut_model),
            ("Seri no", self.dut_serial),
        ) if not w.text().strip()]
        if missing:
            QtWidgets.QMessageBox.warning(
                self, "Eksik bilgi",
                "Şu alanlar doldurulmalı:\n\n• " + "\n• ".join(missing))
            self.dut_tabs.setCurrentIndex(0)
            return

        inst = self._current_instrument()
        if inst is None:
            QtWidgets.QMessageBox.warning(self, "Cihaz yok", "Referans cihaz seçin.")
            return

        # If the plan is empty, the form values become a single-point plan —
        # an operator measuring one point doesn't have to build a plan.
        plan = self.plan()
        if not plan:
            single = self._current_point()
            if single is None:
                QtWidgets.QMessageBox.warning(
                    self, "Fonksiyon yok", "Ölçüm fonksiyonu seçin.")
                return
            plan = [single]

        function_key = plan[0]["function"]
        drv = self._build_driver(inst, nominal=plan[0]["nominal"])
        try:
            drv.connect()
            # isVisible() can't be used here: if the page hasn't been shown yet
            # (tests, background tab) it always returns False and the channel
            # gets silently dropped. count() reflects the widget's own state.
            channel = plan[0].get("channel") or (
                self.channel_combo.currentData()
                if self.channel_combo.count() else None)
            settings = ({"channel": channel} if channel
                        else {"nplc": self.nplc_combo.currentText()})
            drv.configure(function_key, **settings)
        except Exception as exc:
            try:
                drv.close()
            except Exception:
                pass
            QtWidgets.QMessageBox.critical(self, "Cihaz hatası", str(exc))
            return

        dut_id = self._get_or_create_dut()

        import uuid as _uuid
        fn = drivers.REGISTRY[inst["driver"]].function_by_key(function_key)
        started_at = db.utc_now()
        name = (self.name_edit.text().strip()
                or sessions.default_name(dut_id, started_at))
        # The session columns mirror the plan's first point: the history list,
        # trend chart, and waveform queries keep reading these columns.
        first = plan[0]
        session_id = db.execute(
            "INSERT INTO sessions (name, uuid, operator_id, dut_id, instrument_id, function,"
            " channel, unit, nominal, tolerance, tolerance_mode, started_at, status,"
            " is_simulated, env_temp, env_rh, env_pressure, env_source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (name, str(_uuid.uuid4()), self.state.user["id"], dut_id, inst["id"],
             function_key, channel, first.get("unit") or fn.unit,
             first["nominal"], first["tolerance"], first["tolerance_mode"],
             started_at, "running", 1 if drv.is_simulated else 0,
             self._parse_float(self.env_temp.text()),
             self._parse_float(self.env_rh.text()),
             self._parse_float(self.env_pressure.text()),
             "manual"))

        for seq, point in enumerate(plan, start=1):
            points_svc.create(
                session_id, seq, point["function"],
                point.get("unit") or fn.unit, point["nominal"],
                point["tolerance"], point["tolerance_mode"],
                point.get("channel"))

        audit.log("session.start", user_id=self.state.user["id"],
                  entity="session", entity_id=session_id,
                  detail={"dut_id": dut_id, "instrument": inst["serial_no"],
                          "function": function_key, "name": name,
                          "channel": channel, "points": len(plan),
                          "simulated": bool(drv.is_simulated)})

        self.session_started.emit(session_id, drv)
