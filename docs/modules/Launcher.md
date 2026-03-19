# Module: Bot Launcher

## Purpose

The Bot Launcher is the central process that lets you run and manage multiple standalone Telegram bots from one place. It loads a config file, starts bots as subprocesses, tracks their status and stats, optionally runs a monitoring loop (auto-restart on crash), and can start the web dashboard in a thread. Bots do not depend on the launcher; each can be run on its own. The launcher only needs each bot’s directory, script path, and optional venv to spawn and control it.

## Concepts

### Standalone bots
Each bot lives in its own directory with its own `bot.py`, `config.py`, and `requirements.txt`. The launcher does not import bot code; it runs `python bot.py` (or the configured script) in that directory with the bot’s venv. Bots are independent processes.

### Config-driven bot list
Which bots exist and how to run them comes from `bots_config.json`: list of `{ id, name, description, directory, script, venv_path, port?, enabled? }`. The launcher only considers entries with `enabled: true` (default). Adding a bot is done by adding an entry and ensuring that directory/script/venv exist.

### In-memory state
Running bots, stats (start/stop/restart counts, total uptime, errors), and monitoring flag are kept in memory. Nothing is persisted to disk. On launcher exit, all child processes are stopped; on launcher restart, stats are reset. Persistence can be added later (e.g. logging or a JSON file).

## Architecture

### Overview

```
                    main()
                       │
                       ▼
              BotLauncher(config_path)
                       │
         ┌─────────────┼─────────────┐
         │             │             │
    load_config   running_bots   stats (defaultdict)
         │             │             │
         ▼             ▼             ▼
   interactive_menu() ◄──────────────────────┐
         │                                   │
    [1] Start ──► start_bot(bot)             │
    [2] Stop  ──► stop_bot(bot_id)           │
    [3] Restart ► restart_bot(bot_id)       │
    [4] show_status()                        │
    [5] show_stats()                          │
    [6] _start_monitoring() ──► monitor_bots() (thread, daemon)
    [7] _stop_monitoring()                   │
    [8] _start_dashboard() ──► start_dashboard(self, host, port) (thread, daemon)
    [9] _shutdown() ──► stop_bot() for all   │
         │                                   │
         └───────────────────────────────────┘
```

### Components

| Component | Purpose | Location |
|-----------|---------|----------|
| `Colors` | ANSI color codes for terminal output | `bot_launcher.py` (top-level class) |
| `BotProcess` | Dataclass for one running bot (process, pid, start_time, port, last_error, etc.) | `bot_launcher.py` |
| `BotLauncher` | Config load, dependency checks, start/stop/restart, monitoring, menu, dashboard spawn | `bot_launcher.py` |
| `main()` | Create launcher, optional dependency install, signal handlers, `interactive_menu()` | `bot_launcher.py` |

### Data flow

```
bots_config.json ──► load_config() ──► self.config
       │
       └──► get_available_bots() ──► list of enabled bots

start_bot(bot) ──► check_bot_setup() ──► check_bot_dependencies() [optional install]
       │
       └──► subprocess.Popen(python_exe, script_path, cwd=bot_dir)
                │
                └──► BotProcess(…) ──► self.running_bots[bot_id]
                         │
                         └──► self.stats[bot_id]["start_count"] += 1

stop_bot(bot_id) ──► process.terminate() ──► wait(5s) or kill
       │
       └──► stats total_uptime += elapsed; stop_count += 1
            del self.running_bots[bot_id]

monitor_bots() (loop every 5s):
  for each running_bots: if process.poll() is not None
    → capture stderr, update last_error, stats["errors"]
    → del running_bots[bot_id], total_uptime += elapsed
    → start_bot(bot_config)  # auto-restart
```

## Key Files

| File | Purpose | Key Exports |
|------|---------|-------------|
| `bot_launcher.py` | Launcher entry, BotLauncher, BotProcess, Colors, main | `BotLauncher`, `BotProcess`, `Colors`, `main` |
| `bots_config.json` | Bot list and dashboard host/port | Consumed by `load_config()` |
| `launcher_requirements.txt` | Launcher/dashboard deps (e.g. flask) | Used by `install_launcher_dependencies()` |

## Public Interface

### Classes

#### `BotProcess` (dataclass)
**Purpose:** Holds one running bot’s process and metadata.  
**Fields:** `bot_id`, `bot_name`, `process` (Popen), `start_time`, `pid`, `port?`, `status`, `restart_count`, `last_error?`

#### `BotLauncher(config_path: str = "bots_config.json")`
**Purpose:** Load config, manage running bots and stats, provide CLI menu and optional dashboard.  
**Attributes:** `config`, `running_bots`, `stats`, `monitoring`, `monitor_thread`

### Methods

#### `load_config() -> dict`
**Purpose:** Load and return JSON from `self.config_path`. Exits if file missing.  
**Returns:** `dict` with keys `bots` (list) and optionally `dashboard` (host, port).

#### `get_available_bots() -> List[dict]`
**Purpose:** Return bots from config where `enabled` is not False.  
**Returns:** List of bot config dicts.

#### `start_bot(bot: dict, auto_install: bool = True) -> Optional[BotProcess]`
**Purpose:** Start one bot as a subprocess. Checks setup (dir, script, venv), optionally installs missing deps, then `Popen(python_exe, script_path, cwd=bot_dir)`. Waits 2s; if process exited, returns None and prints stderr.  
**Parameters:** `bot` = config dict with `id`, `name`, `directory`, `script`, `venv_path`, optional `port`.  
**Returns:** `BotProcess` or `None`.

#### `stop_bot(bot_id: str) -> bool`
**Purpose:** Terminate bot process (5s timeout then kill). Updates stats (total_uptime, stop_count), removes from `running_bots`.  
**Returns:** `True` if stopped, `False` if not running or error.

#### `restart_bot(bot_id: str) -> bool`
**Purpose:** Stop then start. Looks up config by `bot_id`; calls `stop_bot` then `start_bot`; increments `restart_count` on success.  
**Returns:** `True` if restart succeeded.

#### `check_bot_setup(bot: dict) -> Tuple[bool, str]`
**Purpose:** Verify bot directory, script file, venv, and venv Python exist.  
**Returns:** `(True, "OK")` or `(False, error_message)`.

#### `check_bot_dependencies(bot: dict) -> Tuple[bool, List[str]]`
**Purpose:** Parse bot’s `requirements.txt` and check (via venv’s `pip list --format=json`) that each package is installed.  
**Returns:** `(True, [])` or `(False, list_of_missing_package_names)`.

#### `ensure_dependencies(check_bots: Optional[List[dict]] = None, auto_install: bool = True) -> bool`
**Purpose:** Check launcher deps (flask); optionally check and install deps for `check_bots`. Prompts for install if not `auto_install`.  
**Returns:** `True` if all deps OK or installed successfully.

#### `show_status()` / `show_stats()`
**Purpose:** Print to stdout a table of bot status (running/stopped, PID, uptime) or per-bot stats (starts, stops, restarts, total uptime, error count).

#### `interactive_menu()`
**Purpose:** Main loop: print available bots and actions (1–9), read choice, dispatch to start/stop/restart/status/stats/monitoring/dashboard/exit. Blocks until user chooses Exit.

### Functions

#### `main()`
**Purpose:** Create `BotLauncher()`, optionally install launcher deps, register SIGINT/SIGTERM to call `_shutdown()` then exit, then run `interactive_menu()`.

## Internal Workings

### How start_bot works
1. If `bot_id` already in `running_bots` and `process.poll() is None`, return existing BotProcess.
2. `check_bot_setup(bot)`; if not OK, return None.
3. `check_bot_dependencies(bot)`; if missing and not `auto_install`, return None; if missing and `auto_install`, call `install_bot_dependencies(bot)`.
4. Resolve `python_exe` (venv’s `bin/python` or `bin/python3`) and `script_path` (bot_dir / script).
5. `Popen([python_exe, script_path], cwd=bot_dir, stdout=PIPE, stderr=PIPE, env=os.environ + PYTHONUNBUFFERED=1)`.
6. `time.sleep(2)`; if `process.poll() is not None`, read stderr and return None.
7. Build `BotProcess`, store in `running_bots[bot_id]`, increment `stats[bot_id]["start_count"]`, return BotProcess.

### How monitoring works
- `_start_monitoring()` sets `self.monitoring = True` and starts a daemon thread running `monitor_bots()`.
- `monitor_bots()` loops: `time.sleep(5)`; for each `(bot_id, bot_process)` in `running_bots`, if `process.poll() is not None`, treat as crashed: capture stderr into `last_error` and `stats[bot_id]["errors"]`, update `total_uptime`, remove from `running_bots`, then call `start_bot(bot_config)` to auto-restart.

### State management
- **running_bots:** Dict[bot_id, BotProcess]. Updated only by start_bot (add), stop_bot (remove), monitor_bots (remove then start_bot).
- **stats:** defaultdict per bot_id: start_count, stop_count, restart_count, total_uptime (seconds), errors (list of {time, error}).
- **monitoring:** bool. **monitor_thread:** Thread or None. No persistence.

## Integration Points

### Used by
| Component | How it uses the launcher |
|-----------|---------------------------|
| `main()` | Creates BotLauncher, runs interactive_menu(). |
| `dashboard.start_dashboard(launcher, host, port)` | Receives launcher instance; routes call launcher.start_bot, stop_bot, restart_bot, and read launcher.config, running_bots, stats. |
| `start_selected_bots.py` | Imports BotLauncher, creates instance, calls ensure_dependencies and start_bot for selected bots. |

### Depends on
| Dependency | Why |
|------------|-----|
| `bots_config.json` | Bot list and dashboard host/port. |
| Each bot directory | Must contain script (e.g. bot.py), venv (e.g. venv/), and optionally requirements.txt. |
| `dashboard` (Flask) | Optional; only for “Start dashboard” (menu 8). Fails gracefully if import fails. |
| `launcher_requirements.txt` | For install_launcher_dependencies(). |

## Gotchas & Edge Cases

- **Port in config:** `bot.get('port')` is only for display (e.g. in status and dashboard). The launcher does not bind or check ports. A bot that runs an HTTP server (e.g. TG_download_bot) gets its port from its own .env (e.g. FILE_SERVER_PORT), not from bots_config. So the port shown in the launcher/dashboard is “declared” and may not match the bot’s actual port if the bot uses a different env value.

- **Venv required:** `check_bot_setup` requires the bot’s venv to exist. Bots are always run with the venv’s Python. There is no fallback to system Python.

- **2-second startup window:** After Popen, the launcher sleeps 2 seconds. If the bot exits within 2 seconds (e.g. missing .env), start_bot returns None and the process is not tracked. Slow machines might need a longer delay for “started successfully” detection.

- **Stats and restarts:** When the monitor auto-restarts a bot, it calls `start_bot` but does not increment `restart_count` in stats (only manual restart_bot does). The new BotProcess has `restart_count` on the dataclass (not the same as stats["restart_count"]).

- **Dashboard thread:** The dashboard runs in a daemon thread and holds a reference to the launcher. Exiting the launcher (option 9) stops all bots but the Flask server may still be running until the process exits.

- **No persistence:** Stopping the launcher loses all stats and running state. Bots are terminated; they do not “resume” when the launcher is started again.
