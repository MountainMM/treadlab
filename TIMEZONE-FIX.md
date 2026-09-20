# TreadLab — writing a real `local_timestamp`

**Status: DONE in v0.5.1, 20 September 2026.** Implemented, tested on both
engines, and verified against the consumer. This file is kept as the record of
why the bug existed, how it was fixed, and what to watch for if the writer is
ever touched again.

---

## What was wrong

FIT files carry no timezone field. Local time is encoded implicitly: the
`activity` message holds both `timestamp` (UTC, field 253) and `local_timestamp`
(field 5), and the **difference between them is the UTC offset**.

TreadLab wrote both with the same value:

```python
body += activity.data({253: _fit_ts(t1), 0: elapsed_ms, 1: 1, 2: 0,
                       3: 26, 4: 1, 5: _fit_ts(t1)})
```

Difference zero. Every TreadLab file therefore claimed "my local time is UTC".

**The absolute instant was always correct.** The start-time box is
`<input type="datetime-local">` and `fromLocalInput()` parses it with
`new Date(v)`, which reads a bare datetime string as browser-local and yields a
correct UTC epoch. Only the *offset label* was wrong.

## Why it mattered, and to whom

Only to **RunLog** (`C:\CM Data\Test_Folder\RunLog`), which builds the training
log CSV. RunLog does not trust a zero offset — it treats zero as "not encoded"
and falls back to the **host machine's** timezone (`runlog.py:95-105`), stamping
the row `tz_source = system`.

So a row was correct **if and only if you imported where you ran**. Break that
and the row was silently wrong, permanently: RunLog's merge preserves existing
rows and never recomputes them, and the `.fit` is usually deleted afterwards,
leaving the CSV as the only record.

Garmin files were never affected — the watch writes a real offset, so they land
as `tz_source = file` and are correct wherever they are imported.

## Measured before the fix, 20 September 2026

Run on a second PC set to **Auckland, UTC+12**. Both `.fit` files imported in a
single batch on that machine.

The raw CSVs are kept at `C:\CM Data\Test_Folder\Portable\treadlab-tz-test-evidence\`,
deliberately **outside this repository**: the Garmin row carries real GPS start
coordinates, this repo is public, and `tools/publish.py` stages with `git add -A`,
so anything left in the working tree gets committed.

| Field | UK (BST) | Auckland (UTC+12) |
| --- | --- | --- |
| `date` | 2026-09-20 | **2026-09-21** |
| `time_local` | 14:00 | **01:00** |
| `iso_week` | 2026-W38 | **2026-W39** |
| `weekday` | Sun | **Mon** |
| `tz_source` | system | system |

The Garmin file in the same import came back identical on both machines
(`2026-09-20 09:45`, `tz_source = file`), confirming that a real encoded offset
is entirely host-independent.

### The `iso_week` shift was the real cost

The fix was originally deferred on the basis of "an hour out, occasionally a
day". The measurement showed worse: `Summary.bat` reports year / month / **week**
totals, so a shifted activity **moves between training weeks and takes its
distance with it** — corrupting two weeks of totals at once, silently, in a file
that is the only record. That is what promoted the fix from "someday" to "now".

## What was changed

The offset travels as `utc_offset_s` in the **export request**, which is the
contract both engines already share. One field, five files:

| File | Change |
| --- | --- |
| `treadlab/fit_writer.py` | `utc_offset_s=0` parameter; field 5 becomes `_fit_ts(t1 + utc_offset_s)` |
| `treadlab/server.py` | reads `utc_offset_s` from the request, passes it through |
| `treadlab/static/engine/fit_writer.js` | `utcOffsetS = 0` option; same field 5 change |
| `treadlab/static/engine/index.js` | reads `req.utc_offset_s`, passes it through |
| `treadlab/static/app.js` | computes the offset and puts it in the payload |

**Default `0` everywhere**, which reproduces the old bytes exactly for any caller
that does not pass an offset. That is deliberate: the existing golden suite
becomes the regression check.

In `app.js` the offset is derived at the *activity's* instant, not at "now", so
a file built in one DST period for a run in another is still right:

```js
utc_offset_s: -new Date(startEpoch * 1000).getTimezoneOffset() * 60,
```

(`getTimezoneOffset()` counts minutes **west** of UTC, hence the negation.)

### Design constraint — do NOT read the machine timezone inside the writer

The trap, if this is ever revisited. If the Python engine called `astimezone()`
and the JS engine called `getTimezoneOffset()`, the two would produce
**different bytes on machines in different timezones** — destroying the
byte-identical parity TreadLab maintains, and making any golden test pass only
in the timezone it was generated in. The offset is passed **in**, so the writer
stays a pure function of its inputs.

### Where the source actually lives

`SRC = treadlab/static/`. `tools/make_web_build.py` does `shutil.rmtree(DST)`
then `copytree`, so **`docs/` and `web/` are generated and any edit made there is
destroyed.** Edit `treadlab/` and `treadlab/static/` only, then regenerate.

## Verification

| Check | Result |
| --- | --- |
| `tests/selfcheck.py` (Python) | 108 passed, 0 failed |
| `/_test/` browser suite (JS) | 42 passed, 0 failed |
| New `utc_offset` golden, both engines | **byte-identical (8160 B)** |
| Byte diff, offset 0 vs 3600 | differs only at 5763–5768 — field 5 and CRC |
| RunLog import of a fixed file | **`tz_source = file`**, correct local time |

A golden scenario named `utc_offset` (offset 3600) was added to
`tests/make_golden.py` specifically so the non-zero path is covered by the
Python/JS parity check. Regenerate goldens with
`python-embed\python.exe tests\make_golden.py`.

### Still outstanding

**Re-run on the Auckland PC with a file generated by the published app.** The
Python side is proven and `tz_source = file` means the host clock is provably
not consulted — but the `app.js` offset calculation is only exercised by a real
browser export. Acceptance: the row must read the **same UK wall-clock time that
was typed**, with `tz_source = file`.

If it still reads `system`, suspect a cached service worker before suspecting
the code — close the PWA fully and reopen.

## Release notes for next time

`tools/publish.py` rebuilds `docs/` and the single-file copy, re-records
`checksums.sha256` last, then commits and pushes to
`https://github.com/MountainMM/treadlab.git`.

Two things it does **not** do:

1. **It does not run the test suites.** Only integrity/checksum verification.
   Run `tests/selfcheck.py` and the `/_test/` page yourself before publishing.
2. **It does not bump `CACHE` in `treadlab/static/sw.js`.** That is a manual
   edit, documented in `sw.js` itself. **It was missed on the v0.5.0 release** —
   the constant still read `treadlab-v0.4.0` when v0.5.1 was being prepared.
   Stale-while-revalidate means a miss delays the update by one launch rather
   than breaking it, but bump it with the version every time.

## Rejected alternative

Pinning `Europe/London` in RunLog as the fallback timezone was considered and
**rejected on 20 Sep 2026**. It would have made the log deterministic, but it
would have broken the case that already worked — a run abroad imported abroad
would be rewritten into UK time. It also needs the `tzdata` wheel, since the
embedded Python raises `ZoneInfoNotFoundError` (Windows ships no IANA database).
**Do not implement it.** Fixing the offset at source is the only option that is
both correct and independent of where the file is imported.
