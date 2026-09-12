@echo off
setlocal
cd /d "%~dp0"

rem Publish your changes to https://mountainmm.github.io/treadlab/
rem Double-click this file after editing anything in the project.

if exist "python-embed\python.exe" (
  "python-embed\python.exe" tools\publish.py %*
  goto :done
)
if exist "..\FitLab\python-embed\python.exe" (
  "..\FitLab\python-embed\python.exe" tools\publish.py %*
  goto :done
)
where py >nul 2>nul
if not errorlevel 1 (
  py tools\publish.py %*
  goto :done
)
where python >nul 2>nul
if not errorlevel 1 (
  python tools\publish.py %*
  goto :done
)

echo Python was not found on this PC.
echo TreadLab normally bundles it in python-embed\ - if that folder was
echo deleted, restore it or install Python from https://www.python.org/downloads/

:done
echo.
pause
