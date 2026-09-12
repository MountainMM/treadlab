"""Publish local changes to GitHub Pages in one step.

Normally run by double-clicking Publish.bat, but works directly too:

    python-embed\\python.exe tools\\publish.py "what I changed"
    python-embed\\python.exe tools\\publish.py --dry-run

Does, in order: rebuild docs/ (the copy the website serves), stage
everything, show you exactly what will be uploaded, ask for confirmation,
commit, and push. The rebuild happens first and always, so the live site
can never fall behind the source.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_URL = "https://mountainmm.github.io/treadlab/"


def git(*args, check=True):
    """Run a git command inside the project, return its stdout."""
    r = subprocess.run(("git", "-C", ROOT) + args,
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit("\n  git %s failed:\n%s%s" % (" ".join(args), r.stdout, r.stderr))
    return r.stdout.strip()


def rule(title):
    print("\n" + title)
    print("-" * max(34, len(title)))


def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    message = " ".join(a for a in argv if not a.startswith("--")).strip()

    if not os.path.isdir(os.path.join(ROOT, ".git")):
        sys.exit("  This folder isn't a git repository yet.")

    # 1. Rebuild the folder GitHub Pages serves -- never let it go stale.
    rule("1. Rebuilding docs\\ (the copy your website serves)")
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "make_web_build.py"), "docs"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("  build failed:\n" + r.stdout + r.stderr)
    for line in r.stdout.splitlines():
        if "files," in line:
            print("  " + line.strip())

    # 2. Stage everything and show what it amounts to.
    rule("2. Changes to upload")
    git("add", "-A")
    stat = git("diff", "--cached", "--stat")
    if not stat:
        print("  Nothing has changed since your last upload - nothing to do.")
        return
    for line in stat.splitlines():
        print("  " + line.strip())

    # 3. Confirm, then commit and push.
    if dry:
        rule("Dry run - stopping here")
        print("  Nothing was committed or uploaded.")
        git("reset", "-q")
        print("  (staging undone; your files are untouched)")
        return

    if not message:
        rule("3. Describe the change")
        print("  A short note so you can recognise this later,")
        print('  e.g. "added mph units" or "fixed the pace chart".')
        try:
            message = input("\n  > ").strip()
        except (EOFError, KeyboardInterrupt):
            message = ""
        if not message:
            git("reset", "-q")
            sys.exit("\n  No description given - nothing was uploaded.")

    rule("4. Saving a snapshot (commit)")
    git("commit", "-q", "-m", message)
    print("  " + git("log", "-1", "--format=%h  %s"))

    rule("5. Uploading to GitHub (push)")
    r = subprocess.run(("git", "-C", ROOT, "push"),
                       capture_output=True, text=True)
    if r.returncode != 0:
        print((r.stdout + r.stderr).strip())
        print("\n  Upload failed. Your work is safely committed on this PC -")
        print("  fix the problem above and run this again to retry the upload.")
        sys.exit(1)

    print("  done.")
    rule("Published")
    print("  Your site updates within a minute or so:")
    print("  " + LIVE_URL)
    print("\n  Already installed on a phone? It picks up the new version")
    print("  the next time you open it (sometimes the launch after).")


if __name__ == "__main__":
    main()
