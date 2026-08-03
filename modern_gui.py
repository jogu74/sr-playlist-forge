#!/usr/bin/env python3
"""Modern SR Playlist Forge interface."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk

import synth_playlist_editor as core


BG = "#0A0C10"
RAIL = "#10131A"
SURFACE = "#151922"
SURFACE_RAISED = "#1B202C"
SURFACE_SOFT = "#11151D"
BORDER = "#282E3D"
TEXT = "#F5F7FB"
MUTED = "#969EAF"
ACCENT = "#8B5CF6"
ACCENT_HOVER = "#7C3AED"
CYAN = "#22D3EE"
DANGER = "#EF476F"
SUCCESS = "#34D399"
MAX_IN_MEMORY_COVERS = 160
_MESSAGEBOX_OWNER: tk.Misc | None = None
_NATIVE_SHOWINFO = core.messagebox.showinfo
_NATIVE_SHOWERROR = core.messagebox.showerror
_NATIVE_ASKYESNO = core.messagebox.askyesno


def normalized_hex_color(value: str, fallback: str = "#FFFFFF") -> str:
    candidate = str(value or "").strip().upper()
    if core.re.fullmatch(r"#[0-9A-F]{6}", candidate):
        return candidate
    return fallback


def hex_color_channels(value: str) -> tuple[int, int, int]:
    normalized = normalized_hex_color(value)
    return tuple(int(normalized[index : index + 2], 16) for index in (1, 3, 5))


def channels_hex_color(red: int, green: int, blue: int) -> str:
    channels = (red, green, blue)
    return "#" + "".join(f"{max(0, min(255, int(channel))):02X}" for channel in channels)


def responsive_wrap_width(
    container_width: int,
    *,
    reserved_width: int = 0,
    horizontal_padding: int = 0,
    minimum: int = 180,
) -> int:
    return max(minimum, int(container_width) - int(reserved_width) - int(horizontal_padding))


class ModernMessageDialog(core.BASE_DIALOG_CLASS):
    """Shared modern replacement for information, error, and question message boxes."""

    SPECS = {
        "info": ("NOTICE", "i", CYAN, "#12313A"),
        "error": ("ACTION REQUIRED", "!", DANGER, "#3A1824"),
        "question": ("CONFIRMATION", "?", ACCENT, "#2A1F4A"),
    }

    def __init__(self, parent: tk.Misc, kind: str, title: str, message: str):
        super().__init__(parent)
        ctk = core.ctk
        assert ctk is not None
        eyebrow, glyph, emphasis, glyph_bg = self.SPECS.get(kind, self.SPECS["info"])
        self.result = False
        self.kind = kind
        self.title(f"SR Playlist Forge — {title}")
        core.apply_app_window_icon(self)
        self.geometry("560x270")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        root = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        root.pack(fill="both", expand=True, padx=24, pady=22)
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            root,
            text=eyebrow,
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")

        card = ctk.CTkFrame(
            root,
            fg_color=SURFACE,
            corner_radius=14,
            border_width=1,
            border_color=BORDER if kind == "info" else emphasis,
        )
        card.grid(row=1, column=0, sticky="nsew", pady=(8, 14))
        card.grid_columnconfigure(1, weight=1)
        card.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            card,
            text=glyph,
            width=52,
            height=52,
            corner_radius=26,
            fg_color=glyph_bg,
            text_color=emphasis,
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, rowspan=2, padx=(18, 14), pady=20, sticky="n")
        ctk.CTkLabel(
            card,
            text=str(title),
            text_color=TEXT,
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="sw", padx=(0, 18), pady=(20, 3))
        ctk.CTkLabel(
            card,
            text=str(message),
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
            justify="left",
            anchor="nw",
            wraplength=405,
        ).grid(row=1, column=1, sticky="nw", padx=(0, 18), pady=(2, 20))

        buttons = ctk.CTkFrame(root, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew")
        if kind == "question":
            cancel_button = ctk.CTkButton(
                buttons,
                text="No",
                command=self.cancel,
                width=108,
                height=38,
                fg_color=SURFACE_RAISED,
                hover_color=BORDER,
                border_width=1,
                border_color=BORDER,
                text_color=TEXT,
            )
            cancel_button.pack(side="right")
            ctk.CTkButton(
                buttons,
                text="Yes",
                command=self.confirm,
                width=108,
                height=38,
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
                text_color="#FFFFFF",
                font=ctk.CTkFont(weight="bold"),
            ).pack(side="right", padx=(0, 8))
            self.after(50, cancel_button.focus_set)
        else:
            ok_button = ctk.CTkButton(
                buttons,
                text="OK",
                command=self.confirm,
                width=108,
                height=38,
                fg_color=ACCENT if kind == "info" else DANGER,
                hover_color=ACCENT_HOVER if kind == "info" else "#B83258",
                text_color="#FFFFFF",
                font=ctk.CTkFont(weight="bold"),
            )
            ok_button.pack(side="right")
            self.after(50, ok_button.focus_set)

        self.bind("<Escape>", lambda _event: self.cancel())
        self.bind("<Return>", lambda _event: self.confirm())
        self.after(20, self.center_over_parent)
        self.grab_set()

    def center_over_parent(self) -> None:
        try:
            self.update_idletasks()
            parent = self.master
            x = parent.winfo_rootx() + max(0, (parent.winfo_width() - self.winfo_width()) // 2)
            y = parent.winfo_rooty() + max(0, (parent.winfo_height() - self.winfo_height()) // 2)
            self.geometry(f"+{x}+{y}")
        except (tk.TclError, AttributeError):
            pass

    def confirm(self) -> None:
        self.result = True
        self.destroy()

    def cancel(self) -> None:
        self.result = False
        self.destroy()


def _show_modern_message(kind: str, title: str, message: str, **options: object) -> bool:
    parent = options.get("parent") or _MESSAGEBOX_OWNER
    if (
        parent is None
        or not core.HAS_CUSTOMTKINTER
        or core.ctk is None
    ):
        if kind == "error":
            return bool(_NATIVE_SHOWERROR(title, message, **options))
        if kind == "question":
            return bool(_NATIVE_ASKYESNO(title, message, **options))
        return bool(_NATIVE_SHOWINFO(title, message, **options))
    try:
        dialog = ModernMessageDialog(parent, kind, str(title), str(message))
        parent.wait_window(dialog)
        return dialog.result
    except (tk.TclError, RuntimeError):
        if kind == "error":
            return bool(_NATIVE_SHOWERROR(title, message, **options))
        if kind == "question":
            return bool(_NATIVE_ASKYESNO(title, message, **options))
        return bool(_NATIVE_SHOWINFO(title, message, **options))


def install_modern_messageboxes(owner: tk.Misc) -> None:
    global _MESSAGEBOX_OWNER
    _MESSAGEBOX_OWNER = owner
    core.messagebox.showinfo = lambda title, message, **options: (
        "ok" if _show_modern_message("info", title, message, **options) else "ok"
    )
    core.messagebox.showerror = lambda title, message, **options: (
        "ok" if _show_modern_message("error", title, message, **options) else "ok"
    )
    core.messagebox.askyesno = lambda title, message, **options: _show_modern_message(
        "question", title, message, **options
    )


class ModernColorDialog(core.BASE_DIALOG_CLASS):
    """Compact RGB and hexadecimal color picker for playlist artwork."""

    def __init__(self, parent: tk.Misc, title: str, initial: str):
        super().__init__(parent)
        ctk = core.ctk
        assert ctk is not None
        self.result: str | None = None
        self._updating = False
        red, green, blue = hex_color_channels(initial)
        self.channel_vars = {
            "R": tk.IntVar(value=red),
            "G": tk.IntVar(value=green),
            "B": tk.IntVar(value=blue),
        }
        self.hex_var = tk.StringVar(value=channels_hex_color(red, green, blue))

        self.title("SR Playlist Forge — Color")
        core.apply_app_window_icon(self)
        self.geometry("560x520")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        root = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        root.pack(fill="both", expand=True, padx=24, pady=22)
        ctk.CTkLabel(
            root, text="PLAYLIST COLOR", text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"), anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(
            root, text=title, text_color=TEXT,
            font=ctk.CTkFont(size=22, weight="bold"), anchor="w",
        ).pack(fill="x", pady=(3, 14))

        self.preview = ctk.CTkFrame(
            root, height=92, fg_color=self.hex_var.get(), corner_radius=14,
            border_width=1, border_color=BORDER,
        )
        self.preview.pack(fill="x", pady=(0, 14))
        self.preview.pack_propagate(False)
        self.preview_label = ctk.CTkLabel(
            self.preview, text=self.hex_var.get(), text_color="#FFFFFF",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self.preview_label.pack(expand=True)

        controls = ctk.CTkFrame(root, fg_color=SURFACE, corner_radius=14, border_width=1, border_color=BORDER)
        controls.pack(fill="both", expand=True)
        controls.grid_columnconfigure(1, weight=1)
        for row, channel in enumerate(("R", "G", "B")):
            ctk.CTkLabel(
                controls, text=channel, width=24, text_color=TEXT,
                font=ctk.CTkFont(weight="bold"),
            ).grid(row=row, column=0, padx=(16, 8), pady=(14 if row == 0 else 8, 8))
            ctk.CTkSlider(
                controls, from_=0, to=255, number_of_steps=255,
                variable=self.channel_vars[channel], command=lambda _value: self.update_from_channels(),
                fg_color=SURFACE_SOFT, progress_color=ACCENT, button_color=ACCENT,
                button_hover_color=ACCENT_HOVER,
            ).grid(row=row, column=1, sticky="ew", padx=(0, 10), pady=(14 if row == 0 else 8, 8))
            ctk.CTkLabel(
                controls, textvariable=self.channel_vars[channel], width=38, text_color=MUTED,
            ).grid(row=row, column=2, padx=(0, 16), pady=(14 if row == 0 else 8, 8))

        hex_row = ctk.CTkFrame(controls, fg_color="transparent")
        hex_row.grid(row=3, column=0, columnspan=3, sticky="ew", padx=16, pady=(6, 14))
        hex_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(hex_row, text="HEX", text_color=MUTED).grid(row=0, column=0, padx=(0, 10))
        hex_entry = ctk.CTkEntry(
            hex_row, textvariable=self.hex_var, height=36, fg_color=SURFACE_SOFT,
            border_color=BORDER, text_color=TEXT,
        )
        hex_entry.grid(row=0, column=1, sticky="ew")
        hex_entry.bind("<KeyRelease>", lambda _event: self.update_from_hex())

        buttons = ctk.CTkFrame(root, fg_color="transparent")
        buttons.pack(fill="x", pady=(14, 0))
        ctk.CTkButton(
            buttons, text="Cancel", command=self.cancel, width=108, height=38,
            fg_color=SURFACE_RAISED, hover_color=BORDER, border_width=1,
            border_color=BORDER, text_color=TEXT,
        ).pack(side="right")
        ctk.CTkButton(
            buttons, text="Use color", command=self.confirm, width=122, height=38,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(weight="bold"),
        ).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda _event: self.cancel())
        self.bind("<Return>", lambda _event: self.confirm())
        self.after(20, self.center_over_parent)
        self.grab_set()

    def center_over_parent(self) -> None:
        try:
            self.update_idletasks()
            parent = self.master
            x = parent.winfo_rootx() + max(0, (parent.winfo_width() - self.winfo_width()) // 2)
            y = parent.winfo_rooty() + max(0, (parent.winfo_height() - self.winfo_height()) // 2)
            self.geometry(f"+{x}+{y}")
        except (tk.TclError, AttributeError):
            pass

    def update_preview(self, color: str) -> None:
        self.preview.configure(fg_color=color)
        self.preview_label.configure(
            text=color,
            text_color="#11151D" if sum(hex_color_channels(color)) > 520 else "#FFFFFF",
        )

    def update_from_channels(self) -> None:
        if self._updating:
            return
        color = channels_hex_color(*(variable.get() for variable in self.channel_vars.values()))
        self._updating = True
        self.hex_var.set(color)
        self._updating = False
        self.update_preview(color)

    def update_from_hex(self) -> None:
        if self._updating:
            return
        candidate = self.hex_var.get().strip().upper()
        if not core.re.fullmatch(r"#[0-9A-F]{6}", candidate):
            return
        self._updating = True
        for channel, value in zip(("R", "G", "B"), hex_color_channels(candidate)):
            self.channel_vars[channel].set(value)
        self._updating = False
        self.update_preview(candidate)

    def confirm(self) -> None:
        candidate = self.hex_var.get().strip().upper()
        if not core.re.fullmatch(r"#[0-9A-F]{6}", candidate):
            core.messagebox.showerror("Invalid Color", "Enter a color as #RRGGBB.", parent=self)
            return
        self.result = candidate
        self.destroy()

    def cancel(self) -> None:
        self.destroy()


class ModernSongEditDialog(core.BASE_DIALOG_CLASS):
    """Modern song metadata editor."""

    def __init__(self, parent: tk.Misc, song: core.SongEntry):
        super().__init__(parent)
        ctk = core.ctk
        assert ctk is not None
        self.result: core.SongEntry | None = None
        self.song = core.SongEntry(**core.asdict(song))
        self.vars = {
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

        self.title("SR Playlist Forge — Edit Song")
        core.apply_app_window_icon(self)
        self.geometry("780x680")
        self.minsize(720, 620)
        self.configure(fg_color=BG)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        root = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        root.pack(fill="both", expand=True, padx=24, pady=22)
        ctk.CTkLabel(
            root, text="SONG METADATA", text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"), anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(
            root, text="Edit song", text_color=TEXT,
            font=ctk.CTkFont(size=24, weight="bold"), anchor="w",
        ).pack(fill="x", pady=(3, 2))
        ctk.CTkLabel(
            root, text="Update the metadata stored in the current playlist.",
            text_color=MUTED, font=ctk.CTkFont(size=12), anchor="w",
        ).pack(fill="x", pady=(0, 14))

        form = ctk.CTkScrollableFrame(
            root, fg_color=SURFACE, corner_radius=14, border_width=1, border_color=BORDER,
        )
        form.pack(fill="both", expand=True)
        form.grid_columnconfigure((0, 1), weight=1, uniform="field")

        field_layout = (
            ("Hash", "hash", 0, 0, 2),
            ("Title", "name", 1, 0, 1),
            ("Artist", "author", 1, 1, 1),
            ("Mapper", "beatmapper", 2, 0, 1),
            ("Difficulty text", "difficultyText", 2, 1, 1),
            ("Difficulty", "difficulty", 3, 0, 1),
            ("Duration (seconds)", "trackDuration", 3, 1, 1),
            ("Added (Unix time)", "addedTime", 4, 0, 1),
            ("Beatmap ID", "beatmapId", 4, 1, 1),
            ("Source URL", "sourceUrl", 5, 0, 2),
            ("Download URL", "downloadUrl", 6, 0, 2),
        )
        for label, key, row, column, span in field_layout:
            cell = ctk.CTkFrame(form, fg_color="transparent")
            cell.grid(
                row=row, column=column, columnspan=span, sticky="ew",
                padx=(14 if column == 0 else 7, 14 if column + span == 2 else 7),
                pady=(12 if row == 0 else 7, 7),
            )
            ctk.CTkLabel(
                cell, text=label.upper(), text_color=MUTED,
                font=ctk.CTkFont(size=9, weight="bold"), anchor="w",
            ).pack(fill="x", pady=(0, 4))
            ctk.CTkEntry(
                cell, textvariable=self.vars[key], height=36,
                fg_color=SURFACE_SOFT, border_color=BORDER, text_color=TEXT,
            ).pack(fill="x")

        buttons = ctk.CTkFrame(root, fg_color="transparent")
        buttons.pack(fill="x", pady=(14, 0))
        cancel_button = ctk.CTkButton(
            buttons, text="Cancel", command=self.destroy, width=108, height=38,
            fg_color=SURFACE_RAISED, hover_color=BORDER, border_width=1,
            border_color=BORDER, text_color=TEXT,
        )
        cancel_button.pack(side="right")
        ctk.CTkButton(
            buttons, text="Save changes", command=self.on_save, width=132, height=38,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(weight="bold"),
        ).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Control-Return>", lambda _event: self.on_save())
        self.after(50, cancel_button.focus_set)
        self.grab_set()

    def on_save(self) -> None:
        song_hash = self.vars["hash"].get().strip()
        if not song_hash:
            core.messagebox.showerror("Invalid Song", "A song hash is required.", parent=self)
            return
        self.result = core.SongEntry(
            hash=song_hash,
            name=self.vars["name"].get(),
            author=self.vars["author"].get(),
            beatmapper=self.vars["beatmapper"].get(),
            difficulty=core.force_int(self.vars["difficulty"].get(), 0),
            difficultyText=self.vars["difficultyText"].get().strip(),
            trackDuration=core.force_float(self.vars["trackDuration"].get(), 0.0),
            addedTime=core.force_int(self.vars["addedTime"].get(), int(core.time.time())),
            beatmapId=self.vars["beatmapId"].get().strip(),
            sourceUrl=self.vars["sourceUrl"].get().strip(),
            downloadUrl=self.vars["downloadUrl"].get().strip(),
        )
        self.destroy()


class ModernQuestSongManagerDialog(core.QuestSongManagerDialog):
    """Modern Quest song library while retaining the proven ADB operations."""

    COLUMN_LABELS = {
        "filename": "SONG FILE",
        "artist": "ARTIST",
        "mapper": "MAPPER",
        "status": "PLAYLIST STATUS",
    }

    def _build_ui(self) -> None:
        ctk = core.ctk
        assert ctk is not None
        self.orphan_progress_hide_after_id: str | None = None
        self.title("SR Playlist Forge - Quest Songs")
        self.geometry("1320x780")
        self.minsize(1060, 650)
        self.configure(fg_color=BG)

        root = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        root.pack(fill="both", expand=True, padx=22, pady=18)

        header = ctk.CTkFrame(root, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)
        title_group = ctk.CTkFrame(header, fg_color="transparent")
        title_group.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_group,
            text="QUEST LIBRARY",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_group,
            text="Songs on Quest",
            text_color=TEXT,
            font=ctk.CTkFont(size=25, weight="bold"),
            anchor="w",
        ).pack(anchor="w", pady=(2, 1))
        ctk.CTkLabel(
            title_group,
            text="Find unused songs, create local backups, and safely clean up headset storage.",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkButton(
            header,
            text="Close",
            command=self.destroy,
            width=88,
            height=36,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
        ).grid(row=0, column=1, sticky="e")

        toolbar = ctk.CTkFrame(
            root,
            fg_color=SURFACE,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        toolbar.pack(fill="x", pady=(0, 10))
        toolbar.grid_columnconfigure(0, weight=1)

        path_group = ctk.CTkFrame(toolbar, fg_color="transparent")
        path_group.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 8))
        ctk.CTkLabel(
            path_group,
            text="HEADSET FOLDER",
            text_color=MUTED,
            font=ctk.CTkFont(size=9, weight="bold"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            path_group,
            text=self.songs_dir,
            text_color=CYAN,
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        filter_group = ctk.CTkFrame(toolbar, fg_color="transparent")
        filter_group.grid(row=0, column=1, sticky="e", padx=16, pady=(12, 8))
        self._quest_song_filter_buttons: dict[str, object] = {}
        for label, value, width in (
            ("All", "all", 76),
            ("Unknown", "unknown", 94),
            ("Possible orphans", "orphan", 132),
        ):
            active = value == self.filter_var.get()
            button = ctk.CTkButton(
                filter_group,
                text=label,
                command=lambda choice=value: self.set_filter(choice),
                width=width,
                height=34,
                fg_color=ACCENT if active else SURFACE_RAISED,
                hover_color=ACCENT_HOVER if active else BORDER,
                border_width=1,
                border_color=ACCENT if active else BORDER,
                text_color="#FFFFFF" if active else TEXT,
            )
            button.pack(side="left", padx=(0, 6))
            self._quest_song_filter_buttons[value] = button
        ctk.CTkButton(
            filter_group,
            text="Refresh",
            command=self.refresh_files,
            width=96,
            height=34,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
        ).pack(side="left")

        search_group = ctk.CTkFrame(toolbar, fg_color="transparent")
        search_group.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            padx=16,
            pady=(0, 12),
        )
        search_group.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            search_group,
            text="SEARCH",
            text_color=MUTED,
            font=ctk.CTkFont(size=9, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))
        search_entry = ctk.CTkEntry(
            search_group,
            textvariable=self.search_var,
            height=36,
            placeholder_text="Filename, artist, mapper, or playlist status",
            fg_color=SURFACE_SOFT,
            border_color=BORDER,
            text_color=TEXT,
            placeholder_text_color=MUTED,
        )
        search_entry.grid(row=0, column=1, sticky="ew")
        self.search_var.trace_add("write", lambda *_: self.render_files())

        table_card = ctk.CTkFrame(
            root,
            fg_color=SURFACE,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        table_card.pack(fill="both", expand=True, pady=(0, 10))
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(1, weight=1)

        table_header = ctk.CTkFrame(table_card, fg_color="transparent")
        table_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))
        table_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            table_header,
            text="HEADSET SONGS",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            table_header,
            text="Click a heading to sort  •  Ctrl+A selects visible rows  •  Delete removes selected songs",
            text_color=MUTED,
            font=ctk.CTkFont(size=10),
            anchor="e",
        ).grid(row=0, column=1, sticky="e")

        table_host = ctk.CTkFrame(table_card, fg_color=SURFACE_SOFT, corner_radius=0)
        table_host.grid(row=1, column=0, sticky="nsew", padx=1, pady=(0, 1))
        table_host.grid_columnconfigure(0, weight=1)
        table_host.grid_rowconfigure(0, weight=1)
        style = ttk.Style(self)
        style.configure(
            "QuestSongs.Treeview",
            background=SURFACE_SOFT,
            fieldbackground=SURFACE_SOFT,
            foreground=TEXT,
            borderwidth=0,
            relief="flat",
            rowheight=34,
            font=("Segoe UI", 10),
        )
        style.configure(
            "QuestSongs.Treeview.Heading",
            background=SURFACE_RAISED,
            foreground=MUTED,
            borderwidth=0,
            relief="flat",
            padding=(10, 9),
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "QuestSongs.Treeview",
            background=[("selected", "#4934B8")],
            foreground=[("selected", "#FFFFFF")],
        )
        style.map(
            "QuestSongs.Treeview.Heading",
            background=[("active", BORDER)],
            foreground=[("active", TEXT)],
        )

        columns = ("filename", "artist", "mapper", "status")
        self.tree = ttk.Treeview(
            table_host,
            columns=columns,
            show="headings",
            selectmode="extended",
            style="QuestSongs.Treeview",
        )
        for column in columns:
            self.tree.heading(
                column,
                text=self.COLUMN_LABELS[column],
                command=lambda selected=column: self.sort_by(selected),
            )
        self.tree.column("filename", anchor="w", width=650, stretch=True)
        self.tree.column("artist", anchor="w", width=190, stretch=True)
        self.tree.column("mapper", anchor="w", width=180, stretch=True)
        self.tree.column("status", anchor="w", width=170, stretch=False)
        core.install_tree_column_width_persistence(
            self.tree,
            "quest_songs",
            columns,
        )
        self.tree.tag_configure(
            "possible_orphan",
            background="#311923",
            foreground="#FDA4AF",
        )
        self.tree.tag_configure(
            "in_playlist",
            background="#102820",
            foreground="#A7F3D0",
        )
        self.tree.tag_configure(
            "unknown",
            background="#272416",
            foreground="#FDE68A",
        )
        yscroll = ttk.Scrollbar(table_host, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_host, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Delete>", self.on_delete_key)
        self.tree.bind("<Control-a>", self.on_select_all_shortcut)
        self.tree.bind("<Control-A>", self.on_select_all_shortcut)

        footer = ctk.CTkFrame(root, fg_color="transparent")
        footer.pack(fill="x")
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            footer,
            textvariable=self.status_var,
            height=36,
            corner_radius=10,
            fg_color=SURFACE_RAISED,
            text_color=CYAN,
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.orphan_progress_bar = ctk.CTkProgressBar(
            footer,
            height=6,
            corner_radius=3,
            fg_color=SURFACE_RAISED,
            progress_color=ACCENT,
        )
        self.orphan_progress_bar.set(0)
        self.orphan_progress_bar.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(7, 0),
        )
        self.orphan_progress_bar.grid_remove()

        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        secondary = {
            "height": 36,
            "fg_color": SURFACE_RAISED,
            "hover_color": BORDER,
            "border_width": 1,
            "border_color": BORDER,
            "text_color": TEXT,
        }
        ctk.CTkButton(
            actions,
            text="Backup selected",
            command=self.backup_selected,
            width=124,
            **secondary,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions,
            text="Select visible",
            command=self.select_all_visible,
            width=108,
            **secondary,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions,
            text="Select orphans",
            command=self.select_orphans,
            width=112,
            **secondary,
        ).pack(side="left", padx=(0, 10))
        ctk.CTkButton(
            actions,
            text="Delete orphans",
            command=self.delete_orphans,
            width=116,
            height=36,
            fg_color="#3A1824",
            hover_color="#5B2638",
            border_width=1,
            border_color="#5B2638",
            text_color="#FF9AB5",
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions,
            text="Delete selected",
            command=self.delete_selected,
            width=122,
            height=36,
            fg_color="#B83258",
            hover_color="#922442",
            text_color="#FFFFFF",
        ).pack(side="left")
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def set_filter(self, value: str) -> None:
        super().set_filter(value)
        for filter_value, button in self._quest_song_filter_buttons.items():
            active = filter_value == value
            button.configure(
                fg_color=ACCENT if active else SURFACE_RAISED,
                hover_color=ACCENT_HOVER if active else BORDER,
                border_color=ACCENT if active else BORDER,
                text_color="#FFFFFF" if active else TEXT,
            )

    def sort_by(self, column: str) -> None:
        super().sort_by(column)
        for column_name, label in self.COLUMN_LABELS.items():
            suffix = ""
            if column_name == self.sort_column:
                suffix = "  ▼" if self.sort_desc else "  ▲"
            self.tree.heading(column_name, text=f"{label}{suffix}")

    def update_orphan_progress(self, completed: int, total: int, phase: str) -> None:
        super().update_orphan_progress(completed, total, phase)
        if self.orphan_progress_hide_after_id is not None:
            try:
                self.after_cancel(self.orphan_progress_hide_after_id)
            except tk.TclError:
                pass
            self.orphan_progress_hide_after_id = None
        if total <= 0:
            self.orphan_progress_bar.grid_remove()
            self.orphan_progress_bar.set(0)
            return
        self.orphan_progress_bar.grid()
        self.orphan_progress_bar.set(max(0.0, min(1.0, completed / total)))

    def apply_orphan_status(self, status_map: dict[str, str]) -> None:
        super().apply_orphan_status(status_map)
        self.orphan_progress_bar.set(1)
        scan_generation = self.orphan_scan_generation
        self.orphan_progress_hide_after_id = self.after(
            700,
            lambda: self.hide_orphan_progress(scan_generation),
        )

    def hide_orphan_progress(self, scan_generation: int) -> None:
        if scan_generation != self.orphan_scan_generation:
            return
        self.orphan_progress_hide_after_id = None
        self.orphan_progress_bar.grid_remove()


class ModernQuestPlaylistManagerDialog(core.QuestPlaylistManagerDialog):
    """Modern Quest playlist library while retaining the proven ADB operations."""

    def _build_ui(self) -> None:
        ctk = core.ctk
        assert ctk is not None
        self.reorder_original_names: tuple[str, ...] = ()
        self.reorder_dirty = False
        self.reorder_apply_in_progress = False
        self.reorder_drag_source: str | None = None
        self.reorder_drag_items: tuple[str, ...] = ()
        self.reorder_drag_original: tuple[str, ...] = ()
        self.title("SR Playlist Forge — Quest Playlists")
        self.geometry("1280x760")
        self.minsize(1080, 650)
        self.configure(fg_color=BG)

        root = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        root.pack(fill="both", expand=True, padx=22, pady=18)

        header = ctk.CTkFrame(root, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)
        title_group = ctk.CTkFrame(header, fg_color="transparent")
        title_group.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_group, text="QUEST LIBRARY", text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"), anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_group, text="Playlists on Quest", text_color=TEXT,
            font=ctk.CTkFont(size=25, weight="bold"), anchor="w",
        ).pack(anchor="w", pady=(2, 1))
        ctk.CTkLabel(
            title_group,
            text="Check integrity, create backups, and open a headset playlist in the editor.",
            text_color=MUTED, font=ctk.CTkFont(size=12), anchor="w",
        ).pack(anchor="w")
        ctk.CTkButton(
            header, text="Close", command=self.request_close, width=88, height=36,
            fg_color=SURFACE_RAISED, hover_color=BORDER, border_width=1,
            border_color=BORDER, text_color=TEXT,
        ).grid(row=0, column=1, sticky="e")

        toolbar = ctk.CTkFrame(
            root, fg_color=SURFACE, corner_radius=14, border_width=1, border_color=BORDER,
        )
        toolbar.pack(fill="x", pady=(0, 10))
        toolbar.grid_columnconfigure(0, weight=1)
        path_group = ctk.CTkFrame(toolbar, fg_color="transparent")
        path_group.grid(row=0, column=0, sticky="ew", padx=16, pady=12)
        ctk.CTkLabel(
            path_group, text="HEADSET FOLDER", text_color=MUTED,
            font=ctk.CTkFont(size=9, weight="bold"), anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            path_group, text=self.playlist_dir, text_color=CYAN,
            font=ctk.CTkFont(size=12, weight="bold"), anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        filter_group = ctk.CTkFrame(toolbar, fg_color="transparent")
        filter_group.grid(row=0, column=1, sticky="e", padx=16, pady=12)
        self._quest_filter_buttons: dict[str, object] = {}
        for label, value in (("All", "all"), ("Issues", "broken")):
            active = value == self.filter_var.get()
            button = ctk.CTkButton(
                filter_group, text=label,
                command=lambda choice=value: self.set_filter(choice),
                width=86, height=34,
                fg_color=ACCENT if active else SURFACE_RAISED,
                hover_color=ACCENT_HOVER if active else BORDER,
                border_width=1, border_color=ACCENT if active else BORDER,
                text_color="#FFFFFF" if active else TEXT,
            )
            button.pack(side="left", padx=(0, 6))
            self._quest_filter_buttons[value] = button
        ctk.CTkButton(
            filter_group, text="Refresh", command=self.refresh_files, width=96, height=34,
            fg_color=SURFACE_RAISED, hover_color=BORDER, border_width=1,
            border_color=BORDER, text_color=TEXT,
        ).pack(side="left")

        table_card = ctk.CTkFrame(
            root, fg_color=SURFACE, corner_radius=14, border_width=1, border_color=BORDER,
        )
        table_card.pack(fill="both", expand=True, pady=(0, 10))
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(1, weight=1)
        table_header = ctk.CTkFrame(table_card, fg_color="transparent")
        table_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))
        table_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            table_header, text="HEADSET PLAYLISTS", text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w")
        order_actions = ctk.CTkFrame(table_header, fg_color="transparent")
        order_actions.grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(
            order_actions, text="Drag rows to reorder", text_color=MUTED,
            font=ctk.CTkFont(size=10),
        ).pack(side="left", padx=(0, 10))
        self.compact_numbering_button = ctk.CTkButton(
            order_actions, text="Compact numbering", command=self.compact_playlist_numbering,
            width=132, height=30, state="disabled",
            fg_color=SURFACE_RAISED, hover_color=BORDER,
            border_width=1, border_color=BORDER, text_color=TEXT,
        )
        self.compact_numbering_button.pack(side="left", padx=(0, 6))
        self.order_cancel_button = ctk.CTkButton(
            order_actions, text="Cancel changes", command=self.cancel_playlist_reorder,
            width=112, height=30, state="disabled",
            fg_color=SURFACE_RAISED, hover_color=BORDER,
            border_width=1, border_color=BORDER, text_color=TEXT,
        )
        self.order_cancel_button.pack(side="left", padx=(0, 6))
        self.order_apply_button = ctk.CTkButton(
            order_actions, text="Apply order", command=self.apply_playlist_order,
            width=104, height=30, state="disabled",
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#FFFFFF", font=ctk.CTkFont(weight="bold"),
        )
        self.order_apply_button.pack(side="left")

        table_host = ctk.CTkFrame(table_card, fg_color=SURFACE_SOFT, corner_radius=0)
        table_host.grid(row=1, column=0, sticky="nsew", padx=1, pady=(0, 1))
        table_host.grid_columnconfigure(0, weight=1)
        table_host.grid_rowconfigure(0, weight=1)
        style = ttk.Style(self)
        style.configure(
            "QuestPlaylists.Treeview", background=SURFACE_SOFT,
            fieldbackground=SURFACE_SOFT, foreground=TEXT, borderwidth=0,
            relief="flat", rowheight=34, font=("Segoe UI", 10),
        )
        style.configure(
            "QuestPlaylists.Treeview.Heading", background=SURFACE_RAISED,
            foreground=MUTED, borderwidth=0, relief="flat", padding=(10, 9),
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "QuestPlaylists.Treeview",
            background=[("selected", "#4934B8")],
            foreground=[("selected", "#FFFFFF")],
        )
        style.map(
            "QuestPlaylists.Treeview.Heading",
            background=[("active", BORDER)], foreground=[("active", TEXT)],
        )
        self.tree = ttk.Treeview(
            table_host, columns=("filename", "status"), show="headings",
            selectmode="extended", style="QuestPlaylists.Treeview",
        )
        self.tree.heading("filename", text="PLAYLIST FILE")
        self.tree.heading("status", text="INTEGRITY")
        self.tree.column("filename", anchor="w", width=820, stretch=True)
        self.tree.column("status", anchor="w", width=240, stretch=False)
        core.install_tree_column_width_persistence(
            self.tree,
            "quest_playlists",
            ("filename", "status"),
        )
        self.tree.tag_configure("ok", background=SURFACE_SOFT, foreground="#A7F3D0")
        self.tree.tag_configure("warning", background="#272416", foreground="#FDE68A")
        self.tree.tag_configure("error", background="#311923", foreground="#FDA4AF")
        self.tree.tag_configure("pending", background="#241C3D", foreground="#C4B5FD")
        yscroll = ttk.Scrollbar(table_host, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Delete>", self.on_delete_key)
        self.tree.bind("<Control-a>", self.on_select_all_shortcut)
        self.tree.bind("<Control-A>", self.on_select_all_shortcut)
        self.tree.bind("<Double-1>", lambda _event: self.open_in_editor())
        self.tree.bind("<ButtonPress-1>", self.on_playlist_reorder_press, add="+")
        self.tree.bind("<B1-Motion>", self.on_playlist_reorder_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self.on_playlist_reorder_release, add="+")
        self.tree.bind("<Escape>", lambda _event: self.cancel_playlist_reorder_drag())

        footer = ctk.CTkFrame(root, fg_color="transparent")
        footer.pack(fill="x")
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            footer, textvariable=self.status_var, height=36, corner_radius=10,
            fg_color=SURFACE_RAISED, text_color=CYAN,
            font=ctk.CTkFont(size=11, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 10))

        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        secondary = {
            "height": 36, "fg_color": SURFACE_RAISED, "hover_color": BORDER,
            "border_width": 1, "border_color": BORDER, "text_color": TEXT,
        }
        ctk.CTkButton(
            actions, text="Backup selected", command=self.backup_selected, width=124, **secondary,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions, text="Select visible", command=self.select_all_visible, width=108, **secondary,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions, text="Missing songs", command=self.show_missing_songs, width=116, **secondary,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions, text="Open in editor", command=self.open_in_editor,
            width=126, height=36, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#FFFFFF", font=ctk.CTkFont(weight="bold"),
        ).pack(side="left", padx=(0, 10))
        ctk.CTkButton(
            actions, text="Delete issues", command=self.delete_broken,
            width=108, height=36, fg_color="#3A1824", hover_color="#5B2638",
            border_width=1, border_color="#5B2638", text_color="#FF9AB5",
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions, text="Delete selected", command=self.delete_selected,
            width=122, height=36, fg_color="#B83258", hover_color="#922442",
            text_color="#FFFFFF",
        ).pack(side="left")
        self.protocol("WM_DELETE_WINDOW", self.request_close)

    def set_filter(self, value: str) -> None:
        if self.reorder_dirty and value != "all":
            core.messagebox.showinfo(
                "Pending Playlist Order",
                "Apply or cancel the pending playlist order before changing filters.",
                parent=self,
            )
            return
        super().set_filter(value)
        for filter_value, button in self._quest_filter_buttons.items():
            active = filter_value == value
            button.configure(
                fg_color=ACCENT if active else SURFACE_RAISED,
                hover_color=ACCENT_HOVER if active else BORDER,
                border_color=ACCENT if active else BORDER,
                text_color="#FFFFFF" if active else TEXT,
            )

    def refresh_files(self) -> None:
        if self.reorder_dirty:
            if not core.messagebox.askyesno(
                "Discard Playlist Order",
                "Discard the pending playlist order and reload from Quest?",
                parent=self,
            ):
                return
            self.reorder_dirty = False
        super().refresh_files()

    def _finish_refresh(
        self,
        files: list[str],
        error: Exception | None,
    ) -> None:
        super()._finish_refresh(files, error)
        if error is None:
            self.reorder_original_names = tuple(self.files)
            self.reorder_dirty = False
            self._update_reorder_buttons()

    def apply_playlist_status(self, status_map: dict[str, str]) -> None:
        super().apply_playlist_status(status_map)
        if self.reorder_dirty:
            self._render_pending_playlist_names()

    def _update_reorder_buttons(self) -> None:
        enabled = self.reorder_dirty and not self.reorder_apply_in_progress
        state = "normal" if enabled else "disabled"
        self.order_apply_button.configure(state=state)
        self.order_cancel_button.configure(state=state)
        self.compact_numbering_button.configure(
            state=(
                "normal"
                if self.reorder_original_names and not self.reorder_apply_in_progress
                else "disabled"
            )
        )

    def _block_if_order_pending(self) -> bool:
        if not self.reorder_dirty:
            return False
        core.messagebox.showinfo(
            "Pending Playlist Order",
            "Apply or cancel the pending playlist order before using this action.",
            parent=self,
        )
        return True

    def show_missing_songs(self) -> None:
        if not self._block_if_order_pending():
            super().show_missing_songs()

    def open_in_editor(self) -> None:
        if not self._block_if_order_pending():
            super().open_in_editor()

    def delete_broken(self) -> None:
        if not self._block_if_order_pending():
            super().delete_broken()

    def delete_selected(self) -> None:
        if not self._block_if_order_pending():
            super().delete_selected()

    def request_close(self) -> None:
        if self.reorder_apply_in_progress:
            core.messagebox.showinfo(
                "Playlist Order Running",
                "Wait for the Quest playlist update to finish before closing this window.",
                parent=self,
            )
            return
        if self.reorder_dirty and not core.messagebox.askyesno(
            "Discard Playlist Order",
            "Close this window and discard the pending playlist order?",
            parent=self,
        ):
            return
        super().destroy()

    def on_playlist_reorder_press(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.reorder_apply_in_progress or self.filter_var.get() != "all":
            return
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            self.cancel_playlist_reorder_drag()
            return
        selected = set(self.tree.selection())
        current = tuple(self.tree.get_children())
        self.reorder_drag_source = row_id
        self.reorder_drag_items = tuple(
            item_id
            for item_id in current
            if item_id == row_id or (row_id in selected and item_id in selected)
        )
        self.reorder_drag_original = current

    def on_playlist_reorder_motion(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.reorder_drag_source is None:
            return
        self.tree.configure(cursor="hand2")
        height = self.tree.winfo_height()
        if event.y < 32:
            self.tree.yview_scroll(-1, "units")
        elif event.y > height - 32:
            self.tree.yview_scroll(1, "units")
        row_id = self.tree.identify_row(event.y)
        current = list(self.tree.get_children())
        dragged = set(self.reorder_drag_items)
        remaining = [item_id for item_id in current if item_id not in dragged]
        if row_id and row_id not in dragged and row_id in remaining:
            target = remaining.index(row_id)
            bounds = self.tree.bbox(row_id)
            if bounds and event.y >= bounds[1] + bounds[3] / 2:
                target += 1
        elif not row_id:
            target = 0 if event.y < height / 2 else len(remaining)
        elif row_id in current:
            row_position = current.index(row_id)
            target = sum(
                1 for item_id in current[:row_position] if item_id not in dragged
            )
        else:
            target = 0
        preview = core.move_id_group(current, self.reorder_drag_items, target)
        for position, item_id in enumerate(preview):
            self.tree.move(item_id, "", position)
        self.tree.selection_set(self.reorder_drag_items)
        self.tree.focus(self.reorder_drag_source)

    def cancel_playlist_reorder_drag(self) -> None:
        if self.reorder_drag_source is None:
            return
        for position, item_id in enumerate(self.reorder_drag_original):
            if self.tree.exists(item_id):
                self.tree.move(item_id, "", position)
        self.tree.configure(cursor="")
        self.reorder_drag_source = None
        self.reorder_drag_items = ()
        self.reorder_drag_original = ()

    def on_playlist_reorder_release(self, _event=None) -> None:
        if self.reorder_drag_source is None:
            return
        order = tuple(self.tree.get_children())
        original_tree_order = self.reorder_drag_original
        dragged_names = {
            self.visible_files[int(item_id)]
            for item_id in self.reorder_drag_items
            if item_id.isdigit() and int(item_id) < len(self.visible_files)
        }
        self.tree.configure(cursor="")
        self.reorder_drag_source = None
        self.reorder_drag_items = ()
        self.reorder_drag_original = ()
        if order == original_tree_order:
            return
        try:
            new_order = [self.visible_files[int(item_id)] for item_id in order]
        except (ValueError, IndexError):
            self.render_files()
            return
        self.files = new_order
        self.visible_files = list(new_order)
        self.reorder_dirty = tuple(new_order) != self.reorder_original_names
        self.render_files()
        selected_ids = [
            str(index) for index, name in enumerate(self.visible_files) if name in dragged_names
        ]
        if selected_ids:
            self.tree.selection_set(selected_ids)
            self.tree.focus(selected_ids[0])
        if self.reorder_dirty:
            self._render_pending_playlist_names()
        else:
            self.status_var.set(
                f"Headset playlists: {len(self.files)} | Order unchanged"
            )
        self._update_reorder_buttons()

    def _render_pending_playlist_names(self) -> None:
        try:
            plan = core.build_playlist_reorder_plan(
                self.reorder_original_names,
                self.files,
            )
        except ValueError as error:
            self.status_var.set(f"Order cannot be applied: {error}")
            return
        changed = 0
        for index, action in enumerate(plan):
            item_id = str(index)
            if not self.tree.exists(item_id):
                continue
            status = self.playlist_status.get(action.source_name, "Checking...")
            if action.source_name != action.target_name:
                tags = ("pending",)
                changed += 1
            elif status == "OK":
                tags = ("ok",)
            elif status.startswith("Missing songs") or status == "Empty":
                tags = ("error",)
            else:
                tags = ("warning",)
            self.tree.item(item_id, values=(action.target_name, status), tags=tags)
        self.status_var.set(
            f"Pending order: {changed} filename changes | Existing number gaps preserved"
        )

    def cancel_playlist_reorder(self) -> None:
        if self.reorder_apply_in_progress:
            return
        self.files = list(self.reorder_original_names)
        self.reorder_dirty = False
        self.render_files()
        self.status_var.set(
            f"Headset playlists: {len(self.files)} | Pending order cancelled"
        )
        self._update_reorder_buttons()

    def compact_playlist_numbering(self) -> None:
        self._apply_playlist_order(compact=True)

    def apply_playlist_order(self) -> None:
        self._apply_playlist_order(compact=False)

    def _apply_playlist_order(self, *, compact: bool) -> None:
        if self.reorder_apply_in_progress:
            return
        try:
            plan = core.build_playlist_reorder_plan(
                self.reorder_original_names,
                self.files,
                compact=compact,
            )
        except ValueError as error:
            core.messagebox.showerror("Playlist Order", str(error), parent=self)
            return
        changed = [action for action in plan if action.source_name != action.target_name]
        if not changed:
            core.messagebox.showinfo(
                "Playlist Order",
                "The playlist filenames already match this order.",
                parent=self,
            )
            return
        action_label = "compact the numbering" if compact else "apply the pending order"
        if not core.messagebox.askyesno(
            "Apply Playlist Order",
            f"This will rename {len(changed)} playlists on Quest to {action_label}.\n\n"
            "A local backup is created before any headset file is renamed. Continue?",
            parent=self,
        ):
            return
        self.reorder_apply_in_progress = True
        self.status_var.set(f"Backing up {len(changed)} playlists before renaming…")
        self.order_apply_button.configure(state="disabled", text="Applying…")
        self.order_cancel_button.configure(state="disabled")
        self.compact_numbering_button.configure(state="disabled")

        def worker() -> None:
            backup_dir: Path | None = None
            try:
                backup_dir = self._execute_playlist_rename_plan(changed)
                core.safe_after(
                    self,
                    lambda: self._finish_playlist_reorder(backup_dir, None),
                )
            except Exception as error:  # noqa: BLE001
                core.safe_after(
                    self,
                    lambda error=error, backup_dir=backup_dir: self._finish_playlist_reorder(
                        backup_dir, error
                    ),
                )

        core.threading.Thread(target=worker, daemon=True).start()

    def _execute_playlist_rename_plan(
        self,
        actions: list[core.PlaylistRenameAction],
    ) -> Path:
        backup_root = core.app_support_dir() / "playlist-reorder-backups"
        backup_dir = backup_root / (
            core.datetime.now().strftime("%Y%m%d-%H%M%S")
            + f"-{core.time.time_ns() % 1_000_000:06d}"
        )
        backup_dir.mkdir(parents=True, exist_ok=False)
        try:
            for action in actions:
                core.adb_pull_file(
                    self.adb_path,
                    core.join_remote_path(self.playlist_dir, action.source_name),
                    backup_dir / core.safe_child_filename(action.source_name, "playlist"),
                )
        except Exception as backup_error:
            raise RuntimeError(
                f"Local backup failed before Quest was changed: {backup_error}\n"
                f"Backup folder: {backup_dir}"
            ) from backup_error

        token = core.uuid.uuid4().hex[:12]
        temporary_names = {
            action.source_name: f".__srpf_reorder_{token}_{index:04d}.playlist"
            for index, action in enumerate(actions)
        }
        moved_to_temporary: list[core.PlaylistRenameAction] = []
        moved_to_final: list[core.PlaylistRenameAction] = []
        try:
            for action in actions:
                core.adb_move_file(
                    self.adb_path,
                    core.join_remote_path(self.playlist_dir, action.source_name),
                    core.join_remote_path(
                        self.playlist_dir,
                        temporary_names[action.source_name],
                    ),
                )
                moved_to_temporary.append(action)
            for action in actions:
                core.adb_move_file(
                    self.adb_path,
                    core.join_remote_path(
                        self.playlist_dir,
                        temporary_names[action.source_name],
                    ),
                    core.join_remote_path(self.playlist_dir, action.target_name),
                )
                moved_to_final.append(action)
        except Exception as rename_error:
            rollback_errors: list[str] = []
            for action in reversed(moved_to_final):
                try:
                    core.adb_move_file(
                        self.adb_path,
                        core.join_remote_path(self.playlist_dir, action.target_name),
                        core.join_remote_path(
                            self.playlist_dir,
                            temporary_names[action.source_name],
                        ),
                    )
                except Exception as rollback_error:  # noqa: BLE001
                    rollback_errors.append(str(rollback_error))
            for action in reversed(moved_to_temporary):
                try:
                    temporary_path = core.join_remote_path(
                        self.playlist_dir,
                        temporary_names[action.source_name],
                    )
                    core.adb_move_file(
                        self.adb_path,
                        temporary_path,
                        core.join_remote_path(
                            self.playlist_dir,
                            action.source_name,
                        ),
                    )
                except Exception as rollback_error:  # noqa: BLE001
                    rollback_errors.append(str(rollback_error))
            details = (
                f"\nRollback also reported: {'; '.join(rollback_errors[:3])}"
                if rollback_errors else "\nThe original filenames were restored."
            )
            raise RuntimeError(
                f"Quest playlist rename failed: {rename_error}{details}\n"
                f"Local backup: {backup_dir}"
            ) from rename_error
        return backup_dir

    def _finish_playlist_reorder(
        self,
        backup_dir: Path | None,
        error: Exception | None,
    ) -> None:
        self.reorder_apply_in_progress = False
        self.order_apply_button.configure(text="Apply order")
        if error is not None:
            self.status_var.set("Playlist order was not applied.")
            self._update_reorder_buttons()
            backup_text = f"\n\nLocal backup:\n{backup_dir}" if backup_dir is not None else ""
            core.messagebox.showerror(
                "Playlist Order Failed",
                f"{error}{backup_text}",
                parent=self,
            )
            return
        self.reorder_dirty = False
        self.status_var.set("Playlist order applied. Reloading Quest playlists…")
        core.messagebox.showinfo(
            "Playlist Order Applied",
            f"The Quest playlist order was updated.\n\nLocal backup:\n{backup_dir}",
            parent=self,
        )
        super().refresh_files()


class ModernListBrowserDialog(core.BeatmapBrowserDialog):
    """List browser for the modern workspace."""

    def _dialog_palette(self) -> dict[str, str]:
        return {
            "bg": BG,
            "surface": SURFACE,
            "surface_alt": SURFACE_RAISED,
            "fg": TEXT,
            "muted": MUTED,
            "accent": ACCENT,
            "accent_text": "#FFFFFF",
            "border": BORDER,
            "input_bg": SURFACE_SOFT,
            "input_fg": TEXT,
            "select_bg": "#4934B8",
            "select_fg": "#FFFFFF",
            "table_even": "#12151C",
            "table_odd": "#171A22",
            "table_heading": "#242936",
            "drag_target": "#352B61",
            "drag_source": ACCENT,
            "danger": DANGER,
            "success": SUCCESS,
            "warning": "#F59E0B",
        }

    def _build_ctk_ui(self) -> None:
        ctk = core.ctk
        assert ctk is not None

        self.title("SR Playlist Forge — List Browser")
        self.geometry("1280x760")
        self.minsize(1040, 620)
        self.configure(fg_color=BG)
        self._filter_refresh_after_id: str | None = None

        root = ctk.CTkFrame(self, corner_radius=0, fg_color=BG)
        root.pack(fill="both", expand=True, padx=18, pady=16)

        header = ctk.CTkFrame(root, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)
        title_group = ctk.CTkFrame(header, fg_color="transparent")
        title_group.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_group,
            text="Browse the catalog",
            text_color=TEXT,
            font=ctk.CTkFont(size=24, weight="bold"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_group,
            text="Search the complete beatmap index and add several tracks at once.",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkButton(
            header,
            text="Close",
            command=self.destroy,
            width=82,
            height=34,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
            border_width=1,
            border_color=BORDER,
        ).grid(row=0, column=1, sticky="e")

        filters = ctk.CTkFrame(
            root,
            fg_color=SURFACE,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        filters.pack(fill="x", pady=(0, 10))
        filters.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            filters,
            text="⌕",
            width=26,
            text_color=CYAN,
            font=ctk.CTkFont(size=17, weight="bold"),
        ).grid(row=0, column=0, padx=(14, 2), pady=12)
        filter_entry = ctk.CTkEntry(
            filters,
            textvariable=self.filter_var,
            placeholder_text="Title, artist, mapper, difficulty or beatmap ID…",
            placeholder_text_color=MUTED,
            text_color=TEXT,
            height=38,
            fg_color=SURFACE_SOFT,
            border_color=BORDER,
        )
        filter_entry.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=12)
        filter_entry.bind("<KeyRelease>", lambda _event: self.schedule_filter_refresh())

        ctk.CTkLabel(filters, text="Length", text_color=MUTED).grid(row=0, column=2, padx=(0, 6), pady=12)
        ctk.CTkComboBox(
            filters,
            variable=self.duration_filter_mode,
            values=["Any", "Over", "Under", "Between"],
            width=104,
            height=34,
            fg_color=SURFACE_SOFT,
            border_color=BORDER,
            button_color=SURFACE_RAISED,
            button_hover_color=BORDER,
            command=lambda _choice: self.schedule_filter_refresh(),
        ).grid(row=0, column=3, padx=(0, 6), pady=12)
        duration_min = ctk.CTkEntry(
            filters,
            textvariable=self.duration_filter_value,
            placeholder_text="MM:SS",
            placeholder_text_color=MUTED,
            width=78,
            height=34,
        )
        duration_min.grid(row=0, column=4, padx=(0, 5), pady=12)
        ctk.CTkLabel(filters, text="—", text_color=MUTED).grid(row=0, column=5, padx=(0, 5), pady=12)
        duration_max = ctk.CTkEntry(
            filters,
            textvariable=self.duration_filter_value_max,
            placeholder_text="MM:SS",
            placeholder_text_color=MUTED,
            width=78,
            height=34,
        )
        duration_max.grid(row=0, column=6, padx=(0, 14), pady=12)
        duration_min.bind("<KeyRelease>", lambda _event: self.schedule_filter_refresh())
        duration_max.bind("<KeyRelease>", lambda _event: self.schedule_filter_refresh())

        date_group = ctk.CTkFrame(filters, fg_color="transparent")
        date_group.grid(row=1, column=1, columnspan=6, sticky="w", padx=(0, 14), pady=(0, 12))
        ctk.CTkLabel(date_group, text="Uploaded", text_color=MUTED).pack(side="left", padx=(0, 8))
        date_from = ctk.CTkEntry(
            date_group,
            textvariable=self.date_filter_from,
            placeholder_text="YYYY-MM-DD",
            placeholder_text_color=MUTED,
            width=116,
            height=34,
            fg_color=SURFACE_SOFT,
            border_color=BORDER,
        )
        date_from.pack(side="left")
        ctk.CTkLabel(date_group, text="to", text_color=MUTED).pack(side="left", padx=7)
        date_to = ctk.CTkEntry(
            date_group,
            textvariable=self.date_filter_to,
            placeholder_text="YYYY-MM-DD",
            placeholder_text_color=MUTED,
            width=116,
            height=34,
            fg_color=SURFACE_SOFT,
            border_color=BORDER,
        )
        date_to.pack(side="left")
        ctk.CTkLabel(date_group, text="inclusive", text_color=MUTED).pack(side="left", padx=(8, 10))
        ctk.CTkButton(
            date_group,
            text="Reset dates",
            width=92,
            height=30,
            command=self.reset_date_filter,
            fg_color="transparent",
            hover_color=SURFACE_RAISED,
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
        ).pack(side="left")
        date_from.bind("<KeyRelease>", lambda _event: self.schedule_filter_refresh())
        date_to.bind("<KeyRelease>", lambda _event: self.schedule_filter_refresh())

        command_bar = ctk.CTkFrame(root, fg_color="transparent")
        command_bar.pack(fill="x", pady=(0, 8))
        command_bar.grid_columnconfigure(1, weight=1)
        data_actions = ctk.CTkFrame(command_bar, fg_color="transparent")
        data_actions.grid(row=0, column=0, sticky="w")
        secondary = {
            "height": 32,
            "fg_color": SURFACE_RAISED,
            "hover_color": BORDER,
            "border_width": 1,
            "border_color": BORDER,
            "text_color": TEXT,
        }
        ctk.CTkButton(
            data_actions,
            text="↻  Check for new",
            width=126,
            command=self.sync_latest_rows,
            **secondary,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            data_actions,
            text="Rebuild catalog",
            width=126,
            command=self.load_all_rows,
            **secondary,
        ).pack(side="left")
        ctk.CTkLabel(
            data_actions,
            text="✓ Exact map   ·   ≈ Same song",
            width=196,
            height=28,
            corner_radius=8,
            fg_color="#252B2B",
            text_color="#D7EBDD",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="left", padx=(10, 0))

        selection_actions = ctk.CTkFrame(command_bar, fg_color="transparent")
        selection_actions.grid(row=0, column=2, sticky="e")
        ctk.CTkLabel(
            selection_actions,
            textvariable=self.selection_var,
            width=100,
            height=32,
            corner_radius=9,
            fg_color=SURFACE_RAISED,
            text_color=CYAN,
            font=ctk.CTkFont(weight="bold"),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            selection_actions,
            text="Select visible",
            width=106,
            command=self.select_all_visible,
            **secondary,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            selection_actions,
            text="Clear",
            width=72,
            command=self.clear_selection,
            **secondary,
        ).pack(side="left")

        table_card = ctk.CTkFrame(
            root,
            fg_color=SURFACE,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        table_card.pack(fill="both", expand=True)
        self._build_table(table_card, padx=10, pady=10)

        footer = ctk.CTkFrame(root, fg_color="transparent")
        footer.pack(fill="x", pady=(9, 0))
        footer.grid_columnconfigure(1, weight=1)
        info = ctk.CTkFrame(footer, fg_color="transparent")
        info.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(info, textvariable=self.page_info_var, text_color=MUTED).pack(side="left")
        ctk.CTkLabel(info, text=" · ", text_color=BORDER).pack(side="left")
        ctk.CTkLabel(info, textvariable=self.status_var, text_color=MUTED).pack(side="left")
        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.grid(row=0, column=2, sticky="e")
        ctk.CTkButton(
            actions,
            text="Open on Synthriderz",
            command=self.open_selected_website,
            width=148,
            height=38,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
            border_width=1,
            border_color=BORDER,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            actions,
            text="Add selected  →",
            command=self.on_add_selected,
            width=142,
            height=38,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(weight="bold"),
        ).pack(side="left")

    def schedule_filter_refresh(self, delay_ms: int = 140) -> None:
        if self._filter_refresh_after_id is not None:
            try:
                self.after_cancel(self._filter_refresh_after_id)
            except (tk.TclError, ValueError):
                pass
        self._filter_refresh_after_id = self.after(delay_ms, self._apply_scheduled_filter_refresh)

    def _apply_scheduled_filter_refresh(self) -> None:
        self._filter_refresh_after_id = None
        if self.winfo_exists():
            self.refresh_table()


class ModernVisualBrowserDialog(core.VisualBeatmapBrowserDialog):
    """Cover-first browser for the modern workspace."""

    COVER_BOX_SIZE = 184

    def _build_ctk_ui(self) -> None:
        ctk = core.ctk
        assert ctk is not None

        self.title("SR Playlist Forge — Visual Browser")
        self.geometry("1320x820")
        self.minsize(1080, 680)
        self.configure(fg_color=BG)
        self.card_filter_var = tk.StringVar()
        self._card_filter_after_id: str | None = None
        self._cover_photo_cache: dict[str, object] = {}

        root = ctk.CTkFrame(self, corner_radius=0, fg_color=BG)
        root.pack(fill="both", expand=True, padx=18, pady=16)

        header = ctk.CTkFrame(root, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)
        title_group = ctk.CTkFrame(header, fg_color="transparent")
        title_group.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_group,
            text="Discover by cover",
            text_color=TEXT,
            font=ctk.CTkFont(size=24, weight="bold"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_group,
            text="A visual pass through the newest Synthriderz beatmaps.",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkButton(
            header,
            text="Close",
            command=self.destroy,
            width=82,
            height=34,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
            border_width=1,
            border_color=BORDER,
        ).grid(row=0, column=1, sticky="e")

        controls = ctk.CTkFrame(
            root,
            fg_color=SURFACE,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        controls.pack(fill="x", pady=(0, 10))
        controls.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            controls,
            text="⌕",
            width=26,
            text_color=CYAN,
            font=ctk.CTkFont(size=17, weight="bold"),
        ).grid(row=0, column=0, padx=(14, 2), pady=10)
        filter_entry = ctk.CTkEntry(
            controls,
            textvariable=self.card_filter_var,
            placeholder_text="Filter this page by title, artist or mapper…",
            placeholder_text_color=MUTED,
            text_color=TEXT,
            height=36,
            fg_color=SURFACE_SOFT,
            border_color=BORDER,
        )
        filter_entry.grid(row=0, column=1, sticky="ew", padx=(0, 14), pady=10)
        filter_entry.bind("<KeyRelease>", lambda _event: self.schedule_card_filter())

        page_controls = ctk.CTkFrame(controls, fg_color="transparent")
        page_controls.grid(row=0, column=2, padx=(0, 10), pady=10)
        ctk.CTkButton(
            page_controls,
            text="‹",
            command=lambda: self.load_page(self.current_page - 1),
            width=36,
            height=34,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
        ).pack(side="left", padx=(0, 5))
        page_entry = ctk.CTkEntry(
            page_controls,
            textvariable=self.page_var,
            width=58,
            height=34,
            justify="center",
        )
        page_entry.pack(side="left")
        page_entry.bind("<Return>", lambda _event: self.go_to_page())
        ctk.CTkButton(
            page_controls,
            text="Go",
            command=self.go_to_page,
            width=44,
            height=34,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            page_controls,
            text="›",
            command=lambda: self.load_page(self.current_page + 1),
            width=36,
            height=34,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
        ).pack(side="left")
        ctk.CTkButton(
            controls,
            text="Newest",
            command=self.load_latest_page,
            width=82,
            height=34,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=3, padx=(0, 14), pady=10)

        content = ctk.CTkFrame(
            root,
            fg_color=SURFACE_SOFT,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        content.pack(fill="both", expand=True)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(content, highlightthickness=0, bg=SURFACE_SOFT)
        self.vscroll = ctk.CTkScrollbar(
            content,
            orientation="vertical",
            command=self.canvas.yview,
            width=12,
            fg_color="transparent",
            button_color=BORDER,
            button_hover_color=ACCENT,
        )
        self.canvas.configure(yscrollcommand=self.vscroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
        self.vscroll.grid(row=0, column=1, sticky="ns", padx=(5, 10), pady=10)
        self.cards_frame = ctk.CTkFrame(self.canvas, fg_color="transparent")
        self.cards_window = self.canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.cards_frame.bind("<Configure>", self.on_cards_configure)
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.bind("<MouseWheel>", self.on_mousewheel, add="+")

        footer = ctk.CTkFrame(root, fg_color="transparent")
        footer.pack(fill="x", pady=(8, 0))
        footer.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            footer,
            textvariable=self.page_info_var,
            text_color=TEXT,
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(footer, textvariable=self.status_var, text_color=MUTED).grid(
            row=0, column=1, sticky="e"
        )

    def _visual_canvas_bg(self) -> str:
        return SURFACE_SOFT

    def schedule_card_filter(self, delay_ms: int = 140) -> None:
        if self._card_filter_after_id is not None:
            try:
                self.after_cancel(self._card_filter_after_id)
            except (tk.TclError, ValueError):
                pass
        self._card_filter_after_id = self.after(delay_ms, self._apply_scheduled_card_filter)

    def _apply_scheduled_card_filter(self) -> None:
        self._card_filter_after_id = None
        if self.winfo_exists():
            self.render_cards()

    def apply_cover_photo(self, beatmap_id: str, label: tk.Label, image) -> None:
        super().apply_cover_photo(beatmap_id, label, image)
        photo = self._image_refs.get(beatmap_id)
        if photo is not None:
            self._cover_photo_cache[beatmap_id] = photo
            while len(self._cover_photo_cache) > MAX_IN_MEMORY_COVERS:
                oldest_id = next(iter(self._cover_photo_cache))
                self._cover_photo_cache.pop(oldest_id, None)

    def render_cards(self, preserve_scroll: bool = False) -> None:
        ctk = core.ctk
        if ctk is None:
            super().render_cards(preserve_scroll=preserve_scroll)
            return

        scroll_position = self.canvas.yview()[0] if preserve_scroll else 0.0
        self._image_refs.clear()
        for child in self.cards_frame.winfo_children():
            child.destroy()

        query = self.card_filter_var.get().strip().casefold() if hasattr(self, "card_filter_var") else ""
        visible_rows = [
            row
            for row in self._rows
            if not query or query in " ".join([row.title, row.artist, row.mapper]).casefold()
        ]
        columns = 4
        for index, row in enumerate(visible_rows):
            match_kind = self.row_playlist_match_kind(row)
            in_playlist = match_kind == "exact"
            same_song = match_kind == "track"
            card = ctk.CTkFrame(
                self.cards_frame,
                corner_radius=13,
                fg_color=SURFACE,
                border_width=1,
                border_color="#286653" if in_playlist else "#7A642B" if same_song else BORDER,
            )
            card.grid(
                row=index // columns,
                column=index % columns,
                padx=7,
                pady=7,
                sticky="nsew",
            )

            art_frame = tk.Frame(
                card,
                width=self.COVER_BOX_SIZE,
                height=self.COVER_BOX_SIZE,
                bg="#0D1016",
                highlightthickness=0,
            )
            art_frame.pack(fill="x", padx=9, pady=(9, 0))
            art_frame.pack_propagate(False)
            art_label = tk.Label(
                art_frame,
                text="Loading cover…" if core.HAS_PILLOW else "Cover unavailable",
                bg="#0D1016",
                fg=MUTED,
                anchor="center",
                justify="center",
                wraplength=self.COVER_BOX_SIZE - 12,
            )
            art_label.pack(fill="both", expand=True)
            cached_cover = self._cover_photo_cache.get(row.beatmap_id)
            if cached_cover is not None:
                self._image_refs[row.beatmap_id] = cached_cover
                art_label.configure(image=cached_cover, text="")
            elif core.HAS_PILLOW:
                self.load_card_cover(row, art_label)

            title_row = ctk.CTkFrame(card, fg_color="transparent")
            title_row.pack(fill="x", padx=10, pady=(9, 0))
            title_row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                title_row,
                text=row.title or "Untitled",
                text_color=TEXT,
                font=ctk.CTkFont(size=13, weight="bold"),
                anchor="w",
                justify="left",
                wraplength=210,
            ).grid(row=0, column=0, sticky="w")
            if match_kind:
                ctk.CTkLabel(
                    title_row,
                    text="✓" if in_playlist else "≈",
                    width=22,
                    height=22,
                    corner_radius=11,
                    fg_color="#173E34" if in_playlist else "#3B321D",
                    text_color="#73F2C5" if in_playlist else "#FFD978",
                    font=ctk.CTkFont(weight="bold"),
                ).grid(row=0, column=1, padx=(5, 0), sticky="ne")

            ctk.CTkLabel(
                card,
                text=row.artist or "Unknown artist",
                text_color=MUTED,
                anchor="w",
                wraplength=230,
            ).pack(fill="x", padx=10, pady=(2, 0))
            ctk.CTkLabel(
                card,
                text=f"mapped by {row.mapper or 'Unknown'}",
                text_color="#737C8E",
                anchor="w",
                wraplength=230,
                font=ctk.CTkFont(size=10),
            ).pack(fill="x", padx=10, pady=(1, 0))
            self.render_difficulty_badges(card, row)

            meta = ctk.CTkFrame(card, fg_color=SURFACE_SOFT, corner_radius=8)
            meta.pack(fill="x", padx=9, pady=(0, 8))
            meta.grid_columnconfigure((0, 1), weight=1)
            ctk.CTkLabel(
                meta,
                text=f"◷  {row.duration_text or '—'}",
                text_color=MUTED,
                font=ctk.CTkFont(size=10),
            ).grid(row=0, column=0, sticky="w", padx=8, pady=5)
            ctk.CTkLabel(
                meta,
                text=f"↓  {row.download_count}",
                text_color=MUTED,
                font=ctk.CTkFont(size=10),
            ).grid(row=0, column=1, sticky="e", padx=8, pady=5)

            buttons = ctk.CTkFrame(card, fg_color="transparent")
            buttons.pack(fill="x", padx=9, pady=(0, 9))
            buttons.grid_columnconfigure(0, weight=1)
            if in_playlist:
                ctk.CTkButton(
                    buttons,
                    text="In playlist",
                    state="disabled",
                    height=32,
                    fg_color="#173E34",
                    text_color_disabled="#73F2C5",
                ).grid(row=0, column=0, sticky="ew", padx=(0, 5))
            else:
                ctk.CTkButton(
                    buttons,
                    text="+  Add this map" if same_song else "+  Add",
                    command=lambda selected=row: self.add_single_row(selected),
                    height=32,
                    fg_color=ACCENT,
                    hover_color=ACCENT_HOVER,
                    font=ctk.CTkFont(weight="bold"),
                ).grid(row=0, column=0, sticky="ew", padx=(0, 5))
            ctk.CTkButton(
                buttons,
                text="▶",
                command=lambda selected=row: self.search_row_on_youtube(selected),
                width=36,
                height=32,
                fg_color=SURFACE_RAISED,
                hover_color=BORDER,
            ).grid(row=0, column=1, padx=(0, 5))
            ctk.CTkButton(
                buttons,
                text="↗",
                command=lambda selected=row: self.open_row_website(selected),
                width=36,
                height=32,
                fg_color=SURFACE_RAISED,
                hover_color=BORDER,
            ).grid(row=0, column=2)

        for column in range(columns):
            self.cards_frame.columnconfigure(column, weight=1)
        self.cards_frame.update_idletasks()
        self.on_cards_configure()
        self.canvas.yview_moveto(scroll_position)
        if query:
            self.status_var.set(f"{len(visible_rows)} matches on this page.")


class ModernCommunityPlaylistBrowserDialog(core.BASE_DIALOG_CLASS):
    """Cover-first browser for public Synthriderz playlists."""

    PAGE_SIZE = 12
    COVER_BOX_SIZE = 220

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.title("SR Playlist Forge — Playlist Browser")
        core.apply_app_window_icon(self)
        self.geometry("1320x820")
        self.minsize(1080, 680)
        self.configure(fg_color=BG)
        self.result: tuple[
            str,
            dict[str, object],
            core.CommunityPlaylistEntry,
        ] | None = None
        self.entries: list[core.CommunityPlaylistEntry] = []
        self.filtered_entries: list[core.CommunityPlaylistEntry] = []
        self.current_page = 1
        self.loading = False
        self.filter_after_id: str | None = None
        self.cover_photos: dict[str, object] = {}
        self.busy_playlist_id: str | None = None

        self.search_var = tk.StringVar()
        self.sort_var = tk.StringVar(value="Recently added")
        self.playlist_view_var = tk.StringVar(value="Browse All")
        self.curated_category_var = tk.StringVar(value="All curated")
        self.page_var = tk.StringVar(value="Page 1 / 1")
        self.status_var = tk.StringVar(value="Loading community playlists…")

        self._build_ui()
        self.transient(parent)
        self.grab_set()
        self.load_entries()

    def _build_ui(self) -> None:
        ctk = core.ctk
        assert ctk is not None

        root = ctk.CTkFrame(self, corner_radius=0, fg_color=BG)
        root.pack(fill="both", expand=True, padx=18, pady=16)

        header = ctk.CTkFrame(root, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)
        title_group = ctk.CTkFrame(header, fg_color="transparent")
        title_group.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_group,
            text="Synthriderz playlists",
            text_color=TEXT,
            font=ctk.CTkFont(size=24, weight="bold"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_group,
            text="Browse every public playlist or explore Synthriderz curated collections.",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkButton(
            header,
            text="Close",
            command=self.destroy,
            width=82,
            height=34,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
            border_width=1,
            border_color=BORDER,
        ).grid(row=0, column=1, sticky="e")

        controls = ctk.CTkFrame(
            root,
            fg_color=SURFACE,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        controls.pack(fill="x", pady=(0, 10))
        controls.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            controls,
            text="⌕",
            width=26,
            text_color=CYAN,
            font=ctk.CTkFont(size=17, weight="bold"),
        ).grid(row=0, column=0, padx=(14, 2), pady=10)
        search = ctk.CTkEntry(
            controls,
            textvariable=self.search_var,
            placeholder_text="Search playlist, creator or description…",
            placeholder_text_color=MUTED,
            text_color=TEXT,
            height=36,
            fg_color=SURFACE_SOFT,
            border_color=BORDER,
        )
        search.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=10)
        search.bind("<KeyRelease>", lambda _event: self.schedule_filter())
        ctk.CTkSegmentedButton(
            controls,
            variable=self.playlist_view_var,
            values=["Browse All", "Curated"],
            command=self.on_playlist_view_changed,
            height=34,
            fg_color=SURFACE_SOFT,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            unselected_color=SURFACE_SOFT,
            unselected_hover_color=SURFACE_RAISED,
        ).grid(row=0, column=2, padx=(0, 10), pady=10)
        self.curated_category_combo = ctk.CTkComboBox(
            controls,
            variable=self.curated_category_var,
            values=["All curated", *core.CURATED_PLAYLIST_CATEGORIES],
            command=lambda _value: self.apply_filter(),
            width=174,
            height=34,
            state="disabled",
            fg_color=SURFACE_SOFT,
            border_color=BORDER,
            button_color=SURFACE_RAISED,
            button_hover_color=BORDER,
        )
        self.curated_category_combo.grid(row=0, column=3, padx=(0, 10), pady=10)
        ctk.CTkComboBox(
            controls,
            variable=self.sort_var,
            values=["Recently added", "Most downloaded", "Highest rated", "Name"],
            command=lambda _value: self.apply_filter(),
            width=164,
            height=34,
            fg_color=SURFACE_SOFT,
            border_color=BORDER,
            button_color=SURFACE_RAISED,
            button_hover_color=BORDER,
        ).grid(row=0, column=4, padx=(0, 10), pady=10)
        ctk.CTkButton(
            controls,
            text="Refresh",
            command=self.load_entries,
            width=82,
            height=34,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
            border_width=1,
            border_color=BORDER,
        ).grid(row=0, column=5, padx=(0, 14), pady=10)

        content = ctk.CTkFrame(
            root,
            fg_color=SURFACE_SOFT,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        content.pack(fill="both", expand=True)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(content, highlightthickness=0, bg=SURFACE_SOFT)
        scrollbar = ctk.CTkScrollbar(
            content,
            orientation="vertical",
            command=self.canvas.yview,
            width=12,
            fg_color="transparent",
            button_color=BORDER,
            button_hover_color=ACCENT,
        )
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(5, 10), pady=10)
        self.cards_frame = ctk.CTkFrame(self.canvas, fg_color="transparent")
        self.cards_window = self.canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.cards_frame.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda event: self.canvas.itemconfigure(self.cards_window, width=event.width),
        )
        self.bind(
            "<MouseWheel>",
            lambda event: self.canvas.yview_scroll(int(-event.delta / 120), "units"),
            add="+",
        )

        footer = ctk.CTkFrame(root, fg_color="transparent")
        footer.pack(fill="x", pady=(8, 0))
        footer.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(footer, textvariable=self.status_var, text_color=MUTED).grid(
            row=0, column=0, sticky="w"
        )
        navigation = ctk.CTkFrame(footer, fg_color="transparent")
        navigation.grid(row=0, column=1, sticky="e")
        ctk.CTkButton(
            navigation,
            text="‹",
            command=lambda: self.change_page(-1),
            width=36,
            height=30,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
        ).pack(side="left")
        ctk.CTkLabel(
            navigation,
            textvariable=self.page_var,
            text_color=TEXT,
            width=112,
        ).pack(side="left", padx=7)
        ctk.CTkButton(
            navigation,
            text="›",
            command=lambda: self.change_page(1),
            width=36,
            height=30,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
        ).pack(side="left")

    def schedule_filter(self) -> None:
        if self.filter_after_id is not None:
            try:
                self.after_cancel(self.filter_after_id)
            except (tk.TclError, ValueError):
                pass
        self.filter_after_id = self.after(150, self.apply_filter)

    def on_playlist_view_changed(self, value: str) -> None:
        self.curated_category_combo.configure(state="normal" if value == "Curated" else "disabled")
        self.current_page = 1
        self.apply_filter()

    def load_entries(self) -> None:
        if self.loading:
            return
        self.loading = True
        self.status_var.set("Loading community playlists…")

        def worker() -> None:
            try:
                browse_entries = core.fetch_community_playlists()
                curated_entries = core.fetch_curated_community_playlists()
                entries = core.merge_community_playlist_entries(browse_entries, curated_entries)
                core.safe_after(self, lambda: self.finish_load(entries, None))
            except Exception as error:  # noqa: BLE001
                core.safe_after(self, lambda error=error: self.finish_load([], error))

        core.threading.Thread(target=worker, daemon=True).start()

    def finish_load(
        self,
        entries: list[core.CommunityPlaylistEntry],
        error: Exception | None,
    ) -> None:
        self.loading = False
        if error is not None:
            self.status_var.set("Could not load community playlists.")
            core.messagebox.showerror("Playlist Browser", str(error), parent=self)
            return
        self.entries = entries
        self.current_page = 1
        self.apply_filter()

    def apply_filter(self) -> None:
        self.filter_after_id = None
        query = self.search_var.get().strip().casefold()
        view = self.playlist_view_var.get()
        curated_category = self.curated_category_var.get()
        rows = [
            entry
            for entry in self.entries
            if core.community_playlist_matches_view(entry, view, curated_category)
            and (
                not query
                or query
                in " ".join([entry.name, entry.creator, entry.description]).casefold()
            )
        ]
        sort_mode = self.sort_var.get()
        if sort_mode == "Most downloaded":
            rows.sort(key=lambda entry: (entry.download_count, entry.published_sort), reverse=True)
        elif sort_mode == "Highest rated":
            rows.sort(key=lambda entry: (entry.vote_score, entry.download_count), reverse=True)
        elif sort_mode == "Name":
            rows.sort(key=lambda entry: (entry.name.casefold(), entry.creator.casefold()))
        else:
            rows.sort(key=lambda entry: (entry.published_sort, int(entry.playlist_id)), reverse=True)
        self.filtered_entries = rows
        max_page = max(1, (len(rows) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self.current_page = min(max(1, self.current_page), max_page)
        self.render_cards()

    def change_page(self, delta: int) -> None:
        max_page = max(
            1,
            (len(self.filtered_entries) + self.PAGE_SIZE - 1) // self.PAGE_SIZE,
        )
        target = min(max(1, self.current_page + delta), max_page)
        if target == self.current_page:
            return
        self.current_page = target
        self.render_cards()

    def render_cards(self) -> None:
        ctk = core.ctk
        assert ctk is not None
        for child in self.cards_frame.winfo_children():
            child.destroy()
        start = (self.current_page - 1) * self.PAGE_SIZE
        rows = self.filtered_entries[start : start + self.PAGE_SIZE]
        columns = 4
        for index, entry in enumerate(rows):
            card = ctk.CTkFrame(
                self.cards_frame,
                corner_radius=13,
                fg_color=SURFACE,
                border_width=1,
                border_color=BORDER,
            )
            card.grid(
                row=index // columns,
                column=index % columns,
                padx=7,
                pady=7,
                sticky="nsew",
            )
            art_frame = tk.Frame(
                card,
                width=self.COVER_BOX_SIZE,
                height=self.COVER_BOX_SIZE,
                bg="#0D1016",
                highlightthickness=0,
            )
            art_frame.pack(padx=9, pady=(9, 0))
            art_frame.pack_propagate(False)
            art_label = tk.Label(
                art_frame,
                text="Loading cover…" if core.HAS_PILLOW else "Cover unavailable",
                bg="#0D1016",
                fg=MUTED,
            )
            art_label.pack(fill="both", expand=True)
            cached = self.cover_photos.get(entry.playlist_id)
            if cached is not None:
                art_label.configure(image=cached, text="")
            elif core.HAS_PILLOW:
                self.load_cover(entry, art_label)

            if self.playlist_view_var.get() == "Curated" and entry.curated_categories:
                visible_categories = (
                    entry.curated_categories
                    if self.curated_category_var.get() == "All curated"
                    else (self.curated_category_var.get(),)
                )
                ctk.CTkLabel(
                    card,
                    text="  •  ".join(visible_categories),
                    text_color=CYAN,
                    font=ctk.CTkFont(size=9, weight="bold"),
                    anchor="w",
                ).pack(fill="x", padx=10, pady=(7, 0))

            ctk.CTkLabel(
                card,
                text=entry.name or "Untitled playlist",
                text_color=TEXT,
                font=ctk.CTkFont(size=14, weight="bold"),
                anchor="w",
                justify="left",
                wraplength=240,
            ).pack(
                fill="x",
                padx=10,
                pady=(5, 0)
                if self.playlist_view_var.get() == "Curated" and entry.curated_categories
                else (9, 0),
            )
            ctk.CTkLabel(
                card,
                text=f"by {entry.creator or 'Unknown creator'}",
                text_color=CYAN,
                anchor="w",
                font=ctk.CTkFont(size=10, weight="bold"),
            ).pack(fill="x", padx=10, pady=(2, 0))
            ctk.CTkLabel(
                card,
                text=entry.description or "No description",
                text_color=MUTED,
                anchor="nw",
                justify="left",
                wraplength=240,
                height=42,
                font=ctk.CTkFont(size=10),
            ).pack(fill="x", padx=10, pady=(5, 6))

            meta = ctk.CTkFrame(card, fg_color=SURFACE_SOFT, corner_radius=8)
            meta.pack(fill="x", padx=9, pady=(0, 8))
            meta.grid_columnconfigure((0, 1, 2), weight=1)
            ctk.CTkLabel(
                meta,
                text=f"↓ {entry.download_count}",
                text_color=MUTED,
                font=ctk.CTkFont(size=10),
            ).grid(row=0, column=0, sticky="w", padx=7, pady=5)
            ctk.CTkLabel(
                meta,
                text=f"▲ {entry.vote_score:+d}",
                text_color=MUTED,
                font=ctk.CTkFont(size=10),
            ).grid(row=0, column=1, pady=5)
            ctk.CTkLabel(
                meta,
                text=entry.published_text or "—",
                text_color=MUTED,
                font=ctk.CTkFont(size=10),
            ).grid(row=0, column=2, sticky="e", padx=7, pady=5)

            buttons = ctk.CTkFrame(card, fg_color="transparent")
            buttons.pack(fill="x", padx=9, pady=(0, 9))
            buttons.grid_columnconfigure(0, weight=1)
            ctk.CTkButton(
                buttons,
                text="Open",
                command=lambda selected=entry: self.request_playlist(selected, "open"),
                height=32,
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
                font=ctk.CTkFont(weight="bold"),
            ).grid(row=0, column=0, sticky="ew", padx=(0, 5))
            ctk.CTkButton(
                buttons,
                text="+ Add",
                command=lambda selected=entry: self.request_playlist(selected, "merge"),
                width=58,
                height=32,
                fg_color=SURFACE_RAISED,
                hover_color=BORDER,
            ).grid(row=0, column=1, padx=(0, 5))
            ctk.CTkButton(
                buttons,
                text="↓",
                command=lambda selected=entry: self.save_playlist(selected),
                width=36,
                height=32,
                fg_color=SURFACE_RAISED,
                hover_color=BORDER,
            ).grid(row=0, column=2, padx=(0, 5))
            ctk.CTkButton(
                buttons,
                text="↗",
                command=lambda selected=entry: core.webbrowser.open(
                    f"https://synthriderz.com/playlists/{selected.playlist_id}"
                ),
                width=36,
                height=32,
                fg_color=SURFACE_RAISED,
                hover_color=BORDER,
            ).grid(row=0, column=3)

        for column in range(columns):
            self.cards_frame.columnconfigure(column, weight=1)
        max_page = max(
            1,
            (len(self.filtered_entries) + self.PAGE_SIZE - 1) // self.PAGE_SIZE,
        )
        self.page_var.set(f"Page {self.current_page} / {max_page}")
        noun = "curated playlists" if self.playlist_view_var.get() == "Curated" else "playlists"
        self.status_var.set(
            f"{len(self.filtered_entries)} {noun}"
            if not self.search_var.get().strip()
            else f"{len(self.filtered_entries)} matching {noun}"
        )
        self.cards_frame.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(0)

    def load_cover(self, entry: core.CommunityPlaylistEntry, label: tk.Label) -> None:
        def worker() -> None:
            try:
                cache_path = core.community_playlist_cover_cache_path(entry)
                if cache_path.exists():
                    raw = cache_path.read_bytes()
                else:
                    request = core.Request(
                        core.synthriderz_url(entry.cover_url),
                        headers=core.DEFAULT_HEADERS,
                    )
                    with core.urlopen(request, timeout=20) as response:
                        raw = core.read_limited_response(
                            response,
                            core.MAX_COVER_RESPONSE_BYTES,
                        )
                    core.community_playlist_cover_cache_dir().mkdir(
                        parents=True,
                        exist_ok=True,
                    )
                    core.atomic_write_bytes(cache_path, raw)
                with core.Image.open(core.io.BytesIO(raw)) as source:
                    image = core.ImageOps.fit(
                        source.convert("RGB"),
                        (self.COVER_BOX_SIZE, self.COVER_BOX_SIZE),
                        method=core.Image.Resampling.LANCZOS,
                    )
                core.safe_after(
                    self,
                    lambda: self.apply_cover(entry.playlist_id, label, image),
                )
            except Exception:
                core.safe_after(
                    self,
                    lambda: label.configure(text="Cover unavailable")
                    if label.winfo_exists()
                    else None,
                )

        core.threading.Thread(target=worker, daemon=True).start()

    def apply_cover(self, playlist_id: str, label: tk.Label, image) -> None:
        if not label.winfo_exists() or core.ImageTk is None:
            return
        photo = core.ImageTk.PhotoImage(image)
        self.cover_photos[playlist_id] = photo
        while len(self.cover_photos) > MAX_IN_MEMORY_COVERS:
            oldest_id = next(iter(self.cover_photos))
            self.cover_photos.pop(oldest_id, None)
        label.configure(image=photo, text="")

    def request_playlist(
        self,
        entry: core.CommunityPlaylistEntry,
        action: str,
    ) -> None:
        if self.busy_playlist_id is not None:
            return
        self.busy_playlist_id = entry.playlist_id
        self.status_var.set(f"Downloading {entry.name}…")

        def worker() -> None:
            try:
                payload, _raw = core.fetch_community_playlist_document(entry)
                core.safe_after(
                    self,
                    lambda: self.finish_request(action, entry, payload, None),
                )
            except Exception as error:  # noqa: BLE001
                core.safe_after(
                    self,
                    lambda error=error: self.finish_request(action, entry, None, error),
                )

        core.threading.Thread(target=worker, daemon=True).start()

    def finish_request(
        self,
        action: str,
        entry: core.CommunityPlaylistEntry,
        payload: dict[str, object] | None,
        error: Exception | None,
    ) -> None:
        self.busy_playlist_id = None
        if error is not None or payload is None:
            self.status_var.set("Playlist download failed.")
            core.messagebox.showerror(
                "Playlist Browser",
                str(error or "No playlist data was returned."),
                parent=self,
            )
            return
        self.result = action, payload, entry
        self.destroy()

    def save_playlist(self, entry: core.CommunityPlaylistEntry) -> None:
        if self.busy_playlist_id is not None:
            return
        default_name = core.sanitize_filename_component(entry.name) or f"playlist-{entry.playlist_id}"
        path = core.filedialog.asksaveasfilename(
            parent=self,
            title="Save Community Playlist",
            defaultextension=".playlist",
            initialfile=f"{default_name}.playlist",
            filetypes=[("Synth Riders Playlist", "*.playlist")],
        )
        if not path:
            return
        destination = Path(core.normalize_playlist_path(path))
        if destination.exists() and not core.messagebox.askyesno(
            "File Exists",
            f"Overwrite existing file?\n{destination}",
            parent=self,
        ):
            return
        self.busy_playlist_id = entry.playlist_id
        self.status_var.set(f"Saving {entry.name}…")

        def worker() -> None:
            try:
                _payload, raw = core.fetch_community_playlist_document(entry)
                core.atomic_write_bytes(destination, raw)
                core.safe_after(self, lambda: self.finish_save(destination, None))
            except Exception as error:  # noqa: BLE001
                core.safe_after(
                    self,
                    lambda error=error: self.finish_save(destination, error),
                )

        core.threading.Thread(target=worker, daemon=True).start()

    def finish_save(self, destination: Path, error: Exception | None) -> None:
        self.busy_playlist_id = None
        if error is not None:
            self.status_var.set("Playlist save failed.")
            core.messagebox.showerror("Save Playlist", str(error), parent=self)
            return
        self.status_var.set(f"Saved {destination.name}")
        core.messagebox.showinfo("Playlist Saved", f"Saved:\n{destination}", parent=self)

    def destroy(self) -> None:
        if self.filter_after_id is not None:
            try:
                self.after_cancel(self.filter_after_id)
            except (tk.TclError, ValueError):
                pass
            self.filter_after_id = None
        super().destroy()


class ModernClearAllSongsDialog(core.BASE_DIALOG_CLASS):
    """Destructive confirmation styled for the modern workspace."""

    def __init__(self, parent: tk.Misc, song_count: int):
        super().__init__(parent)
        ctk = core.ctk
        assert ctk is not None
        self.result = False
        self.title("SR Playlist Forge — Clear All Songs")
        core.apply_app_window_icon(self)
        self.geometry("540x260")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        root = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        root.pack(fill="both", expand=True, padx=24, pady=22)
        ctk.CTkLabel(
            root,
            text="PLAYLIST ACTION",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
            anchor="w",
        ).pack(fill="x")

        card = ctk.CTkFrame(
            root,
            fg_color=SURFACE,
            corner_radius=14,
            border_width=1,
            border_color="#5B2638",
        )
        card.pack(fill="both", expand=True, pady=(8, 14))

        warning = ctk.CTkLabel(
            card,
            text="!",
            width=52,
            height=52,
            corner_radius=26,
            fg_color="#3A1824",
            text_color="#FF769B",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        warning.grid(row=0, column=0, rowspan=2, padx=(18, 14), pady=20, sticky="n")
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            card,
            text="Clear all songs?",
            text_color=TEXT,
            font=ctk.CTkFont(size=21, weight="bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="sw", padx=(0, 18), pady=(20, 2))
        song_label = "song" if song_count == 1 else "songs"
        ctk.CTkLabel(
            card,
            text=(
                f"This removes {song_count} {song_label} from the current playlist.\n"
                "This action cannot be undone."
            ),
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
            justify="left",
            anchor="nw",
        ).grid(row=1, column=1, sticky="nw", padx=(0, 18), pady=(2, 20))

        buttons = ctk.CTkFrame(root, fg_color="transparent")
        buttons.pack(fill="x")
        cancel_button = ctk.CTkButton(
            buttons,
            text="Cancel",
            command=self.cancel,
            width=112,
            height=38,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
        )
        cancel_button.pack(side="right")
        ctk.CTkButton(
            buttons,
            text="Clear all songs",
            command=self.confirm,
            width=148,
            height=38,
            fg_color="#B83258",
            hover_color="#922442",
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
        ).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda _event: self.cancel())
        self.bind("<Return>", lambda _event: self.confirm())
        self.after(50, cancel_button.focus_set)
        self.after(20, self.center_over_parent)
        self.grab_set()

    def center_over_parent(self) -> None:
        try:
            self.update_idletasks()
            parent = self.master
            x = parent.winfo_rootx() + max(0, (parent.winfo_width() - self.winfo_width()) // 2)
            y = parent.winfo_rooty() + max(0, (parent.winfo_height() - self.winfo_height()) // 2)
            self.geometry(f"+{x}+{y}")
        except (tk.TclError, AttributeError):
            pass

    def confirm(self) -> None:
        self.result = True
        self.destroy()

    def cancel(self) -> None:
        self.result = False
        self.destroy()


class ModernPlaylistEditorApp(core.PlaylistEditorApp):
    """The standard SR Playlist Forge workspace."""

    def __init__(self, instance_guard: core.SingleInstanceGuard | None = None) -> None:
        super().__init__(instance_guard=instance_guard)
        if core.HAS_CUSTOMTKINTER and core.ctk is not None:
            install_modern_messageboxes(self)

    def session_file_path(self) -> Path:
        return Path.home() / ".sr_playlist_forge_session.json"

    def choose_playlist_color(self, key: str) -> None:
        if not core.HAS_CUSTOMTKINTER or core.ctk is None:
            super().choose_playlist_color(key)
            return
        initial = normalized_hex_color(self.playlist_vars[key].get(), "#FFFFFF")
        dialog = ModernColorDialog(self, f"Choose {key}", initial)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.playlist_vars[key].set(dialog.result)

    def add_empty_song(self) -> None:
        if not core.HAS_CUSTOMTKINTER or core.ctk is None:
            super().add_empty_song()
            return
        song = core.SongEntry(hash="", addedTime=int(core.time.time()))
        dialog = ModernSongEditDialog(self, song)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        if self.hash_exists(dialog.result.hash):
            core.messagebox.showerror("Duplicate Hash", "This song hash is already in the playlist.", parent=self)
            return
        self.songs.append(dialog.result)
        self.refresh_table(keep_index=len(self.songs) - 1)

    def edit_selected(self) -> None:
        if not core.HAS_CUSTOMTKINTER or core.ctk is None:
            super().edit_selected()
            return
        index = self.selected_index()
        if index is None:
            core.messagebox.showerror("No Selection", "Select a song to edit.", parent=self)
            return
        dialog = ModernSongEditDialog(self, self.songs[index])
        self.wait_window(dialog)
        if dialog.result is None:
            return
        if self.hash_exists(dialog.result.hash, ignore_index=index):
            core.messagebox.showerror("Duplicate Hash", "This song hash is already in the playlist.", parent=self)
            return
        self.songs[index] = dialog.result
        self.refresh_table(keep_index=index)

    def open_beatmap_browser(self) -> None:
        dialog = ModernListBrowserDialog(
            self,
            on_add_songs=self.add_songs_from_list_browser,
            existing_songs=self.songs,
        )
        self.wait_window(dialog)
        if dialog.result:
            self.add_songs_from_list_browser(dialog.result)

    def open_visual_browser(self) -> None:
        dialog = ModernVisualBrowserDialog(
            self,
            on_add_song=self.add_song_from_visual_browser,
            existing_songs=self.songs,
        )
        self.wait_window(dialog)
        if dialog.result:
            self.add_song_from_visual_browser(dialog.result[0])

    def open_community_playlist_browser(self) -> None:
        dialog = ModernCommunityPlaylistBrowserDialog(self)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        action, payload, entry = dialog.result
        source_stem = core.sanitize_filename_component(entry.name) or f"playlist-{entry.playlist_id}"
        source_name = f"{source_stem}.playlist"
        if action == "open":
            if self.songs and not core.messagebox.askyesno(
                "Replace Current Playlist",
                f"Open '{entry.name}' by {entry.creator or 'Unknown creator'} "
                "and replace the current editor contents?",
                parent=self,
            ):
                return
            self.load_playlist_payload_into_editor(payload, source_name)
            return
        self.merge_playlist_payload(payload, source_name)

    def open_quest_song_manager(self) -> None:
        adb_path = core.find_adb_executable()
        if not adb_path:
            core.messagebox.showerror(
                "ADB Not Found",
                "adb was not found. Bundle or install adb first.",
                parent=self,
            )
            return
        try:
            devices = core.list_adb_devices(adb_path)
        except Exception as error:  # noqa: BLE001
            core.messagebox.showerror("Quest Not Available", str(error), parent=self)
            return
        if not devices:
            core.messagebox.showerror(
                "Quest Not Detected",
                "Connect the headset and allow USB debugging first.",
                parent=self,
            )
            return
        dialog = ModernQuestSongManagerDialog(
            self,
            adb_path,
            self.quest_song_dir_var.get().strip(),
            self.quest_playlist_dir_var.get().strip(),
        )
        self.wait_window(dialog)

    def open_quest_playlist_manager(self) -> None:
        adb_path = core.find_adb_executable()
        if not adb_path:
            core.messagebox.showerror(
                "ADB Not Found",
                "adb was not found. Bundle or install adb first.",
                parent=self,
            )
            return
        try:
            devices = core.list_adb_devices(adb_path)
        except Exception as error:  # noqa: BLE001
            core.messagebox.showerror("Quest Not Available", str(error), parent=self)
            return
        if not devices:
            core.messagebox.showerror(
                "Quest Not Detected",
                "Connect the headset and allow USB debugging first.",
                parent=self,
            )
            return
        dialog = ModernQuestPlaylistManagerDialog(
            self,
            adb_path,
            self.quest_playlist_dir_var.get().strip(),
        )
        self.wait_window(dialog)
        if dialog.result:
            self.open_headset_playlist_in_editor(adb_path, dialog.result)

    def set_next_quest_playlist_number(self) -> None:
        if self.quest_number_lookup_in_progress:
            return
        self.quest_number_lookup_in_progress = True
        self.quest_number_status_var.set("Checking Quest playlists…")
        self.next_quest_number_button.configure(state="disabled", text="Checking…")
        playlist_dir = self.quest_playlist_dir_var.get().strip()

        def worker() -> None:
            try:
                adb_path = core.find_adb_executable()
                if not adb_path:
                    raise RuntimeError("adb was not found. Bundle or install adb first.")
                devices = core.list_adb_devices(adb_path)
                if not devices:
                    raise RuntimeError("Connect the headset and allow USB debugging first.")
                if not playlist_dir:
                    raise RuntimeError("The Quest playlist folder is empty.")
                file_names = core.list_remote_files(adb_path, playlist_dir)
                next_number = core.next_playlist_number_from_names(file_names)
                core.safe_after(
                    self,
                    lambda: self._finish_next_quest_playlist_number(next_number, None),
                )
            except Exception as error:  # noqa: BLE001
                core.safe_after(
                    self,
                    lambda error=error: self._finish_next_quest_playlist_number(None, error),
                )

        core.threading.Thread(target=worker, daemon=True).start()

    def _finish_next_quest_playlist_number(
        self,
        next_number: int | None,
        error: Exception | None,
    ) -> None:
        self.quest_number_lookup_in_progress = False
        self.next_quest_number_button.configure(state="normal", text="Next on Quest")
        if error is not None:
            self.quest_number_status_var.set("Quest number could not be read.")
            core.messagebox.showerror("Quest Playlist Number", str(error), parent=self)
            return
        assert next_number is not None
        self.playlist_vars["playlistNumber"].set(str(next_number))
        self.quest_number_status_var.set(f"Next available Quest number: {next_number}")

    def confirm_clear_all_songs(self) -> bool:
        dialog = ModernClearAllSongsDialog(self, len(self.songs))
        self.wait_window(dialog)
        return dialog.result

    def _build_ui(self) -> None:
        if not core.HAS_CUSTOMTKINTER or core.ctk is None:
            super()._build_ui()
            self.title(f"SR Playlist Forge v{core.APP_VERSION}")
            return

        ctk = core.ctk
        self.title(f"SR Playlist Forge v{core.APP_VERSION}")
        self.geometry("1460x860")
        self.minsize(1180, 720)
        self.configure(fg_color=BG)

        self.url_var = tk.StringVar()
        self.quest_status_var = tk.StringVar(value="Quest not detected")
        self.quest_number_status_var = tk.StringVar(value="")
        self.quest_number_lookup_in_progress = False
        self.concept_search_var = tk.StringVar()
        self.page_title_var = tk.StringVar(value="Playlist")
        self.page_subtitle_var = tk.StringVar(value="Shape the set, keep the flow.")
        self.selection_title_var = tk.StringVar(value="No song selected")
        self.selection_meta_var = tk.StringVar(value="Select a row to inspect or edit it.")
        self._pages: dict[str, core.ctk.CTkFrame] = {}
        self._nav_buttons: dict[str, core.ctk.CTkButton] = {}

        shell = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        shell.pack(fill="both", expand=True)
        shell.grid_columnconfigure(1, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        self._build_navigation(shell)

        workspace = ctk.CTkFrame(shell, fg_color=BG, corner_radius=0)
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.grid_columnconfigure(0, weight=1)
        workspace.grid_rowconfigure(1, weight=1)

        self._build_header(workspace)

        page_host = ctk.CTkFrame(workspace, fg_color="transparent")
        page_host.grid(row=1, column=0, sticky="nsew", padx=22, pady=(0, 14))
        page_host.grid_columnconfigure(0, weight=1)
        page_host.grid_rowconfigure(0, weight=1)

        self._pages["playlist"] = self._build_playlist_page(page_host)
        self._pages["discover"] = self._build_discover_page(page_host)
        self._pages["appearance"] = self._build_appearance_page(page_host)
        self._pages["quest"] = self._build_quest_page(page_host)
        for page in self._pages.values():
            page.grid(row=0, column=0, sticky="nsew")

        self._build_download_bar(workspace)
        self.show_page("playlist")

    def _build_navigation(self, parent: "core.ctk.CTkFrame") -> None:
        ctk = core.ctk
        assert ctk is not None

        rail = ctk.CTkFrame(parent, width=218, corner_radius=0, fg_color=RAIL)
        rail.grid(row=0, column=0, sticky="nsw")
        rail.grid_propagate(False)

        brand = ctk.CTkFrame(rail, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(24, 30))
        mark = ctk.CTkLabel(
            brand,
            text="SR",
            width=42,
            height=42,
            corner_radius=12,
            fg_color=ACCENT,
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        mark.pack(side="left")
        brand_text = ctk.CTkFrame(brand, fg_color="transparent")
        brand_text.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(
            brand_text,
            text="PLAYLIST FORGE",
            text_color=TEXT,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand_text,
            text=f"VERSION {core.APP_VERSION}",
            text_color=CYAN,
            font=ctk.CTkFont(size=10, weight="bold"),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        ctk.CTkLabel(
            rail,
            text="WORKSPACE",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=22, pady=(0, 8))

        nav_items = [
            ("playlist", "▦", "Playlist"),
            ("discover", "⌕", "Discover"),
            ("appearance", "◇", "Appearance"),
            ("quest", "◉", "Quest"),
        ]
        for key, icon, label in nav_items:
            button = ctk.CTkButton(
                rail,
                text=f"{icon}   {label}",
                command=lambda page=key: self.show_page(page),
                height=42,
                corner_radius=10,
                anchor="w",
                border_spacing=14,
                fg_color="transparent",
                hover_color=SURFACE_RAISED,
                text_color=MUTED,
                font=ctk.CTkFont(size=13, weight="bold"),
            )
            button.pack(fill="x", padx=12, pady=2)
            self._nav_buttons[key] = button

        spacer = ctk.CTkFrame(rail, fg_color="transparent")
        spacer.pack(fill="both", expand=True)

        status_card = ctk.CTkFrame(rail, fg_color=SURFACE_SOFT, corner_radius=12, border_width=1, border_color=BORDER)
        status_card.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkLabel(
            status_card,
            text="CURRENT PLAYLIST",
            text_color=CYAN,
            font=ctk.CTkFont(size=10, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=12, pady=(11, 2))
        ctk.CTkLabel(
            status_card,
            textvariable=self.generated_filename_var,
            text_color=MUTED,
            justify="left",
            anchor="w",
            font=ctk.CTkFont(size=11),
        ).pack(fill="x", padx=12, pady=(0, 11))

    def _build_header(self, parent: "core.ctk.CTkFrame") -> None:
        ctk = core.ctk
        assert ctk is not None

        header = ctk.CTkFrame(parent, fg_color="transparent", height=98)
        header.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 12))
        header.grid_columnconfigure(0, weight=1)

        title_group = ctk.CTkFrame(header, fg_color="transparent")
        title_group.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_group,
            textvariable=self.page_title_var,
            text_color=TEXT,
            font=ctk.CTkFont(size=28, weight="bold"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_group,
            textvariable=self.page_subtitle_var,
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        ctk.CTkButton(
            actions,
            text="Import playlist",
            command=self.add_playlist,
            width=128,
            height=38,
            corner_radius=10,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            actions,
            text="Export playlist  →",
            command=self.export_playlist,
            width=154,
            height=38,
            corner_radius=10,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
        ).pack(side="left")

    def _page_frame(self, parent: "core.ctk.CTkFrame") -> "core.ctk.CTkFrame":
        ctk = core.ctk
        assert ctk is not None
        return ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)

    def _card(self, parent: tk.Misc, **kwargs):
        ctk = core.ctk
        assert ctk is not None
        return ctk.CTkFrame(
            parent,
            fg_color=kwargs.pop("fg_color", SURFACE),
            corner_radius=kwargs.pop("corner_radius", 14),
            border_width=kwargs.pop("border_width", 1),
            border_color=kwargs.pop("border_color", BORDER),
            **kwargs,
        )

    def _build_playlist_page(self, parent: "core.ctk.CTkFrame") -> "core.ctk.CTkFrame":
        ctk = core.ctk
        assert ctk is not None

        page = self._page_frame(parent)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        identity = self._card(page)
        identity.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        identity.grid_columnconfigure(0, weight=1)
        name_group = ctk.CTkFrame(identity, fg_color="transparent")
        name_group.grid(row=0, column=0, sticky="ew", padx=16, pady=13)
        name_group.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(
            name_group,
            textvariable=self.playlist_vars["namePlaylist"],
            height=36,
            fg_color="transparent",
            border_width=0,
            text_color=TEXT,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkEntry(
            name_group,
            textvariable=self.playlist_vars["description"],
            height=28,
            fg_color="transparent",
            border_width=0,
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
        ).grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(
            identity,
            textvariable=self.stats_var,
            text_color=CYAN,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=1, padx=18, pady=13)

        table_card = self._card(page)
        table_card.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(2, weight=1)

        table_title = ctk.CTkFrame(table_card, fg_color="transparent")
        table_title.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(13, 8))
        table_title.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            table_title,
            text="TRACK ORDER",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            table_title,
            text="Clear all",
            command=self.clear_all_songs,
            width=82,
            height=30,
            fg_color="transparent",
            hover_color="#3A1D2A",
            border_width=1,
            border_color="#6B2A42",
            text_color="#FF8EAA",
        ).grid(row=0, column=1, padx=(0, 8))
        ctk.CTkButton(
            table_title,
            text="↑",
            command=lambda: self.move_selected(-1),
            width=34,
            height=30,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
            text_color=TEXT,
        ).grid(row=0, column=2, padx=(0, 5))
        ctk.CTkButton(
            table_title,
            text="↓",
            command=lambda: self.move_selected(1),
            width=34,
            height=30,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
            text_color=TEXT,
        ).grid(row=0, column=3)

        filters = ctk.CTkFrame(table_card, fg_color=SURFACE_SOFT, corner_radius=10)
        filters.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 9))
        filters.grid_columnconfigure(0, weight=1)
        search = ctk.CTkEntry(
            filters,
            textvariable=self.concept_search_var,
            placeholder_text="Search title, artist or mapper…",
            placeholder_text_color=MUTED,
            text_color=TEXT,
            height=34,
            border_width=0,
            fg_color=SURFACE_SOFT,
        )
        search.grid(row=0, column=0, sticky="ew", padx=(10, 5), pady=6)
        search.bind("<Return>", lambda _event: self.refresh_table())
        ctk.CTkComboBox(
            filters,
            variable=self.difficulty_filter_choice,
            values=["Any", "Easy", "Normal", "Hard", "Expert", "Master"],
            width=112,
            height=30,
            fg_color=SURFACE_RAISED,
            border_color=BORDER,
            button_color=SURFACE_RAISED,
            button_hover_color=BORDER,
        ).grid(row=0, column=1, padx=5, pady=6)
        ctk.CTkButton(
            filters,
            text="Filter",
            command=self.apply_filters,
            width=72,
            height=30,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        ).grid(row=0, column=2, padx=5, pady=6)
        ctk.CTkButton(
            filters,
            text="Clear",
            command=self.clear_concept_filters,
            width=66,
            height=30,
            fg_color="transparent",
            hover_color=SURFACE_RAISED,
            border_width=1,
            border_color=BORDER,
        ).grid(row=0, column=3, padx=(5, 8), pady=6)

        columns = ["hash", "name", "author", "beatmapper", "difficulty", "trackDuration", "addedTime"]
        self.column_labels = {
            "hash": "hash",
            "name": "TITLE",
            "author": "ARTIST",
            "beatmapper": "MAPPER",
            "difficulty": "DIFFICULTY",
            "trackDuration": "TIME",
            "addedTime": "ADDED",
        }
        self.tree = ttk.Treeview(
            table_card,
            columns=columns,
            show="headings",
            selectmode="extended",
            style="Playlist.Treeview",
        )
        widths = {
            "hash": 0,
            "name": 270,
            "author": 160,
            "beatmapper": 135,
            "difficulty": 145,
            "trackDuration": 72,
            "addedTime": 135,
        }
        for column in columns:
            self.tree.heading(column, text=self.column_labels[column], command=lambda col=column: self.on_column_click(col))
            self.tree.column(
                column,
                width=widths[column],
                minwidth=0 if column == "hash" else 55,
                stretch=column not in {"hash", "trackDuration"},
                anchor="w",
            )
        self.tree.grid(row=2, column=0, sticky="nsew", padx=(12, 0), pady=(0, 12))
        scrollbar = ctk.CTkScrollbar(
            table_card,
            orientation="vertical",
            command=self.tree.yview,
            width=12,
            fg_color="transparent",
            button_color=BORDER,
            button_hover_color=ACCENT,
        )
        scrollbar.grid(row=2, column=1, sticky="ns", padx=(5, 10), pady=(0, 12))
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<ButtonPress-1>", self.on_song_tree_press)
        self.tree.bind("<B1-Motion>", self.on_song_tree_motion)
        self.tree.bind("<ButtonRelease-1>", self.on_song_tree_release)
        self.tree.bind("<Escape>", self.cancel_song_tree_drag)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.update_selection_summary())
        self.tree.bind("<Double-1>", lambda _event: self.edit_selected())
        core.install_tree_column_width_persistence(self.tree, "playlist_editor", columns)

        side = ctk.CTkFrame(page, fg_color="transparent", width=286)
        side.grid(row=1, column=1, sticky="ns")
        side.grid_propagate(False)

        add_card = self._card(side)
        add_card.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            add_card,
            text="ADD MUSIC",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(13, 4))
        ctk.CTkButton(
            add_card,
            text="Open Visual Browser  →",
            command=self.open_visual_browser,
            height=40,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(weight="bold"),
        ).pack(fill="x", padx=12, pady=(3, 6))
        ctk.CTkButton(
            add_card,
            text="List Browser",
            command=self.open_beatmap_browser,
            height=34,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
        ).pack(fill="x", padx=12, pady=3)
        ctk.CTkButton(
            add_card,
            text="Playlist Browser",
            command=self.open_community_playlist_browser,
            height=34,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
        ).pack(fill="x", padx=12, pady=3)
        ctk.CTkButton(
            add_card,
            text="Import .synth files",
            command=self.add_synth_files_dialog,
            height=34,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
        ).pack(fill="x", padx=12, pady=3)
        ctk.CTkButton(
            add_card,
            text="+  Add manually",
            command=self.add_empty_song,
            height=32,
            fg_color="transparent",
            hover_color=SURFACE_RAISED,
            border_width=1,
            border_color=BORDER,
            text_color=MUTED,
        ).pack(fill="x", padx=12, pady=(3, 12))

        inspect_card = self._card(side)
        inspect_card.pack(fill="x")
        ctk.CTkLabel(
            inspect_card,
            text="SELECTION",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(13, 5))
        ctk.CTkLabel(
            inspect_card,
            textvariable=self.selection_title_var,
            text_color=TEXT,
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
            justify="left",
            wraplength=245,
        ).pack(fill="x", padx=14)
        ctk.CTkLabel(
            inspect_card,
            textvariable=self.selection_meta_var,
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
            justify="left",
            wraplength=245,
        ).pack(fill="x", padx=14, pady=(4, 12))
        selection_actions = ctk.CTkFrame(inspect_card, fg_color="transparent")
        selection_actions.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkButton(
            selection_actions,
            text="Edit",
            command=self.edit_selected,
            height=32,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
        ).pack(side="left", fill="x", expand=True, padx=(0, 3))
        ctk.CTkButton(
            selection_actions,
            text="Remove",
            command=self.remove_selected,
            height=32,
            fg_color="#3A1B28",
            hover_color="#562238",
            text_color="#FF91AE",
        ).pack(side="left", fill="x", expand=True, padx=(3, 0))
        ctk.CTkButton(
            inspect_card,
            text="Download selected",
            command=self.download_selected,
            height=34,
            fg_color="transparent",
            hover_color=SURFACE_RAISED,
            border_width=1,
            border_color=BORDER,
        ).pack(fill="x", padx=12, pady=(0, 12))
        return page

    def _build_discover_page(self, parent: "core.ctk.CTkFrame") -> "core.ctk.CTkFrame":
        ctk = core.ctk
        assert ctk is not None

        page = self._page_frame(parent)
        page.grid_columnconfigure((0, 1), weight=1, uniform="discover")
        page.grid_rowconfigure(1, weight=1)

        hero = self._card(page, fg_color="#171429", border_color="#352B61")
        self.discover_hero = hero
        hero.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        hero.grid_columnconfigure(0, weight=1)
        copy = ctk.CTkFrame(hero, fg_color="transparent")
        copy.grid(row=0, column=0, sticky="ew", padx=24, pady=24)
        ctk.CTkLabel(
            copy,
            text="Find the next track.",
            text_color=TEXT,
            font=ctk.CTkFont(size=24, weight="bold"),
            anchor="w",
        ).pack(anchor="w")
        discover_description = ctk.CTkLabel(
            copy,
            text="Browse songs and community playlists without leaving Playlist Forge.",
            text_color="#BBB4D8",
            font=ctk.CTkFont(size=12),
            anchor="w",
            justify="left",
        )
        self.discover_description = discover_description
        discover_description.pack(fill="x", anchor="w", pady=(5, 0))
        hero_actions = ctk.CTkFrame(hero, fg_color="transparent")
        hero_actions.grid(row=0, column=1, padx=24, pady=24, sticky="e")
        ctk.CTkButton(
            hero_actions,
            text="Visual Browser  →",
            command=self.open_visual_browser,
            width=150,
            height=42,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(weight="bold"),
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            hero_actions,
            text="List Browser",
            command=self.open_beatmap_browser,
            width=120,
            height=42,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
            border_width=1,
            border_color=BORDER,
        ).pack(side="left")
        ctk.CTkButton(
            hero_actions,
            text="Playlist Browser",
            command=self.open_community_playlist_browser,
            width=138,
            height=42,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
            border_width=1,
            border_color=BORDER,
        ).pack(side="left", padx=(8, 0))
        hero.bind(
            "<Configure>",
            lambda event: discover_description.configure(
                wraplength=responsive_wrap_width(
                    event.width,
                    reserved_width=hero_actions.winfo_reqwidth(),
                    horizontal_padding=96,
                    minimum=260,
                )
            ),
            add="+",
        )

        url_card = self._card(page)
        self.discover_url_card = url_card
        url_card.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(
            url_card,
            text="ADD FROM LINK",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", padx=18, pady=(18, 6))
        ctk.CTkLabel(
            url_card,
            text="Paste a beatmap URL",
            text_color=TEXT,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", padx=18)
        url_description = ctk.CTkLabel(
            url_card,
            text="The map metadata is fetched and added directly to this playlist.",
            text_color=MUTED,
            wraplength=430,
            justify="left",
        )
        url_description.pack(fill="x", anchor="w", padx=18, pady=(5, 18))
        url_card.bind(
            "<Configure>",
            lambda event: url_description.configure(
                wraplength=responsive_wrap_width(
                    event.width,
                    horizontal_padding=44,
                    minimum=220,
                )
            ),
            add="+",
        )
        ctk.CTkEntry(
            url_card,
            textvariable=self.url_var,
            placeholder_text="https://synthriderz.com/beatmaps/…",
            height=40,
        ).pack(fill="x", padx=18)
        ctk.CTkButton(
            url_card,
            text="Add to playlist",
            command=self.add_song_from_url,
            height=38,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        ).pack(fill="x", padx=18, pady=(10, 18))

        files_card = self._card(page)
        self.discover_files_card = files_card
        files_card.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(
            files_card,
            text="LOCAL FILES",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", padx=18, pady=(18, 6))
        ctk.CTkLabel(
            files_card,
            text="Bring your own maps",
            text_color=TEXT,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", padx=18)
        files_description = ctk.CTkLabel(
            files_card,
            text="Drop .synth files below or choose them from disk.",
            text_color=MUTED,
            justify="left",
        )
        files_description.pack(fill="x", anchor="w", padx=18, pady=(5, 18))
        files_card.bind(
            "<Configure>",
            lambda event: files_description.configure(
                wraplength=responsive_wrap_width(
                    event.width,
                    horizontal_padding=44,
                    minimum=220,
                )
            ),
            add="+",
        )
        self.drop_zone = ctk.CTkLabel(
            files_card,
            text="DROP .SYNTH FILES HERE\n\nor click Import below",
            height=150,
            corner_radius=12,
            fg_color=SURFACE_SOFT,
            text_color=MUTED,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.drop_zone.pack(fill="both", expand=True, padx=18)
        if core.HAS_DND_SUPPORT and core.DND_FILES is not None:
            self.drop_zone.drop_target_register(core.DND_FILES)
            self.drop_zone.dnd_bind("<<Drop>>", self.on_drop_synth_files)
        ctk.CTkButton(
            files_card,
            text="Import .synth files",
            command=self.add_synth_files_dialog,
            height=38,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
        ).pack(fill="x", padx=18, pady=(10, 18))
        return page

    def _build_appearance_page(self, parent: "core.ctk.CTkFrame") -> "core.ctk.CTkFrame":
        ctk = core.ctk
        assert ctk is not None

        page = self._page_frame(parent)
        page.grid_columnconfigure((0, 1), weight=1)
        page.grid_rowconfigure(0, weight=1)

        details = self._card(page)
        details.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        details.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            details,
            text="PLAYLIST DETAILS",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 5))
        fields = [
            ("Name", "namePlaylist"),
            ("Description", "description"),
            ("Playlist number", "playlistNumber"),
        ]
        row = 1
        for label, key in fields:
            ctk.CTkLabel(details, text=label, text_color=MUTED, anchor="w").grid(
                row=row, column=0, sticky="ew", padx=18, pady=(9, 3)
            )
            field_row = ctk.CTkFrame(details, fg_color="transparent")
            field_row.grid(row=row + 1, column=0, sticky="ew", padx=18)
            field_row.grid_columnconfigure(0, weight=1)
            ctk.CTkEntry(field_row, textvariable=self.playlist_vars[key], height=38).grid(
                row=0, column=0, sticky="ew"
            )
            if key == "playlistNumber":
                self.next_quest_number_button = ctk.CTkButton(
                    field_row,
                    text="Next on Quest",
                    command=self.set_next_quest_playlist_number,
                    width=118,
                    height=38,
                    fg_color=SURFACE_RAISED,
                    hover_color=BORDER,
                    border_width=1,
                    border_color=BORDER,
                    text_color=TEXT,
                )
                self.next_quest_number_button.grid(row=0, column=1, padx=(8, 0))
            row += 2
        ctk.CTkLabel(
            details,
            textvariable=self.quest_number_status_var,
            text_color=CYAN,
            font=ctk.CTkFont(size=10),
            anchor="w",
        ).grid(row=row, column=0, sticky="ew", padx=18, pady=(5, 0))
        row += 1
        ctk.CTkLabel(details, text="Creation date", text_color=MUTED, anchor="w").grid(
            row=row, column=0, sticky="ew", padx=18, pady=(9, 3)
        )
        date_row = ctk.CTkFrame(details, fg_color="transparent")
        date_row.grid(row=row + 1, column=0, sticky="ew", padx=18)
        date_row.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(date_row, textvariable=self.playlist_vars["creationDateHuman"], height=38).grid(
            row=0, column=0, sticky="ew"
        )
        ctk.CTkButton(
            date_row,
            text="Now",
            command=self.set_creation_date_to_now,
            width=70,
            height=38,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
        ).grid(row=0, column=1, padx=(8, 0))
        ctk.CTkLabel(details, text="EXPORT FILE", text_color=MUTED, font=ctk.CTkFont(size=10, weight="bold")).grid(
            row=row + 2, column=0, sticky="w", padx=18, pady=(24, 4)
        )
        ctk.CTkLabel(
            details,
            textvariable=self.generated_filename_var,
            text_color=CYAN,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).grid(row=row + 3, column=0, sticky="ew", padx=18)
        ctk.CTkButton(
            details,
            text="Export playlist  →",
            command=self.export_playlist,
            height=40,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        ).grid(row=row + 4, column=0, sticky="ew", padx=18, pady=(14, 18))

        style = self._card(page)
        style.grid(row=0, column=1, sticky="nsew", padx=6)
        style.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            style,
            text="COVER STYLE",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 5))
        ctk.CTkLabel(
            style,
            text="Tune the in-game identity",
            text_color=TEXT,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 12))
        number_fields = ctk.CTkFrame(style, fg_color="transparent")
        number_fields.grid(row=2, column=0, sticky="ew", padx=18)
        number_fields.grid_columnconfigure((0, 1), weight=1)
        for column, (label, key) in enumerate(
            [("Icon index", "SelectedIconIndex"), ("Texture", "SelectedTexture")]
        ):
            cell = ctk.CTkFrame(number_fields, fg_color="transparent")
            cell.grid(row=0, column=column, sticky="ew", padx=(0, 5) if column == 0 else (5, 0))
            ctk.CTkLabel(cell, text=label, text_color=MUTED, anchor="w").pack(fill="x", pady=(0, 3))
            index_control = ctk.CTkFrame(cell, fg_color="transparent")
            index_control.pack(fill="x")
            entry = ctk.CTkEntry(index_control, textvariable=self.playlist_vars[key], height=38)
            entry.pack(side="left", fill="x", expand=True)
            entry.bind("<Up>", lambda _event, field=key: self.adjust_playlist_visual_index(field, 1))
            entry.bind("<Down>", lambda _event, field=key: self.adjust_playlist_visual_index(field, -1))
            arrows = ctk.CTkFrame(index_control, fg_color="transparent", width=36)
            arrows.pack(side="left", padx=(5, 0))
            ctk.CTkButton(
                arrows,
                text="▲",
                command=lambda field=key: self.adjust_playlist_visual_index(field, 1),
                width=36,
                height=18,
                corner_radius=6,
                fg_color=SURFACE_RAISED,
                hover_color=ACCENT,
                text_color=TEXT,
                font=ctk.CTkFont(size=10, weight="bold"),
            ).pack(pady=(0, 2))
            ctk.CTkButton(
                arrows,
                text="▼",
                command=lambda field=key: self.adjust_playlist_visual_index(field, -1),
                width=36,
                height=18,
                corner_radius=6,
                fg_color=SURFACE_RAISED,
                hover_color=ACCENT,
                text_color=TEXT,
                font=ctk.CTkFont(size=10, weight="bold"),
            ).pack()
        labels = {
            "gradientTop": "Gradient top",
            "gradientDown": "Gradient bottom",
            "colorTitle": "Title color",
            "colorTexture": "Texture color",
        }
        for offset, key in enumerate(labels, start=3):
            ctk.CTkLabel(style, text=labels[key], text_color=MUTED, anchor="w").grid(
                row=offset * 2 - 3, column=0, sticky="ew", padx=18, pady=(10, 3)
            )
            self._build_ctk_color_picker_field(style, key, offset * 2 - 2, 0)
        ctk.CTkButton(
            style,
            text="✦  Randomize coordinated look",
            command=self.randomize_playlist_look,
            height=40,
            fg_color="#1F3A3D",
            hover_color="#285055",
            text_color="#8CEBF3",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=12, column=0, sticky="ew", padx=18, pady=(18, 18))

        preview = self._card(page)
        preview.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        preview.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            preview,
            text="LIVE PREVIEW",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 5))
        ctk.CTkLabel(
            preview,
            text="See the in-game icon and texture",
            text_color=TEXT,
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        self.playlist_preview_label = ctk.CTkLabel(
            preview,
            text="Import visuals to enable preview",
            width=360,
            height=220,
            corner_radius=14,
            fg_color=SURFACE_SOFT,
            text_color=MUTED,
        )
        self.playlist_preview_label.grid(row=2, column=0, sticky="ew", padx=18)
        ctk.CTkLabel(
            preview,
            textvariable=self.playlist_visual_status_var,
            text_color=CYAN,
            font=ctk.CTkFont(size=11, weight="bold"),
            justify="left",
            anchor="w",
            wraplength=340,
        ).grid(row=3, column=0, sticky="ew", padx=18, pady=(10, 12))
        import_actions = ctk.CTkFrame(preview, fg_color="transparent")
        import_actions.grid(row=4, column=0, sticky="ew", padx=18)
        import_actions.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(
            import_actions,
            text="Import from Quest",
            command=self.import_playlist_visuals_from_quest,
            height=38,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(
            import_actions,
            text="Import from PC",
            command=self.import_playlist_visuals_from_pc,
            height=38,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
            border_width=1,
            border_color=BORDER,
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ctk.CTkLabel(
            preview,
            text="Read-only import. Extracted previews stay in your local app cache.",
            text_color=MUTED,
            font=ctk.CTkFont(size=10),
            justify="left",
            anchor="w",
            wraplength=340,
        ).grid(row=5, column=0, sticky="ew", padx=18, pady=(10, 18))
        self.schedule_playlist_visual_preview()
        return page

    def _build_quest_page(self, parent: "core.ctk.CTkFrame") -> "core.ctk.CTkFrame":
        ctk = core.ctk
        assert ctk is not None

        page = self._page_frame(parent)
        page.grid_columnconfigure(0, weight=1)

        connection = self._card(page)
        connection.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        connection.grid_columnconfigure(1, weight=1)
        self.quest_status_indicator = ctk.CTkLabel(
            connection,
            text="●",
            width=24,
            text_color="#F87171",
            font=ctk.CTkFont(size=19, weight="bold"),
        )
        self.quest_status_indicator.grid(row=0, column=0, padx=(18, 8), pady=18)
        status_group = ctk.CTkFrame(connection, fg_color="transparent")
        status_group.grid(row=0, column=1, sticky="w", pady=15)
        ctk.CTkLabel(
            status_group,
            textvariable=self.quest_status_var,
            text_color=TEXT,
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            status_group,
            textvariable=self.quest_adb_var,
            text_color=MUTED,
            font=ctk.CTkFont(size=10),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkButton(
            connection,
            text="Refresh connection",
            command=self.refresh_quest_status,
            width=140,
            height=36,
            fg_color=SURFACE_RAISED,
            hover_color=BORDER,
        ).grid(row=0, column=2, padx=18, pady=15)

        paths = self._card(page)
        paths.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        paths.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(paths, text="DEVICE PATHS", text_color=MUTED, font=ctk.CTkFont(size=10, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=18, pady=(18, 8)
        )
        for row, (label, variable) in enumerate(
            [("Custom songs", self.quest_song_dir_var), ("Playlists", self.quest_playlist_dir_var)],
            start=1,
        ):
            ctk.CTkLabel(paths, text=label, text_color=MUTED, anchor="w").grid(
                row=row * 2 - 1, column=0, sticky="ew", padx=18, pady=(7, 3)
            )
            ctk.CTkEntry(paths, textvariable=variable, height=38).grid(
                row=row * 2, column=0, sticky="ew", padx=18, pady=(0, 5)
            )
        ctk.CTkFrame(paths, height=8, fg_color="transparent").grid(row=5, column=0)

        actions = ctk.CTkFrame(page, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew")
        actions.grid_columnconfigure((0, 1, 2), weight=1)
        quest_actions = [
            ("Manage songs", self.open_quest_song_manager),
            ("Manage playlists", self.open_quest_playlist_manager),
            ("Send current playlist  →", self.send_playlist_to_quest),
        ]
        for column, (label, command) in enumerate(quest_actions):
            primary = column == 2
            ctk.CTkButton(
                actions,
                text=label,
                command=command,
                height=48,
                fg_color=ACCENT if primary else SURFACE,
                hover_color=ACCENT_HOVER if primary else SURFACE_RAISED,
                border_width=0 if primary else 1,
                border_color=BORDER,
                font=ctk.CTkFont(weight="bold"),
            ).grid(row=0, column=column, sticky="ew", padx=(0, 6) if column == 0 else ((6, 0) if column == 2 else 6))
        return page

    def _build_download_bar(self, parent: "core.ctk.CTkFrame") -> None:
        ctk = core.ctk
        assert ctk is not None

        bar = ctk.CTkFrame(parent, fg_color=SURFACE_SOFT, corner_radius=0, height=48)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(
            bar,
            text="TRANSFER",
            text_color=MUTED,
            font=ctk.CTkFont(size=9, weight="bold"),
        ).grid(row=0, column=0, padx=(22, 10), pady=12)
        self.download_progress = ctk.CTkProgressBar(
            bar,
            mode="determinate",
            width=180,
            height=7,
            fg_color=BORDER,
            progress_color=CYAN,
        )
        self.download_progress.set(0)
        self.download_progress.grid(row=0, column=1, padx=(0, 12), pady=12)
        ctk.CTkLabel(
            bar,
            textvariable=self.download_status_var,
            text_color=MUTED,
            anchor="w",
        ).grid(row=0, column=2, sticky="w", pady=12)
        ctk.CTkLabel(
            bar,
            textvariable=self.download_percent_var,
            text_color=TEXT,
            width=48,
        ).grid(row=0, column=3, padx=8, pady=12)
        self.cancel_download_btn = ctk.CTkButton(
            bar,
            text="Cancel",
            command=self.request_cancel_download,
            state="disabled",
            width=72,
            height=28,
            fg_color="transparent",
            hover_color="#3A1B28",
            border_width=1,
            border_color=BORDER,
            text_color=MUTED,
        )
        self.cancel_download_btn.grid(row=0, column=4, padx=(0, 22), pady=10)

    def show_page(self, page_name: str) -> None:
        if page_name not in self._pages:
            return
        titles = {
            "playlist": ("Playlist", "Shape the set, keep the flow."),
            "discover": ("Discover", "Bring in music without leaving your creative rhythm."),
            "appearance": ("Appearance", "Give the playlist a recognizable in-game identity."),
            "quest": ("Quest", "Transfer and manage content on the headset."),
        }
        self.page_title_var.set(titles[page_name][0])
        self.page_subtitle_var.set(titles[page_name][1])
        self._pages[page_name].tkraise()
        for key, button in self._nav_buttons.items():
            selected = key == page_name
            button.configure(
                fg_color="#241E3E" if selected else "transparent",
                text_color="#D8CEFF" if selected else MUTED,
                border_width=1 if selected else 0,
                border_color="#463978",
            )

    def get_visible_indices(self) -> list[int]:
        indices = super().get_visible_indices()
        if not hasattr(self, "concept_search_var"):
            return indices
        query = self.concept_search_var.get().strip().casefold()
        if not query:
            return indices
        return [
            index
            for index in indices
            if query
            in " ".join(
                [
                    self.songs[index].name,
                    self.songs[index].author,
                    self.songs[index].beatmapper,
                    self.songs[index].difficultyText,
                ]
            ).casefold()
        ]

    def clear_concept_filters(self) -> None:
        self.concept_search_var.set("")
        self.clear_filters()

    def refresh_table(self, keep_index: int | None = None) -> None:
        super().refresh_table(keep_index=keep_index)
        if hasattr(self, "selection_title_var"):
            self.update_selection_summary()

    def update_selection_summary(self) -> None:
        if not hasattr(self, "selection_title_var") or not hasattr(self, "tree"):
            return
        indices = self.selected_indices()
        if not indices:
            self.selection_title_var.set("No song selected")
            self.selection_meta_var.set("Select a row to inspect or edit it.")
            return
        if len(indices) > 1:
            self.selection_title_var.set(f"{len(indices)} songs selected")
            total = sum(self.songs[index].trackDuration for index in indices if 0 <= index < len(self.songs))
            self.selection_meta_var.set(f"Combined time {self.format_hhmmss(total)}")
            return
        index = indices[0]
        if not 0 <= index < len(self.songs):
            return
        song = self.songs[index]
        self.selection_title_var.set(song.name or "Untitled")
        details = [song.author or "Unknown artist", song.beatmapper or "Unknown mapper"]
        if song.difficultyText:
            details.append(song.difficultyText)
        self.selection_meta_var.set("\n".join(details))


def main() -> None:
    core.install_global_exception_hooks()
    app = ModernPlaylistEditorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
