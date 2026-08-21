"""Lab identity — organization name, department name, and logo.

This information isn't embedded in the source code: it's kept in the
`lab_settings` table and changed from Administration -> Laboratory tab. The
default setup is institution-agnostic ("Calibration Laboratory") — each lab
enters its own name and logo once, that information stays with the database,
and never mixes into a shared (e.g. GitHub) copy of the source code.

The logo is converted to base64 text and stored as a PNG in the same table:
a single `value TEXT` schema is enough instead of a separate BLOB column,
and `lab_settings` follows the same pattern as the other key/value pairs.
"""

import base64

from . import db

_ORG_KEY = "org_name"
_DEPT_KEY = "department"
_LOGO_KEY = "logo_png_b64"

DEFAULT_ORG_NAME = "Kalibrasyon Laboratuvarı"
DEFAULT_DEPARTMENT = ""


def _get(key, default=""):
    row = db.query_one("SELECT value FROM lab_settings WHERE key = ?", (key,))
    if row is None or row["value"] is None:
        return default
    return row["value"]


def _set(key, value):
    db.execute(
        "INSERT INTO lab_settings (key, value) VALUES (?,?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value))


def org_name():
    return _get(_ORG_KEY, DEFAULT_ORG_NAME) or DEFAULT_ORG_NAME


def department():
    return _get(_DEPT_KEY, DEFAULT_DEPARTMENT)


def header_line():
    """The single line used in certificate/report headers and the login screen."""
    dept = department()
    return "%s — %s" % (org_name(), dept) if dept else org_name()


def initials():
    """Short letter badge used in place of a logo (e.g. 'KL')."""
    words = org_name().split()
    letters = "".join(w[0] for w in words if w)[:4].upper()
    return letters or "?"


def set_org_name(name):
    _set(_ORG_KEY, (name or "").strip())


def set_department(dept):
    _set(_DEPT_KEY, (dept or "").strip())


def logo_bytes():
    """Raw bytes of the saved logo PNG, or None if there isn't one."""
    encoded = _get(_LOGO_KEY, "")
    if not encoded:
        return None
    try:
        return base64.b64decode(encoded)
    except (ValueError, TypeError):
        return None


def set_logo(data):
    """Saves the logo. If `data=None`, the logo is removed."""
    _set(_LOGO_KEY, base64.b64encode(data).decode("ascii") if data else "")
