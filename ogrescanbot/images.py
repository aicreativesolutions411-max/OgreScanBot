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


def build_pnl_card(token: TokenScan, call: CallRecord, title: str = "PNL") -> BytesIO:
    width, height = 1280, 720
    image = _load_background(width, height)
    draw = ImageDraw.Draw(image, "RGBA")

    font_result = _font(158, bold=True)
    font_percent = _font(58, bold=True)
    font_brand = _font(76, bold=True)
    font_label = _font(27, bold=True)
    font_mid = _font(42, bold=True)
    font_small = _font(30, bold=True)
    font_tiny = _font(22)

    metrics = _pnl_metrics(call)
    accent = "#18ff43" if metrics["positive"] else "#ff3333"
    accent_soft = "#8dff9d" if metrics["positive"] else "#ff9a9a"
    glow_dark = "#004b12" if metrics["positive"] else "#4b0000"
    glow_mid = "#0b9f2d" if metrics["positive"] else "#b31818"

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay, "RGBA")
    overlay_draw.rectangle((0, 0, width, height), fill=(0, 18, 6, 52))
    overlay_draw.rectangle((0, 0, width, 130), fill=(0, 0, 0, 105))
    overlay_draw.rectangle((0, 560, width, height), fill=(0, 0, 0, 135))
    overlay_draw.polygon([(610, 0), (width, 0), (width, height), (720, height)], fill=(0, 0, 0, 122))
    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image, "RGBA")

    draw.rectangle((0, 0, width, height), outline="#07110b", width=10)
    draw.line((24, 142, width - 24, 142), fill=accent, width=3)

    _shadow_text(draw, (42, 48), title.upper(), font=font_label, fill=accent)
    _shadow_text(draw, (42, 92), _shorten(f"{token.name} (${token.symbol})", 34), font=font_mid, fill="#ffffff")

    _shadow_text(draw, (width - 52, 48), "OGRE", font=font_brand, fill="#ffffff", anchor="ra")
    _shadow_text(draw, (width - 54, 100), f"called at {money(call.initial_cap)}", font=font_small, fill="#d8f5dd", anchor="ra")

    _glow_text(
        image,
        (940, 292),
        metrics["headline"],
        font_result,
        fill=accent,
        glow_dark=glow_dark,
        glow_mid=glow_mid,
    )
    draw = ImageDraw.Draw(image, "RGBA")
    _shadow_text(draw, (940, 404), metrics["percent"], font=font_percent, fill=accent_soft, anchor="mm")
    _shadow_text(draw, (940, 458), metrics["caption"], font=font_small, fill="#f4fff6", anchor="mm")

    draw.rounded_rectangle((48, 552, 470, 656), radius=18, fill=(0, 0, 0, 152), outline=accent, width=2)
    draw.rounded_rectangle((498, 552, 846, 656), radius=18, fill=(0, 0, 0, 142), outline="#23482c", width=2)
    draw.rounded_rectangle((874, 552, 1232, 656), radius=18, fill=(0, 0, 0, 142), outline="#23482c", width=2)

    _shadow_text(draw, (74, 580), "PLAYER", font=font_tiny, fill=accent_soft)
    _shadow_text(draw, (74, 620), _shorten(call.caller_name, 22), font=font_small, fill="#ffffff")
    _shadow_text(draw, (524, 580), "ATH", font=font_tiny, fill=accent_soft)
    _shadow_text(draw, (524, 620), money(call.peak_cap), font=font_small, fill="#ffffff")
    _shadow_text(draw, (900, 580), "CURRENT", font=font_tiny, fill=accent_soft)
    _shadow_text(draw, (900, 620), f"{money(call.last_cap)} | {metrics['current_x']}", font=font_small, fill="#ffffff")

    short_ca = f"{token.address[:6]}...{token.address[-6:]}"
    _shadow_text(draw, (640, 690), f"@OgreScanBot  |  {short_ca}", fill="#c4d8c7", font=font_tiny, anchor="mm")

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
        "headline": f"{return_pct:.0f}%",
        "percent": f"{current_multiple:.2f}X",
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
