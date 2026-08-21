"""Trend of a measurement point over the years, and limit-crossing forecast.

The trend chart in the device register plotted points but didn't answer the
real question: *when does this device need to be adjusted?*

The slope is fitted against **calendar day**, not measurement order: two
calibrations might be six months apart or six days apart, and using a
sequence number hides that difference, making the "how much does it drift
per year" answer meaningless.

Independent of Qt and the database — its input is (date, value) pairs.
"""

from datetime import date, timedelta

#: Minimum points needed for a trend line. Two points always give a perfect
#: line; the "drifts by this much per year" estimate drawn from it describes
#: noise more than the actual instrument.
MIN_POINTS = 3

#: Shortest observation span (days) for the forecast to be considered
#: meaningful. Reading an annual drift rate from three measurements taken
#: within the same week would be misleading.
MIN_SPAN_DAYS = 30

DAYS_PER_YEAR = 365.25


def parse_day(value):
    """Extracts a date from an ISO timestamp (``2026-08-11T07:03:22+00:00``)."""
    if not value:
        return None
    try:
        parts = str(value)[:10].split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None


def fit(xs, ys):
    """Least-squares line. Returns: ``(slope, intercept, r2)``.

    If all x's are equal (measurements taken on a single day), the slope is
    undefined — returns ``None``, not zero: "not drifting" and "can't tell"
    aren't the same thing.
    """
    n = len(xs)
    if n < 2 or len(ys) != n:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    syy = sum((y - mean_y) ** 2 for y in ys)
    r2 = 1.0 if syy == 0 else max(0.0, min(1.0, (sxy * sxy) / (sxx * syy)))
    return slope, intercept, r2


def analyse(points, nominal=None, tolerance=None, min_points=MIN_POINTS,
            today=None):
    """Drift trend and — if a tolerance is given — a limit-crossing forecast.

    ``points``: ``(timestamp, value)`` pairs (extra fields are ignored).
    Returns ``None`` if there's no trend to plot.

    Return dict:
      ``slope_per_day`` / ``slope_per_year`` — drift rate
      ``r2``       — how much the fit explains (0...1)
      ``days``     — days since the first measurement, for plotting
      ``fitted``   — the line's values on those same days
      ``span_days``— span between the first and last measurement
      ``crossing`` — ``{"limit", "days", "date", "years"}`` or ``None``
    """
    pairs = []
    for p in points:
        day = parse_day(p[0])
        if day is None or p[1] is None:
            continue
        pairs.append((day, float(p[1])))
    if len(pairs) < max(2, min_points):
        return None

    pairs.sort(key=lambda item: item[0])
    origin = pairs[0][0]
    days = [(d - origin).days for d, _ in pairs]
    values = [v for _, v in pairs]

    fitted = fit(days, values)
    if fitted is None:
        return None
    slope, intercept, r2 = fitted

    result = {
        "slope_per_day": slope,
        "slope_per_year": slope * DAYS_PER_YEAR,
        "intercept": intercept,
        "r2": r2,
        "n": len(pairs),
        "origin": origin,
        "days": days,
        "fitted": [intercept + slope * d for d in days],
        "span_days": days[-1],
        "last_day": pairs[-1][0],
        "crossing": None,
        "reliable": days[-1] >= MIN_SPAN_DAYS and len(pairs) >= min_points,
    }
    result["crossing"] = _crossing(result, nominal, tolerance, today)
    return result


def _crossing(trend, nominal, tolerance, today=None):
    """Which day the line will cross the tolerance limit.

    Only computed for a slope heading *outward*. For a device staying within
    the band or trending inward, "when will it cross" has no answer; it's
    also skipped when the slope is zero, to avoid dividing by it.
    """
    if nominal is None or not tolerance or not trend["slope_per_day"]:
        return None
    tolerance = abs(tolerance)
    slope = trend["slope_per_day"]
    today = today or date.today()

    # Today's estimate: where the line has reached, from the first
    # measurement to today.
    day_now = (today - trend["origin"]).days
    value_now = trend["intercept"] + slope * day_now

    limit = nominal + tolerance if slope > 0 else nominal - tolerance
    if (slope > 0 and value_now > limit) or (slope < 0 and value_now < limit):
        # Already outside — this is the current state, not a forecast.
        return {"limit": limit, "days": 0, "date": today, "years": 0.0,
                "already_out": True}

    days_left = (limit - value_now) / slope
    if days_left < 0:
        return None
    days_left = int(round(days_left))
    try:
        when = today + timedelta(days=days_left)
    except OverflowError:
        # If the slope is very close to zero, the forecast points thousands
        # of years out; a number like that is noise on screen, not information.
        return None
    return {"limit": limit, "days": days_left, "date": when,
            "years": days_left / DAYS_PER_YEAR, "already_out": False}


def summary_tr(trend, unit=""):
    """Describes the trend in one sentence — for the caption under the chart."""
    if trend is None:
        return "Eğilim çizgisi için en az %d ölçüm gerekiyor." % MIN_POINTS

    unit = (" " + unit) if unit else ""
    parts = ["Eğilim: %+.3g%s/yıl (r² = %.2f, %d ölçüm, %d gün)"
             % (trend["slope_per_year"], unit, trend["r2"], trend["n"],
                trend["span_days"])]
    if not trend["reliable"]:
        parts.append("Gözlem aralığı %d günden kısa — yıllık hız tahmini "
                     "güvenilir değil." % MIN_SPAN_DAYS)

    crossing = trend["crossing"]
    if crossing is None:
        parts.append("Tolerans sınırına doğru bir eğilim görünmüyor.")
    elif crossing["already_out"]:
        parts.append("Eğilim çizgisi tolerans sınırının (%.7g%s) dışında."
                     % (crossing["limit"], unit))
    elif crossing["days"] > 3650:
        parts.append("Bu hızla sınıra (%.7g%s) on yıldan uzun süre var."
                     % (crossing["limit"], unit))
    else:
        parts.append("Bu hızla giderse %.7g%s sınırını %s tarihinde aşar "
                     "(%d gün ≈ %.1f yıl)."
                     % (crossing["limit"], unit, crossing["date"].isoformat(),
                        crossing["days"], crossing["years"]))
    return "  ".join(parts)
