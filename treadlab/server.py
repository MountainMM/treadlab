"""TreadLab's local HTTP server -- Python standard library only.

Serves the single-page UI from static/ and three JSON/binary endpoints:

  GET  /api/health     liveness + version
  POST /api/parse-fit  raw FIT bytes -> HR/cadence samples + file summary
  POST /api/export     activity JSON -> downloadable .FIT (optionally with
                       the heart-rate stream merged in server-side)
"""

import datetime
import json
import os
import struct
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import APP_NAME, __version__
from .fit_reader_lite import parse_fit
from .fit_writer import write_activity_fit
from .gps_loop import ANCHOR_LAT, ANCHOR_LON, LOCATIONS, add_ocean_loop
from .merge import merge_hr
from .terrain import add_texture

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY = 80 * 1024 * 1024
MAX_RECORDS = 2 * 86400  # two days at 1 Hz is already absurd for a treadmill
MAX_HR_SAMPLES = 30000   # sent to the browser; longer files get strided

_MIME = {".html": "text/html; charset=utf-8", ".css": "text/css",
         ".js": "text/javascript", ".svg": "image/svg+xml",
         ".png": "image/png", ".ico": "image/x-icon",
         ".json": "application/json", ".webmanifest": "application/manifest+json",
         ".fit": "application/octet-stream"}

_SPORT_NAMES = {0: "generic", 1: "running", 2: "cycling", 4: "fitness equipment",
                5: "swimming", 11: "walking", 17: "hiking"}
_SUB_SPORT_NAMES = {1: "treadmill", 58: "virtual activity"}


def _parse_fit_response(data):
    parsed = parse_fit(data)
    recs = parsed["records"]
    hr_recs = [r for r in recs if r.get("hr") is not None]
    if not recs:
        return {"ok": False, "error": "no data records found in that file",
                "warnings": parsed["warnings"]}
    t0 = recs[0]["t"]
    t1 = recs[-1]["t"]
    samples = [[round(r["t"] - t0, 1), r["hr"],
                round(r["cad"], 1) if r.get("cad") is not None else None,
                r.get("temp")]
               for r in hr_recs]
    if len(samples) > MAX_HR_SAMPLES:
        stride = -(-len(samples) // MAX_HR_SAMPLES)
        samples = samples[::stride]
    hrs = [s[1] for s in samples]
    temps = [s[3] for s in samples if s[3] is not None]
    sess = parsed["session"]
    fid = parsed["file_id"]
    dists = [r["dist"] for r in recs if r.get("dist") is not None]
    return {
        "ok": True,
        "n_records": len(recs),
        "start_epoch": t0,
        "duration_s": t1 - t0,
        "distance_m": dists[-1] - dists[0] if dists else None,
        "has_hr": bool(samples),
        "has_cad": any(s[2] is not None for s in samples),
        "has_gps": any(r.get("lat") is not None for r in recs),
        "start_pos": next(([round(r["lat"], 5), round(r["lon"], 5)]
                           for r in recs if r.get("lat") is not None
                           and r.get("lon") is not None), None),
        "has_temp": bool(temps),
        "avg_temp": round(sum(temps) / len(temps), 1) if temps else None,
        "avg_hr": round(sum(hrs) / len(hrs)) if hrs else None,
        "max_hr": max(hrs) if hrs else None,
        "device": fid.get("manufacturer_name"),
        "sport": " / ".join(
            x for x in (_SPORT_NAMES.get(sess.get("sport")),
                        _SUB_SPORT_NAMES.get(sess.get("sub_sport"))) if x),
        "samples": samples,
        "warnings": parsed["warnings"],
    }


def _export_fit(req):
    records_in = req.get("records") or []
    if not records_in:
        raise ValueError("no records to export")
    if len(records_in) > MAX_RECORDS:
        raise ValueError("too many records (%d)" % len(records_in))
    start = float(req.get("start_epoch") or 0)
    if start <= 0:
        raise ValueError("missing start_epoch")
    start_alt = float(req.get("start_alt", 100.0))

    records = []
    for r in records_in:
        rec = {"t": float(r["t"]),
               "time": start + float(r["t"]),
               "speed": float(r["speed"]) if r.get("speed") is not None else None,
               "dist": float(r["dist"]) if r.get("dist") is not None else None,
               "alt": start_alt + float(r["alt"]) if r.get("alt") is not None else None}
        if r.get("hr") is not None:
            rec["hr"] = float(r["hr"])
        if r.get("cad") is not None:
            rec["cad"] = float(r["cad"])
        if r.get("temp") is not None:
            rec["temp"] = float(r["temp"])
        records.append(rec)
    records.sort(key=lambda r: r["t"])

    add_texture(records)  # anti-alias the 0.2 m altitude grid (see terrain.py)

    gps = req.get("gps")  # false/absent, true (legacy), or a location key
    if gps:
        lat0, lon0 = LOCATIONS.get(str(gps).lower(), (ANCHOR_LAT, ANCHOR_LON))
        add_ocean_loop(records, lat0, lon0)

    merge_stats = None
    hr = req.get("hr")
    if hr and hr.get("samples"):
        merge_stats = merge_hr(records, hr["samples"],
                               offset=float(hr.get("offset", 0.0)),
                               copy_cadence=bool(hr.get("copy_cadence", True)),
                               copy_temp=bool(hr.get("copy_temp", True)))
    for rec in records:
        rec.pop("t", None)

    laps = [{"start": start + float(lp["start"]), "end": start + float(lp["end"])}
            for lp in (req.get("laps") or [])]
    calories = req.get("calories")
    fit = write_activity_fit(
        records,
        sport=str(req.get("sport", "running")),
        sub_sport=str(req.get("sub_sport", "virtual_activity")),
        calories=float(calories) if calories else None,
        laps=laps,
    )
    name = "treadlab_%s.fit" % datetime.datetime.fromtimestamp(start).strftime(
        "%Y-%m-%d_%H%M%S")
    return fit, name, merge_stats


class Handler(BaseHTTPRequestHandler):
    server_version = "%s/%s" % (APP_NAME, __version__)

    def log_message(self, fmt, *args):  # keep the console calm
        if "/api/" in (args[0] if args else ""):
            print("  %s" % (fmt % args))

    # -- helpers ---------------------------------------------------------
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            raise ValueError("empty request body")
        if n > MAX_BODY:
            raise ValueError("request too large")
        return self.rfile.read(n)

    def _send(self, code, payload, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, obj, code=200, extra=None):
        self._send(code, json.dumps(obj).encode("utf-8"),
                   "application/json", extra)

    # -- routes ----------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            return self._json({"ok": True, "app": APP_NAME,
                               "version": __version__})
        if path == "/":
            path = "/index.html"
        if path.startswith("/static/"):
            path = path[len("/static"):]
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        if target.is_dir():  # /_test/ -> /_test/index.html
            target = target / "index.html"
        if (not str(target).startswith(str(STATIC_DIR) + os.sep)
                and target != STATIC_DIR / "index.html") or not target.is_file():
            return self._send(404, b"not found", "text/plain")
        self._send(200, target.read_bytes(),
                   _MIME.get(target.suffix.lower(), "application/octet-stream"))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/parse-fit":
                try:
                    resp = _parse_fit_response(self._body())
                except (ValueError, struct.error) as exc:
                    resp = {"ok": False, "error": str(exc)}
                return self._json(resp)
            if path == "/api/export":
                req = json.loads(self._body().decode("utf-8"))
                fit, name, merge_stats = _export_fit(req)
                extra = {"Content-Disposition":
                         'attachment; filename="%s"' % name,
                         "X-TreadLab-File": name}
                if merge_stats:
                    extra["X-TreadLab-Merge"] = json.dumps(merge_stats)
                return self._send(200, fit, "application/octet-stream", extra)
            return self._json({"ok": False, "error": "unknown endpoint"}, 404)
        except Exception as exc:  # noqa: BLE001 -- report, don't crash the app
            return self._json({"ok": False, "error": str(exc)}, 400)


def make_server(port):
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
