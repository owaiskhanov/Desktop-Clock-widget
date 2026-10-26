@echo off
REM Builds DesktopClock.exe locally. Needs Python 3.9+ from python.org
REM (the Microsoft Store build of Python cannot be used with PyInstaller).
setlocal
cd /d "%~dp0"

echo === Creating build environment ===
if not exist .venv (
    python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat

python -m pip install --upgrade pip
pip install pyinstaller -r requirements.txt || goto :error

echo === Building DesktopClock.exe ===
pyinstaller --noconfirm --clean --onefile --windowed ^
    --name DesktopClock ^
    --icon assets\icon.ico ^
    --add-data "assets\icon.ico;assets" ^
    --add-data "assets\icon.png;assets" ^
    --add-data "assets\fonts;assets\fonts" ^
    --copy-metadata tzdata ^
    --collect-data tzdata ^
    clock_widget.py || goto :error

echo.
echo Done -^> dist\DesktopClock.exe
goto :eof

:error
echo.
echo Build failed. See the messages above.
exit /b 1
