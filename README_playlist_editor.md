## SR Playlist Forge

App icon:

- Place your source icon at `icon.png` in the project root.
- Build scripts auto-generate `assets/icon.icns` (macOS) and `assets/icon.ico` (Windows).

Run:

```bash
python3 synth_playlist_editor.py
```

What it supports:

- Create/edit all playlist-level fields used in your sample `.playlist` files
- Add songs from a Synthriderz beatmap URL (`https://synthriderz.com/beatmaps/<id>`)
- Edit song fields manually
- Reorder songs with Move Up/Move Down
- Block duplicate song hashes
- Add/merge existing `.playlist` files into the current list
- Export with enforced `.playlist` extension
- Download `.synth` for a selected song or all songs in the current playlist
- Live stats: song count + total length (`HH:MM:SS`)

Notes:

- URL import uses public Synthriderz API endpoints. If an endpoint shape changes, the app tries multiple common variants and key names.
- Download uses beatmap-linked endpoints and fallback URL patterns. If an endpoint returns JSON with a nested download link, the app follows it automatically.
- This sandbox cannot currently reach Synthriderz, so live URL fetch could not be tested here.

## Build Standalone Single-File Apps (No Python Needed For End Users)

### macOS build (creates one file)

```bash
chmod +x scripts/build_macos.sh
./scripts/build_macos.sh
```

Output:

- `dist/SR Playlist Forge` (single executable file)

### Windows build (creates one file `.exe`)

Run on a Windows machine:

```bat
scripts\build_windows.bat
```

Output:

- `dist\SR Playlist Forge.exe`

### Build both via GitHub Actions

- Workflow file: `.github/workflows/build-binaries.yml`
- Trigger it with `workflow_dispatch` (Run workflow button)
- Download artifacts:
  - `SR-Playlist-Forge-macOS` (zip containing single executable file)
  - `SR-Playlist-Forge-Windows` (zip containing `.exe`)
