@echo off
setlocal
cd /d "%~dp0"

rem TreadLab needs no third-party packages - any Python 3.8+ works.

rem 1) A python-embed bundled inside THIS folder (added later, FitLab recipe).
if exist "python-embed\python.exe" (
  "python-embed\python.exe" run.py
  pause
  exit /b
)

rem 2) Borrow the sibling FitLab's bundled Python - zero installs needed.
if exist "..\FitLab\python-embed\python.exe" (
  "..\FitLab\python-embed\python.exe" run.py
  pause
  exit /b
)

rem 3) An installed Python.
where py >nul 2>nul
if not errorlevel 1 (
  py run.py
  pause
  exit /b
)
where python >nul 2>nul
if not errorlevel 1 (
  python run.py
  pause
  exit /b
)

echo Python was not found on this PC.
echo Either keep this folder next to your FitLab folder (TreadLab can use
echo FitLab's bundled Python), or install Python free from
echo https://www.python.org/downloads/ then double-click TreadLab.bat again.
pause
exit /b 1
