from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import math

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
FONT_DIR = ASSET_DIR / "fonts"
BUNDLED_BOLD_FONT = FONT_DIR / "LiberationSans-Bold.ttf"
BUNDLED_REGULAR_FONT = FONT_DIR / "LiberationSans-Regular.ttf"


@dataclass(frozen=True)
class ChartCandle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class ChartData:
    title: str
    symbol: str
    subtitle: str
    source: str
    source_url: str | None
    interval: str
    candles: list[ChartCandle]
    indicators: list[str] = field(default_factory=list)
    source_interval: str | None = None


def chart_data_from_ohlcv(
    raw_candles: list[list],
    title: str,
    symbol: str,
    subtitle: str,
    source: str,
    source_url: str | None,
    interval: str,
    indicators: list[str] | None = None,
    source_interval: str | None = None,
) -> ChartData | None:
    candles: list[ChartCandle] = []
    for row in raw_candles:
        if len(row) < 6:
            continue
        ts = _int_or_none(row[0])
        open_price = _float_or_none(row[1])
        high = _float_or_none(row[2])
        low = _float_or_none(row[3])
        close = _float_or_none(row[4])
        volume = _float_or_none(row[5]) or 0.0
        if not ts or open_price is None or high is None or low is None or close is None:
            continue
        if high <= 0 or low <= 0 or close <= 0:
            continue
        candles.append(ChartCandle(ts, open_price, high, low, close, max(0.0, volume)))

    candles.sort(key=lambda candle: candle.ts)
    deduped: list[ChartCandle] = []
    seen: set[int] = set()
    for candle in candles:
        if candle.ts in seen:
            continue
        deduped.append(candle)
        seen.add(candle.ts)

    if len(deduped) < 2:
        return None
    return ChartData(
        title=title,
        symbol=symbol,
        subtitle=subtitle,
        source=source,
        source_url=source_url,
        interval=interval,
        candles=deduped[-160:],
        indicators=normalize_indicators(indicators),
        source_interval=source_interval,
    )


def build_chart_image(data: ChartData) -> BytesIO:
    width, height = 1280, 720
    image = Image.new("RGBA", (width, height), "#101722")
    draw = ImageDraw.Draw(image, "RGBA")

    _draw_background(draw, width, height)

    chart_left = 58
    chart_top = 92
    chart_right = 1130
    price_bottom = 455
    volume_top = 474
    volume_bottom = 588
    oscillator_top = 606
    oscillator_bottom = 662

    candles = data.candles[-120:]
    flags = indicator_flags(data.indicators)
    prices = [value for candle in candles for value in (candle.high, candle.low) if value > 0]
    if not prices:
        return _empty_chart(data)

    price_min = min(prices)
    price_max = max(prices)
    if price_min == price_max:
        price_min *= 0.96
        price_max *= 1.04
    pad = (price_max - price_min) * 0.08
    price_min = max(0.0, price_min - pad)
    price_max += pad

    _draw_grid(draw, chart_left, chart_top, chart_right, price_bottom, rows=5, cols=6)
    _draw_panel(draw, chart_left, volume_top, chart_right, volume_bottom, "Volume")
    _draw_panel(draw, chart_left, oscillator_top, chart_right, oscillator_bottom, "Momentum")

    first = candles[0]
    last = candles[-1]
    change = last.close - first.open
    change_pct = (change / first.open) * 100 if first.open else 0.0
    up = change >= 0
    accent = "#17c6a3" if up else "#ff4d61"
    soft_accent = "#67ffe6" if up else "#ff9aa6"

    _draw_header(draw, data, last, change, change_pct, accent, soft_accent)
    _draw_candles(draw, candles, chart_left, chart_top, chart_right, price_bottom, price_min, price_max)
    _draw_overlay_indicators(draw, candles, flags, chart_left, chart_top, chart_right, price_bottom, price_min, price_max)
    _draw_volume(draw, candles, chart_left, volume_top, chart_right, volume_bottom)
    if "macd" in flags:
        _draw_macd(draw, candles, chart_left, oscillator_top, chart_right, oscillator_bottom)
    elif "rsi" in flags:
        _draw_rsi(draw, candles, chart_left, oscillator_top, chart_right, oscillator_bottom)
    else:
        _draw_momentum(draw, candles, chart_left, oscillator_top, chart_right, oscillator_bottom)
    _draw_price_axis(draw, chart_right, chart_top, price_bottom, price_min, price_max, last.close, accent)
    _draw_time_axis(draw, candles, chart_left, chart_right, price_bottom + 12, volume_top + 12)
    _draw_footer(draw, data, width, height)

    output = BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    output.name = "ogrescan-chart.png"
    return output


def _draw_background(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    draw.rectangle((0, 0, width, height), fill="#111925")
    for y in range(0, height, 4):
        alpha = int(22 + (y / height) * 30)
        draw.line((0, y, width, y), fill=(40, 58, 80, alpha), width=1)
    draw.rectangle((0, 0, width, 74), fill=(12, 18, 27, 230))
    draw.rectangle((0, height - 54, width, height), fill=(10, 14, 20, 238))


def _draw_header(
    draw: ImageDraw.ImageDraw,
    data: ChartData,
    last: ChartCandle,
    change: float,
    change_pct: float,
    accent: str,
    soft_accent: str,
) -> None:
    title_font = _font(26, bold=True)
    meta_font = _font(19)
    small_font = _font(18)
    title = _shorten(f"{data.title} ({data.symbol})", 42)
    draw.text((36, 25), title, fill="#f5f9ff", font=title_font, anchor="lm")
    indicator_text = indicator_label(data.indicators)
    source_text = f" | source {data.source_interval}" if data.source_interval and data.source_interval != data.interval else ""
    subtitle = f"{data.subtitle}{source_text}{indicator_text}"
    draw.text((36, 55), _shorten(subtitle, 88), fill="#9aa9bb", font=meta_font, anchor="lm")

    ohlc = (
        f"O {format_price(last.open)}  H {format_price(last.high)}  "
        f"L {format_price(last.low)}  C {format_price(last.close)}"
    )
    change_text = f"{change:+.6g} ({change_pct:+.2f}%)"
    draw.text((520, 26), ohlc, fill="#bec9d6", font=small_font, anchor="lm")
    draw.text((520, 54), change_text, fill=soft_accent, font=small_font, anchor="lm")

    draw.rounded_rectangle((1110, 18, 1244, 58), radius=12, fill=(20, 31, 45, 235), outline=accent, width=2)
    draw.text((1177, 38), data.interval.upper(), fill="#f7fbff", font=_font(22, bold=True), anchor="mm")


def _draw_grid(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    right: int,
    bottom: int,
    rows: int,
    cols: int,
) -> None:
    draw.rounded_rectangle((left, top, right, bottom), radius=8, fill=(17, 25, 36, 245), outline="#243246", width=2)
    for index in range(rows + 1):
        y = top + ((bottom - top) * index / rows)
        draw.line((left, y, right, y), fill=(75, 91, 114, 82), width=1)
    for index in range(cols + 1):
        x = left + ((right - left) * index / cols)
        draw.line((x, top, x, bottom), fill=(75, 91, 114, 54), width=1)


def _draw_panel(draw: ImageDraw.ImageDraw, left: int, top: int, right: int, bottom: int, label: str) -> None:
    draw.rounded_rectangle((left, top, right, bottom), radius=8, fill=(16, 25, 37, 235), outline="#263549", width=1)
    draw.text((left + 14, top + 12), label, fill="#77879a", font=_font(16, bold=True), anchor="la")
    draw.line((left, (top + bottom) // 2, right, (top + bottom) // 2), fill=(95, 115, 137, 64), width=1)


def _draw_candles(
    draw: ImageDraw.ImageDraw,
    candles: list[ChartCandle],
    left: int,
    top: int,
    right: int,
    bottom: int,
    price_min: float,
    price_max: float,
) -> None:
    width = right - left
    step = width / max(1, len(candles))
    candle_w = max(4, min(12, int(step * 0.58)))

    def y_for(value: float) -> float:
        return bottom - ((value - price_min) / (price_max - price_min)) * (bottom - top)

    for index, candle in enumerate(candles):
        x = left + step * index + step / 2
        color = "#17c6a3" if candle.close >= candle.open else "#ff4d61"
        wick = "#7df5db" if candle.close >= candle.open else "#ff9ba7"
        high_y = y_for(candle.high)
        low_y = y_for(candle.low)
        open_y = y_for(candle.open)
        close_y = y_for(candle.close)
        body_top = min(open_y, close_y)
        body_bottom = max(open_y, close_y)
        if body_bottom - body_top < 2:
            body_bottom = body_top + 2
        draw.line((x, high_y, x, low_y), fill=wick, width=2)
        draw.rounded_rectangle(
            (x - candle_w / 2, body_top, x + candle_w / 2, body_bottom),
            radius=2,
            fill=color,
            outline=color,
        )


def _draw_overlay_indicators(
    draw: ImageDraw.ImageDraw,
    candles: list[ChartCandle],
    flags: set[str],
    left: int,
    top: int,
    right: int,
    bottom: int,
    price_min: float,
    price_max: float,
) -> None:
    if not candles or not flags:
        return
    closes = [candle.close for candle in candles]
    if "sma" in flags:
        _draw_indicator_line(draw, candles, moving_average(closes, 20), left, top, right, bottom, price_min, price_max, "#ffd166", 3)
    if "ema" in flags:
        _draw_indicator_line(draw, candles, exponential_average(closes, 20), left, top, right, bottom, price_min, price_max, "#5cc8ff", 3)
    if "vwap" in flags:
        _draw_indicator_line(draw, candles, vwap_values(candles), left, top, right, bottom, price_min, price_max, "#f59e0b", 3)
    if "bb" in flags:
        upper, mid, lower = bollinger_bands(closes, 20, 2.0)
        _draw_indicator_line(draw, candles, upper, left, top, right, bottom, price_min, price_max, "#b779ff", 2)
        _draw_indicator_line(draw, candles, mid, left, top, right, bottom, price_min, price_max, "#d8b4fe", 2)
        _draw_indicator_line(draw, candles, lower, left, top, right, bottom, price_min, price_max, "#b779ff", 2)


def _draw_indicator_line(
    draw: ImageDraw.ImageDraw,
    candles: list[ChartCandle],
    values: list[float | None],
    left: int,
    top: int,
    right: int,
    bottom: int,
    price_min: float,
    price_max: float,
    color: str,
    width: int,
) -> None:
    if len(values) != len(candles) or price_max <= price_min:
        return
    chart_width = right - left
    step = chart_width / max(1, len(candles) - 1)
    segments: list[tuple[float, float]] = []
    for index, value in enumerate(values):
        if value is None:
            if len(segments) >= 2:
                draw.line(segments, fill=color, width=width)
            segments = []
            continue
        x = left + step * index
        y = bottom - ((value - price_min) / (price_max - price_min)) * (bottom - top)
        segments.append((x, y))
    if len(segments) >= 2:
        draw.line(segments, fill=color, width=width)


def _draw_volume(
    draw: ImageDraw.ImageDraw,
    candles: list[ChartCandle],
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> None:
    max_volume = max((candle.volume for candle in candles), default=0.0)
    if max_volume <= 0:
        return
    width = right - left
    step = width / max(1, len(candles))
    bar_w = max(3, min(10, int(step * 0.5)))
    for index, candle in enumerate(candles):
        x = left + step * index + step / 2
        bar_height = (candle.volume / max_volume) * (bottom - top - 18)
        color = (23, 198, 163, 135) if candle.close >= candle.open else (255, 77, 97, 130)
        draw.rectangle((x - bar_w / 2, bottom - bar_height, x + bar_w / 2, bottom), fill=color)


def _draw_momentum(
    draw: ImageDraw.ImageDraw,
    candles: list[ChartCandle],
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> None:
    if len(candles) < 3:
        return
    points: list[tuple[float, float]] = []
    closes = [candle.close for candle in candles]
    window = min(14, max(3, len(closes) // 5))
    width = right - left
    step = width / max(1, len(candles) - 1)
    for index, close in enumerate(closes):
        start = max(0, index - window + 1)
        low = min(closes[start : index + 1])
        high = max(closes[start : index + 1])
        score = 50.0 if high == low else ((close - low) / (high - low)) * 100
        x = left + step * index
        y = bottom - (score / 100.0) * (bottom - top)
        points.append((x, y))
    if len(points) >= 2:
        draw.line(points, fill="#56d86f", width=3)
        glow = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow, "RGBA")
        glow_draw.line(points, fill=(86, 216, 111, 95), width=7)
        glow = glow.filter(ImageFilter.GaussianBlur(3))
        draw.bitmap((0, 0), glow.split()[-1], fill=(86, 216, 111, 80))
    draw.text((right + 18, (top + bottom) // 2), "50", fill="#9aa9bb", font=_font(16), anchor="lm")


def _draw_rsi(
    draw: ImageDraw.ImageDraw,
    candles: list[ChartCandle],
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> None:
    values = rsi_values([candle.close for candle in candles], 14)
    points = panel_points(values, left, top, right, bottom, min_value=0.0, max_value=100.0)
    if len(points) >= 2:
        draw.line(points, fill="#a7f3d0", width=3)
    y70 = bottom - 0.70 * (bottom - top)
    y30 = bottom - 0.30 * (bottom - top)
    draw.line((left, y70, right, y70), fill=(255, 209, 102, 90), width=1)
    draw.line((left, y30, right, y30), fill=(255, 77, 97, 90), width=1)
    draw.text((left + 14, top + 12), "RSI 14", fill="#a7f3d0", font=_font(16, bold=True), anchor="la")
    draw.text((right + 18, y70), "70", fill="#9aa9bb", font=_font(16), anchor="lm")
    draw.text((right + 18, y30), "30", fill="#9aa9bb", font=_font(16), anchor="lm")


def _draw_macd(
    draw: ImageDraw.ImageDraw,
    candles: list[ChartCandle],
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> None:
    macd, signal = macd_values([candle.close for candle in candles])
    valid = [value for value in macd + signal if value is not None]
    if not valid:
        return
    max_abs = max(abs(min(valid)), abs(max(valid)), 1e-12)
    zero_y = bottom - ((0 + max_abs) / (max_abs * 2)) * (bottom - top)
    draw.line((left, zero_y, right, zero_y), fill=(154, 169, 187, 90), width=1)
    macd_points = panel_points(macd, left, top, right, bottom, min_value=-max_abs, max_value=max_abs)
    signal_points = panel_points(signal, left, top, right, bottom, min_value=-max_abs, max_value=max_abs)
    if len(macd_points) >= 2:
        draw.line(macd_points, fill="#56d86f", width=3)
    if len(signal_points) >= 2:
        draw.line(signal_points, fill="#ffb86b", width=3)
    draw.text((left + 14, top + 12), "MACD", fill="#a7f3d0", font=_font(16, bold=True), anchor="la")


def _draw_price_axis(
    draw: ImageDraw.ImageDraw,
    right: int,
    top: int,
    bottom: int,
    price_min: float,
    price_max: float,
    last_close: float,
    accent: str,
) -> None:
    axis_font = _font(18, bold=True)
    for index in range(6):
        value = price_max - (price_max - price_min) * (index / 5)
        y = top + ((bottom - top) * index / 5)
        draw.text((right + 18, y), format_price(value), fill="#b4becc", font=axis_font, anchor="lm")

    y = bottom - ((last_close - price_min) / (price_max - price_min)) * (bottom - top)
    label = format_price(last_close)
    x1, x2 = right + 10, 1260
    draw.line((right, y, x1, y), fill=accent, width=2)
    draw.rounded_rectangle((x1, y - 20, x2, y + 20), radius=7, fill=accent)
    draw.text(((x1 + x2) // 2, y), label, fill="#ffffff", font=axis_font, anchor="mm")


def _draw_time_axis(
    draw: ImageDraw.ImageDraw,
    candles: list[ChartCandle],
    left: int,
    right: int,
    price_y: int,
    volume_y: int,
) -> None:
    if not candles:
        return
    font = _font(17, bold=True)
    count = min(4, len(candles))
    for step_index in range(count):
        idx = int((len(candles) - 1) * (step_index / max(1, count - 1)))
        candle = candles[idx]
        x = left + (right - left) * (idx / max(1, len(candles) - 1))
        label = datetime.fromtimestamp(candle.ts, timezone.utc).strftime("%H:%M")
        draw.text((x, price_y), label, fill="#808fa2", font=font, anchor="mm")
    draw.text((left + 112, volume_y), f"Last vol {compact_number(candles[-1].volume)}", fill="#9aa9bb", font=font, anchor="la")


def _draw_footer(draw: ImageDraw.ImageDraw, data: ChartData, width: int, height: int) -> None:
    font = _font(22, bold=True)
    small = _font(18)
    draw.text((28, height - 27), "OgreScanBot", fill="#eef6ff", font=font, anchor="lm")
    draw.text((176, height - 27), f"{data.source} candles | {data.interval}", fill="#8593a6", font=small, anchor="lm")
    draw.text((width - 28, height - 27), "powered by ogres", fill="#2bff72", font=font, anchor="rm")


def _empty_chart(data: ChartData) -> BytesIO:
    image = Image.new("RGBA", (1280, 720), "#111925")
    draw = ImageDraw.Draw(image, "RGBA")
    _draw_background(draw, 1280, 720)
    draw.text((640, 318), data.title, fill="#f5f9ff", font=_font(48, bold=True), anchor="mm")
    draw.text((640, 376), "No candles available yet", fill="#9aa9bb", font=_font(30), anchor="mm")
    output = BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    output.name = "ogrescan-chart.png"
    return output


INDICATOR_ALIASES = {
    "ma": "sma",
    "sma": "sma",
    "ema": "ema",
    "bb": "bb",
    "boll": "bb",
    "bollinger": "bb",
    "bollingerbands": "bb",
    "vwap": "vwap",
    "rsi": "rsi",
    "macd": "macd",
    "stoch": "stoch",
    "stochastic": "stoch",
}


def normalize_indicators(indicators: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for item in indicators or []:
        for part in str(item).replace(",", " ").split():
            key = "".join(char for char in part.lower() if char.isalnum())
            value = INDICATOR_ALIASES.get(key)
            if value and value not in normalized:
                normalized.append(value)
    return normalized[:5]


def indicator_flags(indicators: list[str] | None) -> set[str]:
    return set(normalize_indicators(indicators))


def indicator_label(indicators: list[str] | None) -> str:
    labels = normalize_indicators(indicators)
    if not labels:
        return ""
    display = {"sma": "SMA", "ema": "EMA", "bb": "BB", "vwap": "VWAP", "rsi": "RSI", "macd": "MACD", "stoch": "Stoch"}
    return " | " + ",".join(display.get(label, label.upper()) for label in labels)


def moving_average(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = []
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= window:
            running -= values[index - window]
        if index + 1 < window:
            result.append(None)
        else:
            result.append(running / window)
    return result


def exponential_average(values: list[float], window: int) -> list[float | None]:
    if not values:
        return []
    alpha = 2 / (window + 1)
    result: list[float | None] = []
    ema = values[0]
    for index, value in enumerate(values):
        ema = (value * alpha) + (ema * (1 - alpha))
        result.append(None if index + 1 < window else ema)
    return result


def bollinger_bands(values: list[float], window: int, deviation: float) -> tuple[list[float | None], list[float | None], list[float | None]]:
    middle = moving_average(values, window)
    upper: list[float | None] = []
    lower: list[float | None] = []
    for index, mid in enumerate(middle):
        if mid is None or index + 1 < window:
            upper.append(None)
            lower.append(None)
            continue
        sample = values[index - window + 1 : index + 1]
        variance = sum((value - mid) ** 2 for value in sample) / window
        band = math.sqrt(variance) * deviation
        upper.append(mid + band)
        lower.append(mid - band)
    return upper, middle, lower


def vwap_values(candles: list[ChartCandle]) -> list[float | None]:
    total_price_volume = 0.0
    total_volume = 0.0
    values: list[float | None] = []
    for candle in candles:
        typical = (candle.high + candle.low + candle.close) / 3
        volume = candle.volume or 1.0
        total_price_volume += typical * volume
        total_volume += volume
        values.append(total_price_volume / total_volume if total_volume else None)
    return values


def rsi_values(values: list[float], window: int) -> list[float | None]:
    if len(values) < 2:
        return [None for _ in values]
    result: list[float | None] = [None]
    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, len(values)):
        delta = values[index] - values[index - 1]
        gains.append(max(delta, 0.0))
        losses.append(abs(min(delta, 0.0)))
        if len(gains) < window:
            result.append(None)
            continue
        avg_gain = sum(gains[-window:]) / window
        avg_loss = sum(losses[-window:]) / window
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100.0 - (100.0 / (1.0 + rs)))
    return result


def macd_values(values: list[float]) -> tuple[list[float | None], list[float | None]]:
    ema12 = exponential_average(values, 12)
    ema26 = exponential_average(values, 26)
    macd: list[float | None] = []
    raw_macd: list[float] = []
    for fast, slow in zip(ema12, ema26):
        if fast is None or slow is None:
            macd.append(None)
            raw_macd.append(0.0)
        else:
            value = fast - slow
            macd.append(value)
            raw_macd.append(value)
    signal_raw = exponential_average(raw_macd, 9)
    signal = [value if m is not None else None for value, m in zip(signal_raw, macd)]
    return macd, signal


def panel_points(
    values: list[float | None],
    left: int,
    top: int,
    right: int,
    bottom: int,
    min_value: float,
    max_value: float,
) -> list[tuple[float, float]]:
    if not values or max_value <= min_value:
        return []
    step = (right - left) / max(1, len(values) - 1)
    points: list[tuple[float, float]] = []
    for index, value in enumerate(values):
        if value is None:
            continue
        x = left + step * index
        y = bottom - ((value - min_value) / (max_value - min_value)) * (bottom - top)
        points.append((x, y))
    return points


def format_price(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value >= 1_000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if value >= 0.01:
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if value >= 0.000001:
        return f"{value:.8f}".rstrip("0").rstrip(".")
    return f"{value:.10f}".rstrip("0").rstrip(".")


def compact_number(value: float | None) -> str:
    if value is None:
        return "n/a"
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs_value >= 1_000:
        return f"{value / 1_000:.2f}K"
    if value == 0:
        return "0"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _shorten(text: str, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return f"{clean[: max(0, limit - 3)]}..."


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        str(BUNDLED_BOLD_FONT if bold else BUNDLED_REGULAR_FONT),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        return number
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
