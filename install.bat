@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set "PY=py -3"
    ) else (
        echo Pyhton not found. Install Python 3.10+ first.
        pause
        exit /b 1
    )
)

%PY% install.py %*
if errorlevel 1 pause
