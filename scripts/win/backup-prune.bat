@echo off
rem Delete all but the newest 3 backups in data\backups (owner decision 2026-10-23; migration backups included).
rem Backups keep data that forget removed from leafi.db, so pruning is also how a forget reaches them.
cd /d "%~dp0..\.."
.venv\Scripts\python.exe -m leafi backup --prune
