"""Ortak sayfa iskeleti: sabit araç çubuğu + daraltılabilir ayar paneli + veri alanı.

Önceki yerleşimde her sayfa kendi ayar kutularını (`QGroupBox`) ve veri
alanını (grafik/tablo) tek bir dikey `QVBoxLayout` içinde üst üste diziyordu;
pencere küçüldüğünde ayarlar veri alanını (osiloskop ekranı, sonuç
tabloları) aşağı itiyor ya da sıkıştırıyordu. `PageShell` üç sabit bölge
tanımlar:

* **Bölge A** — 52 px sabit araç çubuğu: başlık/alt başlık, durum çipi,
  eylem düğmeleri (Başlat/Durdur/Kaydet/...), sağda ayar panelini
  daraltma düğmesi. Asla kaydırılmaz.
* **Bölge B** — 300 px genişliğinde daraltılabilir ayar paneli
  (`QScrollArea` içinde dikey bir yığın). Sayfalar kendi `QGroupBox`
  kutularını (örn. mevcut `_instrument_box()`) hiç değiştirmeden
  `add_settings_widget()` ile buraya taşır. Daraltıldığında 30 px'lik
  dikey bir "Ayarlar ›" şeridine iner; açık/kapalı durumu sayfa anahtarına
  göre kalıcı olarak saklanır.
* **Bölge C** — kalan tüm alanı kaplayan veri bölgesi (`stretch=1`).
  Sayfa burada kendi grafiğini/tablosunu/`QSplitter`'ını `set_content()`
  ile yerleştirir.

Bu sınıf yalnızca yerleşimi standartlaştırır; sayfaların iş mantığı,
sinyal bağlantıları ve veri erişimi değişmeden kalır.
"""

from .. import prefs
from ..qt import Qt, QtCore, QtGui, QtWidgets

#: Ayar paneli her zaman bu genişlikte açılır. Etiketler artık sarmalı
#: (`field_label`) olduğu için sütun genişliğini asıl belirleyen alan
#: tarafı: geniş onay kutusu metinleri ve yan yana kontrol çiftleri.
#: 420 px bunların hepsini yatay kaydırma olmadan barındırıyor.
PANEL_WIDTH = 480
#: Daraltılmış panelin dikey "Ayarlar ›" şeridi genişliği.
RAIL_WIDTH = 30


def field_label(text):
    """Ayar paneli satırları için etiket — `add_settings_widget()` ile
    taşınan `QGroupBox` ızgaralarında kullanılır.

    Sarmalama (`setWordWrap`) burada kozmetik değil, zorunlu: panel sabit
    ve dar (bkz. `PANEL_WIDTH`); "Ekran görüntüsü gecikmesi" gibi uzun bir
    etiket sarmalanmazsa tek satırda 300 px talep edip alanı sıkıştırıyor,
    panel de bunu daraltamayacağı için içerik panelin dışına taşıyor.
    Sarmalı etiket iki satıra bölünüp aynı genişlikte kalabiliyor.
    """
    label = QtWidgets.QLabel(text)
    label.setObjectName("FieldLabel")
    label.setWordWrap(True)
    return label


class _ElidingLabel(QtWidgets.QLabel):
    """Sarmalanmayan bir `QLabel`in tam metin genişliği, `Ignored` politikasına
    rağmen `minimumSizeHint()` üzerinden düzenin minimum genişliğini
    belirliyordu (52 px'lik araç çubuğunda uzun bir alt başlık sayfayı
    1000+ piksel genişlemeye zorluyordu — bkz. nav.py'deki `_elide_name`
    ile aynı sorun). Bu sınıf metni her yeniden boyutlandırmada mevcut
    genişliğe göre kırpıp "…" ekliyor; tam metin araç ipucunda duruyor.
    """

    def __init__(self, parent=None):
        QtWidgets.QLabel.__init__(self, parent)
        self._full_text = ""

    def setFullText(self, text):
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._elide()

    def minimumSizeHint(self):
        hint = QtWidgets.QLabel.minimumSizeHint(self)
        return QtCore.QSize(0, hint.height())

    def resizeEvent(self, event):
        QtWidgets.QLabel.resizeEvent(self, event)
        self._elide()

    def _elide(self):
        metrics = QtGui.QFontMetrics(self.font())
        elided = metrics.elidedText(self._full_text, Qt.ElideRight, self.width())
        QtWidgets.QLabel.setText(self, elided)


class PageShell(QtWidgets.QWidget):
    """A/B/C bölgelerini kuran taban widget. Sayfalar bunu miras alır."""

    settingsToggled = QtCore.Signal(bool)

    def __init__(self, panel_key, parent=None, with_settings_panel=True):
        QtWidgets.QWidget.__init__(self, parent)
        self._panel_key = panel_key
        self._panel_open = True
        self._has_panel = with_settings_panel

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_toolbar())

        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)

        if self._has_panel:
            self._panel = self._build_settings_panel()
            self._rail = self._build_settings_rail()
            body.addWidget(self._panel)
            body.addWidget(self._rail)

        self._content_host = QtWidgets.QWidget()
        self._content_layout = QtWidgets.QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self._content_host, 1)

        if self._has_panel:
            opened = prefs.get(None, self._pref_key(), "1") != "0"
            self.set_settings_open(opened, persist=False)

    # ---- Bölge A: araç çubuğu ---------------------------------------------
    def _build_toolbar(self):
        bar = QtWidgets.QFrame()
        bar.setObjectName("PageToolBar")
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(14)

        # Ayar panelini aç/kapatan düğme en solda — panel de solda olduğu
        # için elin gideceği yer orası, sağ uçtaki eylem düğmelerinin
        # arasında aranmaması gerekiyor.
        self.panel_toggle = QtWidgets.QToolButton()
        self.panel_toggle.setObjectName("PanelToggle")
        self.panel_toggle.setCursor(Qt.PointingHandCursor)
        self.panel_toggle.setText("☰")
        self.panel_toggle.setToolTip("Ayar panelini aç / kapat")
        self.panel_toggle.clicked.connect(
            lambda: self.set_settings_open(not self._panel_open))
        self.panel_toggle.setVisible(self._has_panel)
        lay.addWidget(self.panel_toggle)

        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(0)
        self.title_label = QtWidgets.QLabel()
        self.title_label.setObjectName("PageTitle")
        # Alt başlık tek satıra sığmayan uzun bir açıklama olabilir; 52 px'lik
        # araç çubuğunda sarmak (wrap) yer açmaz. `_ElidingLabel` metni mevcut
        # genişliğe göre "…" ile kırpar, tam metin araç ipucunda kalır — aksi
        # halde sarmalanmayan QLabel'in tam metin genişliği sayfanın minimum
        # genişliğini belirliyordu (bkz. nav.py'deki `_elide_name`).
        self.subtitle_label = _ElidingLabel()
        self.subtitle_label.setObjectName("PageSubtitle")
        self.subtitle_label.setVisible(False)
        title_col.addWidget(self.title_label)
        title_col.addWidget(self.subtitle_label)
        lay.addLayout(title_col)

        self.status_chip = QtWidgets.QFrame()
        self.status_chip.setObjectName("StatusChip")
        self.status_chip.setVisible(False)
        chip_lay = QtWidgets.QHBoxLayout(self.status_chip)
        # Dikey dolgu düğmelerle (QPushButton: padding 5px 12px) aynı satır
        # yüksekliğini vermek için kasıtlı olarak eşitlendi — Bölge A'da
        # rozet ve eylem düğmeleri yan yana aynı yükseklikte durmalı.
        chip_lay.setContentsMargins(10, 6, 10, 6)
        chip_lay.setSpacing(6)
        self._status_dot = QtWidgets.QLabel()
        self._status_dot.setObjectName("StatusChipDot")
        self._status_dot.setFixedSize(8, 8)
        self._status_text = QtWidgets.QLabel()
        self._status_text.setObjectName("StatusChipText")
        chip_lay.addWidget(self._status_dot)
        chip_lay.addWidget(self._status_text)
        lay.addWidget(self.status_chip)

        lay.addStretch(1)

        self.action_row = QtWidgets.QHBoxLayout()
        self.action_row.setSpacing(7)
        lay.addLayout(self.action_row)
        return bar

    def set_title(self, title, subtitle=""):
        self.title_label.setText(title)
        self.subtitle_label.setFullText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))

    def set_status(self, text, state="idle"):
        """`state`: 'ok' | 'warn' | 'bad' | 'idle'. Boş metin çipi gizler."""
        self.status_chip.setVisible(bool(text))
        self._status_text.setText(text or "")
        self._status_dot.setProperty("state", state)
        self._repolish(self._status_dot)

    def add_action(self, text, slot=None, primary=False, danger=False):
        """Bölge A'nın sağına bir eylem düğmesi ekler ve döndürür."""
        btn = QtWidgets.QPushButton(text)
        if primary:
            btn.setProperty("primary", True)
        if danger:
            btn.setProperty("danger", True)
        if slot is not None:
            btn.clicked.connect(slot)
        self.action_row.addWidget(btn)
        return btn

    def add_action_separator(self):
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.VLine)
        line.setFixedHeight(20)
        self.action_row.addWidget(line)

    # ---- Bölge B: ayar paneli ----------------------------------------------
    def _build_settings_panel(self):
        panel = QtWidgets.QFrame()
        panel.setObjectName("SettingsPanel")
        panel.setFixedWidth(PANEL_WIDTH)
        outer = QtWidgets.QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QtWidgets.QFrame()
        head.setObjectName("SettingsPanelHead")
        hl = QtWidgets.QHBoxLayout(head)
        hl.setContentsMargins(13, 8, 6, 8)
        cap = QtWidgets.QLabel("AYARLAR")
        cap.setObjectName("SettingsRailLabel")
        hl.addWidget(cap)
        hl.addStretch(1)
        collapse = QtWidgets.QToolButton()
        collapse.setObjectName("PanelCollapse")
        collapse.setText("‹")
        collapse.setCursor(Qt.PointingHandCursor)
        collapse.setToolTip("Ayar panelini kapat")
        collapse.clicked.connect(lambda: self.set_settings_open(False))
        hl.addWidget(collapse)
        outer.addWidget(head)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        # Panel genişliği sabit; içerik hep tek sütun (etiket + alan) olacak
        # şekilde kuruluyor, o yüzden yatay kaydırma hiç gerekmiyor — çıkarsa
        # bu bir tasarım hatasıdır, sessizce kaydırmaya izin vermek yerine
        # kapalı tutup fark edilmesini sağlıyoruz.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QtWidgets.QWidget()
        self.settings_layout = QtWidgets.QVBoxLayout(body)
        self.settings_layout.setContentsMargins(12, 10, 12, 14)
        self.settings_layout.setSpacing(11)
        self.settings_layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        return panel

    def _build_settings_rail(self):
        rail = QtWidgets.QFrame()
        rail.setObjectName("SettingsRail")
        rail.setFixedWidth(RAIL_WIDTH)
        rail.setCursor(Qt.PointingHandCursor)
        rail.setVisible(False)
        lay = QtWidgets.QVBoxLayout(rail)
        lay.setContentsMargins(2, 10, 2, 10)
        label = QtWidgets.QLabel("AYARLAR ›")
        label.setObjectName("SettingsRailLabel")
        label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        label.setWordWrap(True)
        lay.addWidget(label)
        lay.addStretch(1)

        def _open(_event):
            self.set_settings_open(True)

        rail.mousePressEvent = _open
        return rail

    def add_settings_widget(self, widget):
        """Var olan bir `QGroupBox` (vb.) widget'ını Bölge B'ye taşır.

        Sayfaların kendi `_xxx_box()` fabrika metotları hiç değişmeden
        kullanılabilsin diye widget üretimi çağıran tarafta kalır — bu
        yalnızca onu ayar paneline yerleştirir.
        """
        self.settings_layout.insertWidget(self.settings_layout.count() - 1, widget)
        return widget

    def add_settings_layout(self, layout):
        self.settings_layout.insertLayout(self.settings_layout.count() - 1, layout)

    def set_settings_open(self, open_, persist=True):
        if not self._has_panel:
            return
        self._panel_open = open_
        self._panel.setVisible(open_)
        self._rail.setVisible(not open_)
        self.panel_toggle.setToolTip(
            "Ayar panelini kapat" if open_ else "Ayar panelini aç")
        if persist:
            prefs.set(None, self._pref_key(), "1" if open_ else "0")
        self.settingsToggled.emit(open_)

    def settings_open(self):
        return self._panel_open

    def _pref_key(self):
        return "panel_open_%s" % self._panel_key

    # ---- Bölge C: veri alanı -----------------------------------------------
    def set_content(self, widget):
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self._content_layout.addWidget(widget)

    def content_layout(self):
        """Doğrudan düzen eklemek isteyen sayfalar için (`set_content` yerine)."""
        return self._content_layout

    @staticmethod
    def _repolish(widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)
