@echo off
setlocal
cd /d "%~dp0"

rem Check this copy of TreadLab is intact - nothing lost, nothing corrupted.
rem Double-click this after copying the folder to a USB stick or SSD, or any
rem time you want to be sure the drive has not quietly damaged it.
rem
rem Note the fallbacks below: if python-embed\ itself is the thing that got
rem damaged, this still runs using another Python and tells you so.

if exist "python-embed\python.exe" (
  "python-embed\python.exe" tools\verify.py %*
  goto :done
)
if exist "..\FitLab\python-embed\python.exe" (
  "..\FitLab\python-embed\python.exe" tools\verify.py %*
  goto :done
)
where py >nul 2>nul
if not errorlevel 1 (
  py tools\verify.py %*
  goto :done
)
where python >nul 2>nul
if not errorlevel 1 (
  python tools\verify.py %*
  goto :done
)

echo No Python found, so the checksums cannot be recalculated here.
echo On a Mac or Linux machine you can check this folder without Python:
echo   sha256sum -c checksums.sha256        ^(Linux^)
echo   shasum -a 256 -c checksums.sha256    ^(macOS^)

:done
echo.
pause
