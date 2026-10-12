"""
image_prep.py – open, EXIF-rotate, upscale, produce 3 crops per bill.

Returns: (full_bytes, top_bytes, bottom_bytes)  – all JPEG bytes.
"""
from __future__ import annotations
from io import BytesIO
from pathlib import Path

from PIL import Image, ExifTags, ImageEnhance


def _exif_rotate(img: Image.Image) -> Image.Image:
    """Apply EXIF orientation tag so the image is right-side up."""
    try:
        exif = img._getexif()  # type: ignore[attr-defined]
        if exif is None:
            return img
        orient_key = next(k for k, v in ExifTags.TAGS.items() if v == "Orientation")
        orientation = exif.get(orient_key)
        rotations = {3: 180, 6: 270, 8: 90}
        if orientation in rotations:
            img = img.rotate(rotations[orientation], expand=True)
    except Exception:
        pass
    return img


def _to_jpeg(img: Image.Image, quality: int = 92) -> bytes:
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _upscale_if_small(img: Image.Image, min_long_side: int = 1200, max_long_side: int = 2400) -> Image.Image:
    w, h = img.size
    long_side = max(w, h)
    if long_side < min_long_side:
        scale = min_long_side / long_side
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    elif long_side > max_long_side:
        scale = max_long_side / long_side
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img


def _is_lesco_photo(img: Image.Image) -> bool:
    """Heuristic: portrait phone photos that are small/low-res are likely LESCO."""
    w, h = img.size
    # LESCO bills tend to be tall phone photos at lower resolution
    return h > w and max(w, h) < 2000


def prepare_images(bill_path: Path) -> tuple[bytes, bytes, bytes]:
    """
    Open a bill image and produce three JPEG byte strings:
      1. full  – entire bill, long side ≤ 2400 px
      2. top   – top 55% with 10% overlap (upscaled further for LESCO)
      3. bottom – bottom 55% with 10% overlap

    For low-res LESCO phone photos: upscale 2–3x before cropping.
    """
    img = Image.open(bill_path).convert("RGB")
    img = _exif_rotate(img)

    is_lesco = _is_lesco_photo(img) or "LESCO" in bill_path.name.upper()

    if is_lesco:
        # Upscale 2x-3x for low-res LESCO phone photos
        w, h = img.size
        long_side = max(w, h)
        if long_side < 1500:
            scale = 3.0
        elif long_side < 2400:
            scale = 2.0
        else:
            scale = 1.0
        if scale > 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        # Slightly sharpen to help with glare/blur
        img = ImageEnhance.Sharpness(img).enhance(1.4)

    img = _upscale_if_small(img)

    w, h = img.size

    # Overlap: top crop covers 0..60%, bottom covers 45%..100%
    top_h = int(h * 0.60)
    bottom_start = int(h * 0.45)

    top_crop = img.crop((0, 0, w, top_h))
    bottom_crop = img.crop((0, bottom_start, w, h))

    # Upscale crops a bit more so small print is legible
    crop_scale = 1.3 if not is_lesco else 1.0  # LESCO already upscaled
    if crop_scale > 1.0:
        cw, ch = top_crop.size
        top_crop = top_crop.resize((int(cw * crop_scale), int(ch * crop_scale)), Image.LANCZOS)
        cw, ch = bottom_crop.size
        bottom_crop = bottom_crop.resize((int(cw * crop_scale), int(ch * crop_scale)), Image.LANCZOS)

    return _to_jpeg(img), _to_jpeg(top_crop), _to_jpeg(bottom_crop)
