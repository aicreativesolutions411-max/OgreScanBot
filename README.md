# OgreScanBot

Solana-first Telegram scanner bot using free/public data sources.

## What it does

- Auto-detects Solana contract addresses, supported token links, and `$ticker` mentions in group chats.
- Scans tokens with Dexscreener.
- Records the first caller for each token in each chat.
- Refreshes tracked calls from free APIs in the background so ATH/peak X keeps moving.
- Tracks each chat separately.
- Builds leaderboards based on the biggest X return from a single call.
- Generates call-based PNL/flex cards with `/pnl <ca>` or `/flex <ca>`.
- PNL/flex cards show big call-to-ATH X and percent when a call ran, or a red negative percent when it never moved above entry.
- Pulls token metadata images/descriptions from Dexscreener and falls back to Pump.fun public metadata when available.
- Shows DEX paid status and RugCheck dev-sold status when free endpoints return it.
- Scan captions use compact icon sections for token stats, socials, audit, calls, X links, and trading tools.
- Adds quick links for BubbleMaps, RugCheck, Pump.fun, GMGN, DEX, and X searches for high-engagement recent posts.
- Auto-embeds X/Twitter post links and credits the Telegram user who shared the link.

## Free data sources

- Telegram Bot API
- Dexscreener public API
- Optional RugCheck public report endpoint
- Optional Pump.fun public metadata endpoint
- Local SQLite database
- Optional external Postgres database through `DATABASE_URL` for Render deploys that must remember calls across updates
- Optional Telegram backup channel for SQLite persistence without Postgres

Dexscreener API reference: https://docs.dexscreener.com/api/reference
Dexscreener DEX paid check: https://api.dexscreener.com/orders/v1/solana/{mint}
RugCheck token report pattern: https://api.rugcheck.xyz/v1/tokens/{mint}/report
Pump.fun metadata pattern: https://frontend-api-v3.pump.fun/coins/{mint}

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
/scan <solana_ca_or_link_or_$ticker>
/pnl <solana_ca>
/flex <solana_ca>
/lb
/leaderboard
/lb 1d
/lb 1w
/lb 30d
/backup
/help
```

## Caller rules

- First person to paste a token address or supported link in a chat owns that call for that chat.
- First person to paste a `$ticker` that resolves to a Solana token also owns that call for that chat.
- Every chat has its own call table and leaderboard.
- Leaderboard ranking is by highest recorded multiplier on one call.
- A hit is any call that reaches `MIN_MULTIPLE_FOR_HIT`, default `2.0x`.

`CALL_UPDATE_INTERVAL_SECONDS` controls the live API refresh loop, default `180`. `CALL_UPDATE_LIMIT` controls how many older tracked calls are refreshed per loop, default `150`.

## Notes

This MVP uses call-based PNL, not wallet PNL. That means `/pnl` and `/flex` show "called at market cap vs ATH/peak market cap" instead of exact wallet profit. It keeps the bot free and avoids paid wallet-history APIs.

On Render, set `DATABASE_URL` to a free external Postgres connection string if you want calls and leaderboards to survive deploys. Render free web services use an ephemeral filesystem, so the local SQLite file can reset when the service restarts or redeploys.

## Easier backup without Postgres

Use a private Telegram backup channel:

1. Create a private Telegram channel named something like `OgreScan Backups`.
2. Add your bot as an admin.
3. Give it permission to post messages and pin messages.
4. Get the channel ID or use a public/private channel username if available.
5. You do not need to find the numeric channel ID manually. After deploy, post this inside the backup channel:

```text
/setbackup
```

The bot learns the channel ID from that channel post. If you already know the ID, you can still set it manually:

If Telegram inserts the bot username, `/setbackup@YourBotName` is fine too.

```text
BACKUP_CHAT_ID=-100xxxxxxxxxx
BACKUP_INTERVAL_SECONDS=60
RESTORE_BACKUP_ON_START=true
```

The bot sends the SQLite database to that channel and pins the latest backup. That database includes calls, PNL history, and leaderboard data. The bot also posts a readable leaderboard snapshot showing top callers and best trades. On restart/redeploy, it restores from the pinned backup if the local database file is missing.

Backups happen automatically on the configured interval and after call updates. Use `/backup` in Telegram to force a backup after setup.

Telegram private invite links like `https://t.me/+...` cannot be used directly as a Bot API destination. `/setbackup` is the easy way around that because the bot learns the hidden numeric channel ID from Telegram.
