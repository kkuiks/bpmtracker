@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0apps\daw\scripts\start_windows.ps1"
if errorlevel 1 pause
