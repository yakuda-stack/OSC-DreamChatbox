@echo off
REM ------------------------------------------------------------------
REM  build-exe.bat - double-click wrapper around build-exe.ps1
REM  Same result as running the PowerShell script by hand; this just
REM  spares you the execution-policy dance.
REM
REM  Pass-through switches work too, e.g.:
REM      build-exe.bat -OneFile -NoConsole
REM ------------------------------------------------------------------
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-exe.ps1" %*
echo.
pause
