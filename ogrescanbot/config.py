from dataclasses import dataclass
import os

from dotenv import load_dotenv


DEFAULT_TICKER_ALIASES = {
    "OGRE": "5RAZMWd9RiKfodLPQ73cFk4CMoJzTUsATUoRdDThpump",
}


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    bot_name: str
    database_path: str
    min_multiple_for_hit: float
    enable_rugcheck: bool
    enable_pump_metadata: bool
    enable_geckoterminal_ath: bool
    enable_solana_rpc: bool
    solana_rpc_url: str
    enable_solana_holder_count: bool
    run_mode: str
    webhook_url: str
    webhook_path: str
    host: str
    port: int
    backup_chat_id: str
    backup_chat_id_file: str
    backup_interval_seconds: int
    restore_backup_on_start: bool
    call_update_interval_seconds: int
    call_update_limit: int
    keep_alive_url: str
    keep_alive_interval_seconds: int
    ticker_aliases: dict[str, str]


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing. Copy .env.example to .env and add your bot token.")

    webhook_url = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
    webhook_path = os.getenv("WEBHOOK_PATH", "/telegram/webhook").strip() or "/telegram/webhook"
    keep_alive_url = os.getenv("KEEP_ALIVE_URL", "").strip().rstrip("/")
    if not keep_alive_url and webhook_url:
        keep_alive_url = f"{webhook_url}/healthz"

    return Settings(
        telegram_bot_token=token,
        bot_name=os.getenv("BOT_NAME", "OgreScanBot").strip() or "OgreScanBot",
        database_path=(
            os.getenv("DATABASE_URL", "").strip()
            or os.getenv("DATABASE_PATH", "ogrescanbot.sqlite3").strip()
            or "ogrescanbot.sqlite3"
        ),
        min_multiple_for_hit=float(os.getenv("MIN_MULTIPLE_FOR_HIT", "2.0")),
        enable_rugcheck=os.getenv("ENABLE_RUGCHECK", "true").lower() in {"1", "true", "yes", "on"},
        enable_pump_metadata=os.getenv("ENABLE_PUMP_METADATA", "true").lower() in {"1", "true", "yes", "on"},
        enable_geckoterminal_ath=os.getenv("ENABLE_GECKOTERMINAL_ATH", "true").lower()
        in {"1", "true", "yes", "on"},
        enable_solana_rpc=os.getenv("ENABLE_SOLANA_RPC", "true").lower() in {"1", "true", "yes", "on"},
        solana_rpc_url=os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com").strip()
        or "https://api.mainnet-beta.solana.com",
        enable_solana_holder_count=os.getenv("ENABLE_SOLANA_HOLDER_COUNT", "false").lower()
        in {"1", "true", "yes", "on"},
        run_mode=os.getenv("RUN_MODE", "polling").strip().lower() or "polling",
        webhook_url=webhook_url,
        webhook_path=webhook_path,
        host=os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        backup_chat_id=os.getenv("BACKUP_CHAT_ID", "").strip(),
        backup_chat_id_file=os.getenv("BACKUP_CHAT_ID_FILE", "backup_chat_id.txt").strip() or "backup_chat_id.txt",
        backup_interval_seconds=int(os.getenv("BACKUP_INTERVAL_SECONDS", "60")),
        restore_backup_on_start=os.getenv("RESTORE_BACKUP_ON_START", "true").lower() in {"1", "true", "yes", "on"},
        call_update_interval_seconds=int(os.getenv("CALL_UPDATE_INTERVAL_SECONDS", "180")),
        call_update_limit=int(os.getenv("CALL_UPDATE_LIMIT", "150")),
        keep_alive_url=keep_alive_url,
        keep_alive_interval_seconds=int(os.getenv("KEEP_ALIVE_INTERVAL_SECONDS", "600")),
        ticker_aliases=parse_ticker_aliases(os.getenv("TICKER_ALIASES", "")),
    )


def parse_ticker_aliases(value: str) -> dict[str, str]:
    aliases = dict(DEFAULT_TICKER_ALIASES)
    for item in value.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            continue
        ticker, address = item.split("=", 1)
        ticker = ticker.strip().upper().removeprefix("$")
        address = address.strip()
        if ticker and address:
            aliases[ticker] = address
    return aliases
