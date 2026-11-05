@echo off
chcp 65001 >nul
cd /d "%~dp0" 2>nul
if not exist "launch.py" cd /d "D:\HCTP~2\TRLO-L~1\outputs\Bionic-pet"
start "" ".venv\Scripts\pythonw.exe" "launch.py"
