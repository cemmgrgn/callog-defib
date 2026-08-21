"""User authentication.

The stdlib pbkdf2_hmac is used for password hashing — argon2-cffi's compiler
dependency is an unnecessary risk at packaging time. 200,000 iterations is
more than enough for an in-house application.
"""

import hashlib
import os

from . import audit, db

ITERATIONS = 200_000
ROLES = ("operator", "approver", "admin")


def _hash(password, salt_hex):
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), ITERATIONS
    )
    return dk.hex()


def create_user(username, full_name, password, role="operator", actor_id=None):
    if role not in ROLES:
        raise ValueError("Geçersiz rol: %s" % role)
    salt = os.urandom(16).hex()
    uid = db.execute(
        "INSERT INTO users (username, full_name, role, pwd_hash, salt, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (username.strip().lower(), full_name.strip(), role,
         _hash(password, salt), salt, db.utc_now()),
    )
    audit.log("user.create", user_id=actor_id, entity="user", entity_id=uid,
              detail={"username": username, "role": role})
    return uid


def authenticate(username, password):
    """Returns the user row on success, None otherwise."""
    row = db.query_one(
        "SELECT * FROM users WHERE username = ? AND is_active = 1",
        (username.strip().lower(),),
    )
    if row is None:
        audit.log("auth.login_failed", detail={"username": username, "reason": "no_user"})
        return None
    if not _constant_eq(_hash(password, row["salt"]), row["pwd_hash"]):
        audit.log("auth.login_failed", user_id=row["id"],
                  detail={"username": username, "reason": "bad_password"})
        return None
    audit.log("auth.login", user_id=row["id"], detail={"username": username})
    return row


def _constant_eq(a, b):
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0


def user_count():
    return db.query_one("SELECT COUNT(*) AS n FROM users")["n"]


def list_users():
    return db.query("SELECT * FROM users ORDER BY is_active DESC, full_name")


# --- administration operations ---------------------------------------------------
# There is no user DELETE. A deleted user's past measurements would be
# orphaned and the traceability chain would break. Departing staff are
# deactivated instead.

def set_role(user_id, role, actor_id):
    if role not in ROLES:
        raise ValueError("Geçersiz rol: %s" % role)
    row = db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if row is None:
        raise ValueError("Kullanıcı bulunamadı")
    if row["role"] == role:
        return
    _guard_last_admin(row, new_role=role)
    db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    audit.log("user.role_change", user_id=actor_id, entity="user", entity_id=user_id,
              detail={"username": row["username"], "from": row["role"], "to": role})


def set_active(user_id, is_active, actor_id):
    row = db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if row is None:
        raise ValueError("Kullanıcı bulunamadı")
    if not is_active:
        _guard_last_admin(row, deactivating=True)
    db.execute("UPDATE users SET is_active = ? WHERE id = ?",
               (1 if is_active else 0, user_id))
    audit.log("user.activate" if is_active else "user.deactivate",
              user_id=actor_id, entity="user", entity_id=user_id,
              detail={"username": row["username"]})


def reset_password(user_id, new_password, actor_id):
    row = db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if row is None:
        raise ValueError("Kullanıcı bulunamadı")
    if len(new_password) < 6:
        raise ValueError("Parola en az 6 karakter olmalı")
    salt = os.urandom(16).hex()
    db.execute("UPDATE users SET pwd_hash = ?, salt = ? WHERE id = ?",
               (_hash(new_password, salt), salt, user_id))
    # The password itself is never logged, only the fact that it was changed
    audit.log("user.password_reset", user_id=actor_id, entity="user",
              entity_id=user_id, detail={"username": row["username"]})


def _guard_last_admin(row, new_role=None, deactivating=False):
    """Prevents the last administrator from losing their privileges.

    Otherwise nobody could add a user and the application would become
    unmanageable.
    """
    if row["role"] != "admin" or not row["is_active"]:
        return
    if new_role == "admin":
        return
    others = db.query_one(
        "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND is_active = 1"
        " AND id != ?", (row["id"],))["n"]
    if others == 0:
        raise ValueError(
            "Bu, etkin tek yönetici hesabı. Önce başka bir yönetici tanımlayın."
            if not deactivating else
            "Bu, etkin tek yönetici hesabı. Devre dışı bırakılamaz.")
