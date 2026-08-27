"use strict";
/* Minimal dependency-free FIT parser (read-only) for the HR-merge feature.
   Faithful port of treadlab/fit_reader_lite.py: normal and
   compressed-timestamp record headers, little- and big-endian definitions,
   developer fields (skipped), unknown messages (skipped) and chained FIT
   containers. Tolerant by design -- a bad CRC or truncated tail yields
   whatever records were readable plus a warning; only a file with no FIT
   header at all throws. */

import { BASE_TYPES, FIT_EPOCH_OFFSET, crc16, semicirclesToDeg } from "./fitbase.js";

/* base-type number (low 5 bits) -> canonical base-type byte */
const BY_NUM = {};
for (const key of Object.keys(BASE_TYPES)) {
  const b = Number(key);
  BY_NUM[b & 0x1F] = b;
}

const TS_INVALID = 0xFFFFFFFF;

const MANUFACTURERS = {
  1: "Garmin", 23: "Suunto", 32: "Wahoo", 63: "COROS",
  123: "Polar", 265: "Strava", 255: "development",
};

/* Python raises IndexError past the end of the buffer; a JS typed array
   quietly yields undefined. Throwing keeps the two engines' tolerance for
   truncated files identical. */
function at(data, i) {
  if (i < 0 || i >= data.length) throw new RangeError("read past end of file");
  return data[i];
}

/** Decode one field's raw bytes -> scalar or null (arrays/strings -> null). */
function decodeField(dv, off, size, base, bigEndian) {
  const canonical = BY_NUM[base & 0x1F];
  if (canonical === undefined || canonical === 0x07) return null;
  const t = BASE_TYPES[canonical];
  if (size !== t.size) return null; // array (or malformed size): not a scalar
  const le = !bigEndian;
  let v;
  switch (canonical) {
    case 0x00: case 0x02: case 0x0A: case 0x0D: v = dv.getUint8(off); break;
    case 0x01: v = dv.getInt8(off); break;
    case 0x83: v = dv.getInt16(off, le); break;
    case 0x84: case 0x8B: v = dv.getUint16(off, le); break;
    case 0x85: v = dv.getInt32(off, le); break;
    case 0x86: case 0x8C: v = dv.getUint32(off, le); break;
    case 0x88: v = dv.getFloat32(off, le); break;
    case 0x89: v = dv.getFloat64(off, le); break;
    case 0x8E: v = Number(dv.getBigInt64(off, le)); break;
    case 0x8F: case 0x90: v = Number(dv.getBigUint64(off, le)); break;
    default: return null;
  }
  if (v === t.invalid) return null;
  return v;
}

class Def {
  constructor(globalNum, bigEndian, fields) {
    this.globalNum = globalNum;
    this.bigEndian = bigEndian;
    this.fields = fields; // [[defNum|null, size, baseType|null], ...]
    this.size = fields.reduce((s, f) => s + f[1], 0);
  }
}

/**
 * Parse FIT bytes (Uint8Array) -> {records, fileId, session, laps,
 * warnings, blocks}. Each record: {t: unix seconds, hr, cad, temp, speed,
 * dist, alt, lat, lon} with absent keys omitted.
 */
export function parseFit(data) {
  if (data.length < 12) throw new Error("not a FIT file (too short)");
  const out = {
    records: [], fileId: {}, session: {}, laps: [], warnings: [], blocks: 0,
  };
  const dv = new DataView(data.buffer, data.byteOffset, data.byteLength);
  let pos = 0;
  while (pos !== null && pos + 12 <= data.length && isFitTag(data, pos + 8)) {
    pos = parseBlock(data, dv, pos, out);
    out.blocks += 1;
  }
  if (out.blocks === 0) throw new Error("not a FIT file (missing '.FIT' header tag)");
  return out;
}

function isFitTag(data, i) {
  return data[i] === 0x2E && data[i + 1] === 0x46
      && data[i + 2] === 0x49 && data[i + 3] === 0x54;
}

/* Parse one header+body+crc block. Returns the offset after the block, or
   null if it was truncated (a warning is recorded). */
function parseBlock(data, dv, start, out) {
  const hsize = data[start];
  if (hsize < 12) {
    out.warnings.push(`bad header size ${hsize}`);
    return null;
  }
  const dataSize = dv.getUint32(start + 4, true);
  let bodyEnd = start + hsize + dataSize;
  if (bodyEnd > data.length) {
    out.warnings.push("file shorter than declared data size");
    bodyEnd = data.length;
  } else if (bodyEnd + 2 <= data.length) {
    const stored = dv.getUint16(bodyEnd, true);
    if (crc16(data.subarray(start, bodyEnd)) !== stored) {
      out.warnings.push("file CRC mismatch (parsed anyway)");
    }
  }

  const defs = new Map();
  let lastTs = null; // raw FIT seconds, for compressed-timestamp headers
  let pos = start + hsize;
  try {
    while (pos < bodyEnd) {
      const hdr = at(data, pos);
      pos += 1;
      if (hdr & 0x80) { // compressed-timestamp data message
        const local = (hdr >> 5) & 0x3;
        const offset5 = hdr & 0x1F;
        const d = defs.get(local);
        if (d === undefined) throw new Error("data message before definition");
        if (lastTs !== null) {
          const delta = (offset5 - (lastTs & 0x1F)) & 0x1F;
          lastTs = lastTs + delta;
        }
        pos = readData(data, dv, pos, d, lastTs, out);
      } else if (hdr & 0x40) { // definition message
        const hasDev = Boolean(hdr & 0x20);
        const local = hdr & 0xF;
        const bigEndian = at(data, pos + 1) === 1;
        const globalNum = dv.getUint16(pos + 2, !bigEndian);
        const n = at(data, pos + 4);
        pos += 5;
        const fields = [];
        for (let i = 0; i < n; i++) {
          fields.push([at(data, pos), at(data, pos + 1), at(data, pos + 2)]);
          pos += 3;
        }
        if (hasDev) { // developer fields: keep sizes, skip values later
          const nDev = at(data, pos);
          pos += 1;
          for (let i = 0; i < nDev; i++) {
            fields.push([null, at(data, pos + 1), null]);
            pos += 3;
          }
        }
        defs.set(local, new Def(globalNum, bigEndian, fields));
      } else { // normal data message
        const local = hdr & 0xF;
        const d = defs.get(local);
        if (d === undefined) throw new Error("data message before definition");
        const newTs = peekTs(data, dv, pos, d);
        if (newTs !== null) lastTs = newTs;
        pos = readData(data, dv, pos, d, lastTs, out);
      }
    }
  } catch (exc) {
    out.warnings.push(`stopped early at offset ${pos}: ${exc.message}`);
    return null;
  }
  return bodyEnd + 2 <= data.length ? bodyEnd + 2 : null;
}

/** Return the raw value of field 253 (timestamp) in this data message. */
function peekTs(data, dv, pos, d) {
  let off = 0;
  for (const [defNum, size, base] of d.fields) {
    if (defNum === 253) {
      const v = decodeField(dv, pos + off, size, base, d.bigEndian);
      return v !== TS_INVALID ? v : null;
    }
    off += size;
  }
  return null;
}

/** Consume one data message; harvest fields for the globals we care about. */
function readData(data, dv, pos, d, rawTs, out) {
  if (d.globalNum === 0 || d.globalNum === 18 || d.globalNum === 19 || d.globalNum === 20) {
    const vals = new Map();
    let off = 0;
    for (const [defNum, size, base] of d.fields) {
      if (defNum !== null && base !== null) {
        const v = decodeField(dv, pos + off, size, base, d.bigEndian);
        if (v !== null) vals.set(defNum, v);
      }
      off += size;
    }
    if (d.globalNum === 20) harvestRecord(vals, rawTs, out);
    else if (d.globalNum === 0 && !Object.keys(out.fileId).length) out.fileId = harvestFileId(vals);
    else if (d.globalNum === 18 && !Object.keys(out.session).length) out.session = harvestSession(vals);
    else if (d.globalNum === 19 && out.laps.length < 500) {
      out.laps.push({
        start: vals.has(2) ? vals.get(2) + FIT_EPOCH_OFFSET : null,
        elapsed_s: vals.has(7) ? vals.get(7) / 1000.0 : null,
        dist_m: vals.has(9) ? vals.get(9) / 100.0 : null,
        avg_hr: vals.get(15) ?? null,
      });
    }
  }
  return pos + d.size;
}

function harvestRecord(vals, rawTs, out) {
  const ts = vals.has(253) ? vals.get(253) : rawTs;
  if (ts === null || ts === undefined) return;
  const rec = { t: ts + FIT_EPOCH_OFFSET };
  const hr = vals.get(3);
  if (hr) rec.hr = hr; // 0 bpm is a sensor dropout, not a heart rate
  const cad = vals.get(4);
  if (cad !== undefined) {
    const frac = vals.get(53);
    rec.cad = cad + (frac !== undefined ? frac / 128.0 : 0.0);
  }
  const temp = vals.get(13);
  if (temp !== undefined) rec.temp = temp; // sint8 degC; 0 is valid
  const speed = vals.has(73) ? vals.get(73) : vals.get(6);
  if (speed !== undefined) rec.speed = speed / 1000.0;
  const dist = vals.get(5);
  if (dist !== undefined) rec.dist = dist / 100.0;
  const alt = vals.has(78) ? vals.get(78) : vals.get(2);
  if (alt !== undefined) rec.alt = alt / 5.0 - 500.0;
  const lat = vals.get(0);
  if (lat !== undefined) rec.lat = semicirclesToDeg(lat);
  const lon = vals.get(1);
  if (lon !== undefined) rec.lon = semicirclesToDeg(lon);
  out.records.push(rec);
}

function harvestFileId(vals) {
  const man = vals.get(1) ?? null;
  return {
    manufacturer: man,
    manufacturer_name: MANUFACTURERS[man] ?? `manufacturer #${man}`,
    product: vals.get(2) ?? null,
    time_created: vals.has(4) ? vals.get(4) + FIT_EPOCH_OFFSET : null,
  };
}

function harvestSession(vals) {
  return {
    sport: vals.get(5) ?? null,
    sub_sport: vals.get(6) ?? null,
    start_time: vals.has(2) ? vals.get(2) + FIT_EPOCH_OFFSET : null,
    elapsed_s: vals.has(7) ? vals.get(7) / 1000.0 : null,
    avg_hr: vals.get(16) ?? null,
    max_hr: vals.get(17) ?? null,
    ascent_m: vals.get(22) ?? null,
    descent_m: vals.get(23) ?? null,
    avg_temp_c: vals.get(57) ?? null,
    max_temp_c: vals.get(58) ?? null,
  };
}
