@echo off
REM ===================================================================
REM  Trazo -- one-click demo launcher.
REM
REM  Double-click this file. It brings the entire stack up (postgres,
REM  redis, opa, control plane, dashboard) and then runs the full
REM  six-step demo against it, verifying each step for real.
REM
REM  Requires: Docker Desktop, Python 3.10+, and uv -- all of which the
REM  script checks for and reports on rather than failing cryptically.
REM ===================================================================

cd /d "%~dp0"

echo.
echo   Starting Trazo... (this window will show progress)
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo   [!!] Python is not on your PATH.
    echo        Install Python 3.10+ from https://www.python.org/downloads/
    echo        and make sure "Add python.exe to PATH" is ticked.
    echo.
    pause
    exit /b 1
)

where uv >nul 2>&1
if errorlevel 1 (
    echo   [!!] uv is not on your PATH.
    echo        Install it with:  pip install uv
    echo.
    pause
    exit /b 1
)

python "scripts\run_demo.py" %*
set EXITCODE=%ERRORLEVEL%

echo.
if %EXITCODE%==0 (
    echo   Demo finished successfully.
) else (
    echo   Demo exited with code %EXITCODE% -- see the messages above.
)
echo.
pause
exit /b %EXITCODE%
