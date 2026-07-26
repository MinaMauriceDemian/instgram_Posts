# instgram_Posts
# Instagram Logo & Crop Tool

A point-and-click desktop tool for preparing photos for Instagram: it crops
photos to Instagram's standard sizes, adds your logo/watermark, and can add a
caption template (color bar or side panel with headline/subtitle text) — all
with a live preview before saving anything.

## What it can do

- **Crop to Instagram sizes** — Square (1:1), Portrait (4:5), Landscape
  (1.91:1), or Story/Reel (9:16)
- **Add a logo/watermark** — resize, adjust opacity, add a white border, and
  drag it anywhere on the photo
- **Add a caption/template** — a bottom color bar or side color panel with a
  headline + subtitle, like a promo-graphic template
- **Batch or single photo** — process a whole folder at once, or just one photo
- **Presets** — save named logo presets (e.g. different brands/accounts) and
  caption templates (e.g. "Weekend Special") to reuse later
- **Live preview** — see the crop, logo, and caption together before saving,
  and drag the logo directly on the preview
- **Format handling** — output as JPG, PNG, or match the input format;
  supports iPhone HEIC/HEIF photos too

## How to use it

1. **Setup (one time)**
   Keep `gui_app.py`, `instagram_logo_tool.py`, and the `fonts` folder in the
   same folder, then install the requirements:
   ```
   pip install pillow pillow-heif
   ```

2. **Run it**
   ```
   python gui_app.py
   ```
   (or just double-click `gui_app.py` on Windows)

3. **In the app**
   - Choose **folder** (batch) or **single photo** mode at the top.
   - Use the tabs to set things up:
     - **Files & Presets** — pick your photo(s), logo, and output location
     - **Crop & Output** — choose the Instagram format and save type
     - **Caption / Template** — add a color bar/panel with text, if wanted
     - **Logo** — adjust size, opacity, and border
   - Check the **live preview** on the right, drag the logo to reposition it.
   - Click **▶ Run** to process and save.

Settings and presets are remembered automatically between sessions.
<img width="1521" height="886" alt="image" src="https://github.com/user-attachments/assets/4bc09886-6454-49de-b36a-effe5c1e8957" />
