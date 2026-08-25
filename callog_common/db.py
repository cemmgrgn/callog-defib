"""SQLite database — schema, connection, and immutability guards.

Why not SQLAlchemy: fewer dependencies mean fewer problems in the
PyInstaller bundle. The schema is kept simple enough to migrate to
PostgreSQL later.
"""

import os
import sys
import sqlite3
from datetime import datetime, timezone

# PyInstaller freezes the source tree into a zipped archive, so __file__
# no longer sits next to a real "repo root" on disk — sys.executable does,
# right next to the .exe (see db.py's own note about the PyInstaller bundle).
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(APP_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "callog.db")

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE,
    full_name   TEXT NOT NULL,
    role        TEXT NOT NULL,          -- operator | approver | admin
    pwd_hash    TEXT NOT NULL,
    salt        TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

-- Referans cihazlar (envanterdeki cihazlar)
CREATE TABLE IF NOT EXISTS instruments (
    id            INTEGER PRIMARY KEY,
    brand         TEXT NOT NULL,
    model         TEXT NOT NULL,
    serial_no     TEXT NOT NULL UNIQUE,
    driver        TEXT NOT NULL,         -- fluke8846a | simulated
    address       TEXT,                  -- VISA adresi
    iface         TEXT,                  -- gpib | serial | usb
    serial_cfg    TEXT,                  -- JSON: baud, parity, ...
    cal_cert_no   TEXT,
    cal_date      TEXT,                  -- ISO tarih: sertifikanin duzenlenme tarihi
    cal_due       TEXT,                  -- ISO tarih: gecerlilik bitisi
    is_active     INTEGER NOT NULL DEFAULT 1,
    notes         TEXT
);

-- Kalibre edilen cihaz (DUT) — elle girilir
CREATE TABLE IF NOT EXISTS duts (
    id            INTEGER PRIMARY KEY,
    company       TEXT NOT NULL,         -- şirket / müşteri
    manufacturer  TEXT NOT NULL,         -- uretici firma
    model         TEXT NOT NULL,
    serial_no     TEXT NOT NULL,
    device_type   TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL
);

-- Cihaza ilistirilen belgeler: eski PDF raporlar, teslim tutanaklari, notlar.
-- Dosya data/belgeler/<dut_id>/ altina kopyalanir; kaynak dosya tasinsa bile
-- kayit kirilmaz. sha256 sonradan degistirilmedigini dogrulamak icindir.
CREATE TABLE IF NOT EXISTS dut_documents (
    id            INTEGER PRIMARY KEY,
    dut_id        INTEGER NOT NULL REFERENCES duts(id),
    session_id    INTEGER REFERENCES sessions(id),   -- istege bagli baglanti
    title         TEXT NOT NULL,
    doc_type      TEXT NOT NULL,       -- legacy_cert | report | receipt | other
    doc_date      TEXT,                -- belgenin kendi tarihi (YYYY-AA-GG)
    file_path     TEXT NOT NULL,
    original_name TEXT,
    sha256        TEXT,
    size_bytes    INTEGER,
    notes         TEXT,
    added_by      INTEGER NOT NULL REFERENCES users(id),
    added_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_documents_dut ON dut_documents(dut_id);

-- Osiloskop dalga yakalamalari.
-- Nokta verisi burada DEGIL, CSV dosyasinda durur: bir tetiklemedeki binlerce
-- nokta ayni buyuklugun tekrarli olcumu degil, tek bir olayin ornekleri.
-- readings tablosuna yazmak ortalama +- U hesabini anlamsiz kilardi.
CREATE TABLE IF NOT EXISTS waveform_captures (
    id                INTEGER PRIMARY KEY,
    session_id        INTEGER REFERENCES sessions(id),
    dut_id            INTEGER REFERENCES duts(id),
    instrument_id     INTEGER NOT NULL REFERENCES instruments(id),
    operator_id       INTEGER NOT NULL REFERENCES users(id),
    captured_at       TEXT NOT NULL,
    trigger_no        INTEGER,
    file_path         TEXT NOT NULL,
    sha256            TEXT,
    size_bytes        INTEGER,
    points            INTEGER,
    channels          TEXT,              -- "CH1_V,CH2_V"
    sample_interval_s REAL,
    notes             TEXT,
    is_simulated      INTEGER NOT NULL DEFAULT 0,
    -- Cihaz ekraninin PNG kopyasi: denetimde "ekranda ne vardi" sorusunun
    -- cevabi. Uygulamanin kendi cizimi bolme ayarlarini ve cihaz uzerindeki
    -- olcum okumalarini icermez.
    screenshot_path   TEXT,
    screenshot_sha256 TEXT,
    test_mode         TEXT,              -- free | defib_biphasic | ...
    divider_ratio     REAL,              -- yuksek gerilim bolucu orani
    load_ohm          REAL,              -- yuk direnci
    setup_json        TEXT,              -- uygulanan olcek/tetikleme ayarlari
    analysis_json     TEXT,              -- cozumleme sonucu
    report_no         TEXT,              -- SOK-CAL-MED-YYYY-NNNN
    report_path       TEXT,
    report_sha256     TEXT,
    series_id         TEXT,              -- seri olcumu birlestiren anahtar
    series_index      INTEGER,           -- seri icindeki sira (1..n)
    series_size       INTEGER,           -- serinin hedeflenen olcum sayisi
    nominal_energy_j  REAL               -- cihazda ayarlanan enerji (J)
);
CREATE INDEX IF NOT EXISTS ix_waveform_dut ON waveform_captures(dut_id);
CREATE INDEX IF NOT EXISTS ix_waveform_inst ON waveform_captures(instrument_id);
-- ix_waveform_series burada değil _migrate() içinde kuruluyor: şema betiği
-- sütun eklenmeden önce çalışıyor ve eski veritabanlarında "no such column"
-- ile düşerdi.

CREATE TABLE IF NOT EXISTS sessions (
    id            INTEGER PRIMARY KEY,
    uuid          TEXT NOT NULL UNIQUE,
    name          TEXT,                  -- varsayilan: sirket · seri no · tarih
    operator_id   INTEGER NOT NULL REFERENCES users(id),
    dut_id        INTEGER NOT NULL REFERENCES duts(id),
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    function      TEXT NOT NULL,         -- VDC, VAC, IDC, RES, VPP, FREQ, ...
    channel       TEXT,                  -- osiloskopta olculen kanal
    unit          TEXT NOT NULL,
    nominal       REAL,
    tolerance     REAL,                  -- her zaman ± (mutlak deger)
    tolerance_mode TEXT DEFAULT 'mean',  -- mean | minmax
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    status        TEXT NOT NULL,         -- running | completed | aborted
    is_simulated  INTEGER NOT NULL DEFAULT 0,
    env_temp      REAL,
    env_rh        REAL,
    env_pressure  REAL,
    env_source    TEXT,                  -- manual | api
    notes         TEXT,
    -- Yumusak silme: okuma verisi ve denetim izi korunur, kayit yalnizca
    -- isaretlenir. Silinmis oturumlari yalnizca yoneticiler gorur.
    deleted_at    TEXT,
    deleted_by    INTEGER REFERENCES users(id),
    delete_reason TEXT
);

-- Olcum plani: bir oturumun olcum noktalari.
--
-- Bir multimetre 10 V, 100 V, 1 kOhm, 100 kOhm gibi 6-12 noktada kalibre
-- ediliyor. Her nokta icin ayri oturum acmak ayni cihaz, ayni referans ve
-- ayni ortam sartlarini on kez yeniden girmek ve on ayri sertifika uretmek
-- demekti.
--
-- `sessions` tablosundaki fonksiyon/nominal/tolerans sutunlari duruyor ve
-- planin ILK noktasini yansitiyor: gecmis listesi, seyir grafigi ve dalga
-- sorgulari degismeden calismaya devam etsin diye.
CREATE TABLE IF NOT EXISTS session_points (
    id             INTEGER PRIMARY KEY,
    session_id     INTEGER NOT NULL REFERENCES sessions(id),
    seq            INTEGER NOT NULL,      -- plandaki sira, 1..n
    function       TEXT NOT NULL,
    unit           TEXT NOT NULL,
    nominal        REAL,
    tolerance      REAL,                  -- her zaman +- (mutlak deger)
    tolerance_mode TEXT DEFAULT 'mean',
    channel        TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending|running|done
    started_at     TEXT,
    ended_at       TEXT,
    notes          TEXT,
    UNIQUE (session_id, seq)
);
CREATE INDEX IF NOT EXISTS ix_points_session ON session_points(session_id, seq);

-- Ham okumalar — SALT EKLEME. Tetikleyicilerle korunur.
--
-- `point_id` NULL ise okuma oturumun ILK noktasina aittir. Eski satirlari
-- doldurmak icin UPDATE gerekirdi ve tetikleyiciler buna zaten izin vermiyor;
-- kural, degismezligi bozmadan geriye donuk uyum sagliyor.
CREATE TABLE IF NOT EXISTS readings (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    point_id    INTEGER REFERENCES session_points(id),
    seq         INTEGER NOT NULL,
    ts_utc      TEXT NOT NULL,
    value       REAL NOT NULL,
    unit        TEXT NOT NULL,
    raw         TEXT,
    elapsed_s   REAL
);
CREATE INDEX IF NOT EXISTS ix_readings_session ON readings(session_id, seq);

-- Aykırı değer DIŞLAMA: okuma silinmez, ayrı tabloda işaretlenir
CREATE TABLE IF NOT EXISTS reading_exclusions (
    id          INTEGER PRIMARY KEY,
    reading_id  INTEGER NOT NULL UNIQUE REFERENCES readings(id),
    user_id     INTEGER NOT NULL REFERENCES users(id),
    reason      TEXT NOT NULL,
    ts_utc      TEXT NOT NULL
);

-- Olcum sablonu: "Fluke 175 · yillik kalibrasyon" gibi hazir bir kalip.
-- Nokta plani JSON olarak duruyor; ayri bir tabloya acilsaydi sablon
-- duzenlemek nokta nokta INSERT/DELETE gerektirirdi ve sablonun kendisi
-- olcum verisi degil, bir form doldurma kisayolu.
CREATE TABLE IF NOT EXISTS measurement_templates (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    driver      TEXT,                  -- hangi surucu icin hazirlandi
    interval_s  REAL,
    nplc        TEXT,
    points_json TEXT NOT NULL,         -- [{function, unit, nominal, ...}, ...]
    notes       TEXT,
    created_by  INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL
);

-- Kisi bazli tercihler.
--
-- Tema, yazi boyutu ve dil `QSettings` ile MAKINEYE yaziliyordu; paylasilan
-- lab PC'sinde kullanicilar birbirinin ayarini degistiriyordu.
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id INTEGER NOT NULL REFERENCES users(id),
    key     TEXT NOT NULL,
    value   TEXT,
    PRIMARY KEY (user_id, key)
);

-- Denetim kaydı — hash zinciri ile korumalı, değiştirilemez
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY,
    ts_utc      TEXT NOT NULL,
    user_id     INTEGER,
    action      TEXT NOT NULL,
    entity      TEXT,
    entity_id   INTEGER,
    detail      TEXT,
    prev_hash   TEXT NOT NULL,
    hash        TEXT NOT NULL
);

-- Sertifika iki kaynaktan gelebilir: coklu-okuma oturumu (session_id) ya da
-- dalga bicimi seri olcumu (series_id). Ikisi ayri tablolarda tutulsaydi
-- onay, yumusak silme ve numara dizisi iki yerde iki turlu yasardi; ayni
-- lab sorumlusu ayni is icin iki farkli ekran kullanirdi.
CREATE TABLE IF NOT EXISTS certificates (
    id             INTEGER PRIMARY KEY,
    session_id     INTEGER UNIQUE REFERENCES sessions(id),
    series_id      TEXT UNIQUE,          -- waveform_captures.series_id
    cert_no        TEXT NOT NULL UNIQUE,
    issued_at      TEXT NOT NULL,
    issued_by      INTEGER NOT NULL REFERENCES users(id),
    approved_by    INTEGER REFERENCES users(id),
    approved_at    TEXT,
    result         TEXT NOT NULL,        -- pass | fail | info
    pdf_path       TEXT,
    pdf_sha256     TEXT,
    -- Yumusak silme: kayit veritabanindan cikmaz, yalnizca isaretlenir.
    -- Yoneticiler silinmis kayitlari gormeye devam eder.
    deleted_at     TEXT,
    deleted_by     INTEGER REFERENCES users(id),
    delete_reason  TEXT,
    -- Tam olarak biri dolu olmali: ikisi de bossa sertifika neyi belgeledigi
    -- belirsiz kalir, ikisi de doluysa iki farkli olcume ayni numara verilir.
    CHECK ((session_id IS NULL) <> (series_id IS NULL))
);

-- Toplu degerlendirme raporu: birden cok seri olcumunu (2 J ... 360 J gibi
-- butun enerji noktalarini) tek belgede degerlendirir.
--
-- Neden `certificates` tablosunda degil: oradaki CHECK kisiti bir belgenin
-- TAM OLARAK bir olcum oturumuna ya da bir seriye ait olmasini sart kosuyor
-- ve bu bilincli bir kural. Toplu rapor tanimi geregi N seriyi kapsiyor;
-- kisiti gevsetmek, "bu belge neyi belgeliyor" sorusunu butun sertifikalar
-- icin belirsizlestirirdi. Ayri tablo, ayri numara dizisi.
CREATE TABLE IF NOT EXISTS summary_reports (
    id          INTEGER PRIMARY KEY,
    report_no   TEXT NOT NULL UNIQUE,
    dut_id      INTEGER REFERENCES duts(id),
    series_json TEXT NOT NULL,          -- kapsanan seri anahtarlari
    result      TEXT NOT NULL,          -- pass | fail | info
    issued_at   TEXT NOT NULL,
    issued_by   INTEGER NOT NULL REFERENCES users(id),
    pdf_path    TEXT,
    pdf_sha256  TEXT
);

-- Laboratuvar kimliği: kurum adı, birim adı, logo. Kaynak koduna gömülü
-- değil, kurulumdan sonra Yönetim sayfasından bir kez girilir; öntanımlı
-- kurulum kurum bağımsızdır.
CREATE TABLE IF NOT EXISTS lab_settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

-- Değişmezlik korumaları: ham veri ve denetim kaydı değiştirilemez / silinemez
"""

_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS trg_readings_no_update
    BEFORE UPDATE ON readings
BEGIN SELECT RAISE(ABORT, 'Ham ölçüm verisi değiştirilemez'); END;

CREATE TRIGGER IF NOT EXISTS trg_readings_no_delete
    BEFORE DELETE ON readings
BEGIN SELECT RAISE(ABORT, 'Ham ölçüm verisi silinemez'); END;

CREATE TRIGGER IF NOT EXISTS trg_audit_no_update
    BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'Denetim kaydı değiştirilemez'); END;

CREATE TRIGGER IF NOT EXISTS trg_audit_no_delete
    BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'Denetim kaydı silinemez'); END;
"""


def utc_now():
    """ISO 8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_conn = None


def connect():
    """Returns the singleton connection, setting up the schema on first call."""
    global _conn
    if _conn is not None:
        return _conn
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR)
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    # Wait instead of immediately raising "database is locked" if another
    # process or a measurement thread is writing at the same time.
    _conn.execute("PRAGMA busy_timeout = 5000")
    _conn.executescript(SCHEMA)
    _conn.executescript(_TRIGGERS)
    _conn.commit()
    _migrate(_conn)
    _seed(_conn)
    _reconcile_paths(_conn)
    return _conn


def _migrate_certificates_series(conn):
    """Adds `series_id` to the `certificates` table and frees up `session_id`.

    Can't be done with ALTER TABLE: the `session_id NOT NULL` constraint
    can't be dropped and a CHECK constraint can't be added. SQLite's
    recommended way is to rebuild the table and move the data over.
    Certificate rows are copied **as-is** here — number, approval, and
    deletion info are preserved; otherwise past certificates would leave a
    gap in the number sequence.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(certificates)")}
    if not cols or "series_id" in cols:
        return

    conn.executescript("""
        PRAGMA foreign_keys = OFF;
        BEGIN;
        CREATE TABLE certificates_yeni (
            id             INTEGER PRIMARY KEY,
            session_id     INTEGER UNIQUE REFERENCES sessions(id),
            series_id      TEXT UNIQUE,
            cert_no        TEXT NOT NULL UNIQUE,
            issued_at      TEXT NOT NULL,
            issued_by      INTEGER NOT NULL REFERENCES users(id),
            approved_by    INTEGER REFERENCES users(id),
            approved_at    TEXT,
            result         TEXT NOT NULL,
            pdf_path       TEXT,
            pdf_sha256     TEXT,
            deleted_at     TEXT,
            deleted_by     INTEGER REFERENCES users(id),
            delete_reason  TEXT,
            CHECK ((session_id IS NULL) <> (series_id IS NULL))
        );
        INSERT INTO certificates_yeni (id, session_id, cert_no, issued_at,
            issued_by, approved_by, approved_at, result, pdf_path, pdf_sha256,
            deleted_at, deleted_by, delete_reason)
        SELECT id, session_id, cert_no, issued_at, issued_by, approved_by,
               approved_at, result, pdf_path, pdf_sha256,
               deleted_at, deleted_by, delete_reason FROM certificates;
        DROP TABLE certificates;
        ALTER TABLE certificates_yeni RENAME TO certificates;
        COMMIT;
        PRAGMA foreign_keys = ON;
    """)


def _migrate(conn):
    """Backfills columns added later onto older databases.

    ALTER TABLE ADD COLUMN doesn't trigger the UPDATE trigger on readings —
    existing rows are left unchanged, only the schema widens.
    """
    def add_column(table, column, ddl):
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        if column not in cols:
            conn.execute("ALTER TABLE %s ADD COLUMN %s" % (table, ddl))
            conn.commit()

    add_column("readings", "elapsed_s", "elapsed_s REAL")
    # Existing rows stay NULL, and NULL means "the session's first point".
    # Backfilling them would require an UPDATE, which the trigger on
    # readings doesn't allow — and shouldn't.
    add_column("readings", "point_id", "point_id INTEGER")
    add_column("sessions", "tolerance_mode", "tolerance_mode TEXT DEFAULT 'mean'")
    add_column("certificates", "deleted_at", "deleted_at TEXT")
    add_column("certificates", "deleted_by", "deleted_by INTEGER")
    add_column("certificates", "delete_reason", "delete_reason TEXT")
    _migrate_certificates_series(conn)
    add_column("duts", "notes", "notes TEXT")
    # The certificate's issue date is kept separate from its expiry
    # (cal_due): once cal_due is in the past, the dashboard flags "EXPIRED",
    # so the issue date can't be stored there too.
    add_column("instruments", "cal_date", "cal_date TEXT")
    add_column("sessions", "name", "name TEXT")
    add_column("sessions", "channel", "channel TEXT")
    for col, ddl in (("screenshot_path", "screenshot_path TEXT"),
                     ("screenshot_sha256", "screenshot_sha256 TEXT"),
                     ("test_mode", "test_mode TEXT"),
                     ("divider_ratio", "divider_ratio REAL"),
                     ("load_ohm", "load_ohm REAL"),
                     ("setup_json", "setup_json TEXT"),
                     ("analysis_json", "analysis_json TEXT"),
                     ("report_no", "report_no TEXT"),
                     ("report_path", "report_path TEXT"),
                     ("report_sha256", "report_sha256 TEXT"),
                     # Series measurement: which capture belongs to which
                     # series, so that e.g. 10 shocks can be combined into
                     # a single report.
                     ("series_id", "series_id TEXT"),
                     ("series_index", "series_index INTEGER"),
                     ("series_size", "series_size INTEGER"),
                     # Energy set on the device. A pass/fail decision can't
                     # be made without it: a measured 5.1 J only makes
                     # sense once you know it was "set to 5 J".
                     ("nominal_energy_j", "nominal_energy_j REAL")):
        add_column("waveform_captures", col, ddl)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_waveform_series"
                 " ON waveform_captures(series_id)")
    add_column("sessions", "deleted_at", "deleted_at TEXT")
    add_column("sessions", "deleted_by", "deleted_by INTEGER")
    add_column("sessions", "delete_reason", "delete_reason TEXT")

    # CREATE TRIGGER IF NOT EXISTS doesn't alter an existing trigger, so
    # old databases have theirs dropped and rebuilt here.
    old = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        " AND sql LIKE '%tablosu%'").fetchall()
    if old:
        for row in old:
            conn.execute("DROP TRIGGER %s" % row["name"])
        conn.executescript(_TRIGGERS)
        conn.commit()


#: Reference devices in the inventory. Since serial_no is unique, this can
#: be run repeatedly with INSERT OR IGNORE — existing databases pick up a
#: new device as soon as it's added to the list.
#:
#: The serial number on the real device rows is a placeholder
#: ("SERI-NO-GIRIN…") since every lab's inventory differs. It must be
#: updated with the real serial number after setup, from Yönetim →
#: Referans cihazlar; `*IDN?` matching ("Otomatik bul") looks at this field.
_INSTRUMENTS = [
    ("Fluke", "8846A", "SERI-NO-GIRIN-GPIB", "fluke8846a", None, "gpib"),
    ("Fluke", "8846A", "SIM-8846A", "simulated", "SIM", "sim"),
    ("Keysight", "DSOX1202A", "SERI-NO-GIRIN-USB", "dsox1202a", None, "usb"),
    ("Keysight", "DSOX1202A", "SIM-DSOX1202A", "simulated_scope", "SIM", "sim"),
]


def _seed(conn):
    """Adds the inventory devices and simulation devices.

    Runs unconditionally rather than only when the table is empty — a
    conditional check would mean a device added to the list later never
    reaches installs that already have data.
    """
    conn.executemany(
        "INSERT OR IGNORE INTO instruments"
        " (brand, model, serial_no, driver, address, iface)"
        " VALUES (?,?,?,?,?,?)",
        _INSTRUMENTS,
    )
    conn.commit()


#: (table, id column, [columns holding absolute paths]) — `_reconcile_paths`
#: looks here for broken paths left over from a moved project folder.
_PATH_TABLES = (
    ("waveform_captures", "id", ("file_path", "screenshot_path", "report_path")),
    ("certificates", "id", ("pdf_path",)),
    ("dut_documents", "id", ("file_path",)),
)


def _reanchor(path):
    """If `path` isn't where it should be, retries it under the current `DATA_DIR`.

    When the project folder is moved (to another disk, a different folder),
    the absolute paths stored in the database keep pointing at the old
    location — so instead of fixing every row by hand, this takes the part
    of the path after ``…\\data\\…`` and re-anchors it under the current
    `DATA_DIR`. Returns the result only if it actually exists on disk,
    otherwise `None`: keeping the "not found" state is safer than writing a
    path that happens to point at some unrelated file.
    """
    marker = os.sep + "data" + os.sep
    idx = path.rfind(marker)
    if idx == -1:
        return None
    candidate = os.path.join(DATA_DIR, path[idx + len(marker):])
    return candidate if os.path.isfile(candidate) else None


def _reconcile_paths(conn):
    """Repairs broken absolute paths left over from a moved project folder.

    Runs on every `connect()` call. If no path is broken, only cheap
    `SELECT`s and `os.path.isfile` checks happen and nothing is written —
    as long as the project folder hasn't moved, this function's cost is
    negligible.
    """
    fixed = 0
    for table, id_col, cols in _PATH_TABLES:
        rows = conn.execute(
            "SELECT %s FROM %s" % (", ".join((id_col,) + cols), table)).fetchall()
        for row in rows:
            updates = {}
            for col in cols:
                value = row[col]
                if value and not os.path.isfile(value):
                    new_value = _reanchor(value)
                    if new_value:
                        updates[col] = new_value
            if updates:
                set_clause = ", ".join("%s = ?" % c for c in updates)
                conn.execute(
                    "UPDATE %s SET %s WHERE %s = ?"
                    % (table, set_clause, id_col),
                    tuple(updates.values()) + (row[id_col],))
                fixed += 1
    if fixed:
        conn.commit()
        from . import audit  # imported here to avoid a circular import
        audit.log("db.path_reconcile", detail={"onarilan_satir": fixed})
    return fixed


def query(sql, params=()):
    return connect().execute(sql, params).fetchall()


def query_one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=()):
    conn = connect()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid
