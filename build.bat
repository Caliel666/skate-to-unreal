@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo  Build SkateMapToUnreal.exe  (one-folder shareable package)
echo ============================================================
echo.
echo  Layout expected:
echo    %~dp0skate_map_gui\
echo    %~dp0big_to_skate\
echo    %~dp0skate_to_unreal\
echo.

if not exist "%~dp0skate_map_gui\app.py" (
    echo [error] skate_map_gui\app.py not found next to this build.bat
    pause
    exit /b 1
)
if not exist "%~dp0big_to_skate\big_to_skate.py" (
    echo [error] big_to_skate\big_to_skate.py not found
    pause
    exit /b 1
)
if not exist "%~dp0skate_to_unreal\convert_skate_to_ue.py" (
    echo [error] skate_to_unreal\convert_skate_to_ue.py not found
    pause
    exit /b 1
)

where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
    echo [error] Python 3 not found on PATH.
    pause
    exit /b 1
)

set "VENV=%~dp0.build_venv"
if not exist "%VENV%\Scripts\python.exe" (
    echo [setup] Creating build venv...
    %PY% -m venv "%VENV%"
    if errorlevel 1 (
        echo [error] venv failed
        pause
        exit /b 1
    )
)

echo [setup] Installing PyInstaller + app deps...
"%VENV%\Scripts\pip.exe" install -q --upgrade pip
"%VENV%\Scripts\pip.exe" install -q pyinstaller numpy Pillow
if errorlevel 1 (
    echo [error] pip install failed
    pause
    exit /b 1
)

set "DIST=%~dp0dist\SkateMapToUnreal"
set "WORK=%~dp0build_pyinstaller"
if exist "%DIST%" rmdir /s /q "%DIST%"
if exist "%WORK%" rmdir /s /q "%WORK%"

echo.
echo [build] Running PyInstaller (windowed, onedir)...
echo.

"%VENV%\Scripts\pyinstaller.exe" ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --name "SkateMapToUnreal" ^
    --distpath "%~dp0dist" ^
    --workpath "%WORK%" ^
    --specpath "%WORK%" ^
    --paths "%~dp0skate_map_gui" ^
    --hidden-import=numpy ^
    --hidden-import=PIL ^
    --hidden-import=PIL.Image ^
    --collect-all numpy ^
    --collect-all PIL ^
    --add-data "%~dp0big_to_skate;big_to_skate" ^
    --add-data "%~dp0skate_to_unreal;skate_to_unreal" ^
    "%~dp0skate_map_gui\app.py"

if errorlevel 1 (
    echo.
    echo [error] PyInstaller failed.
    pause
    exit /b 1
)

rem Ensure sibling tools are also beside the exe (easier for subprocess + users)
if not exist "%DIST%\big_to_skate" xcopy /e /i /y "%~dp0big_to_skate" "%DIST%\big_to_skate" >nul
if not exist "%DIST%\skate_to_unreal" xcopy /e /i /y "%~dp0skate_to_unreal" "%DIST%\skate_to_unreal" >nul

rem Drop a short readme for end users
(
echo Skate 3 Map to Unreal
echo =====================
echo.
echo 1. Double-click SkateMapToUnreal.exe
echo 2. Select your Xbox 360 Skate 3 ISO
echo 3. Click Extract ISO  ^(downloads extract-xiso automatically^)
echo 4. Pick a map, set output folders, Convert
echo 5. In Unreal: Tools -^> Execute Python Script -^> import_to_unreal.py
echo.
echo Requirements on the PC:
echo   - Windows 10/11 64-bit
echo   - Git for Windows  ^(first map convert clones the engine^)
echo   - Internet  ^(first run downloads extract-xiso + clones engine^)
echo.
echo Runtime data is stored in the "runtime" folder next to this exe.
) > "%DIST%\README.txt"

echo.
echo ============================================================
echo  BUILD OK
echo.
echo  Share this folder:
echo    %DIST%\
echo.
echo  Contents: SkateMapToUnreal.exe + tools + README.txt
echo ============================================================
echo.
pause
exit /b 0
