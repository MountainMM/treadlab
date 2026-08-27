"use strict";
/* Map a recorded heart-rate stream onto a simulated activity's records.
   Faithful port of treadlab/merge.py.

   Records carry a relative time `t` in seconds; HR samples are
   [t_rel, hr, cad] or [t_rel, hr, cad, temp_c] rows relative to their own
   file's first record (older 3-element rows are still accepted).

   Alignment: the record at activity-time t takes the HR sample nearest to
   sample-time (t + offset). offset > 0 means the HR stream started earlier
   than the simulated activity. Cadence and temperature ride along with
   whichever sample supplied the heart rate. */

import { pyRound } from "./fitbase.js";

const MATCH_TOLERANCE_S = 5.0;  // a sample this close counts as simultaneous
const CARRY_FORWARD_S = 10.0;   // otherwise hold the previous sample this long

export function mergeHr(records, samples, {
  offset = 0.0, copyCadence = true, copyTemp = true,
} = {}) {
  const cleaned = samples
    .filter((s) => s && s[1] && Number(s[1]) > 0 && Number(s[1]) < 255)
    .sort((a, b) => Number(a[0]) - Number(b[0]));
  const times = cleaned.map((s) => Number(s[0]));
  let matched = 0;
  for (const rec of records) {
    const want = Number(rec.t) + Number(offset);
    const hit = nearest(cleaned, times, want);
    if (hit === null) continue;
    const sT = Number(hit[0]);
    const sHr = Number(hit[1]);
    const gap = Math.abs(sT - want);
    if (gap <= MATCH_TOLERANCE_S || (want - sT >= 0 && want - sT <= CARRY_FORWARD_S)) {
      rec.hr = pyRound(sHr);
      if (copyCadence && hit.length > 2 && hit[2] != null) rec.cad = Number(hit[2]);
      if (copyTemp && hit.length > 3 && hit[3] != null) rec.temp = Number(hit[3]);
      matched += 1;
    }
  }
  return { matched, total: records.length, hr_points: cleaned.length };
}

function nearest(samples, times, want) {
  if (!samples.length) return null;
  const i = lowerBound(times, want);
  let best = null;
  for (const j of [i - 1, i]) {
    if (j >= 0 && j < samples.length) {
      if (best === null || Math.abs(times[j] - want) < Math.abs(Number(best[0]) - want)) {
        best = samples[j];
      }
    }
  }
  return best;
}

/** bisect_left */
function lowerBound(arr, x) {
  let lo = 0, hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < x) lo = mid + 1; else hi = mid;
  }
  return lo;
}
