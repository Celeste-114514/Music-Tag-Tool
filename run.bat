@echo off
rem ==== Music Tag Tool launcher (PySide6) ====
rem Launch GUI with pythonw (no console window).
rem Skip WindowsApps app-alias stubs: they have no real pythonw and may open Store.
cd /d "%~dp0"
if exist error.log del /q error.log

rem --- find the first real python.exe (ignore WindowsApps app-alias) ---
set "_PY="
for /f "delims=" %%i in ('where python.exe 2^>nul') do (
    echo %%i | findstr /i "WindowsApps" >nul
    if errorlevel 1 (
        if not defined _PY set "_PY=%%i"
    )
)
if defined _PY (
    for %%p in ("%_PY%") do set "_DIR=%%~dpp"
    if exist "%_DIR%pythonw.exe" (
        start "" "%_DIR%pythonw.exe" MusicTagTool.py
        exit /b 0
    )
)

rem --- fallback: resolve pythonw.exe via python sys.executable ---
set "_W="
for /f "delims=" %%i in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do set "_W=%%i"
if exist "%_W%" (
    start "" "%_W%" MusicTagTool.py
    exit /b 0
)

echo Python not found. Install Python then run: pip install -r requirements.txt
pause
