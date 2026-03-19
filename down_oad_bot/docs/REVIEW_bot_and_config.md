# Review: bot.py & config.py (down_oad_bot)

## Summary

The main bot and config are consistent with project conventions and work as documented. A few improvements would harden callback parsing, reduce dead code, and align with the “no file server in repo” decision. No blocking bugs; one encoding edge case and several small cleanups recommended.

---

### Critical (Must Fix)

*None.* No issues that prevent correct operation under normal use.

---

### Important (Should Fix)

| Issue | Location | Problem | Fix |
|-------|----------|---------|-----|
| **Callback format_id with underscore** | `bot.py` ~441, ~373, ~551 | Callback data is built as `dl_{platform}_{format}_{format_id}_{url_hash}` and parsed with `split("_")`. `format_id` is only encoded for `+` and `/`. If yt-dlp ever returns a format_id containing `_` (e.g. `137_2`), the string would split into more than 5 parts and `parts[4]` would no longer be the 12-char url_hash, so lookups could fail or use the wrong key. | Encode `_` in format_id (e.g. `format_id.replace('_', 'US')`) when building callback_data and decode when parsing (`format_id_encoded.replace('US', '_')`). Use a token that cannot appear in a real format_id (e.g. `_` → `UNDERSCORE`). |
| **Unused config imports in bot** | `bot.py` 25–27 | `ENABLE_FILE_SERVER`, `FILE_SERVER_PORT`, `FILE_SERVER_HOST` are imported from config but never used in `bot.py` (file server not implemented). | Remove these three from the `config` import in `bot.py` until the file server is implemented. Reduces confusion and matches DECISIONS (file server “planned”). |
| **DOWNLOAD_DIR creation at import** | `config.py` 33–34 | `DOWNLOAD_DIR.mkdir(exist_ok=True)` runs at import. If the path is read-only or permissions fail, the process fails at import with no clear message. | Either keep as-is and document in README, or wrap in try/except and log a warning (and let it fail at first download). Optional: create directory on first use in downloaders instead of at config load. |

---

### Suggestions (Nice to Have)

| Suggestion | Location | Details |
|------------|----------|---------|
| **Avoid redundant asyncio import** | `bot.py` 790, 833, 937 | `asyncio` is imported at top (line 5) but re-imported inside `handle_upload_choice` and `upload_playlist_queue`. | Remove the inner `import asyncio` lines; use the top-level import. |
| **Make URLs cap configurable** | `bot.py` 310–315 | Magic number `10` for max URL entries. | Add e.g. `USER_DATA_URLS_MAX_ENTRIES` in config and use it here (see `docs/URLS_RETENTION.md`). |
| **Defensive access to url_data** | `bot.py` 566–568, 602+ | `url_data['url']`, `url_data['platform']` assume keys exist. Corrupted or legacy entries could raise KeyError. | Use `url_data.get('url')` / `url_data.get('platform')` with a check or fallback before using, and show “Request expired” if required keys are missing. |

---

### What's Good

- Authorization is checked at the start of every user-facing handler; unauthorized users get a clear message.
- Callback data uses a short hash to stay under Telegram’s 64-byte limit; encoding for `+` and `/` in format_id is in place.
- Error handler covers Conflict, NetworkError, TimedOut; other errors are logged with exc_info.
- Download/upload paths use Path and check existence before upload; file size is checked against Telegram’s 4GB limit.
- Playlist upload runs in a background task so the handler returns quickly; progress and retries are implemented.
- Logging is consistent (`logger = logging.getLogger(__name__)`); docstrings on main helpers (e.g. `is_user_authorized`, `check_authorization`).
- Conventions match CODEBASE_MAP: single config module, downloaders dict, callback format documented.

---

### Checklist

- [x] Conventions followed (config, downloaders, callbacks, logging)
- [x] Code style matches project (async handlers, Path, try/except with user-facing messages)
- [x] Error handling present (auth, network, download, upload, expired callback)
- [x] No unnecessary complexity
- [x] Plan goals met (context recovery and DECISIONS; no active feature plan in this review)

---

### Verdict

- [x] **Ready to ship** for current scope (with or without the “Important” fixes; recommend doing at least the format_id underscore encoding and removing unused file-server imports).
- [ ] Needs fixes → /iterate (optional: apply Important items)
- [ ] Needs significant rework
- [ ] Needs tests first

**Recommendation:** Apply the format_id underscore encoding and remove the three unused file-server imports from `bot.py`. Then treat as ready to ship; other items can be done in a follow-up pass.
