"""Human-readable channel labels for admin UI."""
from __future__ import annotations

from html import escape


def upload_location_label(upload, *, ingest_channel_id: str | None = None) -> str:
    """
    Where this file lives in the index.

    For ingest forwards, show the source archive — not only index-backfill.
    """
    post_title = None
    if getattr(upload, "channel", None):
        post_title = upload.channel.channel_title or upload.channel.channel_username
    post = post_title or getattr(upload, "channel_id", None) or "?"

    src_id = getattr(upload, "source_channel_id", None)
    if src_id and str(src_id) != str(getattr(upload, "channel_id", None)):
        if getattr(upload, "source_channel", None):
            src = (
                upload.source_channel.channel_title
                or upload.source_channel.channel_username
                or src_id
            )
        else:
            src = src_id
        if ingest_channel_id and str(upload.channel_id) == ingest_channel_id:
            return f"{escape(str(src))} (via {escape(str(post))})"
        return escape(str(src))

    return escape(str(post))
