from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    bot_name: str
    database_path: str
    min_multiple_for_hit: float
    enable_rugcheck: bool
    enable_pump_metadata: bool
    run_mode: str
    webhook_url: str
    webhook_path: str
    host: str
    port: int


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing. Copy .env.example to .env and add your bot token.")

    return Settings(
        telegram_bot_token=token,
        bot_name=os.getenv("BOT_NAME", "OgreScanBot").strip() or "OgreScanBot",
        database_path=os.getenv("DATABASE_PATH", "ogrescanbot.sqlite3").strip() or "ogrescanbot.sqlite3",
        min_multiple_for_hit=float(os.getenv("MIN_MULTIPLE_FOR_HIT", "2.0")),
        enable_rugcheck=os.getenv("ENABLE_RUGCHECK", "true").lower() in {"1", "true", "yes", "on"},
        enable_pump_metadata=os.getenv("ENABLE_PUMP_METADATA", "true").lower() in {"1", "true", "yes", "on"},
        run_mode=os.getenv("RUN_MODE", "polling").strip().lower() or "polling",
        webhook_url=os.getenv("WEBHOOK_URL", "").strip().rstrip("/"),
        webhook_path=os.getenv("WEBHOOK_PATH", "/telegram/webhook").strip() or "/telegram/webhook",
        host=os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
    )
