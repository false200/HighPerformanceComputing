@echo off
title Lattice — WORKER (join AWS cluster)
cd /d "%~dp0"
echo.
echo  Friend setup: donate this PC's CPU/RAM to the live AWS gateway.
echo  You will be asked for: gateway IP (if unknown), join token, your name,
echo  and how much CPU / RAM / GPU to share.
echo.
echo  Keep Worker.bat open while you want to stay connected.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\worker_join.ps1" %*
echo.
pause
