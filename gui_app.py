"""
Instagram Logo & Crop Tool — GUI
================================
A simple point-and-click window for instagram_logo_tool.py.

SETUP (one time):
    1. Keep this file in the SAME folder as "instagram_logo_tool.py".
    2. Install the required libraries (Command Prompt):
           pip install opencv-python pillow numpy
       (tkinter comes built-in with Python on Windows, nothing extra needed.)

RUN:
    Double-click this file, OR in Command Prompt:
           python gui_app.py
"""

import os
import sys
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Make sure we can import the processing functions regardless of how the
# script is launched (double-click vs command line).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from instagram_logo_tool import (
        process_photo,
        batch_process,
        create_test_logo,
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

FOCUS_OPTIONS = ["center", "top", "bottom"]
POSITION_OPTIONS = ["bottom-right", "bottom-left", "top-right", "top-left", "center"]


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
    def __init__(self):
        super().__init__()
        self.title("Instagram Logo & Crop Tool")
        self.geometry("640x680")
        self.resizable(False, False)

        self.log_queue = queue.Queue()
        self.mode = tk.StringVar(value="batch")  # "batch" or "single"

        self._build_ui()
        self.after(150, self._poll_log_queue)

    # ------------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # --- Mode selector ---
        mode_frame = ttk.LabelFrame(self, text="What do you want to process?")
        mode_frame.pack(fill="x", **pad)
        ttk.Radiobutton(mode_frame, text="A whole folder of photos", variable=self.mode,
                         value="batch", command=self._toggle_mode).pack(side="left", padx=10, pady=6)
        ttk.Radiobutton(mode_frame, text="A single photo", variable=self.mode,
                         value="single", command=self._toggle_mode).pack(side="left", padx=10, pady=6)

        # --- Paths ---
        paths_frame = ttk.LabelFrame(self, text="Files & Folders")
        paths_frame.pack(fill="x", **pad)

        self.input_label = ttk.Label(paths_frame, text="Photo folder:")
        self.input_label.grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.input_var = tk.StringVar()
        ttk.Entry(paths_frame, textvariable=self.input_var, width=55).grid(row=0, column=1, padx=4)
        ttk.Button(paths_frame, text="Browse...", command=self._browse_input).grid(row=0, column=2, padx=6)

        ttk.Label(paths_frame, text="Logo file (PNG):").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.logo_var = tk.StringVar()
        ttk.Entry(paths_frame, textvariable=self.logo_var, width=55).grid(row=1, column=1, padx=4)
        ttk.Button(paths_frame, text="Browse...", command=self._browse_logo).grid(row=1, column=2, padx=6)

        self.output_label = ttk.Label(paths_frame, text="Output folder:")
        self.output_label.grid(row=2, column=0, sticky="w", padx=8, pady=6)
        self.output_var = tk.StringVar()
        ttk.Entry(paths_frame, textvariable=self.output_var, width=55).grid(row=2, column=1, padx=4)
        ttk.Button(paths_frame, text="Browse...", command=self._browse_output).grid(row=2, column=2, padx=6)

        # --- Crop settings ---
        crop_frame = ttk.LabelFrame(self, text="Crop for Instagram")
        crop_frame.pack(fill="x", **pad)

        ttk.Label(crop_frame, text="Format:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.crop_var = tk.StringVar(value=list(CROP_LABELS.keys())[0])
        ttk.Combobox(crop_frame, textvariable=self.crop_var, values=list(CROP_LABELS.keys()),
                     width=32, state="readonly").grid(row=0, column=1, sticky="w", padx=4)

        ttk.Label(crop_frame, text="Keep which part (if cropping height):").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.focus_var = tk.StringVar(value="center")
        ttk.Combobox(crop_frame, textvariable=self.focus_var, values=FOCUS_OPTIONS,
                     width=15, state="readonly").grid(row=1, column=1, sticky="w", padx=4)

        # --- Logo settings ---
        logo_frame = ttk.LabelFrame(self, text="Logo Settings")
        logo_frame.pack(fill="x", **pad)

        ttk.Label(logo_frame, text="Size (% of photo width):").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.scale_var = tk.IntVar(value=15)
        ttk.Scale(logo_frame, from_=5, to=40, variable=self.scale_var, orient="horizontal",
                  length=200).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(logo_frame, textvariable=self.scale_var).grid(row=0, column=2, sticky="w")

        ttk.Label(logo_frame, text="Opacity (%):").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.opacity_var = tk.IntVar(value=100)
        ttk.Scale(logo_frame, from_=10, to=100, variable=self.opacity_var, orient="horizontal",
                  length=200).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(logo_frame, textvariable=self.opacity_var).grid(row=1, column=2, sticky="w")

        ttk.Label(logo_frame, text="Position:").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        self.position_var = tk.StringVar(value="bottom-right")
        ttk.Combobox(logo_frame, textvariable=self.position_var, values=POSITION_OPTIONS,
                     width=15, state="readonly").grid(row=2, column=1, sticky="w", padx=4)

        self.border_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(logo_frame, text="Add white border behind logo",
                         variable=self.border_var).grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=6)

        # --- Run button + progress ---
        run_frame = ttk.Frame(self)
        run_frame.pack(fill="x", **pad)
        self.run_button = ttk.Button(run_frame, text="▶ Run", command=self._on_run)
        self.run_button.pack(side="left", padx=4)
        self.progress = ttk.Progressbar(run_frame, mode="indeterminate", length=400)
        self.progress.pack(side="left", padx=10)

        # --- Log output ---
        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=12, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)

        self._toggle_mode()

    # ------------------------------------------------------------------
    def _toggle_mode(self):
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

    def _browse_logo(self):
        path = filedialog.askopenfilename(title="Select logo (PNG)", filetypes=[("PNG images", "*.png")])
        if path:
            self.logo_var.set(path)

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

    # ------------------------------------------------------------------
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
                logo_path = create_test_logo(
                    os.path.join(os.path.dirname(input_path) if os.path.isfile(input_path) else input_path,
                                 "test_logo.png"))
                self.logo_var.set(logo_path)
            else:
                return

        crop_format = CROP_LABELS[self.crop_var.get()]

        settings = dict(
            crop_format=crop_format,
            crop_focus=self.focus_var.get(),
            logo_scale=self.scale_var.get() / 100.0,
            opacity=self.opacity_var.get() / 100.0,
            white_border=self.border_var.get(),
            logo_position=self.position_var.get(),
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
