"""Automatic device discovery.

Method: scan VISA resources, ask each one ``*IDN?``, and match the response
against the serial number in the inventory.

Why serial number: the VISA address (GPIB0::22) shifts when a cable or
address changes, the serial number doesn't. This makes the "I measured with
the wrong device" mistake impossible.
"""

BAUD_CANDIDATES = (9600, 19200, 38400, 57600, 115200, 4800, 2400)

#: Patterns to look for in the *IDN? response → driver name
KNOWN_MODELS = (
    ("FLUKE", "8846A", "fluke8846a"),
    ("FLUKE", "8845A", "fluke8846a"),
    # DSOX1202A's *IDN? response: "KEYSIGHT TECHNOLOGIES,DSO-X 1202A,..."
    # Older firmware may report the brand field as AGILENT TECHNOLOGIES,
    # so the model pattern alone must also match.
    ("KEYSIGHT", "1202A", "dsox1202a"),
    ("AGILENT", "1202A", "dsox1202a"),
)
# Other members of the 1200 X family (1102G, 1204G) are deliberately not
# listed here: the 1204G has four channels, but the driver only defines two.
# Declaring it supported "probably works" without having the device in hand
# would silently turn into reading a missing channel in the field.


class Found(object):
    """A device found during a scan."""

    def __init__(self, address, idn, driver=None, serial_no=None,
                 brand=None, model=None, serial_cfg=None):
        self.address = address
        self.idn = idn
        self.driver = driver
        self.serial_no = serial_no
        self.brand = brand
        self.model = model
        self.serial_cfg = serial_cfg or {}

    @property
    def recognized(self):
        return self.driver is not None

    def __repr__(self):
        return "<Found %s %s>" % (self.address, self.idn)


def parse_idn(idn):
    """'FLUKE,8846A,1234567,1.15' -> (brand, model, serial no)"""
    parts = [p.strip() for p in idn.split(",")]
    while len(parts) < 4:
        parts.append("")
    return parts[0], parts[1], parts[2]


def match_driver(idn):
    up = idn.upper()
    for brand, model, driver in KNOWN_MODELS:
        if brand in up and model in up:
            return driver
    return None


def scan(progress=None, include_serial=True, serial_timeout_ms=1200):
    """Scans connected devices.

    progress: callable(message) invoked at each step — used to show progress
    in the interface.
    Returns: a list of Found objects.
    """
    def _p(msg):
        if progress:
            progress(msg)

    try:
        import pyvisa
    except ImportError:
        _p("PyVISA kurulu değil — tarama atlandı.")
        return []

    # Both backends are tried. A single ResourceManager() wasn't enough:
    # if PyVISA finds a vendor VISA (Keysight IO Libraries, NI-VISA) it uses
    # that; otherwise it falls back to pyvisa-py. A USB oscilloscope only
    # shows up under the vendor VISA; a serial port may only show up under
    # pyvisa-py. Checking only one and skipping the other led to "device
    # not found" while the device was actually plugged in.
    managers = []
    errors = []
    for spec, label in ((None, "üretici VISA"), ("@py", "pyvisa-py")):
        try:
            managers.append((pyvisa.ResourceManager(spec) if spec
                             else pyvisa.ResourceManager(), label))
        except Exception as exc:
            errors.append("%s: %s" % (label, exc))

    if not managers:
        _p("VISA başlatılamadı — %s" % "; ".join(errors))
        return []

    results = []
    seen = set()
    total = 0
    for rm, label in managers:
        try:
            resources = list(rm.list_resources("?*"))
        except Exception as exc:
            _p("%s kaynak listesi alınamadı: %s" % (label, exc))
            resources = []
        total += len(resources)

        for addr in resources:
            key = addr.strip().upper()
            if key in seen:
                continue
            seen.add(key)

            is_serial = key.startswith("ASRL")
            if is_serial and not include_serial:
                continue

            if is_serial:
                found = _probe_serial(rm, addr, serial_timeout_ms, _p)
            else:
                found = _probe(rm, addr, 2000, _p)

            if found:
                results.append(found)

        # rm.close() is deliberately not called: PyVISA caches the
        # ResourceManager per backend, and closing it here would also close
        # the object held by a driver that connects right after this.

    _p("%d VISA kaynağı tarandı, %d cihaz yanıt verdi."
       % (total, len(results)))
    return results


def _probe(rm, addr, timeout_ms, _p, serial_cfg=None):
    """Asks a single resource *IDN?."""
    _p("Sorgulanıyor: %s" % addr)
    inst = None
    try:
        inst = rm.open_resource(addr)
        inst.timeout = timeout_ms
        if serial_cfg:
            inst.baud_rate = serial_cfg["baud"]
            inst.read_termination = "\r\n"
            inst.write_termination = "\r\n"
        else:
            inst.read_termination = "\n"
            inst.write_termination = "\n"
        idn = inst.query("*IDN?").strip()
        if not idn:
            return None
        brand, model, serial_no = parse_idn(idn)
        return Found(
            address=addr, idn=idn, driver=match_driver(idn),
            serial_no=serial_no, brand=brand, model=model,
            serial_cfg=serial_cfg,
        )
    except Exception:
        return None
    finally:
        if inst is not None:
            try:
                inst.close()
            except Exception:
                pass


def _probe_serial(rm, addr, timeout_ms, _p):
    """Tries baud rates in order on the serial port, returns the one that responds."""
    for baud in BAUD_CANDIDATES:
        _p("Sorgulanıyor: %s @ %d baud" % (addr, baud))
        found = _probe(rm, addr, timeout_ms, _p, serial_cfg={"baud": baud})
        if found is not None:
            return found
    return None
