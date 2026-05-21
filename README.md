# OgreScanBot

Solana-first Telegram scanner bot using free/public data sources.

## What it does

- Auto-detects Solana contract addresses, supported token links, and `$ticker` mentions in group chats.
- Scans tokens with Dexscreener.
- Uses exact ticker aliases before search, so `$OGRE` resolves to the official OgreCoin contract.
- Records the first caller for each token in each chat.
- Refreshes tracked calls from free APIs in the background so ATH/peak X keeps moving.
- Pings its own `/healthz` endpoint when hosted with webhooks so free hosts are less likely to idle out.
- Tracks each chat separately.
- Builds leaderboards based on the biggest X return from a single call.
- Leaderboards use a compact tree-and-quote layout for top callers, group stats, and best trades.
- Generates matching call-based PNL/flex cards with `/pnl <ca>`, `/flex <ca>`, `pnl <ca>`, or `flex <ca>`.
- PNL/flex cards use text over the image with no stat boxes, showing a big green call-to-ATH X or a big red loss.
- Pulls token metadata images/descriptions from Dexscreener and falls back to Pump.fun public metadata when available.
- Uses Dexscreener pair fallbacks plus Pump.fun cap metadata when Dex does not return market cap/FDV on the selected pair.
- Shows DEX paid status and RugCheck dev-sold status when free endpoints return it.
- Scan captions use compact icon sections for token stats, socials, audit, calls, X links, and trading tools.
- Auto-scan only reads the new message text/caption, so replying to an old CA does not trigger a scan unless the reply itself includes a `$ticker` or CA.
- Adds quick links for BubbleMaps, RugCheck, Pump.fun, GMGN, DEX, and X searches for high-engagement recent posts.
- Auto-embeds X/Twitter post links and credits the Telegram user who shared the link.

## Free data sources

- Telegram Bot API
- Dexscreener public API
- Optional RugCheck public report endpoint
- Optional Pump.fun public metadata endpoint
- Optional GeckoTerminal public OHLCV endpoint for token ATH estimates
- Local SQLite database
- Optional external Postgres database through `DATABASE_URL` for Render deploys that must remember calls across updates
- Optional Telegram backup channel for SQLite persistence without Postgres

Dexscreener API reference: https://docs.dexscreener.com/api/reference
Dexscreener DEX paid check: https://api.dexscreener.com/orders/v1/solana/{mint}
RugCheck token report pattern: https://api.rugcheck.xyz/v1/tokens/{mint}/report
Pump.fun metadata pattern: https://frontend-api-v3.pump.fun/coins/{mint}
GeckoTerminal OHLCV pattern: https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/ohlcv/hour

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
pnl <solana_ca>
flex <solana_ca>
/lb
/leaderboard
/lb 1d
/lb 1w
/lb 2w
/lb 1m
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

`KEEP_ALIVE_INTERVAL_SECONDS` controls the self-ping loop, default `600`. When `WEBHOOK_URL` is set, the bot pings `WEBHOOK_URL/healthz` unless you set `KEEP_ALIVE_URL` yourself.

For Render, make sure these environment variables are set in the Render dashboard:

```text
RUN_MODE=webhook
WEBHOOK_URL=https://your-render-service.onrender.com
WEBHOOK_PATH=/telegram/webhook
KEEP_ALIVE_INTERVAL_SECONDS=600
```

Then open `https://your-render-service.onrender.com/healthz`. It should show `"keep_alive":{"enabled":true,...}` and `"interval_seconds":600`.

ATH shown in scans is the highest cap the bot has tracked from that chat's call. Dexscreener's free API does not always provide lifetime token ATH, so the bot uses live refreshes to keep the call peak updated.

`TICKER_ALIASES` lets you force exact ticker matches before Dexscreener search. It defaults to:

```text
OGRE=5RAZMWd9RiKfodLPQ73cFk4CMoJzTUsATUoRdDThpump
```

Add more with commas, for example `OGRE=address,ABC=address2`.

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
