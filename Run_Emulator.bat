@echo off
REM Log Emulator for MapReplay Live Testing
REM Usage: Drag and drop a log file onto this batch file, or run from command line

REM Load Python path from config file (if it exists)
if exist "%~dp0python_config.bat" (
    call "%~dp0python_config.bat"
) else (
    set PYTHON_PATH=
)

echo ============================================================
echo  Log Emulator for MapReplay Live Testing
echo ============================================================
echo.

REM Check if Python is configured
if "%PYTHON_PATH%"=="" (
    echo ERROR: Python is not configured yet.
    echo.
    echo Please run Start_MapReplay_Service.bat first.
    echo It will auto-detect Python and save the configuration.
    echo.
    pause
    exit /b 1
)

REM Check if Python exists at specified path
if not exist "%PYTHON_PATH%" (
    echo ERROR: Python not found at: %PYTHON_PATH%
    echo.
    echo Please edit Run_Emulator.bat and set PYTHON_PATH to your Python installation.
    echo Common locations:
    echo   E:\Anaconda\python.exe
    echo   C:\Python311\python.exe
    echo   C:\Users\YourName\AppData\Local\Programs\Python\Python311\python.exe
    echo.
    pause
    exit /b 1
)

echo Using Python: %PYTHON_PATH%
echo.

REM Check if a log file was provided
if "%~1"=="" (
    echo Usage: Drag and drop a log file onto this batch file
    echo    or: %~nx0 ^<log_file^> [speed]
    echo.
    echo Examples:
    echo   %~nx0 L20251214.log
    echo   %~nx0 L20251214.log 30
    echo   %~nx0 L20251214.log 60
    echo.
    pause
    exit /b 1
)

REM Set default speed if not provided
set SPEED=10
if not "%~2"=="" set SPEED=%~2

echo Input file: %~1
echo Speed: %SPEED%x
echo.

REM Get script directory
set SCRIPT_DIR=%~dp0

REM Run the emulator
cd /d "%SCRIPT_DIR%"
"%PYTHON_PATH%" Log_Emulator.py "%~1" --speed %SPEED% --select-game --clear-output

echo.
pause
