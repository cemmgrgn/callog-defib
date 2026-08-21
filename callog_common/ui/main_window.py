"""Shared main window: left navigation rail + role-pruned menu.

This is the base both CalLog apps (`callog_defib`, `callog_seshizi`) build
their own `MainWindow` on top of. Everything that doesn't depend on which
app is running lives here: home screen, devices, sessions, measurement,
approvals, history, admin, theme/font/language, backup, search, shortcuts.

The one page that differs between apps (defib's waveform capture vs.
seshizi's velocity page) is added through a small set of override points
instead of being imported here — see `_build_extra_page`,
`_extra_page_meta`, `_extra_page_available`, `_refresh_extra_appearance`,
`_shutdown_extra`, `_operator_guides`. A subclass overrides only what it
needs; the base implementation is a no-op / empty list, so a window with
no extra page still works.

Role rules aren't defined here but in the `perms` module. This file only
says "don't add the page at all if unauthorized"; see `callog_common/perms.py`
to read which role can see what from a single place.

An unauthorized page **isn't added**, not grayed out: a closed door
constantly reminds the user of something they can't access and generates
support calls.
"""

import os

from .. import audit, backup, branding, db, drivers, i18n, notifications, perms, theme
from ..i18n import t
from ..qt import QT_BINDING, Qt, QtGui, QtWidgets, Signal
from .util import fit_table, empty_state
from .acquire_page import AcquirePage
from .admin_page import AdminPage
from .approvals_page import ApprovalsPage
from .devices_page import DevicesPage
from .history_page import HistoryPage
from .nav import NavRail
from .setup_page import SetupPage


class AppState(object):
    """State shared by pages: the logged-in user and the status bar."""

    def __init__(self, user, window):
        self.user = user
        self._window = window

    def status(self, message, msec=6000):
        self._window.statusBar().showMessage(message, msec)

    # Pages go through here instead of calling perms directly to check
    # authorization; the user row doesn't need to be re-read everywhere.
    def can(self, permission):
        return perms.can(self.user, permission)


class MainWindow(QtWidgets.QMainWindow):

    def __init__(self, user):
        QtWidgets.QMainWindow.__init__(self)
        self.setWindowTitle("%s — %s" % (self._app_title(), branding.org_name()))
        self.resize(1320, 880)

        self.state = AppState(user, self)
        # Preferences are bound to the user and the theme is reapplied:
        # the login screen opened with the machine's setting, this user's
        # own theme and font size only apply once we know who they are.
        theme.bind_user(user["id"])
        i18n.load(user["id"])
        app = QtWidgets.QApplication.instance()
        if app is not None:
            theme.apply(app)

        self.tabs = NavRail(user)
        self.setCentralWidget(self.tabs)

        self.home = HomePage(self.state)
        self.devices = DevicesPage(self.state)
        self.setup = SetupPage(self.state)
        self.acquire = AcquirePage(self.state)
        self.history = HistoryPage(self.state)
        self._extra = (self._build_extra_page()
                       if self._extra_page_available()
                       and self.state.can(self._extra_page_permission())
                       else None)
        # The approval queue is only for approvers: an operator can't act
        # on that queue, so seeing the page would only cause anxiety.
        self.approvals = (ApprovalsPage(self.state)
                          if self.state.can(perms.CERT_APPROVE) else None)
        self.admin = AdminPage(self.state) if self.state.can(perms.VIEW_ADMIN) else None

        self.tabs.add_page("home", self.home, t("Ana ekran"), "home")
        self.tabs.add_page("devices", self.devices, t("Cihazlar"), "devices")
        self.tabs.add_page("setup", self.setup, t("Yeni oturum"), "new")
        self.tabs.add_page("acquire", self.acquire, t("Ölçüm"), "acquire",
                           tooltip="Bir oturum başlatıldığında etkinleşir.")
        if self._extra is not None:
            key, label, icon, tooltip = self._extra_page_meta()
            self.tabs.add_page(key, self._extra, t(label), icon, tooltip=tooltip)
        if self.approvals is not None:
            self.tabs.add_page("approvals", self.approvals, t("Onay kuyruğu"),
                               "approve",
                               tooltip="Onay bekleyen sertifikalar.")
        self.tabs.add_page("history", self.history, t("Geçmiş kayıtlar"),
                           "history")
        if self.admin is not None:
            self.tabs.add_page("admin", self.admin, t("Yönetim"), "admin")
        self.tabs.setTabEnabled(self._idx("acquire"), False)
        self.tabs.refresh_theme()

        self.tabs.theme_btn.clicked.connect(self._toggle_theme)
        self.tabs.logout_btn.clicked.connect(self.close)

        self.home.new_session.connect(lambda: self._go("setup"))
        self.home.open_history.connect(self._go_history)
        self.home.open_devices.connect(lambda: self._go("devices"))
        self.home.open_target.connect(self._go_target)
        self.devices.new_session_for.connect(self._new_session_for_dut)
        self.setup.session_started.connect(self._on_session_started)
        self.acquire.session_finished.connect(self._on_session_finished)
        if self.approvals is not None:
            self.approvals.queue_changed.connect(self.home.refresh)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._build_menu()
        self.statusBar().showMessage(
            "%s · %s" % (user["full_name"], perms.label(user["role"])))
        # Backup age is in the permanent area: transient status messages shouldn't clear it.
        self.backup_label = QtWidgets.QLabel("")
        self.statusBar().addPermanentWidget(self.backup_label)
        self._refresh_backup_label()

    # --- navigation helpers --------------------------------------------
    def _idx(self, key):
        return self.tabs.index_of(key)

    def _go(self, key):
        i = self._idx(key)
        if i >= 0:
            self.tabs.setCurrentIndex(i)

    # --- extension points for app-specific subclasses -------------------
    # Every CalLog app shares this window and adds exactly one extra page
    # (waveform capture for callog_defib, velocity for callog_seshizi).
    # The base class knows nothing about either; a subclass overrides only
    # the hooks below. Defaults are all no-ops so a window with no extra
    # page (e.g. a role without the needed permission) still works unmodified.

    def _extra_page_available(self):
        """Whether an instrument capable of this app's extra page exists."""
        return False

    def _extra_page_permission(self):
        """The `perms` constant that gates this app's extra page."""
        return None

    def _build_extra_page(self):
        """Builds and returns this app's one extra page widget."""
        return None

    def _extra_page_meta(self):
        """(nav key, label, icon name, tooltip) for the extra page's tab."""
        raise NotImplementedError

    def _extra_page_shortcut_entry(self):
        """(nav key, label) for the Ctrl+N shortcut list, or None."""
        return None

    def _refresh_extra_appearance(self):
        """Called after a theme/font change; refresh the extra page's plot colors."""

    def _shutdown_extra(self):
        """Called from closeEvent; release the extra page's driver/thread."""

    def _operator_guides(self):
        """[(menu label, pdf path, preview title), ...] for the Help menu."""
        return []

    def _app_title(self):
        """Display name for the window title and the About dialog."""
        return "CalLog"

    def _app_version_info(self):
        """(version, author) shown in the About dialog. Defaults to callog_common's."""
        from .. import __author__, __version__
        return __version__, __author__

    # --- menu bar -----------------------------------------------------
    def _build_menu(self):
        bar = self.menuBar()

        m_session = bar.addMenu("&" + t("Oturum"))
        self._act(m_session, t("Yeni kalibrasyon oturumu"), "Ctrl+N",
                  lambda: self._go("setup"))
        self.act_finish = self._act(m_session, t("Oturumu bitir"), "Ctrl+W",
                                    self._finish_session)
        self.act_finish.setEnabled(False)
        m_session.addSeparator()
        self._act(m_session, t("Ara…"), "Ctrl+K", self._open_search)
        m_session.addSeparator()
        self._act(m_session, t("Kalibre edilen cihazlar"), "Ctrl+D",
                  lambda: self._go("devices"))
        self._act(m_session, t("Geçmiş kayıtlar"), "Ctrl+H", self._go_history)
        self._act(m_session, t("Sertifikalar"), None,
                  lambda: self._go_history(sub_tab=1))
        if self.approvals is not None:
            self._act(m_session, t("Onay kuyruğu"), "Ctrl+O",
                      lambda: self._go("approvals"))
        m_session.addSeparator()
        self._act(m_session, t("Çıkış"), "Ctrl+Q", self.close)

        m_view = bar.addMenu("&" + t("Görünüm"))
        self.act_light = self._act(m_view, t("Beyaz tema"), None,
                                   lambda: self._set_theme(theme.LIGHT), check=True)
        self.act_dark = self._act(m_view, t("Koyu tema"), None,
                                  lambda: self._set_theme(theme.DARK), check=True)
        self.act_contrast = self._act(
            m_view, t("Yüksek kontrast"), None,
            lambda: self._set_theme(theme.CONTRAST), check=True)
        self.act_contrast.setToolTip(
            "Gri tonu olmayan, kalın kenarlıklı palet — küçük lab "
            "ekranlarında uzaktan okumak için.")
        group = QtGui.QActionGroup(self)
        group.addAction(self.act_light)
        group.addAction(self.act_dark)
        group.addAction(self.act_contrast)

        m_font = m_view.addMenu(t("Yazı boyutu"))
        self._font_actions = []
        font_group = QtGui.QActionGroup(self)
        for label, scale in theme.FONT_SCALES:
            action = self._act(m_font, label, None,
                               lambda checked=False, s=scale: self._set_scale(s),
                               check=True)
            font_group.addAction(action)
            self._font_actions.append((action, scale))

        m_font.addSeparator()
        # The standard key sequence is used: depending on the platform Qt
        # binds it to both "Ctrl++" and "Ctrl+=" — it works without needing
        # Shift on both Turkish and US keyboards.
        act_zoom_in = m_font.addAction(t("Yakınlaştır"))
        act_zoom_in.setShortcuts([QtGui.QKeySequence.ZoomIn,
                                  QtGui.QKeySequence("Ctrl+=")])
        act_zoom_in.triggered.connect(self._zoom_in)
        act_zoom_out = m_font.addAction(t("Uzaklaştır"))
        act_zoom_out.setShortcut(QtGui.QKeySequence.ZoomOut)
        act_zoom_out.triggered.connect(self._zoom_out)
        act_zoom_reset = m_font.addAction(t("Yazı boyutunu sıfırla (%100)"))
        act_zoom_reset.setShortcut("Ctrl+0")
        act_zoom_reset.triggered.connect(self._zoom_reset)

        m_lang = m_view.addMenu(t("Dil / Language"))
        self._lang_actions = []
        lang_group = QtGui.QActionGroup(self)
        for code, label in i18n.LANGUAGES:
            action = self._act(m_lang, label, None,
                               lambda checked=False, c=code: self._set_language(c),
                               check=True)
            lang_group.addAction(action)
            self._lang_actions.append((action, code))

        self._sync_theme_actions()
        m_view.addSeparator()
        # Shortcut numbers match the order in the rail: the counter only
        # advances for pages that were actually added. If the order from the
        # fixed list were used instead, a page missing due to role would
        # shift every following number one ahead of what's shown in the rail.
        n = 0
        shortcut_pages = [
            ("home", "Ana ekran"), ("devices", "Cihazlar"),
            ("setup", "Yeni oturum"), ("acquire", "Ölçüm"),
        ]
        extra_entry = self._extra_page_shortcut_entry()
        if extra_entry is not None:
            shortcut_pages.append(extra_entry)
        shortcut_pages += [
            ("approvals", "Onay kuyruğu"),
            ("history", "Geçmiş kayıtlar"), ("admin", "Yönetim"),
        ]
        for key, label in shortcut_pages:
            if self._idx(key) < 0:
                continue
            n += 1
            self._act(m_view, label, "Ctrl+%d" % n,
                      lambda checked=False, k=key: self._go(k))

        if self.state.can(perms.VIEW_ADMIN):
            m_admin = bar.addMenu("&" + t("Yönetim"))
            if self.state.can(perms.VIEW_USERS):
                self._act(m_admin, t("Kullanıcılar"), None,
                          lambda: self._go_admin("users"))
            self._act(m_admin, t("Referans cihazlar"), None,
                      lambda: self._go_admin("instruments"))
            self._act(m_admin, t("Yetki matrisi"), None,
                      lambda: self._go_admin("perms"))
            if self.state.can(perms.VIEW_AUDIT):
                self._act(m_admin, t("Denetim kaydı"), None,
                          lambda: self._go_admin("audit"))
                m_admin.addSeparator()
                self._act(m_admin, t("Denetim zincirini doğrula"), None,
                          self._verify_audit)
            m_admin.addSeparator()
            self._act(m_admin, t("Veritabanını yedekle"), "Ctrl+B", self._backup_now)

        m_help = bar.addMenu("&" + t("Yardım"))
        guides = self._operator_guides()
        for label, path, title in guides:
            self._act(m_help, t(label), None,
                      lambda checked=False, p=path, ti=title: self._open_guide(p, ti))
        if guides:
            m_help.addSeparator()
        self._act(m_help, t("Klavye kısayolları"), "F1", self._shortcuts)
        self._act(m_help, t("Hakkında"), None, self._about)

    def _act(self, menu, text, shortcut, slot, check=False):
        action = menu.addAction(text)
        if shortcut:
            action.setShortcut(shortcut)
        action.setCheckable(check)
        action.triggered.connect(slot)
        return action

    # --- navigation ----------------------------------------------------------
    def _go_history(self, sub_tab=None):
        self.history.reload()
        if sub_tab is not None:
            self.history.tabs.setCurrentIndex(sub_tab)
        self._go("history")

    def _go_admin(self, sub_key):
        if self.admin is None:
            return
        self._go("admin")
        self.admin.show_section(sub_key)

    def _new_session_for_dut(self, dut_id):
        """'New measurement for this device' from the Devices page."""
        self.setup.load_dut(dut_id)
        self._go("setup")

    def _open_search(self):
        from .search_dialog import SearchDialog

        dlg = SearchDialog(self)
        dlg.chosen.connect(self._open_search_hit)
        dlg.exec()

    def _open_search_hit(self, target, ident):
        """Opens a search result.

        Target names are produced in the `search` module; since this mapping
        is the single place for it, it's clear where to look when a new
        type is added.
        """
        if target == "session":
            self._go_history(sub_tab=0)
            if not self.history.focus_session(ident):
                self.state.status("Oturum #%s listede bulunamadı." % ident)
        elif target == "certificate":
            self._go_history(sub_tab=1)
            if not self.history.focus_certificate(ident):
                self.state.status("Sertifika %s listede bulunamadı." % ident)
        elif target == "dut":
            self._go("devices")
            self.devices.focus_dut(ident)
        else:
            self._go_target(target)

    def _go_target(self, target):
        """Opens the target coming from a notification.

        Target names are produced in the `notifications` module; if a
        notification there doesn't know which screen to take the user to,
        the notification is left incomplete.
        """
        if target == "approvals" and self._idx("approvals") >= 0:
            self._go("approvals")
        elif target == "devices":
            self._go("devices")
        elif target == "backup":
            self._backup_now()
        elif target and target.startswith("admin."):
            self._go_admin(target.split(".", 1)[1])

    def _on_tab_changed(self, index):
        if index == self._idx("history"):
            self.history.reload()

    def _on_session_started(self, session_id, driver):
        self.acquire.begin(session_id, driver,
                           interval_s=self.setup.interval_spin.value())
        self.tabs.setTabEnabled(self._idx("acquire"), True)
        self._go("acquire")
        self.act_finish.setEnabled(True)

    def _on_session_finished(self, session_id):
        self.tabs.setTabEnabled(self._idx("acquire"), False)
        self.act_finish.setEnabled(False)
        self._go_history(sub_tab=0)
        self.state.status("Oturum #%d tamamlandı." % session_id)

    def _finish_session(self):
        if self.acquire.worker is not None:
            self.acquire._finish()

    # --- theme -------------------------------------------------------------
    def _toggle_theme(self):
        self._set_theme(theme.DARK if theme.current_mode() == theme.LIGHT
                        else theme.LIGHT)

    def _set_theme(self, mode):
        theme.apply(QtWidgets.QApplication.instance(), mode)
        self._refresh_appearance()
        self.state.status("Tema: %s" % theme.MODE_TR.get(mode, mode))

    def _set_scale(self, scale):
        theme.apply(QtWidgets.QApplication.instance(), scale=scale)
        self._refresh_appearance()
        self.state.status("Yazı boyutu: %%%d" % round(scale * 100))

    #: Ctrl+/Ctrl- changes the font size by this much per press.
    _ZOOM_STEP = 0.1

    def _zoom_in(self):
        # theme.apply already clamps to MIN/MAX_SCALE, but it applies the
        # unclamped value to the stylesheet while saving the clamped one —
        # clamped here too so the two don't diverge.
        self._set_scale(min(theme.MAX_SCALE,
                            round(theme.font_scale() + self._ZOOM_STEP, 2)))

    def _zoom_out(self):
        self._set_scale(max(theme.MIN_SCALE,
                            round(theme.font_scale() - self._ZOOM_STEP, 2)))

    def _zoom_reset(self):
        self._set_scale(1.0)

    def _set_language(self, code):
        """Changes the language. The UI changes on restart.

        Documents aren't subject to this: a certificate is written in
        whatever language is current at the moment it's generated, so the
        first document produced after a language change is already in the
        new language. Rebuilding the UI live (tearing down and recreating
        every page) would be a much bigger change than switching languages
        is worth.
        """
        if code == i18n.language():
            return
        i18n.set_language(code, self.state.user["id"])
        self._sync_theme_actions()
        QtWidgets.QMessageBox.information(
            self, i18n.label(code),
            "Dil %s olarak kaydedildi.\n\n"
            "Menüler ve sayfa adları uygulama yeniden başlatıldığında "
            "değişecek. Bundan sonra üretilecek sertifika ve raporlar "
            "hemen yeni dilde yazılır."
            % i18n.label(code))
        self.state.status("Dil: %s" % i18n.label(code))

    def _refresh_appearance(self):
        self._sync_theme_actions()
        # pyqtgraph doesn't use the Qt palette, its colors need to be refreshed manually
        self.acquire.apply_plot_theme()
        self.acquire._set_recording_badge(self.acquire.recording)
        self._refresh_extra_appearance()
        self.tabs.refresh_theme()
        self.home.refresh()

    def _sync_theme_actions(self):
        mode = theme.current_mode()
        self.act_light.setChecked(mode == theme.LIGHT)
        self.act_dark.setChecked(mode == theme.DARK)
        self.act_contrast.setChecked(mode == theme.CONTRAST)
        scale = theme.font_scale()
        for action, value in self._font_actions:
            action.setChecked(abs(value - scale) < 0.01)
        for action, code in getattr(self, "_lang_actions", ()):
            action.setChecked(code == i18n.language())

    # --- backup ---------------------------------------------------------
    def _refresh_backup_label(self):
        c = theme.colors()
        age = backup.age_days()
        text = backup.age_text()
        if age is None or age >= backup.STALE_DAYS:
            self.backup_label.setStyleSheet("color:%s;" % c["warn"])
        else:
            self.backup_label.setStyleSheet("color:%s;" % c["text_muted"])
        self.backup_label.setText(text)
        self.backup_label.setToolTip(
            "Yedekler %s klasöründe tutuluyor; en yeni %d kopya saklanır."
            % (backup.backup_dir(), backup.KEEP))

    def _backup_now(self):
        try:
            path = backup.create(self.state.user["id"])
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Yedeklenemedi",
                "Veritabanının kopyası alınamadı:\n\n%s" % exc)
            return
        self._refresh_backup_label()
        self.home.refresh()
        self.state.status("Veritabanı yedeklendi: %s" % path)

    # --- other ------------------------------------------------------------
    def _verify_audit(self):
        from .. import audit as _audit
        ok, bad_id, n = _audit.verify_chain()
        if ok:
            QtWidgets.QMessageBox.information(
                self, "Denetim kaydı",
                "Hash zinciri sağlam.\n\n%d kayıt doğrulandı." % n)
        else:
            QtWidgets.QMessageBox.critical(
                self, "Denetim kaydı BOZUK",
                "Zincir %d numaralı satırda kırıldı.\n\n"
                "Veritabanı dışarıdan değiştirilmiş olabilir. Yedekten geri dönün "
                "ve durumu lab sorumlusuna bildirin." % bad_id)

    def _open_guide(self, path, title):
        if not os.path.isfile(path):
            QtWidgets.QMessageBox.warning(
                self, "Kılavuz bulunamadı",
                "Kılavuz dosyası yerinde değil:\n%s" % path)
            return
        from . import pdf_preview

        pdf_preview.show(path, self, title=title)

    def _shortcuts(self):
        rows = [("Ctrl+N", "Yeni kalibrasyon oturumu"),
                ("Ctrl+W", "Oturumu bitir"),
                ("Ctrl+D", "Kalibre edilen cihazlar"),
                ("Ctrl+H", "Geçmiş kayıtlar")]
        if self.approvals is not None:
            rows.append(("Ctrl+O", "Onay kuyruğu"))
        if self.state.can(perms.VIEW_ADMIN):
            rows.append(("Ctrl+B", "Veritabanını yedekle"))
        rows += [("Ctrl+1…%d" % self.tabs.count(), "Sayfalar arasında geçiş"),
                 ("Ctrl++ / Ctrl+-", "Yazı boyutunu büyüt / küçült"),
                 ("Ctrl+0", "Yazı boyutunu sıfırla (%100)"),
                 ("Ctrl+Q", "Çıkış"),
                 ("F1", "Bu pencere")]
        html = "<table cellspacing='6'>" + "".join(
            "<tr><td><b>%s</b></td><td>%s</td></tr>" % r for r in rows) + "</table>"
        QtWidgets.QMessageBox.information(self, "Klavye kısayolları", html)

    def _about(self):
        version, author = self._app_version_info()
        title = self._app_title()
        QtWidgets.QMessageBox.about(
            self, title,
            "<b>%s %s</b><br><br>"
            "%s<br>"
            "Ölçüm kayıt ve sertifikasyon sistemi<br>"
            "Geliştiren: %s<br><br>"
            "Oturum: %s (%s)<br>"
            "Qt bağlaması: %s<br>"
            "Veritabanı: %s" % (
                title, version, branding.header_line(), author,
                self.state.user["full_name"],
                perms.label(self.state.user["role"]), QT_BINDING, db.DB_PATH))

    def closeEvent(self, event):
        if self.acquire.worker is not None:
            ans = QtWidgets.QMessageBox.question(
                self, "Ölçüm sürüyor",
                "Devam eden bir ölçüm var. Oturum iptal edilerek kapatılsın mı?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if ans != QtWidgets.QMessageBox.Yes:
                event.ignore()
                return
            self.acquire.stop(status="aborted")
        self._shutdown_extra()
        audit.log("auth.logout", user_id=self.state.user["id"])
        event.accept()


class HomePage(QtWidgets.QWidget):
    """Home screen: summary counts, quick actions, instrument status, recent sessions."""

    new_session = Signal()
    open_history = Signal()
    open_devices = Signal()
    open_target = Signal(str)

    def __init__(self, app_state, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.state = app_state

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(14)

        root.addLayout(self._greeting())
        root.addWidget(self._summary_cards())
        root.addWidget(self._notifications_box())
        root.addLayout(self._actions())

        cols = QtWidgets.QHBoxLayout()
        cols.setSpacing(12)
        cols.addWidget(self._instruments_box(), 3)
        cols.addWidget(self._recent_box(), 2)
        root.addLayout(cols, 1)

    def _greeting(self):
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(2)
        title = QtWidgets.QLabel("Merhaba, %s" % _first_name(
            self.state.user["full_name"]))
        title.setProperty("h1", True)
        self.subtitle = QtWidgets.QLabel("")
        self.subtitle.setProperty("hint", True)
        col.addWidget(title)
        col.addWidget(self.subtitle)
        return col

    def _summary_cards(self):
        w = QtWidgets.QFrame()
        w.setProperty("card", True)
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(6)
        self._cards = {}
        cards = [("sessions", "Toplam oturum"), ("certs", "Sertifika"),
                 ("duts", "Kayıtlı cihaz")]
        # "Pending approval" is only meaningful for approvers; an operator
        # can't act on that queue and the number would only cause anxiety.
        if self.state.can(perms.CERT_APPROVE):
            cards.append(("pending", "Onay bekleyen"))
        for i, (key, label) in enumerate(cards):
            if i:
                line = QtWidgets.QFrame()
                line.setFrameShape(QtWidgets.QFrame.VLine)
                line.setFixedWidth(1)
                lay.addWidget(line)
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(2)
            cap = QtWidgets.QLabel(label)
            cap.setProperty("statcap", True)
            val = QtWidgets.QLabel("—")
            val.setProperty("stat", True)
            col.addWidget(cap)
            col.addWidget(val)
            lay.addLayout(col, 1)
            self._cards[key] = val
        return w

    def _notifications_box(self):
        """Everything that needs attention, in one place.

        The box is **hidden** when there are no notifications: an empty
        "everything's fine" panel that's always there becomes invisible
        within a few days, and goes unnoticed once it fills up too.
        """
        self.notif_box = QtWidgets.QGroupBox("Dikkat isteyenler")
        self.notif_list = QtWidgets.QListWidget()
        self.notif_list.setMaximumHeight(92)
        self.notif_list.setAlternatingRowColors(True)
        self.notif_list.itemActivated.connect(self._open_notification)
        self.notif_list.itemDoubleClicked.connect(self._open_notification)
        lay = QtWidgets.QVBoxLayout(self.notif_box)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.addWidget(self.notif_list)
        self.notif_box.setVisible(False)
        return self.notif_box

    def _open_notification(self, item):
        target = item.data(Qt.UserRole)
        if target:
            self.open_target.emit(target)

    def _refresh_notifications(self):
        c = theme.colors()
        items = notifications.collect(self.state.user)
        self.notif_list.clear()
        for n in items:
            entry = QtWidgets.QListWidgetItem(n["title"])
            entry.setForeground(QtGui.QColor(c.get(n["level"], c["text"])))
            entry.setData(Qt.UserRole, n["target"])
            tip = n["detail"]
            if n["target"]:
                tip += "\n\n(Çift tıklayınca ilgili ekran açılır.)"
            entry.setToolTip(tip)
            self.notif_list.addItem(entry)
        self.notif_box.setVisible(bool(items))
        self.notif_box.setTitle("Dikkat isteyenler (%d)" % len(items)
                                if items else "Dikkat isteyenler")

    def _actions(self):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        new_btn = QtWidgets.QPushButton("Yeni kalibrasyon oturumu")
        new_btn.setProperty("primary", True)
        new_btn.setMinimumHeight(42)
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.clicked.connect(self.new_session.emit)
        dev_btn = QtWidgets.QPushButton("Kalibre edilen cihazlar")
        dev_btn.setMinimumHeight(42)
        dev_btn.setCursor(Qt.PointingHandCursor)
        dev_btn.clicked.connect(self.open_devices.emit)
        hist_btn = QtWidgets.QPushButton("Geçmiş kayıtlar")
        hist_btn.setMinimumHeight(42)
        hist_btn.setCursor(Qt.PointingHandCursor)
        hist_btn.clicked.connect(self.open_history.emit)
        row.addWidget(new_btn, 2)
        row.addWidget(dev_btn, 1)
        row.addWidget(hist_btn, 1)
        return row

    def _instruments_box(self):
        box = QtWidgets.QGroupBox("Referans cihazlar")
        self.inst_table = QtWidgets.QTableWidget(0, 5)
        self.inst_table.setHorizontalHeaderLabels(
            ["Cihaz", "Seri no", "Arayüz", "Kalibrasyon geçerliliği", "Durum"])
        self.inst_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.inst_table.setAlternatingRowColors(True)
        self.inst_table.verticalHeader().setVisible(False)
        self.inst_table.horizontalHeader().setStretchLastSection(True)
        lay = QtWidgets.QVBoxLayout(box)
        lay.addWidget(self.inst_table)
        return box

    def _recent_box(self):
        box = QtWidgets.QGroupBox("Son oturumlar")
        self.recent = QtWidgets.QListWidget()
        lay = QtWidgets.QVBoxLayout(box)
        lay.addWidget(self.recent)
        return box

    def showEvent(self, event):
        self.refresh()
        QtWidgets.QWidget.showEvent(self, event)

    def refresh(self):
        from datetime import date

        self._refresh_notifications()
        one = lambda sql: db.query_one(sql)["n"]
        self._cards["sessions"].setText(str(one(
            "SELECT COUNT(*) AS n FROM sessions WHERE deleted_at IS NULL")))
        self._cards["certs"].setText(str(one(
            "SELECT COUNT(*) AS n FROM certificates WHERE deleted_at IS NULL")))
        self._cards["duts"].setText(str(one("SELECT COUNT(*) AS n FROM duts")))
        if "pending" in self._cards:
            self._cards["pending"].setText(str(one(
                "SELECT COUNT(*) AS n FROM certificates"
                " WHERE approved_at IS NULL AND deleted_at IS NULL")))

        mine = db.query_one(
            "SELECT COUNT(*) AS n FROM sessions"
            " WHERE operator_id = ? AND deleted_at IS NULL",
            (self.state.user["id"],))["n"]
        self.subtitle.setText(
            "%s · %d ölçüm oturumu sizin adınıza kayıtlı."
            % (perms.label(self.state.user["role"]), mine))

        c = theme.colors()
        rows = db.query("SELECT * FROM instruments WHERE is_active = 1 ORDER BY id")
        self.inst_table.setRowCount(0)
        for r in rows:
            i = self.inst_table.rowCount()
            self.inst_table.insertRow(i)
            color = None
            if drivers.is_simulated(r["driver"]):
                status, color = "simülasyon", c["warn"]
            elif r["cal_due"]:
                try:
                    d = date(*[int(x) for x in r["cal_due"].split("-")])
                    left = (d - date.today()).days
                    if left < 0:
                        status, color = "SÜRESİ DOLMUŞ", c["bad"]
                    elif left < 30:
                        status, color = "%d gün kaldı" % left, c["warn"]
                    else:
                        status = "geçerli"
                except Exception:
                    status, color = "tarih okunamadı", c["bad"]
            else:
                status, color = "kalibrasyon bilgisi yok", c["warn"]

            cells = ["%s %s" % (r["brand"], r["model"]), r["serial_no"],
                     r["iface"] or "—", r["cal_due"] or "—", status]
            for col, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(str(text))
                if col == 4 and color:
                    item.setForeground(QtGui.QColor(color))
                self.inst_table.setItem(i, col, item)
        fit_table(self.inst_table)
        empty_state(self.inst_table, "Tanımlı referans cihaz yok.")

        self.recent.clear()
        for r in db.query(
            "SELECT s.id, s.name, s.started_at, s.status, s.is_simulated, d.model,"
            " d.serial_no, u.full_name"
            " FROM sessions s JOIN duts d ON d.id = s.dut_id"
            " JOIN users u ON u.id = s.operator_id"
            " WHERE s.deleted_at IS NULL"
            " ORDER BY s.id DESC LIMIT 12"
        ):
            item = QtWidgets.QListWidgetItem(
                "#%d · %s · %s (%s) · %s · %s%s" % (
                    r["id"], (r["started_at"] or "")[:16].replace("T", " "),
                    r["model"], r["serial_no"], r["full_name"], r["status"],
                    " · simülasyon" if r["is_simulated"] else ""))
            if r["is_simulated"]:
                item.setForeground(QtGui.QColor(c["warn"]))
            self.recent.addItem(item)
        empty_state(self.recent,
                    "Henüz ölçüm oturumu yok.\n"
                    "'Yeni kalibrasyon oturumu' ile başlayın.")


def has_active_scope():
    """Whether an active instrument in the inventory can capture waveforms.

    Shared by both apps' `_extra_page_available()`: a waveform-capture page
    (defib) and a velocity page (seshizi) both need *some* oscilloscope-class
    driver, just applied to a different measurement. If none is active, the
    page isn't added at all — an unusable page shouldn't take up space in
    the rail. It becomes visible once the app is restarted after a new
    oscilloscope is defined.
    """
    for row in db.query("SELECT driver FROM instruments WHERE is_active = 1"):
        if drivers.supports_waveform(row["driver"]):
            return True
    return False


def _first_name(full_name):
    parts = [p for p in (full_name or "").split() if p]
    return parts[0] if parts else "kullanıcı"
