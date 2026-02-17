#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import tkinter as tk
from dataclasses import dataclass, asdict
from datetime import datetime
from html import unescape
from pathlib import Path
from tkinter import scrolledtext
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    BASE_TK_CLASS = TkinterDnD.Tk
    HAS_DND_SUPPORT = True
except Exception:  # noqa: BLE001
    DND_FILES = None
    BASE_TK_CLASS = tk.Tk
    HAS_DND_SUPPORT = False


ID_RE = re.compile(r"/beatmaps/(\d+)")
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
        self.widget.bind("<Enter>", self.show)
        self.widget.bind("<Leave>", self.hide)

    def show(self, _event=None):
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
        if self.tipwindow is not None:
            self.tipwindow.destroy()
            self.tipwindow = None


class PlaylistEditorApp(BASE_TK_CLASS):
    def __init__(self) -> None:
        super().__init__()
        self.title("SR Playlist Forge")
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
        self.download_cancel_event = threading.Event()
        self.download_events: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self.download_in_progress = False
        self.download_poll_after_id: str | None = None
        self.download_worker_thread: threading.Thread | None = None
        self.session_save_after_id: str | None = None
        self.restoring_session = False
        self.sort_column: str | None = None
        self.sort_desc: bool = False
        self.current_view_indices: list[int] = []
        self.songs: list[SongEntry] = []
        self.hash_lookup_cache: dict[str, dict[str, Any] | None] = {}
        self.title_artist_lookup_cache: dict[str, dict[str, Any] | None] = {}
        self._tooltips: list[HoverTooltip] = []

        self.playlist_vars["playlistNumber"].trace_add("write", lambda *_: self.update_generated_filename())
        self.playlist_vars["namePlaylist"].trace_add("write", lambda *_: self.update_generated_filename())
        for var in self.playlist_vars.values():
            var.trace_add("write", lambda *_: self.schedule_session_save())
        self.duration_filter_mode = tk.StringVar(value="Any")
        self.duration_filter_value = tk.StringVar(value="")
        self.difficulty_filter_choice = tk.StringVar(value="Any")
        self.update_generated_filename()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.restore_session()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=8)
        root.pack(fill="both", expand=True)

        meta = ttk.LabelFrame(root, text="Playlist Info")
        meta.pack(fill="x", pady=(0, 8))
        meta.columnconfigure(1, weight=1)
        meta.columnconfigure(3, weight=1)
        meta.columnconfigure(5, weight=1)
        fields = [
            ("namePlaylist", "namePlaylist", ""),
            (
                "Playlist Number",
                "playlistNumber",
                "Filename is auto-generated as 000007__namePlaylist.playlist.\n"
                "Enter any number and the app pads it to 6 digits.",
            ),
            ("description", "description", ""),
            ("SelectedIconIndex", "SelectedIconIndex", ""),
            ("SelectedTexture", "SelectedTexture", ""),
            ("gradientTop", "gradientTop", ""),
            ("gradientDown", "gradientDown", ""),
            ("colorTitle", "colorTitle", ""),
            ("colorTexture", "colorTexture", ""),
            (
                "creationDate (local)",
                "creationDateHuman",
                "Shown as readable local date/time.\n"
                "Supported formats: YYYY-MM-DD HH:MM[:SS] or YYYY-MM-DD.",
            ),
        ]
        for i, (label, key, tip) in enumerate(fields):
            ttk.Label(meta, text=label).grid(row=i // 3, column=(i % 3) * 2, padx=6, pady=4, sticky="e")
            col = (i % 3) * 2 + 1
            row = i // 3
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

        import_frame = ttk.LabelFrame(root, text="Add Song")
        import_frame.pack(fill="x", pady=(0, 8))
        import_frame.columnconfigure(1, weight=1)
        self.url_var = tk.StringVar()
        ttk.Label(import_frame, text="Beatmap URL").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(import_frame, textvariable=self.url_var, width=52).grid(row=0, column=1, padx=6, pady=6, sticky="we")
        ttk.Button(import_frame, text="Add from URL", width=14, command=self.add_song_from_url).grid(
            row=0, column=2, padx=6, pady=6
        )
        ttk.Button(import_frame, text="Add Empty Song", width=14, command=self.add_empty_song).grid(
            row=0, column=3, padx=6, pady=6
        )
        ttk.Button(import_frame, text="Add .synth Files", width=14, command=self.add_synth_files_dialog).grid(
            row=0, column=4, padx=6, pady=6
        )

        drop_hint = "Drop .synth files here"
        if not HAS_DND_SUPPORT:
            drop_hint += " | Install tkinterdnd2 for drag-and-drop support"
        self.drop_zone = tk.Label(
            import_frame,
            text=drop_hint,
            anchor="center",
            relief="groove",
            borderwidth=1,
            padx=8,
            pady=6,
        )
        self.drop_zone.grid(row=1, column=0, columnspan=5, sticky="we", padx=6, pady=(2, 6))
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

        table_frame = ttk.Frame(root)
        table_frame.pack(fill="both", expand=True)

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
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
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
        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="left", fill="y")

        btn_col = ttk.Frame(table_frame)
        btn_col.pack(side="left", fill="y", padx=8)
        ttk.Button(btn_col, text="Edit", command=self.edit_selected).pack(fill="x", pady=2)
        ttk.Button(btn_col, text="Remove", command=self.remove_selected).pack(fill="x", pady=2)
        ttk.Button(btn_col, text="Clear All Songs", command=self.clear_all_songs).pack(fill="x", pady=2)
        ttk.Button(btn_col, text="Move Up", command=lambda: self.move_selected(-1)).pack(fill="x", pady=2)
        ttk.Button(btn_col, text="Move Down", command=lambda: self.move_selected(1)).pack(fill="x", pady=2)
        ttk.Button(btn_col, text="Download Selected", command=self.download_selected).pack(fill="x", pady=10)
        ttk.Button(btn_col, text="Download All", command=self.download_all).pack(fill="x", pady=2)

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(8, 0))
        ttk.Label(footer, text="Export filename:").pack(side="left", padx=(6, 4))
        ttk.Label(footer, textvariable=self.generated_filename_var).pack(side="left", padx=(0, 8))
        ttk.Label(footer, textvariable=self.stats_var).pack(side="left", padx=12)
        ttk.Button(footer, text="Add .playlist", command=self.add_playlist).pack(side="right", padx=6)
        ttk.Button(footer, text="Export .playlist", command=self.export_playlist).pack(side="right", padx=6)

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

    def selected_index(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])

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

    def update_generated_filename(self) -> None:
        try:
            name = build_playlist_filename(
                self.playlist_vars["playlistNumber"].get(),
                self.playlist_vars["namePlaylist"].get(),
            )
            self.generated_filename_var.set(name)
        except Exception:
            self.generated_filename_var.set("Invalid playlist number or name")

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
        idx = self.selected_index()
        if idx is None:
            return
        del self.songs[idx]
        keep_idx = min(idx, len(self.songs) - 1) if self.songs else None
        self.refresh_table(keep_index=keep_idx)

    def clear_all_songs(self) -> None:
        if not self.songs:
            return
        if not messagebox.askyesno("Clear All Songs", "Remove all songs from the current playlist?"):
            return
        self.songs.clear()
        self.refresh_table(keep_index=None)

    def move_selected(self, delta: int) -> None:
        idx = self.selected_index()
        if idx is None:
            return
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
            self.playlist_vars["creationDate"].set(str(imported_ts))
            self.playlist_vars["creationDateHuman"].set(timestamp_to_local_text(imported_ts))

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
            default_name = build_playlist_filename(
                self.playlist_vars["playlistNumber"].get(),
                self.playlist_vars["namePlaylist"].get(),
            )
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
        if (song.beatmapId and song.downloadUrl) or not song.hash:
            return
        if not song.beatmapId and song.sourceUrl:
            maybe_id = parse_beatmap_id(song.sourceUrl)
            if maybe_id:
                song.beatmapId = maybe_id
        rec = self.find_beatmap_record_by_hash(song.hash)
        if not rec:
            # Some older playlist hashes are not downloadable anymore; fallback by title/artist.
            rec = self.find_beatmap_record_by_title_artist(song.name, song.author)
        if not rec:
            if song.beatmapId and not song.sourceUrl:
                song.sourceUrl = f"https://synthriderz.com/beatmaps/{song.beatmapId}"
            return

        if not song.beatmapId:
            rec_id = find_first_scalar(rec, ["id", "beatmapId", "mapId"])
            if rec_id is not None:
                song.beatmapId = str(rec_id)
        if song.beatmapId and not song.sourceUrl:
            song.sourceUrl = f"https://synthriderz.com/beatmaps/{song.beatmapId}"
        if not song.downloadUrl:
            song.downloadUrl = resolve_download_url(rec, song.beatmapId)

    def download_selected(self) -> None:
        idx = self.selected_index()
        if idx is None:
            messagebox.showerror("No Selection", "Select a song to download.")
            return
        out_dir = filedialog.askdirectory(title="Select Download Folder")
        if not out_dir:
            return
        song = self.songs[idx]
        label = song.name or song.hash[:10] or "song"
        self._start_download_worker(self._worker_download_selected, (song, Path(out_dir)), f"Starting download: {label}")

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
        self.save_session()

    def on_close(self) -> None:
        self.save_session()
        self.destroy()


def main() -> None:
    app = PlaylistEditorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
