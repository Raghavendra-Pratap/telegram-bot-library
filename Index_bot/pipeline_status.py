"""Pipeline readiness checklist and per-upload publish stage labels."""
from __future__ import annotations

from content_lanes import LANE_LABELS, LANE_MEDIA, normalize_lane
from config import Config
from database import Database
from pipeline_setup import PIPELINE_UPLOAD_TYPES, resolve_source_channel_for_upload_type


def upload_publish_stage(upload, *, db=None) -> str:
    """
    Human-readable pipeline stage for an upload row.
    indexed → library_ready → catalog_published (media + TMDB only)
    """
    db = db or Database()
    if (getattr(upload, "ingest_state", None) or "") == "duplicate_hold":
        return "duplicate_hold"
    route = getattr(upload, "pipeline_route_status", None) or ""
    if route == "pending":
        return "route_pending"
    if route == "failed":
        return "route_failed"

    if not getattr(upload, "is_confirmed", False) and getattr(
        upload, "needs_confirmation", True
    ):
        if getattr(upload, "content_lane", "") == LANE_MEDIA:
            ct_id = getattr(upload, "content_title_id", None)
            if ct_id:
                ct = db.get_content_title(ct_id)
                if ct and not getattr(ct, "tmdb_id", None):
                    return "needs_tmdb"
        return "needs_confirm"

    if not getattr(upload, "library_visible", False):
        return "indexed"

    if not getattr(upload, "distribution_approved", False):
        return "library_ready"

    lane = normalize_lane(getattr(upload, "content_lane", None))
    if lane != LANE_MEDIA:
        return "published_library"

    ct_id = getattr(upload, "content_title_id", None)
    if not ct_id:
        return "library_ready"
    ct = db.get_content_title(ct_id)
    if not ct or not getattr(ct, "tmdb_id", None):
        return "library_ready"

    if db.get_watch_catalog_post(ct.id, getattr(upload, "season_number", None)):
        return "catalog_published"
    return "library_ready"


def get_pipeline_readiness(*, db=None) -> dict:
    db = db or Database()
    defaults = db.list_pipeline_upload_defaults()
    dist = db.list_watch_lane_assignments()
    ingest = db.get_ingest_channel()
    telethon_ok = _telethon_configured()
    dupes = db.count_duplicate_holds()
    route_pending = len(db.list_pipeline_route_queue(limit=100))
    jobs = db.list_upload_jobs(limit=5)

    sources = {}
    for row in defaults:
        ut = row["upload_type"]
        configured = bool(row.get("source_channel_id"))
        sources[ut] = {
            "configured": configured,
            "channel_id": row.get("source_channel_id"),
            "label": row.get("channel_title") or row.get("channel_username"),
        }

    checks = [
        {
            "id": "telethon",
            "label": "Telethon session (bulk upload + route)",
            "ok": telethon_ok,
            "hint": "python telethon_login.py",
        },
        {
            "id": "ingest",
            "label": "Mixed ingest sink channel",
            "ok": bool(ingest),
            "hint": "Library setup → Ingest channel",
        },
        {
            "id": "sources",
            "label": "Pipeline source channels (upload targets)",
            "ok": sum(1 for s in sources.values() if s["configured"])
            >= max(2, len(PIPELINE_UPLOAD_TYPES) // 2),
            "hint": "Library setup → Pipeline upload targets",
        },
        {
            "id": "media_publish",
            "label": "Media watch / publish channel",
            "ok": bool(dist.get(LANE_MEDIA)),
            "hint": "Pipeline targets → Set media publish channel",
        },
        {
            "id": "bot",
            "label": "bot.py running (live index)",
            "ok": None,
            "hint": "Keep bot running during upload tests",
        },
    ]

    return {
        "checks": checks,
        "config": {
            "classify_ingest": Config.PIPELINE_CLASSIFY_INGEST,
            "auto_route": Config.PIPELINE_AUTO_ROUTE,
            "auto_publish_watch": Config.AUTO_PUBLISH_WATCH,
        },
        "sources": sources,
        "ingest_channel": (
            {
                "channel_id": ingest.channel_id,
                "title": ingest.channel_title,
            }
            if ingest
            else None
        ),
        "duplicate_holds": dupes,
        "route_pending": route_pending,
        "recent_jobs": [
            {
                "id": j.id,
                "name": j.name,
                "status": j.status,
                "lane": j.content_lane,
                "target_channel_id": j.target_channel_id,
            }
            for j in jobs
        ],
    }


def _telethon_configured() -> bool:
    import os
    from pathlib import Path

    if not os.getenv("API_ID") or not os.getenv("API_HASH"):
        return False
    session = Path(os.getenv("FORWARD_INGEST_SESSION", "forward_ingest.session"))
    return session.is_file()


STAGE_LABELS = {
    "duplicate_hold": "⚠️ Duplicate review",
    "route_pending": "📤 Routing to bucket…",
    "route_failed": "❌ Route failed",
    "needs_tmdb": "🎬 Needs TMDB",
    "needs_confirm": "⏳ Needs confirm",
    "indexed": "✅ Indexed",
    "library_ready": "📚 Library visible",
    "published_library": "📢 Published (library)",
    "catalog_published": "📺 Watch catalog live",
}
