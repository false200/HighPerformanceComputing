@echo off
title HPC Grid — Submit Job
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\submit_job.ps1" %*
echo.
pause
