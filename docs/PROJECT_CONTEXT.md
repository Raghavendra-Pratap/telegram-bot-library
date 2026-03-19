# Project Context: Telegram Bot Library

## Overview

**What it is:** A monorepo of multiple **standalone** Telegram bots plus a unified launcher and web dashboard. Each bot is a separate Python project in its own directory and can be run on its own (`python bot.py` in that directory). The launcher and dashboard are the layer built to **run and manage multiple bots from one place**—start, stop, restart, and monitor—without running each bot in a separate terminal. The bots do not depend on the launcher; the launcher only uses directory paths and `bots_config.json` to run them.

**Apparent purpose:** Provide a single process (launcher) and optional web UI (dashboard) to operate several standalone Telegram bots (download, upload, caption, indexing) with selective launch, monitoring, auto-restart, and dependency checks.

**Target users:** Developer/operator running their own Telegram bots on their device (personal or small-team use). Dashboard is local-only for now. End users interact with individual bots on Telegram.

**Tech stack:** Python 3.8+, Telegram Bot API (python-telegram-bot), MTProto (Pyrogram) in TG_download_bot, Flask for launcher dashboard. Each bot has its own `requirements.txt` and optional venv.

---

## Features Inventory

| Feature | Description | Status | Location |
|---------|-------------|--------|----------|
| Bot Launcher CLI | Interactive menu to start/stop/restart bots, show status, stats | Complete | `bot_launcher.py` |
| Selective launch | Choose which bots to run | Complete | `bot_launcher.py` |
| Process monitoring | Auto-restart crashed bots | Complete | `bot_launcher.py` |
| Web dashboard | Flask UI to monitor and control bots (port 5000) | Complete | `dashboard.py` |
| Port management | Bots with HTTP servers on different ports (e.g. 8080, 8081) | Complete | `bots_config.json`, launcher |
| Dependency checking | Verify/install launcher and per-bot deps before start | Complete | `bot_launcher.py` |
| Caption Bot | Set filename as caption on upload | Complete | `caption_bot/` |
| Download Bot | Video downloader (YouTube, Reddit, Twitter, Instagram, etc.) | Complete | `down_oad_bot/` |
| Index Bot | Index channels, extract movie/series names, search | Complete | `Index_bot/` |
| Name Bot | Filename-as-caption with HTTP server (port 8080) | Complete | `name-bot/` |
| TG Download Bot | Premium MTProto downloads + file server (port 8081) | Complete | `TG_download_bot/` |
| Upload Bot | Upload with metadata, grouping, CSV/Sheets, channel selection | Complete | `upload_bot/` |

### Feature Groups

**Launcher & ops:**
- Interactive menu (start/stop/restart, status, stats, monitoring, dashboard, exit)
- Config-driven bot list: `bots_config.json` (id, name, directory, script, venv_path, port, enabled)
- Statistics: start/stop/restart counts, uptime, errors per bot

**Bots – download:**
- Download Bot: multi-platform video downloader (YouTube, Reddit, Twitter/X, Instagram, etc.)
- TG Download Bot: premium-speed downloads via MTProto, HTTP file server, token-based access, link expiry

**Bots – upload & caption:**
- Caption Bot: set filename as caption when files are uploaded
- Name Bot: same idea with HTTP server for external triggers
- Upload Bot: uploads with folder/metadata, CSV/Sheets, grouping, channel selection, format/quality options

**Bots – indexing:**
- Index Bot: monitor channels, parse movie/series names, search, library view, admin confirmation, backfill

---

## User Flows

### Flow: Run bots via launcher
```
Run `python bot_launcher.py` → Interactive menu → Start bot(s) → Select bot(s) → Bot(s) run in subprocesses
```
**Status:** Working

### Flow: Monitor via dashboard
```
Start dashboard from launcher (option 8) → Browser to port 5000 → View status, start/stop/restart bots
```
**Status:** Working

### Flow: Download Bot – user downloads video
```
User sends link to bot → Bot downloads from platform → Sends file (or link) to user
```
**Status:** Working (per README)

### Flow: TG Download Bot – premium download
```
User forwards file to bot → Bot downloads via MTProto (premium) → Stores on server → Returns HTTP link → User downloads from server
```
**Status:** Working (per README)

### Flow: Caption / Name Bot – caption on upload
```
User uploads file in channel/group (bot is admin) → Bot edits message to set caption to filename
```
**Status:** Working (per README)

### Flow: Index Bot – search movies/series
```
Admin adds channels → Bot indexes file names → User /search <name> → Bot returns matches across channels
```
**Status:** Working (per README)

### Flow: Upload Bot – upload with metadata
```
Operator uses bot with CSV/Sheets metadata → Selects grouping and channels → Bot uploads files with captions/metadata
```
**Status:** Working (per README)

---

## Data Flows

**Data In:**
- `bots_config.json`: bot definitions (id, name, directory, script, venv_path, port, enabled)
- Per-bot: `.env` (tokens, API keys, optional user allowlists)
- Telegram: messages, files, links from users
- Upload Bot: CSV/Google Sheets for metadata

**Data Processing:**
- Launcher: reads config, spawns subprocesses, tracks PIDs, ports, restarts, stats
- Dashboard: calls launcher/process state, serves HTML/JSON
- Each bot: Telegram handlers, download/upload/index logic, optional local DB (e.g. Index Bot)

**Data Out:**
- Launcher: stdout/stderr of child processes, stats (in-memory and possibly persisted)
- Dashboard: HTML UI, API responses for status/actions
- Bots: Telegram messages, files; TG Download Bot also HTTP file server responses

```
[config + .env] → [Launcher/Dashboard] → [Subprocess bots] ↔ [Telegram API / MTProto / HTTP]
```

---

## Domain Model

| Entity | Description | Relationships |
|--------|-------------|---------------|
| Bot (config) | One entry in bots_config.json | Has directory, script, port, enabled |
| BotProcess | Running bot subprocess | Tied to Bot config, has PID, start_time, restart_count |
| User (Telegram) | End user of a bot | Interacts via Telegram; some bots have allowlists |
| Channel | Telegram channel | Index Bot monitors; Caption/Name Bot add captions in channels |

---

## Glossary

| Term | Meaning |
|------|---------|
| Launcher | `bot_launcher.py` – CLI that starts/stops/monitors bot processes |
| Dashboard | Flask web app in `dashboard.py` – web UI for launcher |
| MTProto | Telegram’s native protocol; used by TG Download Bot for premium-speed downloads |
| Premium account | Telegram Premium; used by TG Download Bot for higher speed/limits |

---

## Current State Assessment

**What's Working:**
- Launcher with menu, dependency checks, multi-bot start/stop/restart, monitoring, stats
- Dashboard on port 5000 with bot cards and controls
- Six bots present with READMEs and requirements; config lists all six

**What's Incomplete (WIP):**
- Some bots are under development; others are ready to use. Root README has been updated to describe launcher and all bots.

**What's Broken:**
- Nothing clearly broken from docs/code structure. No runtime verification done in recovery.

**Technical Debt Observed:**
- Launcher stats are in-memory only; persistence (e.g. logging or JSON) can be planned for later.
- Many untracked docs in bot dirs (e.g. TG_download_bot, name-bot); no single docs index.
- Download Bot directory name `down_oad_bot` is intentional (not a typo).

---

## Resolved Questions

Answered questions are recorded in `docs/decisions/DECISIONS.md`. Summary: `docs/RECOVERY_COMPLETE.md`.

---
*Status: Context Recovery Complete*  
*Next: /map*
