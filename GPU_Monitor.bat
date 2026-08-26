@echo off
REM Floating always-on-top GPU / VRAM / CPU / RAM monitor.
cd /d "%~dp0"

where pythonw >nul 2>nul
if errorlevel 1 (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python was not found on PATH.
        echo Install Python 3 from https://www.python.org/downloads/ and tick "Add to PATH".
        pause
        exit /b 1
    )
)

REM PySide6 draws the card; psutil supplies the CPU and RAM rows.
python -c "import PySide6" >nul 2>nul
if errorlevel 1 (
    echo Installing PySide6...
    python -m pip install --quiet PySide6
)
python -c "import psutil" >nul 2>nul
if errorlevel 1 (
    echo Installing psutil...
    python -m pip install --quiet psutil
)

REM pythonw: no console window behind the overlay.
start "" pythonw "%~dp0gpu_monitor.py"
exit /b 0
