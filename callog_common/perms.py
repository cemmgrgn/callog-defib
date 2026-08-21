"""Role-based permissions — the single source of truth.

Permission checks used to be scattered across interface files (things like
`user["role"] in ("approver", "admin")`). It was easy to miss a spot when
adding a new page, and understanding which role could see what meant reading
six files. Now every rule lives in the table below.

The interface **hides**, the operation layer **rejects**. Both are needed:
a hidden button can still be triggered via a keyboard shortcut or a direct
call.

Roles don't stack — each role's permissions are written out explicitly.
Building one role on top of another ("admin = approver + more") looks
shorter at first glance, but forces the answer to "why can the lab manager
delete the audit log?" to be hunted for across two definitions.
"""

OPERATOR = "operator"
APPROVER = "approver"
ADMIN = "admin"

ROLE_LABELS = {
    OPERATOR: "Operatör",
    APPROVER: "Lab sorumlusu",
    ADMIN: "Yönetici",
}

ROLE_DESCRIPTIONS = {
    OPERATOR: "Ölçüm yapar, sertifika taslağı üretir.",
    APPROVER: "Ölçüm yapar, sertifika onaylar ve kayıt siler.",
    ADMIN: "Her şeye erişir; kullanıcı ve referans cihaz yönetir.",
}

# --- permission names --------------------------------------------------------
# Page visibility
VIEW_DEVICES = "view.devices"
VIEW_HISTORY = "view.history"
VIEW_ADMIN = "view.admin"           # the Administration page itself
VIEW_USERS = "view.users"           # user list
VIEW_AUDIT = "view.audit"           # audit log
VIEW_INSTRUMENTS = "view.instruments"

# Operations
SESSION_CREATE = "session.create"
SESSION_RENAME = "session.rename"
SESSION_DELETE = "session.delete"
SESSION_RESTORE = "session.restore"
SESSION_VIEW_DELETED = "session.view_deleted"

CERT_CREATE = "cert.create"
CERT_APPROVE = "cert.approve"
CERT_DELETE = "cert.delete"
CERT_RESTORE = "cert.restore"
CERT_VIEW_DELETED = "cert.view_deleted"

DOC_ADD = "doc.add"
DOC_REMOVE = "doc.remove"

VIEW_WAVEFORM = "view.waveform"
WAVEFORM_CAPTURE = "waveform.capture"

VIEW_VELOCITY = "view.velocity"
VELOCITY_MEASURE = "velocity.measure"

USER_MANAGE = "user.manage"
INSTRUMENT_EDIT = "instrument.edit"
AUDIT_VERIFY = "audit.verify"
BRANDING_EDIT = "branding.edit"

# --- table ---------------------------------------------------------------
# The roles listed against a permission have that permission.
_TABLE = {
    VIEW_DEVICES:         (OPERATOR, APPROVER, ADMIN),
    VIEW_HISTORY:         (OPERATOR, APPROVER, ADMIN),
    VIEW_INSTRUMENTS:     (OPERATOR, APPROVER, ADMIN),
    VIEW_ADMIN:           (APPROVER, ADMIN),
    VIEW_USERS:           (ADMIN,),
    VIEW_AUDIT:           (APPROVER, ADMIN),

    SESSION_CREATE:       (OPERATOR, APPROVER, ADMIN),
    SESSION_RENAME:       (OPERATOR, APPROVER, ADMIN),
    SESSION_DELETE:       (APPROVER, ADMIN),
    SESSION_RESTORE:      (ADMIN,),
    SESSION_VIEW_DELETED: (ADMIN,),

    CERT_CREATE:          (OPERATOR, APPROVER, ADMIN),
    CERT_APPROVE:         (APPROVER, ADMIN),
    CERT_DELETE:          (APPROVER, ADMIN),
    CERT_RESTORE:         (ADMIN,),
    CERT_VIEW_DELETED:    (ADMIN,),

    DOC_ADD:              (OPERATOR, APPROVER, ADMIN),
    DOC_REMOVE:           (APPROVER, ADMIN),

    VIEW_WAVEFORM:        (OPERATOR, APPROVER, ADMIN),
    WAVEFORM_CAPTURE:     (OPERATOR, APPROVER, ADMIN),

    VIEW_VELOCITY:        (OPERATOR, APPROVER, ADMIN),
    VELOCITY_MEASURE:     (OPERATOR, APPROVER, ADMIN),

    USER_MANAGE:          (ADMIN,),
    INSTRUMENT_EDIT:      (ADMIN,),
    AUDIT_VERIFY:         (APPROVER, ADMIN),
    BRANDING_EDIT:        (ADMIN,),
}

# The explanation shown to the user when a permission is denied. A generic
# "you don't have permission" message leaves the user not knowing who to ask.
_DENIAL = {
    SESSION_DELETE: "Oturum silmek için lab sorumlusu yetkisi gerekiyor.",
    SESSION_RESTORE: "Silinmiş oturumu yalnızca yönetici geri alabilir.",
    CERT_APPROVE: "Sertifikayı yalnızca lab sorumlusu onaylayabilir.",
    CERT_DELETE: "Sertifika silmek için lab sorumlusu yetkisi gerekiyor.",
    CERT_RESTORE: "Silinmiş sertifikayı yalnızca yönetici geri alabilir.",
    DOC_REMOVE: "Belge kaldırmak için lab sorumlusu yetkisi gerekiyor.",
    USER_MANAGE: "Kullanıcı yönetimi yalnızca yöneticilere açıktır.",
    INSTRUMENT_EDIT: "Referans cihaz bilgisini yalnızca yönetici düzenleyebilir.",
    BRANDING_EDIT: "Laboratuvar kimliğini yalnızca yönetici düzenleyebilir.",
    VIEW_AUDIT: "Denetim kaydını yalnızca lab sorumlusu ve yönetici görebilir.",
    VIEW_USERS: "Kullanıcı listesini yalnızca yöneticiler görebilir.",
}


# --- on-screen display ----------------------------------------------------
#: A grouped, human-readable list of permissions. The order is the on-screen
#: order.
#:
#: The table already exists above but reads by its constant names
#: (`cert.view_deleted`); what's needed when assigning a role to new staff,
#: or when an auditor asks "how does authorization work?", is a readable
#: label for these names.
PERMISSION_GROUPS = (
    ("Sayfa görünürlüğü", (
        (VIEW_DEVICES, "Kalibre edilen cihazlar"),
        (VIEW_HISTORY, "Geçmiş kayıtlar"),
        (VIEW_INSTRUMENTS, "Referans cihaz listesi"),
        (VIEW_WAVEFORM, "Dalga yakalama sayfası"),
        (VIEW_VELOCITY, "Ses hızı sayfası"),
        (VIEW_ADMIN, "Yönetim sayfası"),
        (VIEW_USERS, "Kullanıcı listesi"),
        (VIEW_AUDIT, "Denetim kaydı"),
    )),
    ("Ölçüm oturumu", (
        (SESSION_CREATE, "Oturum başlatma"),
        (SESSION_RENAME, "Yeniden adlandırma"),
        (SESSION_DELETE, "Silme (yumuşak)"),
        (SESSION_RESTORE, "Silinmişi geri alma"),
        (SESSION_VIEW_DELETED, "Silinmişleri görme"),
    )),
    ("Sertifika", (
        (CERT_CREATE, "Üretme"),
        (CERT_APPROVE, "Onaylama"),
        (CERT_DELETE, "Silme (yumuşak) / geri çevirme"),
        (CERT_RESTORE, "Silinmişi geri alma"),
        (CERT_VIEW_DELETED, "Silinmişleri görme"),
    )),
    ("Belge ve dalga", (
        (DOC_ADD, "Cihaza belge iliştirme"),
        (DOC_REMOVE, "Belge bağlantısını kaldırma"),
        (WAVEFORM_CAPTURE, "Dalga yakalama"),
        (VELOCITY_MEASURE, "Ses hızı ölçümü"),
    )),
    ("Yönetim", (
        (USER_MANAGE, "Kullanıcı yönetimi"),
        (INSTRUMENT_EDIT, "Referans cihaz düzenleme"),
        (AUDIT_VERIFY, "Denetim zinciri doğrulama"),
        (BRANDING_EDIT, "Laboratuvar kimliği düzenleme"),
    )),
)

#: Order of the matrix columns
ROLE_ORDER = (OPERATOR, APPROVER, ADMIN)


def matrix():
    """Rows of ``(group, permission, label, {role: bool})``.

    `_TABLE` remains the single source of truth: if the screen kept a
    separate list, a permission change would let the table and the screen
    drift apart, and the screen would show wrong information.
    """
    rows = []
    for group, entries in PERMISSION_GROUPS:
        for permission, label in entries:
            rows.append((group, permission, label,
                         {role: can(role, permission) for role in ROLE_ORDER}))
    return rows


def role_of(user):
    """Extracts the role from a user row or a plain string."""
    if user is None:
        return None
    if isinstance(user, str):
        return user
    try:
        return user["role"]
    except (KeyError, IndexError, TypeError):
        return getattr(user, "role", None)


def can(user, permission):
    allowed = _TABLE.get(permission)
    if allowed is None:
        raise KeyError("Tanımsız yetki: %s" % permission)
    return role_of(user) in allowed


def denial_message(permission):
    return _DENIAL.get(permission, "Bu işlem için yetkiniz yok.")


def label(role):
    return ROLE_LABELS.get(role, role or "—")


def require(user, permission):
    """Raises PermissionError if the permission is missing.

    The interface already hides the button; this is the second layer against
    paths where the hiding gets bypassed (a shortcut, a direct call, a menu
    added later).
    """
    if not can(user, permission):
        raise PermissionError(denial_message(permission))


def require_actor(user_id, permission):
    """For the operation layer: reads the role from the user id and checks it.

    Functions like `sessions.soft_delete` already take `user_id`; reading
    the role here instead of having the caller pass it makes it impossible
    for a caller to pass the wrong role.
    """
    from . import db
    row = db.query_one("SELECT role FROM users WHERE id = ?", (user_id,))
    if row is None:
        raise PermissionError("İşlemi yapan kullanıcı bulunamadı.")
    if not can(row["role"], permission):
        raise PermissionError(denial_message(permission))
