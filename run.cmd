@echo off
rem Windows: start the roster launcher (the real work is in launcher\run.cmd).
rem   run.cmd              open the window
rem   run.cmd --check      report what this machine is missing
call "%~dp0launcher\run.cmd" %*
