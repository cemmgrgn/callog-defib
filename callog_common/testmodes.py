"""Test modes — gather everything a test needs in one place.

A test mode carries: oscilloscope scale and trigger settings, the
measurement chain (divider ratio, load resistance), capture behavior, and
the analysis to apply to the captured waveform.

Why a separate module: if this information were scattered across the UI,
the answer to "what settings was a test done with" would be stuck in
screenshots. The mode's key is written to the database with every capture,
and the settings can be read back from here.

The defaults here are a **starting point**, not a rule: the operator can
change them on screen, and the values actually used are what gets recorded.

This module only defines the framework (`TestMode`, the registry, and the
generic scope-display math below) — it knows nothing about defibrillators
or ultrasonic velocity. Each app registers its own modes at import time via
`register_mode()`: see `callog_defib/defib_modes.py` and
`callog_seshizi/seshizi_modes.py`. Keeping the registry here instead of in
either app is what lets both apps record captures with the same
`test_mode` key/lookup mechanism and share `MIN_TIME_PER_DIV_S` and the
generic warnings below.
"""

FREE = "free"


class TestMode(object):

    def __init__(self, key, label, description, setup=None, capture=None,
                 chain=None, analyzer=None, warning=None):
        self.key = key
        self.label = label
        self.description = description
        #: Scale / trigger settings to apply to the instrument
        self.setup = setup or {}
        #: Capture behavior (point count, number of captures, timeout)
        self.capture = capture or {}
        #: Measurement chain: divider ratio, load resistance
        self.chain = chain or {}
        #: Function that analyzes the captured waveform, or None
        self.analyzer = analyzer
        #: Safety / connection warning shown to the operator
        self.warning = warning

    @property
    def needs_load(self):
        return "load_ohm" in self.chain


MODES = []
BY_KEY = {}


def register_mode(mode):
    """Adds a mode to the shared registry. Called by each app at import time."""
    MODES.append(mode)
    BY_KEY[mode.key] = mode
    return mode


register_mode(TestMode(
    key=FREE,
    label="Serbest yakalama",
    description="Cihazdaki mevcut ayarlarla yakalar, hiçbir şeyi değiştirmez.",
))


def get(key):
    return BY_KEY.get(key or FREE, BY_KEY[FREE])


#: Below this, an oscilloscope screen — the instrument's own and this
#: app's scope view alike — shows nothing useful: a few carrier cycles
#: per division become indistinguishable. This floor prefers showing a
#: bit of harmless extra silence over making a signal unreadable.
MIN_TIME_PER_DIV_S = 1e-6


def software_factor(divider_ratio, probe_ratio_on_scope):
    """Multiplier to apply in software to data coming from the instrument.

    If the divider ratio was reported to the instrument as probe
    attenuation, the instrument **already** returns the real voltage;
    multiplying again on top of that inflates the file by 1000x. If it
    wasn't reported (free mode, older firmware), software applies the
    multiplier. This division closes the gap between the two cases.
    """
    divider = float(divider_ratio or 1.0)
    probe = float(probe_ratio_on_scope or 1.0)
    if probe <= 0:
        probe = 1.0
    return divider / probe


def scale(values, factor):
    """Scales the values by the given multiplier."""
    factor = float(factor or 1.0)
    # Always returns a list: if a numpy array were returned instead, a
    # caller's `if not values` check would blow up with "ambiguous truth
    # value."
    return [float(v) * factor for v in values]


def screen_span(volts_per_div, divisions=8):
    """The voltage range covered by the screen (± half). None if no scale."""
    if not volts_per_div:
        return None
    return float(volts_per_div) * divisions / 2.0


def trigger_warning(trigger_level, volts_per_div, divisions=8):
    """Whether the trigger threshold stays within the screen.

    The signal can never reach a threshold that's off-screen. In NORMal
    sweep mode this shows up as "never triggers, screen stays blank" with
    no obvious cause — the user assumes the scale or the cable is wrong.
    """
    span = screen_span(volts_per_div, divisions)
    if span is None or trigger_level is None:
        return None
    if abs(float(trigger_level)) > span:
        return ("Tetikleme eşiği (%.4g V) ekran aralığının (±%.4g V) dışında — "
                "cihaz bu eşiğe ulaşamaz ve hiç tetiklenmez. Eşiği küçültün "
                "ya da V/bölme değerini büyütün." % (float(trigger_level), span))
    return None


def clipping_warning(values, volts_per_div, divider_ratio=1.0, divisions=8):
    """Whether the waveform may have exceeded the screen range.

    The oscilloscope doesn't report a clipped signal as an error; a peak
    that runs off the screen gets recorded as a flat line and measures
    smaller than the real peak voltage. The energy calculation comes out
    low for the same reason.
    """
    # Can't write `not values`: raises ValueError on a numpy array.
    if not volts_per_div or values is None or len(values) == 0:
        return None
    full_scale = float(volts_per_div) * divisions * float(divider_ratio or 1.0)
    peak = max(abs(float(v)) for v in values)
    if peak >= 0.98 * (full_scale / 2.0):
        return ("Tepe değer (%.4g V) ekran aralığının (±%.4g V) sınırında — "
                "dalga kırpılmış olabilir. V/bölme değerini büyütüp tekrarlayın."
                % (peak, full_scale / 2.0))
    return None
