"""Notification center — everything that needs attention, in one list.

Certificates awaiting approval, reference instruments nearing the end of
their calibration validity, documents with missing files, and failed login
attempts used to sit on three separate pages; none of them stood out on
their own.

Pruned by permission: showing an operator an approval queue they can't act
on only creates anxiety.

Doesn't know about Qt — the interface just renders the list, the decision is
made here.
"""

import os
from datetime import date, datetime, timedelta, timezone

from . import backup, db, drivers, perms

#: Warns once this many days remain on calibration validity.
CAL_WARN_DAYS = 30

#: The window over which failed login attempts are counted.
LOGIN_WINDOW_HOURS = 24

#: Severity order — the list is sorted by this.
_LEVEL_ORDER = {"bad": 0, "warn": 1, "info": 2}


def _item(level, key, title, detail, count=1, target=None):
    return {"level": level, "key": key, "title": title, "detail": detail,
            "count": count, "target": target}


def collect(user, cal_warn_days=CAL_WARN_DAYS, today=None):
    """Notifications the user should see, most important first.

    The ``target`` field tells the interface which page to open: taking the
    user to the right place when they click a notification removes the
    "what do I do with this warning" question.
    """
    items = []
    items += _pending_certificates(user)
    items += _instrument_calibration(cal_warn_days, today)
    items += _missing_documents()
    items += _failed_logins(user)
    items += _backup_age()
    items.sort(key=lambda i: (_LEVEL_ORDER.get(i["level"], 9), i["title"]))
    return items


def _pending_certificates(user):
    if not perms.can(user, perms.CERT_APPROVE):
        return []
    n = db.query_one(
        "SELECT COUNT(*) AS n FROM certificates"
        " WHERE approved_at IS NULL AND deleted_at IS NULL")["n"]
    if not n:
        return []
    return [_item("warn", "cert_pending",
                  "%d sertifika onay bekliyor" % n,
                  "Onaylanmamış sertifika resmî belge değildir.",
                  count=n, target="approvals")]


def _instrument_calibration(warn_days, today=None):
    """Reference instrument calibration — an expired one invalidates the measurement."""
    today = today or date.today()
    expired, due_soon, unknown = [], [], []
    for r in db.query("SELECT * FROM instruments WHERE is_active = 1 ORDER BY id"):
        if drivers.is_simulated(r["driver"]):
            continue
        label = "%s %s (SN %s)" % (r["brand"], r["model"], r["serial_no"])
        if not r["cal_due"]:
            unknown.append(label)
            continue
        try:
            due = date(*[int(x) for x in r["cal_due"].split("-")])
        except (ValueError, TypeError):
            unknown.append(label)
            continue
        left = (due - today).days
        if left < 0:
            expired.append("%s — %d gün önce doldu" % (label, -left))
        elif left <= warn_days:
            due_soon.append("%s — %d gün kaldı" % (label, left))

    items = []
    if expired:
        items.append(_item(
            "bad", "cal_expired",
            "%d referans cihazın kalibrasyonu dolmuş" % len(expired),
            "Bu cihazlarla alınan ölçüm geçersizdir.\n" + "\n".join(expired),
            count=len(expired), target="admin.instruments"))
    if due_soon:
        items.append(_item(
            "warn", "cal_due_soon",
            "%d referans cihazın kalibrasyonu yaklaşıyor" % len(due_soon),
            "\n".join(due_soon), count=len(due_soon),
            target="admin.instruments"))
    if unknown:
        items.append(_item(
            "warn", "cal_unknown",
            "%d referans cihazın kalibrasyon tarihi girilmemiş" % len(unknown),
            "\n".join(unknown), count=len(unknown),
            target="admin.instruments"))
    return items


def _missing_documents():
    """Documents whose file is missing.

    Only an *existence* check is done, not SHA-256 verification: recomputing
    the hash of dozens of PDFs on every startup would stall the home screen.
    Whether the content changed is verified document by document in the
    device register.
    """
    missing = []
    for r in db.query(
        "SELECT d.title, d.file_path, t.manufacturer, t.model, t.serial_no"
        " FROM dut_documents d JOIN duts t ON t.id = d.dut_id"
    ):
        if not os.path.isfile(r["file_path"]):
            missing.append("%s — %s %s (SN %s)" % (
                r["title"], r["manufacturer"], r["model"], r["serial_no"]))
    if not missing:
        return []
    return [_item("bad", "doc_missing",
                  "%d belgenin dosyası bulunamıyor" % len(missing),
                  "\n".join(missing[:20]), count=len(missing),
                  target="devices")]


def _failed_logins(user):
    """Failed login attempts in the last 24 hours.

    `auth.login_failed` was already being written to the audit log, but
    never shown on any screen; since nobody looked at it, it never amounted
    to more than a record.
    """
    if not perms.can(user, perms.VIEW_AUDIT):
        return []
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=LOGIN_WINDOW_HOURS)).isoformat(timespec="seconds")
    n = db.query_one(
        "SELECT COUNT(*) AS n FROM audit_log"
        " WHERE action = 'auth.login_failed' AND ts_utc >= ?", (cutoff,))["n"]
    if not n:
        return []
    return [_item("warn" if n < 5 else "bad", "login_failed",
                  "Son %d saatte %d başarısız giriş" % (LOGIN_WINDOW_HOURS, n),
                  "Denetim kaydında `auth.login_failed` satırlarına bakın.",
                  count=n, target="admin.audit")]


def _backup_age():
    age = backup.age_days()
    if age is None:
        return [_item("warn", "backup_none", "Veritabanı hiç yedeklenmemiş",
                      "Yönetim menüsünden 'Veritabanını yedekle' ile "
                      "alabilirsiniz.", target="backup")]
    if age >= backup.STALE_DAYS:
        return [_item("warn", "backup_stale",
                      "Son yedek %d gün önce alınmış" % int(age),
                      "Yedeği olmayan bir kalibrasyon kaydı, olmayan kayıttır.",
                      target="backup")]
    return []
