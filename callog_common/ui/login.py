"""Login screen.

Being certain who a record belongs to is the foundation of traceability —
that's why there's no "remember me". The Windows username is only used
for pre-filling.
"""

import getpass

from .. import auth, branding, db, perms, theme
from ..qt import Qt, QtWidgets
from .util import brand_mark


class LoginDialog(QtWidgets.QDialog):

    def __init__(self, parent=None):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle("CalLog — Giriş")
        self.setMinimumWidth(400)
        self.user = None

        self.username = QtWidgets.QLineEdit()
        self.password = QtWidgets.QLineEdit()
        self.password.setEchoMode(QtWidgets.QLineEdit.Password)
        self.username.setPlaceholderText("kullanıcı adı")
        self.password.setPlaceholderText("parola")

        self.message = QtWidgets.QLabel("")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: %s;" % theme.colors()["bad"])

        mark = brand_mark(44)
        mark_row = QtWidgets.QHBoxLayout()
        mark_row.addStretch(1)
        mark_row.addWidget(mark)
        mark_row.addStretch(1)

        title = QtWidgets.QLabel("CalLog")
        title.setProperty("h1", True)
        title.setAlignment(Qt.AlignCenter)
        subtitle = QtWidgets.QLabel(branding.header_line())
        subtitle.setProperty("hint", True)
        subtitle.setAlignment(Qt.AlignCenter)

        form = QtWidgets.QFormLayout()
        form.addRow("Kullanıcı adı", self.username)
        form.addRow("Parola", self.password)

        self.login_btn = QtWidgets.QPushButton("Giriş yap")
        self.login_btn.setProperty("primary", True)
        self.login_btn.setMinimumHeight(38)
        self.login_btn.clicked.connect(self._try_login)
        cancel_btn = QtWidgets.QPushButton("Çıkış")
        cancel_btn.clicked.connect(self.reject)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(cancel_btn)
        buttons.addWidget(self.login_btn, 1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(10)
        layout.addLayout(mark_row)
        layout.addSpacing(8)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(10)
        layout.addLayout(form)
        layout.addWidget(self.message)
        layout.addLayout(buttons)

        self.username.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._try_login)

        if auth.user_count() == 0:
            self._first_run()
        else:
            self._prefill_username()

    def _prefill_username(self):
        """Only pre-fills the username with an account that actually exists.

        Filling in the Windows username unconditionally was misleading: if
        the account name differed, the user would type a password into an
        account that didn't exist and get a "wrong password" message
        without understanding why.
        """
        try:
            win_user = getpass.getuser().strip().lower()
        except Exception:
            win_user = None

        if win_user and db.query_one(
            "SELECT 1 FROM users WHERE username = ? AND is_active = 1", (win_user,)
        ):
            self.username.setText(win_user)
            self.password.setFocus()
            return

        rows = db.query("SELECT username FROM users WHERE is_active = 1 LIMIT 2")
        if len(rows) == 1:
            self.username.setText(rows[0]["username"])
            self.password.setFocus()

    def _first_run(self):
        """Creates an admin account on first run."""
        QtWidgets.QMessageBox.information(
            self, "İlk kurulum",
            "Veritabanında kayıtlı kullanıcı yok.\n\n"
            "Şimdi bir yönetici hesabı oluşturulacak. Bu hesap kullanıcı "
            "ekleyebilir ve sertifika onaylayabilir.",
        )
        dlg = NewUserDialog(self, force_role="admin")
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.username.setText(dlg.created_username)
            self.password.setFocus()
        else:
            self.reject()

    def _try_login(self):
        u = auth.authenticate(self.username.text(), self.password.text())
        if u is None:
            self.message.setText("Kullanıcı adı veya parola hatalı.")
            self.password.clear()
            self.password.setFocus()
            return
        self.user = u
        self.accept()


class NewUserDialog(QtWidgets.QDialog):
    """User creation — used during first-time setup and on the admin page."""

    def __init__(self, parent=None, force_role=None, actor_id=None):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle("Yeni kullanıcı")
        self.setMinimumWidth(400)
        self.actor_id = actor_id
        self.created_username = None

        self.full_name = QtWidgets.QLineEdit()
        self.username = QtWidgets.QLineEdit()
        self.password = QtWidgets.QLineEdit()
        self.password2 = QtWidgets.QLineEdit()
        self.password.setEchoMode(QtWidgets.QLineEdit.Password)
        self.password2.setEchoMode(QtWidgets.QLineEdit.Password)
        self.full_name.setPlaceholderText("Cem Girgin")
        self.username.setPlaceholderText("cgirgin")

        # The role list and descriptions come from the perms table, so the
        # description doesn't go stale when permissions change.
        self.role = QtWidgets.QComboBox()
        for key in (perms.OPERATOR, perms.APPROVER, perms.ADMIN):
            self.role.addItem(perms.ROLE_LABELS[key], key)
        if force_role:
            self.role.setCurrentIndex(self.role.findData(force_role))
            self.role.setEnabled(False)

        self.role_hint = QtWidgets.QLabel("")
        self.role_hint.setProperty("hint", True)
        self.role_hint.setWordWrap(True)
        self.role.currentIndexChanged.connect(self._update_role_hint)
        self._update_role_hint()

        self.message = QtWidgets.QLabel("")
        self.message.setStyleSheet("color: %s;" % theme.colors()["bad"])
        self.message.setWordWrap(True)

        form = QtWidgets.QFormLayout()
        form.addRow("Ad soyad", self.full_name)
        form.addRow("Kullanıcı adı", self.username)
        form.addRow("Parola", self.password)
        form.addRow("Parola (tekrar)", self.password2)
        form.addRow("Rol", self.role)
        form.addRow("", self.role_hint)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Oluştur")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("Vazgeç")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.addLayout(form)
        layout.addWidget(self.message)
        layout.addWidget(buttons)

    def _update_role_hint(self):
        self.role_hint.setText(
            perms.ROLE_DESCRIPTIONS.get(self.role.currentData(), ""))

    def _save(self):
        if not self.full_name.text().strip():
            self.message.setText("Ad soyad boş bırakılamaz.")
            return
        if not self.username.text().strip():
            self.message.setText("Kullanıcı adı boş bırakılamaz.")
            return
        if len(self.password.text()) < 6:
            self.message.setText("Parola en az 6 karakter olmalı.")
            return
        if self.password.text() != self.password2.text():
            self.message.setText("Parolalar eşleşmiyor.")
            return
        try:
            auth.create_user(
                self.username.text(), self.full_name.text(),
                self.password.text(), self.role.currentData(),
                actor_id=self.actor_id,
            )
        except Exception as exc:
            if "UNIQUE" in str(exc):
                self.message.setText("Bu kullanıcı adı zaten kullanılıyor.")
            else:
                self.message.setText("Kaydedilemedi: %s" % exc)
            return
        self.created_username = self.username.text().strip().lower()
        self.accept()
