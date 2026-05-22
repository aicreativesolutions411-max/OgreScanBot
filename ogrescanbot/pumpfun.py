from __future__ import annotations

import aiohttp

from .models import TokenScan, normalize_media_url, pump_bonding_progress_pct, pump_is_complete


PUMP_METADATA_URLS = (
    "https://frontend-api-v3.pump.fun/coins/{mint}",
    "https://frontend-api-v2.pump.fun/coins/{mint}",
    "https://frontend-api.pump.fun/coins/{mint}",
)
PUMP_SEARCH_URLS = (
    "https://frontend-api-v3.pump.fun/coins",
    "https://frontend-api-v2.pump.fun/coins",
    "https://frontend-api.pump.fun/coins",
)
PUMP_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/",
    "User-Agent": "Mozilla/5.0 OgreScanBot/1.0",
}


class PumpFunClient:
    def __init__(self) -> None:
        timeout = aiohttp.ClientTimeout(total=10)
        self._session = aiohttp.ClientSession(timeout=timeout, headers=PUMP_HEADERS)

    async def close(self) -> None:
        await self._session.close()

    async def metadata(self, mint: str) -> dict:
        mint = str(mint or "").strip()
        if not mint:
            return {}

        for pattern in PUMP_METADATA_URLS:
            url = pattern.format(mint=mint)
            try:
                async with self._session.get(url, params={"sync": "true"}) as response:
                    if response.status >= 400:
                        continue
                    data = await response.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError):
                continue
            if isinstance(data, dict) and data:
                return data
        return {}

    async def best_token_mint_by_ticker(self, ticker: str) -> str | None:
        symbol = str(ticker or "").strip().upper().removeprefix("$")
        if not symbol:
            return None

        candidates = await self.search(symbol)
        exact = [
            item
            for item in candidates
            if str(item.get("symbol") or "").strip().upper() == symbol
        ]
        matched = exact or [
            item
            for item in candidates
            if symbol in str(item.get("symbol") or item.get("name") or "").strip().upper()
        ]
        if not matched and len(candidates) == 1:
            matched = candidates
        if not matched:
            return None
        matched.sort(key=_pump_score, reverse=True)
        return _string_or_none(matched[0].get("mint"))

    async def search(self, query: str) -> list[dict]:
        query = str(query or "").strip()
        if not query:
            return []
        params = {
            "offset": "0",
            "limit": "50",
            "sort": "market_cap",
            "order": "DESC",
            "includeNsfw": "true",
            "searchTerm": query,
        }
        for url in PUMP_SEARCH_URLS:
            try:
                async with self._session.get(url, params=params) as response:
                    if response.status >= 400:
                        continue
                    data = await response.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError):
                continue
            items = _items_from_search_response(data)
            if items:
                return items
        return []

    async def scan_token(self, mint: str) -> TokenScan | None:
        data = await self.metadata(mint)
        if not data:
            return None

        socials = []
        websites = []
        if data.get("twitter"):
            socials.append({"type": "twitter", "url": data.get("twitter")})
        if data.get("telegram"):
            socials.append({"type": "telegram", "url": data.get("telegram")})
        if data.get("website"):
            websites.append({"label": "Web", "url": data.get("website")})

        cap = _float_or_none(data.get("usd_market_cap")) or _float_or_none(data.get("market_cap"))
        return TokenScan(
            address=str(data.get("mint") or mint),
            name=str(data.get("name") or "Unknown"),
            symbol=str(data.get("symbol") or "?"),
            chain_id="solana",
            dex_id="pump",
            pair_address="",
            pair_url=f"https://pump.fun/coin/{mint}",
            price_usd=None,
            market_cap=cap,
            fdv=cap,
            liquidity_usd=None,
            volume_h24=None,
            price_change_h1=None,
            price_change_h24=None,
            buys_h1=None,
            sells_h1=None,
            created_at_ms=_int_or_none(data.get("created_timestamp")),
            image_url=normalize_media_url(_string_or_none(data.get("image_uri"))),
            header_url=None,
            description=_string_or_none(data.get("description")),
            socials=socials,
            websites=websites,
            raw_pair=data,
            bonding_progress_pct=pump_bonding_progress_pct(data, cap),
            is_pump_complete=pump_is_complete(data),
            dex_paid=False,
        )


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


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _items_from_search_response(data: object) -> list[dict]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("coins", "data", "items", "results"):
        items = data.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _pump_score(item: dict) -> float:
    cap = _float_or_none(item.get("usd_market_cap")) or _float_or_none(item.get("market_cap")) or 0
    liquidity = (
        _float_or_none(item.get("virtual_sol_reserves"))
        or _float_or_none(item.get("real_sol_reserves"))
        or _float_or_none(item.get("liquidity"))
        or 0
    )
    score = cap + (liquidity * 10)
    if item.get("complete"):
        score += 5_000
    if item.get("raydium_pool") or item.get("pump_swap_pool"):
        score += 2_500
    if item.get("twitter") or item.get("telegram") or item.get("website"):
        score += 1_000
    if item.get("image_uri"):
        score += 250
    if item.get("hidden") or item.get("is_banned"):
        score -= 100_000
    return score
