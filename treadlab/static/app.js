"use strict";
/* TreadLab UI. Internal units: speed m/s, distance m, altitude m relative
   to 0 (the export adds the configurable start altitude), time = integer
   seconds from activity start. The UI shows km/h, km, %, min/km.

   The FIT engine runs here in the browser (see engine/), so the app needs
   no server at all: TreadLab.bat merely serves these files, and the same
   folder installs as an offline web app on a phone. */

import { buildExport, describeFit } from "./engine/index.js";

const VERSION = "0.5.0";  // displayed version; keep treadlab/__init__.py in step

const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));

/* ---------------------------------------------------------------- utils */
const pad2 = n => String(n).padStart(2, "0");

function fmtDur(s) {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  return h ? `${h}:${pad2(m)}:${pad2(ss)}` : `${m}:${pad2(ss)}`;
}
function fmtPace(kmh) {
  if (!kmh || kmh <= 0.1) return "—";
  const spk = 3600 / kmh;
  return `${Math.floor(spk / 60)}:${pad2(Math.round(spk % 60))}/km`;
}
function parseTimeLen(str) {          // "10" or "7.5" = minutes, "10:30" = mm:ss
  str = String(str).trim();
  if (!str) return 0;
  if (str.includes(":")) {
    const p = str.split(":").map(Number);
    if (p.some(isNaN)) return 0;
    return p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1];
  }
  const mins = parseFloat(str);
  return isNaN(mins) ? 0 : mins * 60;
}
function toLocalInput(epoch) {
  const d = new Date(epoch * 1000);
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}` +
         `T${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}
function fromLocalInput(v) {
  const t = new Date(v).getTime();
  return isFinite(t) ? t / 1000 : null;
}
function fmtClock(epoch) {
  const d = new Date(epoch * 1000);
  return d.toLocaleDateString() + " " + d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
}

/* ---------------------------------------------------------------- state */
const state = {
  plan: [],
  planBuild: null,          // {records, laps, totals} derived from plan
  activity: null,           // {source, records, laps, totals}
  hr: null,                 // /api/parse-fit response (+ .file name)
  settings: { sport: "running/virtual_activity", startAlt: 100, gpsLoc: "watopia" },
};

const live = {
  running: false, startedWall: 0, accum: 0, nextT: 0,
  speed: 9.0, incline: 1.0, dist: 0, alt: 0, ascent: 0,
  recs: [], lapMarks: [], timer: null,
  hrBpm: null, hrAt: 0, bleDevice: null,
};

/* ----------------------------------------------------------------- plan */
/* A segment is described by two independent choices:
   mode  - which pair of {distance, time, speed} you type ("distTime" derives
           speed; "time"/"dist" derive the other length from speed)
   hill  - whether you type the grade ("pct") or the climb in metres ("m")
   The remaining values are solved by segSolve() and shown read-only. */
const MAX_GRADE = 15;  // beyond this, flag the derived grade as unlikely

function defaultPlan() {
  return [
    normSeg({ mode: "time", len: "10:00", speed: 9.0, incline: 1.0 }),
    normSeg({ mode: "time", len: "20:00", speed: 10.5, incline: 5.0 }),
    normSeg({ mode: "time", len: "5:00", speed: 8.5, incline: 0.5 }),
  ];
}
function normSeg(s) {
  s = s || {};
  return {
    mode: ["time", "dist", "distTime"].includes(s.mode) ? s.mode : "time",
    len: s.len != null ? String(s.len) : "5:00",
    timeLen: s.timeLen != null ? String(s.timeLen) : "30:00",
    speed: Number(s.speed) || 10,
    hill: s.hill === "m" ? "m" : "pct",
    incline: Number(s.incline) || 0,
    climb: Number(s.climb) || 0,
    // Optional, and blank by default. Kept as strings so "" means "don't
    // record this at all" -- distinct from a real 0.
    power: s.power != null ? String(s.power) : "",
    cad: s.cad != null ? String(s.cad) : "",
  };
}

const optNum = (v) => (v === "" || v == null ? null : Number(v));

/* Solve one segment -> {dur (whole s), v (m/s), dist (m), incline (%),
   climb (m), kmh}. Everything derives from the integer duration so the
   displayed numbers and the exported 1 Hz records can never disagree. */
function segSolve(seg) {
  let dur = 0, v = 0;
  if (seg.mode === "distTime") {
    const km = parseFloat(seg.len), t = parseTimeLen(seg.timeLen);
    if (km > 0 && t > 0) {
      dur = Math.max(1, Math.round(t));
      v = km * 1000 / dur;          // honour both typed values exactly
    }
  } else if (seg.mode === "dist") {
    const km = parseFloat(seg.len), kmh = Number(seg.speed);
    if (km > 0 && kmh > 0) {
      dur = Math.max(1, Math.round(km * 3600 / kmh));
      v = kmh / 3.6;
    }
  } else {
    const t = parseTimeLen(seg.len), kmh = Number(seg.speed);
    if (t > 0 && kmh > 0) {
      dur = Math.max(1, Math.round(t));
      v = kmh / 3.6;
    }
  }
  const dist = v * dur;
  let incline, climb;
  if (seg.hill === "m") {
    climb = Number(seg.climb) || 0;
    incline = dist > 0 ? climb / dist * 100 : 0;
  } else {
    incline = Number(seg.incline) || 0;
    climb = dist * incline / 100;
  }
  return { dur, v, dist, incline, climb, kmh: v * 3.6,
           power: optNum(seg.power), cad: optNum(seg.cad) };
}

function buildFromPlan() {
  const records = [], laps = [];
  let t = 0, dist = 0, alt = 0, ascent = 0, descent = 0;
  let lastV = 0, lastInc = 0, lastP = null, lastC = null;
  for (const seg of state.plan) {
    const s = segSolve(seg);
    if (!s.dur || !(s.v > 0)) continue;
    const extra = {};
    if (s.power != null) extra.power = s.power;
    if (s.cad != null) extra.cad = s.cad;
    laps.push({ start: t, end: t + s.dur });
    for (let i = 0; i < s.dur; i++) {
      records.push({ t, speed: s.v, incline: s.incline, alt, dist, ...extra });
      const dv = s.v * 1 * s.incline / 100;
      dist += s.v;
      alt += dv;
      if (dv > 0) ascent += dv; else descent -= dv;
      t++;
    }
    lastV = s.v; lastInc = s.incline; lastP = s.power; lastC = s.cad;
  }
  if (records.length) {
    const tail = { t, speed: lastV, incline: lastInc, alt, dist };
    if (lastP != null) tail.power = lastP;
    if (lastC != null) tail.cad = lastC;
    records.push(tail);
  }
  return { records, laps,
           totals: { duration: t, dist, ascent, descent } };
}

function segRow(seg, i) {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input type="checkbox" class="pick"></td>
    <td class="idx">${i + 1}</td>
    <td><select class="mode">
          <option value="time">time</option>
          <option value="dist">dist</option>
          <option value="distTime">dist + time</option>
        </select></td>
    <td><input class="len" size="7"></td>
    <td><input class="num speed" type="number" step="0.1" min="0" max="80"></td>
    <td class="drv pace"></td>
    <td><input class="num timeLen" size="7"></td>
    <td><select class="hill">
          <option value="pct">%</option>
          <option value="m">m</option>
        </select></td>
    <td><input class="num incline" type="number" step="0.5" min="-25" max="40"></td>
    <td><input class="num climb" type="number" step="10"></td>
    <td><input class="num power" type="number" step="5" min="0" max="2000"
               placeholder="—" title="average watts (optional)"></td>
    <td><input class="num cad" type="number" step="1" min="0" max="250"
               placeholder="—" title="average cadence: rpm cycling, steps/min running (optional)"></td>
    <td><button class="del" title="remove">✕</button></td>`;

  tr.addEventListener("input", (e) => {
    if (e.target.classList.contains("mode") || e.target.classList.contains("hill"))
      return switchSegMode(tr, seg);
    readSegRow(tr, seg);
    showDerived(tr, seg);
    recalcPlan();
  });
  tr.querySelector(".del").addEventListener("click", () => {
    state.plan.splice(state.plan.indexOf(seg), 1);
    renderPlan();
  });
  seedSegRow(tr, seg);
  return tr;
}

/* Copy the row's editable cells into the segment. Read-only (derived) cells
   are ignored -- they are output, never input. */
function readSegRow(tr, seg) {
  seg.len = tr.querySelector(".len").value;
  if (seg.mode === "distTime") seg.timeLen = tr.querySelector(".timeLen").value;
  else seg.speed = parseFloat(tr.querySelector(".speed").value) || 0;
  if (seg.hill === "m") seg.climb = parseFloat(tr.querySelector(".climb").value) || 0;
  else seg.incline = parseFloat(tr.querySelector(".incline").value) || 0;
  seg.power = tr.querySelector(".power").value.trim();
  seg.cad = tr.querySelector(".cad").value.trim();
}

/* Fill every cell, editable ones included: for first render and mode swaps. */
function seedSegRow(tr, seg) {
  tr.querySelector(".mode").value = seg.mode;
  tr.querySelector(".hill").value = seg.hill;
  const len = tr.querySelector(".len");
  len.value = seg.len;
  len.placeholder = seg.mode === "time" ? "min or mm:ss" : "km";
  if (seg.mode === "distTime") tr.querySelector(".timeLen").value = seg.timeLen;
  else tr.querySelector(".speed").value = seg.speed;
  if (seg.hill === "m") tr.querySelector(".climb").value = seg.climb;
  else tr.querySelector(".incline").value = seg.incline;
  tr.querySelector(".power").value = seg.power;
  tr.querySelector(".cad").value = seg.cad;
  showDerived(tr, seg);
}

/* Refresh only the derived cells -- never touches a cell being typed in. */
function showDerived(tr, seg) {
  const s = segSolve(seg);
  const cell = (sel, isDerived, value) => {
    const el = tr.querySelector(sel);
    el.readOnly = isDerived;
    el.classList.toggle("derived", isDerived);
    if (isDerived) el.value = value;
  };
  tr.querySelector(".pace").textContent = s.kmh ? fmtPace(s.kmh) : "—";
  cell(".speed", seg.mode === "distTime", s.kmh ? s.kmh.toFixed(2) : "");
  cell(".timeLen", seg.mode !== "distTime", s.dur ? fmtDur(s.dur) : "");
  cell(".incline", seg.hill === "m", s.dur ? s.incline.toFixed(1) : "");
  cell(".climb", seg.hill === "pct", s.dur ? Math.round(s.climb) : "");
  const steep = s.dur > 0 && Math.abs(s.incline) > MAX_GRADE;
  tr.querySelector(".incline").classList.toggle("warn", steep);
  tr.querySelector(".incline").title = steep
    ? `${s.incline.toFixed(1)}% is steeper than most treadmills go (${MAX_GRADE}%)`
    : "";
}

/* Switching mode keeps the run you already described: the solved numbers
   from the old mode become the typed numbers of the new one. */
function switchSegMode(tr, seg) {
  const before = segSolve(seg);
  const mode = tr.querySelector(".mode").value;
  const hill = tr.querySelector(".hill").value;
  if (mode !== seg.mode) {
    if (before.dur > 0) {
      if (mode === "time") seg.len = fmtDur(before.dur);
      else seg.len = (before.dist / 1000).toFixed(2);
      if (mode === "distTime") seg.timeLen = fmtDur(before.dur);
      else seg.speed = Math.round(before.kmh * 100) / 100;
    }
    seg.mode = mode;
  }
  if (hill !== seg.hill) {
    if (before.dur > 0) {
      if (hill === "m") seg.climb = Math.round(before.climb);
      else seg.incline = Math.round(before.incline * 10) / 10;
    }
    seg.hill = hill;
  }
  seedSegRow(tr, seg);
  recalcPlan();
}
function renderPlan() {
  const tb = $("#segTable tbody");
  tb.innerHTML = "";
  state.plan.forEach((seg, i) => tb.appendChild(segRow(seg, i)));
  recalcPlan();
}
function recalcPlan() {
  state.planBuild = buildFromPlan();
  const t = state.planBuild.totals;
  $("#planTotals").innerHTML = totalsHtml([
    [fmtDur(t.duration), "time"],
    [(t.dist / 1000).toFixed(2) + " km", "distance"],
    ["+" + Math.round(t.ascent) + " m", "ascent"],
    ["−" + Math.round(t.descent) + " m", "descent"],
    [t.duration ? fmtPace(t.dist / t.duration * 3.6) : "—", "avg pace"],
  ]);
  drawProfile($("#planChart"), state.planBuild.records);
  saveLocal();
}
function totalsHtml(items) {
  return items.map(([v, l]) =>
    `<span class="t-item"><b class="mono">${v}</b><span>${l}</span></span>`).join("");
}

/* ---------------------------------------------------------------- chart */
function drawProfile(canvas, recs, hrOpts) {
  // Design height is cached on first draw: canvas.width/height assignments
  // rewrite the element's attributes, so re-reading getAttribute("height")
  // here would compound dpr scaling on every redraw (canvas grew until it
  // blanked on scaled displays).
  if (!canvas._designH)
    canvas._designH = parseInt(canvas.getAttribute("height"), 10) || 240;
  const ch = canvas._designH;
  const cw = canvas.clientWidth || canvas.parentElement.clientWidth || 900;
  const dpr = window.devicePixelRatio || 1;
  const bw = Math.round(cw * dpr), bh = Math.round(ch * dpr);
  if (canvas.width !== bw || canvas.height !== bh) {
    canvas.width = bw; canvas.height = bh;
  }
  canvas.style.height = ch + "px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cw, ch);
  ctx.font = "11px Segoe UI";
  if (!recs || recs.length < 2) {
    ctx.fillStyle = "#8b98a8";
    ctx.fillText("add segments to see the profile", 16, 24);
    canvas._hover = null;
    return;
  }
  const css = getComputedStyle(document.documentElement);
  const C = n => css.getPropertyValue(n).trim();
  const L = 46, R = 40, T = 6, B = 18;
  const w = cw - L - R;
  const dur = recs[recs.length - 1].t || 1;
  const x = t => L + t / dur * w;

  const lanes = [
    { key: "speed", scale: v => v * 3.6, color: C("--accent"), label: "km/h", fill: true },
    { key: "incline", scale: v => v, color: C("--blue"), label: "%", fill: true, zero: true },
    { key: "alt", scale: v => v + Number(state.settings.startAlt || 0), color: C("--green"), label: "m", fill: true },
  ];
  const laneH = (ch - T - B) / lanes.length;

  lanes.forEach((lane, li) => {
    const top = T + li * laneH, bot = top + laneH - 8;
    const vals = recs.map(r => lane.scale(r[lane.key]));
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (lane.zero) lo = Math.min(lo, 0);
    if (hi - lo < 1e-9) hi = lo + 1;
    const pad = (hi - lo) * 0.08;
    lo -= lane.zero ? 0 : pad; hi += pad;
    const y = v => bot - (v - lo) / (hi - lo) * (bot - top);

    ctx.strokeStyle = "#2a323e";
    ctx.beginPath(); ctx.moveTo(L, bot + .5); ctx.lineTo(L + w, bot + .5); ctx.stroke();

    ctx.beginPath();
    recs.forEach((r, i) => {
      const px = x(r.t), py = y(vals[i]);
      i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
    });
    if (lane.fill) {
      ctx.save();
      ctx.lineTo(x(recs[recs.length - 1].t), y(Math.max(lo, Math.min(hi, lane.zero ? 0 : lo))));
      ctx.lineTo(x(recs[0].t), y(Math.max(lo, Math.min(hi, lane.zero ? 0 : lo))));
      ctx.closePath();
      ctx.globalAlpha = 0.16; ctx.fillStyle = lane.color; ctx.fill();
      ctx.restore();
      ctx.beginPath();
      recs.forEach((r, i) => {
        const px = x(r.t), py = y(vals[i]);
        i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
      });
    }
    ctx.strokeStyle = lane.color; ctx.lineWidth = 1.6; ctx.stroke(); ctx.lineWidth = 1;

    ctx.fillStyle = "#8b98a8";
    ctx.textAlign = "right";
    ctx.fillText(fmtNum(hi), L - 5, top + 9);
    ctx.fillText(fmtNum(lo), L - 5, bot);
    ctx.textAlign = "left";
    ctx.fillStyle = lane.color;
    ctx.fillText(lane.key === "alt" ? "elev m" : lane.key + " " + lane.label, L + 4, top + 10);
    lane._y = y; lane._top = top; lane._bot = bot;
  });

  // heart-rate overlay across the top (speed) lane, right-hand scale
  const hrPts = collectHrPoints(recs, hrOpts, dur);
  if (hrPts.length > 1) {
    const lane = lanes[0];
    const hrs = hrPts.map(p => p[1]);
    let lo = Math.min(...hrs), hi = Math.max(...hrs);
    if (hi - lo < 5) { lo -= 3; hi += 3; }
    const y = v => lane._bot - (v - lo) / (hi - lo) * (lane._bot - lane._top);
    ctx.beginPath();
    let started = false;
    hrPts.forEach(p => {
      const px = x(p[0]), py = y(p[1]);
      started ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
      started = true;
    });
    ctx.strokeStyle = C("--red"); ctx.globalAlpha = 0.9; ctx.stroke(); ctx.globalAlpha = 1;
    ctx.fillStyle = C("--red"); ctx.textAlign = "left";
    ctx.fillText(Math.round(hi) + "♥", L + w + 4, lanes[0]._top + 9);
    ctx.fillText(Math.round(lo) + "♥", L + w + 4, lanes[0]._bot);
  }

  // x-axis time labels
  ctx.fillStyle = "#8b98a8"; ctx.textAlign = "center";
  const step = niceStep(dur);
  for (let t = 0; t <= dur; t += step) ctx.fillText(fmtDur(t), x(t), ch - 5);
  ctx.textAlign = "left";

  canvas._hover = { recs, x, dur, L, w, hrPts };
  if (!canvas._hoverBound) {
    canvas._hoverBound = true;
    canvas.addEventListener("mousemove", e => hoverReadout(canvas, e));
    canvas.addEventListener("mouseleave", () => { canvas.title = ""; });
  }
}
function fmtNum(v) {
  return Math.abs(v) >= 100 ? Math.round(v) : (Math.round(v * 10) / 10);
}
function niceStep(dur) {
  for (const s of [30, 60, 120, 300, 600, 900, 1800, 3600, 7200])
    if (dur / s <= 9) return s;
  return 14400;
}
function collectHrPoints(recs, hrOpts, dur) {
  if (hrOpts && hrOpts.samples && hrOpts.samples.length) {
    const off = Number(hrOpts.offset) || 0;
    return hrOpts.samples
      .map(s => [s[0] - off, s[1]])
      .filter(p => p[0] >= 0 && p[0] <= dur);
  }
  return recs.filter(r => r.hr != null).map(r => [r.t, r.hr]);
}
function hoverReadout(canvas, e) {
  const hv = canvas._hover;
  if (!hv) return;
  const rect = canvas.getBoundingClientRect();
  const frac = (e.clientX - rect.left - hv.L) / hv.w;
  if (frac < 0 || frac > 1) { canvas.title = ""; return; }
  const t = frac * hv.dur;
  let idx = Math.min(hv.recs.length - 1, Math.max(0, Math.round(t)));
  // records are 1 Hz with t == index for plan/live, but be safe:
  if (hv.recs[idx].t !== Math.round(t)) {
    idx = hv.recs.findIndex(r => r.t >= t);
    if (idx < 0) idx = hv.recs.length - 1;
  }
  const r = hv.recs[idx];
  const hrPt = hv.hrPts.length ? nearestHrPt(hv.hrPts, t) : null;
  canvas.title =
    `${fmtDur(r.t)} · ${(r.speed * 3.6).toFixed(1)} km/h (${fmtPace(r.speed * 3.6)})` +
    ` · ${r.incline.toFixed(1)} % · ${Math.round(r.alt + Number(state.settings.startAlt || 0))} m` +
    (hrPt ? ` · ♥ ${Math.round(hrPt[1])}` : "");
}
function nearestHrPt(pts, t) {
  let best = null;
  for (const p of pts) if (!best || Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p;
  return best && Math.abs(best[0] - t) <= 10 ? best : null;
}

/* ----------------------------------------------------------------- live */
function liveElapsed() {
  return live.accum + (live.running ? (performance.now() - live.startedWall) / 1000 : 0);
}
function liveStartPause() {
  if (!live.running) {
    live.running = true;
    live.startedWall = performance.now();
    if (!live.timer) live.timer = setInterval(liveTick, 250);
    $("#liveStart").textContent = "❚❚ pause";
    $("#liveState").textContent = "recording — mirror your treadmill";
    $("#liveLap").disabled = $("#liveFinish").disabled = $("#liveReset").disabled = false;
  } else {
    live.accum = liveElapsed();
    live.running = false;
    $("#liveStart").textContent = "▶ resume";
    $("#liveState").textContent = "paused (paused time is not recorded)";
  }
  liveTick();
}
function liveTick() {
  const el = liveElapsed();
  while (live.nextT <= Math.floor(el)) {
    const v = live.speed / 3.6;
    const rec = { t: live.nextT, speed: v, incline: live.incline,
                  alt: live.alt, dist: live.dist };
    if (live.hrBpm && Date.now() - live.hrAt < 10000) rec.hr = live.hrBpm;
    live.recs.push(rec);
    const dv = v * live.incline / 100;
    live.dist += v; live.alt += dv;
    if (dv > 0) live.ascent += dv;
    live.nextT++;
  }
  $("#liveTimer").textContent = fmtDur(Math.floor(el));
  $("#liveDist").textContent = (live.dist / 1000).toFixed(2) + " km";
  $("#liveClimb").textContent = Math.round(live.ascent) + " m";
  $("#livePace").textContent = "pace " + fmtPace(live.speed);
  $("#liveLaps").textContent = live.lapMarks.length
    ? live.lapMarks.length + 1 + " laps" : "no laps";
  $("#liveHr").textContent =
    (live.hrBpm && Date.now() - live.hrAt < 10000) ? live.hrBpm : "—";
}
function liveAdjust(dSpeed, dIncline) {
  live.speed = Math.min(30, Math.max(0, Math.round((live.speed + dSpeed) * 10) / 10));
  live.incline = Math.min(25, Math.max(-10, Math.round((live.incline + dIncline) * 10) / 10));
  $("#liveSpeed").textContent = live.speed.toFixed(1);
  $("#liveIncline").textContent = live.incline.toFixed(1);
}
function liveLap() {
  const t = Math.floor(liveElapsed());
  if (t > 0 && !live.lapMarks.includes(t)) live.lapMarks.push(t);
  liveTick();
}
function liveFinish() {
  if (live.running) liveStartPause();
  liveTick();
  if (live.recs.length < 2) { alert("Nothing recorded yet."); return; }
  const end = live.recs[live.recs.length - 1].t;
  const bounds = [0, ...live.lapMarks.filter(m => m < end).sort((a, b) => a - b), end];
  const laps = [];
  for (let i = 0; i + 1 < bounds.length; i++)
    laps.push({ start: bounds[i], end: bounds[i + 1] });
  setActivity({
    source: "live recording",
    records: live.recs.slice(),
    laps,
  });
  switchTab("finish");
}
function liveReset() {
  if (!confirm("Discard this live recording?")) return;
  Object.assign(live, { running: false, accum: 0, nextT: 0, dist: 0, alt: 0,
                        ascent: 0, recs: [], lapMarks: [] });
  clearInterval(live.timer); live.timer = null;
  $("#liveStart").textContent = "▶ start";
  $("#liveState").textContent = "ready";
  $("#liveLap").disabled = $("#liveFinish").disabled = $("#liveReset").disabled = true;
  liveTick();
}

/* ------------------------------------------------------------- live BLE */
async function connectHR() {
  const st = $("#bleStatus");
  if (!navigator.bluetooth) {
    st.textContent = "Web Bluetooth unavailable here — use Chrome/Edge, or enable it in brave://flags. (You can still merge a watch file afterwards.)";
    return;
  }
  try {
    st.textContent = "choose your strap…";
    const dev = await navigator.bluetooth.requestDevice({
      filters: [{ services: ["heart_rate"] }] });
    live.bleDevice = dev;
    dev.addEventListener("gattserverdisconnected", () => {
      st.textContent = "strap disconnected";
      live.hrBpm = null;
    });
    const server = await dev.gatt.connect();
    const svc = await server.getPrimaryService("heart_rate");
    const ch = await svc.getCharacteristic("heart_rate_measurement");
    await ch.startNotifications();
    ch.addEventListener("characteristicvaluechanged", e => {
      const dv = e.target.value;
      const flags = dv.getUint8(0);
      live.hrBpm = flags & 1 ? dv.getUint16(1, true) : dv.getUint8(1);
      live.hrAt = Date.now();
    });
    st.textContent = "connected: " + (dev.name || "HR strap");
  } catch (err) {
    st.textContent = "not connected (" + err.message + ")";
  }
}

/* --------------------------------------------------------------- finish */
function actTotals(records) {
  let ascent = 0, descent = 0;
  for (let i = 1; i < records.length; i++) {
    const d = records[i].alt - records[i - 1].alt;
    if (d > 0) ascent += d; else descent -= d;
  }
  const last = records[records.length - 1];
  return { duration: last.t, dist: last.dist, ascent, descent };
}
function setActivity(act) {
  act.totals = actTotals(act.records);
  state.activity = act;
  $("#startTime").value = toLocalInput(Date.now() / 1000 - act.totals.duration);
  refreshFinish();
}
function refreshFinish() {
  const act = state.activity;
  const has = !!act;
  $("#noActivity").style.display = has ? "none" : "";
  $("#finishBody").style.display = has ? "" : "none";
  if (!has) return;

  const t = act.totals;
  const preview = hrPreviewStats();
  const liveHrs = act.records.filter(r => r.hr != null).map(r => r.hr);
  const hrShown = preview ? `${preview.avg} / ${preview.max}` :
    liveHrs.length ? `${Math.round(liveHrs.reduce((a, b) => a + b) / liveHrs.length)} / ${Math.max(...liveHrs)}` : "—";
  $("#summary").innerHTML = totalsHtml([
    [fmtDur(t.duration), "duration"],
    [(t.dist / 1000).toFixed(2) + " km", "distance"],
    ["+" + Math.round(t.ascent) + " m", "ascent ▲"],
    ["−" + Math.round(t.descent) + " m", "descent"],
    [fmtPace(t.dist / t.duration * 3.6), "avg pace"],
    [String(act.laps.length), "laps"],
    [hrShown, "avg/max ♥"],
    [act.source, "source"],
  ]);

  const adopt = state.hr && $("#adoptStart").checked;
  $("#startTime").disabled = !!adopt;
  if (adopt)
    $("#startTime").value =
      toLocalInput(state.hr.start_epoch + Number($("#hrOffset").value || 0));

  $("#hrCoverage").textContent = preview ?
    `matched ${preview.matched}/${preview.total} records (${Math.round(preview.matched / preview.total * 100)}%) · avg ${preview.avg} · max ${preview.max} bpm` : "";

  drawProfile($("#finishChart"), act.records,
    state.hr ? { samples: state.hr.samples, offset: Number($("#hrOffset").value || 0) } : null);
}

/* client-side mirror of treadlab/merge.py — preview/coverage display only;
   the authoritative merge happens server-side at export */
function hrPreviewStats() {
  if (!state.hr || !state.activity) return null;
  const samples = state.hr.samples;
  if (!samples || !samples.length) return null;
  const off = Number($("#hrOffset").value || 0);
  const times = samples.map(s => s[0]);
  let matched = 0, sum = 0, max = 0;
  for (const rec of state.activity.records) {
    const want = rec.t + off;
    let i = lowerBound(times, want);
    let best = null;
    for (const j of [i - 1, i]) {
      if (j >= 0 && j < samples.length &&
          (best === null || Math.abs(times[j] - want) < Math.abs(times[best] - want)))
        best = j;
    }
    if (best === null) continue;
    const gap = Math.abs(times[best] - want);
    if (gap <= 5 || (want - times[best] >= 0 && want - times[best] <= 10)) {
      matched++; sum += samples[best][1]; max = Math.max(max, samples[best][1]);
    }
  }
  if (!matched) return { matched, total: state.activity.records.length, avg: "—", max: "—" };
  return { matched, total: state.activity.records.length,
           avg: Math.round(sum / matched), max: Math.round(max) };
}
function lowerBound(arr, x) {
  let lo = 0, hi = arr.length;
  while (lo < hi) { const m = (lo + hi) >> 1; arr[m] < x ? lo = m + 1 : hi = m; }
  return lo;
}

async function onHrFile(file) {
  if (!file) return;
  $("#hrInfo").textContent = "reading " + file.name + "…";
  try {
    const buf = await file.arrayBuffer();
    const j = describeFit(new Uint8Array(buf));
    if (!j.ok) throw new Error(j.error || "could not parse file");
    if (!j.has_hr) throw new Error("that file has no heart-rate data");
    j.file = file.name;
    state.hr = j;
    $("#hrInfo").innerHTML =
      `<b>${file.name}</b> — ${j.device || "unknown device"}${j.sport ? " · " + j.sport : ""}` +
      ` · started ${fmtClock(j.start_epoch)} · ${fmtDur(j.duration_s)}` +
      (j.distance_m ? ` · ${(j.distance_m / 1000).toFixed(2)} km` : "") +
      ` · ♥ avg ${j.avg_hr} max ${j.max_hr}` +
      (j.has_cad ? " · has cadence" : "") +
      (j.has_temp ? ` · ${j.avg_temp != null ? "avg " + j.avg_temp + " °C" : "has temperature"}` : "") +
      (j.has_gps ? " · has GPS (not copied)" : "") +
      (j.warnings.length ? ` · <span style="color:var(--red)">${j.warnings.join("; ")}</span>` : "");
    $("#hrClear").style.display = "";
    $("#hrControls").style.display = "";
    $("#copyCad").parentElement.style.display = j.has_cad ? "" : "none";
    $("#copyTemp").parentElement.style.display = j.has_temp ? "" : "none";
    // If you typed a cadence into the plan, that is the number you meant --
    // don't let the watch's cadence quietly replace it.
    if (j.has_cad && state.activity
        && state.activity.records.some(r => r.cad != null)) {
      $("#copyCad").checked = false;
    }
    refreshFinish();
  } catch (err) {
    state.hr = null;
    $("#hrInfo").textContent = "✗ " + err.message;
    $("#hrControls").style.display = "none";
    refreshFinish();
  }
}
function clearHrFile() {
  state.hr = null;
  $("#hrFile").value = "";
  $("#hrInfo").textContent = "no file loaded";
  $("#hrClear").style.display = "none";
  $("#hrControls").style.display = "none";
  refreshFinish();
}

async function exportFit() {
  const act = state.activity;
  if (!act) return;
  const status = $("#exportStatus");
  const adopt = state.hr && $("#adoptStart").checked;
  const offset = Number($("#hrOffset").value || 0);
  const startEpoch = adopt ? state.hr.start_epoch + offset
                           : fromLocalInput($("#startTime").value);
  if (!startEpoch) { status.textContent = "✗ set a start time first"; return; }
  state.settings.sport = $("#sportSel").value;
  state.settings.startAlt = parseFloat($("#startAlt").value) || 0;
  state.settings.gpsLoc = $("#gpsLoc").value;
  saveLocal();

  // the dropdown carries both halves as "sport/sub_sport"
  const [sport, subSport] = String(state.settings.sport).split("/");
  const payload = {
    start_epoch: startEpoch,
    // The UTC offset AT THE ACTIVITY'S INSTANT, not at "now", so a file
    // built in one DST period for a run in another is still right.
    // getTimezoneOffset() counts minutes WEST of UTC, hence the negation.
    // Without this the file claims local == UTC and whatever imports it
    // has to guess from its own clock. See TIMEZONE-FIX.md.
    utc_offset_s: -new Date(startEpoch * 1000).getTimezoneOffset() * 60,
    sport: sport || "running",
    sub_sport: subSport || "virtual_activity",
    start_alt: state.settings.startAlt,
    gps: state.settings.gpsLoc === "off" ? false : state.settings.gpsLoc,
    calories: parseFloat($("#calories").value) || null,
    records: act.records.map(r => ({
      t: r.t, speed: r.speed, alt: r.alt, dist: r.dist,
      ...(r.hr != null ? { hr: r.hr } : {}),
      ...(r.cad != null ? { cad: r.cad } : {}),
      ...(r.power != null ? { power: r.power } : {}),
    })),
    laps: act.laps,
    hr: state.hr ? { samples: state.hr.samples, offset,
                     copy_cadence: $("#copyCad").checked,
                     copy_temp: $("#copyTemp").checked } : null,
  };
  status.textContent = "building FIT…";
  try {
    const { fit, name, mergeStats } = buildExport(payload);
    const blob = new Blob([fit], { type: "application/octet-stream" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 30000);
    const extra = mergeStats
      ? ` · HR merged onto ${mergeStats.matched}/${mergeStats.total} records` : "";
    status.textContent = `✔ ${name} (${(blob.size / 1024).toFixed(1)} kB)${extra} — upload it at strava.com/upload`;
  } catch (err) {
    status.textContent = "✗ export failed: " + err.message;
  }
}

/* ------------------------------------------------------------ tabs, IO */
function switchTab(name) {
  $$(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $$(".pane").forEach(p => p.classList.toggle("active", p.id === "tab-" + name));
  if (name === "finish") refreshFinish();
  if (name === "plan") recalcPlan();
}
function saveLocal() {
  try {
    localStorage.setItem("treadlab", JSON.stringify(
      { plan: state.plan, settings: state.settings }));
  } catch (e) { /* private mode etc. */ }
}
function loadLocal() {
  try {
    const j = JSON.parse(localStorage.getItem("treadlab"));
    if (j && Array.isArray(j.plan) && j.plan.length) state.plan = j.plan.map(normSeg);
    if (j && j.settings) {
      Object.assign(state.settings, j.settings);
      if (j.settings.gpsLoc === undefined)  // migrate pre-dropdown checkbox
        state.settings.gpsLoc = j.settings.gpsLoop === false ? "off" : "watopia";
      delete state.settings.gpsLoop;
      // sport used to hold just the sub-sport, before rides were an option
      if (state.settings.sport && !String(state.settings.sport).includes("/"))
        state.settings.sport = "running/" + state.settings.sport;
    }
  } catch (e) { /* corrupted -> defaults */ }
}

function init() {
  loadLocal();
  if (!state.plan.length) state.plan = defaultPlan();
  $("#sportSel").value = state.settings.sport;
  $("#startAlt").value = state.settings.startAlt;
  $("#gpsLoc").value = state.settings.gpsLoc || "watopia";
  if (!$("#gpsLoc").value) $("#gpsLoc").value = "watopia";  // unknown stored key
  renderPlan();

  $$(".tab").forEach(b => b.addEventListener("click", () => switchTab(b.dataset.tab)));
  $$("[data-goto]").forEach(a => a.addEventListener("click", e => {
    e.preventDefault(); switchTab(a.dataset.goto);
  }));

  $("#addSeg").addEventListener("click", () => {
    const last = state.plan[state.plan.length - 1];
    state.plan.push(last ? { ...last }
                         : normSeg({ mode: "time", len: "5:00", speed: 10, incline: 2 }));
    renderPlan();
  });
  $("#dupSel").addEventListener("click", () => {
    const picked = $$("#segTable .pick")
      .map((cb, i) => cb.checked ? state.plan[i] : null).filter(Boolean);
    if (!picked.length) { alert("Tick the segments to repeat first."); return; }
    const times = Math.max(2, parseInt($("#dupCount").value) || 2);
    for (let k = 1; k < times; k++) picked.forEach(s => state.plan.push({ ...s }));
    renderPlan();
  });
  $("#clearPlan").addEventListener("click", () => {
    if (confirm("Clear the whole plan?")) { state.plan = []; renderPlan(); }
  });
  $("#usePlan").addEventListener("click", () => {
    const b = state.planBuild;
    if (!b || b.records.length < 2) { alert("Add at least one segment first."); return; }
    setActivity({ source: "plan", records: b.records, laps: b.laps });
    switchTab("finish");
  });

  $("#liveStart").addEventListener("click", liveStartPause);
  $("#liveLap").addEventListener("click", liveLap);
  $("#liveFinish").addEventListener("click", liveFinish);
  $("#liveReset").addEventListener("click", liveReset);
  $("#bleBtn").addEventListener("click", connectHR);
  $$(".step").forEach(b => b.addEventListener("click", () =>
    liveAdjust(parseFloat(b.dataset.speed || 0), parseFloat(b.dataset.incline || 0))));

  document.addEventListener("keydown", e => {
    if (!$("#tab-live").classList.contains("active")) return;
    if (/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
    const big = e.shiftKey;
    const acts = {
      " ": () => liveStartPause(),
      "ArrowUp": () => liveAdjust(big ? 1 : 0.1, 0),
      "ArrowDown": () => liveAdjust(big ? -1 : -0.1, 0),
      "ArrowRight": () => liveAdjust(0, big ? 1 : 0.5),
      "ArrowLeft": () => liveAdjust(0, big ? -1 : -0.5),
      "l": () => liveLap(), "L": () => liveLap(),
    };
    if (acts[e.key]) { e.preventDefault(); acts[e.key](); }
  });

  $("#hrFile").addEventListener("change", e => onHrFile(e.target.files[0]));
  $("#hrClear").addEventListener("click", clearHrFile);
  ["adoptStart", "copyCad", "copyTemp", "hrOffset"].forEach(id =>
    $("#" + id).addEventListener("input", refreshFinish));
  $$(".nudge").forEach(b => b.addEventListener("click", () => {
    $("#hrOffset").value = (Number($("#hrOffset").value) || 0) + Number(b.dataset.nudge);
    refreshFinish();
  }));
  $("#startAlt").addEventListener("input", () => {
    state.settings.startAlt = parseFloat($("#startAlt").value) || 0;
    refreshFinish(); saveLocal();
  });
  $("#gpsLoc").addEventListener("input", () => {
    state.settings.gpsLoc = $("#gpsLoc").value;
    saveLocal();
  });
  $("#exportBtn").addEventListener("click", exportFit);

  window.addEventListener("resize", () => {
    recalcPlan();
    if (state.activity) refreshFinish();
  });

  $("#version").textContent = "v" + VERSION;
  $("#version2").textContent = VERSION;

  /* Offline support for the installed web app. Deliberately skipped on
     localhost: running TreadLab.bat on a PC then always serves the files
     straight from disk, so an edit is never masked by a cached build. */
  if ("serviceWorker" in navigator
      && !["localhost", "127.0.0.1", ""].includes(location.hostname)) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }

  liveAdjust(0, 0);
  liveTick();

  // module scope is private; expose a handle for debugging and tests
  window.TL = { state, live, segSolve, normSeg, defaultPlan, renderPlan,
                recalcPlan, switchTab, exportFit, onHrFile, refreshFinish,
                liveStartPause, liveAdjust, liveLap, liveFinish,
                buildExport, describeFit, VERSION };
}
document.addEventListener("DOMContentLoaded", init);
