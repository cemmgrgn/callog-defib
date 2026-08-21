"""Registers this app's test modes into the shared `testmodes` registry.

Importing this module (done once, from `callog_defib/__init__.py`) is what
makes `testmodes.MODES`/`testmodes.get()` know about the defibrillator and
pacer modes — the registry itself lives in `callog_common.testmodes` and
knows nothing about defib specifically.
"""

from callog_common import testmodes

from . import defib

DEFIB_BIPHASIC = "defib_biphasic"
DEFIB_MONOPHASIC = "defib_monophasic"
PACER = "pacer"


def _defib_analyzer(times, values, chain):
    return defib.analyze(times, values,
                         load_ohm=chain.get("load_ohm", 50.3))


_DEFIB_WARNING = (
    "Defibrilatör çıkışı osiloskoba DOĞRUDAN BAĞLANAMAZ — cihaz girişi "
    "300 Vrms (CAT I), defibrilatör 5 kV'a kadar çıkar.\n\n"
    "Bağlantı: defibrilatör → 50 Ω endüktif olmayan yük → yüksek gerilim "
    "bölücü → osiloskop. Bölücü oranını ve yük direncini aşağıya doğru "
    "girin; kayıt gerçek defibrilatör gerilimine çevrilerek saklanır."
)

BIPHASIC_MODE = testmodes.register_mode(testmodes.TestMode(
    key=DEFIB_BIPHASIC,
    label="Defibrilatör — bifazik şok",
    description=(
        "Tek atımlık şok yakalar. Faz süreleri, tepe gerilim/akım, eğim "
        "(tilt) ve yüke aktarılan enerji hesaplanır."),
    setup={
        "volts_per_div": 50.0,
        "time_per_div": 5e-3,
        # The shock should start on the left of the screen: the
        # pre-trigger region is just enough to measure the baseline,
        # the rest is given to the pulse.
        "time_position": 15e-3,
        # The threshold is in terms of the real, **pre-divider**
        # voltage. At a 1:1000 divider, a 5 V threshold meant 5 mV at
        # the oscilloscope input: below the instrument's trigger
        # resolution, so it never triggered and the screen stayed
        # blank. 50 V corresponds to 50 mV on the input side and
        # reliably catches the shock's rising edge.
        "trigger_level": 50.0,
        "trigger_slope": "POSitive",
        "coupling": "DC",
    },
    capture={"points": 20000, "count": 1, "timeout_s": 0},
    # Probe ratio isn't a separate field: the way to tell the
    # instrument about the external divider is the probe attenuation —
    # the two are the same number. Keeping them separate would let one
    # silently drift from the other, producing a 1000x error.
    chain={"divider_ratio": 1000.0, "load_ohm": 50.3},
    analyzer=_defib_analyzer,
    warning=_DEFIB_WARNING,
))

MONOPHASIC_MODE = testmodes.register_mode(testmodes.TestMode(
    key=DEFIB_MONOPHASIC,
    label="Defibrilatör — monofazik şok",
    description=(
        "Tek kutuplu şok. Aynı ölçümler; ikinci faz aranmaz."),
    setup={
        "volts_per_div": 50.0,
        "time_per_div": 5e-3,
        "time_position": 15e-3,
        "trigger_level": 50.0,
        "trigger_slope": "POSitive",
        "coupling": "DC",
    },
    capture={"points": 20000, "count": 1, "timeout_s": 0},
    chain={"divider_ratio": 1000.0, "load_ohm": 50.3},
    analyzer=_defib_analyzer,
    warning=_DEFIB_WARNING,
))

PACER_MODE = testmodes.register_mode(testmodes.TestMode(
    key=PACER,
    label="Harici kalp pili darbesi",
    description=(
        "Pacer darbesi: genlik, genişlik ve tekrarlama. Daha küçük "
        "gerilim ve daha kısa zaman tabanı."),
    setup={
        "volts_per_div": 5.0,
        "time_per_div": 20e-3,
        "time_position": 40e-3,
        # Same reasoning as in defib mode: at a 1:1000 divider the
        # threshold is a thousandth of that at the instrument input.
        # 5 V is within the ±20 V screen range and corresponds to
        # 5 mV at the input.
        "trigger_level": 5.0,
        "trigger_slope": "POSitive",
        "coupling": "DC",
    },
    capture={"points": 20000, "count": 0, "timeout_s": 30},
    chain={"divider_ratio": 1000.0, "load_ohm": 50.3},
    analyzer=_defib_analyzer,
    warning=(
        "Pacer çıkışı da yük direnci üzerinden ölçülür. Bağlantıyı "
        "kontrol edin ve bölücü oranını girin."),
))
