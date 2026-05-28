"""Watch portal business logic (shared DB + TMDB + Telegram delivery)."""
from __future__ import annotations

import logging
import re
from typing import Any

from database import Database
from name_parser import NameParser
from file_variant import extract_quality_label, format_file_size
from tmdb_helper import best_poster_url, poster_image_url, tmdb_helper
from portal.streaming import can_play_in_browser, can_stream_in_browser
from watch_library import dedupe_upload_variants, filter_watchable_media_uploads

logger = logging.getLogger(__name__)
db = Database()
_name_parser = NameParser()

_JUNK_EPISODE_TITLE = re.compile(
    r"^(?:mkv|mp4|avi|mov|webm|m4v|ts|"
    r"webrip|web[- ]?dl|bluray|brrip|dvdrip|hdtv|remux|"
    r"standard|x264|x265|hevc|h\.?264|h\.?265|av1|"
    r"\d{3,4}p|2160p|4k|8k|uhd)$",
    re.I,
)


def _mt_norm(mt: str | None) -> str:
    m = (mt or "movie").lower()
    return "tv" if m in ("tv", "series") else m


def _title_display(ct, entry: dict | None = None) -> str:
    if entry and entry.get("title"):
        return str(entry["title"])
    if ct:
        return ct.tmdb_title or ct.name or "?"
    return "?"


def _parse_genres_json(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(g) for g in raw if g]
    try:
        import json

        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(g) for g in parsed if g]
    except Exception:
        pass
    return []


def tmdb_metadata_for_ct(ct, media_type: str | None = None) -> dict[str, Any]:
    """Merge DB + TMDB details for posters, genres, cast, overview."""
    if not ct:
        return {}
    mt = _mt_norm(media_type or ct.media_type)
    enrich: dict[str, Any] = {}
    if ct.tmdb_id and tmdb_helper.enabled and mt != "course":
        try:
            enrich = (
                tmdb_helper.build_catalog_enrichment(
                    tmdb_id=int(ct.tmdb_id),
                    media_type=mt,
                )
                or {}
            )
        except Exception as e:
            logger.debug("tmdb enrich ct=%s: %s", ct.id, e)

    genres = enrich.get("genres") or _parse_genres_json(ct.genres)
    overview = (enrich.get("overview") or ct.overview or "").strip()
    poster = best_poster_url(enrich) or best_poster_url({"poster_path": ct.poster_path})
    vote = ct.vote_average or enrich.get("vote_average")
    if enrich and not (ct.poster_path or "").strip():
        path_to_cache = enrich.get("poster_path") or enrich.get("backdrop_path")
        if path_to_cache:
            try:
                db.cache_content_poster_path(int(ct.id), str(path_to_cache))
            except Exception as e:
                logger.debug("cache poster ct=%s: %s", ct.id, e)
    return {
        "overview": overview,
        "genres": genres,
        "poster_url": poster,
        "vote_average": vote,
        "cast": enrich.get("cast") or [],
        "directors": enrich.get("directors") or [],
        "writers": enrich.get("writers") or [],
    }


def _card_from_ct(ct, entry: dict | None = None, *, user_id: int | None = None) -> dict:
    e = entry or {}
    mt = _mt_norm(e.get("media_type") or (ct.media_type if ct else None))
    meta = tmdb_metadata_for_ct(ct, mt) if ct else {}
    poster = meta.get("poster_url")
    ct_id = ct.id if ct else e.get("content_title_id")
    in_lib = False
    if ct_id:
        in_lib = db.count_library_uploads_for_content(int(ct_id)) > 0
    fav = False
    on_watchlist = False
    if user_id and ct_id:
        fav = db.is_favorite(user_id, int(ct_id))
        on_watchlist = db.is_on_watchlist(user_id, int(ct_id))
    return {
        "content_title_id": ct_id,
        "title": _title_display(ct, e),
        "media_type": mt,
        "release_year": e.get("release_year") or (ct.release_year if ct else None),
        "vote_average": e.get("vote_average") or meta.get("vote_average") or (ct.vote_average if ct else None),
        "poster_url": poster,
        "genres": meta.get("genres") or [],
        "in_library": in_lib,
        "is_favorite": fav,
        "on_watchlist": on_watchlist,
    }


def _normalize_browse_scope(browse_scope: str | None, *, user_id: int | None) -> str:
    from config import Config

    scope = (browse_scope or "media").lower()
    if scope == "adult":
        if user_id and Config.is_admin(user_id):
            return "adult"
        return "public"
    if scope in ("non_catalog", "non-catalog", "noncatalog"):
        if user_id and Config.is_admin(user_id):
            return "non_catalog"
        return "public"
    if scope in ("archive", "shortform"):
        if user_id and Config.is_admin(user_id):
            return scope
        return "public"
    if scope in ("media", "course", "public"):
        return scope
    return "media"


def browse_titles(
    *,
    limit: int = 28,
    offset: int = 0,
    media_type: str | None = None,
    browse_scope: str = "media",
    user_id: int | None = None,
    min_year: int | None = None,
    max_year: int | None = None,
    min_rating: float | None = None,
    sort: str = "recent",
    sort_desc: bool = True,
    search: str | None = None,
) -> tuple[list[dict], int]:
    """Return (page of cards, total matching titles)."""
    scope = _normalize_browse_scope(browse_scope, user_id=user_id)
    mt = None if not media_type or media_type == "all" else _mt_norm(media_type)
    if scope == "course":
        mt = "course"
    entries, total = db.list_library_browse(
        limit=limit,
        offset=offset,
        library_only=True,
        browse_scope=scope,
        media_type=mt,
        min_year=min_year,
        max_year=max_year,
        min_rating=min_rating,
        sort=sort or "recent",
        desc=sort_desc,
        search=search,
    )
    out = []
    for e in entries:
        ct_id = e.get("content_title_id")
        ct = db.get_content_title(ct_id) if ct_id else None
        out.append(_card_from_ct(ct, e, user_id=user_id))
    return out, total


def get_title_detail(
    content_title_id: int,
    *,
    user_id: int | None = None,
    browse_scope: str | None = None,
) -> dict | None:
    ct = db.get_content_title(content_title_id)
    if not ct:
        return None
    scope = _normalize_browse_scope(browse_scope, user_id=user_id)
    uploads = filter_watchable_media_uploads(
        db.get_library_uploads_for_content(
            content_title_id, library_only=True, browse_scope=scope
        )
    )
    mt = _mt_norm(ct.media_type)
    meta = tmdb_metadata_for_ct(ct, mt)
    card = _card_from_ct(ct, user_id=user_id)
    card.update(
        {
            "overview": meta.get("overview") or "",
            "genres": meta.get("genres") or [],
            "cast": meta.get("cast") or [],
            "directors": meta.get("directors") or [],
            "writers": meta.get("writers") or [],
            "tmdb_id": ct.tmdb_id,
            "upload_count": len(uploads),
            "available": len(uploads) > 0,
        }
    )
    return card


def _clean_episode_title(title: str | None) -> str | None:
    if not title:
        return None
    t = str(title).strip()
    t = re.sub(
        r"\s+(?:\d{3,4}p|4k|2160p|webrip|web[- ]?dl|bluray|hdtv|x26[45]|hevc)\s*$",
        "",
        t,
        flags=re.I,
    ).strip()
    if not t or _JUNK_EPISODE_TITLE.match(t):
        return None
    return t


def _infer_episode_key(upload) -> tuple[int | None, int | None]:
    sn, ep = upload.season_number, upload.episode_number
    if sn is not None or ep is not None:
        return sn, ep
    parsed = _name_parser.parse_name(upload.file_name or "")
    if parsed.get("media_type") == "tv":
        return parsed.get("season"), parsed.get("episode")
    return None, None


def _group_tv_uploads(uploads: list) -> list[tuple[tuple[int | None, int | None], list]]:
    buckets: dict[tuple[int | None, int | None], list] = {}
    for u in uploads:
        key = _infer_episode_key(u)
        buckets.setdefault(key, []).append(u)
    items = list(buckets.items())
    items.sort(
        key=lambda kv: (
            kv[0][0] if kv[0][0] is not None else 9999,
            kv[0][1] if kv[0][1] is not None else 9999,
        )
    )
    return items


def _episode_code(sn: int | None, ep: int | None) -> str | None:
    if sn is not None and ep is not None:
        return f"S{int(sn):02d}E{int(ep):02d}"
    if ep is not None:
        return f"E{int(ep):02d}"
    if sn is not None:
        return f"Season {int(sn)}"
    return None


def _episode_name(ct, sn: int | None, ep: int | None, sample) -> str | None:
    if sample:
        title = _clean_episode_title(getattr(sample, "episode_title", None))
        if title:
            return title
        if sample.file_name:
            parsed = _name_parser.parse_name(sample.file_name)
            title = _clean_episode_title(parsed.get("episode_title"))
            if title:
                return title
    if ct and ct.tmdb_id and sn is not None and ep is not None and tmdb_helper.enabled:
        try:
            return tmdb_helper.get_tv_episode_name(int(ct.tmdb_id), int(sn), int(ep))
        except Exception as e:
            logger.debug("TMDB episode name %s S%sE%s: %s", ct.tmdb_id, sn, ep, e)
    return None


def _episode_row(ct, sn: int | None, ep: int | None, items: list) -> dict:
    sample = items[0] if items else None
    code = _episode_code(sn, ep)
    name = _episode_name(ct, sn, ep, sample)
    if code and name:
        label = f"{code} — {name}"
    elif code:
        label = code
    elif name:
        label = name
    else:
        label = sample.file_name if sample else "Episode"
    n = len(items)
    return {
        "season": sn,
        "episode": ep,
        "label": label,
        "episode_code": code,
        "episode_name": name,
        "upload_count": n,
        "versions_label": f"{n} version{'s' if n != 1 else ''}",
    }


def list_episodes(
    content_title_id: int,
    *,
    user_id: int | None = None,
    browse_scope: str | None = None,
) -> list[dict]:
    ct = db.get_content_title(content_title_id)
    if not ct:
        return []
    scope = _normalize_browse_scope(browse_scope, user_id=user_id)
    uploads = filter_watchable_media_uploads(
        db.get_library_uploads_for_content(
            content_title_id, library_only=True, browse_scope=scope
        )
    )
    mt = _mt_norm(ct.media_type)
    if mt == "course":
        rows = sorted(
            uploads,
            key=lambda u: (u.lesson_sequence or u.episode_number or 0, u.id),
        )
        return [
            {
                "season": None,
                "episode": u.lesson_sequence or u.episode_number,
                "label": u.episode_title or u.file_name,
                "episode_code": None,
                "episode_name": u.episode_title,
                "upload_count": 1,
                "versions_label": "1 version",
            }
            for u in rows
        ]
    if mt in ("tv", "series"):
        return [
            _episode_row(ct, sn, ep, items)
            for (sn, ep), items in _group_tv_uploads(uploads)
        ]
    n = len(uploads)
    return [
        {
            "season": None,
            "episode": None,
            "label": "Movie",
            "episode_code": None,
            "episode_name": None,
            "upload_count": n,
            "versions_label": f"{n} version{'s' if n != 1 else ''}",
        }
    ]


def watchlist_titles(*, user_id: int, limit: int = 60) -> list[dict]:
    rows = db.get_user_watchlist_titles(user_id, limit=limit)
    out = []
    for r in rows:
        ct = db.get_content_title(r["content_title_id"])
        if ct:
            out.append(_card_from_ct(ct, r, user_id=user_id))
    return out


def _episode_key_matches(
    upload, season: int | None, episode: int | None
) -> bool:
    sn, ep = _infer_episode_key(upload)
    if season is not None and sn != season:
        return False
    if episode is not None and ep != episode:
        return False
    return True


def list_qualities(
    content_title_id: int,
    *,
    season: int | None = None,
    episode: int | None = None,
    user_id: int | None = None,
    browse_scope: str | None = None,
) -> list[dict]:
    scope = _normalize_browse_scope(browse_scope, user_id=user_id)
    uploads = filter_watchable_media_uploads(
        db.get_library_uploads_for_content(
            content_title_id, library_only=True, browse_scope=scope
        )
    )
    ct = db.get_content_title(content_title_id)
    if season is not None or episode is not None:
        uploads = [
            u
            for u in uploads
            if _episode_key_matches(u, season, episode)
        ]
    elif ct and _mt_norm(ct.media_type) in ("tv", "series"):
        uploads = []
    variants = dedupe_upload_variants(uploads)
    return [
        {
            "upload_id": u.id,
            "quality": extract_quality_label(u.file_name),
            "size": format_file_size(u.file_size),
            "file_name": u.file_name,
            "can_stream": can_play_in_browser(u),
        }
        for u in variants
    ]


def search_catalog(query: str, *, user_id: int | None = None, limit: int = 12) -> dict:
    q = (query or "").strip()
    if len(q) < 2:
        return {"library": [], "tmdb": []}
    lib = []
    seen_ct: set[int] = set()
    from content_lanes import LANE_COURSE

    for row in db.search_files(q, library_only=True)[: limit * 3]:
        ct_id = row.content_title_id
        if not ct_id or ct_id in seen_ct:
            continue
        if (row.content_lane or "").lower() == LANE_COURSE:
            continue
        seen_ct.add(int(ct_id))
        ct = db.get_content_title(ct_id)
        if ct and _mt_norm(ct.media_type) == "course":
            continue
        if ct:
            lib.append(_card_from_ct(ct, user_id=user_id))
        if len(lib) >= limit:
            break
    seen = {c.get("content_title_id") for c in lib}
    tmdb_rows = []
    if tmdb_helper.enabled:
        for s in tmdb_helper.search_suggestions_multi(q, limit=8):
            tid = s.get("tmdb_id")
            mt = _mt_norm(s.get("media_type"))
            existing = db.find_content_title_by_tmdb(tid, mt) if tid else None
            in_lib = existing and db.count_library_uploads_for_content(existing.id) > 0
            pending = False
            if user_id and tid and not in_lib:
                pending = db.has_pending_upload_request(user_id, tid, mt)
            tmdb_rows.append(
                {
                    "tmdb_id": tid,
                    "title": s.get("title"),
                    "media_type": mt,
                    "release_year": s.get("year"),
                    "vote_average": s.get("vote_average"),
                    "overview": (s.get("overview") or "")[:300],
                    "poster_url": poster_image_url(s),
                    "in_library": bool(in_lib),
                    "content_title_id": existing.id if existing else None,
                    "request_pending": pending,
                }
            )
    return {"library": lib, "tmdb": tmdb_rows}


async def play_upload(user_id: int, upload_id: int, *, bot) -> dict[str, Any]:
    from watch_library import deliver_upload_to_chat

    upload = db.get_file_upload(upload_id)
    if not upload:
        return {"ok": False, "error": "File not found"}
    if not db.is_upload_accessible_for_user(upload, user_id):
        return {"ok": False, "error": "Not available in library"}
    ct = db.get_content_title(upload.content_title_id) if upload.content_title_id else None
    quality = extract_quality_label(upload.file_name)
    try:
        await deliver_upload_to_chat(bot, user_id, upload, ct, quality=quality)
        return {"ok": True, "mode": "telegram_dm", "message": "Sent to your Telegram chat"}
    except Exception as e:
        logger.warning("portal play_upload %s: %s", upload_id, e)
        return {"ok": False, "error": str(e)[:200]}
