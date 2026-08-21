"""Audit log — hash chain.

Each row contains the hash of the one before it. If the database is
tampered with from outside, the chain breaks and verify_chain() detects it.
This is our strongest technical argument against Excel: who did what and
when — provably.
"""

import hashlib
import json

from . import db

GENESIS = "0" * 64


def _row_hash(prev_hash, ts, user_id, action, entity, entity_id, detail):
    payload = json.dumps(
        [prev_hash, ts, user_id, action, entity, entity_id, detail],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def log(action, user_id=None, entity=None, entity_id=None, detail=None):
    """Writes an event to the audit log and extends the hash chain."""
    if detail is not None and not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False, sort_keys=True)

    conn = db.connect()
    last = conn.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    prev = last["hash"] if last else GENESIS
    ts = db.utc_now()
    h = _row_hash(prev, ts, user_id, action, entity, entity_id, detail)
    conn.execute(
        "INSERT INTO audit_log (ts_utc, user_id, action, entity, entity_id, detail,"
        " prev_hash, hash) VALUES (?,?,?,?,?,?,?,?)",
        (ts, user_id, action, entity, entity_id, detail, prev, h),
    )
    conn.commit()
    return h


def verify_chain():
    """Verifies the chain from start to end.

    Returns: (is_valid, broken_row_id or None, number_of_rows_checked)
    """
    rows = db.query("SELECT * FROM audit_log ORDER BY id")
    prev = GENESIS
    for r in rows:
        if r["prev_hash"] != prev:
            return False, r["id"], len(rows)
        expected = _row_hash(
            prev, r["ts_utc"], r["user_id"], r["action"],
            r["entity"], r["entity_id"], r["detail"],
        )
        if expected != r["hash"]:
            return False, r["id"], len(rows)
        prev = r["hash"]
    return True, None, len(rows)
