"""Measurement session operations: naming and soft delete.

Why the delete is "soft": raw readings in the `readings` table are protected
by triggers and can't actually be deleted anyway. Truly deleting a session
would leave those readings orphaned and create a gap in the audit trail. So
a session is only marked deleted; administrators keep seeing it and can
restore it.
"""

from . import audit, db, perms

#: Default session name: "Company · Serial no · YYYY-MM-DD HH:MM"
NAME_SEPARATOR = " · "


def default_name(dut_id, started_at=None):
    """Builds the default session name from company, serial no, and date-time."""
    dut = db.query_one("SELECT company, serial_no FROM duts WHERE id = ?", (dut_id,))
    company = (dut["company"] if dut else "").strip() or "Bilinmeyen firma"
    serial = (dut["serial_no"] if dut else "").strip() or "seri no yok"

    stamp = started_at or db.utc_now()
    # Reduce the ISO timestamp to a locally readable form: "2026-08-06T13:45:02+00:00"
    stamp = stamp.replace("T", " ")[:16]

    return NAME_SEPARATOR.join((company, serial, stamp))


def ensure_name(session_id):
    """Writes the default name to a session whose name is empty, and returns it."""
    row = db.query_one("SELECT name, dut_id, started_at FROM sessions WHERE id = ?",
                       (session_id,))
    if row is None:
        raise ValueError("Oturum bulunamadı: %s" % session_id)
    if (row["name"] or "").strip():
        return row["name"]
    name = default_name(row["dut_id"], row["started_at"])
    db.execute("UPDATE sessions SET name = ? WHERE id = ?", (name, session_id))
    return name


def display_name(row):
    """Name to show in the table — produces a sensible fallback if the record has none."""
    name = (row["name"] or "").strip() if "name" in row.keys() else ""
    if name:
        return name
    return "Oturum #%s" % row["id"]


def rename(session_id, new_name, user_id):
    """Renames the session. An empty name reverts to the default."""
    row = db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
    if row is None:
        raise ValueError("Oturum bulunamadı")
    if row["deleted_at"]:
        raise ValueError("Silinmiş bir oturum yeniden adlandırılamaz")

    new_name = (new_name or "").strip()
    if not new_name:
        new_name = default_name(row["dut_id"], row["started_at"])
    if new_name == (row["name"] or ""):
        return new_name

    db.execute("UPDATE sessions SET name = ? WHERE id = ?", (new_name, session_id))
    audit.log("session.rename", user_id=user_id, entity="session",
              entity_id=session_id,
              detail={"from": row["name"], "to": new_name})
    return new_name


def soft_delete(session_id, user_id, reason):
    """Marks the session as deleted.

    A session with a certificate can't be deleted: dropping a measurement
    that has been assigned a certificate number out of the record breaks
    traceability. The certificate must be deleted first.
    """
    perms.require_actor(user_id, perms.SESSION_DELETE)
    row = db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
    if row is None:
        raise ValueError("Oturum bulunamadı")
    if row["deleted_at"]:
        raise ValueError("Bu oturum zaten silinmiş")
    if not (reason or "").strip():
        raise ValueError("Silme gerekçesi zorunludur")
    if row["status"] == "running":
        raise ValueError("Devam eden bir oturum silinemez, önce bitirin")

    cert = db.query_one(
        "SELECT cert_no FROM certificates"
        " WHERE session_id = ? AND deleted_at IS NULL", (session_id,))
    if cert:
        raise ValueError(
            "Bu oturumun geçerli bir sertifikası var (%s).\n"
            "Önce sertifikayı silin." % cert["cert_no"])

    db.execute(
        "UPDATE sessions SET deleted_at = ?, deleted_by = ?, delete_reason = ?"
        " WHERE id = ?", (db.utc_now(), user_id, reason.strip(), session_id))
    audit.log("session.delete", user_id=user_id, entity="session",
              entity_id=session_id,
              detail={"name": row["name"], "reason": reason.strip()})


def restore(session_id, user_id):
    """Restores a deleted session (administrator only)."""
    perms.require_actor(user_id, perms.SESSION_RESTORE)
    row = db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
    if row is None or not row["deleted_at"]:
        raise ValueError("Silinmiş bir oturum değil")
    db.execute(
        "UPDATE sessions SET deleted_at = NULL, deleted_by = NULL,"
        " delete_reason = NULL WHERE id = ?", (session_id,))
    audit.log("session.restore", user_id=user_id, entity="session",
              entity_id=session_id, detail={"name": row["name"]})
