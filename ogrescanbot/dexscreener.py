from __future__ import annotations

import math
import time

import aiohttp

from .extract import is_solana_address
from .models import TokenScan, normalize_media_url


DEX_API = "https://api.dexscreener.com"


class DexscreenerClient:
    def __init__(self) -> None:
        timeout = aiohttp.ClientTimeout(total=12)
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        await self._session.close()

    async def scan_solana_token(self, token_address: str, strict_ticker: bool = True) -> TokenScan | None:
        query = str(token_address or "").strip()
        query_is_address = is_solana_address(query)
        search_query = query if query_is_address else query.removeprefix("$")
        pairs = await self._token_pairs(query) if query_is_address else []
        pairs = [pair for pair in pairs if pair.get("chainId") == "solana"]
        if query_is_address and not pairs:
            pairs = await self._pair_by_address(query)
        if not pairs:
            pairs = await self._search(search_query)
        pairs = [pair for pair in pairs if pair.get("chainId") == "solana"]
        if not pairs:
            return None
        pair = _select_pair(pairs, search_query, query_is_address, strict_ticker=strict_ticker)
        if not pair and query_is_address:
            pair = _max_liquidity_pair(_pair_address_matches(pairs, query))
        if not pair:
            return None
        base = pair.get("baseToken") or {}
        base_address = _string_or_none(base.get("address")) or query
        related_pairs = _same_base_pairs(pairs, base_address) or [pair]
        info = _merged_info(pair, related_pairs)
        txns_h1 = (pair.get("txns") or {}).get("h1") or {}
        price_change = pair.get("priceChange") or {}
        volume = pair.get("volume") or {}
        liquidity = pair.get("liquidity") or {}
        market_cap = _float_or_none(pair.get("marketCap")) or _max_float_from_pairs(related_pairs, "marketCap")
        fdv = _float_or_none(pair.get("fdv")) or _max_float_from_pairs(related_pairs, "fdv") or market_cap

        return TokenScan(
            address=base_address,
            name=base.get("name") or "Unknown",
            symbol=base.get("symbol") or "?",
            chain_id=pair.get("chainId") or "solana",
            dex_id=pair.get("dexId") or "?",
            pair_address=pair.get("pairAddress") or "",
            pair_url=pair.get("url") or f"https://dexscreener.com/solana/{base_address}",
            price_usd=_float_or_none(pair.get("priceUsd")) or _first_float_from_pairs(related_pairs, "priceUsd"),
            market_cap=market_cap,
            fdv=fdv,
            liquidity_usd=_float_or_none(liquidity.get("usd")) or _max_nested_float_from_pairs(related_pairs, "liquidity", "usd"),
            volume_h24=_float_or_none(volume.get("h24")) or _max_nested_float_from_pairs(related_pairs, "volume", "h24"),
            price_change_h1=_float_or_none(price_change.get("h1")) or _first_nested_float_from_pairs(related_pairs, "priceChange", "h1"),
            price_change_h24=_float_or_none(price_change.get("h24")) or _first_nested_float_from_pairs(related_pairs, "priceChange", "h24"),
            buys_h1=_int_or_none(txns_h1.get("buys")),
            sells_h1=_int_or_none(txns_h1.get("sells")),
            created_at_ms=_earliest_int_from_pairs(related_pairs, "pairCreatedAt") or _int_or_none(pair.get("pairCreatedAt")),
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

    async def _pair_by_address(self, pair_address: str) -> list[dict]:
        url = f"{DEX_API}/latest/dex/pairs/solana/{pair_address}"
        async with self._session.get(url) as response:
            if response.status >= 400:
                return []
            data = await response.json(content_type=None)
        pairs = data.get("pairs") if isinstance(data, dict) else None
        return pairs if isinstance(pairs, list) else []

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


def _select_pair(pairs: list[dict], query: str, query_is_address: bool, strict_ticker: bool = True) -> dict | None:
    if query_is_address:
        matches = [
            pair
            for pair in pairs
            if _token_address(pair.get("baseToken")) == query
        ]
        if matches:
            return _max_liquidity_pair(matches)
        normalized_matches = [
            pair
            for pair in pairs
            if str(_token_address(pair.get("baseToken")) or "").lower() == query.lower()
        ]
        if normalized_matches:
            return _max_liquidity_pair(normalized_matches)
        return None

    symbol = query.strip().upper().removeprefix("$")
    if not symbol:
        return None
    matches = [
        pair
        for pair in pairs
        if str((pair.get("baseToken") or {}).get("symbol") or "").strip().upper() == symbol
    ]
    if not strict_ticker and not matches:
        matches = pairs
    return _best_ticker_pair(matches)


def _same_base_pairs(pairs: list[dict], base_address: str) -> list[dict]:
    return [pair for pair in pairs if _token_address(pair.get("baseToken")) == base_address]


def _pair_address_matches(pairs: list[dict], pair_address: str) -> list[dict]:
    return [
        pair
        for pair in pairs
        if str(pair.get("pairAddress") or "").strip() == pair_address
    ]


def _max_liquidity_pair(pairs: list[dict]) -> dict | None:
    if not pairs:
        return None
    return max(pairs, key=lambda item: float((item.get("liquidity") or {}).get("usd") or 0))


def _best_ticker_pair(pairs: list[dict]) -> dict | None:
    candidates = [_best_pair_for_token(token_pairs) for token_pairs in _pairs_by_base(pairs).values()]
    candidates = [pair for pair in candidates if pair]
    if not candidates:
        return None
    liquid = [pair for pair in candidates if _nested_float(pair, "liquidity", "usd") and _nested_float(pair, "liquidity", "usd") > 0]
    candidates = liquid or candidates
    candidates.sort(key=_ticker_pair_score, reverse=True)
    return candidates[0]


def _pairs_by_base(pairs: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for pair in pairs:
        address = _token_address(pair.get("baseToken"))
        if address:
            groups.setdefault(address, []).append(pair)
    return groups


def _best_pair_for_token(pairs: list[dict]) -> dict | None:
    if not pairs:
        return None
    return max(pairs, key=_pair_liquidity_volume_score)


def _pair_liquidity_volume_score(pair: dict) -> float:
    return (
        (_nested_float(pair, "liquidity", "usd") or 0) * 3
        + (_nested_float(pair, "volume", "h24") or 0)
    )


def _ticker_pair_score(pair: dict) -> float:
    liquidity = _nested_float(pair, "liquidity", "usd") or 0
    volume = _nested_float(pair, "volume", "h24") or 0
    market_cap = _float_or_none(pair.get("marketCap")) or _float_or_none(pair.get("fdv")) or 0
    created_at = _int_or_none(pair.get("pairCreatedAt")) or 0
    info = pair.get("info") if isinstance(pair.get("info"), dict) else {}
    socials = info.get("socials") if isinstance(info.get("socials"), list) else []
    websites = info.get("websites") if isinstance(info.get("websites"), list) else []
    boosts = pair.get("boosts") if isinstance(pair.get("boosts"), dict) else {}
    txns_h24 = (pair.get("txns") or {}).get("h24") or {}
    buys_h24 = _float_or_none(txns_h24.get("buys")) or 0
    sells_h24 = _float_or_none(txns_h24.get("sells")) or 0

    score = 0.0
    score += math.sqrt(max(market_cap, 0)) * 4.0
    score += math.sqrt(max(liquidity, 0)) * 7.0
    score += math.sqrt(max(volume, 0)) * 1.5
    score += math.sqrt(max(buys_h24 + sells_h24, 0)) * 12.0
    if created_at > 0:
        age_days = max(0.0, ((time.time() * 1000) - created_at) / 86_400_000)
        score += min(250.0, age_days * 1.5)
    if socials:
        score += 80
    if websites:
        score += 60
    if info.get("imageUrl") or info.get("header"):
        score += 25
    if _float_or_none(boosts.get("active")):
        score += 120
    if liquidity <= 0:
        score -= 50_000
    elif liquidity < 1_000:
        score -= 120
    if market_cap <= 0:
        score -= 250
    if not socials and not websites:
        score -= 50
    return score


def _nested_float(item: dict, outer_key: str, inner_key: str) -> float | None:
    nested = item.get(outer_key) if isinstance(item, dict) else None
    if not isinstance(nested, dict):
        return None
    return _float_or_none(nested.get(inner_key))


def _token_address(token: object) -> str | None:
    if not isinstance(token, dict):
        return None
    return _string_or_none(token.get("address"))


def _positive(value: float | None) -> bool:
    return value is not None and value > 0


def _first_float_from_pairs(pairs: list[dict], key: str) -> float | None:
    for pair in pairs:
        value = _float_or_none(pair.get(key))
        if _positive(value):
            return value
    return None


def _max_float_from_pairs(pairs: list[dict], key: str) -> float | None:
    values = [_float_or_none(pair.get(key)) for pair in pairs]
    values = [value for value in values if _positive(value)]
    return max(values) if values else None


def _first_nested_float_from_pairs(pairs: list[dict], outer_key: str, inner_key: str) -> float | None:
    for pair in pairs:
        nested = pair.get(outer_key) or {}
        if not isinstance(nested, dict):
            continue
        value = _float_or_none(nested.get(inner_key))
        if value is not None:
            return value
    return None


def _max_nested_float_from_pairs(pairs: list[dict], outer_key: str, inner_key: str) -> float | None:
    values = []
    for pair in pairs:
        nested = pair.get(outer_key) or {}
        if not isinstance(nested, dict):
            continue
        value = _float_or_none(nested.get(inner_key))
        if _positive(value):
            values.append(value)
    return max(values) if values else None


def _earliest_int_from_pairs(pairs: list[dict], key: str) -> int | None:
    values = [_int_or_none(pair.get(key)) for pair in pairs]
    values = [value for value in values if value is not None and value > 0]
    return min(values) if values else None


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
