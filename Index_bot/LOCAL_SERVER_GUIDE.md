# Local Server Guide (Index Bot)

Same dependency model as **name-bot**: shared repo-root `.venv`, `scripts/install_deps.sh`, and optional **bot launcher** auto-install on start.

## 1) Install dependencies (shared, from repo root)

```bash
cd /path/to/Telegram_Bot_Library
./scripts/setup_env.sh
./scripts/install_deps.sh index
source .venv/bin/activate
```

Missing packages are installed automatically when you use:

- `./start_launcher.sh` or `python bot_launcher.py` → start **Index Bot** from the menu
- `./Index_bot/run_bot.sh` or `./Index_bot/start_bot.sh` (calls `install_deps.sh index` if imports fail)

## 2) Configure environment

```bash
cd Index_bot
cp .env.example .env   # or: python create_env.py
```

Edit `.env` — minimum: `BOT_TOKEN`, `ADMIN_USER_IDS`.

## 3) Run the bot

**From repo root (venv already active):**

```bash
cd Index_bot
python bot.py
```

**Or use helper scripts (venv + deps handled for you):**

```bash
cd Index_bot
chmod +x run_bot.sh start_bot.sh stop_bot.sh ensure_env.sh
./run_bot.sh
```

## 4) Launcher (recommended for multiple bots)

```bash
# From repo root
./start_launcher.sh
```

Pick **Index Bot** — dependencies are checked and installed before the process starts (same as name-bot).

## 5) Verify before first run

```bash
cd Index_bot
source ../.venv/bin/activate
python check_readiness.py
```

## Related

- [README.md](README.md) — features and commands
- [HOW_TO_RUN.md](HOW_TO_RUN.md) — ingest, PostgreSQL, stop/start
- [TERMUX_SETUP.md](TERMUX_SETUP.md) — Android / Termux (full monorepo clone recommended)
