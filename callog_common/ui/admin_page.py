"""Admin page: users, reference instruments, audit log.

User deletion is deliberately absent. A deleted user's past measurements
would be left ownerless and break the traceability chain; departed staff
are deactivated instead.

The page's sections are added based on role: the lab manager sees the
audit log and reference instruments but not the user list, an operator
can't reach this page at all. Rules live in the `perms` module.
"""

import csv
import os

from .. import audit, auth, branding, db, perms, theme
from ..qt import Qt, QtGui, QtWidgets
from .util import (DateRangeFilter, empty_state, fit_table, PAGE_MARGIN,
                   PAGE_SPACING)

ROLE_LABELS = perms.ROLE_LABELS


class AdminPage(QtWidgets.QWidget):

    def __init__(self, app_state, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.state = app_state

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGIN)
        root.setSpacing(PAGE_SPACING)

        title = QtWidgets.QLabel("Yönetim")
        title.setProperty("h1", True)
        root.addWidget(title)

        self.notice = QtWidgets.QLabel("")
        self.notice.setProperty("hint", True)
        self.notice.setWordWrap(True)
        root.addWidget(self.notice)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("innerTabs")
        self._sections = {}
        if self.state.can(perms.VIEW_USERS):
            self._add_section("users", self._users_tab(), "Kullanıcılar")
        self._add_section("instruments", self._instruments_tab(),
                          "Referans cihazlar")
        self._add_section("perms", self._perms_tab(), "Yetki matrisi")
        if self.state.can(perms.VIEW_AUDIT):
            self._add_section("audit", self._audit_tab(), "Denetim kaydı")
        if self.state.can(perms.BRANDING_EDIT):
            self._add_section("branding", self._branding_tab(), "Laboratuvar")
        root.addWidget(self.tabs, 1)

    def _add_section(self, key, widget, label):
        self._sections[key] = self.tabs.addTab(widget, label)

    def show_section(self, key):
        index = self._sections.get(key)
        if index is not None:
            self.tabs.setCurrentIndex(index)

    def has_section(self, key):
        return key in self._sections

    # --- users ---------------------------------------------------
    def _users_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)

        self.user_table = QtWidgets.QTableWidget(0, 5)
        self.user_table.setHorizontalHeaderLabels(
            ["Ad soyad", "Kullanıcı adı", "Rol", "Durum", "Oluşturulma"])
        self.user_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.user_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.user_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.user_table.setAlternatingRowColors(True)
        self.user_table.verticalHeader().setVisible(False)
        self.user_table.horizontalHeader().setStretchLastSection(True)
        self.user_table.itemSelectionChanged.connect(self._on_user_selected)
        lay.addWidget(self.user_table, 1)

        row = QtWidgets.QHBoxLayout()
        self.new_user_btn = QtWidgets.QPushButton("Yeni kullanıcı")
        self.new_user_btn.setProperty("primary", True)
        self.new_user_btn.clicked.connect(self._new_user)
        self.role_btn = QtWidgets.QPushButton("Rol değiştir")
        self.role_btn.clicked.connect(self._change_role)
        self.pwd_btn = QtWidgets.QPushButton("Parola sıfırla")
        self.pwd_btn.clicked.connect(self._reset_password)
        self.active_btn = QtWidgets.QPushButton("Devre dışı bırak")
        self.active_btn.clicked.connect(self._toggle_active)
        for b in (self.new_user_btn, self.role_btn, self.pwd_btn, self.active_btn):
            row.addWidget(b)
        row.addStretch(1)

        note = QtWidgets.QLabel(
            "Kullanıcı silme yok — geçmiş ölçümlerin sahibi kaybolmasın diye "
            "ayrılan personel devre dışı bırakılır.")
        note.setProperty("hint", True)
        note.setWordWrap(True)

        lay.addLayout(row)
        lay.addWidget(note)
        return w

    def _selected_user(self):
        rows = self.user_table.selectionModel().selectedRows()
        if not rows:
            return None
        uid = self.user_table.item(rows[0].row(), 0).data(Qt.UserRole)
        return db.query_one("SELECT * FROM users WHERE id = ?", (uid,))

    def _on_user_selected(self):
        u = self._selected_user()
        enabled = u is not None and self._is_admin()
        for b in (self.role_btn, self.pwd_btn, self.active_btn):
            b.setEnabled(enabled)
        if u is not None:
            self.active_btn.setText(
                "Devre dışı bırak" if u["is_active"] else "Yeniden etkinleştir")

    def _is_admin(self):
        return self.state.can(perms.USER_MANAGE)

    def _require(self, permission):
        """Second layer of defense against paths where the hiding was bypassed."""
        if self.state.can(permission):
            return True
        QtWidgets.QMessageBox.warning(
            self, "Yetki yok", perms.denial_message(permission))
        return False

    def _new_user(self):
        if not self._require(perms.USER_MANAGE):
            return
        from .login import NewUserDialog
        dlg = NewUserDialog(self, actor_id=self.state.user["id"])
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.reload()
            self.state.status("Kullanıcı oluşturuldu: %s" % dlg.created_username)

    def _change_role(self):
        if not self._require(perms.USER_MANAGE):
            return
        u = self._selected_user()
        if u is None:
            return
        labels = [ROLE_LABELS[r] for r in auth.ROLES]
        current = auth.ROLES.index(u["role"])
        label, ok = QtWidgets.QInputDialog.getItem(
            self, "Rol değiştir",
            "%s için yeni rol:" % u["full_name"], labels, current, False)
        if not ok:
            return
        role = auth.ROLES[labels.index(label)]
        try:
            auth.set_role(u["id"], role, self.state.user["id"])
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Değiştirilemedi", str(exc))
            return
        self.reload()
        self.state.status("%s → %s" % (u["full_name"], ROLE_LABELS[role]))

    def _reset_password(self):
        if not self._require(perms.USER_MANAGE):
            return
        u = self._selected_user()
        if u is None:
            return
        pwd, ok = QtWidgets.QInputDialog.getText(
            self, "Parola sıfırla",
            "%s için yeni parola (en az 6 karakter):" % u["full_name"],
            QtWidgets.QLineEdit.Password)
        if not ok:
            return
        try:
            auth.reset_password(u["id"], pwd, self.state.user["id"])
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Sıfırlanamadı", str(exc))
            return
        self.state.status("%s kullanıcısının parolası değiştirildi." % u["username"])

    def _toggle_active(self):
        if not self._require(perms.USER_MANAGE):
            return
        u = self._selected_user()
        if u is None:
            return
        making_active = not u["is_active"]
        if not making_active:
            ans = QtWidgets.QMessageBox.question(
                self, "Devre dışı bırak",
                "%s artık giriş yapamayacak.\n\nGeçmiş ölçümleri ve imzaları "
                "kayıtta kalır. Devam edilsin mi?" % u["full_name"],
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if ans != QtWidgets.QMessageBox.Yes:
                return
        try:
            auth.set_active(u["id"], making_active, self.state.user["id"])
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Değiştirilemedi", str(exc))
            return
        self.reload()

    # --- reference instruments ----------------------------------------------
    def _instruments_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)

        self.inst_table = QtWidgets.QTableWidget(0, 7)
        self.inst_table.setHorizontalHeaderLabels(
            ["Marka / model", "Seri no", "Sürücü", "Arayüz", "VISA adresi",
             "Kalibrasyon sertifikası", "Geçerlilik"])
        self.inst_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.inst_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.inst_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.inst_table.setAlternatingRowColors(True)
        self.inst_table.verticalHeader().setVisible(False)
        self.inst_table.horizontalHeader().setStretchLastSection(True)
        self.inst_table.doubleClicked.connect(self._edit_instrument)
        lay.addWidget(self.inst_table, 1)

        row = QtWidgets.QHBoxLayout()
        edit_btn = QtWidgets.QPushButton("Kalibrasyon bilgisini düzenle")
        edit_btn.clicked.connect(self._edit_instrument)
        row.addWidget(edit_btn)
        row.addStretch(1)
        lay.addLayout(row)

        note = QtWidgets.QLabel(
            "Kalibrasyon geçerliliği dolmuş bir referansla alınan ölçüm geçersizdir. "
            "Sertifika numarası ve geçerlilik tarihi sertifikaya basılır.")
        note.setProperty("hint", True)
        note.setWordWrap(True)
        lay.addWidget(note)
        return w

    def _edit_instrument(self):
        if not self._require(perms.INSTRUMENT_EDIT):
            return
        rows = self.inst_table.selectionModel().selectedRows()
        if not rows:
            QtWidgets.QMessageBox.information(
                self, "Seçim yok", "Önce bir cihaz seçin.")
            return
        iid = self.inst_table.item(rows[0].row(), 0).data(Qt.UserRole)
        inst = db.query_one("SELECT * FROM instruments WHERE id = ?", (iid,))

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("%s %s — kalibrasyon bilgisi" % (inst["brand"], inst["model"]))
        dlg.setMinimumWidth(420)
        cert = QtWidgets.QLineEdit(inst["cal_cert_no"] or "")
        cert.setPlaceholderText("CAL-E-2025-0412")
        cal_date = QtWidgets.QLineEdit(inst["cal_date"] or "")
        cal_date.setPlaceholderText("2025-02-07  (YYYY-AA-GG)")
        due = QtWidgets.QLineEdit(inst["cal_due"] or "")
        due.setPlaceholderText("2026-11-14  (YYYY-AA-GG)")
        notes = QtWidgets.QLineEdit(inst["notes"] or "")

        form = QtWidgets.QFormLayout()
        form.addRow("Sertifika no", cert)
        form.addRow("Sertifika tarihi", cal_date)
        form.addRow("Geçerlilik tarihi", due)
        form.addRow("Not", notes)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addLayout(form)
        lay.addWidget(buttons)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        from datetime import date
        due_text = due.text().strip() or None
        date_text = cal_date.text().strip() or None
        for label, value in (("Geçerlilik tarihi", due_text),
                             ("Sertifika tarihi", date_text)):
            if not value:
                continue
            try:
                date(*[int(x) for x in value.split("-")])
            except Exception:
                QtWidgets.QMessageBox.warning(
                    self, "Tarih hatalı",
                    "%s YYYY-AA-GG biçiminde olmalı.\n"
                    "Örnek: 2026-11-14" % label)
                return

        db.execute(
            "UPDATE instruments SET cal_cert_no = ?, cal_date = ?, cal_due = ?,"
            " notes = ? WHERE id = ?",
            (cert.text().strip() or None, date_text, due_text,
             notes.text().strip() or None, iid))
        audit.log("instrument.update", user_id=self.state.user["id"],
                  entity="instrument", entity_id=iid,
                  detail={"cal_cert_no": cert.text().strip(),
                          "cal_date": date_text, "cal_due": due_text})
        self.reload()
        self.state.status("Cihaz kalibrasyon bilgisi güncellendi.")

    # --- lab identity ---------------------------------------------
    def _branding_tab(self):
        """Organization name, department name, and logo — stored in the database.

        No organization name is embedded in the source code: certificate/
        report headers, the login screen, and the navigation rail all read
        the value entered here (`branding.py`). If left empty, an
        organization-neutral default is used.
        """
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)
        lay.setSpacing(10)

        form = QtWidgets.QFormLayout()
        self.org_name_edit = QtWidgets.QLineEdit()
        self.org_name_edit.setPlaceholderText(branding.DEFAULT_ORG_NAME)
        self.department_edit = QtWidgets.QLineEdit()
        self.department_edit.setPlaceholderText("ör. Ölçüm Laboratuvarı")
        form.addRow("Kurum adı", self.org_name_edit)
        form.addRow("Birim / bölüm", self.department_edit)
        lay.addLayout(form)

        logo_row = QtWidgets.QHBoxLayout()
        self.logo_preview = QtWidgets.QLabel()
        self.logo_preview.setFixedSize(64, 64)
        self.logo_preview.setAlignment(Qt.AlignCenter)
        self.logo_preview.setObjectName("brandMark")
        logo_row.addWidget(self.logo_preview)
        logo_btn_col = QtWidgets.QVBoxLayout()
        load_logo_btn = QtWidgets.QPushButton("Logo yükle…")
        load_logo_btn.clicked.connect(self._load_logo)
        remove_logo_btn = QtWidgets.QPushButton("Logoyu kaldır")
        remove_logo_btn.clicked.connect(self._remove_logo)
        logo_btn_col.addWidget(load_logo_btn)
        logo_btn_col.addWidget(remove_logo_btn)
        logo_row.addLayout(logo_btn_col)
        logo_row.addStretch(1)
        lay.addLayout(logo_row)

        save_btn = QtWidgets.QPushButton("Kaydet")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self._save_branding)
        save_row = QtWidgets.QHBoxLayout()
        save_row.addWidget(save_btn)
        save_row.addStretch(1)
        lay.addLayout(save_row)

        note = QtWidgets.QLabel(
            "Bu bilgiler veritabanında tutulur, kaynak kodda yer almaz. "
            "Sertifikalar, raporlar, giriş ekranı ve gezinme şeridi burada "
            "girilen kurum adını ve logoyu kullanır.")
        note.setProperty("hint", True)
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch(1)
        return w

    def _reload_branding(self):
        self.org_name_edit.setText(branding.org_name())
        self.department_edit.setText(branding.department())
        self._refresh_logo_preview()

    def _refresh_logo_preview(self):
        data = branding.logo_bytes()
        if data:
            pixmap = QtGui.QPixmap()
            if pixmap.loadFromData(data) and not pixmap.isNull():
                self.logo_preview.setPixmap(pixmap.scaled(
                    58, 58, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                return
        self.logo_preview.setPixmap(QtGui.QPixmap())
        self.logo_preview.setText(branding.initials())

    def _load_logo(self):
        if not self._require(perms.BRANDING_EDIT):
            return
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self, "Logo seç", "", "Görsel dosyaları (*.png *.jpg *.jpeg)")
        if not path:
            return
        with open(path, "rb") as f:
            data = f.read()
        if path.lower().endswith((".jpg", ".jpeg")):
            from ..qt import QtCore as _QtCore

            image = QtGui.QImage()
            image.loadFromData(data)
            buf = _QtCore.QBuffer()
            buf.open(_QtCore.QBuffer.WriteOnly)
            image.save(buf, "PNG")
            data = bytes(buf.data())
        branding.set_logo(data)
        audit.log("branding.logo_update", user_id=self.state.user["id"])
        self._refresh_logo_preview()
        self.state.status("Logo güncellendi.")

    def _remove_logo(self):
        if not self._require(perms.BRANDING_EDIT):
            return
        branding.set_logo(None)
        audit.log("branding.logo_remove", user_id=self.state.user["id"])
        self._refresh_logo_preview()
        self.state.status("Logo kaldırıldı.")

    def _save_branding(self):
        if not self._require(perms.BRANDING_EDIT):
            return
        branding.set_org_name(self.org_name_edit.text())
        branding.set_department(self.department_edit.text())
        audit.log("branding.update", user_id=self.state.user["id"],
                  detail={"org_name": branding.org_name(),
                          "department": branding.department()})
        self.state.status("Laboratuvar bilgisi kaydedildi.")

    # --- permission matrix ---------------------------------------------------
    def _perms_tab(self):
        """Which role can do what — read-only.

        Rules live in `perms._TABLE`; the table here is generated from it.
        If the screen had its own list, the two would diverge whenever a
        permission changed and the screen would show wrong information.
        """
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)

        self.perm_table = QtWidgets.QTableWidget(0, 2 + len(perms.ROLE_ORDER))
        self.perm_table.setHorizontalHeaderLabels(
            ["Grup", "Yetki"] + [perms.label(r) for r in perms.ROLE_ORDER])
        self.perm_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.perm_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.perm_table.setAlternatingRowColors(True)
        self.perm_table.verticalHeader().setVisible(False)
        lay.addWidget(self.perm_table, 1)

        roles = QtWidgets.QLabel(
            "<br>".join("<b>%s</b> — %s" % (perms.label(r),
                                            perms.ROLE_DESCRIPTIONS[r])
                        for r in perms.ROLE_ORDER))
        roles.setWordWrap(True)
        lay.addWidget(roles)

        note = QtWidgets.QLabel(
            "Roller yığılımlı değil: her rolün yetkileri ayrı ayrı yazılır. "
            "Arayüz yetkisiz düğmeyi gizler, işlem katmanı ayrıca reddeder — "
            "gizlenmiş bir düğme kısayolla ya da doğrudan çağrıyla "
            "tetiklenebilir.")
        note.setProperty("hint", True)
        note.setWordWrap(True)
        lay.addWidget(note)
        return w

    def _reload_perms(self):
        c = theme.colors()
        rows = perms.matrix()
        self.perm_table.setRowCount(0)
        previous_group = None
        for group, _permission, label, allowed in rows:
            i = self.perm_table.rowCount()
            self.perm_table.insertRow(i)
            # The group name is only written when it changes: the same text
            # repeating on every row pulls the eye away from the real information.
            cells = [group if group != previous_group else "", label]
            previous_group = group
            for role in perms.ROLE_ORDER:
                cells.append("✓" if allowed[role] else "—")
            for col, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(text)
                if col >= 2:
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setForeground(QtGui.QColor(
                        c["ok"] if text == "✓" else c["text_muted"]))
                if col == 0 and text:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.perm_table.setItem(i, col, item)
        fit_table(self.perm_table, stretch_column=1)

    # --- audit log ---------------------------------------------------
    def _audit_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)

        row = QtWidgets.QHBoxLayout()
        self.chain_label = QtWidgets.QLabel("")
        self.chain_label.setWordWrap(True)
        row.addWidget(self.chain_label, 1)
        verify_btn = QtWidgets.QPushButton("Zinciri doğrula")
        verify_btn.clicked.connect(self._verify_chain)
        row.addWidget(verify_btn)
        lay.addLayout(row)

        filters = QtWidgets.QHBoxLayout()
        self.audit_search = QtWidgets.QLineEdit()
        self.audit_search.setPlaceholderText(
            "Ara — kullanıcı, işlem ya da nesne (örn. cert.delete)")
        self.audit_search.setClearButtonEnabled(True)
        self.audit_search.textChanged.connect(lambda _t: self._reload_audit())
        self.audit_action = QtWidgets.QComboBox()
        self.audit_action.addItem("Tüm işlem türleri", None)
        # The three things most often searched for in the audit log: who
        # logged in, what got deleted, which certificate was approved.
        for label, prefix in (("Giriş / çıkış", "auth."),
                              ("Sertifika", "cert"),
                              ("Oturum", "session"),
                              ("Kullanıcı", "user."),
                              ("Belge", "document.")):
            self.audit_action.addItem(label, prefix)
        self.audit_action.currentIndexChanged.connect(
            lambda _i: self._reload_audit())
        self.audit_dates = DateRangeFilter()
        self.audit_dates.changed.connect(self._reload_audit)
        self.audit_export_btn = QtWidgets.QPushButton("CSV'ye aktar")
        self.audit_export_btn.setToolTip(
            "Süzgece uyan bütün satırları yazar — ekranda gösterilen ilk\n"
            "500 satırla sınırlı değildir. Denetçi genelde dosya istiyor.")
        self.audit_export_btn.clicked.connect(self._export_audit)
        filters.addWidget(self.audit_search, 1)
        filters.addWidget(self.audit_action)
        filters.addWidget(self.audit_dates)
        filters.addWidget(self.audit_export_btn)
        lay.addLayout(filters)

        self.audit_table = QtWidgets.QTableWidget(0, 5)
        self.audit_table.setHorizontalHeaderLabels(
            ["Zaman (UTC)", "Kullanıcı", "İşlem", "Nesne", "Ayrıntı"])
        self.audit_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.audit_table.setAlternatingRowColors(True)
        self.audit_table.verticalHeader().setVisible(False)
        self.audit_table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.audit_table, 1)

        note = QtWidgets.QLabel(
            "Denetim kaydı değiştirilemez ve silinemez. Her satır bir öncekinin "
            "SHA-256 özetini taşır; veritabanı dışarıdan kurcalanırsa zincir kırılır.")
        note.setProperty("hint", True)
        note.setWordWrap(True)
        lay.addWidget(note)
        return w

    def _verify_chain(self):
        ok, bad_id, n = audit.verify_chain()
        c = theme.colors()
        if ok:
            self.chain_label.setText(
                "<span style='color:%s'>Zincir sağlam — %d kayıt doğrulandı."
                "</span>" % (c["ok"], n))
        else:
            self.chain_label.setText(
                "<span style='color:%s'><b>Zincir %d numaralı satırda kırıldı.</b> "
                "Veritabanı dışarıdan değiştirilmiş olabilir.</span>"
                % (c["bad"], bad_id))

    # --- reload --------------------------------------------------------
    def showEvent(self, event):
        self.reload()
        QtWidgets.QWidget.showEvent(self, event)

    def reload(self):
        if not self._is_admin():
            self.notice.setText(
                "Salt görüntüleme: değişiklik yapmak için yönetici yetkisi gerekiyor.")
        else:
            self.notice.setText("")

        if self.has_section("users"):
            self._reload_users()
        self._reload_instruments()
        self._reload_perms()
        if self.has_section("audit"):
            self._reload_audit()
        if self.has_section("branding"):
            self._reload_branding()

    def _reload_users(self):
        from ..qt import QtGui

        colors = theme.colors()
        # Role color is the most important information in the table: it lets
        # you see at a glance who can approve certificates, instead of
        # reading row by row.
        role_color = {"admin": colors["bad"], "approver": colors["warn"],
                      "operator": colors["ok"]}

        self.user_table.setRowCount(0)
        for u in auth.list_users():
            i = self.user_table.rowCount()
            self.user_table.insertRow(i)
            cells = [u["full_name"], u["username"], ROLE_LABELS.get(u["role"], u["role"]),
                     "etkin" if u["is_active"] else "devre dışı",
                     (u["created_at"] or "")[:10]]
            for c, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(text)
                if c == 0:
                    item.setData(Qt.UserRole, u["id"])
                if c == 2:
                    item.setForeground(QtGui.QColor(
                        role_color.get(u["role"], colors["text"])))
                if not u["is_active"]:
                    font = item.font()
                    font.setStrikeOut(True)
                    item.setFont(font)
                    item.setForeground(QtGui.QColor(colors["text_muted"]))
                self.user_table.setItem(i, c, item)
        fit_table(self.user_table)
        empty_state(self.user_table, "Kayıtlı kullanıcı yok.")
        self.new_user_btn.setEnabled(self._is_admin())
        self._on_user_selected()

    def _reload_instruments(self):
        self.inst_table.setRowCount(0)
        for r in db.query("SELECT * FROM instruments ORDER BY id"):
            i = self.inst_table.rowCount()
            self.inst_table.insertRow(i)
            cells = ["%s %s" % (r["brand"], r["model"]), r["serial_no"],
                     r["driver"], r["iface"] or "—", r["address"] or "—",
                     r["cal_cert_no"] or "—", r["cal_due"] or "—"]
            for c, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(str(text))
                if c == 0:
                    item.setData(Qt.UserRole, r["id"])
                self.inst_table.setItem(i, c, item)
        fit_table(self.inst_table)
        empty_state(self.inst_table, "Tanımlı referans cihaz yok.")

    def _audit_matches(self, limit=None):
        """Audit rows matching the filter, newest to oldest.

        The date range is filtered in SQL, the search text in Python: the
        search text also looks inside the JSON in the `detail` field, and
        doing that in SQL would require a chain of LIKEs for every row.
        `limit` is only for the screen; export writes all rows.
        """
        names = {u["id"]: u["full_name"] for u in auth.list_users()}
        needle = self.audit_search.text().strip().lower()
        prefix = self.audit_action.currentData()
        start, end = self.audit_dates.range()

        sql = "SELECT * FROM audit_log"
        params = []
        if start:
            sql += " WHERE ts_utc >= ? AND ts_utc < ?"
            params += [start, end]
        sql += " ORDER BY id DESC"

        out = []
        for r in db.query(sql, tuple(params)):
            if prefix and not r["action"].startswith(prefix):
                continue
            entity = "%s#%s" % (r["entity"], r["entity_id"]) if r["entity"] else "—"
            who = names.get(r["user_id"], "—")
            if needle and needle not in " ".join(
                    (who, r["action"], entity, r["detail"] or "")).lower():
                continue
            out.append((r, who, entity))
            if limit and len(out) >= limit:
                break
        return out

    def _reload_audit(self):
        rows = self._audit_matches(limit=500)
        self.audit_table.setRowCount(0)
        for r, who, entity in rows:
            i = self.audit_table.rowCount()
            self.audit_table.insertRow(i)
            cells = [r["ts_utc"].replace("T", " ")[:19], who, r["action"], entity,
                     (r["detail"] or "")[:120]]
            for c, text in enumerate(cells):
                self.audit_table.setItem(i, c, QtWidgets.QTableWidgetItem(str(text)))
        fit_table(self.audit_table, stretch_column=4)
        empty_state(self.audit_table,
                    "Bu süzgece uyan kayıt yok.\nTarih aralığı: %s"
                    % self.audit_dates.describe())
        self._verify_chain()

    def _export_audit(self):
        """Writes the rows matching the filter to CSV — including the hash columns.

        `prev_hash` and `hash` are written too so the auditor receiving the
        file can verify the chain without the database. A dump without hash
        columns can't back the claim "these rows haven't changed".
        """
        rows = self._audit_matches()
        if not rows:
            QtWidgets.QMessageBox.information(
                self, "Kayıt yok", "Bu süzgece uyan denetim kaydı yok.")
            return
        suggested = "denetim-kaydi-%s.csv" % self.audit_dates.describe().replace(
            " – ", "_").replace(" ", "-")
        path, _f = QtWidgets.QFileDialog.getSaveFileName(
            self, "Denetim kaydını dışa aktar", suggested, "CSV (*.csv)")
        if not path:
            return
        try:
            # utf-8-sig: Excel mistakes BOM-less UTF-8 for the system code
            # page, and Turkish characters end up looking corrupted.
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh, delimiter=";")
                writer.writerow(["id", "zaman_utc", "kullanici", "islem",
                                 "nesne", "ayrinti", "onceki_ozet", "ozet"])
                for r, who, entity in rows:
                    writer.writerow([r["id"], r["ts_utc"], who, r["action"],
                                     entity, r["detail"] or "",
                                     r["prev_hash"], r["hash"]])
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "Yazılamadı", str(exc))
            return
        audit.log("audit.export", user_id=self.state.user["id"],
                  detail={"path": path, "rows": len(rows),
                          "range": self.audit_dates.describe()})
        self._reload_audit()
        self.state.status("%d denetim satırı yazıldı: %s"
                          % (len(rows), os.path.basename(path)))
