"""Start TreadLab: `py run.py` (or double-click TreadLab.bat)."""

import argparse
import os
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser

# The bundled/borrowed python-embed interpreter runs in isolated-path mode
# and does not add this script's folder to sys.path; add it so `treadlab`
# is importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from treadlab.server import make_server


def find_brave():
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.expandvars(r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    try:
        import winreg
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\brave.exe"
                with winreg.OpenKey(root, key) as k:
                    path = winreg.QueryValueEx(k, None)[0]
                    if path and os.path.isfile(path):
                        return path
            except OSError:
                pass
    except ImportError:  # non-Windows
        pass
    return shutil.which("brave") or shutil.which("brave-browser")


def open_browser(url, prefer):
    if prefer == "brave":
        brave = find_brave()
        if brave:
            try:
                subprocess.Popen([brave, url])
                return
            except OSError:
                pass
        print("  (Brave not found -- opening your default browser instead)")
    webbrowser.open(url)


def free_port(start):
    for port in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("no free port found")


def main():
    ap = argparse.ArgumentParser(description="TreadLab local server")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--no-browser", action="store_true",
                    help="don't open the browser automatically")
    ap.add_argument("--browser", choices=["brave", "default"], default="brave",
                    help="which browser to open (default: brave, falling back "
                         "to the system browser if Brave isn't installed). "
                         "Tip: live Bluetooth HR needs Chrome/Edge, or Brave "
                         "with its Web Bluetooth flag enabled.")
    args = ap.parse_args()

    port = free_port(args.port)
    url = "http://127.0.0.1:%d/" % port
    print("\n  TreadLab running at %s  (Ctrl+C to stop)\n" % url)
    if not args.no_browser:
        threading.Timer(1.0, open_browser, args=(url, args.browser)).start()
    try:
        make_server(port).serve_forever()
    except KeyboardInterrupt:
        print("  bye")


if __name__ == "__main__":
    main()
