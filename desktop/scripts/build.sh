#!/usr/bin/env bash
# Build script for Cato Desktop
# Usage: ./scripts/build.sh [--dev|--release]
#
# Steps:
#   1. (Release only) Freeze the Python daemon into a standalone sidecar binary
#   2. Build the Vite frontend
#   3. Build the Tauri app

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$DESKTOP_DIR/.." && pwd)"

MODE="${1:---dev}"

echo "=== Cato Desktop Build ==="
echo "Mode: $MODE"
echo "Desktop dir: $DESKTOP_DIR"
echo ""

echo "--- Syncing desktop manifests to the canonical Cato version ---"
python "$REPO_ROOT/scripts/sync_version.py" --write
echo ""

# ── Step 1: Freeze Python daemon (release only) ──
if [ "$MODE" = "--release" ]; then
    echo "--- Staging frozen Cato sidecar ---"
    python scripts/stage_sidecar.py
    echo ""
fi

# ── Step 2: Install frontend dependencies ──
echo "--- Installing npm dependencies ---"
cd "$DESKTOP_DIR"
npm ci

# ── Step 3: Build ──
if [ "$MODE" = "--release" ]; then
    echo ""
    echo "--- Building Tauri release ---"
    npx tauri build
    echo ""
    echo "=== Build complete ==="
    echo "Installers: $DESKTOP_DIR/src-tauri/target/release/bundle/"
else
    echo ""
    echo "--- Starting Tauri dev server ---"
    echo "Make sure 'cato start --channel webchat' is running separately."
    npx tauri dev
fi
