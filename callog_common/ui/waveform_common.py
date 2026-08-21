"""Shared constants and helpers -- common between waveform_page.py and
its mixin modules (waveform_discovery/setup/capture/results.py). Kept in
a separate module to avoid circular imports.
"""

import math
import os
import tempfile

from ..drivers import discovery
from ..qt import QtCore, QtGui, Signal


MAX_PLOT_POINTS = 4000

MIN_ANALYSIS_ROWS = 5

_ENERGY_SCALE_DURATION_S = 0.006

class ScanThread(QtCore.QThread):
    """Device scan -- runs on a separate thread to avoid blocking the UI."""

    progress = Signal(str)
    done = Signal(list)

    def run(self):
        try:
            found = discovery.scan(progress=self.progress.emit)
        except Exception as exc:
            self.progress.emit("Tarama hatası: %s" % exc)
            found = []
        self.done.emit(found)

def _safe_setup(driver, channel):
    """Reads the device settings; returns an empty dict if it can't.

    Some old firmware versions don't support certain queries. Canceling
    the capture just because settings couldn't be read would be wrong.
    """
    try:
        return driver.read_setup(channel)
    except Exception:
        return {}

def _close_quietly(driver):
    for call in ("run", "close"):
        try:
            getattr(driver, call)()
        except Exception:
            pass

def _estimate_vdiv_for_energy(energy_j, load_ohm):
    """Derives a rough vertical scale (V/div) estimate from the set energy.

    The real pulse is a truncated exponential decay; here it's treated as
    a rectangular pulse of constant peak voltage and Vpeak is solved from
    E ≈ Vpeak² · T / R. This overestimates the real peak — an exponential
    pulse with the same peak and duration has less energy than a
    rectangular one — and that's deliberate: better than clipping on screen.

    The scale is chosen so the peak fills about 60% of half the screen,
    then the result is rounded to the oscilloscope's 1-2-5 V/div sequence.
    It's only a starting point; the operator should review it before
    'Apply scales to device'.
    """
    if not energy_j or energy_j <= 0 or not load_ohm or load_ohm <= 0:
        return None
    v_peak = (float(energy_j) * float(load_ohm) / _ENERGY_SCALE_DURATION_S) ** 0.5
    half_screen = v_peak / 0.6
    raw_vdiv = half_screen * 2.0 / 8.0     # divisions=8, see testmodes.screen_span
    return _round_vdiv(raw_vdiv)

def _round_vdiv(value):
    """Rounds value up to the next oscilloscope V/div step in the 1-2-5 sequence."""
    if value <= 0:
        return 1.0
    exp = math.floor(math.log10(value))
    base = value / (10 ** exp)
    for step in (1, 2, 5, 10):
        if base <= step:
            return round(step * (10 ** exp), 6)
    return round(10 * (10 ** exp), 6)

def _volts(value):
    """Writes voltage in readable form: 2.5 kV instead of 2500."""
    if value is None:
        return "—"
    value = float(value)
    if abs(value) >= 1000:
        return "%.4g kV" % (value / 1000.0)
    if abs(value) < 0.001:
        return "%.4g µV" % (value * 1e6)
    if abs(value) < 1:
        return "%.4g mV" % (value * 1000.0)
    return "%.4g V" % value

def _column_name(channel):
    """'CHANnel1' -> 'CH1_V' — keeps the CSV header consistent across capture paths."""
    digits = "".join(c for c in str(channel) if c.isdigit())
    return "CH%s_V" % (digits or "?")

def _screenshot_temp(driver, on_error=None):
    """Captures the device screen to a temporary PNG; returns None if it can't.

    A failure doesn't cancel the capture: the screenshot complements the
    record, it isn't a precondition for it. Some old firmware versions
    lack `:DISPlay:DATA?`.
    """
    fd, path = tempfile.mkstemp(prefix="cal-ekran-", suffix=".png")
    os.close(fd)
    try:
        driver.screenshot(path)
        return path
    except Exception as exc:
        if on_error is not None:
            on_error("Ekran görüntüsü alınamadı: %s" % exc)
        try:
            os.unlink(path)
        except OSError:
            pass
        return None

def _row_value(row, key):
    """Safe read from a sqlite3.Row — since it has no .get() method.

    Returns None instead of IndexError when the query changes and a
    column drops out of the list: these values are only used for
    matching, so their absence isn't fatal.
    """
    if row is None:
        return None
    try:
        if key not in row.keys():
            return None
    except AttributeError:
        return row.get(key) if hasattr(row, "get") else None
    return row[key]

def _channel_label(name):
    """'CHANnel1' -> 'Kanal 1' — the SCPI name isn't shown to the user."""
    digits = "".join(c for c in str(name) if c.isdigit())
    return "Kanal %s" % digits if digits else str(name)

def _si(value, unit):
    """Writes small time intervals in readable form: 5 µs instead of 5e-06 s."""
    if value is None:
        return "—"
    for factor, prefix in ((1.0, ""), (1e-3, "m"), (1e-6, "µ"),
                           (1e-9, "n"), (1e-12, "p")):
        if abs(value) >= factor:
            return "%.4g %s%s" % (value / factor, prefix, unit)
    return "%.3g %s" % (value, unit)

def _thin(times, values, limit):
    """Thins out data for plotting — drawing every point is unnecessary and slow."""
    n = len(times)
    if n <= limit:
        return list(times), list(values)
    step = max(1, n // limit)
    return list(times[::step]), list(values[::step])

def _restyle(widget):
    """Reapplies Qt property-based QSS (for badge color changes)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)

def _open_path(path):
    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
