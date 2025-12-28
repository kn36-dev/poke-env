@echo off
REM Batch wrapper for bot_matches.py — forwards args to the Python script in the repo root.
REM Usage: scripts\bot-matches.bat --mode queue --n-battles 1

:: Resolve repo root from script location (this file is in scripts\)
set SCRIPT_DIR=%~dp0
set REPO_ROOT=%SCRIPT_DIR%..\
set REPO_ROOT=%REPO_ROOT:~0,-1%

:: Prefer repo-local .venv if present
set VENV_PY=%REPO_ROOT%\.venv\Scripts\python.exe
if exist "%VENV_PY%" (
    set PYTHON=%VENV_PY%
) else (
    set PYTHON=python
)
echo Running bot_matches.py with args %* using %PYTHON%
%PYTHON% "%REPO_ROOT%\bot_matches.py" %*
exit /b %ERRORLEVEL%
