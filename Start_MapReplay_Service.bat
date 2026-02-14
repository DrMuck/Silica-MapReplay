@echo off
setlocal enabledelayedexpansion

REM MapReplay Live Service Launcher
REM This script starts the real-time replay generation service
REM On first run, it will ask for Python path and install required packages

echo ============================================================
echo  MapReplay Live Service
echo  Real-time game replay generation for Silica Dedicated Server
echo ============================================================
echo.

REM Load Python path from config file (if it exists)
if exist "%~dp0python_config.bat" (
    call "%~dp0python_config.bat"
) else (
    set PYTHON_PATH=
)

REM ============================================================
REM FIRST RUN SETUP - Auto-detect Python, then ask if not found
REM ============================================================
if "%PYTHON_PATH%"=="" (
    echo.
    echo  FIRST TIME SETUP
    echo  ================
    echo.
    echo  Searching for Python installation...
    echo.
    
    set FOUND_PYTHON=
    
    REM --- Method 1: Check system PATH ---
    where python >nul 2>&1
    if not errorlevel 1 (
        for /f "tokens=*" %%p in ('where python 2^>nul') do (
            if not defined FOUND_PYTHON (
                REM Verify it's real Python (not Windows Store stub)
                "%%p" --version >nul 2>&1
                if not errorlevel 1 (
                    set "FOUND_PYTHON=%%p"
                    echo  [FOUND] %%p  (system PATH^)
                )
            )
        )
    )
    
    REM --- Method 2: Check 'py' launcher ---
    if not defined FOUND_PYTHON (
        where py >nul 2>&1
        if not errorlevel 1 (
            for /f "tokens=*" %%p in ('py -c "import sys; print(sys.executable)" 2^>nul') do (
                if not defined FOUND_PYTHON (
                    set "FOUND_PYTHON=%%p"
                    echo  [FOUND] %%p  (py launcher^)
                )
            )
        )
    )
    
    REM --- Method 3: Check common installation directories ---
    if not defined FOUND_PYTHON (
        for %%d in (
            "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
            "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
            "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
            "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
            "%USERPROFILE%\anaconda3\python.exe"
            "%USERPROFILE%\miniconda3\python.exe"
            "C:\Python313\python.exe"
            "C:\Python312\python.exe"
            "C:\Python311\python.exe"
            "C:\Python310\python.exe"
            "C:\Anaconda3\python.exe"
            "C:\ProgramData\anaconda3\python.exe"
            "C:\ProgramData\miniconda3\python.exe"
            "D:\Python313\python.exe"
            "D:\Python312\python.exe"
            "D:\Python311\python.exe"
            "D:\Anaconda\python.exe"
            "D:\Anaconda3\python.exe"
            "E:\Python313\python.exe"
            "E:\Python312\python.exe"
            "E:\Python311\python.exe"
            "E:\Anaconda\python.exe"
            "E:\Anaconda3\python.exe"
        ) do (
            if not defined FOUND_PYTHON (
                if exist %%d (
                    %%d --version >nul 2>&1
                    if not errorlevel 1 (
                        set "FOUND_PYTHON=%%~d"
                        echo  [FOUND] %%~d
                    )
                )
            )
        )
    )
    
    REM --- If found, confirm with user ---
    if defined FOUND_PYTHON (
        echo.
        for /f "tokens=*" %%v in ('"!FOUND_PYTHON!" --version 2^>^&1') do echo  Detected: %%v
        echo.
        echo  Path: !FOUND_PYTHON!
        echo.
        set /p CONFIRM_PYTHON="  Use this Python? [Y/n]: "
        
        if /i "!CONFIRM_PYTHON!"=="n" (
            set FOUND_PYTHON=
        )
        if /i "!CONFIRM_PYTHON!"=="no" (
            set FOUND_PYTHON=
        )
    )
    
    REM --- If not found or user declined, ask for manual input ---
    if not defined FOUND_PYTHON (
        echo.
        echo  Python was not found automatically.
        echo.
        echo  Please enter the full path to your python.exe
        echo.
        echo  Examples:
        echo    C:\Python311\python.exe
        echo    C:\Users\YourName\AppData\Local\Programs\Python\Python311\python.exe
        echo    C:\Users\YourName\anaconda3\python.exe
        echo.
        echo  TIP: Open Command Prompt and type "where python" to find it.
        echo.
        set /p FOUND_PYTHON="  Enter Python path: "
        
        if "!FOUND_PYTHON!"=="" (
            echo.
            echo ERROR: No path entered. Please try again.
            pause
            exit /b 1
        )
        
        if not exist "!FOUND_PYTHON!" (
            echo.
            echo ERROR: File not found: !FOUND_PYTHON!
            echo Please check the path and try again.
            pause
            exit /b 1
        )
        
        REM Verify it's actually Python
        echo.
        echo  Verifying Python...
        "!FOUND_PYTHON!" --version >nul 2>&1
        if errorlevel 1 (
            echo.
            echo ERROR: This doesn't appear to be a valid Python executable.
            echo Please check the path and try again.
            pause
            exit /b 1
        )
    )
    
    REM Save the path to python_config.bat
    echo.
    echo  Saving Python path to configuration...
    (
        echo REM ============================================================
        echo REM MapReplay Python Configuration
        echo REM ============================================================
        echo REM This file stores your Python path.
        echo REM It was set automatically on first run.
        echo REM You can edit it manually if needed.
        echo REM ============================================================
        echo.
        echo REM Python executable path:
        echo set PYTHON_PATH=!FOUND_PYTHON!
        echo.
        echo REM ============================================================
    ) > "%~dp0python_config.bat"
    
    set PYTHON_PATH=!FOUND_PYTHON!
    echo  Python path saved successfully!
    echo.
)

REM ============================================================
REM Verify Python path is valid
REM ============================================================
if "%PYTHON_PATH%"=="python" (
    where python >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python not found in system PATH
        echo Please run this script again and enter the full path.
        
        REM Clear the config so it asks again next time
        (
            echo REM Python path not configured
            echo set PYTHON_PATH=
        ) > "%~dp0python_config.bat"
        
        pause
        exit /b 1
    )
    echo Using Python from PATH
) else (
    if not exist "%PYTHON_PATH%" (
        echo ERROR: Python not found at: %PYTHON_PATH%
        echo.
        echo The configured path no longer exists.
        echo Please run this script again to reconfigure.
        
        REM Clear the config so it asks again next time
        (
            echo REM Python path not configured
            echo set PYTHON_PATH=
        ) > "%~dp0python_config.bat"
        
        pause
        exit /b 1
    )
    echo Using Python: %PYTHON_PATH%
)

REM Show Python version
for /f "tokens=*" %%i in ('"%PYTHON_PATH%" --version 2^>^&1') do echo %%i
echo.

REM ============================================================
REM Check and install required packages
REM ============================================================
echo Checking required packages...
echo.

set NEED_INSTALL=0

REM Check Pillow
"%PYTHON_PATH%" -c "import PIL" >nul 2>&1
if errorlevel 1 (
    echo  [X] Pillow - NOT INSTALLED
    set NEED_INSTALL=1
) else (
    echo  [OK] Pillow
)

REM Check numpy
"%PYTHON_PATH%" -c "import numpy" >nul 2>&1
if errorlevel 1 (
    echo  [X] numpy - NOT INSTALLED
    set NEED_INSTALL=1
) else (
    echo  [OK] numpy
)

REM Check imageio
"%PYTHON_PATH%" -c "import imageio" >nul 2>&1
if errorlevel 1 (
    echo  [X] imageio - NOT INSTALLED
    set NEED_INSTALL=1
) else (
    echo  [OK] imageio
)

REM Check imageio-ffmpeg (provides FFmpeg for video encoding)
"%PYTHON_PATH%" -c "import imageio_ffmpeg; imageio_ffmpeg.get_ffmpeg_exe()" >nul 2>&1
if errorlevel 1 (
    echo  [X] imageio-ffmpeg - NOT INSTALLED (required for video encoding)
    set NEED_INSTALL=1
) else (
    echo  [OK] imageio-ffmpeg (FFmpeg)
)

REM Check matplotlib
"%PYTHON_PATH%" -c "import matplotlib" >nul 2>&1
if errorlevel 1 (
    echo  [X] matplotlib - NOT INSTALLED
    set NEED_INSTALL=1
) else (
    echo  [OK] matplotlib
)

REM Check tqdm
"%PYTHON_PATH%" -c "import tqdm" >nul 2>&1
if errorlevel 1 (
    echo  [X] tqdm - NOT INSTALLED
    set NEED_INSTALL=1
) else (
    echo  [OK] tqdm
)

REM Check psutil (optional but recommended)
"%PYTHON_PATH%" -c "import psutil" >nul 2>&1
if errorlevel 1 (
    echo  [X] psutil - NOT INSTALLED
    set NEED_INSTALL=1
) else (
    echo  [OK] psutil
)

echo.

REM ============================================================
REM Install missing packages if needed
REM ============================================================
if %NEED_INSTALL%==1 (
    echo Some packages are missing. Installing now...
    echo This may take a few minutes on first run...
    echo.
    
    REM Upgrade pip first (suppress most output)
    echo Upgrading pip...
    "%PYTHON_PATH%" -m pip install --upgrade pip >nul 2>&1
    
    REM Install all required packages in one go
    echo.
    echo Installing packages...
    echo.
    "%PYTHON_PATH%" -m pip install Pillow numpy imageio imageio-ffmpeg matplotlib tqdm psutil
    
    if errorlevel 1 (
        echo.
        echo ============================================================
        echo  WARNING: Some packages may have failed to install.
        echo  The service will try to start anyway.
        echo ============================================================
        echo.
        pause
    ) else (
        echo.
        echo All packages installed successfully!
        echo.
    )
)

REM ============================================================
REM Final verification
REM ============================================================
echo Verifying installation...
"%PYTHON_PATH%" -c "import PIL, numpy, imageio, matplotlib, tqdm; import imageio_ffmpeg; imageio_ffmpeg.get_ffmpeg_exe(); print('All core packages OK')" 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: Required packages still missing after installation.
    echo.
    echo Please try running this command manually in Command Prompt:
    echo   "%PYTHON_PATH%" -m pip install Pillow numpy imageio imageio-ffmpeg matplotlib tqdm psutil
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Starting MapReplay Live Service...
echo  Press Ctrl+C to stop
echo ============================================================
echo.

REM Get script directory and start service
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"
"%PYTHON_PATH%" MapReplay_Service.py

echo.
echo Service stopped.
pause
