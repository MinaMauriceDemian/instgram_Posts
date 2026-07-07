"""
Instagram Logo & Crop Tool
==========================
Adds a logo/watermark to photos AND crops them to fit Instagram's
standard aspect ratios (square, portrait, landscape, story).

Works on a single photo or a whole folder of photos.

Requirements:
    pip install pillow

--------------------------------------------------------------------
QUICK START — scroll down to the "CONFIGURE YOUR SETTINGS HERE"
section near the bottom of this file and edit the paths/options,
then just run the script.
--------------------------------------------------------------------
"""

from PIL import Image, ImageDraw, ImageFont
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Instagram's recommended output sizes (width, height) in pixels.
# Cropping first to the matching aspect ratio, then resizing to these exact
# dimensions, gives the sharpest possible result (no extra re-compression
# by Instagram itself).
# ---------------------------------------------------------------------------
INSTAGRAM_FORMATS = {
    "square":    {"ratio": 1 / 1,    "size": (1080, 1080)},
    "portrait":  {"ratio": 4 / 5,    "size": (1080, 1350)},
    "landscape": {"ratio": 1.91 / 1, "size": (1080, 566)},
    "story":     {"ratio": 9 / 16,   "size": (1080, 1920)},
}

IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"]


# ---------------------------------------------------------------------------
# CROPPING
# ---------------------------------------------------------------------------
def crop_to_instagram_format(image, fmt="square", focus="center"):
    """
    Crop a PIL image (RGB/RGBA) to a given Instagram aspect ratio and resize
    it to Instagram's recommended pixel dimensions.

    Args:
        image: PIL.Image
        fmt: one of "square", "portrait", "landscape", "story"
        focus: which part of the image to keep when cropping —
               "center" (default), "top", or "bottom".
               (Top/bottom only matter when cropping height; for width-crops
               it always centers horizontally, which is right for group/portrait
               photos where the subject is usually centered left-right.)

    Returns:
        Cropped + resized PIL.Image, ready to save.
    """
    if fmt not in INSTAGRAM_FORMATS:
        raise ValueError(f"Unknown format '{fmt}'. Choose from {list(INSTAGRAM_FORMATS)}")

    target_ratio = INSTAGRAM_FORMATS[fmt]["ratio"]
    target_size = INSTAGRAM_FORMATS[fmt]["size"]

    width, height = image.size
    current_ratio = width / height

    if current_ratio > target_ratio:
        # Image is too wide -> crop the sides
        new_width = int(height * target_ratio)
        left = (width - new_width) // 2
        box = (left, 0, left + new_width, height)
    else:
        # Image is too tall -> crop top/bottom
        new_height = int(width / target_ratio)
        if focus == "top":
            top = 0
        elif focus == "bottom":
            top = height - new_height
        else:  # center
            top = (height - new_height) // 2
        box = (0, top, width, top + new_height)

    cropped = image.crop(box)
    resized = cropped.resize(target_size, Image.Resampling.LANCZOS)
    return resized


# ---------------------------------------------------------------------------
# LOGO / WATERMARK
# ---------------------------------------------------------------------------
def add_logo(photo, logo_path, logo_scale=0.15, margin_ratio=0.02,
             opacity=1.0, white_border=False, position="bottom-right"):
    """
    Paste a logo onto a PIL image (RGBA-safe).

    Args:
        photo: PIL.Image (RGB or RGBA)
        logo_path: path to the logo PNG (should have transparency)
        logo_scale: logo width as a fraction of photo width
        margin_ratio: margin from the edges as a fraction of photo size
        opacity: 0.0 (invisible) to 1.0 (fully opaque)
        white_border: add a soft white border/plate behind the logo
        position: "bottom-right", "bottom-left", "top-right", "top-left", "center"

    Returns:
        New PIL.Image with the logo applied.
    """
    photo = photo.convert("RGBA")
    photo_width, photo_height = photo.size

    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception as e:
        raise ValueError(f"Could not read logo: {e}")

    logo_width = max(int(photo_width * logo_scale), 1)
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

    margin_x = int(photo_width * margin_ratio)
    margin_y = int(photo_height * margin_ratio)

    positions = {
        "bottom-right": (photo_width - logo_resized.width - margin_x,
                          photo_height - logo_resized.height - margin_y),
        "bottom-left":  (margin_x, photo_height - logo_resized.height - margin_y),
        "top-right":    (photo_width - logo_resized.width - margin_x, margin_y),
        "top-left":     (margin_x, margin_y),
        "center":       ((photo_width - logo_resized.width) // 2,
                          (photo_height - logo_resized.height) // 2),
    }
    pos_x, pos_y = positions.get(position, positions["bottom-right"])

    result = photo.copy()
    result.paste(logo_resized, (pos_x, pos_y), logo_resized)
    return result


# ---------------------------------------------------------------------------
# COMBINED PIPELINE (crop + logo) FOR A SINGLE PHOTO
# ---------------------------------------------------------------------------
def process_photo(photo_path, logo_path, output_path=None,
                   crop_format=None, crop_focus="center",
                   logo_scale=0.15, margin_ratio=0.02, opacity=1.0,
                   white_border=False, logo_position="bottom-right",
                   jpeg_quality=95):
    """
    Full pipeline: load photo -> (optional) crop to Instagram format ->
    add logo -> save.

    Args:
        crop_format: None (no cropping) or one of
                     "square", "portrait", "landscape", "story"
        jpeg_quality: output JPEG quality (1-100), only used for .jpg/.jpeg

    Returns:
        output_path (str)
    """
    photo_path = Path(photo_path)

    # Load with PIL (handles both cropping and pasting cleanly, avoids
    # repeated BGR<->RGBA conversions)
    photo = Image.open(photo_path).convert("RGBA")

    if crop_format:
        photo = crop_to_instagram_format(photo, fmt=crop_format, focus=crop_focus)

    if logo_path:
        photo = add_logo(
            photo, logo_path,
            logo_scale=logo_scale,
            margin_ratio=margin_ratio,
            opacity=opacity,
            white_border=white_border,
            position=logo_position,
        )

    if output_path is None:
        suffix_tag = f"_{crop_format}" if crop_format else ""
        output_path = str(photo_path.parent / f"{photo_path.stem}{suffix_tag}_ig{photo_path.suffix}")
    output_path = str(output_path)

    # Flatten to RGB for JPEG output (JPEG has no alpha channel)
    if output_path.lower().endswith((".jpg", ".jpeg")):
        flat = Image.new("RGB", photo.size, (255, 255, 255))
        flat.paste(photo, mask=photo.split()[3])
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
                   logo_scale=0.15, margin_ratio=0.02, opacity=1.0,
                   white_border=False, logo_position="bottom-right",
                   jpeg_quality=95):
    """
    Run process_photo() over every image in a folder.
    """
    photo_folder = Path(photo_folder)
    print("=" * 60)
    print("📸 INSTAGRAM LOGO & CROP TOOL — BATCH MODE")
    print("=" * 60)
    print(f"📁 Input folder : {photo_folder}")
    print(f"🖼️  Logo         : {logo_path or '(none)'}")
    print(f"✂️  Crop format  : {crop_format or '(none — keep original ratio)'}")
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
                out_suffix = ".jpg" if photo_path.suffix.lower() in (".jpg", ".jpeg") else photo_path.suffix
                out_path = Path(output_folder) / f"{photo_path.stem}{suffix_tag}_ig{out_suffix}"
            else:
                out_path = None

            process_photo(
                photo_path, logo_path, out_path,
                crop_format=crop_format, crop_focus=crop_focus,
                logo_scale=logo_scale, margin_ratio=margin_ratio,
                opacity=opacity, white_border=white_border,
                logo_position=logo_position, jpeg_quality=jpeg_quality,
            )
            success += 1
        except Exception as e:
            print(f"❌ Error: {e}")
            errors += 1

    print("-" * 60)
    print(f"✅ Done. Success: {success}, Errors: {errors}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# OPTIONAL: quick test logo generator (unchanged idea from your original)
# ---------------------------------------------------------------------------
def create_test_logo(save_path="test_logo.png"):
    logo = Image.new("RGBA", (400, 150), (255, 255, 255, 0))
    draw = ImageDraw.Draw(logo)
    draw.rectangle([10, 10, 390, 140], fill=(41, 128, 185, 220))
    draw.rectangle([10, 10, 390, 140], outline=(255, 255, 255, 200), width=3)
    try:
        font = ImageFont.truetype("arial.ttf", 60)
        font_small = ImageFont.truetype("arial.ttf", 25)
    except Exception:
        font = ImageFont.load_default()
        font_small = ImageFont.load_default()
    draw.text((50, 40), "MY LOGO", fill=(255, 255, 255, 255), font=font)
    draw.text((50, 95), "Premium Brand", fill=(255, 255, 255, 200), font=font_small)
    logo.save(save_path, "PNG")
    print(f"✅ Test logo created: {save_path}")
    return save_path


# ===========================================================================
# CONFIGURE YOUR SETTINGS HERE
# ===========================================================================
if __name__ == "__main__":

    # ----- PATHS (edit these) -----
    PHOTO_FOLDER = r"C:\Users\m.malik\Downloads\Instagram_files\Egy_Australia_match"
    LOGO_PATH = r"C:\Users\m.malik\Downloads\Instagram_files\your_logo.png"
    OUTPUT_FOLDER = r"C:\Users\m.malik\Downloads\Instagram_files\Egy_Australia_match\output"

    # ----- CROP SETTINGS -----
    # Choose one: "square", "portrait", "landscape", "story", or None to skip cropping
    CROP_FORMAT = "portrait"
    # Which part to keep if the photo is taller than the target ratio: "center", "top", "bottom"
    CROP_FOCUS = "center"

    # ----- LOGO SETTINGS -----
    LOGO_SCALE = 0.17          # logo width as a fraction of photo width
    OPACITY = 1.0              # 0.0 (invisible) to 1.0 (fully opaque)
    MARGIN_RATIO = 0.02        # margin from edges
    WHITE_BORDER = False
    LOGO_POSITION = "bottom-right"  # bottom-right / bottom-left / top-right / top-left / center

    # ----- OUTPUT QUALITY -----
    JPEG_QUALITY = 95          # 1-100, higher = better quality / bigger file

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
        margin_ratio=MARGIN_RATIO,
        opacity=OPACITY,
        white_border=WHITE_BORDER,
        logo_position=LOGO_POSITION,
        jpeg_quality=JPEG_QUALITY,
    )

    # ----- SINGLE-PHOTO EXAMPLE (uncomment to use instead of batch) -----
    # process_photo(
    #     photo_path=r"C:\Users\m.malik\Downloads\Instagram_files\photo_2026-07-05_10-32-34.jpg",
    #     logo_path=LOGO_PATH,
    #     crop_format="square",
    #     logo_scale=0.15,
    #     opacity=0.7,
    # )
