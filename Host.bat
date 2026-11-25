@echo off
title HPC Grid — HOST
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\host.ps1"
echo.
pause
