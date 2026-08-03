# SR Playlist Forge

SR Playlist Forge is a desktop playlist editor for Synth Riders custom playlists.

It is designed to make playlist creation faster than editing `.playlist` files by hand, while still exposing the fields that matter for cover styling, song management, downloads, and Quest transfer workflows.

## What It Does

- Create new Synth Riders playlists and edit existing `.playlist` files
- Add songs from Synthriderz beatmap URLs
- Browse beatmaps with both a `List Browser` and a `Visual Browser`
- Browse all public or officially curated Synthriderz playlists by cover, creator, downloads, votes, or date
- Open, merge, or save a community `.playlist` directly from the Playlist Browser
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
- Import the original playlist icons and textures read-only from:
  - a connected Quest headset
  - a local Synth Riders PC installation
- Preview the selected icon, texture, gradients, and colors live before export
- Use `Now` to set `creationDate` instantly
- Use `Randomize Look` to generate a coordinated cover style automatically

## Current Highlights

- `creationDate` now follows the current date by default unless you edit it manually
- Playlist look randomization now selects from 12 textures and 21 icons
- Playlist visuals can be cached locally from a user-owned game installation
- The local visual import also reads Bordas for the no-icon playlist initial without redistributing the font
- Quest visual import streams only the required Unity resources and removes temporary game data afterward
- Icon and texture indexes can be browsed with clickable up/down controls and the live preview updates immediately
- Playlist icon index `0` correctly previews the first name character; built-in icons map to indexes `1–20`
- Quest transfer and transfer reports now use the same modern visual language as the main workspace
- Quest Songs now uses the modern library layout with dark status rows, compact filters, search, and clearly separated cleanup actions
- Quest mass-deletion confirmations stay compact so Yes/No controls remain visible regardless of filename count or length
- Quest playlist-usage checks classify cached hashes and filename matches first, read only unresolved songs from the headset, and show determinate progress
- Discover cards now fill the available workspace width and rewrap explanatory text as the window is resized
- `Clear all` is available beside the playlist order controls for quickly starting a fresh song list
- Mouse reordering now moves the playlist live, highlights held songs, and auto-scrolls near the list edges
- Non-adjacent selected songs move together as one block while preserving their relative order
- Both browsers compare against the current playlist: `✓ In playlist` for the exact map and `≈ Song in playlist` for another map of the same track
- Adding from the List Browser updates only row status, preserving selection and scroll position
- The List Browser includes an inclusive upload-date range prefilled from the oldest map to today, sortable upvote/download counts, and clearer multi-select feedback
- The app includes single-instance protection to avoid duplicate launches
- The main window restores its previous size, position, and maximized state
- `Next on Quest` sets the playlist number to one above the highest numbered playlist on the connected headset
- Quest playlists can be drag-reordered while retaining the existing numbered slots and gaps
- Playlist reorder creates a local backup and uses collision-safe two-phase Quest renaming with rollback
- `Compact numbering` remains an explicit action for changing numbered slots to `1..N`
- ADB handling is more resilient when the bundled tools are already in use
- Playlist Browser mirrors the five live Synthriderz Curated categories alongside Browse All
- Resized table columns are remembered separately in Playlist editor, List Browser, Manage playlists, Manage songs, and Missing songs

## Running From Source

Requirements:

- Python 3.10+
- Dependencies from `requirements-build.txt` (including Pillow and UnityPy)
- Optional: `adb` if you want Quest features without the bundled tools

Run:

```bash
python -m pip install -r requirements-build.txt
python synth_playlist_editor.py
```

The previous classic interface is retained as a runnable backup:

```bash
python synth_playlist_editor_classic_backup.py
```

Before future code changes, create a versioned and hash-verified source backup:

```bash
python scripts/backup_source.py --label pre-change
```

## Building

### Windows

```bat
scripts\build_windows.bat
```

Output:

- `dist\SR Playlist Forge.exe`

Installer output used by this repo:

- `release\installer\SR Playlist Forge 3.0.0 setup.exe`

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
- Imported game artwork remains in the user's local application cache and is not bundled with SR Playlist Forge.
