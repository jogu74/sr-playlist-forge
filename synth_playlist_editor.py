#!/usr/bin/env python3
from __future__ import annotations

import json
import io
import msvcrt
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import tkinter as tk
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime
from html import unescape
from pathlib import Path
from tkinter import scrolledtext
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urljoin
from urllib.request import Request, urlopen
import webbrowser

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    BASE_TK_CLASS = TkinterDnD.Tk
    HAS_DND_SUPPORT = True
except Exception:  # noqa: BLE001
    DND_FILES = None
    BASE_TK_CLASS = tk.Tk
    HAS_DND_SUPPORT = False

try:
    from PIL import Image, ImageOps, ImageTk

    HAS_PILLOW = True
except Exception:  # noqa: BLE001
    Image = None
    ImageOps = None
    ImageTk = None
    HAS_PILLOW = False

ENABLE_HOVER_TOOLTIPS = not getattr(sys, "frozen", False)


ID_RE = re.compile(r"/beatmaps/(\d+)")
HASH_TEXT_RE = re.compile(r"\b([a-fA-F0-9]{64})\b")
BEATMAP_ID_TEXT_RE = re.compile(r'"(?:beatmapId|mapId|beatmap_id|map_id|id)"\s*:\s*"?(\d+)"?', flags=re.IGNORECASE)
TITLE_TEXT_RE = re.compile(r'"(?:title|name|songName|songTitle)"\s*:\s*"([^"]+)"', flags=re.IGNORECASE)
ARTIST_TEXT_RE = re.compile(r'"(?:artist|author|songAuthor|trackAuthor)"\s*:\s*"([^"]+)"', flags=re.IGNORECASE)
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://synthriderz.com/",
    "Origin": "https://synthriderz.com",
}

THEME_PRESETS = {
    "light": {
        "bg": "#f5f7fb",
        "surface": "#ffffff",
        "surface_alt": "#eef2ff",
        "fg": "#14213d",
        "muted": "#52607a",
        "accent": "#2563eb",
        "accent_text": "#ffffff",
        "border": "#cbd5e1",
        "input_bg": "#ffffff",
        "input_fg": "#14213d",
        "select_bg": "#dbeafe",
        "select_fg": "#0f172a",
        "danger": "#991b1b",
        "success": "#166534",
        "warning": "#92400e",
    },
    "dark": {
        "bg": "#0f172a",
        "surface": "#111827",
        "surface_alt": "#1f2937",
        "fg": "#e5eefc",
        "muted": "#94a3b8",
        "accent": "#38bdf8",
        "accent_text": "#0f172a",
        "border": "#334155",
        "input_bg": "#111827",
        "input_fg": "#e5eefc",
        "select_bg": "#1d4ed8",
        "select_fg": "#eff6ff",
        "danger": "#fecaca",
        "success": "#bbf7d0",
        "warning": "#fde68a",
    },
}


class DownloadCancelled(Exception):
    pass


@dataclass
class SongEntry:
    hash: str
    name: str = ""
    author: str = ""
    beatmapper: str = ""
    difficulty: int = 0
    difficultyText: str = ""
    trackDuration: float = 0.0
    addedTime: int = 0
    beatmapId: str = ""
    sourceUrl: str = ""
    downloadUrl: str = ""

    def to_playlist_dict(self) -> dict[str, Any]:
        return {
            "hash": self.hash,
            "name": self.name,
            "author": self.author,
            "beatmapper": self.beatmapper,
            "difficulty": int(self.difficulty),
            "trackDuration": float(self.trackDuration),
            "addedTime": int(self.addedTime),
        }


@dataclass
class BeatmapListEntry:
    beatmap_id: str
    title: str
    artist: str
    mapper: str
    uploaded_text: str
    uploaded_sort: float
    duration_text: str
    duration_sort: float
    difficulty_text: str
    download_count: int
    record: dict[str, Any]


@dataclass
class HeadsetSongIdentity:
    file_name: str
    song_hash: str = ""
    beatmap_id: str = ""
    title: str = ""
    artist: str = ""
    mapper: str = ""
    source: str = "unknown"


HEADSET_SYNTH_METADATA_CACHE: dict[str, HeadsetSongIdentity] = {}
BEATMAP_RECORD_BY_HASH_CACHE: dict[str, dict[str, Any] | None] = {}
BEATMAP_RECORD_BY_TITLE_ARTIST_CACHE: dict[str, dict[str, Any] | None] = {}


def force_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def force_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_duration_to_seconds(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    if ":" in text:
        parts = text.split(":")
        try:
            parts_num = [int(p) for p in parts]
        except ValueError:
            return default
        if len(parts_num) == 2:
            return float(parts_num[0] * 60 + parts_num[1])
        if len(parts_num) == 3:
            return float(parts_num[0] * 3600 + parts_num[1] * 60 + parts_num[2])
        return default
    return force_float(text, default)


def infer_difficulty_from_record(record: dict[str, Any]) -> int:
    direct = find_first_scalar(record, ["difficulty", "difficultyInt", "difficultyValue", "diff"])
    if direct is not None and str(direct).strip() != "":
        return force_int(direct, 0)
    diffs = record.get("difficulties")
    if isinstance(diffs, list):
        last_idx = -1
        for idx, val in enumerate(diffs):
            if str(val).strip():
                last_idx = idx
        if last_idx >= 0:
            return last_idx
    return 0


def infer_difficulty_text_from_record(record: dict[str, Any], fallback_int: int) -> str:
    diffs = record.get("difficulties")
    if isinstance(diffs, list):
        labels = [str(v).strip() for v in diffs if str(v).strip()]
        if labels:
            return ", ".join(labels)
    return str(fallback_int)


def timestamp_to_local_text(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def local_text_to_timestamp(text: str) -> int:
    value = text.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            return int(dt.timestamp())
        except ValueError:
            continue
    raise ValueError("Use creation date format YYYY-MM-DD HH:MM[:SS]")


def parse_iso_datetime_to_timestamp(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except ValueError:
        return 0


def normalize_playlist_path(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() != ".playlist":
        p = p.with_suffix(".playlist")
    return str(p)


def sanitize_filename_component(text: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", text).strip().strip(".")
    return cleaned


def build_playlist_filename(playlist_number_text: str, playlist_name_text: str) -> str:
    number_raw = playlist_number_text.strip()
    if not number_raw:
        raise ValueError("Playlist Number is required.")
    number = int(number_raw)
    if number < 0:
        raise ValueError("Playlist Number must be 0 or higher.")
    name = sanitize_filename_component(playlist_name_text.strip())
    if not name:
        raise ValueError("namePlaylist cannot be empty.")
    return f"{str(number).zfill(6)}__{name}.playlist"


def parse_beatmap_id(url_text: str) -> str | None:
    m = ID_RE.search(url_text.strip())
    return m.group(1) if m else None


def safe_filename(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch.isalnum() or ch in (" ", "-", "_", ".")).strip()
    return cleaned[:120] or "beatmap"


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def iter_dict_values(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        out.append(payload)
        for v in payload.values():
            out.extend(iter_dict_values(v))
    elif isinstance(payload, list):
        for v in payload:
            out.extend(iter_dict_values(v))
    return out


def find_first_scalar(record: dict[str, Any], key_names: list[str]) -> Any:
    lowered = {k.lower() for k in key_names}
    for k, v in record.items():
        if k.lower() in lowered and not isinstance(v, (dict, list)):
            return v
    return None


def find_first_url(record: dict[str, Any], key_names: list[str]) -> str | None:
    lowered = {k.lower() for k in key_names}
    for k, v in record.items():
        if k.lower() in lowered and isinstance(v, str) and v.startswith(("http://", "https://", "/")):
            return v
    return None


def walk_values(obj: Any):
    stack = [obj]
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def parse_song_from_record(record: dict[str, Any], beatmap_id: str) -> SongEntry:
    song_hash = find_first_scalar(record, ["hash", "checksum", "mapHash", "songHash", "fileHash"])
    if not song_hash:
        raise RuntimeError("No hash found in beatmap record.")

    now = int(time.time())
    mapper = find_first_scalar(record, ["beatmapper", "mapper", "creator", "uploader", "mapped_by"])
    if not mapper and isinstance(record.get("user"), dict):
        mapper = find_first_scalar(record["user"], ["username", "name"])
    diff_int = infer_difficulty_from_record(record)
    song = SongEntry(
        hash=str(song_hash),
        name=str(find_first_scalar(record, ["name", "title", "songName", "songTitle"]) or "").strip(),
        author=str(find_first_scalar(record, ["author", "artist", "songAuthor", "trackAuthor"]) or "").strip(),
        beatmapper=str(mapper or "").strip(),
        difficulty=diff_int,
        difficultyText=infer_difficulty_text_from_record(record, diff_int),
        trackDuration=parse_duration_to_seconds(
            find_first_scalar(record, ["trackDuration", "track_duration", "duration", "length", "seconds", "songDuration"]),
            0.0,
        ),
        addedTime=force_int(find_first_scalar(record, ["addedTime", "uploadedAt", "timestamp", "createdAt"]), now),
        beatmapId=beatmap_id,
        sourceUrl=f"https://synthriderz.com/beatmaps/{beatmap_id}",
        downloadUrl=resolve_download_url(record, beatmap_id),
    )
    if song.addedTime <= 0:
        song.addedTime = now
    return song


def pick_best_record(payload: Any, beatmap_id: str) -> dict[str, Any]:
    records = iter_dict_values(payload)
    if not records:
        return {}

    # Prefer a record matching the beatmap ID if one is present.
    for rec in records:
        rec_id = find_first_scalar(rec, ["id", "beatmapId", "mapId"])
        if beatmap_id and rec_id is not None and str(rec_id) == str(beatmap_id):
            return rec

    # Fallback: first object that looks like a beatmap.
    for rec in records:
        if find_first_scalar(rec, ["hash", "checksum", "mapHash", "songHash"]) is not None:
            return rec
    return records[0]


def pick_record_by_hash(payload: Any, song_hash: str) -> dict[str, Any]:
    records = iter_dict_values(payload)
    if not records:
        return {}
    target = song_hash.lower()
    for rec in records:
        rec_hash = find_first_scalar(rec, ["hash", "checksum", "mapHash", "songHash", "fileHash"])
        if isinstance(rec_hash, str) and rec_hash.lower() == target:
            return rec
    return {}


def fetch_json(url: str) -> Any:
    req = Request(url, headers=DEFAULT_HEADERS)
    with urlopen(req, timeout=20) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def fetch_text(url: str) -> str:
    req = Request(url, headers=DEFAULT_HEADERS)
    with urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_bytes(url: str) -> bytes:
    req = Request(url, headers=DEFAULT_HEADERS)
    with urlopen(req, timeout=20) as response:
        return response.read()


def safe_after(widget: tk.Misc, callback: Callable[[], None]) -> None:
    try:
        widget.after(0, callback)
    except tk.TclError:
        pass


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def app_support_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        support_dir = root / "SR Playlist Forge"
    else:
        support_dir = Path.home() / ".sr_playlist_forge"
    support_dir.mkdir(parents=True, exist_ok=True)
    return support_dir


def error_log_path() -> Path:
    return app_support_dir() / "error.log"


class SingleInstanceGuard:
    def __init__(self) -> None:
        self.lock_path = app_support_dir() / "app.lock"
        self.handle: io.TextIOWrapper | None = None

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+", encoding="utf-8")
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            handle.close()
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self.handle = handle
        return True

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        try:
            self.handle.close()
        except OSError:
            pass
        self.handle = None


def bundled_tools_source_dirs() -> list[Path]:
    return [
        app_base_dir() / "tools",
        app_base_dir() / "tools" / "platform-tools",
    ]


def stable_bundled_adb_dir() -> Path | None:
    adb_names = ["adb.exe", "adb"]
    dll_names = ["AdbWinApi.dll", "AdbWinUsbApi.dll"]
    if getattr(sys, "frozen", False):
        target_dir = app_support_dir() / "tools"
        target_dir.mkdir(parents=True, exist_ok=True)
        copied_any = False
        for name in [*adb_names, *dll_names]:
            for source_dir in bundled_tools_source_dirs():
                source_path = source_dir / name
                if not source_path.exists():
                    continue
                target_path = target_dir / name
                needs_copy = not target_path.exists()
                if not needs_copy:
                    try:
                        needs_copy = source_path.stat().st_mtime > target_path.stat().st_mtime
                    except OSError:
                        needs_copy = False
                if needs_copy:
                    try:
                        shutil.copy2(source_path, target_path)
                    except PermissionError:
                        # Another running instance may still be holding adb.exe open.
                        # Reuse the existing stable copy instead of failing Quest status polling.
                        if not target_path.exists():
                            continue
                    except OSError:
                        if not target_path.exists():
                            continue
                copied_any = copied_any or target_path.exists()
                break
        if copied_any and any((target_dir / name).exists() for name in adb_names):
            return target_dir

    for source_dir in bundled_tools_source_dirs():
        if any((source_dir / name).exists() for name in adb_names):
            return source_dir
    return None


def subprocess_hidden_window_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    kwargs: dict[str, Any] = {}
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if create_no_window:
        kwargs["creationflags"] = create_no_window
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    kwargs["startupinfo"] = startupinfo
    return kwargs


def write_exception_log(title: str, exc_info: tuple[type[BaseException], BaseException, Any] | None = None) -> Path:
    if exc_info is None:
        exc_info = sys.exc_info()
    exc_type, exc_value, exc_tb = exc_info
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"[{timestamp}] {title}"]
    if exc_type and exc_value:
        lines.append("".join(traceback.format_exception(exc_type, exc_value, exc_tb)).rstrip())
    else:
        lines.append("No traceback available.")
    lines.append("")
    log_path = error_log_path()
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return log_path


def show_fatal_error_dialog(title: str, message: str) -> None:
    try:
        messagebox.showerror(title, message)
    except Exception:
        pass


def install_global_exception_hooks() -> None:
    def _handle_exception(exc_type: type[BaseException], exc_value: BaseException, exc_tb: Any) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        log_path = write_exception_log("Unhandled exception", (exc_type, exc_value, exc_tb))
        show_fatal_error_dialog(
            "SR Playlist Forge Error",
            "An unexpected error occurred.\n\n"
            f"Details were written to:\n{log_path}",
        )

    sys.excepthook = _handle_exception

    def _threading_hook(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, KeyboardInterrupt):
            return
        log_path = write_exception_log(
            f"Unhandled thread exception in {args.thread.name if args.thread else 'unknown thread'}",
            (args.exc_type, args.exc_value, args.exc_traceback),
        )
        show_fatal_error_dialog(
            "SR Playlist Forge Error",
            "A background task crashed.\n\n"
            f"Details were written to:\n{log_path}",
        )

    threading.excepthook = _threading_hook


def adb_candidate_paths() -> list[Path]:
    candidates: list[Path] = []
    stable_dir = stable_bundled_adb_dir()
    if stable_dir is not None:
        candidates.extend([stable_dir / "adb.exe", stable_dir / "adb"])

    bundled_candidates = [
        app_base_dir() / "tools" / "adb.exe",
        app_base_dir() / "tools" / "platform-tools" / "adb.exe",
        app_base_dir() / "tools" / "adb",
        app_base_dir() / "tools" / "platform-tools" / "adb",
    ]
    candidates.extend(bundled_candidates)

    env_roots = [
        os.environ.get("ANDROID_SDK_ROOT", ""),
        os.environ.get("ANDROID_HOME", ""),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk"),
        os.path.join(os.environ.get("APPDATA", ""), "SideQuest"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "SideQuest"),
    ]
    for root in env_roots:
        if not root:
            continue
        root_path = Path(root)
        candidates.extend(
            [
                root_path / "platform-tools" / "adb.exe",
                root_path / "platform-tools" / "adb",
                root_path / "resources" / "app.asar.unpacked" / "build" / "platform-tools" / "adb.exe",
                root_path / "resources" / "app.asar.unpacked" / "platform-tools" / "adb.exe",
            ]
        )

    for candidate in ["adb.exe", "adb"]:
        found = shutil.which(candidate)
        if found:
            candidates.append(Path(found))

    seen: set[str] = set()
    unique_existing: list[Path] = []
    for candidate in candidates:
        normalized = str(candidate).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.exists():
            unique_existing.append(candidate)
    return unique_existing


def adb_looks_usable(adb_path: Path) -> bool:
    try:
        result = run_adb_command(str(adb_path), ["version"], timeout=15)
        output = f"{result.stdout}\n{result.stderr}".lower()
        return result.returncode == 0 and "android debug bridge" in output
    except Exception:
        return False


def find_adb_executable() -> str | None:
    try:
        candidates = adb_candidate_paths()
    except Exception:
        return None
    for candidate in candidates:
        if adb_looks_usable(candidate):
            return str(candidate)
    return None


def merge_headset_song_identity(base: HeadsetSongIdentity, other: HeadsetSongIdentity | None) -> HeadsetSongIdentity:
    if other is None:
        return base
    if other.song_hash and not base.song_hash:
        base.song_hash = other.song_hash
    if other.beatmap_id and not base.beatmap_id:
        base.beatmap_id = other.beatmap_id
    if other.title and not base.title:
        base.title = other.title
    if other.artist and not base.artist:
        base.artist = other.artist
    if other.mapper and not base.mapper:
        base.mapper = other.mapper
    if other.source != "unknown" and base.source == "unknown":
        base.source = other.source
    return base


def extract_song_identity_from_record(record: dict[str, Any], source: str) -> HeadsetSongIdentity | None:
    song_hash = find_first_scalar(record, ["hash", "checksum", "mapHash", "songHash", "fileHash"])
    beatmap_id = find_first_scalar(record, ["id", "beatmapId", "mapId"])
    title = find_first_scalar(record, ["title", "name", "songName", "songTitle"])
    artist = find_first_scalar(record, ["artist", "author", "songAuthor", "trackAuthor"])
    mapper = find_first_scalar(record, ["beatmapper", "mapper", "creator", "uploader", "mapped_by"])
    if song_hash is None and beatmap_id is None and title is None and artist is None and mapper is None:
        return None
    return HeadsetSongIdentity(
        file_name="",
        song_hash=str(song_hash or "").strip().lower(),
        beatmap_id=str(beatmap_id or "").strip(),
        title=str(title or "").strip(),
        artist=str(artist or "").strip(),
        mapper=str(mapper or "").strip(),
        source=source,
    )


def extract_song_identity_from_payload(payload: Any, source: str) -> HeadsetSongIdentity | None:
    merged = HeadsetSongIdentity(file_name="", source="unknown")
    found = False
    for record in iter_dict_values(payload):
        identity = extract_song_identity_from_record(record, source)
        if identity is None:
            continue
        merge_headset_song_identity(merged, identity)
        found = True
        if merged.song_hash and merged.beatmap_id and merged.title:
            break
    return merged if found else None


def decode_text_from_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_song_identity_from_text(text: str, source: str) -> HeadsetSongIdentity | None:
    song_hash_match = HASH_TEXT_RE.search(text)
    beatmap_id_match = ID_RE.search(text) or BEATMAP_ID_TEXT_RE.search(text)
    title_match = TITLE_TEXT_RE.search(text)
    artist_match = ARTIST_TEXT_RE.search(text)
    if not any([song_hash_match, beatmap_id_match, title_match, artist_match]):
        return None
    return HeadsetSongIdentity(
        file_name="",
        song_hash=(song_hash_match.group(1).lower() if song_hash_match else ""),
        beatmap_id=(beatmap_id_match.group(1) if beatmap_id_match else ""),
        title=(unescape(title_match.group(1)).strip() if title_match else ""),
        artist=(unescape(artist_match.group(1)).strip() if artist_match else ""),
        source=source,
    )


def extract_song_identity_from_synth_bytes(data: bytes, file_name: str) -> HeadsetSongIdentity:
    identity = HeadsetSongIdentity(file_name=file_name, beatmap_id=extract_beatmap_id_from_filename(file_name) or "", source="filename")

    payload_identity = None
    try:
        payload = json.loads(decode_text_from_bytes(data))
        payload_identity = extract_song_identity_from_payload(payload, "raw-json")
    except Exception:
        payload_identity = None
    merge_headset_song_identity(identity, payload_identity)

    if zipfile.is_zipfile(io.BytesIO(data)):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    if member.file_size <= 0 or member.file_size > 3 * 1024 * 1024:
                        continue
                    if not member.filename.lower().endswith((".json", ".txt", ".meta", ".dat", ".info")):
                        continue
                    try:
                        member_data = archive.read(member)
                    except Exception:
                        continue
                    text = decode_text_from_bytes(member_data)
                    try:
                        payload = json.loads(text)
                        merge_headset_song_identity(identity, extract_song_identity_from_payload(payload, f"archive:{member.filename}"))
                    except Exception:
                        pass
                    merge_headset_song_identity(identity, extract_song_identity_from_text(text, f"archive:{member.filename}"))
                    if identity.song_hash and identity.beatmap_id and identity.title:
                        break
        except Exception:
            pass

    if not identity.song_hash or not identity.title:
        merge_headset_song_identity(identity, extract_song_identity_from_text(decode_text_from_bytes(data[:512 * 1024]), "text-scan"))
    return identity


def run_adb_command(adb_path: str, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    adb_dir = str(Path(adb_path).resolve().parent)
    env = os.environ.copy()
    env["PATH"] = adb_dir + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [adb_path, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        cwd=adb_dir,
        env=env,
        **subprocess_hidden_window_kwargs(),
    )


def list_adb_devices(adb_path: str) -> list[str]:
    run_adb_command(adb_path, ["start-server"], timeout=30)
    result = run_adb_command(adb_path, ["devices"], timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "adb devices failed.")

    devices: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices attached"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def ensure_device_dir(adb_path: str, remote_dir: str) -> None:
    result = run_adb_command(adb_path, ["shell", "mkdir", "-p", remote_dir], timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Failed to create {remote_dir} on device.")


def adb_push_file(adb_path: str, local_path: Path, remote_path: str, timeout: int = 300) -> None:
    result = run_adb_command(adb_path, ["push", str(local_path), remote_path], timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Failed to push {local_path.name}.")


def adb_pull_file(adb_path: str, remote_path: str, local_path: Path, timeout: int = 300) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    result = run_adb_command(adb_path, ["pull", remote_path, str(local_path)], timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Failed to pull {remote_path}.")


def adb_remote_file_exists(adb_path: str, remote_path: str) -> bool:
    result = run_adb_command(adb_path, ["shell", "ls", remote_path], timeout=30)
    if result.returncode == 0:
        return True
    combined = f"{result.stdout}\n{result.stderr}".lower()
    if "no such file" in combined or "cannot access" in combined:
        return False
    return False


def list_remote_files(adb_path: str, remote_dir: str) -> list[str]:
    result = run_adb_command(adb_path, ["shell", "ls", "-1", remote_dir], timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Failed to list {remote_dir}.")
    items: list[str] = []
    for line in result.stdout.splitlines():
        name = line.strip()
        if not name or name.startswith("ls:"):
            continue
        if name in {".", ".."}:
            continue
        items.append(name)
    return items


def adb_delete_file(adb_path: str, remote_path: str) -> None:
    result = run_adb_command(adb_path, ["shell", "rm", "-f", remote_path], timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Failed to delete {remote_path}.")


def adb_read_text_file(adb_path: str, remote_path: str) -> str:
    result = run_adb_command(adb_path, ["shell", "cat", remote_path], timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Failed to read {remote_path}.")
    return result.stdout


def adb_read_file_bytes(adb_path: str, remote_path: str) -> bytes:
    adb_dir = str(Path(adb_path).resolve().parent)
    env = os.environ.copy()
    env["PATH"] = adb_dir + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [adb_path, "exec-out", "cat", remote_path],
        capture_output=True,
        timeout=120,
        check=False,
        cwd=adb_dir,
        env=env,
        **subprocess_hidden_window_kwargs(),
    )
    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
        stdout_text = result.stdout.decode("utf-8", errors="replace").strip()
        raise RuntimeError(stderr_text or stdout_text or f"Failed to read {remote_path}.")
    return bytes(result.stdout)


def extract_beatmap_id_from_filename(file_name: str) -> str | None:
    match = re.match(r"^(\d+)", Path(file_name).name)
    if not match:
        return None
    return match.group(1)


def normalize_filename_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def headset_filename_matches_song(file_name: str, song: SongEntry) -> bool:
    stem = Path(file_name).stem
    haystack = normalize_filename_token(stem)
    title = normalize_filename_token(song.name)
    artist = normalize_filename_token(song.author)
    if not haystack or not title:
        return False
    if title in haystack:
        if not artist:
            return True
        if artist in haystack:
            return True
        # Accept title-only match when the title is distinctive enough.
        if len(title) >= 10:
            return True
    return False


def headset_identity_matches_song(identity: HeadsetSongIdentity | None, song: SongEntry) -> bool:
    if identity is None:
        return False
    if identity.song_hash and song.hash and identity.song_hash.lower() == song.hash.lower():
        return True
    if identity.beatmap_id and song.beatmapId and identity.beatmap_id == song.beatmapId:
        return True
    if identity.title and normalize_text(identity.title) == normalize_text(song.name or ""):
        if not song.author:
            return True
        if identity.artist and normalize_text(identity.artist) == normalize_text(song.author):
            return True
    return False


def load_cached_beatmap_hashes_by_id() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for row in load_cached_beatmaps():
        rec_hash = find_first_scalar(row.record, ["hash", "checksum", "mapHash", "songHash", "fileHash"])
        if rec_hash:
            hashes[row.beatmap_id] = str(rec_hash)
    return hashes


def load_cached_beatmap_hashes_by_title_artist() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for row in load_cached_beatmaps():
        rec_hash = find_first_scalar(row.record, ["hash", "checksum", "mapHash", "songHash", "fileHash"])
        if not rec_hash:
            continue
        key = f"{normalize_text(row.title)}::{normalize_text(row.artist)}"
        hashes[key] = str(rec_hash).lower()
    return hashes


def collect_playlist_hashes_from_remote(adb_path: str, playlist_dir: str) -> set[str]:
    hashes: set[str] = set()
    names = list_remote_files(adb_path, playlist_dir)
    for name in names:
        if not name.lower().endswith(".playlist"):
            continue
        remote_path = f"{playlist_dir.rstrip('/')}/{name}"
        try:
            raw = adb_read_text_file(adb_path, remote_path)
            payload = json.loads(raw)
        except Exception:
            continue
        items = payload.get("dataString")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            song_hash = item.get("hash")
            if isinstance(song_hash, str) and song_hash.strip():
                hashes.add(song_hash.strip().lower())
    return hashes


def collect_headset_song_hashes(adb_path: str, songs_dir: str) -> set[str]:
    hashes, _, _ = build_headset_song_index(adb_path, songs_dir)
    return hashes


def load_remote_playlist_song_entries(adb_path: str, playlist_path: str) -> list[SongEntry]:
    raw = adb_read_text_file(adb_path, playlist_path)
    payload = json.loads(raw)
    items = payload.get("dataString")
    if not isinstance(items, list):
        return []

    songs: list[SongEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        song_hash = str(item.get("hash", "")).strip()
        if not song_hash:
            continue
        songs.append(
            SongEntry(
                hash=song_hash,
                name=str(item.get("name", "")),
                author=str(item.get("author", "")),
                beatmapper=str(item.get("beatmapper", "")),
                difficulty=force_int(item.get("difficulty"), 0),
                difficultyText=str(item.get("difficultyText", item.get("difficulty", ""))),
                trackDuration=force_float(item.get("trackDuration"), 0.0),
                addedTime=force_int(item.get("addedTime"), int(time.time())),
                beatmapId=str(item.get("beatmapId", "")),
                sourceUrl=str(item.get("sourceUrl", "")),
                downloadUrl=str(item.get("downloadUrl", "")),
            )
        )
    return songs


def find_cached_beatmap_record_by_hash(song_hash: str) -> dict[str, Any] | None:
    target = (song_hash or "").strip().lower()
    if not target:
        return None
    for row in load_cached_beatmaps():
        rec_hash = find_first_scalar(row.record, ["hash", "checksum", "mapHash", "songHash", "fileHash"])
        if isinstance(rec_hash, str) and rec_hash.lower() == target:
            return row.record
    return None


def find_cached_beatmap_record_by_id(beatmap_id: str) -> dict[str, Any] | None:
    target = str(beatmap_id or "").strip()
    if not target:
        return None
    for row in load_cached_beatmaps():
        rec_id = find_first_scalar(row.record, ["id", "beatmapId", "mapId"])
        if rec_id is not None and str(rec_id).strip() == target:
            return row.record
    return None


def find_cached_beatmap_record_by_title_artist(title: str, artist: str) -> dict[str, Any] | None:
    title_norm = normalize_text(title or "")
    artist_norm = normalize_text(artist or "")
    if not title_norm:
        return None
    for row in load_cached_beatmaps():
        if normalize_text(row.title) != title_norm:
            continue
        if artist_norm and normalize_text(row.artist) != artist_norm:
            continue
        return row.record
    return None


def build_cached_beatmap_identity_maps() -> tuple[dict[str, HeadsetSongIdentity], dict[str, HeadsetSongIdentity], dict[str, HeadsetSongIdentity]]:
    by_id: dict[str, HeadsetSongIdentity] = {}
    by_hash: dict[str, HeadsetSongIdentity] = {}
    by_title_artist: dict[str, HeadsetSongIdentity] = {}
    for row in load_cached_beatmaps():
        identity = HeadsetSongIdentity(
            file_name="",
            song_hash=str(find_first_scalar(row.record, ["hash", "checksum", "mapHash", "songHash", "fileHash"]) or "").strip().lower(),
            beatmap_id=row.beatmap_id,
            title=row.title,
            artist=row.artist,
            mapper=row.mapper,
            source="cached-beatmap",
        )
        if identity.beatmap_id:
            by_id[identity.beatmap_id] = identity
        if identity.song_hash:
            by_hash[identity.song_hash] = identity
        if identity.title:
            by_title_artist[f"{normalize_text(identity.title)}::{normalize_text(identity.artist)}"] = identity
    return by_id, by_hash, by_title_artist


def enrich_identity_from_maps(
    identity: HeadsetSongIdentity,
    by_id: dict[str, HeadsetSongIdentity],
    by_hash: dict[str, HeadsetSongIdentity],
    by_title_artist: dict[str, HeadsetSongIdentity],
) -> HeadsetSongIdentity:
    matched = None
    if identity.song_hash:
        matched = by_hash.get(identity.song_hash.lower())
    if matched is None and identity.beatmap_id:
        matched = by_id.get(identity.beatmap_id)
    if matched is None and identity.title:
        matched = by_title_artist.get(f"{normalize_text(identity.title)}::{normalize_text(identity.artist)}")
    if matched is not None:
        merge_headset_song_identity(identity, HeadsetSongIdentity(**asdict(matched)))
    return identity


def enrich_identity_from_cached_beatmap(identity: HeadsetSongIdentity) -> HeadsetSongIdentity:
    by_id, by_hash, by_title_artist = build_cached_beatmap_identity_maps()
    return enrich_identity_from_maps(identity, by_id, by_hash, by_title_artist)


def lookup_beatmap_record_by_hash(song_hash: str) -> dict[str, Any] | None:
    target = (song_hash or "").strip().lower()
    if not target:
        return None
    if target in BEATMAP_RECORD_BY_HASH_CACHE:
        return BEATMAP_RECORD_BY_HASH_CACHE[target]

    cached = find_cached_beatmap_record_by_hash(target)
    if cached:
        BEATMAP_RECORD_BY_HASH_CACHE[target] = cached
        return cached

    endpoints = [
        f"https://synthriderz.com/api/beatmaps?hash={target}",
        f"https://synthriderz.com/api/beatmaps?checksum={target}",
        f"https://synthriderz.com/api/beatmaps?songHash={target}",
        f"https://api.synthriderz.com/beatmaps?hash={target}",
        f"https://api.synthriderz.com/beatmaps?checksum={target}",
        f"https://api.synthriderz.com/beatmaps?songHash={target}",
        f"https://synthriderz.com/api/beatmaps/search?hash={target}",
        f"https://synthriderz.com/api/beatmaps/search?checksum={target}",
        f"https://synthriderz.com/api/beatmaps/search?songHash={target}",
    ]
    for endpoint in endpoints:
        try:
            payload = fetch_json(endpoint)
            record = pick_record_by_hash(payload, target)
            if record:
                BEATMAP_RECORD_BY_HASH_CACHE[target] = record
                return record
        except Exception:
            continue

    page = 1
    while page <= 2000:
        try:
            payload = fetch_json(f"https://synthriderz.com/api/beatmaps?page={page}")
            if not isinstance(payload, dict):
                break
            items = payload.get("data")
            if not isinstance(items, list):
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_hash = find_first_scalar(item, ["hash", "checksum", "mapHash", "songHash", "fileHash"])
                if isinstance(item_hash, str) and item_hash.lower() == target:
                    BEATMAP_RECORD_BY_HASH_CACHE[target] = item
                    return item
            page_count = payload.get("pageCount")
            if isinstance(page_count, int) and page >= page_count:
                break
            page += 1
        except Exception:
            break

    BEATMAP_RECORD_BY_HASH_CACHE[target] = None
    return None


def lookup_beatmap_record_by_title_artist(title: str, artist: str) -> dict[str, Any] | None:
    title_norm = normalize_text(title or "")
    artist_norm = normalize_text(artist or "")
    if not title_norm:
        return None
    cache_key = f"{title_norm}::{artist_norm}"
    if cache_key in BEATMAP_RECORD_BY_TITLE_ARTIST_CACHE:
        return BEATMAP_RECORD_BY_TITLE_ARTIST_CACHE[cache_key]

    cached = find_cached_beatmap_record_by_title_artist(title, artist)
    if cached:
        BEATMAP_RECORD_BY_TITLE_ARTIST_CACHE[cache_key] = cached
        return cached

    page = 1
    while page <= 2000:
        try:
            payload = fetch_json(f"https://synthriderz.com/api/beatmaps?page={page}")
            if not isinstance(payload, dict):
                break
            items = payload.get("data")
            if not isinstance(items, list):
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_title = normalize_text(str(item.get("title", "")))
                if item_title != title_norm:
                    continue
                if artist_norm:
                    item_artist = normalize_text(str(item.get("artist", "")))
                    if item_artist != artist_norm:
                        continue
                BEATMAP_RECORD_BY_TITLE_ARTIST_CACHE[cache_key] = item
                return item
            page_count = payload.get("pageCount")
            if isinstance(page_count, int) and page >= page_count:
                break
            page += 1
        except Exception:
            break

    BEATMAP_RECORD_BY_TITLE_ARTIST_CACHE[cache_key] = None
    return None


def enrich_song_download_metadata_shared(song: SongEntry) -> None:
    if (song.beatmapId and song.downloadUrl) or not song.hash:
        return
    if not song.beatmapId and song.sourceUrl:
        maybe_id = parse_beatmap_id(song.sourceUrl)
        if maybe_id:
            song.beatmapId = maybe_id
    record = lookup_beatmap_record_by_hash(song.hash)
    if not record:
        record = lookup_beatmap_record_by_title_artist(song.name, song.author)
    if not record:
        if song.beatmapId and not song.sourceUrl:
            song.sourceUrl = f"https://synthriderz.com/beatmaps/{song.beatmapId}"
        return

    if not song.beatmapId:
        rec_id = find_first_scalar(record, ["id", "beatmapId", "mapId"])
        if rec_id is not None:
            song.beatmapId = str(rec_id)
    if song.beatmapId and not song.sourceUrl:
        song.sourceUrl = f"https://synthriderz.com/beatmaps/{song.beatmapId}"
    if not song.downloadUrl:
        song.downloadUrl = resolve_download_url(record, song.beatmapId)


def looks_like_custom_playlist_song(song: SongEntry) -> bool:
    if song.sourceUrl and "synthriderz.com/beatmaps/" in song.sourceUrl.lower():
        return True
    if song.downloadUrl and "synthriderz.com" in song.downloadUrl.lower():
        return True
    if song.beatmapId and song.beatmapId in load_cached_beatmap_hashes_by_id():
        return True
    if song.hash and find_cached_beatmap_record_by_hash(song.hash):
        return True
    if song.name and find_cached_beatmap_record_by_title_artist(song.name, song.author):
        return True
    return False


def build_headset_song_index_fast(
    adb_path: str,
    songs_dir: str,
) -> tuple[set[str], list[str], dict[str, HeadsetSongIdentity]]:
    hashes: set[str] = set()
    filenames: list[str] = []
    identities: dict[str, HeadsetSongIdentity] = {}
    hash_by_id = load_cached_beatmap_hashes_by_id()
    hash_by_title_artist = load_cached_beatmap_hashes_by_title_artist()
    names = list_remote_files(adb_path, songs_dir)
    for name in names:
        if not name.lower().endswith(".synth"):
            continue
        filenames.append(name)
        remote_path = f"{songs_dir.rstrip('/')}/{name}"
        cached = HEADSET_SYNTH_METADATA_CACHE.get(remote_path)
        if cached is not None:
            identity = HeadsetSongIdentity(**asdict(cached))
        else:
            identity = HeadsetSongIdentity(
                file_name=name,
                beatmap_id=extract_beatmap_id_from_filename(name) or "",
                source="filename",
            )
        resolved_hash = resolve_song_identity_hash(identity, hash_by_id, hash_by_title_artist)
        if resolved_hash:
            identity.song_hash = resolved_hash
            hashes.add(resolved_hash)
        identities[name] = identity
    return hashes, filenames, identities
    return False


def resolve_song_identity_hash(
    identity: HeadsetSongIdentity,
    hash_by_id: dict[str, str],
    hash_by_title_artist: dict[str, str],
) -> str:
    if identity.song_hash:
        return identity.song_hash.lower()
    if identity.beatmap_id:
        song_hash = hash_by_id.get(identity.beatmap_id)
        if song_hash:
            return song_hash.lower()
        try:
            song = fetch_song_from_url(f"https://synthriderz.com/beatmaps/{identity.beatmap_id}")
            song_hash = song.hash.lower()
            hash_by_id[identity.beatmap_id] = song_hash
            return song_hash
        except Exception:
            pass
    if identity.title:
        key = f"{normalize_text(identity.title)}::{normalize_text(identity.artist)}"
        song_hash = hash_by_title_artist.get(key)
        if song_hash:
            return song_hash.lower()
    return ""


def read_headset_song_identity(adb_path: str, songs_dir: str, file_name: str) -> HeadsetSongIdentity:
    remote_path = f"{songs_dir.rstrip('/')}/{file_name}"
    cached = HEADSET_SYNTH_METADATA_CACHE.get(remote_path)
    if cached is not None:
        return HeadsetSongIdentity(**asdict(cached))
    identity = HeadsetSongIdentity(file_name=file_name, beatmap_id=extract_beatmap_id_from_filename(file_name) or "", source="filename")
    try:
        data = adb_read_file_bytes(adb_path, remote_path)
        parsed = extract_song_identity_from_synth_bytes(data, file_name)
        merge_headset_song_identity(identity, parsed)
    except Exception:
        pass
    HEADSET_SYNTH_METADATA_CACHE[remote_path] = HeadsetSongIdentity(**asdict(identity))
    return identity


def build_headset_song_index(adb_path: str, songs_dir: str) -> tuple[set[str], list[str], dict[str, HeadsetSongIdentity]]:
    hashes: set[str] = set()
    filenames: list[str] = []
    identities: dict[str, HeadsetSongIdentity] = {}
    hash_by_id = load_cached_beatmap_hashes_by_id()
    hash_by_title_artist = load_cached_beatmap_hashes_by_title_artist()
    names = list_remote_files(adb_path, songs_dir)
    for name in names:
        if not name.lower().endswith(".synth"):
            continue
        filenames.append(name)
        identity = read_headset_song_identity(adb_path, songs_dir, name)
        resolved_hash = resolve_song_identity_hash(identity, hash_by_id, hash_by_title_artist)
        if resolved_hash:
            identity.song_hash = resolved_hash
            hashes.add(resolved_hash)
        identities[name] = identity
    return hashes, filenames, identities


def parse_beatmap_list_entry(record: dict[str, Any]) -> BeatmapListEntry | None:
    beatmap_id = find_first_scalar(record, ["id", "beatmapId", "mapId"])
    if beatmap_id is None:
        return None

    title = str(find_first_scalar(record, ["title", "name", "songName", "songTitle"]) or "").strip()
    artist = str(find_first_scalar(record, ["artist", "author", "songAuthor", "trackAuthor"]) or "").strip()
    mapper = str(find_first_scalar(record, ["beatmapper", "mapper", "creator", "uploader", "mapped_by"]) or "").strip()
    if not mapper and isinstance(record.get("user"), dict):
        mapper = str(find_first_scalar(record["user"], ["username", "name"]) or "").strip()

    duration_value = find_first_scalar(record, ["trackDuration", "track_duration", "duration", "length", "seconds"])
    duration_seconds = parse_duration_to_seconds(duration_value, 0.0)
    duration_text = str(duration_value).strip() if isinstance(duration_value, str) and ":" in duration_value else ""
    if not duration_text:
        duration_text = f"{int(duration_seconds // 60):02d}:{int(duration_seconds % 60):02d}" if duration_seconds > 0 else ""

    uploaded_raw = (
        record.get("published_at")
        or record.get("created_at")
        or record.get("updated_at")
        or find_first_scalar(record, ["publishedAt", "createdAt", "updatedAt", "uploadedAt"])
    )
    uploaded_sort = parse_iso_datetime_to_timestamp(uploaded_raw)
    uploaded_text = datetime.fromtimestamp(uploaded_sort).strftime("%Y-%m-%d %H:%M") if uploaded_sort > 0 else ""

    difficulty_text = infer_difficulty_text_from_record(record, infer_difficulty_from_record(record))
    return BeatmapListEntry(
        beatmap_id=str(beatmap_id),
        title=title,
        artist=artist,
        mapper=mapper,
        uploaded_text=uploaded_text,
        uploaded_sort=uploaded_sort,
        duration_text=duration_text,
        duration_sort=duration_seconds,
        difficulty_text=difficulty_text,
        download_count=force_int(record.get("download_count"), 0),
        record=record,
    )


def fetch_beatmaps_page(page: int) -> tuple[list[BeatmapListEntry], int, int]:
    payload = fetch_json(f"https://synthriderz.com/api/beatmaps?page={page}")
    if not isinstance(payload, dict):
        raise RuntimeError("Beatmap list response was not a JSON object.")

    raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        raise RuntimeError("Beatmap list response did not contain a data list.")

    items: list[BeatmapListEntry] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        parsed = parse_beatmap_list_entry(item)
        if parsed is not None:
            items.append(parsed)

    page_count = force_int(payload.get("pageCount"), 1)
    total_count = force_int(payload.get("total"), len(items))
    return items, page_count, total_count


def fetch_all_beatmaps(progress_cb: Callable[[int, int, int], None] | None = None) -> list[BeatmapListEntry]:
    first_page_rows, page_count, total_count = fetch_beatmaps_page(1)
    all_rows = list(first_page_rows)
    if progress_cb:
        progress_cb(1, page_count, len(all_rows))

    for page in range(2, page_count + 1):
        rows, _, _ = fetch_beatmaps_page(page)
        all_rows.extend(rows)
        if progress_cb:
            progress_cb(page, page_count, len(all_rows))

    if total_count and len(all_rows) > total_count:
        all_rows = all_rows[:total_count]
    return all_rows


def beatmap_cache_file_path() -> Path:
    return Path.home() / ".sr_playlist_forge_beatmaps_cache.json"


def beatmap_cover_cache_dir() -> Path:
    return Path.home() / ".sr_playlist_forge_beatmap_covers"


def beatmap_cover_cache_path(beatmap_id: str) -> Path:
    return beatmap_cover_cache_dir() / f"{beatmap_id}.img"


def cover_url_from_record(record: dict[str, Any], beatmap_id: str) -> str:
    raw = find_first_url(record, ["cover_url", "coverUrl", "coverURL", "image", "imageUrl"])
    if raw:
        return urljoin("https://synthriderz.com", raw) if raw.startswith("/") else raw
    return f"https://synthriderz.com/api/beatmaps/{beatmap_id}/cover"


def load_cached_beatmaps() -> list[BeatmapListEntry]:
    path = beatmap_cache_file_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return []

    rows: list[BeatmapListEntry] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        parsed = parse_beatmap_list_entry(item)
        if parsed is not None:
            rows.append(parsed)
    return rows


def save_cached_beatmaps(rows: list[BeatmapListEntry]) -> None:
    payload = {
        "savedAt": int(time.time()),
        "count": len(rows),
        "items": [row.record for row in rows],
    }
    try:
        beatmap_cache_file_path().write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def merge_beatmap_rows(existing: list[BeatmapListEntry], incoming: list[BeatmapListEntry]) -> list[BeatmapListEntry]:
    merged: dict[str, BeatmapListEntry] = {row.beatmap_id: row for row in existing}
    for row in incoming:
        merged[row.beatmap_id] = row
    return list(merged.values())


def fetch_newer_beatmaps(
    known_latest: BeatmapListEntry | None,
    progress_cb: Callable[[int, int, int], None] | None = None,
) -> tuple[list[BeatmapListEntry], int]:
    first_page_rows, page_count, total_count = fetch_beatmaps_page(1)
    if progress_cb:
        progress_cb(1, page_count, len(first_page_rows))

    if known_latest is None:
        all_rows = list(first_page_rows)
        for page in range(2, page_count + 1):
            rows, _, _ = fetch_beatmaps_page(page)
            all_rows.extend(rows)
            if progress_cb:
                progress_cb(page, page_count, len(all_rows))
        return all_rows, total_count

    latest_id = known_latest.beatmap_id
    incoming: list[BeatmapListEntry] = []
    loaded_count = 0

    for page in range(1, page_count + 1):
        rows = first_page_rows if page == 1 else fetch_beatmaps_page(page)[0]
        loaded_count += len(rows)
        if progress_cb and page != 1:
            progress_cb(page, page_count, loaded_count)
        for row in rows:
            if row.beatmap_id == latest_id:
                return incoming, total_count
            incoming.append(row)
    return incoming, total_count


def parse_song_from_beatmap_html(html_text: str, beatmap_id: str) -> SongEntry:
    # Try embedded app state first (__NEXT_DATA__, __NUXT__, window.__INITIAL_STATE__)
    patterns = [
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        r"window\.__INITIAL_STATE__\s*=\s*({.*?});",
        r"__NUXT__\s*=\s*({.*?});",
    ]
    for pattern in patterns:
        m = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        blob = m.group(1).strip()
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            continue
        for node in walk_values(parsed):
            if not isinstance(node, dict):
                continue
            node_id = find_first_scalar(node, ["id", "beatmapId", "mapId"])
            if str(node_id) != beatmap_id:
                continue
            if find_first_scalar(node, ["hash", "checksum", "mapHash", "songHash", "fileHash"]) is None:
                continue
            return parse_song_from_record(node, beatmap_id)

    # Fallback: regex scrape when embedded JSON cannot be parsed.
    hash_match = re.search(r'"hash"\s*:\s*"([a-fA-F0-9]{64})"', html_text)
    if not hash_match:
        raise RuntimeError("No song hash found in beatmap page HTML.")
    record: dict[str, Any] = {
        "hash": hash_match.group(1),
        "title": "",
        "artist": "",
        "beatmapper": "",
        "difficulty": 0,
        "duration": 0.0,
    }
    og_title = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html_text, flags=re.IGNORECASE)
    if og_title:
        record["title"] = unescape(og_title.group(1)).strip()
    artist_match = re.search(r'"artist"\s*:\s*"([^"]+)"', html_text)
    if artist_match:
        record["artist"] = unescape(artist_match.group(1)).strip()
    mapper_match = re.search(r'"(beatmapper|mapper|creator)"\s*:\s*"([^"]+)"', html_text)
    if mapper_match:
        record["beatmapper"] = unescape(mapper_match.group(2)).strip()
    duration_match = re.search(r'"(trackDuration|duration|length|seconds)"\s*:\s*([0-9]+(?:\.[0-9]+)?)', html_text)
    if duration_match:
        record["duration"] = force_float(duration_match.group(2), 0.0)
    difficulty_match = re.search(r'"difficulty"\s*:\s*([0-9]+)', html_text)
    if difficulty_match:
        record["difficulty"] = force_int(difficulty_match.group(1), 0)
    download_match = re.search(
        r'"(downloadUrl|downloadURL|downloadLink|download)"\s*:\s*"([^"]+)"', html_text, flags=re.IGNORECASE
    )
    if download_match:
        raw = unescape(download_match.group(2)).strip()
        record["downloadUrl"] = urljoin("https://synthriderz.com", raw) if raw.startswith("/") else raw

    return parse_song_from_record(record, beatmap_id)


def resolve_download_url(record: dict[str, Any], beatmap_id: str) -> str:
    direct = find_first_url(
        record,
        [
            "download",
            "downloadUrl",
            "downloadURL",
            "downloadLink",
            "fileUrl",
            "fileURL",
            "mapDownload",
            "zipUrl",
            "zipURL",
        ],
    )
    if direct:
        if direct.startswith("/"):
            return urljoin("https://synthriderz.com", direct)
        return direct

    return f"https://synthriderz.com/api/beatmaps/{beatmap_id}/download"


def get_download_url_candidates(song: SongEntry) -> list[str]:
    out: list[str] = []
    if song.downloadUrl:
        out.append(song.downloadUrl)
    if song.beatmapId:
        out.extend(
            [
                f"https://synthriderz.com/api/beatmaps/{song.beatmapId}/download",
                f"https://synthriderz.com/api/beatmaps/{song.beatmapId}/download?hash={song.hash}",
                f"https://synthriderz.com/api/beatmaps/download/{song.beatmapId}",
                f"https://api.synthriderz.com/beatmaps/{song.beatmapId}/download",
                f"https://synthriderz.com/beatmaps/{song.beatmapId}/download",
            ]
        )
    if song.hash:
        out.extend(
            [
                f"https://synthriderz.com/api/beatmaps/download?hash={song.hash}",
                f"https://synthriderz.com/api/beatmaps/download?checksum={song.hash}",
                f"https://synthriderz.com/api/beatmaps/download?songHash={song.hash}",
                f"https://api.synthriderz.com/beatmaps/download?hash={song.hash}",
                f"https://api.synthriderz.com/beatmaps/download?checksum={song.hash}",
                f"https://api.synthriderz.com/beatmaps/download?songHash={song.hash}",
            ]
        )
    seen: set[str] = set()
    deduped: list[str] = []
    for url in out:
        if url and url not in seen:
            deduped.append(url)
            seen.add(url)
    return deduped


def extract_filename_from_headers(content_disposition: str | None) -> str:
    if not content_disposition:
        return ""
    # Handles both filename="x.synth" and filename*=UTF-8''x.synth
    m = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip().strip('"')
    m = re.search(r'filename="?([^";]+)"?', content_disposition, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def pick_download_url_from_json(payload: Any) -> str | None:
    records = iter_dict_values(payload)
    for rec in records:
        candidate = find_first_url(
            rec,
            [
                "download",
                "downloadUrl",
                "downloadURL",
                "downloadLink",
                "fileUrl",
                "fileURL",
                "mapDownload",
                "zipUrl",
                "zipURL",
            ],
        )
        if candidate:
            if candidate.startswith("/"):
                return urljoin("https://synthriderz.com", candidate)
            return candidate
    return None


def download_song_to_dir(
    song: SongEntry,
    out_dir: Path,
    progress_cb: Callable[[int, int | None, str], None] | None = None,
    cancel_cb: Callable[[], bool] | None = None,
) -> tuple[Path, str]:
    errors: list[str] = []
    url_candidates = get_download_url_candidates(song)
    if not url_candidates:
        raise RuntimeError("No download URL candidates available for this song.")

    for candidate in url_candidates:
        if cancel_cb and cancel_cb():
            raise DownloadCancelled("Download cancelled by user.")
        try:
            req = Request(candidate, headers=DEFAULT_HEADERS)
            with urlopen(req, timeout=40) as response:
                content_type = str(response.headers.get("Content-Type", "")).lower()
                content_disposition = response.headers.get("Content-Disposition")
                final_url = response.geturl()

                if "application/json" in content_type:
                    raw = response.read()
                    payload = json.loads(raw.decode("utf-8"))
                    nested_url = pick_download_url_from_json(payload)
                    if nested_url and nested_url != candidate:
                        url_candidates.append(nested_url)
                        continue
                    errors.append(f"{candidate}: returned JSON without a download URL")
                    continue

                filename = extract_filename_from_headers(content_disposition)
                if not filename:
                    basename = os.path.basename(final_url.split("?", 1)[0])
                    filename = basename if basename else ""
                if not filename.lower().endswith(".synth"):
                    prefix = safe_filename(song.name) if song.name else (song.beatmapId or song.hash[:10])
                    filename = f"{prefix}.synth"

                out_path = out_dir / filename
                if out_path.exists():
                    stem = out_path.stem
                    suffix = out_path.suffix
                    for i in range(2, 1000):
                        candidate_path = out_dir / f"{stem}_{i}{suffix}"
                        if not candidate_path.exists():
                            out_path = candidate_path
                            break

                total_size = None
                total_header = response.headers.get("Content-Length")
                if total_header:
                    total_size = force_int(total_header, 0) or None

                written = 0
                chunk_size = 256 * 1024
                try:
                    with out_path.open("wb") as f:
                        while True:
                            if cancel_cb and cancel_cb():
                                raise DownloadCancelled("Download cancelled by user.")
                            chunk = response.read(chunk_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            written += len(chunk)
                            if progress_cb:
                                progress_cb(written, total_size, filename)
                except Exception:
                    if out_path.exists():
                        out_path.unlink(missing_ok=True)
                    raise

                if progress_cb:
                    progress_cb(written, total_size, filename)
                return out_path, candidate
        except DownloadCancelled:
            raise
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError, RuntimeError) as err:
            errors.append(f"{candidate}: {err}")
            continue

    raise RuntimeError("\n".join(errors))


def fetch_song_from_url(url_text: str) -> SongEntry:
    beatmap_id = parse_beatmap_id(url_text)
    if not beatmap_id:
        raise ValueError("URL must look like https://synthriderz.com/beatmaps/<id>")

    endpoints = [
        f"https://synthriderz.com/api/beatmaps/{beatmap_id}",
        f"https://synthriderz.com/api/beatmaps/{beatmap_id}/json",
        f"https://synthriderz.com/api/beatmap/{beatmap_id}",
        f"https://synthriderz.com/api/beatmaps?id={beatmap_id}",
        f"https://synthriderz.com/api/beatmaps/{beatmap_id}?format=json",
        f"https://api.synthriderz.com/beatmaps/{beatmap_id}",
    ]

    payload = None
    last_err: Exception | None = None
    for endpoint in endpoints:
        try:
            payload = fetch_json(endpoint)
            break
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as err:
            last_err = err
            continue

    if payload is None:
        # Fallback: scan paged list endpoint for this beatmap ID.
        page = 1
        while page <= 2000:
            try:
                page_payload = fetch_json(f"https://synthriderz.com/api/beatmaps?page={page}")
                if not isinstance(page_payload, dict):
                    break
                items = page_payload.get("data")
                if not isinstance(items, list):
                    break
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item_id = find_first_scalar(item, ["id", "beatmapId", "mapId"])
                    if str(item_id) == beatmap_id:
                        return parse_song_from_record(item, beatmap_id)
                page_count = page_payload.get("pageCount")
                if isinstance(page_count, int) and page >= page_count:
                    break
                page += 1
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
                break

        try:
            html_text = fetch_text(f"https://synthriderz.com/beatmaps/{beatmap_id}")
            return parse_song_from_beatmap_html(html_text, beatmap_id)
        except Exception as html_err:  # noqa: BLE001
            raise RuntimeError(f"Unable to fetch beatmap data ({last_err}); HTML fallback failed ({html_err})")

    rec = pick_best_record(payload, beatmap_id)
    if not rec:
        raise RuntimeError("Beatmap response did not contain a usable record.")
    return parse_song_from_record(rec, beatmap_id)


class SongEditDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, song: SongEntry):
        super().__init__(parent)
        self.title("Edit Song")
        self.resizable(False, False)
        self.result: SongEntry | None = None
        self.song = SongEntry(**asdict(song))

        self.vars: dict[str, tk.StringVar] = {
            "hash": tk.StringVar(value=self.song.hash),
            "name": tk.StringVar(value=self.song.name),
            "author": tk.StringVar(value=self.song.author),
            "beatmapper": tk.StringVar(value=self.song.beatmapper),
            "difficulty": tk.StringVar(value=str(self.song.difficulty)),
            "difficultyText": tk.StringVar(value=self.song.difficultyText),
            "trackDuration": tk.StringVar(value=str(self.song.trackDuration)),
            "addedTime": tk.StringVar(value=str(self.song.addedTime)),
            "beatmapId": tk.StringVar(value=self.song.beatmapId),
            "sourceUrl": tk.StringVar(value=self.song.sourceUrl),
            "downloadUrl": tk.StringVar(value=self.song.downloadUrl),
        }
        field_labels = {
            "hash": "hash",
            "name": "name",
            "author": "artist",
            "beatmapper": "mapper",
            "difficulty": "difficulty",
            "trackDuration": "duration (sec)",
            "addedTime": "added (unix)",
            "beatmapId": "beatmapId",
            "sourceUrl": "sourceUrl",
            "downloadUrl": "downloadUrl",
        }

        row = 0
        for field in [
            "hash",
            "name",
            "author",
            "beatmapper",
            "difficulty",
            "difficultyText",
            "trackDuration",
            "addedTime",
            "beatmapId",
            "sourceUrl",
            "downloadUrl",
        ]:
            ttk.Label(self, text=field_labels[field]).grid(row=row, column=0, sticky="w", padx=8, pady=4)
            ttk.Entry(self, width=70, textvariable=self.vars[field]).grid(row=row, column=1, padx=8, pady=4)
            row += 1

        btns = ttk.Frame(self)
        btns.grid(row=row, column=0, columnspan=2, sticky="e", padx=8, pady=8)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save", command=self.on_save).pack(side="right")

        self.transient(parent)
        self.grab_set()
        self.wait_visibility()
        self.focus()

    def on_save(self) -> None:
        song_hash = self.vars["hash"].get().strip()
        if not song_hash:
            messagebox.showerror("Invalid Song", "hash is required.")
            return
        self.result = SongEntry(
            hash=song_hash,
            name=self.vars["name"].get(),
            author=self.vars["author"].get(),
            beatmapper=self.vars["beatmapper"].get(),
            difficulty=force_int(self.vars["difficulty"].get(), 0),
            difficultyText=self.vars["difficultyText"].get().strip(),
            trackDuration=force_float(self.vars["trackDuration"].get(), 0.0),
            addedTime=force_int(self.vars["addedTime"].get(), int(time.time())),
            beatmapId=self.vars["beatmapId"].get().strip(),
            sourceUrl=self.vars["sourceUrl"].get().strip(),
            downloadUrl=self.vars["downloadUrl"].get().strip(),
        )
        self.destroy()


class HoverTooltip:
    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self.tipwindow: tk.Toplevel | None = None
        self.after_id: str | None = None
        self.enabled = ENABLE_HOVER_TOOLTIPS
        self.widget.bind("<Enter>", self.schedule_show)
        self.widget.bind("<Leave>", self.hide)
        self.widget.bind("<ButtonPress>", self.hide)

    def schedule_show(self, _event=None):
        if not self.enabled or self.tipwindow is not None or self.after_id is not None:
            return
        try:
            self.after_id = self.widget.after(450, self.show)
        except tk.TclError:
            self.after_id = None

    def show(self, _event=None):
        self.after_id = None
        if not self.enabled:
            return
        if self.tipwindow is not None:
            return
        tip_text = self.text.strip() if self.text else ""
        if not tip_text:
            tip_text = "Ingen information tillgänglig."
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + 20
        tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=tip_text,
            justify="left",
            foreground="#111111",
            background="#fff8bf",
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=6,
            wraplength=360,
        )
        label.pack()
        self.tipwindow = tw

    def hide(self, _event=None):
        if self.after_id is not None:
            try:
                self.widget.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None
        if self.tipwindow is not None:
            self.tipwindow.destroy()
            self.tipwindow = None


class QuestTransferDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, song_dir: str, playlist_dir: str):
        super().__init__(parent)
        self.title("Send to Quest")
        self.resizable(False, False)
        self.result: dict[str, str] | None = None

        self.song_dir_var = tk.StringVar(value=song_dir)
        self.playlist_dir_var = tk.StringVar(value=playlist_dir)
        self.transfer_mode_var = tk.StringVar(value="both")
        self.duplicate_mode_var = tk.StringVar(value="skip")

        self._build_ui()
        self.transient(parent)
        self.grab_set()
        self.wait_visibility()
        self.focus()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="Choose what to send and how duplicates should be handled.").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )

        ttk.Label(root, text="Songs Folder").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        ttk.Entry(root, textvariable=self.song_dir_var, width=56).grid(row=1, column=1, sticky="we", pady=4)

        ttk.Label(root, text="Playlist Folder").grid(row=2, column=0, sticky="e", padx=(0, 8), pady=4)
        ttk.Entry(root, textvariable=self.playlist_dir_var, width=56).grid(row=2, column=1, sticky="we", pady=4)

        transfer_box = ttk.LabelFrame(root, text="Transfer")
        transfer_box.grid(row=3, column=0, columnspan=2, sticky="we", pady=(10, 6))
        ttk.Radiobutton(transfer_box, text="Songs and Playlist", variable=self.transfer_mode_var, value="both").pack(
            anchor="w", padx=8, pady=2
        )
        ttk.Radiobutton(transfer_box, text="Songs Only", variable=self.transfer_mode_var, value="songs").pack(
            anchor="w", padx=8, pady=2
        )
        ttk.Radiobutton(transfer_box, text="Playlist Only", variable=self.transfer_mode_var, value="playlist").pack(
            anchor="w", padx=8, pady=2
        )

        duplicate_box = ttk.LabelFrame(root, text="Duplicates on Headset")
        duplicate_box.grid(row=4, column=0, columnspan=2, sticky="we", pady=6)
        ttk.Radiobutton(duplicate_box, text="Skip existing files", variable=self.duplicate_mode_var, value="skip").pack(
            anchor="w", padx=8, pady=2
        )
        ttk.Radiobutton(
            duplicate_box,
            text="Overwrite existing files",
            variable=self.duplicate_mode_var,
            value="overwrite",
        ).pack(anchor="w", padx=8, pady=2)

        buttons = ttk.Frame(root)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Start Transfer", command=self.on_confirm).pack(side="right")

        root.columnconfigure(1, weight=1)

    def on_confirm(self) -> None:
        song_dir = self.song_dir_var.get().strip()
        playlist_dir = self.playlist_dir_var.get().strip()
        if not song_dir:
            messagebox.showerror("Missing Songs Folder", "Quest songs folder is required.", parent=self)
            return
        if not playlist_dir:
            messagebox.showerror("Missing Playlist Folder", "Quest playlist folder is required.", parent=self)
            return
        self.result = {
            "song_dir": song_dir,
            "playlist_dir": playlist_dir,
            "transfer_mode": self.transfer_mode_var.get(),
            "duplicate_mode": self.duplicate_mode_var.get(),
        }
        self.destroy()


class QuestSongManagerDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, adb_path: str, songs_dir: str, playlist_dir: str):
        super().__init__(parent)
        self.title("Quest Songs")
        self.geometry("1120x680")
        self.minsize(940, 540)
        self.adb_path = adb_path
        self.songs_dir = songs_dir
        self.playlist_dir = playlist_dir
        self.status_var = tk.StringVar(value="Loading headset songs...")
        self.filter_var = tk.StringVar(value="all")
        self.search_var = tk.StringVar(value="")
        self.files: list[str] = []
        self.visible_files: list[str] = []
        self.orphan_status: dict[str, str] = {}
        self.file_details: dict[str, HeadsetSongIdentity] = {}
        self.loading = False
        self.sort_column = "filename"
        self.sort_desc = False

        self._build_ui()
        self.transient(parent)
        self.grab_set()
        self.refresh_files()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x", pady=(0, 8))
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Quest Songs Folder").grid(row=0, column=0, sticky="w")
        ttk.Label(top, text=self.songs_dir).grid(row=0, column=1, sticky="we", padx=(8, 12))
        filter_buttons = ttk.Frame(top)
        filter_buttons.grid(row=0, column=2, sticky="e")
        ttk.Button(filter_buttons, text="Refresh", command=self.refresh_files).pack(side="right")
        ttk.Button(filter_buttons, text="Possible Orphans", command=lambda: self.set_filter("orphan")).pack(side="right", padx=(6, 0))
        ttk.Button(filter_buttons, text="Unknown", command=lambda: self.set_filter("unknown")).pack(side="right", padx=(6, 0))
        ttk.Button(filter_buttons, text="All", command=lambda: self.set_filter("all")).pack(side="right", padx=(6, 0))

        search_row = ttk.Frame(root)
        search_row.pack(fill="x", pady=(0, 8))
        ttk.Label(search_row, text="Search").pack(side="left")
        search_entry = ttk.Entry(search_row, textvariable=self.search_var, width=30)
        search_entry.pack(side="left", padx=(6, 0))
        self.search_var.trace_add("write", lambda *_: self.render_files())

        table_frame = ttk.Frame(root)
        table_frame.pack(fill="both", expand=True)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("filename", "artist", "mapper", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("filename", text="Filename", command=lambda: self.sort_by("filename"))
        self.tree.heading("artist", text="Artist", command=lambda: self.sort_by("artist"))
        self.tree.heading("mapper", text="Mapper", command=lambda: self.sort_by("mapper"))
        self.tree.heading("status", text="Playlist Status", command=lambda: self.sort_by("status"))
        self.tree.column("filename", anchor="w", width=620, stretch=True)
        self.tree.column("artist", anchor="w", width=150, stretch=True)
        self.tree.column("mapper", anchor="w", width=150, stretch=True)
        self.tree.column("status", anchor="w", width=160, stretch=False)
        self.tree.tag_configure("possible_orphan", background="#fef2f2", foreground="#991b1b")
        self.tree.tag_configure("in_playlist", background="#f0fdf4", foreground="#166534")
        self.tree.tag_configure("unknown", background="#fffbeb", foreground="#92400e")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Delete>", self.on_delete_key)
        self.tree.bind("<Control-a>", self.on_select_all_shortcut)
        self.tree.bind("<Control-A>", self.on_select_all_shortcut)

        bottom = ttk.Frame(root)
        bottom.pack(fill="x", pady=(8, 0))
        ttk.Label(bottom, textvariable=self.status_var).pack(side="left")
        action_groups = ttk.Frame(bottom)
        action_groups.pack(side="right")

        manage_group = ttk.LabelFrame(action_groups, text="Select / Backup", padding=(8, 6))
        manage_group.pack(side="left")
        ttk.Button(manage_group, text="Backup Selected", command=self.backup_selected).pack(side="left", padx=(0, 6))
        ttk.Button(manage_group, text="Select All Visible", command=self.select_all_visible).pack(side="left", padx=6)
        ttk.Button(manage_group, text="Select Possible Orphans", command=self.select_orphans).pack(side="left", padx=(6, 0))

        delete_group = ttk.LabelFrame(action_groups, text="Delete", padding=(8, 6))
        delete_group.pack(side="left", padx=(10, 0))
        ttk.Button(delete_group, text="Delete Possible Orphans", command=self.delete_orphans).pack(side="left", padx=(0, 6))
        ttk.Button(delete_group, text="Delete Selected", command=self.delete_selected).pack(side="left", padx=(6, 0))

        ttk.Button(action_groups, text="Close", command=self.destroy).pack(side="left", padx=(10, 0))

    def refresh_files(self) -> None:
        if self.loading:
            return
        self.loading = True
        self.status_var.set("Loading headset songs...")
        self.tree.delete(*self.tree.get_children())
        self.files = []
        self.visible_files = []
        self.file_details = {}

        def worker() -> None:
            try:
                names = list_remote_files(self.adb_path, self.songs_dir)
                synth_files = sorted([name for name in names if name.lower().endswith(".synth")], key=str.lower)
                by_id, by_hash, by_title_artist = build_cached_beatmap_identity_maps()
                details: dict[str, HeadsetSongIdentity] = {}
                for name in synth_files:
                    remote_path = f"{self.songs_dir.rstrip('/')}/{name}"
                    cached = HEADSET_SYNTH_METADATA_CACHE.get(remote_path)
                    if cached is not None:
                        identity = HeadsetSongIdentity(**asdict(cached))
                    else:
                        identity = HeadsetSongIdentity(file_name=name, beatmap_id=extract_beatmap_id_from_filename(name) or "", source="filename")
                    details[name] = enrich_identity_from_maps(identity, by_id, by_hash, by_title_artist)
                safe_after(self, lambda details=details: self._finish_refresh(synth_files, details, None))
            except Exception as err:  # noqa: BLE001
                safe_after(self, lambda err=err: self._finish_refresh([], {}, err))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_refresh(self, files: list[str], details: dict[str, HeadsetSongIdentity], err: Exception | None) -> None:
        if not self.winfo_exists() or not self.tree.winfo_exists():
            return
        self.loading = False
        if err is not None:
            self.status_var.set(f"Load failed: {err}")
            messagebox.showerror("Quest Songs", str(err), parent=self)
            return
        self.files = files
        self.file_details = details
        self.render_files()
        self.status_var.set(f"Headset songs: {len(files)}")
        safe_after(self, self.compute_orphan_status)

    def selected_files(self) -> list[str]:
        selected: list[str] = []
        for item_id in self.tree.selection():
            idx = force_int(item_id, -1)
            if 0 <= idx < len(self.visible_files):
                selected.append(self.visible_files[idx])
        return selected

    def set_filter(self, value: str) -> None:
        self.filter_var.set(value)
        self.render_files()

    def sort_by(self, column: str) -> None:
        if self.sort_column == column:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_column = column
            self.sort_desc = False
        self.render_files()

    def render_files(self) -> None:
        self.tree.delete(*self.tree.get_children())
        active_filter = self.filter_var.get()
        search_text = normalize_text(self.search_var.get())
        visible_files: list[str] = []
        visible_count = 0
        filtered_files = list(self.files)
        if self.sort_column:
            def sort_key(file_name: str):
                detail = self.file_details.get(file_name, HeadsetSongIdentity(file_name=file_name))
                status = self.orphan_status.get(file_name, "Unknown")
                if self.sort_column == "artist":
                    return normalize_text(detail.artist)
                if self.sort_column == "mapper":
                    return normalize_text(detail.mapper)
                if self.sort_column == "status":
                    return normalize_text(status)
                return normalize_text(file_name)
            filtered_files.sort(key=sort_key, reverse=self.sort_desc)

        for name in filtered_files:
            status = self.orphan_status.get(name, "Unknown")
            if active_filter == "orphan" and status != "Possibly orphan":
                continue
            if active_filter == "unknown" and status != "Unknown":
                continue
            detail = self.file_details.get(name, HeadsetSongIdentity(file_name=name))
            if search_text:
                haystack = " ".join(
                    [
                        normalize_text(name),
                        normalize_text(detail.title),
                        normalize_text(detail.artist),
                        normalize_text(detail.mapper),
                        normalize_text(status),
                    ]
                )
                if search_text not in haystack:
                    continue
            tag = "unknown"
            if status == "Possibly orphan":
                tag = "possible_orphan"
            elif status == "In playlist":
                tag = "in_playlist"
            idx = len(visible_files)
            self.tree.insert("", "end", iid=str(idx), values=(name, detail.artist, detail.mapper, status), tags=(tag,))
            visible_files.append(name)
            visible_count += 1
        self.visible_files = visible_files
        if self.files:
            self.status_var.set(f"Headset songs: {len(self.files)} | Showing: {visible_count}")

    def compute_orphan_status(self) -> None:
        self.status_var.set("Checking playlist usage...")

        def worker() -> None:
            try:
                playlist_hashes = collect_playlist_hashes_from_remote(self.adb_path, self.playlist_dir)
                hash_by_id = load_cached_beatmap_hashes_by_id()
                hash_by_title_artist = load_cached_beatmap_hashes_by_title_artist()
                status_map: dict[str, str] = {}
                for name in self.files:
                    identity = read_headset_song_identity(self.adb_path, self.songs_dir, name)
                    song_hash = resolve_song_identity_hash(identity, hash_by_id, hash_by_title_artist)
                    if not song_hash:
                        status_map[name] = "Unknown"
                        continue
                    status_map[name] = "In playlist" if song_hash.lower() in playlist_hashes else "Possibly orphan"
                safe_after(self, lambda: self.apply_orphan_status(status_map))
            except Exception as err:  # noqa: BLE001
                safe_after(self, lambda err=err: self.status_var.set(f"Usage check failed: {err}"))

        threading.Thread(target=worker, daemon=True).start()

    def apply_orphan_status(self, status_map: dict[str, str]) -> None:
        if not self.winfo_exists() or not self.tree.winfo_exists():
            return
        self.orphan_status = status_map
        self.render_files()
        orphan_count = sum(1 for status in status_map.values() if status == "Possibly orphan")
        self.status_var.set(f"Headset songs: {len(self.files)} | Possible orphans: {orphan_count}")

    def select_orphans(self) -> None:
        orphan_ids = [str(idx) for idx, name in enumerate(self.visible_files) if self.orphan_status.get(name) == "Possibly orphan"]
        if not orphan_ids:
            messagebox.showinfo("Select Possible Orphans", "No possible orphan songs were found.", parent=self)
            return
        self.tree.selection_set(orphan_ids)
        self.tree.focus(orphan_ids[0])
        self.status_var.set(f"Selected possible orphans: {len(orphan_ids)}")

    def select_all_visible(self) -> None:
        all_ids = [str(idx) for idx in range(len(self.visible_files))]
        if not all_ids:
            messagebox.showinfo("Select All Visible", "There are no visible songs to select.", parent=self)
            return
        self.tree.selection_set(all_ids)
        self.tree.focus(all_ids[0])
        self.status_var.set(f"Selected visible songs: {len(all_ids)}")

    def on_delete_key(self, _event=None) -> None:
        self.delete_selected()

    def on_select_all_shortcut(self, _event=None):
        self.select_all_visible()
        return "break"

    def delete_selected(self) -> None:
        selected = self.selected_files()
        if not selected:
            messagebox.showerror("No Selection", "Select one or more songs first.", parent=self)
            return
        if not self.confirm_delete("songs", selected):
            return

        count = len(selected)
        self.status_var.set(f"Deleting {count} songs...")

        def worker() -> None:
            failed: list[str] = []
            for name in selected:
                remote_path = f"{self.songs_dir.rstrip('/')}/{name}"
                try:
                    adb_delete_file(self.adb_path, remote_path)
                    HEADSET_SYNTH_METADATA_CACHE.pop(remote_path, None)
                except Exception as err:  # noqa: BLE001
                    failed.append(f"{name}: {err}")
            safe_after(self, lambda: self._finish_delete(count, failed))

        threading.Thread(target=worker, daemon=True).start()

    def backup_selected(self) -> None:
        selected = self.selected_files()
        if not selected:
            messagebox.showerror("No Selection", "Select one or more songs first.", parent=self)
            return
        out_dir = filedialog.askdirectory(title="Select Backup Folder")
        if not out_dir:
            return
        self.status_var.set(f"Backing up {len(selected)} songs...")

        def worker() -> None:
            failed: list[str] = []
            copied = 0
            base_dir = Path(out_dir)
            for name in selected:
                remote_path = f"{self.songs_dir.rstrip('/')}/{name}"
                local_path = base_dir / name
                try:
                    adb_pull_file(self.adb_path, remote_path, local_path)
                    copied += 1
                except Exception as err:  # noqa: BLE001
                    failed.append(f"{name}: {err}")
            safe_after(self, lambda: self._finish_backup("songs", copied, failed))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_delete(self, count: int, failed: list[str]) -> None:
        if not self.winfo_exists():
            return
        if failed:
            messagebox.showerror(
                "Delete Failed",
                "\n".join(failed[:10]) + (f"\n...and {len(failed) - 10} more" if len(failed) > 10 else ""),
                parent=self,
            )
        else:
            messagebox.showinfo("Deleted", f"Deleted {count} songs.", parent=self)
        self.refresh_files()

    def delete_orphans(self) -> None:
        selected = [name for name in self.files if self.orphan_status.get(name) == "Possibly orphan"]
        if not selected:
            messagebox.showinfo("Delete Possible Orphans", "No possible orphan songs were found.", parent=self)
            return
        if not self.confirm_delete("possible orphan songs", selected):
            return

        count = len(selected)
        self.status_var.set(f"Deleting {count} possible orphan songs...")

        def worker() -> None:
            failed: list[str] = []
            for name in selected:
                remote_path = f"{self.songs_dir.rstrip('/')}/{name}"
                try:
                    adb_delete_file(self.adb_path, remote_path)
                    HEADSET_SYNTH_METADATA_CACHE.pop(remote_path, None)
                except Exception as err:  # noqa: BLE001
                    failed.append(f"{name}: {err}")
            safe_after(self, lambda: self._finish_delete(count, failed))

        threading.Thread(target=worker, daemon=True).start()

    def confirm_delete(self, label: str, names: list[str]) -> bool:
        count = len(names)
        preview = "\n".join(names[:12])
        if len(names) > 12:
            preview += f"\n...and {len(names) - 12} more"
        return messagebox.askyesno(
            f"Delete {label.title()}",
            f"Are you sure you want to delete {count} {label}?\n\n{preview}",
            parent=self,
        )

    def _finish_backup(self, label: str, copied: int, failed: list[str]) -> None:
        if not self.winfo_exists():
            return
        if failed:
            messagebox.showerror(
                "Backup Incomplete",
                f"Copied {copied} {label}.\n\n" + "\n".join(failed[:10]) + (f"\n...and {len(failed) - 10} more" if len(failed) > 10 else ""),
                parent=self,
            )
        else:
            messagebox.showinfo("Backup Complete", f"Copied {copied} {label} to your computer.", parent=self)
        self.status_var.set(f"Headset songs: {len(self.files)} | Showing: {len(self.visible_files)}")


class QuestPlaylistManagerDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, adb_path: str, playlist_dir: str):
        super().__init__(parent)
        self.title("Quest Playlists")
        self.geometry("1080x660")
        self.minsize(900, 520)
        self.result: str | None = None
        self.adb_path = adb_path
        self.playlist_dir = playlist_dir
        self.songs_dir = getattr(parent, "quest_song_dir_var").get().strip() if hasattr(parent, "quest_song_dir_var") else ""
        self.status_var = tk.StringVar(value="Loading headset playlists...")
        self.filter_var = tk.StringVar(value="all")
        self.files: list[str] = []
        self.visible_files: list[str] = []
        self.playlist_status: dict[str, str] = {}
        self.loading = False

        self._build_ui()
        self.transient(parent)
        self.grab_set()
        self.refresh_files()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x", pady=(0, 8))
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Quest Playlist Folder").grid(row=0, column=0, sticky="w")
        ttk.Label(top, text=self.playlist_dir).grid(row=0, column=1, sticky="we", padx=(8, 12))
        filter_buttons = ttk.Frame(top)
        filter_buttons.grid(row=0, column=2, sticky="e")
        ttk.Button(filter_buttons, text="Refresh", command=self.refresh_files).pack(side="right")
        ttk.Button(filter_buttons, text="Broken", command=lambda: self.set_filter("broken")).pack(side="right", padx=(6, 0))
        ttk.Button(filter_buttons, text="All", command=lambda: self.set_filter("all")).pack(side="right", padx=(6, 0))

        table_frame = ttk.Frame(root)
        table_frame.pack(fill="both", expand=True)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(table_frame, columns=("filename", "status"), show="headings", selectmode="extended")
        self.tree.heading("filename", text="Filename")
        self.tree.heading("status", text="Status")
        self.tree.column("filename", anchor="w", width=760, stretch=True)
        self.tree.column("status", anchor="w", width=220, stretch=False)
        self.tree.tag_configure("ok", background="#f0fdf4", foreground="#166534")
        self.tree.tag_configure("warning", background="#fffbeb", foreground="#92400e")
        self.tree.tag_configure("error", background="#fef2f2", foreground="#991b1b")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Delete>", self.on_delete_key)
        self.tree.bind("<Control-a>", self.on_select_all_shortcut)
        self.tree.bind("<Control-A>", self.on_select_all_shortcut)

        bottom = ttk.Frame(root)
        bottom.pack(fill="x", pady=(8, 0))
        ttk.Label(bottom, textvariable=self.status_var).pack(side="left")
        action_groups = ttk.Frame(bottom)
        action_groups.pack(side="right")

        manage_group = ttk.LabelFrame(action_groups, text="Open / Backup", padding=(8, 6))
        manage_group.pack(side="left")
        ttk.Button(manage_group, text="Backup Selected", command=self.backup_selected).pack(side="left", padx=(0, 6))
        ttk.Button(manage_group, text="Select All Visible", command=self.select_all_visible).pack(side="left", padx=6)
        ttk.Button(manage_group, text="Show Missing Songs", command=self.show_missing_songs).pack(side="left", padx=6)
        ttk.Button(manage_group, text="Open in Editor", command=self.open_in_editor).pack(side="left", padx=(6, 0))

        delete_group = ttk.LabelFrame(action_groups, text="Delete", padding=(8, 6))
        delete_group.pack(side="left", padx=(10, 0))
        ttk.Button(delete_group, text="Delete Broken", command=self.delete_broken).pack(side="left", padx=(0, 6))
        ttk.Button(delete_group, text="Delete Selected", command=self.delete_selected).pack(side="left", padx=(6, 0))

        ttk.Button(action_groups, text="Close", command=self.destroy).pack(side="left", padx=(10, 0))

    def refresh_files(self) -> None:
        if self.loading:
            return
        self.loading = True
        self.status_var.set("Loading headset playlists...")
        self.tree.delete(*self.tree.get_children())

        def worker() -> None:
            try:
                names = list_remote_files(self.adb_path, self.playlist_dir)
                playlist_files = sorted([name for name in names if name.lower().endswith(".playlist")], key=str.lower)
                safe_after(self, lambda: self._finish_refresh(playlist_files, None))
            except Exception as err:  # noqa: BLE001
                safe_after(self, lambda err=err: self._finish_refresh([], err))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_refresh(self, files: list[str], err: Exception | None) -> None:
        if not self.winfo_exists() or not self.tree.winfo_exists():
            return
        self.loading = False
        if err is not None:
            self.status_var.set(f"Load failed: {err}")
            messagebox.showerror("Quest Playlists", str(err), parent=self)
            return
        self.files = files
        self.status_var.set(f"Headset playlists: {len(files)}")
        self.render_files()
        self.compute_playlist_status()

    def selected_files(self) -> list[str]:
        selected: list[str] = []
        for item_id in self.tree.selection():
            idx = force_int(item_id, -1)
            if 0 <= idx < len(self.visible_files):
                selected.append(self.visible_files[idx])
        return selected

    def render_files(self) -> None:
        self.tree.delete(*self.tree.get_children())
        active_filter = self.filter_var.get()
        visible_files: list[str] = []
        for name in self.files:
            status = self.playlist_status.get(name, "Checking...")
            if active_filter == "broken" and status == "OK":
                continue
            tag = "warning"
            if status == "OK":
                tag = "ok"
            elif status.startswith("Missing songs") or status == "Empty":
                tag = "error"
            idx = len(visible_files)
            self.tree.insert("", "end", iid=str(idx), values=(name, status), tags=(tag,))
            visible_files.append(name)
        self.visible_files = visible_files

    def set_filter(self, value: str) -> None:
        self.filter_var.set(value)
        self.render_files()

    def on_select_all_shortcut(self, _event=None):
        self.select_all_visible()
        return "break"

    def select_all_visible(self) -> None:
        all_ids = [str(idx) for idx in range(len(self.visible_files))]
        if not all_ids:
            messagebox.showinfo("Select All Visible", "There are no visible playlists to select.", parent=self)
            return
        self.tree.selection_set(all_ids)
        self.tree.focus(all_ids[0])
        self.status_var.set(f"Selected visible playlists: {len(all_ids)}")

    def compute_playlist_status(self) -> None:
        self.status_var.set("Checking playlist integrity...")

        def worker() -> None:
            try:
                if self.songs_dir:
                    headset_hashes, headset_filenames, headset_identities = build_headset_song_index_fast(
                        self.adb_path,
                        self.songs_dir,
                    )
                else:
                    headset_hashes, headset_filenames, headset_identities = set(), [], {}
                status_map: dict[str, str] = {}
                for name in self.files:
                    remote_path = f"{self.playlist_dir.rstrip('/')}/{name}"
                    try:
                        raw = adb_read_text_file(self.adb_path, remote_path)
                        payload = json.loads(raw)
                    except Exception:
                        status_map[name] = "Unreadable"
                        continue
                    items = payload.get("dataString")
                    if not isinstance(items, list) or not items:
                        status_map[name] = "Empty"
                        continue
                    playlist_hashes = {
                        str(item.get("hash", "")).strip().lower()
                        for item in items
                        if isinstance(item, dict) and str(item.get("hash", "")).strip()
                    }
                    if not playlist_hashes:
                        status_map[name] = "Empty"
                        continue
                    playlist_songs = load_remote_playlist_song_entries(self.adb_path, remote_path)
                    missing = 0
                    for song in playlist_songs:
                        if not looks_like_custom_playlist_song(song):
                            continue
                        if song.hash.lower() in headset_hashes:
                            continue
                        if any(headset_identity_matches_song(identity, song) for identity in headset_identities.values()):
                            continue
                        if any(headset_filename_matches_song(file_name, song) for file_name in headset_filenames):
                            continue
                        missing += 1
                    status_map[name] = "OK" if missing == 0 else f"Missing songs: {missing}"
                safe_after(self, lambda: self.apply_playlist_status(status_map))
            except Exception as err:  # noqa: BLE001
                safe_after(self, lambda err=err: self.status_var.set(f"Integrity check failed: {err}"))

        threading.Thread(target=worker, daemon=True).start()

    def apply_playlist_status(self, status_map: dict[str, str]) -> None:
        if not self.winfo_exists() or not self.tree.winfo_exists():
            return
        self.playlist_status = status_map
        self.render_files()
        bad_count = sum(1 for status in status_map.values() if status != "OK")
        self.status_var.set(f"Headset playlists: {len(self.files)} | Issues: {bad_count}")

    def show_missing_songs(self) -> None:
        selected = self.selected_files()
        if len(selected) != 1:
            messagebox.showerror("Select One Playlist", "Select exactly one playlist first.", parent=self)
            return
        playlist_name = selected[0]
        if not self.playlist_status.get(playlist_name, "").startswith("Missing songs"):
            messagebox.showinfo("Show Missing Songs", "That playlist does not currently report missing songs.", parent=self)
            return
        dialog = MissingPlaylistSongsDialog(
            self,
            self.adb_path,
            self.songs_dir,
            f"{self.playlist_dir.rstrip('/')}/{playlist_name}",
            playlist_name,
        )
        self.wait_window(dialog)
        self.refresh_files()

    def open_in_editor(self) -> None:
        selected = self.selected_files()
        if len(selected) != 1:
            messagebox.showerror("Select One Playlist", "Select exactly one playlist first.", parent=self)
            return
        self.result = selected[0]
        self.destroy()

    def on_delete_key(self, _event=None) -> None:
        self.delete_selected()

    def backup_selected(self) -> None:
        selected = self.selected_files()
        if not selected:
            messagebox.showerror("No Selection", "Select one or more playlists first.", parent=self)
            return
        out_dir = filedialog.askdirectory(title="Select Backup Folder")
        if not out_dir:
            return
        self.status_var.set(f"Backing up {len(selected)} playlists...")

        def worker() -> None:
            failed: list[str] = []
            copied = 0
            base_dir = Path(out_dir)
            for name in selected:
                remote_path = f"{self.playlist_dir.rstrip('/')}/{name}"
                local_path = base_dir / name
                try:
                    adb_pull_file(self.adb_path, remote_path, local_path)
                    copied += 1
                except Exception as err:  # noqa: BLE001
                    failed.append(f"{name}: {err}")
            safe_after(self, lambda: self._finish_backup("playlists", copied, failed))

        threading.Thread(target=worker, daemon=True).start()

    def delete_selected(self) -> None:
        selected = self.selected_files()
        if not selected:
            messagebox.showerror("No Selection", "Select one or more playlists first.", parent=self)
            return
        if not self.confirm_delete("playlists", selected):
            return

        count = len(selected)
        self.status_var.set(f"Deleting {count} playlists...")

        def worker() -> None:
            failed: list[str] = []
            for name in selected:
                remote_path = f"{self.playlist_dir.rstrip('/')}/{name}"
                try:
                    adb_delete_file(self.adb_path, remote_path)
                except Exception as err:  # noqa: BLE001
                    failed.append(f"{name}: {err}")
            safe_after(self, lambda: self._finish_delete(count, failed))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_delete(self, count: int, failed: list[str]) -> None:
        if not self.winfo_exists():
            return
        if failed:
            messagebox.showerror(
                "Delete Failed",
                "\n".join(failed[:10]) + (f"\n...and {len(failed) - 10} more" if len(failed) > 10 else ""),
                parent=self,
            )
        else:
            messagebox.showinfo("Deleted", f"Deleted {count} playlists.", parent=self)
        self.refresh_files()

    def delete_broken(self) -> None:
        selected = [name for name in self.files if self.playlist_status.get(name) != "OK"]
        if not selected:
            messagebox.showinfo("Delete Broken", "No broken playlists were found.", parent=self)
            return
        if not self.confirm_delete("broken playlists", selected):
            return

        count = len(selected)
        self.status_var.set(f"Deleting {count} broken playlists...")

        def worker() -> None:
            failed: list[str] = []
            for name in selected:
                remote_path = f"{self.playlist_dir.rstrip('/')}/{name}"
                try:
                    adb_delete_file(self.adb_path, remote_path)
                except Exception as err:  # noqa: BLE001
                    failed.append(f"{name}: {err}")
            safe_after(self, lambda: self._finish_delete(count, failed))

        threading.Thread(target=worker, daemon=True).start()

    def confirm_delete(self, label: str, names: list[str]) -> bool:
        count = len(names)
        preview = "\n".join(names[:12])
        if len(names) > 12:
            preview += f"\n...and {len(names) - 12} more"
        return messagebox.askyesno(
            f"Delete {label.title()}",
            f"Are you sure you want to delete {count} {label}?\n\n{preview}",
            parent=self,
        )

    def _finish_backup(self, label: str, copied: int, failed: list[str]) -> None:
        if not self.winfo_exists():
            return
        if failed:
            messagebox.showerror(
                "Backup Incomplete",
                f"Copied {copied} {label}.\n\n" + "\n".join(failed[:10]) + (f"\n...and {len(failed) - 10} more" if len(failed) > 10 else ""),
                parent=self,
            )
        else:
            messagebox.showinfo("Backup Complete", f"Copied {copied} {label} to your computer.", parent=self)
        self.status_var.set(f"Headset playlists: {len(self.files)} | Issues: {sum(1 for status in self.playlist_status.values() if status != 'OK')}")


class MissingPlaylistSongsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, adb_path: str, songs_dir: str, playlist_path: str, playlist_name: str):
        super().__init__(parent)
        self.parent_dialog = parent
        self.title(f"Missing Songs - {playlist_name}")
        self.geometry("920x580")
        self.minsize(780, 440)
        self.adb_path = adb_path
        self.songs_dir = songs_dir
        self.playlist_path = playlist_path
        self.playlist_name = playlist_name
        self.status_var = tk.StringVar(value="Checking missing songs...")
        self.songs: list[SongEntry] = []

        self._build_ui()
        self.transient(parent)
        self.grab_set()
        self.refresh_missing_songs()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text=self.playlist_name).pack(side="left")
        ttk.Button(top, text="Refresh", command=self.refresh_missing_songs).pack(side="right")

        table_frame = ttk.Frame(root)
        table_frame.pack(fill="both", expand=True)

        columns = ("name", "author", "beatmapper", "difficulty")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("name", text="Song")
        self.tree.heading("author", text="Artist")
        self.tree.heading("beatmapper", text="Mapper")
        self.tree.heading("difficulty", text="Difficulty")
        self.tree.column("name", width=300, anchor="w")
        self.tree.column("author", width=180, anchor="w")
        self.tree.column("beatmapper", width=180, anchor="w")
        self.tree.column("difficulty", width=90, anchor="w")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        bottom = ttk.Frame(root)
        bottom.pack(fill="x", pady=(8, 0))
        ttk.Label(bottom, textvariable=self.status_var).pack(side="left")
        ttk.Button(bottom, text="Download All Missing Songs", command=self.download_all_to_headset).pack(side="right")
        ttk.Button(bottom, text="Download Selected to Headset", command=self.download_selected_to_headset).pack(side="right")
        ttk.Button(bottom, text="Close", command=self.destroy).pack(side="right", padx=(0, 6))

    def refresh_missing_songs(self) -> None:
        self.status_var.set("Checking missing songs...")
        self.tree.delete(*self.tree.get_children())

        def worker() -> None:
            try:
                headset_hashes, headset_filenames, headset_identities = build_headset_song_index_fast(
                    self.adb_path,
                    self.songs_dir,
                )
                playlist_songs = load_remote_playlist_song_entries(self.adb_path, self.playlist_path)
                missing = [
                    song
                    for song in playlist_songs
                    if looks_like_custom_playlist_song(song)
                    if song.hash.lower() not in headset_hashes
                    and not any(headset_identity_matches_song(identity, song) for identity in headset_identities.values())
                    and not any(headset_filename_matches_song(file_name, song) for file_name in headset_filenames)
                ]
                safe_after(self, lambda: self._finish_refresh(missing, None))
            except Exception as err:  # noqa: BLE001
                safe_after(self, lambda err=err: self._finish_refresh([], err))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_refresh(self, songs: list[SongEntry], err: Exception | None) -> None:
        if not self.winfo_exists() or not self.tree.winfo_exists():
            return
        if err is not None:
            self.status_var.set(f"Load failed: {err}")
            messagebox.showerror("Missing Songs", str(err), parent=self)
            return
        self.songs = songs
        for idx, song in enumerate(songs):
            self.tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(song.name or song.hash[:12], song.author, song.beatmapper, song.difficultyText or song.difficulty),
            )
        self.status_var.set(f"Missing songs: {len(songs)}")

    def selected_songs(self) -> list[SongEntry]:
        selected: list[SongEntry] = []
        for item_id in self.tree.selection():
            idx = force_int(item_id, -1)
            if 0 <= idx < len(self.songs):
                selected.append(self.songs[idx])
        return selected

    def download_selected_to_headset(self) -> None:
        selected = self.selected_songs()
        if not selected:
            messagebox.showerror("No Selection", "Select one or more missing songs first.", parent=self)
            return
        preview = "\n".join((song.name or song.hash[:12]) for song in selected[:12])
        if len(selected) > 12:
            preview += f"\n...and {len(selected) - 12} more"
        if not messagebox.askyesno(
            "Download Missing Songs",
            f"Download {len(selected)} missing songs to the headset?\n\n{preview}",
            parent=self,
        ):
            return

        self.status_var.set(f"Downloading {len(selected)} missing songs...")
        self._start_missing_song_download(selected)

    def download_all_to_headset(self) -> None:
        if not self.songs:
            messagebox.showinfo("Download All Missing Songs", "There are no missing songs to download.", parent=self)
            return
        preview = "\n".join((song.name or song.hash[:12]) for song in self.songs[:12])
        if len(self.songs) > 12:
            preview += f"\n...and {len(self.songs) - 12} more"
        if not messagebox.askyesno(
            "Download All Missing Songs",
            f"Download all {len(self.songs)} missing songs to the headset?\n\n{preview}",
            parent=self,
        ):
            return

        self.status_var.set(f"Downloading all {len(self.songs)} missing songs...")
        self._start_missing_song_download(list(self.songs))

    def _start_missing_song_download(self, songs_to_download: list[SongEntry]) -> None:
        snapshot = list(songs_to_download)

        def worker() -> None:
            failed: list[str] = []
            transferred = 0
            with tempfile.TemporaryDirectory(prefix="sr_playlist_forge_missing_") as temp_dir:
                out_dir = Path(temp_dir)
                for song in snapshot:
                    try:
                        enrich_song_download_metadata_shared(song)
                        if not (song.beatmapId or song.downloadUrl):
                            raise RuntimeError("Song is not mapped to a downloadable Synthriderz custom beatmap.")
                        local_file, _ = download_song_to_dir(song, out_dir)
                        remote_path = f"{self.songs_dir.rstrip('/')}/{local_file.name}"
                        adb_push_file(self.adb_path, local_file, remote_path)
                        HEADSET_SYNTH_METADATA_CACHE.pop(remote_path, None)
                        transferred += 1
                    except Exception as err:  # noqa: BLE001
                        failed.append(f"{song.name or song.hash[:12]}: {err}")
            safe_after(self, lambda: self._finish_download(transferred, failed))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_download(self, transferred: int, failed: list[str]) -> None:
        if not self.winfo_exists():
            return
        if failed:
            messagebox.showerror(
                "Download Incomplete",
                f"Transferred: {transferred}\n\n" + "\n".join(failed[:10]) + (f"\n...and {len(failed) - 10} more" if len(failed) > 10 else ""),
                parent=self,
            )
        else:
            messagebox.showinfo("Download Complete", f"Transferred {transferred} missing songs to the headset.", parent=self)
        if hasattr(self.parent_dialog, "refresh_files"):
            safe_after(self.parent_dialog, lambda: self.parent_dialog.refresh_files())
        self.refresh_missing_songs()


class BeatmapBrowserDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, on_add_songs: Callable[[list[SongEntry]], tuple[int, int]] | None = None):
        super().__init__(parent)
        self.title("List Browser")
        self.geometry("1100x620")
        self.minsize(920, 520)
        self.result: list[SongEntry] = []
        self.on_add_songs = on_add_songs

        self.filter_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Loading beatmaps...")
        self.page_info_var = tk.StringVar(value="Loading full beatmap list...")
        self.selection_var = tk.StringVar(value="Selected: 0")
        self.status_message = "Loading beatmaps..."

        self.total_count = 0
        self.loading = False
        self.sort_column = "uploaded"
        self.sort_desc = True
        self.cache_loaded = False
        self._rows: list[BeatmapListEntry] = []
        self._visible_rows: list[BeatmapListEntry] = []

        self._build_ui()
        self.transient(parent)
        self.grab_set()
        self.load_cached_rows()
        self.sync_latest_rows()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        controls = ttk.Frame(root)
        controls.pack(fill="x", pady=(0, 8))

        ttk.Label(controls, text="Filter").pack(side="left", padx=(0, 6))
        filter_entry = ttk.Entry(controls, textvariable=self.filter_var, width=28)
        filter_entry.pack(side="left", fill="x", expand=True)
        filter_entry.bind("<KeyRelease>", lambda _event: self.refresh_table())

        ttk.Button(controls, text="Refresh New", command=self.sync_latest_rows).pack(side="left", padx=(10, 0))
        ttk.Button(controls, text="Full Refresh", command=self.load_all_rows).pack(side="left", padx=(6, 0))
        ttk.Button(controls, text="Select All", command=self.select_all_visible).pack(side="left", padx=(6, 0))
        ttk.Button(controls, text="Clear Selection", command=self.clear_selection).pack(side="left", padx=(6, 0))

        ttk.Button(controls, text="Open Website", command=self.open_selected_website).pack(side="right", padx=(8, 0))
        ttk.Button(controls, text="Add Selected", command=self.on_add_selected).pack(side="right")

        info = ttk.Frame(root)
        info.pack(fill="x", pady=(0, 8))
        ttk.Label(info, textvariable=self.page_info_var).pack(side="left")
        ttk.Label(info, textvariable=self.status_var).pack(side="left", padx=(14, 0))
        ttk.Label(info, textvariable=self.selection_var).pack(side="right")

        table_frame = ttk.Frame(root)
        table_frame.pack(fill="both", expand=True)

        columns = ("uploaded", "title", "artist", "mapper", "duration", "difficulties", "downloads")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        headings = {
            "uploaded": "Uploaded",
            "title": "Title",
            "artist": "Artist",
            "mapper": "Mapper",
            "duration": "Duration",
            "difficulties": "Difficulties",
            "downloads": "Downloads",
        }
        widths = {
            "uploaded": 135,
            "title": 250,
            "artist": 180,
            "mapper": 160,
            "duration": 80,
            "difficulties": 220,
            "downloads": 90,
        }
        for col in columns:
            self.tree.heading(col, text=headings[col], command=lambda c=col: self.on_column_click(c))
            anchor = "e" if col == "downloads" else "w"
            self.tree.column(col, width=widths[col], anchor=anchor)

        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _event: self.on_add_selected())
        self.tree.bind("<Button-3>", self.on_tree_right_click)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.update_selection_status())
        self.tree.bind("<Control-a>", lambda _event: self.select_all_visible())
        self.tree.bind("<Control-A>", lambda _event: self.select_all_visible())
        self.tree.bind("<Escape>", lambda _event: self.clear_selection())

        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Add to Playlist", command=self.on_add_selected)
        self.context_menu.add_command(label="Search on YouTube", command=self.search_selected_on_youtube)

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(8, 0))
        ttk.Button(footer, text="Close", command=self.destroy).pack(side="right")

    def set_loading_state(self, is_loading: bool, message: str) -> None:
        self.loading = is_loading
        self.set_status_message(message)

    def set_status_message(self, message: str) -> None:
        self.status_message = message
        self.update_selection_status()

    def update_selection_status(self) -> None:
        selected_count = len(self.tree.selection()) if hasattr(self, "tree") else 0
        self.status_var.set(self.status_message)
        self.selection_var.set(f"Selected: {selected_count}")

    def load_cached_rows(self) -> None:
        rows = load_cached_beatmaps()
        self.cache_loaded = bool(rows)
        if not rows:
            self.page_info_var.set("No local cache yet.")
            self.set_status_message("No cached beatmaps found. Loading from Synthriderz...")
            return
        self._rows = rows
        self.total_count = len(rows)
        self.page_info_var.set(f"Cached beatmaps: {self.total_count}")
        self.set_status_message(f"Loaded {self.total_count} cached beatmaps.")
        self.refresh_table()

    def load_all_rows(self) -> None:
        if self.loading:
            return
        self._rows = []
        self._visible_rows = []
        self.tree.delete(*self.tree.get_children())
        self.page_info_var.set("Loading full beatmap list...")
        self.set_loading_state(True, "Loading beatmaps from Synthriderz...")

        def worker() -> None:
            try:
                rows = fetch_all_beatmaps(progress_cb=self._queue_progress_update)
                save_cached_beatmaps(rows)
                self._queue_finish_load(rows, None, "full")
            except Exception as err:  # noqa: BLE001
                self._queue_finish_load([], err, "full")

        threading.Thread(target=worker, daemon=True).start()

    def sync_latest_rows(self) -> None:
        if self.loading:
            return
        self.page_info_var.set("Checking for new beatmaps...")
        self.set_loading_state(True, "Checking Synthriderz for newer beatmaps...")
        known_latest = max(self._rows, key=lambda row: (row.uploaded_sort, force_int(row.beatmap_id, 0)), default=None)

        def worker() -> None:
            try:
                incoming, total_count = fetch_newer_beatmaps(known_latest, progress_cb=self._queue_progress_update)
                merged_rows = merge_beatmap_rows(self._rows, incoming)
                save_cached_beatmaps(merged_rows)
                self._queue_finish_load(merged_rows, None, "sync", len(incoming), total_count)
            except Exception as err:  # noqa: BLE001
                self._queue_finish_load(self._rows, err, "sync")

        threading.Thread(target=worker, daemon=True).start()

    def _queue_progress_update(self, page: int, page_count: int, loaded_count: int) -> None:
        try:
            self.after(0, lambda: self._apply_progress_update(page, page_count, loaded_count))
        except tk.TclError:
            pass

    def _apply_progress_update(self, page: int, page_count: int, loaded_count: int) -> None:
        self.page_info_var.set(f"Loaded page {page} / {page_count}")
        self.set_status_message(f"Loaded {loaded_count} beatmaps so far...")

    def _queue_finish_load(
        self,
        rows: list[BeatmapListEntry],
        err: Exception | None,
        mode: str,
        added_count: int = 0,
        total_count: int | None = None,
    ) -> None:
        try:
            self.after(0, lambda: self._finish_load(rows, err, mode, added_count, total_count))
        except tk.TclError:
            pass

    def _finish_load(
        self,
        rows: list[BeatmapListEntry],
        err: Exception | None,
        mode: str,
        added_count: int = 0,
        total_count: int | None = None,
    ) -> None:
        self.set_loading_state(False, "Ready")
        if err is not None:
            self.set_status_message(f"Load failed: {err}")
            messagebox.showerror("List Browser", str(err), parent=self)
            return

        self._rows = rows
        self.total_count = total_count if total_count is not None and total_count > 0 else len(rows)
        self.cache_loaded = bool(rows)
        self.page_info_var.set(f"Total beatmaps loaded: {len(rows)}")
        if mode == "sync":
            if added_count > 0:
                self.set_status_message(f"Added {added_count} new beatmaps from Synthriderz.")
            else:
                self.set_status_message("No newer beatmaps found.")
        else:
            self.set_status_message(f"Loaded {len(rows)} beatmaps from Synthriderz.")
        self.refresh_table()

    def refresh_table(self) -> None:
        needle = normalize_text(self.filter_var.get())
        rows = []
        self.tree.delete(*self.tree.get_children())

        for row in self._rows:
            haystack = normalize_text(" ".join([row.title, row.artist, row.mapper, row.difficulty_text]))
            if needle and needle not in haystack:
                continue
            rows.append(row)

        self._visible_rows = sorted(rows, key=self.sort_key, reverse=self.sort_desc)

        for visible_index, row in enumerate(self._visible_rows):
            self.tree.insert(
                "",
                "end",
                iid=str(visible_index),
                values=(
                    row.uploaded_text,
                    row.title,
                    row.artist,
                    row.mapper,
                    row.duration_text,
                    row.difficulty_text,
                    row.download_count,
                ),
            )

        shown = len(self._visible_rows)
        self.set_status_message(f"Showing {shown} of {len(self._rows)} beatmaps.")
        if shown:
            first_id = self.tree.get_children()[0]
            self.tree.selection_set(first_id)
            self.tree.focus(first_id)
        else:
            self.update_selection_status()

    def sort_key(self, row: BeatmapListEntry):
        if self.sort_column == "uploaded":
            return row.uploaded_sort
        if self.sort_column == "title":
            return row.title.lower()
        if self.sort_column == "artist":
            return row.artist.lower()
        if self.sort_column == "mapper":
            return row.mapper.lower()
        if self.sort_column == "duration":
            return row.duration_sort
        if self.sort_column == "difficulties":
            return row.difficulty_text.lower()
        if self.sort_column == "downloads":
            return row.download_count
        return row.uploaded_sort

    def on_column_click(self, column: str) -> None:
        if self.sort_column != column:
            self.sort_column = column
            self.sort_desc = column in {"uploaded", "downloads", "duration"}
        else:
            self.sort_desc = not self.sort_desc
        self.refresh_table()

    def selected_row(self) -> BeatmapListEntry | None:
        selection = self.tree.selection()
        if not selection:
            return None
        idx = force_int(selection[0], -1)
        if 0 <= idx < len(self._visible_rows):
            return self._visible_rows[idx]
        return None

    def selected_rows(self) -> list[BeatmapListEntry]:
        rows: list[BeatmapListEntry] = []
        for item_id in self.tree.selection():
            idx = force_int(item_id, -1)
            if 0 <= idx < len(self._visible_rows):
                rows.append(self._visible_rows[idx])
        return rows

    def select_all_visible(self) -> None:
        all_ids = self.tree.get_children()
        if all_ids:
            self.tree.selection_set(all_ids)
            self.tree.focus(all_ids[0])
        self.update_selection_status()

    def clear_selection(self) -> None:
        self.tree.selection_remove(self.tree.selection())
        self.update_selection_status()

    def on_tree_right_click(self, event) -> None:  # type: ignore[no-untyped-def]
        row_id = self.tree.identify_row(event.y)
        if row_id:
            if row_id not in self.tree.selection():
                self.tree.selection_set(row_id)
                self.tree.focus(row_id)
            self.context_menu.tk_popup(event.x_root, event.y_root)
        self.context_menu.grab_release()

    def open_selected_website(self) -> None:
        row = self.selected_row()
        if row is None:
            messagebox.showerror("No Selection", "Select a beatmap first.", parent=self)
            return
        webbrowser.open(f"https://synthriderz.com/beatmaps/{row.beatmap_id}")

    def search_selected_on_youtube(self) -> None:
        row = self.selected_row()
        if row is None:
            messagebox.showerror("No Selection", "Select a beatmap first.", parent=self)
            return
        query = quote_plus(" ".join(part for part in [row.artist, row.title] if part).strip())
        webbrowser.open(f"https://www.youtube.com/results?search_query={query}")

    def on_add_selected(self) -> None:
        rows = self.selected_rows()
        if not rows:
            messagebox.showerror("No Selection", "Select one or more beatmaps first.", parent=self)
            return
        songs = [parse_song_from_record(row.record, row.beatmap_id) for row in rows]
        if self.on_add_songs is not None:
            added, skipped = self.on_add_songs(songs)
            if added == 0:
                self.set_status_message(f"No songs added. Skipped duplicates: {skipped}.")
            elif skipped:
                self.set_status_message(f"Added {added} songs. Skipped duplicates: {skipped}.")
            else:
                self.set_status_message(f"Added {added} songs to the playlist.")
            return
        self.result = songs
        self.destroy()


class VisualBeatmapBrowserDialog(tk.Toplevel):
    COVER_BOX_SIZE = 180

    def __init__(self, parent: tk.Misc, on_add_song: Callable[[SongEntry], bool] | None = None):
        super().__init__(parent)
        self.title("Visual Beatmap Browser")
        self.geometry("1180x760")
        self.minsize(980, 620)
        self.result: list[SongEntry] = []
        self.on_add_song = on_add_song

        self.page_var = tk.StringVar(value="1")
        self.page_info_var = tk.StringVar(value="Loading...")
        self.status_var = tk.StringVar(value="Loading beatmaps...")

        self.page_count = 1
        self.total_count = 0
        self.current_page = 1
        self.loading = False
        self._rows: list[BeatmapListEntry] = []
        self._image_refs: dict[str, Any] = {}

        self._build_ui()
        self.transient(parent)
        self.grab_set()
        self.load_latest_page()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        controls = ttk.Frame(root)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text="Page").pack(side="left")
        page_entry = ttk.Entry(controls, textvariable=self.page_var, width=7)
        page_entry.pack(side="left", padx=(6, 6))
        page_entry.bind("<Return>", lambda _event: self.go_to_page())
        ttk.Button(controls, text="Go", command=self.go_to_page).pack(side="left")
        ttk.Button(controls, text="Previous", command=lambda: self.load_page(self.current_page - 1)).pack(
            side="left", padx=(10, 4)
        )
        ttk.Button(controls, text="Next", command=lambda: self.load_page(self.current_page + 1)).pack(side="left")
        ttk.Button(controls, text="Full Refresh", command=self.load_latest_page).pack(side="left", padx=(10, 0))

        ttk.Label(controls, textvariable=self.page_info_var).pack(side="left", padx=(18, 0))
        ttk.Label(controls, textvariable=self.status_var).pack(side="right")

        content = ttk.Frame(root)
        content.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(content, highlightthickness=0)
        self.vscroll = ttk.Scrollbar(content, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vscroll.set)
        self.vscroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.cards_frame = ttk.Frame(self.canvas)
        self.cards_window = self.canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.cards_frame.bind("<Configure>", self.on_cards_configure)
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self.on_mousewheel)

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(8, 0))
        ttk.Button(footer, text="Close", command=self.destroy).pack(side="right")

    def destroy(self) -> None:
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        super().destroy()

    def on_cards_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def on_canvas_configure(self, event) -> None:  # type: ignore[no-untyped-def]
        self.canvas.itemconfigure(self.cards_window, width=event.width)

    def on_mousewheel(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.winfo_exists():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def set_loading_state(self, is_loading: bool, message: str) -> None:
        self.loading = is_loading
        self.status_var.set(message)

    def load_latest_page(self) -> None:
        self.load_page(999999)

    def go_to_page(self) -> None:
        self.load_page(force_int(self.page_var.get(), self.current_page))

    def load_page(self, page: int) -> None:
        if self.loading:
            return
        page = max(1, page)
        self.page_var.set(str(page))
        self.set_loading_state(True, "Loading visual beatmaps...")
        self.page_info_var.set("Loading page...")

        def worker() -> None:
            try:
                rows, page_count, total_count = fetch_beatmaps_page(page if page < 999999 else 1)
                target_page = min(page, page_count) if page < 999999 else page_count
                need_reload = (page >= 999999) or (target_page != page)
                if need_reload:
                    rows, page_count, total_count = fetch_beatmaps_page(target_page)
                self._queue_finish_load(target_page, rows, page_count, total_count, None)
            except Exception as err:  # noqa: BLE001
                self._queue_finish_load(self.current_page, [], self.page_count, self.total_count, err)

        threading.Thread(target=worker, daemon=True).start()

    def _queue_finish_load(
        self,
        page: int,
        rows: list[BeatmapListEntry],
        page_count: int,
        total_count: int,
        err: Exception | None,
    ) -> None:
        try:
            self.after(0, lambda: self._finish_load(page, rows, page_count, total_count, err))
        except tk.TclError:
            pass

    def _finish_load(
        self,
        page: int,
        rows: list[BeatmapListEntry],
        page_count: int,
        total_count: int,
        err: Exception | None,
    ) -> None:
        self.set_loading_state(False, "Ready")
        if err is not None:
            self.status_var.set(f"Load failed: {err}")
            messagebox.showerror("Visual Beatmap Browser", str(err), parent=self)
            return

        self.current_page = max(1, page)
        self.page_count = max(1, page_count)
        self.total_count = max(0, total_count)
        self.page_var.set(str(self.current_page))
        self.page_info_var.set(f"Page {self.current_page} / {self.page_count} | Beatmaps: {self.total_count}")
        self.status_var.set(f"Loaded {len(rows)} beatmaps for this page.")
        self._rows = sorted(rows, key=lambda row: row.uploaded_sort, reverse=True)
        self.render_cards()

    def render_cards(self) -> None:
        self._image_refs.clear()
        for child in self.cards_frame.winfo_children():
            child.destroy()

        columns = 4
        for idx, row in enumerate(self._rows):
            card = ttk.Frame(self.cards_frame, padding=8, relief="ridge")
            card.grid(row=idx // columns, column=idx % columns, padx=8, pady=8, sticky="nsew")

            art_frame = tk.Frame(card, width=self.COVER_BOX_SIZE, height=self.COVER_BOX_SIZE, bg="#202020")
            art_frame.pack(fill="x")
            art_frame.pack_propagate(False)
            art_label = tk.Label(
                art_frame,
                text="Loading cover..." if HAS_PILLOW else "Cover unavailable",
                bg="#202020",
                fg="#f5f5f5",
                anchor="center",
                justify="center",
                wraplength=self.COVER_BOX_SIZE - 10,
            )
            art_label.pack(fill="both", expand=True)
            if HAS_PILLOW:
                self.load_card_cover(row, art_label)

            title_label = tk.Label(
                card,
                text=row.title or "(Untitled)",
                font=("Segoe UI", 10, "bold"),
                anchor="w",
                justify="left",
                wraplength=190,
                padx=0,
                pady=2,
            )
            title_label.pack(fill="x", anchor="w", pady=(8, 2))
            ttk.Label(card, text=row.artist or "Unknown artist", wraplength=180).pack(anchor="w")
            ttk.Label(card, text=f"Mapper: {row.mapper or 'Unknown'}", wraplength=180).pack(anchor="w", pady=(2, 0))
            ttk.Label(card, text=f"Uploaded: {row.uploaded_text or '-'}", wraplength=180).pack(anchor="w")
            ttk.Label(card, text=f"Duration: {row.duration_text or '-'}").pack(anchor="w")
            ttk.Label(card, text=f"Downloads: {row.download_count}").pack(anchor="w", pady=(0, 6))

            buttons = ttk.Frame(card)
            buttons.pack(fill="x", pady=(4, 0))
            ttk.Button(buttons, text="Add", command=lambda r=row: self.add_single_row(r)).pack(side="left")
            ttk.Button(buttons, text="YouTube", command=lambda r=row: self.search_row_on_youtube(r)).pack(
                side="left", padx=(6, 0)
            )
            ttk.Button(buttons, text="Open", command=lambda r=row: self.open_row_website(r)).pack(side="right")

        for col in range(columns):
            self.cards_frame.columnconfigure(col, weight=1)
        self.canvas.yview_moveto(0.0)
        self.on_cards_configure()

    def load_card_cover(self, row: BeatmapListEntry, label: tk.Label) -> None:
        def worker() -> None:
            image = self.load_cover_photo(row)
            try:
                self.after(0, lambda: self.apply_cover_photo(row.beatmap_id, label, image))
            except tk.TclError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def load_cover_photo(self, row: BeatmapListEntry):
        if not HAS_PILLOW or Image is None or ImageTk is None or ImageOps is None:
            return None
        cache_path = beatmap_cover_cache_path(row.beatmap_id)
        try:
            if cache_path.exists():
                raw = cache_path.read_bytes()
            else:
                beatmap_cover_cache_dir().mkdir(parents=True, exist_ok=True)
                raw = fetch_bytes(cover_url_from_record(row.record, row.beatmap_id))
                cache_path.write_bytes(raw)
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            contained = ImageOps.contain(image, (self.COVER_BOX_SIZE, self.COVER_BOX_SIZE), Image.Resampling.LANCZOS)
            square = Image.new("RGB", (self.COVER_BOX_SIZE, self.COVER_BOX_SIZE), "#202020")
            offset_x = (self.COVER_BOX_SIZE - contained.width) // 2
            offset_y = (self.COVER_BOX_SIZE - contained.height) // 2
            square.paste(contained, (offset_x, offset_y))
            return ImageTk.PhotoImage(square)
        except Exception:
            return None

    def apply_cover_photo(self, beatmap_id: str, label: tk.Label, image) -> None:
        if not label.winfo_exists():
            return
        if image is None:
            label.configure(text="Cover unavailable")
            return
        self._image_refs[beatmap_id] = image
        label.configure(image=image, text="")

    def add_single_row(self, row: BeatmapListEntry) -> None:
        song = parse_song_from_record(row.record, row.beatmap_id)
        if self.on_add_song is not None:
            added = self.on_add_song(song)
            self.status_var.set("Added to playlist." if added else "Song already in playlist.")
            return
        self.result = [song]
        self.destroy()

    def open_row_website(self, row: BeatmapListEntry) -> None:
        webbrowser.open(f"https://synthriderz.com/beatmaps/{row.beatmap_id}")

    def search_row_on_youtube(self, row: BeatmapListEntry) -> None:
        query = quote_plus(" ".join(part for part in [row.artist, row.title] if part).strip())
        webbrowser.open(f"https://www.youtube.com/results?search_query={query}")


class PlaylistEditorApp(BASE_TK_CLASS):
    def __init__(self, instance_guard: SingleInstanceGuard | None = None) -> None:
        super().__init__()
        self.instance_guard = instance_guard
        self.title("SR Playlist Forge v.2.1")
        self.geometry("1220x700")
        self.minsize(1120, 620)

        now_ts = int(time.time())
        self.playlist_vars: dict[str, tk.StringVar] = {
            "namePlaylist": tk.StringVar(value="New Playlist"),
            "playlistNumber": tk.StringVar(value="1"),
            "description": tk.StringVar(value="new playlist"),
            "SelectedIconIndex": tk.StringVar(value="0"),
            "SelectedTexture": tk.StringVar(value="0"),
            "gradientTop": tk.StringVar(value="#DDD8BF"),
            "gradientDown": tk.StringVar(value="#E75193"),
            "colorTitle": tk.StringVar(value="#FFFFFF"),
            "colorTexture": tk.StringVar(value="#0F9E88"),
            "creationDate": tk.StringVar(value=str(now_ts)),
            "creationDateHuman": tk.StringVar(value=timestamp_to_local_text(now_ts)),
        }
        self.generated_filename_var = tk.StringVar(value="")
        self.stats_var = tk.StringVar(value="Songs: 0 | Total Length: 00:00:00")
        self.download_status_var = tk.StringVar(value="Idle")
        self.download_percent_var = tk.StringVar(value="0%")
        self.download_progress_var = tk.DoubleVar(value=0.0)
        self.theme_mode_var = tk.StringVar(value="light")
        self.theme_button_var = tk.StringVar(value="")
        self.quest_song_dir_var = tk.StringVar(value="/sdcard/SynthRidersUC/CustomSongs")
        self.quest_playlist_dir_var = tk.StringVar(value="/sdcard/Android/data/com.kluge.SynthRiders/files/Playlist")
        self.quest_adb_var = tk.StringVar(value="ADB: Searching...")
        self.download_cancel_event = threading.Event()
        self.download_events: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self.download_in_progress = False
        self.download_poll_after_id: str | None = None
        self.download_worker_thread: threading.Thread | None = None
        self.session_save_after_id: str | None = None
        self.quest_status_after_id: str | None = None
        self.restoring_session = False
        self.creation_date_auto_managed = True
        self._suppress_creation_date_manual_detection = False
        self.sort_column: str | None = None
        self.sort_desc: bool = False
        self.current_view_indices: list[int] = []
        self.drag_source_iid: str | None = None
        self.drag_target_iid: str | None = None
        self.drag_blocked_notice_shown = False
        self.songs: list[SongEntry] = []
        self.hash_lookup_cache: dict[str, dict[str, Any] | None] = {}
        self.title_artist_lookup_cache: dict[str, dict[str, Any] | None] = {}
        self._tooltips: list[HoverTooltip] = []
        self.color_preview_canvases: dict[str, tk.Canvas] = {}
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self.playlist_vars["playlistNumber"].trace_add("write", lambda *_: self.update_generated_filename())
        self.playlist_vars["namePlaylist"].trace_add("write", lambda *_: self.update_generated_filename())
        self.playlist_vars["creationDateHuman"].trace_add("write", lambda *_: self.on_creation_date_human_changed())
        for key in ("gradientTop", "gradientDown", "colorTitle", "colorTexture"):
            self.playlist_vars[key].trace_add("write", lambda *_ignored, field=key: self.update_color_preview(field))
        for var in self.playlist_vars.values():
            var.trace_add("write", lambda *_: self.schedule_session_save())
        self.duration_filter_mode = tk.StringVar(value="Any")
        self.duration_filter_value = tk.StringVar(value="")
        self.difficulty_filter_choice = tk.StringVar(value="Any")
        self.update_generated_filename()

        self._build_ui()
        self.apply_theme()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.restore_session()
        self.schedule_quest_status_check(initial=True)

    def report_callback_exception(
        self,
        exc: type[BaseException],
        val: BaseException,
        tb: Any,
    ) -> None:
        log_path = write_exception_log("Tkinter callback exception", (exc, val, tb))
        try:
            messagebox.showerror(
                "SR Playlist Forge Error",
                "An unexpected interface error occurred.\n\n"
                f"Details were written to:\n{log_path}",
                parent=self,
            )
        except Exception:
            show_fatal_error_dialog(
                "SR Playlist Forge Error",
                "An unexpected interface error occurred.\n\n"
                f"Details were written to:\n{log_path}",
            )

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=8)
        root.pack(fill="both", expand=True)

        top_bar = ttk.Frame(root)
        top_bar.pack(fill="x", pady=(0, 8))
        ttk.Label(top_bar, text="SR Playlist Forge v.2.1", style="Title.TLabel").pack(side="left")
        ttk.Label(top_bar, textvariable=self.stats_var).pack(side="left", padx=(12, 0))
        ttk.Checkbutton(
            top_bar,
            textvariable=self.theme_button_var,
            command=self.toggle_theme,
            style="ThemeSwitch.TCheckbutton",
        ).pack(side="right")

        controls = ttk.Notebook(root)
        controls.pack(fill="x", pady=(0, 8))

        meta = ttk.Frame(controls, padding=8)
        add_tab = ttk.Frame(controls, padding=8)
        quest_tab = ttk.Frame(controls, padding=8)
        controls.add(meta, text="Playlist")
        controls.add(add_tab, text="Add Songs")
        controls.add(quest_tab, text="Quest")

        meta.columnconfigure(1, weight=1)
        meta.columnconfigure(3, weight=1)
        fields = [
            ("namePlaylist", "namePlaylist", ""),
            ("description", "description", ""),
            (
                "Playlist Number",
                "playlistNumber",
                "Filename is auto-generated as 000007__namePlaylist.playlist.\n"
                "Enter any number and the app pads it to 6 digits.",
            ),
            (
                "creationDate (local)",
                "creationDateHuman",
                "Shown as readable local date/time.\n"
                "Supported formats: YYYY-MM-DD HH:MM[:SS] or YYYY-MM-DD.",
            ),
            ("SelectedIconIndex", "SelectedIconIndex", ""),
            ("SelectedTexture", "SelectedTexture", ""),
            ("gradientTop", "gradientTop", ""),
            ("gradientDown", "gradientDown", ""),
            ("colorTexture", "colorTexture", ""),
            ("colorTitle", "colorTitle", ""),
        ]
        field_positions = {
            "namePlaylist": (0, 0),
            "description": (1, 0),
            "playlistNumber": (2, 0),
            "creationDateHuman": (3, 0),
            "SelectedIconIndex": (4, 0),
            "SelectedTexture": (0, 2),
            "gradientTop": (1, 2),
            "gradientDown": (2, 2),
            "colorTexture": (3, 2),
            "colorTitle": (4, 2),
        }
        for i, (label, key, tip) in enumerate(fields):
            row, label_col = field_positions.get(key, (i, 0))
            ttk.Label(meta, text=label).grid(row=row, column=label_col, padx=6, pady=4, sticky="e")
            col = label_col + 1
            if key in {"gradientTop", "gradientDown", "colorTitle", "colorTexture"}:
                self._build_color_picker_field(meta, key, row, col)
                continue
            if tip:
                cell = ttk.Frame(meta)
                cell.grid(row=row, column=col, padx=6, pady=4, sticky="we")
                cell.columnconfigure(0, weight=1)
                ttk.Entry(cell, textvariable=self.playlist_vars[key], width=28).grid(row=0, column=0, sticky="we")
                info_label = ttk.Label(cell, text="(i)")
                info_label.grid(row=0, column=1, padx=(6, 0), sticky="w")
                self._tooltips.append(HoverTooltip(info_label, tip))
            else:
                ttk.Entry(meta, textvariable=self.playlist_vars[key], width=36).grid(
                    row=row, column=col, padx=6, pady=4, sticky="we"
                )

        playlist_actions = ttk.Frame(meta)
        playlist_actions.grid(row=5, column=0, columnspan=4, sticky="we", pady=(8, 0))
        ttk.Label(playlist_actions, text="Export filename:").pack(side="left")
        ttk.Label(playlist_actions, textvariable=self.generated_filename_var).pack(side="left", padx=(6, 14))
        ttk.Button(playlist_actions, text="Add .playlist", command=self.add_playlist).pack(side="right", padx=(6, 0))
        ttk.Button(playlist_actions, text="Export .playlist", command=self.export_playlist).pack(side="right")

        add_tab.columnconfigure(1, weight=1)
        self.url_var = tk.StringVar()
        ttk.Label(add_tab, text="Beatmap URL").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(add_tab, textvariable=self.url_var, width=52).grid(row=0, column=1, padx=6, pady=6, sticky="we")
        ttk.Button(add_tab, text="Add from URL", width=14, command=self.add_song_from_url).grid(
            row=0, column=2, padx=6, pady=6
        )
        quick_actions = ttk.Frame(add_tab)
        quick_actions.grid(row=1, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 6))
        ttk.Button(quick_actions, text="Add Empty Song", width=16, command=self.add_empty_song).pack(side="left", padx=(0, 6))
        ttk.Button(quick_actions, text="Add .synth Files", width=16, command=self.add_synth_files_dialog).pack(
            side="left", padx=6
        )
        ttk.Button(quick_actions, text="List Browser", width=16, command=self.open_beatmap_browser).pack(
            side="left", padx=6
        )
        ttk.Button(quick_actions, text="Visual Browser", width=16, command=self.open_visual_browser).pack(
            side="left", padx=6
        )

        drop_hint = "Drop .synth files here"
        if not HAS_DND_SUPPORT:
            drop_hint += " | Install tkinterdnd2 for drag-and-drop support"
        self.drop_zone = tk.Label(
            add_tab,
            text=drop_hint,
            anchor="center",
            relief="groove",
            borderwidth=1,
            padx=8,
            pady=6,
        )
        self.drop_zone.grid(row=2, column=0, columnspan=3, sticky="we", padx=6, pady=(2, 6))
        if HAS_DND_SUPPORT and DND_FILES is not None:
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind("<<Drop>>", self.on_drop_synth_files)

        filter_frame = ttk.LabelFrame(root, text="Temporary Filters")
        filter_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(filter_frame, text="Duration").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Combobox(
            filter_frame,
            textvariable=self.duration_filter_mode,
            values=["Any", "Over", "Under"],
            state="readonly",
            width=8,
        ).grid(row=0, column=1, padx=6, pady=6)
        ttk.Entry(filter_frame, textvariable=self.duration_filter_value, width=10).grid(row=0, column=2, padx=6, pady=6)
        ttk.Label(filter_frame, text="(seconds or MM:SS)").grid(row=0, column=3, padx=6, pady=6, sticky="w")

        ttk.Label(filter_frame, text="Difficulty").grid(row=0, column=4, padx=(18, 6), pady=6, sticky="w")
        ttk.Combobox(
            filter_frame,
            textvariable=self.difficulty_filter_choice,
            values=["Any", "Easy", "Normal", "Hard", "Expert", "Master"],
            state="readonly",
            width=10,
        ).grid(row=0, column=5, padx=6, pady=6)

        ttk.Button(filter_frame, text="Apply", command=self.apply_filters).grid(row=0, column=7, padx=10, pady=6)
        ttk.Button(filter_frame, text="Clear", command=self.clear_filters).grid(row=0, column=8, padx=6, pady=6)
        ttk.Button(filter_frame, text="Refresh Difficulties", command=self.refresh_difficulty_labels).grid(
            row=0, column=9, padx=(12, 6), pady=6
        )

        content = ttk.Panedwindow(root, orient="horizontal")
        content.pack(fill="both", expand=True)

        table_frame = ttk.Frame(content)
        content.add(table_frame, weight=5)

        cols = ["hash", "name", "author", "beatmapper", "difficulty", "trackDuration", "addedTime"]
        self.column_labels = {
            "hash": "hash",
            "name": "name",
            "author": "artist",
            "beatmapper": "mapper",
            "difficulty": "difficulty",
            "trackDuration": "duration",
            "addedTime": "added",
        }
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="extended")
        for c in cols:
            self.tree.heading(c, text=self.column_labels[c], command=lambda col=c: self.on_column_click(col))
            width = 80
            if c == "hash":
                width = 240
            elif c == "difficulty":
                width = 180
            elif c in {"name", "author", "beatmapper"}:
                width = 150
            self.tree.column(c, width=width, anchor="w")

        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.tag_configure("drag_target", background="#e0f2fe")
        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="left", fill="y")
        self.tree.bind("<ButtonPress-1>", self.on_song_tree_press)
        self.tree.bind("<B1-Motion>", self.on_song_tree_motion)
        self.tree.bind("<ButtonRelease-1>", self.on_song_tree_release)

        sidebar = ttk.Frame(content, padding=(10, 0, 0, 0))
        content.add(sidebar, weight=0)

        song_actions = ttk.LabelFrame(sidebar, text="Song Actions", padding=8)
        song_actions.pack(fill="x")
        ttk.Button(song_actions, text="Remove Selected", command=self.remove_selected).pack(fill="x", pady=2)
        ttk.Button(song_actions, text="Clear All Songs", command=self.clear_all_songs).pack(fill="x", pady=2)
        ttk.Button(song_actions, text="Move Up", command=lambda: self.move_selected(-1)).pack(fill="x", pady=(10, 2))
        ttk.Button(song_actions, text="Move Down", command=lambda: self.move_selected(1)).pack(fill="x", pady=2)

        download_actions = ttk.LabelFrame(sidebar, text="Downloads", padding=8)
        download_actions.pack(fill="x", pady=(10, 0))
        ttk.Button(download_actions, text="Download Selected", command=self.download_selected).pack(fill="x", pady=2)
        ttk.Button(download_actions, text="Download All", command=self.download_all).pack(fill="x", pady=2)
        ttk.Button(download_actions, text="Send to Quest", command=self.send_playlist_to_quest).pack(fill="x", pady=(10, 2))

        dl_frame = ttk.Frame(root)
        dl_frame.pack(fill="x", pady=(6, 0))
        ttk.Label(dl_frame, text="Download:").pack(side="left", padx=(6, 6))
        self.download_progress = ttk.Progressbar(
            dl_frame,
            orient="horizontal",
            mode="determinate",
            maximum=100.0,
            variable=self.download_progress_var,
            length=350,
        )
        self.download_progress.pack(side="left", padx=(0, 8))
        ttk.Label(dl_frame, textvariable=self.download_percent_var, width=6).pack(side="left", padx=(0, 8))
        ttk.Label(dl_frame, textvariable=self.download_status_var).pack(side="left")
        self.cancel_download_btn = ttk.Button(
            dl_frame,
            text="Cancel Download",
            command=self.request_cancel_download,
            state="disabled",
        )
        self.cancel_download_btn.pack(side="right", padx=(8, 6))

        quest_frame = ttk.LabelFrame(quest_tab, text="Headset Connection", padding=8)
        quest_frame.pack(fill="x")
        self.quest_status_canvas = tk.Canvas(quest_frame, width=16, height=16, highlightthickness=0)
        self.quest_status_canvas.grid(row=0, column=0, padx=(6, 2), pady=6, sticky="w")
        self.quest_status_indicator = self.quest_status_canvas.create_oval(2, 2, 14, 14, fill="#b91c1c", outline="")
        self.quest_status_var = tk.StringVar(value="Quest: Not detected")
        ttk.Label(quest_frame, textvariable=self.quest_status_var).grid(row=0, column=1, padx=(0, 12), pady=6, sticky="w")
        ttk.Button(quest_frame, text="Refresh Status", command=self.refresh_quest_status).grid(
            row=0, column=4, padx=6, pady=6, sticky="e"
        )
        ttk.Button(quest_frame, text="Manage Headset Songs", command=self.open_quest_song_manager).grid(
            row=0, column=5, padx=(0, 6), pady=6, sticky="e"
        )
        ttk.Button(quest_frame, text="Manage Headset Playlists", command=self.open_quest_playlist_manager).grid(
            row=0, column=6, padx=(0, 6), pady=6, sticky="e"
        )
        ttk.Label(quest_frame, textvariable=self.quest_adb_var).grid(row=0, column=7, padx=(6, 6), pady=6, sticky="e")
        ttk.Label(quest_frame, text="Songs Dir").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(quest_frame, textvariable=self.quest_song_dir_var, width=46).grid(
            row=1, column=1, columnspan=2, padx=6, pady=6, sticky="we"
        )
        ttk.Label(quest_frame, text="Playlist Dir").grid(row=1, column=3, padx=6, pady=6, sticky="e")
        ttk.Entry(quest_frame, textvariable=self.quest_playlist_dir_var, width=46).grid(
            row=1, column=4, columnspan=2, padx=6, pady=6, sticky="we"
        )
        quest_frame.columnconfigure(1, weight=1)
        quest_frame.columnconfigure(2, weight=1)
        quest_frame.columnconfigure(4, weight=1)
        quest_frame.columnconfigure(7, weight=1)

    def _build_color_picker_field(self, parent: ttk.Frame, key: str, row: int, col: int) -> None:
        cell = ttk.Frame(parent)
        cell.grid(row=row, column=col, padx=6, pady=4, sticky="we")
        cell.columnconfigure(0, weight=1)

        entry = ttk.Entry(cell, textvariable=self.playlist_vars[key], width=18, state="readonly")
        entry.grid(row=0, column=0, sticky="we")
        entry.bind("<Button-1>", lambda _event, field=key: self.choose_playlist_color(field))

        preview = tk.Canvas(cell, width=20, height=20, highlightthickness=1, bd=0)
        preview.grid(row=0, column=1, padx=(6, 6))
        preview.bind("<Button-1>", lambda _event, field=key: self.choose_playlist_color(field))
        self.color_preview_canvases[key] = preview

        ttk.Button(cell, text="Choose...", width=10, command=lambda field=key: self.choose_playlist_color(field)).grid(
            row=0, column=2, sticky="w"
        )
        self.update_color_preview(key)

    def choose_playlist_color(self, key: str) -> None:
        current = self.playlist_vars[key].get().strip()
        initial = current if re.fullmatch(r"#[0-9a-fA-F]{6}", current) else None
        _rgb, chosen = colorchooser.askcolor(color=initial, parent=self, title=f"Choose {key}")
        if not chosen:
            return
        self.playlist_vars[key].set(chosen.upper())

    def update_color_preview(self, key: str) -> None:
        canvas = self.color_preview_canvases.get(key)
        if canvas is None or not canvas.winfo_exists():
            return

        value = self.playlist_vars[key].get().strip()
        palette = THEME_PRESETS.get(self.theme_mode_var.get(), THEME_PRESETS["light"])
        is_valid = bool(re.fullmatch(r"#[0-9a-fA-F]{6}", value))
        fill = value if is_valid else palette["surface_alt"]
        outline = palette["border"] if is_valid else palette["warning"]
        canvas.configure(bg=fill, highlightbackground=outline, highlightcolor=outline)

    def selected_index(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def selected_indices(self) -> list[int]:
        selected: list[int] = []
        for item_id in self.tree.selection():
            try:
                selected.append(int(item_id))
            except ValueError:
                continue
        return selected

    def refresh_table(self, keep_index: int | None = None) -> None:
        self.update_column_headers()
        self.current_view_indices = self.get_visible_indices()
        self.tree.delete(*self.tree.get_children())
        for idx in self.current_view_indices:
            song = self.songs[idx]
            self.tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    song.hash,
                    song.name,
                    song.author,
                    song.beatmapper,
                    song.difficultyText or str(song.difficulty),
                    self.format_mmss(song.trackDuration),
                    self.format_added_time(song.addedTime),
                ),
            )
        if keep_index is not None and keep_index in self.current_view_indices:
            self.tree.selection_set(str(keep_index))
            self.tree.focus(str(keep_index))
        self.update_stats()
        self.schedule_session_save()
        self.clear_drag_state()

    def format_hhmmss(self, total_seconds: float) -> str:
        seconds = max(0, int(round(total_seconds)))
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def format_mmss(self, total_seconds: float) -> str:
        seconds = max(0, int(round(total_seconds)))
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:02d}"

    def format_added_time(self, timestamp: int) -> str:
        try:
            return datetime.fromtimestamp(force_int(timestamp, 0)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(timestamp)

    def parse_duration_filter(self, text: str) -> float | None:
        value = text.strip()
        if not value:
            return None
        if ":" in value:
            parts = value.split(":")
            try:
                if len(parts) == 2:
                    return float(int(parts[0]) * 60 + int(parts[1]))
                if len(parts) == 3:
                    return float(int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]))
            except ValueError:
                return None
        try:
            return float(value)
        except ValueError:
            return None

    def get_visible_indices(self) -> list[int]:
        indices = list(range(len(self.songs)))

        duration_mode = self.duration_filter_mode.get()
        duration_value = self.parse_duration_filter(self.duration_filter_value.get())
        if duration_mode in {"Over", "Under"} and duration_value is not None:
            if duration_mode == "Over":
                indices = [i for i in indices if self.songs[i].trackDuration > duration_value]
            else:
                indices = [i for i in indices if self.songs[i].trackDuration < duration_value]

        diff_choice = self.difficulty_filter_choice.get().strip().lower()
        if diff_choice and diff_choice != "any":
            def has_difficulty_label(song: SongEntry) -> bool:
                text = (song.difficultyText or "").lower()
                if text:
                    labels = [p.strip() for p in text.split(",")]
                    return diff_choice in labels
                numeric_map = {0: "easy", 1: "normal", 2: "hard", 3: "expert", 4: "master", 5: "master"}
                return numeric_map.get(song.difficulty, "") == diff_choice

            indices = [i for i in indices if has_difficulty_label(self.songs[i])]

        if self.sort_column:
            def sort_key(i: int):
                s = self.songs[i]
                if self.sort_column == "hash":
                    return s.hash.lower()
                if self.sort_column == "name":
                    return s.name.lower()
                if self.sort_column == "author":
                    return s.author.lower()
                if self.sort_column == "beatmapper":
                    return s.beatmapper.lower()
                if self.sort_column == "difficulty":
                    return s.difficulty
                if self.sort_column == "trackDuration":
                    return s.trackDuration
                if self.sort_column == "addedTime":
                    return s.addedTime
                return i

            indices = sorted(indices, key=sort_key, reverse=self.sort_desc)

        return indices

    def update_column_headers(self) -> None:
        for col, label in self.column_labels.items():
            suffix = ""
            if col == self.sort_column:
                suffix = " ▼" if self.sort_desc else " ▲"
            self.tree.heading(col, text=f"{label}{suffix}", command=lambda c=col: self.on_column_click(c))

    def on_column_click(self, column: str) -> None:
        if self.sort_column != column:
            self.sort_column = column
            self.sort_desc = False
        elif not self.sort_desc:
            self.sort_desc = True
        else:
            self.sort_column = None
            self.sort_desc = False
        self.refresh_table()

    def apply_filters(self) -> None:
        self.refresh_table()

    def clear_filters(self) -> None:
        self.duration_filter_mode.set("Any")
        self.duration_filter_value.set("")
        self.difficulty_filter_choice.set("Any")
        self.refresh_table()

    def can_drag_reorder(self) -> bool:
        if self.sort_column is not None:
            return False
        if self.duration_filter_mode.get() != "Any":
            return False
        if self.duration_filter_value.get().strip():
            return False
        if self.difficulty_filter_choice.get().strip().lower() != "any":
            return False
        return True

    def clear_drag_state(self) -> None:
        self.drag_source_iid = None
        self.drag_target_iid = None
        for item_id in self.tree.get_children():
            self.tree.item(item_id, tags=())

    def on_song_tree_press(self, event) -> None:  # type: ignore[no-untyped-def]
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            self.clear_drag_state()
            return
        if not self.can_drag_reorder():
            if not self.drag_blocked_notice_shown:
                self.drag_blocked_notice_shown = True
                messagebox.showinfo(
                    "Drag Reorder Disabled",
                    "Clear sorting and filters before dragging songs with the mouse.",
                )
            self.clear_drag_state()
            return
        self.drag_blocked_notice_shown = False
        self.drag_source_iid = row_id
        self.drag_target_iid = row_id

    def on_song_tree_motion(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.drag_source_iid is None:
            return
        row_id = self.tree.identify_row(event.y)
        self.drag_target_iid = row_id if row_id else None
        for item_id in self.tree.get_children():
            self.tree.item(item_id, tags=("drag_target",) if item_id == self.drag_target_iid else ())

    def on_song_tree_release(self, _event=None) -> None:
        if self.drag_source_iid is None or self.drag_target_iid is None:
            self.clear_drag_state()
            return
        if self.drag_source_iid == self.drag_target_iid:
            self.clear_drag_state()
            return

        try:
            source_idx = int(self.drag_source_iid)
            target_idx = int(self.drag_target_iid)
        except ValueError:
            self.clear_drag_state()
            return

        song = self.songs.pop(source_idx)
        if source_idx < target_idx:
            target_idx -= 1
        self.songs.insert(target_idx, song)
        self.refresh_table(keep_index=target_idx)

    def refresh_difficulty_labels(self) -> None:
        if not self.songs:
            return
        updated = 0
        checked = 0
        for song in self.songs:
            # Skip when we already have multiple labels.
            if "," in (song.difficultyText or ""):
                continue
            checked += 1
            rec = self.find_beatmap_record_by_hash(song.hash)
            if not rec:
                rec = self.find_beatmap_record_by_title_artist(song.name, song.author)
            if not rec:
                continue
            new_text = infer_difficulty_text_from_record(rec, song.difficulty)
            if new_text and new_text != (song.difficultyText or str(song.difficulty)):
                song.difficultyText = new_text
                updated += 1
        self.refresh_table()
        messagebox.showinfo("Difficulty Refresh", f"Updated {updated} songs (checked {checked}).")

    def update_stats(self) -> None:
        total_seconds = sum(force_float(song.trackDuration, 0.0) for song in self.songs)
        self.stats_var.set(f"Songs: {len(self.songs)} | Total Length: {self.format_hhmmss(total_seconds)}")

    def toggle_theme(self) -> None:
        new_mode = "dark" if self.theme_mode_var.get() == "light" else "light"
        self.theme_mode_var.set(new_mode)
        self.apply_theme()
        self.schedule_session_save()

    def apply_theme(self) -> None:
        mode = self.theme_mode_var.get()
        palette = THEME_PRESETS.get(mode, THEME_PRESETS["light"])
        icon = "\u263d" if mode == "dark" else "\u2600"
        label = "Dark" if mode == "dark" else "Light"
        self.theme_button_var.set(f"{icon} {label}")
        # Keep theming in ttk styles instead of Tk's root palette. On some Windows/Tk
        # setups, palette updates can mis-parse font names like "Segoe UI" during startup.

        self.style.configure(".", background=palette["bg"], foreground=palette["fg"], fieldbackground=palette["input_bg"])
        self.style.configure("TFrame", background=palette["bg"])
        self.style.configure("TPanedwindow", background=palette["bg"])
        self.style.configure("TNotebook", background=palette["bg"], borderwidth=0)
        self.style.configure(
            "TNotebook.Tab",
            background=palette["surface_alt"],
            foreground=palette["fg"],
            bordercolor=palette["border"],
            padding=(12, 6),
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", palette["surface"]), ("active", palette["surface"])],
            foreground=[("selected", palette["fg"]), ("active", palette["fg"])],
        )
        self.style.configure("TLabelframe", background=palette["bg"], bordercolor=palette["border"])
        self.style.configure("TLabelframe.Label", background=palette["bg"], foreground=palette["fg"])
        self.style.configure("TLabel", background=palette["bg"], foreground=palette["fg"])
        self.style.configure("Title.TLabel", background=palette["bg"], foreground=palette["fg"], font=("Segoe UI Semibold", 13))
        self.style.configure(
            "TButton",
            background=palette["surface_alt"],
            foreground=palette["fg"],
            bordercolor=palette["border"],
            focusthickness=1,
            focuscolor=palette["accent"],
        )
        self.style.map(
            "TButton",
            background=[("active", palette["accent"]), ("pressed", palette["accent"])],
            foreground=[("active", palette["accent_text"]), ("pressed", palette["accent_text"])],
        )
        self.style.configure(
            "ThemeSwitch.TCheckbutton",
            background=palette["surface_alt"],
            foreground=palette["fg"],
            indicatorcolor=palette["surface_alt"],
            indicatormargin=0,
            indicatordiameter=0,
            padding=(12, 6),
            bordercolor=palette["border"],
            relief="solid",
        )
        self.style.map(
            "ThemeSwitch.TCheckbutton",
            background=[("active", palette["accent"]), ("selected", palette["accent"])],
            foreground=[("active", palette["accent_text"]), ("selected", palette["accent_text"])],
        )
        self.style.configure(
            "TEntry",
            fieldbackground=palette["input_bg"],
            foreground=palette["input_fg"],
            insertcolor=palette["input_fg"],
            bordercolor=palette["border"],
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=palette["input_bg"],
            foreground=palette["input_fg"],
            arrowcolor=palette["fg"],
            bordercolor=palette["border"],
        )
        self.style.map(
            "Treeview",
            background=[("selected", palette["select_bg"])],
            foreground=[("selected", palette["select_fg"])],
        )
        self.style.configure(
            "Treeview",
            background=palette["surface"],
            fieldbackground=palette["surface"],
            foreground=palette["fg"],
            bordercolor=palette["border"],
            rowheight=24,
        )
        self.style.configure("Treeview.Heading", background=palette["surface_alt"], foreground=palette["fg"], bordercolor=palette["border"])
        self.style.configure("TScrollbar", background=palette["surface_alt"], troughcolor=palette["bg"], bordercolor=palette["border"])
        self.style.configure(
            "Horizontal.TProgressbar",
            background=palette["accent"],
            troughcolor=palette["surface_alt"],
            bordercolor=palette["border"],
        )
        for key in self.color_preview_canvases:
            self.update_color_preview(key)

    def update_generated_filename(self) -> None:
        try:
            name = build_playlist_filename(
                self.playlist_vars["playlistNumber"].get(),
                self.playlist_vars["namePlaylist"].get(),
            )
            self.generated_filename_var.set(name)
        except Exception:
            self.generated_filename_var.set("Invalid playlist number or name")

    def set_creation_date_timestamp(self, ts: int, *, auto_managed: bool) -> None:
        self._suppress_creation_date_manual_detection = True
        try:
            self.playlist_vars["creationDate"].set(str(ts))
            self.playlist_vars["creationDateHuman"].set(timestamp_to_local_text(ts))
        finally:
            self._suppress_creation_date_manual_detection = False
        self.creation_date_auto_managed = auto_managed

    def refresh_creation_date_if_auto(self) -> None:
        if self.creation_date_auto_managed:
            self.set_creation_date_timestamp(int(time.time()), auto_managed=True)

    def on_creation_date_human_changed(self) -> None:
        if self._suppress_creation_date_manual_detection or self.restoring_session:
            return
        self.creation_date_auto_managed = False

    def build_playlist_export_payload(self) -> tuple[dict[str, Any], str]:
        self.refresh_creation_date_if_auto()
        creation_ts = local_text_to_timestamp(self.playlist_vars["creationDateHuman"].get())
        self.playlist_vars["creationDate"].set(str(creation_ts))
        export_indices = self.get_visible_indices()
        payload = {
            "dataString": [self.songs[i].to_playlist_dict() for i in export_indices],
            "SelectedIconIndex": force_int(self.playlist_vars["SelectedIconIndex"].get(), 0),
            "SelectedTexture": force_int(self.playlist_vars["SelectedTexture"].get(), 0),
            "namePlaylist": self.playlist_vars["namePlaylist"].get(),
            "description": self.playlist_vars["description"].get(),
            "gradientTop": self.playlist_vars["gradientTop"].get(),
            "gradientDown": self.playlist_vars["gradientDown"].get(),
            "colorTitle": self.playlist_vars["colorTitle"].get(),
            "colorTexture": self.playlist_vars["colorTexture"].get(),
            "creationDate": str(creation_ts),
        }
        return payload, build_playlist_filename(
            self.playlist_vars["playlistNumber"].get(),
            self.playlist_vars["namePlaylist"].get(),
        )

    def set_download_progress(
        self,
        percent: float | None,
        status_text: str,
        indeterminate: bool = False,
    ) -> None:
        if indeterminate:
            self.download_progress.configure(mode="indeterminate")
            self.download_progress.start(10)
            self.download_percent_var.set("--")
        else:
            self.download_progress.stop()
            self.download_progress.configure(mode="determinate")
            value = max(0.0, min(100.0, percent if percent is not None else 0.0))
            self.download_progress_var.set(value)
            self.download_percent_var.set(f"{int(round(value))}%")
        self.download_status_var.set(status_text)
        self.update_idletasks()

    def estimate_download_percent(self, downloaded: int, total: int | None) -> float:
        if total and total > 0:
            return max(0.0, min(100.0, (downloaded / total) * 100.0))
        # Fallback estimate when Content-Length is missing: assumes ~12MB typical map size.
        return max(1.0, min(99.0, (downloaded / (12 * 1024 * 1024)) * 100.0))

    def reset_download_progress(self, status_text: str = "Idle") -> None:
        self.download_progress.stop()
        self.download_progress.configure(mode="determinate")
        self.download_progress_var.set(0.0)
        self.download_percent_var.set("0%")
        self.download_status_var.set(status_text)
        self.update_idletasks()

    def begin_download_session(self, initial_status: str) -> None:
        self.download_cancel_event.clear()
        self.download_in_progress = True
        self.cancel_download_btn.configure(state="normal")
        self.set_download_progress(0.0, initial_status)

    def end_download_session(self, final_status: str = "Idle") -> None:
        self.download_in_progress = False
        self.cancel_download_btn.configure(state="disabled")
        self.download_cancel_event.clear()
        if self.download_poll_after_id:
            try:
                self.after_cancel(self.download_poll_after_id)
            except Exception:  # noqa: BLE001
                pass
            self.download_poll_after_id = None
        self.reset_download_progress(final_status)

    def request_cancel_download(self) -> None:
        self.download_cancel_event.set()
        self.download_status_var.set("Cancelling...")
        self.update_idletasks()

    def schedule_quest_status_check(self, initial: bool = False) -> None:
        delay = 500 if initial else 15000
        if self.quest_status_after_id:
            try:
                self.after_cancel(self.quest_status_after_id)
            except Exception:  # noqa: BLE001
                pass
        self.quest_status_after_id = self.after(delay, self.refresh_quest_status)

    def refresh_quest_status(self) -> None:
        adb_path = find_adb_executable()

        def worker() -> None:
            if not adb_path:
                self.after(0, lambda: self.apply_quest_status(False, "Quest: adb not found", "ADB: Not found"))
                return
            try:
                devices = list_adb_devices(adb_path)
                connected = bool(devices)
                text = "Quest: Connected" if connected else "Quest: Not detected"
                adb_text = f"ADB: {adb_path}"
                self.after(0, lambda: self.apply_quest_status(connected, text, adb_text))
            except Exception:
                self.after(0, lambda: self.apply_quest_status(False, "Quest: adb unavailable", f"ADB: {adb_path}"))

        threading.Thread(target=worker, daemon=True).start()

    def apply_quest_status(self, connected: bool, text: str, adb_text: str) -> None:
        self.quest_status_var.set(text)
        self.quest_adb_var.set(adb_text)
        color = "#15803d" if connected else "#b91c1c"
        self.quest_status_canvas.itemconfigure(self.quest_status_indicator, fill=color)
        self.schedule_quest_status_check()

    def open_quest_song_manager(self) -> None:
        adb_path = find_adb_executable()
        if not adb_path:
            messagebox.showerror("ADB Not Found", "adb was not found. Bundle or install adb first.")
            return
        try:
            devices = list_adb_devices(adb_path)
        except Exception as err:  # noqa: BLE001
            messagebox.showerror("Quest Not Available", str(err))
            return
        if not devices:
            messagebox.showerror("Quest Not Detected", "Connect the headset and allow USB debugging first.")
            return
        dialog = QuestSongManagerDialog(
            self,
            adb_path,
            self.quest_song_dir_var.get().strip(),
            self.quest_playlist_dir_var.get().strip(),
        )
        self.wait_window(dialog)

    def open_quest_playlist_manager(self) -> None:
        adb_path = find_adb_executable()
        if not adb_path:
            messagebox.showerror("ADB Not Found", "adb was not found. Bundle or install adb first.")
            return
        try:
            devices = list_adb_devices(adb_path)
        except Exception as err:  # noqa: BLE001
            messagebox.showerror("Quest Not Available", str(err))
            return
        if not devices:
            messagebox.showerror("Quest Not Detected", "Connect the headset and allow USB debugging first.")
            return
        dialog = QuestPlaylistManagerDialog(self, adb_path, self.quest_playlist_dir_var.get().strip())
        self.wait_window(dialog)
        if dialog.result:
            self.open_headset_playlist_in_editor(adb_path, dialog.result)

    def open_headset_playlist_in_editor(self, adb_path: str, playlist_name: str) -> None:
        remote_path = f"{self.quest_playlist_dir_var.get().strip().rstrip('/')}/{playlist_name}"
        try:
            raw_text = adb_read_text_file(adb_path, remote_path)
            payload = json.loads(raw_text)
        except Exception as err:  # noqa: BLE001
            messagebox.showerror("Open Headset Playlist Failed", str(err))
            return
        if self.songs and not messagebox.askyesno(
            "Replace Current Playlist",
            f"Open headset playlist '{playlist_name}' and replace the current editor contents?",
        ):
            return
        self.load_playlist_payload_into_editor(payload, playlist_name)

    def is_download_cancelled(self) -> bool:
        return self.download_cancel_event.is_set()

    def _queue_download_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.download_events.put((event_type, payload))

    def show_text_report_dialog(self, title: str, report_text: str, default_filename: str = "download_report.txt") -> None:
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry("900x620")
        dialog.minsize(700, 420)
        dialog.transient(self)

        frame = ttk.Frame(dialog, padding=10)
        frame.pack(fill="both", expand=True)

        text = scrolledtext.ScrolledText(frame, wrap="word")
        text.pack(fill="both", expand=True)
        text.insert("1.0", report_text)
        text.focus_set()

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(8, 0))

        def copy_all() -> None:
            dialog.clipboard_clear()
            dialog.clipboard_append(text.get("1.0", "end-1c"))

        def save_as_txt() -> None:
            out_path = filedialog.asksaveasfilename(
                parent=dialog,
                title="Save Report As",
                defaultextension=".txt",
                initialfile=default_filename,
                filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
            )
            if not out_path:
                return
            Path(out_path).write_text(text.get("1.0", "end-1c"), encoding="utf-8")

        ttk.Button(btns, text="Copy All", command=copy_all).pack(side="left")
        ttk.Button(btns, text="Save as .txt", command=save_as_txt).pack(side="left", padx=6)
        ttk.Button(btns, text="Close", command=dialog.destroy).pack(side="right")

        dialog.grab_set()

    def _poll_download_events(self) -> None:
        while True:
            try:
                event_type, payload = self.download_events.get_nowait()
            except queue.Empty:
                break

            if event_type == "progress":
                self.set_download_progress(
                    payload.get("percent"),
                    payload.get("status", ""),
                    payload.get("indeterminate", False),
                )
            elif event_type == "single_done":
                self.set_download_progress(100.0, f"Completed: {Path(payload['out_path']).name}")
                messagebox.showinfo("Downloaded", f"Saved:\n{payload['out_path']}\n\nFrom:\n{payload['used_url']}")
            elif event_type == "batch_done":
                lines = payload["lines"]
                report_text = "\n".join(lines)
                if payload.get("failed"):
                    self.show_text_report_dialog("Download Complete (with errors)", report_text, "download_report_errors.txt")
                elif payload.get("cancelled"):
                    self.show_text_report_dialog("Download Cancelled", report_text, "download_report_cancelled.txt")
                else:
                    self.show_text_report_dialog("Download Complete", report_text, "download_report.txt")
            elif event_type == "cancelled":
                messagebox.showinfo("Download Cancelled", "The download was cancelled.")
            elif event_type == "error":
                messagebox.showerror(payload.get("title", "Error"), payload.get("message", "Unknown error"))
            elif event_type == "session_end":
                self.end_download_session("Idle")

        if self.download_in_progress:
            self.download_poll_after_id = self.after(80, self._poll_download_events)

    def _start_download_worker(self, target: Callable[..., None], args: tuple[Any, ...], initial_status: str) -> None:
        if self.download_in_progress:
            messagebox.showerror("Download Running", "A download is already in progress.")
            return
        self.begin_download_session(initial_status)
        self.download_worker_thread = threading.Thread(target=target, args=args, daemon=True)
        self.download_worker_thread.start()
        self._poll_download_events()

    def hash_exists(self, song_hash: str, ignore_index: int | None = None) -> bool:
        for idx, song in enumerate(self.songs):
            if ignore_index is not None and idx == ignore_index:
                continue
            if song.hash == song_hash:
                return True
        return False

    def add_song_from_url(self) -> None:
        url_text = self.url_var.get().strip()
        if not url_text:
            messagebox.showerror("Missing URL", "Enter a Synthriderz beatmap URL first.")
            return
        try:
            song = fetch_song_from_url(url_text)
        except Exception as err:  # noqa: BLE001
            messagebox.showerror("Import Failed", str(err))
            return

        if self.hash_exists(song.hash):
            messagebox.showerror("Duplicate Hash", "This song hash is already in the playlist.")
            return

        self.songs.append(song)
        self.refresh_table(keep_index=len(self.songs) - 1)
        self.url_var.set("")

    def open_beatmap_browser(self) -> None:
        dialog = BeatmapBrowserDialog(self, on_add_songs=self.add_songs_from_list_browser)
        self.wait_window(dialog)
        if dialog.result is None:
            return

        if not dialog.result:
            return
        self.add_songs_from_list_browser(dialog.result)

    def add_songs_from_list_browser(self, songs: list[SongEntry]) -> tuple[int, int]:
        added = 0
        skipped = 0
        keep_index: int | None = None
        for song in songs:
            if self.hash_exists(song.hash):
                skipped += 1
                continue
            self.songs.append(song)
            keep_index = len(self.songs) - 1
            added += 1

        if added > 0:
            self.refresh_table(keep_index=keep_index)
        return added, skipped

    def add_song_from_visual_browser(self, song: SongEntry) -> bool:
        if self.hash_exists(song.hash):
            messagebox.showinfo("Visual Browser", "That song is already in the playlist.")
            return False
        self.songs.append(song)
        self.refresh_table(keep_index=len(self.songs) - 1)
        return True

    def open_visual_browser(self) -> None:
        dialog = VisualBeatmapBrowserDialog(self, on_add_song=self.add_song_from_visual_browser)
        self.wait_window(dialog)
        if not dialog.result:
            return
        self.add_song_from_visual_browser(dialog.result[0])

    def extract_beatmap_id_from_synth_filename(self, file_path: str) -> str | None:
        cleaned = file_path.strip().strip("{}").strip('"').strip("'")
        name = Path(cleaned).name
        if not name.lower().endswith(".synth"):
            return None
        match = re.match(r"^(\d+)", name)
        if not match:
            return None
        return match.group(1)

    def add_songs_from_synth_paths(self, paths: list[str]) -> None:
        if not paths:
            return

        added = 0
        skipped = 0
        failed: list[str] = []
        for raw_path in paths:
            path = raw_path.strip().strip("{}").strip('"').strip("'")
            beatmap_id = self.extract_beatmap_id_from_synth_filename(path)
            if not beatmap_id:
                skipped += 1
                continue
            url_text = f"https://synthriderz.com/beatmaps/{beatmap_id}"
            try:
                song = fetch_song_from_url(url_text)
            except Exception as err:  # noqa: BLE001
                failed.append(f"{Path(path).name}: {err}")
                continue

            if self.hash_exists(song.hash):
                skipped += 1
                continue
            self.songs.append(song)
            added += 1

        self.refresh_table(keep_index=len(self.songs) - 1 if self.songs else None)
        if failed:
            self.show_text_report_dialog(
                "Add .synth Files (with errors)",
                f"Added: {added}\nSkipped: {skipped}\nFailed: {len(failed)}\n\n" + "\n".join(failed),
                default_filename="synth_import_errors.txt",
            )
        else:
            messagebox.showinfo("Add .synth Files", f"Added {added}, skipped {skipped}.")

    def add_synth_files_dialog(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Add .synth Files",
            filetypes=[("Synth Files", "*.synth"), ("All Files", "*.*")],
        )
        if not paths:
            return
        self.add_songs_from_synth_paths(list(paths))

    def on_drop_synth_files(self, event) -> None:  # type: ignore[no-untyped-def]
        try:
            dropped = list(self.tk.splitlist(event.data))
        except Exception:  # noqa: BLE001
            dropped = str(event.data).split()
        self.add_songs_from_synth_paths(dropped)

    def add_empty_song(self) -> None:
        song = SongEntry(hash="", addedTime=int(time.time()))
        dialog = SongEditDialog(self, song)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        if self.hash_exists(dialog.result.hash):
            messagebox.showerror("Duplicate Hash", "This song hash is already in the playlist.")
            return
        self.songs.append(dialog.result)
        self.refresh_table(keep_index=len(self.songs) - 1)

    def edit_selected(self) -> None:
        idx = self.selected_index()
        if idx is None:
            messagebox.showerror("No Selection", "Select a song to edit.")
            return
        dialog = SongEditDialog(self, self.songs[idx])
        self.wait_window(dialog)
        if dialog.result is None:
            return
        if self.hash_exists(dialog.result.hash, ignore_index=idx):
            messagebox.showerror("Duplicate Hash", "This song hash is already in the playlist.")
            return
        self.songs[idx] = dialog.result
        self.refresh_table(keep_index=idx)

    def remove_selected(self) -> None:
        indices = self.selected_indices()
        if not indices:
            return
        for idx in sorted(indices, reverse=True):
            if 0 <= idx < len(self.songs):
                del self.songs[idx]
        anchor_idx = min(indices)
        keep_idx = min(anchor_idx, len(self.songs) - 1) if self.songs else None
        self.refresh_table(keep_index=keep_idx)

    def clear_all_songs(self) -> None:
        if not self.songs:
            return
        if not messagebox.askyesno("Clear All Songs", "Remove all songs from the current playlist?"):
            return
        self.songs.clear()
        self.refresh_table(keep_index=None)

    def move_selected(self, delta: int) -> None:
        indices = self.selected_indices()
        if not indices:
            return
        if len(indices) != 1:
            messagebox.showinfo("Move Songs", "Select exactly one song to move up or down.")
            return
        idx = indices[0]
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(self.songs):
            return
        self.songs[idx], self.songs[new_idx] = self.songs[new_idx], self.songs[idx]
        self.refresh_table(keep_index=new_idx)

    def add_playlist(self) -> None:
        path = filedialog.askopenfilename(
            title="Add Playlist",
            filetypes=[("Synth Riders Playlist", "*.playlist"), ("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as err:  # noqa: BLE001
            messagebox.showerror("Load Failed", str(err))
            return

        self.merge_playlist_payload(raw, path)

    def load_playlist_payload_into_editor(self, raw: dict[str, Any], source_name: str) -> None:
        meta_keys = [
            "namePlaylist",
            "description",
            "SelectedIconIndex",
            "SelectedTexture",
            "gradientTop",
            "gradientDown",
            "colorTitle",
            "colorTexture",
            "creationDate",
        ]
        for key in meta_keys:
            if key in raw:
                self.playlist_vars[key].set(str(raw[key]))

        imported_ts = force_int(raw.get("creationDate"), int(time.time()))
        self.set_creation_date_timestamp(imported_ts, auto_managed=False)

        stem = Path(source_name).stem
        m = re.match(r"^(\d{1,6})__", stem)
        if m:
            self.playlist_vars["playlistNumber"].set(str(int(m.group(1))))

        self.songs = []
        for item in raw.get("dataString", []):
            if not isinstance(item, dict):
                continue
            song = SongEntry(
                hash=str(item.get("hash", "")),
                name=str(item.get("name", "")),
                author=str(item.get("author", "")),
                beatmapper=str(item.get("beatmapper", "")),
                difficulty=force_int(item.get("difficulty"), 0),
                difficultyText=str(item.get("difficultyText", item.get("difficulty", ""))),
                trackDuration=force_float(item.get("trackDuration"), 0.0),
                addedTime=force_int(item.get("addedTime"), int(time.time())),
                beatmapId=str(item.get("beatmapId", "")),
                sourceUrl=str(item.get("sourceUrl", "")),
                downloadUrl=str(item.get("downloadUrl", "")),
            )
            if song.hash:
                self.songs.append(song)

        self.update_generated_filename()
        self.refresh_table(keep_index=0 if self.songs else None)
        messagebox.showinfo("Playlist Opened", f"Opened playlist:\n{source_name}")

    def merge_playlist_payload(self, raw: dict[str, Any], source_name: str) -> None:

        # If this is the first import into an empty playlist, use imported playlist metadata.
        if not self.songs:
            meta_keys = [
                "namePlaylist",
                "description",
                "SelectedIconIndex",
                "SelectedTexture",
                "gradientTop",
                "gradientDown",
                "colorTitle",
                "colorTexture",
                "creationDate",
            ]
            for key in meta_keys:
                if key in raw:
                    self.playlist_vars[key].set(str(raw[key]))

            imported_ts = force_int(raw.get("creationDate"), int(time.time()))
            self.set_creation_date_timestamp(imported_ts, auto_managed=False)

            # Infer playlist number from filename prefix like 000007__halloween.playlist
            stem = Path(path).stem
            m = re.match(r"^(\d{1,6})__", stem)
            if m:
                self.playlist_vars["playlistNumber"].set(str(int(m.group(1))))

        added = 0
        skipped = 0
        for item in raw.get("dataString", []):
            song = SongEntry(
                hash=str(item.get("hash", "")),
                name=str(item.get("name", "")),
                author=str(item.get("author", "")),
                beatmapper=str(item.get("beatmapper", "")),
                difficulty=force_int(item.get("difficulty"), 0),
                difficultyText=str(item.get("difficultyText", item.get("difficulty", ""))),
                trackDuration=force_float(item.get("trackDuration"), 0.0),
                addedTime=force_int(item.get("addedTime"), int(time.time())),
                beatmapId=str(item.get("beatmapId", "")),
                sourceUrl=str(item.get("sourceUrl", "")),
                downloadUrl=str(item.get("downloadUrl", "")),
            )
            if song.hash and not self.hash_exists(song.hash):
                self.songs.append(song)
                added += 1
            else:
                skipped += 1
        self.refresh_table(keep_index=len(self.songs) - 1 if self.songs else None)
        messagebox.showinfo("Playlist Added", f"Added {added} songs, skipped {skipped} duplicates/invalid entries.")

    def export_playlist(self) -> None:
        try:
            payload, default_name = self.build_playlist_export_payload()
            path = filedialog.asksaveasfilename(
                title="Export Playlist",
                defaultextension=".playlist",
                initialfile=default_name,
                filetypes=[("Synth Riders Playlist", "*.playlist")],
            )
            if not path:
                return
            path = normalize_playlist_path(path)
            if Path(path).exists():
                if not messagebox.askyesno("File Exists", f"Overwrite existing file?\n{path}"):
                    return
            Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as err:  # noqa: BLE001
            messagebox.showerror("Export Failed", str(err))
            return
        messagebox.showinfo("Exported", f"Saved:\n{path}")

    def find_beatmap_record_by_hash(self, song_hash: str) -> dict[str, Any] | None:
        if not song_hash:
            return None
        if song_hash in self.hash_lookup_cache:
            return self.hash_lookup_cache[song_hash]

        endpoints = [
            f"https://synthriderz.com/api/beatmaps?hash={song_hash}",
            f"https://synthriderz.com/api/beatmaps?checksum={song_hash}",
            f"https://synthriderz.com/api/beatmaps?songHash={song_hash}",
            f"https://api.synthriderz.com/beatmaps?hash={song_hash}",
            f"https://api.synthriderz.com/beatmaps?checksum={song_hash}",
            f"https://api.synthriderz.com/beatmaps?songHash={song_hash}",
            f"https://synthriderz.com/api/beatmaps/search?hash={song_hash}",
            f"https://synthriderz.com/api/beatmaps/search?checksum={song_hash}",
            f"https://synthriderz.com/api/beatmaps/search?songHash={song_hash}",
        ]
        for endpoint in endpoints:
            try:
                payload = fetch_json(endpoint)
                rec = pick_record_by_hash(payload, song_hash)
                if rec:
                    self.hash_lookup_cache[song_hash] = rec
                    return rec
            except Exception:  # noqa: BLE001
                continue

        # Fallback: iterate paginated beatmaps list and match by hash.
        page = 1
        while page <= 2000:
            try:
                payload = fetch_json(f"https://synthriderz.com/api/beatmaps?page={page}")
                if not isinstance(payload, dict):
                    break
                items = payload.get("data")
                if not isinstance(items, list):
                    break
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item_hash = find_first_scalar(item, ["hash", "checksum", "mapHash", "songHash", "fileHash"])
                    if isinstance(item_hash, str) and item_hash.lower() == song_hash.lower():
                        self.hash_lookup_cache[song_hash] = item
                        return item
                page_count = payload.get("pageCount")
                if isinstance(page_count, int) and page >= page_count:
                    break
                page += 1
            except Exception:  # noqa: BLE001
                break

        self.hash_lookup_cache[song_hash] = None
        return None

    def find_beatmap_record_by_title_artist(self, title: str, artist: str) -> dict[str, Any] | None:
        title_norm = normalize_text(title or "")
        artist_norm = normalize_text(artist or "")
        if not title_norm:
            return None
        cache_key = f"{title_norm}::{artist_norm}"
        if cache_key in self.title_artist_lookup_cache:
            return self.title_artist_lookup_cache[cache_key]

        page = 1
        while page <= 2000:
            try:
                payload = fetch_json(f"https://synthriderz.com/api/beatmaps?page={page}")
                if not isinstance(payload, dict):
                    break
                items = payload.get("data")
                if not isinstance(items, list):
                    break

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item_title = normalize_text(str(item.get("title", "")))
                    if item_title != title_norm:
                        continue
                    if artist_norm:
                        item_artist = normalize_text(str(item.get("artist", "")))
                        if item_artist != artist_norm:
                            continue
                    self.title_artist_lookup_cache[cache_key] = item
                    return item

                page_count = payload.get("pageCount")
                if isinstance(page_count, int) and page >= page_count:
                    break
                page += 1
            except Exception:  # noqa: BLE001
                break

        self.title_artist_lookup_cache[cache_key] = None
        return None

    def enrich_song_download_metadata(self, song: SongEntry) -> None:
        enrich_song_download_metadata_shared(song)

    def download_selected(self) -> None:
        indices = self.selected_indices()
        if not indices:
            messagebox.showerror("No Selection", "Select a song to download.")
            return
        out_dir = filedialog.askdirectory(title="Select Download Folder")
        if not out_dir:
            return
        songs_snapshot = [self.songs[idx] for idx in indices if 0 <= idx < len(self.songs)]
        if not songs_snapshot:
            messagebox.showerror("No Selection", "Select a song to download.")
            return
        if len(songs_snapshot) == 1:
            song = songs_snapshot[0]
            label = song.name or song.hash[:10] or "song"
            self._start_download_worker(
                self._worker_download_selected,
                (song, Path(out_dir)),
                f"Starting download: {label}",
            )
            return
        total_songs = len(songs_snapshot)
        self._start_download_worker(
            self._worker_download_all,
            (songs_snapshot, Path(out_dir)),
            f"Starting selected downloads (0/{total_songs})",
        )

    def _worker_download_selected(self, song: SongEntry, out_dir: Path) -> None:
        try:
            self.enrich_song_download_metadata(song)

            def progress_cb(downloaded: int, total: int | None, filename: str) -> None:
                pct = self.estimate_download_percent(downloaded, total)
                self._queue_download_event(
                    "progress",
                    {"percent": pct, "status": f"Downloading {filename} ({downloaded // 1024} KB)", "indeterminate": False},
                )

            out_path, used_url = download_song_to_dir(
                song,
                out_dir,
                progress_cb=progress_cb,
                cancel_cb=self.is_download_cancelled,
            )
            self._queue_download_event("single_done", {"out_path": str(out_path), "used_url": used_url})
        except DownloadCancelled:
            self._queue_download_event("cancelled", {})
        except Exception as err:  # noqa: BLE001
            self._queue_download_event("error", {"title": "Download Failed", "message": str(err)})
        finally:
            self._queue_download_event("session_end", {})

    def download_all(self) -> None:
        if not self.songs:
            messagebox.showerror("No Songs", "There are no songs to download.")
            return
        out_dir = filedialog.askdirectory(title="Select Download Folder")
        if not out_dir:
            return
        songs_snapshot = list(self.songs)
        total_songs = len(songs_snapshot)
        self._start_download_worker(
            self._worker_download_all,
            (songs_snapshot, Path(out_dir)),
            f"Starting batch download (0/{total_songs})",
        )

    def send_playlist_to_quest(self) -> None:
        if not self.songs:
            messagebox.showerror("No Songs", "There are no songs to send.")
            return
        adb_path = find_adb_executable()
        if not adb_path:
            messagebox.showerror(
                "ADB Not Found",
                "Android Platform Tools (adb) was not found in PATH. Install adb first to send files to a Quest headset.",
            )
            return
        dialog = QuestTransferDialog(self, self.quest_song_dir_var.get(), self.quest_playlist_dir_var.get())
        self.wait_window(dialog)
        if dialog.result is None:
            return
        songs_dir = dialog.result["song_dir"]
        playlist_dir = dialog.result["playlist_dir"]
        transfer_mode = dialog.result["transfer_mode"]
        duplicate_mode = dialog.result["duplicate_mode"]
        self.quest_song_dir_var.set(songs_dir)
        self.quest_playlist_dir_var.set(playlist_dir)
        songs_snapshot = list(self.songs)
        try:
            playlist_payload, playlist_filename = self.build_playlist_export_payload()
        except Exception as err:  # noqa: BLE001
            messagebox.showerror("Playlist Export Failed", str(err))
            return
        self._start_download_worker(
            self._worker_send_playlist_to_quest,
            (
                adb_path,
                songs_snapshot,
                songs_dir,
                playlist_dir,
                playlist_payload,
                playlist_filename,
                transfer_mode,
                duplicate_mode,
            ),
            f"Starting Quest transfer (0/{len(songs_snapshot)})",
        )

    def _worker_send_playlist_to_quest(
        self,
        adb_path: str,
        songs_snapshot: list[SongEntry],
        quest_songs_dir: str,
        quest_playlist_dir: str,
        playlist_payload: dict[str, Any],
        playlist_filename: str,
        transfer_mode: str,
        duplicate_mode: str,
    ) -> None:
        downloaded: list[Path] = []
        failed: list[str] = []
        transferred = 0
        skipped_existing = 0
        playlist_remote_path = ""

        try:
            devices = list_adb_devices(adb_path)
            if not devices:
                raise RuntimeError("No Quest device detected via adb. Connect the headset and allow USB debugging.")

            ensure_device_dir(adb_path, quest_songs_dir)
            ensure_device_dir(adb_path, quest_playlist_dir)

            total_songs = len(songs_snapshot)
            with tempfile.TemporaryDirectory(prefix="sr_playlist_forge_quest_") as temp_dir:
                temp_path = Path(temp_dir)

                if transfer_mode in {"both", "songs"}:
                    for i, song in enumerate(songs_snapshot, start=1):
                        if self.is_download_cancelled():
                            raise DownloadCancelled("Quest transfer cancelled by user.")
                        self.enrich_song_download_metadata(song)
                        label = song.name or song.hash[:10] or f"Song {i}"
                        self._queue_download_event(
                            "progress",
                            {
                                "percent": ((i - 1) / max(total_songs, 1)) * 100.0,
                                "status": f"Downloading {i}/{total_songs}: {label}",
                                "indeterminate": False,
                            },
                        )
                        try:
                            local_file, _ = download_song_to_dir(
                                song,
                                temp_path,
                                cancel_cb=self.is_download_cancelled,
                            )
                            downloaded.append(local_file)
                            remote_path = f"{quest_songs_dir.rstrip('/')}/{local_file.name}"
                            if duplicate_mode == "skip" and adb_remote_file_exists(adb_path, remote_path):
                                skipped_existing += 1
                                continue
                            self._queue_download_event(
                                "progress",
                                {
                                    "percent": ((i - 0.5) / max(total_songs, 1)) * 100.0,
                                    "status": f"Pushing {i}/{total_songs}: {local_file.name}",
                                    "indeterminate": False,
                                },
                            )
                            adb_push_file(adb_path, local_file, remote_path)
                            HEADSET_SYNTH_METADATA_CACHE.pop(remote_path, None)
                            transferred += 1
                        except DownloadCancelled:
                            raise
                        except Exception as err:  # noqa: BLE001
                            failed.append(f"{label}: {err}")

                if transfer_mode in {"both", "playlist"}:
                    playlist_local_path = temp_path / playlist_filename
                    playlist_local_path.write_text(
                        json.dumps(playlist_payload, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    playlist_remote_path = f"{quest_playlist_dir.rstrip('/')}/{playlist_filename}"
                    if not (duplicate_mode == "skip" and adb_remote_file_exists(adb_path, playlist_remote_path)):
                        self._queue_download_event(
                            "progress",
                            {"percent": 100.0, "status": f"Pushing playlist: {playlist_filename}", "indeterminate": False},
                        )
                        adb_push_file(adb_path, playlist_local_path, playlist_remote_path)
                    else:
                        skipped_existing += 1

            lines = []
            if transfer_mode in {"both", "songs"}:
                lines.append(f"Transferred songs: {transferred}/{len(songs_snapshot)}")
            if transfer_mode in {"both", "playlist"}:
                lines.append(f"Playlist: {playlist_remote_path or 'Skipped existing playlist'}")
            if skipped_existing:
                lines.append(f"Skipped existing files: {skipped_existing}")
            if failed:
                lines.extend(["", "Failed songs:"])
                lines.extend(failed[:20])
                if len(failed) > 20:
                    lines.append(f"...and {len(failed) - 20} more")
                self._queue_download_event("batch_done", {"lines": lines, "failed": True, "cancelled": False})
            else:
                self._queue_download_event("batch_done", {"lines": lines, "failed": False, "cancelled": False})
        except DownloadCancelled:
            self._queue_download_event("cancelled", {})
        except Exception as err:  # noqa: BLE001
            self._queue_download_event("error", {"title": "Quest Transfer Failed", "message": str(err)})
        finally:
            self._queue_download_event("session_end", {})

    def _worker_download_all(self, songs_snapshot: list[SongEntry], out_path: Path) -> None:
        ok: list[str] = []
        failed: list[str] = []
        total_songs = len(songs_snapshot)
        cancelled = False

        try:
            for i, song in enumerate(songs_snapshot, start=1):
                if self.is_download_cancelled():
                    cancelled = True
                    break
                self.enrich_song_download_metadata(song)
                try:
                    label = song.name or song.hash[:10] or f"Song {i}"

                    def progress_cb(downloaded: int, total: int | None, filename: str, idx=i, name=label) -> None:
                        song_pct = self.estimate_download_percent(downloaded, total) / 100.0
                        overall = ((idx - 1) + song_pct) / total_songs * 100.0
                        self._queue_download_event(
                            "progress",
                            {
                                "percent": overall,
                                "status": f"Downloading {idx}/{total_songs}: {name} ({downloaded // 1024} KB)",
                                "indeterminate": False,
                            },
                        )

                    saved, _ = download_song_to_dir(
                        song,
                        out_path,
                        progress_cb=progress_cb,
                        cancel_cb=self.is_download_cancelled,
                    )
                    ok.append(f"{i}. {saved.name}")
                    overall_done = (i / total_songs) * 100.0
                    self._queue_download_event(
                        "progress",
                        {"percent": overall_done, "status": f"Completed {i}/{total_songs}: {saved.name}", "indeterminate": False},
                    )
                except DownloadCancelled:
                    cancelled = True
                    break
                except Exception as err:  # noqa: BLE001
                    label = song.name or song.hash or f"Song {i}"
                    failed.append(f"{i}. {label}: {err}")

            self._queue_download_event(
                "progress",
                {
                    "percent": 100.0,
                    "status": f"Batch finished: {len(ok)}/{total_songs} downloaded",
                    "indeterminate": False,
                },
            )

            lines = [f"Downloaded: {len(ok)}/{total_songs}"]
            if cancelled:
                lines.append("Status: Cancelled by user.")
            if ok:
                lines.extend(["", "Success:"])
                lines.extend(ok[:30])
                if len(ok) > 30:
                    lines.append(f"...and {len(ok) - 30} more")
            if failed:
                lines.extend(["", "Failed:"])
                lines.extend(failed[:20])
                if len(failed) > 20:
                    lines.append(f"...and {len(failed) - 20} more")
            self._queue_download_event("batch_done", {"lines": lines, "failed": bool(failed), "cancelled": cancelled})
        except Exception as err:  # noqa: BLE001
            self._queue_download_event("error", {"title": "Download Failed", "message": str(err)})
        finally:
            self._queue_download_event("session_end", {})

    def session_file_path(self) -> Path:
        return Path.home() / ".sr_playlist_forge_session.json"

    def schedule_session_save(self) -> None:
        if self.restoring_session:
            return
        if self.session_save_after_id:
            try:
                self.after_cancel(self.session_save_after_id)
            except Exception:  # noqa: BLE001
                pass
        self.session_save_after_id = self.after(400, self.save_session)

    def save_session(self) -> None:
        self.session_save_after_id = None
        if self.restoring_session:
            return
        payload = {
            "playlist_vars": {k: v.get() for k, v in self.playlist_vars.items()},
            "playlist_state": {
                "creation_date_auto_managed": self.creation_date_auto_managed,
            },
            "theme_mode": self.theme_mode_var.get(),
            "quest_vars": {
                "song_dir": self.quest_song_dir_var.get(),
                "playlist_dir": self.quest_playlist_dir_var.get(),
            },
            "songs": [asdict(song) for song in self.songs],
        }
        try:
            self.session_file_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def restore_session(self) -> None:
        path = self.session_file_path()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return

        self.restoring_session = True
        try:
            playlist_raw = raw.get("playlist_vars", {})
            if isinstance(playlist_raw, dict):
                for key, var in self.playlist_vars.items():
                    if key in playlist_raw:
                        var.set(str(playlist_raw[key]))
            playlist_state = raw.get("playlist_state", {})
            if isinstance(playlist_state, dict):
                self.creation_date_auto_managed = bool(
                    playlist_state.get("creation_date_auto_managed", self.creation_date_auto_managed)
                )

            quest_raw = raw.get("quest_vars", {})
            if isinstance(quest_raw, dict):
                self.quest_song_dir_var.set(str(quest_raw.get("song_dir", self.quest_song_dir_var.get())))
                self.quest_playlist_dir_var.set(str(quest_raw.get("playlist_dir", self.quest_playlist_dir_var.get())))

            theme_mode = str(raw.get("theme_mode", self.theme_mode_var.get()))
            if theme_mode in THEME_PRESETS:
                self.theme_mode_var.set(theme_mode)
                self.apply_theme()

            songs_raw = raw.get("songs", [])
            restored: list[SongEntry] = []
            if isinstance(songs_raw, list):
                for item in songs_raw:
                    if not isinstance(item, dict):
                        continue
                    restored.append(
                        SongEntry(
                            hash=str(item.get("hash", "")),
                            name=str(item.get("name", "")),
                            author=str(item.get("author", "")),
                            beatmapper=str(item.get("beatmapper", "")),
                            difficulty=force_int(item.get("difficulty"), 0),
                            difficultyText=str(item.get("difficultyText", item.get("difficulty", ""))),
                            trackDuration=force_float(item.get("trackDuration"), 0.0),
                            addedTime=force_int(item.get("addedTime"), int(time.time())),
                            beatmapId=str(item.get("beatmapId", "")),
                            sourceUrl=str(item.get("sourceUrl", "")),
                            downloadUrl=str(item.get("downloadUrl", "")),
                        )
                    )
            self.songs = restored
            self.update_generated_filename()
            self.refresh_table(keep_index=0 if self.songs else None)
        finally:
            self.restoring_session = False
        self.refresh_creation_date_if_auto()
        self.save_session()

    def on_close(self) -> None:
        if self.quest_status_after_id:
            try:
                self.after_cancel(self.quest_status_after_id)
            except Exception:  # noqa: BLE001
                pass
            self.quest_status_after_id = None
        self.save_session()
        if self.instance_guard is not None:
            self.instance_guard.release()
            self.instance_guard = None
        self.destroy()


def main() -> None:
    install_global_exception_hooks()
    instance_guard = SingleInstanceGuard()
    if not instance_guard.acquire():
        show_fatal_error_dialog(
            "SR Playlist Forge Already Running",
            "SR Playlist Forge is already open.\n\n"
            "Please switch to the existing window or close it before starting another instance.",
        )
        return
    app: PlaylistEditorApp | None = None
    try:
        app = PlaylistEditorApp(instance_guard=instance_guard)
        app.mainloop()
    finally:
        if app is None or instance_guard is not app.instance_guard:
            instance_guard.release()


if __name__ == "__main__":
    main()
