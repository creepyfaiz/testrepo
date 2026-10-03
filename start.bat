@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel% equ 0 (
    python auto_repo.py
    goto :done
)

where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 auto_repo.py
    goto :done
)

echo [!] Python is not installed.
echo Please install Python from https://www.python.org/

:done
pause
