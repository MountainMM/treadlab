# What is in this folder, and how to check it is intact

TreadLab is meant to keep working for years with nothing installed and
nothing updated. This file records exactly what it is built from, so
that a future you — or a future computer — can tell whether this copy is
still the real thing.

Recorded **19 September 2026**, TreadLab **v0.5.0**.

---

## Checking this copy

```
python-embed\python.exe tools\verify.py
```

It compares every file against `checksums.sha256` and says either
"Everything matches" or exactly which files differ. Takes a second or
two over 323 files (23.6 MB).

`checksums.sha256` is in the ordinary `sha256sum` format, so it also
works with the tools already built into macOS and Linux, without needing
Python or this script at all:

```
sha256sum -c checksums.sha256        # Linux
shasum -a 256 -c checksums.sha256    # macOS
```

If you change something deliberately, re-record it with
`tools\verify.py --write`. `Publish.bat` does this for you.

**What the hashes do and do not prove.** They prove this folder is
byte-for-byte what it was on the date above — which is the failure that
actually happens to a drive left in a cupboard for five years, or a copy
that stopped half way. They are hashes of the files as deployed here,
not a comparison against python.org's published release hash: the folder
was modified after unpacking (see the `._pth` edit below), so no upstream
hash could match it anyway.

---

## Bundled Python

| | |
| --- | --- |
| Version | **3.13.6** (`tags/v3.13.6:4e66535`, 6 Aug 2025, MSC v.1944 64-bit) |
| Build | Windows x86-64 **embeddable package** |
| Source | https://www.python.org/downloads/release-python-3136/ |
| Location | `python-embed\` (388 files, ~27 MB) |
| In git? | **No** — see below |

Key file hashes (SHA-256):

```
91566dc8bb9a336c36c607ee0d5a5135e54ddce2418e2cd7728a49c8f098904a  python.exe
d55bfc311d20febe151563c2b6c121eccfe706136c03632f0f807b28558c0cb0  python313.zip
e84008229855396958b1ca16bdaca534b9c64d99e243cf2fa4b9ff60447d7dd3  python313._pth
```

### The one edit that matters

`python313._pth` was changed from the stock file to add the last line:

```
python313.zip
.
Lib\site-packages
```

Without `Lib\site-packages`, the embeddable Python cannot see any
installed package and imports fail in a confusing way. If you ever
rebuild this folder from a fresh python.org zip, **this is the step to
remember.**

### Why it is not on GitHub

`python-embed\` is in `.gitignore`. It is ~27 MB of redistributed
binaries, and TreadLab needs no packages at all to run, so anyone
cloning the repository can use their own Python. The consequence worth
knowing: **a `git clone` does not give you a runnable folder the way
copying the drive does.** `tools\verify.py` will report the whole of
`python-embed/` as missing in that case, which is expected, not damage.

---

## Bundled Python packages

In `python-embed\Lib\site-packages`:

| Package | Version | Used by TreadLab? |
| --- | --- | --- |
| fitdecode | 0.11.0 | **Tests only** — `tests\selfcheck.py` uses it as an independent decoder to strict-CRC-check the FIT files TreadLab writes |
| flask, jinja2, werkzeug, click, blinker, itsdangerous, markupsafe, gpxpy | (various) | **No** |

TreadLab's own code is **Python standard library only** — no third-party
imports anywhere in `treadlab\`, `run.py` or `tools\`.

The eight unused packages (~5 MB) came along when this folder's
`python-embed` was copied wholesale from the sibling FitLab project,
which does use Flask. They are inert: nothing imports them, and they
cost about 5 MB of a 30 MB folder. They are deliberately **left alone** —
deleting files from a working, verified runtime to reclaim 5 MB is a
poor trade.

---

## The app itself

TreadLab **v0.5.0**. The version appears in two places that must always
agree: `treadlab\__init__.py` and `treadlab\static\app.js`.

There are three copies of the same app, and they are all built from
`treadlab\static\`:

| Copy | What it needs | Notes |
| --- | --- | --- |
| **`TreadLab.bat`** (this folder) | the bundled Python, Windows | the normal one. Only copy with live Bluetooth HR support |
| **`TreadLab-any-computer.html`** | a web browser, nothing else | one self-contained file. Works from a USB stick on any OS, offline, no Python, no server. No Bluetooth (see below) |
| **https://mountainmm.github.io/treadlab/** | internet, once | installable on a phone. The same file is also downloadable there as `TreadLab-any-computer.html` |

`Publish.bat` rebuilds all three from source before every upload, so
they cannot drift apart.

### Why the single file has no Bluetooth

Browsers only allow Web Bluetooth in a "secure context" — `https://` or
`http://127.0.0.1`. A file opened directly from a drive is neither, so
`navigator.bluetooth` does not exist there and live HR-strap recording
is unavailable. Everything else works, including merging heart rate,
cadence and temperature from a watch's FIT file, which is the path that
gets used in practice. For the same reason the saved plan may not
survive a page reload in that copy.

### Third-party code in the app

None. No CDN, no fonts, no map tiles, no analytics, no network requests
of any kind at runtime — the app never calls out, which is why it works
offline and why it will still work when the services of 2026 are gone.
