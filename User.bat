@echo off
title Lattice — USER (submit code to AWS cluster)
cd /d "%~dp0"
echo.
echo  Friend setup: upload your Python job + CSV to the live AWS gateway.
echo  Same join token as workers. You appear as a user node on the console.
echo.
echo  Your train.py must define:
echo      def train_shard(header, rows, params) -^> dict
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\user_submit.ps1" %*
echo.
pause
