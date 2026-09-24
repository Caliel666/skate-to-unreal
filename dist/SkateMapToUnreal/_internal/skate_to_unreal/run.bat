@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem =============================================================================
rem  skate → Unreal converter launcher
rem  Usage:
rem    run.bat BlackBoxPark.skate -o .\export
rem    run.bat "C:\maps\MyPark.skate" -o "D:\UE\Content\SkateMaps"
rem =============================================================================

cd /d "%~dp0"

set "PYTHON_OK="
set "VENV_DIR=%~dp0.venv"
set "REQ=%~dp0requirements.txt"
set "CONVERTER=%~dp0convert_skate_to_ue.py"

if "%~1"=="" (
    echo.
    echo  Usage:  run.bat ^<map.skate^> [options]
    echo.
    echo  Examples:
    echo    run.bat BlackBoxPark.skate
    echo    run.bat BlackBoxPark.skate -o .\export
    echo    run.bat "C:\games\maps\Park.skate" -o .\export --keep-lightmaps
    echo.
    echo  Options are passed through to convert_skate_to_ue.py
    echo    -o / --output DIR     Output root ^(default: .\export^)
    echo    --keep-lightmaps      Also export lightmap textures
    echo.
    exit /b 1
)

rem --- find Python ---
where py >nul 2>&1 && set "PY_CMD=py -3"
if not defined PY_CMD (
    where python >nul 2>&1 && set "PY_CMD=python"
)
if not defined PY_CMD (
    echo [error] Python 3 not found on PATH.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo and check "Add python.exe to PATH".
    exit /b 1
)

rem --- create / reuse virtual environment ---
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [setup] Creating virtual environment in .venv ...
    %PY_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [error] Failed to create venv.
        exit /b 1
    )
)

set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"

echo [setup] Ensuring dependencies ...
"%VENV_PIP%" install --upgrade pip >nul 2>&1
"%VENV_PIP%" install -r "%REQ%"
if errorlevel 1 (
    echo [error] pip install failed.
    exit /b 1
)

rem --- default -o .\export if user did not pass -o / --output ---
set "HAS_OUTPUT="
set "ARGS="
:parse
if "%~1"=="" goto parsed
if /I "%~1"=="-o" set "HAS_OUTPUT=1"
if /I "%~1"=="--output" set "HAS_OUTPUT=1"
set "ARGS=!ARGS! %1"
shift
goto parse
:parsed

if not defined HAS_OUTPUT (
    set "ARGS=!ARGS! -o .\export"
)

echo.
echo [run] "%VENV_PY%" "%CONVERTER%" !ARGS!
echo.
"%VENV_PY%" "%CONVERTER%" !ARGS!
if errorlevel 1 (
    echo.
    echo [error] Conversion failed.
    exit /b 1
)

rem --- locate the newest / expected export folder ---
set "OUT_DIR="
rem Try to pick map name from first .skate argument for a friendlier path
for %%A in (!ARGS!) do (
    echo %%A | findstr /I /C:".skate" >nul && set "SKATE_FILE=%%~A"
)
if defined SKATE_FILE (
    for %%F in ("!SKATE_FILE!") do set "MAP_STEM=%%~nF"
)

rem Scan ARGS for -o value
set "PREV="
for %%A in (!ARGS!) do (
    if /I "!PREV!"=="-o" set "OUT_DIR=%%~A"
    if /I "!PREV!"=="--output" set "OUT_DIR=%%~A"
    set "PREV=%%A"
)
if not defined OUT_DIR set "OUT_DIR=.\export"

rem Resolve map export folder
set "MAP_OUT=%OUT_DIR%"
if defined MAP_STEM (
    if exist "%OUT_DIR%\%MAP_STEM%\" set "MAP_OUT=%OUT_DIR%\%MAP_STEM%"
)

echo.
echo =============================================================================
echo  Conversion finished.
echo  Export folder: %MAP_OUT%
echo =============================================================================
echo.

if exist "%MAP_OUT%\import_to_unreal.py" (
    echo  Unreal Engine 5.4 import script is ready:
    echo    %MAP_OUT%\import_to_unreal.py
    echo.
    echo  The import script must run INSIDE the Unreal Editor
    echo  ^(Python Editor Script Plugin^), not from this batch file.
    echo.
    choice /C YN /M "Open the export folder in Explorer"
    if errorlevel 2 goto after_open
    if errorlevel 1 explorer "%MAP_OUT%"
    :after_open
    echo.
    choice /C YN /M "Show Unreal import steps now"
    if errorlevel 2 goto end
    if errorlevel 1 goto show_ue_help
) else (
    echo  [warn] import_to_unreal.py not found under %MAP_OUT%
    choice /C YN /M "Open the export folder in Explorer"
    if errorlevel 2 goto end
    if errorlevel 1 explorer "%MAP_OUT%"
    goto end
)

:show_ue_help
echo.
echo  ---------------------------------------------------------------------------
echo   Unreal Engine 5.4.4 — automatic material import
echo  ---------------------------------------------------------------------------
echo.
echo   1. Copy the folder:
echo        %MAP_OUT%
echo      into your project, for example:
echo        ^<Project^>\Content\%MAP_STEM%\
echo.
echo   2. Edit -^> Plugins -^> enable "Python Editor Script Plugin"
echo      ^(restart the editor if it asks^).
echo.
echo   3. Run with ONE of these methods:
echo.
echo      A^) Easiest:  File -^> Execute Python Script
echo         then select import_to_unreal.py in the folder you copied.
echo.
echo      B^) Output Log — py command + FORWARD SLASHES
echo         ^(backslash \U in \Users is a Python unicode escape and fails^):
echo.
echo         py "C:/Users/Demuriel/Documents/Unreal Projects/rolloutskatemaps/Content/BlackBoxPark/import_to_unreal.py"
echo.
echo         Do NOT use:  exec^(open^(...^).read^(^)^)   ^<-- deprecated in UE 5.4
echo         Do NOT use:  python "C:\Users\..."       ^<-- \U breaks the path
echo.
echo   The script will:
echo      - create master material  /Game/SkateMaps/_Shared/M_Skate_Master
echo      - import textures ^(albedo sRGB, normals TC_Normalmap^)
echo      - create Material Instances and assign textures
echo      - import mesh.glb and assign materials to slots
echo.
echo   No lightmaps are imported — light the map inside Unreal.
echo  ---------------------------------------------------------------------------
echo.

:end
echo Done.
endlocal
exit /b 0
