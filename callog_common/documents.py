"""Documents attached to a device.

Most devices that come into the lab come back again and again; their
calibrations from before this application existed sit around as
hand-prepared PDF reports. This module attaches those files to the device
record, so a device's entire history is visible in one place.

The file is **copied** into the application's own folder. The record stays
intact even if the source file is moved, renamed, or the network drive
disconnects.
"""

import hashlib
import os
import shutil

from . import audit, db, perms

#: The folder is computed **at call time**, not at import time: tests and
#: the screenshot script point `db.DATA_DIR` at a temporary folder. A fixed
#: module-level variable would miss that change, and trial output would get
#: written into the real project folder.
def doc_dir():
    return os.path.join(db.DATA_DIR, "belgeler")

DOC_TYPES = (
    ("legacy_cert", "Eski kalibrasyon sertifikası"),
    ("report", "Ölçüm raporu"),
    ("receipt", "Teslim / kabul belgesi"),
    ("other", "Diğer"),
)
DOC_TYPE_TR = dict(DOC_TYPES)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _unique_path(directory, filename):
    """Doesn't overwrite a file with the same name — appends a number instead."""
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, "%s (%d)%s" % (base, n, ext))
        n += 1
    return candidate


def add(dut_id, source_path, title, doc_type, user_id,
        doc_date=None, session_id=None, notes=None):
    """Copies the file into the device folder and creates the record."""
    if not os.path.isfile(source_path):
        raise ValueError("Dosya bulunamadı: %s" % source_path)
    if doc_type not in DOC_TYPE_TR:
        raise ValueError("Geçersiz belge türü: %s" % doc_type)
    title = (title or "").strip() or os.path.basename(source_path)

    target_dir = os.path.join(doc_dir(), str(dut_id))
    if not os.path.isdir(target_dir):
        os.makedirs(target_dir)
    target = _unique_path(target_dir, os.path.basename(source_path))
    shutil.copy2(source_path, target)

    doc_id = db.execute(
        "INSERT INTO dut_documents (dut_id, session_id, title, doc_type, doc_date,"
        " file_path, original_name, sha256, size_bytes, notes, added_by, added_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (dut_id, session_id, title, doc_type, doc_date or None, target,
         os.path.basename(source_path), _sha256(target),
         os.path.getsize(target), (notes or "").strip() or None,
         user_id, db.utc_now()))

    audit.log("document.add", user_id=user_id, entity="dut", entity_id=dut_id,
              detail={"document_id": doc_id, "title": title, "type": doc_type,
                      "original_name": os.path.basename(source_path)})
    return doc_id


def list_for_dut(dut_id):
    return db.query(
        "SELECT d.*, u.full_name AS added_by_name FROM dut_documents d"
        " JOIN users u ON u.id = d.added_by"
        " WHERE d.dut_id = ? ORDER BY COALESCE(d.doc_date, d.added_at) DESC",
        (dut_id,))


def get(doc_id):
    return db.query_one("SELECT * FROM dut_documents WHERE id = ?", (doc_id,))


def verify(doc_id):
    """Whether the file still exists and its content is unchanged.

    Return: (status, message) — status: 'ok' | 'missing' | 'changed' | 'unknown'
    """
    row = get(doc_id)
    if row is None:
        return "unknown", "Kayıt bulunamadı"
    if not os.path.isfile(row["file_path"]):
        return "missing", "Dosya bulunamıyor: %s" % row["file_path"]
    if not row["sha256"]:
        return "unknown", "Özet kaydedilmemiş"
    if _sha256(row["file_path"]) != row["sha256"]:
        return "changed", "Dosya eklendiğinden beri değişmiş"
    return "ok", "Dosya değişmemiş"


def remove(doc_id, user_id, reason):
    """Removes the document's link. The file stays on disk.

    We don't delete the file: this way a document removed by mistake can be
    re-added, and the audit trail keeps pointing at a real file.
    """
    perms.require_actor(user_id, perms.DOC_REMOVE)
    row = get(doc_id)
    if row is None:
        raise ValueError("Belge bulunamadı")
    if not (reason or "").strip():
        raise ValueError("Kaldırma gerekçesi zorunludur")
    db.execute("DELETE FROM dut_documents WHERE id = ?", (doc_id,))
    audit.log("document.remove", user_id=user_id, entity="dut",
              entity_id=row["dut_id"],
              detail={"document_id": doc_id, "title": row["title"],
                      "file_path": row["file_path"], "reason": reason.strip()})


# --- device summary --------------------------------------------------------
def dut_summary(dut_id):
    """A device's entire history: sessions, certificates, documents."""
    dut = db.query_one("SELECT * FROM duts WHERE id = ?", (dut_id,))
    if dut is None:
        raise ValueError("Cihaz bulunamadı: %s" % dut_id)

    sessions = db.query(
        "SELECT s.*, u.full_name AS operator_name, c.cert_no, c.result AS cert_result,"
        " c.approved_at, c.deleted_at AS cert_deleted_at"
        " FROM sessions s"
        " JOIN users u ON u.id = s.operator_id"
        " LEFT JOIN certificates c ON c.session_id = s.id"
        " WHERE s.dut_id = ? AND s.deleted_at IS NULL"
        " ORDER BY s.started_at DESC", (dut_id,))

    counts = db.query_one(
        "SELECT"
        " (SELECT COUNT(*) FROM sessions WHERE dut_id = ?"
        "   AND deleted_at IS NULL) AS sessions,"
        " (SELECT COUNT(*) FROM certificates c JOIN sessions s ON s.id = c.session_id"
        "   WHERE s.dut_id = ? AND c.deleted_at IS NULL) AS certificates,"
        " (SELECT COUNT(*) FROM dut_documents WHERE dut_id = ?) AS documents",
        (dut_id, dut_id, dut_id))

    return {"dut": dut, "sessions": sessions, "documents": list_for_dut(dut_id),
            "counts": counts}


def measurement_series(dut_id):
    """The same measurement point's progression over time (drift analysis).

    Return: {(function, nominal, unit):
            [(date, mean, U, result, session_id, tolerance), ...]}

    Since the same device is calibrated at the same points over the years,
    this series shows the device's drift — something invisible in
    hand-kept spreadsheets.

    Tolerance is carried along too: it's needed to draw the tolerance band
    on the trend chart and to estimate "at this rate, when will it exceed
    the limit." It isn't part of the key — the same point may have been
    measured with a different tolerance two years apart, and that doesn't
    warrant opening two separate series.
    """
    from . import points

    series = {}
    for s in db.query(
        "SELECT id, started_at FROM sessions"
        " WHERE dut_id = ? AND status = 'completed' AND deleted_at IS NULL"
        " ORDER BY started_at", (dut_id,)
    ):
        try:
            summaries = points.collect(s["id"])
        except Exception:
            continue
        # Grouped by **point**, not by session: in a multi-point plan a
        # single session contains both 10 V and 100 V, and those are
        # separate trends.
        for p in summaries:
            if p["nominal"] is None or p["n"] == 0:
                continue
            key = (p["function"], p["nominal"], p["unit"])
            series.setdefault(key, []).append(
                (s["started_at"], p["mean"], p["U"], p["result"], s["id"],
                 p["tolerance"]))
    return series
