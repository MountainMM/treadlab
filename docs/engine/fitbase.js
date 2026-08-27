"use strict";
/* Shared low-level FIT constants and helpers.
   Faithful port of treadlab/fitbase.py -- the Python and JS engines must
   produce byte-identical files, so behaviour is mirrored exactly, quirks
   included (see pyRound below). */

export const FIT_EPOCH_OFFSET = 631065600;

const CRC_TABLE = [
  0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
  0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
];

/** Garmin FIT CRC-16 (nibble table algorithm). */
export function crc16(bytes, crc = 0) {
  for (const byte of bytes) {
    let tmp = CRC_TABLE[crc & 0xF];
    crc = (crc >> 4) & 0x0FFF;
    crc = crc ^ tmp ^ CRC_TABLE[byte & 0xF];
    tmp = CRC_TABLE[crc & 0xF];
    crc = (crc >> 4) & 0x0FFF;
    crc = crc ^ tmp ^ CRC_TABLE[(byte >> 4) & 0xF];
  }
  return crc;
}

/* Python's round() is banker's rounding (half-to-even): round(2.5) == 2,
   round(0.5) == 0. JavaScript's Math.round() rounds half up, so a value
   landing exactly on .5 -- which the fixed-point FIT encodings hit often --
   would encode one unit apart from the Python engine. This reproduces
   Python, and is why the two engines agree byte-for-byte. */
export function pyRound(x) {
  const f = Math.floor(x);
  const diff = x - f;
  if (diff > 0.5) return f + 1;
  if (diff < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}

/* base type byte -> {name, size, invalid sentinel, signed} */
export const BASE_TYPES = {
  0x00: { name: "enum", size: 1, invalid: 0xFF, signed: false },
  0x01: { name: "sint8", size: 1, invalid: 0x7F, signed: true },
  0x02: { name: "uint8", size: 1, invalid: 0xFF, signed: false },
  0x83: { name: "sint16", size: 2, invalid: 0x7FFF, signed: true },
  0x84: { name: "uint16", size: 2, invalid: 0xFFFF, signed: false },
  0x85: { name: "sint32", size: 4, invalid: 0x7FFFFFFF, signed: true },
  0x86: { name: "uint32", size: 4, invalid: 0xFFFFFFFF, signed: false },
  0x07: { name: "string", size: 1, invalid: 0x00, signed: false },
  0x88: { name: "float32", size: 4, invalid: 0xFFFFFFFF, float: true },
  0x89: { name: "float64", size: 8, invalid: 0xFFFFFFFFFFFFFFFF, float: true },
  0x0A: { name: "uint8z", size: 1, invalid: 0x00, signed: false },
  0x8B: { name: "uint16z", size: 2, invalid: 0x0000, signed: false },
  0x8C: { name: "uint32z", size: 4, invalid: 0x00000000, signed: false },
  0x0D: { name: "byte", size: 1, invalid: 0xFF, signed: false },
  0x8E: { name: "sint64", size: 8, invalid: 0x7FFFFFFFFFFFFFFF, signed: true },
  0x8F: { name: "uint64", size: 8, invalid: 0xFFFFFFFFFFFFFFFF, signed: false },
  0x90: { name: "uint64z", size: 8, invalid: 0x0000000000000000, signed: false },
};

export function semicirclesToDeg(semi) {
  return semi * (180.0 / 2 ** 31);
}

export function degToSemicircles(deg) {
  return pyRound(deg * 2 ** 31 / 180.0);
}

/** Growable little-endian byte buffer (the FIT files we write are all LE). */
export class Sink {
  constructor() { this.b = []; }
  u8(v) { this.b.push(v & 0xFF); }
  u16(v) { this.b.push(v & 0xFF, (v >>> 8) & 0xFF); }
  u32(v) {
    this.b.push(v & 0xFF, (v >>> 8) & 0xFF, (v >>> 16) & 0xFF, (v >>> 24) & 0xFF);
  }
  raw(arr) { for (const x of arr) this.b.push(x & 0xFF); }
  get length() { return this.b.length; }
  bytes() { return Uint8Array.from(this.b); }
}

/* Two's complement masking makes signed values pack correctly at every
   width, so one helper covers the whole integer set the writer uses. */
export function packValue(sink, baseType, value) {
  const t = BASE_TYPES[baseType];
  const v = (value === null || value === undefined) ? t.invalid : value;
  if (t.size === 1) sink.u8(v);
  else if (t.size === 2) sink.u16(v);
  else if (t.size === 4) sink.u32(v);
  else { // 64-bit: split into two 32-bit halves
    const big = BigInt(Math.trunc(Number(v)));
    sink.u32(Number(big & 0xFFFFFFFFn));
    sink.u32(Number((big >> 32n) & 0xFFFFFFFFn));
  }
}
