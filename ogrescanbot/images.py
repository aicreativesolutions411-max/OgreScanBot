from __future__ import annotations

from io import BytesIO
from pathlib import Path
import random
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, UnidentifiedImageError

if TYPE_CHECKING:
    from .db import CallRecord
    from .models import TokenScan


ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
PNL_BACKGROUND = ASSET_DIR / "pnl_background_ogre.jpg"
SCAN_FALLBACK = ASSET_DIR / "scan_fallback_ogre.jpg"


def build_pnl_card(token: TokenScan, call: CallRecord, title: str = "PNL") -> BytesIO:
    width, height = 1280, 720
    image = _load_background(width, height)
    draw = ImageDraw.Draw(image, "RGBA")

    metrics = _pnl_metrics(call)
    headline = str(metrics["headline"])
    accent = "#18ff43" if metrics["positive"] else "#ff3333"
    accent_soft = "#8dff9d" if metrics["positive"] else "#ff9a9a"
    glow_dark = "#004b12" if metrics["positive"] else "#4b0000"
    glow_mid = "#0b9f2d" if metrics["positive"] else "#b31818"

    font_result = _fit_headline_font(headline, max_width=560, start_size=224)
    font_percent = _font(88, bold=True)
    font_brand = _font(118, bold=True)
    font_label = _font(48, bold=True)
    font_mid = _font(62, bold=True)
    font_small = _font(54, bold=True)
    font_tiny = _font(40, bold=True)
    font_detail = _font(34, bold=True)
    font_footer = _font(22, bold=True)

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay, "RGBA")
    overlay_draw.rectangle((0, 0, width, height), fill=(0, 18, 6, 45))
    overlay_draw.polygon([(610, 0), (width, 0), (width, height), (760, height)], fill=(0, 0, 0, 142))
    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image, "RGBA")

    _shadow_text(draw, (72, 82), title.upper(), font=font_label, fill=accent)
    _shadow_text(draw, (72, 152), _shorten(f"{token.name} (${token.symbol})", 24), font=font_mid, fill="#ffffff")
    _shadow_text(draw, (width // 2, 40), _shorten(token.name, 16), font=font_tiny, fill=accent_soft, anchor="mm")

    _shadow_text(draw, (width - 72, 104), "OGRE", font=font_brand, fill="#ffffff", anchor="ra")
    _shadow_text(draw, (width - 78, 202), f"called at {money(call.initial_cap)}", font=font_mid, fill="#f4fff6", anchor="ra")

    _spray_text(
        image,
        (960, 384),
        headline,
        font_result,
        fill=accent,
        glow_dark=glow_dark,
        glow_mid=glow_mid,
    )
    draw = ImageDraw.Draw(image, "RGBA")
    _shadow_text(draw, (960, 528), str(metrics["percent"]), font=font_percent, fill=accent_soft, anchor="mm")
    _shadow_text(draw, (960, 590), f"by {_shorten(call.caller_name, 14).upper()}", font=font_small, fill="#ffffff", anchor="mm")
    _shadow_text(draw, (960, 628), str(metrics["caption"]), font=font_tiny, fill="#f4fff6", anchor="mm")

    detail = f"ATH {money(call.peak_cap)}  |  now {money(call.last_cap)}  |  {metrics['current_x']}"
    _shadow_text(draw, (960, 676), detail, font=font_detail, fill=accent_soft, anchor="mm")

    short_ca = f"{token.address[:6]}...{token.address[-6:]}"
    footer_y = height - 10
    _shadow_text(draw, (width - 74, footer_y), "@OgreScanBot", fill="#f4fff6", font=font_footer, anchor="rb")
    _shadow_text(draw, (74, footer_y), short_ca, fill="#c4d8c7", font=font_footer, anchor="lb")

    output = BytesIO()
    image.convert("RGB").save(output, format="PNG")
    output.seek(0)
    output.name = "ogrescan-pnl.png"
    return output


def build_scan_banner(token: TokenScan, source_image: bytes | None = None) -> BytesIO:
    width, height = 1280, 360
    use_fallback_branding = False
    if source_image:
        image = _banner_from_bytes(source_image, width, height)
    elif SCAN_FALLBACK.exists():
        image = _banner_from_file(SCAN_FALLBACK, width, height)
        use_fallback_branding = True
    else:
        image = _load_background(width, height)
        use_fallback_branding = True

    draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((0, 0, width, height), outline="#1eff4d", width=6)
    if use_fallback_branding:
        _draw_scan_fallback_branding(draw, width)

    output = BytesIO()
    image.convert("RGB").save(output, format="JPEG", quality=90, optimize=True)
    output.seek(0)
    output.name = "ogrescan-banner.jpg"
    return output


def _banner_from_bytes(data: bytes, width: int, height: int) -> Image.Image:
    try:
        source = Image.open(BytesIO(data)).convert("RGB")
    except (OSError, UnidentifiedImageError):
        return _fallback_banner(width, height)
    return _smart_banner(source, width, height)


def _banner_from_file(path: Path, width: int, height: int) -> Image.Image:
    try:
        source = Image.open(path).convert("RGB")
    except OSError:
        return _load_background(width, height)
    return _smart_banner(source, width, height)


def _smart_banner(source: Image.Image, width: int, height: int) -> Image.Image:
    dst_ratio = width / height
    src_ratio = source.width / source.height
    if abs(src_ratio - dst_ratio) < 0.7:
        return _cover_resize(source, width, height).convert("RGBA")

    background = _cover_resize(source, width, height).convert("RGBA")
    background = background.filter(ImageFilter.GaussianBlur(18))
    background = ImageEnhance.Brightness(background).enhance(0.58)

    foreground = source.copy()
    foreground.thumbnail((width, height), Image.Resampling.LANCZOS)
    canvas = background
    x = (width - foreground.width) // 2
    y = (height - foreground.height) // 2
    canvas.alpha_composite(foreground.convert("RGBA"), (x, y))
    return canvas


def _fallback_banner(width: int, height: int) -> Image.Image:
    if SCAN_FALLBACK.exists():
        return _banner_from_file(SCAN_FALLBACK, width, height)
    return _load_background(width, height)


def _draw_scan_fallback_branding(draw: ImageDraw.ImageDraw, width: int) -> None:
    label_font = _font(28, bold=True)
    ticker_font = _font(42, bold=True)

    draw.rounded_rectangle((28, 24, 330, 76), radius=14, fill=(0, 0, 0, 150), outline="#39ff57", width=2)
    draw.text((48, 50), "Powered by Ogres", fill="#f4fff6", font=label_font, anchor="lm")

    draw.rounded_rectangle((width - 190, 24, width - 28, 82), radius=16, fill=(0, 0, 0, 150), outline="#39ff57", width=2)
    draw.text((width - 109, 52), "$OGRE", fill="#43ff62", font=ticker_font, anchor="mm")


def _load_background(width: int, height: int) -> Image.Image:
    if not PNL_BACKGROUND.exists():
        return Image.new("RGBA", (width, height), "#06120d")

    source = Image.open(PNL_BACKGROUND).convert("RGB")
    image = _cover_resize(source, width, height)
    image = ImageEnhance.Brightness(image).enhance(0.78)
    image = ImageEnhance.Contrast(image).enhance(1.15)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle((0, 0, width, height), fill=(0, 20, 8, 58))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def _cover_resize(source: Image.Image, width: int, height: int) -> Image.Image:
    src_ratio = source.width / source.height
    dst_ratio = width / height
    if src_ratio > dst_ratio:
        new_width = int(source.height * dst_ratio)
        left = (source.width - new_width) // 2
        source = source.crop((left, 0, left + new_width, source.height))
    else:
        new_height = int(source.width / dst_ratio)
        top = (source.height - new_height) // 2
        source = source.crop((0, top, source.width, top + new_height))
    return source.resize((width, height), Image.Resampling.LANCZOS)


def _pnl_metrics(call: CallRecord) -> dict[str, object]:
    current_multiple = call.last_cap / call.initial_cap if call.initial_cap else call.peak_multiple
    peak_multiple = call.peak_multiple if call.peak_multiple else current_multiple
    positive = peak_multiple > 1.0001

    if positive:
        return_pct = (peak_multiple - 1.0) * 100
        return {
            "positive": True,
            "headline": f"{peak_multiple:.2f}X",
            "percent": f"+{return_pct:.0f}%",
            "caption": "CALL TO ATH",
            "current_x": f"{current_multiple:.2f}X",
        }

    return_pct = (current_multiple - 1.0) * 100
    return {
        "positive": False,
        "headline": f"{current_multiple:.2f}X",
        "percent": f"{return_pct:.0f}%",
        "caption": "CURRENT FROM CALL",
        "current_x": f"{current_multiple:.2f}X",
    }


def _shadow_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
    anchor: str = "la",
) -> None:
    x, y = xy
    draw.text((x + 3, y + 3), text, fill=(0, 0, 0, 210), font=font, anchor=anchor)
    draw.text((x, y), text, fill=fill, font=font, anchor=anchor)


def _glow_text(
    image: Image.Image,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: str = "#18ff43",
    glow_dark: str = "#004b12",
    glow_mid: str = "#0b9f2d",
) -> None:
    x, y = xy
    for radius, glow_fill in [(12, glow_dark), (6, glow_mid)]:
        glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.text((x, y), text, fill=glow_fill, font=font, anchor="mm")
        glow = glow.filter(ImageFilter.GaussianBlur(radius))
        image.alpha_composite(glow)
    draw = ImageDraw.Draw(image)
    draw.text((x, y), text, fill=fill, font=font, anchor="mm")


def _spray_text(
    image: Image.Image,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
    glow_dark: str,
    glow_mid: str,
) -> None:
    x, y = xy
    seed = sum((index + 1) * ord(char) for index, char in enumerate(text)) + x * 17 + y * 31
    rng = random.Random(seed)

    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text((x, y), text, fill=255, font=font, anchor="mm", stroke_width=7, stroke_fill=255)
    bbox = mask.getbbox()
    if not bbox:
        return

    for radius, color in [(14, glow_dark), (7, glow_mid)]:
        glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        glow.putalpha(mask.filter(ImageFilter.GaussianBlur(radius)))
        glow_color = Image.new("RGBA", image.size, _hex_rgba(color, 180))
        image.alpha_composite(Image.composite(glow_color, Image.new("RGBA", image.size, (0, 0, 0, 0)), glow.split()[-1]))

    spray = Image.new("RGBA", image.size, (0, 0, 0, 0))
    spray_draw = ImageDraw.Draw(spray, "RGBA")
    spray_mask = mask.filter(ImageFilter.GaussianBlur(8))
    left, top, right, bottom = bbox
    for _ in range(520):
        px = rng.randint(max(0, left - 42), min(image.width - 1, right + 42))
        py = rng.randint(max(0, top - 34), min(image.height - 1, bottom + 34))
        strength = spray_mask.getpixel((px, py))
        if strength <= rng.randint(8, 170):
            continue
        dot = rng.choice([1, 1, 1, 2, 2, 3, 4])
        alpha = rng.randint(70, 195)
        spray_draw.ellipse((px - dot, py - dot, px + dot, py + dot), fill=_hex_rgba(fill, alpha))
    image.alpha_composite(spray)

    text_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    text_draw = ImageDraw.Draw(text_layer)
    text_draw.text(
        (x + 9, y + 12),
        text,
        fill=(0, 0, 0, 215),
        font=font,
        anchor="mm",
        stroke_width=10,
        stroke_fill=(0, 0, 0, 210),
    )
    for ox, oy in [(-2, 1), (2, -1), (0, 0)]:
        text_draw.text(
            (x + ox, y + oy),
            text,
            fill=fill,
            font=font,
            anchor="mm",
            stroke_width=6,
            stroke_fill=glow_dark,
        )
    image.alpha_composite(text_layer)


def money(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:.2f}"


def _shorten(text: str, limit: int) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    return f"{clean[: max(0, limit - 3)]}..."


def _hex_rgba(color: str, alpha: int) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    if len(value) != 6:
        return (255, 255, 255, alpha)
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)


def _headline_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_headline_font(
    text: str,
    max_width: int,
    start_size: int = 232,
    min_size: int = 150,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    measuring = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for size in range(start_size, min_size - 1, -6):
        font = _headline_font(size)
        left, _top, right, _bottom = measuring.textbbox((0, 0), text, font=font, stroke_width=10)
        if right - left <= max_width:
            return font
    return _headline_font(min_size)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()
