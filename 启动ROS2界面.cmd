@echo off
cd /d "%~dp0"
wsl.exe -d Ubuntu-22.04 --cd "%~dp0." -- bash start.sh
pause
