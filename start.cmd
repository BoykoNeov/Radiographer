@echo off
REM ===========================================================================
REM  Radiographer launcher (Windows) — double-click this file to start the app.
REM
REM  What it does: makes sure Node deps are installed, then starts the local
REM  dev server and opens the app in your default browser. All physics runs
REM  in the browser (Pyodide/WASM) — there is no server to deploy.
REM
REM  First launch needs internet: the browser downloads the Pyodide runtime
REM  from a CDN and may take tens of seconds to become interactive.
REM
REM  macOS / Linux: there is no .cmd; run the equivalent from a terminal:
REM      cd web && npm install && npm run dev
REM ===========================================================================

REM Anchor to this script's folder, then into the web app (double-clicking a
REM .cmd starts with an arbitrary working directory, so this is required).
cd /d "%~dp0web" || goto :fail

REM Node is required to run the dev server / build the runtime archive.
where node >nul 2>nul
if errorlevel 1 (
  echo.
  echo [Radiographer] Node.js was not found on your PATH.
  echo Install the LTS release from https://nodejs.org/ and run this again.
  goto :fail
)

REM Install dependencies on a fresh clone (your node_modules may already exist).
if not exist "node_modules" (
  echo [Radiographer] Installing dependencies ^(first run only^)...
  call npm install || goto :fail
)

echo [Radiographer] Starting the dev server and opening your browser...
echo [Radiographer] Leave this window open while you use the app; close it to stop.
call npm start
if errorlevel 1 goto :fail

goto :eof

:fail
echo.
echo [Radiographer] Startup failed — see the message above.
pause
exit /b 1
