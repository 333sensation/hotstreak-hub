@echo off
rem Windows: start the roster launcher.
rem   run.cmd            open the window
rem   run.cmd --check    report what this machine is missing
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  set PY=py -3
) else (
  set PY=python
)

%PY% -c "import tkinter" 2>nul
if errorlevel 1 (
  echo tkinter is missing. Reinstall Python from python.org with "tcl/tk and IDLE" checked.
  pause
  exit /b 1
)

%PY% -c "import PIL" 2>nul
if errorlevel 1 (
  echo Pillow is missing. Install it with: %PY% -m pip install pillow
  pause
  exit /b 1
)

%PY% SkylandersLauncher.py %*
if errorlevel 1 pause
endlocal
