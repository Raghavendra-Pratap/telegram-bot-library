# Codebase Map: Telegram Bot Library

**Intent:** All bots are **standalone** (runnable on their own). The launcher and dashboard exist to **run and manage multiple bots** from one place—start, stop, restart, monitor—without a separate terminal per bot.

## Folder Structure

```
Telegram_Bot_Library/
├── docs/                          # Recovery / project documentation
│   ├── plans/
│   ├── decisions/
│   │   └── DECISIONS.md
│   ├── sessions/
│   ├── modules/
│   ├── PROJECT_CONTEXT.md
│   └── CODEBASE_MAP.md            # This file
├── caption_bot/                   # Caption Bot – filename as caption on upload
│   ├── bot.py                     # Entry point; telegram handlers
│   ├── config.py                  # Env-based config
│   ├── requirements.txt
│   └── env_template.txt
├── down_oad_bot/                  # Video Download Bot (multi-platform)
│   ├── bot.py                     # Entry point; URL routing to downloaders
│   ├── config.py
│   ├── downloaders/               # Platform-specific downloaders
│   │   ├── __init__.py
│   │   ├── base_downloader.py
│   │   ├── youtube_downloader.py
│   │   ├── reddit_downloader.py
│   │   ├── twitter_downloader.py
│   │   ├── instagram_downloader.py
│   │   ├── threads_downloader.py
│   │   └── gif_downloader.py
│   ├── utils/
│   │   ├── __init__.py
│   │   └── url_detector.py
│   ├── downloads/                 # Default download output dir (runtime)
│   ├── requirements.txt
│   ├── env_template.txt
│   ├── test_bot_init.py
│   └── test_setup.py
├── Index_bot/                     # Index Bot – channel indexing, movie/series search
│   ├── bot.py                     # Entry point; commands & handlers
│   ├── config.py                  # Config class (env + DB path)
│   ├── database.py                # DB models (Channel, FileUpload, CustomList)
│   ├── name_parser.py             # Parse file names to movie/series titles
│   ├── tmdb_helper.py             # TMDB API (optional)
│   ├── requirements.txt
│   ├── check_readiness.py
│   ├── create_env.py
│   ├── setup.py
│   ├── test_bot_startup.py
│   ├── test_full_startup.py
│   └── test_parser.py
├── name-bot/                      # Name Bot – filename caption + HTTP server
│   ├── bot.py                     # Entry point; Telegram + optional HTTP
│   ├── config.py
│   ├── user_manager.py            # Allowed users (e.g. users.json)
│   ├── requirements.txt
│   ├── env_template.txt
│   └── users.json                # Runtime allowed users (if used)
├── TG_download_bot/               # TG Download Bot – premium MTProto + file server
│   ├── bot.py                     # Entry point; Telegram handlers
│   ├── config.py
│   ├── mtproto_downloader.py      # PremiumDownloader (MTProto)
│   ├── file_server.py             # HTTP file server (download links)
│   ├── user_manager.py            # Dynamic allowlist (allowed_users.json)
│   ├── check_premium.py
│   ├── test_mtproto.py
│   ├── allowed_users.json         # Runtime allowed users
│   ├── requirements.txt
│   ├── env_template.txt
│   └── *.sh                       # Auth, restart, production scripts
├── upload_bot/                    # Upload Bot – metadata, grouping, channels
│   ├── bot.py                     # Entry point; Telegram + upload flow
│   ├── config.py
│   ├── metadata/
│   │   ├── __init__.py
│   │   ├── csv_reader.py
│   │   ├── sheets_reader.py       # Google Sheets
│   │   └── matcher.py
│   ├── uploaders/
│   │   ├── __init__.py
│   │   └── file_uploader.py
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── file_scanner.py
│   │   └── tree_builder.py
│   └── requirements.txt
├── bot_launcher.py                # Launcher entry point; CLI menu, process management
├── dashboard.py                   # Flask dashboard (in-process with launcher)
├── bots_config.json               # Bot list: id, name, directory, script, venv_path, port, enabled
├── launcher_requirements.txt      # flask (for dashboard)
├── start_launcher.sh              # Run launcher (checks Flask, runs bot_launcher.py)
├── start_selected_bots.py         # Helper to start selected bots
├── check_all_bots.py              # Check/sanity script for bots
├── test_bots_startup.py           # Test launcher/bot startup
└── README.md
```

---

## Feature-to-Code Map

| Feature | Launcher/Dashboard | Bot (per bot) | Key Files |
|---------|--------------------|---------------|-----------|
| Interactive menu | `bot_launcher.py` | — | `BotLauncher.interactive_menu`, `_start_bots_menu`, `_stop_bots_menu` |
| Start/stop/restart bots | `bot_launcher.py` | — | `start_bot`, `stop_bot`, `restart_bot` (subprocess) |
| Web dashboard | `dashboard.py` | — | `start_dashboard(launcher)`, routes `/`, `/api/status`, `/api/start/<id>`, etc. |
| Process monitoring (auto-restart) | `bot_launcher.py` | — | `_monitor_loop`, `start_monitoring` |
| Caption Bot | — | `caption_bot/` | `caption_bot/bot.py`, `config.py` |
| Download Bot | — | `down_oad_bot/` | `bot.py`, `downloaders/*`, `utils/url_detector.py` |
| Index Bot | — | `Index_bot/` | `bot.py`, `database.py`, `name_parser.py`, `tmdb_helper.py` |
| Name Bot | — | `name-bot/` | `bot.py`, `config.py`, `user_manager.py` |
| TG Download Bot | — | `TG_download_bot/` | `bot.py`, `mtproto_downloader.py`, `file_server.py`, `user_manager.py` |
| Upload Bot | — | `upload_bot/` | `bot.py`, `metadata/*`, `uploaders/file_uploader.py`, `utils/*` |

---

## Entry Points

**Launcher (application entry):**
- Main: `bot_launcher.py` — `main()` → `BotLauncher()` → `interactive_menu()`. Loads `bots_config.json`, handles SIGINT/SIGTERM, optional dependency install.

**Dashboard (same process as launcher):**
- Started from launcher menu (option 8): `start_dashboard(self, host, port)` in `dashboard.py` runs in a daemon thread.
- Entry: Flask app in `dashboard.py`; single HTML template in `DASHBOARD_HTML` (inline).
- API routes: `/api/status`, `/api/start/<bot_id>`, `/api/stop/<bot_id>`, `/api/restart/<bot_id>`, `/api/stats`.

**Each bot (separate process):**
- Started by launcher: `subprocess.Popen([python_exe, script_path], cwd=bot_dir)`.
- Script: per-bot `script` in config (e.g. `bot.py`).
- Bot entry: `bot.py` in each bot directory — typically `Application.run_polling()` or equivalent (python-telegram-bot).

---

## Component Communication

**Dashboard ↔ Launcher:**
- Method: In-process. Dashboard receives `launcher` (BotLauncher instance); routes call `launcher.start_bot()`, `launcher.stop_bot()`, `launcher.restart_bot()`, and read `launcher.running_bots`, `launcher.stats`, `launcher.config`.
- Defined in: `dashboard.start_dashboard(launcher, host, port)`; launcher starts it via `threading.Thread(target=start_dashboard, args=(self, ...))`.

**Launcher ↔ Bots:**
- Method: Process boundary. Launcher spawns bots with `subprocess.Popen`; no shared memory. Stop via `process.terminate()` / `process.kill()`.
- Config: `bots_config.json` (directory, script, venv_path, port for display only).

**Bots ↔ Telegram:**
- Method: Telegram Bot API (HTTPS). Each bot uses python-telegram-bot (and optionally Telethon for TG_download_bot MTProto).
- Credentials: Per-bot `.env` (e.g. `TELEGRAM_BOT_TOKEN`, and for TG_download_bot: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`).

**Key integration points:**

| Action | Initiator | Handler |
|--------|-----------|---------|
| Start bot | User in dashboard or CLI menu | `BotLauncher.start_bot(bot_config)` → `subprocess.Popen` |
| Stop bot | User in dashboard or CLI | `BotLauncher.stop_bot(bot_id)` → `process.terminate()` |
| Restart bot | User in dashboard or CLI | `BotLauncher.restart_bot(bot_id)` → stop then `start_bot` |
| Get status | Dashboard JS fetch | `GET /api/status` → launcher.running_bots + config |
| Bot crash recovery | Launcher monitor thread | `_monitor_loop` polls `process.poll()`, calls `start_bot` if exited |

---

## Conventions Observed

### File Naming
| Type | Pattern | Example |
|------|---------|---------|
| Bot entry | `bot.py` | All six bots use `bot.py` |
| Config | `config.py` or env | `config.py` loads from env / `.env` |
| Env template | `env_template.txt` | `caption_bot`, `down_oad_bot`, `name-bot`, `TG_download_bot` |
| Utilities | `utils/<name>.py` | `down_oad_bot/utils/url_detector.py`, `upload_bot/utils/file_scanner.py` |
| Tests | `test_*.py` | `test_bots_startup.py`, `Index_bot/test_parser.py`, `down_oad_bot/test_setup.py` |
| Shell scripts | `*.sh` | `start_launcher.sh`, `TG_download_bot/restart_bot.sh` |

### Code Patterns
- **Bot layout:** Each bot has `bot.py` (handlers), `config.py` (env), optional packages (`downloaders/`, `metadata/`, `uploaders/`, `utils/`). Imports are local to the bot dir (e.g. `from config import ...`, `from downloaders import ...`).
- **Error handling:** Try/except with logging; launcher captures bot stderr via `subprocess.PIPE` and can surface `last_error`.
- **State:** Launcher holds `running_bots` (dict of BotProcess) and `stats` (defaultdict) in memory; no persistent stats file observed. Bots use JSON files for allowlists (e.g. `allowed_users.json`, `users.json`). Index Bot uses SQLite (`database.py`).
- **Async:** Bots use `async` handlers (python-telegram-bot). Launcher/dashboard are synchronous.

### Style
- Python 3.8+; type hints used in launcher (e.g. `Optional[BotProcess]`). Logging via `logging` module. No single formatter/linter config in repo root.

---

## Key Reusable Components

| Component | Location | Purpose | Used By |
|-----------|----------|---------|---------|
| BotLauncher | `bot_launcher.py` | Load config, start/stop/restart subprocesses, CLI menu, monitoring | `main()`, dashboard (via passed `launcher`) |
| start_dashboard | `dashboard.py` | Create Flask app, register API routes, run server | Launcher (option 8) |
| URLDetector / Platform | `down_oad_bot/utils/url_detector.py` | Detect platform from URL | `down_oad_bot/bot.py` |
| Downloaders | `down_oad_bot/downloaders/*` | Platform-specific download implementations | `down_oad_bot/bot.py` |
| PremiumDownloader | `TG_download_bot/mtproto_downloader.py` | MTProto download | `TG_download_bot/bot.py` |
| FileServer | `TG_download_bot/file_server.py` | HTTP file server for download links | `TG_download_bot/bot.py` |
| UserManager | `TG_download_bot/user_manager.py`, `name-bot/user_manager.py` | Allowed users (JSON) | Respective `bot.py` |
| Database / NameParser | `Index_bot/database.py`, `Index_bot/name_parser.py` | Persistence and name parsing | `Index_bot/bot.py` |
| MetadataMatcher / readers | `upload_bot/metadata/` | CSV/Sheets + matching | `upload_bot/bot.py` |
| FileUploader | `upload_bot/uploaders/file_uploader.py` | Upload to Telegram | `upload_bot/bot.py` |

---

## Configuration Files

| File | Purpose |
|------|---------|
| `bots_config.json` | List of bots: id, name, description, directory, script, venv_path, port, enabled. Dashboard host/port. |
| `launcher_requirements.txt` | Launcher/dashboard deps (e.g. flask). |
| Per-bot `config.py` + `.env` | Bot token, API keys, feature flags, paths. Sourced from `env_template.txt`. |
| `TG_download_bot/allowed_users.json` | Allowed user IDs (dynamic user management). |
| `name-bot/users.json` | Allowed users for Name Bot (if used). |

---

## Tests

**Test locations:**
- Root: `test_bots_startup.py`, `check_all_bots.py` (launcher/bots sanity).
- `down_oad_bot`: `test_bot_init.py`, `test_setup.py`.
- `Index_bot`: `test_bot_startup.py`, `test_full_startup.py`, `test_parser.py`.
- `TG_download_bot`: `test_mtproto.py`.

**Framework:** Ad-hoc (no pytest/unittest root config observed). Some scripts are runnable checks rather than automated test suites.

**Coverage:** Sparse — per-bot and launcher checks exist; no unified test runner or coverage report.

---

## Build & Scripts

| Script | Command | Purpose |
|--------|---------|---------|
| Launcher | `python bot_launcher.py` or `./start_launcher.sh` | Start interactive launcher (menu, optional dashboard) |
| Start selected | `python start_selected_bots.py` | Start a subset of bots (helper) |
| Check bots | `python check_all_bots.py` | Sanity check bots |
| Test startup | `python test_bots_startup.py` | Test launcher/bot startup |
| Caption Bot | `python bot.py` (in caption_bot/) | Run Caption Bot |
| Download Bot | `python bot.py` (in down_oad_bot/) or `./START_BOT.sh` | Run Download Bot |
| Index Bot | `python bot.py` (in Index_bot/) or `./run_bot.sh` | Run Index Bot |
| Name Bot | `python bot.py` (in name-bot/) | Run Name Bot |
| TG Download Bot | `python bot.py` (in TG_download_bot/) or `./start_bot.sh` | Run TG Download Bot |
| Upload Bot | `python bot.py` (in upload_bot/) | Run Upload Bot |

---

## Resolved / Notes

- **Launcher stats:** In-memory only for now; persistence (e.g. logging or JSON) can be planned later.
- **Dashboard-only entry:** A separate entry point to run only the dashboard (no CLI menu) can be planned for headless/scripted use.
- **Download Bot directory:** Name `down_oad_bot` is intentional (not a typo). See `docs/decisions/DECISIONS.md`.

---
*Status: Codebase Mapping Complete*  
*Next: /technical*
