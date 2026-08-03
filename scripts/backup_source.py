#!/usr/bin/env python3
"""Create a hash-verified source snapshot before code changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path


INCLUDED_SUFFIXES = {
    ".py",
    ".bat",
    ".sh",
    ".ps1",
    ".spec",
    ".iss",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".cfg",
}
EXCLUDED_DIRS = {
    ".git",
    ".external",
    ".codex-security-scans",
    "__pycache__",
    "backups",
    "build",
    "dist",
    "installer",
    "playlists",
    "txt",
    "windows",
}


def project_version(project_root: Path) -> str:
    source = (project_root / "synth_playlist_editor.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', source, flags=re.MULTILINE)
    return match.group(1) if match else "unknown"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files(project_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in project_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in INCLUDED_SUFFIXES:
            continue
        relative = path.relative_to(project_root)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        files.append(relative)
    return sorted(files, key=lambda item: str(item).casefold())


def create_backup(project_root: Path, label: str) -> Path:
    version = project_version(project_root)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_label = re.sub(r"[^A-Za-z0-9._-]+", "-", label.strip()).strip("-") or "snapshot"
    backup_root = project_root / "backups" / f"{version}-{safe_label}-{timestamp}"
    backup_root.mkdir(parents=True, exist_ok=False)

    manifest_files: list[dict[str, str]] = []
    for relative in source_files(project_root):
        source = project_root / relative
        destination = backup_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        source_hash = sha256(source)
        backup_hash = sha256(destination)
        if source_hash != backup_hash:
            raise RuntimeError(f"Backup verification failed for {relative}")
        manifest_files.append({"path": relative.as_posix(), "sha256": backup_hash})

    manifest = {
        "version": version,
        "label": safe_label,
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "fileCount": len(manifest_files),
        "files": manifest_files,
    }
    (backup_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return backup_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="pre-change", help="Short label included in the backup directory name")
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parent.parent
    backup_path = create_backup(project_root, args.label)
    print(f"Created verified source backup: {backup_path}")


if __name__ == "__main__":
    main()
