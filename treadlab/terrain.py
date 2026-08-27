"""Sub-meter terrain texture for exported altitude streams.

A perfectly linear synthetic climb collides with FIT's 0.2 m altitude
quantization: the encoded stream becomes a periodic staircase whose beat
pattern Strava's grade smoothing renders as a zig-zag GAP trace (grade
oscillating ~7-14% on a constant 10% treadmill climb, flagged by Cam after
a real upload). Real barometric recordings never show this because real
terrain has organic sub-meter variation that swamps the staircase.

add_texture() layers a deterministic, grade-proportional undulation onto
the altitude stream:

- amplitude = 2.2 x |local grade| meters, capped at 0.30 m (22 cm on a 10%
  climb) -- flat segments get exactly zero and stay perfectly flat;
- the texture's maximum slope is ~16% of the local grade, so climbs stay
  strictly monotonic and total ascent / descent are preserved;
- endpoints are blended to zero so net elevation and start/end altitude
  are untouched;
- wavelengths (181 m and 47 m) are incommensurate with the quantization
  staircase, which breaks up the beat pattern Strava was amplifying.
"""

import math

_W1, _W2 = 181.0, 47.0   # texture wavelengths, meters
_K = 2.2                 # meters of amplitude per unit of |grade|
_CAP = 0.30              # amplitude ceiling, meters


def add_texture(records):
    """Mutates records' 'alt' in place (needs 'alt' + 'dist').
    Returns the number of records touched."""
    pts = [r for r in records
           if r.get("alt") is not None and r.get("dist") is not None]
    if len(pts) < 3:
        return 0
    total_d = pts[-1]["dist"] - pts[0]["dist"]
    if total_d <= 0:
        return 0

    raw = []
    for j, r in enumerate(pts):
        prev = pts[max(0, j - 1)]
        nxt = pts[min(len(pts) - 1, j + 1)]
        dd = nxt["dist"] - prev["dist"]
        g = abs((nxt["alt"] - prev["alt"]) / dd) if dd > 0 else 0.0
        amp = min(_CAP, _K * g)
        d = r["dist"]
        raw.append(amp * (0.62 * math.sin(2 * math.pi * d / _W1)
                          + 0.38 * math.sin(2 * math.pi * d / _W2 + 2.03)))

    t0, t1 = raw[0], raw[-1]
    d0 = pts[0]["dist"]
    for j, r in enumerate(pts):
        f = (r["dist"] - d0) / total_d
        r["alt"] += raw[j] - (t0 * (1 - f) + t1 * f)
    return len(pts)
