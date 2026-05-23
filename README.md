# SR Playlist Forge

SR Playlist Forge is a desktop playlist editor for Synth Riders custom playlists.

It is designed to make playlist creation faster than editing `.playlist` files by hand, while still exposing the fields that matter for cover styling, song management, downloads, and Quest transfer workflows.

## What It Does

- Create new Synth Riders playlists and edit existing `.playlist` files
- Add songs from Synthriderz beatmap URLs
- Browse beatmaps with both a `List Browser` and a `Visual Browser`
- Import and merge existing playlist files
- Prevent duplicate song hashes
- Reorder songs, remove songs, and edit song metadata manually
- Export playlists with the expected filename format
- Download selected songs or full playlists as `.synth` files
- Send playlists and songs to a Quest headset through `adb`
- Open and manage headset playlists and headset songs from inside the app
- Customize playlist cover styling with:
  - playlist icon
  - texture
  - gradient colors
  - icon/title/texture colors
- Use `Now` to set `creationDate` instantly
- Use `Randomize Look` to generate a coordinated cover style automatically

## Current Highlights

- `creationDate` now follows the current date by default unless you edit it manually
- Playlist look randomization now selects from 12 textures and 21 icons
- The List Browser includes better multi-select UX and clearer selection feedback
- The app includes single-instance protection to avoid duplicate launches
- ADB handling is more resilient when the bundled tools are already in use

## Running From Source

Requirements:

- Python 3.10+
- Optional: `adb` if you want Quest features without the bundled tools

Run:

```bash
python synth_playlist_editor.py
```

## Building

### Windows

```bat
scripts\build_windows.bat
```

Output:

- `dist\SR Playlist Forge.exe`

Installer output used by this repo:

- `release\installer\SR Playlist Forge 2.5 setup.exe`

### macOS

```bash
chmod +x scripts/build_macos.sh
./scripts/build_macos.sh
```

Output:

- `dist/SR Playlist Forge`

## Icons

The project uses `icon.png` in the repository root as the source image.

Generated assets:

- `assets/icon.ico`
- `assets/icon.icns`

You can regenerate them with:

```bash
python scripts/generate_icons.py --windows --mac --input icon.png
```

## Notes

- Synthriderz API responses can change over time, so the app includes fallback parsing for several common field names and endpoint shapes.
- Quest features depend on `adb` and USB debugging access.
- Playlist cover texture values currently assume 12 in-game options, and icon values assume 21 in-game options.
