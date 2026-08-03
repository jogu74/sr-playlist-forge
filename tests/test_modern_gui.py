from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import modern_gui
import synth_playlist_editor as core


class FakeVariable:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class FakeButton:
    def __init__(self) -> None:
        self.options: dict[str, str] = {}

    def configure(self, **options: str) -> None:
        self.options.update(options)


class ModernGuiHelperTests(unittest.TestCase):
    def test_normalized_hex_color_accepts_valid_and_uses_fallback(self) -> None:
        self.assertEqual(modern_gui.normalized_hex_color("#8b5cf6"), "#8B5CF6")
        self.assertEqual(modern_gui.normalized_hex_color("invalid", "#123456"), "#123456")

    def test_hex_color_channels_round_trip(self) -> None:
        color = "#22D3EE"
        self.assertEqual(
            modern_gui.channels_hex_color(*modern_gui.hex_color_channels(color)),
            color,
        )

    def test_channels_hex_color_clamps_out_of_range_values(self) -> None:
        self.assertEqual(modern_gui.channels_hex_color(-20, 128, 999), "#0080FF")

    def test_responsive_wrap_width_uses_available_space_and_minimum(self) -> None:
        self.assertEqual(
            modern_gui.responsive_wrap_width(
                1200,
                reserved_width=440,
                horizontal_padding=96,
                minimum=260,
            ),
            664,
        )
        self.assertEqual(
            modern_gui.responsive_wrap_width(
                500,
                reserved_width=440,
                horizontal_padding=96,
                minimum=260,
            ),
            260,
        )

    def test_all_supported_message_dialog_kinds_have_visual_specs(self) -> None:
        self.assertEqual(
            set(modern_gui.ModernMessageDialog.SPECS),
            {"info", "error", "question"},
        )

    def test_modern_quest_playlist_manager_reuses_core_operations(self) -> None:
        self.assertTrue(
            issubclass(
                modern_gui.ModernQuestPlaylistManagerDialog,
                core.QuestPlaylistManagerDialog,
            )
        )

    def test_modern_quest_song_manager_reuses_core_operations(self) -> None:
        self.assertTrue(
            issubclass(
                modern_gui.ModernQuestSongManagerDialog,
                core.QuestSongManagerDialog,
            )
        )
        self.assertEqual(
            set(modern_gui.ModernQuestSongManagerDialog.COLUMN_LABELS),
            {"filename", "artist", "mapper", "status"},
        )

    def test_finished_quest_number_lookup_updates_number_and_button(self) -> None:
        class FakeEditor:
            quest_number_lookup_in_progress = True
            next_quest_number_button = FakeButton()
            quest_number_status_var = FakeVariable()
            playlist_vars = {"playlistNumber": FakeVariable("7")}

        editor = FakeEditor()
        modern_gui.ModernPlaylistEditorApp._finish_next_quest_playlist_number(
            editor,
            18,
            None,
        )
        self.assertFalse(editor.quest_number_lookup_in_progress)
        self.assertEqual(editor.playlist_vars["playlistNumber"].get(), "18")
        self.assertEqual(editor.next_quest_number_button.options["state"], "normal")
        self.assertIn("18", editor.quest_number_status_var.get())

    def test_playlist_reorder_executes_backup_then_two_phase_rename(self) -> None:
        editor = object.__new__(modern_gui.ModernQuestPlaylistManagerDialog)
        editor.adb_path = "adb"
        editor.playlist_dir = "/quest/playlists"
        actions = [
            core.PlaylistRenameAction("000002__A.playlist", "000002__B.playlist", 2),
            core.PlaylistRenameAction("000005__B.playlist", "000005__A.playlist", 5),
        ]
        pull = Mock()
        move = Mock()
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(core, "app_support_dir", return_value=Path(temp_dir)),
                patch.object(core, "adb_pull_file", pull),
                patch.object(core, "adb_move_file", move),
            ):
                backup_dir = editor._execute_playlist_rename_plan(actions)
        self.assertEqual(pull.call_count, 2)
        self.assertEqual(move.call_count, 4)
        self.assertIn("playlist-reorder-backups", str(backup_dir))
        first_phase_targets = [call.args[2] for call in move.call_args_list[:2]]
        self.assertTrue(all(".__srpf_reorder_" in target for target in first_phase_targets))
        self.assertEqual(
            [call.args[2] for call in move.call_args_list[2:]],
            ["/quest/playlists/000002__B.playlist", "/quest/playlists/000005__A.playlist"],
        )

    def test_playlist_reorder_attempts_rollback_after_rename_failure(self) -> None:
        editor = object.__new__(modern_gui.ModernQuestPlaylistManagerDialog)
        editor.adb_path = "adb"
        editor.playlist_dir = "/quest/playlists"
        actions = [
            core.PlaylistRenameAction("000002__A.playlist", "000002__B.playlist", 2),
            core.PlaylistRenameAction("000005__B.playlist", "000005__A.playlist", 5),
        ]
        moves: list[tuple[str, str]] = []

        def move_with_failure(_adb: str, source: str, target: str) -> None:
            moves.append((source, target))
            if len(moves) == 3:
                raise RuntimeError("simulated rename failure")

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(core, "app_support_dir", return_value=Path(temp_dir)),
                patch.object(core, "adb_pull_file"),
                patch.object(core, "adb_move_file", side_effect=move_with_failure),
            ):
                with self.assertRaisesRegex(RuntimeError, "original filenames were restored"):
                    editor._execute_playlist_rename_plan(actions)
        rollback_targets = [target for _source, target in moves[3:]]
        self.assertEqual(
            rollback_targets,
            ["/quest/playlists/000005__B.playlist", "/quest/playlists/000002__A.playlist"],
        )


if __name__ == "__main__":
    unittest.main()
