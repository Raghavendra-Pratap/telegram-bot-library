"""Admin tracking list (TV, multipart, TMDB collections) for the portal."""
from __future__ import annotations

import os
import time

from database import Database
from tmdb_helper import tmdb_helper
from tracking_stats import (
    build_indexed_episode_stats,
    collection_tracking_counts,
    enrich_tracking_entry,
    filter_tracking_completion,
    sort_tracking_entries,
)

db = Database()

_RAW_CACHE: dict[str, tuple[list[dict], float]] = {}
_RAW_CACHE_TTL = 120.0
_EMPTY_STATS = build_indexed_episode_stats([])


def _tracking_tmdb_fetch_cap() -> int:
    try:
        return max(0, int(os.getenv("TRACKING_TMDB_FETCH_MAX", "100")))
    except ValueError:
        return 100


def _ensure_tv_totals(entries: list[dict], *, max_fetch: int | None = None) -> None:
    tv_entries = [
        e
        for e in entries
        if e.get("kind") == "tv" and e.get("tmdb_episodes") is None and e.get("tmdb_id")
    ]
    if not tv_entries or not tmdb_helper.enabled:
        return
    cap = max_fetch if max_fetch is not None else len(tv_entries)
    for i, entry in enumerate(tv_entries[:cap]):
        if i:
            time.sleep(0.12)
        tr = tmdb_helper.fetch_tv_tracking(int(entry["tmdb_id"]))
        if tr:
            entry["tmdb_episodes"] = tr.get("number_of_episodes")


def _collect_raw_entries(filter_kind: str, *, fetch_tmdb: bool) -> list[dict]:
    kind = (filter_kind or "all").lower()
    cache_key = f"{kind}:{'tmdb' if fetch_tmdb else 'db'}"
    now = time.time()
    cached = _RAW_CACHE.get(cache_key)
    if cached and now - cached[1] < _RAW_CACHE_TTL:
        return [dict(e) for e in cached[0]]

    entries: list[dict] = []
    indexed_movie_ids = db.get_indexed_movie_tmdb_ids()
    seen_collections: set[int] = set()
    load_collections = fetch_tmdb and kind in ("all", "franchise")

    if kind in ("all", "tv"):
        tv_rows = db.get_tracking_tv_shows(limit=1000)
        ct_ids = [int(r["content_title_id"]) for r in tv_rows]
        batch_stats = db.batch_indexed_episode_stats(ct_ids)
        for row in tv_rows:
            ct_id = int(row["content_title_id"])
            stats = batch_stats.get(ct_id, _EMPTY_STATS)
            by_season = stats.get("by_season") or {}
            entries.append(
                {
                    "kind": "tv",
                    "title": row["title"],
                    "content_title_id": ct_id,
                    "tmdb_id": row.get("tmdb_id"),
                    "release_year": row.get("release_year"),
                    "indexed_episodes": stats["indexed_episodes"],
                    "indexed_seasons": stats["indexed_seasons"],
                    "file_count": stats.get("file_count", 0),
                    "tmdb_episodes": None,
                    "seasons_indexed": [
                        {"season": int(sn), "episodes": len(eps)}
                        for sn, eps in sorted(by_season.items(), key=lambda x: x[0])
                    ],
                }
            )

    if kind in ("all", "franchise"):
        for row in db.get_tracking_multipart_movies(limit=1000):
            total = row.get("total_parts") or len(row["indexed_parts"])
            entries.append(
                {
                    "kind": "multipart",
                    "title": row["title"],
                    "content_title_id": row["content_title_id"],
                    "release_year": row.get("release_year"),
                    "indexed_parts": len(row["indexed_parts"]),
                    "total_parts": total,
                    "part_set": row["indexed_parts"],
                }
            )

        if load_collections and tmdb_helper.enabled:
            for movie in db.get_movie_rows_for_tracking():
                if movie.get("franchise_sequence"):
                    continue
                coll = tmdb_helper.fetch_collection_for_movie(movie["tmdb_id"])
                if not coll:
                    continue
                cid = coll["collection_id"]
                if cid in seen_collections:
                    continue
                ccounts = collection_tracking_counts(
                    coll["parts"], indexed_movie_ids
                )
                if not ccounts["indexed_released"] and not ccounts["released_count"]:
                    continue
                seen_collections.add(cid)
                newest_year = 0
                for p in ccounts.get("released") or []:
                    py = p.get("year")
                    if py is not None:
                        try:
                            newest_year = max(newest_year, int(py))
                        except (TypeError, ValueError):
                            pass
                entries.append(
                    {
                        "kind": "collection",
                        "title": coll["name"],
                        "collection_id": cid,
                        "release_year": newest_year or None,
                        "indexed_parts": ccounts["indexed_released"],
                        "total_parts": ccounts["released_count"],
                        "upcoming_count": ccounts["upcoming_count"],
                        "parts": coll["parts"],
                    }
                )

    _RAW_CACHE[cache_key] = (entries, now)
    return [dict(e) for e in entries]


def list_tracking_entries(
    filter_kind: str = "all",
    *,
    completion: str = "all",
    page: int = 1,
    page_size: int = 12,
    fetch_tmdb: bool = False,
    fetch_page_tmdb: bool = False,
) -> tuple[list[dict], int, int]:
    """
    Paginated tracking list. TMDB episode totals are fetched only for the
    current page (fast), except when filtering to *complete* — then we need
    totals for TV rows before filtering (capped by TRACKING_TMDB_FETCH_MAX).
    """
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 48))
    completion = (completion or "all").lower()

    raw = _collect_raw_entries(filter_kind, fetch_tmdb=fetch_tmdb)
    entries = [dict(e) for e in raw]

    # Do not bulk-fetch TMDB for "incomplete" — that blocked the UI for minutes.
    if fetch_page_tmdb and completion == "complete":
        tv_only = [e for e in entries if e.get("kind") == "tv"]
        _ensure_tv_totals(tv_only, max_fetch=_tracking_tmdb_fetch_cap())

    enriched = [enrich_tracking_entry(e) for e in entries]
    filtered = filter_tracking_completion(enriched, completion)
    sorted_all = sort_tracking_entries(filtered)
    total = len(sorted_all)
    pages = max(1, (total + page_size - 1) // page_size) if total else 1
    offset = (page - 1) * page_size
    page_items = [dict(e) for e in sorted_all[offset : offset + page_size]]

    if fetch_page_tmdb:
        tv_page = [
            e
            for e in page_items
            if e.get("kind") == "tv" and e.get("tmdb_episodes") is None and e.get("tmdb_id")
        ]
        if tv_page:
            _ensure_tv_totals(tv_page)
        page_items = [enrich_tracking_entry(e) for e in page_items]

    return page_items, total, pages


def count_tracking_entries() -> int:
    return db.count_tracking_tv_shows() + db.count_tracking_multipart_movies()
