from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class RugSummary:
    score: float | None
    risk_count: int | None
    top_holder_pct: float | None
    mint_authority: str | None
    freeze_authority: str | None
    raw: dict[str, Any]
