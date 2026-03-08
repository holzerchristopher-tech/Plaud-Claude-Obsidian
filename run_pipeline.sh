#!/bin/bash
# Native run script for audio-pipeline.
# Loads .env, ensures Homebrew binaries are on PATH, then exec's the watcher.

# Homebrew on Apple Silicon installs to /opt/homebrew
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env into the environment
set -a
# shellcheck disable=SC1090
source "$SCRIPT_DIR/.env"
set +a

exec "$SCRIPT_DIR/venv/bin/python" -u "$SCRIPT_DIR/watcher.py"
