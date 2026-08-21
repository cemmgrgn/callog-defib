"""Waveform capture: CSV writing and the capture ledger.

Why this doesn't get written to the ``readings`` table: the thousands of
points that come in on a single trigger are not *repeated measurements of
the same quantity* — they're samples of a single event. Storing them as
reading rows would make the mean ± U calculation meaningless and would grow
the database by tens of thousands of rows on every trigger.

Instead, the capture stays a **file**, and the database holds only its
metadata: which instrument, who, when, how many points, which channels, and
the file's SHA-256 hash. The hash means a CSV that's altered afterward gets
noticed — the rule that raw measurement data must be immutable applies here
too.
"""

import csv
import hashlib
import json
import os
import shutil
from datetime import datetime

from . import audit, db

#: The capture folder is computed **at call time**, not at import time: tests
#: and the screenshot script point `db.DATA_DIR` at a temporary folder. If a
#: fixed module-level variable were used, that change would arrive too late
#: and trial captures would get written into the real project folder.
def capture_root():
    return os.path.join(db.DATA_DIR, "dalgalar")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def default_dir(dut_id=None):
    """Folder captures are written to. Its own subfolder if a device is selected."""
    if dut_id:
        return os.path.join(capture_root(), str(dut_id))
    return os.path.join(capture_root(), "genel")


def align(times, columns):
    """Trims channels to a common length.

    Channels can arrive with different record lengths (one was toggled off
    and back on, or the memory depth changed). Writing arrays of different
    lengths side by side silently skews the CSV: the later rows end up
    matched to the wrong time.
    """
    lengths = [len(times)] + [len(v) for v in columns.values()]
    n = min(lengths)
    return times[:n], {k: v[:n] for k, v in columns.items()}


def write_csv(path, times, columns):
    """columns: {"CH1_V": array, "CH2_V": array} — shared time axis."""
    times, columns = align(times, columns)
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["time_s"] + list(columns.keys()))
        names = list(columns.keys())
        for i in range(len(times)):
            writer.writerow(["%.12g" % times[i]]
                            + ["%.9g" % columns[name][i] for name in names])
    return len(times)


def channel_stats(values):
    """Channel summary for the table and a quick visual check."""
    if len(values) == 0:
        return {"min": None, "max": None, "vpp": None, "mean": None}
    lo = float(min(values))
    hi = float(max(values))
    return {"min": lo, "max": hi, "vpp": hi - lo,
            "mean": float(sum(values) / len(values))}


def sample_interval(times):
    """Sampling interval (s). None if there aren't enough points."""
    if len(times) < 2:
        return None
    return float((times[-1] - times[0]) / (len(times) - 1))


def save(times, columns, instrument_id, operator_id, dut_id=None,
         session_id=None, outdir=None, prefix="yakalama", trigger_no=None,
         notes=None, is_simulated=False, screenshot=None, test_mode=None,
         divider_ratio=None, load_ohm=None, setup=None, analysis=None,
         series_id=None, series_index=None, series_size=None,
         nominal_energy_j=None):
    """Writes the capture to CSV and records its metadata in the database.

    screenshot: temporary path of a PNG grabbed from the instrument. If
    given, it's moved next to the CSV under the same base name, so the two
    don't end up separated.

    Return: id of the inserted record.
    """
    times, columns = align(times, columns)
    if len(times) == 0:
        raise ValueError("Boş yakalama kaydedilemez")

    directory = outdir or default_dir(dut_id)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    seq = trigger_no if trigger_no is not None else next_index(directory, prefix)
    base = "%s_%04d_%s" % (prefix, seq, stamp)
    path = os.path.join(directory, base + ".csv")

    points = write_csv(path, times, columns)

    # The screenshot carries the same base name as the CSV, so it's clear
    # from the filename alone that the two files sitting side by side in
    # the folder belong to the same capture. Using different timestamps
    # would make matching them dependent on the database.
    shot_path = None
    shot_hash = None
    if screenshot and os.path.isfile(screenshot):
        shot_path = os.path.join(directory, base + ".png")
        shutil.move(screenshot, shot_path)
        shot_hash = _sha256(shot_path)

    capture_id = db.execute(
        "INSERT INTO waveform_captures (session_id, dut_id, instrument_id,"
        " operator_id, captured_at, trigger_no, file_path, sha256, size_bytes,"
        " points, channels, sample_interval_s, notes, is_simulated,"
        " screenshot_path, screenshot_sha256, test_mode, divider_ratio,"
        " load_ohm, setup_json, analysis_json,"
        " series_id, series_index, series_size, nominal_energy_j)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (session_id, dut_id, instrument_id, operator_id, db.utc_now(), seq,
         path, _sha256(path), os.path.getsize(path), points,
         ",".join(columns.keys()), sample_interval(times),
         (notes or "").strip() or None, 1 if is_simulated else 0,
         shot_path, shot_hash, test_mode, divider_ratio, load_ohm,
         _json(setup), _json(analysis),
         series_id, series_index, series_size, nominal_energy_j))

    audit.log("waveform.capture", user_id=operator_id, entity="instrument",
              entity_id=instrument_id,
              detail={"capture_id": capture_id, "file": os.path.basename(path),
                      "points": points, "channels": list(columns.keys()),
                      "dut_id": dut_id, "simulated": bool(is_simulated),
                      "test_mode": test_mode, "screenshot": bool(shot_path),
                      "divider_ratio": divider_ratio, "load_ohm": load_ohm})
    return capture_id


def _json(value):
    return json.dumps(value, ensure_ascii=False, default=str) if value else None


def analysis_of(row):
    """Returns the analysis result stored in the record as a dict."""
    if row is None or "analysis_json" not in row.keys() or not row["analysis_json"]:
        return None
    try:
        return json.loads(row["analysis_json"])
    except ValueError:
        return None


def reanalyze(capture_id, user_id=None):
    """Recomputes the analysis from the raw CSV and writes it back to the record.

    The analysis is computed and stored at capture time so the report and
    the screen can reproduce the result the operator saw at that moment.
    But once the analysis code is fixed, the stored result goes stale, and
    the report keeps printing the old/wrong value **despite** the fixed
    code.

    Only **derived** data changes here: the raw CSV and its SHA-256 hash
    are untouched, and the recomputation is done from that same file. The
    operation is written to the audit log — if someone later asks why a
    number on a certificate changed, the answer lives there.

    Return: (old_analysis, new_analysis). (None, None) if the file is missing.
    """
    from . import testmodes

    row = get(capture_id)
    if row is None or not os.path.isfile(row["file_path"]):
        return None, None

    mode = testmodes.get(row["test_mode"])
    if mode.analyzer is None:
        return None, None

    times, columns = read_csv(row["file_path"])
    if not times or not columns:
        return None, None

    before = analysis_of(row)
    chain = {"load_ohm": row["load_ohm"] or 50.0}
    after = mode.analyzer(times, columns[list(columns.keys())[0]], chain)

    db.execute("UPDATE waveform_captures SET analysis_json = ? WHERE id = ?",
               (_json(after), capture_id))
    audit.log("waveform.reanalyze", user_id=user_id, entity="waveform",
              entity_id=capture_id,
              detail={"onceki_sekil": (before or {}).get("shape"),
                      "yeni_sekil": after.get("shape"),
                      "onceki_enerji_j": (before or {}).get("energy_j"),
                      "yeni_enerji_j": after.get("energy_j")})
    return before, after


def next_index(directory, prefix):
    """Generates the next number by looking at the files already in the folder.

    The counter isn't kept in memory: if it were, numbering would restart
    from scratch whenever the app was closed and reopened, and the same
    folder would end up with 0001 twice.
    """
    if not os.path.isdir(directory):
        return 1
    biggest = 0
    for name in os.listdir(directory):
        if not name.startswith(prefix + "_") or not name.endswith(".csv"):
            continue
        parts = name[len(prefix) + 1:].split("_")
        if parts and parts[0].isdigit():
            biggest = max(biggest, int(parts[0]))
    return biggest + 1


# --- queries ---------------------------------------------------------------
def list_captures(dut_id=None, session_id=None, instrument_id=None, limit=500):
    sql = ("SELECT w.*, u.full_name AS operator_name,"
           " d.manufacturer, d.model, d.serial_no,"
           " i.brand AS inst_brand, i.model AS inst_model"
           " FROM waveform_captures w"
           " JOIN users u ON u.id = w.operator_id"
           " LEFT JOIN duts d ON d.id = w.dut_id"
           " LEFT JOIN instruments i ON i.id = w.instrument_id"
           " WHERE 1 = 1")
    params = []
    if dut_id:
        sql += " AND w.dut_id = ?"
        params.append(dut_id)
    if session_id:
        sql += " AND w.session_id = ?"
        params.append(session_id)
    if instrument_id:
        sql += " AND w.instrument_id = ?"
        params.append(instrument_id)
    sql += " ORDER BY w.id DESC LIMIT ?"
    params.append(int(limit))
    return db.query(sql, tuple(params))


def get(capture_id):
    return db.query_one("SELECT * FROM waveform_captures WHERE id = ?",
                        (capture_id,))


def new_series_id():
    """Generates the key that groups a series of measurements together.

    Timestamp-based: a sequence number would collide when databases
    prepared on two different computers are merged.
    """
    return "SER-%s" % datetime.now().strftime("%Y%m%d-%H%M%S")


def series_captures(series_id):
    """Captures belonging to a series, in measurement order.

    The device under test (`duts`) and the oscilloscope's serial number /
    calibration info come along too — the same fields used by the
    single-shock report's query (`shockreport.build_pdf`). To avoid a clash
    between `d.serial_no` (device under test) and `i.serial_no`
    (oscilloscope), the latter is aliased as `inst_serial`.
    """
    if not series_id:
        return []
    return db.query(
        "SELECT w.*, u.full_name AS operator_name,"
        " d.company, d.manufacturer, d.model, d.serial_no, d.device_type,"
        " i.brand AS inst_brand, i.model AS inst_model,"
        " i.serial_no AS inst_serial, i.cal_cert_no, i.cal_date, i.cal_due"
        " FROM waveform_captures w"
        " JOIN users u ON u.id = w.operator_id"
        " LEFT JOIN duts d ON d.id = w.dut_id"
        " LEFT JOIN instruments i ON i.id = w.instrument_id"
        " WHERE w.series_id = ?"
        " ORDER BY COALESCE(w.series_index, w.id), w.id", (series_id,))


def series_for_dut(dut_id):
    """A device's waveform series measurements, newest first.

    So they can show up next to the sessions on the device page: captures
    carried `dut_id`, but nothing grouped them by device, so "what have we
    done with this defibrillator" could only be answered from the waveform
    tab.

    Single captures with no series are left out (`series_id IS NOT NULL`):
    a single shock isn't certified, the series report relies on the
    distribution of n shocks.
    """
    return db.query(
        "SELECT w.series_id,"
        " COUNT(*) AS n,"
        " MIN(w.captured_at) AS first_at,"
        " MAX(w.captured_at) AS last_at,"
        " MAX(w.series_size) AS series_size,"
        " MAX(w.test_mode) AS test_mode,"
        " MAX(w.nominal_energy_j) AS nominal_energy_j,"
        " MAX(w.is_simulated) AS is_simulated,"
        " MAX(u.full_name) AS operator_name,"
        " c.cert_no, c.result AS cert_result, c.approved_at,"
        " c.deleted_at AS cert_deleted_at, c.pdf_path AS cert_path"
        " FROM waveform_captures w"
        " JOIN users u ON u.id = w.operator_id"
        " LEFT JOIN certificates c ON c.series_id = w.series_id"
        " WHERE w.dut_id = ? AND w.series_id IS NOT NULL"
        " GROUP BY w.series_id"
        " ORDER BY MIN(w.captured_at) DESC", (dut_id,))


def series_of(row):
    """The series key the record belongs to; None if it isn't part of one."""
    if row is None or "series_id" not in row.keys():
        return None
    return row["series_id"] or None


def verify(capture_id):
    """Whether the file still exists and its content is unchanged.

    Return: (status, message) — 'ok' | 'missing' | 'changed' | 'unknown'
    """
    row = get(capture_id)
    if row is None:
        return "unknown", "Kayıt bulunamadı"

    state, message = _verify_file(row["file_path"], row["sha256"], "CSV")
    if state != "ok":
        return state, message

    # The screenshot is part of the record too: saying "everything's fine"
    # would be misleading if the CSV is intact but the PNG has gone missing.
    keys = row.keys()
    if "screenshot_path" in keys and row["screenshot_path"]:
        shot_state, shot_message = _verify_file(
            row["screenshot_path"], row["screenshot_sha256"], "Ekran görüntüsü")
        if shot_state != "ok":
            return shot_state, shot_message
    return "ok", "Dosyalar değişmemiş"


def _verify_file(path, expected_hash, label):
    if not path:
        return "unknown", "%s yolu kayıtlı değil" % label
    if not os.path.isfile(path):
        return "missing", "%s bulunamıyor: %s" % (label, path)
    if not expected_hash:
        return "unknown", "%s özeti kaydedilmemiş" % label
    if _sha256(path) != expected_hash:
        return "changed", "%s yakalandığından beri değişmiş" % label
    return "ok", "%s değişmemiş" % label


def read_csv(path, max_points=None):
    """Reads a saved capture back in — for displaying it on a chart.

    Return: (time list, {channel: value list})
    """
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header or len(header) < 2:
            raise ValueError("Beklenen başlık bulunamadı: %s" % path)
        names = header[1:]
        times = []
        columns = dict((n, []) for n in names)
        # Downsample for large files: reading every single point is
        # pointless when plotting a 10,000-point capture into an
        # 800-pixel-wide chart.
        step = 1
        if max_points:
            total = sum(1 for _ in reader)
            fh.seek(0)
            reader = csv.reader(fh)
            next(reader, None)
            step = max(1, total // int(max_points))
        for i, row in enumerate(reader):
            if i % step or len(row) < 2:
                continue
            try:
                times.append(float(row[0]))
                for k, name in enumerate(names):
                    columns[name].append(float(row[k + 1]))
            except ValueError:
                continue
    return times, columns
