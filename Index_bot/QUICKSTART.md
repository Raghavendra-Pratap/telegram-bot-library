# Quick Start

Minimal path to a running bot. For full detail see [README.md](./README.md) and [HOW_TO_RUN.md](./HOW_TO_RUN.md).

## 1. Credentials

1. [@BotFather](https://t.me/BotFather) → `/newbot` → copy **BOT_TOKEN**
2. [@userinfobot](https://t.me/userinfobot) → copy your numeric **user ID**

## 2. Config

```bash
cd Index_bot
cp .env.example .env
# Edit: BOT_TOKEN, ADMIN_USER_IDS
```

## 3. Install & run

```bash
./run_all.sh
```

Or bot only: `./run_bot.sh`

## 4. Telegram

- Add bot as **admin** to channels you want to index
- Message the bot: `/start`, `/menu`
- Optional portal: `/portal` (set `PORTAL_PUBLIC_URL` in `.env` first)

## 5. Optional next steps

| Goal | Doc |
|------|-----|
| Termux phone server | [TERMUX_SETUP.md](./TERMUX_SETUP.md) |
| Upload courses in bulk | [UPLOAD_PIPELINE.md](./UPLOAD_PIPELINE.md) |
| Mac uploads + bot on phone | [DEPLOYMENT.md](./DEPLOYMENT.md) |
| Portal API | [API_DOCS.md](./API_DOCS.md) |
| Old channel history | [HOW_TO_RUN.md](./HOW_TO_RUN.md) → Historical ingest |

## Verify

```bash
python check_readiness.py
```
