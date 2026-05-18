from __future__ import annotations

import html
import time

from .db import CallRecord
from .models import RugSummary, TokenScan


def user_display_name(user) -> str:
    name = " ".join(part for part in [user.first_name, user.last_name] if part).strip()
    return user.username or name or str(user.id)


def format_scan(token: TokenScan, call: CallRecord | None, is_new_call: bool, rug: RugSummary | None) -> str:
    ca = html.escape(token.address)
    title = html.escape(f"{token.name} (${token.symbol})")
    call_line = ""
    if call:
        status = "New call" if is_new_call else "Already called"
        call_line = (
            f"\n\n<b>Caller</b>\n"
            f"|- {html.escape(status)} by <b>{html.escape(call.caller_name)}</b>\n"
            f"|- Called at <b>{money(call.initial_cap)}</b>\n"
            f"|- Best <b>{call.peak_multiple:.2f}x</b>"
        )

    socials = social_links(token)
    rug_text = format_rug(rug)
    meta_text = format_metadata(token)

    return (
        f"<b>OgreScanBot</b>\n\n"
        f"<b>{title}</b>\n"
        f"<code>{ca}</code>\n"
        f"|- #SOL | {html.escape(token.dex_id)} | {age_from_ms(token.created_at_ms)}\n\n"
        f"{meta_text}"
        f"<b>Stats</b>\n"
        f"|- USD     <b>{price(token.price_usd)}</b> ({pct(token.price_change_h24)} 24h)\n"
        f"|- MC      <b>{money(token.market_cap)}</b>\n"
        f"|- FDV     <b>{money(token.fdv)}</b>\n"
        f"|- Vol     <b>{money(token.volume_h24)}</b>\n"
        f"|- LP      <b>{money(token.liquidity_usd)}</b>\n"
        f"|- 1H      <b>{pct(token.price_change_h1)}</b> B {token.buys_h1 or 0} / S {token.sells_h1 or 0}\n\n"
        f"<b>Socials</b>\n"
        f"|- {socials}\n\n"
        f"<b>Security</b>\n"
        f"{rug_text}\n\n"
        f"<a href=\"{html.escape(token.pair_url)}\">Dexscreener</a>"
        f"{call_line}"
    )


def format_leaderboard(period: str, calls: list[CallRecord], stats: dict[str, float | int]) -> str:
    rows = []
    medals = ["1", "2", "3"]
    for index, call in enumerate(calls, start=1):
        prefix = medals[index - 1] if index <= 3 else str(index)
        rows.append(
            f"{prefix}. <b>{html.escape(call.token_symbol)}</b> by "
            f"{html.escape(call.caller_name)} [{call.peak_multiple:.2f}x]"
        )
    body = "\n".join(rows) if rows else "No calls tracked for this period yet."
    return (
        f"<b>Leaderboard</b>\n\n"
        f"<b>Top Calls</b>\n"
        f"{body}\n\n"
        f"<b>Group Stats</b>\n"
        f"|- Period   <b>{html.escape(period)}</b>\n"
        f"|- Calls    <b>{int(stats['calls'])}</b>\n"
        f"|- Hit Rate <b>{int(stats['hit_rate'])}%</b>\n"
        f"|- Median   <b>{float(stats['median']):.2f}x</b>\n"
        f"|- Return   <b>{float(stats['return']):.2f}x</b>"
    )


def format_help(bot_name: str) -> str:
    return (
        f"<b>{html.escape(bot_name)}</b>\n\n"
        "Paste a Solana CA or supported token link and I will scan it. "
        "The first paste in each chat becomes that chat's call.\n\n"
        "<b>Commands</b>\n"
        "|- /scan &lt;ca or link&gt;\n"
        "|- /pnl &lt;ca&gt;\n"
        "|- /flex &lt;ca&gt;\n"
        "|- /lb 1d | /lb 1w | /lb 30d | /lb all"
    )


def money(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:.2f}"


def price(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value < 0.00001:
        return f"${value:.10f}".rstrip("0")
    if value < 0.01:
        return f"${value:.8f}".rstrip("0")
    return f"${value:.4f}"


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1f}%"


def age_from_ms(created_at_ms: int | None) -> str:
    if not created_at_ms:
        return "age n/a"
    seconds = max(0, int(time.time() - (created_at_ms / 1000)))
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def social_links(token: TokenScan) -> str:
    links: list[str] = []
    for site in token.websites[:2]:
        url = site.get("url")
        label = site.get("label") or "Web"
        if url:
            links.append(f"<a href=\"{html.escape(str(url))}\">{html.escape(str(label))}</a>")
    for social in token.socials[:4]:
        url = social.get("url")
        label = social.get("type") or "Social"
        if url:
            links.append(f"<a href=\"{html.escape(str(url))}\">{html.escape(str(label))}</a>")
    return " | ".join(links) if links else "none found"


def format_metadata(token: TokenScan) -> str:
    lines: list[str] = []
    if token.description:
        description = " ".join(token.description.split())
        if len(description) > 220:
            description = f"{description[:217]}..."
        lines.append(f"|- Info    {html.escape(description)}")
    if token.image_url:
        lines.append(f"|- Image   <a href=\"{html.escape(token.image_url)}\">token pic</a>")
    if token.header_url:
        lines.append(f"|- Header  <a href=\"{html.escape(token.header_url)}\">banner</a>")
    if not lines:
        return ""
    return "<b>Metadata</b>\n" + "\n".join(lines) + "\n\n"


def format_rug(rug: RugSummary | None) -> str:
    if not rug:
        return "|- RugCheck unavailable/free endpoint did not return data"
    mint = "none" if not rug.mint_authority else "active"
    freeze = "none" if not rug.freeze_authority else "active"
    risk_count = rug.risk_count if rug.risk_count is not None else "n/a"
    top = f"{rug.top_holder_pct:.1f}%" if rug.top_holder_pct is not None else "n/a"
    score = f"{rug.score:.0f}" if rug.score is not None else "n/a"
    return (
        f"|- Score   <b>{score}</b>\n"
        f"|- Risks   <b>{risk_count}</b>\n"
        f"|- Top     <b>{top}</b>\n"
        f"|- Mint    <b>{mint}</b>\n"
        f"|- Freeze  <b>{freeze}</b>"
    )
