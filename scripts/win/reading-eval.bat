@echo off
rem Reading evaluation on speechocean762 (ADR-0013 false-alarm budget; plan M4.4a, TD-28): about 11 minutes,
rem offline, silent. Extra arguments pass through (e.g. --max-age 12, --limit 100). Results also go to
rem data\evals\results\.
cd /d "%~dp0..\.."
.venv\Scripts\python.exe scripts\evals\reading_eval.py --set speechocean762 %*
