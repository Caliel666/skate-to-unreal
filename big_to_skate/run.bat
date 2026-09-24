@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if "%~1"=="" (
    echo.
    echo  Convert Skate 3 worldDIST_*.big -^> .skate
    echo.
    echo  Usage:
    echo    run.bat worldDIST_BlackBoxPark.big
    echo    run.bat worldDIST_BlackBoxPark.big -o .\skate_out
    echo    run.bat map.big -o .\out --engine C:\src\skate-3-rust-engine
    echo.
    echo  First time: clone the engine next to this folder or pass --engine
    echo    git clone https://github.com/SK8-ENGINE/skate-3-rust-engine.git
    echo.
    exit /b 1
)

set "VENV=%~dp0.venv"
set "REQ=%~dp0requirements.txt"

where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
    echo [error] Python 3 not found on PATH.
    exit /b 1
)

if not exist "%VENV%\Scripts\python.exe" (
    echo [setup] Creating .venv ...
    %PY% -m venv "%VENV%"
    if errorlevel 1 exit /b 1
)

"%VENV%\Scripts\pip.exe" install -q --upgrade pip
"%VENV%\Scripts\pip.exe" install -q -r "%REQ%"
if errorlevel 1 exit /b 1

echo [run] big_to_skate.py %*
"%VENV%\Scripts\python.exe" "%~dp0big_to_skate.py" %*
exit /b %ERRORLEVEL%
