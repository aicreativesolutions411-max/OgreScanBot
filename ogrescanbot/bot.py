from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from .config import Settings, load_settings
from .db import Database, period_to_since
from .dexscreener import DexscreenerClient
from .extract import extract_token_queries
from .formatting import format_help, format_leaderboard, format_scan, powered_by_footer, user_display_name
from .images import build_pnl_card
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
        self._register_handlers()

    async def start(self) -> None:
        await self.db.open()
        try:
            await self.dp.start_polling(self.bot)
        finally:
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
        await self.db.open()
        webhook_endpoint = f"{self.settings.webhook_url}{self.settings.webhook_path}"
        await self.bot.set_webhook(webhook_endpoint, drop_pending_updates=True)
        logging.info("Webhook set to %s", webhook_endpoint)

    async def _on_webhook_cleanup(self, app: web.Application) -> None:
        await self.dex.close()
        if self.rug:
            await self.rug.close()
        if self.pump:
            await self.pump.close()
        await self.db.close()
        await self.bot.session.close()

    def _register_handlers(self) -> None:
        self.dp.message.register(self.help_handler, Command("start", "help"))
        self.dp.message.register(self.scan_command, Command("scan"))
        self.dp.message.register(self.pnl_command, Command("pnl", "flex"))
        self.dp.message.register(self.leaderboard_command, Command("lb", "leaderboard"))
        self.dp.message.register(self.auto_scan_message, F.text)

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
        query = first_token_query_from_message(message)
        if query:
            await self.scan_and_reply(message, query)

    async def pnl_command(self, message: Message) -> None:
        query = first_token_query_from_message(message)
        if not query:
            await message.reply("Send /pnl followed by a Solana contract address or $ticker.")
            return

        token = await self.dex.scan_solana_token(query)
        if not token:
            await message.reply("I could not find that Solana token on Dexscreener yet.")
            return
        if self.pump:
            token = token.with_pump_metadata(await self.pump.metadata(token.address))

        user = message.from_user
        if not user:
            await message.reply("I need a Telegram user to attach this card to.")
            return

        call, _ = await self.db.upsert_call(message.chat.id, token, user.id, user_display_name(user))
        card = build_pnl_card(token, call)
        photo = BufferedInputFile(card.getvalue(), filename=card.name)
        await message.reply_photo(
            photo,
            caption=f"{token.symbol} call card | {call.peak_multiple:.2f}x best{powered_by_footer()}",
        )

    async def leaderboard_command(self, message: Message) -> None:
        args = command_args(message)
        period, since_ts = period_to_since(args[0] if args else "1w")
        traders = await self.db.top_traders(
            message.chat.id,
            since_ts=since_ts,
            min_hit_multiple=self.settings.min_multiple_for_hit,
            limit=5,
        )
        calls = await self.db.leaderboard(message.chat.id, since_ts=since_ts, limit=10)
        stats = await self.db.stats(message.chat.id, since_ts, self.settings.min_multiple_for_hit)
        await message.reply(format_leaderboard(period, traders, calls, stats), disable_web_page_preview=True)

    async def scan_and_reply(self, message: Message, query: str) -> None:
        await message.bot.send_chat_action(message.chat.id, "typing")
        token = await self.dex.scan_solana_token(query)
        if not token:
            await message.reply("I could not find that Solana token on Dexscreener yet.")
            return
        if self.pump:
            token = token.with_pump_metadata(await self.pump.metadata(token.address))

        user = message.from_user
        caller_id = user.id if user else 0
        caller_name = user_display_name(user) if user else "unknown"
        try:
            call, is_new_call = await self.db.upsert_call(message.chat.id, token, caller_id, caller_name)
        except ValueError:
            call, is_new_call = None, False

        rug = await self.rug.summary(token.address) if self.rug else None
        scan_text = format_scan(token, call, is_new_call, rug)
        if token.image_url:
            try:
                await message.reply_photo(
                    token.image_url,
                    caption=photo_caption(scan_text),
                    show_caption_above_media=False,
                )
                return
            except Exception:
                logging.exception("Telegram rejected token image URL: %s", token.image_url)
        await message.reply(scan_text, disable_web_page_preview=True)


def command_args(message: Message) -> list[str]:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return []
    return parts[1].split()


def first_token_query_from_message(message: Message) -> str | None:
    queries = extract_token_queries(message.text or message.caption or "")
    return queries[0] if queries else None


def photo_caption(text: str, limit: int = 1000) -> str:
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

    remaining = limit - len(footer) - len("\n\n...")
    if remaining < 100:
        return text[:limit]
    return f"{body[:remaining].rstrip()}\n\n...{footer}"


def remove_section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return text
    end = text.find("\n\n", start)
    if end < 0:
        return text[:start].rstrip()
    return (text[:start] + text[end + 2 :]).strip()


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
