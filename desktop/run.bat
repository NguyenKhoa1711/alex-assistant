@echo off
chcp 65001 >nul
cd /d "%~dp0" 2>nul
start "" ".venv\Scripts\pythonw.exe" "launch.py"
