"""Measurement plan: a session's measurement points.

Until now, it was **one session = one point**. In reality a multimeter is
calibrated at 6-12 points — 10 V, 100 V, 1 kΩ, 100 kΩ, and so on; opening a
separate session for each point meant re-entering the same instrument, the
same reference, and the same environmental conditions ten times over and
producing ten separate certificates.

Backward compatibility is maintained by two rules:

* The function / nominal / tolerance columns in the `sessions` table
  **still exist** and reflect the plan's first point. The history list, the
  trend chart, and the waveform queries all keep working unchanged.
* If `readings.point_id` is NULL, the reading belongs to the **first
  point**. Backfilling old readings would require an UPDATE; the trigger on
  `readings` doesn't allow that, and shouldn't.

Doesn't know about Qt.
"""

from . import db
from .stats import verdict_ok

PENDING = "pending"
RUNNING = "running"
DONE = "done"

STATUS_TR = {PENDING: "bekliyor", RUNNING: "ölçülüyor", DONE: "tamamlandı"}


def list_for(session_id):
    """The session's points, in plan order. Doesn't write anything."""
    return db.query(
        "SELECT * FROM session_points WHERE session_id = ? ORDER BY seq, id",
        (session_id,))


def get(point_id):
    return db.query_one("SELECT * FROM session_points WHERE id = ?", (point_id,))


def create(session_id, seq, function, unit, nominal=None, tolerance=None,
           tolerance_mode="mean", channel=None, notes=None):
    """Adds a point to the plan. Tolerance is always stored as ± (absolute)."""
    return db.execute(
        "INSERT INTO session_points (session_id, seq, function, unit, nominal,"
        " tolerance, tolerance_mode, channel, status, notes)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (session_id, seq, function, unit, nominal,
         abs(tolerance) if tolerance else None,
         tolerance_mode if tolerance_mode in ("mean", "minmax") else "mean",
         channel, PENDING, notes))


def ensure_default(session_id):
    """Builds a single-point plan from its own columns for a session with no plan.

    Needed for sessions opened before this feature existed. It's called
    **explicitly** and on purpose, not hidden inside `list_for`: a read call
    silently writing to the database would be the kind of behavior that's
    hard to trace back — "I opened the list and a record changed."

    Return: the point list (newly created, or already existing).
    """
    rows = list_for(session_id)
    if rows:
        return rows
    s = db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
    if s is None:
        raise ValueError("Oturum bulunamadı: %s" % session_id)
    create(session_id, 1, s["function"], s["unit"], s["nominal"],
           s["tolerance"], s["tolerance_mode"], s["channel"])
    db.execute("UPDATE session_points SET status = ?, started_at = ?,"
               " ended_at = ? WHERE session_id = ?",
               (DONE if s["ended_at"] else PENDING, s["started_at"],
                s["ended_at"], session_id))
    return list_for(session_id)


def sync_session(session_id):
    """Syncs the session columns to match the plan's first point.

    Columns like `sessions.function` are still read in dozens of queries;
    if the session row kept showing the old value after the plan's first
    point changed, the history list and the certificate would diverge.
    """
    rows = list_for(session_id)
    if not rows:
        return
    p = rows[0]
    db.execute(
        "UPDATE sessions SET function = ?, unit = ?, nominal = ?,"
        " tolerance = ?, tolerance_mode = ?, channel = ? WHERE id = ?",
        (p["function"], p["unit"], p["nominal"], p["tolerance"],
         p["tolerance_mode"], p["channel"], session_id))


def start(point_id):
    row = get(point_id)
    if row is None:
        raise ValueError("Ölçüm noktası bulunamadı: %s" % point_id)
    db.execute("UPDATE session_points SET status = ?, started_at = ?"
               " WHERE id = ?", (RUNNING, row["started_at"] or db.utc_now(),
                                 point_id))


def finish(point_id):
    db.execute("UPDATE session_points SET status = ?, ended_at = ?"
               " WHERE id = ?", (DONE, db.utc_now(), point_id))


def next_pending(session_id, after_seq=None):
    """The next unmeasured point; None if there isn't one."""
    for p in list_for(session_id):
        if after_seq is not None and p["seq"] <= after_seq:
            continue
        if p["status"] != DONE:
            return p
    return None


def _values(point, is_first):
    """The point's non-excluded reading values, and the count of excluded ones.

    If ``is_first``, unowned (``point_id IS NULL``) readings are also
    counted toward this point — all the data from old sessions with no plan
    ends up here.
    """
    owner = ("(r.point_id = ? OR r.point_id IS NULL)" if is_first
             else "r.point_id = ?")
    values = [r["value"] for r in db.query(
        "SELECT r.value FROM readings r"
        " LEFT JOIN reading_exclusions e ON e.reading_id = r.id"
        " WHERE r.session_id = ? AND " + owner + " AND e.id IS NULL"
        " ORDER BY r.seq", (point["session_id"], point["id"]))]
    excluded = db.query_one(
        "SELECT COUNT(*) AS n FROM reading_exclusions e"
        " JOIN readings r ON r.id = e.reading_id"
        " WHERE r.session_id = ? AND " + owner,
        (point["session_id"], point["id"]))["n"]
    return values, excluded


def summarize(point, is_first=False):
    """Statistics and pass/fail verdict for a single point.

    The calculation is **identical** to `certificate.collect`: mean, sample
    standard deviation (n-1), u = s/sqrt(n), U = 2u, and `stats.verdict_ok`.
    Computing it two different ways in two places would mean two different
    numbers for the same measurement.
    """
    values, excluded = _values(point, is_first)
    n = len(values)
    mean = sum(values) / n if n else 0.0
    if n >= 2:
        std = (sum((v - mean) ** 2 for v in values) / (n - 1)) ** 0.5
        u_a = std / (n ** 0.5)
    else:
        std = u_a = 0.0

    nominal = point["nominal"]
    tolerance = abs(point["tolerance"]) if point["tolerance"] else None
    mode = (point["tolerance_mode"]
            if point["tolerance_mode"] in ("mean", "minmax") else "mean")
    lo = min(values) if values else None
    hi = max(values) if values else None
    ok = verdict_ok(mode, nominal, tolerance, mean, u_a, lo, hi)

    return {
        "point": point, "seq": point["seq"], "function": point["function"],
        "unit": point["unit"], "channel": point["channel"],
        "status": point["status"],
        "n": n, "excluded": excluded, "mean": mean, "std": std, "u_a": u_a,
        "U": 2 * u_a, "min": lo, "max": hi,
        "nominal": nominal, "tolerance": tolerance, "mode": mode,
        "deviation": (mean - nominal) if nominal is not None else None,
        "result": "info" if ok is None else ("pass" if ok else "fail"),
    }


def collect(session_id):
    """Statistics list for all of the session's points (in plan order)."""
    rows = ensure_default(session_id)
    return [summarize(p, is_first=(i == 0)) for i, p in enumerate(rows)]


def overall_result(summaries):
    """The session's single overall result.

    If even one point fails, **the document fails**: the certificate states
    that the instrument is usable at those points, not that it is on
    average. Points where no verdict can be reached (no nominal/tolerance
    entered) don't spoil the result, but on their own they don't make it
    "pass" either.
    """
    if not summaries:
        return "info"
    if any(s["result"] == "fail" for s in summaries):
        return "fail"
    if any(s["result"] == "pass" for s in summaries):
        return "pass"
    return "info"


def label(summary_or_point):
    """Short label for a point: "10 V (VDC)"."""
    row = summary_or_point
    nominal = row["nominal"]
    unit = row["unit"]
    if nominal is None:
        return "%s" % row["function"]
    return "%g %s (%s)" % (nominal, unit, row["function"])
