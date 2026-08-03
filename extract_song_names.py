#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def extract_song_names(playlist_path: Path) -> list[str]:
    with playlist_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Playlist root must be a JSON object: {playlist_path}")
    songs = data.get("dataString", [])
    if not isinstance(songs, list):
        raise ValueError(f"Playlist dataString must be a list: {playlist_path}")
    return [
        str(item.get("name", "")).strip()
        for item in songs
        if isinstance(item, dict) and item.get("name")
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract song names from Synth Riders .playlist files into .txt files."
    )
    parser.add_argument(
        "--input-dir",
        default="playlists",
        help="Directory containing .playlist files (default: playlists)",
    )
    parser.add_argument(
        "--output-dir",
        default="txt",
        help="Directory for generated .txt files (default: txt)",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    if not input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    playlist_files = sorted(input_dir.glob("*.playlist"))
    if not playlist_files:
        raise SystemExit(f"No .playlist files found in {input_dir}")

    for playlist_file in playlist_files:
        names = extract_song_names(playlist_file)
        out_file = output_dir / f"{playlist_file.stem}.txt"
        out_file.write_text("\n".join(names) + ("\n" if names else ""), encoding="utf-8")
        print(f"Wrote {len(names)} songs -> {out_file}")


if __name__ == "__main__":
    main()
