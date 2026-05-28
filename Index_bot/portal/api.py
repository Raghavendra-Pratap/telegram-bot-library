"""FastAPI watch portal — catalog UI + Telegram-backed play."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from telegram import Bot

from config import Config
from database import Database
from portal import admin_service
from portal import service
from portal.deps import get_user_id, get_user_id_optional, require_admin, user_role
from portal.stream_progress import snapshot as stream_progress_snapshot
from portal.streaming import can_stream_in_browser, stream_upload, telethon_stream_ready
from portal.transcode_stream import ffmpeg_available

logger = logging.getLogger(__name__)
_STATIC = Path(__file__).resolve().parent / "static"
db = Database()


def _portal_url() -> str:
    return (os.getenv("PORTAL_PUBLIC_URL") or "http://127.0.0.1:8765").rstrip("/")


def _guard_admin_browse_scope(scope: str, user_id: int) -> None:
    s = (scope or "").lower()
    if s in (
        "adult",
        "non_catalog",
        "non-catalog",
        "noncatalog",
        "archive",
        "shortform",
    ) and user_role(user_id) != "admin":
        raise HTTPException(403, "Admin only")


def get_bot() -> Bot:
    return Bot(token=Config.BOT_TOKEN)


app = FastAPI(title="Index Watch Portal", version="1.0")


class AuthBody(BaseModel):
    token: str


class RequestBody(BaseModel):
    tmdb_id: int | None = None
    media_type: str = "movie"
    title: str
    release_year: int | None = None


class UnpublishBody(BaseModel):
    content_title_id: int
    season_number: int | None = None


class RequestStatusBody(BaseModel):
    status: str


class TmdbPickBody(BaseModel):
    suggestion_index: int = 0
    search_query: str | None = None
    tmdb_id: int | None = None
    apply_siblings: bool = False
    page: int = 1
    title: str | None = None
    media_type: str | None = None
    year: int | None = None


@app.get("/api/health")
def health():
    from tmdb_helper import tmdb_helper

    tmdb = tmdb_helper.ping() if tmdb_helper.enabled else {"ok": False, "error": "not configured"}
    return {
        "ok": True,
        "portal_url": _portal_url(),
        "browser_stream": telethon_stream_ready(),
        "ffmpeg_transcode": ffmpeg_available(),
        "tmdb_enabled": tmdb_helper.enabled,
        "tmdb_reachable": bool(tmdb.get("ok")),
        "tmdb_error": None if tmdb.get("ok") else tmdb.get("error"),
    }


@app.post("/api/auth/login")
def auth_login(body: AuthBody):
    uid = db.get_portal_user_id(body.token.strip())
    if not uid:
        raise HTTPException(401, "Invalid or expired link token")
    return {
        "user_id": uid,
        "token": body.token.strip(),
        "role": user_role(uid),
    }


@app.get("/api/me")
def me(user_id: int = Depends(get_user_id)):
    return {"user_id": user_id, "role": user_role(user_id)}


@app.get("/api/browse")
def browse(
    limit: int = Query(28, ge=12, le=84),
    offset: int = Query(0, ge=0),
    page: int = Query(1, ge=1),
    type: str = Query("all"),
    scope: str = Query("media"),
    sort: str = Query("recent"),
    order: str = Query("desc"),
    min_year: int | None = Query(None),
    max_year: int | None = Query(None),
    min_rating: float | None = Query(None, ge=0, le=10),
    q: str | None = Query(None),
    user_id: int = Depends(get_user_id),
):
    _guard_admin_browse_scope(scope, user_id)
    if page > 1:
        offset = (page - 1) * limit
    items, total = service.browse_titles(
        limit=limit,
        offset=offset,
        media_type=type,
        browse_scope=scope,
        user_id=user_id,
        min_year=min_year,
        max_year=max_year,
        min_rating=min_rating,
        sort=sort,
        sort_desc=order.lower() != "asc",
        search=q,
    )
    page_count = max(1, (total + limit - 1) // limit) if total else 1
    current_page = (offset // limit) + 1 if limit else 1
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "page": current_page,
        "page_count": page_count,
        "has_more": offset + len(items) < total,
    }


@app.get("/api/search")
def search(q: str = Query(""), user_id: int = Depends(get_user_id)):
    return service.search_catalog(q, user_id=user_id)


@app.get("/api/title/{content_title_id}")
def title_detail(
    content_title_id: int,
    scope: str = Query("public"),
    user_id: int = Depends(get_user_id),
):
    _guard_admin_browse_scope(scope, user_id)
    detail = service.get_title_detail(
        content_title_id, user_id=user_id, browse_scope=scope
    )
    if not detail:
        raise HTTPException(404, "Title not found")
    return detail


@app.get("/api/title/{content_title_id}/episodes")
def title_episodes(
    content_title_id: int,
    scope: str = Query("public"),
    user_id: int = Depends(get_user_id),
):
    _guard_admin_browse_scope(scope, user_id)
    if not db.get_content_title(content_title_id):
        raise HTTPException(404, "Title not found")
    return {
        "episodes": service.list_episodes(
            content_title_id, user_id=user_id, browse_scope=scope
        )
    }


@app.get("/api/title/{content_title_id}/qualities")
def title_qualities(
    content_title_id: int,
    season: int | None = None,
    episode: int | None = None,
    scope: str = Query("public"),
    user_id: int = Depends(get_user_id),
):
    _guard_admin_browse_scope(scope, user_id)
    if not db.get_content_title(content_title_id):
        raise HTTPException(404, "Title not found")
    return {
        "qualities": service.list_qualities(
            content_title_id,
            season=season,
            episode=episode,
            user_id=user_id,
            browse_scope=scope,
        )
    }


@app.post("/api/favorites/{content_title_id}")
def toggle_favorite(content_title_id: int, user_id: int = Depends(get_user_id)):
    now = db.toggle_favorite(user_id, content_title_id)
    return {"favorited": now}


@app.post("/api/watchlist/{content_title_id}")
def toggle_watchlist(content_title_id: int, user_id: int = Depends(get_user_id)):
    if not db.get_content_title(content_title_id):
        raise HTTPException(404, "Title not found")
    on_list = db.toggle_watchlist_title(user_id, content_title_id)
    return {"on_watchlist": on_list}


@app.get("/api/watchlist")
def watchlist(user_id: int = Depends(get_user_id)):
    return {"items": service.watchlist_titles(user_id=user_id)}


@app.get("/api/favorites")
def favorites(user_id: int = Depends(get_user_id)):
    rows = db.get_user_favorites(user_id, limit=60)
    items = []
    for r in rows:
        ct = db.get_content_title(r["content_title_id"])
        items.append(service._card_from_ct(ct, r, user_id=user_id))
    return {"items": items}


@app.get("/api/requests")
def my_requests(user_id: int = Depends(get_user_id)):
    rows = db.get_user_upload_requests(user_id, limit=30)
    return {
        "items": [
            {
                "id": r.id,
                "tmdb_id": r.tmdb_id,
                "title": r.tmdb_title,
                "media_type": r.media_type,
                "status": r.status,
            }
            for r in rows
        ]
    }


@app.post("/api/requests")
def create_request(body: RequestBody, user_id: int = Depends(get_user_id)):
    mt = body.media_type or "movie"
    if body.tmdb_id and db.has_pending_upload_request(user_id, body.tmdb_id, mt):
        return {"ok": True, "status": "already_pending"}
    rid = db.create_upload_request(
        user_id,
        tmdb_id=body.tmdb_id,
        media_type=mt,
        tmdb_title=body.title[:200],
        release_year=body.release_year,
    )
    if not rid:
        raise HTTPException(500, "Could not save request")
    return {"ok": True, "id": rid}


@app.post("/api/play/{upload_id}")
async def play(upload_id: int, user_id: int = Depends(get_user_id), bot: Bot = Depends(get_bot)):
    return await service.play_upload(user_id, upload_id, bot=bot)


@app.get("/api/admin/dashboard")
def admin_dashboard(_admin: int = Depends(require_admin)):
    return admin_service.dashboard_stats()


@app.get("/api/admin/channels/monitoring")
def admin_channels_monitoring(_admin: int = Depends(require_admin)):
    return admin_service.channel_monitoring_status()


@app.get("/api/admin/pending")
def admin_pending(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=5, le=50),
    batch_page: int = Query(1, ge=1),
    _admin: int = Depends(require_admin),
):
    return admin_service.list_pending(page=page, limit=limit, batch_page=batch_page)


@app.get("/api/admin/pending/{upload_id}/tmdb")
def admin_pending_tmdb(
    upload_id: int,
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int | None = Query(None, ge=1, le=40),
    filter_type: str = Query("all"),
    _admin: int = Depends(require_admin),
):
    data = admin_service.pending_tmdb_lookup(
        upload_id,
        search_query=q,
        page=page,
        per_page=per_page,
        filter_type=filter_type,
    )
    if not data.get("ok"):
        raise HTTPException(404, data.get("error", "Not found"))
    data.pop("_meta", None)
    return data


@app.post("/api/admin/pending/{upload_id}/tmdb-pick")
def admin_pending_tmdb_pick(
    upload_id: int,
    body: TmdbPickBody,
    _admin: int = Depends(require_admin),
):
    return admin_service.apply_tmdb_suggestion(
        upload_id,
        suggestion_index=body.suggestion_index,
        search_query=body.search_query,
        tmdb_id=body.tmdb_id,
        apply_siblings=body.apply_siblings,
        page=body.page,
        title=body.title,
        media_type=body.media_type,
        year=body.year,
    )


@app.post("/api/admin/pending/{upload_id}/tmdb-retry")
def admin_pending_tmdb_retry(
    upload_id: int, _admin: int = Depends(require_admin)
):
    data = admin_service.retry_pending_tmdb(upload_id)
    if not data.get("ok"):
        raise HTTPException(404, data.get("error", "Not found"))
    return data


@app.post("/api/admin/pending/retry-all-tmdb")
async def admin_pending_retry_all(_admin: int = Depends(require_admin)):
    return await asyncio.to_thread(admin_service.retry_all_pending_tmdb)


@app.get("/api/admin/titles/{content_title_id}/uploads")
def admin_title_uploads(
    content_title_id: int,
    _admin: int = Depends(require_admin),
):
    data = admin_service.list_remap_uploads(content_title_id)
    if not data.get("ok"):
        raise HTTPException(404, data.get("error", "Not found"))
    return data


@app.post("/api/admin/titles/{content_title_id}/lane")
def admin_title_lane_all(
    content_title_id: int,
    body: dict,
    _admin: int = Depends(require_admin),
):
    lane = (body.get("lane") or body.get("content_lane") or "").strip()
    if not lane:
        raise HTTPException(400, "lane required")
    return admin_service.set_title_uploads_lane(content_title_id, lane)


@app.get("/api/admin/uploads/{upload_id}/tmdb")
def admin_upload_tmdb(
    upload_id: int,
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int | None = Query(None, ge=1, le=40),
    filter_type: str = Query("all"),
    _admin: int = Depends(require_admin),
):
    data = admin_service.upload_tmdb_lookup(
        upload_id,
        search_query=q,
        page=page,
        per_page=per_page,
        filter_type=filter_type,
    )
    if not data.get("ok"):
        raise HTTPException(404, data.get("error", "Not found"))
    data.pop("_meta", None)
    return data


@app.post("/api/admin/uploads/{upload_id}/tmdb-pick")
def admin_upload_tmdb_pick(
    upload_id: int,
    body: TmdbPickBody,
    _admin: int = Depends(require_admin),
):
    return admin_service.apply_tmdb_suggestion(
        upload_id,
        suggestion_index=body.suggestion_index,
        search_query=body.search_query,
        tmdb_id=body.tmdb_id,
        apply_siblings=body.apply_siblings,
        page=body.page,
        title=body.title,
        media_type=body.media_type,
        year=body.year,
    )


@app.post("/api/admin/uploads/{upload_id}/tmdb-retry")
def admin_upload_tmdb_retry(
    upload_id: int, _admin: int = Depends(require_admin)
):
    data = admin_service.retry_upload_tmdb(upload_id)
    if not data.get("ok"):
        raise HTTPException(404, data.get("error", "Not found"))
    return data


@app.post("/api/admin/uploads/{upload_id}/lane")
def admin_upload_lane(
    upload_id: int,
    body: dict,
    _admin: int = Depends(require_admin),
):
    lane = (body.get("lane") or body.get("content_lane") or "").strip()
    if not lane:
        raise HTTPException(400, "lane required")
    return admin_service.set_pending_upload_lane(upload_id, lane)


@app.post("/api/admin/uploads/{upload_id}/queue-tmdb-pending")
def admin_upload_queue_tmdb_pending(
    upload_id: int,
    _admin: int = Depends(require_admin),
):
    return admin_service.queue_upload_for_tmdb_mapping(upload_id)


@app.get("/api/admin/pending/batches/{match_key:path}/tmdb")
def admin_batch_tmdb(
    match_key: str,
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int | None = Query(None, ge=1, le=40),
    filter_type: str = Query("all"),
    _admin: int = Depends(require_admin),
):
    data = admin_service.batch_tmdb_lookup(
        match_key,
        search_query=q,
        page=page,
        per_page=per_page,
        filter_type=filter_type,
    )
    if not data.get("ok"):
        raise HTTPException(404, data.get("error", "Not found"))
    data.pop("_meta", None)
    return data


@app.post("/api/admin/pending/batches/{match_key:path}/tmdb-pick")
def admin_batch_tmdb_pick(
    match_key: str,
    body: TmdbPickBody,
    _admin: int = Depends(require_admin),
):
    return admin_service.apply_batch_tmdb_pick(
        match_key,
        suggestion_index=body.suggestion_index,
        search_query=body.search_query,
        tmdb_id=body.tmdb_id,
        page=body.page,
        title=body.title,
        media_type=body.media_type,
        year=body.year,
    )


@app.post("/api/admin/pending/{upload_id}/approve")
def admin_pending_approve(upload_id: int, _admin: int = Depends(require_admin)):
    return admin_service.approve_pending(upload_id)


@app.post("/api/admin/pending/{upload_id}/confirm")
def admin_pending_confirm(upload_id: int, _admin: int = Depends(require_admin)):
    return admin_service.confirm_pending_without_tmdb(upload_id)


@app.post("/api/admin/pending/{upload_id}/defer")
def admin_pending_defer(upload_id: int, _admin: int = Depends(require_admin)):
    return admin_service.defer_pending(upload_id)


@app.post("/api/admin/pending/{upload_id}/skip")
def admin_pending_skip(upload_id: int, _admin: int = Depends(require_admin)):
    return admin_service.skip_pending(upload_id)


@app.post("/api/admin/pending/{upload_id}/skip-catalog")
def admin_pending_skip_catalog(
    upload_id: int, _admin: int = Depends(require_admin)
):
    return admin_service.skip_catalog_pending(upload_id)


@app.post("/api/admin/pending/{upload_id}/lane")
def admin_pending_upload_lane(
    upload_id: int,
    body: dict,
    _admin: int = Depends(require_admin),
):
    lane = (body.get("lane") or body.get("content_lane") or "").strip()
    if not lane:
        raise HTTPException(400, "lane required")
    data = admin_service.set_pending_upload_lane(upload_id, lane)
    if not data.get("ok"):
        raise HTTPException(400, data.get("error", "Failed"))
    return data


@app.post("/api/admin/pending/batches/{match_key:path}/lane")
def admin_pending_batch_lane(
    match_key: str,
    body: dict,
    _admin: int = Depends(require_admin),
):
    lane = (body.get("lane") or body.get("content_lane") or "").strip()
    if not lane:
        raise HTTPException(400, "lane required")
    raw_ids = body.get("file_ids")
    file_ids = None
    if isinstance(raw_ids, list):
        file_ids = [int(x) for x in raw_ids if x is not None]
    data = admin_service.set_pending_batch_lane(match_key, lane, file_ids=file_ids)
    if not data.get("ok"):
        raise HTTPException(400, data.get("error", "Failed"))
    return data


@app.post("/api/admin/pending/batches/{match_key:path}/defer")
def admin_pending_batch_defer(
    match_key: str, _admin: int = Depends(require_admin)
):
    return admin_service.defer_pending_batch(match_key)


@app.post("/api/admin/pending/batches/{match_key:path}/skip-catalog")
def admin_pending_batch_skip_catalog(
    match_key: str, _admin: int = Depends(require_admin)
):
    return admin_service.skip_catalog_pending_batch(match_key)


@app.get("/api/admin/requests")
def admin_requests(
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=6, le=48),
    _admin: int = Depends(require_admin),
):
    return admin_service.list_user_requests(page=page, limit=limit)


@app.post("/api/admin/requests/{request_id}")
def admin_request_resolve(
    request_id: int,
    body: RequestStatusBody,
    _admin: int = Depends(require_admin),
):
    return admin_service.resolve_request(request_id, status=body.status)


@app.get("/api/admin/catalog/unpublished")
def admin_catalog_unpublished(
    limit: int = Query(30, ge=1, le=100),
    _admin: int = Depends(require_admin),
):
    return admin_service.list_unpublished_catalog(limit=limit)


@app.post("/api/admin/catalog/publish")
async def admin_catalog_publish(
    limit: int = Query(10, ge=1, le=25),
    _admin: int = Depends(require_admin),
):
    return await admin_service.publish_catalog_chunk(limit=limit)


@app.post("/api/admin/catalog/publish-all")
async def admin_catalog_publish_all(_admin: int = Depends(require_admin)):
    return await admin_service.start_publish_catalog_all()


@app.get("/api/admin/catalog/publish-all/status")
def admin_catalog_publish_all_status(_admin: int = Depends(require_admin)):
    return admin_service.publish_catalog_all_status()


@app.get("/api/admin/catalog/published")
def admin_catalog_published(
    page: int = Query(1, ge=1),
    limit: int = Query(28, ge=12, le=84),
    _admin: int = Depends(require_admin),
):
    return admin_service.list_published_catalog(page=page, limit=limit)


@app.get("/api/admin/catalog")
def admin_catalog_list(
    page: int = Query(1, ge=1),
    limit: int = Query(28, ge=12, le=84),
    status: str = Query("all"),
    q: str | None = Query(None),
    sort: str = Query("published_at"),
    order: str = Query("desc"),
    _admin: int = Depends(require_admin),
):
    return admin_service.list_watch_catalog(
        page=page,
        limit=limit,
        status=status,
        search=q,
        sort=sort,
        order=order,
    )


@app.post("/api/admin/catalog/unpublish")
async def admin_catalog_unpublish(
    body: UnpublishBody,
    _admin: int = Depends(require_admin),
):
    return await admin_service.unpublish_catalog_item(
        int(body.content_title_id), season_number=body.season_number
    )


@app.get("/api/admin/tracking")
def admin_tracking(
    filter: str = Query("all"),
    completion: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=6, le=48),
    _admin: int = Depends(require_admin),
):
    return admin_service.list_tracking(
        filter_kind=filter,
        completion=completion,
        page=page,
        page_size=page_size,
    )


@app.get("/api/admin/metadata-gaps")
def admin_metadata_gaps(
    issue: str = Query("all"),
    page: int = Query(1, ge=1),
    limit: int = Query(40, ge=10, le=100),
    _admin: int = Depends(require_admin),
):
    return admin_service.list_metadata_gaps(issue=issue, page=page, limit=limit)


@app.get("/api/admin/filename-rules")
def admin_filename_rules_list(_admin: int = Depends(require_admin)):
    return admin_service.list_filename_strip_rules()


@app.post("/api/admin/filename-rules")
def admin_filename_rules_add(
    body: dict,
    _admin: int = Depends(require_admin),
):
    pattern = (body.get("pattern") or "").replace("\r", "").replace("\n", "")
    if not pattern.strip():
        raise HTTPException(400, "pattern required")
    note = (body.get("note") or "").strip() or None
    is_regex = bool(body.get("is_regex"))
    return admin_service.add_filename_strip_rule(
        pattern, note=note, is_regex=is_regex
    )


@app.delete("/api/admin/filename-rules/{rule_id}")
def admin_filename_rules_delete(
    rule_id: int,
    _admin: int = Depends(require_admin),
):
    return admin_service.delete_filename_strip_rule(rule_id)


@app.post("/api/admin/filename-rules/preview")
def admin_filename_rules_preview(
    body: dict,
    _admin: int = Depends(require_admin),
):
    filename = (body.get("filename") or "").strip()
    if not filename:
        raise HTTPException(400, "filename required")
    return admin_service.preview_filename_strip(filename)


@app.post("/api/admin/uploads/{upload_id}/convert-mp4")
async def admin_upload_convert_mp4(
    upload_id: int,
    _admin: int = Depends(require_admin),
):
    return admin_service.start_upload_mp4_convert(upload_id)


@app.get("/api/admin/uploads/{upload_id}/convert-mp4")
def admin_upload_convert_mp4_status(
    upload_id: int,
    _admin: int = Depends(require_admin),
):
    return admin_service.upload_mp4_convert_status(upload_id)


@app.get("/api/admin/pipeline/status")
def admin_pipeline_status(_admin: int = Depends(require_admin)):
    return admin_service.pipeline_status()


@app.get("/api/admin/pipeline/defaults")
def admin_pipeline_defaults(_admin: int = Depends(require_admin)):
    return admin_service.pipeline_defaults()


class PipelineSourceBody(BaseModel):
    source_channel_id: str | None = None


@app.put("/api/admin/pipeline/defaults/{upload_type}")
def admin_pipeline_set_source(
    upload_type: str,
    body: PipelineSourceBody,
    _admin: int = Depends(require_admin),
):
    return admin_service.set_pipeline_source(upload_type, body.source_channel_id)


@app.get("/api/admin/upload-jobs")
def admin_upload_jobs(
    limit: int = Query(30, ge=1, le=100),
    _admin: int = Depends(require_admin),
):
    return admin_service.list_upload_jobs_admin(limit=limit)


@app.get("/api/admin/duplicate-holds")
def admin_duplicate_holds(
    limit: int = Query(40, ge=1, le=200),
    _admin: int = Depends(require_admin),
):
    return admin_service.list_duplicate_holds_admin(limit=limit)


@app.get("/api/stream/{upload_id}")
async def stream(
    upload_id: int,
    request: Request,
    user_id: int = Depends(get_user_id_optional),
    bot: Bot = Depends(get_bot),
):
    upload = db.get_file_upload(upload_id)
    if not upload or not db.is_upload_accessible_for_user(upload, user_id):
        raise HTTPException(404, "Not available")
    if not can_stream_in_browser(upload):
        raise HTTPException(
            503,
            "Browser playback unavailable — configure Telethon (telethon_login.py)",
        )
    return await stream_upload(
        upload,
        range_header=request.headers.get("range"),
        bot=bot,
    )


@app.get("/api/stream/{upload_id}/progress")
def stream_progress(
    upload_id: int,
    user_id: int = Depends(get_user_id_optional),
):
    upload = db.get_file_upload(upload_id)
    if not upload or not db.is_upload_accessible_for_user(upload, user_id):
        raise HTTPException(404, "Not available")
    prog = stream_progress_snapshot(upload_id)
    if not prog:
        return {
            "active": False,
            "bytes_from_telegram": 0,
            "request_percent": 0,
            "file_percent": 0,
            "file_size": int(upload.file_size or 0),
            "phase": "idle",
        }
    return prog


@app.get("/")
def index():
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
