# Telegram Bot Library

A collection of **standalone** Telegram bots, plus a **launcher and web dashboard** to run and manage multiple bots from one place.

- **Bots are standalone:** Each bot can be run on its own (e.g. `python bot.py` in its directory). They do not depend on the launcher.
- **Launcher & dashboard:** Use the launcher (CLI) or dashboard (web UI) to start, stop, restart, and monitor bots without a separate terminal per bot.

## Quick start (run and manage all bots)

```bash
# From repo root: start the launcher (interactive menu)
python bot_launcher.py
# or
./start_launcher.sh
```

Then choose which bots to start, view status, or start the web dashboard (option 8, default http://localhost:5000). The dashboard is **local-only** (no auth); all bots run on your device.

See [LAUNCHER_README.md](LAUNCHER_README.md) for launcher and dashboard details.

## Structure

```
Telegram_Bot_Library/
├── bot_launcher.py       # Launcher entry (menu + optional dashboard)
├── dashboard.py          # Web UI for monitoring/controlling bots
├── bots_config.json      # List of bots (id, directory, script, port, etc.)
├── caption_bot/          # Caption Bot – filename as caption on upload
├── down_oad_bot/         # Download Bot – video downloader (YouTube, Reddit, etc.)
├── Index_bot/            # Index Bot – search movies/series across channels
├── name-bot/             # Name Bot – filename caption + HTTP server
├── TG_download_bot/      # TG Download Bot – premium MTProto + file server
├── upload_bot/            # Upload Bot – upload with metadata, grouping, channels
└── [each bot]/           # Self-contained: bot.py, config.py, requirements.txt
```

## Available bots

| Bot | Directory | Description |
|-----|-----------|-------------|
| **Caption Bot** | `caption_bot/` | Sets filename as caption when files are uploaded to channels/groups. |
| **Download Bot** | `down_oad_bot/` | Video downloader for YouTube, Reddit, Twitter/X, Instagram, GIFs. |
| **Index Bot** | `Index_bot/` | Indexes channels, extracts movie/series names, search and library view. |
| **Name Bot** | `name-bot/` | Filename-as-caption with optional HTTP server. |
| **TG Download Bot** | `TG_download_bot/` | Fast file downloads via Premium/MTProto + HTTP file server. |
| **Upload Bot** | `upload_bot/` | Upload with metadata, CSV/Sheets, grouping, channel selection. |

Each bot has its own README. Dependencies are installed from a **shared root virtualenv** to avoid duplicate packages.

## Shared dependencies (recommended)

```bash
# From repo root
./scripts/setup_env.sh
./scripts/install_deps.sh down_oad
source .venv/bin/activate
python down_oad_bot/bot.py
```

You can install deps for other bots with:
`main`, `name-bot`, `caption`, `tg-download`, `down_oad`, `upload`, `index`, `launcher`, or `all`.

## Branching model

See [BRANCHING.md](BRANCHING.md) for the full policy.

**Summary:**
- `main` = production-ready bots only (currently `name-bot`)
- `development` = all under-development bots
- `feature/*` → `development` → `main`

## Server workflow (main branch)

On your server, install only the dependencies for bots that exist in `main`.
When a bot is promoted from a dev branch into `main`, install its new deps (if any).

```bash
# From repo root (server)
./scripts/setup_env.sh
./scripts/install_deps.sh main
./scripts/install_deps.sh launcher
./start_launcher.sh
```

## Local development workflow

```bash
# From repo root
./scripts/setup_env.sh
./scripts/install_deps.sh down_oad   # pick the dev bot you need
./start_launcher.sh
```

## Adding a new bot

1. Create a new folder (e.g. `my_bot/`) with at least `bot.py`, `config.py`, `requirements.txt`.
2. Add an entry to `bots_config.json` under `bots` with `id`, `name`, `description`, `directory`, `script` (e.g. `bot.py`), `venv_path`, optional `port`, and `enabled: true`.
3. Optionally add the bot to this README’s “Available bots” table.

## License

This library is for personal use. Respect platform Terms of Service.
