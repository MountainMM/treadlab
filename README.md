# TreadLab v0.5.0

> ## If you have not touched this in years, read this bit
>
> **To run it — pick whichever works:**
>
> 1. **Windows:** double-click **`TreadLab.bat`**. Your browser opens and
>    that is it. Nothing needs installing.
> 2. **Anything else, or if the .bat fails:** double-click
>    **`TreadLab-any-computer.html`**. It is the whole app in one file and
>    needs nothing but a web browser — no Python, no internet, any operating
>    system. (The only thing it cannot do is talk to a Bluetooth HR strap.)
> 3. **Nothing here works at all:** the same app is online at
>    **https://mountainmm.github.io/treadlab/** — and you can download a
>    fresh copy of the single file from there.
>
> **"Python was not found"** — use option 2 above. That is exactly what it
> is there for; you do not need to fix anything.
>
> **Is this copy still intact?** Double-click **`Verify.bat`**. On a Mac
> or Linux machine you do not need Python for this at all:
> `shasum -a 256 -c checksums.sha256` / `sha256sum -c checksums.sha256`.
> It checks every file in the folder and tells you if the drive has
> lost anything. Worth doing right after copying to a new drive.
>
> **What is all this made of?** See [VERSIONS.md](VERSIONS.md).


**Turn treadmill runs into Strava-ready FIT files with real elevation gain —
and your real heart rate.**

Treadmill runs normally upload to Strava with zero elevation. TreadLab lets
you recreate (or record live) the speed + incline of your run, integrates

    distance = Σ speed · dt        climb = Σ speed · dt · incline%

and writes a FIT activity whose altitude stream gives Strava a true
elevation-gain number. Offline, open source, zero dependencies — sibling of
[FitLab](../FitLab/).

## Quick start (Windows)

Double-click **TreadLab.bat** (or `py run.py`). Your browser opens
`http://127.0.0.1:8766`.

**Fully self-contained & offline.** The folder bundles its own Python
runtime (`python-embed\`, Win64) and the app makes zero network requests —
no CDN scripts, fonts, or map tiles. Copy the folder to a USB stick or
another PC and double-click the .bat; nothing needs to be installed and
nothing is written outside the folder (exports go to the browser's normal
Downloads; saved plans live in that PC's browser storage). If
`python-embed\` is ever deleted, the launcher falls back to a sibling
`..\FitLab\python-embed`, then to any installed Python 3.8+.

**Since v0.4.0 Python is only a file server.** The whole FIT engine —
writing files, parsing your watch's file, the HR merge, the map loop, the
terrain texture — runs in the browser as JavaScript (`treadlab/static/engine/`).
Nothing is uploaded, nothing is computed server-side, and there is no API
to call. That is what makes the phone build possible.

## Putting it on your phone

The app is a self-sufficient folder of static files (93 KB): serve it over
HTTPS and it installs on a phone as a normal-looking app that **works with
no signal at all**.

Run the build first — it strips the developer-only test suite:

    python-embed\python.exe tools\make_web_build.py

That writes `web\`. Upload its **contents** to any HTTPS host, then open
the page in Safari on the iPhone → **Share** → **Add to Home Screen**
(Android/Chrome offers **Install app**). It launches full-screen with its
own icon, and `sw.js` keeps a copy so it opens offline. Exported .fit
files land in Files, and you load a watch .fit straight from there.

### Hosting it on a WordPress site

This works well, because the app never needs PHP, a database, or
WordPress itself — it only needs the files served. Put it in a
**subfolder**, not into WordPress's content:

1. Via FTP/SFTP or your host's File Manager, create `public_html/treadlab/`
   (alongside `wp-content`, `wp-admin`, …) and upload the contents of
   `web\` into it. **Don't** use the WordPress Media Library — it rejects
   `.js`/`.json` uploads and scatters files into dated folders.
2. Visit `https://yoursite.com/treadlab/`.

The included `.htaccess` handles the three things that usually go wrong on
shared hosting: it stops WordPress's rewrite rules from swallowing the
URLs, forces correct content types (a manifest or ES module served as
`text/html` silently breaks startup), and marks `sw.js` as never-cacheable
so future updates can actually reach an installed phone. On **nginx**
hosts `.htaccess` is ignored — ask support to serve `/treadlab/` as plain
static files with correct MIME types.

One more trap: if you run a caching/optimisation plugin (WP Rocket,
LiteSpeed Cache, Autoptimize, Cloudflare APO), **exclude `/treadlab/`**
from minification, JS combining and CDN rewriting. Those tools assume
classic scripts and will break ES modules and the service worker.

Verified: served from a subfolder, the manifest's `start_url` and `scope`
and the service worker's scope all resolve to `/treadlab/` — so the app
installs correctly and cannot interfere with the rest of your site.

### Hosting it on GitHub Pages

Free, HTTPS by default, and no CMS to fight. Pages can serve a repo's
`docs/` folder directly, so publishing is a commit.

    python-embed\python.exe tools\make_web_build.py docs

Then, once:

    git init
    git add .
    git commit -m "TreadLab: treadmill runs to Strava-ready FIT files"
    git branch -M main
    git remote add origin https://github.com/<you>/treadlab.git
    git push -u origin main

In the repo: **Settings → Pages → Source: Deploy from a branch →
`main` / `/docs`**. The app appears at
`https://<you>.github.io/treadlab/` within a minute or two.

### Publishing an update

Double-click **Publish.bat**. It rebuilds `docs/`, shows you exactly what
changed, asks for a one-line description, commits and pushes.

Rebuilding `docs/` first — always, automatically — is the point of the
script: edit the app but forget that step and the live site silently keeps
serving the old version, with nothing to indicate anything is wrong.

`Publish.bat --dry-run` runs everything except the commit and upload, if
you just want to see what would go.

Doing it by hand is three commands from the project folder:

    python-embed\python.exe tools\make_web_build.py docs
    git add -A && git commit -m "what changed"
    git push

Notes specific to Pages:

* **`.nojekyll`** is written into the build automatically. Without it
  GitHub runs the files through Jekyll, which silently drops anything
  whose name starts with an underscore.
* `.htaccess` is inert here (Pages isn't Apache) but harmless — Pages
  already serves correct content types.
* `.gitignore` keeps `python-embed/` (~26 MB of redistributed Python) and
  the generated test fixtures out of the repo. A fresh clone runs on any
  Python 3.8+, or none at all if you only want the web app.
* Free Pages hosting requires a **public** repo. If you'd rather keep the
  code private, host the `web/` build on your own site instead — the app
  is identical either way.

Two honest caveats on iOS:

* **Live Bluetooth HR does not work** — Safari has never supported Web
  Bluetooth. The watch-file merge works normally, which is the path you
  actually use. A native app would be needed for live straps.
* **HTTPS is required** for offline install; a plain `http://192.168.x.x`
  address on your home network will run the app but cannot install it.

Nothing about the phone build is Apple-specific: the same URL installs on
Android, and works in any modern desktop browser.

## The three tabs

1. **Plan** — build the run as segments; each becomes a lap in the FIT file.
   Two dropdowns per row decide what you type and what TreadLab works out:
   * **by** — `time` (duration + speed), `dist` (km + speed), or
     `dist + time` (km + duration, *speed* is solved for you — handy when
     you remember "10K in 65 minutes" rather than a pace).
   * **hill** — `%` to type the grade, or `m` to type the total climb and
     have the grade solved instead.

   Calculated cells show greyed and italic, and changing a dropdown carries
   the run across rather than resetting it. A derived grade steeper than 15%
   is flagged, since most treadmills stop there. Tick rows + "duplicate" to
   build interval repeats; totals and the profile chart update live.

   **power (W)** and **cad (rpm)** are optional. Fill either in and that
   figure is written to every second of the segment — which is how you log
   a session you only remember the averages for. Leave them blank and the
   fields are omitted from the file entirely.

## Rides as well as runs

The activity dropdown on the export tab offers **Virtual ride** and
**Indoor ride** alongside the two run types, so the same machinery works
for an exercise bike. A typical bike session is one segment:

| | |
|---|---|
| by | `dist + time` — e.g. 11.3 km and 30:10, speed solved for you |
| hill | `%` at 0 if you aren't simulating a climb |
| power / cad | the averages off the bike console, e.g. 75 W and 80 rpm |

Then load your watch's heart-rate file as usual, and you get a ride whose
HR you can read against distance. If your watch records **only** heart
rate, that's fine — the cadence and temperature options simply don't
appear, and your typed cadence is used instead. (If the watch *does* have
cadence and you've typed one, TreadLab leaves the copy-cadence box
unticked so your number isn't overwritten.)

A constant wattage is an average, not a real power trace, so treat
Strava's derived figures (normalised power, intensity) as indicative
rather than meaningful.
2. **Live run** — mirror the treadmill while you run: big timer, hotkeys
   (**Space** start/pause, **↑↓** speed ±0.1 — with Shift ±1.0, **←→**
   incline ±0.5 — Shift ±1.0, **L** lap). Optionally connect a Bluetooth
   heart-rate strap (see below) to record live HR.
3. **Finish & export** — summary, optional heart-rate merge, export .FIT.

## Heart rate

Two ways to get your real HR into the file:

* **Merge from your watch (recommended).** Did the run earlier with a watch
  recording HR? On the Finish tab load that .FIT file — TreadLab copies its
  HR stream (plus cadence and temperature, if recorded — each has its own
  checkbox) onto your simulated activity. By default the
  activity also adopts the watch file's real start time, so one upload has
  your real HR, real time of day, and simulated elevation. Use the offset
  buttons if the traces need nudging; the red HR line on the chart and the
  "matched N/N records" line show the alignment. Then delete the watch's
  own zero-elevation upload from Strava (or don't upload it at all).
* **Live over Bluetooth.** On the Live tab, "♥ connect strap" pairs any
  standard BLE heart-rate strap via Web Bluetooth. Works in Chrome/Edge;
  Brave ships with Web Bluetooth **disabled** — enable it in `brave://flags`
  or use Chrome/Edge for live HR. (The merge option works in any browser.)

## Uploading to Strava

Export defaults to **Virtual run** (what Zwift uses) because Strava reliably
keeps a file's elevation for virtual activities; "Treadmill run" is also
offered but some platforms zero elevation on treadmill-flagged uploads.
**Make your first upload private and check it** — then delete/adjust. Upload
at `strava.com/upload`; Strava asks for the activity name there.

**Map or no map — your choice.** The "map loop" dropdown draws the run as
a closed loop in verified-empty ocean, sized so the loop's length equals
your distance with each second at its true along-track position — map,
pace and splits all agree. Two venues: **near Watopia** (12°S 166°E, the
default — the same trick Zwift uses to park Watopia on the Solomon
Islands, but 80+ km from any land, road or Zwift island) and **Point
Nemo** (49°S 123°W — the oceanic pole of inaccessibility, 2,700 km from
the nearest land, where retired spacecraft are deorbited). Or pick **no
map** for a plain activity. Either way, simulated runs can't touch
real-world segments or leaderboards (open water; and Strava keeps virtual
activities off real leaderboards anyway).

## Engine notes

The engine exists **twice**, and the two are held byte-identical:

* `treadlab/static/engine/*.js` — what actually runs. The browser builds
  and reads FIT files itself; this is the version your phone uses.
* `treadlab/*.py` — the original, now the reference implementation and the
  thing the test suites measure against.

`tests/make_golden.py` writes FIT files from the Python engine into
`treadlab/static/_test/golden/`; opening **`/_test/`** in the browser
rebuilds every one of them in JavaScript and compares them **byte for
byte** (including cases engineered to land on rounding boundaries, where
Python's round-half-to-even and JavaScript's round-half-up would otherwise
disagree — see `pyRound` in `engine/fitbase.js`). It also re-parses a real
2,700-record device file and checks every stream against Python's read of
it. Regenerate the goldens whenever the Python engine changes.

* `treadlab/fit_writer.py` — FIT encoder, based on FitLab's tested encoder,
  extended with multi-lap support and named sub-sports
  (`virtual_activity` = 58, `treadmill` = 1).
* `treadlab/fit_reader_lite.py` — dependency-free FIT parser for the HR
  merge (normal + compressed-timestamp headers, both endiannesses,
  developer fields, chained files; tolerant of truncation/bad CRC).
* `treadlab/merge.py` — the authoritative HR merge (nearest sample within
  5 s, carry-forward up to 10 s; 0/≥255 bpm treated as dropouts); cadence
  and temperature ride along with the matched sample.
* `treadlab/gps_loop.py` — the optional ocean map loop: an organic closed
  curve scaled so its perimeter equals the activity distance, positions
  assigned per record from the distance stream; two anchor venues
  (near-Watopia, Point Nemo), both open ocean.
* `treadlab/terrain.py` — anti-aliasing for FIT's 0.2 m altitude grid: a
  deterministic sub-meter undulation (grade-proportional, ≤0.3 m, zero on
  flat, endpoints pinned, climbs stay monotonic so ascent totals are
  exact) that stops Strava's grade/GAP smoothing from turning a perfectly
  constant incline into a zig-zag.
* `treadlab/server.py` — stdlib HTTP server, three endpoints
  (`/api/health`, `/api/parse-fit`, `/api/export`).
* `tests/selfcheck.py` — 108-check Python suite:
  `python-embed\python.exe tests\selfcheck.py`. Includes fitdecode
  strict-CRC cross-validation of generated files and a field-by-field
  comparison of the lite reader against fitdecode on a real sample file
  (those checks skip gracefully on a Python without fitdecode).
* `/_test/` in the browser — 41-check JavaScript suite, described above.
  Both suites should be green before shipping a change.
* `tools/make_icons.py` — regenerates the PWA icons (stdlib only; draws
  and antialiases the mountain glyph straight into PNG).

## Known limits / roadmap

* Page reload clears an un-exported activity (the plan itself is saved).
* Live mode: paused time is simply not recorded (timestamps stay
  continuous), and sub-second speed changes land on the next whole second.
* HR merge assumes both recordings run at the same clock rate (no
  stretching) — fine for "same run, two devices".
* Live Bluetooth HR needs a Chromium browser (Chrome/Edge, or Brave with
  its Web Bluetooth flag); it is unavailable on iOS entirely.
* Roadmap: mph units, per-lap drag-to-edit on the chart, GPX export,
  dark/light toggle. If the phone build ever needs live HR straps or
  Apple Health integration, that is the point at which a native wrapper
  (Capacitor + a $99/year Apple Developer account) starts to earn its
  keep — the web app would remain the same codebase inside it.
