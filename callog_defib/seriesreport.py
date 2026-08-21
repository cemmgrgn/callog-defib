"""Series shock test report — combining n shocks into a single document.

A single shock doesn't say anything about the device's consistency.
IEC 60601-2-4 requires energy repeatability, and that needs the
**distribution** of several shocks in a row. This module takes every
capture belonging to a series and produces one report:

* **Overlay chart** — every waveform in the series overlaid in a faint
  color, with the **mean waveform** on top in a separate, bold color. How
  similar the shocks are to each other is visible at a glance; that
  doesn't show up in n separately drawn charts.
* **Statistics table** — for each quantity: n, mean, standard deviation,
  type A standard uncertainty (s/√n), expanded uncertainty (k=2), min, max,
  and span. The same rule as the certificate applies here too.
* **Measurement-by-measurement table** — each shock in the series on its
  own row: which file, which energy, which peak.
* **Screenshots** — each shock's PNG taken from the device, in order.

Why the mean waveform is resampled: even if captures are taken with the
same settings, their time axes may not line up exactly (if the point count
or trigger delay differs). Averaging without moving the traces onto a
shared axis via linear interpolation would sum up misaligned samples,
flattening the waveform and showing the peak as smaller than it is.
"""

import hashlib
import os

from reportlab.graphics.shapes import Drawing, Group, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.units import mm

from callog_common import audit, branding, certificate, db, testmodes, waveform
from callog_common.chart import _fmt, _nice_ticks
from callog_common.stats import Statistics, verdict_ok

from . import defib, shockreport

#: Individual shocks in the overlay chart — faint so they stay behind the mean
C_MEMBER = colors.HexColor("#B9C6D6")
#: Mean waveform — different color, bold, on top
C_MEAN = colors.HexColor("#C2410C")
#: Shock-by-shock energy chart colors
C_POINT_S = colors.HexColor("#185FA5")
C_AXIS_S = colors.HexColor("#666666")
C_GRID_S = colors.HexColor("#DDDDDD")
C_NOMINAL_S = colors.HexColor("#444444")

#: How many points to generate on the shared time axis. 1500 points is
#: finer than a pixel at A4 width; more bloats the file, fewer rounds off
#: steep edges.
RESAMPLE_POINTS = 1500

#: Quantities statistics are extracted for: (key, label, unit, format)
QUANTITIES = (
    ("energy_j", "Aktarılan enerji", "J", "%.4g"),
    ("peak_voltage", "Tepe gerilim", "V", "%.4g"),
    ("peak_current", "Tepe akım", "A", "%.4g"),
    ("total_duration", "Toplam süre", "s", None),
)

#: Extracted per phase
PHASE_QUANTITIES = (
    ("duration", "%d. faz süresi", "s", None),
    ("peak", "%d. faz tepe", "V", "%.4g"),
    ("tilt_percent", "%d. faz eğimi (tilt)", "%", "%.1f"),
    ("tau", "%d. faz zaman sabiti τ", "s", None),
)


# --- statistics -------------------------------------------------------------
def summarize(values):
    """A quantity's distribution across the series.

    Uses the same `Statistics` as the certificate: mean, sample standard
    deviation (n-1), type A standard uncertainty s/√n, and expanded
    uncertainty with k=2. Computing the same rule two different ways in two
    places would mean different numbers in two documents.
    """
    values = [float(v) for v in values if v is not None]
    if not values:
        return None
    st = Statistics()
    for v in values:
        st.add(v)
    return {"n": st.n, "mean": st.mean, "std": st.std, "u": st.u_a,
            "U": 2.0 * st.u_a, "min": st.min, "max": st.max, "span": st.span}


def energy_verdict(analyses, nominal_j):
    """The series' energy pass/fail decision.

    Returns: (result, detail dict) — result is 'pass' | 'fail' | 'info'.

    The decision rule is **identical** to the multi-reading certificate's
    (`verdict_ok`, `mean` mode): |x̄ − nominal| + U ≤ T. Both documents
    carry the same lab's same signature; having two different definitions
    of "pass" would mean the result depends on which document you're
    looking at.

    If the set energy wasn't entered, no decision is made ('info'): a
    measured 5.1 J on its own is neither pass nor fail.
    """
    good = [a for a in analyses if a and a.get("found")]
    stats = summarize([a.get("energy_j") for a in good])
    tolerance = defib.energy_tolerance(nominal_j)
    detail = {"stats": stats, "nominal": nominal_j, "tolerance": tolerance}
    if stats is None:
        return "info", detail
    ok = verdict_ok("mean", nominal_j, tolerance, stats["mean"], stats["u"],
                    stats["min"], stats["max"])
    detail["deviation"] = (stats["mean"] - float(nominal_j)
                           if nominal_j is not None else None)
    return ("info" if ok is None else ("pass" if ok else "fail")), detail


def _phase_count(analyses):
    counts = [len(a.get("phases", [])) for a in analyses if a and a.get("found")]
    return min(counts) if counts else 0


def statistics_rows(analyses):
    """(label, n, mean, s, u, U, min, max) rows."""
    good = [a for a in analyses if a and a.get("found")]
    if len(good) < 1:
        return []

    rows = []

    def add(label, unit, fmt, values):
        s = summarize(values)
        if s is None:
            return
        rows.append((label, unit, fmt, s))

    for key, label, unit, fmt in QUANTITIES:
        add(label, unit, fmt, [a.get(key) for a in good])

    for i in range(_phase_count(good)):
        for key, label, unit, fmt in PHASE_QUANTITIES:
            values = [a["phases"][i].get(key) for a in good]
            if not any(v is not None for v in values):
                continue
            add(label % (i + 1), unit, fmt, values)
    return rows


def format_value(value, unit, fmt):
    """Format appropriate to the unit. Durations as ms/µs, voltages as kV."""
    if value is None:
        return "—"
    if unit == "s":
        return defib._s(value)
    if unit == "V":
        return defib._v(value)
    return ((fmt or "%.4g") % value) + (" %s" % unit if unit else "")


# --- mean waveform -----------------------------------------------------------
def _interp(times, values, x):
    """Linear interpolation. `times` is assumed to be increasing."""
    n = len(times)
    if n == 0:
        return None
    if x <= times[0]:
        return float(values[0])
    if x >= times[-1]:
        return float(values[-1])
    lo, hi = 0, n - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if times[mid] <= x:
            lo = mid
        else:
            hi = mid
    t0, t1 = times[lo], times[hi]
    if t1 == t0:
        return float(values[lo])
    w = (x - t0) / (t1 - t0)
    return float(values[lo]) * (1.0 - w) + float(values[hi]) * w


def mean_waveform(traces, points=RESAMPLE_POINTS):
    """Shared time axis and mean waveform.

    traces: [(time list, value list), …]
    Returns: (shared time axis, mean values) — (None, None) if there's no data.

    The shared axis is built over the **intersection** of all recordings:
    with a union, only some recordings would supply data at the edges and
    the mean would jump there.
    """
    usable = [(list(t), list(v)) for t, v in traces if len(t) > 1 and len(v) > 1]
    if not usable:
        return None, None

    lo = max(t[0] for t, _v in usable)
    hi = min(t[-1] for t, _v in usable)
    if not (hi > lo):
        return None, None

    step = (hi - lo) / float(points - 1)
    axis = [lo + i * step for i in range(points)]
    mean = []
    for x in axis:
        acc = 0.0
        for t, v in usable:
            acc += _interp(t, v, x)
        mean.append(acc / len(usable))
    return axis, mean


# --- overlay chart ------------------------------------------------------------
def overlay_drawing(traces, mean_axis, mean_values, width=165 * mm,
                    height=85 * mm, font="Helvetica", font_bold=None):
    """All waveforms in the series plus the mean waveform in a single chart.

    Returns None if there's no data — the caller skips the chart.
    """
    font_bold = font_bold or font
    if not traces or mean_axis is None:
        return None

    d = Drawing(width, height)
    left, right = 20 * mm, 5 * mm
    bottom, top = 14 * mm, 6 * mm
    plot_w = width - left - right
    plot_h = height - bottom - top

    all_values = [float(v) for _t, vals in traces for v in vals]
    if not all_values:
        return None
    peak = max(abs(v) for v in all_values) or 1.0
    v_mul, v_unit = shockreport._volt_scale(peak)

    y_lo, y_hi = min(all_values), max(all_values)
    pad = max((y_hi - y_lo) * 0.10, peak * 0.05)
    y_lo, y_hi = y_lo - pad, y_hi + pad
    if y_hi - y_lo < 1e-12:
        y_lo, y_hi = -1.0, 1.0

    x_lo, x_hi = float(mean_axis[0]), float(mean_axis[-1])
    if x_hi - x_lo < 1e-12:
        x_hi = x_lo + 1e-6
    t_mul, t_unit = shockreport._time_scale(x_hi - x_lo)

    def px(x):
        return left + (x - x_lo) / (x_hi - x_lo) * plot_w

    def py(v):
        return bottom + (max(y_lo, min(y_hi, v)) - y_lo) / (y_hi - y_lo) * plot_h

    d.add(Rect(left, bottom, plot_w, plot_h, fillColor=colors.white,
               strokeColor=shockreport.C_AXIS, strokeWidth=0.5))

    y_span = y_hi - y_lo
    for value in _nice_ticks(y_lo, y_hi, 6):
        y = py(value)
        d.add(Line(left, y, left + plot_w, y, strokeColor=shockreport.C_GRID,
                   strokeWidth=0.3))
        d.add(String(left - 2, y - 2, _fmt(value * v_mul, y_span * v_mul),
                     fontName=font, fontSize=5.5,
                     fillColor=shockreport.C_TEXT, textAnchor="end"))
    for value in _nice_ticks(x_lo, x_hi, 6):
        x = px(value)
        d.add(Line(x, bottom, x, bottom + plot_h,
                   strokeColor=shockreport.C_GRID, strokeWidth=0.3))
        d.add(String(x, bottom - 6, _fmt(value * t_mul, (x_hi - x_lo) * t_mul),
                     fontName=font, fontSize=5.5,
                     fillColor=shockreport.C_TEXT, textAnchor="middle"))

    if y_lo < 0 < y_hi:
        d.add(Line(left, py(0.0), left + plot_w, py(0.0),
                   strokeColor=shockreport.C_ZERO, strokeWidth=0.5))
    if x_lo < 0 < x_hi:
        d.add(Line(px(0.0), bottom, px(0.0), bottom + plot_h,
                   strokeColor=shockreport.C_TRIGGER, strokeWidth=0.6,
                   strokeDashArray=[3, 2]))

    d.add(String(left + plot_w / 2.0, bottom - 12, "Zaman (%s)" % t_unit,
                 fontName=font, fontSize=6, fillColor=shockreport.C_TEXT,
                 textAnchor="middle"))
    y_title = Group(String(0, 0, "Gerilim (%s)" % v_unit, fontName=font,
                           fontSize=6, fillColor=shockreport.C_TEXT,
                           textAnchor="middle"))
    y_title.translate(7, bottom + plot_h / 2.0)
    y_title.rotate(90)
    d.add(y_title)

    # Individual shocks drawn first and faint, so the mean stays readable on top.
    for t, vals in traces:
        pts = shockreport._envelope(t, vals, buckets=500)
        flat = []
        for x, v in pts:
            flat.extend((px(x), py(v)))
        if len(flat) >= 4:
            d.add(PolyLine(flat, strokeColor=C_MEMBER, strokeWidth=0.4))

    flat = []
    for x, v in shockreport._envelope(mean_axis, mean_values, buckets=500):
        flat.extend((px(x), py(v)))
    if len(flat) >= 4:
        d.add(PolyLine(flat, strokeColor=C_MEAN, strokeWidth=1.3))

    # Legend box — without labeling which line is which, the chart is unreadable
    lx, ly = left + plot_w - 46 * mm, bottom + plot_h - 5 * mm
    d.add(Line(lx, ly + 2, lx + 7 * mm, ly + 2, strokeColor=C_MEMBER,
               strokeWidth=0.9))
    d.add(String(lx + 8 * mm, ly, "tek tek şoklar (%d)" % len(traces),
                 fontName=font, fontSize=5.5, fillColor=shockreport.C_TEXT))
    d.add(Line(lx, ly - 6, lx + 7 * mm, ly - 6, strokeColor=C_MEAN,
               strokeWidth=1.3))
    d.add(String(lx + 8 * mm, ly - 8, "ortalama dalga", fontName=font_bold,
                 fontSize=5.5, fillColor=C_MEAN))
    return d


# --- report -------------------------------------------------------------------
def _load_series(series_id):
    """Reads the series: rows, waveform traces, and analyses.

    Returns: (rows, traces, analyses, missing, row_series)

    `row_series` is **aligned one-to-one** with `rows` — None for missing
    or empty files. Drawing each measurement's own chart (next to its
    screenshot) needs to know which row corresponds to which (time,
    channel) data; `traces` only carries the usable ones (enough for the
    overlay chart), so it doesn't line up with row numbers.
    """
    rows = waveform.series_captures(series_id)
    if not rows:
        raise ValueError("Seri bulunamadı: %s" % series_id)

    row_series = []
    analyses = []
    missing = []
    for row in rows:
        if not os.path.isfile(row["file_path"]):
            missing.append(os.path.basename(row["file_path"]))
            row_series.append(None)
            analyses.append(None)
            continue
        times, columns = waveform.read_csv(row["file_path"])
        if not times or not columns:
            row_series.append(None)
            analyses.append(None)
            continue
        row_series.append((times, columns))

        first = list(columns.keys())[0]
        stored = waveform.analysis_of(row)
        if stored is None:
            stored = defib.analyze(times, columns[first],
                                   load_ohm=row["load_ohm"] or 50.0)
        analyses.append(stored)

    traces = []
    for item in row_series:
        if item is None:
            continue
        t, c = item
        traces.append((t, c[list(c.keys())[0]]))

    return rows, traces, analyses, missing, row_series


def energy_scatter(analyses, nominal_j=None, tolerance=None,
                   width=165 * mm, height=62 * mm, font="Helvetica"):
    """Energy delivered shock by shock — each value labeled, mean and ±s drawn.

    The statistics table gives the distribution's numbers but not its
    **shape**: whether there's one stray shock or the whole series is
    drifting only becomes clear when the values are seen in order. The
    mean is drawn solid, ±s dashed, ±U as a faint band; the set energy, if
    given, is marked with a dotted line.
    """
    values = [a.get("energy_j") for a in analyses
              if a and a.get("found") and a.get("energy_j") is not None]
    d = Drawing(width, height)
    if len(values) < 1:
        return None

    st = summarize(values)
    mean, std, U = st["mean"], st["std"], st["U"]

    left, right = 22 * mm, width - 4 * mm
    top, bottom = height - 6 * mm, 13 * mm
    plot_w, plot_h = right - left, top - bottom

    # Y range fits the data; mean +- s and, if present, the nominal value too.
    lo = min(list(values) + [mean - std, mean - U])
    hi = max(list(values) + [mean + std, mean + U])
    if nominal_j:
        lo, hi = min(lo, float(nominal_j)), max(hi, float(nominal_j))
    pad = (hi - lo) * 0.18 or (abs(mean) * 0.02 + 1e-9)
    lo, hi = lo - pad, hi + pad

    def px(i):
        if len(values) == 1:
            return left + plot_w / 2.0
        return left + (i / float(len(values) - 1)) * plot_w

    def py(v):
        return bottom + (max(lo, min(hi, v)) - lo) / (hi - lo) * plot_h

    # +-U band (faint fill) — the result's uncertainty
    d.add(Rect(left, py(mean - U), plot_w, py(mean + U) - py(mean - U),
               fillColor=colors.HexColor("#EAF2FB"), strokeColor=None))

    # Frame + Y labels
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        v = lo + (hi - lo) * frac
        y = bottom + frac * plot_h
        d.add(Line(left, y, right, y, strokeColor=C_GRID_S, strokeWidth=0.3))
        d.add(String(left - 2, y - 2.2, "%.4g" % v, fontName=font,
                     fontSize=5.8, fillColor=C_AXIS_S, textAnchor="end"))
    d.add(Line(left, bottom, left, top, strokeColor=C_AXIS_S, strokeWidth=0.6))

    # Set energy
    if nominal_j and lo <= float(nominal_j) <= hi:
        yn = py(float(nominal_j))
        d.add(Line(left, yn, right, yn, strokeColor=C_NOMINAL_S,
                   strokeWidth=0.8, strokeDashArray=[1, 2]))
        d.add(String(right, yn + 2.0, "ayarlanan %.4g J" % float(nominal_j),
                     fontName=font, fontSize=5.6, fillColor=C_NOMINAL_S,
                     textAnchor="end"))

    # Mean and +-s
    ym = py(mean)
    d.add(Line(left, ym, right, ym, strokeColor=C_MEAN, strokeWidth=1.1))
    d.add(String(left + 1, ym + 2.2, "ortalama %.4g J" % mean, fontName=font,
                 fontSize=5.8, fillColor=C_MEAN))
    for sign in (1, -1):
        ys = py(mean + sign * std)
        d.add(Line(left, ys, right, ys, strokeColor=C_MEAN, strokeWidth=0.7,
                   strokeDashArray=[3, 2]))
    d.add(String(left + 1, py(mean + std) + 1.6, "+s", fontName=font,
                 fontSize=5.4, fillColor=C_MEAN))
    d.add(String(left + 1, py(mean - std) - 4.2, "-s", fontName=font,
                 fontSize=5.4, fillColor=C_MEAN))

    # Points + each value's own label
    pts = []
    for i, v in enumerate(values):
        x, y = px(i), py(v)
        pts += [x, y]
    if len(values) > 1:
        d.add(PolyLine(pts, strokeColor=C_POINT_S, strokeWidth=0.6))
    for i, v in enumerate(values):
        x, y = px(i), py(v)
        d.add(Rect(x - 1.5, y - 1.5, 3.0, 3.0, fillColor=C_POINT_S,
                   strokeColor=C_POINT_S))
        # Value label: written below the point when it's under the mean, so
        # it doesn't collide with the lines.
        above = v >= mean
        d.add(String(x, y + (4.0 if above else -6.6), "%.4g" % v,
                     fontName=font, fontSize=5.4, fillColor=C_POINT_S,
                     textAnchor="middle"))
        d.add(String(x, bottom - 6.5, "%d" % (i + 1), fontName=font,
                     fontSize=5.6, fillColor=C_AXIS_S, textAnchor="middle"))

    d.add(String((left + right) / 2.0, 2.0, "Sok sirasi", fontName=font,
                 fontSize=6.2, fillColor=C_AXIS_S, textAnchor="middle"))
    d.add(String(left - 18, top + 1.0, "Enerji (J)", fontName=font,
                 fontSize=6.2, fillColor=C_AXIS_S))
    return d


def energy_prefix(nominal_j):
    """Energy tag at the start of the filename: ``030J-``, ``360J-``.

    The filename states which energy the test is for, so scanning a folder
    by eye is easy. Zero-padded so filename order matches energy order:
    002J < 030J < 360J. Without padding, alphabetical sorting would put
    "2J" after "30J".

    If the set energy wasn't entered, there's no prefix either — a made-up
    "000J" in the filename would be wrong information.
    """
    if not nominal_j:
        return ""
    value = float(nominal_j)
    if value <= 0:
        return ""
    if abs(value - round(value)) < 1e-9:
        return "%03dJ-" % int(round(value))
    return "%sJ-" % ("%05.1f" % value).replace(".", ",")


def build_pdf(series_id, issued_by, path=None, report_no=None):
    """Generates the series shock report.

    ``report_no`` is normally assigned automatically (the next sequential
    number). It's only passed explicitly when a document that's already
    numbered needs to be regenerated with the **same number** (e.g. a
    template text correction) — a corrected version of the existing
    document, not a new measurement.

    Returns: (file path, report number)
    """
    import json

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)

    from callog_common import pdffont

    rows, traces, analyses, missing, row_series = _load_series(series_id)
    head = rows[0]
    simulated = any(bool(r["is_simulated"]) for r in rows)
    if report_no is None:
        report_no = shockreport.next_report_no(simulated, kind="series")
    font, font_bold, ascii_only = pdffont.register()

    if path is None:
        directory = shockreport.report_dir()
        if not os.path.isdir(directory):
            os.makedirs(directory)
        path = os.path.join(
            directory, "%s%s.pdf"
            % (energy_prefix(head["nominal_energy_j"]), report_no))

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

    def kv_table(kv, key_w=58 * mm):
        t = Table([[k, v] for k, v in kv], colWidths=(key_w, 160 * mm - key_w))
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

    def grid_table(data, widths, aligns=None):
        t = Table(data, colWidths=widths, repeatRows=1)
        style = [
            ("FONTNAME", (0, 0), (-1, 0), font_bold),
            ("FONTNAME", (0, 1), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2F6")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#AAAAAA")),
            ("LINEBELOW", (0, 1), (-1, -2), 0.25, colors.HexColor("#DDDDDD")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F8F9FB")]),
        ]
        for col in (aligns or []):
            style.append(("ALIGN", (col, 1), (col, -1), "RIGHT"))
        t.setStyle(TableStyle(style))
        return t

    story = [
        Paragraph(branding.header_line(), p_h1),
        Paragraph("SERİ DEFİBRİLATÖR ŞOK TEST RAPORU", p_h2),
        Spacer(1, 4 * mm),
    ]

    if simulated:
        title, rest = shockreport.SIM_WARNING.split("\n", 1)
        story += [
            Table([[Paragraph("<b>%s</b><br/>%s" % (title, rest), p_body)]],
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

    mode = testmodes.get(head["test_mode"])
    good = [a for a in analyses if a and a.get("found")]
    nominal_j = head["nominal_energy_j"]
    result, verdict = energy_verdict(analyses, nominal_j)
    story += [
        kv_table([
            ("Sertifika / rapor no", report_no),
            ("Seri anahtarı", series_id),
            ("Ölçüm sayısı", "%d yakalama · %d çözümlenebildi"
             % (len(rows), len(good))),
            ("İlk yakalama", (head["captured_at"] or "").replace("T", " ")[:19]),
            ("Son yakalama",
             (rows[-1]["captured_at"] or "").replace("T", " ")[:19]),
            ("Rapor tarihi", db.utc_now()[:10]),
            ("Test modu", mode.label),
            ("Ölçümü yapan", head["operator_name"]),
        ]),
        Spacer(1, 3 * mm),
    ]

    # Device under test (duts) — same section as in the single-shock report.
    if head["serial_no"]:
        story += [
            Paragraph("Test edilen cihaz", p_h4),
            kv_table([
                ("Şirket / müşteri", head["company"] or "—"),
                ("Üretici firma", head["manufacturer"] or "—"),
                ("Model", head["model"] or "—"),
                ("Seri no", head["serial_no"]),
                ("Cihaz tipi", head["device_type"] or "—"),
            ]),
            Spacer(1, 3 * mm),
        ]

    setup = None
    if head["setup_json"]:
        try:
            setup = json.loads(head["setup_json"])
        except ValueError:
            setup = None
    story += [
        Paragraph("Ölçüm zinciri ve cihaz ayarları", p_h4),
        kv_table(shockreport._chain_rows(head, setup)),
        Spacer(1, 4 * mm),
    ]
    # The measuring oscilloscope's serial number and calibration info —
    # answers which device measured this and whether its calibration is
    # valid. Kept under a separate heading so it isn't confused with the
    # device under test (above).
    if head["inst_serial"]:
        story += [
            kv_table([
                ("Osiloskop seri no", head["inst_serial"]),
                ("Osiloskop kalibrasyon sertifikası", head["cal_cert_no"] or "—"),
                ("Sertifika tarihi", head["cal_date"] or "—"),
                ("Geçerlilik", head["cal_due"] or "—"),
            ]),
            Spacer(1, 3 * mm),
        ]

    if missing:
        story += [
            Paragraph("<b>Uyarı:</b> %d kayıt dosyası bulunamadı ve "
                      "istatistiğe girmedi: %s"
                      % (len(missing), ", ".join(missing)), p_body),
            Spacer(1, 3 * mm),
        ]

    # --- overlay chart -------------------------------------------------------
    axis, mean_values = mean_waveform(traces)
    drawing = overlay_drawing(traces, axis, mean_values, font=font,
                              font_bold=font_bold)
    if drawing is not None:
        story += [
            PageBreak(),
            Paragraph("Serinin bindirmeli dalga biçimi", p_h4),
            drawing,
            Paragraph(
                "Soluk çizgiler serideki tek tek şoklar, koyu turuncu çizgi "
                "ortak zaman eksenine taşınmış <b>ortalama dalgadır</b>. "
                "Çizgilerin birbirinden ayrılması tekrarlanabilirliğin "
                "bozulduğu bölgeyi doğrudan gösterir.", p_body),
            Spacer(1, 4 * mm),
        ]

    # --- statistics ------------------------------------------------------------
    stat_rows = statistics_rows(analyses)
    if stat_rows:
        data = [["Büyüklük", "n", "Ortalama", "Std. sapma s",
                 "u = s/√n", "U (k=2)", "En küçük", "En büyük"]]
        for label, unit, fmt, s in stat_rows:
            data.append([
                label, str(s["n"]),
                format_value(s["mean"], unit, fmt),
                format_value(s["std"], unit, fmt),
                format_value(s["u"], unit, fmt),
                format_value(s["U"], unit, fmt),
                format_value(s["min"], unit, fmt),
                format_value(s["max"], unit, fmt),
            ])
        story += [
            Paragraph("Seri istatistiği", p_h4),
            grid_table(data,
                       widths=(42 * mm, 8 * mm, 20 * mm, 20 * mm, 18 * mm,
                               18 * mm, 17 * mm, 17 * mm),
                       aligns=(1, 2, 3, 4, 5, 6, 7)),
            Paragraph(
                "Standart sapma örnek standart sapmasıdır (n−1 bölen). "
                "u yalnızca <b>A tipi</b> (tekrarlanabilirlik) bileşenidir; "
                "bölücü oranının, yük direncinin ve osiloskobun katkıları "
                "dahil değildir. U = 2u, yaklaşık %95 kapsam olasılığına "
                "karşılık gelir.", p_body),
            Spacer(1, 4 * mm),
        ]

    # --- shock-by-shock energy chart ------------------------------------------
    scatter = energy_scatter(analyses, nominal_j, verdict.get("tolerance"),
                             font=font)
    if scatter is not None:
        story += [
            KeepTogether([
                Paragraph("Şok şok aktarılan enerji", p_h4),
                scatter,
            ]),
            Paragraph(
                "Her şokun yüke aktardığı enerji sırayla; değerler noktaların "
                "üstünde yazılıdır. Düz çizgi ortalama, kesikli çizgiler "
                "<b>± bir standart sapma (s)</b>, soluk bant ise ortalamanın "
                "genişletilmiş belirsizliğidir (± U, k=2). Noktalı çizgi "
                "cihazda ayarlanan enerjidir. Tek bir kaçak şok ile bütün "
                "serinin sürüklenmesi ancak bu sırada bakınca ayırt edilir; "
                "istatistik tablosu dağılımın sayısını verir, şeklini değil.",
                p_body),
            Spacer(1, 4 * mm),
        ]

    # --- pass/fail decision ----------------------------------------------------
    # This is the certificate's central statement. If the set energy wasn't
    # entered, no decision is made and the document says so explicitly —
    # silently saying "pass" would make an unevaluated device look like it
    # passed.
    stats = verdict["stats"]
    tolerance = verdict["tolerance"]
    if nominal_j and stats:
        verdict_rows = [
            ("Ayarlanan enerji", "%.4g J" % float(nominal_j)),
            ("Ölçülen ortalama", "%.4g J" % stats["mean"]),
            ("Sapma", "%+.4g J" % verdict["deviation"]),
            ("Genişletilmiş belirsizlik U (k=2)", "%.4g J" % stats["U"]),
            ("İzin verilen tolerans",
             "± %.4g J  (IEC 60601-2-4: ayarın %%%d'i ya da %.4g J — büyük olan)"
             % (tolerance, int(defib.ENERGY_TOLERANCE_RATIO * 100),
                defib.ENERGY_TOLERANCE_FLOOR_J)),
            ("Karar kuralı", "|sapma| + U ≤ tolerans"),
        ]
    else:
        verdict_rows = [
            ("Ayarlanan enerji", "girilmedi"),
            ("Ölçülen ortalama",
             "%.4g J" % stats["mean"] if stats else "hesaplanamadı"),
        ]
    # Heading, table, and the "Result: ..." line are all in **one
    # KeepTogether**: as separate flowables, a page break could fall
    # between them and split the decision from its rationale, leaving the
    # document's most important sentence stranded at the top of a page.
    verdict_block = [
        Paragraph("Uygunluk değerlendirmesi", p_h4),
        Paragraph(
            "Karar kuralı: ölçülen ortalamanın ayarlanan enerjiden sapması, "
            "ölçümün kendi belirsizliğiyle (genişletilmiş belirsizlik U) "
            "birlikte izin verilen toleransı aşmıyorsa sonuç UYGUN'dur; "
            "aşıyorsa UYGUN DEĞİL'dir. Tolerans IEC 60601-2-4'e göre "
            "belirlenir.", p_body),
        kv_table(verdict_rows),
        Spacer(1, 2 * mm),
        Paragraph("<b>Sonuç: %s</b>" % certificate.VERDICT_TR[result], p_h2),
    ]
    if result == "info":
        verdict_block.append(Paragraph(
            "Cihazda ayarlanan enerji kaydedilmediği için uygunluk kararı "
            "verilmemiştir; belge ölçülen değerleri bildirir. Karar "
            "gerekiyorsa seri, ayarlanan enerji girilerek tekrarlanmalıdır.",
            p_body))
    else:
        total = abs(verdict["deviation"]) + stats["U"]
        verdict_block.append(Paragraph(
            "Bu rapor için: |%.4g − %.4g| + U = %.4g + %.4g = <b>%.4g J</b>, "
            "izin verilen toleransın (± %.4g J) <b>%s</b> kaldığı için "
            "sonuç <b>%s</b>'dir."
            % (stats["mean"], float(nominal_j), abs(verdict["deviation"]),
               stats["U"], total, tolerance,
               "altında" if total <= tolerance else "üstünde",
               certificate.VERDICT_TR[result]),
            p_body))
    story += [KeepTogether(verdict_block), Spacer(1, 4 * mm)]

    # --- measurement-by-measurement table --------------------------------------
    data = [["#", "Zaman", "Enerji", "Tepe gerilim", "Tepe akım",
             "Toplam süre", "Kayıt dosyası"]]
    for i, (row, an) in enumerate(zip(rows, analyses), start=1):
        no = row["series_index"] or i
        if an and an.get("found"):
            cells = ["%.4g J" % an["energy_j"],
                     defib._v(an["peak_voltage"]),
                     "%.4g A" % an["peak_current"],
                     defib._s(an["total_duration"])]
        else:
            reason = (an or {}).get("reason", "çözümlenemedi")
            cells = [reason, "—", "—", "—"]
        data.append([str(no),
                     (row["captured_at"] or "").replace("T", " ")[11:19],
                     cells[0], cells[1], cells[2], cells[3],
                     os.path.basename(row["file_path"])])
    story += [
        Paragraph("Ölçüm ölçüm sonuçlar", p_h4),
        grid_table(data,
                   widths=(8 * mm, 18 * mm, 20 * mm, 24 * mm, 20 * mm,
                           22 * mm, 48 * mm),
                   aligns=(2, 3, 4, 5)),
        Spacer(1, 4 * mm),
    ]

    # --- measurement-by-measurement: screenshot + chart drawn from the recording ---
    # The single-shock report provides both because they answer different
    # questions (what the device saw / what's computed from the recording).
    # The same reasoning applies to the series — the screenshot alone
    # doesn't show why an outlier shock is an outlier (phase boundaries,
    # peak point).
    detail = [(row, row["screenshot_path"], row_series[i], analyses[i])
             for i, row in enumerate(rows)
             if row["screenshot_path"] and os.path.isfile(row["screenshot_path"])]

    def shock_block(row, shot, series_data, analysis):
        idx = row["series_index"] or 0
        col_w = 78 * mm

        try:
            iw, ih = ImageReader(shot).getSize()
            shot_img = Image(shot, width=col_w, height=col_w * ih / float(iw))
        except Exception:
            shot_img = Paragraph("ekran görüntüsü okunamadı", p_body)

        if series_data is not None:
            times, columns = series_data
            # Tried up to 48 mm height: since font size stays fixed
            # (5.5-6 pt), the peak/phase labels overlapped at the top edge.
            # They separate cleanly at 58 mm.
            drawing = shockreport.waveform_drawing(
                times, columns, analysis, width=col_w, height=58 * mm,
                font=font, font_bold=font_bold)
            if drawing is None:
                drawing = Paragraph("grafik çizilemedi", p_body)
        else:
            drawing = Paragraph("kayıt dosyası bulunamadı", p_body)

        header = [Paragraph("<b>%d. şok</b> — ekran görüntüsü" % idx, p_body),
                  Paragraph("<b>%d. şok</b> — kayıttan çizilen grafik" % idx,
                           p_body)]
        # Heading and images are in **one inner table**, wrapped with
        # KeepTogether: as separate flowables, a page break could fall
        # between them and leave the heading on one page, the image on
        # another.
        inner = Table([header, [shot_img, drawing]],
                      colWidths=[col_w, col_w])
        inner.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        return KeepTogether(inner)

    if detail:
        story.append(PageBreak())
        story.append(Paragraph(
            "Ölçüm ölçüm: ekran görüntüsü ve kayıttan çizilen grafik", p_h4))
        for row, shot, series_data, analysis in detail:
            story.append(shock_block(row, shot, series_data, analysis))
            story.append(Spacer(1, 5 * mm))

    # --- source files ------------------------------------------------------
    p_hash = ParagraphStyle("ozet", parent=base["BodyText"], fontName=font,
                            fontSize=6.5, leading=8.5, wordWrap="CJK")
    data = [["#", "Kayıt dosyası", "SHA-256", "Bütünlük"]]
    for i, row in enumerate(rows, start=1):
        state, message = waveform.verify(row["id"])
        data.append([str(row["series_index"] or i),
                     Paragraph(os.path.basename(row["file_path"]), p_hash),
                     Paragraph(row["sha256"] or "—", p_hash),
                     Paragraph(message, p_hash)])
    story += [
        Paragraph("Kaynak dosyalar ve bütünlük denetimi", p_h4),
        grid_table(data, widths=(8 * mm, 52 * mm, 58 * mm, 42 * mm)),
        Spacer(1, 4 * mm),
        Paragraph(shockreport.DISCLAIMER, p_body),
        Spacer(1, 8 * mm),
        kv_table([("Ölçümü yapan", head["operator_name"]),
                  ("Onaylayan",
                   "................................................")]),
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

    # The report number is written to **all** of the series' records: no
    # matter which row is viewed in the list, that the report was produced
    # should be visible.
    db.execute(
        "UPDATE waveform_captures SET report_no = ?, report_path = ?,"
        " report_sha256 = ? WHERE series_id = ?",
        (report_no, path, sha, series_id))
    audit.log("waveform.series_report", user_id=issued_by, entity="instrument",
              entity_id=head["instrument_id"],
              detail={"series_id": series_id, "report_no": report_no,
                      "sha256": sha, "simulated": simulated,
                      "captures": len(rows), "analyzed": len(good),
                      "missing_files": missing, "result": result,
                      "nominal_energy_j": nominal_j,
                      "font_ascii_fallback": ascii_only})

    # Record in the certificate register: approval, soft deletion, and the
    # certificate listing come from here. The report number is used as
    # `cert_no` — stamping a second number on the document would mean the
    # same output has two names.
    certificate.register_series(series_id, report_no, issued_by, result, path,
                                sha)
    return path, report_no
