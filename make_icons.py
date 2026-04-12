#!/usr/bin/env python3
"""Generate IstaDash app icons for all platforms.

Uses the "thermometer-hot" icon by Delapouite from game-icons.net
(CC BY 3.0 – https://creativecommons.org/licenses/by/3.0/).

Run once with:
    uv run --with pillow make_icons.py

Output:
    icons/icon-{16,32,48,64,128,256,512}.png  – Linux (briefcase) & Android
    icons/icon.ico                             – Windows (multi-size)

Commit the icons/ folder to git; Briefcase picks them up via
    icon = "icons/icon"  in pyproject.toml.
"""

import io
import os
import urllib.request
from PIL import Image, ImageDraw, ImageFilter

# ── Paths ──────────────────────────────────────────────────────────────────────
OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
os.makedirs(OUTPUT, exist_ok=True)

# ── Source icon (white mask on black background, 512×512) ─────────────────────
# thermometer-hot by Delapouite – CC BY 3.0 – https://game-icons.net/1x1/delapouite/thermometer-hot.html
_ICON_URL = "https://game-icons.net/icons/ffffff/000000/1x1/delapouite/thermometer-hot.png"

print("Downloading thermometer-hot from game-icons.net …")
with urllib.request.urlopen(_ICON_URL) as resp:
    _mask_src = Image.open(io.BytesIO(resp.read())).convert("L")   # grayscale mask

# ── Colour palette ─────────────────────────────────────────────────────────────
BG_COLOR    = (15,  23,  42,  255)   # #0F172A  dark navy
ICON_COLOR  = (234, 88,  12,  255)   # #EA580C  vivid orange
GLOW_COLOR  = (245, 158, 11,  180)   # #F59E0B  amber, semi-transparent glow


def create_icon(target: int) -> Image.Image:
    """Render the icon at 4× then downsample for crisp edges at any size."""
    S   = target * 4
    pad = int(S * 0.09)           # inset from edge

    # -- base canvas -------------------------------------------------------
    base = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)
    r    = int(S * 0.20)
    draw.rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=BG_COLOR)

    # -- scale mask to padded area -----------------------------------------
    icon_size = S - 2 * pad
    mask = _mask_src.resize((icon_size, icon_size), Image.LANCZOS)

    # soft ambient glow (blurred, slightly larger than icon)
    glow_mask = mask.resize((icon_size + pad, icon_size + pad), Image.LANCZOS)
    glow_mask = glow_mask.filter(ImageFilter.GaussianBlur(radius=S * 0.030))
    glow_layer = Image.new("RGBA", (S, S), GLOW_COLOR)
    glow_alpha = Image.new("L", (S, S), 0)
    glow_alpha.paste(glow_mask, (pad - pad // 2, pad - pad // 2))
    glow_layer.putalpha(glow_alpha)
    base = Image.alpha_composite(base, glow_layer)

    # crisp icon fill
    icon_layer = Image.new("RGBA", (S, S), ICON_COLOR)
    icon_alpha = Image.new("L", (S, S), 0)
    icon_alpha.paste(mask, (pad, pad))
    icon_layer.putalpha(icon_alpha)
    base = Image.alpha_composite(base, icon_layer)

    return base.resize((target, target), Image.LANCZOS)


# ── Generate & save ────────────────────────────────────────────────────────────
SIZES = [16, 32, 48, 64, 128, 256, 512]

print("Generating IstaDash icons …")
images: dict[int, Image.Image] = {}

for sz in SIZES:
    icon = create_icon(sz)
    path = os.path.join(OUTPUT, f"icon-{sz}.png")
    icon.save(path, "PNG")
    images[sz] = icon
    print(f"  ✓  icons/icon-{sz}.png")

# Windows ICO – embed multiple sizes in a single file
ico_sizes  = [16, 32, 48, 64, 128, 256]
ico_images = [images[s] for s in ico_sizes]
ico_path   = os.path.join(OUTPUT, "icon.ico")
ico_images[0].save(
    ico_path,
    format="ICO",
    sizes=[(s, s) for s in ico_sizes],
    append_images=ico_images[1:],
)
print(f"  ✓  icons/icon.ico  ({', '.join(str(s) for s in ico_sizes)})")

print(f"\nDone – {len(SIZES) + 1} files written to  icons/")
