"""Stability assessment and outlier reading detection.

The operator used to decide "has the reading settled" by eye; that's why the
same measurement used to take different amounts of time with different
operators. The rule here is written down, so it's repeatable.

Kept independent of Qt — so it can be tested without a device or interface.
`stats.Statistics` gives a single-pass summary (mean, s, u); the
calculations here work over **a window of the last N readings**, so they
need to see the array.
"""

#: Window over which stability is assessed (number of readings)
DEFAULT_WINDOW = 20

#: No decision is made below this count. Calling three readings "stable"
#: says the reading hasn't even started, not that it has settled.
MIN_SAMPLES = 5

#: Outlier reading threshold. Even 3s produces about three false alarms per
#: thousand in everyday noise; over a long session that's a warning every
#: hundred readings.
OUTLIER_K = 4.0

#: Number of readings required before outlier detection starts. With too
#: few readings, s itself is unreliable and the second reading comes out
#: "outlier".
MIN_OUTLIER_SAMPLES = 10

UNKNOWN = "unknown"
DRIFTING = "drifting"
NOISY = "noisy"
STABLE = "stable"

STATE_TR = {
    UNKNOWN: "veri toplanıyor",
    DRIFTING: "oturuyor",
    NOISY: "saçılım geniş",
    STABLE: "kararlı",
}

#: Theme color key for the state. We don't keep the color value here: the
#: module doesn't know about Qt or the theme, only what meaning it carries.
STATE_COLOR = {
    UNKNOWN: "text_muted",
    DRIFTING: "warn",
    NOISY: "warn",
    STABLE: "ok",
}


def mean_std(values):
    """(mean, sample standard deviation). s = 0 for a single reading."""
    n = len(values)
    if n == 0:
        return None, 0.0
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean, var ** 0.5


def slope(values, interval_s=1.0):
    """Least-squares slope — units / second.

    Readings are assumed evenly spaced; using the sequence index instead of
    an actual timestamp only gives a correct slope if the interval is
    constant, which holds since `AcquisitionWorker` reads on a fixed period.
    """
    n = len(values)
    if n < 2 or interval_s <= 0:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    sxx = sum((i - mean_x) ** 2 for i in range(n))
    if sxx == 0:
        return 0.0
    sxy = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    return (sxy / sxx) / interval_s


def assess(values, interval_s=1.0, window=DEFAULT_WINDOW, tolerance=None,
           min_samples=MIN_SAMPLES):
    """Produces a stability state by looking at the last `window` readings.

    Returns: ``{"state", "n", "mean", "std", "spread", "slope", "drift"}`` —
    ``slope`` is units/second, ``drift`` is the accumulated change over the
    window.

    Decision order:

    * ``n < min_samples`` -> **unknown**.
    * ``|drift| > 2s`` -> **drifting**. If the accumulated *directional*
      change over the window exceeds the noise, the reading is still
      settling. Looking at spread alone isn't enough: a noise-free but
      steadily climbing reading would look like "narrow spread".
    * a tolerance is given and spread > tolerance -> **noisy**. The mean of
      a reading that scatters wider than the band itself isn't reliable
      either.
    * otherwise -> **stable**.
    """
    window_values = list(values)[-window:] if window else list(values)
    n = len(window_values)
    result = {"state": UNKNOWN, "n": n, "mean": None, "std": 0.0,
              "spread": 0.0, "slope": 0.0, "drift": 0.0}
    if n < max(2, min_samples):
        return result

    mean, std = mean_std(window_values)
    per_s = slope(window_values, interval_s)
    drift = per_s * (n - 1) * interval_s
    result.update({"mean": mean, "std": std, "slope": per_s, "drift": drift,
                   "spread": max(window_values) - min(window_values)})

    if abs(drift) > 2 * std:
        result["state"] = DRIFTING
    elif tolerance and result["spread"] > abs(tolerance):
        result["state"] = NOISY
    else:
        result["state"] = STABLE
    return result


def is_outlier(value, mean, std, n, k=OUTLIER_K,
               min_samples=MIN_OUTLIER_SAMPLES):
    """Outlier check for a single reading during a live measurement.

    `Statistics` already keeps the mean and s; a separate function so it can
    be asked without re-scanning the array. No decision is made when s = 0
    (all readings identical): at zero deviation, any differing reading comes
    out as infinite sigma.
    """
    if mean is None or n < min_samples or not std:
        return False
    return abs(value - mean) > k * std


def outliers(values, k=OUTLIER_K, min_samples=MIN_OUTLIER_SAMPLES):
    """Indices of outlier readings: ``|x - x_bar| > k.s``.

    We state the limitation deliberately: an outlier hides itself by pulling
    both the mean and s toward it, and two large outliers can mask each
    other. The list here is therefore a *suggestion*; the exclusion decision
    always goes on record together with the operator and their reasoning.
    """
    values = list(values)
    if len(values) < min_samples:
        return []
    mean, std = mean_std(values)
    if not std:
        return []
    limit = k * std
    return [i for i, v in enumerate(values) if abs(v - mean) > limit]
