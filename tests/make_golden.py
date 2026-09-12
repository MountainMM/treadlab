"""Generate golden FIT files from the Python engine for the JS port to match.

    python-embed\\python.exe tests\\make_golden.py

Writes treadlab/static/_test/golden/<name>.json (the exact request) and
<name>.fit (the bytes Python produced). The browser test suite feeds each
request to the JavaScript engine and compares byte for byte.
"""

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from treadlab import server as srv
from treadlab.fit_reader_lite import parse_fit
from treadlab.fit_writer import write_activity_fit

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "treadlab", "static", "_test", "golden")
START = 1_753_600_000


def ramp(n, kmh, grade_pct, hr=None, cad=None, temp=None):
    """n+1 one-second records at a constant speed and grade."""
    v = kmh / 3.6
    recs = []
    for t in range(n + 1):
        r = {"t": t, "speed": v, "dist": v * t, "alt": v * t * grade_pct / 100.0}
        if hr is not None:
            r["hr"] = hr + (t % 7)
        if cad is not None:
            r["cad"] = cad + (t % 3)
        if temp is not None:
            r["temp"] = temp + t // 500
        recs.append(r)
    return recs


def intervals(n):
    recs = []
    dist = alt = 0.0
    for t in range(n + 1):
        fast = (t // 60) % 2 == 1
        v = (14.0 if fast else 8.0) / 3.6
        recs.append({"t": t, "speed": v, "dist": dist, "alt": alt,
                     "hr": 120 + (40 if fast else 0), "cad": 160 + t % 5,
                     "temp": 20 + t // 200})
        dist += v
        alt += v * 0.02
    return recs


BASE = {"start_epoch": START, "sport": "running",
        "sub_sport": "virtual_activity", "start_alt": 100.0}

SCENARIOS = {
    # Cam's real case: 10 km at 10 km/h on 10 % -> 1000 m of climb
    "cam_10k": dict(BASE, records=ramp(3600, 10.0, 10.0),
                    laps=[{"start": 0, "end": 3600}], gps=False),
    # flat ground must stay perfectly flat through the terrain texture
    "flat": dict(BASE, records=ramp(1200, 9.0, 0.0), laps=[], gps=False),
    # downhill, negative grade + negative temperatures
    "decline": dict(BASE, records=ramp(900, 11.0, -3.0, temp=-5), laps=[], gps=False),
    # every optional stream present, multiple laps, calories
    "intervals": dict(BASE, sub_sport="treadmill", records=intervals(600),
                      calories=333,
                      laps=[{"start": 0, "end": 200}, {"start": 200, "end": 400},
                            {"start": 400, "end": 600}], gps=False),
    # the HR/cadence/temperature merge path
    "merge": dict(BASE, records=ramp(1200, 10.8, 3.0),
                  laps=[{"start": 0, "end": 600}, {"start": 600, "end": 1200}],
                  gps=False,
                  hr={"samples": [[t, 140 + (t % 20), 172.5, 24] for t in range(1150)],
                      "offset": 0, "copy_cadence": True, "copy_temp": True}),
    # merge with an offset and cadence/temperature switched off
    "merge_offset": dict(BASE, records=ramp(600, 9.5, 2.0), laps=[], gps=False,
                         hr={"samples": [[t + 0.4, 130 + (t % 11), 170, 21]
                                         for t in range(900)],
                             "offset": 30, "copy_cadence": False,
                             "copy_temp": False}),
    # both map-loop venues
    "gps_watopia": dict(BASE, records=ramp(1800, 12.0, 4.0),
                        laps=[{"start": 0, "end": 1800}], gps="watopia"),
    "gps_nemo": dict(BASE, records=ramp(1800, 12.0, 4.0),
                     laps=[{"start": 0, "end": 1800}], gps="nemo"),
    # The real ride case: 11.3 km in 30:10, flat, constant averages noted
    # from the bike console (75 W, 80 rpm), HR merged from a watch file that
    # records heart rate and nothing else.
    "ride_flat_power": dict(
        BASE, sport="cycling", sub_sport="virtual_activity", gps=False,
        records=[{"t": t, "speed": 11300.0 / 1810, "dist": 11300.0 / 1810 * t,
                  "alt": 0.0, "power": 75, "cad": 80} for t in range(1811)],
        laps=[{"start": 0, "end": 1810}],
        hr={"samples": [[t, 128 + (t % 23), None, None] for t in range(1810)],
            "offset": 0, "copy_cadence": False, "copy_temp": False}),
    # indoor ride sub-sport, power only, no cadence
    "ride_indoor": dict(
        BASE, sport="cycling", sub_sport="indoor_cycling", gps=False, laps=[],
        records=[{"t": t, "speed": 6.5, "dist": 6.5 * t, "alt": 0.0,
                  "power": 90 + (t % 40)} for t in range(900)]),
    # values engineered to land exactly on .5 after fixed-point scaling, so
    # Python's round-half-to-even and JS's round-half-up would disagree
    "rounding_edges": dict(BASE, start_alt=0.0, gps=False, laps=[], records=[
        {"t": 0, "speed": 1.0005, "dist": 0.005, "alt": -499.9,
         "hr": 0.5, "cad": 1.5, "temp": 2.5},
        {"t": 1, "speed": 2.0015, "dist": 0.015, "alt": -499.7,
         "hr": 2.5, "cad": 3.5, "temp": -2.5},
        {"t": 2, "speed": 3.0025, "dist": 0.025, "alt": -499.5,
         "hr": 4.5, "cad": 5.5, "temp": 4.5},
        {"t": 3, "speed": 4.0035, "dist": 0.035, "alt": -499.3,
         "hr": 6.5, "cad": 7.5, "temp": -6.5},
    ]),
}


def main():
    os.makedirs(OUT, exist_ok=True)
    index = []
    for name, req in SCENARIOS.items():
        fit, fname, stats = srv._export_fit(json.loads(json.dumps(req)))
        with open(os.path.join(OUT, name + ".fit"), "wb") as fh:
            fh.write(fit)
        with open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"request": req, "name": fname, "merge": stats,
                       "bytes": len(fit)}, fh)
        index.append(name)
        print("  %-16s %6d bytes  %s" % (name, len(fit), fname))

    # a raw-writer case that bypasses the export pipeline entirely
    recs = [{"time": START + t, "speed": 2.5, "dist": 2.5 * t,
             "alt": 100 + 0.05 * t, "hr": 150, "cad": 85.5, "temp": 19,
             "power": 300, "lat": -12.1 + t * 1e-5, "lon": 166.0 + t * 1e-5}
            for t in range(300)]
    raw = write_activity_fit(recs, sport="running", sub_sport="treadmill",
                             calories=120, laps=[{"start": START,
                                                  "end": START + 299}])
    with open(os.path.join(OUT, "raw_writer.fit"), "wb") as fh:
        fh.write(raw)
    with open(os.path.join(OUT, "raw_writer.json"), "w", encoding="utf-8") as fh:
        json.dump({"records": recs, "sport": "running",
                   "sub_sport": "treadmill", "calories": 120,
                   "laps": [{"start": START, "end": START + 299}],
                   "bytes": len(raw)}, fh)
    index.append("raw_writer")
    print("  %-16s %6d bytes  (direct writer call)" % ("raw_writer", len(raw)))

    # parser golden: a real device file, plus the streams Python reads out
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sample = os.path.join(os.path.dirname(root), "FitLab", "samples",
                          "sample_ride.fit")
    if os.path.isfile(sample):
        with open(sample, "rb") as fh:
            raw_bytes = fh.read()
        shutil.copyfile(sample, os.path.join(OUT, "real_sample.fit"))
        p = parse_fit(raw_bytes)
        cols = {k: [r.get(k) for r in p["records"]]
                for k in ("t", "hr", "cad", "dist", "alt", "lat", "lon", "speed", "temp")}
        with open(os.path.join(OUT, "real_sample.json"), "w", encoding="utf-8") as fh:
            json.dump({"n": len(p["records"]), "warnings": p["warnings"],
                       "file_id": p["file_id"], "session": p["session"],
                       "n_laps": len(p["laps"]), "cols": cols}, fh)
        print("  %-16s %6d bytes  (%d records parsed by Python)"
              % ("real_sample", len(raw_bytes), len(p["records"])))
        index.append("real_sample")

    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh)
    print("\n%d golden files -> %s" % (len(index), OUT))


if __name__ == "__main__":
    main()
