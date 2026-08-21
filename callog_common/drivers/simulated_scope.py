"""Oscilloscope simulation — for development, demos, and testing without a device.

The waveform it produces and the scalar measurements it returns come from
**the same source**: the ``:MEASure:VPP?`` result is consistent with the
peak-to-peak value of the captured CSV. This consistency is essential —
otherwise a verification done in simulation would give a result that doesn't
hold on the real device, and simulation mode would inspire no confidence.

Recordings taken with this driver are marked ``is_simulated = 1``; the
generated certificate is watermarked and gets a number from the SIM- series.
"""

import math
import random
import struct
import time
import zlib

from .base import InstrumentError, MeasurementFunction, WaveformDriver

#: Simulated signal: 1 kHz, 2 Vpp sine, 0.2 V DC offset
SIGNAL = {
    "amplitude": 1.0,        # peak amplitude (V)
    "offset": 0.2,           # DC offset (V)
    "frequency": 1000.0,     # Hz
    "noise": 0.004,          # RMS noise (V)
    "rise_ratio": 0.35,      # rise time / period (~0.35 for a sine)
}

#: Channel 2 is an attenuated, phase-shifted version of the same signal — so
#: it's visible by eye that a two-channel capture is correctly aligned in the CSV.
CH2_GAIN = 0.5
CH2_PHASE = math.pi / 3.0

#: Simulated biphasic defibrillator shock (truncated exponential).
#: The durations are close to a typical biphasic device's. The peak voltage
#: is solved **from the configured energy** (see `defib_peak_for_energy`);
#: the "peak" below is only the fallback value used when no energy is given.
DEFIB = {
    "peak": 170.0,          # V — fallback peak used when no energy is given
    "tau": 9e-3,            # s — RC decay time constant
    "phase1": 6e-3,         # s — phase 1 duration
    "phase2": 4e-3,         # s — phase 2 duration
    "gap": 100e-6,          # s — polarity-switch dead time
    "phase2_ratio": 0.85,   # phase 2 start / phase 1 cutoff voltage
    "noise": 0.4,           # V
    "window": 50e-3,        # s — total time shown on screen
    #: The high-voltage divider in the simulated setup. "peak" is the actual
    #: voltage **before** the divider; the oscilloscope input sees 1/1000 of
    #: it. The value the device returns is that multiplied by the reported
    #: probe ratio — a real device behaves exactly the same way. Without
    #: modeling this, a double-scaling error when the probe ratio is
    #: reported wouldn't show up in simulation.
    "divider": 1000.0,
    #: The load the peak voltage is solved against when "configured energy"
    #: isn't given. 50 Ohm as specified by IEC 60601-2-4; if the load field
    #: in test mode differs, that value is passed to the driver instead.
    "load_ohm": 50.0,
}


def defib_peak_for_energy(energy_j, load_ohm=None):
    """Peak voltage (V) that delivers the targeted energy.

    For a truncated-exponential biphasic waveform, the energy delivered to
    the load can be solved analytically::

        E = V0² . tau / (2R) . K
        K = (1 - e^(-2.t1/tau)) + ratio² . e^(-2.t1/tau) . (1 - e^(-2.t2/tau))

    From which ``V0 = sqrt(2.R.E / (tau.K))``. Using a fixed peak voltage
    meant the simulation produced the same waveform **no matter what energy
    it was set to**: the operator would select 200 J and measure 2 J, and
    the conformity decision couldn't be tested. Now 200 J yields a peak of
    ~1.6 kV — the right order of magnitude for a real biphasic defibrillator.
    """
    if not energy_j or energy_j <= 0:
        return None
    load = float(load_ohm or DEFIB["load_ohm"])
    if load <= 0:
        load = DEFIB["load_ohm"]

    tau = DEFIB["tau"]
    decay1 = math.exp(-2.0 * DEFIB["phase1"] / tau)
    decay2 = math.exp(-2.0 * DEFIB["phase2"] / tau)
    shape = ((1.0 - decay1)
             + (DEFIB["phase2_ratio"] ** 2) * decay1 * (1.0 - decay2))
    if shape <= 0:
        return None
    return math.sqrt(2.0 * load * float(energy_j) / (tau * shape))


class SimulatedScope(WaveformDriver):
    """Mimics the behavior of the Keysight DSOX1202A."""

    FUNCTIONS = [
        MeasurementFunction("VPP", "Tepeden tepeye gerilim", "V"),
        MeasurementFunction("VAMP", "Genlik (tepe–taban)", "V"),
        MeasurementFunction("VMAX", "En büyük gerilim", "V"),
        MeasurementFunction("VMIN", "En küçük gerilim", "V"),
        MeasurementFunction("VAVG", "Ortalama gerilim (DC)", "V"),
        MeasurementFunction("VRMS", "RMS gerilim", "V"),
        MeasurementFunction("FREQ", "Frekans", "Hz"),
        MeasurementFunction("PER", "Periyot", "s"),
        MeasurementFunction("RISE", "Yükselme süresi", "s"),
        MeasurementFunction("FALL", "Düşme süresi", "s"),
        MeasurementFunction("PWID", "Pozitif darbe genişliği", "s"),
        MeasurementFunction("DUTY", "Görev çevrimi", "%"),
    ]

    CHANNELS = (("CHANnel1", "Kanal 1"), ("CHANnel2", "Kanal 2"))

    #: Points per capture (close to the device's default)
    DEFAULT_POINTS = 2000

    def __init__(self, address="SIM", channel="CHANnel1", trigger_delay=None,
                 waveform="sine", nominal_energy_j=None, load_ohm=None,
                 **kwargs):
        WaveformDriver.__init__(self, address, **kwargs)
        self.channel = channel if str(channel).startswith("CHAN") else "CHANnel1"
        # Delay can be provided externally so tests can pass without waiting.
        self._trigger_delay = trigger_delay
        self._armed = False
        self._armed_at = 0.0
        self._t0 = time.time()
        #: "sine" or "defib" — set by the application depending on test mode
        self.waveform = waveform
        #: Configured energy (J) and load (Ohm). The waveform is generated
        #: from these; the interface refreshes them every time before a
        #: capture, since the operator can change the energy after connecting.
        self.nominal_energy_j = nominal_energy_j
        self.load_ohm = load_ohm
        self._setup = {
            "volts_per_div": 1.0, "time_per_div": 1e-3, "offset": 0.0,
            "probe_ratio": 1.0, "time_position": 0.0, "trigger_level": 0.0,
        }

    @property
    def is_simulated(self):
        return True

    # --- lifecycle -------------------------------------------------
    def connect(self):
        self.identity = ("KEYSIGHT TECHNOLOGIES,DSO-X 1202A,SIM-DSOX1202A,"
                         "SIMULASYON-1.0")
        return self.identity

    def close(self):
        self._armed = False

    def identify(self):
        return self.identity or self.connect()

    def check_errors(self):
        return []

    # --- scalar measurement ---------------------------------------------------
    def configure(self, function_key, channel=None, **settings):
        if channel:
            self.channel = channel
        self._function = function_key
        self._t0 = time.time()

    def read_one(self):
        gain = CH2_GAIN if self.channel.endswith("2") else 1.0
        amp = SIGNAL["amplitude"] * gain
        offset = SIGNAL["offset"] * gain
        noise = SIGNAL["noise"] * gain
        period = 1.0 / SIGNAL["frequency"]

        # Measurement noise: an oscilloscope's per-reading scatter is much
        # larger than a multimeter's, due to the 8-bit ADC and limited
        # record length.
        exact = {
            "VPP": 2 * amp,
            "VAMP": 2 * amp,
            "VMAX": amp + offset,
            "VMIN": -amp + offset,
            "VAVG": offset,
            "VRMS": math.sqrt((amp ** 2) / 2.0 + offset ** 2),
            "FREQ": SIGNAL["frequency"],
            "PER": period,
            "RISE": SIGNAL["rise_ratio"] * period,
            "FALL": SIGNAL["rise_ratio"] * period,
            "PWID": period / 2.0,
            "DUTY": 50.0,
        }.get(self._function)

        if exact is None:
            raise KeyError("Bu cihazda olmayan fonksiyon: %s" % self._function)

        # Relative scatter: ~0.2% for voltages, ~0.05% for time quantities
        spread = 0.0005 if self._function in ("FREQ", "PER") else 0.002
        value = exact * (1.0 + random.gauss(0.0, spread))
        if self._function == "VAVG":
            # The offset is small, so relative noise wouldn't be meaningful
            value = exact + random.gauss(0.0, noise / 8.0)
        return value, "%+.4E" % value

    # --- dalga yakalama --------------------------------------------------
    def displayed_channels(self, force=()):
        return [name for name, _label in self.CHANNELS]

    def arm(self):
        self._armed = True
        self._armed_at = time.monotonic()

    def wait_trigger(self, timeout_s=None, should_stop=None, poll_s=0.05):
        """Produces a realistic wait: a random delay of 0.15-0.6 s."""
        delay = (self._trigger_delay if self._trigger_delay is not None
                 else random.uniform(0.15, 0.6))
        deadline = self._armed_at + delay
        while True:
            if should_stop is not None and should_stop():
                return False
            now = time.monotonic()
            if now >= deadline:
                self._armed = False
                return True
            if timeout_s is not None and (now - self._armed_at) > timeout_s:
                return False
            time.sleep(min(poll_s, max(0.0, deadline - now)))

    def read_waveform(self, source, points=None):
        if self.waveform == "defib":
            return self._defib_waveform(source, points)
        return self._sine_waveform(source, points)

    def _sine_waveform(self, source, points=None):
        import numpy as np

        n = int(points or self.DEFAULT_POINTS)
        gain = CH2_GAIN if str(source).endswith("2") else 1.0
        phase = CH2_PHASE if str(source).endswith("2") else 0.0

        period = 1.0 / SIGNAL["frequency"]
        # ~10 periods on screen, trigger point centered (same as the real device)
        span = 10 * period
        times = np.linspace(-span / 2.0, span / 2.0, n)

        volts = (SIGNAL["amplitude"] * gain
                 * np.sin(2 * np.pi * SIGNAL["frequency"] * times + phase)
                 + SIGNAL["offset"] * gain)
        volts = volts + np.random.normal(0.0, SIGNAL["noise"] * gain, n)

        # 8-bit vertical resolution: mimics the real device's stepped output.
        # Without this, CSVs look smoother than they really are, and later
        # analysis steps are surprised by real data.
        full_scale = 8.0 * SIGNAL["amplitude"] * gain
        lsb = full_scale / 256.0
        volts = np.round(volts / lsb) * lsb

        return times, volts

    def _defib_waveform(self, source, points=None):
        """Truncated-exponential biphasic shock — at real defibrillator voltage.

        The returned values are the **real** device voltage: on a real
        oscilloscope too, once probe attenuation is set to the divider
        ratio, the data comes in at this scale. This keeps simulation and
        real device working at the same order of magnitude. The peak
        voltage is solved from the configured energy — ~1.6 kV at 200 J,
        ~2.2 kV at 360 J.

        If a vertical scale is set, the waveform is **clipped** to the
        screen range — the real device does the same and doesn't report
        clipping as an error. Not simulating the clipping would make a wrong
        scale choice invisible in simulation.
        """
        import numpy as np

        n = int(points or self.DEFAULT_POINTS)
        if str(source).endswith("2"):
            # Channel 2 is typically connected to a sync/marker output
            return self._marker_waveform(n)

        span = DEFIB["window"]
        times = np.linspace(-0.2 * span, 0.8 * span, n)

        # The scale the device returns: input voltage x reported probe
        # ratio. If probe is reported as 1:1000, the real (pre-divider)
        # voltage comes back; if left at 1:1, the divided input voltage
        # comes back.
        probe = float(self._setup.get("probe_ratio") or 1.0)
        gain = probe / DEFIB["divider"]

        peak = self._defib_peak() * random.uniform(0.98, 1.02) * gain
        tau = DEFIB["tau"]
        t1 = DEFIB["phase1"]
        t2 = DEFIB["phase2"]
        gap = DEFIB["gap"]

        volts = np.zeros(n)
        # Phase 1: sudden rise, exponential decay, cutoff
        m1 = (times >= 0) & (times < t1)
        volts[m1] = peak * np.exp(-times[m1] / tau)
        # Polarity switch: phase 2 starts in the opposite direction from the
        # voltage where phase 1 ended
        v_switch = peak * math.exp(-t1 / tau) * DEFIB["phase2_ratio"]
        m2 = (times >= t1 + gap) & (times < t1 + gap + t2)
        volts[m2] = -v_switch * np.exp(-(times[m2] - t1 - gap) / tau)

        volts = volts + np.random.normal(0.0, DEFIB["noise"] * gain, n)

        # Screen range: 8 divisions, +-4 divisions. The excess is clipped.
        vdiv = self._setup.get("volts_per_div")
        if vdiv:
            limit = 4.0 * float(vdiv)
            offset = float(self._setup.get("offset") or 0.0)
            volts = np.clip(volts, -limit + offset, limit + offset)
            lsb = (8.0 * float(vdiv)) / 256.0
        else:
            lsb = (8.0 * peak / 6.0) / 256.0

        # 8-bit vertical resolution — the real device's stepped output
        volts = np.round(volts / lsb) * lsb
        return times, volts

    def _defib_peak(self):
        """Peak voltage (pre-divider) of the shock to be generated.

        If a configured energy is given, it's solved from that; otherwise
        the fixed `DEFIB["peak"]` is used as before — so trials made without
        entering an energy, and existing tests, keep seeing the same waveform.
        """
        solved = defib_peak_for_energy(self.nominal_energy_j, self.load_ohm)
        return solved if solved else DEFIB["peak"]

    def _marker_waveform(self, n):
        """Channel 2: the sync pulse marking the moment of the shock."""
        import numpy as np

        span = DEFIB["window"]
        times = np.linspace(-0.2 * span, 0.8 * span, n)
        volts = np.where((times >= 0) & (times < DEFIB["phase1"]), 3.3, 0.0)
        return times, volts + np.random.normal(0.0, 0.01, n)

    # --- scale, trigger, screenshot --------------------------------
    def apply_setup(self, channel=None, **settings):
        """Like the real driver: makes accepted settings readable back.

        The vertical scale limit is also simulated (probe ratio x 500 uV to
        5 V): an invalid scale request must be rejected in simulation too,
        otherwise the error path would only ever show up in the field.
        """
        for key, value in settings.items():
            if value is not None:
                self._setup[key] = value
        if channel:
            self.channel = channel

        probe = float(self._setup.get("probe_ratio") or 1.0)
        vdiv = self._setup.get("volts_per_div")
        if vdiv and not (0.0005 * probe <= float(vdiv) <= 5.0 * probe):
            raise InstrumentError(
                "Cihaz şu ayar(lar)ı kabul etmedi:\n"
                "• Dikey ölçek  →  -222,\"Data out of range\"\n\n"
                "Prob oranı 1:%g iken izin verilen aralık %.4g V – %.4g V/bölme."
                % (probe, 0.0005 * probe, 5.0 * probe))
        return dict(self._setup)

    def autoscale(self, channel=None):
        """Mimics the device's Auto Scale.

        On a real device the scale is chosen based on the signal; here the
        peak of the generated waveform is known, and the nearest 1-2-5 scale
        that fills about three quarters of the screen is chosen.
        """
        probe = float(self._setup.get("probe_ratio") or 1.0)
        if self.waveform == "defib":
            peak = self._defib_peak() * probe / DEFIB["divider"]
        else:
            peak = 3.3
        target = peak / 3.0                    # ~3/4 of the 8 divisions
        self._setup["volts_per_div"] = _nice_scale(target, probe)
        self._setup["trigger_sweep"] = "AUTO"
        if channel:
            self.channel = channel
        return dict(self._setup)

    def set_sweep(self, mode):
        self._setup["trigger_sweep"] = mode

    def read_setup(self, channel=None):
        out = dict(self._setup)
        out["channel"] = channel or self.channel
        return out

    def stop(self):
        self._armed = False

    def screenshot(self, path, palette="COLor"):
        """Produces a PNG mimicking the device screen.

        The real driver pulls a binary PNG from the device; simulation needs
        to produce the same kind of file so that the whole saving, summary,
        and reporting path works without a device. The PNG is written by
        hand — adding a Qt or image-library dependency just for simulation
        isn't worth it.
        """
        try:
            times, volts = self.read_waveform(self.channel, 1200)
        except Exception as exc:
            raise InstrumentError("Ekran görüntüsü üretilemedi: %s" % exc)
        png = _scope_screen_png(list(times), list(volts),
                                grayscale=(str(palette).upper().startswith("GRAY")))
        with open(path, "wb") as fh:
            fh.write(png)
        return path

    def run(self):
        self._armed = False


def _nice_scale(target, probe):
    """Nearest 1-2-5 scale to the target; clipped to the device's limits."""
    lo, hi = 0.0005 * probe, 5.0 * probe
    candidates = []
    exp = -4
    while exp <= 4:
        for mantissa in (1.0, 2.0, 5.0):
            value = mantissa * (10.0 ** exp)
            if lo <= value <= hi:
                candidates.append(value)
        exp += 1
    if not candidates:
        return hi
    # A scale smaller than the target would clip the waveform; so the
    # smallest of the values >= target is chosen.
    above = [c for c in candidates if c >= target]
    return min(above) if above else max(candidates)


# --- fake screenshot ------------------------------------------------------
# A small PNG writer mimicking the oscilloscope screen. Written by hand
# instead of adding Pillow: it's only used in simulation, and every
# dependency to package is one more headache on the PyInstaller side.
SCREEN_W, SCREEN_H = 640, 400
_MARGIN = 24


def _png_bytes(width, height, rows):
    """rows: bytearray(RGB triples) for each row. Returns a compressed PNG."""
    raw = bytearray()
    for row in rows:
        raw.append(0)              # filter type: None
        raw.extend(row)

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b""))


def _scope_screen_png(times, volts, grayscale=False):
    bg = (0, 0, 0)
    grid = (48, 48, 48)
    axis = (110, 110, 110)
    trace = (255, 216, 0)          # InfiniiVision kanal 1 sarısı
    if grayscale:
        bg, grid, axis, trace = (0, 0, 0), (60, 60, 60), (128, 128, 128), (235, 235, 235)

    canvas = [[bg] * SCREEN_W for _ in range(SCREEN_H)]

    plot_w = SCREEN_W - 2 * _MARGIN
    plot_h = SCREEN_H - 2 * _MARGIN

    # 10 x 8 division grid — like the real device
    for i in range(11):
        x = _MARGIN + int(i * plot_w / 10.0)
        for y in range(_MARGIN, _MARGIN + plot_h):
            canvas[y][x] = axis if i in (0, 5, 10) else grid
    for j in range(9):
        y = _MARGIN + int(j * plot_h / 8.0)
        for x in range(_MARGIN, _MARGIN + plot_w):
            canvas[y][x] = axis if j in (0, 4, 8) else grid

    if times and volts:
        t0, t1 = min(times), max(times)
        peak = max(abs(v) for v in volts) or 1.0
        span_t = (t1 - t0) or 1.0
        # Vertical scale: let the peak value fill 3/4 of the screen
        scale_v = (plot_h / 2.0) / (peak * 1.33)

        prev = None
        for t, v in zip(times, volts):
            x = _MARGIN + int((t - t0) / span_t * (plot_w - 1))
            y = _MARGIN + int(plot_h / 2.0 - v * scale_v)
            y = max(_MARGIN, min(_MARGIN + plot_h - 1, y))
            if prev is not None:
                _draw_line(canvas, prev[0], prev[1], x, y, trace)
            prev = (x, y)

    rows = []
    for row in canvas:
        line = bytearray()
        for r, g, b in row:
            line += bytes((r, g, b))
        rows.append(line)
    return _png_bytes(SCREEN_W, SCREEN_H, rows)


def _draw_line(canvas, x0, y0, x1, y1, color):
    """Bresenham. Also draws vertical jumps: plotting points individually
    made the truncated exponential waveform's steep edges look broken up."""
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        if 0 <= y0 < len(canvas) and 0 <= x0 < len(canvas[0]):
            canvas[y0][x0] = color
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
