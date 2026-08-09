@echo off
rem Open the action editor UI (writes config/tasks.yml); Ctrl+C in this window to stop
cd /d "%~dp0..\.."
.venv\Scripts\python -m agent.webui
pause
