@echo off
title HPC Grid — Submit logistic regression job (USER)
cd /d "%~dp0"
echo.
echo  USER submit: examples\logistic_regression\job.yaml + dataset
echo  Does NOT redeploy AWS. Platform must already be running.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\submit_logreg_job.ps1" %*
echo.
pause
