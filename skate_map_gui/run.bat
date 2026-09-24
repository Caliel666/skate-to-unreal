@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================
echo  Skate 3 Map -^> Unreal  (GUI)
echo ============================================
echo.

where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
    echo [error] Python 3 not found. Install from https://www.python.org/downloads/
    echo         Enable "Add python.exe to PATH".
    pause
    exit /b 1
)

set "VENV=%~dp0.venv"
if not exist "%VENV%\Scripts\python.exe" (
    echo [setup] Creating virtual environment...
    %PY% -m venv "%VENV%"
    if errorlevel 1 (
        echo [error] Could not create venv.
        pause
        exit /b 1
    )
)

echo [setup] Installing dependencies...
"%VENV%\Scripts\pip.exe" install -q --upgrade pip
"%VENV%\Scripts\pip.exe" install -q -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo [error] pip install failed.
    pause
    exit /b 1
)

rem Expect sibling folders: big_to_skate and skate_to_unreal
if not exist "%~dp0..\big_to_skate\big_to_skate.py" (
    if not exist "%~dp0big_to_skate\big_to_skate.py" (
        echo [warn] big_to_skate.py not found next to this app.
        echo        Keep the big_to_skate folder beside skate_map_gui.
    )
)
if not exist "%~dp0..\skate_to_unreal\convert_skate_to_ue.py" (
    if not exist "%~dp0skate_to_unreal\convert_skate_to_ue.py" (
        echo [warn] convert_skate_to_ue.py not found next to this app.
        echo        Keep the skate_to_unreal folder beside skate_map_gui.
    )
)

echo.
echo [run] Starting GUI...
echo.
"%VENV%\Scripts\python.exe" "%~dp0app.py"
if errorlevel 1 (
    echo.
    echo [error] App exited with an error.
    pause
)
exit /b %ERRORLEVEL%
