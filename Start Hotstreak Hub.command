#!/bin/sh
# Double-click this file in the Finder to start Hotstreak Hub.
#
# It opens a Terminal window, installs the two small Python extras if they are
# missing, sets everything up from your own game file the first time, and then
# opens the launcher. Nothing else is needed.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "This needs Python 3.9 or newer, and python3 is not installed."
  echo "Opening the download page - get the macOS installer, run it, then"
  echo "double-click this file again."
  open "https://www.python.org/downloads/" 2>/dev/null
  echo
  printf "Press Enter to close this window."
  read -r _
  exit 1
fi

python3 start.py "$@"
status=$?
if [ "$status" -ne 0 ]; then
  echo
  printf "Press Enter to close this window."
  read -r _
fi
exit "$status"
