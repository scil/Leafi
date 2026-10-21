@echo off
rem Show one test toast the way Leafi alerts appear (ADR-0016); nothing is sent off the PC
cd /d "%~dp0..\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\win\toast.ps1 -Title "Leafi" -Body "Test: Leafi alerts appear like this."
if errorlevel 1 (echo [X] toast failed) else (echo [OK] toast shown; if you saw nothing, check Settings ^> Notifications ^> Windows PowerShell)
