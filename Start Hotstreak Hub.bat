@echo off
rem Double-click this file to start Hotstreak Hub.
rem
rem It installs the two small Python extras if they are missing, sets everything
rem up from your own game file the first time, and then opens the launcher.
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  set "PY=python"
)

%PY% -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo This needs Python 3.9 or newer, and Python was not found.
  echo Opening the download page - install it with "Add python.exe to PATH"
  echo ticked, then double-click this file again.
  start "" "https://www.python.org/downloads/"
  pause
  exit /b 1
)

%PY% start.py %*
if errorlevel 1 pause
endlocal
