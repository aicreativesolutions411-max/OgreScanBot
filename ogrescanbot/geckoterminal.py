from __future__ import annotations

from dataclasses import replace

import aiohttp

from .models import TokenScan


GECKO_API = "https://api.geckoterminal.com/api/v2"


class GeckoTerminalClient:
    def __init__(self) -> None:
        timeout = aiohttp.ClientTimeout(total=12)
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        await self._session.close()

    async def enrich_ath(self, token: TokenScan) -> TokenScan:
        if not token.pair_address or not token.price_usd or not token.cap_for_tracking:
            return token

        supply = token.cap_for_tracking / token.price_usd if token.price_usd > 0 else None
        if not supply or supply <= 0:
            return token

        best = await self.best_high_price(token.pair_address)
        if not best:
            return token

        high_price, high_ts = best
        current_ath_price = token.ath_price_usd or 0
        if high_price <= current_ath_price:
            return token

        return replace(
            token,
            ath_price_usd=high_price,
            ath_market_cap=high_price * supply,
            ath_timestamp=high_ts,
        )

    async def best_high_price(self, pool_address: str) -> tuple[float, int] | None:
        return await self.best_high_price_since(pool_address)

    async def best_high_price_since(self, pool_address: str, since_ts: int | None = None) -> tuple[float, int] | None:
        candidates = [
            ("hour", 1, 1000),
            ("minute", 15, 1000),
            ("day", 1, 365),
        ]
        best_price = 0.0
        best_ts = 0
        for timeframe, aggregate, limit in candidates:
            data = await self.ohlcv(pool_address, timeframe, aggregate, limit)
            for candle in data:
                if len(candle) < 3:
                    continue
                ts = _int_or_none(candle[0])
                high = _float_or_none(candle[2])
                if since_ts and ts and ts < since_ts:
                    continue
                if ts and high and high > best_price:
                    best_price = high
                    best_ts = ts
        if best_price <= 0 or best_ts <= 0:
            return None
        return best_price, best_ts

    async def ohlcv(
        self,
        pool_address: str,
        timeframe: str,
        aggregate: int,
        limit: int,
    ) -> list[list]:
        url = f"{GECKO_API}/networks/solana/pools/{pool_address}/ohlcv/{timeframe}"
        params = {
            "aggregate": str(aggregate),
            "limit": str(limit),
            "currency": "usd",
            "token": "base",
        }
        try:
            async with self._session.get(url, params=params) as response:
                if response.status >= 400:
                    return []
                payload = await response.json(content_type=None)
        except aiohttp.ClientError:
            return []

        data = payload.get("data") if isinstance(payload, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        candles = attributes.get("ohlcv_list") if isinstance(attributes, dict) else None
        return candles if isinstance(candles, list) else []


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
