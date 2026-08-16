"""
Instagram Logo & Crop Tool — GUI
================================
A simple point-and-click window for instagram_logo_tool.py, with:
  - A live preview: see the crop + caption + logo before you save anything
  - Drag the logo directly on the preview to reposition it
  - A caption/template system: color bar or side panel + headline/subtitle
    text (like the promo-graphic templates you see on Instagram)
  - Named presets for both logos and caption templates (e.g. "Brand A")
  - Remembers your last-used folders/settings between sessions

SETUP (one time):
    1. Keep this file, "instagram_logo_tool.py", and the "fonts" folder
       all in the SAME folder.
    2. Install the required libraries (Command Prompt):
           pip install pillow pillow-heif
       (tkinter comes built-in with Python on Windows, nothing extra needed.
        pillow-heif adds support for iPhone .heic/.heif photos.)

RUN:
    Double-click this file, OR in Command Prompt:
           python gui_app.py
"""

import os
import sys
import json
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
from PIL import Image, ImageTk

# Make sure we can import the processing functions regardless of how the
# script is launched (double-click vs command line).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from instagram_logo_tool import (
        process_photo,
        batch_process,
        build_preview_with_overlay,
        create_test_logo,
        NAMED_POSITIONS,
        IMAGE_EXTENSIONS,
        OUTPUT_FORMAT_CHOICES,
    )
except ImportError:
    messagebox.showerror(
        "Missing file",
        "Could not find instagram_logo_tool.py.\n\n"
        "Make sure gui_app.py is saved in the SAME folder as instagram_logo_tool.py.",
    )
    raise


CROP_LABELS = {
    "No cropping (keep original)": None,
    "Square (1:1) — 1080x1080": "square",
    "Portrait (4:5) — 1080x1350": "portrait",
    "Landscape (1.91:1) — 1080x566": "landscape",
    "Story/Reel (9:16) — 1080x1920": "story",
}
CROP_LABELS_REVERSE = {v: k for k, v in CROP_LABELS.items()}

FOCUS_OPTIONS = ["center", "top", "bottom"]

CAPTION_LAYOUT_LABELS = {
    "No caption/template": None,
    "Bottom color bar": "bottom_bar",
    "Side color panel": "side_panel",
}
CAPTION_LAYOUT_LABELS_REVERSE = {v: k for k, v in CAPTION_LAYOUT_LABELS.items()}

OUTPUT_FORMAT_LABELS = {
    "JPG (recommended — converts HEIC/etc. too)": "jpg",
    "Match input file format": "match_input",
    "PNG (keeps transparency)": "png",
}
OUTPUT_FORMAT_LABELS_REVERSE = {v: k for k, v in OUTPUT_FORMAT_LABELS.items()}

# ---------------------------------------------------------------------------
# Settings persistence — saved next to the script (or next to the .exe, if
# this has been packaged with PyInstaller).
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(_BASE_DIR, "instagram_tool_settings.json")

DEFAULT_CONFIG = {
    "paths": {"input": "", "logo": "", "output": ""},
    "mode": "batch",
    "crop_format": "portrait",
    "crop_focus": "center",
    "output_format": "jpg",
    "logo_scale": 0.15,
    "opacity": 1.0,
    "white_border": False,
    "position": list(NAMED_POSITIONS["bottom-right"]),
    "presets": {},
    "last_preset": "",
    "caption": {
        "layout": None,
        "bar_color": "#1a1a1a",
        "text_color": "#ffffff",
        "headline": "",
        "subtitle": "",
        "bar_ratio": 0.22,
        "side": "right",
        "vertical_text": False,
        "opacity": 1.0,
    },
    "caption_presets": {},
    "last_caption_preset": "",
}


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # Fill in any keys missing from an older config file version.
            merged = dict(DEFAULT_CONFIG)
            merged.update(cfg)
            merged["paths"] = {**DEFAULT_CONFIG["paths"], **cfg.get("paths", {})}
            merged["caption"] = {**DEFAULT_CONFIG["caption"], **cfg.get("caption", {})}
            return merged
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"⚠️ Could not save settings: {e}")


def _hex_to_rgb(hexstr):
    hexstr = (hexstr or "#000000").lstrip("#")
    if len(hexstr) != 6:
        return (0, 0, 0)
    try:
        return tuple(int(hexstr[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (0, 0, 0)


class LogWriter:
    """Redirects print() output into a thread-safe queue the GUI can poll."""

    def __init__(self, q):
        self.q = q

    def write(self, text):
        if text.strip():
            self.q.put(text)

    def flush(self):
        pass


class App(tk.Tk):
    PREVIEW_W = 440
    PREVIEW_H = 440

    def __init__(self):
        super().__init__()
        self.title("Instagram Logo & Crop Tool")
        self.geometry("1020x680")
        self.minsize(940, 560)

        self.log_queue = queue.Queue()
        self.config_data = load_config()
        self.presets = dict(self.config_data.get("presets", {}))
        self.caption_presets = dict(self.config_data.get("caption_presets", {}))
        self.logo_pos = list(self.config_data.get("position", [0.90, 0.90]))
        self._preview_source = None
        self._preview_photo_ref = None
        self._preview_offset = (0, 0)
        self._preview_disp_size = (0, 0)
        self._preview_img_size = (0, 0)
        self._crop_rect = (0, 0, 0, 0)

        self.mode = tk.StringVar(value=self.config_data.get("mode", "batch"))
        self.rotate_var = tk.IntVar(value=self.config_data.get("rotate", 0))

        self._build_ui()
        self._load_config_into_vars()
        self._refresh_preset_dropdown()
        self._refresh_caption_preset_dropdown()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(150, self._poll_log_queue)
        self._on_input_changed()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        main = ttk.Frame(self)
        main.pack(fill="both", expand=True)

        left = ttk.Frame(main)
        left.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        right = ttk.Frame(main)
        right.pack(side="left", fill="y", padx=10, pady=10)

        pad = {"padx": 8, "pady": 5}

        # --- Mode selector (stays visible above the tabs — it decides how the
        #     rest of the app behaves, so it shouldn't be buried in a tab) ---
        mode_frame = ttk.LabelFrame(left, text="What do you want to process?")
        mode_frame.pack(fill="x", pady=(0, 8))
        ttk.Radiobutton(mode_frame, text="📁 A whole folder of photos", variable=self.mode,
                         value="batch", command=self._on_input_changed).pack(side="left", padx=10, pady=6)
        ttk.Radiobutton(mode_frame, text="🖼 A single photo", variable=self.mode,
                         value="single", command=self._on_input_changed).pack(side="left", padx=10, pady=6)

        # --- Tabbed "taskbar" — each section lives on its own page instead of
        #     one long scrolling column. ---
        notebook = ttk.Notebook(left)
        notebook.pack(fill="both", expand=True, pady=(0, 8))

        source_tab = ttk.Frame(notebook, padding=8)
        crop_tab = ttk.Frame(notebook, padding=8)
        caption_tab = ttk.Frame(notebook, padding=8)
        logo_tab = ttk.Frame(notebook, padding=8)

        notebook.add(source_tab, text="  📂 Files & Presets  ")
        notebook.add(crop_tab, text="  ✂ Crop & Output  ")
        notebook.add(caption_tab, text="  🏷 Caption / Template  ")
        notebook.add(logo_tab, text="  🖋 Logo  ")

        # --- Paths (Files & Presets tab) ---
        paths_frame = ttk.LabelFrame(source_tab, text="Files & Folders")
        paths_frame.pack(fill="x", pady=(0, 8))

        self.input_label = ttk.Label(paths_frame, text="Photo folder:")
        self.input_label.grid(row=0, column=0, sticky="w", **pad)
        self.input_var = tk.StringVar()
        ttk.Entry(paths_frame, textvariable=self.input_var, width=48).grid(row=0, column=1, padx=4)
        ttk.Button(paths_frame, text="Browse...", command=self._browse_input).grid(row=0, column=2, padx=6)

        ttk.Label(paths_frame, text="Logo file (PNG):").grid(row=1, column=0, sticky="w", **pad)
        self.logo_var = tk.StringVar()
        ttk.Entry(paths_frame, textvariable=self.logo_var, width=48).grid(row=1, column=1, padx=4)
        ttk.Button(paths_frame, text="Browse...", command=self._browse_logo).grid(row=1, column=2, padx=6)

        self.output_label = ttk.Label(paths_frame, text="Output folder:")
        self.output_label.grid(row=2, column=0, sticky="w", **pad)
        self.output_var = tk.StringVar()
        ttk.Entry(paths_frame, textvariable=self.output_var, width=48).grid(row=2, column=1, padx=4)
        ttk.Button(paths_frame, text="Browse...", command=self._browse_output).grid(row=2, column=2, padx=6)

        # --- Logo presets (Files & Presets tab) ---
        preset_frame = ttk.LabelFrame(source_tab, text="Logo Presets (e.g. different brands/accounts)")
        preset_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(preset_frame, text="Preset:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(preset_frame, textvariable=self.preset_var,
                                          width=25, state="readonly")
        self.preset_combo.grid(row=0, column=1, sticky="w", padx=4)
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)
        ttk.Button(preset_frame, text="💾 Save As...", command=self._save_preset).grid(row=0, column=2, padx=4)
        ttk.Button(preset_frame, text="🗑 Delete", command=self._delete_preset).grid(row=0, column=3, padx=4)

        # --- Crop settings (Crop & Output tab) ---
        crop_frame = ttk.LabelFrame(crop_tab, text="Crop for Instagram")
        crop_frame.pack(fill="x", pady=(0, 8))

        ttk.Label(crop_frame, text="Format:").grid(row=0, column=0, sticky="w", **pad)
        self.crop_var = tk.StringVar(value=list(CROP_LABELS.keys())[0])
        crop_combo = ttk.Combobox(crop_frame, textvariable=self.crop_var, values=list(CROP_LABELS.keys()),
                                   width=30, state="readonly")
        crop_combo.grid(row=0, column=1, sticky="w", padx=4)
        crop_combo.bind("<<ComboboxSelected>>", self._on_setting_changed)

        ttk.Label(crop_frame, text="Keep which part (if cropping height):").grid(row=1, column=0, sticky="w", **pad)
        self.focus_var = tk.StringVar(value="center")
        focus_combo = ttk.Combobox(crop_frame, textvariable=self.focus_var, values=FOCUS_OPTIONS,
                                    width=15, state="readonly")
        focus_combo.grid(row=1, column=1, sticky="w", padx=4)
        focus_combo.bind("<<ComboboxSelected>>", self._on_setting_changed)

        ttk.Label(crop_frame, text="Save as:").grid(row=2, column=0, sticky="w", **pad)
        self.output_format_var = tk.StringVar(value=list(OUTPUT_FORMAT_LABELS.keys())[0])
        output_format_combo = ttk.Combobox(crop_frame, textvariable=self.output_format_var,
                                            values=list(OUTPUT_FORMAT_LABELS.keys()),
                                            width=38, state="readonly")
        output_format_combo.grid(row=2, column=1, sticky="w", padx=4)
        output_format_combo.bind("<<ComboboxSelected>>", self._on_setting_changed)

        # --- Rotate (Crop & Output tab) ---
        rotate_frame = ttk.LabelFrame(crop_tab, text="Rotate")
        rotate_frame.pack(fill="x", pady=(0, 8))

        turn_row = ttk.Frame(rotate_frame)
        turn_row.grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(6, 2))
        ttk.Button(turn_row, text="⟲ Rotate Left 90°", command=lambda: self._quick_rotate(-90)).pack(side="left", padx=(0, 6))
        ttk.Button(turn_row, text="⟳ Rotate Right 90°", command=lambda: self._quick_rotate(90)).pack(side="left", padx=6)
        ttk.Button(turn_row, text="↻ 180°", command=lambda: self._quick_rotate(180)).pack(side="left", padx=6)
        ttk.Button(turn_row, text="Reset", command=self._reset_rotate).pack(side="left", padx=6)
        self.rotate_label = ttk.Label(turn_row, text="0°", width=6)
        self.rotate_label.pack(side="left", padx=(10, 0))

        ttk.Label(rotate_frame, text="Straighten (fine tune):").grid(row=1, column=0, sticky="w", **pad)
        self.fine_rotate_var = tk.DoubleVar(value=self.config_data.get("fine_rotate", 0.0))
        fine_scale = ttk.Scale(rotate_frame, from_=-15, to=15, orient="horizontal",
                                variable=self.fine_rotate_var, length=220,
                                command=lambda _v: self._on_fine_rotate_changed())
        fine_scale.grid(row=1, column=1, sticky="w", padx=4)
        self.fine_rotate_label = ttk.Label(rotate_frame, text="0.0°", width=6)
        self.fine_rotate_label.grid(row=1, column=2, sticky="w")

        # --- Caption / Template (Caption / Template tab) ---
        caption_frame = ttk.LabelFrame(caption_tab, text="Caption / Text Template (color bar or panel + text)")
        caption_frame.pack(fill="x", pady=(0, 8))

        ttk.Label(caption_frame, text="Layout:").grid(row=0, column=0, sticky="w", **pad)
        self.caption_layout_var = tk.StringVar(value=list(CAPTION_LAYOUT_LABELS.keys())[0])
        layout_combo = ttk.Combobox(caption_frame, textvariable=self.caption_layout_var,
                                     values=list(CAPTION_LAYOUT_LABELS.keys()), width=22, state="readonly")
        layout_combo.grid(row=0, column=1, sticky="w", padx=4)
        layout_combo.bind("<<ComboboxSelected>>", self._on_setting_changed)

        ttk.Label(caption_frame, text="Side panel: which side / rotate text:").grid(row=0, column=2, sticky="w", padx=(16, 4))
        self.caption_side_var = tk.StringVar(value="right")
        side_combo = ttk.Combobox(caption_frame, textvariable=self.caption_side_var,
                                   values=["left", "right"], width=6, state="readonly")
        side_combo.grid(row=0, column=3, sticky="w", padx=4)
        side_combo.bind("<<ComboboxSelected>>", self._on_setting_changed)
        self.caption_vertical_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(caption_frame, text="Rotate", variable=self.caption_vertical_var,
                         command=self._on_setting_changed).grid(row=0, column=4, sticky="w", padx=4)

        ttk.Label(caption_frame, text="Headline:").grid(row=1, column=0, sticky="w", **pad)
        self.caption_headline_var = tk.StringVar(value="")
        headline_entry = ttk.Entry(caption_frame, textvariable=self.caption_headline_var, width=38)
        headline_entry.grid(row=1, column=1, columnspan=3, sticky="w", padx=4)
        headline_entry.bind("<KeyRelease>", self._on_setting_changed)

        ttk.Label(caption_frame, text="Subtitle:").grid(row=2, column=0, sticky="w", **pad)
        self.caption_subtitle_var = tk.StringVar(value="")
        subtitle_entry = ttk.Entry(caption_frame, textvariable=self.caption_subtitle_var, width=38)
        subtitle_entry.grid(row=2, column=1, columnspan=3, sticky="w", padx=4)
        subtitle_entry.bind("<KeyRelease>", self._on_setting_changed)

        ttk.Label(caption_frame, text="Colors:").grid(row=3, column=0, sticky="w", **pad)
        self.caption_bar_color = tk.StringVar(value="#1a1a1a")
        self.bar_color_btn = tk.Button(caption_frame, text="Bar/Panel", width=10,
                                        bg=self.caption_bar_color.get(), command=self._pick_bar_color)
        self.bar_color_btn.grid(row=3, column=1, sticky="w", padx=4)
        self.caption_text_color = tk.StringVar(value="#ffffff")
        self.text_color_btn = tk.Button(caption_frame, text="Text", width=10,
                                         bg=self.caption_text_color.get(), command=self._pick_text_color)
        self.text_color_btn.grid(row=3, column=2, sticky="w", padx=4)

        ttk.Label(caption_frame, text="Bar/panel size (%):").grid(row=4, column=0, sticky="w", **pad)
        self.caption_bar_ratio_var = tk.IntVar(value=22)
        ttk.Scale(caption_frame, from_=10, to=45, variable=self.caption_bar_ratio_var, orient="horizontal",
                  length=160, command=self._on_setting_changed).grid(row=4, column=1, columnspan=2, sticky="w", padx=4)
        ttk.Label(caption_frame, textvariable=self.caption_bar_ratio_var).grid(row=4, column=3, sticky="w")

        ttk.Label(caption_frame, text="Bar opacity (%):").grid(row=5, column=0, sticky="w", **pad)
        self.caption_opacity_var = tk.IntVar(value=100)
        ttk.Scale(caption_frame, from_=40, to=100, variable=self.caption_opacity_var, orient="horizontal",
                  length=160, command=self._on_setting_changed).grid(row=5, column=1, columnspan=2, sticky="w", padx=4)
        ttk.Label(caption_frame, textvariable=self.caption_opacity_var).grid(row=5, column=3, sticky="w")

        # Caption/template presets
        cap_preset_row = ttk.Frame(caption_frame)
        cap_preset_row.grid(row=6, column=0, columnspan=5, sticky="w", padx=4, pady=(6, 4))
        ttk.Label(cap_preset_row, text="Template:").pack(side="left", padx=(4, 4))
        self.caption_preset_var = tk.StringVar()
        self.caption_preset_combo = ttk.Combobox(cap_preset_row, textvariable=self.caption_preset_var,
                                                  width=22, state="readonly")
        self.caption_preset_combo.pack(side="left", padx=4)
        self.caption_preset_combo.bind("<<ComboboxSelected>>", self._on_caption_preset_selected)
        ttk.Button(cap_preset_row, text="💾 Save As...", command=self._save_caption_preset).pack(side="left", padx=4)
        ttk.Button(cap_preset_row, text="🗑 Delete", command=self._delete_caption_preset).pack(side="left", padx=4)

        # --- Logo settings (Logo tab) ---
        logo_frame = ttk.LabelFrame(logo_tab, text="Logo Settings")
        logo_frame.pack(fill="x", pady=(0, 8))

        ttk.Label(logo_frame, text="Size (% of photo width):").grid(row=0, column=0, sticky="w", **pad)
        self.scale_var = tk.IntVar(value=15)
        ttk.Scale(logo_frame, from_=5, to=40, variable=self.scale_var, orient="horizontal",
                  length=200, command=self._on_setting_changed).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(logo_frame, textvariable=self.scale_var).grid(row=0, column=2, sticky="w")

        ttk.Label(logo_frame, text="Opacity (%):").grid(row=1, column=0, sticky="w", **pad)
        self.opacity_var = tk.IntVar(value=100)
        ttk.Scale(logo_frame, from_=10, to=100, variable=self.opacity_var, orient="horizontal",
                  length=200, command=self._on_setting_changed).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(logo_frame, textvariable=self.opacity_var).grid(row=1, column=2, sticky="w")

        self.border_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(logo_frame, text="Add white border behind logo", variable=self.border_var,
                         command=self._on_setting_changed).grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=6)

        # --- Run button + progress ---
        run_frame = ttk.Frame(left)
        run_frame.pack(fill="x", pady=(0, 8))
        self.run_button = ttk.Button(run_frame, text="▶ Run", command=self._on_run)
        self.run_button.pack(side="left", padx=4)
        self.progress = ttk.Progressbar(run_frame, mode="indeterminate", length=380)
        self.progress.pack(side="left", padx=10)

        # --- Log output ---
        log_frame = ttk.LabelFrame(left, text="Log")
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, height=8, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)

        # --- Preview (right side) ---
        preview_frame = ttk.LabelFrame(right, text="Live Preview — drag the logo to reposition it")
        preview_frame.pack()
        self.preview_canvas = tk.Canvas(preview_frame, width=self.PREVIEW_W, height=self.PREVIEW_H,
                                         bg="#282828", highlightthickness=0)
        self.preview_canvas.pack(padx=8, pady=8)
        self.preview_canvas.bind("<Button-1>", self._on_canvas_drag)
        self.preview_canvas.bind("<B1-Motion>", self._on_canvas_drag)

        quick_frame = ttk.Frame(preview_frame)
        quick_frame.pack(pady=(0, 8))
        ttk.Label(quick_frame, text="Quick position:").pack(side="left", padx=(4, 6))
        for label, key in [("↖", "top-left"), ("↗", "top-right"), ("⊙", "center"),
                            ("↙", "bottom-left"), ("↘", "bottom-right")]:
            ttk.Button(quick_frame, text=label, width=3,
                       command=lambda k=key: self._set_named_position(k)).pack(side="left", padx=2)

    # ------------------------------------------------------------------
    # Color pickers
    # ------------------------------------------------------------------
    def _pick_bar_color(self):
        _, hexstr = colorchooser.askcolor(color=self.caption_bar_color.get(), title="Choose bar/panel color")
        if hexstr:
            self.caption_bar_color.set(hexstr)
            self.bar_color_btn.config(bg=hexstr)
            self._refresh_preview()

    def _pick_text_color(self):
        _, hexstr = colorchooser.askcolor(color=self.caption_text_color.get(), title="Choose text color")
        if hexstr:
            self.caption_text_color.set(hexstr)
            self.text_color_btn.config(bg=hexstr)
            self._refresh_preview()

    # ------------------------------------------------------------------
    # Config <-> UI
    # ------------------------------------------------------------------
    def _load_config_into_vars(self):
        cfg = self.config_data
        self.input_var.set(cfg["paths"].get("input", ""))
        self.logo_var.set(cfg["paths"].get("logo", ""))
        self.output_var.set(cfg["paths"].get("output", ""))
        self.crop_var.set(CROP_LABELS_REVERSE.get(cfg.get("crop_format"), list(CROP_LABELS.keys())[0]))
        self.focus_var.set(cfg.get("crop_focus", "center"))
        self.output_format_var.set(
            OUTPUT_FORMAT_LABELS_REVERSE.get(cfg.get("output_format", "jpg"), list(OUTPUT_FORMAT_LABELS.keys())[0])
        )
        self.scale_var.set(round(cfg.get("logo_scale", 0.15) * 100))
        self.opacity_var.set(round(cfg.get("opacity", 1.0) * 100))
        self.border_var.set(cfg.get("white_border", False))
        self.rotate_var.set(cfg.get("rotate", 0))
        self.fine_rotate_var.set(cfg.get("fine_rotate", 0.0))
        self.rotate_label.config(text=f"{self.rotate_var.get()}°")
        self.fine_rotate_label.config(text=f"{self.fine_rotate_var.get():.1f}°")
        self._toggle_mode_labels()
        last_preset = cfg.get("last_preset", "")
        if last_preset in self.presets:
            self.preset_var.set(last_preset)

        cap = cfg.get("caption", {})
        self.caption_layout_var.set(CAPTION_LAYOUT_LABELS_REVERSE.get(cap.get("layout"), list(CAPTION_LAYOUT_LABELS.keys())[0]))
        self.caption_bar_color.set(cap.get("bar_color", "#1a1a1a"))
        self.caption_text_color.set(cap.get("text_color", "#ffffff"))
        self.caption_headline_var.set(cap.get("headline", ""))
        self.caption_subtitle_var.set(cap.get("subtitle", ""))
        self.caption_bar_ratio_var.set(round(cap.get("bar_ratio", 0.22) * 100))
        self.caption_side_var.set(cap.get("side", "right"))
        self.caption_vertical_var.set(cap.get("vertical_text", False))
        self.caption_opacity_var.set(round(cap.get("opacity", 1.0) * 100))
        self.bar_color_btn.config(bg=self.caption_bar_color.get())
        self.text_color_btn.config(bg=self.caption_text_color.get())
        last_cap_preset = cfg.get("last_caption_preset", "")
        if last_cap_preset in self.caption_presets:
            self.caption_preset_var.set(last_cap_preset)

    def _gather_config(self):
        return {
            "paths": {
                "input": self.input_var.get(),
                "logo": self.logo_var.get(),
                "output": self.output_var.get(),
            },
            "mode": self.mode.get(),
            "crop_format": CROP_LABELS[self.crop_var.get()],
            "crop_focus": self.focus_var.get(),
            "output_format": OUTPUT_FORMAT_LABELS[self.output_format_var.get()],
            "logo_scale": self.scale_var.get() / 100.0,
            "opacity": self.opacity_var.get() / 100.0,
            "white_border": self.border_var.get(),
            "position": list(self.logo_pos),
            "rotate": self.rotate_var.get(),
            "fine_rotate": self.fine_rotate_var.get(),
            "presets": self.presets,
            "last_preset": self.preset_var.get(),
            "caption": {
                "layout": CAPTION_LAYOUT_LABELS[self.caption_layout_var.get()],
                "bar_color": self.caption_bar_color.get(),
                "text_color": self.caption_text_color.get(),
                "headline": self.caption_headline_var.get(),
                "subtitle": self.caption_subtitle_var.get(),
                "bar_ratio": self.caption_bar_ratio_var.get() / 100.0,
                "side": self.caption_side_var.get(),
                "vertical_text": self.caption_vertical_var.get(),
                "opacity": self.caption_opacity_var.get() / 100.0,
            },
            "caption_presets": self.caption_presets,
            "last_caption_preset": self.caption_preset_var.get(),
        }

    def _on_close(self):
        save_config(self._gather_config())
        self.destroy()

    # ------------------------------------------------------------------
    # Logo presets
    # ------------------------------------------------------------------
    def _refresh_preset_dropdown(self):
        self.preset_combo["values"] = list(self.presets.keys())

    def _on_preset_selected(self, event=None):
        name = self.preset_var.get()
        p = self.presets.get(name)
        if not p:
            return
        self.logo_var.set(p.get("logo_path", ""))
        self.scale_var.set(round(p.get("logo_scale", 0.15) * 100))
        self.opacity_var.set(round(p.get("opacity", 1.0) * 100))
        self.border_var.set(p.get("white_border", False))
        self.logo_pos = list(p.get("position", [0.90, 0.90]))
        self._refresh_preview()

    def _ask_text_input(self, title, prompt):
        """
        A small custom "type a name" popup, used instead of tkinter's
        built-in simpledialog — on some Windows setups (high DPI / display
        scaling), simpledialog's window renders too small and its OK
        button ends up clipped off-screen. This version has a fixed,
        generous size so that can't happen.
        """
        result = {"value": None}

        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry("360x150")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(dialog, text=prompt).pack(padx=16, pady=(20, 6), anchor="w")
        name_var = tk.StringVar()
        entry = ttk.Entry(dialog, textvariable=name_var, width=40)
        entry.pack(padx=16, pady=(0, 16), fill="x")
        entry.focus_set()

        def on_ok(event=None):
            result["value"] = name_var.get().strip()
            dialog.destroy()

        def on_cancel(event=None):
            dialog.destroy()

        button_row = ttk.Frame(dialog)
        button_row.pack(pady=(0, 10))
        ttk.Button(button_row, text="OK", command=on_ok).pack(side="left", padx=6)
        ttk.Button(button_row, text="Cancel", command=on_cancel).pack(side="left", padx=6)

        entry.bind("<Return>", on_ok)
        dialog.bind("<Escape>", on_cancel)

        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - 180
        y = self.winfo_y() + (self.winfo_height() // 2) - 75
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        dialog.wait_window()
        return result["value"]

    def _save_preset(self):
        name = self._ask_text_input("Save Preset", "Preset name (e.g. 'Brand A'):")
        if not name:
            return
        self.presets[name] = {
            "logo_path": self.logo_var.get().strip(),
            "logo_scale": self.scale_var.get() / 100.0,
            "opacity": self.opacity_var.get() / 100.0,
            "white_border": self.border_var.get(),
            "position": list(self.logo_pos),
        }
        self._refresh_preset_dropdown()
        self.preset_var.set(name)
        save_config(self._gather_config())
        messagebox.showinfo("Saved", f"Preset '{name}' saved.")

    def _delete_preset(self):
        name = self.preset_var.get()
        if not name or name not in self.presets:
            messagebox.showinfo("No preset selected", "Choose a preset from the dropdown first.")
            return
        if messagebox.askyesno("Delete preset", f"Delete preset '{name}'?"):
            del self.presets[name]
            self._refresh_preset_dropdown()
            self.preset_var.set("")
            save_config(self._gather_config())

    # ------------------------------------------------------------------
    # Caption/template presets
    # ------------------------------------------------------------------
    def _refresh_caption_preset_dropdown(self):
        self.caption_preset_combo["values"] = list(self.caption_presets.keys())

    def _on_caption_preset_selected(self, event=None):
        name = self.caption_preset_var.get()
        p = self.caption_presets.get(name)
        if not p:
            return
        self.caption_layout_var.set(CAPTION_LAYOUT_LABELS_REVERSE.get(p.get("layout"), list(CAPTION_LAYOUT_LABELS.keys())[0]))
        self.caption_bar_color.set(p.get("bar_color", "#1a1a1a"))
        self.caption_text_color.set(p.get("text_color", "#ffffff"))
        self.caption_headline_var.set(p.get("headline", ""))
        self.caption_subtitle_var.set(p.get("subtitle", ""))
        self.caption_bar_ratio_var.set(round(p.get("bar_ratio", 0.22) * 100))
        self.caption_side_var.set(p.get("side", "right"))
        self.caption_vertical_var.set(p.get("vertical_text", False))
        self.caption_opacity_var.set(round(p.get("opacity", 1.0) * 100))
        self.bar_color_btn.config(bg=self.caption_bar_color.get())
        self.text_color_btn.config(bg=self.caption_text_color.get())
        self._refresh_preview()

    def _save_caption_preset(self):
        name = self._ask_text_input("Save Caption Template", "Template name (e.g. 'Weekend Special'):")
        if not name:
            return
        self.caption_presets[name] = {
            "layout": CAPTION_LAYOUT_LABELS[self.caption_layout_var.get()],
            "bar_color": self.caption_bar_color.get(),
            "text_color": self.caption_text_color.get(),
            "headline": self.caption_headline_var.get(),
            "subtitle": self.caption_subtitle_var.get(),
            "bar_ratio": self.caption_bar_ratio_var.get() / 100.0,
            "side": self.caption_side_var.get(),
            "vertical_text": self.caption_vertical_var.get(),
            "opacity": self.caption_opacity_var.get() / 100.0,
        }
        self._refresh_caption_preset_dropdown()
        self.caption_preset_var.set(name)
        save_config(self._gather_config())
        messagebox.showinfo("Saved", f"Caption template '{name}' saved.")

    def _delete_caption_preset(self):
        name = self.caption_preset_var.get()
        if not name or name not in self.caption_presets:
            messagebox.showinfo("No template selected", "Choose a caption template from the dropdown first.")
            return
        if messagebox.askyesno("Delete template", f"Delete caption template '{name}'?"):
            del self.caption_presets[name]
            self._refresh_caption_preset_dropdown()
            self.caption_preset_var.set("")
            save_config(self._gather_config())

    # ------------------------------------------------------------------
    # Path selection
    # ------------------------------------------------------------------
    def _toggle_mode_labels(self):
        if self.mode.get() == "batch":
            self.input_label.config(text="Photo folder:")
            self.output_label.config(text="Output folder:")
        else:
            self.input_label.config(text="Photo file:")
            self.output_label.config(text="Output file (optional):")

    def _browse_input(self):
        if self.mode.get() == "batch":
            path = filedialog.askdirectory(title="Select photo folder")
        else:
            path = filedialog.askopenfilename(
                title="Select photo",
                filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.tiff *.webp *.heic *.heif")],
            )
        if path:
            self.input_var.set(path)
            self._on_input_changed()

    def _browse_logo(self):
        path = filedialog.askopenfilename(title="Select logo (PNG)", filetypes=[("PNG images", "*.png")])
        if path:
            self.logo_var.set(path)
            self._refresh_preview()

    def _browse_output(self):
        if self.mode.get() == "batch":
            path = filedialog.askdirectory(title="Select output folder")
        else:
            path = filedialog.asksaveasfilename(
                title="Save output as", defaultextension=".jpg",
                filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png")],
            )
        if path:
            self.output_var.set(path)

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------
    def _on_input_changed(self):
        self._toggle_mode_labels()
        self._load_preview_source()
        self._refresh_preview()

    def _on_setting_changed(self, *_):
        self._refresh_preview()

    def _quick_rotate(self, delta):
        self.rotate_var.set((self.rotate_var.get() + delta) % 360)
        self.rotate_label.config(text=f"{self.rotate_var.get()}°")
        self._refresh_preview()

    def _reset_rotate(self):
        self.rotate_var.set(0)
        self.fine_rotate_var.set(0.0)
        self.rotate_label.config(text="0°")
        self.fine_rotate_label.config(text="0.0°")
        self._refresh_preview()

    def _on_fine_rotate_changed(self):
        self.fine_rotate_label.config(text=f"{self.fine_rotate_var.get():.1f}°")
        self._refresh_preview()

    def _total_rotate(self):
        return self.rotate_var.get() + self.fine_rotate_var.get()

    def _get_caption_kwargs(self):
        layout = CAPTION_LAYOUT_LABELS.get(self.caption_layout_var.get())
        if not layout:
            return None
        return dict(
            layout=layout,
            bar_color=_hex_to_rgb(self.caption_bar_color.get()),
            text_color=_hex_to_rgb(self.caption_text_color.get()),
            headline=self.caption_headline_var.get(),
            subtitle=self.caption_subtitle_var.get(),
            bar_ratio=self.caption_bar_ratio_var.get() / 100.0,
            side=self.caption_side_var.get(),
            vertical_text=self.caption_vertical_var.get(),
            opacity=self.caption_opacity_var.get() / 100.0,
        )

    def _load_preview_source(self):
        self._preview_source = None
        path = self.input_var.get().strip()
        if not path or not os.path.exists(path):
            return
        try:
            if self.mode.get() == "batch":
                if os.path.isdir(path):
                    candidates = sorted(
                        p for p in os.listdir(path)
                        if os.path.splitext(p)[1].lower() in IMAGE_EXTENSIONS
                    )
                    if candidates:
                        self._preview_source = Image.open(os.path.join(path, candidates[0])).convert("RGBA")
            else:
                if os.path.isfile(path):
                    self._preview_source = Image.open(path).convert("RGBA")
        except Exception as e:
            self._preview_source = None
            print(f"⚠️ Could not load preview: {e}")

    def _refresh_preview(self):
        canvas = self.preview_canvas
        canvas.delete("all")

        if self._preview_source is None:
            canvas.create_text(
                self.PREVIEW_W // 2, self.PREVIEW_H // 2,
                text="Select a photo (or folder)\nto see a live preview",
                fill="#aaaaaa", justify="center", font=("Segoe UI", 11),
            )
            return

        crop_format = CROP_LABELS.get(self.crop_var.get())
        logo_path = self.logo_var.get().strip() or None

        try:
            img, crop_rect = build_preview_with_overlay(
                self._preview_source,
                logo_path=logo_path,
                crop_format=crop_format,
                crop_focus=self.focus_var.get(),
                logo_scale=self.scale_var.get() / 100.0,
                opacity=self.opacity_var.get() / 100.0,
                white_border=self.border_var.get(),
                position=tuple(self.logo_pos),
                caption=self._get_caption_kwargs(),
                rotate=self._total_rotate(),
                max_dim=self.PREVIEW_W - 20,
            )
        except Exception as e:
            canvas.create_text(
                self.PREVIEW_W // 2, self.PREVIEW_H // 2,
                text=f"Preview error:\n{e}", fill="#ff8080", justify="center",
            )
            return

        self._crop_rect = crop_rect  # (left, top, w, h) in img's own pixel space
        self._render_preview(img)

    def _render_preview(self, pil_img):
        cw, ch = self.PREVIEW_W, self.PREVIEW_H
        scale = min(cw / pil_img.width, ch / pil_img.height)
        dw = max(int(pil_img.width * scale), 1)
        dh = max(int(pil_img.height * scale), 1)
        disp = pil_img.resize((dw, dh), Image.Resampling.LANCZOS)

        background = Image.new("RGB", (cw, ch), (40, 40, 40))
        offset = ((cw - dw) // 2, (ch - dh) // 2)
        if disp.mode == "RGBA":
            background.paste(disp, offset, disp)
        else:
            background.paste(disp, offset)

        self._preview_photo_ref = ImageTk.PhotoImage(background)  # keep a reference!
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(0, 0, anchor="nw", image=self._preview_photo_ref)

        self._preview_offset = offset
        self._preview_disp_size = (dw, dh)
        self._preview_img_size = pil_img.size  # native size of img, before canvas-fit scaling

    def _on_canvas_drag(self, event):
        if self._preview_source is None:
            return
        dw, dh = self._preview_disp_size
        if dw == 0 or dh == 0:
            return
        ox, oy = self._preview_offset
        iw, ih = self._preview_img_size
        crop_left, crop_top, crop_w, crop_h = getattr(self, "_crop_rect", (0, 0, iw, ih))
        if crop_w == 0 or crop_h == 0:
            return

        # canvas pixel -> preview image's own pixel coords -> fraction within crop box
        img_x = (event.x - ox) * (iw / dw)
        img_y = (event.y - oy) * (ih / dh)
        x_frac = (img_x - crop_left) / crop_w
        y_frac = (img_y - crop_top) / crop_h
        x_frac = min(max(x_frac, 0.0), 1.0)
        y_frac = min(max(y_frac, 0.0), 1.0)
        self.logo_pos = [x_frac, y_frac]
        self._refresh_preview()

    def _set_named_position(self, key):
        self.logo_pos = list(NAMED_POSITIONS[key])
        self._refresh_preview()

    # ------------------------------------------------------------------
    # Run / processing
    # ------------------------------------------------------------------
    def _log(self, msg):
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg if msg.endswith("\n") else msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self._log(msg)
        except queue.Empty:
            pass
        self.after(150, self._poll_log_queue)

    def _on_run(self):
        input_path = self.input_var.get().strip()
        logo_path = self.logo_var.get().strip()
        output_path = self.output_var.get().strip()

        if not input_path:
            messagebox.showwarning("Missing info", "Please choose a photo (or folder) first.")
            return
        if not os.path.exists(input_path):
            messagebox.showerror("Not found", f"Could not find:\n{input_path}")
            return

        if logo_path and not os.path.exists(logo_path):
            if messagebox.askyesno("Logo not found",
                                    "Logo file not found. Create a test logo to use instead?"):
                base_dir = os.path.dirname(input_path) if os.path.isfile(input_path) else input_path
                logo_path = create_test_logo(os.path.join(base_dir, "test_logo.png"))
                self.logo_var.set(logo_path)
            else:
                return

        settings = dict(
            crop_format=CROP_LABELS[self.crop_var.get()],
            crop_focus=self.focus_var.get(),
            output_format=OUTPUT_FORMAT_LABELS[self.output_format_var.get()],
            logo_scale=self.scale_var.get() / 100.0,
            opacity=self.opacity_var.get() / 100.0,
            white_border=self.border_var.get(),
            logo_position=tuple(self.logo_pos),
            caption=self._get_caption_kwargs(),
            rotate=self._total_rotate(),
        )

        self.run_button.config(state="disabled")
        self.progress.start(12)
        self._log("Starting...")

        thread = threading.Thread(
            target=self._run_job,
            args=(input_path, logo_path or None, output_path or None, settings),
            daemon=True,
        )
        thread.start()

    def _run_job(self, input_path, logo_path, output_path, settings):
        old_stdout = sys.stdout
        sys.stdout = LogWriter(self.log_queue)
        try:
            if self.mode.get() == "batch":
                batch_process(
                    photo_folder=input_path,
                    logo_path=logo_path,
                    output_folder=output_path,
                    **settings,
                )
            else:
                process_photo(
                    photo_path=input_path,
                    logo_path=logo_path,
                    output_path=output_path,
                    **settings,
                )
            self.log_queue.put("🎉 All done!")
        except Exception as e:
            self.log_queue.put(f"❌ Error: {e}")
        finally:
            sys.stdout = old_stdout
            self.after(0, self._job_finished)

    def _job_finished(self):
        self.progress.stop()
        self.run_button.config(state="normal")


if __name__ == "__main__":
    app = App()
    app.mainloop()
