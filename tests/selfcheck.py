"""TreadLab self-check suite -- run with any Python 3.8+:

    py tests\\selfcheck.py
    ..\\FitLab\\python-embed\\python.exe tests\\selfcheck.py   (adds fitdecode
                                                    cross-validation checks)

Standard library only. Exercises the FIT writer, the lite FIT reader, the
HR merge, the export pipeline and the HTTP server end-to-end.
"""

import json
import math
import os
import struct
import sys
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from treadlab.fitbase import FIT_EPOCH_OFFSET, crc16
from treadlab.fit_reader_lite import parse_fit
from treadlab.fit_writer import write_activity_fit
from treadlab.gps_loop import (ANCHOR_LAT, ANCHOR_LON, LOCATIONS,
                               add_ocean_loop)
from treadlab.merge import merge_hr
from treadlab.terrain import add_texture
from treadlab import server as srv


def hav(lat1, lon1, lat2, lon2):
    """Haversine distance in meters."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(a))

PASS = 0
FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("FAIL  %s  %s" % (label, detail))


def crc16_reference(data):
    """Independent bit-by-bit CRC-16/ARC (poly 0x8005 reflected -> 0xA001)."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


# ---------------------------------------------------------------- helpers
START = 1_753_600_000  # arbitrary 2025-ish unix time


def cam_scenario_records():
    """Cam's real case: 10.00 km at 10.0 km/h on 5.0 % -> exactly 500 m up.
    3600 one-second steps -> 3601 records, alt relative 0."""
    v = 10.0 / 3.6
    recs = []
    t = dist = alt = 0.0
    for t in range(3600):
        recs.append({"time": START + t, "speed": v, "dist": dist, "alt": alt,
                     "hr": None, "cad": None})
        dist += v
        alt += v * 0.05
    recs.append({"time": START + 3600, "speed": v, "dist": dist, "alt": alt})
    return recs


def interval_records(n=600):
    recs = []
    dist = alt = 0.0
    for t in range(n + 1):
        fast = (t // 60) % 2 == 1
        v = (14.0 if fast else 8.0) / 3.6
        recs.append({"time": START + t, "speed": v, "dist": dist, "alt": alt,
                     "hr": 120 + (40 if fast else 0), "cad": 160 + t % 5,
                     "temp": 20 + t // 200})
        dist += v
        alt += v * 0.02
    return recs


# ================================================================ 1. CRC
data = os.urandom(257) + b"123456789"
check("crc16 matches independent CRC-16/ARC", crc16(data) == crc16_reference(data))
check("crc16 known vector '123456789' == 0xBB3D", crc16(b"123456789") == 0xBB3D)

# ====================================================== 2. writer basics
fit = write_activity_fit(cam_scenario_records(), sport="running",
                         sub_sport="virtual_activity")
check("writer: header starts 14/.FIT", fit[0] == 14 and fit[8:12] == b".FIT")
declared = struct.unpack_from("<I", fit, 4)[0]
check("writer: declared size + header + crc == file size",
      14 + declared + 2 == len(fit), "%d vs %d" % (14 + declared + 2, len(fit)))
check("writer: file CRC valid", crc16(fit[:-2]) == struct.unpack("<H", fit[-2:])[0])
check("writer: header CRC valid", crc16(fit[:12]) == struct.unpack_from("<H", fit, 12)[0])

# =============================================== 3. round-trip (scenario)
parsed = parse_fit(fit)
recs = parsed["records"]
check("round-trip: 3601 records", len(recs) == 3601, str(len(recs)))
check("round-trip: no warnings", not parsed["warnings"], str(parsed["warnings"]))
check("round-trip: timestamps 1 Hz monotonic",
      all(b["t"] - a["t"] == 1 for a, b in zip(recs, recs[1:])))
check("round-trip: start time exact", recs[0]["t"] == START)
check("round-trip: distance ~10.00 km", abs(recs[-1]["dist"] - 10000) < 3,
      str(recs[-1]["dist"]))
check("round-trip: speed ~2.778 m/s everywhere",
      max(abs(r["speed"] - 10 / 3.6) for r in recs) < 0.001)
sess = parsed["session"]
check("CAM SCENARIO: session total_ascent == 500 m", sess.get("ascent_m") == 500,
      str(sess.get("ascent_m")))
check("session: sport running / sub_sport virtual (58)",
      sess.get("sport") == 1 and sess.get("sub_sport") == 58,
      "%s/%s" % (sess.get("sport"), sess.get("sub_sport")))
check("session: elapsed 3600 s", sess.get("elapsed_s") == 3600.0,
      str(sess.get("elapsed_s")))
alt_span = recs[-1]["alt"] - recs[0]["alt"]
check("round-trip: altitude span ~500 m", abs(alt_span - 500) < 1, str(alt_span))

fit_tm = write_activity_fit(cam_scenario_records(), sport="running",
                            sub_sport="treadmill")
check("sub_sport 'treadmill' encodes as 1",
      parse_fit(fit_tm)["session"].get("sub_sport") == 1)

# ========================================================== 4. laps + HR
laps_in = [{"start": START, "end": START + 200},
           {"start": START + 200, "end": START + 400},
           {"start": START + 400, "end": START + 600}]
fit2 = write_activity_fit(interval_records(600), sport="running",
                          sub_sport="treadmill", laps=laps_in, calories=333)
p2 = parse_fit(fit2)
check("laps: 3 laps come back", len(p2["laps"]) == 3, str(len(p2["laps"])))
check("laps: start times correct",
      [lp["start"] for lp in p2["laps"]] == [START, START + 200, START + 400])
iv = interval_records(600)
expect_lap_dist = [iv[e]["dist"] - iv[s]["dist"]
                   for s, e in ((0, 200), (200, 400), (400, 600))]
check("laps: per-lap distances match the record integral",
      all(abs(lp["dist_m"] - want) < 0.5
          for lp, want in zip(p2["laps"], expect_lap_dist)),
      "%s vs %s" % ([lp["dist_m"] for lp in p2["laps"]], expect_lap_dist))
check("laps: distances sum to the total",
      abs(sum(lp["dist_m"] for lp in p2["laps"]) - iv[600]["dist"]) < 1.5)
check("laps: avg HR in plausible band",
      all(115 <= lp["avg_hr"] <= 165 for lp in p2["laps"]),
      str([lp["avg_hr"] for lp in p2["laps"]]))
check("records: HR and cadence round-trip",
      p2["records"][61]["hr"] == 160 and int(p2["records"][61]["cad"]) == 160 + 61 % 5)
check("session: avg/max HR present",
      115 <= p2["session"]["avg_hr"] <= 165 and p2["session"]["max_hr"] == 160)
check("records: temperature round-trip",
      p2["records"][0]["temp"] == 20 and p2["records"][450]["temp"] == 22,
      str([p2["records"][i].get("temp") for i in (0, 450)]))
check("session: avg/max temperature (57/58)",
      p2["session"]["avg_temp_c"] == 21 and p2["session"]["max_temp_c"] == 23,
      "%s/%s" % (p2["session"].get("avg_temp_c"), p2["session"].get("max_temp_c")))

# ============================================================== 5. merge
mrecs = [{"t": t} for t in range(0, 101)]
samples = [[t + 0.4, 100 + t, 170.0] for t in range(0, 101)]
stats = merge_hr(mrecs, samples, offset=0.0)
check("merge: full coverage", stats["matched"] == 101, str(stats))
check("merge: nearest sample wins", mrecs[50]["hr"] == 150, str(mrecs[50]))
check("merge: cadence copied", mrecs[50]["cad"] == 170.0)

mrecs = [{"t": t} for t in range(0, 101)]
merge_hr(mrecs, samples, offset=0.0, copy_cadence=False)
check("merge: cadence NOT copied when off", "cad" not in mrecs[50])

mrecs = [{"t": t} for t in range(0, 101)]
stats = merge_hr(mrecs, [[0.0, 140, None], [100.0, 160, None]], offset=0.0)
check("merge: carry-forward max 10 s",
      mrecs[10].get("hr") == 140 and "hr" not in mrecs[50], str(stats))

mrecs = [{"t": t} for t in range(0, 101)]
merge_hr(mrecs, samples, offset=30.0)
check("merge: +30 s offset shifts stream", mrecs[0]["hr"] == 130, str(mrecs[0]))
check("merge: offset tail unmatched (no sample at 130.4+10)",
      "hr" not in mrecs[100] or mrecs[100]["hr"] == 200)

mrecs = [{"t": t} for t in range(0, 10)]
stats = merge_hr(mrecs, [[3.0, 0, None], [4.0, 300, None]], offset=0.0)
check("merge: bogus HR values (0 / 300 bpm) ignored", stats["matched"] == 0)

tsamples = [[t, 130, 170.0, -2] for t in range(0, 11)]
mrecs = [{"t": t} for t in range(0, 11)]
merge_hr(mrecs, tsamples)
check("merge: temperature copied (incl. negative)", mrecs[5]["temp"] == -2.0)
mrecs = [{"t": t} for t in range(0, 11)]
merge_hr(mrecs, tsamples, copy_temp=False)
check("merge: temperature NOT copied when off", "temp" not in mrecs[5])
mrecs = [{"t": t} for t in range(0, 11)]
merge_hr(mrecs, [[t, 130, 170.0] for t in range(0, 11)])
check("merge: old 3-element samples still fine (no temp key)",
      mrecs[5]["hr"] == 130 and "temp" not in mrecs[5])

# =============================================== 6. hand-crafted parsing
def block(body):
    hdr = bytearray([14, 0x10]) + struct.pack("<H", 2195)
    hdr += struct.pack("<I", len(body)) + b".FIT"
    hdr += struct.pack("<H", crc16(bytes(hdr[:12])))
    out = bytes(hdr) + body
    return out + struct.pack("<H", crc16(out))

FT = START - FIT_EPOCH_OFFSET
# compressed-timestamp layout as watches write it: a full-timestamp record
# establishes the clock, then a second definition WITHOUT field 253 is used
# by compressed-header rows whose 5-bit offset advances the clock.
body = bytearray()
body += bytes([0x40, 0, 0]) + struct.pack("<H", 20) + bytes([2])
body += bytes([253, 4, 0x86]) + bytes([3, 1, 0x02])      # local 0: ts + hr
body += bytes([0x00]) + struct.pack("<I", FT) + bytes([111])
body += bytes([0x41, 0, 0]) + struct.pack("<H", 20) + bytes([1])
body += bytes([3, 1, 0x02])                              # local 1: hr only
for i in (1, 2, 3):
    body += bytes([0x80 | (1 << 5) | ((FT + i) & 0x1F), 120 + i])
pc = parse_fit(block(bytes(body)))
check("compressed timestamps: 4 records, +1 s each",
      [r["t"] for r in pc["records"]] == [START, START + 1, START + 2, START + 3],
      str([r["t"] for r in pc["records"]]))
check("compressed timestamps: HR values kept",
      [r.get("hr") for r in pc["records"]] == [111, 121, 122, 123])

# big-endian definition
body = bytearray()
body += bytes([0x40, 0, 1]) + struct.pack(">H", 20) + bytes([2])
body += bytes([253, 4, 0x86]) + bytes([6, 2, 0x84])      # ts + speed(mm/s)
body += bytes([0x00]) + struct.pack(">I", FT) + struct.pack(">H", 2778)
pb = parse_fit(block(bytes(body)))
check("big-endian records parse", pb["records"] and
      pb["records"][0]["t"] == START and abs(pb["records"][0]["speed"] - 2.778) < 1e-9,
      str(pb["records"]))

# signed temperature (sint8): -3 parses, 0x7F sentinel -> absent
body = bytearray()
body += bytes([0x40, 0, 0]) + struct.pack("<H", 20) + bytes([2])
body += bytes([253, 4, 0x86]) + bytes([13, 1, 0x01])     # ts + temp degC
body += bytes([0x00]) + struct.pack("<I", FT) + struct.pack("<b", -3)
body += bytes([0x00]) + struct.pack("<I", FT + 1) + bytes([0x7F])
pt = parse_fit(block(bytes(body)))
check("temperature: sint8 -3 parses, invalid 0x7F absent",
      pt["records"][0].get("temp") == -3 and "temp" not in pt["records"][1],
      str(pt["records"]))

# developer fields skipped cleanly
body = bytearray()
body += bytes([0x60, 0, 0]) + struct.pack("<H", 20) + bytes([2])   # 0x60: def + dev flag
body += bytes([253, 4, 0x86]) + bytes([3, 1, 0x02])
body += bytes([1]) + bytes([0, 4, 0])                    # one 4-byte dev field
body += bytes([0x00]) + struct.pack("<I", FT) + bytes([99]) + b"\xDE\xAD\xBE\xEF"
pd = parse_fit(block(bytes(body)))
check("developer fields skipped", pd["records"] and pd["records"][0]["hr"] == 99
      and not pd["warnings"], str(pd))

# chained container + tolerance
pch = parse_fit(fit + fit2)
check("chained FIT blocks both parsed", pch["blocks"] == 2 and
      len(pch["records"]) == 3601 + 601, str((pch["blocks"], len(pch["records"]))))
ptr = parse_fit(fit[:2000])
check("truncated file -> records + warning, no crash",
      len(ptr["records"]) > 0 and ptr["warnings"], str(ptr["warnings"][:1]))
try:
    parse_fit(b"this is not a fit file at all........")
    check("garbage raises ValueError", False)
except ValueError:
    check("garbage raises ValueError", True)

# ==================================================== 7. export pipeline
export_req = {
    "start_epoch": START,
    "sport": "running", "sub_sport": "virtual_activity",
    "start_alt": 250.0, "calories": 500,
    "records": [{"t": t, "speed": 3.0, "dist": 3.0 * t, "alt": 0.09 * t}
                for t in range(0, 1201)],
    "laps": [{"start": 0, "end": 600}, {"start": 600, "end": 1200}],
    "hr": {"samples": [[t, 140 + (t % 20), 172, 24] for t in range(0, 1150)],
           "offset": 0, "copy_cadence": True, "copy_temp": True},
}
fit3, name3, mstats3 = srv._export_fit(json.loads(json.dumps(export_req)))
p3 = parse_fit(fit3)
check("export: filename pattern", name3.startswith("treadlab_") and name3.endswith(".fit"), name3)
check("export: merge stats ~1150/1201 matched",
      1140 <= mstats3["matched"] <= 1160, str(mstats3))
check("export: HR landed in records", p3["records"][100]["hr"] == 140 + 100 % 20)
check("export: cadence landed in records", int(p3["records"][100]["cad"]) == 172)
check("export: temperature landed in records", p3["records"][100]["temp"] == 24)
check("export: session avg temperature 24", p3["session"]["avg_temp_c"] == 24,
      str(p3["session"].get("avg_temp_c")))
check("export: altitude starts at start_alt",
      abs(p3["records"][0]["alt"] - 250.0) < 0.3, str(p3["records"][0]["alt"]))
check("export: ascent = 0.09*1200 = 108 m", p3["session"]["ascent_m"] == 108,
      str(p3["session"]["ascent_m"]))
check("export: 2 laps", len(p3["laps"]) == 2)
check("export: avg speed ~3 m/s",
      abs(sum(r["speed"] for r in p3["records"]) / len(p3["records"]) - 3.0) < 0.01)
check("export: no GPS unless asked", "lat" not in p3["records"][0]
      and "lat" not in p3["records"][600])

# =============================================== 7aa. cycling / power
# A ride logged from remembered averages: 11.3 km in 30:10, flat, constant
# watts and cadence, no elevation.
ride_req = {
    "start_epoch": START, "sport": "cycling", "sub_sport": "virtual_activity",
    "start_alt": 0.0, "gps": False,
    "records": [{"t": t, "speed": 11300.0 / 1810, "dist": 11300.0 / 1810 * t,
                 "alt": 0.0, "power": 75, "cad": 80} for t in range(1811)],
    "laps": [{"start": 0, "end": 1810}],
}
fit_ride, _, _ = srv._export_fit(json.loads(json.dumps(ride_req)))
p_ride = parse_fit(fit_ride)
check("cycling: sport 2 / sub_sport 58 (virtual ride)",
      p_ride["session"]["sport"] == 2 and p_ride["session"]["sub_sport"] == 58,
      "%s/%s" % (p_ride["session"].get("sport"), p_ride["session"].get("sub_sport")))
check("cycling: 11.30 km over 1810 s",
      abs(p_ride["records"][-1]["dist"] - 11300) < 1
      and p_ride["session"]["elapsed_s"] == 1810.0,
      "%.1f m / %s s" % (p_ride["records"][-1]["dist"],
                         p_ride["session"].get("elapsed_s")))
check("cycling: a flat ride reports zero ascent",
      p_ride["session"]["ascent_m"] == 0, str(p_ride["session"].get("ascent_m")))
check("cycling: cadence round-trips at 80 rpm on every record",
      all(int(r["cad"]) == 80 for r in p_ride["records"]))
fit_indoor, _, _ = srv._export_fit(json.loads(json.dumps(
    dict(ride_req, sub_sport="indoor_cycling"))))
check("cycling: sub_sport indoor_cycling == 6",
      parse_fit(fit_indoor)["session"]["sub_sport"] == 6)
fit_nopower, _, _ = srv._export_fit(json.loads(json.dumps(dict(
    ride_req,
    records=[{"t": t, "speed": 11300.0 / 1810, "dist": 11300.0 / 1810 * t,
              "alt": 0.0} for t in range(1811)]))))
p_np = parse_fit(fit_nopower)
check("cycling: leaving power/cadence blank omits both fields",
      all("cad" not in r for r in p_np["records"])
      and len(fit_nopower) < len(fit_ride) - 1811 * 2,
      "%d vs %d bytes" % (len(fit_nopower), len(fit_ride)))

# ================================================== 7a. terrain texture
flat = [{"dist": 3.0 * t, "alt": 42.0} for t in range(1001)]
add_texture(flat)
check("texture: flat stays perfectly flat",
      all(r["alt"] == 42.0 for r in flat))

climb = [{"dist": 3.0 * t, "alt": 0.09 * t} for t in range(1201)]  # 3% grade
add_texture(climb)
check("texture: endpoints pinned (net elevation exact)",
      abs(climb[0]["alt"]) < 1e-9 and abs(climb[-1]["alt"] - 108.0) < 1e-9)
check("texture: climb stays strictly monotonic",
      all(b["alt"] > a["alt"] for a, b in zip(climb, climb[1:])))
grades = [(b["alt"] - a["alt"]) / 3.0 for a, b in zip(climb, climb[1:])]
check("texture: local grade stays within ~16%% of target",
      0.024 < min(grades) and max(grades) < 0.036,
      "%.4f..%.4f" % (min(grades), max(grades)))
dev = max(abs(r["alt"] - 0.09 * i) for i, r in enumerate(climb))
check("texture: sub-meter undulation present (<=0.3 m)",
      0.02 < dev <= 0.30, "%.3f m" % dev)

lin = [{"time": START + t, "speed": 3.0, "dist": 3.0 * t,
        "alt": 250.0 + 0.09 * t} for t in range(1201)]
plain = parse_fit(write_activity_fit(lin, sport="running"))["records"]
differ = sum(1 for a, b in zip(plain, p3["records"])
             if round(a["alt"], 1) != round(b["alt"], 1))
check("texture: survives 0.2 m quantization (step pattern reshuffled)",
      differ > 120, "%d/1201 records differ" % differ)

# ======================================================== 7b. ocean loop
lrecs = [{"dist": i * 2.5} for i in range(4001)]      # 10.00 km
check("loop: positions every record", add_ocean_loop(lrecs) == 4001)
check("loop: closes on itself (<1.5 m)",
      hav(lrecs[0]["lat"], lrecs[0]["lon"], lrecs[-1]["lat"], lrecs[-1]["lon"]) < 1.5)
lap_len = sum(hav(a["lat"], a["lon"], b["lat"], b["lon"])
              for a, b in zip(lrecs, lrecs[1:]))
check("loop: polyline length == distance (within 1%)",
      abs(lap_len - 10000) < 100, "%.1f m" % lap_len)
far = max(hav(ANCHOR_LAT, ANCHOR_LON, r["lat"], r["lon"]) for r in lrecs)
check("loop: stays within 5 km of the ocean anchor", far < 5000, "%.0f m" % far)

fit_gps, _, _ = srv._export_fit(json.loads(json.dumps(dict(export_req, gps=True))))
pg = parse_fit(fit_gps)
check("gps export: every record has coordinates",
      all(r.get("lat") is not None and r.get("lon") is not None
          for r in pg["records"]))
gps_len = sum(hav(a["lat"], a["lon"], b["lat"], b["lon"])
              for a, b in zip(pg["records"], pg["records"][1:]))
check("gps export: track length matches 3.6 km distance",
      abs(gps_len - 3600) < 80, "%.1f m" % gps_len)
check("gps export: loop closes after round-trip (<3 m)",
      hav(pg["records"][0]["lat"], pg["records"][0]["lon"],
          pg["records"][-1]["lat"], pg["records"][-1]["lon"]) < 3)
check("gps export: parse-fit reports has_gps",
      srv._parse_fit_response(fit_gps)["has_gps"] is True)

# location dropdown: watopia / nemo / legacy true
check("locations: watopia + nemo defined",
      set(LOCATIONS) == {"watopia", "nemo"} and LOCATIONS["watopia"] == (ANCHOR_LAT, ANCHOR_LON))
nlat, nlon = LOCATIONS["nemo"]
nrecs = [{"dist": i * 2.5} for i in range(4001)]      # 10 km at 49 S
add_ocean_loop(nrecs, nlat, nlon)
nemo_len = sum(hav(a["lat"], a["lon"], b["lat"], b["lon"])
               for a, b in zip(nrecs, nrecs[1:]))
check("nemo loop: length right at high latitude (cos-lat scaling)",
      abs(nemo_len - 10000) < 100, "%.1f m" % nemo_len)
check("nemo loop: closes and stays near Point Nemo",
      hav(nrecs[0]["lat"], nrecs[0]["lon"], nrecs[-1]["lat"], nrecs[-1]["lon"]) < 1.5
      and max(hav(nlat, nlon, r["lat"], r["lon"]) for r in nrecs) < 5000)

fit_nemo, _, _ = srv._export_fit(json.loads(json.dumps(dict(export_req, gps="nemo"))))
sp = srv._parse_fit_response(fit_nemo)["start_pos"]
check("export gps='nemo': starts at Point Nemo",
      sp and abs(sp[0] - nlat) < 0.1 and abs(sp[1] - nlon) < 0.1, str(sp))
sp = srv._parse_fit_response(fit_gps)["start_pos"]
check("export gps=True (legacy): starts near Watopia",
      sp and abs(sp[0] - ANCHOR_LAT) < 0.1 and abs(sp[1] - ANCHOR_LON) < 0.1, str(sp))
fit_wat, _, _ = srv._export_fit(json.loads(json.dumps(dict(export_req, gps="watopia"))))
sp = srv._parse_fit_response(fit_wat)["start_pos"]
check("export gps='watopia': starts near Watopia",
      sp and abs(sp[0] - ANCHOR_LAT) < 0.1 and abs(sp[1] - ANCHOR_LON) < 0.1, str(sp))
check("no-gps export: start_pos is null",
      srv._parse_fit_response(fit3)["start_pos"] is None)

# =========================================================== 8. server E2E
httpd = srv.make_server(0)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % port

with urllib.request.urlopen(base + "/api/health", timeout=5) as r:
    health = json.loads(r.read())
check("server: /api/health ok", health.get("ok") is True and health.get("app") == "TreadLab")
with urllib.request.urlopen(base + "/", timeout=5) as r:
    page = r.read()
check("server: index.html served", b"TreadLab" in page and r.status == 200)
with urllib.request.urlopen(base + "/static/app.js", timeout=5) as r:
    check("server: app.js served", b"buildFromPlan" in r.read())
try:
    urllib.request.urlopen(base + "/static/../../run.py", timeout=5)
    check("server: path traversal blocked", False)
except Exception:
    check("server: path traversal blocked", True)

req = urllib.request.Request(base + "/api/parse-fit", data=fit2, method="POST")
with urllib.request.urlopen(req, timeout=10) as r:
    pj = json.loads(r.read())
check("server: parse-fit ok + HR summary",
      pj["ok"] and pj["has_hr"] and pj["has_cad"] and pj["n_records"] == 601
      and pj["start_epoch"] == START, str({k: pj[k] for k in ("ok", "n_records")}))
check("server: parse-fit samples are relative", pj["samples"][0][0] == 0.0)
check("server: parse-fit reports temperature (avg 21 degC)",
      pj["has_temp"] and pj["avg_temp"] == 21.0 and pj["samples"][0][3] == 20,
      "%s/%s" % (pj.get("has_temp"), pj.get("avg_temp")))
check("server: no-GPS file reports has_gps false", pj["has_gps"] is False)

req = urllib.request.Request(
    base + "/api/export", data=json.dumps(export_req).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=10) as r:
    body3 = r.read()
    cd = r.headers.get("Content-Disposition") or ""
    merged_hdr = r.headers.get("X-TreadLab-Merge")
check("server: export returns valid FIT",
      body3[8:12] == b".FIT" and crc16(body3[:-2]) == struct.unpack("<H", body3[-2:])[0])
check("server: attachment + merge headers", "attachment" in cd and merged_hdr)

req = urllib.request.Request(base + "/api/parse-fit", data=b"garbage" * 10, method="POST")
with urllib.request.urlopen(req, timeout=5) as r:
    check("server: bad FIT -> ok:false JSON (no 500)",
          json.loads(r.read()).get("ok") is False and r.status == 200)
httpd.shutdown()

# ========================================== 9. optional fitdecode checks
try:
    import fitdecode
    HAVE_FITDECODE = True
except ImportError:
    HAVE_FITDECODE = False
    print("  --  fitdecode not available: skipping cross-validation "
          "(run via ..\\FitLab\\python-embed\\python.exe for full checks)")

if HAVE_FITDECODE:
    def fd_read(data):
        import io
        recs, sess = [], {}
        with fitdecode.FitReader(io.BytesIO(data)) as fr:  # strict CRC mode
            for fr_frame in fr:
                if isinstance(fr_frame, fitdecode.FitDataMessage):
                    if fr_frame.global_mesg_num == 20:
                        recs.append({f.name: f.value for f in fr_frame.fields})
                    elif fr_frame.global_mesg_num == 18 and not sess:
                        sess = {f.name: f.value for f in fr_frame.fields}
        return recs, sess

    fd_recs, fd_sess = fd_read(fit3)
    check("fitdecode: strict-CRC decode, 1201 records", len(fd_recs) == 1201)
    check("fitdecode: total_ascent 108", fd_sess.get("total_ascent") == 108,
          str(fd_sess.get("total_ascent")))
    check("fitdecode: sub_sport virtual", "virtual" in str(fd_sess.get("sub_sport")),
          str(fd_sess.get("sub_sport")))
    check("fitdecode: HR matches lite reader",
          fd_recs[100].get("heart_rate") == p3["records"][100]["hr"])
    check("fitdecode: record temperature 24 degC",
          fd_recs[100].get("temperature") == 24, str(fd_recs[100].get("temperature")))
    check("fitdecode: session avg_temperature 24",
          fd_sess.get("avg_temperature") == 24, str(fd_sess.get("avg_temperature")))

    rd_recs, rd_sess = fd_read(fit_ride)
    check("fitdecode: ride power on every record (75 W)",
          len(rd_recs) == 1811 and all(r.get("power") == 75 for r in rd_recs),
          str(sorted({r.get("power") for r in rd_recs})[:5]))
    check("fitdecode: ride decodes as cycling",
          "cycling" in str(rd_sess.get("sport")), str(rd_sess.get("sport")))
    check("fitdecode: session avg/max cadence 80",
          rd_sess.get("avg_cadence") == 80 and rd_sess.get("max_cadence") == 80)

    gd_recs, gd_sess = fd_read(fit_gps)
    check("fitdecode: gps export strict-decodes with positions",
          len(gd_recs) == 1201 and gd_recs[500].get("position_lat") is not None)
    check("fitdecode: session start position set",
          gd_sess.get("start_position_lat") is not None
          and gd_sess.get("start_position_long") is not None)

    sample = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "..", "FitLab", "samples", "sample_ride.fit")
    if os.path.isfile(sample):
        with open(sample, "rb") as fh:
            raw = fh.read()
        mine = parse_fit(raw)
        theirs, _ = fd_read(raw)
        t_mine = [r["t"] for r in mine["records"]]
        t_theirs = [ts.timestamp() for ts in
                    (r.get("timestamp") for r in theirs) if ts is not None]
        check("real sample: record counts agree (lite %d vs fitdecode %d)"
              % (len(t_mine), len(t_theirs)), len(t_mine) == len(t_theirs))
        check("real sample: first/last timestamps agree",
              t_mine[0] == t_theirs[0] and t_mine[-1] == t_theirs[-1],
              "%s vs %s" % (t_mine[:1], t_theirs[:1]))
        hr_mine = [r.get("hr") for r in mine["records"]]
        hr_theirs = [r.get("heart_rate") for r in theirs]
        agree = sum(1 for a, b in zip(hr_mine, hr_theirs)
                    if a == b or (a is None and not b))
        check("real sample: HR streams agree (%d/%d)" % (agree, len(hr_mine)),
              agree == len(hr_mine))
    else:
        print("  --  FitLab sample_ride.fit not found; skipped real-file check")

print()
print("%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
