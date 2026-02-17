#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-build.txt
python3 scripts/generate_icons.py --mac --input icon.png

rm -rf build dist

APP_NAME="SR Playlist Forge"

python3 -m PyInstaller \
  --noconfirm \
  --onefile \
  --windowed \
  --clean \
  --icon "assets/icon.icns" \
  --name "$APP_NAME" \
  synth_playlist_editor.py

echo "Built macOS single-file binary at: $ROOT_DIR/dist/$APP_NAME"
