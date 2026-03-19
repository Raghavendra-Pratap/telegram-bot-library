# Decision Log: Telegram Bot Library

Decisions recovered from existing codebase and developer clarification.

---

## 2026-02-15 - Documented During Context Recovery

### Standalone bots + launcher/dashboard
**Context:** Developer clarification on project intent.  
**Decision:** All bots are standalone (runnable on their own). The launcher and web dashboard are the layer built to run and manage multiple bots from one place. Bots do not depend on the launcher; the launcher only uses directory paths and `bots_config.json` to spawn and control them.  
**Rationale:** Single process and optional UI to start/stop/restart/monitor bots without a separate terminal per bot.

### Dashboard: local-only, no auth
**Context:** Security and deployment.  
**Decision:** Dashboard is intended for local use only (all bots on the operator’s device). No authentication; not assumed behind a reverse proxy or exposed publicly.  
**Rationale:** Developer confirmed local-only for now.

### Download Bot directory name
**Context:** Naming consistency (down_oad_bot vs download_bot).  
**Decision:** Keep directory name `down_oad_bot`; it is intentional, not a typo.  
**Rationale:** Developer confirmed.

### Launcher stats: in-memory only for now
**Context:** Stats (start/stop/restart counts, uptime, errors) are not persisted.  
**Decision:** Stats remain in-memory; persistence (e.g. logging or JSON file) can be planned later. Not a dealbreaker.  
**Rationale:** Developer confirmed; optional to add later.

### Dashboard-only entry point
**Context:** Running only the web UI without the CLI menu.  
**Decision:** Can be planned as a future enhancement (e.g. for headless/scripted use).  
**Rationale:** Developer open to adding later.

### Bot maturity
**Context:** Which bots are production-ready vs experimental.  
**Decision:** Some bots are under development; some are ready to use.  
**Rationale:** Developer confirmed mix.

### Index Bot schema (FileUpload ↔ MovieSeries)
**Context:** Relationship is by string match; no FK.  
**Decision:** Index Bot is under development; FK or consistency checks can be planned later.  
**Rationale:** Developer confirmed; future improvement.

### Tech stack (launcher and bots)
**Context:** Analyzed codebase and requirements files.  
**Decision:** Python 3.8+; launcher uses Flask for dashboard; bots use python-telegram-bot; TG_download_bot uses Pyrogram (MTProto) and aiohttp; Index_bot uses SQLAlchemy (SQLite). Each bot has its own requirements.txt and optional venv.  
**Rationale:** Historical – established in implementation.

### Bot execution: subprocess + venv
**Context:** How the launcher runs bots.  
**Decision:** Each bot is started as a subprocess with `Popen(python_exe, script_path, cwd=bot_dir)`. Python is the bot’s venv (e.g. `venv/bin/python`). No fallback to system Python.  
**Rationale:** Isolation and per-bot dependencies.

### Config-driven bot list
**Context:** How bots are registered.  
**Decision:** Bot list comes from `bots_config.json` (id, name, directory, script, venv_path, port?, enabled?). Adding a bot = add entry + ensure directory/script/venv exist.  
**Rationale:** Single config file; no code change to add a bot.

---

*Add new decisions as development continues.*
