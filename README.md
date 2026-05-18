# OgreScanBot

Solana-first Telegram scanner bot using free/public data sources.

## What it does

- Auto-detects Solana contract addresses in group chats.
- Scans tokens with Dexscreener.
- Records the first caller for each token in each chat.
- Tracks each chat separately.
- Builds leaderboards based on the biggest X return from a single call.
- Generates call-based PNL/flex cards with `/pnl <ca>` or `/flex <ca>`.

## Free data sources

- Telegram Bot API
- Dexscreener public API
- Optional RugCheck public report endpoint
- Local SQLite database

Dexscreener API reference: https://docs.dexscreener.com/api/reference
RugCheck token report pattern: https://api.rugcheck.xyz/v1/tokens/{mint}/report

## Setup

1. Create a bot with Telegram's `@BotFather`.
2. Copy `.env.example` to `.env`.
3. Put your Telegram bot token in `.env`.
4. Install dependencies:

```bash
pip install -r requirements.txt
```

5. Run:

```bash
python -m ogrescanbot
```

## Commands

```text
/scan <solana_ca_or_link>
/pnl <solana_ca>
/flex <solana_ca>
/lb
/lb 1d
/lb 1w
/lb 30d
/help
```

## Caller rules

- First person to paste a token address or supported link in a chat owns that call for that chat.
- Every chat has its own call table and leaderboard.
- Leaderboard ranking is by highest recorded multiplier on one call.
- A hit is any call that reaches `MIN_MULTIPLE_FOR_HIT`, default `2.0x`.

## Notes

This MVP uses call-based PNL, not wallet PNL. That means `/pnl` shows "called at market cap vs current market cap" instead of exact wallet profit. It keeps the bot free and avoids paid wallet-history APIs.
