from __future__ import annotations

import json

import aiohttp

from .models import RugSummary


class RugCheckClient:
    def __init__(self) -> None:
        timeout = aiohttp.ClientTimeout(total=10)
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        await self._session.close()

    async def summary(self, mint: str) -> RugSummary | None:
        url = f"https://api.rugcheck.xyz/v1/tokens/{mint}/report"
        try:
            async with self._session.get(url) as response:
                if response.status >= 400:
                    return None
                data = await response.json(content_type=None)
        except aiohttp.ClientError:
            return None

        risks = data.get("risks") if isinstance(data, dict) else None
        top_holders = data.get("topHolders") if isinstance(data, dict) else None
        top_pct = None
        top_10_pct = None
        if isinstance(top_holders, list) and top_holders:
            filtered = _filtered_holders(data, top_holders)
            if filtered:
                top_pct = _holder_pct(filtered[0])
                top_10_values = [_holder_pct(holder) for holder in filtered[:10]]
                top_10_pct = sum(value for value in top_10_values if value is not None)

        return RugSummary(
            score=_float_or_none(data.get("score")) if isinstance(data, dict) else None,
            risk_count=len(risks) if isinstance(risks, list) else None,
            top_holder_pct=top_pct,
            top_10_holder_pct=top_10_pct,
            holder_count=_holder_count(data) if isinstance(data, dict) else None,
            mint_authority=_string_or_none(data.get("mintAuthority")) if isinstance(data, dict) else None,
            freeze_authority=_string_or_none(data.get("freezeAuthority")) if isinstance(data, dict) else None,
            dev_sold=_detect_dev_sold(data) if isinstance(data, dict) else None,
            dev_wallet=_dev_wallet(data) if isinstance(data, dict) else None,
            raw=data if isinstance(data, dict) else {},
            holder_count_source="RugCheck" if _holder_count(data) is not None else None,
            concentration_source="RugCheck" if top_pct is not None or top_10_pct is not None else None,
        )


def _float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _holder_pct(holder: dict) -> float | None:
    for key in ("pct", "percentage", "uiPct"):
        value = _float_or_none(holder.get(key))
        if value is not None:
            return value
    return None


def _filtered_holders(data: dict, holders: list) -> list[dict]:
    market_addresses = _market_addresses(data)
    clean: list[dict] = []
    for holder in holders:
        if not isinstance(holder, dict):
            continue
        owner = _holder_owner(holder)
        if owner and owner in market_addresses:
            continue
        label = json.dumps(holder, default=str).lower()
        if any(word in label for word in ("liquidity", "raydium", "meteora", "orca", "pump amm", "pool")):
            continue
        clean.append(holder)
    return clean or [holder for holder in holders if isinstance(holder, dict)]


def _holder_owner(holder: dict) -> str | None:
    for key in ("owner", "address", "wallet", "tokenAccount", "token_account"):
        value = _string_or_none(holder.get(key))
        if value:
            return value
    return None


def _market_addresses(data: dict) -> set[str]:
    addresses: set[str] = set()
    for key in ("markets", "pairs", "pools"):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for address_key in ("address", "pubkey", "lpMint", "lp", "pairAddress", "market"):
                value = _string_or_none(item.get(address_key))
                if value:
                    addresses.add(value)
    return addresses


def _holder_count(data: dict) -> int | None:
    # Avoid the generic "holders" key: some free endpoints use it for token
    # accounts or sampled holder rows, which can disagree with chart UIs.
    for key in ("holderCount", "totalHolders", "total_holders", "numHolders"):
        value = data.get(key)
        if isinstance(value, int):
            return value
        parsed = _float_or_none(value)
        if parsed is not None:
            return int(parsed)
    token = data.get("token") if isinstance(data.get("token"), dict) else {}
    for key in ("holderCount", "totalHolders"):
        value = token.get(key)
        if isinstance(value, int):
            return value
        parsed = _float_or_none(value)
        if parsed is not None:
            return int(parsed)
    return None


def _dev_wallet(data: dict) -> str | None:
    for key in ("creator", "creatorAddress", "deployer", "deployerAddress", "owner"):
        value = _string_or_none(data.get(key))
        if value:
            return value
    token = data.get("token") if isinstance(data.get("token"), dict) else {}
    for key in ("creator", "creatorAddress", "deployer", "deployerAddress", "owner"):
        value = _string_or_none(token.get(key))
        if value:
            return value
    return None


def _detect_dev_sold(data: dict) -> bool | None:
    risks = data.get("risks")
    text = json.dumps(risks if isinstance(risks, list) else data, default=str).lower()
    negative = (
        "dev has not sold",
        "developer has not sold",
        "creator has not sold",
        "dev not sold",
        "creator not sold",
    )
    if any(phrase in text for phrase in negative):
        return False

    positive = (
        "dev sold",
        "developer sold",
        "creator sold",
        "deployer sold",
        "creator has sold",
    )
    if any(phrase in text for phrase in positive):
        return True

    if isinstance(risks, list):
        return False
    return None
