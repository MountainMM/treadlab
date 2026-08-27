"""Map a recorded heart-rate stream onto a simulated activity's records.

The single authoritative implementation of the merge (the browser UI only
draws a preview). Records carry a relative time 't' in seconds; HR samples
are [t_rel, hr, cad] or [t_rel, hr, cad, temp_c] rows relative to their own
file's first record (older 3-element rows are still accepted).

Alignment rule: the record at activity-time t takes the HR sample nearest to
sample-time (t + offset). offset > 0 means the HR stream started earlier
than the simulated activity (skip its first `offset` seconds). Cadence and
temperature ride along with whichever sample supplied the heart rate.
"""

from bisect import bisect_left

MATCH_TOLERANCE_S = 5.0   # a sample this close counts as simultaneous
CARRY_FORWARD_S = 10.0    # otherwise hold the previous sample this long


def merge_hr(records, samples, offset=0.0, copy_cadence=True, copy_temp=True):
    """Mutates records (list of dicts with 't') by setting 'hr' and
    optionally 'cad'/'temp' from samples ([[t_rel, hr, cad, temp?], ...]).
    Returns {'matched': n, 'total': n_records, 'hr_points': n_samples}."""
    cleaned = sorted(
        (s for s in samples
         if s and s[1] and 0 < float(s[1]) < 255),
        key=lambda s: float(s[0]))
    times = [float(s[0]) for s in cleaned]
    matched = 0
    for rec in records:
        want = float(rec["t"]) + float(offset)
        hit = _nearest(cleaned, times, want)
        if hit is None:
            continue
        s_t, s_hr = float(hit[0]), float(hit[1])
        gap = abs(s_t - want)
        if gap <= MATCH_TOLERANCE_S or (0 <= want - s_t <= CARRY_FORWARD_S):
            rec["hr"] = int(round(s_hr))
            if copy_cadence and len(hit) > 2 and hit[2] is not None:
                rec["cad"] = float(hit[2])
            if copy_temp and len(hit) > 3 and hit[3] is not None:
                rec["temp"] = float(hit[3])
            matched += 1
    return {"matched": matched, "total": len(records),
            "hr_points": len(cleaned)}


def _nearest(samples, times, want):
    if not samples:
        return None
    i = bisect_left(times, want)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(samples):
            if best is None or abs(times[j] - want) < abs(float(best[0]) - want):
                best = samples[j]
    return best
