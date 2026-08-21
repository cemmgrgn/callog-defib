"""Database backup and backup age.

A calibration record with no backup is a record that doesn't exist — but
until now the application itself neither took backups nor said whether one
had been taken.

SQLite's own backup API is used instead of `shutil.copy`: copying the file
while a connection is open in WAL mode leaves out transactions not yet
flushed to the main file — the copy is silently incomplete, and that's only
noticed when a restore is actually needed.
"""

import os
import sqlite3
from datetime import datetime

from . import audit, db

#: How many backups to keep. Older ones are pruned automatically: otherwise
#: a copy piles up on every startup and the data folder grows.
KEEP = 10

#: A backup older than this is considered "stale" and generates a notification.
STALE_DAYS = 7

PREFIX = "callog-"
SUFFIX = ".db"


def backup_dir():
    """The folder is computed at call time — tests change `db.DATA_DIR`."""
    return os.path.join(db.DATA_DIR, "yedek")


def list_backups():
    """List of ``(path, datetime)``, newest first."""
    directory = backup_dir()
    if not os.path.isdir(directory):
        return []
    found = []
    for name in os.listdir(directory):
        if not (name.startswith(PREFIX) and name.endswith(SUFFIX)):
            continue
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        found.append((path, datetime.fromtimestamp(os.path.getmtime(path))))
    found.sort(key=lambda item: item[1], reverse=True)
    return found


def last():
    """The most recent backup: ``(path, datetime)``, or ``None`` if there is none."""
    found = list_backups()
    return found[0] if found else None


def age_days():
    """How many days ago the last backup was taken. ``None`` if there is none."""
    newest = last()
    if newest is None:
        return None
    return (datetime.now() - newest[1]).total_seconds() / 86400.0


def age_text():
    """Short text for the status bar."""
    newest = last()
    if newest is None:
        return "Yedek alınmamış"
    delta = datetime.now() - newest[1]
    minutes = delta.total_seconds() / 60.0
    if minutes < 90:
        return "Son yedek: %d dk önce" % max(1, int(minutes))
    hours = minutes / 60.0
    if hours < 36:
        return "Son yedek: %d saat önce" % int(hours)
    return "Son yedek: %d gün önce" % int(hours / 24)


def create(user_id=None, keep=KEEP):
    """Takes a consistent copy of the database and prunes old ones.

    Doesn't touch the source connection (the backup API works on the read
    side), so it can be called even while a measurement is in progress.
    """
    directory = backup_dir()
    if not os.path.isdir(directory):
        os.makedirs(directory)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = os.path.join(directory, "%s%s%s" % (PREFIX, stamp, SUFFIX))
    # Don't overwrite if a second call happens within the same second
    n = 2
    while os.path.exists(target):
        target = os.path.join(directory, "%s%s-%d%s" % (PREFIX, stamp, n, SUFFIX))
        n += 1

    dest = sqlite3.connect(target)
    try:
        db.connect().backup(dest)
    finally:
        dest.close()

    removed = prune(keep)
    audit.log("db.backup", user_id=user_id,
              detail={"path": target, "size_bytes": os.path.getsize(target),
                      "pruned": removed})
    return target


def prune(keep=KEEP):
    """Keeps the newest `keep` backups, deletes the rest. Returns: number deleted."""
    if keep is None or keep <= 0:
        return 0
    stale = list_backups()[keep:]
    removed = 0
    for path, _when in stale:
        try:
            os.remove(path)
            removed += 1
        except OSError:
            # If the file is locked, we don't count the backup as failed:
            # the actual job was producing the copy, and that's done.
            pass
    return removed
