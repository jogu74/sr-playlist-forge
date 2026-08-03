#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 -m pip install --disable-pip-version-check -r requirements-build.txt
python3 scripts/generate_icons.py --mac --input icon.png

rm -rf "$ROOT_DIR/build" "$ROOT_DIR/dist"
mkdir -p "$ROOT_DIR/build"

APP_NAME="SR Playlist Forge"
ADD_DATA_ARGS=()
if [[ -d assets ]]; then
  ADD_DATA_ARGS+=(--add-data "$ROOT_DIR/assets:assets")
fi
if [[ -f icon.png ]]; then
  ADD_DATA_ARGS+=(--add-data "$ROOT_DIR/icon.png:.")
fi
if [[ -d tools ]]; then
  ADD_DATA_ARGS+=(--add-data "$ROOT_DIR/tools:tools")
fi

python3 -m PyInstaller \
  --noconfirm \
  --onefile \
  --windowed \
  --clean \
  --additional-hooks-dir "$ROOT_DIR/hooks" \
  --collect-data UnityPy \
  --hidden-import UnityPy \
  --exclude-module numpy \
  --exclude-module pandas \
  --exclude-module scipy \
  --exclude-module sqlalchemy \
  --exclude-module PIL._avif \
  --exclude-module PIL.AvifImagePlugin \
  --specpath build \
  --icon "$ROOT_DIR/assets/icon.icns" \
  --name "$APP_NAME" \
  "${ADD_DATA_ARGS[@]}" \
  synth_playlist_editor.py

echo "Built macOS single-file binary at: $ROOT_DIR/dist/$APP_NAME"
