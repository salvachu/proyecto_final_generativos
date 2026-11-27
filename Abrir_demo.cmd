@echo off
setlocal
cd /d "%~dp0"
if exist "Aplicacion\Mazmorras.exe" (
    start "" "Aplicacion\Mazmorras.exe"
    exit /b
)
set "demoPython=python"
if exist "%LOCALAPPDATA%\wm-pop-nivel1\venv\Scripts\python.exe" set "demoPython=%LOCALAPPDATA%\wm-pop-nivel1\venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "demoPython=.venv\Scripts\python.exe"
"%demoPython%" explorar.py
if errorlevel 1 pause
