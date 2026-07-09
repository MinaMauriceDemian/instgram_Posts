"""
Instagram Logo & Crop Tool — GUI
================================
A simple point-and-click window for instagram_logo_tool.py, with:
  - A live preview: see the crop + logo before you save anything
  - Drag the logo directly on the preview to reposition it
  - Named presets (e.g. "Brand A") you can save and reload instantly
  - Remembers your last-used folders/settings between sessions

SETUP (one time):
    1. Keep this file in the SAME folder as "instagram_logo_tool.py".
    2. Install the required library (Command Prompt):
           pip install pillow
       (tkinter comes built-in with Python on Windows, nothing extra needed.)

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
from tkinter import ttk, filedialog, messagebox
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
    "logo_scale": 0.15,
    "opacity": 1.0,
    "white_border": False,
    "position": list(NAMED_POSITIONS["bottom-right"]),
    "presets": {},
    "last_preset": "",
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
            return merged
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"⚠️ Could not save settings: {e}")


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
        self.geometry("1100x720")
        self.resizable(False, False)

        self.log_queue = queue.Queue()
        self.config_data = load_config()
        self.presets = dict(self.config_data.get("presets", {}))
        self.logo_pos = list(self.config_data.get("position", [0.90, 0.90]))
        self._preview_source = None
        self._preview_photo_ref = None
        self._preview_offset = (0, 0)
        self._preview_disp_size = (0, 0)
        self._preview_img_size = (0, 0)
        self._crop_rect = (0, 0, 0, 0)

        self.mode = tk.StringVar(value=self.config_data.get("mode", "batch"))

        self._build_ui()
        self._load_config_into_vars()
        self._refresh_preset_dropdown()
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

        # --- Mode selector ---
        mode_frame = ttk.LabelFrame(left, text="What do you want to process?")
        mode_frame.pack(fill="x", pady=(0, 8))
        ttk.Radiobutton(mode_frame, text="A whole folder of photos", variable=self.mode,
                         value="batch", command=self._on_input_changed).pack(side="left", padx=10, pady=6)
        ttk.Radiobutton(mode_frame, text="A single photo", variable=self.mode,
                         value="single", command=self._on_input_changed).pack(side="left", padx=10, pady=6)

        # --- Paths ---
        paths_frame = ttk.LabelFrame(left, text="Files & Folders")
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

        # --- Presets ---
        preset_frame = ttk.LabelFrame(left, text="Logo Presets (e.g. different brands/accounts)")
        preset_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(preset_frame, text="Preset:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(preset_frame, textvariable=self.preset_var,
                                          width=25, state="readonly")
        self.preset_combo.grid(row=0, column=1, sticky="w", padx=4)
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)
        ttk.Button(preset_frame, text="💾 Save As...", command=self._save_preset).grid(row=0, column=2, padx=4)
        ttk.Button(preset_frame, text="🗑 Delete", command=self._delete_preset).grid(row=0, column=3, padx=4)

        # --- Crop settings ---
        crop_frame = ttk.LabelFrame(left, text="Crop for Instagram")
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

        # --- Logo settings ---
        logo_frame = ttk.LabelFrame(left, text="Logo Settings")
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
        self.log_text = tk.Text(log_frame, height=10, state="disabled", wrap="word")
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
    # Config <-> UI
    # ------------------------------------------------------------------
    def _load_config_into_vars(self):
        cfg = self.config_data
        self.input_var.set(cfg["paths"].get("input", ""))
        self.logo_var.set(cfg["paths"].get("logo", ""))
        self.output_var.set(cfg["paths"].get("output", ""))
        self.crop_var.set(CROP_LABELS_REVERSE.get(cfg.get("crop_format"), list(CROP_LABELS.keys())[0]))
        self.focus_var.set(cfg.get("crop_focus", "center"))
        self.scale_var.set(round(cfg.get("logo_scale", 0.15) * 100))
        self.opacity_var.set(round(cfg.get("opacity", 1.0) * 100))
        self.border_var.set(cfg.get("white_border", False))
        self._toggle_mode_labels()
        last_preset = cfg.get("last_preset", "")
        if last_preset in self.presets:
            self.preset_var.set(last_preset)

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
            "logo_scale": self.scale_var.get() / 100.0,
            "opacity": self.opacity_var.get() / 100.0,
            "white_border": self.border_var.get(),
            "position": list(self.logo_pos),
            "presets": self.presets,
            "last_preset": self.preset_var.get(),
        }

    def _on_close(self):
        save_config(self._gather_config())
        self.destroy()

    # ------------------------------------------------------------------
    # Presets
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

    def _ask_preset_name(self):
        """
        A small custom "type a name" popup, used instead of tkinter's
        built-in simpledialog — on some Windows setups (high DPI / display
        scaling), simpledialog's window renders too small and its OK
        button ends up clipped off-screen. This version has a fixed,
        generous size so that can't happen.
        """
        result = {"value": None}

        dialog = tk.Toplevel(self)
        dialog.title("Save Preset")
        dialog.geometry("360x150")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(dialog, text="Preset name (e.g. 'Brand A'):").pack(padx=16, pady=(20, 6), anchor="w")
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

        # Center the dialog over the main window
        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - 180
        y = self.winfo_y() + (self.winfo_height() // 2) - 75
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        dialog.wait_window()
        return result["value"]

    def _save_preset(self):
        name = self._ask_preset_name()
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
                filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.tiff *.webp")],
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
            logo_scale=self.scale_var.get() / 100.0,
            opacity=self.opacity_var.get() / 100.0,
            white_border=self.border_var.get(),
            logo_position=tuple(self.logo_pos),
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
