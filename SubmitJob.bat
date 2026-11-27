@echo off
title HPC Grid — USER Submit (to existing AWS / master)
cd /d "%~dp0"
echo.
echo  You are a USER of the cluster — not a worker.
echo  This only submits a job to the already-running platform.
echo  It does NOT redeploy AWS / EC2.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\submit_job.ps1" %*
echo.
pause
