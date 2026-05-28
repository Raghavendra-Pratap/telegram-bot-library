# Deployment guide

How to run Index_bot processes on **Termux (phone server)**, **Mac/PC**, or **split** (bot on phone, uploads on Mac).

## Process overview

| Process | Script | Purpose |
|---------|--------|---------|
| **Bot** | `run_bot.sh` / `bot.py` | Telegram commands, indexing, upload job UI |
| **Portal** | `run_portal.sh` / `run_portal.py` | Web UI + REST API |
| **Stack** | `run_all.sh` | Bot + portal together (background) |
| **Upload worker** | `run_upload_worker.sh` | **Upload pipeline only** — no bot polling |

Only **one** instance should poll Telegram with `BOT_TOKEN` (one `bot.py`).

## Recommended layouts

### A. Termux only (simple)

```
Phone (Termux)
├── bot.py          ← indexing + admin
├── run_portal.py   ← optional watch portal
└── PostgreSQL      ← optional (section 18 in TERMUX_SETUP.md)
```

```bash
cd ~/projects/Telegram_Bot_Library/Index_bot
./run_all.sh
# stop: ./stop_all.sh
```

Upload files must exist **on the phone** (`local_path` / folder scan).

### B. Termux bot + Mac upload worker (your setup)

```
Termux                          Mac
├── bot.py                      ├── run_upload_worker.py
├── run_portal.py               ├── files on Mac disk
├── shared DATABASE_URL ────────┘   (PostgreSQL or reachable DB)
```

1. Set **`DATABASE_URL`** to the same Postgres on both machines (Termux hosts DB or remote Postgres).
2. On Termux: `./run_all.sh` (or bot + portal separately).
3. On Mac: create jobs in Telegram (paths = Mac paths), then:

```bash
cd /path/to/Index_bot
./run_upload_worker.sh
```

4. Mac needs `API_ID`, `API_HASH`, and `python telethon_login.py` (own `forward_ingest.session` is fine).

Worker picks jobs with `upload`/`force` items whose `local_path` exists **on Mac**.

### C. Mac/PC development

Same as B, or run everything locally:

```bash
./run_all.sh          # bot + portal
./run_upload_worker.sh   # optional, if testing pipeline uploads
```

## Dependencies

| File | Use |
|------|-----|
| `requirements-all.txt` | **Combined** runtime deps (bot + portal + Telethon + Postgres) |
| `../requirements/bot-index.txt` | Monorepo canonical list (included by `requirements-all.txt`) |
| `requirements.txt` | Standalone copy fallback |

`ensure_env.sh` (used by all `run_*.sh` scripts) creates/activates venv and runs `pip install -r requirements-all.txt` when imports are missing.

## Telethon sessions

| Session file | Used by |
|--------------|---------|
| `forward_ingest.session` | Bot gateway (uploads, routes, member watch), Mac worker |
| `forward_ingest_portal.session` | Portal Play/streaming only |

```bash
python telethon_login.py          # bot / worker
python telethon_login_portal.py   # portal streaming
```

Set `TELETHON_GATEWAY_ENABLED=true` on the bot (default).

## Environment checklist

| Variable | Bot | Portal | Upload worker |
|----------|-----|--------|---------------|
| `BOT_TOKEN` | ✓ | ✓ (play to DM) | — |
| `ADMIN_USER_IDS` | ✓ | ✓ (admin API) | — |
| `DATABASE_URL` | ✓ | ✓ | ✓ (shared for split deploy) |
| `API_ID` / `API_HASH` | Telethon features | stream | ✓ |
| `PORTAL_PUBLIC_URL` | `/portal` links | ✓ | — |
| `UPLOAD_WORKER_*` | — | — | optional tuning |

See **`.env.example`** for full list.

## Start / stop cheat sheet

```bash
# Full stack (background)
./run_all.sh
./stop_all.sh

# Foreground bot (debug)
./run_bot.sh

# Portal only
./run_portal.sh

# Mac upload worker only
./run_upload_worker.sh
# Ctrl+C to stop (or kill PID from .upload_worker.lock host process)

# Readiness
python check_readiness.py
```

Logs: `bot.log`, `portal.log` (when using `run_all.sh`).

## PostgreSQL on Termux (no Docker)

```bash
./scripts/setup_postgres_termux.sh
# add printed DATABASE_URL to .env on bot + portal + Mac worker
python scripts/migrate_sqlite_to_postgres.py
```

Details: [TERMUX_SETUP.md §18](./TERMUX_SETUP.md#18-optional-postgresql-instead-of-sqlite-no-docker).

## Documentation index

| Doc | Contents |
|-----|----------|
| [README.md](./README.md) | Overview + quick links |
| [HOW_TO_RUN.md](./HOW_TO_RUN.md) | Run bot, env, historical ingest |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | This file |
| [API_DOCS.md](./API_DOCS.md) | Portal REST API |
| [WATCH_PORTAL.md](./WATCH_PORTAL.md) | Portal user guide |
| [UPLOAD_PIPELINE.md](./UPLOAD_PIPELINE.md) | Bulk upload jobs |
| [TERMUX_SETUP.md](./TERMUX_SETUP.md) | Phone server from scratch |
| [PIPELINE_E2E_TEST.md](./PIPELINE_E2E_TEST.md) | Test checklist |
| `.env.example` | All configuration variables |
