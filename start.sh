#!/usr/bin/env bash
# =============================================================================
#  Radiographer launcher (macOS / Linux) — the companion to start.cmd (Windows).
#
#  What it does: makes sure Node deps are installed, then starts the local dev
#  server and opens the app in your browser. All physics runs in the browser
#  (Pyodide/WASM) — there is no server to deploy.
#
#  First launch needs internet: the browser downloads the Pyodide runtime from
#  a CDN and may take tens of seconds to become interactive.
#
#  Run it from a terminal:   ./start.sh   (or: bash start.sh)
#  (Double-clicking a .sh does not reliably open a terminal on macOS/Linux, so
#   the terminal command above — and the README's `cd web && npm …` — is the
#   canonical path.)
# =============================================================================
set -euo pipefail

# Anchor to this script's folder, then into the web app (so it works regardless
# of the directory the terminal happens to be in).
cd "$(dirname "$0")/web"

if ! command -v node >/dev/null 2>&1; then
  echo "[Radiographer] Node.js was not found on your PATH."
  echo "Install the LTS release from https://nodejs.org/ and run this again."
  exit 1
fi

# Install dependencies on a fresh clone (node_modules may already exist).
if [ ! -d "node_modules" ]; then
  echo "[Radiographer] Installing dependencies (first run only)..."
  npm install
fi

echo "[Radiographer] Starting the dev server and opening your browser..."
echo "[Radiographer] Leave this terminal open while you use the app; Ctrl-C to stop."
npm start
