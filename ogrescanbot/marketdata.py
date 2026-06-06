from __future__ import annotations

from urllib.parse import quote

import aiohttp

from .charts import ChartCandle, ChartData


YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
COINGECKO_MARKET_CHART_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"

CRYPTO_ALIASES = {
    "BTC": "BTC-USD",
    "BITCOIN": "BTC-USD",
    "ETH": "ETH-USD",
    "ETHEREUM": "ETH-USD",
    "SOL": "SOL-USD",
    "SOLANA": "SOL-USD",
    "DOGE": "DOGE-USD",
    "DOGECOIN": "DOGE-USD",
    "XRP": "XRP-USD",
    "ADA": "ADA-USD",
    "CARDANO": "ADA-USD",
    "AVAX": "AVAX-USD",
    "BNB": "BNB-USD",
    "LTC": "LTC-USD",
    "LINK": "LINK-USD",
    "SUI": "SUI20947-USD",
}

COINGECKO_IDS = {
    "BTC": "bitcoin",
    "BITCOIN": "bitcoin",
    "ETH": "ethereum",
    "ETHEREUM": "ethereum",
    "SOL": "solana",
    "SOLANA": "solana",
    "DOGE": "dogecoin",
    "DOGECOIN": "dogecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "CARDANO": "cardano",
    "AVAX": "avalanche-2",
    "BNB": "binancecoin",
    "LTC": "litecoin",
    "LINK": "chainlink",
    "SUI": "sui",
}

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36 OgreScanBot/1.0"
    ),
    "Accept": "application/json,text/plain,*/*",
}


class YahooChartClient:
    def __init__(self) -> None:
        timeout = aiohttp.ClientTimeout(total=12)
        self._session = aiohttp.ClientSession(timeout=timeout, headers=REQUEST_HEADERS)

    async def close(self) -> None:
        await self._session.close()

    async def chart_for_query(
        self,
        query: str,
        timeframe: str = "5m",
        indicators: list[str] | None = None,
    ) -> ChartData | None:
        clean = normalize_market_query(query)
        if not clean:
            return None

        candidates = await self.symbol_candidates(clean)
        for symbol, display_name, quote_type in candidates:
            data = await self.chart_for_symbol(
                symbol,
                display_name=display_name,
                quote_type=quote_type,
                timeframe=timeframe,
                indicators=indicators,
            )
            if data:
                return data

        return await self.coingecko_chart_for_query(clean, timeframe=timeframe, indicators=indicators)

    async def resolve_symbol(self, query: str) -> tuple[str | None, str | None, str | None]:
        candidates = await self.symbol_candidates(query)
        return candidates[0] if candidates else (None, None, None)

    async def symbol_candidates(self, query: str) -> list[tuple[str, str | None, str | None]]:
        clean = normalize_market_query(query)
        if not clean:
            return []

        candidates: list[tuple[str, str | None, str | None]] = []
        alias = CRYPTO_ALIASES.get(clean.upper())
        if alias:
            candidates.append((alias, clean.upper(), "CRYPTOCURRENCY"))

        if clean.upper().endswith("-USD"):
            candidates.append((clean.upper(), clean.upper(), "CRYPTOCURRENCY"))

        if is_likely_symbol(clean):
            candidates.append((clean.upper(), clean.upper(), None))

        try:
            async with self._session.get(YAHOO_SEARCH_URL, params={"q": clean, "quotesCount": "8", "newsCount": "0"}) as response:
                if response.status >= 400:
                    return unique_symbol_candidates(candidates)
                payload = await response.json(content_type=None)
        except aiohttp.ClientError:
            return unique_symbol_candidates(candidates)

        quotes = payload.get("quotes") if isinstance(payload, dict) else None
        if not isinstance(quotes, list):
            return unique_symbol_candidates(candidates)

        preferred = []
        for quote_data in quotes:
            if not isinstance(quote_data, dict):
                continue
            symbol = _string_or_none(quote_data.get("symbol"))
            if not symbol:
                continue
            quote_type = _string_or_none(quote_data.get("quoteType"))
            if quote_type not in {"EQUITY", "ETF", "CRYPTOCURRENCY", "INDEX", "MUTUALFUND"}:
                continue
            name = (
                _string_or_none(quote_data.get("shortname"))
                or _string_or_none(quote_data.get("longname"))
                or symbol
            )
            score = market_quote_score(quote_data, clean)
            preferred.append((score, symbol, name, quote_type))

        if not preferred:
            return unique_symbol_candidates(candidates)
        preferred.sort(reverse=True)
        candidates.extend((symbol, name, quote_type) for _score, symbol, name, quote_type in preferred)
        return unique_symbol_candidates(candidates)

    async def chart_for_symbol(
        self,
        symbol: str,
        display_name: str | None = None,
        quote_type: str | None = None,
        timeframe: str = "5m",
        indicators: list[str] | None = None,
    ) -> ChartData | None:
        symbol = normalize_market_query(symbol).upper()
        if not symbol:
            return None

        for range_value, interval, label, source_label, resample_seconds in yahoo_ranges_for_timeframe(timeframe):
            data = await self._chart(
                symbol,
                range_value,
                interval,
                label,
                source_label,
                resample_seconds,
                display_name,
                quote_type,
                indicators,
            )
            if data and len(data.candles) >= 2:
                return data
        return None

    async def _chart(
        self,
        symbol: str,
        range_value: str,
        interval: str,
        label: str,
        source_label: str,
        resample_seconds: int | None,
        display_name: str | None,
        quote_type: str | None,
        indicators: list[str] | None,
    ) -> ChartData | None:
        url = f"{YAHOO_CHART_URL}/{quote(symbol, safe='')}"
        params = {
            "range": range_value,
            "interval": interval,
            "includePrePost": "false",
            "events": "history",
        }
        try:
            async with self._session.get(url, params=params) as response:
                if response.status >= 400:
                    return None
                payload = await response.json(content_type=None)
        except aiohttp.ClientError:
            return None

        result = ((payload.get("chart") or {}).get("result") or [None])[0] if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            return None
        timestamps = result.get("timestamp")
        quote_block = (((result.get("indicators") or {}).get("quote") or [None])[0])
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        if not isinstance(timestamps, list) or not isinstance(quote_block, dict):
            return None

        opens = quote_block.get("open") or []
        highs = quote_block.get("high") or []
        lows = quote_block.get("low") or []
        closes = quote_block.get("close") or []
        volumes = quote_block.get("volume") or []

        candles: list[ChartCandle] = []
        for index, ts in enumerate(timestamps):
            candle = candle_from_yahoo(ts, opens, highs, lows, closes, volumes, index)
            if candle:
                candles.append(candle)

        if len(candles) < 2:
            return None
        if resample_seconds:
            candles = resample_candles(candles, resample_seconds)
            if len(candles) < 2:
                return None

        name = (
            display_name
            or _string_or_none(meta.get("shortName"))
            or _string_or_none(meta.get("longName"))
            or symbol
        )
        resolved_symbol = _string_or_none(meta.get("symbol")) or symbol
        kind = quote_type or _string_or_none(meta.get("instrumentType")) or "MARKET"
        source_url = f"https://finance.yahoo.com/quote/{quote(resolved_symbol, safe='')}"
        return ChartData(
            title=name,
            symbol=resolved_symbol,
            subtitle=f"{kind} | Yahoo Finance | {range_value}",
            source="Yahoo Finance",
            source_url=source_url,
            interval=label,
            source_interval=source_label,
            indicators=indicators or [],
            candles=candles[-160:],
        )

    async def coingecko_chart_for_query(
        self,
        query: str,
        timeframe: str = "5m",
        indicators: list[str] | None = None,
    ) -> ChartData | None:
        clean = normalize_market_query(query).upper()
        coin_id = COINGECKO_IDS.get(clean)
        if not coin_id and clean.endswith("-USD"):
            coin_id = COINGECKO_IDS.get(clean.removesuffix("-USD"))
        if not coin_id:
            return None

        url = COINGECKO_MARKET_CHART_URL.format(coin_id=coin_id)
        params = {"vs_currency": "usd", "days": coingecko_days_for_timeframe(timeframe)}
        try:
            async with self._session.get(url, params=params) as response:
                if response.status >= 400:
                    return None
                payload = await response.json(content_type=None)
        except aiohttp.ClientError:
            return None

        prices = payload.get("prices") if isinstance(payload, dict) else None
        volumes = payload.get("total_volumes") if isinstance(payload, dict) else None
        if not isinstance(prices, list):
            return None

        bucket_seconds = timeframe_seconds(timeframe) or 300
        candles = coingecko_candles(prices, volumes if isinstance(volumes, list) else [], bucket_seconds=bucket_seconds)
        if len(candles) < 2:
            return None

        symbol = clean.removesuffix("-USD")
        return ChartData(
            title=symbol,
            symbol=f"{symbol}-USD",
            subtitle="CRYPTOCURRENCY | CoinGecko | 1d",
            source="CoinGecko",
            source_url=f"https://www.coingecko.com/en/coins/{coin_id}",
            interval=timeframe,
            source_interval="market_chart",
            indicators=indicators or [],
            candles=candles[-160:],
        )


def yahoo_ranges_for_timeframe(timeframe: str) -> list[tuple[str, str, str, str, int | None]]:
    tf = normalize_timeframe_label(timeframe)
    direct = {
        "1m": ("1d", "1m", "1m", "1m", None),
        "5m": ("5d", "5m", "5m", "5m", None),
        "15m": ("5d", "15m", "15m", "15m", None),
        "30m": ("1mo", "30m", "30m", "30m", None),
        "1h": ("1mo", "60m", "1h", "1h", None),
        "1d": ("1y", "1d", "1d", "1d", None),
        "1w": ("2y", "1wk", "1w", "1w", None),
        "1M": ("5y", "1mo", "1M", "1M", None),
    }
    resampled = {
        "1s": ("1d", "1m", "1s", "1m", None),
        "5s": ("1d", "1m", "5s", "1m", None),
        "15s": ("1d", "1m", "15s", "1m", None),
        "30s": ("1d", "1m", "30s", "1m", None),
        "3m": ("1d", "1m", "3m", "1m", 180),
        "45m": ("5d", "15m", "45m", "15m", 2700),
        "2h": ("1mo", "60m", "2h", "1h", 7200),
        "3h": ("1mo", "60m", "3h", "1h", 10800),
        "4h": ("1mo", "60m", "4h", "1h", 14400),
        "3d": ("1y", "1d", "3d", "1d", 259200),
    }
    primary = direct.get(tf) or resampled.get(tf) or direct["5m"]
    fallbacks = [
        primary,
        ("5d", "5m", tf, "5m", timeframe_seconds(tf) if tf not in {"1s", "5s", "15s", "30s"} else None),
        ("1mo", "60m", tf, "1h", timeframe_seconds(tf) if timeframe_seconds(tf) and timeframe_seconds(tf) >= 3600 else None),
        ("1y", "1d", tf, "1d", timeframe_seconds(tf) if timeframe_seconds(tf) and timeframe_seconds(tf) >= 86400 else None),
    ]
    unique: list[tuple[str, str, str, str, int | None]] = []
    seen: set[tuple[str, str, int | None]] = set()
    for item in fallbacks:
        key = (item[0], item[1], item[4])
        if key not in seen:
            unique.append(item)
            seen.add(key)
    return unique


def normalize_timeframe_label(timeframe: str | None) -> str:
    raw = str(timeframe or "5m").strip()
    if raw == "1M":
        return "1M"
    lowered = raw.lower()
    if lowered in {"1mo", "1month", "1month"}:
        return "1M"
    return lowered


def timeframe_seconds(timeframe: str | None) -> int | None:
    tf = normalize_timeframe_label(timeframe)
    if tf.endswith("s"):
        return _int_or_none(tf[:-1])
    if tf.endswith("m") and tf != "1M":
        minutes = _int_or_none(tf[:-1])
        return minutes * 60 if minutes else None
    if tf.endswith("h"):
        hours = _int_or_none(tf[:-1])
        return hours * 3600 if hours else None
    if tf.endswith("d"):
        days = _int_or_none(tf[:-1])
        return days * 86400 if days else None
    if tf.endswith("w"):
        weeks = _int_or_none(tf[:-1])
        return weeks * 604800 if weeks else None
    if tf == "1M":
        return 30 * 86400
    return None


def coingecko_days_for_timeframe(timeframe: str) -> str:
    seconds = timeframe_seconds(timeframe) or 300
    if seconds < 86400:
        return "1"
    if seconds < 604800:
        return "30"
    return "365"


def resample_candles(candles: list[ChartCandle], bucket_seconds: int) -> list[ChartCandle]:
    if bucket_seconds <= 0:
        return candles
    grouped: dict[int, list[ChartCandle]] = {}
    for candle in candles:
        bucket = (candle.ts // bucket_seconds) * bucket_seconds
        grouped.setdefault(bucket, []).append(candle)
    result: list[ChartCandle] = []
    for bucket in sorted(grouped):
        group = sorted(grouped[bucket], key=lambda candle: candle.ts)
        if not group:
            continue
        result.append(
            ChartCandle(
                ts=bucket,
                open=group[0].open,
                high=max(candle.high for candle in group),
                low=min(candle.low for candle in group),
                close=group[-1].close,
                volume=sum(candle.volume for candle in group),
            )
        )
    return result


def normalize_market_query(query: str | None) -> str:
    text = str(query or "").strip()
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        text = parts[1] if len(parts) > 1 else ""
    return text.strip().removeprefix("$").strip()


def is_likely_symbol(query: str) -> bool:
    clean = query.strip()
    if not clean or " " in clean:
        return False
    if clean.upper() in CRYPTO_ALIASES:
        return True
    if clean.upper().endswith("-USD"):
        return True
    return clean.replace(".", "").replace("-", "").isalnum() and len(clean) <= 8


def market_quote_score(quote_data: dict, query: str) -> float:
    symbol = str(quote_data.get("symbol") or "").upper()
    name = " ".join(
        str(quote_data.get(key) or "")
        for key in ("shortname", "longname", "name")
    ).upper()
    clean = query.upper()
    score = 0.0
    if symbol == clean:
        score += 100.0
    if clean in name:
        score += 45.0
    quote_type = quote_data.get("quoteType")
    if quote_type in {"EQUITY", "ETF", "CRYPTOCURRENCY"}:
        score += 25.0
    score += float(quote_data.get("score") or 0) * 5.0
    return score


def unique_symbol_candidates(candidates: list[tuple[str, str | None, str | None]]) -> list[tuple[str, str | None, str | None]]:
    seen: set[str] = set()
    unique: list[tuple[str, str | None, str | None]] = []
    for symbol, display_name, quote_type in candidates:
        clean = str(symbol or "").strip().upper()
        if not clean or clean in seen:
            continue
        unique.append((clean, display_name, quote_type))
        seen.add(clean)
    return unique


def coingecko_candles(prices: list, volumes: list, bucket_seconds: int = 300) -> list[ChartCandle]:
    volume_by_bucket: dict[int, float] = {}
    for point in volumes:
        if not isinstance(point, list) or len(point) < 2:
            continue
        ts_ms = _int_or_none(point[0])
        volume = _float_or_none(point[1])
        if not ts_ms or volume is None:
            continue
        bucket = (ts_ms // 1000 // bucket_seconds) * bucket_seconds
        volume_by_bucket[bucket] = max(volume_by_bucket.get(bucket, 0.0), volume)

    grouped: dict[int, list[float]] = {}
    for point in prices:
        if not isinstance(point, list) or len(point) < 2:
            continue
        ts_ms = _int_or_none(point[0])
        price = _float_or_none(point[1])
        if not ts_ms or price is None or price <= 0:
            continue
        bucket = (ts_ms // 1000 // bucket_seconds) * bucket_seconds
        grouped.setdefault(bucket, []).append(price)

    candles: list[ChartCandle] = []
    for bucket in sorted(grouped):
        values = grouped[bucket]
        if not values:
            continue
        candles.append(
            ChartCandle(
                ts=bucket,
                open=values[0],
                high=max(values),
                low=min(values),
                close=values[-1],
                volume=volume_by_bucket.get(bucket, 0.0),
            )
        )
    return candles


def candle_from_yahoo(
    ts: object,
    opens: list,
    highs: list,
    lows: list,
    closes: list,
    volumes: list,
    index: int,
) -> ChartCandle | None:
    timestamp = _int_or_none(ts)
    open_price = _value_at(opens, index)
    high = _value_at(highs, index)
    low = _value_at(lows, index)
    close = _value_at(closes, index)
    volume = _value_at(volumes, index) or 0.0
    if not timestamp or open_price is None or high is None or low is None or close is None:
        return None
    if high <= 0 or low <= 0 or close <= 0:
        return None
    return ChartCandle(timestamp, open_price, high, low, close, max(0.0, volume))


def _value_at(items: list, index: int) -> float | None:
    if index >= len(items):
        return None
    return _float_or_none(items[index])


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
