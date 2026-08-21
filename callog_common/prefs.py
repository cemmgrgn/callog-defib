"""Per-user preferences.

Theme, font size, and language used to be written to the **machine** via
`QSettings`; on a shared lab PC, users kept changing each other's settings.
Now a preference is tied to the user: whoever logs in finds their own settings.

When there's no known user yet (the login screen), it's called with
`user_id=None` and preferences fall back to `QSettings` — there's no account
to attach to at that stage.

Preferences aren't written to the audit log: a display setting has nothing
to do with traceability, and every theme change would bloat the chain.
"""

from . import db

THEME = "theme"
FONT_SCALE = "font_scale"
LANGUAGE = "language"

#: Defaults — a user with no saved record sees these.
DEFAULTS = {THEME: "light", FONT_SCALE: "1.0", LANGUAGE: "tr"}

#: `QSettings` registry path identifiers — only for machine settings before
#: the login screen (see module docstring); carries no institution name.
_ORG = "CalLog"
_APP = "CalLog"


def _settings():
    from .qt import QtCore

    return QtCore.QSettings(_ORG, _APP)


def get(user_id, key, default=None):
    """Reads a preference. Falls back to the machine setting if there's no user."""
    if default is None:
        default = DEFAULTS.get(key)
    if user_id is None:
        value = _settings().value(key, default)
        return default if value is None else str(value)
    row = db.query_one(
        "SELECT value FROM user_prefs WHERE user_id = ? AND key = ?",
        (user_id, key))
    if row is None or row["value"] is None:
        return default
    return row["value"]


def set(user_id, key, value):
    """Writes the preference (overwrites)."""
    value = "" if value is None else str(value)
    if user_id is None:
        _settings().setValue(key, value)
        return
    db.execute(
        "INSERT INTO user_prefs (user_id, key, value) VALUES (?,?,?)"
        " ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
        (user_id, key, value))


def get_float(user_id, key, default):
    try:
        return float(get(user_id, key, str(default)))
    except (TypeError, ValueError):
        return default


def all_for(user_id):
    """All of the user's preferences, missing ones filled in with defaults."""
    values = dict(DEFAULTS)
    if user_id is None:
        for key in DEFAULTS:
            values[key] = get(None, key)
        return values
    for row in db.query("SELECT key, value FROM user_prefs WHERE user_id = ?",
                        (user_id,)):
        values[row["key"]] = row["value"]
    return values
