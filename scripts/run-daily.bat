@echo off
rem Collect listings, score them, and update the phone app. Used by Task Scheduler.
cd /d "%~dp0.."
if not exist data mkdir data
echo ==== %date% %time% ==== >> data\run.log
py -m homefinder run >> data\run.log 2>&1
