"""CalLog Defib — defibrillator/pacemaker waveform capture and certification.

Built on `callog_common` (auth, certificates, audit, database, backup — the
lab-wide infrastructure shared with `callog_seshizi`). This package adds
only what's specific to defibrillator testing: shock/pacer analysis,
waveform capture UI, and the shock/series/summary reports.

Importing this package registers its test modes into the shared
`callog_common.testmodes` registry — anything that lists `testmodes.MODES`
needs this import to have happened first (`run.py` does it on startup).
"""

from . import defib_modes  # noqa: F401  (registers DEFIB_BIPHASIC/MONOPHASIC/PACER)

__version__ = "0.2.0"
__author__ = "Cem Girgin"
