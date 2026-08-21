"""Shock test report — PDF.

The report carries two images together, and each answers a different
question:

* **Chart drawn from the CSV** — the measured data. Phase boundaries, peak
  points, and the trigger instant are marked; since it comes from the same
  source as the numbers, it's exactly consistent with the report's table.
* **Oscilloscope screenshot** — what the device saw at the time. Includes
  the division settings, the trigger marker, and the readings on the
  device itself. This is the answer to "what was on the screen" during an
  audit; the application's own drawing can't answer that question.

The report number comes from a separate series (``SOK-CAL-MED-YYYY-NNNN``);
simulation reports are numbered with a ``SIM-`` prefix and carry a
watermark.
"""

import hashlib
import os
from datetime import datetime

from reportlab.graphics.shapes import (Drawing, Group, Line, PolyLine, Rect,
                                       String)
from reportlab.lib import colors
from reportlab.lib.units import mm

from callog_common import audit, branding, db, testmodes
from callog_common.chart import _fmt, _nice_ticks

from . import defib

#: The folder is computed **at call time**, not at import time: tests and
#: the screenshot script point `db.DATA_DIR` at a temporary folder. A fixed
#: module-level variable would miss that change and test output would land
#: in the real project folder.
def report_dir():
    return os.path.join(db.DATA_DIR, "raporlar")

C_AXIS = colors.HexColor("#666666")
C_GRID = colors.HexColor("#DDDDDD")
C_TRACE = colors.HexColor("#185FA5")
C_TRACE2 = colors.HexColor("#8A5209")
C_PHASE1 = colors.HexColor("#EAF1FA")
C_PHASE2 = colors.HexColor("#FBEFE3")
C_TRIGGER = colors.HexColor("#A32D2D")
C_ZERO = colors.HexColor("#888888")
C_TEXT = colors.HexColor("#444444")
C_PEAK = colors.HexColor("#0F6E56")

SIM_WARNING = (
    "SİMÜLASYON KAYDI — GEÇERLİ ÖLÇÜM DEĞİLDİR\n"
    "Bu rapor simülasyon sürücüsüyle üretilmiş verilerden hazırlanmıştır. "
    "Hiçbir gerçek defibrilatör ölçülmemiştir."
)

DISCLAIMER = (
    "Rapordaki değerler yakalanan dalga biçiminden hesaplanmıştır; sertifikalı "
    "bir defibrilatör analizörü ölçümü değildir. Enerji E = ∫v²/R dt "
    "bağıntısıyla, yamuk kuralıyla türetilmiştir — yük direncinin gerçek "
    "değeri ve osiloskobun dikey doğruluğu doğrudan sonuca girer. Faz "
    "sınırları tepe değerin %5'ini geçen kesintisiz bölge olarak belirlenmiştir."
)


# --- numbering -----------------------------------------------------------
def next_report_no(simulated=False, kind="single"):
    """The next report number. Simulation gets a number from a separate series.

    Simulation reports consuming the official series would leave
    unexplained gaps in the number sequence.

    kind="series" also puts series reports in a separate sequence: the
    single-shock report and the n-shock series report are different
    documents, and if their numbers mixed there'd be no way to answer
    which one "SOK-…-0007" was. Since the prefix comes first, the LIKE
    patterns don't catch each other.
    """
    prefix = "SOK-CAL-MED"
    if kind == "series":
        prefix = "SERI-" + prefix
    if simulated:
        prefix = "SIM-" + prefix
    year = datetime.now().year
    like = "%s-%d-%%" % (prefix, year)
    row = db.query_one(
        "SELECT report_no FROM waveform_captures WHERE report_no LIKE ?"
        " ORDER BY report_no DESC LIMIT 1", (like,))
    nxt = 1
    if row and row["report_no"]:
        try:
            nxt = int(row["report_no"].rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            nxt = 1
    return "%s-%d-%04d" % (prefix, year, nxt)


# --- waveform chart -------------------------------------------------------
def _envelope(times, values, buckets=700):
    """Downsamples to a min/max envelope scaled to the chart width.

    Simple "take every Nth point" decimation misses the peak and steep
    edges of a truncated exponential waveform: in a 20,000-point capture
    the peak can live in a single sample, and the chart ends up looking
    lower than it really is. Plotting each bucket's min and max together
    is what oscilloscopes do, and it preserves the edges.
    """
    n = min(len(times), len(values))
    if n <= buckets * 2:
        return [(float(times[i]), float(values[i])) for i in range(n)]

    step = n / float(buckets)
    points = []
    for b in range(buckets):
        start = int(b * step)
        end = max(start + 1, int((b + 1) * step))
        chunk = values[start:end]
        lo = min(chunk)
        hi = max(chunk)
        t_mid = float(times[(start + end - 1) // 2])
        # Preserve the order within the bucket: whichever extreme the
        # first sample is closer to comes first
        first = float(chunk[0])
        if abs(first - lo) <= abs(first - hi):
            points.append((t_mid, float(lo)))
            points.append((t_mid, float(hi)))
        else:
            points.append((t_mid, float(hi)))
            points.append((t_mid, float(lo)))
    return points


def _time_scale(span):
    """Picks a unit and multiplier for the time axis (s / ms / µs)."""
    for factor, label in ((1.0, "s"), (1e-3, "ms"), (1e-6, "µs")):
        if span >= factor * 2:
            return 1.0 / factor, label
    return 1e6, "µs"


def _volt_scale(peak):
    for factor, label in ((1000.0, "kV"), (1.0, "V"), (1e-3, "mV")):
        if peak >= factor:
            return 1.0 / factor, label
    return 1.0, "V"


def waveform_drawing(times, columns, analysis=None, width=165 * mm,
                     height=85 * mm, font="Helvetica", font_bold=None):
    """Draws the captured waveform as a vector graphic.

    Returns None if there's no data — the caller skips the chart.
    """
    font_bold = font_bold or font
    names = [n for n in columns if len(columns[n])]
    if not names or not len(times):
        return None

    d = Drawing(width, height)
    left, right = 20 * mm, 5 * mm
    bottom, top = 14 * mm, 6 * mm
    plot_w = width - left - right
    plot_h = height - bottom - top

    all_values = [float(v) for name in names for v in columns[name]]
    peak = max(abs(v) for v in all_values) or 1.0
    v_mul, v_unit = _volt_scale(peak)

    y_lo, y_hi = min(all_values), max(all_values)
    pad = max((y_hi - y_lo) * 0.10, peak * 0.05)
    y_lo, y_hi = y_lo - pad, y_hi + pad
    if y_hi - y_lo < 1e-12:
        y_lo, y_hi = -1.0, 1.0

    x_lo, x_hi = float(times[0]), float(times[-1])
    if x_hi - x_lo < 1e-12:
        x_hi = x_lo + 1e-6
    t_mul, t_unit = _time_scale(x_hi - x_lo)

    def px(x):
        return left + (x - x_lo) / (x_hi - x_lo) * plot_w

    def py(v):
        return bottom + (v - y_lo) / (y_hi - y_lo) * plot_h

    d.add(Rect(left, bottom, plot_w, plot_h, fillColor=colors.white,
               strokeColor=C_AXIS, strokeWidth=0.5))

    # --- phase regions (if analysis is available) -------------------------
    if analysis and analysis.get("found"):
        for i, ph in enumerate(analysis.get("phases", [])):
            x0, x1 = px(ph["start_time"]), px(ph["end_time"])
            d.add(Rect(x0, bottom, max(x1 - x0, 0.4), plot_h,
                       fillColor=(C_PHASE1 if i == 0 else C_PHASE2),
                       strokeColor=None))
            d.add(String((x0 + x1) / 2.0, bottom + plot_h - 8,
                         "%d. faz" % (i + 1), fontName=font, fontSize=5.5,
                         fillColor=C_TEXT, textAnchor="middle"))

    # --- grid and axis labels ----------------------------------------------
    y_span = y_hi - y_lo
    # Asking for 5 jumps the step to the next order of magnitude and
    # leaves only two labels on the axis; asking for 6 picks a step of 500.
    for value in _nice_ticks(y_lo, y_hi, 6):
        y = py(value)
        d.add(Line(left, y, left + plot_w, y, strokeColor=C_GRID, strokeWidth=0.3))
        d.add(String(left - 2, y - 2, _fmt(value * v_mul, y_span * v_mul),
                     fontName=font, fontSize=5.5, fillColor=C_TEXT,
                     textAnchor="end"))
    for value in _nice_ticks(x_lo, x_hi, 6):
        x = px(value)
        d.add(Line(x, bottom, x, bottom + plot_h, strokeColor=C_GRID,
                   strokeWidth=0.3))
        d.add(String(x, bottom - 6, _fmt(value * t_mul, (x_hi - x_lo) * t_mul),
                     fontName=font, fontSize=5.5, fillColor=C_TEXT,
                     textAnchor="middle"))

    # zero line: polarity changes are read from here
    if y_lo < 0 < y_hi:
        d.add(Line(left, py(0.0), left + plot_w, py(0.0), strokeColor=C_ZERO,
                   strokeWidth=0.5))

    # trigger instant — t = 0 on the device
    if x_lo < 0 < x_hi:
        d.add(Line(px(0.0), bottom, px(0.0), bottom + plot_h,
                   strokeColor=C_TRIGGER, strokeWidth=0.6,
                   strokeDashArray=[3, 2]))
        d.add(String(px(0.0) + 2, bottom + 3, "tetikleme", fontName=font,
                     fontSize=5, fillColor=C_TRIGGER))

    d.add(String(left + plot_w / 2.0, bottom - 12, "Zaman (%s)" % t_unit,
                 fontName=font, fontSize=6, fillColor=C_TEXT,
                 textAnchor="middle"))
    y_title = Group(String(0, 0, "Gerilim (%s)" % v_unit, fontName=font,
                           fontSize=6, fillColor=C_TEXT, textAnchor="middle"))
    y_title.translate(7, bottom + plot_h / 2.0)
    y_title.rotate(90)
    d.add(y_title)

    # --- traces --------------------------------------------------------------
    for i, name in enumerate(names):
        pts = _envelope(times, columns[name])
        flat = []
        for x, v in pts:
            flat.extend((px(x), py(max(y_lo, min(y_hi, v)))))
        if len(flat) >= 4:
            d.add(PolyLine(flat, strokeColor=(C_TRACE if i == 0 else C_TRACE2),
                           strokeWidth=0.7))
        d.add(String(left + plot_w - 2, bottom + plot_h - 8 - i * 7,
                     name.replace("_V", ""), fontName=font_bold, fontSize=5.5,
                     fillColor=(C_TRACE if i == 0 else C_TRACE2),
                     textAnchor="end"))

    # --- peak markers --------------------------------------------------------
    if analysis and analysis.get("found"):
        for ph in analysis.get("phases", []):
            peak_v = ph["peak"]
            if not (y_lo <= peak_v <= y_hi):
                continue
            y = py(peak_v)
            d.add(Line(left, y, left + plot_w, y, strokeColor=C_PEAK,
                       strokeWidth=0.4, strokeDashArray=[1.5, 2]))
            d.add(String(left + 3, y + 2, "tepe %s" % defib._v(peak_v),
                         fontName=font, fontSize=5, fillColor=C_PEAK))

    return d


# --- report ----------------------------------------------------------------
def _chain_rows(row, setup):
    rows = [("Osiloskop", "%s %s" % (row["inst_brand"] or "",
                                     row["inst_model"] or "")),
            ("Yakalanan kanallar", (row["channels"] or "").replace("_V", ""))]
    if row["divider_ratio"]:
        rows.append(("Bölücü oranı", "1 : %g" % row["divider_ratio"]))
    if row["load_ohm"]:
        rows.append(("Yük direnci", "%g Ω" % row["load_ohm"]))
    if setup:
        if setup.get("volts_per_div"):
            rows.append(("Dikey ölçek", "%g V/bölme" % setup["volts_per_div"]))
        if setup.get("time_per_div"):
            rows.append(("Zaman tabanı", defib._s(setup["time_per_div"]) + "/bölme"))
        if setup.get("trigger_level") is not None:
            rows.append(("Tetikleme eşiği", "%g V (%s)" % (
                setup["trigger_level"],
                "yükselen kenar" if str(setup.get("trigger_slope", "")).upper()
                .startswith("POS") else "düşen kenar")))
    rows.append(("Nokta sayısı", str(row["points"] or "—")))
    if row["sample_interval_s"]:
        rows.append(("Örnekleme aralığı", defib._s(row["sample_interval_s"])))
    return rows


def build_pdf(capture_id, issued_by, path=None):
    """Generates the shock report as a PDF and returns its path.

    Returns: (file path, report number)
    """
    import json

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    from callog_common import pdffont, waveform

    row = db.query_one(
        "SELECT w.*, u.full_name AS operator_name,"
        " d.company, d.manufacturer, d.model, d.serial_no, d.device_type,"
        " i.brand AS inst_brand, i.model AS inst_model,"
        " i.serial_no AS inst_serial, i.cal_cert_no, i.cal_date, i.cal_due"
        " FROM waveform_captures w"
        " JOIN users u ON u.id = w.operator_id"
        " LEFT JOIN duts d ON d.id = w.dut_id"
        " LEFT JOIN instruments i ON i.id = w.instrument_id"
        " WHERE w.id = ?", (capture_id,))
    if row is None:
        raise ValueError("Yakalama bulunamadı: %s" % capture_id)
    if not os.path.isfile(row["file_path"]):
        raise ValueError("Yakalama dosyası bulunamıyor:\n%s" % row["file_path"])

    times, columns = waveform.read_csv(row["file_path"])
    if not times:
        raise ValueError("Yakalama dosyasında veri yok")

    analysis = waveform.analysis_of(row)
    if analysis is None:
        # If no analysis was saved (captured in free mode), it's computed
        # at report time: the report shouldn't be just a page showing the
        # raw file.
        first = list(columns.keys())[0]
        analysis = defib.analyze(times, columns[first],
                                 load_ohm=row["load_ohm"] or 50.0)

    setup = None
    if row["setup_json"]:
        try:
            setup = json.loads(row["setup_json"])
        except ValueError:
            setup = None

    simulated = bool(row["is_simulated"])
    report_no = next_report_no(simulated)
    font, font_bold, ascii_only = pdffont.register()

    if path is None:
        directory = report_dir()
        if not os.path.isdir(directory):
            os.makedirs(directory)
        path = os.path.join(directory, "%s.pdf" % report_no)

    base = getSampleStyleSheet()
    p_body = ParagraphStyle("govde", parent=base["BodyText"], fontName=font,
                            fontSize=8.5, leading=12)
    p_h1 = ParagraphStyle("baslik", parent=base["Title"], fontName=font_bold,
                          fontSize=15, leading=19, spaceAfter=2)
    p_h2 = ParagraphStyle("altbaslik", parent=base["Heading2"],
                          fontName=font_bold, fontSize=11.5, leading=15)
    p_h4 = ParagraphStyle("bolum", parent=base["Heading4"], fontName=font_bold,
                          fontSize=9.5, leading=13, spaceBefore=4, spaceAfter=2)

    doc = SimpleDocTemplate(
        path, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=report_no, author=branding.org_name())

    def kv_table(rows, key_w=58 * mm):
        t = Table([[k, v] for k, v in rows], colWidths=(key_w, 160 * mm - key_w))
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
            ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#DDDDDD")),
        ]))
        return t

    story = [
        Paragraph(branding.header_line(), p_h1),
        Paragraph("DEFİBRİLATÖR ŞOK TEST RAPORU", p_h2),
        Spacer(1, 4 * mm),
    ]

    if simulated:
        head, rest = SIM_WARNING.split("\n", 1)
        story += [
            Table([[Paragraph("<b>%s</b><br/>%s" % (head, rest), p_body)]],
                  colWidths=[160 * mm],
                  style=TableStyle([
                      ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FCEBEB")),
                      ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#A32D2D")),
                      ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#A32D2D")),
                      ("LEFTPADDING", (0, 0), (-1, -1), 8),
                      ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                      ("TOPPADDING", (0, 0), (-1, -1), 6),
                      ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                  ])),
            Spacer(1, 4 * mm),
        ]

    mode = testmodes.get(row["test_mode"])
    story += [
        kv_table([
            ("Rapor no", report_no),
            ("Yakalama tarihi", (row["captured_at"] or "").replace("T", " ")[:19]),
            ("Rapor tarihi", db.utc_now()[:10]),
            ("Test modu", mode.label),
            ("Ölçümü yapan", row["operator_name"]),
        ]),
        Spacer(1, 3 * mm),
    ]

    if row["serial_no"]:
        story += [
            Paragraph("Test edilen cihaz", p_h4),
            kv_table([
                ("Şirket / müşteri", row["company"] or "—"),
                ("Üretici firma", row["manufacturer"] or "—"),
                ("Model", row["model"] or "—"),
                ("Seri no", row["serial_no"]),
                ("Cihaz tipi", row["device_type"] or "—"),
            ]),
            Spacer(1, 3 * mm),
        ]

    story += [
        Paragraph("Ölçüm zinciri ve cihaz ayarları", p_h4),
        kv_table(_chain_rows(row, setup)),
        Spacer(1, 3 * mm),
    ]
    if row["inst_serial"]:
        story += [
            kv_table([
                ("Osiloskop seri no", row["inst_serial"]),
                ("Osiloskop kalibrasyon sertifikası", row["cal_cert_no"] or "—"),
                ("Sertifika tarihi", row["cal_date"] or "—"),
                ("Geçerlilik", row["cal_due"] or "—"),
            ]),
            Spacer(1, 3 * mm),
        ]

    story += [
        Paragraph("Şok çözümlemesi", p_h4),
        kv_table(defib.summary_rows(analysis)),
        Spacer(1, 4 * mm),
    ]

    drawing = waveform_drawing(times, columns, analysis, font=font,
                               font_bold=font_bold)
    if drawing is not None:
        story += [
            Paragraph("Ölçülen dalga biçimi (kayıt dosyasından çizildi)", p_h4),
            drawing,
            Spacer(1, 4 * mm),
        ]

    shot = row["screenshot_path"]
    if shot and os.path.isfile(shot):
        try:
            iw, ih = ImageReader(shot).getSize()
            target_w = 150 * mm
            target_h = target_w * ih / float(iw)
            # Don't let a tall screenshot overflow the page
            max_h = 95 * mm
            if target_h > max_h:
                target_h = max_h
                target_w = max_h * iw / float(ih)
            story += [
                Paragraph("Osiloskop ekran görüntüsü (cihazdan alındı)", p_h4),
                Image(shot, width=target_w, height=target_h),
                Spacer(1, 4 * mm),
            ]
        except Exception:
            story.append(Paragraph(
                "Ekran görüntüsü rapora eklenemedi: dosya okunamadı.", p_body))

    # SHA-256 is 64 characters; plain text in the cell won't wrap and
    # overflows the page edge. wordWrap="CJK" allows breaking after any
    # character.
    p_hash = ParagraphStyle("ozet", parent=base["BodyText"], fontName=font,
                            fontSize=7, leading=9, wordWrap="CJK")

    def hash_cell(value):
        return Paragraph(value or "—", p_hash)

    verify_rows = [("Kayıt dosyası", os.path.basename(row["file_path"])),
                   ("SHA-256", hash_cell(row["sha256"]))]
    if shot:
        verify_rows += [("Ekran görüntüsü", os.path.basename(shot)),
                        ("SHA-256", hash_cell(row["screenshot_sha256"]))]
    state, message = waveform.verify(capture_id)
    verify_rows.append(("Bütünlük denetimi", message))

    story += [
        Paragraph("Kaynak dosyalar", p_h4),
        kv_table(verify_rows, key_w=42 * mm),
        Spacer(1, 4 * mm),
        Paragraph(DISCLAIMER, p_body),
        Spacer(1, 8 * mm),
        kv_table([("Ölçümü yapan", row["operator_name"]),
                  ("Onaylayan", "................................................")]),
    ]

    def stamp(canvas, _doc):
        if not simulated:
            return
        canvas.saveState()
        canvas.translate(A4[0] / 2.0, A4[1] / 2.0)
        canvas.rotate(45)
        canvas.setFillColor(colors.Color(0.64, 0.18, 0.18, alpha=0.16))
        canvas.setFont(font_bold, 62)
        canvas.drawCentredString(0, 0, "SİMÜLASYON")
        canvas.setFont(font_bold, 20)
        canvas.drawCentredString(0, -42, "GEÇERLİ ÖLÇÜM DEĞİLDİR")
        canvas.restoreState()

    doc.build(story, onFirstPage=stamp, onLaterPages=stamp)

    with open(path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()

    db.execute(
        "UPDATE waveform_captures SET report_no = ?, report_path = ?,"
        " report_sha256 = ? WHERE id = ?", (report_no, path, sha, capture_id))
    audit.log("waveform.report", user_id=issued_by, entity="instrument",
              entity_id=row["instrument_id"],
              detail={"capture_id": capture_id, "report_no": report_no,
                      "sha256": sha, "simulated": simulated,
                      "integrity": state,
                      "font_ascii_fallback": ascii_only})
    return path, report_no
