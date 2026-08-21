"""Live statistics calculation. Kept independent of Qt — so it can be
tested without a device or interface.
"""


#: Conformity criteria
CRITERION_MEAN = "mean"        # is mean +- U within tolerance
CRITERION_MINMAX = "minmax"    # are all readings within tolerance


def verdict_ok(mode, nominal, tolerance, mean, u_a, minimum, maximum, k=2):
    """Conformity decision. Tolerance is always taken as +- (absolute).

    ``mean``   — requires the deviation, together with the expanded
                 uncertainty, to fit within the tolerance band:
                 |x_bar - nominal| + k.u <= T. This is the decision rule
                 commonly used in calibration.
    ``minmax`` — not conforming if even a single reading falls outside the
                 band. Catches deviations the mean would hide on an unstable
                 device.
    """
    if nominal is None or not tolerance:
        return None
    tolerance = abs(tolerance)
    if mode == CRITERION_MINMAX:
        if minimum is None or maximum is None:
            return None
        return (minimum >= nominal - tolerance) and (maximum <= nominal + tolerance)
    return abs(mean - nominal) + k * u_a <= tolerance


class Statistics(object):
    """Single-pass mean and standard deviation via Welford's method.

    Why Welford: re-summing the whole array on every reading gets slow over
    long sessions, and floating-point error accumulates. Welford is both
    O(1) and numerically stable.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.n = 0
        self.mean = 0.0
        self._m2 = 0.0
        self.min = None
        self.max = None
        self.last = None

    def add(self, value):
        self.n += 1
        delta = value - self.mean
        self.mean += delta / self.n
        self._m2 += delta * (value - self.mean)
        self.last = value
        self.min = value if self.min is None else min(self.min, value)
        self.max = value if self.max is None else max(self.max, value)

    @property
    def std(self):
        """Sample standard deviation (divides by n-1)."""
        if self.n < 2:
            return 0.0
        return (self._m2 / (self.n - 1)) ** 0.5

    @property
    def u_a(self):
        """Type A standard uncertainty: s / sqrt(n)."""
        if self.n < 2:
            return 0.0
        return self.std / (self.n ** 0.5)

    @property
    def span(self):
        if self.min is None:
            return 0.0
        return self.max - self.min
