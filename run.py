"""CalLog Defib entry point.

    python run.py
"""

import sys


def _install_excepthook():
    """Shows uncaught errors in a window.

    There's no console when the app is launched with pythonw.exe; an
    uncaught error disappears silently and the user says "I clicked the
    button and nothing happened." This hook makes the error visible.
    """
    import traceback

    from callog_common.qt import QtWidgets

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            box = QtWidgets.QMessageBox()
            box.setIcon(QtWidgets.QMessageBox.Critical)
            box.setWindowTitle("Beklenmeyen hata")
            box.setText("İşlem tamamlanamadı:\n\n%s: %s" % (exc_type.__name__, exc))
            box.setDetailedText(text)
            box.exec()
        except Exception:
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def main():
    import callog_defib  # noqa: F401  (registers defib test modes)
    from callog_common import audit, db, theme
    from callog_common.qt import QtCore, QtWidgets
    from callog_common.ui.login import LoginDialog
    from callog_defib.ui.main_window import MainWindow

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("CalLog Defib")
    app.setOrganizationName("CalLog")

    _install_excepthook()

    # Single-instance lock. Not shared with callog_pulse_echo (separate repo,
    # separate install) — if the two are ever pointed at the same database
    # file on purpose, running both at once is still the operator's call to
    # make, not something this lock can coordinate across processes it
    # doesn't know about.
    lock = QtCore.QLockFile(
        QtCore.QDir.tempPath() + "/callog-defib.lock")
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QtWidgets.QMessageBox.warning(
            None, "CalLog Defib zaten açık",
            "Uygulama zaten çalışıyor.\n\n"
            "Aynı veritabanına iki kopya yazarsa kayıtlar çakışır. "
            "Açık olan pencereyi kullanın.")
        return 0

    db.connect()
    theme.apply(app)   # independent of the OS: default is white

    # Verify the audit chain's integrity on startup
    ok, bad_id, _ = audit.verify_chain()
    if not ok:
        QtWidgets.QMessageBox.critical(
            None, "Denetim kaydı bozuk",
            "Denetim kaydının hash zinciri %d numaralı satırda kırılmış.\n\n"
            "Veritabanı dışarıdan değiştirilmiş olabilir. Yedekten geri dönün "
            "ve durumu lab sorumlusuna bildirin." % bad_id)

    login = LoginDialog()
    if login.exec() != QtWidgets.QDialog.Accepted or login.user is None:
        return 0

    window = MainWindow(login.user)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
