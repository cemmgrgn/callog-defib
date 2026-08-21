"""Device drivers.

To add a new device that both apps might use: write a module that inherits
`base.Driver` and register it below in `REGISTRY`/`SIMULATED_DRIVERS`
directly. To add a device specific to one app (e.g. `callog_seshizi`'s
DSOX3012T): register it via `register_driver()` from that app's
`__init__.py` instead — see `callog_seshizi/__init__.py`. Either way the
rest of the application (discovery, `drivers.create()`, `is_simulated()`)
stays unchanged, since both paths feed the same registry.
"""

from .base import Driver, InstrumentError, MeasurementFunction, WaveformDriver
from .fluke8846a import Fluke8846A
from .keysight_dsox1202a import KeysightDSOX1202A
from .simulated import SimulatedDMM
from .simulated_scope import SimulatedScope

REGISTRY = {
    "fluke8846a": Fluke8846A,
    "dsox1202a": KeysightDSOX1202A,
    "simulated": SimulatedDMM,
    "simulated_scope": SimulatedScope,
}

#: Names of the simulation drivers. The interface used to check "is this a
#: real device" by comparing against a single name (`== "simulated"`); once a
#: second simulation driver was added, that check silently gave the wrong
#: answer. `register_driver(..., simulated=True)` adds to this too.
SIMULATED_DRIVERS = set(("simulated", "simulated_scope"))


def register_driver(name, cls, simulated=False):
    """Adds a driver to the shared registry — for app-specific devices."""
    REGISTRY[name] = cls
    if simulated:
        SIMULATED_DRIVERS.add(name)
    return cls


def create(driver_name, address, **kwargs):
    """Creates an instance from the driver name."""
    try:
        cls = REGISTRY[driver_name]
    except KeyError:
        raise InstrumentError("Bilinmeyen sürücü: %s" % driver_name)
    return cls(address, **kwargs)


def supports_waveform(driver_name):
    """Whether the driver can capture waveforms — queryable before connecting."""
    cls = REGISTRY.get(driver_name)
    return bool(cls and getattr(cls, "supports_waveform", False))


def is_simulated(driver_name):
    return driver_name in SIMULATED_DRIVERS


__all__ = [
    "Driver", "InstrumentError", "MeasurementFunction", "WaveformDriver",
    "Fluke8846A", "KeysightDSOX1202A", "SimulatedDMM", "SimulatedScope",
    "REGISTRY", "create", "supports_waveform",
]
