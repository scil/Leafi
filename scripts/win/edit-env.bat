@echo off
rem Open .env in VS Code (fallback: notepad). Creates .env from example if missing.
cd /d "%~dp0..\.."
if not exist .env copy .env.example .env
where code >nul 2>nul && (call code .env) || (start "" notepad .env)
