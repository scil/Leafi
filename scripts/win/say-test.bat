@echo off
rem Real speaker test: speaks an English test sentence through the camera speaker
cd /d "%~dp0..\.."
.venv\Scripts\python -m agent.main --say "Hello! Rocco!This is your coach speaking. If you can hear me loud and clear, the speaker test is a big success!" --voice en-US-JennyNeural
pause
