# Decision Log: down_oad_bot

Decisions recovered from existing codebase and developer clarification.

---

## 2025-02 - Documented During Context Recovery

### Tech stack
**Context:** Analyzed existing codebase  
**Decision:** Python 3.8+, python-telegram-bot ≥22.5, yt-dlp, instaloader, requests, aiohttp, python-dotenv, ffmpeg-python; FFmpeg binary on PATH.  
**Rationale:** Historical – stack established before documentation.

### Env and setup
**Context:** README referenced `.env.example`; repo had `env_template.txt`.  
**Decision:** Canonical template is `env_template.txt`; copy to `.env`. README updated.  
**Rationale:** Developer clarification; avoids setup confusion.

### File server
**Context:** Config exposes ENABLE_FILE_SERVER, FILE_SERVER_*; no file server code in repo.  
**Decision:** Keep config; plan implementation and configure later; currently saving files locally only.  
**Rationale:** Developer: save locally for now, implement and configure file server later.

### Threads and platform expansion
**Context:** ThreadsDownloader existed but was disabled in bot.  
**Decision:** Re-enable Threads in bot; plan to expand to more platforms over time.  
**Rationale:** Developer: enable Threads and expand accepted sites/portals/platforms.

### URLs retention
**Context:** Bot trims `context.user_data['urls']` to last 10 entries per user.  
**Decision:** Keep "last 10" for now; no strict file/URL count limits; discuss bottlenecks if needed. See `docs/URLS_RETENTION.md`.  
**Rationale:** Developer: no max file limits; discuss bottlenecks; cap kept as-is for now.

### TikTok
**Context:** URLDetector had TikTok patterns; no TikTok downloader in bot.  
**Decision:** Disable TikTok detection (not supported in region); plan support later. Patterns commented out in `utils/url_detector.py`.  
**Rationale:** Developer: TikTok not supported in our country; plan support later.

### PREFERRED_QUALITY
**Context:** In config but not used in bot logic.  
**Decision:** Keep in config; planned for future use.  
**Rationale:** Developer: plan it.

### ffmpeg-python
**Context:** In requirements; no `import ffmpeg` in codebase; yt-dlp uses FFmpeg binary.  
**Decision:** Keep package in requirements for now; document that conversion is via yt-dlp/FFmpeg binary.  
**Rationale:** Developer unsure; may be used as converter; keep unless confirmed unused.

### Conventions (observed)
**Context:** Codebase analysis.  
**Decision:** Single `config.py` with env; downloaders extend BaseDownloader; callback data uses 12-char url_hash; handlers in one `bot.py`.  
**Rationale:** Established convention.

---

*Add new decisions as development continues.*
