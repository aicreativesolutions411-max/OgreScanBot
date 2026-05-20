# Free Hosting Plan

Goal: run OgreScanBot without paying monthly fees.

## Best free-first choice: Koyeb

Koyeb is the best fit for this bot right now because its free tier includes one free web service with 512MB RAM, 0.1 vCPU, and 2GB SSD in Frankfurt or Washington, D.C. That is enough for a small Telegram webhook bot using SQLite.

Use webhook mode:

```text
RUN_MODE=webhook
WEBHOOK_URL=https://your-koyeb-app-name.koyeb.app
WEBHOOK_PATH=/telegram/webhook
PORT=8080
```

Deploy steps:

1. Push this folder to a GitHub repo.
2. Create a free Koyeb account.
3. Create a new Web Service from the repo.
4. Choose Dockerfile deployment.
5. Add environment variables:

```text
TELEGRAM_BOT_TOKEN=your_botfather_token
RUN_MODE=webhook
WEBHOOK_URL=https://your-koyeb-app-name.koyeb.app
WEBHOOK_PATH=/telegram/webhook
BOT_NAME=OgreScanBot
DATABASE_PATH=ogrescanbot.sqlite3
ENABLE_RUGCHECK=true
ENABLE_PUMP_METADATA=true
MIN_MULTIPLE_FOR_HIT=2.0
CALL_UPDATE_INTERVAL_SECONDS=180
CALL_UPDATE_LIMIT=150
TICKER_ALIASES=OGRE=5RAZMWd9RiKfodLPQ73cFk4CMoJzTUsATUoRdDThpump
```

6. Deploy.
7. Open `https://your-koyeb-app-name.koyeb.app/healthz`. It should return `{"ok": true, ...}`.

## Backup free choice: Render

Render has free web services, but they spin down after 15 minutes without inbound traffic. Telegram webhook bots can be delayed when the service wakes up, so this is okay for testing but worse for active groups.

Use the included `render.yaml`.

Environment variables:

```text
TELEGRAM_BOT_TOKEN=your_botfather_token
RUN_MODE=webhook
WEBHOOK_URL=https://your-render-service.onrender.com
WEBHOOK_PATH=/telegram/webhook
DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require
```

Do not hardcode the Render port in `bot.py`. Render provides a `PORT` environment variable automatically, and OgreScanBot already reads it through `settings.port`.

Important: Render free web services should not be treated like production. They can sleep, and local SQLite files will not survive redeploys because the filesystem is ephemeral. Use `DATABASE_URL` with a free external Postgres database if you want calls, PNL, and leaderboards to persist.

Free database options:

- Supabase free project: create a Postgres database and use the connection string with `sslmode=require`.
- Neon free project: create a Postgres database and use the connection string with `sslmode=require`.

Easier non-Postgres option:

1. Create a private Telegram channel for backups.
2. Add the bot as an admin.
3. Allow it to post and pin messages.
4. After deploy, post this in the backup channel:

```text
/setbackup
```

That lets the bot learn the hidden channel ID automatically. If you already know the channel ID, you can set:

If Telegram inserts the bot username, `/setbackup@YourBotName` works too.

```text
BACKUP_CHAT_ID=-100xxxxxxxxxx
BACKUP_INTERVAL_SECONDS=60
RESTORE_BACKUP_ON_START=true
```

The bot will automatically send its SQLite file to that channel and pin the newest backup. That file includes calls, PNL history, and leaderboard data. It also posts a readable leaderboard snapshot. After a redeploy, it restores from the pinned backup. Use `/backup` to force a backup any time.

Telegram private invite links like `https://t.me/+...` cannot be used directly as a Bot API destination, so `/setbackup` is the no-ID setup path.

## Not recommended for this goal

- Fly.io: current docs say there is no general free account/free tier for new users, only legacy allowances or short trials.
- PythonAnywhere free: good for learning Python, but always-on/background tasks are not a good fit for a 24/7 Telegram bot on new free accounts.
- Railway: useful platform, but not a reliable zero-cost default for this goal.

## Local fallback

The most reliable zero-dollar option is still running it on your own machine:

```bash
pip install -r requirements.txt
copy .env.example .env
python -m ogrescanbot
```

Set `RUN_MODE=polling` locally.
