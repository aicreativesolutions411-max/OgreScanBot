from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import Any


@dataclass(frozen=True)
class TokenScan:
    address: str
    name: str
    symbol: str
    chain_id: str
    dex_id: str
    pair_address: str
    pair_url: str
    price_usd: float | None
    market_cap: float | None
    fdv: float | None
    liquidity_usd: float | None
    volume_h24: float | None
    price_change_h1: float | None
    price_change_h24: float | None
    buys_h1: int | None
    sells_h1: int | None
    created_at_ms: int | None
    image_url: str | None
    header_url: str | None
    description: str | None
    socials: list[dict[str, Any]]
    websites: list[dict[str, Any]]
    raw_pair: dict[str, Any]

    @property
    def cap_for_tracking(self) -> float | None:
        return self.market_cap or self.fdv

    def with_pump_metadata(self, pump: dict[str, Any]) -> "TokenScan":
        if not pump:
            return self

        websites = list(self.websites)
        socials = list(self.socials)
        website = _clean_string(pump.get("website"))
        telegram = _clean_string(pump.get("telegram"))
        twitter = _clean_string(pump.get("twitter"))

        if website and not _has_url(websites, website):
            websites.append({"label": "Web", "url": website})
        if telegram and not _has_url(socials, telegram):
            socials.append({"type": "telegram", "url": telegram})
        if twitter and not _has_url(socials, twitter):
            socials.append({"type": "twitter", "url": twitter})

        return replace(
            self,
            name=self.name if self.name != "Unknown" else _clean_string(pump.get("name")) or self.name,
            symbol=self.symbol if self.symbol != "?" else _clean_string(pump.get("symbol")) or self.symbol,
            image_url=self.image_url or _clean_string(pump.get("image_uri")),
            description=self.description or _clean_string(pump.get("description")),
            socials=socials,
            websites=websites,
        )


@dataclass(frozen=True)
class RugSummary:
    score: float | None
    risk_count: int | None
    top_holder_pct: float | None
    mint_authority: str | None
    freeze_authority: str | None
    raw: dict[str, Any]


def _clean_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _has_url(items: list[dict[str, Any]], url: str) -> bool:
    return any(str(item.get("url", "")).strip().lower() == url.lower() for item in items)
