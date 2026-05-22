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
- Supports `/call` as an explicit call/scan command when groups want a cleaner workflow than just pasting a CA.
- Builds leaderboards based on the biggest X return from a single call.
- Leaderboards use a compact tree-and-quote layout for top callers, group stats, and best trades.
- Leaderboard names link to the Telegram caller profile when Telegram gives the bot a user ID.
- Shows `/calls` history for a trader from that chat's tracked calls, hit rate, best calls, and badges.
- Shows `/stats` as a quick trader profile with rank, win rate, best/worst trade, favorite chain, and badges. Stats, Calls, and Group LB switch in-place with buttons.
- Generates matching call-based PNL/flex cards with `/pnl <ca>`, `/flex <ca>`, `pnl <ca>`, or `flex <ca>`.
- PNL/flex cards use text over the image with no stat boxes, showing a big green call-to-ATH X or a big red loss.
- Pulls token metadata images/descriptions from Dexscreener and falls back to Pump.fun public metadata when available.
- Uses Dexscreener pair fallbacks plus Pump.fun cap metadata when Dex does not return market cap/FDV on the selected pair.
- Shows DEX paid status and RugCheck dev-sold status when free endpoints return it.
- Verifies token supply and top-holder concentration directly through Solana RPC when enabled.
- Adds an Explain button on every scan for a quick human-readable token risk read using free scan and RugCheck data.
- Adds Smart Token Intelligence: explain modes, paid trend check, cautious wallet cluster read, and explain-my-loss views.
- Scan captions use compact icon sections for token stats, socials, audit, and calls, with categorized button menus for Smart Intel, charts, X links, security, socials, and trade tools. The trade menu includes OgreTradeBot.
- Auto-scan only reads the new message text/caption, so replying to an old CA does not trigger a scan unless the reply itself includes a `$ticker` or CA.
- Adds quick links for BubbleMaps, RugCheck, Pump.fun, GMGN, DEX, and X searches for high-engagement recent posts.
- Auto-embeds X/Twitter post links and credits the Telegram user who shared the link.
- `/status` shows backup, keep-alive, live refresh, and current chat tracking health.

## Free data sources

- Telegram Bot API
- Dexscreener public API
- Optional RugCheck public report endpoint
- Optional Pump.fun public metadata endpoint
- Optional GeckoTerminal public OHLCV endpoint for token ATH estimates
- Optional Solana RPC for on-chain token supply and top-holder concentration checks
- Local SQLite database
- Optional external Postgres database through `DATABASE_URL` for Render deploys that must remember calls across updates
- Optional Telegram backup channel for SQLite persistence without Postgres

Dexscreener API reference: https://docs.dexscreener.com/api/reference
Dexscreener DEX paid check: https://api.dexscreener.com/orders/v1/solana/{mint}
RugCheck token report pattern: https://api.rugcheck.xyz/v1/tokens/{mint}/report
Pump.fun metadata pattern: https://frontend-api-v3.pump.fun/coins/{mint}
GeckoTerminal OHLCV pattern: https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/ohlcv/hour
Solana RPC methods used: `getTokenSupply`, `getTokenLargestAccounts`, and optionally `getProgramAccounts`

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
/call <solana_ca_or_link_or_$ticker>
/intel <solana_ca_or_link_or_$ticker>
/explain <solana_ca_or_link_or_$ticker>
/paid <solana_ca_or_link_or_$ticker>
/boosts <solana_ca_or_link_or_$ticker>
/cluster <solana_ca_or_link_or_$ticker>
/whylose <wallet_optional> <solana_ca_or_link_or_$ticker>
/pnl <solana_ca>
/flex <solana_ca>
pnl <solana_ca>
flex <solana_ca>
/stats
/calls
/lb
/leaderboard
lb
leaderboard
/lb 1d
/lb 1w
/lb 2w
/lb 1m
/status
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

ATH shown in scans uses GeckoTerminal free OHLCV candles when a pool is available, then falls back to the highest cap the bot has tracked from that chat's call. Free APIs do not always expose a perfect lifetime ATH for every token, so the bot keeps refreshing call peaks in the background.

Supply and top-holder concentration use Solana RPC when `ENABLE_SOLANA_RPC=true`. The default public RPC is free but rate-limited. For best reliability, set `SOLANA_RPC_URL` to a free RPC endpoint from a provider such as Helius, QuickNode, Alchemy, or Triton. Exact holder count requires the heavier `ENABLE_SOLANA_HOLDER_COUNT=true`, and should only be used with a good RPC because many public endpoints block or throttle that call.

Smart Intel uses free data. Paid-trend impact improves after the bot has multiple snapshots for a token. Cluster checks use cautious wording and are not proof of wallet relationships. Explain-my-loss uses tracked calls/current market data unless a future wallet-history layer is added.

`TICKER_ALIASES` lets you force exact ticker matches before Dexscreener search. It defaults to:

```text
OGRE=5RAZMWd9RiKfodLPQ73cFk4CMoJzTUsATUoRdDThpump
```

Add more with commas, for example `OGRE=address,ABC=address2`.

## Notes

This MVP uses call-based PNL, not wallet PNL. That means `/pnl` and `/flex` show "called at market cap vs ATH/peak market cap" instead of exact wallet profit. It keeps the bot free and avoids paid wallet-history APIs.

`/stats` and `/calls` are call-based for now. They use the calls this bot has tracked in the current chat, not a verified wallet signature. A wallet-verified Trader Passport can be added later with a Telegram Mini App or signed-message flow.

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
