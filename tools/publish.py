"""Publish local changes to GitHub Pages in one step.

Normally run by double-clicking Publish.bat, but works directly too:

    python-embed\\python.exe tools\\publish.py "what I changed"
    python-embed\\python.exe tools\\publish.py --dry-run

Does, in order: check this folder has not been damaged, rebuild docs/
(the copy the website serves) and the single-file build, re-record
checksums.sha256, stage everything, show you exactly what will be
uploaded, ask for confirmation, commit, and push. The rebuild happens
first and always, so the live site can never fall behind the source.
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


def invisible_drift():
    """Manifest changes that the 'Changes to upload' list will NOT show.

    Anything git tracks turns up in that diff, so you can see it and judge
    it for yourself. Anything git IGNORES never appears there -- above all
    the 27 MB inside python-embed -- so without this check a byte quietly
    lost on the drive would be re-recorded as correct on the next publish,
    and checksums.sha256 would end up certifying the damage instead of
    catching it.

    Returns a list of (kind, path) for the invisible ones only.
    """
    if not os.path.isfile(os.path.join(ROOT, "checksums.sha256")):
        return []  # nothing recorded yet; nothing to compare against
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import verify

    recorded = verify.read_manifest()
    now = verify.scan()
    drift = ([("changed", p) for p in recorded if p in now and now[p] != recorded[p]]
             + [("missing", p) for p in recorded if p not in now]
             + [("new", p) for p in now if p not in recorded])
    if not drift:
        return []

    # Ask git which of these it ignores; those are the invisible ones.
    r = subprocess.run(("git", "-C", ROOT, "check-ignore", "--stdin"),
                       input="\n".join(sorted({p for _, p in drift})),
                       capture_output=True, text=True)
    ignored = set(r.stdout.split())
    return sorted((kind, p) for kind, p in drift if p in ignored)


def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    message = " ".join(a for a in argv if not a.startswith("--")).strip()

    if not os.path.isdir(os.path.join(ROOT, ".git")):
        sys.exit("  This folder isn't a git repository yet.")

    # 1. Before building anything FROM this folder, check the folder itself.
    rule("1. Checking this copy is intact")
    drift = invisible_drift()
    if not drift:
        print("  No unexplained changes.")
    else:
        print("  These files changed, and they will NOT appear in the list of")
        print("  changes further down, because git ignores them:\n")
        for kind, path in drift[:30]:
            print("    %-8s %s" % (kind, path))
        if len(drift) > 30:
            print("    ... and %d more" % (len(drift) - 30))
        print("\n  If you did not change these deliberately, this may be the")
        print("  drive losing data. Publishing now would record the damage as")
        print("  if it were correct. Stop, and compare against a known-good")
        print("  copy first.")
        if dry:
            print("\n  (dry run - stopping here)")
            return
        try:
            answer = input("\n  Type yes to publish anyway: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer != "yes":
            sys.exit("\n  Stopped. Nothing was committed or uploaded.")

    # 2. Rebuild the folder GitHub Pages serves -- never let it go stale.
    rule("2. Rebuilding docs\\ (the copy your website serves)")
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "make_web_build.py"), "docs"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("  build failed:\n" + r.stdout + r.stderr)
    for line in r.stdout.splitlines():
        if "files," in line:
            print("  " + line.strip())

    # The root single-file copy (the one that travels on the USB/SSD) is
    # rebuilt from the same source in the same breath as docs/, so the two
    # can never disagree about which version they are.
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "make_single_file.py")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("  single-file build failed:" + r.stdout + r.stderr)
    for line in r.stdout.splitlines():
        if "->" in line:
            print("  single file:%s" % line.split("->")[1].rstrip())

    # Re-record the integrity manifest last, so checksums.sha256 always
    # describes exactly what is being published (see VERSIONS.md).
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "verify.py"), "--write"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("  manifest update failed:" + r.stdout + r.stderr)
    for line in r.stdout.splitlines():
        if "recorded" in line:
            print("  " + line.strip())

    # 3. Stage everything and show what it amounts to.
    rule("3. Changes to upload")
    git("add", "-A")
    stat = git("diff", "--cached", "--stat")
    if not stat:
        print("  Nothing has changed since your last upload - nothing to do.")
        return
    for line in stat.splitlines():
        print("  " + line.strip())

    # 4. Confirm, then commit and push.
    if dry:
        rule("Dry run - stopping here")
        print("  Nothing was committed or uploaded.")
        git("reset", "-q")
        print("  (staging undone; your files are untouched)")
        return

    if not message:
        rule("4. Describe the change")
        print("  A short note so you can recognise this later,")
        print('  e.g. "added mph units" or "fixed the pace chart".')
        try:
            message = input("\n  > ").strip()
        except (EOFError, KeyboardInterrupt):
            message = ""
        if not message:
            git("reset", "-q")
            sys.exit("\n  No description given - nothing was uploaded.")

    rule("5. Saving a snapshot (commit)")
    git("commit", "-q", "-m", message)
    print("  " + git("log", "-1", "--format=%h  %s"))

    rule("6. Uploading to GitHub (push)")
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
