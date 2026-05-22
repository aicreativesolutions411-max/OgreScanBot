from __future__ import annotations

import math

import aiohttp

from .extract import is_solana_address


JUPITER_TOKEN_SEARCH_URL = "https://api.jup.ag/tokens/v2/search"
JUPITER_VERIFIED_TAG_URL = "https://api.jup.ag/tokens/v2/tag"


class JupiterTokenClient:
    def __init__(self, api_key: str = "") -> None:
        timeout = aiohttp.ClientTimeout(total=10)
        self.api_key = api_key.strip()
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        await self._session.close()

    async def best_token_mint(self, ticker: str) -> str | None:
        symbol = str(ticker or "").strip().upper().removeprefix("$")
        if not symbol or is_solana_address(symbol):
            return None

        candidates = await self.search(symbol)
        if not candidates:
            candidates = await self.verified_list(symbol)
        exact = [
            item
            for item in candidates
            if str(item.get("symbol") or "").strip().upper() == symbol
        ]
        if not exact:
            return None
        exact.sort(key=_jupiter_score, reverse=True)
        return _mint(exact[0])

    async def token_by_mint(self, mint: str) -> dict | None:
        mint = str(mint or "").strip()
        if not is_solana_address(mint):
            return None
        candidates = await self.search(mint)
        exact = [item for item in candidates if _mint(item) == mint]
        if exact:
            exact.sort(key=_jupiter_score, reverse=True)
            return exact[0]
        return candidates[0] if len(candidates) == 1 else None

    async def search(self, query: str) -> list[dict]:
        if not self.api_key:
            return []
        headers = {"x-api-key": self.api_key}
        try:
            async with self._session.get(
                JUPITER_TOKEN_SEARCH_URL,
                params={"query": query},
                headers=headers,
            ) as response:
                if response.status >= 400:
                    return []
                data = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError):
            return []
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        items = (data.get("tokens") or data.get("data")) if isinstance(data, dict) else None
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    async def verified_list(self, symbol: str) -> list[dict]:
        if not self.api_key:
            return []
        headers = {"x-api-key": self.api_key}
        try:
            async with self._session.get(
                JUPITER_VERIFIED_TAG_URL,
                params={"query": "verified"},
                headers=headers,
            ) as response:
                if response.status >= 400:
                    return []
                data = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        wanted = symbol.strip().upper()
        return [
            item
            for item in data
            if isinstance(item, dict) and str(item.get("symbol") or "").strip().upper() == wanted
        ]


def _jupiter_score(item: dict) -> float:
    score = 0.0
    if _boolish(item.get("isVerified") or item.get("verified")):
        score += 20_000
    if _boolish(item.get("strict") or item.get("isStrict")):
        score += 5_000
    if _boolish(item.get("banned") or item.get("isBanned") or item.get("freezeAuthority")):
        score -= 50_000

    audit = item.get("audit") if isinstance(item.get("audit"), dict) else {}
    if _boolish(audit.get("isSus") or audit.get("mintAuthority") or audit.get("freezeAuthority")):
        score -= 20_000

    score += _log_score(item, ("organicScore", "organic_score"), 12.0)
    score += _log_score(item, ("mcap", "marketCap", "market_cap", "fdv"), 3.0)
    score += _log_score(item, ("liquidity", "liquidityUsd", "liquidity_usd"), 4.0)
    score += _log_score(item, ("daily_volume", "volume24h", "volume_24h"), 2.0)
    score += _log_score(item, ("holderCount", "holders", "holder_count"), 1.5)

    if item.get("logoURI") or item.get("icon"):
        score += 100
    if item.get("twitter") or item.get("telegram") or item.get("website"):
        score += 200
    return score


def _log_score(item: dict, keys: tuple[str, ...], weight: float) -> float:
    for key in keys:
        value = _float_or_none(item.get(key))
        if value is not None and value > 0:
            return math.log1p(value) * weight
    return 0.0


def _mint(item: dict) -> str | None:
    for key in ("address", "id", "mint", "mintAddress"):
        value = str(item.get(key) or "").strip()
        if is_solana_address(value):
            return value
    return None


def _boolish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
