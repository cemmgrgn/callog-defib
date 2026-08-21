"""Measurement acquisition thread.

Critical rule: VISA calls are never made on the main (UI) thread.
inst.query() can block for seconds and would freeze the UI. Reading is done
in this QThread, and the result is sent to the UI via a Qt signal.

Readings aren't INSERTed into the database one at a time — they accumulate
in a buffer and are written in a batch once a second.
"""

import os
import time

from .qt import QtCore, Signal
from .stats import Statistics  # noqa: F401  (backward-compat import)


class AcquisitionWorker(QtCore.QThread):
    """Reads periodically from the instrument."""

    #: (seq, timestamp_utc, value, raw response, elapsed seconds)
    reading = Signal(int, str, float, str, float)
    #: error text to show to the user
    error = Signal(str)
    #: connection lost / thread stopped
    finished_run = Signal()

    #: instrument was set to a new measurement point (point change in the plan)
    reconfigured = Signal(str)

    def __init__(self, driver, interval_s=1.0, parent=None):
        QtCore.QThread.__init__(self, parent)
        self._driver = driver
        self._interval = max(0.05, float(interval_s))
        self._running = False
        self._paused = False
        self._seq = 0
        self._fail_streak = 0
        self._pending_config = None

    # --- control ---------------------------------------------------------
    def stop(self):
        self._running = False

    def set_paused(self, paused):
        self._paused = bool(paused)

    def set_interval(self, seconds):
        self._interval = max(0.05, float(seconds))

    def request_configure(self, function_key, **settings):
        """Delegates setting the instrument to a new function to the **worker thread**.

        The instrument must be reconfigured when the plan advances to the
        next point. If `driver.configure()` were called directly from the
        main thread, the read loop could be inside `read_one()` at that
        exact moment, and the same VISA session would be written to from
        two places at once — a lockup, or a garbled response.
        """
        self._pending_config = (function_key, settings)

    # --- run loop ----------------------------------------------------------
    def run(self):
        from datetime import datetime, timezone

        self._running = True
        # Elapsed time is measured from the monotonic clock, not the wall
        # clock — so the chart doesn't break if the system clock changes
        # mid-session (NTP, DST).
        t0 = time.monotonic()
        while self._running:
            started = time.time()

            if self._pending_config is not None:
                function_key, settings = self._pending_config
                self._pending_config = None
                try:
                    self._driver.configure(function_key, **settings)
                    self.reconfigured.emit(function_key)
                except Exception as exc:
                    self.error.emit("Cihaz yeni noktaya ayarlanamadı: %s" % exc)

            if self._paused:
                self.msleep(100)
                continue

            try:
                value, raw = self._driver.read_one()
                self._fail_streak = 0
                self._seq += 1
                ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                elapsed = time.monotonic() - t0
                self.reading.emit(self._seq, ts, value, raw, elapsed)
            except Exception as exc:
                self._fail_streak += 1
                if self._fail_streak <= 3:
                    # Transient error: back off exponentially and retry
                    self.error.emit(
                        "Okuma başarısız (%d/3), yeniden deneniyor: %s"
                        % (self._fail_streak, exc)
                    )
                    self.msleep(200 * (2 ** self._fail_streak))
                    continue
                self.error.emit(
                    "Cihazla bağlantı kurulamıyor, ölçüm durduruldu: %s" % exc
                )
                break

            # Keep the period — subtract the time the read took
            remaining = self._interval - (time.time() - started)
            if remaining > 0:
                self.msleep(int(remaining * 1000))

        self.finished_run.emit()


class WaveformWorker(QtCore.QThread):
    """Arms the oscilloscope, waits for the trigger, reads the channels.

    Why a separate thread: the trigger wait is unbounded. If the signal
    never arrives, `wait_trigger` can spin for minutes; if this ran on the
    main thread, the window would stop responding and Windows would call it
    "not responding."

    Stopping takes effect immediately: the wait loop checks the `_running`
    flag on every iteration, `terminate()` is never called. A VISA read cut
    off midway leaves the instrument in an undefined state, and the next
    connection fails with "device busy."
    """

    #: (trigger number, time array, {channel: array}, screenshot path)
    captured = Signal(int, object, object, object)
    #: error text to show to the user
    error = Signal(str)
    #: status info (waiting for trigger, timeout, ...)
    status = Signal(str)
    finished_run = Signal()

    #: Delay between the trigger and the screenshot (s). Default 0: the
    #: delay is a value the operator sets by hand, depending on the
    #: instrument/cable. If the image comes back blank, this field is
    #: increased in the UI.
    DEFAULT_SHOT_DELAY_S = 1.0

    def __init__(self, driver, channels, points=None, max_captures=0,
                 timeout_s=None, screenshot=True, shot_delay_s=None,
                 parent=None):
        QtCore.QThread.__init__(self, parent)
        self._driver = driver
        self._channels = list(channels)
        self._points = points or None
        self._max = int(max_captures or 0)      # 0 = unlimited
        self._timeout_s = timeout_s
        self._screenshot = bool(screenshot)
        self._shot_delay = (self.DEFAULT_SHOT_DELAY_S if shot_delay_s is None
                            else float(shot_delay_s))
        self._running = False
        self._count = 0

    def stop(self):
        self._running = False

    @property
    def count(self):
        return self._count

    def run(self):
        self._running = True
        fail_streak = 0

        while self._running and (self._max == 0 or self._count < self._max):
            try:
                self._driver.arm()
            except Exception as exc:
                self.error.emit("Cihaz silahlandırılamadı: %s" % exc)
                break

            self.status.emit("Tetikleme bekleniyor…")
            try:
                fired = self._driver.wait_trigger(
                    timeout_s=self._timeout_s,
                    should_stop=lambda: not self._running)
            except Exception as exc:
                self.error.emit("Tetikleme beklenirken hata: %s" % exc)
                break

            if not self._running:
                break
            if not fired:
                # A timeout isn't fatal: the trigger condition might be
                # wrong, so let the user fix the setting and keep waiting.
                self.status.emit(
                    "Zaman aşımı — tetikleme gelmedi, yeniden bekleniyor.")
                continue

            shot = None
            if self._screenshot:
                if self._shot_delay > 0:
                    self.msleep(int(self._shot_delay * 1000))
                shot = self._grab_screenshot()

            try:
                times, columns = self._read_channels()
                fail_streak = 0
            except Exception as exc:
                fail_streak += 1
                _discard(shot)
                if fail_streak <= 3:
                    self.error.emit("Dalga okunamadı (%d/3): %s"
                                    % (fail_streak, exc))
                    self.msleep(300 * fail_streak)
                    continue
                self.error.emit("Dalga okunamıyor, yakalama durduruldu: %s" % exc)
                break

            self._count += 1
            self.captured.emit(self._count, times, columns, shot)

        self.finished_run.emit()

    def _grab_screenshot(self):
        """Grabs the instrument screen into a temporary PNG; None on failure.

        A failure doesn't cancel the capture: the screenshot complements
        the record, it isn't a precondition for it. Older firmware versions
        may not implement `:DISPlay:DATA?`.
        """
        import tempfile

        fd, path = tempfile.mkstemp(prefix="cal-ekran-", suffix=".png")
        os.close(fd)
        try:
            self._driver.screenshot(path)
            return path
        except Exception as exc:
            self.status.emit("Ekran görüntüsü alınamadı: %s" % exc)
            _discard(path)
            return None

    def _read_channels(self):
        times = None
        columns = {}
        for ch in self._channels:
            t, v = self._driver.read_waveform(ch, self._points)
            if times is None:
                times = t
            columns[_column_name(ch)] = v
        # Trimming channels to a common length is the storage layer's job
        # (waveform.align); it's sent out raw here.
        return times, columns


def _discard(path):
    """Deletes an unused temp file — so half-finished captures don't pile up."""
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def _column_name(channel):
    """'CHANnel1' -> 'CH1_V'"""
    digits = "".join(c for c in str(channel) if c.isdigit())
    return "CH%s_V" % (digits or "?")
