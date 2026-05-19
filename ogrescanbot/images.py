from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, UnidentifiedImageError

if TYPE_CHECKING:
    from .db import CallRecord
    from .models import TokenScan


ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
PNL_BACKGROUND = ASSET_DIR / "pnl_background_ogre.jpg"
SCAN_FALLBACK = ASSET_DIR / "scan_fallback_ogre.jpg"


def build_pnl_card(token: TokenScan, call: CallRecord) -> BytesIO:
    width, height = 1280, 720
    image = _load_background(width, height)
    draw = ImageDraw.Draw(image, "RGBA")

    font_huge = _font(148, bold=True)
    font_brand = _font(74, bold=True)
    font_mid = _font(44, bold=True)
    font_small = _font(31, bold=True)
    font_tiny = _font(24)

    multiple = max(1.0, call.last_cap / call.initial_cap) if call.initial_cap else call.peak_multiple

    draw.rectangle((0, 0, width, height), outline="#06120d", width=10)
    draw.rounded_rectangle((710, 54, 1228, 620), radius=22, fill=(0, 0, 0, 145), outline="#43ff62", width=3)
    draw.rounded_rectangle((734, 76, 1204, 598), radius=18, outline="#0e5329", width=2)

    draw.text((968, 126), "OGRE", fill="#ffffff", font=font_brand, anchor="mm")
    draw.text((968, 190), f"called at {money(call.initial_cap)}", fill="#d8f5dd", font=font_small, anchor="mm")

    _glow_text(image, (968, 330), f"{multiple:.2f}x", font_huge)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text((968, 422), "PLAYER", fill="#69ff83", font=font_tiny, anchor="mm")
    draw.text((968, 462), _shorten(call.caller_name, 20), fill="#f4fff6", font=font_mid, anchor="mm")
    draw.text((968, 502), "TOKEN", fill="#69ff83", font=font_tiny, anchor="mm")
    draw.text((968, 536), _shorten(f"{token.name} (${token.symbol})", 24), fill="#c4e6ca", font=font_small, anchor="mm")
    draw.text((968, 580), f"now {money(call.last_cap)} | best {call.peak_multiple:.2f}x", fill="#69ff83", font=font_small, anchor="mm")

    short_ca = f"{token.address[:6]}...{token.address[-6:]}"
    draw.rounded_rectangle((370, 646, 910, 696), radius=12, fill=(0, 0, 0, 135))
    draw.text((640, 672), f"@OgreScanBot  |  {short_ca}", fill="#c4d8c7", font=font_tiny, anchor="mm")

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
    overlay_draw.rectangle((690, 0, width, height), fill=(0, 0, 0, 105))
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


def _glow_text(image: Image.Image, xy: tuple[int, int], text: str, font: ImageFont.ImageFont) -> None:
    x, y = xy
    for radius, fill in [(12, "#004b12"), (6, "#0b9f2d")]:
        glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.text((x, y), text, fill=fill, font=font, anchor="mm")
        glow = glow.filter(ImageFilter.GaussianBlur(radius))
        image.alpha_composite(glow)
    draw = ImageDraw.Draw(image)
    draw.text((x, y), text, fill="#18ff43", font=font, anchor="mm")


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
