"""Admin-only portal: pending review, requests, catalog publish."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from name_parser import NameParser
from telegram import Bot
from tmdb_helper import (
    best_poster_url,
    poster_image_url,
    sort_suggestions_poster_first,
    tmdb_helper,
    tmdb_web_url,
)
from title_indexer import (
    build_index_metadata,
    build_pick_metadata,
    episode_display_name,
)
from series_grouping import (
    batched_pending_file_ids,
    build_pending_groups,
    show_group_key,
    sibling_pending_ids,
)

from config import Config
from database import Database
from portal.service import tmdb_metadata_for_ct
from portal.tracking_service import count_tracking_entries, list_tracking_entries
from watch_catalog import publish_catalog_all, publish_catalog_batch, unpublish_catalog_slot

logger = logging.getLogger(__name__)
db = Database()
_parser = NameParser()


def dashboard_stats() -> dict[str, Any]:
    summary = db.get_index_summary()
    metadata_gaps = db.count_metadata_gap_summary()
    return {
        "pending_confirmations": db.count_pending_confirmations(),
        "pending_user_requests": db.count_pending_upload_requests(),
        "unpublished_catalog_slots": db.count_unpublished_catalog_slots(),
        "published_catalog": db.count_watch_published(),
        "library_titles": db.count_library_browse_titles(
            library_only=True, browse_scope="public"
        ),
        "media_library_titles": db.count_library_browse_titles(
            library_only=True, browse_scope="media"
        ),
        "course_library_titles": db.count_library_browse_titles(
            library_only=True, browse_scope="course"
        ),
        "adult_library_titles": db.count_library_browse_titles(
            library_only=True, browse_scope="adult"
        ),
        "non_catalog_titles": db.count_library_browse_titles(
            library_only=True, browse_scope="non_catalog"
        ),
        "archive_library_titles": db.count_library_browse_titles(
            library_only=True, browse_scope="archive"
        ),
        "shortform_library_titles": db.count_library_browse_titles(
            library_only=True, browse_scope="shortform"
        ),
        "channels_active": db.count_active_channels(),
        "channels_by_lane": db.get_channel_lane_counts(),
        "tracking_items": count_tracking_entries(),
        "total_uploads": summary.get("total_uploads", 0),
        "confirmed_uploads": summary.get("confirmed", 0),
        "metadata_gaps": metadata_gaps,
    }


def channel_monitoring_status() -> dict[str, Any]:
    """Channels indexed live by the bot vs polled via Telethon member watch."""
    from config import Config

    overview = db.get_channel_monitoring_overview()
    return {
        **overview,
        "member_watch_enabled": bool(Config.TELETHON_MEMBER_WATCH_ENABLED),
        "member_watch_interval_s": Config.TELETHON_MEMBER_WATCH_INTERVAL_S,
        "bot_indexed_count": len(overview.get("bot_indexed") or []),
        "member_watch_count": len(overview.get("member_watch") or []),
        "ingest_sink_count": len(overview.get("ingest_sinks") or []),
    }


def list_metadata_gaps(
    *,
    issue: str = "all",
    page: int = 1,
    limit: int = 40,
) -> dict[str, Any]:
    issue = (issue or "all").lower()
    if issue not in ("all", "no_tmdb", "no_poster", "no_both"):
        issue = "all"
    page = max(1, int(page))
    limit = max(1, min(int(limit), 100))
    offset = (page - 1) * limit
    items, total = db.list_library_titles_missing_metadata(
        issue=issue, limit=limit, offset=offset
    )
    for item in items:
        ct = db.get_content_title(int(item["content_title_id"]))
        item["poster_url"] = _poster_for_ct(ct)
        if ct and ct.tmdb_id:
            item["tmdb_url"] = tmdb_web_url(
                {"tmdb_id": ct.tmdb_id, "media_type": ct.media_type}
            )
    pages = max(1, (total + limit - 1) // limit) if total else 1
    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": pages,
        "limit": limit,
        "issue": issue,
        "summary": db.count_metadata_gap_summary(),
        "tmdb_enabled": tmdb_helper.enabled,
    }


def _poster_from_db(ct) -> str | None:
    if not ct or not ct.poster_path:
        return None
    return poster_image_url({"poster_path": ct.poster_path})


def _poster_for_ct(ct) -> str | None:
    if not ct:
        return None
    url = _poster_from_db(ct)
    if url:
        return url
    meta = tmdb_metadata_for_ct(ct, ct.media_type)
    return meta.get("poster_url")


def list_tracking(
    *,
    filter_kind: str = "all",
    completion: str = "all",
    page: int = 1,
    page_size: int = 12,
) -> dict[str, Any]:
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 48))
    items, total, pages = list_tracking_entries(
        filter_kind,
        completion=completion,
        page=page,
        page_size=page_size,
        fetch_tmdb=(filter_kind == "franchise"),
        fetch_page_tmdb=True,
    )
    for item in items:
        ct_id = item.get("content_title_id")
        if ct_id:
            ct = db.get_content_title(int(ct_id))
            item["poster_url"] = _poster_for_ct(ct)
            if ct and ct.tmdb_id:
                item["tmdb_url"] = tmdb_web_url(
                    {"tmdb_id": ct.tmdb_id, "media_type": ct.media_type}
                )
        if item.get("kind") == "multipart" and item.get("part_set"):
            item["parts_label"] = ", ".join(f"#{p}" for p in item["part_set"][:12])
    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": page_size,
        "filter": filter_kind,
        "completion": completion,
    }


def list_watch_catalog(
    *,
    page: int = 1,
    limit: int = 28,
    status: str = "all",
    search: str | None = None,
    sort: str = "published_at",
    order: str = "desc",
) -> dict[str, Any]:
    """Catalog slots with published / unpublished filter (DB-paginated when possible)."""
    status = (status or "all").lower()
    desc = (order or "desc").lower() != "asc"

    if status == "published":
        return _list_watch_catalog_published_fast(
            page=page,
            limit=limit,
            status="published",
            search=search,
            sort=sort,
            desc=desc,
            unpublished_count=0,
        )

    unpublished_n = db.count_unpublished_catalog_slots()

    if status == "all" and unpublished_n == 0:
        return _list_watch_catalog_published_fast(
            page=page,
            limit=limit,
            status=status,
            search=search,
            sort=sort,
            desc=desc,
            unpublished_count=0,
        )

    return _list_watch_catalog_full_scan(
        page=page,
        limit=limit,
        status=status,
        search=search,
        sort=sort,
        desc=desc,
        unpublished_count=unpublished_n,
    )


def _list_watch_catalog_published_fast(
    *,
    page: int,
    limit: int,
    status: str,
    search: str | None,
    sort: str,
    desc: bool,
    unpublished_count: int,
) -> dict[str, Any]:
    offset = max(0, (page - 1) * limit)
    rows, published_n = db.list_published_catalog_page(
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        desc=desc,
    )
    items = []
    for row in rows:
        ct = db.get_content_title(row["content_title_id"])
        poster = _poster_for_ct(ct) or (
            poster_image_url({"poster_path": row.get("poster_path")})
            if row.get("poster_path")
            else None
        )
        items.append(
            {
                **row,
                "poster_url": poster,
                "in_library": True,
                "is_published": True,
            }
        )
    total = published_n if status == "published" else published_n + unpublished_count
    page_count = max(1, (total + limit - 1) // limit) if total else 1
    return {
        "items": items,
        "total": total,
        "published_count": published_n,
        "unpublished_count": unpublished_count,
        "page": page,
        "page_count": page_count,
        "limit": limit,
        "status": status,
        "fast_path": True,
    }


def _list_watch_catalog_full_scan(
    *,
    page: int,
    limit: int,
    status: str,
    search: str | None,
    sort: str,
    desc: bool,
    unpublished_count: int,
) -> dict[str, Any]:
    """Legacy path when unpublished slots exist (slower — scans all library slots)."""
    slots = db.get_library_catalog_slots(limit=None)
    rows: list[dict[str, Any]] = []
    q = (search or "").strip().lower()
    for s in slots:
        ct_id = s["content_title_id"]
        season = s.get("season_number")
        post = db.get_watch_catalog_post(ct_id, season)
        is_published = post is not None
        if status == "published" and not is_published:
            continue
        if status == "unpublished" and is_published:
            continue
        ct = db.get_content_title(ct_id)
        title = (ct.tmdb_title or ct.name or "?") if ct else "?"
        if q and q not in title.lower():
            continue
        rows.append(
            {
                "content_title_id": ct_id,
                "season_number": season,
                "media_type": (s.get("media_type") or "movie").lower(),
                "is_published": is_published,
                "message_id": post.message_id if post else None,
                "published_at": (
                    post.published_at.isoformat() if post and post.published_at else None
                ),
                "title": title,
                "release_year": ct.release_year if ct else None,
                "vote_average": ct.vote_average if ct else None,
            }
        )
    sort_key = (sort or "title").lower()
    reverse = desc

    def _sort_key(r: dict) -> tuple:
        if sort_key == "year":
            return (r.get("release_year") or 0, r.get("title") or "")
        if sort_key == "rating":
            return (r.get("vote_average") or 0, r.get("title") or "")
        if sort_key == "published_at":
            return (r.get("published_at") or "", r.get("title") or "")
        return (r.get("title") or "").lower()

    rows.sort(key=_sort_key, reverse=reverse)
    total = len(rows)
    offset = max(0, (page - 1) * limit)
    page_slots = rows[offset : offset + limit]
    page_items: list[dict[str, Any]] = []
    for slot in page_slots:
        ct = db.get_content_title(slot["content_title_id"])
        page_items.append(
            {
                **slot,
                "media_type": slot.get("media_type")
                or ((ct.media_type or "movie").lower() if ct else "movie"),
                "poster_url": _poster_for_ct(ct),
                "in_library": True,
            }
        )
    page_count = max(1, (total + limit - 1) // limit) if total else 1
    published_n = sum(1 for r in rows if r["is_published"])
    return {
        "items": page_items,
        "total": total,
        "published_count": published_n,
        "unpublished_count": unpublished_count,
        "page": page,
        "page_count": page_count,
        "limit": limit,
        "status": status,
        "fast_path": False,
    }


def list_published_catalog(
    *, page: int = 1, limit: int = 28
) -> dict[str, Any]:
    offset = max(0, (page - 1) * limit)
    rows, total = db.list_published_catalog_page(limit=limit, offset=offset)
    items = []
    for row in rows:
        ct = db.get_content_title(row["content_title_id"])
        meta = tmdb_metadata_for_ct(ct, row.get("media_type")) if ct else {}
        poster = _poster_for_ct(ct) or meta.get("poster_url")
        items.append({**row, "poster_url": poster, "in_library": True, "is_published": True})
    page_count = max(1, (total + limit - 1) // limit) if total else 1
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_count": page_count,
        "limit": limit,
    }


async def unpublish_catalog_item(
    content_title_id: int, *, season_number: int | None = None
) -> dict[str, Any]:
    bot = Bot(token=Config.BOT_TOKEN)
    ok, msg = await unpublish_catalog_slot(
        bot, db, int(content_title_id), season_number
    )
    return {"ok": ok, "message": msg}


def _can_convert_mp4(upload) -> bool:
    from portal.convert_pipeline import can_convert_upload

    return bool(upload and can_convert_upload(upload))


def _mp4_cached(upload_id: int) -> bool:
    from portal.convert_pipeline import mp4_cache_ready

    return mp4_cache_ready(int(upload_id))


def _build_batch_page(
    pending: list, *, batch_page: int, batch_limit: int
) -> tuple[list[dict[str, Any]], int, int]:
    """Group pending uploads into series/movie batches (bot-style)."""
    from content_lanes import normalize_lane
    from portal.streaming import (
        browser_friendly_video,
        can_play_in_browser,
        can_stream_in_browser,
    )

    groups = build_pending_groups(pending, parser=_parser)
    batched_ids = batched_pending_file_ids(groups)
    pending_by_id = {int(p.id): p for p in pending}
    batch_offset = max(0, (batch_page - 1) * batch_limit)
    batch_slice = groups[batch_offset : batch_offset + batch_limit]
    batches = []
    for g in batch_slice:
        lanes = {
            normalize_lane(getattr(pending_by_id.get(int(fid)), "content_lane", None))
            for fid in g.get("file_ids") or []
            if pending_by_id.get(int(fid))
        }
        if len(lanes) == 1:
            content_lane = next(iter(lanes))
            lane_uniform = True
        elif not lanes:
            content_lane = "media"
            lane_uniform = True
        else:
            content_lane = "mixed"
            lane_uniform = False
        batches.append(
            {
                "match_key": g["match_key"],
                "group_id": g.get("group_id"),
                "show_name": g.get("show_name"),
                "media_type": g.get("media_type"),
                "file_count": len(g.get("file_ids") or []),
                "file_ids": g.get("file_ids") or [],
                "label": g.get("label"),
                "deferred": bool(g.get("deferred")),
                "content_lane": content_lane,
                "lane_uniform": lane_uniform,
                "preview_files": [
                    (f.get("file_name") or "")[:80]
                    for f in (g.get("files") or [])[:5]
                ],
                "files": [
                    {
                        "upload_id": int(fid),
                        "file_name": (
                            pending_by_id[int(fid)].file_name or ""
                        )[:120],
                        "can_stream": can_stream_in_browser(
                            pending_by_id[int(fid)]
                        ),
                        "browser_friendly": browser_friendly_video(
                            pending_by_id[int(fid)].file_name
                        ),
                        "browser_play": can_play_in_browser(pending_by_id[int(fid)]),
                        "can_convert_mp4": _can_convert_mp4(pending_by_id[int(fid)]),
                    }
                    for fid in (g.get("file_ids") or [])[:12]
                    if pending_by_id.get(int(fid))
                ],
            }
        )
    return batches, len(groups), len(batched_ids)


def list_pending(
    *,
    page: int = 1,
    limit: int = 20,
    batch_page: int = 1,
    batch_limit: int | None = None,
) -> dict[str, Any]:
    batch_limit = batch_limit or max(1, Config.PENDING_BATCH_PAGE_SIZE)
    offset = max(0, (page - 1) * limit)
    items, total = db.list_pending_confirmations_page(offset=offset, limit=limit)
    pending_total = db.count_pending_confirmations()

    batches: list[dict[str, Any]] = []
    batch_total = 0
    batched_file_count = 0
    batch_page_count = 1
    try:
        scan_limit = min(Config.PENDING_SCAN_LIMIT, 3000)
        pending = db.get_pending_confirmations(limit=scan_limit)
        batches, batch_total, batched_file_count = _build_batch_page(
            pending, batch_page=batch_page, batch_limit=batch_limit
        )
        batch_page_count = (
            max(1, (batch_total + batch_limit - 1) // batch_limit) if batch_total else 1
        )
    except Exception as e:
        logger.warning("pending batch grouping failed: %s", e)

    from portal.streaming import (
        browser_friendly_video,
        can_play_in_browser,
        can_stream_in_browser,
    )

    pending_items = []
    for item in items:
        row = dict(item)
        upload = db.get_file_upload(int(row["id"]))
        row["can_stream"] = bool(upload and can_stream_in_browser(upload))
        row["browser_friendly"] = browser_friendly_video(row.get("file_name"))
        row["browser_play"] = bool(upload and can_play_in_browser(upload))
        row["can_convert_mp4"] = _can_convert_mp4(upload)
        row["mp4_cached"] = _mp4_cached(int(row["id"]))
        pending_items.append(row)

    return {
        "items": pending_items,
        "total": total,
        "page": page,
        "page_count": max(1, (total + limit - 1) // limit) if total else 1,
        "limit": limit,
        "batches": batches,
        "batch_page": batch_page,
        "batch_page_count": batch_page_count,
        "batch_total": batch_total,
        "batched_file_count": batched_file_count,
        "pending_total": pending_total,
    }


def _infer_pick_media_type(parsed: dict | None) -> str:
    """Prefer TV when filename looks episodic (e.g. One Piece S01E01)."""
    p = parsed or {}
    mt = (p.get("media_type") or "movie").lower()
    if mt in ("series", "show", "tv"):
        return "tv"
    if p.get("episode") is not None or p.get("season") is not None:
        return "tv"
    return mt if mt in ("movie", "tv") else "movie"


def _suggestion_cards(
    suggestions: list[dict],
    *,
    limit: int | None = None,
    index_offset: int = 0,
) -> list[dict]:
    from config import Config
    from tmdb_helper import sort_suggestions_poster_first

    cap = limit if limit is not None else Config.TMDB_PICK_SUGGESTION_LIMIT
    ordered = sort_suggestions_poster_first(suggestions[:cap])
    out = []
    for i, s in enumerate(ordered):
        overview = (s.get("overview") or "").strip()
        if len(overview) > 280:
            overview = overview[:277] + "…"
        out.append(
            {
                "index": index_offset + i,
                "tmdb_id": s.get("tmdb_id"),
                "title": s.get("title"),
                "media_type": s.get("media_type"),
                "year": s.get("year"),
                "vote_average": s.get("vote_average"),
                "overview": overview,
                "poster_url": best_poster_url(s) or poster_image_url(s),
                "tmdb_url": tmdb_web_url(s),
                "from_hint": bool(s.get("from_hint")),
            }
        )
    return out


def pending_tmdb_lookup(
    upload_id: int,
    *,
    search_query: str | None = None,
    page: int = 1,
    per_page: int | None = None,
    filter_type: str = "all",
) -> dict[str, Any]:
    from config import Config

    upload = db.get_file_upload(upload_id)
    if not upload:
        return {"ok": False, "error": "Upload not found"}
    from content_lanes import lane_allows_tmdb, normalize_lane

    lane = normalize_lane(upload.content_lane)
    if not lane_allows_tmdb(lane):
        return {
            "ok": False,
            "error": "TMDB mapping is only for Media or Adult lane. Set lane first.",
            "content_lane": lane,
            "tmdb_enabled": tmdb_helper.enabled,
        }
    page = max(1, int(page))
    per_page_val = max(1, int(per_page or Config.TMDB_PICK_PAGE_SIZE))
    ft = (filter_type or "all").lower()
    if ft not in ("all", "tv", "movie"):
        ft = "all"
    has_more = False

    if search_query and search_query.strip():
        parsed = _parser.parse_name(upload.file_name)
        mt = _infer_pick_media_type(parsed)
        q = search_query.strip()
        suggestions = []
        if tmdb_helper.enabled:
            try:
                yr = int(parsed["year"]) if parsed.get("year") else None
            except (TypeError, ValueError):
                yr = None
            picked = tmdb_helper.search_pick_page(
                q,
                page=page,
                per_page=per_page_val,
                filter_type=ft,
                media_type=mt,
                year=yr,
            )
            suggestions = picked.get("items") or []
            has_more = bool(picked.get("has_more"))
        meta = {
            "parsed": parsed,
            "media_type": mt,
            "search_name": q,
            "local_name": q,
            "suggestions": suggestions,
            "tmdb_unreachable": bool(tmdb_helper._last_api_error) and not suggestions,
            "manual_search": True,
        }
    else:
        meta = build_pick_metadata(
            upload.file_name,
            parser=_parser,
            tmdb_helper=tmdb_helper,
            db=db,
        )
        meta["manual_search"] = False
        if page > 1 and tmdb_helper.enabled:
            parsed0 = meta.get("parsed") or _parser.parse_name(upload.file_name)
            mt = _infer_pick_media_type(parsed0)
            q = meta.get("search_name") or meta.get("local_name") or ""
            try:
                yr = int(parsed0["year"]) if parsed0.get("year") else None
            except (TypeError, ValueError):
                yr = None
            if q:
                picked = tmdb_helper.search_pick_page(
                    q,
                    page=page,
                    per_page=per_page_val,
                    filter_type=ft,
                    media_type=mt,
                    year=yr,
                )
                meta["suggestions"] = picked.get("items") or []
                has_more = bool(picked.get("has_more"))
        else:
            all_sug = meta.get("suggestions") or []
            if (
                tmdb_helper.enabled
                and all_sug
                and not meta.get("tmdb_unreachable")
            ):
                q = meta.get("search_name") or meta.get("local_name") or ""
                parsed0 = meta.get("parsed") or {}
                mt = meta.get("media_type") or "movie"
                try:
                    yr = int(parsed0["year"]) if parsed0.get("year") else None
                except (TypeError, ValueError):
                    yr = None
                if q:
                    probe = tmdb_helper.search_pick_page(
                        q,
                        page=2,
                        per_page=per_page_val,
                        filter_type=ft,
                        media_type=mt,
                        year=yr,
                    )
                    has_more = bool(probe.get("has_more")) or bool(probe.get("items"))
            meta["suggestions"] = (meta.get("suggestions") or [])[:per_page_val]

    parsed = meta.get("parsed") or {}
    show = meta.get("local_name") or meta.get("search_name")
    index_offset = (page - 1) * per_page_val
    return {
        "ok": True,
        "upload_id": upload_id,
        "file_name": upload.file_name,
        "parsed_name": upload.parsed_name,
        "media_type": meta.get("media_type") or "movie",
        "search_label": show or upload.parsed_name,
        "season": parsed.get("season"),
        "episode": parsed.get("episode"),
        "episode_title": parsed.get("episode_title"),
        "tmdb_enabled": tmdb_helper.enabled,
        "tmdb_unreachable": bool(meta.get("tmdb_unreachable")),
        "suggestions": _suggestion_cards(
            sort_suggestions_poster_first(meta.get("suggestions") or []),
            index_offset=index_offset,
        ),
        "search_query": search_query.strip() if search_query and search_query.strip() else None,
        "manual_search": bool(meta.get("manual_search")),
        "page": page,
        "per_page": per_page_val,
        "has_more": has_more,
        "filter_type": ft,
        "_meta": meta,
    }


def _resolve_pending_group(match_key: str) -> dict[str, Any] | None:
    pending = db.get_pending_confirmations(limit=Config.PENDING_SCAN_LIMIT)
    for g in build_pending_groups(pending, parser=_parser):
        if g.get("match_key") == match_key:
            return g
    return None


def _client_pick_selection(
    *,
    tmdb_id: int | None,
    title: str | None = None,
    media_type: str | None = None,
    year: int | None = None,
) -> dict | None:
    """Use the card the admin clicked — do not depend on a second TMDB lookup."""
    if tmdb_id is None:
        return None
    tid = int(tmdb_id)
    if tid <= 0:
        return None
    mt = (media_type or "movie").lower()
    if mt in ("series", "show"):
        mt = "tv"
    out: dict[str, Any] = {
        "tmdb_id": tid,
        "title": (title or "").strip() or None,
        "media_type": mt,
    }
    if year is not None:
        out["year"] = year
    return out


def _resolve_selection(
    meta: dict,
    *,
    suggestion_index: int,
    tmdb_id: int | None = None,
    client: dict | None = None,
) -> dict | None:
    if client and client.get("tmdb_id"):
        return client
    suggestions = list(meta.get("suggestions") or [])
    if tmdb_id is not None:
        tid = int(tmdb_id)
        for s in suggestions:
            if int(s.get("tmdb_id") or 0) == tid:
                return s
    for s in suggestions:
        if int(s.get("index", -1)) == int(suggestion_index):
            return s
    if 0 <= suggestion_index < len(suggestions):
        return suggestions[suggestion_index]
    if tmdb_id and tmdb_helper.enabled:
        mt = (meta.get("media_type") or "movie").lower()
        if mt in ("tv", "series", "show"):
            mt = "tv"
        else:
            mt = "movie" if mt not in ("tv", "movie") else mt
        if mt == "tv":
            details = tmdb_helper.fetch_tv_details(int(tmdb_id)) or {}
        else:
            details = tmdb_helper.fetch_movie_details(int(tmdb_id)) or {}
        title = details.get("tmdb_title") if details else None
        if details or title:
            return {
                "tmdb_id": int(tmdb_id),
                "title": title or f"TMDB #{tmdb_id}",
                "media_type": mt,
                "year": details.get("release_year") if details else None,
                "poster_path": details.get("poster_path") if details else None,
            }
    return None


def _meta_for_bulk_file(file_name: str, selection: dict) -> dict:
    parsed = _parser.parse_name(file_name)
    media_type = selection.get("media_type") or parsed.get("media_type") or "tv"
    show = parsed.get("show_name") or parsed.get("name") or selection.get("title")
    return {
        "parsed": parsed,
        "media_type": media_type,
        "search_name": show,
        "local_name": show,
        "show_group_key": show_group_key(parsed, file_name),
    }


def _apply_one_tmdb(
    upload_id: int,
    selection: dict,
    meta: dict,
    *,
    details: dict | None = None,
    save_hint: bool = True,
) -> bool:
    upload = db.get_file_upload(upload_id)
    if not upload:
        return False
    parsed = meta.get("parsed") or _parser.parse_name(upload.file_name)
    media_type = selection.get("media_type") or meta.get("media_type") or "movie"
    tmdb_id = selection.get("tmdb_id")
    if details is None:
        details = {}
        if tmdb_id and tmdb_helper.enabled:
            if media_type in ("tv", "series"):
                details = tmdb_helper.fetch_tv_details(tmdb_id) or {}
            else:
                details = tmdb_helper.fetch_movie_details(tmdb_id) or {}
    tmdb_title = selection.get("title") or details.get("tmdb_title")
    local_name = meta.get("local_name") or meta.get("search_name")
    if tmdb_title:
        local_name = tmdb_title
    if media_type in ("tv", "series"):
        display = episode_display_name(
            tmdb_title or local_name or "",
            parsed.get("season"),
            parsed.get("episode"),
            parsed.get("episode_title"),
        )
    else:
        display = tmdb_title or local_name or upload.parsed_name

    row = db.apply_tmdb_pick(
        upload_id,
        tmdb_id=tmdb_id,
        tmdb_title=tmdb_title,
        media_type="tv" if media_type in ("tv", "series") else "movie",
        local_name=local_name,
        parsed_name=display,
        season_number=parsed.get("season"),
        episode_number=parsed.get("episode"),
        episode_title=parsed.get("episode_title"),
        release_year=details.get("release_year") or selection.get("year"),
        poster_path=details.get("poster_path"),
        overview=details.get("overview"),
        vote_average=details.get("vote_average"),
        genres=details.get("genres"),
        library_visible=bool(tmdb_id),
    )
    if row:
        db.promote_upload_to_library(upload_id)
        if save_hint and tmdb_id:
            hint_key = meta.get("show_group_key") or show_group_key(
                parsed, upload.file_name
            )
            if hint_key:
                db.save_title_hint(
                    hint_key,
                    tmdb_id=tmdb_id,
                    tmdb_title=tmdb_title,
                    media_type="tv" if media_type in ("tv", "series") else "movie",
                )
    return bool(row)


def apply_tmdb_bulk(file_ids: list[int], selection: dict) -> int:
    media_type = selection.get("media_type") or "tv"
    tmdb_id = selection.get("tmdb_id")
    details: dict = {}
    if tmdb_id and tmdb_helper.enabled:
        if media_type in ("tv", "series"):
            details = tmdb_helper.fetch_tv_details(tmdb_id) or {}
        else:
            details = tmdb_helper.fetch_movie_details(tmdb_id) or {}

    applied = 0
    hint_key: str | None = None
    for fid in file_ids:
        upload = db.get_file_upload(fid)
        if not upload:
            continue
        meta = _meta_for_bulk_file(upload.file_name, selection)
        if not hint_key:
            hint_key = meta.get("show_group_key")
        if _apply_one_tmdb(fid, selection, meta, details=details, save_hint=False):
            applied += 1

    if applied and tmdb_id and hint_key:
        db.save_title_hint(
            hint_key,
            tmdb_id=tmdb_id,
            tmdb_title=selection.get("title") or details.get("tmdb_title"),
            media_type="tv" if media_type in ("tv", "series") else "movie",
        )
    return applied


def batch_tmdb_lookup(
    match_key: str,
    *,
    search_query: str | None = None,
    page: int = 1,
    per_page: int | None = None,
    filter_type: str = "all",
) -> dict[str, Any]:
    group = _resolve_pending_group(match_key)
    if not group:
        return {"ok": False, "error": "Batch not found"}
    file_ids = group.get("file_ids") or []
    if not file_ids:
        return {"ok": False, "error": "Batch has no files"}
    first = db.get_file_upload(file_ids[0])
    if not first:
        return {"ok": False, "error": "Upload not found"}
    from content_lanes import lane_allows_tmdb, normalize_lane

    lanes = {
        normalize_lane(db.get_file_upload(fid).content_lane)
        for fid in file_ids
        if db.get_file_upload(fid)
    }
    if len(lanes) != 1:
        return {
            "ok": False,
            "error": "Batch has mixed lanes — set one lane for all files first.",
        }
    batch_lane = next(iter(lanes))
    if not lane_allows_tmdb(batch_lane):
        return {
            "ok": False,
            "error": "TMDB batch pick is only for Media or Adult lane.",
            "content_lane": batch_lane,
        }
    lookup = pending_tmdb_lookup(
        first.id,
        search_query=search_query.strip() if search_query and search_query.strip() else None,
        page=page,
        per_page=per_page,
        filter_type=filter_type,
    )
    if not lookup.get("ok"):
        return lookup
    lookup["match_key"] = match_key
    lookup["file_ids"] = file_ids
    lookup["file_count"] = len(file_ids)
    lookup["show_name"] = group.get("show_name")
    lookup["batch"] = True
    meta = lookup.pop("_meta", {})
    meta["bulk_file_ids"] = file_ids
    meta["bulk_match_key"] = match_key
    lookup["_meta"] = meta
    if not search_query:
        lookup["search_label"] = group.get("show_name") or lookup.get("search_label")
    return lookup


def apply_batch_tmdb_pick(
    match_key: str,
    *,
    suggestion_index: int = 0,
    search_query: str | None = None,
    tmdb_id: int | None = None,
    page: int = 1,
    title: str | None = None,
    media_type: str | None = None,
    year: int | None = None,
) -> dict[str, Any]:
    client_sel = _client_pick_selection(
        tmdb_id=tmdb_id, title=title, media_type=media_type, year=year
    )
    lookup = batch_tmdb_lookup(
        match_key, search_query=search_query, page=max(1, int(page or 1))
    )
    if not lookup.get("ok"):
        return lookup
    meta = lookup.get("_meta") or {}
    display_suggestions = list(lookup.get("suggestions") or [])
    file_ids = meta.get("bulk_file_ids") or lookup.get("file_ids") or []
    selection = _resolve_selection(
        meta,
        suggestion_index=suggestion_index,
        tmdb_id=tmdb_id,
        client=client_sel,
    )
    if not selection and display_suggestions:
        selection = _resolve_selection(
            {"suggestions": display_suggestions},
            suggestion_index=suggestion_index,
            tmdb_id=tmdb_id,
            client=client_sel,
        )
    if not selection:
        return {"ok": False, "error": "Suggestion not found"}
    from content_lanes import lane_allows_tmdb, normalize_lane

    if not selection.get("tmdb_id"):
        for fid in file_ids:
            u = db.get_file_upload(int(fid))
            if (
                u
                and u.needs_confirmation
                and not u.is_confirmed
                and lane_allows_tmdb(normalize_lane(u.content_lane))
            ):
                return {
                    "ok": False,
                    "error": "Select a TMDB match from the list — required for Media and Adult lanes.",
                }
    n = apply_tmdb_bulk(file_ids, selection)
    title = selection.get("title") or "title"
    return {
        "ok": n > 0,
        "applied": n,
        "message": f"Linked {n} file(s) to {title}",
        "title": title,
    }


def apply_tmdb_suggestion(
    upload_id: int,
    *,
    suggestion_index: int = 0,
    search_query: str | None = None,
    tmdb_id: int | None = None,
    apply_siblings: bool = False,
    page: int = 1,
    title: str | None = None,
    media_type: str | None = None,
    year: int | None = None,
    meta: dict | None = None,
) -> dict[str, Any]:
    upload = db.get_file_upload(upload_id)
    if not upload:
        return {"ok": False, "error": "Upload not found"}
    client_sel = _client_pick_selection(
        tmdb_id=tmdb_id, title=title, media_type=media_type, year=year
    )
    display_suggestions: list[dict] = []
    if meta is None:
        lookup = pending_tmdb_lookup(
            upload_id, search_query=search_query, page=max(1, int(page or 1))
        )
        if not lookup.get("ok"):
            return lookup
        meta = lookup.get("_meta") or {}
        display_suggestions = list(lookup.get("suggestions") or [])
    selection = _resolve_selection(
        meta,
        suggestion_index=suggestion_index,
        tmdb_id=tmdb_id,
        client=client_sel,
    )
    if not selection and display_suggestions:
        selection = _resolve_selection(
            {"suggestions": display_suggestions},
            suggestion_index=suggestion_index,
            tmdb_id=tmdb_id,
            client=client_sel,
        )
    if not selection:
        return {"ok": False, "error": "Suggestion not found"}
    from content_lanes import lane_allows_tmdb, normalize_lane

    lane = normalize_lane(upload.content_lane)
    if (
        upload.needs_confirmation
        and not upload.is_confirmed
        and lane_allows_tmdb(lane)
        and not selection.get("tmdb_id")
    ):
        return {
            "ok": False,
            "error": "Select a TMDB match from the list — required for Media and Adult lanes.",
        }
    if not meta.get("show_group_key"):
        parsed = meta.get("parsed") or _parser.parse_name(upload.file_name)
        meta["show_group_key"] = show_group_key(parsed, upload.file_name)
    ok = _apply_one_tmdb(upload_id, selection, meta)
    title = selection.get("title") or upload.parsed_name
    out: dict[str, Any] = {
        "ok": ok,
        "message": f"Linked to {title}" if ok else "Could not save pick",
        "title": title,
    }
    if ok and not apply_siblings:
        pending = db.get_pending_confirmations(limit=500)
        parsed = meta.get("parsed") or _parser.parse_name(upload.file_name)
        sib_ids = sibling_pending_ids(
            pending,
            parser=_parser,
            anchor_file_id=upload_id,
            anchor_parsed=parsed,
            anchor_file_name=upload.file_name,
        )
        out["sibling_count"] = len(sib_ids)
    if ok and apply_siblings:
        pending = db.get_pending_confirmations(limit=500)
        parsed = meta.get("parsed") or _parser.parse_name(upload.file_name)
        sib_ids = sibling_pending_ids(
            pending,
            parser=_parser,
            anchor_file_id=upload_id,
            anchor_parsed=parsed,
            anchor_file_name=upload.file_name,
        )
        n = apply_tmdb_bulk(sib_ids, selection) if sib_ids else 0
        out["siblings_applied"] = n
        if n:
            out["message"] = f"Linked + applied to {n} similar file(s)"
    return out


def list_remap_uploads(content_title_id: int) -> dict[str, Any]:
    """Indexed files under a library title (portal TMDB remap)."""
    from content_lanes import LANE_LABELS, lane_allows_tmdb, normalize_lane
    from portal.streaming import can_play_in_browser

    ct = db.get_content_title(int(content_title_id))
    if not ct:
        return {"ok": False, "error": "Title not found"}
    uploads = db.list_uploads_for_content_admin(int(content_title_id))
    items = []
    for u in uploads:
        lane = normalize_lane(u.content_lane)
        is_pending = bool(u.needs_confirmation and not u.is_confirmed)
        allows_tmdb = lane_allows_tmdb(lane)
        items.append(
            {
                "upload_id": u.id,
                "file_name": u.file_name,
                "parsed_name": u.parsed_name,
                "confirmed_name": u.confirmed_name,
                "content_lane": lane,
                "content_lane_label": LANE_LABELS.get(lane, lane),
                "season_number": u.season_number,
                "episode_number": u.episode_number,
                "library_visible": bool(u.library_visible),
                "lane_allows_tmdb": allows_tmdb,
                "is_pending": is_pending,
                "can_queue_tmdb": not is_pending and not allows_tmdb,
                "browser_play": can_play_in_browser(u),
            }
        )
    return {
        "ok": True,
        "content_title_id": int(content_title_id),
        "title": ct.tmdb_title or ct.name,
        "tmdb_id": ct.tmdb_id,
        "media_type": ct.media_type,
        "uploads": items,
        "lanes": [
            {"id": "media", "label": "Media library"},
            {"id": "adult", "label": "Adult vault"},
            {"id": "course", "label": "Course"},
            {"id": "archive", "label": "Archive"},
            {"id": "shortform", "label": "Shortform"},
        ],
    }


def set_upload_content_lane(upload_id: int, lane: str) -> dict[str, Any]:
    """Set lane on a confirmed/indexed upload (not pending queue)."""
    from content_lanes import LANE_LABELS, VALID_LANES, lane_allows_tmdb, normalize_lane

    upload = db.get_file_upload(upload_id)
    if not upload:
        return {"ok": False, "error": "Upload not found"}
    if upload.needs_confirmation and not upload.is_confirmed:
        return set_pending_upload_lane(upload_id, lane)

    lane = normalize_lane(lane)
    if lane not in VALID_LANES:
        return {"ok": False, "error": "Invalid lane"}
    row = db.set_upload_content_lane(upload_id, lane)
    if not row:
        return {"ok": False, "error": "Upload not found"}
    label = LANE_LABELS.get(lane, lane)
    msg = f"Content lane: {label}"
    if lane_allows_tmdb(lane):
        msg += " — use Change TMDB or Send to Pending (TMDB)"
    return {
        "ok": True,
        "message": msg,
        "content_lane": lane,
        "upload_id": upload_id,
        "lane_allows_tmdb": lane_allows_tmdb(lane),
        "removed_from_pending": False,
    }


def set_title_uploads_lane(content_title_id: int, lane: str) -> dict[str, Any]:
    """Apply one lane to every file on a title (pending + indexed)."""
    ct = db.get_content_title(int(content_title_id))
    if not ct:
        return {"ok": False, "error": "Title not found"}
    lane = (lane or "").strip()
    if not lane:
        return {"ok": False, "error": "lane required"}

    uploads = db.list_uploads_for_content_admin(int(content_title_id))
    if not uploads:
        return {"ok": False, "error": "No files on this title"}

    updated = 0
    removed_from_pending = 0
    errors: list[str] = []
    for u in uploads:
        r = set_pending_upload_lane(int(u.id), lane)
        if r.get("ok"):
            updated += 1
            if r.get("removed_from_pending"):
                removed_from_pending += 1
        else:
            errors.append(f"#{u.id}: {r.get('error', 'failed')}")

    from content_lanes import LANE_LABELS, normalize_lane

    label = LANE_LABELS.get(normalize_lane(lane), lane)
    msg = f"{label} applied to {updated}/{len(uploads)} file(s)"
    if removed_from_pending:
        msg += f" · {removed_from_pending} left pending queue"
    return {
        "ok": updated > 0,
        "message": msg,
        "content_title_id": int(content_title_id),
        "content_lane": normalize_lane(lane),
        "updated": updated,
        "total": len(uploads),
        "removed_from_pending": removed_from_pending,
        "errors": errors[:8],
    }


def queue_upload_for_tmdb_mapping(upload_id: int) -> dict[str, Any]:
    """Return an indexed file to the pending queue for TMDB mapping (media lane)."""
    from content_lanes import LANE_LABELS, LANE_MEDIA, normalize_lane

    upload = db.get_file_upload(upload_id)
    if not upload:
        return {"ok": False, "error": "Upload not found"}
    if (upload.ingest_state or "") == "skipped":
        return {"ok": False, "error": "Upload was removed"}
    if upload.needs_confirmation and not upload.is_confirmed:
        return {
            "ok": True,
            "message": "Already in pending — open Pending list to map TMDB",
            "already_pending": True,
            "content_lane": normalize_lane(upload.content_lane),
        }
    row = db.queue_upload_for_tmdb_pending(upload_id)
    if not row:
        return {"ok": False, "error": "Could not queue"}
    label = LANE_LABELS.get(LANE_MEDIA, LANE_MEDIA)
    return {
        "ok": True,
        "message": f"Sent to Pending ({label}) for TMDB mapping",
        "content_lane": LANE_MEDIA,
        "queued": True,
    }


def set_pending_upload_lane(upload_id: int, lane: str) -> dict[str, Any]:
    """Set content lane on one pending file; non-media lanes leave the pending queue."""
    from content_lanes import LANE_ADULT, LANE_LABELS, LANE_MEDIA, normalize_lane

    upload = db.get_file_upload(upload_id)
    if not upload:
        return {"ok": False, "error": "Upload not found"}
    if (upload.ingest_state or "") == "skipped":
        return {"ok": False, "error": "Upload was removed"}

    lane = normalize_lane(lane)
    label = LANE_LABELS.get(lane, lane)

    if not upload.needs_confirmation or upload.is_confirmed:
        out = set_upload_content_lane(upload_id, lane)
        if not out.get("ok"):
            return out
        out["removed_from_pending"] = False
        return out

    row = db.set_upload_content_lane(upload_id, lane)
    if not row:
        return {"ok": False, "error": "Upload not found"}

    if lane == LANE_MEDIA:
        return {
            "ok": True,
            "message": f"{label} — still pending (use TMDB map)",
            "content_lane": lane,
            "removed_from_pending": False,
        }

    if lane == LANE_ADULT:
        return {
            "ok": True,
            "message": f"{label} — removed from pending",
            "content_lane": lane,
            "removed_from_pending": True,
        }

    confirmed = confirm_pending_without_tmdb(upload_id)
    if not confirmed.get("ok"):
        return confirmed
    return {
        "ok": True,
        "message": f"{label} — removed from pending",
        "content_lane": lane,
        "removed_from_pending": True,
    }


def set_pending_batch_lane(
    match_key: str,
    lane: str,
    *,
    file_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Set content lane on every file in a pending batch."""
    from content_lanes import LANE_LABELS, normalize_lane

    lane = normalize_lane(lane)
    ids: list[int] = []
    if file_ids:
        ids = [int(x) for x in file_ids if x is not None]
    if not ids:
        group = _resolve_pending_group(match_key)
        if not group:
            return {
                "ok": False,
                "error": "Batch not found — refresh the page and try again",
            }
        ids = [int(x) for x in (group.get("file_ids") or [])]
    if not ids:
        return {"ok": False, "error": "Batch has no files"}
    from content_lanes import LANE_ADULT, LANE_MEDIA

    updated = 0
    removed = 0
    errors: list[str] = []
    for fid in ids:
        upload = db.get_file_upload(int(fid))
        if not upload or (upload.ingest_state or "") == "skipped":
            continue
        was_pending = bool(upload.needs_confirmation and not upload.is_confirmed)
        if not db.set_upload_content_lane(int(fid), lane):
            continue
        updated += 1
        if not was_pending:
            continue
        if lane == LANE_MEDIA:
            continue
        if lane == LANE_ADULT:
            removed += 1
            continue
        result = confirm_pending_without_tmdb(int(fid))
        if result.get("ok"):
            removed += 1
        elif result.get("error"):
            errors.append(str(result["error"])[:120])
    label = LANE_LABELS.get(lane, lane)
    if lane == LANE_MEDIA:
        msg = f"{label} — {updated} file(s); still pending (use TMDB batch)"
    elif removed:
        msg = f"{label} — {removed} file(s) removed from pending"
    elif errors:
        msg = f"{label} — lane set but could not confirm: {errors[0]}"
    else:
        msg = f"{label} — {updated} file(s)"
    return {
        "ok": updated > 0 and (lane == LANE_MEDIA or removed > 0 or not errors),
        "message": msg,
        "content_lane": lane,
        "updated": updated,
        "removed_from_pending": removed,
        "errors": errors[:3],
        "match_key": match_key,
    }


def retry_pending_tmdb(upload_id: int) -> dict[str, Any]:
    """Re-run auto TMDB lookup for one pending file (like bot Retry TMDB search)."""
    upload = db.get_file_upload(upload_id)
    if not upload:
        return {"ok": False, "error": "Upload not found"}
    meta = build_pick_metadata(
        upload.file_name,
        parser=_parser,
        tmdb_helper=tmdb_helper,
        db=db,
    )
    if tmdb_helper.enabled and not meta.get("suggestions"):
        try:
            db.refresh_pending_upload_from_meta(
                upload_id,
                build_index_metadata(
                    upload.file_name,
                    parser=_parser,
                    tmdb_helper=tmdb_helper,
                    db=db,
                ),
            )
        except Exception as e:
            logger.debug("retry auto-index #%s: %s", upload_id, e)
    data = pending_tmdb_lookup(upload_id)
    data.pop("_meta", None)
    return data


upload_tmdb_lookup = pending_tmdb_lookup
retry_upload_tmdb = retry_pending_tmdb


def retry_all_pending_tmdb() -> dict[str, Any]:
    """Re-run TMDB index on all pending files (like bot Retry TMDB all)."""
    if not tmdb_helper.enabled:
        return {"ok": False, "error": "TMDB not configured"}
    pending = db.get_pending_confirmations(limit=Config.PENDING_SCAN_LIMIT)
    stats = {
        "total": len(pending),
        "scanned": 0,
        "matched": 0,
        "still_pending": 0,
        "api_errors": 0,
        "errors": 0,
    }
    for upload in pending:
        stats["scanned"] += 1
        try:
            meta = build_index_metadata(
                upload.file_name,
                parser=_parser,
                tmdb_helper=tmdb_helper,
                db=db,
            )
            api_err = bool(tmdb_helper._last_api_error) and meta.get("needs_tmdb_pick")
            outcome = db.refresh_pending_upload_from_meta(upload.id, meta)
            if outcome == "matched":
                stats["matched"] += 1
            elif outcome == "still_pending":
                stats["still_pending"] += 1
                if api_err:
                    stats["api_errors"] += 1
        except Exception:
            stats["errors"] += 1
            logger.exception("retry_all_pending failed for #%s", upload.id)
    stats["remaining"] = db.count_pending_confirmations()
    return {
        "ok": True,
        "message": (
            f"Scanned {stats['scanned']}, auto-matched {stats['matched']}, "
            f"{stats['remaining']} still pending"
        ),
        **stats,
    }


def approve_pending(upload_id: int) -> dict[str, Any]:
    """Deprecated — Media/Adult must use TMDB pick; other lanes use confirm."""
    upload = db.get_file_upload(upload_id)
    if not upload:
        return {"ok": False, "error": "Upload not found"}
    from content_lanes import lane_allows_tmdb, normalize_lane

    lane = normalize_lane(upload.content_lane)
    if lane_allows_tmdb(lane):
        return {
            "ok": False,
            "error": "Use 🎬 TMDB map for Media or Adult lane files. Approve is disabled.",
        }
    return confirm_pending_without_tmdb(upload_id)


def _confirm_pending_lane_minimal(upload_id: int, lane: str) -> bool:
    """Confirm pending file when content-title upsert fails (name collision, etc.)."""
    from content_lanes import LANE_ARCHIVE, LANE_COURSE, LANE_SHORTFORM, normalize_lane
    from database import FileUpload

    lane = normalize_lane(lane)
    upload = db.get_file_upload(upload_id)
    if not upload or not upload.needs_confirmation or upload.is_confirmed:
        return False
    label = (upload.parsed_name or upload.file_name or "Upload")[:200]
    library_visible = lane == LANE_COURSE
    session = db.get_session()
    try:
        row = session.query(FileUpload).filter_by(id=int(upload_id)).first()
        if not row:
            return False
        row.content_lane = lane
        row.parsed_name = label
        row.confirmed_name = label
        row.is_confirmed = True
        row.needs_confirmation = False
        row.pending_deferred_at = None
        row.library_visible = bool(library_visible)
        row.distribution_approved = bool(library_visible)
        row.ingest_state = "normal"
        session.commit()
        if lane == LANE_COURSE:
            db.promote_upload_to_library(upload_id)
        return True
    except Exception as e:
        session.rollback()
        logger.warning("_confirm_pending_lane_minimal %s: %s", upload_id, e)
        return False
    finally:
        session.close()


def confirm_pending_without_tmdb(upload_id: int) -> dict[str, Any]:
    """Confirm pending uploads on lanes that do not use TMDB (course, archive, shortform)."""
    from content_lanes import (
        LANE_ARCHIVE,
        LANE_COURSE,
        LANE_SHORTFORM,
        lane_allows_tmdb,
        normalize_lane,
    )

    upload = db.get_file_upload(upload_id)
    if not upload:
        return {"ok": False, "error": "Upload not found"}
    if not upload.needs_confirmation or upload.is_confirmed:
        return {"ok": False, "error": "Not in pending queue"}
    lane = normalize_lane(upload.content_lane)
    if lane_allows_tmdb(lane):
        return {
            "ok": False,
            "error": "Use 🎬 TMDB map for Media or Adult lane files.",
        }

    parsed = _parser.parse_name(upload.file_name)
    mt = (parsed.get("media_type") or "movie").lower()
    if mt in ("series", "show"):
        mt = "tv"
    if lane == LANE_COURSE:
        mt = "course"
    local = (
        parsed.get("show_name")
        or parsed.get("name")
        or upload.parsed_name
        or upload.file_name
    )
    if mt == "tv":
        display = episode_display_name(
            local,
            parsed.get("season"),
            parsed.get("episode"),
            parsed.get("episode_title"),
        )
    else:
        display = local

    catalog_excluded = lane in (LANE_ARCHIVE, LANE_SHORTFORM)
    library_visible = lane == LANE_COURSE

    try:
        row = db.apply_tmdb_pick(
            upload_id,
            local_name=str(local)[:200],
            parsed_name=display,
            media_type=mt,
            season_number=parsed.get("season"),
            episode_number=parsed.get("episode"),
            episode_title=parsed.get("episode_title"),
            library_visible=library_visible,
            catalog_excluded=catalog_excluded,
        )
        if not row:
            if _confirm_pending_lane_minimal(upload_id, lane):
                return {
                    "ok": True,
                    "message": "Confirmed — removed from pending",
                    "content_lane": lane,
                }
            return {"ok": False, "error": "Could not confirm upload"}
        if lane == LANE_COURSE:
            db.promote_upload_to_library(upload_id)
        return {
            "ok": True,
            "message": "Confirmed — removed from pending",
            "content_lane": lane,
        }
    except Exception as e:
        logger.warning("confirm_pending_without_tmdb %s: %s", upload_id, e)
        if _confirm_pending_lane_minimal(upload_id, lane):
            return {
                "ok": True,
                "message": "Confirmed — removed from pending",
                "content_lane": lane,
            }
        return {"ok": False, "error": str(e)[:200]}


def _skip_catalog_upload(upload_id: int, *, library_only: bool = False) -> bool:
    """Confirm without TMDB; exclude from watch channel (matches bot skip catalog)."""
    upload = db.get_file_upload(upload_id)
    if not upload:
        return False
    parsed = _parser.parse_name(upload.file_name)
    mt = (parsed.get("media_type") or "movie").lower()
    if mt in ("series", "show"):
        mt = "tv"
    local = (
        parsed.get("show_name")
        or parsed.get("name")
        or upload.parsed_name
        or upload.file_name
    )
    if mt == "tv":
        display = episode_display_name(
            local,
            parsed.get("season"),
            parsed.get("episode"),
            parsed.get("episode_title"),
        )
    else:
        display = local
    return (
        db.apply_tmdb_pick(
            upload_id,
            local_name=str(local)[:200],
            parsed_name=display,
            media_type=mt,
            season_number=parsed.get("season"),
            episode_number=parsed.get("episode"),
            episode_title=parsed.get("episode_title"),
            library_visible=library_only,
            catalog_excluded=True,
            indexed_only=True,
        )
        is not None
    )


def defer_pending(upload_id: int) -> dict[str, Any]:
    n = db.defer_pending_files([int(upload_id)])
    return {
        "ok": n > 0,
        "message": "Skipped for now — moved to end of queue" if n else "Not found",
    }


def defer_pending_batch(match_key: str) -> dict[str, Any]:
    group = _resolve_pending_group(match_key)
    if not group:
        return {"ok": False, "error": "Batch not found"}
    file_ids = group.get("file_ids") or []
    n = db.defer_pending_files(file_ids)
    label = group.get("show_name") or "Batch"
    return {
        "ok": n > 0,
        "count": n,
        "message": f"Skipped for now — {n} file(s) in “{label}” moved to end of queue"
        if n
        else "Not found",
    }


def skip_catalog_pending(upload_id: int) -> dict[str, Any]:
    ok = _skip_catalog_upload(int(upload_id), library_only=False)
    return {
        "ok": ok,
        "message": "Skipped watch catalog — indexed only" if ok else "Not found",
    }


def skip_catalog_pending_batch(match_key: str) -> dict[str, Any]:
    group = _resolve_pending_group(match_key)
    if not group:
        return {"ok": False, "error": "Batch not found"}
    n = sum(
        1 for fid in (group.get("file_ids") or []) if _skip_catalog_upload(fid)
    )
    label = group.get("show_name") or "Batch"
    return {
        "ok": n > 0,
        "count": n,
        "message": f"Skipped watch catalog for {n} file(s) in “{label}”"
        if n
        else "Nothing updated",
    }


def skip_pending(upload_id: int) -> dict[str, Any]:
    ok = db.skip_pending_upload(int(upload_id))
    return {"ok": ok, "message": "Removed from pending queue" if ok else "Not found"}


def list_user_requests(*, page: int = 1, limit: int = 12) -> dict[str, Any]:
    page = max(1, int(page))
    limit = max(1, min(int(limit), 48))
    offset = (page - 1) * limit
    total = db.count_pending_upload_requests()
    rows = db.get_pending_upload_requests(limit=limit, offset=offset)
    items = []
    for r in rows:
        mt = (r.media_type or "movie").lower()
        poster = None
        overview = ""
        if r.tmdb_id and tmdb_helper.enabled:
            if mt in ("tv", "series"):
                details = tmdb_helper.fetch_tv_details(int(r.tmdb_id)) or {}
            else:
                details = tmdb_helper.fetch_movie_details(int(r.tmdb_id)) or {}
            poster = best_poster_url(details)
            overview = (details.get("overview") or "")[:320]
        items.append(
            {
                "id": r.id,
                "user_id": r.user_id,
                "tmdb_id": r.tmdb_id,
                "title": r.tmdb_title,
                "media_type": mt,
                "release_year": r.release_year,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "poster_url": poster,
                "overview": overview,
                "tmdb_url": tmdb_web_url({"tmdb_id": r.tmdb_id, "media_type": mt})
                if r.tmdb_id
                else None,
            }
        )
    pages = max(1, (total + limit - 1) // limit) if total else 1
    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": pages,
        "limit": limit,
    }


def resolve_request(request_id: int, *, status: str) -> dict[str, Any]:
    if status not in ("done", "rejected"):
        return {"ok": False, "error": "status must be done or rejected"}
    ok = db.set_upload_request_status(int(request_id), status)
    return {"ok": ok, "message": f"Marked {status}" if ok else "Request not found"}


def list_unpublished_catalog(*, limit: int = 30) -> dict[str, Any]:
    slots = db.get_unpublished_catalog_slots(limit=limit)
    items = []
    for s in slots:
        ct = db.get_content_title(s["content_title_id"])
        items.append(
            {
                "content_title_id": s["content_title_id"],
                "season_number": s.get("season_number"),
                "title": (ct.tmdb_title or ct.name) if ct else "?",
                "media_type": ct.media_type if ct else None,
            }
        )
    return {"items": items, "total": db.count_unpublished_catalog_slots()}


_catalog_publish_all_task: asyncio.Task | None = None
_catalog_publish_all_result: dict[str, Any] | None = None


async def start_publish_catalog_all() -> dict[str, Any]:
    """Queue publish for all unpublished slots (runs in background)."""
    global _catalog_publish_all_task, _catalog_publish_all_result

    if _catalog_publish_all_task and not _catalog_publish_all_task.done():
        return {"ok": False, "status": "running", "message": "Publish all is already running"}

    unpublished = db.count_unpublished_catalog_slots()
    if not unpublished:
        return {"ok": True, "status": "idle", "message": "Nothing to publish", "published": 0}

    queue_total = unpublished
    _catalog_publish_all_result = {
        "status": "running",
        "published": 0,
        "failed": 0,
        "processed": 0,
        "total": queue_total,
        "remaining": unpublished,
    }

    async def _run() -> None:
        global _catalog_publish_all_result
        bot = Bot(token=Config.BOT_TOKEN)
        try:
            me = await bot.get_me()

            async def _progress(
                done: int,
                ok: int,
                fail: int,
                _batch_num: int,
                total: int = 0,
            ) -> None:
                _catalog_publish_all_result.update(
                    {
                        "status": "running",
                        "published": ok,
                        "failed": fail,
                        "processed": done,
                        "total": total or queue_total,
                        "remaining": max(0, (total or queue_total) - done),
                    }
                )

            ok, fail, errors, _total, stats = await publish_catalog_all(
                bot,
                db,
                bot_username=me.username,
                max_total=0,
                progress_callback=_progress,
            )
            _catalog_publish_all_result = {
                "ok": fail == 0 or ok > 0,
                "status": "done",
                "published": ok,
                "failed": fail,
                "processed": ok + fail,
                "total": stats.get("queue_total") or queue_total,
                "errors": errors[:10],
                "stats": stats,
                "remaining": db.count_unpublished_catalog_slots(),
                "message": f"Published {ok} catalog card(s), {fail} failed",
            }
        except Exception as e:
            logger.exception("publish_catalog_all failed: %s", e)
            _catalog_publish_all_result = {
                "ok": False,
                "status": "error",
                "message": str(e),
            }

    _catalog_publish_all_task = asyncio.create_task(_run())
    return {
        "ok": True,
        "status": "running",
        "message": f"Publishing {unpublished} catalog card(s) in background…",
        "total": queue_total,
        "remaining": unpublished,
    }


def publish_catalog_all_status() -> dict[str, Any]:
    if _catalog_publish_all_task and not _catalog_publish_all_task.done():
        base = _catalog_publish_all_result or {}
        total = base.get("total")
        processed = base.get("processed", 0)
        remaining = base.get("remaining")
        if remaining is None and total is not None:
            remaining = max(0, int(total) - int(processed))
        return {
            "status": "running",
            "total": total,
            "processed": processed,
            "remaining": remaining,
            "published": base.get("published", 0),
            "failed": base.get("failed", 0),
        }
    if _catalog_publish_all_result:
        return dict(_catalog_publish_all_result)
    return {"status": "idle"}


async def publish_catalog_chunk(*, limit: int = 10) -> dict[str, Any]:
    bot = Bot(token=Config.BOT_TOKEN)
    me = await bot.get_me()
    slots = db.get_unpublished_catalog_slots(limit=limit)
    if not slots:
        return {"ok": True, "message": "Nothing to publish", "published": 0}
    ok, fail, errors, n, stats = await publish_catalog_batch(
        bot,
        db,
        limit=limit,
        slots=slots,
        bot_username=me.username,
    )
    return {
        "ok": fail == 0 or ok > 0,
        "published": ok,
        "failed": fail,
        "errors": errors[:5],
        "stats": stats,
        "message": f"Published {ok} catalog card(s), {fail} failed",
    }


def list_filename_strip_rules() -> dict[str, Any]:
    rules = db.list_filename_strip_rules(active_only=False)
    return {"rules": rules, "total": len(rules)}


def add_filename_strip_rule(
    pattern: str, *, note: str | None = None, is_regex: bool = False
) -> dict[str, Any]:
    from name_parser import invalidate_filename_strip_rules_cache

    row = db.add_filename_strip_rule(pattern, note=note, is_regex=is_regex)
    if not row:
        return {"ok": False, "error": "Pattern cannot be empty"}
    invalidate_filename_strip_rules_cache()
    return {"ok": True, "rule": row}


def delete_filename_strip_rule(rule_id: int) -> dict[str, Any]:
    from name_parser import invalidate_filename_strip_rules_cache

    ok = db.delete_filename_strip_rule(rule_id)
    if ok:
        invalidate_filename_strip_rules_cache()
    return {"ok": ok}


def preview_filename_strip(filename: str) -> dict[str, Any]:
    from name_parser import apply_filename_strip_rules

    stripped = apply_filename_strip_rules(filename)
    parsed = _parser.parse_name(filename)
    title = parsed.get("show_name") or parsed.get("name")
    return {
        "filename": filename,
        "stripped": stripped,
        "parsed_title": title,
        "media_type": parsed.get("media_type"),
        "year": parsed.get("year"),
    }


def start_upload_mp4_convert(upload_id: int) -> dict[str, Any]:
    from portal.convert_pipeline import schedule_convert

    return schedule_convert(int(upload_id), db)


def upload_mp4_convert_status(upload_id: int) -> dict[str, Any]:
    from portal.convert_pipeline import convert_status, mp4_cache_ready

    uid = int(upload_id)
    st = convert_status(uid) or {}
    if mp4_cache_ready(uid) and st.get("phase") != "complete":
        st = {**st, "phase": "complete", "cached": True}
    return {"ok": True, "upload_id": uid, **st}


def pipeline_status() -> dict[str, Any]:
    from pipeline_status import get_pipeline_readiness

    return get_pipeline_readiness(db=db)


def pipeline_defaults() -> dict[str, Any]:
    from content_lanes import LANE_LABELS
    from pipeline_setup import PIPELINE_UPLOAD_TYPES

    rows = db.list_pipeline_upload_defaults()
    channels = [
        {
            "channel_id": str(c.channel_id),
            "title": c.channel_title,
            "username": c.channel_username,
        }
        for c in db.get_channels_bot_can_post(active_only=True)
    ]
    types = []
    for row in rows:
        ut = row["upload_type"]
        label = dict(PIPELINE_UPLOAD_TYPES).get(ut, LANE_LABELS.get(ut, ut))
        types.append({**row, "label": label})
    from content_lanes import LANE_MEDIA

    dist = db.list_watch_lane_assignments()
    media_pub = dist.get(LANE_MEDIA)
    return {
        "upload_types": types,
        "postable_channels": channels,
        "media_publish_channel": (
            {
                "channel_id": str(media_pub.channel_id),
                "title": media_pub.channel_title,
                "username": media_pub.channel_username,
            }
            if media_pub
            else None
        ),
    }


def set_pipeline_source(upload_type: str, source_channel_id: str | None) -> dict[str, Any]:
    ok = db.set_pipeline_source_channel(upload_type, source_channel_id)
    return {"ok": ok}


def list_upload_jobs_admin(*, limit: int = 30) -> dict[str, Any]:
    jobs = db.list_upload_jobs(limit=limit)
    out = []
    for j in jobs:
        summary = db.get_upload_job_summary(j.id)
        out.append(
            {
                "id": j.id,
                "name": j.name,
                "status": j.status,
                "content_lane": j.content_lane,
                "target_channel_id": j.target_channel_id,
                "course_title": j.course_title,
                "total_items": summary.get("total", 0),
                "decisions": summary.get("decisions") or {},
                "item_statuses": summary.get("statuses") or {},
            }
        )
    return {"jobs": out}


def list_duplicate_holds_admin(*, limit: int = 40) -> dict[str, Any]:
    session = db.get_session()
    try:
        from database import FileUpload

        rows = (
            session.query(FileUpload)
            .filter_by(ingest_state="duplicate_hold")
            .order_by(FileUpload.uploaded_at.desc())
            .limit(limit)
            .all()
        )
        items = []
        for u in rows:
            items.append(
                {
                    "id": u.id,
                    "file_name": u.file_name,
                    "channel_id": u.channel_id,
                    "content_lane": u.content_lane,
                    "duplicate_of_upload_id": u.duplicate_of_upload_id,
                    "uploaded_at": u.uploaded_at.isoformat() if u.uploaded_at else None,
                }
            )
        return {"items": items, "total": len(items)}
    finally:
        session.close()
