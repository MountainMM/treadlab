"""Minimal FIT activity encoder (little-endian, protocol 1.0).

Based on FitLab's tested encoder (../FitLab/fitlab/fit_writer.py), extended
for TreadLab with: named sub-sports (treadmill / virtual_activity), multiple
laps (one per planned segment or live lap press), session cadence fields,
and a distance-derived average speed. Message layouts are otherwise
identical to the FitLab original.

Writes the message set needed for a valid, widely-accepted activity file:
file_id, event (timer start/stop), record stream, laps, session, activity.
Field numbers follow the public FIT profile.
"""

import struct

from .fitbase import BASE_TYPES, FIT_EPOCH_OFFSET, crc16, deg_to_semicircles

GLOBAL_FILE_ID = 0
GLOBAL_SESSION = 18
GLOBAL_LAP = 19
GLOBAL_RECORD = 20
GLOBAL_EVENT = 21
GLOBAL_ACTIVITY = 34

SPORT_NAMES = {
    "generic": 0, "running": 1, "cycling": 2, "transition": 3,
    "fitness_equipment": 4, "swimming": 5, "walking": 11, "hiking": 17,
}

SUB_SPORT_NAMES = {
    "generic": 0, "treadmill": 1, "street": 2, "trail": 3, "track": 4,
    "indoor_cycling": 6, "virtual_activity": 58,
}


def _fit_ts(unix_s):
    return int(round(unix_s)) - FIT_EPOCH_OFFSET


class _Msg:
    """A fixed message layout: emits its definition and packs data records."""

    def __init__(self, local, global_num, fields):
        self.local = local
        self.global_num = global_num
        self.fields = fields  # [(field_def_num, base_type_byte)]

    def definition(self):
        out = bytearray([0x40 | self.local, 0x00, 0x00])  # header, reserved, little-endian
        out += struct.pack("<H", self.global_num)
        out.append(len(self.fields))
        for def_num, base in self.fields:
            out += bytes([def_num, BASE_TYPES[base][1], base])
        return bytes(out)

    def data(self, values):
        """values: {field_def_num: int}; missing fields get the invalid sentinel."""
        out = bytearray([self.local])
        for def_num, base in self.fields:
            _, _, invalid, fmt = BASE_TYPES[base]
            v = values.get(def_num)
            out += struct.pack("<" + fmt, invalid if v is None else v)
        return bytes(out)


# record columns: model key -> (field_def_num, base_type, encode function)
_RECORD_COLUMNS = (
    ("time", 253, 0x86, _fit_ts),
    ("lat", 0, 0x85, deg_to_semicircles),
    ("lon", 1, 0x85, deg_to_semicircles),
    ("alt", 2, 0x84, lambda m: max(0, min(0xFFFE, int(round((m + 500.0) * 5))))),
    ("hr", 3, 0x02, lambda v: max(0, min(254, int(round(v))))),
    ("cad", 4, 0x02, lambda v: max(0, min(254, int(round(v))))),
    ("dist", 5, 0x86, lambda m: int(round(m * 100))),
    ("speed", 6, 0x84, lambda ms: max(0, min(0xFFFE, int(round(ms * 1000))))),
    ("power", 7, 0x84, lambda w: max(0, min(0xFFFE, int(round(w))))),
    ("temp", 13, 0x01, lambda c: max(-127, min(126, int(round(c))))),
)


def _lap_rows(laps, records, t0, t1):
    """Build per-lap value dicts. laps: [{'start': unix_s, 'end': unix_s}];
    when empty, the whole activity is one lap. Stats come from the records
    that fall inside each lap's window."""
    if not laps:
        laps = [{"start": t0, "end": t1}]
    laps = sorted(laps, key=lambda lp: lp["start"])
    rows = []
    for i, lp in enumerate(laps):
        s = max(t0, min(t1, lp["start"]))
        e = max(s, min(t1, lp["end"]))
        rs = [r for r in records if s <= r["time"] <= e]
        hrs = [r["hr"] for r in rs if r.get("hr") is not None]
        dl = [r["dist"] for r in rs if r.get("dist") is not None]
        ms = int(round((e - s) * 1000))
        rows.append({
            253: _fit_ts(e), 254: i, 2: _fit_ts(s), 7: ms, 8: ms,
            9: int(round((dl[-1] - dl[0]) * 100)) if dl else 0,
            0: 9, 1: 1,
            15: int(round(sum(hrs) / len(hrs))) if hrs else None,
            16: int(round(max(hrs))) if hrs else None,
        })
    return rows


def write_activity_fit(records, sport=0, sub_sport=0, manufacturer=255,
                       product=0, serial=0x1F2E3D4C, calories=None, laps=None):
    """records: list of dicts with unix 'time' (required) and optionally
    lat/lon (deg), alt (m), hr (bpm), cad (rpm), dist (m), speed (m/s),
    power (W), temp (C). laps: optional [{'start': unix_s, 'end': unix_s}].
    Returns complete FIT file bytes."""
    records = [r for r in records if r.get("time") is not None]
    if not records:
        raise ValueError("no timestamped records to write")
    records = sorted(records, key=lambda r: r["time"])
    if isinstance(sport, str):
        sport = SPORT_NAMES.get(sport.lower().strip(), 0)
    if isinstance(sub_sport, str):
        sub_sport = SUB_SPORT_NAMES.get(sub_sport.lower().strip(), 0)

    present = [c for c in _RECORD_COLUMNS
               if c[0] == "time" or any(r.get(c[0]) is not None for r in records)]

    file_id = _Msg(0, GLOBAL_FILE_ID, [(0, 0x00), (1, 0x84), (2, 0x84), (3, 0x8C), (4, 0x86)])
    event = _Msg(1, GLOBAL_EVENT, [(253, 0x86), (0, 0x00), (1, 0x00), (4, 0x02)])
    record = _Msg(2, GLOBAL_RECORD, [(num, base) for _, num, base, _ in present])
    lap = _Msg(3, GLOBAL_LAP, [
        (253, 0x86), (254, 0x84), (2, 0x86), (7, 0x86), (8, 0x86), (9, 0x86),
        (0, 0x00), (1, 0x00), (15, 0x02), (16, 0x02),
    ])
    session = _Msg(4, GLOBAL_SESSION, [
        (253, 0x86), (254, 0x84), (2, 0x86), (3, 0x85), (4, 0x85), (5, 0x00),
        (6, 0x00), (7, 0x86), (8, 0x86), (9, 0x86), (11, 0x84), (14, 0x84),
        (15, 0x84), (16, 0x02), (17, 0x02), (18, 0x02), (19, 0x02),
        (22, 0x84), (23, 0x84), (25, 0x84), (26, 0x84), (57, 0x01), (58, 0x01),
        (0, 0x00), (1, 0x00),
    ])
    activity = _Msg(5, GLOBAL_ACTIVITY, [
        (253, 0x86), (0, 0x86), (1, 0x84), (2, 0x00), (3, 0x00), (4, 0x00), (5, 0x86),
    ])

    t0, t1 = records[0]["time"], records[-1]["time"]
    elapsed_ms = int(round((t1 - t0) * 1000))

    def series(key):
        return [r[key] for r in records if r.get(key) is not None]

    dists = series("dist")
    total_dist_m = dists[-1] if dists else 0.0
    total_dist_cm = int(round(total_dist_m * 100))
    hrs = series("hr")
    cads = series("cad")
    temps = series("temp")
    speeds = series("speed")
    alts = series("alt")

    def temp8(v):
        return max(-127, min(126, int(round(v))))
    ascent = descent = 0.0
    for a, b in zip(alts, alts[1:]):
        d = b - a
        if d > 0:
            ascent += d
        else:
            descent -= d
    lats = [r["lat"] for r in records if r.get("lat") is not None]
    lons = [r["lon"] for r in records if r.get("lon") is not None]

    if total_dist_m > 0 and elapsed_ms > 0:
        avg_speed_mm = int(round(total_dist_m / (elapsed_ms / 1000.0) * 1000))
    elif speeds:
        avg_speed_mm = int(round(sum(speeds) / len(speeds) * 1000))
    else:
        avg_speed_mm = None

    body = bytearray()
    body += file_id.definition()
    body += file_id.data({0: 4, 1: manufacturer, 2: product, 3: serial, 4: _fit_ts(t0)})
    body += event.definition()
    body += event.data({253: _fit_ts(t0), 0: 0, 1: 0, 4: 0})  # timer start
    body += record.definition()
    for r in records:
        values = {}
        for key, num, _base, enc in present:
            v = r.get(key)
            if v is not None:
                values[num] = enc(v)
        body += record.data(values)
    body += event.data({253: _fit_ts(t1), 0: 0, 1: 4, 4: 0})  # timer stop_all

    lap_rows = _lap_rows(laps, records, t0, t1)
    body += lap.definition()
    for row in lap_rows:
        body += lap.data(row)

    body += session.definition()
    body += session.data({
        253: _fit_ts(t1), 254: 0, 2: _fit_ts(t0),
        7: elapsed_ms, 8: elapsed_ms, 9: total_dist_cm,
        0: 8, 1: 1,
        3: deg_to_semicircles(lats[0]) if lats else None,
        4: deg_to_semicircles(lons[0]) if lons else None,
        5: sport, 6: sub_sport,
        11: int(round(calories)) if calories else None,
        14: avg_speed_mm,
        15: int(round(max(speeds) * 1000)) if speeds else None,
        16: int(round(sum(hrs) / len(hrs))) if hrs else None,
        17: int(round(max(hrs))) if hrs else None,
        18: int(round(sum(cads) / len(cads))) if cads else None,
        19: int(round(max(cads))) if cads else None,
        22: int(round(ascent)), 23: int(round(descent)),
        25: 0, 26: len(lap_rows),
        57: temp8(sum(temps) / len(temps)) if temps else None,
        58: temp8(max(temps)) if temps else None})
    body += activity.definition()
    body += activity.data({253: _fit_ts(t1), 0: elapsed_ms, 1: 1, 2: 0,
                           3: 26, 4: 1, 5: _fit_ts(t1)})

    header = bytearray([14, 0x10])
    header += struct.pack("<H", 2195)  # profile version
    header += struct.pack("<I", len(body))
    header += b".FIT"
    header += struct.pack("<H", crc16(bytes(header[:12])))
    out = bytes(header) + bytes(body)
    return out + struct.pack("<H", crc16(out))
