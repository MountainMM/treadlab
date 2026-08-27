"use strict";
/* Sub-metre terrain texture for exported altitude streams.
   Faithful port of treadlab/terrain.py.

   A perfectly linear synthetic climb collides with FIT's 0.2 m altitude
   quantization: the encoded stream becomes a periodic staircase whose beat
   pattern Strava's grade smoothing renders as a zig-zag GAP trace. Real
   barometric recordings never show this, because real terrain has organic
   sub-metre variation that swamps the staircase.

   addTexture() layers a deterministic, grade-proportional undulation on
   top: zero on flat ground, capped at 0.30 m, slope budget small enough
   that climbs stay strictly monotonic and total ascent is preserved, and
   endpoints blended to zero so net elevation is untouched. */

const W1 = 181.0, W2 = 47.0;  // texture wavelengths, metres
const K = 2.2;                // metres of amplitude per unit of |grade|
const CAP = 0.30;             // amplitude ceiling, metres

/** Mutates records' `alt` in place (needs `alt` + `dist`). Returns count. */
export function addTexture(records) {
  const pts = records.filter((r) => r.alt != null && r.dist != null);
  if (pts.length < 3) return 0;
  const totalD = pts[pts.length - 1].dist - pts[0].dist;
  if (totalD <= 0) return 0;

  const raw = [];
  for (let j = 0; j < pts.length; j++) {
    const prev = pts[Math.max(0, j - 1)];
    const next = pts[Math.min(pts.length - 1, j + 1)];
    const dd = next.dist - prev.dist;
    const g = dd > 0 ? Math.abs((next.alt - prev.alt) / dd) : 0.0;
    const amp = Math.min(CAP, K * g);
    const d = pts[j].dist;
    raw.push(amp * (0.62 * Math.sin(2 * Math.PI * d / W1)
                    + 0.38 * Math.sin(2 * Math.PI * d / W2 + 2.03)));
  }

  const t0 = raw[0], t1 = raw[raw.length - 1];
  const d0 = pts[0].dist;
  for (let j = 0; j < pts.length; j++) {
    const f = (pts[j].dist - d0) / totalD;
    pts[j].alt += raw[j] - (t0 * (1 - f) + t1 * f);
  }
  return pts.length;
}
