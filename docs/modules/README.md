# Module deep-dives

Detailed documentation for the main “run and manage multiple bots” components:

| Module | Doc | Description |
|--------|-----|-------------|
| **Launcher** | [Launcher.md](Launcher.md) | Bot Launcher: config, start/stop/restart, dependencies, monitoring, CLI menu. |
| **Dashboard** | [Dashboard.md](Dashboard.md) | Web dashboard: Flask app, in-process with launcher, API and single-page UI. |

Other bots (caption_bot, down_oad_bot, Index_bot, name-bot, TG_download_bot, upload_bot) are standalone; add module docs here if you need a deep-dive for a specific bot (e.g. TG_download_bot MTProto + file server, or Index_bot database + parser).
