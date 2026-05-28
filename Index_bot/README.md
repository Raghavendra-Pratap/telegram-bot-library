# Index Bot

Telegram bot that indexes channel files, matches titles (TMDB), powers a **watch portal**, and runs a **bulk upload pipeline** (courses, media, archives).

> Under active development on the `development` branch.

## What it does

- Monitors Telegram channels and indexes documents / video / audio
- Parses filenames → movies, series, courses; TMDB metadata when configured
- Admin pending queue, duplicates, content lanes, pipeline routing
- **Upload pipeline** — plan batches from folder/CSV/paths, upload to target channels via Telethon
- **Watch portal** — browse library, play in browser, admin catalog tools ([WATCH_PORTAL.md](./WATCH_PORTAL.md))

## Quick start

```bash
cd Index_bot
cp .env.example .env   # edit BOT_TOKEN, ADMIN_USER_IDS
./run_all.sh           # installs deps if needed, starts bot + portal
```

Foreground bot only: `./run_bot.sh`  
Stop stack: `./stop_all.sh`

Verify: `python check_readiness.py`

Full setup: [HOW_TO_RUN.md](./HOW_TO_RUN.md) · Phone server: [TERMUX_SETUP.md](./TERMUX_SETUP.md)

## Deployment options

| Mode | Where | Command |
|------|-------|---------|
| All-in-one | Termux / server | `./run_all.sh` |
| Bot only | Any | `./run_bot.sh` |
| Portal only | Any | `./run_portal.sh` |
| Uploads from Mac paths | Mac + shared DB | `./run_upload_worker.sh` on Mac; bot on Termux |

**Split deploy (bot on phone, files on Mac):** shared `DATABASE_URL` (PostgreSQL recommended), Mac worker runs pipeline uploads from local paths. See [DEPLOYMENT.md](./DEPLOYMENT.md).

## Dependencies

- **Combined:** `requirements-all.txt` (bot + portal + Telethon + psycopg)
- Monorepo: `../requirements/bot-index.txt` via `ensure_env.sh` / `run_*.sh`

## Configuration

All variables: **`.env.example`** (copy to `.env`).

| Variable | Purpose |
|----------|---------|
| `BOT_TOKEN`, `ADMIN_USER_IDS` | Required for bot |
| `DATABASE_URL` | Optional Postgres (shared DB for multi-machine) |
| `API_ID`, `API_HASH` | Telethon (ingest, uploads, portal stream) |
| `PORTAL_PUBLIC_URL` | Link in `/portal` command |
| `TELETHON_GATEWAY_ENABLED` | Single queued Telethon client on bot (default on) |
| `TELETHON_PORTAL_SESSION` | Separate session for portal streaming |

## Documentation

| Document | Description |
|----------|-------------|
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Processes, Termux/Mac split, start/stop |
| [HOW_TO_RUN.md](./HOW_TO_RUN.md) | Bot, env, historical ingest, workers |
| [API_DOCS.md](./API_DOCS.md) | Portal REST API (+ `/docs` Swagger) |
| [WATCH_PORTAL.md](./WATCH_PORTAL.md) | Portal setup and features |
| [UPLOAD_PIPELINE.md](./UPLOAD_PIPELINE.md) | Bulk upload jobs and CSV |
| [TERMUX_SETUP.md](./TERMUX_SETUP.md) | Complete Termux install guide |
| [PIPELINE_E2E_TEST.md](./PIPELINE_E2E_TEST.md) | End-to-end test checklist |
| [QUICKSTART.md](./QUICKSTART.md) | Minimal first-time setup |
| [LOCAL_SERVER_GUIDE.md](./LOCAL_SERVER_GUIDE.md) | Monorepo / shared venv |

## User commands (Telegram)

- `/start`, `/menu` — main menu
- `/search`, `/library`, `/watch`, `/portal`, `/favorites`, `/watchlist`
- `/list_channels`, `/stats`

## Admin (Telegram)

- `/menu` → Upload pipeline, Watch hub, Library setup, pending TMDB, etc.
- `/add_channel`, `/discover_channels`, `/backfill`
- Historical import: `forward_ingest.py` ([HOW_TO_RUN.md](./HOW_TO_RUN.md))

## Database

SQLite (`DB_PATH`, default `index_bot.db`) or **PostgreSQL** (`DATABASE_URL`). Schema is created on first start.

Migrate SQLite → Postgres on Termux: `scripts/migrate_sqlite_to_postgres.py` ([TERMUX_SETUP.md §18](./TERMUX_SETUP.md)).

## Historical ingest

Bots cannot read old channel history. Use Telethon to forward into an **ingest** channel:

```bash
python telethon_login.py
python forward_ingest.py @SourceChannel @IngestChannel
```

## License / repo

Part of **Telegram_Bot_Library**. Use repo-root `./scripts/install_deps.sh index` when working from the monorepo.
