"use strict";
/* Minimal FIT activity encoder (little-endian, protocol 1.0).
   Faithful port of treadlab/fit_writer.py -- same message set, same field
   order, same rounding, so both engines emit byte-identical files. */

import {
  BASE_TYPES, FIT_EPOCH_OFFSET, Sink, crc16, degToSemicircles, packValue, pyRound,
} from "./fitbase.js";

const GLOBAL_FILE_ID = 0;
const GLOBAL_SESSION = 18;
const GLOBAL_LAP = 19;
const GLOBAL_RECORD = 20;
const GLOBAL_EVENT = 21;
const GLOBAL_ACTIVITY = 34;

export const SPORT_NAMES = {
  generic: 0, running: 1, cycling: 2, transition: 3,
  fitness_equipment: 4, swimming: 5, walking: 11, hiking: 17,
};

export const SUB_SPORT_NAMES = {
  generic: 0, treadmill: 1, street: 2, trail: 3, track: 4,
  indoor_cycling: 6, virtual_activity: 58,
};

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

function fitTs(unixS) {
  return pyRound(unixS) - FIT_EPOCH_OFFSET;
}

/** A fixed message layout: emits its definition and packs data records. */
class Msg {
  constructor(local, globalNum, fields) {
    this.local = local;
    this.globalNum = globalNum;
    this.fields = fields; // [[fieldDefNum, baseTypeByte], ...]
  }

  definition(sink) {
    sink.raw([0x40 | this.local, 0x00, 0x00]); // header, reserved, little-endian
    sink.u16(this.globalNum);
    sink.u8(this.fields.length);
    for (const [defNum, base] of this.fields) {
      sink.raw([defNum, BASE_TYPES[base].size, base]);
    }
  }

  /** values: Map/object of fieldDefNum -> int; missing fields get the sentinel. */
  data(sink, values) {
    sink.u8(this.local);
    for (const [defNum, base] of this.fields) {
      packValue(sink, base, values.get(defNum));
    }
  }
}

/* record columns: model key -> [fieldDefNum, baseType, encoder] */
const RECORD_COLUMNS = [
  ["time", 253, 0x86, fitTs],
  ["lat", 0, 0x85, degToSemicircles],
  ["lon", 1, 0x85, degToSemicircles],
  ["alt", 2, 0x84, (m) => clamp(pyRound((m + 500.0) * 5), 0, 0xFFFE)],
  ["hr", 3, 0x02, (v) => clamp(pyRound(v), 0, 254)],
  ["cad", 4, 0x02, (v) => clamp(pyRound(v), 0, 254)],
  ["dist", 5, 0x86, (m) => pyRound(m * 100)],
  ["speed", 6, 0x84, (ms) => clamp(pyRound(ms * 1000), 0, 0xFFFE)],
  ["power", 7, 0x84, (w) => clamp(pyRound(w), 0, 0xFFFE)],
  ["temp", 13, 0x01, (c) => clamp(pyRound(c), -127, 126)],
];

const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;

/* Build per-lap value maps. laps: [{start, end}] in unix seconds; when
   empty the whole activity is one lap. Stats come from the records inside
   each lap's window. */
function lapRows(laps, records, t0, t1) {
  let src = (laps && laps.length) ? laps.slice() : [{ start: t0, end: t1 }];
  src.sort((a, b) => a.start - b.start);
  const rows = [];
  src.forEach((lp, i) => {
    const s = clamp(lp.start, t0, t1);
    const e = Math.max(s, Math.min(t1, lp.end));
    const rs = records.filter((r) => r.time >= s && r.time <= e);
    const hrs = rs.filter((r) => r.hr != null).map((r) => r.hr);
    const dl = rs.filter((r) => r.dist != null).map((r) => r.dist);
    const ms = pyRound((e - s) * 1000);
    rows.push(new Map([
      [253, fitTs(e)], [254, i], [2, fitTs(s)], [7, ms], [8, ms],
      [9, dl.length ? pyRound((dl[dl.length - 1] - dl[0]) * 100) : 0],
      [0, 9], [1, 1],
      [15, hrs.length ? pyRound(mean(hrs)) : null],
      [16, hrs.length ? pyRound(Math.max(...hrs)) : null],
    ]));
  });
  return rows;
}

/**
 * records: array of objects with unix `time` (required) and optionally
 * lat/lon (deg), alt (m), hr (bpm), cad (rpm), dist (m), speed (m/s),
 * power (W), temp (C). laps: optional [{start, end}] in unix seconds.
 * Returns a Uint8Array holding the complete FIT file.
 */
export function writeActivityFit(records, {
  sport = 0, subSport = 0, manufacturer = 255, product = 0,
  serial = 0x1F2E3D4C, calories = null, laps = null, utcOffsetS = 0,
} = {}) {
  records = records.filter((r) => r.time != null).slice();
  if (!records.length) throw new Error("no timestamped records to write");
  records.sort((a, b) => a.time - b.time);
  if (typeof sport === "string") sport = SPORT_NAMES[sport.toLowerCase().trim()] ?? 0;
  if (typeof subSport === "string") subSport = SUB_SPORT_NAMES[subSport.toLowerCase().trim()] ?? 0;

  const present = RECORD_COLUMNS.filter(
    (c) => c[0] === "time" || records.some((r) => r[c[0]] != null));

  const fileId = new Msg(0, GLOBAL_FILE_ID,
    [[0, 0x00], [1, 0x84], [2, 0x84], [3, 0x8C], [4, 0x86]]);
  const event = new Msg(1, GLOBAL_EVENT,
    [[253, 0x86], [0, 0x00], [1, 0x00], [4, 0x02]]);
  const record = new Msg(2, GLOBAL_RECORD, present.map(([, num, base]) => [num, base]));
  const lap = new Msg(3, GLOBAL_LAP, [
    [253, 0x86], [254, 0x84], [2, 0x86], [7, 0x86], [8, 0x86], [9, 0x86],
    [0, 0x00], [1, 0x00], [15, 0x02], [16, 0x02],
  ]);
  const session = new Msg(4, GLOBAL_SESSION, [
    [253, 0x86], [254, 0x84], [2, 0x86], [3, 0x85], [4, 0x85], [5, 0x00],
    [6, 0x00], [7, 0x86], [8, 0x86], [9, 0x86], [11, 0x84], [14, 0x84],
    [15, 0x84], [16, 0x02], [17, 0x02], [18, 0x02], [19, 0x02],
    [22, 0x84], [23, 0x84], [25, 0x84], [26, 0x84], [57, 0x01], [58, 0x01],
    [0, 0x00], [1, 0x00],
  ]);
  const activity = new Msg(5, GLOBAL_ACTIVITY, [
    [253, 0x86], [0, 0x86], [1, 0x84], [2, 0x00], [3, 0x00], [4, 0x00], [5, 0x86],
  ]);

  const t0 = records[0].time;
  const t1 = records[records.length - 1].time;
  const elapsedMs = pyRound((t1 - t0) * 1000);

  const series = (key) => records.filter((r) => r[key] != null).map((r) => r[key]);
  const dists = series("dist");
  const totalDistM = dists.length ? dists[dists.length - 1] : 0.0;
  const totalDistCm = pyRound(totalDistM * 100);
  const hrs = series("hr");
  const cads = series("cad");
  const temps = series("temp");
  const speeds = series("speed");
  const alts = series("alt");
  let ascent = 0.0, descent = 0.0;
  for (let i = 1; i < alts.length; i++) {
    const d = alts[i] - alts[i - 1];
    if (d > 0) ascent += d; else descent -= d;
  }
  const lats = records.filter((r) => r.lat != null).map((r) => r.lat);
  const lons = records.filter((r) => r.lon != null).map((r) => r.lon);

  let avgSpeedMm;
  if (totalDistM > 0 && elapsedMs > 0) avgSpeedMm = pyRound(totalDistM / (elapsedMs / 1000.0) * 1000);
  else if (speeds.length) avgSpeedMm = pyRound(mean(speeds) * 1000);
  else avgSpeedMm = null;

  const temp8 = (v) => clamp(pyRound(v), -127, 126);

  const body = new Sink();
  fileId.definition(body);
  fileId.data(body, new Map([
    [0, 4], [1, manufacturer], [2, product], [3, serial], [4, fitTs(t0)]]));
  event.definition(body);
  event.data(body, new Map([[253, fitTs(t0)], [0, 0], [1, 0], [4, 0]])); // timer start
  record.definition(body);
  for (const r of records) {
    const values = new Map();
    for (const [key, num, , enc] of present) {
      const v = r[key];
      if (v != null) values.set(num, enc(v));
    }
    record.data(body, values);
  }
  event.data(body, new Map([[253, fitTs(t1)], [0, 0], [1, 4], [4, 0]])); // stop_all

  const rows = lapRows(laps, records, t0, t1);
  lap.definition(body);
  for (const row of rows) lap.data(body, row);

  session.definition(body);
  session.data(body, new Map([
    [253, fitTs(t1)], [254, 0], [2, fitTs(t0)],
    [7, elapsedMs], [8, elapsedMs], [9, totalDistCm],
    [0, 8], [1, 1],
    [3, lats.length ? degToSemicircles(lats[0]) : null],
    [4, lons.length ? degToSemicircles(lons[0]) : null],
    [5, sport], [6, subSport],
    [11, calories ? pyRound(calories) : null],
    [14, avgSpeedMm],
    [15, speeds.length ? pyRound(Math.max(...speeds) * 1000) : null],
    [16, hrs.length ? pyRound(mean(hrs)) : null],
    [17, hrs.length ? pyRound(Math.max(...hrs)) : null],
    [18, cads.length ? pyRound(mean(cads)) : null],
    [19, cads.length ? pyRound(Math.max(...cads)) : null],
    [22, pyRound(ascent)], [23, pyRound(descent)],
    [25, 0], [26, rows.length],
    [57, temps.length ? temp8(mean(temps)) : null],
    [58, temps.length ? temp8(Math.max(...temps)) : null],
  ]));
  activity.definition(body);
  // field 5 is local_timestamp: timestamp + offset. Equal values would
  // claim a zero offset, which is what this fix exists to stop.
  activity.data(body, new Map([
    [253, fitTs(t1)], [0, elapsedMs], [1, 1], [2, 0],
    [3, 26], [4, 1], [5, fitTs(t1 + utcOffsetS)]]));

  const bodyBytes = body.bytes();
  const header = new Sink();
  header.raw([14, 0x10]);
  header.u16(2195); // profile version
  header.u32(bodyBytes.length);
  header.raw([0x2E, 0x46, 0x49, 0x54]); // ".FIT"
  header.u16(crc16(header.bytes().subarray(0, 12)));

  const out = new Uint8Array(header.length + bodyBytes.length + 2);
  out.set(header.bytes(), 0);
  out.set(bodyBytes, header.length);
  const crc = crc16(out.subarray(0, out.length - 2));
  out[out.length - 2] = crc & 0xFF;
  out[out.length - 1] = (crc >>> 8) & 0xFF;
  return out;
}
