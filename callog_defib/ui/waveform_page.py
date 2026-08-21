"""Waveform capture page -- trigger-driven CSV recording.

A separate page from the measurement page because the workflow is
fundamentally different: there, readings are taken at fixed intervals and
statistics accumulate; here, an **event** is awaited and each event is its
own record.

Captured point data is written to CSV, not the database; the database only
holds the metadata (who, when, how many points, SHA-256). See
`callog_common/waveform.py` for the rationale.
"""

from callog_common import testmodes
from callog_common import theme
from callog_common import waveform
from callog_common.acquisition import WaveformWorker
from callog_common.qt import Qt
from callog_common.qt import QtCore
from callog_common.qt import QtGui
from callog_common.qt import QtWidgets
from callog_common.ui.util import PAGE_MARGIN
from callog_common.ui.util import PAGE_SPACING
from callog_common.ui.util import empty_state
from callog_common.ui.util import fit_table
from callog_common.ui.waveform_discovery import _DiscoveryMixin
from .waveform_capture import _CaptureMixin
from callog_common.ui.waveform_common import _si
# Backward-compatible import: tests call these two through `waveform_page`;
# their actual definitions now live in waveform_common.py.
from callog_common.ui.waveform_common import (_ENERGY_SCALE_DURATION_S,  # noqa: F401
                              _estimate_vdiv_for_energy)  # noqa: F401
from .waveform_results import _ResultsMixin
from .waveform_setup import _SetupMixin
import os


class WaveformPage(_DiscoveryMixin, _SetupMixin, _CaptureMixin,
                   _ResultsMixin, QtWidgets.QWidget):

    def __init__(self, app_state, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.state = app_state
        self.driver = None
        self.worker = None
        self._scan_thread = None
        self._auto_scanned = False
        self._applied_setup = None
        self._series = []
        self._curves = {}

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGIN)
        root.setSpacing(PAGE_SPACING)

        title = QtWidgets.QLabel("Dalga yakalama")
        title.setProperty("h1", True)
        subtitle = QtWidgets.QLabel(
            "Tetiklemede açık kanalları okur, ortak zaman eksenli CSV ve "
            "cihaz ekranının PNG kopyasını kaydeder.")
        subtitle.setProperty("hint", True)
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        # Only the settings boxes scroll; the plot and list stay outside.
        # Making the whole page scrollable let the plot stretch without
        # limit and pushed it below the fold in an 880px window. Placing the
        # boxes side by side was tried too: two four-column grids don't fit
        # and force horizontal scrolling, which is worse than vertical.
        settings_scroll = QtWidgets.QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        settings_scroll.setMaximumHeight(252)

        holder = QtWidgets.QWidget()
        hlay = QtWidgets.QVBoxLayout(holder)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(7)
        hlay.addWidget(self._settings_box())
        hlay.addWidget(self._chain_box())
        settings_scroll.setWidget(holder)

        root.addWidget(settings_scroll)
        root.addLayout(self._buttons())

        split = QtWidgets.QSplitter(Qt.Vertical)
        split.addWidget(self._plot_box())
        split.addWidget(self._table_box())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        # A stretch factor alone isn't enough: the plot swallowed the whole
        # area and the list showed nothing but the last capture. Initial
        # sizes are given explicitly; the user can drag the splitter after.
        split.setSizes([460, 220])
        # Minimum heights are deliberately low: higher values grow the
        # window itself and it no longer fits the 1366x768 lab screen.
        self.table.setMinimumHeight(110)
        self.plot.setMinimumHeight(180)
        root.addWidget(split, 1)

        self.status_label = QtWidgets.QLabel("Hazır.")
        self.status_label.setProperty("hint", True)
        # Line wrap + shrinkable size policy: a non-wrapping QLabel's minimum
        # width equals its full text, and the longest status message was
        # setting the page's minimum width (1428 px). The lab screen is
        # 1366 px, so the window didn't fit and horizontal scrolling appeared.
        self.status_label.setWordWrap(True)
        self.status_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                                        QtWidgets.QSizePolicy.Preferred)
        self.status_label.setMinimumWidth(200)
        root.addWidget(self.status_label)

        self._reload_instruments()
        self._reload_duts()
        self._on_mode_changed()
        self._update_buttons()

    def _settings_box(self):
        box = QtWidgets.QGroupBox("Yakalama ayarları")
        grid = QtWidgets.QGridLayout(box)
        grid.setHorizontalSpacing(12)

        self.mode_combo = QtWidgets.QComboBox()
        for mode in testmodes.MODES:
            self.mode_combo.addItem(mode.label, mode.key)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        self.mode_hint = QtWidgets.QLabel("")
        self.mode_hint.setProperty("hint", True)
        self.mode_hint.setWordWrap(True)

        self.instrument_combo = QtWidgets.QComboBox()
        self.instrument_combo.currentIndexChanged.connect(self._on_instrument_changed)

        self.address_edit = QtWidgets.QLineEdit()
        # Short placeholder, long example in the tooltip: placeholder text
        # sets the field's minimum width, and the full VISA address forced
        # the window to 1464 px.
        self.address_edit.setPlaceholderText("USB0::…::INSTR")
        self.address_edit.setToolTip(
            "Örnek: USB0::0x2A8D::0x1797::CN00000000::INSTR\n"
            "Boş bırakılırsa veya 'Otomatik bul' butonuna basılırsa otomatik taranır.")

        self.scan_addr_btn = QtWidgets.QPushButton("Otomatik bul")
        self.scan_addr_btn.setToolTip(
            "Bağlı VISA osiloskoplarını tarar ve adresi otomatik doldurur.")
        self.scan_addr_btn.clicked.connect(self._scan_address)

        addr_row = QtWidgets.QHBoxLayout()
        addr_row.addWidget(self.address_edit, 1)
        addr_row.addWidget(self.scan_addr_btn)

        self.ch1_chk = QtWidgets.QCheckBox("Kanal 1")
        self.ch1_chk.setChecked(True)
        self.ch2_chk = QtWidgets.QCheckBox("Kanal 2")
        chan_row = QtWidgets.QHBoxLayout()
        chan_row.addWidget(self.ch1_chk)
        chan_row.addWidget(self.ch2_chk)
        self.auto_chan_chk = QtWidgets.QCheckBox("Ekranda açık olanları kullan")
        self.auto_chan_chk.setChecked(True)
        self.auto_chan_chk.setToolTip(
            "Bağlanıldığında osiloskopta görünen kanallar otomatik seçilir.")
        self.auto_chan_chk.toggled.connect(
            lambda on: [w.setEnabled(not on) for w in (self.ch1_chk, self.ch2_chk)])
        chan_row.addWidget(self.auto_chan_chk)
        chan_row.addStretch(1)
        self.ch1_chk.setEnabled(False)
        self.ch2_chk.setEnabled(False)

        self.points_spin = QtWidgets.QSpinBox()
        self.points_spin.setRange(0, 2000000)
        self.points_spin.setSingleStep(1000)
        self.points_spin.setValue(2000)
        self.points_spin.setSpecialValueText("cihaz varsayılanı")
        self.points_spin.setToolTip(
            "Kanal başına nokta sayısı. Az nokta = hızlı aktarım.")

        self.count_spin = QtWidgets.QSpinBox()
        self.count_spin.setRange(0, 100000)
        self.count_spin.setValue(0)
        self.count_spin.setSpecialValueText("sınırsız")
        self.count_spin.setToolTip(
            "Kaç tetikleme yakalanacak. 10 yazıp başlatırsanız cihaz her "
            "şoktan sonra kendini yeniden silahlandırır; 10 ayrı CSV, 10 "
            "ekran görüntüsü ve seri sonunda enerji/tepe dağılımı çıkar.")

        self.series10_btn = QtWidgets.QToolButton()
        self.series10_btn.setText("10×")
        self.series10_btn.setToolTip(
            "Seriyi 10 ölçüme ayarlar — tekrarlanabilirlik için.")
        self.series10_btn.clicked.connect(lambda: self.count_spin.setValue(10))
        count_row = QtWidgets.QHBoxLayout()
        count_row.addWidget(self.count_spin, 1)
        count_row.addWidget(self.series10_btn)

        self.timeout_spin = QtWidgets.QSpinBox()
        self.timeout_spin.setRange(0, 3600)
        self.timeout_spin.setValue(30)
        self.timeout_spin.setSuffix(" s")
        self.timeout_spin.setSpecialValueText("beklemeye devam")
        self.timeout_spin.setToolTip(
            "Bu süre içinde tetikleme gelmezse uyarır ve beklemeyi yeniler.")

        self.shot_delay_spin = QtWidgets.QDoubleSpinBox()
        self.shot_delay_spin.setRange(0.0, 10.0)
        self.shot_delay_spin.setDecimals(1)
        self.shot_delay_spin.setSingleStep(0.1)
        self.shot_delay_spin.setValue(WaveformWorker.DEFAULT_SHOT_DELAY_S)
        self.shot_delay_spin.setSuffix(" s")
        self.shot_delay_spin.setToolTip(
            "Tetikleme ile ekran görüntüsü arasındaki bekleme.\n\n"
            "Cihaz edinimi bitirdiğini bildirdiğinde ekranı henüz çizmemiş "
            "olabiliyor; hemen istenen görüntü boş geliyor. Görüntü hâlâ boş "
            "geliyorsa bu değeri artırın.")

        self.dut_combo = QtWidgets.QComboBox()
        self.dut_combo.setToolTip(
            "Yakalamayı kalibre edilen bir cihaza bağlar — cihaz defterinde "
            "birlikte görünürler.")

        # Placed here rather than in the test mode: being able to enter the
        # energy once and still see it while switching modes beats having
        # to open the 'measurement chain' box every time.
        self.nominal_spin = QtWidgets.QDoubleSpinBox()
        self.nominal_spin.setRange(0.0, 1000.0)
        self.nominal_spin.setDecimals(1)
        self.nominal_spin.setValue(0.0)
        self.nominal_spin.setSuffix(" J")
        self.nominal_spin.setSpecialValueText("girilmedi")
        self.nominal_spin.setToolTip(
            "Defibrilatörde ayarlanan (seçilen) enerji.\n\n"
            "Uygunluk kararı bu değere göre veriliyor: IEC 60601-2-4 "
            "toleransı ayarın %15'i ya da 4 J — hangisi büyükse.\n"
            "Boş bırakılırsa seri raporu yalnızca ölçülen değerleri bildirir, "
            "uygun/uygun değil kararı vermez.\n\n"
            "'Ayarları otomatik uygula' işaretliyken bu değer değiştikçe "
            "dikey ölçek buna göre kabaca tahmin edilip yazılır.")
        self.nominal_spin.valueChanged.connect(self._on_energy_changed)

        self.auto_apply_chk = QtWidgets.QCheckBox("Ayarları otomatik uygula")
        self.auto_apply_chk.setToolTip(
            "İşaretliyken 'Ayarlanan enerji' değiştikçe dikey ölçek "
            "(V/bölme) buna göre yeniden hesaplanıp yazılır.\n\n"
            "Kaba bir başlangıç tahminidir — kırpılmayı önlemek için "
            "bilerek gevşek bırakılır. Yakalamadan önce gözden geçirip "
            "gerekirse elle inceltin.")
        # Checked by default: most operators turned it on anyway, and
        # leaving it off meant one extra click per measurement.
        self.auto_apply_chk.setChecked(True)
        self.auto_apply_chk.toggled.connect(self._on_auto_apply_toggled)

        nominal_row = QtWidgets.QHBoxLayout()
        nominal_row.addWidget(self.nominal_spin, 1)
        nominal_row.addWidget(self.auto_apply_chk)

        self.outdir_edit = QtWidgets.QLineEdit()
        self.outdir_edit.setReadOnly(True)
        browse = QtWidgets.QPushButton("Değiştir…")
        browse.clicked.connect(self._choose_dir)
        dir_row = QtWidgets.QHBoxLayout()
        dir_row.addWidget(self.outdir_edit, 1)
        dir_row.addWidget(browse)

        # Two label-field pairs (four columns). Three pairs were tried, but
        # the page's minimum width grew to 1464 px, requiring horizontal
        # scrolling on the 1366 px lab screen, which is worse than vertical.
        grid.addWidget(QtWidgets.QLabel("Test modu"), 0, 0)
        grid.addWidget(self.mode_combo, 0, 1)
        grid.addWidget(self.mode_hint, 0, 2, 1, 2)

        grid.addWidget(QtWidgets.QLabel("Osiloskop"), 1, 0)
        grid.addWidget(self.instrument_combo, 1, 1)
        grid.addWidget(QtWidgets.QLabel("VISA adresi"), 1, 2)
        grid.addLayout(addr_row, 1, 3)

        grid.addWidget(QtWidgets.QLabel("Kanallar"), 2, 0)
        grid.addLayout(chan_row, 2, 1, 1, 3)

        grid.addWidget(QtWidgets.QLabel("Nokta / kanal"), 3, 0)
        grid.addWidget(self.points_spin, 3, 1)
        grid.addWidget(QtWidgets.QLabel("Ölçüm sayısı (seri)"), 3, 2)
        grid.addLayout(count_row, 3, 3)

        grid.addWidget(QtWidgets.QLabel("Tetikleme zaman aşımı"), 4, 0)
        grid.addWidget(self.timeout_spin, 4, 1)
        grid.addWidget(QtWidgets.QLabel("Ekran görüntüsü gecikmesi"), 4, 2)
        grid.addWidget(self.shot_delay_spin, 4, 3)

        grid.addWidget(QtWidgets.QLabel("Kalibre edilen cihaz"), 5, 0)
        grid.addWidget(self.dut_combo, 5, 1)
        grid.addWidget(QtWidgets.QLabel("Ayarlanan enerji"), 5, 2)
        grid.addLayout(nominal_row, 5, 3)

        grid.addWidget(QtWidgets.QLabel("Klasör"), 6, 0)
        grid.addLayout(dir_row, 6, 1, 1, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        return box

    def _chain_box(self):
        """Measurement chain and instrument scales — only visible in test mode."""
        self.chain_box = QtWidgets.QGroupBox("Ölçüm zinciri ve cihaz ölçekleri")
        grid = QtWidgets.QGridLayout(self.chain_box)
        grid.setHorizontalSpacing(12)

        self.divider_spin = QtWidgets.QDoubleSpinBox()
        self.divider_spin.setRange(1.0, 100000.0)
        self.divider_spin.setDecimals(1)
        # The lab's defibrillator setup uses a 1:1000 divider; make the most
        # common value the default so it doesn't need entering every time.
        self.divider_spin.setValue(1000.0)
        self.divider_spin.setPrefix("1 : ")
        self.divider_spin.setToolTip(
            "Yüksek gerilim bölücünün oranı.\n\n"
            "Bu sayı cihaza **prob zayıflatması** olarak da bildirilir: "
            "dikey ölçek sınırı prob oranına bağlı olduğu için 1:1'de "
            "50 V/bölme isteği -222 'Data out of range' ile reddedilir.\n"
            "Bildirim yapıldığında cihaz zaten gerçek gerilimi döndürür, "
            "uygulama üstüne bir kez daha çarpmaz.")
        self.divider_spin.valueChanged.connect(self._update_span_hint)

        self.load_spin = QtWidgets.QDoubleSpinBox()
        self.load_spin.setRange(1.0, 10000.0)
        self.load_spin.setDecimals(2)
        self.load_spin.setValue(50.0)
        self.load_spin.setSuffix(" Ω")
        self.load_spin.setToolTip(
            "Şokun verildiği yük direnci. Enerji hesabı E = ∫v²/R dt bu "
            "değere doğrudan bağlı.")
        # The load resistance also feeds the energy-to-vertical-scale
        # estimate (E ≈ Vpeak²·T/R); when auto-apply is on, a change here
        # must trigger a recalculation too.
        self.load_spin.valueChanged.connect(self._on_energy_changed)

        self.vdiv_spin = QtWidgets.QDoubleSpinBox()
        # Upper bound is 2000, not 1000: the energy-based auto-scale
        # estimate can exceed 1000 at high Joule values (e.g. 300 J / 50 Ω
        # is right at ~1000 V/div), and real defibrillator output can reach
        # up to 5 kV (see defib.py). At a lower limit the value would be
        # silently clipped, invalidating the estimate.
        self.vdiv_spin.setRange(0.001, 2000.0)
        self.vdiv_spin.setDecimals(3)
        self.vdiv_spin.setValue(50.0)
        self.vdiv_spin.setSuffix(" V/böl")
        self.vdiv_spin.valueChanged.connect(self._update_span_hint)

        self.tdiv_spin = QtWidgets.QDoubleSpinBox()
        self.tdiv_spin.setRange(0.000001, 10.0)
        self.tdiv_spin.setDecimals(6)
        self.tdiv_spin.setValue(0.005)
        self.tdiv_spin.setSuffix(" s/böl")

        self.trig_spin = QtWidgets.QDoubleSpinBox()
        self.trig_spin.setRange(-1000.0, 1000.0)
        self.trig_spin.setDecimals(3)
        self.trig_spin.setValue(5.0)
        self.trig_spin.setSuffix(" V")
        self.trig_spin.setToolTip(
            "Tetikleme eşiği — bölücü **öncesindeki** gerçek gerilime göre.\n"
            "Bölücü oranı cihaza prob zayıflatması olarak bildirildiği için "
            "cihaz da eşiği bu ölçekte yorumlar.\n"
            "Eşiğin ekran aralığının içinde kalması gerekir, yoksa cihaz hiç "
            "tetiklenmez.")
        self.trig_spin.valueChanged.connect(self._update_span_hint)

        self.slope_combo = QtWidgets.QComboBox()
        self.slope_combo.addItem("Yükselen kenar", "POSitive")
        self.slope_combo.addItem("Düşen kenar", "NEGative")

        self.delay_spin = QtWidgets.QDoubleSpinBox()
        self.delay_spin.setRange(-1.0, 1.0)
        self.delay_spin.setDecimals(4)
        # Default 0: the trigger sits dead center on screen. Mode
        # suggestions may differ, but the field always starts at 0 and is
        # changed by hand — it isn't overwritten when the mode changes.
        self.delay_spin.setValue(0.0)
        self.delay_spin.setSuffix(" s")
        self.delay_spin.setToolTip(
            "Zaman konumu (:TIMebase:POSition) — tetikleme anının ekrandaki "
            "yatay konumu. Pozitif değer tetiklemeyi sağa, negatif sola "
            "kaydırır. 0: tam ortada.")

        self.apply_setup_btn = QtWidgets.QPushButton("Ölçekleri cihaza uygula")
        self.apply_setup_btn.clicked.connect(self._apply_setup)
        self.apply_setup_btn.setToolTip(
            "Yukarıdaki ölçek ve tetikleme değerlerini osiloskoba yazar ve "
            "cihazı taramaya (AUTO süpürme) geri alır — sinyal ekranda kalır.")

        self.autoscale_btn = QtWidgets.QPushButton("Otomatik ölçekle")
        self.autoscale_btn.clicked.connect(self._autoscale)
        self.autoscale_btn.setToolTip(
            "Cihazın ön panelindeki Auto Scale ile aynı: sinyali bulup "
            "ekrana oturtur. Bulunan ölçek yukarıdaki alanlara yazılır.")

        self.span_hint = QtWidgets.QLabel("")
        self.span_hint.setProperty("hint", True)
        self.span_hint.setWordWrap(True)

        # Three column pairs: the box fits in two rows. A four-row layout
        # grew the window to 1156 px, which didn't fit the lab screen.
        grid.addWidget(QtWidgets.QLabel("Bölücü oranı"), 0, 0)
        grid.addWidget(self.divider_spin, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Yük direnci"), 0, 2)
        grid.addWidget(self.load_spin, 0, 3)
        grid.addWidget(QtWidgets.QLabel("Dikey ölçek"), 1, 0)
        grid.addWidget(self.vdiv_spin, 1, 1)
        grid.addWidget(QtWidgets.QLabel("Zaman tabanı"), 1, 2)
        grid.addWidget(self.tdiv_spin, 1, 3)
        grid.addWidget(QtWidgets.QLabel("Tetikleme eşiği"), 2, 0)
        grid.addWidget(self.trig_spin, 2, 1)
        grid.addWidget(QtWidgets.QLabel("Kenar"), 2, 2)
        grid.addWidget(self.slope_combo, 2, 3)
        grid.addWidget(QtWidgets.QLabel("Zaman konumu (gecikme)"), 3, 0)
        grid.addWidget(self.delay_spin, 3, 1)
        grid.addWidget(self.span_hint, 4, 0, 1, 2)
        setup_row = QtWidgets.QHBoxLayout()
        setup_row.addStretch(1)
        setup_row.addWidget(self.autoscale_btn)
        setup_row.addWidget(self.apply_setup_btn)
        grid.addLayout(setup_row, 4, 2, 1, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self.chain_box.setVisible(False)
        self._update_span_hint()
        return self.chain_box

    def apply_plot_theme(self):
        import pyqtgraph as pg

        c = theme.colors()
        self.plot.setBackground(QtGui.QColor(c["surface"]))
        for name in ("left", "bottom"):
            axis = self.plot.getAxis(name)
            axis.setPen(pg.mkPen(c["border_strong"]))
            axis.setTextPen(pg.mkPen(c["text_muted"]))
        self.plot.showGrid(x=True, y=True, alpha=c["grid"])
        self._trigger_line.setPen(pg.mkPen(c["guide"], width=1, style=Qt.DashLine))
        for i, curve in enumerate(self._curves.values()):
            curve.setPen(pg.mkPen(c["curve"] if i == 0 else c["warn"], width=1.4))

    def current_mode(self):
        return testmodes.get(self.mode_combo.currentData())

    def showEvent(self, event):
        self._reload_duts()
        self.reload()
        QtWidgets.QWidget.showEvent(self, event)
        # If the address is empty the first time the page opens, it is
        # auto-scanned once. The delay keeps the scan from starting before
        # the window is drawn: the scan can take seconds, and waiting on a
        # blank window looks like it "didn't open". Not repeated on every
        # open — the address is written to inventory once found and isn't
        # needed again.
        if not self._auto_scanned:
            self._auto_scanned = True
            QtCore.QTimer.singleShot(150, self._auto_scan_if_needed)

    def reload(self):
        inst = self._current_instrument()
        instrument_id = (inst["id"] if inst is not None
                         and self.only_mine_chk.isChecked() else None)
        rows = waveform.list_captures(instrument_id=instrument_id, limit=300)

        # Preserve the selection: generating a report refreshes the list,
        # and losing the selection would force the user to relocate the
        # row they were just looking at.
        previous = self._selected_capture()
        previous_id = previous["id"] if previous is not None else None

        c = theme.colors()
        self.table.setRowCount(0)
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            state, _msg = waveform.verify(r["id"])
            state_tr = {"ok": "dosya yerinde", "missing": "DOSYA YOK",
                        "changed": "DEĞİŞMİŞ", "unknown": "bilinmiyor"}[state]
            dt = r["sample_interval_s"]
            if r["series_id"]:
                series_cell = "%s/%s" % (r["series_index"] or "?",
                                         r["series_size"] or "?")
            else:
                series_cell = "—"
            cells = [str(r["trigger_no"] or r["id"]),
                     (r["captured_at"] or "").replace("T", " ")[:19],
                     "%s %s" % (r["inst_brand"] or "", r["inst_model"] or ""),
                     (r["channels"] or "").replace("_V", ""),
                     str(r["points"] or "—"),
                     _si(dt, "s"),
                     series_cell,
                     os.path.basename(r["file_path"]),
                     r["report_no"] or "—",
                     state_tr]
            for col, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(str(text))
                if col == 0:
                    item.setData(Qt.UserRole, r["id"])
                if col == 6 and r["series_id"]:
                    item.setToolTip("Seri anahtarı: %s" % r["series_id"])
                if col == 9 and state != "ok":
                    item.setForeground(QtGui.QColor(c["bad"]))
                if r["is_simulated"] and col == 2:
                    item.setForeground(QtGui.QColor(c["warn"]))
                self.table.setItem(i, col, item)
        fit_table(self.table, stretch_column=7)
        empty_state(self.table,
                    "Henüz yakalama yok. Osiloskobu bağlayıp\n"
                    "'Yakalamayı başlat' ile tetikleme bekleyin.")

        restored = False
        if previous_id is not None:
            for i in range(self.table.rowCount()):
                if self.table.item(i, 0).data(Qt.UserRole) == previous_id:
                    self.table.selectRow(i)
                    restored = True
                    break
        # If nothing is selected, the newest capture is selected. Otherwise
        # even with a full list the "Shock report / Show in plot / Open
        # CSV" buttons below stay disabled, and the user doesn't know they
        # need to click a row first.
        if not restored and self.table.rowCount():
            self.table.selectRow(0)
        self._on_capture_selected()

    def shutdown(self):
        """Called when the window closes — so the worker thread isn't left hanging."""
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(3000)
