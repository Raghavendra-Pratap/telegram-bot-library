# Local Server Guide (Recommended)

This bot is intended to run on your **local server**. The steps below assume you are running from this repo and using the shared virtual environment at the repo root.

## 1) Install dependencies (shared)

```bash
# From repo root
./scripts/setup_env.sh
./scripts/install_deps.sh name-bot
source .venv/bin/activate
```

## 2) Configure environment

```bash
cd name-bot
cp env_template.txt .env
```

Edit `.env` and set at least:

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

## 3) Run the bot

```bash
python bot.py
```

## 4) Health check endpoint (local)

The bot can run a lightweight HTTP health check server. It is useful for:
- Local monitoring (e.g., uptime checks on your LAN)
- Keeping the bot active if you enable auto-shutdown

Default endpoint:

```
http://localhost:8080/
```

You can change the port using `HTTP_SERVER_PORT` in `.env`.

## 5) Auto-shutdown (optional)

If `ENABLE_AUTO_SHUTDOWN=true`, the bot stops itself after `IDLE_TIMEOUT_MINUTES` of inactivity.  
Set `IDLE_TIMEOUT_MINUTES=0` to disable auto-shutdown and keep the bot running continuously.

## 6) Access from other devices (optional)

If you want to access the health check endpoint from another device on your LAN:

1. Find your local IP (e.g., `192.168.1.10`)
2. Open `http://<your-local-ip>:8080/` from another device

Port forwarding is only needed if you want access from outside your home network.
