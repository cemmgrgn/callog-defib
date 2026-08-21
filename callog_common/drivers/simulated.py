"""Simulation driver — for development and demos without a device.

Produces realistic behavior: warm-up drift, white noise, and occasional
outliers. This lets the statistics panel, tolerance check, and outlier
flagging flow be tested without a real device.

Recordings taken with this driver are marked sessions.is_simulated = 1; the
generated certificate is watermarked and gets a number from the SIM- series.
"""

import math
import random
import time

from .base import Driver, MeasurementFunction

_NOMINALS = {
    "VDC": (10.0, 2e-5),        # (default nominal, relative noise)
    "VAC": (10.0, 8e-5),
    "IDC": (0.1, 5e-5),
    "IAC": (0.1, 1e-4),
    "RES": (1000.0, 3e-5),
    "FRES": (1000.0, 1e-5),
    "FREQ": (1000.0, 1e-6),
    "PER": (1e-3, 1e-6),
    "CAP": (1e-6, 5e-4),
}


class SimulatedDMM(Driver):
    """Mimics the behavior of the Fluke 8846A."""

    FUNCTIONS = [
        MeasurementFunction("VDC", "DC gerilim", "V"),
        MeasurementFunction("VAC", "AC gerilim", "V"),
        MeasurementFunction("IDC", "DC akım", "A"),
        MeasurementFunction("IAC", "AC akım", "A"),
        MeasurementFunction("RES", "Direnç (2 telli)", "Ω"),
        MeasurementFunction("FRES", "Direnç (4 telli)", "Ω"),
        MeasurementFunction("FREQ", "Frekans", "Hz"),
        MeasurementFunction("PER", "Periyot", "s"),
        MeasurementFunction("CAP", "Kapasitans", "F"),
    ]

    def __init__(self, address="SIM", nominal=None, **kwargs):
        Driver.__init__(self, address, **kwargs)
        self._t0 = time.time()
        self._nominal_override = nominal
        self._nominal = 10.0
        self._noise = 2e-5

    @property
    def is_simulated(self):
        return True

    def connect(self):
        self.identity = "FLUKE,8846A,SIM-8846A,SIMULASYON-1.0"
        return self.identity

    def close(self):
        pass

    def identify(self):
        return self.identity or "FLUKE,8846A,SIM-8846A,SIMULASYON-1.0"

    def check_errors(self):
        return []

    def configure(self, function_key, **settings):
        nominal, noise = _NOMINALS.get(function_key, (1.0, 1e-4))
        # When the measurement plan moves to the next point, the simulation
        # must move to the new point too: otherwise all three of the 10 V,
        # 1 V, and 1 kOhm points would read the single value entered at the
        # start of the session, and the plan couldn't be tested.
        if "nominal" in settings:
            self._nominal_override = settings["nominal"]
        self._nominal = self._nominal_override if self._nominal_override else nominal
        self._noise = noise
        self._function = function_key
        self._t0 = time.time()

    def read_one(self):
        elapsed = time.time() - self._t0

        # Warm-up drift: settles onto the nominal exponentially over the
        # first ~3 minutes
        warmup = 3.0 * self._noise * math.exp(-elapsed / 180.0)
        # Slow thermal oscillation
        drift = 0.5 * self._noise * math.sin(elapsed / 45.0)
        # White noise
        noise = random.gauss(0.0, self._noise)

        value = self._nominal * (1.0 + warmup + drift + noise)

        # About a 0.5% chance of an outlier — to test the flagging flow
        if random.random() < 0.005:
            value *= 1.0 + random.choice((-1, 1)) * 12 * self._noise

        return value, "%+.8E" % value
