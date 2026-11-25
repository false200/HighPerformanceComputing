@echo off
title HPC Grid — CONNECT
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\connect.ps1" %*
echo.
pause
