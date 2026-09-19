r"""Check that this TreadLab folder is exactly as it was when published.

    python-embed\python.exe tools\verify.py            check the folder
    python-embed\python.exe tools\verify.py --write    record it as correct

Why this exists: TreadLab is meant to live on a USB stick or external SSD
for years and still work when plugged into some future computer. The
realistic way that fails is not software going out of date -- it is the
drive quietly losing a byte, or a copy that stopped half way through.
This tells you in one run whether the folder is intact.

It writes `checksums.sha256` in the ordinary sha256sum format, so even
if this script is useless on some future machine you can still check the
folder with the tools built into macOS or Linux:

    sha256sum -c checksums.sha256      (Linux)
    shasum -a 256 -c checksums.sha256  (macOS)

Skipped: .git, __pycache__, generated test fixtures, the web/ FTP build
-- everything that is rebuilt on demand and would only create noise.
"""

import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "checksums.sha256")

SKIP_DIRS = {".git", "__pycache__", "web", ".vscode", ".idea"}
SKIP_RELS = {"treadlab/static/_test/golden"}
SKIP_FILES = {"checksums.sha256", "Thumbs.db", "desktop.ini", ".DS_Store"}


def walk():
    """Every file worth checking, as repo-relative forward-slash paths."""
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        rel_dir = os.path.relpath(base, ROOT).replace(os.sep, "/")
        if rel_dir == ".":
            rel_dir = ""
        if any(rel_dir == s or rel_dir.startswith(s + "/") for s in SKIP_RELS):
            dirs[:] = []
            continue
        for name in sorted(names):
            if name in SKIP_FILES:
                continue
            yield ("%s/%s" % (rel_dir, name)).lstrip("/")


def digest(rel):
    h = hashlib.sha256()
    with open(os.path.join(ROOT, rel.replace("/", os.sep)), "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan():
    return {rel: digest(rel) for rel in walk()}


def write():
    now = scan()
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as fh:
        for rel in sorted(now):
            fh.write("%s  %s\n" % (now[rel], rel))
    total = sum(os.path.getsize(os.path.join(ROOT, r.replace("/", os.sep)))
                for r in now)
    print("  recorded %d files (%.1f MB) -> checksums.sha256"
          % (len(now), total / 1048576.0))


def read_manifest():
    recorded = {}
    with open(MANIFEST, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            h, _, rel = line.partition("  ")
            recorded[rel] = h
    return recorded


def check():
    if not os.path.isfile(MANIFEST):
        sys.exit("  No checksums.sha256 here yet. Create one with:\n"
                 r"    python-embed\python.exe tools\verify.py --write")
    recorded = read_manifest()
    now = scan()

    changed = sorted(r for r in recorded if r in now and now[r] != recorded[r])
    missing = sorted(r for r in recorded if r not in now)
    added = sorted(r for r in now if r not in recorded)

    print("\n  checked %d files against checksums.sha256\n" % len(recorded))
    if not (changed or missing or added):
        print("  Everything matches. This copy is intact.\n")
        return 0

    if changed:
        print("  CHANGED (%d) -- these files are not what they were:" % len(changed))
        for r in changed[:40]:
            print("    %s" % r)
        if len(changed) > 40:
            print("    ... and %d more" % (len(changed) - 40))
    if missing:
        print("\n  MISSING (%d):" % len(missing))
        for r in missing[:40]:
            print("    %s" % r)
        if len(missing) > 40:
            print("    ... and %d more" % (len(missing) - 40))
        if any(r.startswith("python-embed/") for r in missing):
            print("\n    Lots of python-embed/ files missing usually means you")
            print("    downloaded this from GitHub rather than copying the")
            print("    folder. That is expected -- the bundled Python is not")
            print("    stored on GitHub. See VERSIONS.md.")
    if added:
        print("\n  NEW since the manifest (%d):" % len(added))
        for r in added[:40]:
            print("    %s" % r)
        if len(added) > 40:
            print("    ... and %d more" % (len(added) - 40))

    print("\n  If you changed these on purpose, re-record with --write.\n")
    return 1


def main():
    if "--write" in sys.argv[1:]:
        write()
        return 0
    return check()


if __name__ == "__main__":
    sys.exit(main())
