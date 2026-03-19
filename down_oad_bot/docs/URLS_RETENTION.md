# URLs retention – how it works

This doc explains how the bot stores and trims URL-related state per user, and what you can tune.

---

## What is “URLs retention”?

When a user sends a link, the bot:

1. **Stores** the URL (and later the file path) in **per-user in-memory state**: `context.user_data['urls']`.
2. Uses a **short key** (12‑char hash) so Telegram’s inline buttons can reference it (callback_data is limited to 64 bytes).
3. **Trims** that map so each user keeps only the **last 10 entries**.

So “URLs retention” = **how many of these entries we keep per user** (and for how long). It does **not** limit:

- Number of files on disk
- Size of downloaded files
- How many links a user can send in total

---

## Where it lives

| What | Where |
|------|--------|
| Store | `context.user_data['urls']` (dict: hash → entry) |
| Trim logic | `bot.py` in `handle_url`, right before storing a new URL (lines ~310–315) |
| Lookup | `handle_callback` and `handle_upload_choice` when the user taps a button |

State is **in-memory only**. It is lost on bot restart. There is no database or file backing this.

---

## When entries are added

Roughly:

| Step | What gets stored | Key |
|------|-------------------|-----|
| User sends URL | One entry per link | `url_hash = md5(url)[:12]` |
| User taps “Download” (single file) | Two extra entries for “Upload” / “Keep local” | `md5(url_hash + "_upload")[:12]`, `md5(url_hash + "_local")[:12]` |
| User taps “Download playlist” | Same: upload + local keys for the playlist | Same pattern with `_upload_playlist`, `_local_playlist` |

So **one link** can end up as **1 or 3 entries** (1 for the link, 2 after download for the two buttons). If a user sends several links and downloads each, the count grows quickly (e.g. 4 links → 4 + 8 = 12 entries).

---

## How the trim works (current “last 10”)

**When:** Only in `handle_url`, when the user sends a **new** URL.

**Condition:** `if len(context.user_data['urls']) > 10`

**Action:** Remove oldest entries so that only **10 remain** (by insertion order, so the 10 most recently added are kept).

```python
# bot.py (handle_url)
if len(context.user_data['urls']) > 10:
    keys_to_remove = list(context.user_data['urls'].keys())[:-10]  # all but last 10
    for key in keys_to_remove:
        del context.user_data['urls'][key]
```

So:

- We never trim **during** a flow (e.g. when they tap “Download” or “Upload”).
- We trim only when they send another link and the map is already bigger than 10.
- “Oldest” = first inserted; “last 10” = the 10 most recently added entries.

---

## What happens when an entry is gone?

If the user taps a button whose key was already removed (e.g. an old “Download” or “Upload to Telegram”):

- Lookup fails: `url_hash not in context.user_data['urls']`.
- They see: **“Request expired or invalid. Please send the link again.”**

So the only effect of trimming is that **old buttons can expire** once we’ve kept more than 10 newer entries. The files on disk are unchanged; they just can’t use that button to upload or see the path again without resending the link.

---

## Why cap at 10?

1. **Telegram callback_data** is 64 bytes; we can’t put the full URL in the button, so we store it in memory and use a short hash. That forces a server-side store.
2. **Memory:** Each entry is small (URL string, platform, title, maybe file path and playlist paths). Even hundreds of entries per user would be modest, but with no expiry and no limit, a long-running bot could grow.
3. **Simplicity:** A fixed “last 10” is easy and avoids implementing TTL or LRU. The downside is that a user who sends many links and then goes back to an old message can hit “Request expired” after we’ve trimmed.

So 10 is a **conservative default** to avoid unbounded growth; it’s not a technical requirement.

---

## Per-entry size (rough)

Each entry is a dict, for example:

- `url`: str (can be long, e.g. 100–200 chars)
- `platform`: str (short)
- `title`: str (we store up to 60 chars)
- After download: `file_path`, `format_type`; for playlists: `all_files` (list of paths), `playlist_folder`

So on the order of **hundreds of bytes to a few KB per entry**. 10 entries ≈ few KB per user. Even 100–500 entries per user would still be small unless you have huge numbers of users.

---

## Options if you want to change behaviour

| Option | Pros | Cons |
|--------|------|------|
| **Increase the cap** (e.g. 30 or 50) | Fewer “Request expired” for users who send many links. | Slightly more memory per user; still bounded. |
| **Remove the cap** | Buttons never expire from trimming. | Unbounded growth per user (need to watch memory over time). |
| **Time-based expiry** (e.g. remove entries older than 1 hour) | Old buttons expire in a predictable way. | More code (store timestamp, cleanup on access or on a job). |
| **LRU / “least recently used”** | Keep the N most recently **used** entries, not just “last N added”. | More code; need to touch entries on each button click. |

Recommendation: if users often hit “Request expired” after sending several links, **increase the cap** (e.g. 30). If you’re fine with the current behaviour, keep 10. If you later need stricter control, add time-based expiry or LRU.

---

## Making the limit configurable (optional)

You can move the magic number into config and document it:

1. In `config.py`: e.g. `USER_DATA_URLS_MAX_ENTRIES = int(os.getenv("USER_DATA_URLS_MAX_ENTRIES", "10"))`
2. In `bot.py`: replace `if len(...) > 10` and `[:-10]` with that constant.
3. In `env_template.txt` and docs: describe the variable (max stored URL entries per user; old buttons may show “Request expired” when over limit).

That way you can tune or disable the cap (e.g. set to `0` or a very large number to effectively “no limit”) without code changes.

---

## Summary

| Question | Answer |
|----------|--------|
| What is retained? | Up to 10 **entries** per user in `context.user_data['urls']` (each entry = one URL or one upload/local choice). |
| Where? | In-memory only; lost on restart. |
| When is it trimmed? | When the user sends a **new** URL and the map already has more than 10 entries. |
| What breaks when trimmed? | Old inline buttons for that user can show “Request expired”. Files on disk are unaffected. |
| Can we change it? | Yes: increase cap, remove cap, or add time-based/LRU expiry; optional: make the cap a config/env setting. |
