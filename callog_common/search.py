"""General search — serial no, certificate no, company, or session name, from one box.

What's searched for is usually "I have a serial number, what have we done
with this device". Until now that meant finding the right page first, then
the right filter.

Results come back **with their kind** (`kind`) and say where to go
(`target`): the interface layer doesn't have to work out again which page
shows which record.

Doesn't know about Qt.
"""

from . import db

#: Kind order — results are grouped in this order in the list. Certificate
#: is first: someone with a number in hand is looking for the document, not
#: the device card.
KIND_ORDER = ("certificate", "series", "session", "dut", "instrument")

KIND_TR = {
    "certificate": "Sertifika",
    "series": "Dalga serisi",
    "session": "Ölçüm oturumu",
    "dut": "Kalibre edilen cihaz",
    "instrument": "Referans cihaz",
}

#: Maximum results of a single kind. The limit is per kind: typing "SN-2024"
#: shouldn't return 200 sessions and push the device the user is looking for
#: off the list.
PER_KIND = 8


def _hit(kind, title, subtitle, target, ident):
    return {"kind": kind, "title": title, "subtitle": subtitle,
            "target": target, "id": ident}


def find(term, per_kind=PER_KIND):
    """Records matching the term, in kind order.

    Empty list for an empty or single-character term: a single letter would
    return everything and make the list unusable.
    """
    term = (term or "").strip()
    if len(term) < 2:
        return []
    like = "%" + term + "%"

    hits = []
    hits += _certificates(like, per_kind)
    hits += _series(like, per_kind)
    hits += _sessions(like, per_kind)
    hits += _duts(like, per_kind)
    hits += _instruments(like, per_kind)
    hits.sort(key=lambda h: KIND_ORDER.index(h["kind"]))
    return hits


def _certificates(like, limit):
    rows = db.query(
        "SELECT c.id, c.cert_no, c.issued_at, c.result, c.approved_at,"
        " c.deleted_at, d.manufacturer, d.model, d.serial_no, d.company"
        " FROM certificates c"
        " LEFT JOIN sessions s ON s.id = c.session_id"
        " LEFT JOIN waveform_captures w ON w.series_id = c.series_id"
        " LEFT JOIN duts d ON d.id = COALESCE(s.dut_id, w.dut_id)"
        " WHERE c.cert_no LIKE ? OR d.serial_no LIKE ? OR d.company LIKE ?"
        " GROUP BY c.id ORDER BY c.id DESC LIMIT ?",
        (like, like, like, limit))
    out = []
    for r in rows:
        state = ("silinmiş" if r["deleted_at"] else
                 ("onaylandı" if r["approved_at"] else "onay bekliyor"))
        out.append(_hit(
            "certificate", r["cert_no"],
            "%s %s (SN %s) · %s · %s" % (
                r["manufacturer"] or "?", r["model"] or "?",
                r["serial_no"] or "?", (r["issued_at"] or "")[:10], state),
            "certificate", r["cert_no"]))
    return out


def _series(like, limit):
    rows = db.query(
        "SELECT w.series_id, MIN(w.captured_at) AS first_at, COUNT(*) AS n,"
        " MAX(w.dut_id) AS dut_id, MAX(w.report_no) AS report_no,"
        " MAX(d.manufacturer) AS manufacturer, MAX(d.model) AS model,"
        " MAX(d.serial_no) AS serial_no"
        " FROM waveform_captures w LEFT JOIN duts d ON d.id = w.dut_id"
        " WHERE w.series_id IS NOT NULL"
        "   AND (w.series_id LIKE ? OR w.report_no LIKE ? OR d.serial_no LIKE ?)"
        " GROUP BY w.series_id ORDER BY MIN(w.captured_at) DESC LIMIT ?",
        (like, like, like, limit))
    return [_hit("series", r["report_no"] or r["series_id"],
                 "%s %s (SN %s) · %d şok · %s" % (
                     r["manufacturer"] or "?", r["model"] or "?",
                     r["serial_no"] or "?", r["n"],
                     (r["first_at"] or "")[:10]),
                 "dut", r["dut_id"])
            for r in rows]


def _sessions(like, limit):
    rows = db.query(
        "SELECT s.id, s.name, s.started_at, s.function, s.status,"
        " d.manufacturer, d.model, d.serial_no, d.company"
        " FROM sessions s JOIN duts d ON d.id = s.dut_id"
        " WHERE s.deleted_at IS NULL"
        "   AND (s.name LIKE ? OR d.serial_no LIKE ? OR d.company LIKE ?"
        "        OR d.model LIKE ?)"
        " ORDER BY s.id DESC LIMIT ?", (like, like, like, like, limit))
    from . import sessions as session_svc

    return [_hit("session", session_svc.display_name(r),
                 "#%d · %s · %s %s (SN %s)" % (
                     r["id"], (r["started_at"] or "")[:10], r["manufacturer"],
                     r["model"], r["serial_no"]),
                 "session", r["id"])
            for r in rows]


def _duts(like, limit):
    rows = db.query(
        "SELECT d.*,"
        " (SELECT COUNT(*) FROM sessions s WHERE s.dut_id = d.id) AS n_sessions"
        " FROM duts d"
        " WHERE d.serial_no LIKE ? OR d.model LIKE ? OR d.manufacturer LIKE ?"
        "    OR d.company LIKE ?"
        " ORDER BY d.id DESC LIMIT ?", (like, like, like, like, limit))
    return [_hit("dut", "%s %s — %s" % (r["manufacturer"], r["model"],
                                        r["serial_no"]),
                 "%s · %d ölçüm oturumu" % (r["company"], r["n_sessions"]),
                 "dut", r["id"])
            for r in rows]


def _instruments(like, limit):
    rows = db.query(
        "SELECT * FROM instruments"
        " WHERE serial_no LIKE ? OR model LIKE ? OR brand LIKE ?"
        "    OR cal_cert_no LIKE ?"
        " ORDER BY id LIMIT ?", (like, like, like, like, limit))
    return [_hit("instrument", "%s %s — %s" % (r["brand"], r["model"],
                                               r["serial_no"]),
                 "Sertifika: %s · Geçerlilik: %s" % (r["cal_cert_no"] or "—",
                                                     r["cal_due"] or "—"),
                 "admin.instruments", r["id"])
            for r in rows]
