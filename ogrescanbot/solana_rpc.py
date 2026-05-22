from __future__ import annotations

import base64
from dataclasses import dataclass
from dataclasses import replace
from decimal import Decimal, InvalidOperation

import aiohttp

from .models import RugSummary, TokenScan


SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
DEFAULT_SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"


@dataclass(frozen=True)
class OnChainSecurity:
    supply: float | None
    top_holder_pct: float | None
    top_10_holder_pct: float | None
    holder_count: int | None
    raw: dict


class SolanaRpcClient:
    def __init__(self, rpc_url: str = DEFAULT_SOLANA_RPC_URL, enable_holder_count: bool = False) -> None:
        timeout = aiohttp.ClientTimeout(total=15)
        self.rpc_url = (rpc_url or DEFAULT_SOLANA_RPC_URL).strip()
        self.enable_holder_count = enable_holder_count
        self._session = aiohttp.ClientSession(timeout=timeout)
        self._request_id = 0

    async def close(self) -> None:
        await self._session.close()

    async def enrich_token_supply(self, token: TokenScan) -> TokenScan:
        supply = await self.token_supply(token.address)
        if supply is None:
            return token
        return replace(token, supply=supply, supply_source="Solana RPC")

    async def security_summary(self, mint: str) -> OnChainSecurity | None:
        supply_raw, supply = await self._token_supply_raw(mint)
        if supply_raw is None or supply_raw <= 0:
            return None

        largest_raw = await self._largest_account_raw_amounts(mint)
        top_holder_pct = None
        top_10_holder_pct = None
        if largest_raw:
            top_holder_pct = _pct(largest_raw[0], supply_raw)
            top_10_holder_pct = _pct(sum(largest_raw[:10], Decimal(0)), supply_raw)

        holder_count = await self._exact_holder_count(mint) if self.enable_holder_count else None
        if top_holder_pct is None and top_10_holder_pct is None and holder_count is None and supply is None:
            return None
        return OnChainSecurity(
            supply=supply,
            top_holder_pct=top_holder_pct,
            top_10_holder_pct=top_10_holder_pct,
            holder_count=holder_count,
            raw={
                "source": "Solana RPC",
                "rpc_url": self.rpc_url,
                "exact_holder_count_enabled": self.enable_holder_count,
            },
        )

    async def token_supply(self, mint: str) -> float | None:
        _raw, ui_amount = await self._token_supply_raw(mint)
        return ui_amount

    async def _token_supply_raw(self, mint: str) -> tuple[Decimal | None, float | None]:
        result = await self._rpc("getTokenSupply", [mint])
        value = (result or {}).get("value") if isinstance(result, dict) else None
        raw, ui_amount = _token_amount(value)
        return raw, ui_amount

    async def _largest_account_raw_amounts(self, mint: str) -> list[Decimal]:
        result = await self._rpc("getTokenLargestAccounts", [mint])
        values = (result or {}).get("value") if isinstance(result, dict) else None
        if not isinstance(values, list):
            return []
        amounts: list[Decimal] = []
        for item in values:
            raw, _ui = _token_amount(item if isinstance(item, dict) else None)
            if raw is not None and raw > 0:
                amounts.append(raw)
        return amounts

    async def _exact_holder_count(self, mint: str) -> int | None:
        # Counts unique SPL token-account owners with a positive token amount.
        # Many public RPCs rate-limit or disable this heavy method, so this is optional.
        config = {
            "encoding": "base64",
            "dataSlice": {"offset": 32, "length": 40},
            "filters": [
                {"dataSize": 165},
                {"memcmp": {"offset": 0, "bytes": mint}},
            ],
        }
        result = await self._rpc("getProgramAccounts", [SPL_TOKEN_PROGRAM_ID, config])
        if not isinstance(result, list):
            return None
        owners: set[bytes] = set()
        for item in result:
            account = item.get("account") if isinstance(item, dict) else None
            data = account.get("data") if isinstance(account, dict) else None
            encoded = data[0] if isinstance(data, list) and data else None
            if not isinstance(encoded, str):
                continue
            try:
                decoded = base64.b64decode(encoded)
            except (ValueError, TypeError):
                continue
            if len(decoded) < 40:
                continue
            owner = decoded[:32]
            amount = int.from_bytes(decoded[32:40], "little")
            if amount > 0:
                owners.add(owner)
        return len(owners) if owners else None

    async def _rpc(self, method: str, params: list) -> dict | list | None:
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        try:
            async with self._session.post(self.rpc_url, json=payload) as response:
                if response.status >= 400:
                    return None
                data = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("error"):
            return None
        result = data.get("result")
        return result if isinstance(result, (dict, list)) else None


def merge_onchain_security(rug: RugSummary | None, onchain: OnChainSecurity | None) -> RugSummary | None:
    if not onchain:
        return rug
    if not rug:
        return RugSummary(
            score=None,
            risk_count=None,
            top_holder_pct=onchain.top_holder_pct,
            top_10_holder_pct=onchain.top_10_holder_pct,
            holder_count=onchain.holder_count,
            mint_authority=None,
            freeze_authority=None,
            dev_sold=None,
            dev_wallet=None,
            raw={"solana_rpc": onchain.raw},
            holder_count_source="Solana RPC" if onchain.holder_count is not None else None,
            concentration_source="Solana RPC"
            if onchain.top_holder_pct is not None or onchain.top_10_holder_pct is not None
            else None,
        )

    raw = dict(rug.raw or {})
    raw["solana_rpc"] = onchain.raw
    return RugSummary(
        score=rug.score,
        risk_count=rug.risk_count,
        top_holder_pct=onchain.top_holder_pct if onchain.top_holder_pct is not None else rug.top_holder_pct,
        top_10_holder_pct=onchain.top_10_holder_pct if onchain.top_10_holder_pct is not None else rug.top_10_holder_pct,
        holder_count=onchain.holder_count if onchain.holder_count is not None else rug.holder_count,
        mint_authority=rug.mint_authority,
        freeze_authority=rug.freeze_authority,
        dev_sold=rug.dev_sold,
        dev_wallet=rug.dev_wallet,
        raw=raw,
        holder_count_source="Solana RPC" if onchain.holder_count is not None else rug.holder_count_source,
        concentration_source="Solana RPC"
        if onchain.top_holder_pct is not None or onchain.top_10_holder_pct is not None
        else rug.concentration_source,
    )


def _token_amount(value: dict | None) -> tuple[Decimal | None, float | None]:
    if not isinstance(value, dict):
        return None, None
    raw = _decimal_or_none(value.get("amount"))
    decimals = _int_or_none(value.get("decimals")) or 0
    ui_amount = _float_or_none(value.get("uiAmountString"))
    if ui_amount is None:
        ui_amount = _float_or_none(value.get("uiAmount"))
    if raw is not None and ui_amount is None:
        try:
            ui_amount = float(raw / (Decimal(10) ** decimals))
        except (InvalidOperation, OverflowError, ZeroDivisionError):
            ui_amount = None
    return raw, ui_amount


def _pct(part: Decimal, total: Decimal) -> float | None:
    try:
        if total <= 0:
            return None
        return float((part / total) * Decimal(100))
    except (InvalidOperation, OverflowError, ZeroDivisionError):
        return None


def _decimal_or_none(value: object) -> Decimal | None:
    try:
        if value is None:
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


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
