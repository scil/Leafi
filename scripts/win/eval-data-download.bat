@echo off
rem Fetch the public reading-evaluation data (speechocean762, 520 MB, CC BY 4.0) into data\evals\ (plan M4.4a).
rem Skips what is present; never part of a plain doctor --download.
cd /d "%~dp0..\.."
.venv\Scripts\python.exe -m leafi doctor --download --only speechocean762
