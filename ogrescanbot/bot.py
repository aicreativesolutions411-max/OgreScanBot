from __future__ import annotations

import asyncio
from dataclasses import replace
import html
import logging
from io import BytesIO
from pathlib import Path
import time

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import ClientError, web
from PIL import Image, UnidentifiedImageError

from .config import Settings, load_settings
from .db import Database, period_to_since
from .dexscreener import DexscreenerClient
from .extract import extract_token_queries, extract_x_post_links, is_solana_address
from .formatting import (
    format_help,
    format_leaderboard,
    format_leaderboard_backup_snapshot,
    format_scan,
    format_scan_caption,
    format_x_post_embed,
    powered_by_footer,
    user_display_name,
)
from .images import build_pnl_card, build_scan_banner
from .pumpfun import PumpFunClient
from .rugcheck import RugCheckClient


class OgreScanApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bot = Bot(
            token=settings.telegram_bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.dp = Dispatcher()
        self.db = Database(settings.database_path)
        self.dex = DexscreenerClient()
        self.rug = RugCheckClient() if settings.enable_rugcheck else None
        self.pump = PumpFunClient() if settings.enable_pump_metadata else None
        self.last_backup_at = 0.0
        self.backup_task: asyncio.Task | None = None
        self.call_tracker_task: asyncio.Task | None = None
        self.learned_backup_chat_id = ""
        self._register_handlers()

    async def start(self) -> None:
        await self.restore_database_backup()
        await self.db.open()
        await self.load_backup_chat_id_from_db()
        self.start_auto_backup_loop()
        self.start_call_tracker_loop()
        try:
            await self.dp.start_polling(self.bot)
        finally:
            await self.stop_call_tracker_loop()
            await self.stop_auto_backup_loop()
            await self.dex.close()
            if self.rug:
                await self.rug.close()
            if self.pump:
                await self.pump.close()
            await self.db.close()
            await self.bot.session.close()

    def build_webhook_app(self) -> web.Application:
        if not self.settings.webhook_url:
            raise RuntimeError("WEBHOOK_URL is required when RUN_MODE=webhook.")

        app = web.Application()
        app.on_startup.append(self._on_webhook_startup)
        app.on_cleanup.append(self._on_webhook_cleanup)
        app.router.add_get("/", self.health)
        app.router.add_get("/healthz", self.health)
        SimpleRequestHandler(dispatcher=self.dp, bot=self.bot).register(app, path=self.settings.webhook_path)
        setup_application(app, self.dp, bot=self.bot)
        return app

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "bot": self.settings.bot_name})

    async def _on_webhook_startup(self, app: web.Application) -> None:
        await self.restore_database_backup()
        await self.db.open()
        await self.load_backup_chat_id_from_db()
        self.start_auto_backup_loop()
        self.start_call_tracker_loop()
        webhook_endpoint = f"{self.settings.webhook_url}{self.settings.webhook_path}"
        await self.bot.set_webhook(
            webhook_endpoint,
            drop_pending_updates=True,
            allowed_updates=self.dp.resolve_used_update_types(),
        )
        logging.info("Webhook set to %s", webhook_endpoint)

    async def _on_webhook_cleanup(self, app: web.Application) -> None:
        await self.stop_call_tracker_loop()
        await self.stop_auto_backup_loop()
        await self.dex.close()
        if self.rug:
            await self.rug.close()
        if self.pump:
            await self.pump.close()
        await self.db.close()
        await self.bot.session.close()

    def _register_handlers(self) -> None:
        self.dp.message.register(self.help_handler, Command("start", "help"))
        self.dp.message.register(self.set_backup_channel_command, lambda message: is_backup_command(message.text or ""))
        self.dp.message.register(self.scan_command, Command("scan"))
        self.dp.message.register(self.pnl_command, Command("pnl", "flex"))
        self.dp.message.register(self.pnl_command, lambda message: is_plain_card_command(message.text or ""))
        self.dp.message.register(self.leaderboard_command, Command("lb", "leaderboard"))
        self.dp.callback_query.register(self.leaderboard_period_callback, F.data.startswith("lb:"))
        self.dp.message.register(self.backup_command, Command("backup"))
        self.dp.message.register(self.auto_scan_message, F.text)
        self.dp.channel_post.register(self.channel_post_text_handler, F.text)
        self.dp.my_chat_member.register(self.maybe_auto_set_backup_channel)

    async def help_handler(self, message: Message) -> None:
        await message.reply(format_help(self.settings.bot_name), disable_web_page_preview=True)

    async def scan_command(self, message: Message) -> None:
        query = first_token_query_from_message(message)
        if not query:
            await message.reply("Send /scan followed by a Solana contract address, supported token link, or $ticker.")
            return
        await self.scan_and_reply(message, query)

    async def auto_scan_message(self, message: Message) -> None:
        text = message.text or ""
        if text.startswith("/"):
            return
        await self.maybe_embed_x_posts(message)
        query = first_token_query_from_message(message)
        if query:
            await self.scan_and_reply(message, query)

    async def maybe_embed_x_posts(self, message: Message) -> None:
        links = extract_x_post_links(message.text or message.caption or "")
        for username, _status_id, embed_url in links[:2]:
            try:
                await message.reply(
                    format_x_post_embed(username, embed_url, message.from_user),
                    disable_web_page_preview=False,
                )
            except Exception:
                logging.exception("Failed to embed X post: %s", embed_url)

    async def pnl_command(self, message: Message) -> None:
        query = first_token_query_from_message(message)
        command = command_name(message.text or "")
        title = "FLEX" if command == "flex" else "PNL"
        if not query:
            await message.reply(f"Send /{title.lower()} followed by a Solana contract address or $ticker.")
            return

        token = await self.resolve_token(query)
        if not token:
            await message.reply("I could not find that Solana token on Dexscreener or Pump.fun yet.")
            return

        user = message.from_user
        if not user:
            await message.reply("I need a Telegram user to attach this card to.")
            return

        try:
            call, _ = await self.db.upsert_call(message.chat.id, token, user.id, user_display_name(user))
        except ValueError:
            await message.reply("That token is missing market cap/FDV data, so I cannot build a tracked PNL/FLEX card yet.")
            return
        await self.maybe_backup_database()
        current_x = call.last_cap / call.initial_cap if call.initial_cap else call.peak_multiple
        result_line = pnl_result_line(call, current_x)
        card = build_pnl_card(token, call, title=title)
        photo = BufferedInputFile(card.getvalue(), filename=card.name)
        token_title = html.escape(f"{token.name} (${token.symbol})")
        player = html.escape(user_display_name(user))
        await message.reply_photo(
            photo,
            caption=(
                f"🧌 <b>{title} CARD</b>\n"
                f"<b>{token_title}</b>\n"
                f"Player <b>{player}</b>\n"
                f"Called <b>{plain_money(call.initial_cap)}</b> | ATH <b>{plain_money(call.peak_cap)}</b>\n"
                f"{result_line}"
                f"{powered_by_footer()}"
            ),
        )

    async def leaderboard_command(self, message: Message) -> None:
        args = command_args(message)
        period, text, markup = await self.build_leaderboard_message(message.chat.id, args[0] if args else "1d")
        await message.reply(text, reply_markup=markup, disable_web_page_preview=True)

    async def leaderboard_period_callback(self, callback: CallbackQuery) -> None:
        if not callback.message or not callback.data:
            await callback.answer()
            return
        requested = callback.data.split(":", 1)[1]
        _period, text, markup = await self.build_leaderboard_message(callback.message.chat.id, requested)
        try:
            await callback.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
            await callback.answer()
        except Exception:
            logging.exception("Leaderboard period update failed.")
            await callback.answer("Could not update leaderboard right now.", show_alert=False)

    async def build_leaderboard_message(
        self,
        chat_id: int,
        requested_period: str,
    ) -> tuple[str, str, InlineKeyboardMarkup]:
        period, since_ts = period_to_since(requested_period)
        traders = await self.db.top_traders(
            chat_id,
            since_ts=since_ts,
            min_hit_multiple=self.settings.min_multiple_for_hit,
            limit=5,
        )
        calls = await self.db.leaderboard(chat_id, since_ts=since_ts, limit=10)
        stats = await self.db.stats(chat_id, since_ts, self.settings.min_multiple_for_hit)
        return period, format_leaderboard(period, traders, calls, stats), leaderboard_keyboard(period)

    async def backup_command(self, message: Message) -> None:
        if not self.sqlite_backup_enabled():
            await message.reply("Backup channel is not configured. Post /setbackup inside the private backup channel first.")
            return
        await self.backup_database()
        await message.reply("Backup sent to the configured Telegram backup channel.")

    async def set_backup_channel_command(self, message: Message) -> None:
        await self.save_backup_chat_id(str(message.chat.id))
        await message.answer(
            f"OgreScanBot backup channel set.\nChat ID: {message.chat.id}\nI will auto-backup here."
        )
        self.start_auto_backup_loop()
        restored = False
        if self.db.conn and not await self.db.chat_ids(limit=1):
            restored = await self.restore_database_backup(force=True)
        if restored:
            await message.answer("Restored calls and leaderboards from the pinned backup.")
        if self.db.conn:
            await self.backup_database()

    async def channel_post_text_handler(self, message: Message) -> None:
        if is_backup_command(message.text or ""):
            await self.set_backup_channel_command(message)

    async def maybe_auto_set_backup_channel(self, event: ChatMemberUpdated) -> None:
        chat_type = getattr(event.chat.type, "value", event.chat.type)
        status = getattr(event.new_chat_member.status, "value", event.new_chat_member.status)
        if chat_type != "channel" or status not in {"administrator", "creator"}:
            return
        if self.backup_chat_id():
            return

        await self.save_backup_chat_id(str(event.chat.id))
        self.start_auto_backup_loop()
        try:
            await self.bot.send_message(
                event.chat.id,
                f"OgreScanBot backup channel auto-set.\nChat ID: {event.chat.id}\nI will auto-backup here.",
            )
            if self.db.conn:
                await self.backup_database()
        except Exception:
            logging.exception("Auto-set backup channel message failed.")

    async def scan_and_reply(self, message: Message, query: str) -> None:
        await message.bot.send_chat_action(message.chat.id, "typing")
        token = await self.resolve_token(query)
        if not token:
            await message.reply("I could not find that Solana token on Dexscreener or Pump.fun yet.")
            return

        user = message.from_user
        caller_id = user.id if user else 0
        caller_name = user_display_name(user) if user else "unknown"
        try:
            call, is_new_call = await self.db.upsert_call(message.chat.id, token, caller_id, caller_name)
            await self.maybe_backup_database()
        except ValueError:
            call, is_new_call = None, False

        rug = await self.rug.summary(token.address) if self.rug else None
        scan_text = format_scan_caption(token, call, is_new_call, rug)
        banner = await self.build_scan_photo(token)
        try:
            await message.reply_photo(banner, caption=scan_text)
        except Exception:
            logging.exception("Full scan photo send failed; retrying with safe caption.")
            safe_caption = safe_scan_caption(token, call)
            try:
                await message.reply_photo(banner, caption=safe_caption, parse_mode=None)
            except Exception:
                logging.exception("Safe scan photo send failed; falling back to text reply.")
                await message.reply(safe_caption, parse_mode=None, disable_web_page_preview=True)

    async def build_scan_photo(self, token) -> BufferedInputFile:
        source = None
        for image_url in unique_urls([token.image_url, token.header_url]):
            source = await self.download_image(image_url)
            if source:
                break
        banner = build_scan_banner(token, source)
        return BufferedInputFile(banner.getvalue(), filename=banner.name)

    async def download_image(self, url: str) -> bytes | None:
        try:
            async with self.dex._session.get(url, headers={"User-Agent": "OgreScanBot/1.0"}) as response:
                if response.status >= 400:
                    return None
                data = await response.read()
        except ClientError:
            return None
        if not data or len(data) > 10_000_000:
            return None
        return normalize_image_bytes(data)

    async def resolve_token(self, query: str, include_paid: bool = True):
        query = self.resolve_ticker_alias(query)
        token = await self.dex.scan_solana_token(query)
        if token and self.pump:
            token = token.with_pump_metadata(await self.pump.metadata(token.address))
        if token:
            return await self.enrich_dex_paid(token) if include_paid else token
        if self.pump and is_solana_address(query):
            pump_token = await self.pump.scan_token(query)
            if not pump_token:
                return None
            return await self.enrich_dex_paid(pump_token) if include_paid else pump_token
        return None

    async def enrich_dex_paid(self, token):
        paid = await self.dex.token_orders_paid(token.chain_id or "solana", token.address)
        if paid is None:
            return token
        return replace(token, dex_paid=bool(token.dex_paid or paid))

    def resolve_ticker_alias(self, query: str) -> str:
        clean = str(query or "").strip()
        if is_solana_address(clean):
            return clean
        alias = self.settings.ticker_aliases.get(clean.upper().removeprefix("$"))
        return alias or clean

    def start_auto_backup_loop(self) -> None:
        if not self.sqlite_backup_enabled() or self.backup_task:
            return
        self.backup_task = asyncio.create_task(self.auto_backup_loop())

    async def stop_auto_backup_loop(self) -> None:
        if not self.backup_task:
            return
        self.backup_task.cancel()
        try:
            await self.backup_task
        except asyncio.CancelledError:
            pass
        self.backup_task = None

    async def auto_backup_loop(self) -> None:
        while True:
            await asyncio.sleep(max(60, self.settings.backup_interval_seconds))
            await self.backup_database()

    def start_call_tracker_loop(self) -> None:
        if self.call_tracker_task or self.settings.call_update_interval_seconds <= 0:
            return
        self.call_tracker_task = asyncio.create_task(self.call_tracker_loop())

    async def stop_call_tracker_loop(self) -> None:
        if not self.call_tracker_task:
            return
        self.call_tracker_task.cancel()
        try:
            await self.call_tracker_task
        except asyncio.CancelledError:
            pass
        self.call_tracker_task = None

    async def call_tracker_loop(self) -> None:
        while True:
            await asyncio.sleep(max(30, self.settings.call_update_interval_seconds))
            await self.refresh_tracked_calls()

    async def refresh_tracked_calls(self) -> None:
        try:
            calls = await self.db.tracked_calls(limit=max(1, self.settings.call_update_limit))
        except Exception:
            logging.exception("Could not load tracked calls for live API refresh.")
            return

        changed = 0
        for record in calls:
            try:
                token = await self.resolve_token(record.token_address, include_paid=False)
                if not token or not token.cap_for_tracking:
                    continue
                updated, _ = await self.db.upsert_call(
                    record.chat_id,
                    token,
                    record.caller_user_id,
                    record.caller_name,
                )
                if updated.last_cap != record.last_cap or updated.peak_multiple != record.peak_multiple:
                    changed += 1
            except Exception:
                logging.exception("Live call refresh failed for %s", record.token_address)
            await asyncio.sleep(0.25)

        if changed:
            logging.info("Live call tracker refreshed %s calls.", changed)
            await self.maybe_backup_database()

    def sqlite_backup_enabled(self) -> bool:
        return bool(
            self.backup_chat_id()
            and not self.settings.database_path.startswith(("postgres://", "postgresql://"))
        )

    def backup_chat_id(self) -> str:
        if self.settings.backup_chat_id:
            return self.settings.backup_chat_id
        if self.learned_backup_chat_id:
            return self.learned_backup_chat_id
        path = Path(self.settings.backup_chat_id_file)
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                self.learned_backup_chat_id = value
                return value
        return ""

    async def save_backup_chat_id(self, chat_id: str) -> None:
        self.learned_backup_chat_id = chat_id
        Path(self.settings.backup_chat_id_file).write_text(chat_id, encoding="utf-8")
        if self.db.conn or self.db.pool:
            await self.db.set_setting("backup_chat_id", chat_id)

    async def load_backup_chat_id_from_db(self) -> None:
        if self.settings.backup_chat_id or self.learned_backup_chat_id:
            return
        if not (self.db.conn or self.db.pool):
            return
        value = await self.db.get_setting("backup_chat_id")
        if value:
            self.learned_backup_chat_id = value
            Path(self.settings.backup_chat_id_file).write_text(value, encoding="utf-8")

    async def restore_database_backup(self, force: bool = False) -> bool:
        if not self.sqlite_backup_enabled() or not self.settings.restore_backup_on_start:
            return False

        db_path = Path(self.settings.database_path)
        if db_path.exists() and db_path.stat().st_size > 0 and not force:
            return False

        try:
            backup_chat_id = self.backup_chat_id()
            if not backup_chat_id:
                return False
            chat = await self.telegram_api("getChat", {"chat_id": backup_chat_id})
            pinned = (chat.get("result") or {}).get("pinned_message") or {}
            document = pinned.get("document") or {}
            file_id = document.get("file_id")
            if not file_id:
                logging.info("No pinned backup document found in BACKUP_CHAT_ID.")
                return False

            file_info = await self.telegram_api("getFile", {"file_id": file_id})
            file_path = (file_info.get("result") or {}).get("file_path")
            if not file_path:
                return False

            data = await self.download_telegram_file(file_path)
            if not data:
                return False

            was_open = bool(self.db.conn)
            if was_open:
                await self.db.close()
                self.db.conn = None
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db_path.write_bytes(data)
            if was_open:
                await self.db.open()
                await self.load_backup_chat_id_from_db()
            logging.info("Restored SQLite database from pinned Telegram backup.")
            return True
        except Exception:
            logging.exception("Database backup restore failed.")
            return False

    async def maybe_backup_database(self) -> None:
        if not self.sqlite_backup_enabled():
            return

        now = time.time()
        if now - self.last_backup_at < self.settings.backup_interval_seconds:
            return
        self.last_backup_at = now
        await self.backup_database()

    async def backup_database(self) -> None:
        db_path = Path(self.settings.database_path)
        if not db_path.exists() or db_path.stat().st_size <= 0:
            return

        try:
            if self.db.conn:
                await self.db.conn.execute("PRAGMA wal_checkpoint(FULL)")
                await self.db.conn.commit()
            doc = BufferedInputFile(db_path.read_bytes(), filename=db_path.name)
            backup_chat_id = self.backup_chat_id()
            sent = await self.bot.send_document(
                backup_chat_id,
                doc,
                caption=f"OgreScanBot database backup {int(time.time())}\nIncludes calls, PNL history, and leaderboard data.",
                disable_notification=True,
            )
            try:
                await self.bot.pin_chat_message(
                    backup_chat_id,
                    sent.message_id,
                    disable_notification=True,
                )
            except Exception:
                logging.exception("Backup was sent, but pinning failed. Give the bot pin permission or pin manually.")
            await self.send_leaderboard_backup_snapshot()
        except Exception:
            logging.exception("Database backup send failed.")

    async def send_leaderboard_backup_snapshot(self) -> None:
        try:
            sections = []
            for chat_id in await self.db.chat_ids(limit=10):
                traders = await self.db.top_traders(
                    chat_id,
                    since_ts=None,
                    min_hit_multiple=self.settings.min_multiple_for_hit,
                    limit=3,
                )
                calls = await self.db.leaderboard(chat_id, since_ts=None, limit=5)
                stats = await self.db.stats(chat_id, None, self.settings.min_multiple_for_hit)
                sections.append((chat_id, traders, calls, stats))

            text = format_leaderboard_backup_snapshot(int(time.time()), sections)
            await self.bot.send_message(
                self.backup_chat_id(),
                text,
                disable_notification=True,
                parse_mode=None,
            )
        except Exception:
            logging.exception("Leaderboard backup snapshot failed.")

    async def telegram_api(self, method: str, params: dict) -> dict:
        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/{method}"
        async with self.dex._session.post(url, data=params) as response:
            return await response.json(content_type=None)

    async def download_telegram_file(self, file_path: str) -> bytes | None:
        url = f"https://api.telegram.org/file/bot{self.settings.telegram_bot_token}/{file_path}"
        async with self.dex._session.get(url) as response:
            if response.status >= 400:
                return None
            data = await response.read()
        return data or None


def command_args(message: Message) -> list[str]:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return []
    return parts[1].split()


def command_name(text: str) -> str:
    first = (text or "").strip().split(maxsplit=1)[0].lower()
    first = first.removeprefix("/")
    return first.split("@", 1)[0]


def is_plain_card_command(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped or stripped.startswith("/"):
        return False
    return command_name(stripped) in {"pnl", "flex"}


def first_token_query_from_message(message: Message) -> str | None:
    sources = [message.text, message.caption]
    reply = getattr(message, "reply_to_message", None)
    if reply:
        sources.extend([reply.text, reply.caption])

    for source in sources:
        queries = extract_token_queries(source or "")
        if queries:
            return queries[0]
    return None


def leaderboard_keyboard(active_period: str) -> InlineKeyboardMarkup:
    periods = [("1d", "1D"), ("1w", "1W"), ("2w", "2W"), ("1m", "1M")]
    buttons = []
    for key, label in periods:
        text = f"• {label} •" if key == active_period else label
        buttons.append(InlineKeyboardButton(text=text, callback_data=f"lb:{key}"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def is_backup_command(text: str) -> bool:
    command = text.strip().split(maxsplit=1)[0].lower()
    return command in {
        "/setbackup",
        "/backuphere",
    } or command.startswith("/setbackup@") or command.startswith("/backuphere@")


def photo_caption(text: str, limit: int = 850) -> str:
    if len(text) <= limit:
        return text

    footer_start = text.find("<b>Powered by Ogres</b>")
    footer = text[footer_start - 2 :] if footer_start > 0 else ""
    body = text[: footer_start - 2] if footer_start > 0 else text

    removable_sections = ["🔎 <b>X Posts</b>", "🧾 <b>Info</b>"]
    for section in removable_sections:
        body = remove_section(body, section)
        candidate = f"{body.rstrip()}{footer}"
        if len(candidate) <= limit:
            return candidate

    lines: list[str] = []
    for line in body.splitlines():
        candidate = "\n".join(lines + [line]).rstrip() + footer
        if len(candidate) > limit:
            break
        lines.append(line)
    if lines:
        return "\n".join(lines).rstrip() + footer
    return strip_html(text)[:limit]


def remove_section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return text
    end = text.find("\n\n", start)
    if end < 0:
        return text[:start].rstrip()
    return (text[:start] + text[end + 2 :]).strip()


def unique_urls(urls: list[str | None]) -> list[str]:
    seen: set[str] = set()
    clean: list[str] = []
    for url in urls:
        if not url:
            continue
        value = str(url).strip()
        if value and value not in seen:
            clean.append(value)
            seen.add(value)
    return clean


def safe_scan_caption(token, call) -> str:
    cap = call.initial_cap if call else None
    peak = call.peak_cap if call else None
    best = call.peak_multiple if call else None
    current = (call.last_cap / call.initial_cap) if call and call.initial_cap else None
    caller = call.caller_name if call else "unknown"
    lines = [
        "OgreScanBot",
        f"{token.name} (${token.symbol})",
        token.address,
        f"#SOL | {token.dex_id}",
        "",
        "Stats",
        f"USD: {token.price_usd or 'n/a'}",
        f"MC: {plain_money(token.market_cap)}",
        f"FDV: {plain_money(token.fdv)}",
        f"Vol: {plain_money(token.volume_h24)}",
        f"LP: {plain_money(token.liquidity_usd)}",
        f"ATH: {plain_money(peak)} ({best:.2f}x)" if best else "ATH: n/a",
        "",
        f"Caller: {caller}",
        f"Called at: {plain_money(cap)}",
        f"Call to ATH: {best:.2f}x" if best is not None else "Call to ATH: n/a",
        f"Current: {current:.2f}x" if current is not None else "Current: n/a",
        "",
        "Powered by Ogres",
        "Telegram: https://t.me/ogrecoinonsol",
        "Website: https://ogremode.com/",
        "Twitter: https://twitter.com/i/communities/1930265213917425858",
    ]
    return "\n".join(lines)[:850]


def pnl_result_line(call, current_x: float) -> str:
    if call.peak_multiple > 1.0001:
        peak_pct = (call.peak_multiple - 1.0) * 100
        current_pct = (current_x - 1.0) * 100
        return (
            f"Call to ATH <b>{call.peak_multiple:.2f}x</b> "
            f"(<b>+{peak_pct:.0f}%</b>) | Current <b>{current_x:.2f}x</b> ({current_pct:+.0f}%)"
        )
    current_pct = (current_x - 1.0) * 100
    return f"Current <b>{current_x:.2f}x</b> (<b>{current_pct:+.0f}%</b>) | ATH <b>{call.peak_multiple:.2f}x</b>"


def plain_money(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:.2f}"


def strip_html(text: str) -> str:
    return (
        text.replace("<b>", "")
        .replace("</b>", "")
        .replace("<code>", "")
        .replace("</code>", "")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )


def normalize_image_bytes(data: bytes) -> bytes | None:
    try:
        image = Image.open(BytesIO(data))
        image.thumbnail((1280, 1280))
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        output = BytesIO()
        image.save(output, format="JPEG", quality=88, optimize=True)
        return output.getvalue()
    except (OSError, UnidentifiedImageError):
        return None


async def run_polling(settings: Settings) -> None:
    logging.basicConfig(level=logging.INFO)
    app = OgreScanApp(settings)
    await app.start()


async def create_webhook_app(settings: Settings) -> web.Application:
    logging.basicConfig(level=logging.INFO)
    app = OgreScanApp(settings)
    return app.build_webhook_app()


def main() -> None:
    settings = load_settings()
    if settings.run_mode == "webhook":
        web.run_app(create_webhook_app(settings), host=settings.host, port=settings.port)
    else:
        asyncio.run(run_polling(settings))
