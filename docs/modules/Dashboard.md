# Module: Dashboard

## Purpose

The Dashboard is a Flask web app that provides a web UI to monitor and control the bots managed by the Bot Launcher. It runs in the same process as the launcher (in a daemon thread) and receives the launcher instance so it can call start/stop/restart and read status and stats. It is local-only by design (no authentication). Intended for use on the operator’s machine to manage multiple bots without using the CLI menu.

## Concepts

### In-process, not standalone
The dashboard is not a separate service. It is started from the launcher (menu option 8) via `start_dashboard(launcher, host, port)`. The Flask app is created inside that function and holds closures over `launcher`. All API handlers use the same `launcher` object that the CLI menu uses.

### Single-page UI + REST API
The UI is one HTML page (embedded in `DASHBOARD_HTML` in `dashboard.py`) with inline CSS and JavaScript. The page polls `GET /api/status` every 3 seconds and calls `POST /api/start|<bot_id>`, `POST /api/stop|<bot_id>`, `POST /api/restart|<bot_id>` for button actions. There is no separate front-end build or router.

### No authentication
There are no auth headers, cookies, or login. The app is intended for local use (e.g. http://localhost:5000). If the dashboard is exposed (e.g. reverse proxy), the operator should add auth or restrict access.

## Architecture

### Overview

```
                    Launcher (menu option 8)
                              │
                              ▼
                 start_dashboard(launcher, host, port)
                              │
                    Flask(app)  ← launcher in closure
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
    GET  /              GET  /api/status    POST  /api/start/<id>
         │                    │              POST  /api/stop/<id>
         ▼                    ▼              POST  /api/restart/<id>
   DASHBOARD_HTML       launcher.             launcher.start_bot(config)
   (single page)        get_available_bots()  launcher.stop_bot(id)
   + JS polling         running_bots         launcher.restart_bot(id)
                        config
                              │
                        GET  /api/stats
                              │
                              ▼
                        launcher.stats
```

### Components

| Component | Purpose | Location |
|-----------|---------|----------|
| `DASHBOARD_HTML` | Single HTML document with inline CSS/JS; bot cards, Start/Stop/Restart, status, stats | `dashboard.py` (string constant) |
| `start_dashboard(launcher, host, port)` | Create Flask app, register routes, run app.run(host, port) | `dashboard.py` |

### Data flow

- **Page load:** Browser GET `/` → Flask returns `render_template_string(DASHBOARD_HTML)`.
- **Polling:** JS `setInterval(loadBots, 3000)` → `fetch('/api/status')` → response has `bots`, `running_count`, `stopped_count` → DOM updated (cards, badges, uptime, buttons).
- **Start/Stop/Restart:** Button click → `fetch('/api/start|stop|restart/<bot_id>', { method: 'POST' })` → Flask calls `launcher.start_bot(bot_config)` or `stop_bot`/`restart_bot` → JSON `{ success: true }` or `{ success: false, error }` → alert on error.
- **Stats:** Optional; `/api/stats` returns per-bot stats (start_count, stop_count, restart_count, total_uptime_hours, error_count). Used if the UI has a stats view.

## Key Files

| File | Purpose | Key Exports |
|------|---------|-------------|
| `dashboard.py` | Flask app, routes, and single HTML template | `start_dashboard` (and Flask app built inside it) |

## Public Interface

### Functions

#### `start_dashboard(launcher, host='0.0.0.0', port=5000)`
**Purpose:** Create a Flask application, register routes that use `launcher`, and run `app.run(host=host, port=port, debug=False, threaded=True)`. Blocks until the server is stopped.  
**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| launcher | BotLauncher (instance) | Same object used by the CLI; must have config, running_bots, stats, start_bot, stop_bot, restart_bot, get_available_bots. |
| host | str | Bind address (default 0.0.0.0). |
| port | int | Bind port (default 5000). |

**Called by:** Launcher’s `_start_dashboard()` in a daemon thread. Host/port usually come from `launcher.config.get('dashboard', {}).get('host'|'port')`.

## API Endpoints (internal to module)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serve the single-page HTML. |
| GET | `/api/status` | List all available bots with status (running/stopped), pid, port, uptime_seconds, start_time, last_error. |
| POST | `/api/start/<bot_id>` | Start bot; 404 if bot_id not in config, 500 if start_bot returns None. |
| POST | `/api/stop/<bot_id>` | Stop bot; returns { success: bool }. |
| POST | `/api/restart/<bot_id>` | Restart bot; returns { success: bool }. |
| GET | `/api/stats` | Per-bot stats: start_count, stop_count, restart_count, total_uptime_hours, error_count. |

All responses are JSON except `/` (HTML).

## Integration Points

### Used by
| Component | How it uses the dashboard |
|-----------|---------------------------|
| `bot_launcher.py` → `_start_dashboard()` | Imports `start_dashboard` from dashboard, starts it in a threading.Thread with `args=(self, dashboard_host, dashboard_port)`, daemon=True. |

### Depends on
| Dependency | Why |
|------------|-----|
| Flask | `Flask`, `jsonify`, `render_template_string`. |
| BotLauncher instance | Provides config, running_bots, stats, get_available_bots(), start_bot(), stop_bot(), restart_bot(). |
| datetime | For uptime and start_time in /api/status. |

## Gotchas & Edge Cases

- **Port vs bot’s actual port:** The dashboard shows `port` from launcher config (or BotProcess.port). For bots that run their own HTTP server (e.g. TG_download_bot), the real port is from the bot’s .env (e.g. FILE_SERVER_PORT). The displayed port may not match.

- **Daemon thread:** When the launcher exits (e.g. user chooses Exit), the main thread ends. The dashboard thread is daemon, so the process can exit while Flask is still running; the server is not gracefully shut down.

- **process.poll() in status:** `/api/status` uses `bot_process.process.poll() is None` to decide “running”. If a bot has exited but the launcher hasn’t run the monitor loop yet, the dashboard might still show it as running for up to one poll interval (3s) plus monitor interval (5s). After the monitor removes it, the next /api/status will show it as stopped.

- **No CSRF or rate limiting:** POST endpoints are not protected. Safe if the dashboard is only used locally and not exposed.
