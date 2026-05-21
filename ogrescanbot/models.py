from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import Any
from urllib.parse import urlparse


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
    bonding_progress_pct: float | None = None
    is_pump_complete: bool | None = None
    dex_paid: bool | None = None

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

        pump_cap = _float_or_none(pump.get("usd_market_cap")) or _float_or_none(pump.get("market_cap"))
        return replace(
            self,
            name=self.name if self.name != "Unknown" else _clean_string(pump.get("name")) or self.name,
            symbol=self.symbol if self.symbol != "?" else _clean_string(pump.get("symbol")) or self.symbol,
            market_cap=self.market_cap or pump_cap,
            fdv=self.fdv or pump_cap,
            image_url=self.image_url or normalize_media_url(_clean_string(pump.get("image_uri"))),
            description=self.description or _clean_string(pump.get("description")),
            socials=socials,
            websites=websites,
            bonding_progress_pct=self.bonding_progress_pct
            if self.bonding_progress_pct is not None
            else pump_bonding_progress_pct(pump, self.cap_for_tracking),
            is_pump_complete=self.is_pump_complete
            if self.is_pump_complete is not None
            else pump_is_complete(pump),
        )


@dataclass(frozen=True)
class RugSummary:
    score: float | None
    risk_count: int | None
    top_holder_pct: float | None
    mint_authority: str | None
    freeze_authority: str | None
    dev_sold: bool | None
    raw: dict[str, Any]


PUMP_BONDING_COMPLETE_USD = 69_000.0


def _clean_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _has_url(items: list[dict[str, Any]], url: str) -> bool:
    return any(str(item.get("url", "")).strip().lower() == url.lower() for item in items)


def pump_is_complete(pump: dict[str, Any]) -> bool | None:
    for key in ("complete", "graduated", "migrated"):
        value = pump.get(key)
        if isinstance(value, bool):
            return value
    if pump.get("raydium_pool") or pump.get("raydiumPool") or pump.get("pool"):
        return True
    return False if pump else None


def pump_bonding_progress_pct(pump: dict[str, Any], fallback_cap: float | None = None) -> float | None:
    if not pump:
        return None
    if pump_is_complete(pump):
        return 100.0

    for key in ("bonding_curve_progress", "bondingCurveProgress", "progress"):
        value = _float_or_none(pump.get(key))
        if value is not None:
            return _clamp_pct(value * 100 if value <= 1 else value)

    cap = (
        _float_or_none(pump.get("usd_market_cap"))
        or _float_or_none(pump.get("market_cap"))
        or fallback_cap
    )
    if cap is None or cap <= 0:
        return None
    return _clamp_pct((cap / PUMP_BONDING_COMPLETE_USD) * 100, max_value=99.9)


def normalize_media_url(url: str | None) -> str | None:
    if not url:
        return None
    text = url.strip()
    if text.startswith("ipfs://"):
        return f"https://ipfs.io/ipfs/{text.removeprefix('ipfs://')}"
    if text.startswith("ar://"):
        return f"https://arweave.net/{text.removeprefix('ar://')}"
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"}:
        return text
    if text.startswith("Qm") or text.startswith("bafy"):
        return f"https://ipfs.io/ipfs/{text}"
    return text


def _float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp_pct(value: float, max_value: float = 100.0) -> float:
    return max(0.0, min(max_value, value))
