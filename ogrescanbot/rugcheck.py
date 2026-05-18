from __future__ import annotations

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
        if isinstance(top_holders, list) and top_holders:
            top_pct = _float_or_none(top_holders[0].get("pct"))

        return RugSummary(
            score=_float_or_none(data.get("score")) if isinstance(data, dict) else None,
            risk_count=len(risks) if isinstance(risks, list) else None,
            top_holder_pct=top_pct,
            mint_authority=_string_or_none(data.get("mintAuthority")) if isinstance(data, dict) else None,
            freeze_authority=_string_or_none(data.get("freezeAuthority")) if isinstance(data, dict) else None,
            raw=data if isinstance(data, dict) else {},
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
