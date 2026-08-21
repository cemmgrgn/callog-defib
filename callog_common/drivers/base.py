"""Device driver interface.

To add a new device, inherit this class, implement the four methods, and
register it in the REGISTRY in drivers/__init__.py.
"""


class MeasurementFunction(object):
    """Definition of a measurement function (display name + unit)."""

    def __init__(self, key, label, unit):
        self.key = key
        self.label = label
        self.unit = unit


class InstrumentError(Exception):
    pass


class Driver(object):
    """Base class for all device drivers."""

    #: Measurement functions this device supports
    FUNCTIONS = []

    #: Whether it can capture waveforms (oscilloscopes). The interface uses
    #: this to decide whether to open the page; checking isinstance against
    #: the concrete class name would require updating this check for every
    #: new oscilloscope.
    supports_waveform = False

    def __init__(self, address, **kwargs):
        self.address = address
        self.identity = None
        self._function = None

    # --- lifecycle -------------------------------------------------
    def connect(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    # --- queries ------------------------------------------------------
    def identify(self):
        """Returns the raw *IDN? response."""
        raise NotImplementedError

    def check_errors(self):
        """Drains the device's error queue and returns the list of error texts."""
        return []

    # --- measurement ---------------------------------------------------------
    def configure(self, function_key, **settings):
        raise NotImplementedError

    def read_one(self):
        """Returns a single reading: (value, raw response)"""
        raise NotImplementedError

    # --- helper ------------------------------------------------------
    @classmethod
    def function_by_key(cls, key):
        for f in cls.FUNCTIONS:
            if f.key == key:
                return f
        raise KeyError(key)

    @property
    def is_simulated(self):
        return False


class WaveformDriver(Driver):
    """Devices that can capture trigger-based waveforms (oscilloscopes).

    The scalar measurement interface (`read_one`) still applies as-is —
    the oscilloscope also produces a single number via `:MEASure:` queries,
    so the application's session/certificate flow works unchanged. The
    methods below are the waveform capture capability **on top of** that.
    """

    supports_waveform = True

    #: Channel name → display label
    CHANNELS = ()

    def displayed_channels(self):
        """List of channels currently shown on screen."""
        raise NotImplementedError

    def arm(self):
        """Arms for a single-shot capture (:SINGle)."""
        raise NotImplementedError

    def wait_trigger(self, timeout_s=None, should_stop=None, poll_s=0.05):
        """Waits until the trigger fires and acquisition finishes.

        should_stop: callable checked on every loop iteration; if it
        returns True, the wait is cancelled. This is how the user's "Stop"
        button works — otherwise the application would hang on a setup
        that never triggers.

        Returns: True if triggered, False on timeout or cancellation.
        """
        raise NotImplementedError

    def read_waveform(self, source, points=None):
        """Reads (time array, voltage array) from a single channel."""
        raise NotImplementedError

    def run(self):
        """Returns the device to continuous sweep mode."""
        raise NotImplementedError

    def stop(self):
        """Stops the sweep."""
        raise NotImplementedError

    def screenshot(self, path, palette="COLor"):
        """Saves the device screen as a PNG and returns the file path."""
        raise NotImplementedError

    def apply_setup(self, **settings):
        """Applies scale / trigger settings to the device."""
        raise NotImplementedError

    def read_setup(self, channel=None):
        """Reads the device's current scale / trigger settings as a dict."""
        raise NotImplementedError

    def autoscale(self, channel=None):
        """Runs the device's own auto-scaling (Auto Scale)."""
        raise NotImplementedError

    def set_sweep(self, mode):
        """Trigger sweep mode: 'AUTO' | 'NORMal' | 'SINGle'."""
        raise NotImplementedError
