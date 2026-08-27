"use strict";
/* The engine's public surface -- what server.py's two endpoints used to do,
   now running in the browser. Faithful port of the _export_fit and
   _parse_fit_response functions in treadlab/server.py, in the same order,
   so the file bytes are identical either way. */

import { pyRound } from "./fitbase.js";
import { parseFit } from "./fit_reader.js";
import { writeActivityFit } from "./fit_writer.js";
import { ANCHOR_LAT, ANCHOR_LON, LOCATIONS, addOceanLoop } from "./gps_loop.js";
import { mergeHr } from "./merge.js";
import { addTexture } from "./terrain.js";

export { parseFit, writeActivityFit, LOCATIONS };

const MAX_RECORDS = 2 * 86400;  // two days at 1 Hz is absurd for a treadmill
const MAX_HR_SAMPLES = 30000;   // longer HR files get strided for the UI

const SPORT_LABELS = {
  0: "generic", 1: "running", 2: "cycling", 4: "fitness equipment",
  5: "swimming", 11: "walking", 17: "hiking",
};
const SUB_SPORT_LABELS = { 1: "treadmill", 58: "virtual activity" };

const round1 = (x) => pyRound(x * 10) / 10;
const pad2 = (n) => String(n).padStart(2, "0");

/**
 * req: {start_epoch, start_alt, sport, sub_sport, records:[{t,speed,dist,alt,hr?,cad?,temp?}],
 *       laps:[{start,end}], gps: false|"watopia"|"nemo", calories,
 *       hr: {samples, offset, copy_cadence, copy_temp}}
 * Returns {fit: Uint8Array, name, mergeStats}.
 */
export function buildExport(req) {
  const recordsIn = req.records || [];
  if (!recordsIn.length) throw new Error("no records to export");
  if (recordsIn.length > MAX_RECORDS) throw new Error(`too many records (${recordsIn.length})`);
  const start = Number(req.start_epoch || 0);
  if (!(start > 0)) throw new Error("missing start_epoch");
  const startAlt = Number(req.start_alt ?? 100.0);

  const records = recordsIn.map((r) => {
    const rec = {
      t: Number(r.t),
      time: start + Number(r.t),
      speed: r.speed != null ? Number(r.speed) : null,
      dist: r.dist != null ? Number(r.dist) : null,
      alt: r.alt != null ? startAlt + Number(r.alt) : null,
    };
    if (r.hr != null) rec.hr = Number(r.hr);
    if (r.cad != null) rec.cad = Number(r.cad);
    if (r.temp != null) rec.temp = Number(r.temp);
    return rec;
  });
  records.sort((a, b) => a.t - b.t);

  addTexture(records); // anti-alias the 0.2 m altitude grid (see terrain.js)

  const gps = req.gps; // false/absent, true (legacy), or a location key
  if (gps) {
    const [lat0, lon0] = LOCATIONS[String(gps).toLowerCase()] || [ANCHOR_LAT, ANCHOR_LON];
    addOceanLoop(records, lat0, lon0);
  }

  let mergeStats = null;
  const hr = req.hr;
  if (hr && hr.samples && hr.samples.length) {
    mergeStats = mergeHr(records, hr.samples, {
      offset: Number(hr.offset || 0.0),
      copyCadence: Boolean(hr.copy_cadence ?? true),
      copyTemp: Boolean(hr.copy_temp ?? true),
    });
  }
  for (const rec of records) delete rec.t;

  const laps = (req.laps || []).map((lp) => ({
    start: start + Number(lp.start), end: start + Number(lp.end),
  }));
  const fit = writeActivityFit(records, {
    sport: String(req.sport ?? "running"),
    subSport: String(req.sub_sport ?? "virtual_activity"),
    calories: req.calories ? Number(req.calories) : null,
    laps,
  });
  const d = new Date(start * 1000);
  const name = `treadlab_${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
             + `_${pad2(d.getHours())}${pad2(d.getMinutes())}${pad2(d.getSeconds())}.fit`;
  return { fit, name, mergeStats };
}

/** Summarise an uploaded watch FIT for the HR-merge panel. */
export function describeFit(bytes) {
  let parsed;
  try {
    parsed = parseFit(bytes);
  } catch (exc) {
    return { ok: false, error: exc.message };
  }
  const recs = parsed.records;
  if (!recs.length) {
    return { ok: false, error: "no data records found in that file",
             warnings: parsed.warnings };
  }
  const hrRecs = recs.filter((r) => r.hr != null);
  const t0 = recs[0].t;
  const t1 = recs[recs.length - 1].t;
  let samples = hrRecs.map((r) => [
    round1(r.t - t0), r.hr, r.cad != null ? round1(r.cad) : null, r.temp ?? null,
  ]);
  if (samples.length > MAX_HR_SAMPLES) {
    const stride = Math.ceil(samples.length / MAX_HR_SAMPLES);
    samples = samples.filter((_, i) => i % stride === 0);
  }
  const hrs = samples.map((s) => s[1]);
  const temps = samples.map((s) => s[3]).filter((v) => v != null);
  const sess = parsed.session;
  const fid = parsed.fileId;
  const dists = recs.filter((r) => r.dist != null).map((r) => r.dist);
  const label = [SPORT_LABELS[sess.sport], SUB_SPORT_LABELS[sess.sub_sport]]
    .filter(Boolean).join(" / ");
  return {
    ok: true,
    n_records: recs.length,
    start_epoch: t0,
    duration_s: t1 - t0,
    distance_m: dists.length ? dists[dists.length - 1] - dists[0] : null,
    has_hr: samples.length > 0,
    has_cad: samples.some((s) => s[2] != null),
    has_gps: recs.some((r) => r.lat != null),
    has_temp: temps.length > 0,
    avg_temp: temps.length ? round1(temps.reduce((a, b) => a + b, 0) / temps.length) : null,
    avg_hr: hrs.length ? pyRound(hrs.reduce((a, b) => a + b, 0) / hrs.length) : null,
    max_hr: hrs.length ? Math.max(...hrs) : null,
    device: fid.manufacturer_name ?? null,
    sport: label,
    start_pos: (() => {
      const r = recs.find((x) => x.lat != null && x.lon != null);
      return r ? [round5(r.lat), round5(r.lon)] : null;
    })(),
    samples,
    warnings: parsed.warnings,
  };
}

const round5 = (x) => pyRound(x * 1e5) / 1e5;
