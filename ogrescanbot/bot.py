from __future__ import annotations

import asyncio
from dataclasses import replace
import html
import logging
from io import BytesIO
from pathlib import Path
import time
from urllib.parse import quote_plus

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup, Message
try:
    from aiogram.types import CopyTextButton
except ImportError:  # Older aiogram fallback: show the CA in an alert.
    CopyTextButton = None
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import ClientError, web
from PIL import Image, UnidentifiedImageError

from .config import OGRE_CA, OLD_BAD_OGRE_CA, Settings, load_settings
from .db import Database, TraderRecord, period_to_since
from .dexscreener import DexscreenerClient
from .extract import extract_ca_like_values, extract_solana_addresses, extract_token_queries, extract_x_post_links, is_solana_address
from .formatting import (
    format_help,
    format_leaderboard,
    format_leaderboard_backup_snapshot,
    format_cluster_report,
    format_paid_trend,
    format_scan,
    format_scan_caption,
    format_status,
    format_token_explainer,
    format_trader_stats,
    format_trader_passport,
    format_why_loss,
    format_x_post_embed,
    powered_by_footer,
    user_display_name,
)
from .geckoterminal import GeckoTerminalClient
from .images import build_pnl_card, build_scan_banner
from .jupiter import JupiterTokenClient
from .models import TokenScan, normalize_media_url
from .pumpfun import PumpFunClient
from .rugcheck import RugCheckClient
from .solana_rpc import SolanaRpcClient, merge_onchain_security


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
        self.gecko = GeckoTerminalClient() if settings.enable_geckoterminal_ath else None
        self.rug = RugCheckClient() if settings.enable_rugcheck else None
        self.pump = PumpFunClient() if settings.enable_pump_metadata else None
        self.jupiter = JupiterTokenClient(settings.jupiter_api_key) if settings.enable_jupiter_tokens else None
        self.solana = (
            SolanaRpcClient(settings.solana_rpc_url, settings.enable_solana_holder_count)
            if settings.enable_solana_rpc
            else None
        )
        self.last_backup_at = 0.0
        self.backup_task: asyncio.Task | None = None
        self.call_tracker_task: asyncio.Task | None = None
        self.keep_alive_task: asyncio.Task | None = None
        self.learned_backup_chat_id = ""
        self._register_handlers()

    async def start(self) -> None:
        await self.restore_database_backup()
        await self.db.open()
        await self.load_backup_chat_id_from_db()
        self.start_auto_backup_loop()
        self.start_call_tracker_loop()
        self.start_keep_alive_loop()
        try:
            await self.dp.start_polling(self.bot)
        finally:
            await self.stop_keep_alive_loop()
            await self.stop_call_tracker_loop()
            await self.stop_auto_backup_loop()
            await self.dex.close()
            if self.gecko:
                await self.gecko.close()
            if self.rug:
                await self.rug.close()
            if self.pump:
                await self.pump.close()
            if self.jupiter:
                await self.jupiter.close()
            if self.solana:
                await self.solana.close()
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
        return web.json_response(
            {
                "ok": True,
                "bot": self.settings.bot_name,
                "keep_alive": {
                    "enabled": bool(self.settings.keep_alive_url and self.settings.keep_alive_interval_seconds > 0),
                    "url": self.settings.keep_alive_url,
                    "interval_seconds": self.settings.keep_alive_interval_seconds,
                },
                "database": "postgres" if self.settings.database_path.startswith(("postgres://", "postgresql://")) else "sqlite",
            }
        )

    async def _on_webhook_startup(self, app: web.Application) -> None:
        await self.restore_database_backup()
        await self.db.open()
        await self.load_backup_chat_id_from_db()
        self.start_auto_backup_loop()
        self.start_call_tracker_loop()
        self.start_keep_alive_loop()
        webhook_endpoint = f"{self.settings.webhook_url}{self.settings.webhook_path}"
        await self.bot.set_webhook(
            webhook_endpoint,
            drop_pending_updates=True,
            allowed_updates=self.dp.resolve_used_update_types(),
        )
        logging.info("Webhook set to %s", webhook_endpoint)

    async def _on_webhook_cleanup(self, app: web.Application) -> None:
        await self.stop_keep_alive_loop()
        await self.stop_call_tracker_loop()
        await self.stop_auto_backup_loop()
        await self.dex.close()
        if self.gecko:
            await self.gecko.close()
        if self.rug:
            await self.rug.close()
        if self.pump:
            await self.pump.close()
        if self.jupiter:
            await self.jupiter.close()
        if self.solana:
            await self.solana.close()
        await self.db.close()
        await self.bot.session.close()

    def _register_handlers(self) -> None:
        self.dp.message.register(self.help_handler, Command("start", "help"))
        self.dp.message.register(self.set_backup_channel_command, lambda message: is_backup_command(message.text or ""))
        self.dp.message.register(self.scan_command, Command("scan", "call"))
        self.dp.message.register(self.smart_intel_command, Command("intel", "explain", "paid", "boosts", "cluster", "whylose"))
        self.dp.message.register(self.pnl_command, Command("pnl", "flex"))
        self.dp.message.register(self.pnl_command, lambda message: is_plain_card_command(message.text or ""))
        self.dp.message.register(self.stats_command, Command("stats"))
        self.dp.message.register(self.stats_command, lambda message: is_plain_stats_command(message.text or ""))
        self.dp.message.register(self.calls_command, Command("calls"))
        self.dp.message.register(self.calls_command, lambda message: is_plain_calls_command(message.text or ""))
        self.dp.message.register(self.leaderboard_command, Command("lb", "leaderboard"))
        self.dp.message.register(self.leaderboard_command, lambda message: is_plain_leaderboard_command(message.text or ""))
        self.dp.message.register(self.safe_scan_command, Command("safescan", "filters"))
        self.dp.callback_query.register(self.leaderboard_period_callback, F.data.startswith("lb:"))
        self.dp.callback_query.register(self.copy_ca_callback, F.data.startswith("copyca:"))
        self.dp.callback_query.register(self.scan_links_callback, F.data.startswith("scanmenu:"))
        self.dp.callback_query.register(self.trader_menu_callback, F.data.startswith("trader:"))
        self.dp.message.register(self.status_command, Command("status"))
        self.dp.message.register(self.status_command, lambda message: is_plain_status_command(message.text or ""))
        self.dp.message.register(self.backup_command, Command("backup"))
        self.dp.message.register(self.auto_scan_message, F.text)
        self.dp.channel_post.register(self.channel_post_text_handler, F.text)
        self.dp.my_chat_member.register(self.maybe_auto_set_backup_channel)

    async def help_handler(self, message: Message) -> None:
        await message.reply(format_help(self.settings.bot_name), disable_web_page_preview=True)

    async def scan_command(self, message: Message) -> None:
        query = first_token_query_from_message(message, include_reply=True)
        if not query:
            command = command_name(message.text or "") or "scan"
            await message.reply(f"Send /{command} followed by a Solana contract address, supported token link, or $ticker.")
            return
        await self.scan_and_reply(message, query)

    async def auto_scan_message(self, message: Message) -> None:
        text = message.text or ""
        if text.startswith("/"):
            return
        await self.maybe_embed_x_posts(message)
        query = first_token_query_from_message(message, include_reply=False)
        if query:
            await self.scan_and_reply(message, query, auto=True)

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

    async def smart_intel_command(self, message: Message) -> None:
        command = command_name(message.text or "")
        wallet, query = intel_query_from_message(message, include_reply=True, prefer_last=command == "whylose")
        if not query:
            await message.reply("Send /intel, /explain, /paid, /cluster, or /whylose followed by a Solana CA or $ticker.")
            return

        token = await self.resolve_token(query)
        if not token:
            await message.reply("I could not find that Solana token on Dexscreener or Pump.fun yet.")
            return

        rug = await self.rug.summary(token.address) if self.rug else None
        rug = await self.enrich_security_data(token, rug)
        call = await self.db.get_call(message.chat.id, token.address)
        first_snapshot, latest_snapshot = await self.db.token_snapshot_range(message.chat.id, token.address)
        view = {"whylose": "why", "boosts": "paid", "explain": "exs", "intel": "exs"}.get(command, command)
        text = await self.smart_intel_text(
            message.chat.id,
            token,
            rug,
            call,
            view,
            wallet=wallet,
            first_snapshot=first_snapshot,
            latest_snapshot=latest_snapshot,
        )
        await self.db.add_token_snapshot(message.chat.id, token, snapshot_holder_count(rug))
        await message.reply(
            text,
            reply_markup=smart_intel_keyboard(token.address, view),
            disable_web_page_preview=True,
        )

    async def pnl_command(self, message: Message) -> None:
        query = first_token_query_from_message(message, include_reply=True)
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

    async def stats_command(self, message: Message) -> None:
        user = passport_target_user(message)
        if not user:
            await message.reply("I need a Telegram user to show stats.")
            return

        calls = await self.db.caller_calls(message.chat.id, user.id, since_ts=None, limit=200)
        trader = trader_record_from_calls(user.id, user_display_name(user), calls, self.settings.min_multiple_for_hit)
        rank = await self.caller_rank(message.chat.id, user.id)
        await message.reply(
            format_trader_stats(
                user.id,
                user_display_name(user),
                trader,
                calls,
                rank,
                self.settings.min_multiple_for_hit,
            ),
            reply_markup=trader_menu_keyboard(user.id, "stats"),
            disable_web_page_preview=True,
        )

    async def calls_command(self, message: Message) -> None:
        user = passport_target_user(message)
        if not user:
            await message.reply("I need a Telegram user to show call history.")
            return

        args = command_args(message)
        requested_period = args[0] if args else "all"
        period, since_ts = period_to_since(requested_period)
        calls = await self.db.caller_calls(message.chat.id, user.id, since_ts=since_ts, limit=200)
        trader = trader_record_from_calls(user.id, user_display_name(user), calls, self.settings.min_multiple_for_hit)
        await message.reply(
            format_trader_passport(
                period,
                user.id,
                user_display_name(user),
                trader,
                calls,
                self.settings.min_multiple_for_hit,
            ),
            reply_markup=trader_menu_keyboard(user.id, "calls"),
            disable_web_page_preview=True,
        )

    async def trader_menu_callback(self, callback: CallbackQuery) -> None:
        if not callback.message or not callback.data:
            await callback.answer()
            return
        try:
            _prefix, view, user_id_text = callback.data.split(":", 2)
            user_id = int(user_id_text)
        except ValueError:
            await callback.answer()
            return

        try:
            text = await self.build_trader_menu_text(callback.message.chat.id, user_id, view)
            await callback.message.edit_text(
                text,
                reply_markup=trader_menu_keyboard(user_id, view),
                disable_web_page_preview=True,
            )
            await callback.answer()
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                await callback.answer()
                return
            logging.exception("Trader menu update failed.")
            await callback.answer("Could not update trader view right now.", show_alert=False)
        except Exception:
            logging.exception("Trader menu update failed.")
            await callback.answer("Could not update trader view right now.", show_alert=False)

    async def build_trader_menu_text(self, chat_id: int, user_id: int, view: str) -> str:
        calls = await self.db.caller_calls(chat_id, user_id, since_ts=None, limit=200)
        name = trader_name_from_calls(user_id, calls)
        trader = trader_record_from_calls(user_id, name, calls, self.settings.min_multiple_for_hit)
        if view == "calls":
            return format_trader_passport("all", user_id, name, trader, calls, self.settings.min_multiple_for_hit)
        if view == "leaderboard":
            _period, text, _markup = await self.build_leaderboard_message(chat_id, "1d")
            return text
        rank = await self.caller_rank(chat_id, user_id)
        return format_trader_stats(user_id, name, trader, calls, rank, self.settings.min_multiple_for_hit)

    async def caller_rank(self, chat_id: int, caller_user_id: int) -> int | None:
        traders = await self.db.top_traders(
            chat_id,
            since_ts=None,
            min_hit_multiple=self.settings.min_multiple_for_hit,
            limit=1000,
        )
        for index, trader in enumerate(traders, start=1):
            if trader.caller_user_id == caller_user_id:
                return index
        return None

    async def leaderboard_command(self, message: Message) -> None:
        args = command_args(message)
        period, text, markup = await self.build_leaderboard_message(message.chat.id, args[0] if args else "1d")
        await message.reply(text, reply_markup=markup, disable_web_page_preview=True)

    async def safe_scan_command(self, message: Message) -> None:
        args = [arg.lower() for arg in command_args(message)]
        key = strict_filter_setting_key(message.chat.id)
        if args and args[0] in {"on", "true", "strict", "enable", "enabled"}:
            await self.db.set_setting(key, "on")
            await message.reply("SafeScan is on. It will help rank duplicate tickers and log warnings, but found CA/$ticker scans will still post.")
            return
        if args and args[0] in {"off", "false", "loose", "disable", "disabled"}:
            await self.db.set_setting(key, "off")
            await message.reply("SafeScan is off for this chat. I will still post found CA/$ticker scans and use basic ticker ranking.")
            return
        enabled = await self.strict_filter_enabled(message.chat.id)
        await message.reply(
            f"SafeScan is {'on' if enabled else 'off'}.\n\n"
            "Found CA/$ticker scans always post. SafeScan only helps pick cleaner duplicate ticker matches and keeps risk warnings visible."
        )

    async def status_command(self, message: Message) -> None:
        stats = await self.db.stats(message.chat.id, None, self.settings.min_multiple_for_hit)
        await message.reply(
            format_status(self.settings, self.backup_chat_id(), stats),
            disable_web_page_preview=True,
        )

    async def leaderboard_period_callback(self, callback: CallbackQuery) -> None:
        if not callback.message or not callback.data:
            await callback.answer()
            return
        requested = callback.data.split(":", 1)[1]
        _period, text, markup = await self.build_leaderboard_message(callback.message.chat.id, requested)
        try:
            await callback.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
            await callback.answer()
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                await callback.answer()
                return
            logging.exception("Leaderboard period update failed.")
            await callback.answer("Could not update leaderboard right now.", show_alert=False)
        except Exception:
            logging.exception("Leaderboard period update failed.")
            await callback.answer("Could not update leaderboard right now.", show_alert=False)

    async def copy_ca_callback(self, callback: CallbackQuery) -> None:
        if not callback.data:
            await callback.answer()
            return
        address = callback.data.split(":", 1)[1]
        await callback.answer(f"CA:\n{address}", show_alert=True)

    async def scan_links_callback(self, callback: CallbackQuery) -> None:
        if not callback.message or not callback.data:
            await callback.answer()
            return

        try:
            _prefix, menu, address = callback.data.split(":", 2)
        except ValueError:
            await callback.answer()
            return
        include_ath = menu in {"exs", "exd", "exr", "exw", "exo", "paid", "cluster", "why", "scan"}
        token = await self.resolve_token(address, include_paid=True, include_ath=include_ath)
        if not token:
            await callback.answer("Could not refresh those links right now.", show_alert=False)
            return

        needs_rug = menu in {"security", "exs", "exd", "exr", "exw", "exo", "paid", "cluster", "why", "scan"}
        rug = await self.rug.summary(token.address) if self.rug and needs_rug else None
        rug = await self.enrich_security_data(token, rug) if needs_rug else rug
        if menu in {"exs", "exd", "exr", "exw", "exo", "paid", "cluster", "why", "scan"}:
            call = await self.db.get_call(callback.message.chat.id, token.address)
            first_snapshot, latest_snapshot = await self.db.token_snapshot_range(callback.message.chat.id, token.address)
            if menu == "scan":
                caption = photo_caption(format_scan_caption(token, call, False, rug), limit=1000)
            else:
                caption = photo_caption(
                    await self.smart_intel_text(
                        callback.message.chat.id,
                        token,
                        rug,
                        call,
                        menu,
                        first_snapshot=first_snapshot,
                        latest_snapshot=latest_snapshot,
                    ),
                    limit=1000,
                )
                await self.db.add_token_snapshot(callback.message.chat.id, token, snapshot_holder_count(rug))
            markup = scan_links_keyboard(token, rug, menu=menu if menu != "scan" else "main")
            try:
                if getattr(callback.message, "photo", None):
                    await callback.message.edit_caption(caption=caption, reply_markup=markup)
                else:
                    await callback.message.edit_text(
                        caption,
                        reply_markup=markup,
                        disable_web_page_preview=True,
                    )
                await callback.answer()
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc).lower():
                    await callback.answer()
                    return
                logging.exception("Scan explanation update failed.")
                await callback.answer("Could not update the scan right now.", show_alert=False)
            except Exception:
                logging.exception("Scan explanation update failed.")
                await callback.answer("Could not update the scan right now.", show_alert=False)
            return

        markup = scan_links_keyboard(token, rug, menu=menu)
        try:
            await callback.message.edit_reply_markup(reply_markup=markup)
            await callback.answer()
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                await callback.answer()
                return
            logging.exception("Scan link menu update failed.")
            await callback.answer("Could not update links right now.", show_alert=False)
        except Exception:
            logging.exception("Scan link menu update failed.")
            await callback.answer("Could not update links right now.", show_alert=False)

    async def smart_intel_text(
        self,
        chat_id: int,
        token,
        rug,
        call,
        view: str,
        wallet: str | None = None,
        first_snapshot=None,
        latest_snapshot=None,
    ) -> str:
        mode_map = {
            "intel": "simple",
            "explain": "simple",
            "exs": "simple",
            "exd": "simple",
            "exr": "risk",
            "exw": "whale",
            "exo": "owner",
        }
        if view in mode_map:
            return format_token_explainer(token, rug, call, mode=mode_map[view])
        if view in {"paid", "boosts"}:
            return format_paid_trend(token, rug, first_snapshot, latest_snapshot)
        if view == "cluster":
            return format_cluster_report(token, rug)
        if view == "why":
            return format_why_loss(token, call, wallet=wallet)
        return format_token_explainer(token, rug, call)

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

    async def scan_and_reply(self, message: Message, query: str, auto: bool = False) -> None:
        await message.bot.send_chat_action(message.chat.id, "typing")
        token = await self.resolve_token(query)
        if not token:
            fallback_address = first_ca_like_from_message(message) or ca_like_query(query)
            if fallback_address:
                logging.info("Using CA fallback scan for unresolved query %s", fallback_address)
                token = await self.finalize_resolved_token(
                    fallback_token_scan(fallback_address),
                    include_paid=True,
                    include_ath=True,
                )
            else:
                await message.reply("I could not find that Solana token on Dexscreener or Pump.fun yet.")
                return

        rug = await self.rug.summary(token.address) if self.rug else None
        rug = await self.enrich_security_data(token, rug)
        rejection = strict_scan_rejection(token, rug, auto=auto)
        if rejection and await self.strict_filter_enabled(message.chat.id):
            logging.info("SafeScan warning for %s: %s", token.address, rejection)

        user = message.from_user
        caller_id = user.id if user else 0
        caller_name = user_display_name(user) if user else "unknown"
        try:
            call, is_new_call = await self.db.upsert_call(message.chat.id, token, caller_id, caller_name)
            await self.maybe_backup_database()
        except ValueError:
            call, is_new_call = None, False
        await self.db.add_token_snapshot(message.chat.id, token, snapshot_holder_count(rug))
        scan_text = photo_caption(format_scan_caption(token, call, is_new_call, rug), limit=1000)
        banner = await self.build_scan_photo(token)
        links = scan_links_keyboard(token, rug)
        try:
            await message.reply_photo(banner, caption=scan_text, reply_markup=links)
        except Exception:
            logging.exception("Full scan photo send failed; retrying with safe caption.")
            safe_caption = safe_scan_caption(token, call)
            try:
                await message.reply_photo(banner, caption=safe_caption, parse_mode=None, reply_markup=links)
            except Exception:
                logging.exception("Safe scan photo send failed; falling back to text reply.")
                await message.reply(safe_caption, parse_mode=None, reply_markup=links, disable_web_page_preview=True)

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

    async def resolve_token(self, query: str, include_paid: bool = True, include_ath: bool = True):
        query = self.resolve_ticker_alias(query)
        if is_solana_address(query):
            return await self.resolve_address_token(query, include_paid=include_paid, include_ath=include_ath, allow_fallback=True)

        token = await self.dex.scan_solana_token(query)
        if token:
            return await self.finalize_resolved_token(token, include_paid=include_paid, include_ath=include_ath)

        if self.jupiter:
            mint = await self.jupiter.best_token_mint(query)
            if mint:
                token = await self.resolve_address_token(mint, include_paid=include_paid, include_ath=include_ath, allow_fallback=False)
                if token:
                    return token

        if self.pump:
            pump_mint = await self.pump.best_token_mint_by_ticker(query)
            if pump_mint:
                token = await self.resolve_address_token(
                    pump_mint,
                    include_paid=include_paid,
                    include_ath=include_ath,
                    allow_fallback=False,
                )
                if token:
                    return token
        return None

    async def resolve_address_token(
        self,
        address: str,
        include_paid: bool = True,
        include_ath: bool = True,
        allow_fallback: bool = True,
    ):
        try:
            token = await self.dex.scan_solana_token(address)
        except Exception:
            logging.exception("Dexscreener CA lookup failed for %s", address)
            token = None
        if token:
            return await self.finalize_resolved_token(token, include_paid=include_paid, include_ath=include_ath)

        if self.pump:
            try:
                pump_token = await self.pump.scan_token(address)
            except Exception:
                logging.exception("Pump.fun CA lookup failed for %s", address)
                pump_token = None
            if pump_token:
                return await self.finalize_resolved_token(pump_token, include_paid=include_paid, include_ath=include_ath)

        if self.jupiter:
            try:
                jupiter_data = await self.jupiter.token_by_mint(address)
            except Exception:
                logging.exception("Jupiter CA lookup failed for %s", address)
                jupiter_data = None
            if jupiter_data:
                token = jupiter_token_scan(address, jupiter_data)
                return await self.finalize_resolved_token(token, include_paid=include_paid, include_ath=include_ath)

        if allow_fallback:
            fallback = fallback_token_scan(address)
            return await self.finalize_resolved_token(fallback, include_paid=include_paid, include_ath=include_ath)
        return None

    async def finalize_resolved_token(self, token, include_paid: bool = True, include_ath: bool = True):
        if token and self.pump:
            try:
                token = token.with_pump_metadata(await self.pump.metadata(token.address))
            except Exception:
                logging.exception("Pump metadata enrichment failed for %s", token.address)
        if include_ath:
            token = await self.enrich_market_data(token)
        return await self.enrich_dex_paid(token) if include_paid else token

    async def resolve_scan_query(self, query: str) -> str:
        resolved = self.resolve_ticker_alias(query)
        if is_solana_address(resolved):
            return resolved
        return resolved

    async def enrich_market_data(self, token):
        if self.gecko:
            try:
                token = await self.gecko.enrich_ath(token)
            except Exception:
                logging.exception("GeckoTerminal enrichment failed for %s", token.address)
        if self.solana:
            try:
                token = await self.solana.enrich_token_supply(token)
            except Exception:
                logging.exception("Solana RPC supply enrichment failed for %s", token.address)
        return token

    async def enrich_dex_paid(self, token):
        try:
            paid = await self.dex.token_orders_paid(token.chain_id or "solana", token.address)
        except Exception:
            logging.exception("Dex paid enrichment failed for %s", token.address)
            return token
        if paid is None:
            return token
        return replace(token, dex_paid=bool(token.dex_paid or paid))

    async def enrich_security_data(self, token, rug):
        if not self.solana:
            return rug
        onchain = await self.solana.security_summary(token.address)
        return merge_onchain_security(rug, onchain)

    async def strict_filter_enabled(self, chat_id: int) -> bool:
        value = await self.db.get_setting(strict_filter_setting_key(chat_id))
        if value is None:
            return self.settings.strict_auto_scan_filter
        return value.lower() in {"1", "true", "yes", "on", "strict", "enabled"}

    def resolve_ticker_alias(self, query: str) -> str:
        clean = str(query or "").strip()
        if clean == OLD_BAD_OGRE_CA:
            return OGRE_CA
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
                token = await self.resolve_token(record.token_address, include_paid=False, include_ath=False)
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

    def start_keep_alive_loop(self) -> None:
        if self.keep_alive_task or not self.settings.keep_alive_url:
            return
        if self.settings.keep_alive_interval_seconds <= 0:
            return
        logging.info(
            "Keep-alive enabled: pinging %s every %s seconds.",
            self.settings.keep_alive_url,
            max(60, self.settings.keep_alive_interval_seconds),
        )
        self.keep_alive_task = asyncio.create_task(self.keep_alive_loop())

    async def stop_keep_alive_loop(self) -> None:
        if not self.keep_alive_task:
            return
        self.keep_alive_task.cancel()
        try:
            await self.keep_alive_task
        except asyncio.CancelledError:
            pass
        self.keep_alive_task = None

    async def keep_alive_loop(self) -> None:
        await asyncio.sleep(30)
        while True:
            await self.ping_keep_alive()
            await asyncio.sleep(max(60, self.settings.keep_alive_interval_seconds))

    async def ping_keep_alive(self) -> None:
        url = self.settings.keep_alive_url
        if not url:
            return
        try:
            async with self.dex._session.get(url, headers={"User-Agent": "OgreScanBot-KeepAlive/1.0"}) as response:
                await response.read()
                logging.info("Keep-alive ping %s -> %s", url, response.status)
        except Exception:
            logging.exception("Keep-alive ping failed for %s", url)

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


def is_plain_stats_command(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped or stripped.startswith("/"):
        return False
    return command_name(stripped) == "stats"


def is_plain_calls_command(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped or stripped.startswith("/"):
        return False
    return command_name(stripped) == "calls"


def is_plain_leaderboard_command(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped or stripped.startswith("/"):
        return False
    return command_name(stripped) in {"lb", "leaderboard"}


def is_plain_status_command(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped or stripped.startswith("/"):
        return False
    return command_name(stripped) == "status"


def passport_target_user(message: Message):
    reply = getattr(message, "reply_to_message", None)
    if reply and reply.from_user:
        return reply.from_user
    return message.from_user


def trader_record_from_calls(
    caller_user_id: int,
    caller_name: str,
    calls,
    min_hit_multiple: float,
) -> TraderRecord | None:
    if not calls:
        return None
    multiples = [call.peak_multiple for call in calls]
    hits = [value for value in multiples if value >= min_hit_multiple]
    return TraderRecord(
        caller_user_id=caller_user_id,
        caller_name=caller_name,
        total_calls=len(calls),
        best_multiple=max(multiples),
        avg_multiple=sum(multiples) / len(multiples),
        hits=len(hits),
    )


def trader_name_from_calls(user_id: int, calls) -> str:
    if calls:
        return calls[0].caller_name
    return str(user_id)


def snapshot_holder_count(rug) -> int | None:
    if not rug or getattr(rug, "holder_count_source", None) != "Solana RPC":
        return None
    return rug.holder_count


def strict_filter_setting_key(chat_id: int) -> str:
    return f"strict_scan_filter:{chat_id}"


def fallback_token_scan(address: str) -> TokenScan:
    return TokenScan(
        address=address,
        name="Unindexed Token",
        symbol="UNKNOWN",
        chain_id="solana",
        dex_id="unindexed",
        pair_address="",
        pair_url=f"https://dexscreener.com/solana/{address}",
        price_usd=None,
        market_cap=None,
        fdv=None,
        liquidity_usd=None,
        volume_h24=None,
        price_change_h1=None,
        price_change_h24=None,
        buys_h1=None,
        sells_h1=None,
        created_at_ms=None,
        image_url=None,
        header_url=None,
        description="Dexscreener and Pump.fun have not indexed this contract yet.",
        socials=[],
        websites=[],
        raw_pair={"fallback": True},
        dex_paid=None,
    )


def jupiter_token_scan(address: str, data: dict) -> TokenScan:
    name = str(data.get("name") or "Unknown").strip() or "Unknown"
    symbol = str(data.get("symbol") or "?").strip() or "?"
    cap = first_float(data, "mcap", "marketCap", "market_cap", "fdv")
    liquidity = first_float(data, "liquidity", "liquidityUsd", "liquidity_usd")
    volume = first_float(data, "daily_volume", "volume24h", "volume_24h")
    image = data.get("logoURI") or data.get("icon") or data.get("image")
    socials = []
    websites = []
    if data.get("twitter"):
        socials.append({"type": "twitter", "url": str(data.get("twitter"))})
    if data.get("telegram"):
        socials.append({"type": "telegram", "url": str(data.get("telegram"))})
    if data.get("website"):
        websites.append({"label": "Web", "url": str(data.get("website"))})
    return TokenScan(
        address=address,
        name=name,
        symbol=symbol,
        chain_id="solana",
        dex_id="jupiter",
        pair_address="",
        pair_url=f"https://dexscreener.com/solana/{address}",
        price_usd=None,
        market_cap=cap,
        fdv=cap,
        liquidity_usd=liquidity,
        volume_h24=volume,
        price_change_h1=None,
        price_change_h24=None,
        buys_h1=None,
        sells_h1=None,
        created_at_ms=None,
        image_url=normalize_media_url(str(image).strip()) if image else None,
        header_url=None,
        description=str(data.get("description") or "").strip() or None,
        socials=socials,
        websites=websites,
        raw_pair={"jupiter": data},
        dex_paid=None,
    )


def first_float(data: dict, *keys: str) -> float | None:
    for key in keys:
        try:
            value = data.get(key)
            if value is not None:
                parsed = float(value)
                if parsed > 0:
                    return parsed
        except (TypeError, ValueError):
            continue
    return None


def strict_scan_rejection(token, rug, auto: bool = False) -> str | None:
    liquidity = token.liquidity_usd
    cap = token.cap_for_tracking
    has_metadata = bool(token.socials or token.websites or token.description or token.image_url or token.header_url)
    if liquidity is None or liquidity <= 0:
        return "zero or missing liquidity"
    if cap is None or cap <= 0 or token.price_usd is None:
        return "missing core market data"
    if rug and getattr(rug, "freeze_authority", None):
        return "freeze authority appears active"
    if not has_metadata and liquidity < 250:
        return "near-zero liquidity with no metadata/socials"
    if auto and not has_metadata and liquidity < 1_000 and cap < 50_000 and token_is_new(token):
        return "near-empty new token with no metadata/socials"
    return None


def token_is_new(token) -> bool:
    if not token.created_at_ms:
        return False
    return (time.time() - (token.created_at_ms / 1000)) < 86_400


def first_token_query_from_message(message: Message, include_reply: bool = False) -> str | None:
    sources = [message.text, message.caption]
    reply = getattr(message, "reply_to_message", None)
    if include_reply and reply:
        sources.extend([reply.text, reply.caption])

    for source in sources:
        queries = extract_token_queries(source or "")
        if queries:
            return queries[0]
        ca_values = extract_ca_like_values(source or "")
        if ca_values:
            return ca_values[0]
    return None


def first_ca_like_from_message(message: Message) -> str | None:
    for source in (message.text, message.caption):
        ca_values = extract_ca_like_values(source or "")
        if ca_values:
            return ca_values[0]
    return None


def ca_like_query(query: str | None) -> str | None:
    ca_values = extract_ca_like_values(query or "")
    return ca_values[0] if ca_values else None


def intel_query_from_message(
    message: Message,
    include_reply: bool = False,
    prefer_last: bool = False,
) -> tuple[str | None, str | None]:
    sources = [message.text, message.caption]
    reply = getattr(message, "reply_to_message", None)
    if include_reply and reply:
        sources.extend([reply.text, reply.caption])

    for source in sources:
        text = source or ""
        queries = extract_token_queries(text)
        if not queries:
            continue
        addresses = extract_solana_addresses(text)
        wallet = addresses[0] if prefer_last and len(addresses) >= 2 else None
        query = queries[-1] if prefer_last else queries[0]
        return wallet, query
    return None, None


def leaderboard_keyboard(active_period: str) -> InlineKeyboardMarkup:
    periods = [("1d", "1D"), ("1w", "1W"), ("2w", "2W"), ("1m", "1M")]
    buttons = []
    for key, label in periods:
        text = f"[{label}]" if key == active_period else label
        buttons.append(InlineKeyboardButton(text=text, callback_data=f"lb:{key}"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def trader_menu_keyboard(user_id: int, active_view: str) -> InlineKeyboardMarkup:
    items = [
        ("stats", "Stats"),
        ("calls", "Calls"),
        ("leaderboard", "Group LB"),
    ]
    buttons = []
    for view, label in items:
        text = f"[{label}]" if view == active_view else label
        buttons.append(InlineKeyboardButton(text=text, callback_data=f"trader:{view}:{user_id}"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def smart_intel_keyboard(address: str, active_view: str = "exs") -> InlineKeyboardMarkup:
    rows = [
        [
            intel_button("Overview", "exs", address, active_view),
            intel_button("Risk Check", "exr", address, active_view),
        ],
        [
            intel_button("Whale View", "exw", address, active_view),
            intel_button("Project View", "exo", address, active_view),
        ],
        [
            intel_button("Paid Trend", "paid", address, active_view),
            intel_button("Wallet Map", "cluster", address, active_view),
        ],
        [
            intel_button("Loss Check", "why", address, active_view),
            InlineKeyboardButton(text="← Back to Scan", callback_data=scan_menu_data("scan", address)),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def intel_button(label: str, view: str, address: str, active_view: str) -> InlineKeyboardButton:
    text = f"[{label}]" if view == active_view else label
    return InlineKeyboardButton(text=text, callback_data=scan_menu_data(view, address))


def scan_links_keyboard(token, rug=None, menu: str = "main") -> InlineKeyboardMarkup:
    address = token.address
    pair = token.pair_address or token.address
    rows: list[list[InlineKeyboardButton]] = []
    terms = [address]
    if token.symbol and token.symbol != "?":
        terms.append(f"${token.symbol}")
    query = " OR ".join(terms)

    if menu == "charts":
        add_button_row(
            rows,
            [
                ("Dexscreener", token.pair_url or f"https://dexscreener.com/solana/{address}"),
                ("Dextools", f"https://www.dextools.io/app/en/solana/pair-explorer/{pair}"),
            ],
        )
        add_button_row(
            rows,
            [
                ("GeckoTerminal", f"https://www.geckoterminal.com/solana/pools/{pair}"),
                ("Birdeye", f"https://birdeye.so/token/{address}?chain=solana"),
            ],
        )
        add_button_row(rows, [("Solscan", f"https://solscan.io/token/{address}")])
        add_back_row(rows, address)
        return InlineKeyboardMarkup(inline_keyboard=rows)

    if menu == "x":
        add_button_row(
            rows,
            [
                ("Main X", first_token_social(token, {"twitter", "x"})),
                ("Recent", f"https://x.com/search?q={quote_plus(query)}&src=typed_query&f=live"),
            ],
        )
        add_button_row(rows, [("Big Mentions", f"https://x.com/search?q={quote_plus(query + ' min_faves:25')}&src=typed_query&f=top")])
        add_back_row(rows, address)
        return InlineKeyboardMarkup(inline_keyboard=rows)

    if menu == "security":
        add_button_row(
            rows,
            [
                ("RugCheck", f"https://rugcheck.xyz/tokens/{address}"),
                ("BubbleMaps", f"https://app.bubblemaps.io/sol/token/{address}"),
            ],
        )
        add_button_row(
            rows,
            [
                ("DEX Paid", token.pair_url or f"https://dexscreener.com/solana/{address}"),
                ("Dev Wallet", dev_wallet_url(rug)),
            ],
        )
        add_back_row(rows, address)
        return InlineKeyboardMarkup(inline_keyboard=rows)

    if menu == "trade":
        add_button_row(
            rows,
            [
                ("OgreTradeBot", "https://t.me/ogretradebot"),
                ("GMGN", f"https://gmgn.ai/sol/token/{address}"),
            ],
        )
        add_button_row(
            rows,
            [
                ("Pump.fun", f"https://pump.fun/coin/{address}"),
                ("Dexscreener", token.pair_url or f"https://dexscreener.com/solana/{address}"),
            ],
        )
        add_back_row(rows, address)
        return InlineKeyboardMarkup(inline_keyboard=rows)

    if menu == "socials":
        add_button_row(
            rows,
            [
                ("Telegram", first_token_social(token, {"telegram", "tg"})),
                ("Website", first_token_website(token)),
            ],
        )
        add_button_row(rows, [("X", first_token_social(token, {"twitter", "x"}))])
        add_back_row(rows, address)
        return InlineKeyboardMarkup(inline_keyboard=rows)

    if menu == "intel":
        return smart_intel_keyboard(address)

    if menu in {"exs", "exd", "exr", "exw", "exo", "paid", "cluster", "why"}:
        return smart_intel_keyboard(address, menu)

    rows.append(
        [
            copy_ca_button(address),
            InlineKeyboardButton(text="Dexscreener", url=token.pair_url or f"https://dexscreener.com/solana/{address}"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="Explain", callback_data=scan_menu_data("exs", address)),
            InlineKeyboardButton(text="Paid Trend", callback_data=scan_menu_data("paid", address)),
            InlineKeyboardButton(text="Wallet Map", callback_data=scan_menu_data("cluster", address)),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="Loss Check", callback_data=scan_menu_data("why", address)),
            InlineKeyboardButton(text="Charts", callback_data=scan_menu_data("charts", address)),
            InlineKeyboardButton(text="Trade", callback_data=scan_menu_data("trade", address)),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="Security", callback_data=scan_menu_data("security", address)),
            InlineKeyboardButton(text="X Links", callback_data=scan_menu_data("x", address)),
            InlineKeyboardButton(text="Socials", callback_data=scan_menu_data("socials", address)),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def scan_menu_data(menu: str, address: str) -> str:
    return f"scanmenu:{menu}:{address}"


def copy_ca_button(address: str) -> InlineKeyboardButton:
    if CopyTextButton is not None:
        return InlineKeyboardButton(text="Copy CA", copy_text=CopyTextButton(text=address))
    return InlineKeyboardButton(text="Show CA", callback_data=f"copyca:{address}")


def add_back_row(rows: list[list[InlineKeyboardButton]], address: str) -> None:
    rows.append([InlineKeyboardButton(text="← Back", callback_data=scan_menu_data("main", address))])


def dev_wallet_url(rug) -> str | None:
    wallet = getattr(rug, "dev_wallet", None) if rug else None
    if not wallet:
        return None
    return f"https://solscan.io/account/{wallet}"


def add_button_row(rows: list[list[InlineKeyboardButton]], items: list[tuple[str, str | None]]) -> None:
    buttons = [
        InlineKeyboardButton(text=label, url=url)
        for label, url in items
        if url and str(url).startswith(("http://", "https://"))
    ]
    if buttons:
        rows.append(buttons)


def first_token_social(token, labels: set[str]) -> str | None:
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


def first_token_website(token) -> str | None:
    for site in token.websites:
        url = str(site.get("url") or "").strip()
        if url:
            return url
    return None


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

    removable_sections = [
        "🔎 <b>Links</b>",
        "🔗 <b>Socials</b>",
        "🔎 <b>X Posts</b>",
        "🧾 <b>Info</b>",
    ]
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
        f"MC: {plain_money(token.market_cap or token.fdv)}",
        f"FDV: {plain_money(token.fdv)}",
        f"Vol: {plain_money(token.volume_h24)}",
        f"LP: {plain_money(token.liquidity_usd)}",
        f"ATH: {plain_money(peak)} ({best:.2f}x from call)" if best else (
            f"ATH: {plain_money(token.cap_for_tracking)} (current)" if token.cap_for_tracking else "ATH: n/a"
        ),
        "",
        f"CA: https://solscan.io/token/{token.address}",
        f"DEX: {token.pair_url or f'https://dexscreener.com/solana/{token.address}'}",
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
