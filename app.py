"""Sierpiński Studio – graficzny generator trójkąta Sierpińskiego.

Uruchomienie:  .venv\\Scripts\\python.exe app.py
"""
from __future__ import annotations

import os
import queue
import re
import threading
import time
from dataclasses import replace
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageTk

from sierpinski import (
    MAX_DEPTH,
    Settings,
    checkerboard,
    export_dimensions,
    export_supersample,
    render,
    save_svg,
    smallest_side,
    triangle_count,
)

APP_TITLE = "Sierpiński Studio"
ACCENT = "#7C5CFF"
ACCENT_HOVER = "#6846F0"
ACCENT_TEXT = ("#5B3FE0", "#B9A6FF")
CARD_BG = ("#FFFFFF", "#1B1830")
SIDEBAR_BG = ("#EEEDF5", "#120F22")
MUTED = ("#6B6880", "#8E8AA8")

PRESETS = [
    ("Lawenda", "#A78BFA", "#0F0B1E"),
    ("Neon", "#22E4FF", "#071018"),
    ("Zachód", "#FF7A6B", "#1C0F1F"),
    ("Las", "#4ADE80", "#0B1A12"),
    ("Złoto", "#F5C542", "#161310"),
    ("Klasyk", "#111111", "#FFFFFF"),
]

FILETYPES = [
    ("PNG (przezroczystość)", "*.png"),
    ("SVG – grafika wektorowa", "*.svg"),
    ("WebP (bezstratny)", "*.webp"),
    ("TIFF", "*.tif *.tiff"),
    ("JPEG", "*.jpg *.jpeg"),
    ("BMP", "*.bmp"),
]
RASTER_EXT = {".png", ".webp", ".tif", ".tiff", ".jpg", ".jpeg", ".bmp"}
NO_ALPHA_EXT = {".jpg", ".jpeg", ".bmp"}
HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")


def fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


# --------------------------------------------------------------------------- #
# Komponenty
# --------------------------------------------------------------------------- #
class Card(ctk.CTkFrame):
    """Zaokrąglona sekcja panelu bocznego z nagłówkiem."""

    def __init__(self, master, title: str):
        super().__init__(master, corner_radius=14, fg_color=CARD_BG)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self, text=title.upper(), anchor="w", text_color=ACCENT_TEXT,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        self._row = 1

    def add(self, widget, pady=(6, 6)):
        widget.grid(row=self._row, column=0, sticky="ew", padx=16, pady=pady)
        self._row += 1
        return widget


class LabeledSlider(ctk.CTkFrame):
    """Suwak z etykietą, bieżącą wartością i opcjonalnymi przyciskami −/+."""

    def __init__(self, master, text, from_, to, steps, value, fmt, command,
                 stepper: float | None = None):
        super().__init__(master, fg_color="transparent")
        self._fmt, self._command = fmt, command
        self._from, self._to, self._step = from_, to, stepper
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text=text, anchor="w").grid(row=0, column=0, sticky="w")
        self.value_label = ctk.CTkLabel(
            self, text="", anchor="e", text_color=ACCENT_TEXT,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.value_label.grid(row=0, column=1, sticky="e")

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        row.grid_columnconfigure(1, weight=1)
        self.slider = ctk.CTkSlider(
            row, from_=from_, to=to, number_of_steps=steps, command=self._changed,
            button_color=ACCENT, button_hover_color=ACCENT_HOVER, progress_color=ACCENT,
        )
        self.slider.set(value)
        self.slider.grid(row=0, column=1, sticky="ew")
        if stepper:
            for col, sign, txt in ((0, -1, "−"), (2, 1, "+")):
                ctk.CTkButton(
                    row, text=txt, width=28, height=26, corner_radius=8,
                    fg_color=("gray85", "#2A2645"), hover_color=("gray75", "#3A3560"),
                    text_color=("gray10", "gray95"), font=ctk.CTkFont(size=15, weight="bold"),
                    command=lambda s=sign: self.nudge(s),
                ).grid(row=0, column=col, padx=(0, 6) if col == 0 else (6, 0))
        self.refresh_label()

    def _changed(self, value):
        self.refresh_label()
        self._command(value)

    def nudge(self, sign: int):
        value = min(self._to, max(self._from, self.slider.get() + sign * self._step))
        self.slider.set(value)
        self._changed(value)

    def get(self) -> float:
        return self.slider.get()

    def set(self, value):
        self.slider.set(value)
        self.refresh_label()

    def refresh_label(self):
        self.value_label.configure(text=self._fmt(self.slider.get()))


class ColorPicker(ctk.CTkFrame):
    """Próbnik koloru (otwiera systemowy wybierak) + pole HEX."""

    def __init__(self, master, text: str, initial: str, command):
        super().__init__(master, fg_color="transparent")
        self._command = command
        self._color = initial.upper()
        self.grid_columnconfigure(1, weight=1)
        self.title = ctk.CTkLabel(self, text=text, anchor="w")
        self.title.grid(row=0, column=0, columnspan=2, sticky="w")

        self.swatch = ctk.CTkButton(
            self, text="", width=44, height=30, corner_radius=8, border_width=2,
            border_color=("gray70", "gray40"), fg_color=self._color,
            hover_color=self._color, command=self._choose,
        )
        self.swatch.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(2, 0))
        self.var = ctk.StringVar(value=self._color)
        self.entry = ctk.CTkEntry(self, textvariable=self.var, height=30,
                                  font=ctk.CTkFont(family="Consolas", size=13))
        self.entry.grid(row=1, column=1, sticky="ew", pady=(2, 0))
        self.entry.bind("<Return>", self._on_entry)
        self.entry.bind("<FocusOut>", self._on_entry)

    def _choose(self):
        _rgb, hx = colorchooser.askcolor(color=self._color, title=self.title.cget("text"),
                                         parent=self.winfo_toplevel())
        if hx:
            self.set(hx, notify=True)

    def _on_entry(self, _event=None):
        value = self.var.get().strip()
        if not value.startswith("#"):
            value = "#" + value
        if HEX_RE.fullmatch(value):
            if value.upper() != self._color:
                self.set(value, notify=True)
        else:
            self.var.set(self._color)

    def set(self, hx: str, notify: bool = False):
        self._color = hx.upper()
        self.var.set(self._color)
        self.swatch.configure(fg_color=self._color, hover_color=self._color)
        if notify:
            self._command(self._color)

    def get(self) -> str:
        return self._color

    def set_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.swatch.configure(state=state)
        self.entry.configure(state=state)
        self.title.configure(text_color=("gray10", "gray90") if enabled else MUTED)


# --------------------------------------------------------------------------- #
# Aplikacja
# --------------------------------------------------------------------------- #
class SierpinskiApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1320x860")
        self.minsize(1000, 660)

        self.settings = Settings()
        self._results: "queue.Queue[tuple]" = queue.Queue()
        self._req_lock = threading.Lock()
        self._req_event = threading.Event()
        self._pending = None
        self._render_after = None
        self._preview_img = None
        self._last_area = (0, 0)
        self._exporting = False

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_preview()
        self._sync_widgets()

        threading.Thread(target=self._preview_worker, daemon=True).start()
        self.after(30, self._poll_results)
        self.after(300, self._set_icon)
        self.bind_all("<Control-s>", lambda _e: self.save())
        self.bind_all("<Control-S>", lambda _e: self.save())

    # ------------------------------------------------------------- UI build
    def _build_sidebar(self):
        side = ctk.CTkScrollableFrame(self, width=340, corner_radius=0, fg_color=SIDEBAR_BG)
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_columnconfigure(0, weight=1)
        r = 0

        head = ctk.CTkFrame(side, fg_color="transparent")
        head.grid(row=r, column=0, sticky="ew", padx=14, pady=(16, 10)); r += 1
        ctk.CTkLabel(head, text="△  Sierpiński Studio", anchor="w",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(head, text="Generator fraktala w czasie rzeczywistym", anchor="w",
                     text_color=MUTED, font=ctk.CTkFont(size=12)).pack(anchor="w")

        # --- Parametry
        card = Card(side, "Parametry fraktala")
        card.grid(row=r, column=0, sticky="ew", padx=12, pady=6); r += 1
        self.depth_slider = card.add(LabeledSlider(
            card, "Głębokość  n", 0, MAX_DEPTH, MAX_DEPTH, self.settings.depth,
            fmt=lambda v: str(int(round(v))), command=self._on_depth, stepper=1))
        self.margin_slider = card.add(LabeledSlider(
            card, "Margines", 0, 25, 25, self.settings.margin * 100,
            fmt=lambda v: f"{int(round(v))} %", command=self._on_margin))
        self.opacity_slider = card.add(LabeledSlider(
            card, "Krycie trójkątów", 5, 100, 19, 100,
            fmt=lambda v: f"{int(round(v))} %", command=self._on_opacity), pady=(6, 14))

        # --- Kolory
        card = Card(side, "Kolory")
        card.grid(row=r, column=0, sticky="ew", padx=12, pady=6); r += 1
        self.fg_picker = card.add(ColorPicker(card, "Kolor trójkątów", self.settings.fg,
                                              lambda c: self._update(fg=c)))
        self.bg_picker = card.add(ColorPicker(card, "Kolor tła", self.settings.bg,
                                              lambda c: self._update(bg=c)))
        self.transparent_switch = card.add(ctk.CTkSwitch(
            card, text="Przezroczyste tło", command=self._on_transparent,
            progress_color=ACCENT))
        card.add(ctk.CTkButton(
            card, text="⇄  Zamień kolory", height=30, fg_color="transparent",
            border_width=1, border_color=("gray70", "#3A3560"), text_color=("gray10", "gray90"),
            hover_color=("gray88", "#2A2645"), command=self._swap_colors))

        ctk.CTkLabel(card, text="Gotowe palety", anchor="w", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).grid(row=card._row, column=0, sticky="w",
                                                     padx=16, pady=(8, 0))
        card._row += 1
        grid = ctk.CTkFrame(card, fg_color="transparent")
        card.add(grid, pady=(4, 14))
        for idx, (name, fg, bg) in enumerate(PRESETS):
            grid.grid_columnconfigure(idx % 3, weight=1, uniform="p")
            ctk.CTkButton(
                grid, text=f"▲ {name}", height=34, corner_radius=10, fg_color=bg,
                hover_color=bg, text_color=fg, border_width=2, border_color=fg,
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda f=fg, b=bg: self._apply_preset(f, b),
            ).grid(row=idx // 3, column=idx % 3, sticky="ew", padx=3, pady=3)

        # --- Opcje
        card = Card(side, "Opcje")
        card.grid(row=r, column=0, sticky="ew", padx=12, pady=6); r += 1
        self.aa_switch = card.add(ctk.CTkSwitch(
            card, text="Wygładzanie krawędzi (antyaliasing)", progress_color=ACCENT,
            command=lambda: self._update(antialias=bool(self.aa_switch.get()))))
        self.inv_switch = card.add(ctk.CTkSwitch(
            card, text="Odwrócony (wierzchołek w dół)", progress_color=ACCENT,
            command=lambda: self._update(inverted=bool(self.inv_switch.get()))))
        ctk.CTkLabel(card, text="Format obrazu", anchor="w").grid(
            row=card._row, column=0, sticky="w", padx=16, pady=(6, 0))
        card._row += 1
        self.fit_seg = card.add(ctk.CTkSegmentedButton(
            card, values=["Kwadrat", "Dopasowany"], command=self._on_fit,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER), pady=(4, 14))

        # --- Eksport
        card = Card(side, "Eksport")
        card.grid(row=r, column=0, sticky="ew", padx=12, pady=6); r += 1
        self.size_slider = card.add(LabeledSlider(
            card, "Rozdzielczość", 256, 8192, (8192 - 256) // 128, self.settings.size,
            fmt=self._size_label, command=self._on_size))
        self.detail_label = card.add(ctk.CTkLabel(
            card, text="", anchor="w", justify="left", text_color=MUTED,
            font=ctk.CTkFont(size=12)), pady=(0, 4))
        self.save_btn = card.add(ctk.CTkButton(
            card, text="⬇  Zapisz do pliku…", height=44, corner_radius=12,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=15, weight="bold"), command=self.save), pady=(8, 4))
        self.progress = ctk.CTkProgressBar(card, height=6, progress_color=ACCENT)
        self.progress.set(0)
        self._progress_row = card._row
        card._row += 1
        card.add(ctk.CTkLabel(
            card, text="Ctrl+S  •  PNG/WebP/TIFF/SVG zachowują przezroczystość",
            text_color=MUTED, font=ctk.CTkFont(size=11), anchor="w"), pady=(2, 14))
        self._export_card = card

        # --- Wygląd
        card = Card(side, "Aplikacja")
        card.grid(row=r, column=0, sticky="ew", padx=12, pady=(6, 16)); r += 1
        self.theme_seg = card.add(ctk.CTkSegmentedButton(
            card, values=["Ciemny", "Jasny", "System"], command=self._on_theme,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER))
        self.theme_seg.set("Ciemny")
        card.add(ctk.CTkButton(
            card, text="↺  Przywróć ustawienia domyślne", height=30, fg_color="transparent",
            border_width=1, border_color=("gray70", "#3A3560"), text_color=("gray10", "gray90"),
            hover_color=("gray88", "#2A2645"), command=self._reset), pady=(6, 14))

    def _build_preview(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=20, pady=(16, 10))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(main, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(bar, text="Podgląd", font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")
        self.chips = {}
        for key in ("time", "size", "count", "depth"):
            chip = ctk.CTkLabel(bar, text="", corner_radius=10, fg_color=CARD_BG, height=28,
                                font=ctk.CTkFont(size=12, weight="bold"), text_color=ACCENT_TEXT)
            chip.pack(side="right", padx=(8, 0), ipadx=10)
            self.chips[key] = chip

        self.canvas = ctk.CTkFrame(main, corner_radius=18, fg_color=("#DCDAE8", "#0A0816"),
                                   border_width=1, border_color=("#C9C6DA", "#221E3A"))
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.preview_label = ctk.CTkLabel(self.canvas, text="Generowanie…", text_color=MUTED)
        self.preview_label.place(relx=0.5, rely=0.5, anchor="center")
        self.canvas.bind("<Configure>", self._on_resize)

        self.status = ctk.CTkLabel(main, text="Gotowy.", anchor="w", text_color=MUTED,
                                   font=ctk.CTkFont(size=12))
        self.status.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def _set_icon(self):
        try:
            icon = render(replace(self.settings, depth=4, margin=0.02, transparent=True,
                                  fg=ACCENT), 64, 64, supersample=4)
            self._icon = ImageTk.PhotoImage(icon)
            self.iconphoto(True, self._icon)
        except Exception:
            pass

    # ------------------------------------------------------------- helpers
    def _scaling(self) -> float:
        try:
            return float(ctk.ScalingTracker.get_widget_scaling(self))
        except Exception:
            return 1.0

    def _size_label(self, value: float) -> str:
        w, h = export_dimensions(replace(self.settings, size=int(round(value))))
        return f"{w} × {h} px"

    def _sync_widgets(self):
        """Ustawia wszystkie kontrolki zgodnie z self.settings."""
        s = self.settings
        self.depth_slider.set(s.depth)
        self.margin_slider.set(s.margin * 100)
        self.opacity_slider.set(round(s.fg_alpha / 255 * 100))
        self.fg_picker.set(s.fg)
        self.bg_picker.set(s.bg)
        (self.transparent_switch.select if s.transparent else self.transparent_switch.deselect)()
        (self.aa_switch.select if s.antialias else self.aa_switch.deselect)()
        (self.inv_switch.select if s.inverted else self.inv_switch.deselect)()
        self.fit_seg.set("Kwadrat" if s.fit == "square" else "Dopasowany")
        self.size_slider.set(s.size)
        self.bg_picker.set_enabled(not s.transparent)
        self._refresh_details()

    def _refresh_details(self):
        s = self.settings
        side = smallest_side(s)
        warn = "  ⚠ poniżej 1 px – zwiększ rozdzielczość" if side < 1 else ""
        self.detail_label.configure(text=f"Najmniejszy trójkąt w pliku: {side:.1f} px{warn}")
        self.chips["depth"].configure(text=f"n = {s.depth}")
        self.chips["count"].configure(text=f"{fmt_int(triangle_count(s.depth))} trójkątów")
        self.chips["size"].configure(text=self._size_label(s.size))

    def _update(self, **changes):
        new = replace(self.settings, **changes)
        if new == self.settings:
            return
        self.settings = new
        self._refresh_details()
        self.schedule_render()

    # ------------------------------------------------------------- callbacks
    def _on_depth(self, v):
        self._update(depth=int(round(v)))

    def _on_margin(self, v):
        self._update(margin=round(v) / 100)

    def _on_opacity(self, v):
        self._update(fg_alpha=int(round(v / 100 * 255)))

    def _on_size(self, v):
        self._update(size=int(round(v)))

    def _on_fit(self, value):
        self._update(fit="square" if value == "Kwadrat" else "fit")
        self.size_slider.refresh_label()

    def _on_transparent(self):
        transparent = bool(self.transparent_switch.get())
        self.bg_picker.set_enabled(not transparent)
        self._update(transparent=transparent)

    def _swap_colors(self):
        fg, bg = self.settings.bg, self.settings.fg
        self.fg_picker.set(fg)
        self.bg_picker.set(bg)
        self._update(fg=fg, bg=bg)

    def _apply_preset(self, fg, bg):
        self.fg_picker.set(fg)
        self.bg_picker.set(bg)
        self._update(fg=fg, bg=bg)

    def _on_theme(self, value):
        ctk.set_appearance_mode({"Ciemny": "dark", "Jasny": "light"}.get(value, "system"))

    def _reset(self):
        self.settings = Settings()
        self._sync_widgets()
        self.schedule_render()
        self._set_status("Przywrócono ustawienia domyślne.")

    def _on_resize(self, event):
        area = (event.width, event.height)
        if abs(area[0] - self._last_area[0]) > 3 or abs(area[1] - self._last_area[1]) > 3:
            self._last_area = area
            self.schedule_render(delay=120)

    def _set_status(self, text: str, color=MUTED):
        self.status.configure(text=text, text_color=color)

    # ------------------------------------------------------------- preview rendering
    def schedule_render(self, delay: int = 30):
        """Debounce – przy szybkim przesuwaniu suwaka renderujemy tylko ostatni stan."""
        if self._render_after is not None:
            self.after_cancel(self._render_after)
        self._render_after = self.after(delay, self._submit_render)

    def _submit_render(self):
        self._render_after = None
        pad = int(28 * self._scaling())
        aw = self.canvas.winfo_width() - 2 * pad
        ah = self.canvas.winfo_height() - 2 * pad
        if aw < 40 or ah < 40:
            self.schedule_render(100)
            return
        with self._req_lock:
            self._pending = (self.settings, aw, ah)
        self._req_event.set()

    def _preview_worker(self):
        """Jeden wątek roboczy; zawsze bierze najnowsze żądanie (starsze pomija)."""
        while True:
            self._req_event.wait()
            with self._req_lock:
                req, self._pending = self._pending, None
                self._req_event.clear()
            if req is None:
                continue
            s, aw, ah = req
            try:
                t0 = time.perf_counter()
                w, h = export_dimensions(s)
                k = min(aw / w, ah / h)
                pw, ph = max(1, int(w * k)), max(1, int(h * k))
                img = render(s, pw, ph, supersample=3 if s.antialias else 1)
                if s.transparent:
                    board = checkerboard(pw, ph).convert("RGBA")
                    img = Image.alpha_composite(board, img).convert("RGB")
                self._results.put(("preview", img, time.perf_counter() - t0))
            except Exception as exc:  # pragma: no cover
                self._results.put(("error", f"Błąd podglądu: {exc}"))

    def _poll_results(self):
        try:
            while True:
                msg = self._results.get_nowait()
                kind = msg[0]
                if kind == "preview":
                    self._show_preview(msg[1], msg[2])
                elif kind == "progress":
                    self.progress.set(msg[1])
                elif kind == "saved":
                    self._export_finished()
                    _, path, dt, extra = msg
                    self._set_status(f"✔ Zapisano: {path}  ({dt:.2f} s){extra}",
                                     ("#1E8E5A", "#4ADE80"))
                elif kind == "export_error":
                    self._export_finished()
                    self._set_status(f"✖ Błąd zapisu: {msg[1]}", ("#C0392B", "#FF7A6B"))
                    messagebox.showerror("Błąd zapisu", msg[1], parent=self)
                elif kind == "error":
                    self._set_status(msg[1], ("#C0392B", "#FF7A6B"))
        except queue.Empty:
            pass
        self.after(30, self._poll_results)

    def _show_preview(self, img: Image.Image, dt: float):
        scale = self._scaling()
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                               size=(img.width / scale, img.height / scale))
        self.preview_label.configure(image=ctk_img, text="")
        self._preview_img = ctk_img  # trzymamy referencję
        self.chips["time"].configure(text=f"{dt * 1000:.0f} ms")

    # ------------------------------------------------------------- export
    def save(self):
        if self._exporting:
            return
        s = self.settings
        path = filedialog.asksaveasfilename(
            parent=self, title="Zapisz trójkąt Sierpińskiego", defaultextension=".png",
            initialfile=f"sierpinski_n{s.depth}.png", filetypes=FILETYPES)
        if not path:
            return
        ext = Path(path).suffix.lower()
        if ext not in RASTER_EXT and ext != ".svg":
            messagebox.showerror("Nieobsługiwany format",
                                 f"Format „{ext}” nie jest obsługiwany.\n"
                                 "Wybierz PNG, SVG, WebP, TIFF, JPEG lub BMP.", parent=self)
            return
        if s.transparent and ext in NO_ALPHA_EXT:
            if not messagebox.askyesno(
                    "Brak przezroczystości",
                    f"Format {ext.upper()[1:]} nie obsługuje przezroczystości.\n"
                    f"Tło zostanie wypełnione kolorem {s.bg}. Kontynuować?", parent=self):
                return
            s = replace(s, transparent=False)

        self._exporting = True
        self.save_btn.configure(state="disabled", text="Zapisywanie…")
        self.progress.set(0)
        self.progress.grid(row=self._progress_row, column=0, sticky="ew", padx=16, pady=(2, 2))
        self._set_status(f"Generowanie {self._size_label(s.size)}…")
        threading.Thread(target=self._export_worker, args=(s, path, ext), daemon=True).start()

    def _export_worker(self, s: Settings, path: str, ext: str):
        try:
            t0 = time.perf_counter()
            w, h = export_dimensions(s)
            extra = ""
            if ext == ".svg":
                eff = save_svg(s, w, h, path)
                self._results.put(("progress", 1.0))
                if eff < s.depth:
                    extra = f"  •  SVG ograniczony do n={eff} (mniejsze detale niewidoczne)"
            else:
                ss = export_supersample(w, h) if s.antialias else 1
                img = render(s, w, h, ss,
                             progress=lambda f: self._results.put(("progress", f)))
                opts = {
                    ".png": {"compress_level": 6},
                    ".webp": {"lossless": True},
                    ".jpg": {"quality": 95, "subsampling": 0},
                    ".jpeg": {"quality": 95, "subsampling": 0},
                    ".tif": {"compression": "tiff_deflate"},
                    ".tiff": {"compression": "tiff_deflate"},
                }.get(ext, {})
                if ext in NO_ALPHA_EXT and img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(path, **opts)
            size_kb = os.path.getsize(path) / 1024
            extra = f"  •  {size_kb:,.0f} KB".replace(",", " ") + extra
            self._results.put(("saved", path, time.perf_counter() - t0, extra))
        except Exception as exc:
            self._results.put(("export_error", str(exc)))

    def _export_finished(self):
        self._exporting = False
        self.save_btn.configure(state="normal", text="⬇  Zapisz do pliku…")
        self.progress.grid_remove()


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = SierpinskiApp()
    app.mainloop()


if __name__ == "__main__":
    main()
