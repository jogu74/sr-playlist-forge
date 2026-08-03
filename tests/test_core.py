from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import extract_song_names
from scripts import backup_source
import synth_playlist_editor as core


class FakeResponse:
    def __init__(self, payload: bytes, content_type: str = "application/json") -> None:
        self.payload = payload
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(payload)),
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.payload if size < 0 else self.payload[:size]

    def geturl(self) -> str:
        return "https://example.test/download"


class FakeVariable:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class FakeBrowserTree:
    def __init__(self) -> None:
        self.rows = {
            "0": {"values": ("", "First"), "tags": ("browser_even_row",)},
            "1": {"values": ("", "Second"), "tags": ("browser_odd_row",)},
        }
        self.selected = ("1",)
        self.focused = "1"
        self.scroll = (0.42, 0.82)
        self.restored_scroll: float | None = None

    def yview(self):
        return self.scroll

    def get_children(self):
        return tuple(self.rows)

    def selection(self):
        return self.selected

    def selection_set(self, item_ids) -> None:
        self.selected = tuple(item_ids)

    def focus(self, item_id: str | None = None):
        if item_id is None:
            return self.focused
        self.focused = item_id

    def item(self, item_id: str, option: str | None = None, **kwargs):
        if option is not None:
            return self.rows[item_id][option]
        self.rows[item_id].update(kwargs)

    def yview_moveto(self, position: float) -> None:
        self.restored_scroll = position


class CoreSafetyTests(unittest.TestCase):
    def test_current_patch_version(self) -> None:
        self.assertEqual(core.APP_VERSION, "3.0.0")

    def test_mass_delete_confirmation_does_not_include_filenames(self) -> None:
        message = core.deletion_confirmation_message("possible orphan songs", 53)
        self.assertIn("53 possible orphan songs", message)
        self.assertIn("cannot be undone", message.lower())
        self.assertNotIn(".synth", message)
        self.assertLess(len(message), 180)

    def test_orphan_scan_classifies_cached_and_filename_matches_first(self) -> None:
        files = [
            "101-Already-Known.synth",
            "202-Cached-Orphan.synth",
            "303-Artist-Long-Distinctive-Title-Mapper.synth",
            "mystery.synth",
        ]
        details = {
            files[0]: core.HeadsetSongIdentity(
                file_name=files[0],
                song_hash="IN-PLAYLIST",
            ),
            files[1]: core.HeadsetSongIdentity(
                file_name=files[1],
                beatmap_id="202",
            ),
        }
        playlist_song = core.SongEntry(
            hash="",
            name="Long Distinctive Title",
            author="Artist",
        )
        statuses, unresolved = core.classify_known_headset_song_statuses(
            files,
            details,
            {"in-playlist"},
            [playlist_song],
            {"202": "not-in-playlist"},
            {},
        )
        self.assertEqual(statuses[files[0]], "In playlist")
        self.assertEqual(statuses[files[1]], "Possibly orphan")
        self.assertEqual(statuses[files[2]], "In playlist")
        self.assertEqual(unresolved, [files[3]])

    def test_stale_orphan_scan_progress_is_ignored(self) -> None:
        class FakeDialog:
            orphan_scan_generation = 4

            def __init__(self) -> None:
                self.updates: list[tuple[int, int, str]] = []

            def update_orphan_progress(self, completed: int, total: int, phase: str) -> None:
                self.updates.append((completed, total, phase))

        dialog = FakeDialog()
        core.QuestSongManagerDialog.publish_orphan_progress(
            dialog,
            3,
            10,
            20,
            "Old scan",
        )
        core.QuestSongManagerDialog.publish_orphan_progress(
            dialog,
            4,
            11,
            20,
            "Current scan",
        )
        self.assertEqual(dialog.updates, [(11, 20, "Current scan")])

    def test_saved_table_column_widths_are_validated_per_table(self) -> None:
        self.assertEqual(
            core.validated_table_column_widths(
                {
                    "name": 321,
                    "artist": "180",
                    "unknown": 500,
                    "mapper": -1,
                    "difficulty": 5001,
                    "selected": True,
                },
                ("name", "artist", "mapper", "difficulty", "selected"),
            ),
            {"name": 321, "artist": 180},
        )

    def test_table_column_widths_are_saved_by_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "columns.json"
            with patch.object(core, "table_column_widths_file_path", return_value=settings_path):
                core._TABLE_COLUMN_WIDTHS_CACHE = None
                core.save_table_column_widths("playlist_editor", {"name": 300})
                core.save_table_column_widths("list_browser", {"title": 250})
                core._TABLE_COLUMN_WIDTHS_CACHE = None
                loaded = core.load_table_column_widths()
        core._TABLE_COLUMN_WIDTHS_CACHE = None
        self.assertEqual(loaded["playlist_editor"], {"name": 300})
        self.assertEqual(loaded["list_browser"], {"title": 250})

    def test_list_browser_default_dates_show_format_and_full_catalog_range(self) -> None:
        date_from, date_to = core.default_beatmap_date_filter_range(
            datetime(2026, 8, 3, 14, 2, 0)
        )
        self.assertEqual(date_from, "2019-08-20")
        self.assertEqual(date_to, "2026-08-03")
        core.parse_date_filter_range(date_from, date_to)

    def test_curated_playlist_queries_match_official_categories(self) -> None:
        getting_started = dict(core.curated_playlist_query("Getting Started"))
        self.assertEqual(getting_started["limit"], 48)
        self.assertEqual(
            json.loads(getting_started["s"]),
            {"tags.tag.slug": "getting-started"},
        )
        star_mappers = dict(core.curated_playlist_query("Star Mappers"))
        self.assertEqual(
            json.loads(star_mappers["s"]),
            {"auto_playlist_id": {"$startsL": "star-mapper-"}},
        )
        with self.assertRaises(ValueError):
            core.curated_playlist_query("Unknown")

    def test_curated_and_browse_playlist_entries_merge_without_duplicates(self) -> None:
        browse = core.parse_community_playlist_entry({"id": 10, "name": "Shared"})
        curated_a = core.parse_community_playlist_entry({"id": 10, "name": "Shared"})
        curated_b = core.parse_community_playlist_entry({"id": 11, "name": "Only curated"})
        assert browse is not None and curated_a is not None and curated_b is not None
        curated_a.curated_categories = ("Staff Picks",)
        curated_a.in_browse_all = False
        curated_b.curated_categories = ("Events",)
        curated_b.in_browse_all = False
        merged = core.merge_community_playlist_entries([browse], [curated_a, curated_b])
        self.assertEqual([entry.playlist_id for entry in merged], ["10", "11"])
        self.assertTrue(merged[0].in_browse_all)
        self.assertEqual(merged[0].curated_categories, ("Staff Picks",))
        self.assertFalse(merged[1].in_browse_all)
        self.assertTrue(core.community_playlist_matches_view(merged[0], "Browse All", "All curated"))
        self.assertTrue(core.community_playlist_matches_view(merged[0], "Curated", "Staff Picks"))
        self.assertFalse(core.community_playlist_matches_view(merged[1], "Browse All", "All curated"))

    def test_beatmap_entry_reads_published_date_downloads_and_upvotes(self) -> None:
        entry = core.parse_beatmap_list_entry(
            {
                "id": 11720,
                "title": "Firebird",
                "artist": "MDK",
                "mapper": "Raptor",
                "published_at": "2025-02-12T12:34:56Z",
                "download_count": 1234,
                "upvote_count": 87,
            }
        )
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.download_count, 1234)
        self.assertEqual(entry.upvote_count, 87)
        self.assertEqual(entry.uploaded_text[:10], "2025-02-12")

    def test_date_filter_is_inclusive_and_rejects_unknown_dates(self) -> None:
        start, end = core.parse_date_filter_range("2025-02-12", "2026-03-18")
        first_day = datetime.strptime("2025-02-12 00:00:00", "%Y-%m-%d %H:%M:%S").timestamp()
        last_day = datetime.strptime("2026-03-18 23:59:59", "%Y-%m-%d %H:%M:%S").timestamp()
        after = datetime.strptime("2026-03-19 00:00:00", "%Y-%m-%d %H:%M:%S").timestamp()
        self.assertTrue(core.timestamp_matches_date_filter(first_day, start, end))
        self.assertTrue(core.timestamp_matches_date_filter(last_day, start, end))
        self.assertFalse(core.timestamp_matches_date_filter(after, start, end))
        self.assertFalse(core.timestamp_matches_date_filter(0, start, end))

    def test_date_filter_validates_format_and_order(self) -> None:
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            core.parse_date_filter_range("12 feb 2025", "")
        with self.assertRaisesRegex(ValueError, "From date"):
            core.parse_date_filter_range("2026-03-18", "2025-02-12")

    def test_upvote_column_sorts_highest_first_on_first_click(self) -> None:
        browser = object.__new__(core.BeatmapBrowserDialog)
        browser.sort_column = "uploaded"
        browser.sort_desc = True
        browser.refresh_table = Mock()
        browser.on_column_click("upvotes")
        self.assertEqual(browser.sort_column, "upvotes")
        self.assertTrue(browser.sort_desc)
        browser.sort_key = core.BeatmapBrowserDialog.sort_key.__get__(browser)
        row = core.BeatmapListEntry("", "", "", "", "", 0, "", 0, "", 0, {}, upvote_count=42)
        self.assertEqual(browser.sort_key(row), 42)

    def test_clear_all_songs_respects_confirmation(self) -> None:
        editor = object.__new__(core.PlaylistEditorApp)
        editor.songs = [core.SongEntry(hash="a" * 64)]
        editor.confirm_clear_all_songs = Mock(return_value=False)
        editor.refresh_table = Mock()
        editor.clear_all_songs()
        self.assertEqual(len(editor.songs), 1)
        editor.confirm_clear_all_songs = Mock(return_value=True)
        editor.clear_all_songs()
        self.assertEqual(editor.songs, [])
        editor.refresh_table.assert_called_once_with(keep_index=None)

    def test_community_playlist_entry_uses_official_resources(self) -> None:
        entry = core.parse_community_playlist_entry(
            {
                "id": 3139,
                "name": "Golden Core",
                "description": "Rhythm songs",
                "published_at": "2026-07-12T10:30:00Z",
                "download_count": 120,
                "vote_diff": 3,
                "cover_version": 2,
                "user": {"username": "zekses"},
                "download_url": "/api/playlists/3139/download",
                "cover_url": "/api/playlists/3139/cover",
            }
        )
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.playlist_id, "3139")
        self.assertEqual(entry.creator, "zekses")
        self.assertEqual(
            entry.download_url,
            "https://synthriderz.com/api/playlists/3139/download",
        )
        self.assertEqual(
            entry.cover_url,
            "https://synthriderz.com/api/playlists/3139/cover?v=2&size=500",
        )

    def test_community_playlist_document_is_validated_and_bounded(self) -> None:
        entry = core.parse_community_playlist_entry(
            {
                "id": 3139,
                "name": "Golden Core",
                "download_url": "/api/playlists/3139/download",
            }
        )
        assert entry is not None
        raw = json.dumps(
            {
                "namePlaylist": "Golden Core",
                "dataString": [{"hash": "a" * 64, "name": "One"}],
            }
        ).encode("utf-8")
        with patch.object(core, "urlopen", return_value=FakeResponse(raw)):
            payload, downloaded = core.fetch_community_playlist_document(entry)
        self.assertEqual(payload["namePlaylist"], "Golden Core")
        self.assertEqual(downloaded, raw)

    def test_community_playlist_urls_reject_other_hosts_and_http(self) -> None:
        with self.assertRaises(ValueError):
            core.synthriderz_url("https://example.com/api/playlists/1/download")
        with self.assertRaises(ValueError):
            core.synthriderz_url("http://synthriderz.com/api/playlists/1/download")

    def test_window_geometry_keeps_valid_size_and_position(self) -> None:
        self.assertEqual(
            core.constrain_window_geometry("1460x860-1800+120", (-1920, 0, 3840, 1080)),
            "1460x860-1800+120",
        )

    def test_window_geometry_recenters_after_monitor_is_disconnected(self) -> None:
        self.assertEqual(
            core.constrain_window_geometry("1460x860+2600+120", (0, 0, 1920, 1080)),
            "1460x860+230+110",
        )

    def test_window_geometry_rejects_invalid_or_too_small_values(self) -> None:
        self.assertIsNone(core.constrain_window_geometry("not geometry", (0, 0, 1920, 1080)))
        self.assertIsNone(core.constrain_window_geometry("200x100+0+0", (0, 0, 1920, 1080)))

    def test_icon_zero_preview_renders_playlist_initial(self) -> None:
        editor = object.__new__(core.PlaylistEditorApp)
        editor.playlist_vars = {
            "gradientTop": FakeVariable("#111111"),
            "gradientDown": FakeVariable("#222222"),
            "SelectedTexture": FakeVariable("0"),
            "colorTexture": FakeVariable("#FFFFFF"),
            "SelectedIconIndex": FakeVariable("0"),
            "colorTitle": FakeVariable("#FFFFFF"),
            "namePlaylist": FakeVariable("August"),
        }
        with (
            patch.object(core.visual_assets, "cached_visual_path", return_value=None),
            patch.object(core.visual_assets, "cached_font_path", return_value=None),
        ):
            preview = editor.build_playlist_visual_preview(240, 180)
        self.assertIsNotNone(preview)
        bright_pixels = [
            pixel
            for pixel in preview.crop((70, 15, 170, 125)).getdata()
            if pixel[0] > 220 and pixel[1] > 220 and pixel[2] > 220
        ]
        self.assertTrue(bright_pixels)

    def test_live_drag_order_uses_tree_row_positions(self) -> None:
        items = ["First", "Second", "Third", "Fourth"]
        self.assertEqual(
            core.reorder_items_by_index_ids(items, ("0", "2", "3", "1")),
            ["First", "Third", "Fourth", "Second"],
        )

    def test_live_drag_order_rejects_incomplete_or_duplicate_rows(self) -> None:
        with self.assertRaises(ValueError):
            core.reorder_items_by_index_ids(["First", "Second"], ("0", "0"))
        with self.assertRaises(ValueError):
            core.reorder_items_by_index_ids(["First", "Second"], ("0",))

    def test_non_adjacent_drag_selection_moves_as_stable_group(self) -> None:
        self.assertEqual(
            core.move_id_group(("A", "B", "C", "D", "E"), ("D", "B"), 3),
            ["A", "C", "E", "B", "D"],
        )
        self.assertEqual(
            core.move_id_group(("A", "B", "C", "D", "E"), ("B", "D"), 0),
            ["B", "D", "A", "C", "E"],
        )

    def test_group_drag_rejects_invalid_selection(self) -> None:
        with self.assertRaises(ValueError):
            core.move_id_group(("A", "B"), (), 0)
        with self.assertRaises(ValueError):
            core.move_id_group(("A", "B"), ("B", "B"), 0)

    def test_list_browser_status_updates_without_rebuilding_or_losing_position(self) -> None:
        browser = object.__new__(core.BeatmapBrowserDialog)
        browser.tree = FakeBrowserTree()
        browser._visible_rows = [False, True]
        browser.can_update_ui = lambda: True
        browser.row_playlist_match_kind = lambda row: "exact" if row else ""

        browser.update_playlist_status_rows()

        self.assertEqual(browser.tree.rows["0"]["values"][0], "")
        self.assertEqual(browser.tree.rows["1"]["values"][0], "✓ In playlist")
        self.assertEqual(browser.tree.rows["1"]["tags"], ("browser_existing_row",))
        self.assertEqual(browser.tree.selected, ("1",))
        self.assertEqual(browser.tree.focused, "1")
        self.assertEqual(browser.tree.restored_scroll, 0.42)

    def test_browsers_distinguish_exact_map_from_same_track(self) -> None:
        songs = [
            core.SongEntry(
                hash="EXACT-HASH",
                name="Firebird",
                author="MDK ft. Nick Sadler",
                beatmapId="11720",
            )
        ]
        hashes, beatmap_ids = core.playlist_identity_sets(songs)
        tracks = core.playlist_track_identity_set(songs)
        exact_row = core.BeatmapListEntry(
            "11720", "Firebird", "MDK ft. Nick Sadler", "Mapper A", "", 0, "", 0, "", 0, {"hash": "other"}
        )
        same_track_row = core.BeatmapListEntry(
            "8937", "Firebird", "MDK ft. Nick Sadler", "Mapper B", "", 0, "", 0, "", 0, {"hash": "different"}
        )
        unrelated_row = core.BeatmapListEntry(
            "42", "Another Song", "Another Artist", "Mapper C", "", 0, "", 0, "", 0, {"hash": "third"}
        )

        self.assertEqual(core.beatmap_playlist_match_kind(exact_row, hashes, beatmap_ids, tracks), "exact")
        self.assertEqual(core.beatmap_playlist_match_kind(same_track_row, hashes, beatmap_ids, tracks), "track")
        self.assertEqual(core.beatmap_playlist_match_kind(unrelated_row, hashes, beatmap_ids, tracks), "")

    def test_track_identity_normalizes_case_spacing_and_punctuation(self) -> None:
        self.assertEqual(
            core.normalized_track_identity("  Cap'n  Morgan's Revenge ", "MDK"),
            core.normalized_track_identity("CAP N MORGAN S REVENGE", "mdk"),
        )

    def test_visual_option_arrows_wrap_at_valid_bounds(self) -> None:
        self.assertEqual(core.wrapped_option_index("20", 1, 21), 0)
        self.assertEqual(core.wrapped_option_index("0", -1, 21), 20)
        self.assertEqual(core.wrapped_option_index("11", 1, 12), 0)
        self.assertEqual(core.wrapped_option_index("invalid", -1, 12), 11)
        with self.assertRaises(ValueError):
            core.wrapped_option_index("0", 1, 0)

    def test_playlist_number_comes_from_source_name(self) -> None:
        self.assertEqual(core.playlist_number_from_source_name("000042__favorites.playlist"), "42")
        self.assertIsNone(core.playlist_number_from_source_name("favorites.playlist"))

    def test_next_quest_playlist_number_uses_highest_valid_prefix(self) -> None:
        self.assertEqual(
            core.next_playlist_number_from_names(
                [
                    "000002__halloween.playlist",
                    "000017__Aug2026.playlist",
                    "000009__jan26.playlist",
                    "cover.png",
                    "42_single_underscore.playlist",
                    "not-numbered.playlist",
                ]
            ),
            18,
        )
        self.assertEqual(core.next_playlist_number_from_names([]), 1)

    def test_next_quest_playlist_number_rejects_exhausted_range(self) -> None:
        with self.assertRaises(ValueError):
            core.next_playlist_number_from_names(["999999__last.playlist"])

    def test_playlist_reorder_preserves_existing_number_slots(self) -> None:
        original = (
            "000002__A.playlist",
            "000005__B.playlist",
            "000009__C.playlist",
            "000014__D.playlist",
        )
        plan = core.build_playlist_reorder_plan(
            original,
            (
                "000014__D.playlist",
                "000002__A.playlist",
                "000005__B.playlist",
                "000009__C.playlist",
            ),
        )
        self.assertEqual(
            [action.target_name for action in plan],
            [
                "000002__D.playlist",
                "000005__A.playlist",
                "000009__B.playlist",
                "000014__C.playlist",
            ],
        )
        self.assertEqual([action.assigned_number for action in plan], [2, 5, 9, 14])

    def test_playlist_reorder_can_compact_numbering_explicitly(self) -> None:
        original = ("000002__A.playlist", "000009__B.playlist")
        plan = core.build_playlist_reorder_plan(original, original, compact=True)
        self.assertEqual(
            [action.target_name for action in plan],
            ["000001__A.playlist", "000002__B.playlist"],
        )

    def test_playlist_reorder_rejects_invalid_or_duplicate_slots(self) -> None:
        with self.assertRaises(ValueError):
            core.build_playlist_reorder_plan(
                ("A.playlist", "000002__B.playlist"),
                ("A.playlist", "000002__B.playlist"),
            )
        with self.assertRaises(ValueError):
            core.build_playlist_reorder_plan(
                ("000002__A.playlist", "02__B.playlist"),
                ("000002__A.playlist", "02__B.playlist"),
            )

    def test_playlist_items_ignore_malformed_entries(self) -> None:
        payload = {"dataString": [{"hash": "ABC"}, "bad", None, 12]}
        items = core.playlist_song_items(payload)
        self.assertEqual(items, [{"hash": "ABC"}])
        self.assertEqual(core.song_entry_from_playlist_item(items[0]).hash, "ABC")

    def test_hashes_are_case_insensitive(self) -> None:
        self.assertEqual(core.normalized_song_hash(" AbCd "), "abcd")

    def test_remote_urls_must_use_http(self) -> None:
        self.assertEqual(core.validated_http_url("https://example.test/a"), "https://example.test/a")
        for unsafe in (
            "file:///tmp/map.synth",
            "ftp://example.test/map.synth",
            "https://user:secret@example.test/map.synth",
            "not a url",
        ):
            with self.subTest(url=unsafe):
                with self.assertRaises(ValueError):
                    core.validated_http_url(unsafe)

    def test_limited_response_rejects_oversized_content(self) -> None:
        response = FakeResponse(b"x" * 11, content_type="application/octet-stream")
        with self.assertRaises(RuntimeError):
            core.read_limited_response(response, 10)

    def test_atomic_write_replaces_complete_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "session.json"
            core.atomic_write_text(target, "old")
            core.atomic_write_text(target, "new")
            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_download_url_cycle_is_bounded(self) -> None:
        responses = {
            "https://example.test/a": {"downloadUrl": "https://example.test/b"},
            "https://example.test/b": {"downloadUrl": "https://example.test/a"},
        }
        calls: list[str] = []

        def fake_urlopen(request, timeout=0):
            url = request.full_url
            calls.append(url)
            return FakeResponse(json.dumps(responses[url]).encode("utf-8"))

        song = core.SongEntry(hash="", downloadUrl="https://example.test/a")
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(core, "urlopen", side_effect=fake_urlopen):
                with self.assertRaises(RuntimeError):
                    core.download_song_to_dir(song, Path(temp_dir))
        self.assertEqual(calls, ["https://example.test/a", "https://example.test/b"])

    def test_merge_playlist_uses_source_name_and_skips_bad_items(self) -> None:
        class FakeEditor:
            songs: list[core.SongEntry] = []
            playlist_vars = {
                key: FakeVariable()
                for key in (
                    "namePlaylist",
                    "description",
                    "SelectedIconIndex",
                    "SelectedTexture",
                    "gradientTop",
                    "gradientDown",
                    "colorTitle",
                    "colorTexture",
                    "creationDate",
                    "playlistNumber",
                )
            }

            def set_creation_date_timestamp(self, timestamp: int, *, auto_managed: bool) -> None:
                self.playlist_vars["creationDate"].set(str(timestamp))

            def refresh_table(self, keep_index=None) -> None:
                self.keep_index = keep_index

        editor = FakeEditor()
        editor.hash_exists = core.PlaylistEditorApp.hash_exists.__get__(editor, FakeEditor)
        payload = {
            "namePlaylist": "Imported",
            "dataString": [{"hash": "ABC", "name": "One"}, "bad"],
        }
        with patch.object(core.messagebox, "showinfo"):
            core.PlaylistEditorApp.merge_playlist_payload(
                editor,
                payload,
                "000042__imported.playlist",
            )
        self.assertEqual(editor.playlist_vars["playlistNumber"].get(), "42")
        self.assertEqual([song.name for song in editor.songs], ["One"])


class ExtractSongNamesTests(unittest.TestCase):
    def test_extract_ignores_non_object_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            playlist = Path(temp_dir) / "test.playlist"
            playlist.write_text(
                json.dumps({"dataString": [{"name": "One"}, "bad", {"name": "Two"}]}),
                encoding="utf-8",
            )
            self.assertEqual(extract_song_names.extract_song_names(playlist), ["One", "Two"])

    def test_extract_rejects_invalid_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            playlist = Path(temp_dir) / "test.playlist"
            playlist.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                extract_song_names.extract_song_names(playlist)


class BackupSourceTests(unittest.TestCase):
    def test_backup_is_versioned_verified_and_non_recursive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "synth_playlist_editor.py").write_text('APP_VERSION = "9.8.7"\n', encoding="utf-8")
            (root / "feature.py").write_text("value = 1\n", encoding="utf-8")
            (root / "backups" / "old").mkdir(parents=True)
            (root / "backups" / "old" / "ignored.py").write_text("ignored = True\n", encoding="utf-8")
            created = backup_source.create_backup(root, "before test")
            manifest = json.loads((created / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], "9.8.7")
            self.assertEqual(manifest["fileCount"], 2)
            self.assertTrue((created / "feature.py").exists())
            self.assertFalse((created / "backups").exists())


if __name__ == "__main__":
    unittest.main()
