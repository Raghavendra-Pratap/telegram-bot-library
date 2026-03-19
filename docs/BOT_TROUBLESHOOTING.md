# Bot troubleshooting: “Running but not working”

When bots are started via the launcher they can be “running” (process is up) but not behave as expected. Use this checklist and your logs to fix it.

---

## 1. Each bot must have its own token

- **name-bot** and **down_oad_bot** (and every other bot) must use **different** Telegram bot tokens.
- If two processes use the same token, only one gets updates; the other will never react.
- **Check:** In each bot folder, open `.env` and ensure `TELEGRAM_BOT_TOKEN` is set and **different** per bot.
- Create separate bots in [@BotFather](https://t.me/BotFather) if needed (e.g. one for “caption”, one for “download”).

---

## 2. Name bot (filename as caption in channels/groups)

**Expected behavior:** When someone uploads a file in a channel or group, the bot edits the message and adds the filename as caption.

### Checklist

| Check | What to do |
|-------|------------|
| **Bot is admin** | In the channel/group: Channel/Group info → Administrators → add your bot as admin. |
| **“Edit messages” permission** | In the same place, ensure the bot has **“Edit messages of others”** (or “Edit messages”) enabled. Without this, edits fail. |
| **Correct token** | `name-bot/.env` → `TELEGRAM_BOT_TOKEN` must be the token of the bot you added as admin. |
| **User verification** | If `ENABLE_USER_VERIFICATION=true`, only `ALLOWED_USER_IDS` can use the bot. For channel posts, the “user” may be missing; the code allows that when verification is off. Prefer `ENABLE_USER_VERIFICATION=false` while testing. |
| **Auto-shutdown** | name-bot has **idle auto-shutdown** (e.g. 12 minutes). After that, the process exits and stops reacting. For “always on” use, set in `name-bot/.env`: `ENABLE_AUTO_SHUTDOWN=false`. |

### Logs

- Launcher log file: `logs/name_bot.log`
- After uploading a file in the channel/group you should see lines like “Processing…”, “Successfully added caption”, or errors.

**Typical errors:**

- “Forbidden: bot can't edit message” → Bot is not admin or doesn’t have “Edit messages” permission.
- “Unauthorized” / “401” → Wrong or expired token in `.env`.
- No log lines when you upload → Bot not getting updates (wrong token, or another process using same token).

---

## 3. Download bot (down_oad_bot) – download links sent to the bot

**Expected behavior:** You send a supported video link (e.g. YouTube, Reddit, Twitter) **to the bot** (e.g. in a private chat with the bot). The bot replies with download options or the file.

### Checklist

| Check | What to do |
|-------|------------|
| **Correct token** | `down_oad_bot/.env` → `TELEGRAM_BOT_TOKEN` is the token of the bot you’re messaging. |
| **Where you send the link** | Send the link **to the bot** (e.g. open chat with the bot, paste link there). In groups, the bot must be a member and will react to messages that contain links. |
| **Supported link** | YouTube, Reddit, Twitter/X, Instagram, etc. Unsupported URLs are ignored or may log “Unsupported”. |
| **No conflict** | Only one process must run with this bot’s token. If the same token is used elsewhere (another script or bot), stop it so this bot can poll. |

### Logs

- Launcher log file: `logs/download_bot.log`
- When you send a link you should see handling of the message and the URL; errors (e.g. download failed, unsupported URL) will appear there.

**Typical errors:**

- No reaction at all → Wrong token, or another process using same token (Conflict), or bot not receiving updates.
- “Conflict” in logs → Another instance of the same bot is running; stop all other instances and restart.

---

## 4. Quick checks that apply to all bots

1. **Logs**  
   From the project root:
   - `tail -f logs/name_bot.log`
   - `tail -f logs/download_bot.log`  
   Reproduce the action (upload a file / send a link) and watch for new lines or errors.

2. **.env in the right place**  
   Each bot loads `.env` from **its own directory** (e.g. `name-bot/.env`, `down_oad_bot/.env`). The launcher starts the bot with that directory as the working directory, so ensure the correct `.env` is there and has the right `TELEGRAM_BOT_TOKEN`.

3. **Run one bot by itself (no launcher)**  
   To see all output in the terminal and rule out launcher issues:
   ```bash
   cd name-bot
   . venv/bin/activate   # or: source venv/bin/activate
   python bot.py
   ```
   Then upload a file in a channel where the bot is admin with “Edit messages”. Same idea for `down_oad_bot`: run `python bot.py` in `down_oad_bot` and send a link to the bot.

4. **Telegram status**  
   In [@BotFather](https://t.me/BotFather), open the bot and ensure it’s not disabled or restricted in a way that would block updates.

---

## 5. Summary table

| Bot | Main requirement | Common fix |
|-----|------------------|------------|
| **name-bot** | Admin in channel/group with **“Edit messages”**; correct token; consider `ENABLE_AUTO_SHUTDOWN=false` | Add bot as admin with edit permission; check `logs/name_bot.log` |
| **down_oad_bot** | Correct token; send link **to the bot**; only one process per token | Check token in `down_oad_bot/.env`; stop duplicate processes; check `logs/download_bot.log` |

After changing `.env`, **restart the bot** (stop from launcher, then start again, or restart the launcher).
