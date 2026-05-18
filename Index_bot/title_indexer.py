"""
Resolve parsed filenames + TMDB into content_title rows and per-file episode fields.
"""
from __future__ import annotations

import logging
from typing import Any

from series_grouping import show_group_key
from tmdb_helper import split_title_year, titles_match

logger = logging.getLogger(__name__)


def build_pick_metadata(file_name: str, *, parser, tmdb_helper, db) -> dict[str, Any]:
    """
    Fast metadata for pending TMDB picker (parse + search only, no DB upsert / details).
    """
    parsed = parser.parse_name(file_name)
    media_type = parsed.get("media_type") or "movie"
    if media_type == "tv":
        search_name = parsed.get("show_name") or parsed.get("name")
    else:
        search_name = parsed.get("name")

    meta: dict[str, Any] = {
        "parsed": parsed,
        "media_type": media_type,
        "search_name": search_name,
        "local_name": search_name,
        "show_group_key": show_group_key(parsed, file_name),
        "suggestions": [],
    }
    if search_name and tmdb_helper.enabled:
        tmdb_helper._last_api_error = None
        meta["suggestions"] = gather_tmdb_suggestions(meta, tmdb_helper=tmdb_helper, db=db)
        meta["tmdb_unreachable"] = bool(tmdb_helper._last_api_error) and not meta["suggestions"]
    else:
        meta["tmdb_unreachable"] = False
    return meta


def gather_tmdb_suggestions(meta: dict, *, tmdb_helper, db) -> list[dict]:
    """Load TMDB suggestions for pick UI (fresh search + DB fallback)."""
    suggestions = list(meta.get("suggestions") or [])
    search_name = meta.get("search_name") or meta.get("local_name")
    media_type = meta.get("media_type") or "movie"
    if suggestions or not search_name or not tmdb_helper.enabled:
        return suggestions

    parsed = meta.get("parsed") or {}
    year = parsed.get("year")
    try:
        year_int = int(year) if year else None
    except (TypeError, ValueError):
        year_int = None

    clean_search, embedded_year = split_title_year(search_name or "")
    if embedded_year is not None and year_int is None:
        year_int = embedded_year
    search_name = clean_search or search_name

    if media_type == "tv":
        suggestions = tmdb_helper.search_suggestions_multi(
            search_name, media_type="tv", year=year_int, limit=6
        )
    else:
        suggestions = tmdb_helper.search_suggestions_multi(
            search_name, media_type="movie", year=year_int, limit=6
        )

    match_key = meta.get("show_group_key")
    if match_key:
        hint = db.get_title_hint(match_key)
        if hint and hint.tmdb_id:
            hint_row = {
                "tmdb_id": hint.tmdb_id,
                "title": hint.tmdb_title or search_name,
                "media_type": hint.media_type or media_type,
                "year": None,
                "from_hint": True,
            }
            if not any(
                s.get("tmdb_id") == hint.tmdb_id and s.get("media_type") == hint_row["media_type"]
                for s in suggestions
            ):
                suggestions.insert(0, hint_row)

    if not suggestions:
        existing = db.get_movie_series(search_name)
        if existing and existing.tmdb_id:
            suggestions = [
                {
                    "tmdb_id": existing.tmdb_id,
                    "title": existing.tmdb_title or existing.name,
                    "media_type": existing.media_type or media_type,
                    "year": str(existing.release_year) if existing.release_year else None,
                }
            ]
    return suggestions


def episode_display_name(
    show_title: str,
    season: int | None,
    episode: int | None,
    episode_title: str | None = None,
) -> str:
    if show_title and season is not None and episode is not None:
        base = f"{show_title} · S{int(season):02d}E{int(episode):02d}"
        if episode_title:
            return f"{base} — {episode_title}"
        return base
    return show_title or ""


def build_index_metadata(
    file_name: str,
    *,
    parser,
    tmdb_helper,
    db,
) -> dict[str, Any]:
    """
    Produce fields for FileUpload + MovieSeries from a Telegram file name.

    Returns dict with keys for add_file_upload and content title linkage.
    """
    parsed = parser.parse_name(file_name)
    media_type = parsed.get("media_type") or "movie"
    year = parsed.get("year")
    franchise_sequence = parsed.get("franchise_sequence")
    season = parsed.get("season")
    episode = parsed.get("episode")
    episode_title = parsed.get("episode_title")

    if media_type == "tv":
        search_name = parsed.get("show_name") or parsed.get("name")
    else:
        search_name = parsed.get("name")

    suggestions: list[dict] = []
    tmdb_result = None

    if tmdb_helper.enabled and search_name:
        try:
            year_int = int(year) if year else None
        except (TypeError, ValueError):
            year_int = None

        clean_search, embedded_year = split_title_year(search_name or "")
        if embedded_year is not None and year_int is None:
            year_int = embedded_year
        search_name = clean_search or search_name

        if media_type == "tv":
            suggestions = tmdb_helper.search_tv_suggestions(search_name, year_int, limit=6)
            match = tmdb_helper.pick_best_match(suggestions, search_name, media_type="tv")
        else:
            suggestions = tmdb_helper.search_movie_suggestions(search_name, year_int, limit=6)
            match = tmdb_helper.pick_best_match(suggestions, search_name, media_type="movie")

        if match and titles_match(search_name, match.get("title", "")):
            tmdb_result = {
                "correct_name": match["title"],
                "tmdb_id": match["tmdb_id"],
                "media_type": match["media_type"],
                "year": match.get("year"),
            }

        # Reuse TMDB link from another file of the same show when search failed transiently
        if not tmdb_result and search_name:
            existing = db.get_movie_series(search_name)
            if existing and existing.tmdb_id:
                tmdb_result = {
                    "correct_name": existing.tmdb_title or existing.name,
                    "tmdb_id": existing.tmdb_id,
                    "media_type": existing.media_type or media_type,
                    "year": existing.release_year,
                }
                if not suggestions:
                    suggestions = [
                        {
                            "tmdb_id": existing.tmdb_id,
                            "title": existing.tmdb_title or existing.name,
                            "media_type": existing.media_type or "tv",
                            "year": str(existing.release_year) if existing.release_year else None,
                        }
                    ]

    tmdb_id = tmdb_result.get("tmdb_id") if tmdb_result else None
    tmdb_title = tmdb_result.get("correct_name") if tmdb_result else None
    if tmdb_result and tmdb_result.get("media_type"):
        media_type = "tv" if tmdb_result["media_type"] in ("tv", "series") else "movie"
    if tmdb_result and tmdb_result.get("year"):
        try:
            year = int(tmdb_result["year"])
        except (TypeError, ValueError):
            pass

    metadata: dict[str, Any] = {}
    if tmdb_id and tmdb_helper.enabled:
        if media_type == "tv":
            metadata = tmdb_helper.fetch_tv_details(tmdb_id) or {}
        else:
            metadata = tmdb_helper.fetch_movie_details(tmdb_id) or {}

    local_name = search_name or parsed.get("name")
    show_label = tmdb_title or metadata.get("tmdb_title") or local_name

    if media_type == "tv":
        parsed_name = episode_display_name(show_label, season, episode, episode_title)
        if not parsed_name:
            parsed_name = parsed.get("name") or file_name
    elif media_type == "movie" and tmdb_title:
        parsed_name = tmdb_title
        if franchise_sequence:
            parsed_name = f"{tmdb_title} ({franchise_sequence})"
    else:
        parsed_name = parsed.get("name") or local_name

    content_title = db.upsert_content_title(
        local_name=local_name,
        media_type=media_type,
        tmdb_id=tmdb_id,
        tmdb_title=tmdb_title or metadata.get("tmdb_title"),
        release_year=year or metadata.get("release_year"),
        franchise_sequence=franchise_sequence,
        poster_path=metadata.get("poster_path"),
        overview=metadata.get("overview"),
        vote_average=metadata.get("vote_average"),
        genres=metadata.get("genres"),
    )

    needs_tmdb_pick = bool(tmdb_helper.enabled and search_name and not tmdb_id)
    auto_confirm = bool(tmdb_result) or (
        not tmdb_helper.enabled
        and parsed.get("confidence") == "high"
        and parsed_name
        and len(str(parsed_name)) > 3
    )

    return {
        "parsed_name": parsed_name,
        "auto_confirm": auto_confirm,
        "library_visible": bool(tmdb_result),
        "needs_tmdb_pick": needs_tmdb_pick,
        "suggestions": suggestions,
        "content_title_id": content_title.id if content_title else None,
        "season_number": season,
        "episode_number": episode,
        "episode_title": episode_title,
        "media_type": media_type,
        "tmdb_result": tmdb_result,
        "parsed": parsed,
        "search_name": search_name,
        "local_name": local_name,
    }


def apply_index_metadata_to_upload(upload, meta: dict) -> str:
    """
    Apply build_index_metadata() to an existing FileUpload row (caller holds session).

    Returns ``matched`` when TMDB auto-confirmed, else ``still_pending``.
    """
    upload.parsed_name = meta["parsed_name"]
    upload.content_title_id = meta.get("content_title_id")
    upload.season_number = meta.get("season_number")
    upload.episode_number = meta.get("episode_number")
    upload.episode_title = meta.get("episode_title")
    upload.library_visible = bool(meta.get("library_visible"))
    if meta["auto_confirm"]:
        upload.is_confirmed = True
        upload.needs_confirmation = False
        upload.confirmed_name = meta["parsed_name"]
        upload.pending_deferred_at = None
        return "matched"
    if meta.get("needs_tmdb_pick"):
        upload.is_confirmed = False
        upload.needs_confirmation = True
        upload.confirmed_name = None
        upload.library_visible = False
    return "still_pending"
