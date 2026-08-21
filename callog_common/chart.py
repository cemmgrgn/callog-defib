"""Measurement chart for the certificate (reportlab.graphics — vector, no Qt needed).

The chart has two panels:

* **Top panel** — readings over time. Tolerance band, nominal line, mean and
  the x̄ ± U band, ±s error bars per reading, excluded readings marked
  separately.
* **Bottom panel** — distribution of the readings (histogram). This shows
  whether the measurement is symmetric and single-peaked; a shift or a
  second peak points to an unstable instrument or to warm-up not having
  finished.

The meaning of the error bars was chosen deliberately: since each point is a
**single reading**, the bars show ±s (the standard deviation of a single
reading). The uncertainty of the result is a different thing — that's the
x̄ ± U band around the mean. A caption below the chart spells this out so
the two aren't confused.
"""

import math

from reportlab.graphics.shapes import (Circle, Drawing, Group, Line, PolyLine,
                                       Rect, String)
from reportlab.lib import colors
from reportlab.lib.units import mm

from . import db
from .i18n import t

# --- colors (low saturation so the certificate can be printed in black and white) ---
C_AXIS = colors.HexColor("#666666")
C_GRID = colors.HexColor("#DDDDDD")
C_POINT = colors.HexColor("#185FA5")
C_ERR = colors.HexColor("#9AA7B4")
C_MEAN = colors.HexColor("#0F6E56")
C_UBAND = colors.HexColor("#DCEFE7")
C_TOL = colors.HexColor("#F2F5F8")
C_TOL_EDGE = colors.HexColor("#9AA7B4")
C_NOMINAL = colors.HexColor("#555555")
C_EXCLUDED = colors.HexColor("#A32D2D")
C_TEXT = colors.HexColor("#444444")


def _nice_ticks(lo, hi, count=5):
    """Generates readable axis values (in steps of 1, 2, 5 x 10^n)."""
    if hi <= lo:
        hi = lo + 1.0
    raw = (hi - lo) / max(1, count)
    magnitude = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
    for mult in (1, 2, 2.5, 5, 10):
        step = mult * magnitude
        if raw <= step:
            break
    start = math.ceil(lo / step) * step
    ticks = []
    value = start
    while value <= hi + step * 1e-9:
        ticks.append(value)
        value += step
    return ticks


def _fmt(value, span):
    """Axis label: picks a meaningful number of digits based on the range."""
    if span <= 0:
        return "%.6g" % value
    digits = max(0, int(math.ceil(-math.log10(span / 6.0))) + 1)
    return ("%%.%df" % min(digits, 9)) % value


def load_series(session_id, point=None, is_first=False):
    """Fetches the session's readings along with exclusion info.

    If `point` is given, only that point's readings are returned. If
    `is_first`, unowned readings (`point_id IS NULL`) are also counted
    toward this point — this is where data from sessions taken before the
    plan concept existed ends up.
    """
    sql = ("SELECT r.seq, r.value, r.elapsed_s, e.id AS excluded_id"
           " FROM readings r"
           " LEFT JOIN reading_exclusions e ON e.reading_id = r.id"
           " WHERE r.session_id = ?")
    params = [session_id]
    if point is not None:
        sql += (" AND (r.point_id = ? OR r.point_id IS NULL)" if is_first
                else " AND r.point_id = ?")
        params.append(point["id"])
    rows = db.query(sql + " ORDER BY r.seq", tuple(params))
    included, excluded = [], []
    for i, r in enumerate(rows):
        # elapsed_s can be empty in old records; falls back to the sequence number
        x = r["elapsed_s"] if r["elapsed_s"] is not None else float(i)
        (excluded if r["excluded_id"] else included).append((x, r["value"]))
    return included, excluded


def session_drawing(session_id, width=165 * mm, height=95 * mm, font="Helvetica",
                    font_bold=None, summary=None, is_first=True):
    """Produces a single measurement point's chart as a Drawing.

    If `summary` isn't given, the session's **first** point is drawn — same
    behavior as before for a single-point session. For a multi-point
    certificate the caller calls this separately for each point: plotting
    10 V and 1 kΩ on the same Y axis in one chart would make both unreadable.

    Returns None if there's no data — the caller skips the chart.
    """
    from .certificate import collect

    font_bold = font_bold or font
    data = collect(session_id)
    if summary is None:
        summary = data["points"][0]
        is_first = True
    unit = summary["unit"]
    included, excluded = load_series(session_id, summary["point"], is_first)
    if not included:
        return None

    mean, std, U = summary["mean"], summary["std"], summary["U"]
    nominal, tolerance = summary["nominal"], summary["tolerance"]
    n_included = summary["n"]

    d = Drawing(width, height)

    # --- layout -------------------------------------------------------------
    left, right = 20 * mm, 4 * mm
    caption_h = 17 * mm      # caption + histogram axis labels
    hist_h = 20 * mm
    gap = 9 * mm
    main_bottom = caption_h + hist_h + gap
    main_h = height - main_bottom - 4 * mm
    plot_w = width - left - right

    # --- Y scale: data + tolerance + uncertainty band must all fit --------
    values = [v for _x, v in included] + [v for _x, v in excluded]
    y_lo, y_hi = min(values), max(values)
    y_lo = min(y_lo, mean - max(U, std))
    y_hi = max(y_hi, mean + max(U, std))
    if tolerance and nominal is not None:
        y_lo = min(y_lo, nominal - tolerance)
        y_hi = max(y_hi, nominal + tolerance)
    if y_hi - y_lo < 1e-15:
        y_lo, y_hi = y_lo - 1e-6, y_hi + 1e-6
    pad = (y_hi - y_lo) * 0.12
    y_lo, y_hi = y_lo - pad, y_hi + pad

    xs = [x for x, _v in included] + [x for x, _v in excluded]
    x_lo, x_hi = min(xs), max(xs)
    if x_hi - x_lo < 1e-9:
        x_hi = x_lo + 1.0

    def px(x):
        return left + (x - x_lo) / (x_hi - x_lo) * plot_w

    def py(v):
        return main_bottom + (v - y_lo) / (y_hi - y_lo) * main_h

    # --- main panel frame and grid -----------------------------------------
    d.add(Rect(left, main_bottom, plot_w, main_h, fillColor=colors.white,
               strokeColor=C_AXIS, strokeWidth=0.5))

    y_span = y_hi - y_lo
    for value in _nice_ticks(y_lo, y_hi, 5):
        y = py(value)
        d.add(Line(left, y, left + plot_w, y, strokeColor=C_GRID, strokeWidth=0.3))
        d.add(String(left - 2, y - 2, _fmt(value, y_span), fontName=font,
                     fontSize=5.5, fillColor=C_TEXT, textAnchor="end"))
    for value in _nice_ticks(x_lo, x_hi, 6):
        x = px(value)
        d.add(Line(x, main_bottom, x, main_bottom + main_h, strokeColor=C_GRID,
                   strokeWidth=0.3))
        d.add(String(x, main_bottom - 6, _fmt(value, x_hi - x_lo), fontName=font,
                     fontSize=5.5, fillColor=C_TEXT, textAnchor="middle"))

    d.add(String(left + plot_w / 2.0, main_bottom - 12, t("Süre (s)"),
                 fontName=font,
                 fontSize=6, fillColor=C_TEXT, textAnchor="middle"))
    y_title = Group(String(0, 0, "%s (%s)" % (summary["function"], unit),
                           fontName=font,
                           fontSize=6, fillColor=C_TEXT, textAnchor="middle"))
    y_title.translate(7, main_bottom + main_h / 2.0)
    y_title.rotate(90)
    d.add(y_title)

    # --- tolerance band ------------------------------------------------------
    if tolerance and nominal is not None:
        top = min(nominal + tolerance, y_hi)
        bottom = max(nominal - tolerance, y_lo)
        d.add(Rect(left, py(bottom), plot_w, py(top) - py(bottom),
                   fillColor=C_TOL, strokeColor=None))
        for edge in (nominal - tolerance, nominal + tolerance):
            if y_lo <= edge <= y_hi:
                d.add(Line(left, py(edge), left + plot_w, py(edge),
                           strokeColor=C_TOL_EDGE, strokeWidth=0.6,
                           strokeDashArray=[3, 2]))

    # --- x̄ ± U band and mean -------------------------------------------
    if U > 0:
        d.add(Rect(left, py(mean - U), plot_w, py(mean + U) - py(mean - U),
                   fillColor=C_UBAND, strokeColor=None))
    d.add(Line(left, py(mean), left + plot_w, py(mean), strokeColor=C_MEAN,
               strokeWidth=0.9))

    if nominal is not None and y_lo <= nominal <= y_hi:
        d.add(Line(left, py(nominal), left + plot_w, py(nominal),
                   strokeColor=C_NOMINAL, strokeWidth=0.6,
                   strokeDashArray=[1, 2]))

    # --- data: curve + error bars + points ---------------------------------
    if len(included) > 1:
        path = []
        for x, v in included:
            path.extend([px(x), py(v)])
        d.add(PolyLine(path, strokeColor=C_POINT, strokeWidth=0.5))

    # Error bars are thinned out when there are many points; otherwise the
    # chart turns into an unreadable comb.
    step = max(1, len(included) // 40)
    cap = 1.1
    for i, (x, v) in enumerate(included):
        x_pos = px(x)
        if std > 0 and i % step == 0:
            top, bottom = py(v + std), py(v - std)
            d.add(Line(x_pos, bottom, x_pos, top, strokeColor=C_ERR,
                       strokeWidth=0.4))
            d.add(Line(x_pos - cap, top, x_pos + cap, top, strokeColor=C_ERR,
                       strokeWidth=0.4))
            d.add(Line(x_pos - cap, bottom, x_pos + cap, bottom,
                       strokeColor=C_ERR, strokeWidth=0.4))
        d.add(Circle(x_pos, py(v), 0.9, fillColor=C_POINT, strokeColor=None))

    for x, v in excluded:
        x_pos, y_pos = px(x), py(v)
        r = 1.6
        d.add(Line(x_pos - r, y_pos - r, x_pos + r, y_pos + r,
                   strokeColor=C_EXCLUDED, strokeWidth=0.7))
        d.add(Line(x_pos - r, y_pos + r, x_pos + r, y_pos - r,
                   strokeColor=C_EXCLUDED, strokeWidth=0.7))

    # --- histogram -----------------------------------------------------------
    _add_histogram(d, [v for _x, v in included], left, caption_h, plot_w, hist_h,
                   mean, font, unit)

    # --- caption ---------------------------------------------------------
    legend = [t(x) for x in ("● okuma", "│ ±s (tek okuma)", "─ ortalama",
                             "░ x̄ ± U (k=2)")]
    if tolerance:
        legend.append(t("░ tolerans bandi"))
    if excluded:
        legend.append(t("× dislanan (%d)") % len(excluded))
    d.add(String(left, caption_h - 17, "   ".join(legend), fontName=font,
                 fontSize=5.5, fillColor=C_TEXT))
    d.add(String(
        left, caption_h - 25,
        "n = %d  ·  x̄ = %.7g %s  ·  s = %.3g %s  ·  U = %.3g %s (k=2)"
        % (n_included, mean, unit, std, unit, U, unit),
        fontName=font_bold, fontSize=5.5, fillColor=C_TEXT))
    return d


def _add_histogram(d, values, left, bottom, width, height, mean, font, unit):
    """Distribution of the readings — shows whether the measurement is symmetric."""
    if len(values) < 4:
        return
    lo, hi = min(values), max(values)
    if hi - lo < 1e-15:
        return

    bins = max(6, min(24, int(math.sqrt(len(values))) * 2))
    step = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = min(bins - 1, int((v - lo) / step))
        counts[idx] += 1
    peak = max(counts) or 1

    d.add(Rect(left, bottom, width, height, fillColor=colors.white,
               strokeColor=C_AXIS, strokeWidth=0.5))
    bar_w = width / float(bins)
    for i, count in enumerate(counts):
        if not count:
            continue
        h = (count / float(peak)) * (height - 3)
        d.add(Rect(left + i * bar_w + 0.4, bottom, bar_w - 0.8, h,
                   fillColor=C_UBAND, strokeColor=C_POINT, strokeWidth=0.3))

    x_mean = left + (mean - lo) / (hi - lo) * width
    d.add(Line(x_mean, bottom, x_mean, bottom + height, strokeColor=C_MEAN,
               strokeWidth=0.8))
    span = hi - lo
    d.add(String(left + 2, bottom + height - 6, t("Dagilim"), fontName=font,
                 fontSize=5.5, fillColor=C_TEXT))
    d.add(String(left, bottom - 6, _fmt(lo, span), fontName=font, fontSize=5,
                 fillColor=C_TEXT))
    d.add(String(left + width, bottom - 6, _fmt(hi, span), fontName=font,
                 fontSize=5, fillColor=C_TEXT, textAnchor="end"))


def png(session_id, path, scale=3.0, font="Helvetica", font_bold=None):
    """Writes the same chart as a PNG (for DOCX output).

    Return: the file path, or None if there's no data.
    """
    from reportlab.graphics import renderPM

    drawing = session_drawing(session_id, font=font, font_bold=font_bold)
    if drawing is None:
        return None
    drawing.scale(scale, scale)
    drawing.width *= scale
    drawing.height *= scale
    renderPM.drawToFile(drawing, path, "PNG", bg=0xFFFFFF)
    return path
