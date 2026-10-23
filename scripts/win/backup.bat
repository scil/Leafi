@echo off
rem Consistent copy of data\leafi.db to data\backups\leafi-<UTC time>.db through SQLite's backup API (ADR-0019 section 8);
rem never copy the file by hand. Works at any schema version and beside running services (a shared lock).
cd /d "%~dp0..\.."
.venv\Scripts\python.exe -m leafi backup
