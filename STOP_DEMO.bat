@echo off
REM Stops the Trazo stack started by RUN_DEMO.bat. Data is kept, so the
REM next run still has this run's traces in it -- RUN_DEMO.bat resets the
REM database itself on each start unless you pass --keep-data.

cd /d "%~dp0"

echo.
echo   Stopping the Trazo stack...
echo.

docker compose --project-name trazo --env-file deploy\.env -f deploy\docker-compose.yml down

echo.
echo   Stopped.
echo.
pause
