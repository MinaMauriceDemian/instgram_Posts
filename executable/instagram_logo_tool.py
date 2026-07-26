"""
Instagram Logo & Crop Tool
==========================
Adds a logo/watermark AND a text caption/template (color bar + headline +
subtitle) to photos, and crops them to fit Instagram's standard aspect
ratios (square, portrait, landscape, story).

Works on a single photo or a whole folder of photos.

Requirements:
    pip install pillow

--------------------------------------------------------------------
QUICK START — scroll down to the "CONFIGURE YOUR SETTINGS HERE"
section near the bottom of this file and edit the paths/options,
then just run the script.

For a point-and-click interface with a live preview instead, use
gui_app.py (in the same folder).
--------------------------------------------------------------------
"""

from PIL import Image, ImageDraw, ImageFont
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# HEIC/HEIF support (iPhone photos) — Pillow can't open these natively, so
# we register pillow-heif's opener with Pillow if it's installed.
#   pip install pillow-heif
# ---------------------------------------------------------------------------
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:
    HEIC_SUPPORTED = False

# ---------------------------------------------------------------------------
# Base directory (works whether this is run as a plain script or bundled
# into a PyInstaller .exe) — used to find the bundled fonts.
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FONTS_DIR = os.path.join(_BASE_DIR, "fonts")

# ---------------------------------------------------------------------------
# Instagram's recommended output sizes (width, height) in pixels.
# ---------------------------------------------------------------------------
INSTAGRAM_FORMATS = {
    "square":    {"ratio": 1 / 1,    "size": (1080, 1080)},
    "portrait":  {"ratio": 4 / 5,    "size": (1080, 1350)},
    "landscape": {"ratio": 1.91 / 1, "size": (1080, 566)},
    "story":     {"ratio": 9 / 16,   "size": (1080, 1920)},
}

IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp", ".heic", ".heif"]

# Logo position is a (x_frac, y_frac) tuple: where the CENTER of the logo
# sits, as a fraction of the photo's width/height (0.0-1.0).
NAMED_POSITIONS = {
    "bottom-right": (0.90, 0.90),
    "bottom-left":  (0.10, 0.90),
    "top-right":    (0.90, 0.10),
    "top-left":     (0.10, 0.10),
    "center":       (0.50, 0.50),
}

DEFAULT_POSITION = NAMED_POSITIONS["bottom-right"]

CAPTION_LAYOUTS = ["bottom_bar", "side_panel"]

# ---------------------------------------------------------------------------
# OUTPUT FORMAT — what file type saved photos come out as.
#   "jpg"          -> always save as .jpg (recommended for HEIC/iPhone photos,
#                     since HEIC isn't viewable/uploadable most places)
#   "match_input"  -> keep the same format as the source photo (old behavior)
#   "png"          -> always save as .png (keeps transparency, larger files)
# ---------------------------------------------------------------------------
OUTPUT_FORMAT_CHOICES = ["jpg", "match_input", "png"]


def _resolve_output_extension(input_suffix, output_format="jpg"):
    input_suffix = input_suffix.lower()
    if output_format == "png":
        return ".png"
    if output_format == "match_input":
        # jpg/jpeg inputs always normalize to .jpg; everything else (including
        # heic) keeps its original extension.
        return ".jpg" if input_suffix in (".jpg", ".jpeg") else input_suffix
    # default: "jpg" — always save as a normal, widely-viewable JPG
    return ".jpg"


# ---------------------------------------------------------------------------
# FONTS
# ---------------------------------------------------------------------------
def _font_search_paths(filename):
    paths = [os.path.join(FONTS_DIR, filename)]
    meipass = getattr(sys, "_MEIPASS", None)  # PyInstaller onefile extraction dir
    if meipass:
        paths.append(os.path.join(meipass, "fonts", filename))
    return paths


def _load_font(filename, size, system_fallbacks=None):
    size = max(int(size), 1)
    for p in _font_search_paths(filename):
        try:
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        except Exception:
            continue
    for name in (system_fallbacks or []):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def get_headline_font(size):
    """Bold poster-style font for captions (bundled 'Anton', falls back to system bold)."""
    return _load_font("Anton-Regular.ttf", size, ["arialbd.ttf", "Arial Bold.ttf", "arial.ttf"])


def get_subtitle_font(size):
    """Regular-weight font for smaller caption text (bundled 'Open Sans', falls back to system)."""
    return _load_font("OpenSans-Regular.ttf", size, ["arial.ttf"])


# ---------------------------------------------------------------------------
# CROPPING
# ---------------------------------------------------------------------------
def compute_crop_box(width, height, fmt, focus="center"):
    """
    Work out the crop rectangle (left, top, right, bottom), in the given
    width/height's own pixel coordinates, for a given Instagram format,
    without actually cropping anything. Shared by the real crop function
    and the preview overlay.
    """
    if fmt not in INSTAGRAM_FORMATS:
        raise ValueError(f"Unknown format '{fmt}'. Choose from {list(INSTAGRAM_FORMATS)}")

    target_ratio = INSTAGRAM_FORMATS[fmt]["ratio"]
    current_ratio = width / height

    if current_ratio > target_ratio:
        new_width = int(height * target_ratio)
        left = (width - new_width) // 2
        return (left, 0, left + new_width, height)
    else:
        new_height = int(width / target_ratio)
        if focus == "top":
            top = 0
        elif focus == "bottom":
            top = height - new_height
        else:  # center
            top = (height - new_height) // 2
        return (0, top, width, top + new_height)


def crop_to_instagram_format(image, fmt="square", focus="center"):
    """
    Crop a PIL image (RGB/RGBA) to a given Instagram aspect ratio and resize
    it to Instagram's recommended pixel dimensions.
    """
    target_size = INSTAGRAM_FORMATS[fmt]["size"]
    box = compute_crop_box(image.width, image.height, fmt, focus)
    cropped = image.crop(box)
    resized = cropped.resize(target_size, Image.Resampling.LANCZOS)
    return resized


# ---------------------------------------------------------------------------
# SHARED HELPERS
# ---------------------------------------------------------------------------
def _prepare_logo(logo_path, target_width, opacity=1.0, white_border=False):
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception as e:
        raise ValueError(f"Could not read logo: {e}")

    logo_width = max(int(target_width), 1)
    logo_aspect = logo.width / logo.height
    logo_height = max(int(logo_width / logo_aspect), 1)
    logo_resized = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)

    if opacity < 1.0:
        alpha = logo_resized.split()[3]
        alpha = alpha.point(lambda p: int(p * opacity))
        logo_resized.putalpha(alpha)

    if white_border:
        bordered = Image.new(
            "RGBA",
            (logo_resized.width + 20, logo_resized.height + 20),
            (255, 255, 255, 200),
        )
        bordered.paste(logo_resized, (10, 10), logo_resized)
        logo_resized = bordered

    return logo_resized


def _resolve_position(position):
    if isinstance(position, str):
        return NAMED_POSITIONS.get(position, DEFAULT_POSITION)
    return position


def _clamped_paste_xy(x_frac, y_frac, region_width, region_height, logo_w, logo_h):
    half_w_frac = (logo_w / 2) / region_width if region_width else 0
    half_h_frac = (logo_h / 2) / region_height if region_height else 0
    x_frac = min(max(x_frac, half_w_frac), 1 - half_w_frac) if region_width > logo_w else 0.5
    y_frac = min(max(y_frac, half_h_frac), 1 - half_h_frac) if region_height > logo_h else 0.5
    pos_x = int(x_frac * region_width - logo_w / 2)
    pos_y = int(y_frac * region_height - logo_h / 2)
    return pos_x, pos_y


# ---------------------------------------------------------------------------
# LOGO / WATERMARK
# ---------------------------------------------------------------------------
def add_logo(photo, logo_path, logo_scale=0.15, opacity=1.0,
             white_border=False, position=DEFAULT_POSITION):
    """
    Paste a logo onto a PIL image (RGBA-safe).

    position: named string ("bottom-right", etc.) or (x_frac, y_frac) tuple
              giving the CENTER of the logo as a fraction of the photo.
    """
    photo = photo.convert("RGBA")
    photo_width, photo_height = photo.size

    logo_resized = _prepare_logo(logo_path, photo_width * logo_scale, opacity, white_border)
    x_frac, y_frac = _resolve_position(position)
    pos_x, pos_y = _clamped_paste_xy(
        x_frac, y_frac, photo_width, photo_height, logo_resized.width, logo_resized.height
    )

    result = photo.copy()
    result.paste(logo_resized, (pos_x, pos_y), logo_resized)
    return result


# ---------------------------------------------------------------------------
# CAPTION / TEMPLATE (color bar or side panel + headline/subtitle text)
# ---------------------------------------------------------------------------
def _draw_wrapped_text(draw, text, font, x, y, max_width, fill, line_spacing=1.15):
    """Word-wrap text to max_width and draw it, returning the y position after the last line."""
    if not text:
        return y
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        w_px = draw.textlength(test, font=font)
        if w_px <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)

    line_height = getattr(font, "size", 20) * line_spacing
    cy = y
    for line in lines:
        draw.text((x, cy), line, font=font, fill=fill)
        cy += line_height
    return cy


def _render_rotated_text(text, font, fill, angle=90):
    """Render text onto a tightly-cropped transparent image, then rotate it (for side panels)."""
    tmp = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp)
    bbox = tmp_draw.textbbox((0, 0), text, font=font)
    w = max(bbox[2] - bbox[0], 1)
    h = max(bbox[3] - bbox[1], 1)
    pad = 6
    text_img = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(text_img)
    d.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=fill)
    return text_img.rotate(angle, expand=True)


def build_caption_layer(width, height, layout=None, bar_color=(20, 20, 20),
                         text_color=(255, 255, 255), headline="", subtitle="",
                         bar_ratio=0.22, side="right", vertical_text=False, opacity=1.0):
    """
    Build a transparent RGBA layer (same size as the target photo) with a
    color bar/panel and headline/subtitle text drawn on it, ready to be
    pasted onto a photo. Returns an all-transparent layer if layout is
    None/"none" so callers don't need to special-case it.
    """
    width, height = max(int(width), 1), max(int(height), 1)
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if not layout or layout == "none":
        return layer

    draw = ImageDraw.Draw(layer)
    r, g, b = bar_color[:3]
    a = int(255 * max(0.0, min(opacity, 1.0)))

    if layout == "bottom_bar":
        bar_h = max(int(height * bar_ratio), 1)
        draw.rectangle((0, height - bar_h, width, height), fill=(r, g, b, a))

        pad_x = int(width * 0.05)
        headline_size = max(int(bar_h * 0.34), 10)
        subtitle_size = max(int(bar_h * 0.16), 8)
        hf = get_headline_font(headline_size)
        sf = get_subtitle_font(subtitle_size)

        text_y = height - bar_h + int(bar_h * 0.16)
        if headline:
            draw.text((pad_x, text_y), headline.upper(), font=hf, fill=text_color)
            text_y += int(headline_size * 1.05) + int(bar_h * 0.06)
        if subtitle:
            _draw_wrapped_text(draw, subtitle, sf, pad_x, text_y, width - 2 * pad_x, text_color)

    elif layout == "side_panel":
        panel_w = max(int(width * bar_ratio), 1)
        panel_left = 0 if side == "left" else width - panel_w
        draw.rectangle((panel_left, 0, panel_left + panel_w, height), fill=(r, g, b, a))
        pad = int(panel_w * 0.14)

        if vertical_text and headline:
            headline_size = max(int(panel_w * 0.30), 10)
            hf = get_headline_font(headline_size)
            rotated = _render_rotated_text(headline.upper(), hf, text_color, angle=90)
            if rotated.height > height * 0.92:
                scale = (height * 0.92) / rotated.height
                rotated = rotated.resize(
                    (max(int(rotated.width * scale), 1), max(int(rotated.height * scale), 1)),
                    Image.Resampling.LANCZOS,
                )
            rx = panel_left + (panel_w - rotated.width) // 2
            ry = (height - rotated.height) // 2
            layer.alpha_composite(rotated, (max(rx, 0), max(ry, 0)))
            if subtitle:
                subtitle_size = max(int(panel_w * 0.10), 8)
                sf = get_subtitle_font(subtitle_size)
                _draw_wrapped_text(
                    draw, subtitle, sf, panel_left + pad,
                    height - int(height * 0.16), panel_w - 2 * pad, text_color,
                )
        else:
            headline_size = max(int(panel_w * 0.17), 10)
            subtitle_size = max(int(panel_w * 0.10), 8)
            hf = get_headline_font(headline_size)
            sf = get_subtitle_font(subtitle_size)
            y = int(height * 0.08)
            if headline:
                y = _draw_wrapped_text(
                    draw, headline.upper(), hf, panel_left + pad, y,
                    panel_w - 2 * pad, text_color, line_spacing=1.08,
                )
                y += int(panel_w * 0.08)
            if subtitle:
                _draw_wrapped_text(draw, subtitle, sf, panel_left + pad, y, panel_w - 2 * pad, text_color)

    return layer


def add_caption(photo, layout=None, bar_color=(20, 20, 20), text_color=(255, 255, 255),
                 headline="", subtitle="", bar_ratio=0.22, side="right",
                 vertical_text=False, opacity=1.0):
    """
    Add a color bar/panel + headline/subtitle text to a photo. Returns the
    photo unchanged if layout is None/"none".
    """
    photo = photo.convert("RGBA").copy()
    if not layout or layout == "none":
        return photo
    layer = build_caption_layer(
        photo.width, photo.height, layout=layout, bar_color=bar_color,
        text_color=text_color, headline=headline, subtitle=subtitle,
        bar_ratio=bar_ratio, side=side, vertical_text=vertical_text, opacity=opacity,
    )
    photo.paste(layer, (0, 0), layer)
    return photo


# ---------------------------------------------------------------------------
# PREVIEW (used by the GUI, but also handy standalone)
# ---------------------------------------------------------------------------
def build_preview_with_overlay(source, logo_path=None, crop_format=None, crop_focus="center",
                                logo_scale=0.15, opacity=1.0, white_border=False,
                                position=DEFAULT_POSITION, caption=None,
                                max_dim=800, dim_strength=0.55):
    """
    Build a preview that shows the FULL original photo (nothing cut off),
    with a highlighted rectangle showing what the crop will keep, the
    caption bar/panel (if any), and the logo — both drawn at their actual
    relative positions within that rectangle.

    Args:
        source: a file path (str/Path) or an already-open PIL.Image
        caption: None, or a dict of build_caption_layer() keyword args
                 (layout, bar_color, text_color, headline, subtitle,
                 bar_ratio, side, vertical_text, opacity)
        max_dim: longest side of the returned preview, in pixels
        dim_strength: how dark the area outside the crop box is (0-1)

    Returns:
        (PIL.Image RGBA, crop_rect) where crop_rect is (left, top, width,
        height) in the RETURNED image's own pixel coordinates.
    """
    photo = Image.open(source).convert("RGBA") if not isinstance(source, Image.Image) else source.convert("RGBA")

    if max(photo.size) > max_dim:
        ratio = max_dim / max(photo.size)
        new_size = (max(int(photo.width * ratio), 1), max(int(photo.height * ratio), 1))
        photo = photo.resize(new_size, Image.Resampling.LANCZOS)

    if crop_format:
        crop_box = compute_crop_box(photo.width, photo.height, crop_format, crop_focus)
        crop_left, crop_top, crop_right, crop_bottom = crop_box
        crop_w, crop_h = crop_right - crop_left, crop_bottom - crop_top

        dim_layer = Image.new("RGBA", photo.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(dim_layer)
        draw.rectangle([0, 0, photo.width, photo.height], fill=(0, 0, 0, int(255 * dim_strength)))
        draw.rectangle(crop_box, fill=(0, 0, 0, 0))
        photo = Image.alpha_composite(photo, dim_layer)

        border_draw = ImageDraw.Draw(photo)
        border_width = max(2, photo.width // 300)
        border_draw.rectangle(crop_box, outline=(255, 255, 255, 255), width=border_width)
    else:
        crop_left, crop_top, crop_w, crop_h = 0, 0, photo.width, photo.height

    if caption and caption.get("layout") not in (None, "none"):
        cap_layer = build_caption_layer(crop_w, crop_h, **caption)
        photo.paste(cap_layer, (crop_left, crop_top), cap_layer)

    if logo_path and os.path.exists(logo_path):
        logo_resized = _prepare_logo(logo_path, crop_w * logo_scale, opacity, white_border)
        x_frac, y_frac = _resolve_position(position)
        rel_x, rel_y = _clamped_paste_xy(
            x_frac, y_frac, crop_w, crop_h, logo_resized.width, logo_resized.height
        )
        photo.paste(logo_resized, (crop_left + rel_x, crop_top + rel_y), logo_resized)

    return photo, (crop_left, crop_top, crop_w, crop_h)


# ---------------------------------------------------------------------------
# COMBINED PIPELINE (crop + caption + logo) FOR A SINGLE PHOTO
# ---------------------------------------------------------------------------
def process_photo(photo_path, logo_path, output_path=None,
                   crop_format=None, crop_focus="center",
                   logo_scale=0.15, opacity=1.0,
                   white_border=False, logo_position=DEFAULT_POSITION,
                   caption=None, jpeg_quality=95, output_format="jpg"):
    """
    Full pipeline: load photo -> (optional) crop -> (optional) caption
    bar/panel -> (optional) logo -> save.

    Args:
        crop_format: None or one of "square"/"portrait"/"landscape"/"story"
        caption: None, or a dict of build_caption_layer() keyword args
        jpeg_quality: output JPEG quality (1-100), only used for .jpg/.jpeg
        output_format: "jpg" (default, always save as .jpg — recommended for
            HEIC input), "match_input" (keep source format), or "png".
            Only applies when output_path isn't explicitly given; an
            explicit output_path's own extension always wins.

    Returns:
        output_path (str)
    """
    photo_path = Path(photo_path)
    photo = Image.open(photo_path).convert("RGBA")

    if crop_format:
        photo = crop_to_instagram_format(photo, fmt=crop_format, focus=crop_focus)

    if caption and caption.get("layout") not in (None, "none"):
        photo = add_caption(photo, **caption)

    if logo_path:
        photo = add_logo(
            photo, logo_path,
            logo_scale=logo_scale, opacity=opacity,
            white_border=white_border, position=logo_position,
        )

    if output_path is None:
        suffix_tag = f"_{crop_format}" if crop_format else ""
        ext = _resolve_output_extension(photo_path.suffix, output_format)
        output_path = str(photo_path.parent / f"{photo_path.stem}{suffix_tag}_ig{ext}")
    output_path = str(output_path)

    if output_path.lower().endswith((".jpg", ".jpeg", ".bmp")):
        flat = Image.new("RGB", photo.size, (255, 255, 255))
        flat.paste(photo, mask=photo.split()[3])
        if output_path.lower().endswith(".bmp"):
            flat.save(output_path)
        else:
            flat.save(output_path, "JPEG", quality=jpeg_quality)
    else:
        photo.save(output_path)

    print(f"✅ Saved: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# BATCH PROCESSING
# ---------------------------------------------------------------------------
def batch_process(photo_folder, logo_path=None, output_folder=None,
                   crop_format=None, crop_focus="center",
                   logo_scale=0.15, opacity=1.0,
                   white_border=False, logo_position=DEFAULT_POSITION,
                   caption=None, jpeg_quality=95, output_format="jpg"):
    """Run process_photo() over every image in a folder."""
    photo_folder = Path(photo_folder)
    print("=" * 60)
    print("📸 INSTAGRAM LOGO & CROP TOOL — BATCH MODE")
    print("=" * 60)
    print(f"📁 Input folder : {photo_folder}")
    print(f"🖼️  Logo         : {logo_path or '(none)'}")
    print(f"✂️  Crop format  : {crop_format or '(none — keep original ratio)'}")
    print(f"💾 Save as      : {output_format}")
    if caption and caption.get("layout") not in (None, "none"):
        print(f"🏷️  Caption      : {caption.get('layout')}")
    print(f"📊 Opacity      : {opacity * 100:.0f}%")
    print("-" * 60)

    if logo_path and not os.path.exists(logo_path):
        print(f"❌ Logo not found: {logo_path}")
        return

    if output_folder:
        os.makedirs(output_folder, exist_ok=True)
        print(f"📁 Output folder: {output_folder}")

    photo_files = sorted(
        p for p in photo_folder.iterdir()
        if p.suffix.lower() in IMAGE_EXTENSIONS
    )

    if not HEIC_SUPPORTED and any(p.suffix.lower() in (".heic", ".heif") for p in photo_files):
        print("⚠️  HEIC/HEIF files found but pillow-heif isn't installed.")
        print("    Run: pip install pillow-heif")
        print("    Those files will fail to open until it's installed.")
        print("-" * 60)

    if not photo_files:
        print(f"❌ No image files found in {photo_folder}")
        return

    print(f"📸 Found {len(photo_files)} images")
    print("-" * 60)

    success, errors = 0, 0
    for i, photo_path in enumerate(photo_files, 1):
        print(f"[{i}/{len(photo_files)}] {photo_path.name}", end=" ... ")
        try:
            if output_folder:
                suffix_tag = f"_{crop_format}" if crop_format else ""
                out_suffix = _resolve_output_extension(photo_path.suffix, output_format)
                out_path = Path(output_folder) / f"{photo_path.stem}{suffix_tag}_ig{out_suffix}"
            else:
                out_path = None

            process_photo(
                photo_path, logo_path, out_path,
                crop_format=crop_format, crop_focus=crop_focus,
                logo_scale=logo_scale,
                opacity=opacity, white_border=white_border,
                logo_position=logo_position, caption=caption,
                jpeg_quality=jpeg_quality, output_format=output_format,
            )
            success += 1
        except Exception as e:
            print(f"❌ Error: {e}")
            errors += 1

    print("-" * 60)
    print(f"✅ Done. Success: {success}, Errors: {errors}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# OPTIONAL: quick test logo generator
# ---------------------------------------------------------------------------
def create_test_logo(save_path="test_logo.png"):
    logo = Image.new("RGBA", (400, 150), (255, 255, 255, 0))
    draw = ImageDraw.Draw(logo)
    draw.rectangle([10, 10, 390, 140], fill=(41, 128, 185, 220))
    draw.rectangle([10, 10, 390, 140], outline=(255, 255, 255, 200), width=3)
    hf = get_headline_font(50)
    sf = get_subtitle_font(22)
    draw.text((30, 35), "MY LOGO", fill=(255, 255, 255, 255), font=hf)
    draw.text((30, 95), "Premium Brand", fill=(255, 255, 255, 200), font=sf)
    logo.save(save_path, "PNG")
    print(f"✅ Test logo created: {save_path}")
    return save_path


# ===========================================================================
# CONFIGURE YOUR SETTINGS HERE  (only used when running this file directly —
# the GUI app has its own settings screen and doesn't need this edited)
# ===========================================================================
if __name__ == "__main__":

    # ----- PATHS (edit these) -----
    PHOTO_FOLDER = r"C:\Users\m.malik\Downloads\Instagram_files\Egy_Australia_match"
    LOGO_PATH = r"C:\Users\m.malik\Downloads\Instagram_files\your_logo.png"
    OUTPUT_FOLDER = r"C:\Users\m.malik\Downloads\Instagram_files\Egy_Australia_match\output"

    # ----- CROP SETTINGS -----
    CROP_FORMAT = "portrait"
    CROP_FOCUS = "center"

    # ----- LOGO SETTINGS -----
    LOGO_SCALE = 0.17
    OPACITY = 1.0
    WHITE_BORDER = False
    LOGO_POSITION = "bottom-right"

    # ----- CAPTION / TEMPLATE (optional — set CAPTION to None to skip) -----
    CAPTION = {
        "layout": "bottom_bar",          # "bottom_bar", "side_panel", or None
        "bar_color": (20, 20, 20),
        "text_color": (255, 255, 255),
        "headline": "MATCH DAY",
        "subtitle": "Egypt vs Australia — Live from the fan zone",
        "bar_ratio": 0.22,
        "side": "right",                 # only used for "side_panel"
        "vertical_text": False,          # only used for "side_panel"
        "opacity": 1.0,
    }

    # ----- OUTPUT QUALITY -----
    JPEG_QUALITY = 95
    OUTPUT_FORMAT = "jpg"  # "jpg" (always JPG), "match_input", or "png"

    # ----- SAFETY CHECKS -----
    if not os.path.exists(PHOTO_FOLDER):
        print(f"❌ Photo folder not found: {PHOTO_FOLDER}")
        exit()

    if LOGO_PATH and not os.path.exists(LOGO_PATH):
        print(f"⚠️ Logo not found at: {LOGO_PATH}")
        print("🔄 Creating a test logo instead...")
        LOGO_PATH = create_test_logo(str(Path(PHOTO_FOLDER) / "test_logo.png"))

    batch_process(
        photo_folder=PHOTO_FOLDER,
        logo_path=LOGO_PATH,
        output_folder=OUTPUT_FOLDER,
        crop_format=CROP_FORMAT,
        crop_focus=CROP_FOCUS,
        logo_scale=LOGO_SCALE,
        opacity=OPACITY,
        white_border=WHITE_BORDER,
        logo_position=LOGO_POSITION,
        caption=CAPTION,
        jpeg_quality=JPEG_QUALITY,
        output_format=OUTPUT_FORMAT,
    )
