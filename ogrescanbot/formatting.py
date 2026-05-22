from __future__ import annotations

import html
import time
from urllib.parse import quote_plus

from .db import CallRecord, TokenSnapshot, TraderRecord
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
        status = "New first call" if is_new_call else "First called"
        call_line = (
            f"\n\n<b>Caller</b>\n"
            f"├ {html.escape(status)} by {caller_profile_link(call)}\n"
            f"├ Entry MC <b>{money(call.initial_cap)}</b>\n"
            f"└ ATH since call <b>{call.peak_multiple:.2f}x</b> ({multiple_pct(call.peak_multiple)}) | "
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
        f"└ ATH     <b>{token_ath_value(token, call)}</b>\n\n"
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
    status = "New first call" if is_new_call else "First called"
    caller = caller_profile_link(call) if call else "unknown"
    called_at = money(call.initial_cap) if call else "n/a"
    now = money(call.last_cap) if call else money(token.cap_for_tracking)
    best = f"{call.peak_multiple:.2f}x" if call else "n/a"
    current_value = current_multiple(call)
    current = f"{current_value:.2f}x" if current_value is not None else "n/a"
    ath = token_ath_value(token, call)
    stats = [
        "📊 <b>Token Stats</b>",
        f"├ MC:   <b>{money(token.market_cap or token.fdv)}</b>",
        f"├ ATH:  <b>{ath}</b>",
        f"├ USD:  <b>{price(token.price_usd)}</b> ({pct(token.price_change_h24)})",
        f"├ LIQ:  <b>{money(token.liquidity_usd)}</b>",
        f"├ VOL:  <b>{money(token.volume_h24)}</b> (24h)",
        f"├ SUP:  <b>{supply_value(token)}</b>",
        f"├ 1H:   <b>B {token.buys_h1 or 0} / S {token.sells_h1 or 0}</b> ({pct(token.price_change_h1)})",
    ]
    stats.extend(
        [
            f"├ P:    <code>{short_address(token.pair_address or token.address)}</code>",
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
        f"├ {html.escape(status)} by {caller}\n"
        f"├ Entry MC <b>{called_at}</b> | Now <b>{now}</b>\n"
        f"└ ATH since call <b>{best}</b> ({multiple_pct(call.peak_multiple if call else None)}) | "
        f"Current <b>{current}</b> ({multiple_pct(current_value)})\n\n"
        f"🔎 <b>Links</b>\n"
        f"└ Tap a button below for explain, paid trend, wallet map, charts, trade, security, X, and socials."
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
            f"{branch}{medal} {telegram_user_link(trader.caller_user_id, trader.caller_name)} "
            f"[{trader.best_multiple:.1f} pts]"
        )
    trader_body = "\n".join(trader_rows) if trader_rows else "└ No callers tracked yet"

    call_rows = []
    for index, call in enumerate(calls, start=1):
        prefix = "🎉" if index <= 3 else "😎"
        marker = "💊" if index in {2, 7, 8, 9} else "🟪"
        call_rows.append(
            f"{prefix}{marker} {index} <b>{html.escape(call.token_symbol)}</b> » "
            f"{telegram_user_link(call.caller_user_id, call.caller_name)} [<b>{call.peak_multiple:.1f}x</b>]"
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


def format_status(settings, backup_chat_id: str, stats: dict[str, float | int] | None = None) -> str:
    db_type = "Postgres" if settings.database_path.startswith(("postgres://", "postgresql://")) else "SQLite"
    backup = "on" if backup_chat_id and db_type == "SQLite" else ("Postgres" if db_type == "Postgres" else "off")
    keep_alive = "on" if settings.keep_alive_url and settings.keep_alive_interval_seconds > 0 else "off"
    stats = stats or {"calls": 0, "return": 0, "hit_rate": 0}
    return (
        f"<b>{html.escape(settings.bot_name)} Status</b>\n\n"
        f"├ DB        <b>{db_type}</b>\n"
        f"├ Backup    <b>{html.escape(backup)}</b>\n"
        f"├ Keepalive <b>{html.escape(keep_alive)}</b> ({settings.keep_alive_interval_seconds}s)\n"
        f"├ Live calls <b>{settings.call_update_interval_seconds}s</b> / {settings.call_update_limit} calls\n"
        f"├ RugCheck  <b>{on_off(settings.enable_rugcheck)}</b>\n"
        f"├ Pump meta <b>{on_off(settings.enable_pump_metadata)}</b>\n"
        f"├ Gecko ATH <b>{on_off(settings.enable_geckoterminal_ath)}</b>\n"
        f"├ Solana RPC <b>{on_off(settings.enable_solana_rpc)}</b>\n"
        f"├ Jupiter tokens <b>{on_off(settings.enable_jupiter_tokens)}</b>\n"
        f"└ SafeScan default <b>{on_off(settings.strict_auto_scan_filter)}</b>\n\n"
        f"<b>This Chat</b>\n"
        f"├ Calls    <b>{int(stats.get('calls', 0))}</b>\n"
        f"├ Best     <b>{float(stats.get('return', 0)):.2f}x</b>\n"
        f"└ Hit Rate <b>{int(stats.get('hit_rate', 0))}%</b>"
        f"{powered_by_footer()}"
    )


def format_trader_passport(
    period: str,
    caller_user_id: int,
    caller_name: str,
    trader: TraderRecord | None,
    calls: list[CallRecord],
    min_hit_multiple: float,
) -> str:
    user = telegram_user_link(caller_user_id, caller_name)
    if not trader or not calls:
        return (
            f"📜 <b>Trader Calls</b>\n\n"
            f"├ Trader  {user}\n"
            f"├ Period  <b>{html.escape(period)}</b>\n"
            f"└ Status  No calls tracked yet\n\n"
            "Paste a CA or $ticker in this chat to start building call history."
            f"{powered_by_footer()}"
        )

    best = calls[0]
    worst = min(calls, key=lambda item: item.peak_multiple)
    hit_rate = (trader.hits / trader.total_calls) * 100 if trader.total_calls else 0
    badges = passport_badges(trader, calls, min_hit_multiple)
    top_lines = []
    for index, call in enumerate(calls[:5], start=1):
        top_lines.append(
            f"{index}. <b>${html.escape(call.token_symbol)}</b> "
            f"[<b>{call.peak_multiple:.2f}x</b>] called at {money(call.initial_cap)}"
        )

    return (
        f"📜 <b>Trader Calls</b>\n\n"
        f"├ Trader  {user}\n"
        f"├ Period  <b>{html.escape(period)}</b>\n"
        f"├ Calls   <b>{trader.total_calls}</b>\n"
        f"├ Hit Rate <b>{hit_rate:.0f}%</b> ({trader.hits}/{trader.total_calls} at {min_hit_multiple:.1f}x+)\n"
        f"├ Best    <b>${html.escape(best.token_symbol)}</b> <b>{best.peak_multiple:.2f}x</b>\n"
        f"├ Worst   <b>${html.escape(worst.token_symbol)}</b> <b>{worst.peak_multiple:.2f}x</b>\n"
        f"└ Avg ATH <b>{trader.avg_multiple:.2f}x</b>\n\n"
        f"🏅 <b>Badges</b>\n"
        f"└ {badges}\n\n"
        f"📣 <b>Best Calls</b>\n"
        f"<blockquote>{chr(10).join(top_lines)}</blockquote>"
        f"{powered_by_footer()}"
    )


def format_trader_stats(
    caller_user_id: int,
    caller_name: str,
    trader: TraderRecord | None,
    calls: list[CallRecord],
    rank: int | None,
    min_hit_multiple: float,
) -> str:
    username = telegram_user_link(caller_user_id, display_username(caller_name))
    if not trader or not calls:
        return (
            f"<b>Trader Stats</b>\n\n"
            f"Username: {username}\n"
            "PnL Rank: Unranked\n"
            "Win Rate: 0%\n"
            "Best Trade: n/a\n"
            "Worst Trade: n/a\n"
            "Favorite Chain: Solana\n"
            "Badges:\n"
            "Rookie Caller"
            f"{powered_by_footer()}"
        )

    win_rate = (trader.hits / trader.total_calls) * 100 if trader.total_calls else 0
    best_pct = (trader.best_multiple - 1.0) * 100
    worst_pct = min(call_current_pct(call) for call in calls)
    rank_text = f"#{rank}" if rank else "Unranked"
    badges = trader_stats_badges(trader, calls, rank, min_hit_multiple)

    return (
        f"<b>Trader Stats</b>\n\n"
        f"Username: {username}\n"
        f"PnL Rank: <b>{rank_text}</b>\n"
        f"Win Rate: <b>{win_rate:.0f}%</b>\n"
        f"Best Trade: <b>{best_pct:+.0f}%</b>\n"
        f"Worst Trade: <b>{worst_pct:+.0f}%</b>\n"
        "Favorite Chain: <b>Solana</b>\n"
        "Badges:\n"
        f"{badges}"
        f"{powered_by_footer()}"
    )


def format_token_explainer(
    token: TokenScan,
    rug: RugSummary | None,
    call: CallRecord | None = None,
    mode: str = "simple",
) -> str:
    good = token_good_signs(token, rug)[:2]
    risks = token_risk_signs(token, rug)[:3]
    risk_level = explainer_risk_level(risks)
    mode_label = explainer_mode_label(mode)
    summary = explainer_summary(token, rug, mode, risk_level)
    call_line = f"\n\n📣 Call ATH <b>{call.peak_multiple:.2f}x</b>" if call else ""

    return (
        f"🧠 <b>Ogre Read</b> <i>{html.escape(mode_label)}</i>\n"
        f"<b>{html.escape(token.name)} (${html.escape(token.symbol)})</b>\n"
        f"<code>{html.escape(token.address)}</code>\n\n"
        f"🗣 <b>Summary</b>\n"
        f"└ {html.escape(summary)}\n\n"
        f"✅ <b>Good Signs</b>\n"
        f"{format_sign_lines(good)}\n\n"
        f"⚠️ <b>Risk Signs</b>\n"
        f"{format_sign_lines(risks)}\n\n"
        f"💧 <b>LP</b>\n"
        f"└ {html.escape(liquidity_meaning(token))}\n\n"
        f"👥 <b>Holders</b>\n"
        f"└ {html.escape(holder_meaning(rug))}\n\n"
        f"📊 <b>Flow</b>\n"
        f"└ {html.escape(volume_flow_meaning(token))}\n\n"
        f"🎯 <b>Overall</b>\n"
        f"└ <b>{risk_level}</b> from free scan data. Quick read, not financial advice."
        f"{call_line}"
        f"{powered_by_footer()}"
    )


def format_paid_trend(
    token: TokenScan,
    rug: RugSummary | None,
    first_snapshot: TokenSnapshot | None = None,
    latest_snapshot: TokenSnapshot | None = None,
) -> str:
    label = paid_trend_label(token, first_snapshot)
    before_after = paid_before_after_lines(token, rug, first_snapshot, latest_snapshot)
    worked = paid_worked_line(token, first_snapshot)
    return (
        f"📣 <b>Paid Trend Check</b>\n"
        f"<b>{html.escape(token.name)} (${html.escape(token.symbol)})</b>\n"
        f"<code>{html.escape(token.address)}</code>\n\n"
        f"├ Label <b>{label}</b>\n"
        f"├ Boost detected <b>{dex_paid_bracket(token.dex_paid)}</b>\n"
        f"├ Current MC <b>{money(token.cap_for_tracking)}</b>\n"
        f"├ Current Vol <b>{money(token.volume_h24)}</b>\n"
        f"└ Current LP <b>{money(token.liquidity_usd)}</b>\n\n"
        f"📈 <b>Impact</b>\n"
        f"{before_after}\n\n"
        f"🧪 <b>Did it work?</b>\n"
        f"└ {worked}\n\n"
        "Snapshots improve as the bot sees the token over time."
        f"{powered_by_footer()}"
    )


def format_cluster_report(token: TokenScan, rug: RugSummary | None) -> str:
    signals = cluster_signals(token, rug)
    return (
        f"🧬 <b>Wallet Cluster Check</b>\n"
        f"<b>{html.escape(token.name)} (${html.escape(token.symbol)})</b>\n"
        f"<code>{html.escape(token.address)}</code>\n\n"
        "This is a cautious free-data read. It can flag possible patterns, not prove wallet links.\n\n"
        f"🔎 <b>Possible Signals</b>\n"
        f"{format_sign_lines(signals)}\n\n"
        f"👥 <b>Holder Concentration</b>\n"
        f"└ {html.escape(holder_meaning(rug))}\n\n"
        "For visual wallet mapping, use the BubbleMaps button below."
        f"{powered_by_footer()}"
    )


def format_why_loss(token: TokenScan, call: CallRecord | None, wallet: str | None = None) -> str:
    wallet_line = f"Wallet: <code>{html.escape(short_address(wallet))}</code>\n" if wallet else ""
    if call and call.initial_cap > 0:
        current_cap = token.cap_for_tracking or call.last_cap
        loss_pct = ((current_cap / call.initial_cap) - 1.0) * 100 if current_cap else 0
        entry = money(call.initial_cap)
        current = money(current_cap)
    else:
        loss_pct = token.price_change_h24 or 0
        entry = "n/a"
        current = money(token.cap_for_tracking)

    mistakes = why_loss_reasons(token, call, loss_pct)
    lesson = why_loss_lesson(loss_pct)
    return (
        f"🧯 <b>Explain My Loss</b>\n"
        f"<b>{html.escape(token.name)} (${html.escape(token.symbol)})</b>\n"
        f"{wallet_line}"
        f"<code>{html.escape(token.address)}</code>\n\n"
        f"├ Entry MC <b>{entry}</b>\n"
        f"├ Now MC <b>{current}</b>\n"
        f"└ Result <b>{loss_pct:+.0f}%</b>\n\n"
        f"⚠️ <b>What likely went wrong</b>\n"
        f"{format_sign_lines(mistakes)}\n\n"
        f"📘 <b>Lesson</b>\n"
        f"└ {html.escape(lesson)}\n\n"
        "Wallet-level trade history needs a wallet/indexer layer. This view uses tracked calls and current free market data."
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
        "|- /scan or /call &lt;ca, link, or $ticker&gt;\n"
        "|- /intel &lt;ca or $ticker&gt;\n"
        "|- /pnl | /flex &lt;ca or $ticker&gt;\n"
        "|- /stats\n"
        "|- /calls\n"
        "|- /leaderboard\n"
        "|- /lb 1d | /lb 1w | /lb 2w | /lb 1m\n"
        "|- lb | leaderboard\n"
        "|- /safescan on | /safescan off\n"
        "|- /status\n"
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


def supply_value(token: TokenScan) -> str:
    if token.supply:
        return compact_number(token.supply)
    if not token.price_usd or token.price_usd <= 0 or not token.cap_for_tracking:
        return "n/a"
    return compact_number(token.cap_for_tracking / token.price_usd)


def compact_number(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"


def token_ath_value(token: TokenScan, call: CallRecord | None = None) -> str:
    if token.ath_market_cap:
        current_cap = token.cap_for_tracking
        pct_text = ""
        if current_cap and token.ath_market_cap > 0:
            pct_text = f"{((current_cap / token.ath_market_cap) - 1.0) * 100:+.0f}%"
        age_text = age_from_seconds(int(time.time()) - token.ath_timestamp) if token.ath_timestamp else ""
        detail = " / ".join(part for part in [pct_text, age_text] if part)
        return f"{money(token.ath_market_cap)} ({detail})" if detail else money(token.ath_market_cap)
    if call:
        return f"{money(call.peak_cap)} ({call.peak_multiple:.2f}x from call)"
    if token.cap_for_tracking:
        return f"{money(token.cap_for_tracking)} (current)"
    return "n/a"


def current_multiple(call: CallRecord | None) -> float | None:
    if not call or call.initial_cap <= 0:
        return None
    return max(0.0, call.last_cap / call.initial_cap)


def caller_profile_link(call: CallRecord | None) -> str:
    if not call:
        return "unknown"
    return telegram_user_link(call.caller_user_id, call.caller_name)


def telegram_user_link(user_id: int | None, name: str | None) -> str:
    clean = html.escape(name or "unknown")
    if user_id and user_id > 0:
        return f"<a href=\"tg://user?id={user_id}\">{clean}</a>"
    return clean


def on_off(value: bool) -> str:
    return "on" if value else "off"


def passport_badges(trader: TraderRecord, calls: list[CallRecord], min_hit_multiple: float) -> str:
    badges: list[str] = []
    if trader.best_multiple >= 10:
        badges.append("🚀 10x Caller")
    elif trader.best_multiple >= 5:
        badges.append("🔥 5x Caller")
    elif trader.best_multiple >= min_hit_multiple:
        badges.append("📣 Hit Caller")
    if trader.total_calls >= 25:
        badges.append("🏟 Season Grinder")
    elif trader.total_calls >= 10:
        badges.append("📚 Active Caller")
    if trader.hits >= 5:
        badges.append("🎯 Consistent")
    if calls and max(call.peak_cap for call in calls) >= 1_000_000:
        badges.append("🐋 Whale Radar")
    return " • ".join(badges) if badges else "Rookie Caller"


def trader_stats_badges(
    trader: TraderRecord,
    calls: list[CallRecord],
    rank: int | None,
    min_hit_multiple: float,
) -> str:
    badges: list[str] = []
    if rank and rank <= 100:
        badges.append("🏆 Top 100 Trader")
    if trader.best_multiple >= min_hit_multiple:
        badges.append("🔥 Early Caller")
    if any(call.initial_cap <= 100_000 for call in calls):
        badges.append("💎 Low Cap Hunter")
    if any(call.peak_cap >= 1_000_000 for call in calls):
        badges.append("🐋 Whale Watcher")
    if any(call.peak_multiple >= min_hit_multiple and call_current_pct(call) <= -30 for call in calls):
        badges.append("🛡 Rug Survivor")
    if trader.total_calls >= 10:
        badges.append("📚 Active Caller")
    if not badges:
        badges.append("Rookie Caller")
    return "\n".join(badges[:6])


def display_username(name: str | None) -> str:
    clean = str(name or "unknown").strip()
    if clean == "unknown" or clean.startswith("@") or " " in clean:
        return clean
    return f"@{clean}"


def call_current_pct(call: CallRecord) -> float:
    if call.initial_cap <= 0:
        return 0.0
    return ((call.last_cap / call.initial_cap) - 1.0) * 100


def explainer_mode_label(mode: str) -> str:
    labels = {
        "simple": "Overview",
        "degen": "Degen",
        "risk": "Risk",
        "whale": "Whale",
        "owner": "Project Owner",
    }
    return labels.get(mode, labels["simple"])


def explainer_summary(token: TokenScan, rug: RugSummary | None, mode: str, risk_level: str) -> str:
    cap = money(token.cap_for_tracking)
    lp = money(token.liquidity_usd)
    if mode == "degen":
        return f"{token.symbol} is a {risk_level.lower()} play at {cap} MC with {lp} liquidity. Watch flow before chasing."
    if mode == "risk":
        return f"Main risk read: {risk_level.lower()}, with liquidity, holders, and short-term flow driving the score."
    if mode == "whale":
        return f"For bigger entries, focus on LP depth ({lp}), holder concentration, and whether exits can happen cleanly."
    if mode == "owner":
        return "Owner view: improve trust with clear socials, safer authorities, healthier LP, and cleaner holders."
    return f"This is a Solana token at {cap} MC with {lp} liquidity. The quick read is {risk_level.lower()}."


def liquidity_meaning(token: TokenScan) -> str:
    lp = token.liquidity_usd
    if lp is None:
        return "Liquidity was not returned by the free API, so trade depth is unclear."
    if lp < 5_000:
        return f"Very thin liquidity ({money(lp)}). Small buys/sells can move price hard."
    if lp < 25_000:
        return f"Low liquidity ({money(lp)}). Usable for small trades, risky for size."
    return f"Liquidity is healthier for a small-cap token ({money(lp)}), but still watch slippage."


def holder_meaning(rug: RugSummary | None) -> str:
    if not rug:
        return "Holder data was not available from the free RugCheck endpoint."
    pct = rug.top_10_holder_pct if rug.top_10_holder_pct is not None else rug.top_holder_pct
    if pct is None:
        return "Holder concentration was not returned by the free RugCheck endpoint."
    total = ""
    if rug.holder_count and rug.holder_count_source == "Solana RPC":
        total = f" across {rug.holder_count} on-chain holders"
    if pct >= 30:
        return f"Concentrated: top holders control about {pct:.1f}%{total}."
    if pct >= 15:
        return f"Moderate concentration: top holders control about {pct:.1f}%{total}."
    return f"Lower visible concentration: top holders control about {pct:.1f}%{total}."


def volume_flow_meaning(token: TokenScan) -> str:
    buys = token.buys_h1 or 0
    sells = token.sells_h1 or 0
    vol = money(token.volume_h24)
    if buys > sells:
        return f"1h flow leans bullish: B {buys} / S {sells}, with {vol} 24h volume."
    if sells > buys:
        return f"1h flow leans sell-side: B {buys} / S {sells}, with {vol} 24h volume."
    return f"1h flow is balanced or missing: B {buys} / S {sells}, with {vol} 24h volume."


def paid_trend_label(token: TokenScan, first_snapshot: TokenSnapshot | None) -> str:
    if token.dex_paid is True and first_snapshot and first_snapshot.market_cap and token.cap_for_tracking:
        move = (token.cap_for_tracking / first_snapshot.market_cap) - 1.0
        return "Paid / Working" if move > 0.25 else "Paid / Mixed"
    if token.dex_paid is True:
        return "Paid"
    return "Organic" if token.dex_paid is False else "Mixed"


def paid_before_after_lines(
    token: TokenScan,
    rug: RugSummary | None,
    first_snapshot: TokenSnapshot | None,
    latest_snapshot: TokenSnapshot | None,
) -> str:
    if not first_snapshot or not latest_snapshot or first_snapshot.id == latest_snapshot.id:
        return (
            "└ No earlier snapshot yet. Scan or check this token again later to measure before/after boost impact."
        )
    lines = [
        f"├ MC {money(first_snapshot.market_cap)} → {money(token.cap_for_tracking)} ({delta_pct(first_snapshot.market_cap, token.cap_for_tracking)})",
        f"├ Vol {money(first_snapshot.volume_h24)} → {money(token.volume_h24)} ({delta_pct(first_snapshot.volume_h24, token.volume_h24)})",
        f"└ LP {money(first_snapshot.liquidity_usd)} → {money(token.liquidity_usd)} ({delta_pct(first_snapshot.liquidity_usd, token.liquidity_usd)})",
    ]
    return "\n".join(lines)


def paid_worked_line(token: TokenScan, first_snapshot: TokenSnapshot | None) -> str:
    if not first_snapshot or not first_snapshot.market_cap or not token.cap_for_tracking:
        return "Tracking starts once the bot has more than one snapshot."
    move_pct = ((token.cap_for_tracking / first_snapshot.market_cap) - 1.0) * 100
    if move_pct >= 50:
        return f"Looks effective so far: MC is up {move_pct:.0f}% from the first snapshot."
    if move_pct > 0:
        return f"Mixed so far: MC is up {move_pct:.0f}%, but keep watching volume and LP."
    return f"Not working yet: MC is down {move_pct:.0f}% from the first snapshot."


def cluster_signals(token: TokenScan, rug: RugSummary | None) -> list[str]:
    signals: list[str] = []
    if rug and rug.top_10_holder_pct is not None and rug.top_10_holder_pct >= 30:
        signals.append(f"Possible concentration cluster: top 10 holders around {rug.top_10_holder_pct:.1f}%")
    if rug and rug.top_10_holder_pct is not None and rug.top_10_holder_pct < 15:
        signals.append(f"Lower visible holder concentration: top 10 around {rug.top_10_holder_pct:.1f}%")
    if rug and rug.holder_count is not None and rug.holder_count_source == "Solana RPC" and rug.holder_count < 100:
        signals.append(f"Small holder base from on-chain RPC: {rug.holder_count} holders")
    if token.created_at_ms:
        age = age_from_ms(token.created_at_ms)
        if age.endswith("m") or age.endswith("h"):
            signals.append(f"Fresh launch behavior can hide sniper/insider clusters: age {age}")
    if token.liquidity_usd is not None and token.liquidity_usd < 10_000:
        signals.append(f"Thin LP can amplify coordinated sells: {money(token.liquidity_usd)}")
    if (token.sells_h1 or 0) > (token.buys_h1 or 0):
        signals.append(f"Recent sell pressure is higher than buys: B {token.buys_h1 or 0} / S {token.sells_h1 or 0}")
    return signals or ["No strong cluster signal from free data. Use BubbleMaps for a visual wallet map."]


def why_loss_reasons(token: TokenScan, call: CallRecord | None, loss_pct: float) -> list[str]:
    reasons: list[str] = []
    if loss_pct < 0:
        reasons.append(f"Current value is below tracked entry by {abs(loss_pct):.0f}%")
    if token.price_change_h1 is not None and token.price_change_h1 < 0:
        reasons.append(f"1h momentum turned negative: {pct(token.price_change_h1)}")
    if (token.sells_h1 or 0) > (token.buys_h1 or 0):
        reasons.append(f"Sell pressure beat buys: B {token.buys_h1 or 0} / S {token.sells_h1 or 0}")
    if token.liquidity_usd is not None and token.liquidity_usd < 10_000:
        reasons.append(f"Liquidity was thin, so price can move sharply: {money(token.liquidity_usd)}")
    if call and call.peak_multiple > 2 and loss_pct < 0:
        reasons.append("The call had profit available earlier, but current price gave it back")
    return reasons or ["No tracked loss pattern yet. More entry/exit data would improve this read."]


def why_loss_lesson(loss_pct: float) -> str:
    if loss_pct <= -50:
        return "Size smaller, respect liquidity, and consider taking partials when a low-cap trade runs."
    if loss_pct < 0:
        return "Wait for buy flow to confirm and avoid entering after momentum flips sell-side."
    return "This does not look like a tracked loss from current data. Review entry timing and liquidity before sizing up."


def delta_pct(start: float | None, end: float | None) -> str:
    if not start or not end or start <= 0:
        return "n/a"
    return f"{((end / start) - 1.0) * 100:+.0f}%"


def token_good_signs(token: TokenScan, rug: RugSummary | None) -> list[str]:
    signs: list[str] = []
    if token.liquidity_usd and token.liquidity_usd >= 10_000:
        signs.append(f"Liquidity is usable for a small-cap scan: {money(token.liquidity_usd)}")
    if token.volume_h24 and token.liquidity_usd and token.volume_h24 >= token.liquidity_usd:
        signs.append(f"24h volume is active versus liquidity: {money(token.volume_h24)}")
    if (token.buys_h1 or 0) > (token.sells_h1 or 0):
        signs.append(f"1h flow leans buy-side: B {token.buys_h1 or 0} / S {token.sells_h1 or 0}")
    if token.dex_paid is True:
        signs.append("DEX paid/enhanced status is detected")
    if rug and not rug.mint_authority and not rug.freeze_authority:
        signs.append("Mint and freeze authority look off")
    if scan_social_links(token) != "none found":
        signs.append("Social or website metadata is present")
    return signs[:5] or ["No strong positive signal found from the free data"]


def token_risk_signs(token: TokenScan, rug: RugSummary | None) -> list[str]:
    signs: list[str] = []
    if token.created_at_ms:
        seconds_old = int(time.time() - (token.created_at_ms / 1000))
        if seconds_old < 3600:
            signs.append(f"Very new token: {age_from_ms(token.created_at_ms)} old")
    if not token.liquidity_usd or token.liquidity_usd < 5_000:
        signs.append(f"Thin or missing liquidity: {money(token.liquidity_usd)}")
    if token.price_change_h24 is not None and token.price_change_h24 <= -30:
        signs.append(f"24h price action is weak: {pct(token.price_change_h24)}")
    if token.price_change_h1 is not None and token.price_change_h1 <= -15:
        signs.append(f"1h momentum is negative: {pct(token.price_change_h1)}")
    if rug and rug.top_10_holder_pct is not None and rug.top_10_holder_pct >= 30:
        signs.append(f"Top 10 holder concentration is high: {rug.top_10_holder_pct:.1f}%")
    elif rug and rug.top_holder_pct is not None and rug.top_holder_pct >= 15:
        signs.append(f"Top holder concentration is high: {rug.top_holder_pct:.1f}%")
    if rug and rug.dev_sold is True:
        signs.append("RugCheck indicates dev sold")
    if rug and (rug.mint_authority or rug.freeze_authority):
        signs.append("Mint or freeze authority appears active")
    if token.dex_paid is False:
        signs.append("DEX paid/enhanced status was not found")
    return signs[:6] or ["No major risk flag found from the free data"]


def format_sign_lines(items: list[str]) -> str:
    if not items:
        return "└ n/a"
    lines = []
    for index, item in enumerate(items):
        branch = "└" if index == len(items) - 1 else "├"
        lines.append(f"{branch} {html.escape(item)}")
    return "\n".join(lines)


def explainer_risk_level(risks: list[str]) -> str:
    count = len([risk for risk in risks if "No major risk" not in risk])
    if count >= 5:
        return "High risk"
    if count >= 3:
        return "Medium/high risk"
    if count >= 1:
        return "Medium risk"
    return "Lower visible risk"


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
        f"├ 👥 Top 10 <b>[{rug_top_10_holders(rug)}]</b>\n"
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


def dex_paid_link(token: TokenScan) -> str:
    label = dex_paid_bracket(token.dex_paid)
    url = html.escape(token.pair_url or f"https://dexscreener.com/solana/{token.address}")
    return f"<a href=\"{url}\">{label}</a>"


def dev_sold_bracket(value: bool | None) -> str:
    if value is True:
        return "[YES]"
    if value is False:
        return "[NO]"
    return "[n/a]"


def dev_sold_link(rug: RugSummary | None) -> str:
    label = dev_sold_bracket(rug.dev_sold if rug else None)
    wallet = rug.dev_wallet if rug else None
    if not wallet:
        return label
    return f"<a href=\"https://solscan.io/account/{html.escape(wallet)}\">{label}</a>"


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


def rug_top_10_holders(rug: RugSummary | None) -> str:
    if not rug:
        return "n/a"
    pct_value = rug.top_10_holder_pct if rug.top_10_holder_pct is not None else rug.top_holder_pct
    pct = f"{pct_value:.1f}%" if pct_value is not None else "n/a"
    if rug.holder_count is not None and rug.holder_count_source == "Solana RPC":
        return f"{pct} | {rug.holder_count} holders"
    return pct


def age_from_ms(created_at_ms: int | None) -> str:
    if not created_at_ms:
        return "age n/a"
    seconds = max(0, int(time.time() - (created_at_ms / 1000)))
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def age_from_seconds(seconds: int | None) -> str:
    if seconds is None:
        return ""
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return f"{max(1, seconds // 60)}m"
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
        links.append("TG")
    if website:
        links.append("Web")
    if x_url:
        links.append("X")
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
