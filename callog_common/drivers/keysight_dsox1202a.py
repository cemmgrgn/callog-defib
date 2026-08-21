"""Keysight DSOX1202A (InfiniiVision 1200 X series) oscilloscope driver.

It has two capabilities, and they produce different kinds of data:

* **Scalar measurement** — queries like ``:MEASure:VPP?`` return a single
  number per reading. The application's session / statistics / certificate
  flow is built on this and works unchanged. The oscilloscope is calibrated
  against exactly these quantities anyway (vertical accuracy, timebase
  accuracy, rise time).
* **Waveform capture** — thousands of (t, V) points per trigger. These are
  not repeated measurements of the same quantity but samples of a single
  event; they are not written to the ``readings`` table but stored as a CSV
  file (see ``waveform.py``).

Interface notes
----------------
* Works over USB (the "USB Device" port on the rear panel). Keysight IO
  Libraries Suite (VISA) must be installed.
* ``*IDN?`` response: ``KEYSIGHT TECHNOLOGIES,DSO-X 1202A,CN00000000,02.xx.xxxx``
  Older firmware may report the brand field as ``AGILENT TECHNOLOGIES``.
* Two analog channels (CHANnel1, CHANnel2).

Two traps are explicitly handled in this driver; both silently produce wrong
data otherwise:

1. **+9.9E+37 = "measurement could not be made".** If there is no signal, the
   trigger was missed, or the quantity isn't visible on screen, the device
   doesn't raise an error — it returns this number instead. If recorded as-is,
   the mean shoots to ~1e37 and the whole session is ruined. ``read_one``
   catches this and raises ``InstrumentError``.
2. **Measurement freezes on a stopped device.** While in ``:STOP`` state,
   ``:MEASure:VPP?`` returns the *same* value every time. The application
   would take this as N repeated readings, computing zero standard deviation
   and zero uncertainty — even though no measurement actually happened.
   ``configure`` puts the device into ``:RUN`` state, and ``read_one``
   verifies that acquisition is progressing.
"""

import threading
import time

from .base import InstrumentError, MeasurementFunction, WaveformDriver

#: The device's "measurement could not be made" value. The threshold is set
#: a bit lower: some firmware versions return 9.99999E+37.
INVALID_MEASUREMENT = 9.9e37
INVALID_THRESHOLD = 9.0e37

#: Operation Status Condition Register, bit 3 = Run/acquiring
OPER_RUN_BIT = 1 << 3


class KeysightDSOX1202A(WaveformDriver):

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

    #: Function key → :MEASure: query.
    #: VAVerage and VRMS need extra arguments; those are set up specially below.
    _MEASURE = {
        "VPP": "VPP",
        "VAMP": "VAMPlitude",
        "VMAX": "VMAX",
        "VMIN": "VMIN",
        "FREQ": "FREQuency",
        "PER": "PERiod",
        "RISE": "RISetime",
        "FALL": "FALLtime",
        "PWID": "PWIDth",
        "DUTY": "DUTYcycle",
    }

    def __init__(self, address, channel="CHANnel1", timeout_ms=15000, **kwargs):
        WaveformDriver.__init__(self, address, **kwargs)
        self.channel = _normalize_channel(channel)
        self.timeout_ms = timeout_ms
        self._inst = None
        self._rm = None
        self._lock = threading.Lock()

    # --- lifecycle -------------------------------------------------
    def connect(self):
        import pyvisa

        self._rm = pyvisa.ResourceManager()
        self._inst = self._rm.open_resource(self.address)
        self._inst.timeout = self.timeout_ms
        self._inst.read_termination = "\n"
        self._inst.write_termination = "\n"

        self.identity = self.identify()
        up = self.identity.upper()
        if "1202" not in up and "1200" not in up and "DSO-X" not in up:
            raise InstrumentError(
                "Beklenen cihaz DSOX1202A değil. Gelen yanıt: %s" % self.identity)

        self._write("*CLS")
        return self.identity

    def close(self):
        with self._lock:
            if self._inst is not None:
                try:
                    # Hand the front panel back to the user: leaving it on a
                    # stopped screen makes the next person think the device
                    # is broken.
                    self._inst.write(":RUN")
                except Exception:
                    pass
                try:
                    self._inst.close()
                finally:
                    self._inst = None
            if self._rm is not None:
                try:
                    self._rm.close()
                finally:
                    self._rm = None

    # --- low level --------------------------------------------------
    def _write(self, cmd):
        with self._lock:
            self._inst.write(cmd)

    def _query(self, cmd):
        with self._lock:
            return self._inst.query(cmd).strip()

    def _query_binary(self, cmd):
        import numpy as np

        with self._lock:
            return self._inst.query_binary_values(
                cmd, datatype="H", is_big_endian=False, container=np.array)

    # --- queries ------------------------------------------------------
    def identify(self):
        return self._query("*IDN?")

    def check_errors(self):
        errors = []
        for _ in range(20):
            resp = self._query(":SYSTem:ERRor?")
            if not resp:
                break
            code = resp.split(",")[0].strip()
            if code in ("0", "+0"):
                break
            errors.append(resp)
        return errors

    # --- scalar measurement ---------------------------------------------------
    def configure(self, function_key, channel=None, averaging=None,
                  autoscale=False, **kw):
        if function_key not in self._MEASURE and function_key not in ("VAVG", "VRMS"):
            raise InstrumentError("Bu cihazda olmayan fonksiyon: %s" % function_key)

        if channel:
            self.channel = _normalize_channel(channel)
        self._write(":%s:DISPlay ON" % self.channel)

        if autoscale:
            # If the signal magnitude is unknown, let the device pick the
            # vertical/horizontal settings. Usually not wanted during
            # calibration since changing the scale affects the accuracy
            # budget, so it defaults to off.
            self._write(":AUToscale")

        if averaging:
            self._write(":ACQuire:TYPE AVERage")
            self._write(":ACQuire:COUNt %d" % int(averaging))
        else:
            self._write(":ACQuire:TYPE NORMal")

        # The device must keep sweeping for the measurement to refresh.
        self._write(":RUN")
        self._write(":MEASure:SOURce %s" % self.channel)

        self._function = function_key
        errs = self.check_errors()
        if errs:
            raise InstrumentError("Cihaz hatası: " + "; ".join(errs))

    def _measure_query(self, function_key):
        if function_key == "VAVG":
            # <range>,<source>: average over all data on screen
            return ":MEASure:VAVerage? DISPlay,%s" % self.channel
        if function_key == "VRMS":
            # <range>,<type>,<source>: true RMS including the DC component
            return ":MEASure:VRMS? DISPlay,DC,%s" % self.channel
        return ":MEASure:%s? %s" % (self._MEASURE[function_key], self.channel)

    def read_one(self):
        if self._function is None:
            raise InstrumentError("Önce configure() çağrılmalı")
        raw = self._query(self._measure_query(self._function))
        try:
            value = float(raw)
        except ValueError:
            raise InstrumentError("Sayıya çevrilemeyen yanıt: %r" % raw)

        if abs(value) >= INVALID_THRESHOLD:
            raise InstrumentError(
                "Cihaz ölçüm yapamadı (%s). Sinyal yok, tetikleme kararsız ya da "
                "ölçülen büyüklük ekranda görünmüyor olabilir. Dikey/yatay ölçeği "
                "kontrol edin." % raw)
        return value, raw

    # --- waveform capture --------------------------------------------------
    def displayed_channels(self, force=()):
        """Channels currently on screen. Those given via force are always included."""
        found = []
        for name, _label in self.CHANNELS:
            try:
                on = self._query(":%s:DISPlay?" % name) in ("1", "ON")
            except Exception:
                on = False
            if on or name in force:
                found.append(name)
        return found

    def arm(self):
        self._write(":SINGle")
        self._query("*OPC?")   # make sure the command has been processed

    def wait_trigger(self, timeout_s=None, should_stop=None, poll_s=0.05):
        start = time.monotonic()
        while True:
            if should_stop is not None and should_stop():
                return False
            try:
                cond = int(self._query(":OPERegister:CONDition?"))
            except (ValueError, InstrumentError):
                return False
            if not cond & OPER_RUN_BIT:
                return True          # Run bit cleared -> triggered, acquisition done
            if timeout_s is not None and (time.monotonic() - start) > timeout_s:
                return False
            time.sleep(poll_s)

    def read_waveform(self, source, points=None):
        import numpy as np

        self._write(":WAVeform:SOURce %s" % _normalize_channel(source))
        self._write(":WAVeform:POINts:MODE RAW")
        if points:
            self._write(":WAVeform:POINts %d" % int(points))
        self._write(":WAVeform:FORMat WORD")
        self._write(":WAVeform:BYTeorder LSBFirst")
        self._write(":WAVeform:UNSigned 1")

        pre = [float(v) for v in self._query(":WAVeform:PREamble?").split(",")]
        if len(pre) < 10:
            raise InstrumentError("Eksik dalga başlığı: %r" % pre)
        _fmt, _typ, _npts, _cnt, xinc, xorig, xref, yinc, yorig, yref = pre[:10]

        raw = self._query_binary(":WAVeform:DATA?")
        if raw.size == 0:
            raise InstrumentError("Cihaz boş dalga verisi döndürdü")

        volts = (raw.astype(np.float64) - yref) * yinc + yorig
        times = (np.arange(raw.size, dtype=np.float64) - xref) * xinc + xorig
        return times, volts

    def run(self):
        self._write(":RUN")

    def stop(self):
        self._write(":STOP")

    # --- screenshot ---------------------------------------------------------
    def screenshot(self, path, palette="COLor"):
        """Saves the oscilloscope screen as-is, as a PNG.

        Why it's captured from the device instead of drawn by the
        application: the image that goes into the report needs to be *what
        the device saw*. The application's own rendering wouldn't include
        the division settings, the trigger marker, or the on-screen
        measurement readouts; in an audit, this file is the answer to
        "what was on screen".
        """
        with self._lock:
            old_term = self._inst.read_termination
            old_timeout = self._inst.timeout
            try:
                # A line-ending character would cut the binary transfer
                # short: a 0x0A byte occurring inside PNG data is normal.
                self._inst.read_termination = None
                self._inst.timeout = max(self.timeout_ms, 20000)
                data = self._inst.query_binary_values(
                    ":DISPlay:DATA? PNG,%s" % palette,
                    datatype="B", container=bytearray, header_fmt="ieee")
            finally:
                self._inst.read_termination = old_term
                self._inst.timeout = old_timeout

        blob = bytes(data)
        if not blob.startswith(b"\x89PNG"):
            raise InstrumentError(
                "Cihazdan gelen veri PNG değil (%d bayt). Aygıt yazılımı "
                "ekran görüntüsünü desteklemiyor olabilir." % len(blob))
        with open(path, "wb") as fh:
            fh.write(blob)
        return path

    # --- scale and trigger ------------------------------------------------
    def _apply_one(self, label, command, failures):
        """Sends a single command and immediately checks the error queue.

        Sending everything in a batch and checking only at the end would say
        `-222,"Data out of range"` without telling the user **which**
        setting was rejected. It would also let commands after a rejected
        one keep being applied against an inconsistent scale.
        """
        self._write(command)
        for err in self.check_errors():
            failures.append((label, command, err))
            return False
        return True

    def autoscale(self, channel=None):
        """The device's own auto-scaling (front panel Auto Scale).

        Not used for the calibration measurement itself — scale is part of
        the accuracy budget. But it is used to *find* the signal: while
        connecting, the operator wants to see the waveform on screen without
        having to reach for the front panel. Afterwards, the test mode's
        scales are rewritten via `apply_setup`.
        """
        ch = _normalize_channel(channel or self.channel)
        self._write(":%s:DISPlay ON" % ch)
        self._write(":AUToscale")
        self._query("*OPC?")
        errs = self.check_errors()
        if errs:
            raise InstrumentError("Otomatik ölçekleme hatası: " + "; ".join(errs))
        return self.read_setup(ch)

    def set_sweep(self, mode):
        """Trigger sweep mode: 'AUTO' | 'NORMal' | 'SINGle'."""
        self._write(":TRIGger:SWEep %s" % mode)

    def apply_setup(self, channel=None, volts_per_div=None, offset=None,
                    time_per_div=None, time_position=None, probe_ratio=None,
                    coupling=None, trigger_level=None, trigger_slope=None,
                    trigger_source=None, averaging=None, trigger_sweep="NORMal"):
        """Applies the device settings the test mode requires.

        Only the given fields are changed. `:AUToscale` is not used, since
        in calibration the scale is part of the accuracy budget — the scale
        is chosen deliberately and the chosen value is recorded.

        **Probe ratio = divider ratio.** The way to tell the device about an
        external divider is probe attenuation. If it isn't reported, two
        things break at once:

        * The vertical sensitivity limit at 1:1 is 500 µV...5 V/div; asking
          for 50 V/div makes the device return `-222 Data out of range`. At
          1:1000 the limit becomes 0.5 V...5 kV/div and the request becomes
          valid.
        * The device's screen, measurements, and screenshot show the divided
          voltage, which won't match the kV values in the report.
        """
        ch = _normalize_channel(channel or self.channel)
        failures = []
        self._write(":%s:DISPlay ON" % ch)
        self.check_errors()

        # Probe ratio FIRST: the vertical scale limit depends on the probe
        # ratio; if set afterward, even a valid V/div value gets rejected.
        if probe_ratio:
            self._apply_one("Prob / bölücü oranı",
                            ":%s:PROBe %g" % (ch, float(probe_ratio)), failures)
        if coupling:
            self._apply_one("Kuplaj", ":%s:COUPling %s" % (ch, coupling), failures)
        if volts_per_div:
            self._apply_one("Dikey ölçek",
                            ":%s:SCALe %g" % (ch, float(volts_per_div)), failures)
        if offset is not None:
            self._apply_one("Dikey ofset",
                            ":%s:OFFSet %g" % (ch, float(offset)), failures)

        if time_per_div:
            self._apply_one("Zaman tabanı",
                            ":TIMebase:SCALe %g" % float(time_per_div), failures)
        if time_position is not None:
            self._apply_one("Zaman konumu",
                            ":TIMebase:POSition %g" % float(time_position),
                            failures)

        if trigger_source or trigger_level is not None or trigger_slope:
            source = _normalize_channel(trigger_source or ch)
            self._apply_one("Tetikleme modu", ":TRIGger:MODE EDGE", failures)
            self._apply_one("Tetikleme kaynağı",
                            ":TRIGger:EDGE:SOURce %s" % source, failures)
            if trigger_slope:
                self._apply_one("Tetikleme kenarı",
                                ":TRIGger:EDGE:SLOPe %s" % trigger_slope, failures)
            if trigger_level is not None:
                self._apply_one("Tetikleme eşiği",
                                ":TRIGger:EDGE:LEVel %g,%s"
                                % (float(trigger_level), source), failures)
            # The sweep mode is left to the caller, because there are two
            # different jobs:
            #
            # * NORMal is needed during capture — the device must not sweep
            #   on its own if no trigger arrives, otherwise we'd mistake an
            #   empty screen for a "captured shock".
            # * AUTO is needed while adjusting scales. In NORMal the screen
            #   freezes until a trigger arrives; after applying a setting,
            #   the operator loses the signal and can't get it back without
            #   pressing Auto Scale on the front panel.
            if trigger_sweep:
                self._apply_one("Tetikleme süpürmesi",
                                ":TRIGger:SWEep %s" % trigger_sweep, failures)

        if averaging:
            self._apply_one("Ortalama türü", ":ACQuire:TYPE AVERage", failures)
            self._apply_one("Ortalama sayısı",
                            ":ACQuire:COUNt %d" % int(averaging), failures)

        if failures:
            raise InstrumentError(_setup_error_text(failures, self.read_setup(ch)))
        return self.read_setup(ch)

    def read_setup(self, channel=None):
        """Reads the scale/trigger settings currently in effect on the device."""
        ch = _normalize_channel(channel or self.channel)

        def num(cmd, default=None):
            try:
                return float(self._query(cmd))
            except (ValueError, InstrumentError):
                return default

        return {
            "channel": ch,
            "volts_per_div": num(":%s:SCALe?" % ch),
            "offset": num(":%s:OFFSet?" % ch),
            "probe_ratio": num(":%s:PROBe?" % ch),
            "time_per_div": num(":TIMebase:SCALe?"),
            "time_position": num(":TIMebase:POSition?"),
            "trigger_level": num(":TRIGger:EDGE:LEVel?"),
        }


def _setup_error_text(failures, current):
    """Describes the rejected settings along with the values the device accepts.

    `-222,"Data out of range"` says nothing on its own; the user needs to
    know which field to change on screen.
    """
    lines = ["Cihaz şu ayar(lar)ı kabul etmedi:"]
    for label, command, err in failures:
        lines.append("• %s  →  %s" % (label, err))

    if any(f[0] == "Dikey ölçek" for f in failures):
        probe = current.get("probe_ratio") or 1.0
        lines.append("")
        lines.append(
            "Dikey ölçek sınırı prob oranına bağlı: cihaz 1:1 probda "
            "500 µV – 5 V/bölme kabul eder. Şu an prob oranı 1:%g, yani "
            "izin verilen aralık %s – %s/bölme."
            % (probe, _volt_text(0.0005 * probe), _volt_text(5.0 * probe)))
        lines.append(
            "Harici bölücü kullanıyorsanız bölücü oranını girin — uygulama "
            "onu cihaza prob oranı olarak bildirir.")

    lines.append("")
    lines.append("Cihazda şu an geçerli olan: %s/bölme · %s/bölme · prob 1:%g"
                 % (_volt_text(current.get("volts_per_div")),
                    _time_text(current.get("time_per_div")),
                    current.get("probe_ratio") or 1.0))
    return "\n".join(lines)


def _volt_text(value):
    if value is None:
        return "—"
    if abs(value) >= 1000:
        return "%.4g kV" % (value / 1000.0)
    if abs(value) < 0.001:
        return "%.4g µV" % (value * 1e6)
    if abs(value) < 1:
        return "%.4g mV" % (value * 1000.0)
    return "%.4g V" % value


def _time_text(value):
    if value is None:
        return "—"
    for factor, unit in ((1.0, "s"), (1e-3, "ms"), (1e-6, "µs"), (1e-9, "ns")):
        if abs(value) >= factor:
            return "%.4g %s" % (value / factor, unit)
    return "%.3g s" % value


def _normalize_channel(name):
    """'CH1', 'ch1', '1', 'CHANnel1' -> 'CHANnel1'"""
    text = str(name).strip().upper()
    for suffix in ("1", "2"):
        if text in ("CHANNEL" + suffix, "CHAN" + suffix, "CH" + suffix, suffix):
            return "CHANnel" + suffix
    return str(name)
