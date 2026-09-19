"""Assemble the folder you publish to a web host.

    python-embed\\python.exe tools\\make_web_build.py          -> web\\
    python-embed\\python.exe tools\\make_web_build.py docs     -> docs\\

Copies treadlab/static/ into the output folder minus the developer-only
bits (the JS test suite and its ~1.6 MB of golden files), so what you
publish is just the app.

  web\\   for uploading by FTP to your own host (e.g. public_html/treadlab/)
  docs\\  for GitHub Pages, which can serve a repo's /docs folder directly.
          A .nojekyll file is always written so GitHub serves the files
          verbatim instead of running them through Jekyll.
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_single_file  # noqa: E402  (sibling tool, not an installed package)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "treadlab", "static")
DST = os.path.join(ROOT, sys.argv[1] if len(sys.argv) > 1 else "web")

# developer-only; harmless but pointless on a public host
EXCLUDE_DIRS = {"_test", "__pycache__"}


def main():
    if not os.path.isdir(SRC):
        sys.exit("cannot find %s" % SRC)
    if os.path.isdir(DST):
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST,
                    ignore=shutil.ignore_patterns(*EXCLUDE_DIRS))

    # GitHub Pages runs Jekyll unless told not to; Jekyll silently drops
    # files and folders whose names begin with an underscore. Harmless
    # elsewhere, so it is always written.
    open(os.path.join(DST, ".nojekyll"), "w").close()

    # The single-file offline copy ships alongside the normal app, so the
    # website and the USB/SSD copy each hold a spare of the other. Always
    # regenerated from source here -- never hand-edited, never stale.
    make_single_file.build(
        os.path.join(DST, make_single_file.DEFAULT_NAME), quiet=True)

    total = 0
    files = []
    for base, dirs, names in os.walk(DST):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for n in sorted(names):
            p = os.path.join(base, n)
            size = os.path.getsize(p)
            total += size
            files.append((os.path.relpath(p, DST), size))

    for rel, size in sorted(files):
        print("  %-34s %7s B" % (rel, format(size, ",")))
    print("\n  %d files, %.1f KB" % (len(files), total / 1024.0))

    missing = [f for f in ("index.html", "app.js", "sw.js", "manifest.json",
                           "icon-192.png", "icon-512.png",
                           "apple-touch-icon.png", ".htaccess", ".nojekyll",
                           make_single_file.DEFAULT_NAME)
               if not os.path.exists(os.path.join(DST, f))]
    if missing:
        print("\n  WARNING missing: %s" % ", ".join(missing))
    engine = os.path.join(DST, "engine")
    n_engine = len(os.listdir(engine)) if os.path.isdir(engine) else 0
    print("  engine modules: %d" % n_engine)

    if os.path.basename(DST) == "docs":
        print("\nGitHub Pages: commit and push docs/, then in the repo go to")
        print("  Settings -> Pages -> Source: 'Deploy from a branch'")
        print("  Branch: main   Folder: /docs")
        print("Your app appears at https://<user>.github.io/<repo>/")
    else:
        print("\nUpload the CONTENTS of this folder:")
        print("  %s" % DST)
        print("into a folder on your site, e.g. public_html/treadlab/")
        print("Then open https://yoursite.com/treadlab/ on your phone.")


if __name__ == "__main__":
    main()
