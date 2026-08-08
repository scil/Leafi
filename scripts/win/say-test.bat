@echo off
rem Real speaker test: pushes TTS to the camera speaker via go2rtc (.env creds required)
cd /d "%~dp0..\.."
.venv\Scripts\python -m agent.main --now brush_pm
pause
