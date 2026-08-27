"use strict";
/* Cosmetic GPS track: a Zwift-style closed loop in empty ocean, sized so
   the loop's length equals the activity's distance.
   Faithful port of treadlab/gps_loop.py.

   Each record's position comes from the distance stream, so speed changes,
   laps and pauses stay consistent: faster seconds cover more of the loop,
   and the final record arrives exactly back at the start. */

export const ANCHOR_LAT = -12.1;  // open Coral Sea, near Zwift's Watopia spot
export const ANCHOR_LON = 166.0;

/* location key -> [lat, lon]; both are verified-empty open ocean */
export const LOCATIONS = {
  watopia: [ANCHOR_LAT, ANCHOR_LON],
  // Point Nemo, the oceanic pole of inaccessibility (~2,700 km from any
  // land; the "spacecraft cemetery").
  nemo: [-48.876, -123.393],
};

const N = 2048; // curve sampling resolution

/** Organic loop shape: unit radius plus two gentle harmonics. Amplitudes
    stay small so curvature is low everywhere -- sharper lobes made Strava's
    track smoothing dent the pace trace at the pinch points. */
function blob(theta) {
  return 1.0 + 0.11 * Math.sin(2 * theta) + 0.06 * Math.sin(3 * theta + 1.1);
}

function polyline() {
  const pts = [];
  for (let i = 0; i <= N; i++) {
    const th = 2 * Math.PI * i / N;
    const r = blob(th);
    pts.push([r * Math.cos(th), r * Math.sin(th)]);
  }
  const cum = [0.0];
  for (let i = 0; i + 1 < pts.length; i++) {
    cum.push(cum[cum.length - 1] + Math.hypot(pts[i + 1][0] - pts[i][0],
                                              pts[i + 1][1] - pts[i][1]));
  }
  return { pts, cum };
}

/**
 * Set lat/lon (degrees) on each record along one closed loop whose length
 * equals the final distance. Records need monotonic `dist` in metres; a
 * missing dist reuses the previous position. Returns how many were placed.
 */
export function addOceanLoop(records, lat0 = ANCHOR_LAT, lon0 = ANCHOR_LON) {
  let total = 0.0;
  for (const r of records) {
    if (r.dist != null) total = Math.max(total, Number(r.dist));
  }
  if (total <= 0) return 0;

  const { pts, cum } = polyline();
  const perim = cum[cum.length - 1];
  const scale = total / perim; // metres per curve unit
  const mPerDegLat = 111320.0;
  const mPerDegLon = 111320.0 * Math.cos(lat0 * Math.PI / 180);

  let n = 0, last = 0.0, j = 0;
  for (const r of records) {
    const d = r.dist == null ? last : Number(r.dist);
    last = d;
    const s = (d / total) * perim;
    while (j + 1 < cum.length - 1 && cum[j + 1] < s) j += 1;
    const seg = cum[j + 1] - cum[j];
    const f = seg > 0 ? (s - cum[j]) / seg : 0.0;
    const x = (pts[j][0] + f * (pts[j + 1][0] - pts[j][0])) * scale;
    const y = (pts[j][1] + f * (pts[j + 1][1] - pts[j][1])) * scale;
    r.lat = lat0 + y / mPerDegLat;
    r.lon = lon0 + x / mPerDegLon;
    n += 1;
  }
  return n;
}
