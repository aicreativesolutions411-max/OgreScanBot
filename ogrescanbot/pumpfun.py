from __future__ import annotations

import aiohttp

from .models import TokenScan, normalize_media_url


class PumpFunClient:
    def __init__(self) -> None:
        timeout = aiohttp.ClientTimeout(total=10)
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        await self._session.close()

    async def metadata(self, mint: str) -> dict:
        url = f"https://frontend-api-v3.pump.fun/coins/{mint}"
        try:
            async with self._session.get(url) as response:
                if response.status >= 400:
                    return {}
                data = await response.json(content_type=None)
        except aiohttp.ClientError:
            return {}
        return data if isinstance(data, dict) else {}

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
            pair_url=f"https://pump.fun/{mint}",
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
