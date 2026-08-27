"""Cosmetic GPS track: a Zwift-style closed loop in an empty patch of the
South Pacific, sized so the loop's length equals the activity's distance.

Each record's position is assigned from the distance stream, so speed
changes, laps and pauses stay consistent: faster seconds cover more of the
loop, and the final record arrives exactly back at the start.

The anchor (12.1 S, 166.0 E) is open water in the Coral Sea, 80+ km from
the nearest land (Vanikoro / the Torres Islands) and well away from the
Solomon-Islands spot where Zwift parks Watopia -- the loop can never overlap
a real road or an existing virtual segment. Purely cosmetic: it exists so
Strava and friends render a map thumbnail for the activity.
"""

import math

ANCHOR_LAT = -12.1   # default: open Coral Sea, near Zwift's Watopia spot
ANCHOR_LON = 166.0

# location key -> (lat, lon); both are verified-empty open ocean
LOCATIONS = {
    "watopia": (ANCHOR_LAT, ANCHOR_LON),
    # Point Nemo, the oceanic pole of inaccessibility (~2,700 km from any
    # land; the "spacecraft cemetery"). High latitude exercises the
    # cos(lat) longitude scaling.
    "nemo": (-48.876, -123.393),
}

_N = 2048  # curve sampling resolution


def _blob(theta):
    """Organic loop shape: unit radius plus two gentle harmonics. Amplitudes
    are kept small so curvature stays low everywhere -- sharper lobes made
    Strava's track smoothing dent the pace trace at the two pinch points."""
    return 1.0 + 0.11 * math.sin(2 * theta) + 0.06 * math.sin(3 * theta + 1.1)


def _polyline():
    pts = []
    for i in range(_N + 1):
        th = 2 * math.pi * i / _N
        r = _blob(th)
        pts.append((r * math.cos(th), r * math.sin(th)))
    cum = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
    return pts, cum


def add_ocean_loop(records, lat0=ANCHOR_LAT, lon0=ANCHOR_LON):
    """Set 'lat'/'lon' (degrees) on each record along one closed loop whose
    length equals the final distance. Records need monotonic 'dist' in
    meters; a missing dist reuses the previous position. Returns the number
    of records positioned."""
    total = 0.0
    for r in records:
        d = r.get("dist")
        if d is not None:
            total = max(total, float(d))
    if total <= 0:
        return 0

    pts, cum = _polyline()
    perim = cum[-1]
    scale = total / perim  # meters per curve unit
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat0))

    n = 0
    last = 0.0
    j = 0
    for r in records:
        d = r.get("dist")
        d = last if d is None else float(d)
        last = d
        s = (d / total) * perim
        while j + 1 < len(cum) - 1 and cum[j + 1] < s:
            j += 1
        seg = cum[j + 1] - cum[j]
        f = (s - cum[j]) / seg if seg > 0 else 0.0
        x = (pts[j][0] + f * (pts[j + 1][0] - pts[j][0])) * scale
        y = (pts[j][1] + f * (pts[j + 1][1] - pts[j][1])) * scale
        r["lat"] = lat0 + y / m_per_deg_lat
        r["lon"] = lon0 + x / m_per_deg_lon
        n += 1
    return n
