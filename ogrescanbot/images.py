from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from .db import CallRecord
from .formatting import money
from .models import TokenScan


def build_pnl_card(token: TokenScan, call: CallRecord) -> BytesIO:
    width, height = 1200, 630
    image = Image.new("RGB", (width, height), "#07150f")
    draw = ImageDraw.Draw(image)

    for y in range(height):
        green = int(18 + (y / height) * 28)
        draw.line([(0, y), (width, y)], fill=(5, green, 18))

    draw.rectangle((0, 0, width, height), outline="#19ff58", width=8)
    draw.rounded_rectangle((55, 55, 1145, 575), radius=34, fill="#0b2117", outline="#1b5f35", width=3)

    font_big = _font(120, bold=True)
    font_title = _font(62, bold=True)
    font_mid = _font(44, bold=True)
    font_small = _font(30)
    font_tiny = _font(24)

    multiple = max(1.0, call.last_cap / call.initial_cap) if call.initial_cap else call.peak_multiple

    draw.text((90, 92), "OGRE", fill="#f2fff4", font=font_title)
    draw.text((90, 162), f"${token.symbol}", fill="#19ff58", font=font_mid)
    draw.text((90, 220), token.name[:28], fill="#b8d9c1", font=font_small)

    draw.text((90, 320), f"{multiple:.2f}x", fill="#19ff58", font=font_big)
    draw.text((92, 455), f"called at {money(call.initial_cap)}", fill="#f2fff4", font=font_mid)
    draw.text((92, 510), f"now {money(call.last_cap)} by {call.caller_name}", fill="#b8d9c1", font=font_small)

    draw.rounded_rectangle((760, 100, 1085, 425), radius=28, fill="#102a1d", outline="#246b3f", width=3)
    draw.text((800, 135), "OGRESCAN", fill="#f2fff4", font=font_mid)
    draw.text((800, 205), "CALL CARD", fill="#19ff58", font=font_small)
    draw.text((800, 300), f"best {call.peak_multiple:.2f}x", fill="#f2fff4", font=font_mid)
    draw.text((800, 360), "solana tracker", fill="#b8d9c1", font=font_tiny)

    short_ca = f"{token.address[:6]}...{token.address[-6:]}"
    draw.text((760, 500), short_ca, fill="#789a84", font=font_tiny)

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    output.name = "ogrescan-pnl.png"
    return output


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
