@echo off
title HPC Grid — USER upload+run logistic regression
cd /d "%~dp0"
echo.
echo  USER path: upload train.py + CSV to the LIVE gateway, then run.
echo  Does NOT redeploy or restart AWS. Workers must already be connected.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\submit_logreg_job.ps1" %*
echo.
pause
