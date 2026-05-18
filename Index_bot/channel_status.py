"""
Channel role badges: bot monitoring vs historical (Telethon) ingest.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def format_channel_status_icons(
    channel,
    *,
    live_count: int = 0,
    backfill_count: int = 0,
) -> str:
    """
    Compact prefix for channel list buttons.

    📥 ingest sink
    🤖 bot indexes new posts in this channel (live)
    📜 historical import via backfill (forwards into ingest)
    👤 historical only (backfill done, no live bot posts in source)
    ⏳ registered but not historically ingested yet
    """
    if getattr(channel, "is_ingest_channel", False):
        return "📥"
    icons: list[str] = []
    if live_count > 0:
        icons.append("🤖")
    if backfill_count > 0:
        if live_count == 0:
            icons.append("👤")
        icons.append("📜")
    elif getattr(channel, "is_active", False) and not getattr(
        channel, "is_ingest_channel", False
    ):
        icons.append("⏳")
    return "".join(icons) if icons else "📺"


def channel_status_lines(
    channel,
    *,
    live_count: int,
    backfill_count: int,
    historical_ingested_at: datetime | None = None,
) -> list[str]:
    """Detail lines for channel info screen."""
    lines: list[str] = []
    if getattr(channel, "is_ingest_channel", False):
        lines.append(
            "<b>Role:</b> 📥 <b>Historical ingest sink</b> — forwards land here; "
            "not counted as a source archive."
        )
        return lines

    lines.append("<b>Monitoring &amp; ingest</b>")
    if live_count > 0:
        lines.append(
            f"🤖 <b>Bot monitoring</b> — <b>{live_count:,}</b> file(s) indexed from "
            "new posts in this channel."
        )
    elif getattr(channel, "is_active", False):
        lines.append(
            "🤖 <b>Bot registered</b> — no files indexed from live posts here yet "
            "(add bot as admin or post once)."
        )
    else:
        lines.append("⏸ <b>Not monitoring</b> — channel inactive in the bot.")

    if backfill_count > 0:
        when = ""
        if historical_ingested_at:
            when = f" · last run {historical_ingested_at.strftime('%Y-%m-%d %H:%M')} UTC"
        if live_count == 0:
            lines.append(
                f"👤📜 <b>Historically ingested</b> (Telethon / your account) — "
                f"<b>{backfill_count:,}</b> file(s) imported via forwards"
                f"{when}."
            )
        else:
            lines.append(
                f"📜 <b>Historically ingested</b> — <b>{backfill_count:,}</b> file(s) "
                f"imported via backfill{when}."
            )
    else:
        lines.append(
            "⏳ <b>Not historically ingested</b> — use "
            "<b>▶️ Start historical ingestion</b> to import old posts."
        )
    return lines


def channel_list_label_with_status(
    channel,
    *,
    live_count: int,
    backfill_count: int,
    file_count: int | None,
    label_fn,
    max_len: int = 64,
) -> str:
    prefix = format_channel_status_icons(
        channel, live_count=live_count, backfill_count=backfill_count
    )
    count_suffix = f" · {file_count}" if file_count is not None else ""
    inner_max = max_len - len(prefix) - len(count_suffix) - 1
    base = label_fn(channel, max_len=max(inner_max, 12))
    return f"{prefix} {base}{count_suffix}"
