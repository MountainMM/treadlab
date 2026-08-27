"""Minimal dependency-free FIT parser (read-only) for the HR-merge feature.

Extracts the record stream (timestamp, heart rate, cadence, plus speed /
distance / altitude for the info panel), the file_id and the first session
summary from a watch or app FIT file. Understands normal and
compressed-timestamp record headers, little- and big-endian definitions,
developer fields (skipped), unknown messages (skipped) and chained FIT
containers. Tolerant by design: a bad CRC or truncated tail yields whatever
records were readable plus a warning, never an exception; only a file with
no FIT header at all raises ValueError.
"""

import struct

from .fitbase import BASE_TYPES, FIT_EPOCH_OFFSET, crc16, semicircles_to_deg

# base-type number (low 5 bits) -> canonical base-type byte
_BY_NUM = {b & 0x1F: b for b in BASE_TYPES}

_TS_INVALID = 0xFFFFFFFF

_MANUFACTURERS = {1: "Garmin", 23: "Suunto", 32: "Wahoo", 63: "COROS",
                  123: "Polar", 265: "Strava", 255: "development"}


def _decode_field(buf, base, big_endian):
    """Decode one field's raw bytes -> scalar value or None.
    Arrays and strings return None (we only need scalars)."""
    canonical = _BY_NUM.get(base & 0x1F)
    if canonical is None or canonical == 0x07:  # unknown or string
        return None
    _, elem, invalid, fmt = BASE_TYPES[canonical]
    if len(buf) != elem:  # array (or malformed size): not a scalar
        return None
    v = struct.unpack((">" if big_endian else "<") + fmt, buf)[0]
    if v == invalid:
        return None
    return v


class _Def:
    __slots__ = ("global_num", "big_endian", "fields", "size")

    def __init__(self, global_num, big_endian, fields):
        self.global_num = global_num
        self.big_endian = big_endian
        self.fields = fields  # [(def_num, size, base_type_byte)]
        self.size = sum(f[1] for f in fields)


def parse_fit(data):
    """Parse FIT bytes -> {'records': [...], 'file_id': {}, 'session': {},
    'warnings': [...], 'blocks': n}. Each record: {'t': unix_s, 'hr': bpm,
    'cad': rpm, 'speed': m/s, 'dist': m, 'alt': m} (absent keys omitted)."""
    if len(data) < 12:
        raise ValueError("not a FIT file (too short)")
    out = {"records": [], "file_id": {}, "session": {}, "laps": [],
           "warnings": [], "blocks": 0}
    pos = 0
    while pos + 12 <= len(data) and data[pos + 8:pos + 12] == b".FIT":
        pos = _parse_block(data, pos, out)
        out["blocks"] += 1
        if pos is None:
            break
    if out["blocks"] == 0:
        raise ValueError("not a FIT file (missing '.FIT' header tag)")
    return out


def _parse_block(data, start, out):
    """Parse one header+body+crc block. Returns offset after the block,
    or None if the block was truncated (a warning is recorded)."""
    hsize = data[start]
    if hsize < 12:
        out["warnings"].append("bad header size %d" % hsize)
        return None
    data_size = struct.unpack_from("<I", data, start + 4)[0]
    body_end = start + hsize + data_size
    if body_end > len(data):
        out["warnings"].append("file shorter than declared data size")
        body_end = len(data)
        crc_end = body_end
    else:
        crc_end = body_end + 2
        if crc_end <= len(data):
            stored = struct.unpack_from("<H", data, body_end)[0]
            if crc16(data[start:body_end]) != stored:
                out["warnings"].append("file CRC mismatch (parsed anyway)")

    defs = {}
    last_ts = None  # raw FIT seconds, for compressed-timestamp headers
    pos = start + hsize
    try:
        while pos < body_end:
            hdr = data[pos]
            pos += 1
            if hdr & 0x80:  # compressed-timestamp data message
                local = (hdr >> 5) & 0x3
                offset5 = hdr & 0x1F
                d = defs.get(local)
                if d is None:
                    raise ValueError("data message before definition")
                if last_ts is not None:
                    delta = (offset5 - (last_ts & 0x1F)) & 0x1F
                    last_ts = last_ts + delta
                pos = _read_data(data, pos, d, last_ts, out)
            elif hdr & 0x40:  # definition message
                has_dev = bool(hdr & 0x20)
                local = hdr & 0xF
                big_endian = data[pos + 1] == 1
                global_num = struct.unpack_from(
                    ">H" if big_endian else "<H", data, pos + 2)[0]
                n = data[pos + 4]
                pos += 5
                fields = []
                for _ in range(n):
                    fields.append((data[pos], data[pos + 1], data[pos + 2]))
                    pos += 3
                if has_dev:  # developer fields: keep sizes, skip values later
                    n_dev = data[pos]
                    pos += 1
                    for _ in range(n_dev):
                        fields.append((None, data[pos + 1], None))
                        pos += 3
                defs[local] = _Def(global_num, big_endian, fields)
            else:  # normal data message
                local = hdr & 0xF
                d = defs.get(local)
                if d is None:
                    raise ValueError("data message before definition")
                new_ts = _peek_ts(data, pos, d)
                if new_ts is not None:
                    last_ts = new_ts
                pos = _read_data(data, pos, d, last_ts, out)
    except (IndexError, ValueError, struct.error) as exc:
        out["warnings"].append("stopped early at offset %d: %s" % (pos, exc))
        return None
    return body_end + 2 if body_end + 2 <= len(data) else None


def _peek_ts(data, pos, d):
    """Return the raw value of field 253 (timestamp) in this data message."""
    off = 0
    for def_num, size, base in d.fields:
        if def_num == 253:
            v = _decode_field(data[pos + off:pos + off + size], base,
                              d.big_endian)
            return v if v != _TS_INVALID else None
        off += size
    return None


def _read_data(data, pos, d, raw_ts, out):
    """Consume one data message; harvest fields for globals we care about."""
    if d.global_num in (0, 18, 19, 20):
        vals = {}
        off = 0
        for def_num, size, base in d.fields:
            if def_num is not None and base is not None:
                v = _decode_field(data[pos + off:pos + off + size], base,
                                  d.big_endian)
                if v is not None:
                    vals[def_num] = v
            off += size
        if d.global_num == 20:
            _harvest_record(vals, raw_ts, out)
        elif d.global_num == 0 and not out["file_id"]:
            out["file_id"] = _harvest_file_id(vals)
        elif d.global_num == 18 and not out["session"]:
            out["session"] = _harvest_session(vals)
        elif d.global_num == 19 and len(out["laps"]) < 500:
            out["laps"].append({
                "start": (vals[2] + FIT_EPOCH_OFFSET) if 2 in vals else None,
                "elapsed_s": (vals[7] / 1000.0) if 7 in vals else None,
                "dist_m": (vals[9] / 100.0) if 9 in vals else None,
                "avg_hr": vals.get(15),
            })
    return pos + d.size


def _harvest_record(vals, raw_ts, out):
    ts = vals.get(253, raw_ts)
    if ts is None:
        return
    rec = {"t": ts + FIT_EPOCH_OFFSET}
    hr = vals.get(3)
    if hr:  # 0 bpm is a sensor dropout, not a heart rate
        rec["hr"] = hr
    cad = vals.get(4)
    if cad is not None:
        frac = vals.get(53)
        rec["cad"] = cad + (frac / 128.0 if frac is not None else 0.0)
    temp = vals.get(13)
    if temp is not None:  # sint8 degC; 0 is a valid temperature
        rec["temp"] = temp
    lat = vals.get(0)
    if lat is not None:
        rec["lat"] = semicircles_to_deg(lat)
    lon = vals.get(1)
    if lon is not None:
        rec["lon"] = semicircles_to_deg(lon)
    speed = vals.get(73, vals.get(6))
    if speed is not None:
        rec["speed"] = speed / 1000.0
    dist = vals.get(5)
    if dist is not None:
        rec["dist"] = dist / 100.0
    alt = vals.get(78, vals.get(2))
    if alt is not None:
        rec["alt"] = alt / 5.0 - 500.0
    out["records"].append(rec)


def _harvest_file_id(vals):
    man = vals.get(1)
    return {
        "manufacturer": man,
        "manufacturer_name": _MANUFACTURERS.get(man, "manufacturer #%s" % man),
        "product": vals.get(2),
        "time_created": (vals[4] + FIT_EPOCH_OFFSET) if 4 in vals else None,
    }


def _harvest_session(vals):
    return {
        "sport": vals.get(5),
        "sub_sport": vals.get(6),
        "start_time": (vals[2] + FIT_EPOCH_OFFSET) if 2 in vals else None,
        "elapsed_s": (vals[7] / 1000.0) if 7 in vals else None,
        "avg_hr": vals.get(16),
        "max_hr": vals.get(17),
        "ascent_m": vals.get(22),
        "descent_m": vals.get(23),
        "avg_temp_c": vals.get(57),
        "max_temp_c": vals.get(58),
    }
