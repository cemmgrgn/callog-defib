"""Measurement templates — ready-made patterns like "Fluke 175 · annual calibration".

The same device is calibrated at the same points every year; rewriting the
points, tolerances, and reading interval each time is both a waste of time
and a source of error. **A manually entered tolerance is the most likely
data-entry mistake** — entering and saving it correctly once is safer than
retyping it every session.

A template isn't measurement data, it's a form-filling shortcut: so there's
no soft delete, deleting it really deletes it. Sessions produced from a
template aren't affected — the plan is copied into the session, no link is
kept. If a link were kept, a later change to the template would look like it
had altered the plan of a past certificate.

Doesn't know about Qt.
"""

import json

from . import audit, db


def list_all(driver=None):
    """Templates, sorted by name. If `driver` is given, restricted to it and generic ones."""
    if driver:
        return db.query(
            "SELECT * FROM measurement_templates"
            " WHERE driver IS NULL OR driver = ? ORDER BY name", (driver,))
    return db.query("SELECT * FROM measurement_templates ORDER BY name")


def get(template_id):
    return db.query_one("SELECT * FROM measurement_templates WHERE id = ?",
                        (template_id,))


def by_name(name):
    return db.query_one("SELECT * FROM measurement_templates WHERE name = ?",
                        ((name or "").strip(),))


def points_of(row):
    """The template's point list. Empty list on malformed JSON — the
    template can't be applied, but the application doesn't crash."""
    if row is None or not row["points_json"]:
        return []
    try:
        data = json.loads(row["points_json"])
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def save(name, points, driver=None, interval_s=None, nplc=None, notes=None,
         user_id=None):
    """Saves the template; **overwrites** if one with the same name exists.

    The name is unique: having two templates named "Fluke 175 annual" would
    make it ambiguous which one gets applied.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Şablon adı zorunludur")
    if not points:
        raise ValueError("Boş plan şablon olarak kaydedilemez")

    payload = json.dumps(points, ensure_ascii=False)
    existing = by_name(name)
    if existing is not None:
        db.execute(
            "UPDATE measurement_templates SET driver = ?, interval_s = ?,"
            " nplc = ?, points_json = ?, notes = ? WHERE id = ?",
            (driver, interval_s, nplc, payload, notes, existing["id"]))
        tid, action = existing["id"], "template.update"
    else:
        tid = db.execute(
            "INSERT INTO measurement_templates (name, driver, interval_s, nplc,"
            " points_json, notes, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (name, driver, interval_s, nplc, payload, notes, user_id,
             db.utc_now()))
        action = "template.create"
    audit.log(action, user_id=user_id, entity="template", entity_id=tid,
              detail={"name": name, "points": len(points), "driver": driver})
    return tid


def delete(template_id, user_id=None):
    row = get(template_id)
    if row is None:
        raise ValueError("Şablon bulunamadı")
    db.execute("DELETE FROM measurement_templates WHERE id = ?", (template_id,))
    audit.log("template.delete", user_id=user_id, entity="template",
              entity_id=template_id, detail={"name": row["name"]})
