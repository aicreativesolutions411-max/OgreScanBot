from __future__ import annotations

import html
import time
from urllib.parse import quote_plus

from .db import CallRecord, TraderRecord
from .models import RugSummary, TokenScan


OGRE_TELEGRAM_URL = "https://t.me/ogrecoinonsol"
OGRE_WEBSITE_URL = "https://ogremode.com/"
OGRE_TWITTER_URL = "https://twitter.com/i/communities/1930265213917425858"


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
            f"├ {html.escape(status)} by <b>{html.escape(call.caller_name)}</b>\n"
            f"├ Called at <b>{money(call.initial_cap)}</b>\n"
            f"└ Best <b>{call.peak_multiple:.2f}x</b>"
        )

    socials = social_links(token)
    rug_text = format_rug(rug)
    meta_text = format_metadata(token)
    tools = tool_links(token)
    x_posts = x_search_links(token)

    return (
        f"<b>OgreScanBot</b>\n"
        f"💊 <b>{title}</b>\n"
        f"<code>{ca}</code>\n"
        f"└ #SOL | {html.escape(token.dex_id)} | {age_from_ms(token.created_at_ms)}\n\n"
        f"{meta_text}"
        f"📊 <b>Stats</b>\n"
        f"├ USD     <b>{price(token.price_usd)}</b> ({pct(token.price_change_h24)} 24h)\n"
        f"├ MC      <b>{money(token.market_cap)}</b>\n"
        f"├ FDV     <b>{money(token.fdv)}</b>\n"
        f"├ Vol     <b>{money(token.volume_h24)}</b>\n"
        f"├ LP      <b>{money(token.liquidity_usd)}</b>\n"
        f"├ 1H      <b>{pct(token.price_change_h1)}</b> 🟢 {token.buys_h1 or 0} 🔴 {token.sells_h1 or 0}\n"
        f"└ ATH     <b>{ath_value(call)}</b>\n\n"
        f"🔗 <b>Socials</b>\n"
        f"└ {socials}\n\n"
        f"🔎 <b>X Posts</b>\n"
        f"└ {x_posts}\n\n"
        f"🔒 <b>Security</b>\n"
        f"{rug_text}\n\n"
        f"{tools}"
        f"{call_line}"
        f"{powered_by_footer()}"
    )


def format_leaderboard(
    period: str,
    traders: list[TraderRecord],
    calls: list[CallRecord],
    stats: dict[str, float | int],
) -> str:
    trader_rows = []
    medals = ["1", "2", "3"]
    for index, trader in enumerate(traders, start=1):
        prefix = medals[index - 1] if index <= 3 else str(index)
        trader_rows.append(
            f"{prefix}. <b>{html.escape(trader.caller_name)}</b> "
            f"[{trader.best_multiple:.2f}x] "
            f"{trader.hits}/{trader.total_calls} hits"
        )
    trader_body = "\n".join(trader_rows) if trader_rows else "No traders tracked for this period yet."

    call_rows = []
    for index, call in enumerate(calls, start=1):
        prefix = medals[index - 1] if index <= 3 else str(index)
        call_rows.append(
            f"{prefix}. <b>{html.escape(call.token_symbol)}</b> by "
            f"{html.escape(call.caller_name)} [{call.peak_multiple:.2f}x]"
        )
    call_body = "\n".join(call_rows) if call_rows else "No calls tracked for this period yet."
    return (
        f"<b>Leaderboard</b>\n\n"
        f"<b>Top Traders</b>\n"
        f"{trader_body}\n\n"
        f"<b>Best Trades</b>\n"
        f"{call_body}\n\n"
        f"<b>Group Stats</b>\n"
        f"|- Period   <b>{html.escape(period)}</b>\n"
        f"|- Calls    <b>{int(stats['calls'])}</b>\n"
        f"|- Hit Rate <b>{int(stats['hit_rate'])}%</b>\n"
        f"|- Median   <b>{float(stats['median']):.2f}x</b>\n"
        f"|- Return   <b>{float(stats['return']):.2f}x</b>"
        f"{powered_by_footer()}"
    )


def format_help(bot_name: str) -> str:
    return (
        f"<b>{html.escape(bot_name)}</b>\n\n"
        "Paste a Solana CA or supported token link and I will scan it. "
        "The first paste in each chat becomes that chat's call.\n\n"
        "<b>Commands</b>\n"
        "|- /scan &lt;ca, link, or $ticker&gt;\n"
        "|- /pnl &lt;ca or $ticker&gt;\n"
        "|- /flex &lt;ca or $ticker&gt;\n"
        "|- /leaderboard 1w\n"
        "|- /lb 1d | /lb 1w | /lb 30d | /lb all"
        f"{powered_by_footer()}"
    )


def powered_by_footer() -> str:
    return (
        "\n\n<b>Powered by Ogres</b>\n"
        f"<a href=\"{OGRE_TELEGRAM_URL}\">Telegram</a> • "
        f"<a href=\"{OGRE_WEBSITE_URL}\">Website</a> • "
        f"<a href=\"{OGRE_TWITTER_URL}\">Twitter</a>"
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


def ath_value(call: CallRecord | None) -> str:
    if not call:
        return "n/a"
    return f"{money(call.peak_cap)} ({call.peak_multiple:.2f}x)"


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
        if len(description) > 120:
            description = f"{description[:117]}..."
        lines.append(f"└ {html.escape(description)}")
    if not lines:
        return ""
    return "🧾 <b>Info</b>\n" + "\n".join(lines) + "\n\n"


def x_search_links(token: TokenScan) -> str:
    official = official_x_link(token)
    terms = [token.address]
    if token.symbol and token.symbol != "?":
        terms.append(f"${token.symbol}")
    base_query = " OR ".join(terms)
    recent_query = quote_plus(base_query)
    big_query = quote_plus(f"{base_query} min_faves:25")
    recent = f"https://x.com/search?q={recent_query}&src=typed_query&f=live"
    top = f"https://x.com/search?q={big_query}&src=typed_query&f=top"
    links = [
        f"<a href=\"{html.escape(recent)}\">recent mentions</a>",
        f"<a href=\"{html.escape(top)}\">big mentions</a>",
    ]
    if official:
        links.insert(0, f"<a href=\"{html.escape(official)}\">official X</a>")
    return " • ".join(links)


def official_x_link(token: TokenScan) -> str | None:
    for social in token.socials:
        url = str(social.get("url") or "")
        label = str(social.get("type") or "").lower()
        if "twitter.com" in url or "x.com" in url or label in {"twitter", "x"}:
            return url
    return None


def tool_links(token: TokenScan) -> str:
    address = html.escape(token.address)
    links = [
        f"<a href=\"{html.escape(token.pair_url)}\">DEX</a>",
        f"<a href=\"https://app.bubblemaps.io/sol/token/{address}\">BUB</a>",
        f"<a href=\"https://rugcheck.xyz/tokens/{address}\">RUG</a>",
        f"<a href=\"https://pump.fun/{address}\">PUMP</a>",
        f"<a href=\"https://gmgn.ai/sol/token/{address}\">GMGN</a>",
    ]
    return " • ".join(links)


def format_rug(rug: RugSummary | None) -> str:
    if not rug:
        return "└ RugCheck unavailable/free endpoint did not return data"
    mint = "none" if not rug.mint_authority else "active"
    freeze = "none" if not rug.freeze_authority else "active"
    risk_count = rug.risk_count if rug.risk_count is not None else "n/a"
    top = f"{rug.top_holder_pct:.1f}%" if rug.top_holder_pct is not None else "n/a"
    score = f"{rug.score:.0f}" if rug.score is not None else "n/a"
    return (
        f"├ Score   <b>{score}</b>\n"
        f"├ Risks   <b>{risk_count}</b>\n"
        f"├ Top     <b>{top}</b>\n"
        f"├ Mint    <b>{mint}</b>\n"
        f"└ Freeze  <b>{freeze}</b>"
    )
