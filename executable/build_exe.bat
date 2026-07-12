@echo off
REM =====================================================================
REM  Build script - turns gui_app.py into a standalone Windows .exe
REM
REM  HOW TO USE:
REM   1. Put this file in the SAME folder as gui_app.py,
REM      instagram_logo_tool.py, and the "fonts" folder.
REM   2. Double-click this file (build_exe.bat)
REM   3. Wait for it to finish - it will open the output folder
REM      automatically when done.
REM   4. Your .exe will be in a new "dist" folder.
REM =====================================================================

echo ============================================================
echo  Instagram Logo Tool - EXE Builder
echo ============================================================
echo.

REM --- Check Python is installed ---
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python was not found on this computer.
    echo Please install Python from https://www.python.org/downloads/
    echo and make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

if not exist fonts (
    echo WARNING: "fonts" folder not found next to this script.
    echo The app will still work, but captions will use a plainer
    echo system font instead of the bundled bold poster font.
    echo.
)

echo [1/4] Installing required packages...
python -m pip install --upgrade pip >nul
pip install pillow pyinstaller
if errorlevel 1 (
    echo ERROR: Failed to install required packages.
    pause
    exit /b 1
)

echo.
echo [2/4] Cleaning up old build files (if any)...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist InstagramLogoTool.spec del InstagramLogoTool.spec

echo.
echo [3/4] Building the .exe (this can take a minute or two)...
if exist fonts (
    pyinstaller --noconfirm --onefile --windowed ^
        --name "InstagramLogoTool" ^
        --hidden-import=PIL._tkinter_finder ^
        --add-data "fonts;fonts" ^
        gui_app.py
) else (
    pyinstaller --noconfirm --onefile --windowed ^
        --name "InstagramLogoTool" ^
        --hidden-import=PIL._tkinter_finder ^
        gui_app.py
)

if errorlevel 1 (
    echo.
    echo ERROR: Build failed. Scroll up to see the error message.
    pause
    exit /b 1
)

echo.
echo [4/4] Done!
echo Your app is here: dist\InstagramLogoTool.exe
echo You can copy that single .exe file anywhere and double-click it to run.
echo ============================================================
explorer dist
pause
