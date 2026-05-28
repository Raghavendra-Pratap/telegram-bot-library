# Index Bot — Complete Termux Setup Guide

This guide walks you through installing and running **Index_bot** on an Android phone or tablet using **[Termux](https://termux.dev/)**, from a blank Termux install to a bot that stays running in the background.

**Time estimate:** 30–60 minutes the first time (mostly waiting on downloads and Telegram setup).

**What you need before you start:**

| Item | Why |
|------|-----|
| Android device with Termux | The “server” |
| Stable Wi‑Fi or mobile data | Bot talks to Telegram constantly |
| A second device or PC (optional) | Easier to copy tokens and edit long `.env` lines |
| Telegram account | Bot token, your user ID, optional user login for history import |

---

## Table of contents

1. [Install Termux correctly](#1-install-termux-correctly)
2. [First-time Termux setup](#2-first-time-termux-setup)
3. [Get the bot code onto your phone](#3-get-the-bot-code-onto-your-phone)
4. [Python virtual environment and dependencies](#4-python-virtual-environment-and-dependencies)
5. [Create your Telegram bot (BotFather)](#5-create-your-telegram-bot-botfather)
6. [Get your Telegram user ID](#6-get-your-telegram-user-id)
7. [Telegram API credentials (for history import)](#7-telegram-api-credentials-for-history-import)
8. [Optional: TMDB API key](#8-optional-tmdb-api-key)
9. [Create and edit `.env`](#9-create-and-edit-env)
10. [Verify everything before starting](#10-verify-everything-before-starting)
11. [Start the bot (foreground test)](#11-start-the-bot-foreground-test)
12. [Run the bot in the background (production)](#12-run-the-bot-in-the-background-production)
13. [Keep Termux alive on Android](#13-keep-termux-alive-on-android)
14. [Use `tmux` so SSH disconnect does not kill the bot](#14-use-tmux-so-ssh-disconnect-does-not-kill-the-bot)
15. [Auto-start after phone reboot (optional)](#15-auto-start-after-phone-reboot-optional)
16. [Telegram: add channels and test commands](#16-telegram-add-channels-and-test-commands)
17. [Historical import (old posts) on Termux](#17-historical-import-old-posts-on-termux)
18. [Optional: PostgreSQL instead of SQLite](#18-optional-postgresql-instead-of-sqlite)
19. [Updating the bot later](#19-updating-the-bot-later)
20. [Stopping and restarting](#20-stopping-and-restarting)
21. [Troubleshooting on Termux](#21-troubleshooting-on-termux)
22. [Quick reference cheat sheet](#22-quick-reference-cheat-sheet)

---

## 1. Install Termux correctly

**Do not** install Termux from the Google Play Store — that build is outdated and often broken.

1. Install **[F-Droid](https://f-droid.org/)** on your Android device.
2. In F-Droid, search for **Termux** and install it.
3. Open Termux once so it can create its home directory (`~/`).

You will do almost all work inside the Termux terminal (black screen with a `$` prompt).

---

## 2. First-time Termux setup

Open Termux and run these commands **one block at a time**. Wait for each to finish before the next.

### 2.1 Update package lists and upgrade

```bash
pkg update -y && pkg upgrade -y
```

If Termux asks to confirm replacing packages, type `y` and Enter.

### 2.2 Install required system packages

```bash
pkg install -y python git build-essential libffi openssl procps curl tmux
```

| Package | Purpose |
|---------|---------|
| `python` | Runs the bot |
| `git` | Clone the repository |
| `build-essential`, `libffi`, `openssl` | Build some Python wheels if needed |
| `procps` | `ps`, `grep` used by helper scripts |
| `curl` | Download files / sanity checks |
| `tmux` | Keep the bot running when you close Termux |

### 2.3 (Recommended) Allow Termux to access shared storage

Useful if you copy a zip of the project from Downloads:

```bash
termux-setup-storage
```

Tap **Allow** on the Android permission dialog. Your shared storage is then available at:

```text
~/storage/shared/
```

(e.g. `~/storage/shared/Download/`)

### 2.4 Create a projects folder

```bash
mkdir -p ~/projects
cd ~/projects
pwd
```

You should see something like `/data/data/com.termux/files/home/projects`.

---

## 3. Get the bot code onto your phone

Pick **one** method.

### Method A — Git clone (recommended if the repo is on GitHub/GitLab)

Replace the URL with your real repository URL:

```bash
cd ~/projects
git clone https://github.com/YOUR_USER/Telegram_Bot_Library.git
cd Telegram_Bot_Library/Index_bot
pwd
```

If the repo is **private**, use a personal access token in the URL or set up SSH keys in Termux (`pkg install openssh`, then `ssh-keygen`).

Expected path when done:

```text
~/projects/Telegram_Bot_Library/Index_bot
```

### Method B — Copy only the `Index_bot` folder

If you zip `Index_bot` on your PC and copy it to the phone (USB, Google Drive, etc.):

1. Put the zip in Downloads on the phone.
2. In Termux:

```bash
cd ~/projects
cp ~/storage/shared/Download/Index_bot.zip .
unzip Index_bot.zip
cd Index_bot
```

You need **all** core Python files (`bot.py`, `config.py`, `database.py`, etc.) and `requirements.txt`. Do **not** copy `.env` from your PC if it contains secrets you might leak; create a fresh `.env` on the phone (step 9).

### Method C — `scp` from your computer

From your **computer** (not Termux), if Termux SSH is enabled:

```bash
scp -r /path/to/Index_bot u0_a123@PHONE_IP:~/projects/Index_bot
```

Find Termux’s user and IP with `whoami` and `ifconfig` inside Termux after `pkg install openssh` and `sshd`.

---

## 4. Python virtual environment and dependencies

**Recommended (same as name-bot):** clone the **full** `Telegram_Bot_Library` repo and use the **shared** `.venv` at the repo root. Helper scripts auto-install missing packages.

```bash
cd ~/projects/Telegram_Bot_Library
./scripts/setup_env.sh
./scripts/install_deps.sh index
```

Then run Index_bot (deps are re-checked and installed if needed):

```bash
cd Index_bot
chmod +x run_bot.sh start_bot.sh stop_bot.sh ensure_env.sh
./run_bot.sh
```

`run_bot.sh` / `start_bot.sh` call `ensure_env.sh`, which mirrors **bot_launcher.py**: create `.venv` if missing, run `install_deps.sh index` if imports fail.

### 4.1 Manual path (full monorepo)

```bash
cd ~/projects/Telegram_Bot_Library
source .venv/bin/activate
cd Index_bot
python check_readiness.py
python bot.py
```

### 4.2 Standalone `Index_bot` folder only (no parent `scripts/`)

If you copied **only** `Index_bot` (no monorepo), `ensure_env.sh` falls back to a **local** `Index_bot/venv` and `pip install -r requirements.txt`.

```bash
cd ~/projects/Index_bot
chmod +x run_bot.sh ensure_env.sh
./run_bot.sh
```

Or install manually:

```bash
python -m venv venv && source venv/bin/activate
pip install --upgrade pip wheel
pip install "python-telegram-bot>=22.5" "python-dotenv>=1.0.0" \
  "sqlalchemy>=2.0.36" "tmdbv3api==1.2.0" "regex==2023.10.3" \
  "telethon>=1.36.0" "psycopg[binary]>=3.1.18"
```

If `pip install` fails to build a wheel, run `pkg install -y clang` and retry.

### 4.3 Launcher on Termux (optional)

From repo root:

```bash
./scripts/setup_env.sh
python bot_launcher.py
```

Start **Index Bot** from the menu — same auto dependency install as name-bot.

### 4.4 Make shell scripts executable (optional)

```bash
chmod +x run_bot.sh start_bot.sh stop_bot.sh ensure_env.sh stop_all_bots.sh check_bot_processes.sh
```

On Termux, `stop_bot.sh` may not find `lsof` unless you install it: `pkg install -y lsof`. If stop scripts fail, use the manual stop commands in [section 20](#20-stopping-and-restarting).

---

## 5. Create your Telegram bot (BotFather)

Do this in the **Telegram app** (phone or desktop), not in Termux.

1. Open Telegram and search for **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot`.
3. Choose a **display name** (e.g. `My Library Index`).
4. Choose a **username** ending in `bot` (e.g. `my_library_index_bot`).
5. BotFather replies with a token like:

   ```text
   7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

6. **Copy that entire string** — that is your `BOT_TOKEN`. Treat it like a password.

Optional but useful:

- `/setprivacy` → **Disable** if the bot must see all messages in groups (usually you use **channels**, so privacy mode matters less there).
- `/setdescription` — short description for users.

---

## 6. Get your Telegram user ID

You need your numeric ID for admin commands (`/pending`, channel management, etc.).

1. Open **[@userinfobot](https://t.me/userinfobot)** in Telegram.
2. Send `/start`.
3. It replies with **Id:** `123456789` (your number).

That number goes in `.env` as `ADMIN_USER_IDS`. Multiple admins: comma-separated, no spaces:

```text
ADMIN_USER_IDS=111111111,222222222
```

---

## 7. Telegram API credentials (for history import)

Required if you will use **historical ingest** (`forward_ingest.py`, `/discover_channels`, `discover_bot_channels.py`). The main bot (`bot.py`) only **strictly** needs `BOT_TOKEN` and `ADMIN_USER_IDS`, but you should still set these before running Telethon tools.

1. On a browser, log in at **[https://my.telegram.org](https://my.telegram.org)** with your **user** account (not the bot).
2. Open **API development tools**.
3. Create an application (any name / platform).
4. Note:
   - **api_id** → integer, e.g. `12345678`
   - **api_hash** → long hex string

Put them in `.env` as `API_ID` and `API_HASH`.

---

## 8. Optional: TMDB API key

Improves title matching and metadata.

1. Create an account at [themoviedb.org](https://www.themoviedb.org/).
2. Go to **Settings → API** and request an API key (Developer type is enough).
3. Add to `.env`:

   ```text
   TMDB_API_KEY=your_key_here
   ```

Leave empty to run without TMDB (parsing still works, with less validation).

---

## 9. Create and edit `.env`

Still in `Index_bot` (with repo `.venv` or local `venv` activated):

### 9.1 Copy the template

```bash
cd ~/projects/Telegram_Bot_Library/Index_bot
cp .env.example .env
```

### 9.2 Edit `.env`

Termux has several editors. Pick one:

**nano (easiest for beginners):**

```bash
nano .env
```

- Edit values after the `=` signs.
- Save: **Ctrl+O**, Enter, then exit: **Ctrl+X**.

**vim:**

```bash
vim .env
```

### 9.3 Minimum `.env` to run the bot

```env
BOT_TOKEN=7123456789:AAH_your_real_token_from_botfather
ADMIN_USER_IDS=123456789

API_ID=12345678
API_HASH=your_api_hash_from_my_telegram_org

TMDB_API_KEY=

DB_PATH=index_bot.db
```

### 9.4 Optional variables (explain when you need them)

| Variable | When to set |
|----------|-------------|
| `DATABASE_URL` | You run PostgreSQL (advanced; see [section 18](#18-optional-postgresql-instead-of-sqlite)). If set, `DB_PATH` is ignored. |
| `WATCH_CHANNEL_ID` | Public “watch” channel ID (negative number like `-1001234567890`) for publishing cards. |
| `AUTO_PUBLISH_WATCH` | `true` to auto-publish to watch channel when configured. |
| `FORWARD_INGEST_SESSION` | Custom path/name for Telethon session file (default `forward_ingest.session`). |
| `TELEGRAM_*`, `JOB_*`, `WATCH_CATALOG_*` | Tune rate limits and workers on large channels (defaults are fine to start). |

**Security:**

- Never commit `.env` to git.
- Never share `BOT_TOKEN`, `API_HASH`, or `*.session` files.

### 9.5 Interactive alternative

```bash
source venv/bin/activate
python create_env.py
```

Answer the prompts in the terminal. Use this only in an **interactive** Termux session (not over a non-interactive SSH runner).

---

## 10. Verify everything before starting

```bash
cd ~/projects/Telegram_Bot_Library/Index_bot
./run_bot.sh   # installs deps if needed, then readiness + bot
# or: source ../.venv/bin/activate && python check_readiness.py
```

Fix anything marked **FAIL**:

- Missing packages → repeat [section 4](#4-python-virtual-environment-and-dependencies).
- `.env` invalid → check `BOT_TOKEN` and `ADMIN_USER_IDS` in [section 9](#9-create-and-edit-env).
- Database error → check `DB_PATH` is writable in this folder, or fix `DATABASE_URL`.

You want: **“All checks passed! Bot is ready to run.”**

---

## 11. Start the bot (foreground test)

**Bot + portal together (background):**

```bash
cd ~/projects/Telegram_Bot_Library/Index_bot
chmod +x run_all.sh stop_all.sh
./run_all.sh
```

Logs: `bot.log`, `portal.log`. Stop: `./stop_all.sh`. See [DEPLOYMENT.md](./DEPLOYMENT.md).

**Foreground bot only** (see errors immediately):

```bash
cd ~/projects/Telegram_Bot_Library/Index_bot
./run_bot.sh
# or: source ../.venv/bin/activate && python bot.py
```

**Success looks like:**

```text
============================================================
🚀 Bot starting...
============================================================
INFO:__main__:✅ No webhook found, using polling mode
INFO:telegram.ext.Application:Application started
```

In Telegram, open **your bot** (the username from BotFather) and send:

```text
/start
```

As admin you should also try:

```text
/list_channels
/stats
```

Stop the test with **Ctrl+C** in Termux.

**If you see `409 Conflict`:** another copy of the bot is already polling. Stop it ([section 20](#20-stopping-and-restarting)) and wait 10–15 seconds.

---

## 12. Run the bot in the background (production)

After a successful foreground test:

```bash
cd ~/projects/Telegram_Bot_Library/Index_bot
source venv/bin/activate
nohup python bot.py >> bot.log 2>&1 &
echo $! > .bot.pid
```

Check it is running:

```bash
ps aux | grep bot.py | grep -v grep
tail -n 30 bot.log
```

Follow logs live:

```bash
tail -f bot.log
```

Stop following logs with **Ctrl+C** (the bot keeps running).

---

## 13. Keep Termux alive on Android

Android aggressively kills background apps. For a 24/7 “server” on a phone:

1. **Disable battery optimization** for Termux  
   Android Settings → Apps → Termux → Battery → **Unrestricted** (wording varies by manufacturer).

2. **Keep Wi‑Fi on during sleep** (Settings → Wi‑Fi → Advanced → keep connected).

3. Leave the device **plugged in** if possible.

4. Acquire a partial wake lock while the bot runs (install Termux:API from F-Droid if needed):

   ```bash
   pkg install termux-api
   termux-wake-lock
   ```

   Release when you intentionally stop the bot:

   ```bash
   termux-wake-unlock
   ```

5. Pin Termux in **recent apps** and avoid “Force stop” on Termux.

6. Some OEMs (Xiaomi, Huawei, etc.) need **autostart** permission for Termux in their security app.

---

## 14. Use `tmux` so SSH disconnect does not kill the bot

`tmux` is more reliable than `nohup` alone on Termux.

```bash
cd ~/projects/Telegram_Bot_Library/Index_bot
tmux new -s indexbot
source venv/bin/activate
python bot.py
```

Detach (bot keeps running): press **Ctrl+B**, then **D**.

Later, reattach:

```bash
tmux attach -t indexbot
```

List sessions:

```bash
tmux ls
```

---

## 15. Auto-start after phone reboot (optional)

Requires **[Termux:Boot](https://github.com/termux/termux-boot)** from F-Droid.

1. Install **Termux:Boot** and open it once.
2. Create the boot script:

```bash
mkdir -p ~/.termux/boot
nano ~/.termux/boot/index-bot.sh
```

Paste (adjust the path if yours differs):

```bash
#!/data/data/com.termux/files/usr/bin/bash
sleep 30
cd /data/data/com.termux/files/home/projects/Telegram_Bot_Library/Index_bot
source venv/bin/activate
termux-wake-lock
nohup python bot.py >> bot.log 2>&1 &
echo $! > .bot.pid
```

Save, then:

```bash
chmod +x ~/.termux/boot/index-bot.sh
```

Reboot the phone once to test. Check `bot.log` after boot.

---

## 16. Telegram: add channels and test commands

### 16.1 Add the bot to a channel

1. Create or open a **channel** with media you want indexed.
2. **Channel → Manage → Administrators → Add administrator**.
3. Add **your bot**.
4. Permissions: at minimum allow it to **read** / see posts. It does not need to post unless you use a watch/ingest workflow that requires posting.

### 16.2 Register the channel with the bot

As your admin user, message the bot:

```text
/add_channel @YourChannelUsername
```

Or post once in the channel after the bot is admin — many setups **auto-register** on first post.

Verify:

```text
/list_channels
```

### 16.3 User vs admin commands

| Command | Who |
|---------|-----|
| `/start`, `/search`, `/library`, `/list_channels`, `/stats` | Everyone |
| `/add_channel`, `/remove_channel`, `/pending`, `/confirm`, `/backfill`, admin menus | Users listed in `ADMIN_USER_IDS` only |

---

## 17. Historical import (old posts) on Termux

The Bot API **cannot** read old channel messages. Index_bot uses **your Telegram user account** (Telethon) to forward old files into an **ingest channel** where the bot is admin.

### 17.1 Setup in Telegram

1. **Source channel** — archive with old uploads. Your **user** account must be able to open it and forward from it.
2. **Ingest channel** — empty channel used only for imports. Add **Index_bot as administrator** (read messages).
3. Register ingest channel: `/add_channel @YourIngestChannel` (or let it auto-register on first forward).
4. Keep **`bot.py` running** ([section 12](#12-run-the-bot-in-the-background-production)) while importing.

### 17.2 Log in Telethon once (interactive)

```bash
cd ~/projects/Telegram_Bot_Library/Index_bot
source venv/bin/activate
python telethon_login.py
```

Enter phone number, login code, and 2FA password if enabled. This creates `forward_ingest.session` in the project folder. **Back up this file privately** — it is your account session.

### 17.3 Dry run (count only)

```bash
python forward_ingest.py @SourceChannel @IngestChannel --dry-run
```

### 17.4 Real import

```bash
python forward_ingest.py @SourceChannel @IngestChannel --delay 2.0
```

Useful flags: `--limit N`, `--batch-size 15`. If Telegram rate-limits you, increase `--delay`.

### 17.5 Discover all channels where the bot is admin

```bash
python discover_bot_channels.py
```

Or in Telegram (admin): `/discover_channels`

Requires the same Telethon session as above.

---

## 18. Optional: PostgreSQL instead of SQLite (no Docker)

**Default on Termux:** SQLite via `DB_PATH=index_bot.db` — no extra services.

Use **native PostgreSQL** when uploads, ingest, portal, and pipeline jobs hit `database is locked` on SQLite, or when bot + portal write at the same time. This project does **not** require Docker — only the Termux `postgresql` package.

### 18.1 Install and create DB

```bash
cd ~/projects/Telegram_Bot_Library/Index_bot
chmod +x scripts/setup_postgres_termux.sh
./scripts/setup_postgres_termux.sh
```

The script prints a `DATABASE_URL=postgresql+psycopg://...` line. Add it to `.env` (same value for bot and portal).

Optional overrides before running the script:

```bash
export INDEX_PG_USER=index_user
export INDEX_PG_PASS='your_strong_password'
export INDEX_PG_DB=index_bot
```

URL-encode special characters in passwords (`@`, `#`, etc.) if you edit `.env` by hand.

### 18.2 Migrate existing SQLite data

**Stop the bot and portal first** (section 20).

```bash
source venv/bin/activate
pip install 'psycopg[binary]>=3.1'
python scripts/migrate_sqlite_to_postgres.py
```

Keep `index_bot.db` as a backup until you have verified uploads, pending queue, and portal admin.

### 18.3 Telethon: two sessions (no lock between bot and portal)

| Session file | Used by | Login command |
|--------------|---------|----------------|
| `forward_ingest.session` | Bot gateway (uploads, routes, member watch) | `python telethon_login.py` |
| `forward_ingest_portal.session` (default) | Portal Play / streaming | `python telethon_login_portal.py` |

Set `TELETHON_GATEWAY_ENABLED=true` (default) so the bot uses one shared Telethon client instead of many clones.

Restart bot and portal after changing `.env` or sessions.

---

## 19. Updating the bot later

```bash
cd ~/projects/Telegram_Bot_Library/Index_bot
# stop bot first — section 20
git pull
source venv/bin/activate
pip install -r ../requirements/bot-index.txt
python check_readiness.py
# start bot again — section 12 or 14
```

If you copied files manually, replace the folder and **keep** your `.env`, `*.db`, and `*.session` files.

---

## 20. Stopping and restarting

### Stop (background)

```bash
cd ~/projects/Telegram_Bot_Library/Index_bot
./stop_bot.sh
```

Or manually:

```bash
pkill -f "bot.py"
rm -f .bot.pid
termux-wake-unlock
```

Wait **10–15 seconds** before starting again (avoids Telegram `409 Conflict`).

### Start again

```bash
source venv/bin/activate
nohup python bot.py >> bot.log 2>&1 &
echo $! > .bot.pid
```

Or use `tmux` ([section 14](#14-use-tmux-so-ssh-disconnect-does-not-kill-the-bot)).

---

## 21. Troubleshooting on Termux

| Problem | What to do |
|---------|------------|
| `command not found: python` | Run `pkg install python`, use `python` not `python3` if only one exists |
| `venv/bin/activate: No such file` | Create venv: `python -m venv venv` from `Index_bot` directory |
| `pip install` fails building wheel | `pkg install -y clang rust` then retry |
| `409 Conflict` | Only one `bot.py` with this `BOT_TOKEN`; `pkill -f bot.py`, wait, restart |
| Bot starts then dies | `tail -50 bot.log`; often invalid `BOT_TOKEN` or network drop |
| `ModuleNotFoundError` | Activate venv, reinstall requirements ([section 4](#4-python-virtual-environment-and-dependencies)) |
| Admin commands ignored | Your Telegram ID must match `ADMIN_USER_IDS` exactly |
| Telethon login fails | Check `API_ID` / `API_HASH`; run `python telethon_login.py` in interactive Termux |
| `check_readiness` psycopg fail | `pip install "psycopg[binary]>=3.1.18"` |
| Android killed Termux | Battery unrestricted, wake lock, tmux, keep charger connected |
| `stop_bot.sh` errors on `lsof` | `pkg install lsof` or use `pkill -f bot.py` |
| Database locked (SQLite) | Only one bot instance; do not copy `index_bot.db` while bot is writing |

---

## 22. Quick reference cheat sheet

```bash
# Every new Termux session
cd ~/projects/Telegram_Bot_Library/Index_bot
source venv/bin/activate

# Check config
python check_readiness.py

# Foreground run (testing)
python bot.py

# Background run
nohup python bot.py >> bot.log 2>&1 &
echo $! > .bot.pid

# Logs
tail -f bot.log

# Stop
pkill -f "bot.py"

# Telethon login (once)
python telethon_login.py

# History import
python forward_ingest.py @Source @Ingest --delay 2.0
```

**Files you must protect**

| File | Contains |
|------|----------|
| `.env` | Bot token, API secrets |
| `forward_ingest.session` | Your Telegram user session |
| `index_bot.db` | All indexed data (if using SQLite) |

---

## Related docs in this repo

- [HOW_TO_RUN.md](HOW_TO_RUN.md) — general run/stop, PostgreSQL, ingest details
- [.env.example](.env.example) — every environment variable
- [README.md](README.md) — features and command list

If something in this guide does not match your tree (paths or script names), run `ls` in your `Index_bot` folder and compare with the paths above.
