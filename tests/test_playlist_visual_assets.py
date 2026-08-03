from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import playlist_visual_assets as visuals


class FakeImage:
    def convert(self, _mode: str):
        return self

    def save(self, path: Path) -> None:
        Path(path).write_bytes(b"fake-png")


class FakeObject:
    def __init__(self, name: str) -> None:
        self.name = name
        self.type = SimpleNamespace(name="Sprite")

    def peek_name(self) -> str:
        return self.name

    def read(self, check_read: bool = False):
        return SimpleNamespace(image=FakeImage())


class FakeFontObject:
    type = SimpleNamespace(name="Font")

    def peek_name(self) -> str:
        return visuals.PLAYLIST_INITIAL_FONT_NAME

    def read(self, check_read: bool = False):
        return SimpleNamespace(m_FontData=b"\x00\x01\x00\x00fake-font-data")


class PlaylistVisualAssetTests(unittest.TestCase):
    def test_game_index_maps_match_serialized_option_counts(self) -> None:
        self.assertEqual(len(visuals.ICON_INDEX_NAMES), 21)
        self.assertIsNone(visuals.ICON_INDEX_NAMES[0])
        self.assertEqual(visuals.ICON_INDEX_NAMES[1], "CustomProfile-01")
        self.assertEqual(visuals.ICON_INDEX_NAMES[20], "CustomProfile-20")
        self.assertEqual(len(visuals.TEXTURE_INDEX_NAMES), 12)
        self.assertIsNone(visuals.TEXTURE_INDEX_NAMES[1])

    def test_resolve_pc_game_and_data_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir) / "Synth Riders"
            data_dir = game_dir / "SynthRiders_Data"
            data_dir.mkdir(parents=True)
            (data_dir / "sharedassets2.assets").write_bytes(b"asset")
            self.assertEqual(visuals.resolve_pc_unity_source(game_dir), data_dir.resolve())
            self.assertEqual(visuals.resolve_pc_unity_source(data_dir), data_dir.resolve())

    def test_local_obb_extraction_uses_only_required_members(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "main.1.com.kluge.SynthRiders.obb"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
                for index, member in enumerate(visuals.QUEST_UNITY_ENTRIES, start=1):
                    archive.writestr(member, bytes([index]) * index)
                archive.writestr("unrelated.bin", b"do not extract")
            destination = root / "unity"
            source = visuals.prepare_local_obb_source(archive_path, destination)
            self.assertEqual(source, destination / "data.unity3d")
            self.assertEqual(
                sorted(path.name for path in destination.iterdir()),
                sorted(Path(member).name for member in visuals.QUEST_UNITY_ENTRIES),
            )

    def test_import_builds_complete_versioned_cache(self) -> None:
        objects = [
            FakeObject(name)
            for name in (*visuals.ICON_NAMES, *visuals.TEXTURE_NAMES)
        ]
        objects.append(FakeFontObject())
        reader = SimpleNamespace(disposed=False)
        reader.dispose = lambda: setattr(reader, "disposed", True)
        environment = SimpleNamespace(objects=objects, files={}, cabs={"fixture": reader})
        fake_unitypy = SimpleNamespace(load=lambda _source: environment)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(visuals, "_load_unitypy", return_value=fake_unitypy):
                result = visuals.import_unity_visuals(
                    root / "data.unity3d",
                    root / "cache",
                    source_kind="test",
                    source_label="fixture",
                )
            self.assertEqual(result.icon_count, 21)
            self.assertEqual(result.texture_count, 12)
            loaded = visuals.load_current_manifest(root / "cache")
            self.assertIsNotNone(loaded)
            import_dir, manifest = loaded or (Path(), {})
            self.assertEqual(len(manifest["icons"]), 21)
            self.assertEqual(len(manifest["textures"]), 12)
            self.assertEqual(manifest["schemaVersion"], 2)
            self.assertTrue((import_dir / manifest["icons"]["0"]).is_file())
            self.assertTrue((import_dir / manifest["icons"]["1"]).is_file())
            self.assertNotEqual(
                (import_dir / manifest["icons"]["0"]).read_bytes(),
                (import_dir / manifest["icons"]["1"]).read_bytes(),
            )
            self.assertTrue((import_dir / manifest["textures"]["1"]).is_file())
            self.assertEqual(
                visuals.cached_font_path(root / "cache").read_bytes(),
                b"\x00\x01\x00\x00fake-font-data",
            )
            self.assertTrue(reader.disposed)

    def test_cached_path_rejects_manifest_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            import_dir = root / "import-20260731T000000Z-deadbeef"
            import_dir.mkdir()
            (root / "outside.png").write_bytes(b"x")
            (root / "current.json").write_text(
                json.dumps({"schemaVersion": 1, "importId": import_dir.name}),
                encoding="utf-8",
            )
            (import_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "icons": {"0": "../outside.png"},
                        "textures": {},
                    }
                ),
                encoding="utf-8",
            )
            self.assertIsNone(visuals.cached_visual_path(root, "icons", 0))

    def test_find_quest_obb_prefers_highest_main_version(self) -> None:
        completed = SimpleNamespace(
            returncode=0,
            stdout=(
                "patch.1200.com.kluge.SynthRiders.obb\n"
                "main.1144.com.kluge.SynthRiders.obb\n"
                "main.1200.com.kluge.SynthRiders.obb\n"
                "unexpected.obb\n"
            ),
            stderr="",
        )
        with patch.object(visuals, "_run_adb", return_value=completed):
            self.assertEqual(
                visuals.find_quest_obb("adb"),
                f"{visuals.QUEST_OBB_DIR}/main.1200.com.kluge.SynthRiders.obb",
            )

    def test_steam_library_parser_unescapes_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vdf = Path(temp_dir) / "libraryfolders.vdf"
            vdf.write_text(
                '"0" { "path" "C:\\\\Program Files (x86)\\\\Steam" }\n'
                '"1" { "path" "E:\\\\SteamLibrary" }\n',
                encoding="utf-8",
            )
            self.assertEqual(
                visuals._parse_steam_library_paths(vdf),
                [Path(r"C:\Program Files (x86)\Steam"), Path(r"E:\SteamLibrary")],
            )


if __name__ == "__main__":
    unittest.main()
