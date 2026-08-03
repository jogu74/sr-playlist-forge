#!/usr/bin/env python3
"""Import Synth Riders playlist icons and textures from a user-owned installation."""

from __future__ import annotations

import importlib
import gc
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SYNTH_RIDERS_PACKAGE = "com.kluge.SynthRiders"
SYNTH_RIDERS_STEAM_APP_ID = "885000"
QUEST_OBB_DIR = f"/sdcard/Android/obb/{SYNTH_RIDERS_PACKAGE}"
QUEST_UNITY_ENTRIES = (
    "assets/bin/Data/data.unity3d",
    "assets/bin/Data/resources.resource",
    "assets/bin/Data/sharedassets2.resource",
    "assets/bin/Data/sharedassets3.resource",
    "assets/bin/Data/sharedassets17.resource",
)
MAX_QUEST_ENTRY_BYTES = 4 * 1024 * 1024 * 1024
MAX_QUEST_TOTAL_BYTES = 5 * 1024 * 1024 * 1024
ICON_NAMES = tuple(f"CustomProfile-{index:02d}" for index in range(1, 21))
TEXTURE_NAMES = (
    "imageAlpha",
    "texture1",
    "texture2",
    "texture3",
    "texture4",
    "texture5",
    "texture6",
    "texture7",
    "texture8",
    "texture9",
    "texture810",
)
ICON_INDEX_NAMES: tuple[str | None, ...] = (None, *ICON_NAMES)
TEXTURE_INDEX_NAMES: tuple[str | None, ...] = (
    "imageAlpha",
    None,
    "texture1",
    "texture2",
    "texture3",
    "texture4",
    "texture5",
    "texture6",
    "texture7",
    "texture8",
    "texture9",
    "texture810",
)
ProgressCallback = Callable[[str], None]
PLAYLIST_INITIAL_FONT_NAME = "Bordas"
PLAYLIST_INITIAL_FONT_ROLE = "playlistInitial"


class PlaylistVisualImportError(RuntimeError):
    """Raised when playlist visual resources cannot be imported safely."""


@dataclass(frozen=True)
class PlaylistVisualImportResult:
    source_kind: str
    source_label: str
    cache_dir: Path
    icon_count: int
    texture_count: int


def _notify(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _hidden_window_kwargs() -> dict[str, Any]:
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


def _adb_environment(adb_path: str) -> tuple[str, dict[str, str]]:
    resolved = str(Path(adb_path).resolve())
    adb_dir = str(Path(resolved).parent)
    env = os.environ.copy()
    env["PATH"] = adb_dir + os.pathsep + env.get("PATH", "")
    return adb_dir, env


def _run_adb(adb_path: str, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    adb_dir, env = _adb_environment(adb_path)
    return subprocess.run(
        [adb_path, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=adb_dir,
        env=env,
        **_hidden_window_kwargs(),
    )


def find_quest_obb(adb_path: str) -> str:
    result = _run_adb(adb_path, ["shell", "ls", "-1", QUEST_OBB_DIR], timeout=60)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise PlaylistVisualImportError(f"Synth Riders OBB folder could not be read: {detail or 'unknown adb error'}")
    valid_names = [
        line.strip()
        for line in result.stdout.splitlines()
        if re.fullmatch(r"(?:main|patch)\.\d+\.com\.kluge\.SynthRiders\.obb", line.strip())
    ]
    main_names = [name for name in valid_names if name.startswith("main.")]
    if not main_names:
        raise PlaylistVisualImportError("No Synth Riders main OBB file was found on the connected headset.")
    main_names.sort(key=lambda value: int(value.split(".", 2)[1]), reverse=True)
    return f"{QUEST_OBB_DIR}/{main_names[0]}"


def _quest_zip_entry_size(adb_path: str, archive_path: str, entry_name: str) -> int:
    result = _run_adb(adb_path, ["shell", "unzip", "-l", archive_path, entry_name], timeout=60)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise PlaylistVisualImportError(f"Could not inspect {entry_name} on the headset: {detail}")
    for line in result.stdout.splitlines():
        columns = line.split()
        if columns and columns[-1] == entry_name and columns[0].isdigit():
            return int(columns[0])
    raise PlaylistVisualImportError(f"The required Unity file {entry_name} is missing from the headset installation.")


def _stream_quest_zip_entry(
    adb_path: str,
    archive_path: str,
    entry_name: str,
    destination: Path,
    expected_size: int,
) -> None:
    adb_dir, env = _adb_environment(adb_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output:
        process = subprocess.Popen(
            [adb_path, "exec-out", "unzip", "-p", archive_path, entry_name],
            stdout=output,
            stderr=subprocess.PIPE,
            cwd=adb_dir,
            env=env,
            **_hidden_window_kwargs(),
        )
        try:
            _stdout, stderr = process.communicate(timeout=1800)
        except subprocess.TimeoutExpired as err:
            process.kill()
            process.communicate()
            destination.unlink(missing_ok=True)
            raise PlaylistVisualImportError(f"Timed out while reading {entry_name} from the headset.") from err
    if process.returncode != 0:
        destination.unlink(missing_ok=True)
        detail = (stderr or b"").decode("utf-8", errors="replace").strip()
        raise PlaylistVisualImportError(f"Could not read {entry_name} from the headset: {detail or 'adb failed'}")
    actual_size = destination.stat().st_size
    if actual_size != expected_size:
        destination.unlink(missing_ok=True)
        raise PlaylistVisualImportError(
            f"Incomplete headset transfer for {entry_name}: expected {expected_size} bytes, got {actual_size}."
        )


def prepare_quest_unity_source(
    adb_path: str,
    destination_dir: Path,
    progress: ProgressCallback | None = None,
) -> tuple[Path, str]:
    archive_path = find_quest_obb(adb_path)
    sizes = {
        entry_name: _quest_zip_entry_size(adb_path, archive_path, entry_name)
        for entry_name in QUEST_UNITY_ENTRIES
    }
    if any(size <= 0 or size > MAX_QUEST_ENTRY_BYTES for size in sizes.values()):
        raise PlaylistVisualImportError("The headset installation contains an unexpectedly large or empty Unity file.")
    if sum(sizes.values()) > MAX_QUEST_TOTAL_BYTES:
        raise PlaylistVisualImportError("The required headset resources exceed the safe transfer limit.")

    destination_dir.mkdir(parents=True, exist_ok=True)
    for position, entry_name in enumerate(QUEST_UNITY_ENTRIES, start=1):
        _notify(progress, f"Reading game resources from Quest ({position}/{len(QUEST_UNITY_ENTRIES)})…")
        destination = destination_dir / Path(entry_name).name
        _stream_quest_zip_entry(adb_path, archive_path, entry_name, destination, sizes[entry_name])
    return destination_dir / "data.unity3d", archive_path


def _safe_zip_member(zip_file: zipfile.ZipFile, member_name: str) -> zipfile.ZipInfo:
    try:
        info = zip_file.getinfo(member_name)
    except KeyError as err:
        raise PlaylistVisualImportError(f"The required Unity file {member_name} is missing.") from err
    if info.file_size <= 0 or info.file_size > MAX_QUEST_ENTRY_BYTES:
        raise PlaylistVisualImportError(f"Unexpected size for {member_name}.")
    return info


def prepare_local_obb_source(
    archive_path: Path,
    destination_dir: Path,
    progress: ProgressCallback | None = None,
) -> Path:
    with zipfile.ZipFile(archive_path) as archive:
        infos = [_safe_zip_member(archive, name) for name in QUEST_UNITY_ENTRIES]
        if sum(info.file_size for info in infos) > MAX_QUEST_TOTAL_BYTES:
            raise PlaylistVisualImportError("The required Unity resources exceed the safe extraction limit.")
        destination_dir.mkdir(parents=True, exist_ok=True)
        for position, info in enumerate(infos, start=1):
            _notify(progress, f"Extracting local game resources ({position}/{len(infos)})…")
            destination = destination_dir / Path(info.filename).name
            with archive.open(info) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            if destination.stat().st_size != info.file_size:
                raise PlaylistVisualImportError(f"Incomplete extraction for {info.filename}.")
    return destination_dir / "data.unity3d"


def resolve_pc_unity_source(selected_path: Path) -> Path:
    selected = selected_path.expanduser().resolve()
    if not selected.exists():
        raise PlaylistVisualImportError("The selected Synth Riders installation does not exist.")
    if selected.is_file():
        return selected

    direct_bundle = selected / "data.unity3d"
    if direct_bundle.is_file():
        return direct_bundle

    preferred_data_dirs = [
        selected / "SynthRiders_Data",
        selected / "Synth Riders_Data",
    ]
    preferred_data_dirs.extend(
        child for child in selected.iterdir() if child.is_dir() and child.name.casefold().endswith("_data")
    )
    for data_dir in preferred_data_dirs:
        if not data_dir.is_dir():
            continue
        bundle = data_dir / "data.unity3d"
        if bundle.is_file():
            return bundle
        if any(data_dir.glob("*.assets")):
            return data_dir

    if any(selected.glob("*.assets")):
        return selected
    raise PlaylistVisualImportError(
        "No Unity game data was found. Select the Synth Riders game folder or its *_Data folder."
    )


def _load_unitypy() -> Any:
    try:
        return importlib.import_module("UnityPy")
    except ImportError as err:
        raise PlaylistVisualImportError(
            "Unity resource support is missing from this build. Reinstall SR Playlist Forge or install UnityPy."
        ) from err


def _peek_name(obj: Any) -> str:
    try:
        return str(obj.peek_name() or "").strip()
    except Exception:
        return ""


def _dispose_unity_environment(environment: Any) -> None:
    seen: set[int] = set()

    def dispose(value: Any) -> None:
        if value is None or id(value) in seen:
            return
        seen.add(id(value))
        if isinstance(value, dict):
            for child in list(value.values()):
                dispose(child)
            return
        if isinstance(value, (list, tuple, set)):
            for child in list(value):
                dispose(child)
            return
        for attribute in ("files", "cabs"):
            children = getattr(value, attribute, None)
            if isinstance(children, dict):
                dispose(children)
        reader = getattr(value, "reader", None)
        if reader is not value:
            dispose(reader)
        disposer = getattr(value, "dispose", None)
        if callable(disposer):
            try:
                disposer()
            except Exception:
                pass
            return
        stream = getattr(value, "stream", None)
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    dispose(environment)
    for attribute in ("files", "cabs"):
        collection = getattr(environment, attribute, None)
        if isinstance(collection, dict):
            collection.clear()
    gc.collect()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _create_transparent_png(path: Path) -> None:
    try:
        pillow_image = importlib.import_module("PIL.Image")
    except ImportError as err:
        raise PlaylistVisualImportError("Pillow is required to create the playlist preview cache.") from err
    pillow_image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(path)


def import_unity_visuals(
    unity_source: Path,
    cache_root: Path,
    *,
    source_kind: str,
    source_label: str,
    progress: ProgressCallback | None = None,
) -> PlaylistVisualImportResult:
    unitypy = _load_unitypy()
    _notify(progress, "Scanning Unity resources for playlist visuals…")
    try:
        environment = unitypy.load(str(unity_source))
    except Exception as err:
        raise PlaylistVisualImportError(f"The selected Unity resources could not be opened: {err}") from err

    wanted = set(ICON_NAMES) | set(TEXTURE_NAMES)
    found: dict[str, Any] = {}
    playlist_initial_font_data: bytes | None = None
    try:
        for obj in environment.objects:
            name = _peek_name(obj)
            if obj.type.name == "Font" and name == PLAYLIST_INITIAL_FONT_NAME:
                try:
                    font_data = bytes(obj.read(check_read=False).m_FontData or b"")
                    if font_data:
                        playlist_initial_font_data = font_data
                except Exception:
                    pass
                continue
            if obj.type.name != "Sprite":
                continue
            if name not in wanted or name in found:
                continue
            try:
                found[name] = obj.read(check_read=False).image.convert("RGBA")
            except Exception:
                continue
            if wanted.issubset(found) and playlist_initial_font_data is not None:
                break
    except Exception as err:
        raise PlaylistVisualImportError(f"Unity resource scanning failed: {err}") from err
    finally:
        _dispose_unity_environment(environment)

    required = set(ICON_NAMES) | set(TEXTURE_NAMES[1:])
    missing = sorted(required - set(found))
    if missing:
        preview = ", ".join(missing[:8])
        suffix = f" and {len(missing) - 8} more" if len(missing) > 8 else ""
        raise PlaylistVisualImportError(
            f"This installation does not contain all expected playlist visuals ({preview}{suffix})."
        )

    cache_root = cache_root.resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    import_id = datetime.now(timezone.utc).strftime("import-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    import_dir = cache_root / import_id
    icons_dir = import_dir / "icons"
    textures_dir = import_dir / "textures"
    fonts_dir = import_dir / "fonts"
    icons_dir.mkdir(parents=True)
    textures_dir.mkdir(parents=True)
    fonts_dir.mkdir(parents=True)
    try:
        icon_files: dict[str, str] = {}
        for index, name in enumerate(ICON_INDEX_NAMES):
            relative = Path("icons") / f"{index:02d}.png"
            destination = import_dir / relative
            if name is None:
                _create_transparent_png(destination)
            else:
                found[name].save(destination)
            icon_files[str(index)] = relative.as_posix()

        texture_files: dict[str, str] = {}
        for index, name in enumerate(TEXTURE_INDEX_NAMES):
            relative = Path("textures") / f"{index:02d}.png"
            destination = import_dir / relative
            if name is None or name not in found:
                _create_transparent_png(destination)
            else:
                found[name].save(destination)
            texture_files[str(index)] = relative.as_posix()

        font_files: dict[str, str] = {}
        if playlist_initial_font_data:
            extension = ".otf" if playlist_initial_font_data.startswith(b"OTTO") else ".ttf"
            relative = Path("fonts") / f"Bordas{extension}"
            (import_dir / relative).write_bytes(playlist_initial_font_data)
            font_files[PLAYLIST_INITIAL_FONT_ROLE] = relative.as_posix()

        manifest = {
            "schemaVersion": 2,
            "sourceKind": source_kind,
            "sourceLabel": source_label,
            "importedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "icons": icon_files,
            "textures": texture_files,
            "fonts": font_files,
        }
        _atomic_write_json(import_dir / "manifest.json", manifest)
        _atomic_write_json(cache_root / "current.json", {"schemaVersion": 2, "importId": import_id})
    except Exception:
        shutil.rmtree(import_dir, ignore_errors=True)
        raise

    _notify(progress, "Playlist visuals imported.")
    return PlaylistVisualImportResult(
        source_kind=source_kind,
        source_label=source_label,
        cache_dir=import_dir,
        icon_count=len(ICON_INDEX_NAMES),
        texture_count=len(TEXTURE_INDEX_NAMES),
    )


def import_from_quest(
    adb_path: str,
    cache_root: Path,
    progress: ProgressCallback | None = None,
) -> PlaylistVisualImportResult:
    with tempfile.TemporaryDirectory(prefix="srpf-quest-visuals-") as temp_dir:
        unity_source, archive_path = prepare_quest_unity_source(adb_path, Path(temp_dir), progress)
        return import_unity_visuals(
            unity_source,
            cache_root,
            source_kind="quest",
            source_label=archive_path,
            progress=progress,
        )


def import_from_pc(
    selected_path: Path,
    cache_root: Path,
    progress: ProgressCallback | None = None,
) -> PlaylistVisualImportResult:
    selected = selected_path.expanduser().resolve()
    source = resolve_pc_unity_source(selected)
    if source.is_file() and source.suffix.casefold() in {".obb", ".zip"}:
        with tempfile.TemporaryDirectory(prefix="srpf-pc-visuals-") as temp_dir:
            unity_source = prepare_local_obb_source(source, Path(temp_dir), progress)
            return import_unity_visuals(
                unity_source,
                cache_root,
                source_kind="pc",
                source_label=str(selected),
                progress=progress,
            )
    return import_unity_visuals(
        source,
        cache_root,
        source_kind="pc",
        source_label=str(selected),
        progress=progress,
    )


def load_current_manifest(cache_root: Path) -> tuple[Path, dict[str, Any]] | None:
    root = cache_root.resolve()
    pointer_path = root / "current.json"
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        import_id = pointer["importId"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None
    if not isinstance(import_id, str) or not re.fullmatch(r"import-[A-Za-z0-9TZ-]+", import_id):
        return None
    import_dir = (root / import_id).resolve()
    try:
        import_dir.relative_to(root)
    except ValueError:
        return None
    try:
        manifest = json.loads((import_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") not in {1, 2}:
        return None
    return import_dir, manifest


def cached_visual_path(cache_root: Path, kind: str, index: int) -> Path | None:
    if kind not in {"icons", "textures"}:
        return None
    loaded = load_current_manifest(cache_root)
    if loaded is None:
        return None
    import_dir, manifest = loaded
    entries = manifest.get(kind)
    if not isinstance(entries, dict):
        return None
    relative_value = entries.get(str(index))
    if not isinstance(relative_value, str):
        return None
    candidate = (import_dir / relative_value).resolve()
    try:
        candidate.relative_to(import_dir)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def cached_font_path(cache_root: Path, role: str = PLAYLIST_INITIAL_FONT_ROLE) -> Path | None:
    loaded = load_current_manifest(cache_root)
    if loaded is None:
        return None
    import_dir, manifest = loaded
    entries = manifest.get("fonts")
    if not isinstance(entries, dict):
        return None
    relative_value = entries.get(role)
    if not isinstance(relative_value, str):
        return None
    candidate = (import_dir / relative_value).resolve()
    try:
        candidate.relative_to(import_dir)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _parse_steam_library_paths(vdf_path: Path) -> list[Path]:
    try:
        text = vdf_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    paths: list[Path] = []
    for raw_path in re.findall(r'"path"\s+"([^"]+)"', text, flags=re.IGNORECASE):
        paths.append(Path(raw_path.replace("\\\\", "\\")))
    return paths


def discover_pc_installations() -> list[Path]:
    candidates: list[Path] = []
    if os.name == "nt":
        try:
            winreg = importlib.import_module("winreg")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                candidates.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except (OSError, ImportError):
            pass
        program_files_x86 = os.environ.get("ProgramFiles(x86)")
        program_files = os.environ.get("ProgramFiles")
        if program_files_x86:
            candidates.append(Path(program_files_x86) / "Steam")
        if program_files:
            candidates.extend(
                [
                    Path(program_files) / "Oculus" / "Software" / "Software",
                    Path(program_files) / "Meta Quest Link" / "Software" / "Software",
                ]
            )
    else:
        candidates.extend(
            [
                Path.home() / ".steam" / "steam",
                Path.home() / "Library" / "Application Support" / "Steam",
            ]
        )

    steam_roots = list(candidates)
    for root in list(steam_roots):
        steam_roots.extend(_parse_steam_library_paths(root / "steamapps" / "libraryfolders.vdf"))

    installations: list[Path] = []
    for root in steam_roots:
        manifest_path = root / "steamapps" / f"appmanifest_{SYNTH_RIDERS_STEAM_APP_ID}.acf"
        if manifest_path.is_file():
            try:
                text = manifest_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            match = re.search(r'"installdir"\s+"([^"]+)"', text, flags=re.IGNORECASE)
            if match:
                installations.append(root / "steamapps" / "common" / match.group(1))
        installations.extend(
            [
                root / "steamapps" / "common" / "Synth Riders",
                root / "kluge-interactive-synth-riders",
                root / "kluge-interactive-synthriders",
            ]
        )

    unique: list[Path] = []
    seen: set[str] = set()
    for path in installations:
        normalized = os.path.normcase(str(path.resolve()))
        if normalized in seen or not path.is_dir():
            continue
        seen.add(normalized)
        try:
            resolve_pc_unity_source(path)
        except PlaylistVisualImportError:
            continue
        unique.append(path.resolve())
    return unique
