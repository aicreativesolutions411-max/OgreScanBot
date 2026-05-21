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


def telegram_credit(user) -> str:
    if not user:
        return "unknown"
    if user.username:
        return f"@{html.escape(user.username)}"
    name = " ".join(part for part in [user.first_name, user.last_name] if part).strip()
    return html.escape(name or str(user.id))


def format_x_post_embed(username: str, embed_url: str, user) -> str:
    return (
        f"<b>X Post</b> by @{html.escape(username)}\n"
        f"{html.escape(embed_url)}\n\n"
        f"Shared by {telegram_credit(user)}"
        f"{powered_by_footer()}"
    )


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
            f"└ ATH from call <b>{call.peak_multiple:.2f}x</b> ({multiple_pct(call.peak_multiple)}) | "
            f"Current <b>{current_multiple(call):.2f}x</b> ({multiple_pct(current_multiple(call))})"
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
        f"├ MC      <b>{money(token.market_cap or token.fdv)}</b>\n"
        f"├ FDV     <b>{money(token.fdv)}</b>\n"
        f"├ Vol     <b>{money(token.volume_h24)}</b>\n"
        f"├ LP      <b>{money(token.liquidity_usd)}</b>\n"
        f"├ 1H      <b>{pct(token.price_change_h1)}</b> 🟢 {token.buys_h1 or 0} 🔴 {token.sells_h1 or 0}\n"
        f"└ ATH     <b>{ath_value(call, token)}</b>\n\n"
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


def format_scan_caption(
    token: TokenScan,
    call: CallRecord | None,
    is_new_call: bool,
    rug: RugSummary | None = None,
) -> str:
    status = "New call" if is_new_call else "Already called"
    caller = html.escape(call.caller_name) if call else "unknown"
    called_at = money(call.initial_cap) if call else "n/a"
    now = money(call.last_cap) if call else money(token.cap_for_tracking)
    best = f"{call.peak_multiple:.2f}x" if call else "n/a"
    current_value = current_multiple(call)
    current = f"{current_value:.2f}x" if current_value is not None else "n/a"
    ath = ath_value(call, token)
    stats = [
        "📊 <b>Token Stats</b>",
        f"├ MC:   <b>{money(token.market_cap or token.fdv)}</b>",
        f"├ ATH:  <b>{ath}</b>",
        f"├ USD:  <b>{price(token.price_usd)}</b> ({pct(token.price_change_h24)})",
        f"├ LIQ:  <b>{money(token.liquidity_usd)}</b>",
        f"├ VOL:  <b>{money(token.volume_h24)}</b> (24h)",
        f"├ 1H:   <b>B {token.buys_h1 or 0} / S {token.sells_h1 or 0}</b> ({pct(token.price_change_h1)})",
    ]
    stats.extend(
        [
            f"├ P:    {pair_short_link(token)}",
            f"└ CA:   <code>{short_address(token.address)}</code>",
        ]
    )

    return (
        f"<b>OgreScanBot</b>\n"
        f"🧬 <b>{html.escape(token.name)} (${html.escape(token.symbol)})</b>\n"
        f"<code>{html.escape(token.address)}</code>\n"
        f"└ 🌱 #SOL • {html.escape(token.dex_id)} • {age_from_ms(token.created_at_ms)}\n\n"
        f"{chr(10).join(stats)}\n\n"
        f"🔗 <b>Socials</b>\n"
        f"└ {scan_social_links(token)}\n\n"
        f"🛡 <b>Audit</b> <b>{audit_badge(rug)}</b>\n"
        f"{audit_status(token, rug)}\n\n"
        f"🧌 <b>Call</b>\n"
        f"├ {html.escape(status)} by <b>{caller}</b>\n"
        f"├ Called <b>{called_at}</b> | Now <b>{now}</b>\n"
        f"└ ATH from call <b>{best}</b> ({multiple_pct(call.peak_multiple if call else None)}) | "
        f"Current <b>{current}</b> ({multiple_pct(current_value)})\n\n"
        f"{scan_tool_links(token)}\n"
        f"{scan_x_links(token)}"
        f"{powered_by_footer()}"
    )


def format_leaderboard(
    period: str,
    traders: list[TraderRecord],
    calls: list[CallRecord],
    stats: dict[str, float | int],
) -> str:
    trader_rows = []
    medals = ["🥇", "🥈", "🥉"]
    tree = ["├", "├", "└"]
    for index, trader in enumerate(traders[:3], start=1):
        branch = tree[index - 1]
        medal = medals[index - 1]
        trader_rows.append(
            f"{branch}{medal} <b>{html.escape(trader.caller_name)}</b> "
            f"[{trader.best_multiple:.1f} pts]"
        )
    trader_body = "\n".join(trader_rows) if trader_rows else "└ No callers tracked yet"

    call_rows = []
    for index, call in enumerate(calls, start=1):
        prefix = "🎉" if index <= 3 else "😎"
        marker = "💊" if index in {2, 7, 8, 9} else "🟪"
        call_rows.append(
            f"{prefix}{marker} {index} <b>{html.escape(call.token_symbol)}</b> » "
            f"<i>{html.escape(call.caller_name)}</i> [<b>{call.peak_multiple:.1f}x</b>]"
        )
    call_body = "\n".join(call_rows) if call_rows else "No calls tracked for this period yet."
    avg = float(stats.get("avg", 0))
    return (
        f"🏆 <b>Leaderboard</b>\n\n"
        f"👑 <b>Top Callers</b>\n"
        f"{trader_body}\n\n"
        f"📊 <b>Group Stats</b>\n"
        f"├Period   <b>{html.escape(period)}</b>\n"
        f"├Calls    <b>{int(stats['calls'])}</b>\n"
        f"├Hit Rate <b>{int(stats['hit_rate'])}%</b>\n"
        f"├Median   <b>{leaderboard_median_pct(stats)}</b>\n"
        f"└Return   <b>{float(stats['return']):.1f}x</b> (<i>Avg: {avg:.1f}x</i>)\n\n"
        f"<blockquote>{call_body}</blockquote>\n\n"
        f"📚 <a href=\"{OGRE_WEBSITE_URL}\">Learn More!</a>"
        f"{powered_by_footer()}"
    )


def format_leaderboard_backup_snapshot(
    generated_at: int,
    sections: list[tuple[int, list[TraderRecord], list[CallRecord], dict[str, float | int]]],
) -> str:
    if not sections:
        return "OgreScanBot leaderboard backup\nNo calls tracked yet."

    lines = [
        "OgreScanBot leaderboard backup",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(generated_at))}",
        "",
    ]
    for chat_id, traders, calls, stats in sections[:10]:
        lines.append(f"Chat {chat_id}")
        lines.append(
            f"Stats: {int(stats['calls'])} calls | {int(stats['hit_rate'])}% hit | "
            f"best {float(stats['return']):.2f}x"
        )
        if traders:
            lines.append("Top callers:")
            for index, trader in enumerate(traders[:3], start=1):
                lines.append(
                    f"{index}. {trader.caller_name} [{trader.best_multiple:.2f}x] "
                    f"{trader.hits}/{trader.total_calls} hits"
                )
        if calls:
            lines.append("Best trades:")
            for index, call in enumerate(calls[:5], start=1):
                lines.append(f"{index}. ${call.token_symbol} by {call.caller_name} [{call.peak_multiple:.2f}x]")
        lines.append("")
    return "\n".join(lines)[:3800]


def format_help(bot_name: str) -> str:
    return (
        f"<b>{html.escape(bot_name)}</b>\n\n"
        "Paste a Solana CA or supported token link and I will scan it. "
        "The first paste in each chat becomes that chat's call.\n\n"
        "<b>Commands</b>\n"
        "|- /scan &lt;ca, link, or $ticker&gt;\n"
        "|- /pnl &lt;ca or $ticker&gt;\n"
        "|- /flex &lt;ca or $ticker&gt;\n"
        "|- /leaderboard\n"
        "|- /lb 1d | /lb 1w | /lb 2w | /lb 1m\n"
        "|- /backup"
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


def ath_value(call: CallRecord | None, token: TokenScan | None = None) -> str:
    if not call:
        if token and token.cap_for_tracking:
            return f"{money(token.cap_for_tracking)} (current)"
        return "n/a"
    return f"{money(call.peak_cap)} ({call.peak_multiple:.2f}x from call)"


def current_multiple(call: CallRecord | None) -> float | None:
    if not call or call.initial_cap <= 0:
        return None
    return max(0.0, call.last_cap / call.initial_cap)


def multiple_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{(value - 1.0) * 100:+.0f}%"


def leaderboard_median_pct(stats: dict[str, float | int]) -> str:
    if int(stats.get("calls", 0)) <= 0:
        return "0%"
    return multiple_pct(float(stats.get("median", 0)))


def security_status(token: TokenScan, rug: RugSummary | None) -> str:
    return (
        f"├ Dev Sold <b>{dev_sold_light(rug.dev_sold if rug else None)}</b>\n"
        f"├ DEX Paid <b>{dex_paid_light(token.dex_paid)}</b>\n"
        f"├ Rug Score <b>{rug_score(rug)}</b> | Top <b>{rug_top_holder(rug)}</b>\n"
        f"└ Mint <b>{authority_light(rug.mint_authority if rug else None, rug is not None)}</b> | "
        f"Freeze <b>{authority_light(rug.freeze_authority if rug else None, rug is not None)}</b>"
    )


def audit_status(token: TokenScan, rug: RugSummary | None) -> str:
    return (
        f"├ 🧾 DEX <b>{dex_paid_bracket(token.dex_paid)}</b>\n"
        f"├ 👥 Top Holders <b>[{rug_top_holder(rug)}]</b>\n"
        f"├ 🧑‍💻 Dev Sold <b>{dev_sold_bracket(rug.dev_sold if rug else None)}</b>\n"
        f"└ 🔐 Mint <b>{authority_bracket(rug.mint_authority if rug else None, rug is not None)}</b> • "
        f"Freeze <b>{authority_bracket(rug.freeze_authority if rug else None, rug is not None)}</b>"
    )


def audit_badge(rug: RugSummary | None) -> str:
    if not rug:
        return "[n/a]"
    risks = rug.risk_count if rug.risk_count is not None else 3
    value = max(1, min(10, 10 - int(risks)))
    return f"[{value}/10]"


def dex_paid_bracket(value: bool | None) -> str:
    if value is True:
        return "[PAID]"
    if value is False:
        return "[UNPAID]"
    return "[n/a]"


def dev_sold_bracket(value: bool | None) -> str:
    if value is True:
        return "[YES]"
    if value is False:
        return "[NO]"
    return "[n/a]"


def authority_bracket(value: str | None, available: bool) -> str:
    if not available:
        return "[n/a]"
    if value:
        return "[ON]"
    return "[OFF]"


def dev_sold_light(value: bool | None) -> str:
    if value is True:
        return "🔴 Yes"
    if value is False:
        return "🟢 No"
    return "⚪ n/a"


def dex_paid_light(value: bool | None) -> str:
    if value is True:
        return "🟢 Paid"
    if value is False:
        return "🔴 Unpaid"
    return "⚪ n/a"


def authority_light(value: str | None, available: bool) -> str:
    if not available:
        return "⚪ n/a"
    if value:
        return "🔴 active"
    return "🟢 none"


def rug_score(rug: RugSummary | None) -> str:
    if not rug or rug.score is None:
        return "n/a"
    risk_count = rug.risk_count if rug.risk_count is not None else "?"
    return f"{rug.score:.0f} ({risk_count} risks)"


def rug_top_holder(rug: RugSummary | None) -> str:
    if not rug or rug.top_holder_pct is None:
        return "n/a"
    return f"{rug.top_holder_pct:.1f}%"


def age_from_ms(created_at_ms: int | None) -> str:
    if not created_at_ms:
        return "age n/a"
    seconds = max(0, int(time.time() - (created_at_ms / 1000)))
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def short_address(address: str, left: int = 4, right: int = 4) -> str:
    clean = str(address or "").strip()
    if len(clean) <= left + right + 3:
        return html.escape(clean)
    return html.escape(f"{clean[:left]}...{clean[-right:]}")


def pair_short_link(token: TokenScan) -> str:
    label = short_address(token.pair_address or token.address)
    url = html.escape(token.pair_url or f"https://dexscreener.com/solana/{token.address}")
    return f"<a href=\"{url}\">{label}</a>"


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


def scan_social_links(token: TokenScan) -> str:
    links: list[str] = []
    telegram = social_url(token, {"telegram", "tg"})
    website = first_website_url(token)
    x_url = social_url(token, {"twitter", "x"})
    if telegram:
        links.append(f"<a href=\"{html.escape(telegram)}\">TG</a>")
    if website:
        links.append(f"<a href=\"{html.escape(website)}\">Web</a>")
    if x_url:
        links.append(f"<a href=\"{html.escape(x_url)}\">X</a>")
    if token.description:
        links.append("About")
    return " • ".join(links) if links else "none found"


def social_url(token: TokenScan, labels: set[str]) -> str | None:
    for social in token.socials:
        url = str(social.get("url") or "").strip()
        label = str(social.get("type") or "").strip().lower()
        if not url:
            continue
        if label in labels:
            return url
        if "telegram" in labels and ("t.me/" in url or "telegram." in url):
            return url
        if labels & {"twitter", "x"} and ("twitter.com" in url or "x.com" in url):
            return url
    return None


def first_website_url(token: TokenScan) -> str | None:
    for site in token.websites:
        url = str(site.get("url") or "").strip()
        if url:
            return url
    return None


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
        f"<a href=\"https://rugcheck.xyz/tokens/{address}\">RUG</a>",
        f"<a href=\"https://app.bubblemaps.io/sol/token/{address}\">BUB</a>",
        f"<a href=\"https://solscan.io/token/{address}\">SOL</a>",
        f"<a href=\"https://birdeye.so/token/{address}?chain=solana\">BIRD</a>",
        f"<a href=\"https://pump.fun/{address}\">PUMP</a>",
        f"<a href=\"https://gmgn.ai/sol/token/{address}\">GMGN</a>",
    ]
    return " • ".join(links)


def scan_tool_links(token: TokenScan) -> str:
    address = html.escape(token.address)
    pair = html.escape(token.pair_address or token.address)
    dex_url = html.escape(token.pair_url)
    dextools = f"https://www.dextools.io/app/en/solana/pair-explorer/{pair}"
    gecko = f"https://www.geckoterminal.com/solana/pools/{pair}"
    mobula = f"https://mobula.io/asset/{address}"
    birdeye = f"https://birdeye.so/token/{address}?chain=solana"
    rug = f"https://rugcheck.xyz/tokens/{address}"
    solscan = f"https://solscan.io/token/{address}"
    pump = f"https://pump.fun/{address}"
    gmgn = f"https://gmgn.ai/sol/token/{address}"
    bub = f"https://app.bubblemaps.io/sol/token/{address}"
    return (
        f"<a href=\"{dex_url}\">DEX</a>·"
        f"<a href=\"{html.escape(dextools)}\">DEF</a>·"
        f"<a href=\"{html.escape(gecko)}\">GT</a>·"
        f"<a href=\"{html.escape(mobula)}\">MOB</a>·"
        f"<a href=\"{html.escape(birdeye)}\">EXP</a>·"
        f"<a href=\"{html.escape(rug)}\">RUG</a>\n"
        f"<a href=\"{html.escape(bub)}\">BUB</a>·"
        f"<a href=\"{html.escape(solscan)}\">SOL</a>·"
        f"<a href=\"{html.escape(pump)}\">PUMP</a>·"
        f"<a href=\"{html.escape(gmgn)}\">GMGN</a>"
    )


def scan_x_links(token: TokenScan) -> str:
    official = official_x_link(token)
    terms = [token.address]
    if token.symbol and token.symbol != "?":
        terms.append(f"${token.symbol}")
    base_query = " OR ".join(terms)
    recent = f"https://x.com/search?q={quote_plus(base_query)}&src=typed_query&f=live"
    top = f"https://x.com/search?q={quote_plus(base_query + ' min_faves:25')}&src=typed_query&f=top"
    links = []
    if official:
        links.append(f"<a href=\"{html.escape(official)}\">X</a>")
    links.append(f"<a href=\"{html.escape(recent)}\">Xs</a>")
    links.append(f"<a href=\"{html.escape(top)}\">Big Xs</a>")
    return " · ".join(links)


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
        f"├ Dev Sold <b>{dev_sold_light(rug.dev_sold)}</b>\n"
        f"├ Mint    <b>{mint}</b>\n"
        f"└ Freeze  <b>{freeze}</b>"
    )
