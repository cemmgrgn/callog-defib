"""Fluke 8846A 6½-digit precision multimeter driver.

The driver works with any Fluke 8846A over GPIB; the serial number in the
inventory is entered per installation from Administration -> Reference
instruments.

Interface notes
----------------
* Works over GPIB (via a USB-GPIB adapter). LAN is not used.
* When working over RS-232, ``SYST:REM`` must be sent to put the device into
  remote mode; on GPIB this happens automatically.
* RS-232 defaults: 9600 baud, 8N1, Xon/Xoff, CR LF terminator.
* If the device's language setting is "Fluke 45 emulation", it must be
  switched to SCPI mode (front panel: SETUP > REMOTE > LANGUAGE > SCPI).
"""

import threading

from .base import Driver, InstrumentError, MeasurementFunction

# Functions NPLC applies to (excludes frequency/period/capacitance)
_NPLC_FUNCTIONS = {"VDC", "VAC", "IDC", "IAC", "RES", "FRES"}


class Fluke8846A(Driver):

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

    _SCPI = {
        "VDC": ("VOLT:DC", "VOLT:DC"),
        "VAC": ("VOLT:AC", "VOLT:AC"),
        "IDC": ("CURR:DC", "CURR:DC"),
        "IAC": ("CURR:AC", "CURR:AC"),
        "RES": ("RES", "RES"),
        "FRES": ("FRES", "FRES"),
        "FREQ": ("FREQ", None),
        "PER": ("PER", None),
        "CAP": ("CAP", None),
    }

    def __init__(self, address, serial_cfg=None, timeout_ms=10000, **kwargs):
        Driver.__init__(self, address, **kwargs)
        self.serial_cfg = serial_cfg or {}
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

        is_serial = self.address.upper().startswith("ASRL")
        if is_serial:
            cfg = self.serial_cfg
            self._inst.baud_rate = int(cfg.get("baud", 9600))
            self._inst.data_bits = int(cfg.get("data_bits", 8))
            self._inst.read_termination = cfg.get("read_termination", "\r\n")
            self._inst.write_termination = cfg.get("write_termination", "\r\n")
        else:
            self._inst.read_termination = "\n"
            self._inst.write_termination = "\n"

        self.identity = self.identify()
        if "8846" not in self.identity and "8845" not in self.identity:
            raise InstrumentError(
                "Beklenen cihaz Fluke 8846A değil. Gelen yanıt: %s" % self.identity
            )

        if is_serial:
            self._write("SYST:REM")     # remote mode over RS-232
        self._write("*CLS")
        return self.identity

    def close(self):
        with self._lock:
            if self._inst is not None:
                try:
                    self._inst.write("SYST:LOC")   # hand the front panel back to the user
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

    # --- queries ------------------------------------------------------
    def identify(self):
        return self._query("*IDN?")

    def check_errors(self):
        """Drains the error queue. The 8846A's queue is empty once it returns '+0,"No error"'."""
        errors = []
        for _ in range(20):
            resp = self._query("SYST:ERR?")
            if not resp:
                break
            code = resp.split(",")[0].strip()
            if code in ("0", "+0"):
                break
            errors.append(resp)
        return errors

    # --- measurement ---------------------------------------------------------
    def configure(self, function_key, nplc=None, auto_range=True, range_=None, **kw):
        conf, sense = self._SCPI[function_key]
        self._write("CONF:%s" % conf)

        if sense is not None:
            if auto_range:
                self._write("%s:RANG:AUTO ON" % sense)
            elif range_ is not None:
                self._write("%s:RANG %s" % (sense, range_))

        if nplc is not None and function_key in _NPLC_FUNCTIONS:
            self._write("%s:NPLC %s" % (sense, nplc))

        self._function = function_key
        errs = self.check_errors()
        if errs:
            raise InstrumentError("Cihaz hatası: " + "; ".join(errs))

    def read_one(self):
        raw = self._query("READ?")
        try:
            return float(raw), raw
        except ValueError:
            raise InstrumentError("Sayıya çevrilemeyen yanıt: %r" % raw)
