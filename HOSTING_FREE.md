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
```

Do not hardcode the Render port in `bot.py`. Render provides a `PORT` environment variable automatically, and OgreScanBot already reads it through `settings.port`.

Important: Render free web services should not be treated like production. They can sleep, and local SQLite files may not survive redeploys the way you expect.

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
