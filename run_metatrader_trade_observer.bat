@echo off
setlocal
cd /d "%~dp0"

set "BUNDLED_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "LOCAL313=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
set "RUN_MODE="
set "RUN_PATH="
set "RUN_DESC="
set "RUN_PY_VER="

call :try_direct "%BUNDLED_PY%" "Bundled Python"
if defined RUN_MODE goto :start

call :try_direct "%LOCAL313%" "Local Python 3.13"
if defined RUN_MODE goto :start

call :try_pyver 3.13
if defined RUN_MODE goto :start

call :try_pyver 3.12
if defined RUN_MODE goto :start

where python >nul 2>nul
if %errorlevel%==0 (
    call :try_direct "python" "PATH Python"
    if defined RUN_MODE goto :start
)

if exist "%BUNDLED_PY%" (
    set "RUN_MODE=direct"
    set "RUN_PATH=%BUNDLED_PY%"
    set "RUN_DESC=Bundled Python (MetaTrader5 missing)"
    goto :start
)

echo Python was not found. Install Python or add it to PATH, then run this app again.
pause
exit /b 1

:start
echo Starting MetaTrader Trade Observer...
echo Keep this window open while you use the dashboard.
echo Then open http://127.0.0.1:8765 in your browser.
if /i "%RUN_MODE%"=="py" (
    echo Using Python: Python launcher %RUN_PY_VER%
    echo Command: py -%RUN_PY_VER% server.py
    py -%RUN_PY_VER% server.py
) else (
    echo Using Python: %RUN_DESC%
    echo Command: "%RUN_PATH%" server.py
    "%RUN_PATH%" server.py
)
pause
exit /b %errorlevel%

:try_direct
set "CANDIDATE=%~1"
set "LABEL=%~2"
if not exist "%CANDIDATE%" (
    if /i not "%CANDIDATE%"=="python" goto :eof
)
"%CANDIDATE%" -c "import MetaTrader5" >nul 2>nul
if %errorlevel%==0 (
    set "RUN_MODE=direct"
    set "RUN_PATH=%CANDIDATE%"
    set "RUN_DESC=%LABEL%"
)
goto :eof

:try_pyver
where py >nul 2>nul
if %errorlevel% neq 0 goto :eof
py -%~1 -c "import MetaTrader5" >nul 2>nul
if %errorlevel%==0 (
    set "RUN_MODE=py"
    set "RUN_PY_VER=%~1"
)
goto :eof
