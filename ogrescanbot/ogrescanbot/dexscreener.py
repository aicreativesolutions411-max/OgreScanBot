from __future__ import annotations

import aiohttp

from .models import TokenScan, normalize_media_url


DEX_API = "https://api.dexscreener.com"


class DexscreenerClient:
    def __init__(self) -> None:
        timeout = aiohttp.ClientTimeout(total=12)
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        await self._session.close()

    async def scan_solana_token(self, token_address: str) -> TokenScan | None:
        pairs = await self._token_pairs(token_address)
        if not pairs:
            pairs = await self._search(token_address)
        pairs = [pair for pair in pairs if pair.get("chainId") == "solana"]
        if not pairs:
            return None
        pair = max(pairs, key=lambda item: float((item.get("liquidity") or {}).get("usd") or 0))
        base = pair.get("baseToken") or {}
        info = _merged_info(pair, pairs)
        txns_h1 = (pair.get("txns") or {}).get("h1") or {}
        price_change = pair.get("priceChange") or {}
        volume = pair.get("volume") or {}
        liquidity = pair.get("liquidity") or {}

        return TokenScan(
            address=base.get("address") or token_address,
            name=base.get("name") or "Unknown",
            symbol=base.get("symbol") or "?",
            chain_id=pair.get("chainId") or "solana",
            dex_id=pair.get("dexId") or "?",
            pair_address=pair.get("pairAddress") or "",
            pair_url=pair.get("url") or f"https://dexscreener.com/solana/{token_address}",
            price_usd=_float_or_none(pair.get("priceUsd")),
            market_cap=_float_or_none(pair.get("marketCap")),
            fdv=_float_or_none(pair.get("fdv")),
            liquidity_usd=_float_or_none(liquidity.get("usd")),
            volume_h24=_float_or_none(volume.get("h24")),
            price_change_h1=_float_or_none(price_change.get("h1")),
            price_change_h24=_float_or_none(price_change.get("h24")),
            buys_h1=_int_or_none(txns_h1.get("buys")),
            sells_h1=_int_or_none(txns_h1.get("sells")),
            created_at_ms=_int_or_none(pair.get("pairCreatedAt")),
            image_url=normalize_media_url(_string_or_none(info.get("imageUrl"))),
            header_url=normalize_media_url(_string_or_none(info.get("header"))),
            description=_string_or_none(info.get("description")),
            socials=info.get("socials") or [],
            websites=info.get("websites") or [],
            raw_pair=pair,
            dex_paid=_boosts_paid(pair),
        )

    async def token_orders_paid(self, chain_id: str, token_address: str) -> bool | None:
        url = f"{DEX_API}/orders/v1/{chain_id}/{token_address}"
        try:
            async with self._session.get(url) as response:
                if response.status >= 400:
                    return None
                data = await response.json(content_type=None)
        except aiohttp.ClientError:
            return None

        orders = data
        if isinstance(data, dict):
            orders = data.get("orders") or data.get("data") or []
        if not isinstance(orders, list):
            return None
        if not orders:
            return False
        return any(_paid_order(order) for order in orders if isinstance(order, dict))

    async def _token_pairs(self, token_address: str) -> list[dict]:
        url = f"{DEX_API}/token-pairs/v1/solana/{token_address}"
        async with self._session.get(url) as response:
            if response.status >= 400:
                return []
            data = await response.json(content_type=None)
        return data if isinstance(data, list) else []

    async def _search(self, query: str) -> list[dict]:
        url = f"{DEX_API}/latest/dex/search"
        async with self._session.get(url, params={"q": query}) as response:
            if response.status >= 400:
                return []
            data = await response.json(content_type=None)
        return data.get("pairs") or []


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


def _merged_info(selected_pair: dict, pairs: list[dict]) -> dict:
    selected = selected_pair.get("info") or {}
    infos = [selected] + [pair.get("info") or {} for pair in pairs if pair is not selected_pair]
    merged = dict(selected)
    for key in ["imageUrl", "header", "description"]:
        if not merged.get(key):
            for info in infos:
                if info.get(key):
                    merged[key] = info.get(key)
                    break
    for key in ["socials", "websites"]:
        if not merged.get(key):
            for info in infos:
                if info.get(key):
                    merged[key] = info.get(key)
                    break
    return merged


def _boosts_paid(pair: dict) -> bool | None:
    boosts = pair.get("boosts") or {}
    if not isinstance(boosts, dict):
        return None
    active = _float_or_none(boosts.get("active"))
    if active is None:
        return None
    return active > 0


def _paid_order(order: dict) -> bool:
    status = str(order.get("status") or "").lower()
    payment_timestamp = order.get("paymentTimestamp")
    if payment_timestamp:
        return status not in {"cancelled", "rejected"}
    return status in {"approved", "processing", "on-hold"}
