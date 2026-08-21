"""Defibrillator shock waveform analysis.

Derives what the device actually delivered from the captured waveform: phase
peak voltages, phase durations, tilt, and energy delivered to the load.

Measurement chain
------------------
The defibrillator output **cannot be connected directly to the
oscilloscope**: the DSOX1202A input is rated 300 Vrms CAT I, while a
defibrillator can put out up to 5 kV. In between sits the **50 Ω
non-inductive load** and a **high-voltage divider** required by IEC
60601-2-4. This module works in real defibrillator voltage; multiplying the
value coming from the oscilloscope by the divider ratio is the caller's job
(see `waveform.save`), and the ratio is recorded — if the ratio isn't
recorded, the file is silently off by a factor of 1000.

Limitation
----------
The numbers here are **computed from the captured waveform**, not values
measured by a certified defibrillator analyzer. Energy is derived from the
voltage record: E = ∫ v²/R dt. The actual value of the load resistor and the
oscilloscope's vertical accuracy feed directly into the result.
"""

import math

#: Threshold that defines phase boundaries — percentage of the peak value.
#: 5%: above the noise floor, but low enough not to miss the truncation
#: instant. A higher threshold systematically measures phase duration as
#: shorter; a lower one mistakes noise for a pulse.
THRESHOLD_RATIO = 0.05

#: A second phase smaller than this ratio is considered "absent" — a
#: monophasic device, or just noise. On biphasic devices the second phase
#: peak is generally greater than 40% of the first.
BIPHASIC_MIN_RATIO = 0.10

#: Minimum duration of a phase (s) and minimum sample count.
#:
#: The oscilloscope's 8-bit vertical resolution gets coarser as the vertical
#: scale grows. When a capture spans only a few dozen quantization steps,
#: even a **single-sample** baseline noise spike can exceed the threshold
#: (5% of the peak value): at 30 J readings a quantization step was 40 V
#: while the threshold was 28 V. In that case "the first unbroken region
#: above threshold" was single-sample noise rather than a real phase; the
#: second phase was never found, the shock was mistaken for monophasic, and
#: because energy was computed from the first phase alone, it came out low.
#:
#: A real defibrillator phase is on the order of milliseconds, and even the
#: narrowest pacemaker pulse is around half a millisecond; a microsecond-scale
#: spike cannot be a phase. The limit was set between the two: about 10x the
#: noise spike, about 1/10th of a real pulse.
MIN_PHASE_DURATION_S = 50e-6
MIN_PHASE_SAMPLES = 3

#: IEC 60601-2-4 energy tolerance: 15% of the set value or 3 J, whichever is
#: greater. Percentage alone would give a band like ±0.3 J at a 2 J setting
#: that the measurement chain can't resolve; the 3 J floor prevents that at
#: low settings.
ENERGY_TOLERANCE_RATIO = 0.15
ENERGY_TOLERANCE_FLOOR_J = 3.0

#: Level at which the shock is considered to have ended — percentage of the
#: peak value — and the number of samples that must stay below that level.
#:
#: Phase boundaries are drawn with `THRESHOLD_RATIO` (5%); but the capacitor
#: keeps delivering energy to the load after the truncation instant. If the
#: energy integral is cut off at the phase boundary, this tail is lost. The
#: limit is pulled down to 1%: the remaining energy is negligible, while the
#: noise floor is still far below. `HOLD` prevents a single noise spike from
#: extending the integral to the end of the record.
TAIL_THRESHOLD_RATIO = 0.01
TAIL_HOLD_SAMPLES = 20


def energy_tolerance(nominal_j):
    """± absolute tolerance (J) for the set energy. None if no nominal."""
    if nominal_j is None:
        return None
    nominal_j = float(nominal_j)
    if nominal_j <= 0:
        return None
    return max(nominal_j * ENERGY_TOLERANCE_RATIO, ENERGY_TOLERANCE_FLOOR_J)


def analyze(times, values, load_ohm=50.0):
    """Analyzes the shock waveform.

    times: seconds, values: actual defibrillator voltage (V)
    Return: dict; {"found": False} if the waveform contains no pulse
    """
    n = min(len(times), len(values))
    if n < 8 or not load_ohm:
        return {"found": False, "reason": "Yeterli veri yok"}

    times = [float(t) for t in times[:n]]
    values = [float(v) for v in values[:n]]

    # Baseline (offset) is the median of the pre-trigger region: it's the
    # measurement chain's own DC drift, not the real voltage across the
    # load. It's subtracted before both phase detection and the
    # E = ∫v²/R dt computation.
    #
    # Energy used to be computed from the raw signal. Gold-standard
    # measurements showed this was wrong: since the device's error is a
    # pure gain, the correct algorithm is the one that pins the
    # measurement/gold ratio to a single constant across 2-360 J. With the
    # baseline-corrected calculation this ratio's coefficient of variation
    # is 0.93%, versus 1.77% for the raw calculation — the corrected
    # calculation is twice as consistent.
    baseline = _baseline(times, values)
    values = [v - baseline for v in values]

    peak_abs = max(abs(v) for v in values)
    if peak_abs <= 0:
        return {"found": False, "reason": "Sinyal yok"}

    threshold = THRESHOLD_RATIO * peak_abs
    phase1 = _phase(times, values, threshold, positive=_peak_is_positive(values))
    if phase1 is None:
        return {"found": False, "reason": "Darbe bulunamadı"}

    phase2 = _phase(times, values, threshold,
                    positive=not phase1["positive"],
                    start_after=phase1["end_index"])
    if phase2 is not None and abs(phase2["peak"]) < BIPHASIC_MIN_RATIO * abs(phase1["peak"]):
        phase2 = None

    phases = [phase1] + ([phase2] if phase2 else [])
    start = phase1["start_time"]
    end = (phase2 or phase1)["end_time"]

    shock_end = _shock_end(values, peak_abs, (phase2 or phase1)["end_index"])
    energy = _energy(times, values, load_ohm, phase1["start_index"], shock_end)

    return {
        "found": True,
        "shape": "bifazik" if phase2 else "monofazik",
        "baseline": baseline,
        "load_ohm": float(load_ohm),
        "phases": phases,
        "peak_voltage": max(abs(p["peak"]) for p in phases),
        "peak_current": max(abs(p["peak"]) for p in phases) / float(load_ohm),
        "total_duration": end - start,
        "start_time": start,
        "end_time": end,
        "energy_j": energy,
        # Range covered by the energy integral — longer than the phase
        # duration, since it also includes the post-truncation tail (see
        # `_shock_end`).
        "energy_start_time": times[phase1["start_index"]],
        "energy_end_time": times[shock_end],
        "sample_interval": (times[-1] - times[0]) / (n - 1) if n > 1 else None,
        "points": n,
    }


def _peak_is_positive(values):
    return abs(max(values)) >= abs(min(values))


def _baseline(times, values):
    """Median of the pre-trigger region.

    Median, not mean: a single spike before the trigger (a pre-pulse, a
    leak) would shift the mean and drag every phase boundary with it.
    """
    pre = [v for t, v in zip(times, values) if t < 0]
    if len(pre) < 5:
        # No pre-trigger region: treat the first 5% as baseline
        pre = values[:max(5, len(values) // 20)]
    return _median(pre)


def _median(seq):
    ordered = sorted(seq)
    k = len(ordered)
    if k == 0:
        return 0.0
    mid = k // 2
    return ordered[mid] if k % 2 else 0.5 * (ordered[mid - 1] + ordered[mid])


def _phase(times, values, threshold, positive, start_after=0):
    """Finds and measures the first **meaningful** unbroken region above threshold.

    Accepting the first region above threshold unconditionally would miss
    the real phase entirely whenever a quantization step rose above the
    threshold (see `MIN_PHASE_DURATION_S`). Regions too short to be a phase
    are now skipped and the search continues.
    """
    sign = 1.0 if positive else -1.0
    i = max(0, int(start_after))
    n = len(values)

    while i < n:
        if sign * values[i] <= threshold:
            i += 1
            continue
        begin = i
        while i < n and sign * values[i] > threshold:
            i += 1
        end = i - 1
        if _is_phase_sized(times, begin, end):
            return _measure_phase(times, values, begin, end, positive)
    return None


def _is_phase_sized(times, begin, end):
    """Is the region long enough to be a real phase — or is it noise?"""
    if end - begin + 1 < MIN_PHASE_SAMPLES:
        return False
    return (times[end] - times[begin]) >= MIN_PHASE_DURATION_S


def _shock_end(values, peak, after):
    """Index of the sample where the shock actually ends.

    Scans forward from the end of the last phase: the shock has ended once
    the signal drops below `TAIL_THRESHOLD_RATIO` of the peak value and
    stays there for `TAIL_HOLD_SAMPLES` samples. A threshold without a hold
    would cut the integral short at a single zero-crossing inside the tail.
    """
    limit = TAIL_THRESHOLD_RATIO * peak
    below = 0
    for i in range(max(0, int(after)), len(values)):
        if abs(values[i]) <= limit:
            below += 1
            if below >= TAIL_HOLD_SAMPLES:
                return i - TAIL_HOLD_SAMPLES + 1
        else:
            below = 0
    return len(values) - 1


def _measure_phase(times, values, begin, end, positive):
    """Computes the magnitudes of a phase with known boundaries."""
    segment = values[begin:end + 1]
    peak = max(segment, key=abs)
    initial = segment[0]
    final = segment[-1]
    # Tilt: the drop from peak value to the voltage at the truncation
    # instant. In a truncated exponential waveform it reflects the device's
    # energy efficiency and the capacitor's time constant; it's the
    # quantity reported under IEC 60601-2-4.
    tilt = None
    if peak:
        tilt = 100.0 * (abs(peak) - abs(final)) / abs(peak)

    return {
        "positive": positive,
        "peak": peak,
        "initial": initial,
        "final": final,
        "tilt_percent": tilt,
        "start_time": times[begin],
        "end_time": times[end],
        "duration": times[end] - times[begin],
        "start_index": begin,
        "end_index": end,
        "tau": _time_constant(times[begin:end + 1], segment),
    }


def _time_constant(times, values):
    """Time constant τ (s) of the truncated exponential decay.

    v(t) = V0·e^(−t/τ) → ln|v| is linear; τ is the inverse of the slope.
    Using the two endpoints instead of least squares would let a single
    noisy sample throw off the result.
    """
    pairs = [(t - times[0], math.log(abs(v))) for t, v in zip(times, values)
             if abs(v) > 1e-12]
    if len(pairs) < 3:
        return None
    n = len(pairs)
    sx = sum(p[0] for p in pairs)
    sy = sum(p[1] for p in pairs)
    sxx = sum(p[0] * p[0] for p in pairs)
    sxy = sum(p[0] * p[1] for p in pairs)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-30:
        return None
    slope = (n * sxy - sx * sy) / denom
    if slope >= 0:
        return None          # no decay (rising) — τ is meaningless
    return -1.0 / slope


def _energy(times, values, load_ohm, begin, end):
    """E = ∫ v²/R dt — trapezoidal rule, over the **baseline-corrected** signal.

    `analyze` passes in values with the baseline already subtracted: the
    measurement chain's DC drift isn't the voltage across the load, and if
    it leaks into the v² computation it skews the result.

    The range runs from the start of the first phase to where the
    post-truncation tail ends (see `_shock_end`) — cutting it off at the
    phase boundary would lose the energy carried by the tail.

    Trapezoidal instead of a rectangular sum: in a truncated exponential
    waveform, if the sampling interval is coarse relative to the time
    constant, a rectangular sum systematically overstates the energy.
    """
    total = 0.0
    for i in range(begin, min(end, len(times) - 1)):
        dt = times[i + 1] - times[i]
        if dt <= 0:
            continue
        p1 = values[i] ** 2 / load_ohm
        p2 = values[i + 1] ** 2 / load_ohm
        total += 0.5 * (p1 + p2) * dt
    return total


def summary_rows(result):
    """(label, value) pairs to display in the UI and the report."""
    if not result.get("found"):
        return [("Sonuç", result.get("reason", "Darbe bulunamadı"))]

    # Ordered by importance: the first number checked in a defibrillator
    # test is the delivered energy, so it must stay visible even if the
    # panel is shortened.
    rows = [
        ("Aktarılan enerji", "%.4g J" % result["energy_j"]),
        ("Tepe gerilim", _v(result["peak_voltage"])),
        ("Tepe akım", "%.4g A" % result["peak_current"]),
        ("Dalga biçimi", result["shape"]),
        ("Toplam süre", _s(result["total_duration"])),
        ("Yük direnci", "%g Ω" % result["load_ohm"]),
    ]
    for i, ph in enumerate(result["phases"], start=1):
        rows.append(("%d. faz süresi" % i, _s(ph["duration"])))
        rows.append(("%d. faz tepe" % i, _v(ph["peak"])))
        if ph["tilt_percent"] is not None:
            rows.append(("%d. faz eğimi (tilt)" % i,
                         "%.1f %%" % ph["tilt_percent"]))
        if ph["tau"]:
            rows.append(("%d. faz zaman sabiti τ" % i, _s(ph["tau"])))
    return rows


def _v(value):
    if value is None:
        return "—"
    if abs(value) >= 1000:
        return "%.4g kV" % (value / 1000.0)
    return "%.4g V" % value


def _s(value):
    if value is None:
        return "—"
    for factor, prefix in ((1.0, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n")):
        if abs(value) >= factor:
            return "%.4g %ss" % (value / factor, prefix)
    return "%.3g s" % value
