"""
Admin tracking: indexed vs TMDB totals for TV seasons/episodes and movie franchises.
"""
from __future__ import annotations

from collections import defaultdict
from html import escape
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def normalize_episode_key(
    season: int | None, episode: int | None
) -> tuple[int, int] | None:
    if episode is None:
        return None
    s = int(season) if season is not None else 1
    return (s, int(episode))


def build_indexed_episode_stats(upload_rows: list) -> dict[str, Any]:
    """
    From rows with season_number, episode_number (and optional file count).
    upload_rows: list of (season, episode) or FileUpload-like objects.
    """
    pairs: set[tuple[int, int]] = set()
    by_season: dict[int, set[int]] = defaultdict(set)
    file_count = 0
    for row in upload_rows:
        if hasattr(row, "season_number"):
            s, e = row.season_number, row.episode_number
        else:
            s, e = row[0], row[1]
        key = normalize_episode_key(s, e)
        if not key:
            continue
        file_count += 1
        pairs.add(key)
        by_season[key[0]].add(key[1])
    return {
        "episode_pairs": pairs,
        "by_season": dict(by_season),
        "indexed_episodes": len(pairs),
        "indexed_seasons": len(by_season),
        "file_count": file_count,
    }


def _progress_bar(ratio: float, width: int = 8) -> str:
    ratio = max(0.0, min(1.0, ratio))
    filled = int(round(ratio * width))
    return "█" * filled + "░" * (width - filled)


def format_tv_tracking_detail(
    title: str,
    indexed: dict[str, Any],
    tmdb: dict[str, Any] | None,
) -> str:
    lines = [f"<b>📺 {escape(title)}</b>", ""]
    ie = indexed["indexed_episodes"]
    is_ = indexed["indexed_seasons"]
    fc = indexed["file_count"]

    if tmdb:
        ts = tmdb.get("number_of_seasons") or len(tmdb.get("seasons") or [])
        te = tmdb.get("number_of_episodes") or 0
        lines.append(f"<b>TMDB</b> · {ts} season(s) · {te} episode(s)")
        lines.append(f"<b>Indexed</b> · {is_} season(s) · {ie} episode(s) · {fc} file(s)")
        if te:
            left = max(0, te - ie)
            pct = int(100 * ie / te) if te else 0
            lines.append(f"<b>Progress</b> · {pct}% · <b>{left}</b> episode(s) left")
        lines.append("")
        by_season = indexed.get("by_season") or {}
        for season_info in sorted(tmdb.get("seasons") or [], key=lambda x: x["season_number"]):
            sn = season_info["season_number"]
            expected = season_info.get("episode_count") or 0
            have = by_season.get(sn, set())
            got = len(have)
            bar = _progress_bar(got / expected if expected else 0)
            lines.append(f"<b>S{sn:02d}</b> {got}/{expected} {bar}")
            if expected and got <= 20:
                missing = [e for e in range(1, expected + 1) if e not in have]
                have_list = ", ".join(f"E{e:02d}" for e in sorted(have)[:24])
                if have_list:
                    lines.append(f"  ✅ {have_list}")
                if missing and len(missing) <= 16:
                    miss = ", ".join(f"E{e:02d}" for e in missing[:16])
                    lines.append(f"  ❌ {miss}")
                elif missing:
                    lines.append(f"  ❌ {len(missing)} missing")
            elif have:
                lines.append(f"  ✅ {got} episode(s) indexed")
            lines.append("")
        indexed_seasons_not_in_tmdb = set(by_season) - {
            s["season_number"] for s in (tmdb.get("seasons") or [])
        }
        if indexed_seasons_not_in_tmdb:
            lines.append("<i>Extra indexed seasons (not on TMDB list):</i>")
            for sn in sorted(indexed_seasons_not_in_tmdb):
                eps = sorted(by_season[sn])
                lines.append(f"  S{sn:02d}: {len(eps)} ep — {', '.join(f'E{e:02d}' for e in eps[:12])}")
    else:
        lines.append("<b>Indexed</b> (TMDB not configured — no episode totals)")
        lines.append(f"{is_} season(s) · {ie} episode(s) · {fc} file(s)")
        lines.append("")
        for sn in sorted(indexed.get("by_season") or {}):
            eps = sorted(indexed["by_season"][sn])
            lines.append(
                f"<b>S{sn:02d}</b> · {len(eps)} ep — "
                f"{', '.join(f'E{e:02d}' for e in eps[:20])}"
            )
            if len(eps) > 20:
                lines.append(f"  <i>…+{len(eps) - 20} more</i>")
    return "\n".join(lines).strip()


def _collection_parts_by_release(parts: list[dict]) -> tuple[list, list, list]:
    released: list[dict] = []
    upcoming: list[dict] = []
    announced: list[dict] = []
    for p in parts:
        st = p.get("release_status") or "released"
        if st == "released":
            released.append(p)
        elif st == "upcoming":
            upcoming.append(p)
        else:
            announced.append(p)
    return released, upcoming, announced


def collection_tracking_counts(
    parts: list[dict], indexed_tmdb_ids: set[int]
) -> dict:
    """Progress counts only against released films (not announced/upcoming)."""
    released, upcoming, announced = _collection_parts_by_release(parts)
    rel_ids = {p["tmdb_id"] for p in released}
    indexed_released = len(rel_ids & indexed_tmdb_ids)
    missing_released = len(rel_ids - indexed_tmdb_ids)
    return {
        "released": released,
        "upcoming": upcoming,
        "announced": announced,
        "released_count": len(released),
        "indexed_released": indexed_released,
        "missing_released": missing_released,
        "upcoming_count": len(upcoming) + len(announced),
    }


def format_collection_tracking_detail(
    collection_name: str,
    parts: list[dict],
    indexed_tmdb_ids: set[int],
) -> str:
    counts = collection_tracking_counts(parts, indexed_tmdb_ids)
    released = counts["released"]
    upcoming = counts["upcoming"]
    announced = counts["announced"]
    indexed_rel = counts["indexed_released"]
    rel_n = counts["released_count"]

    lines = [
        f"<b>🎬 {escape(collection_name)}</b>",
        "",
        f"<b>Released on TMDB</b> · {rel_n} film(s)",
    ]
    if counts["upcoming_count"]:
        bits = []
        if upcoming:
            bits.append(f"{len(upcoming)} upcoming")
        if announced:
            bits.append(f"{len(announced)} announced")
        lines.append(f"<b>Not out yet</b> · {' · '.join(bits)} (not counted in progress)")
    lines.append(f"<b>Indexed</b> · {indexed_rel}/{rel_n} released")
    if rel_n:
        left = counts["missing_released"]
        pct = int(100 * indexed_rel / rel_n)
        lines.append(f"<b>Progress</b> · {pct}% · <b>{left}</b> to upload")
    lines.append("")
    if released:
        lines.append("<b>Released</b>")
        for p in released:
            tid = p.get("tmdb_id")
            name = escape((p.get("title") or "?").strip())
            yr = p.get("year") or ""
            mark = "✅" if tid in indexed_tmdb_ids else "❌"
            lines.append(f"{mark} {name}" + (f" ({yr})" if yr else ""))
        lines.append("")
    not_out = upcoming + announced
    if not_out:
        lines.append("<b>Not released yet</b>")
        for p in upcoming:
            tid = p.get("tmdb_id")
            name = escape((p.get("title") or "?").strip())
            rd = p.get("release_date") or ""
            if tid in indexed_tmdb_ids:
                mark = "✅"
                note = "indexed early"
            else:
                mark = "🕐"
                note = f"releases {rd}" if rd else "upcoming"
            lines.append(f"{mark} {name} — <i>{note}</i>")
        for p in announced:
            tid = p.get("tmdb_id")
            name = escape((p.get("title") or "?").strip())
            if tid in indexed_tmdb_ids:
                lines.append(f"✅ {name} — <i>indexed early</i>")
            else:
                lines.append(f"📋 {name} — <i>announced (no release date)</i>")
    return "\n".join(lines).strip()


def format_multipart_tracking_detail(
    title: str,
    indexed_parts: set[int],
    total_parts: int | None,
) -> str:
    lines = [
        f"<b>🎬 {escape(title)}</b>",
        "<i>Multi-part release (single title)</i>",
        "",
    ]
    got = len(indexed_parts)
    if total_parts and total_parts > 0:
        lines.append(f"<b>Parts</b> · {got}/{total_parts} indexed")
        lines.append(
            f"<b>Progress</b> · {int(100 * got / total_parts)}% · "
            f"<b>{max(0, total_parts - got)}</b> left"
        )
        missing = [p for p in range(1, total_parts + 1) if p not in indexed_parts]
    else:
        lines.append(f"<b>Parts indexed</b> · {got}")
        missing = []
    lines.append("")
    if indexed_parts:
        lines.append(
            "✅ "
            + ", ".join(f"Part {p}" for p in sorted(indexed_parts))
        )
    if missing:
        lines.append("❌ " + ", ".join(f"Part {p}" for p in missing))
    return "\n".join(lines)


def tracking_entry_is_complete(entry: dict) -> bool | None:
    """True if indexed counts meet TMDB totals; None when total is unknown."""
    kind = entry.get("kind")
    if kind == "tv":
        total = entry.get("tmdb_episodes")
        if total is None:
            return None
        try:
            total_n = int(total)
        except (TypeError, ValueError):
            return None
        if total_n <= 0:
            return None
        return int(entry.get("indexed_episodes") or 0) >= total_n
    if kind == "multipart":
        total = entry.get("total_parts")
        if not total:
            return None
        try:
            total_n = int(total)
        except (TypeError, ValueError):
            return None
        if total_n <= 0:
            return None
        return int(entry.get("indexed_parts") or 0) >= total_n
    if kind == "collection":
        total = entry.get("total_parts")
        if not total:
            return None
        try:
            total_n = int(total)
        except (TypeError, ValueError):
            return None
        if total_n <= 0:
            return None
        return int(entry.get("indexed_parts") or 0) >= total_n
    return None


def tracking_entry_sort_year(entry: dict) -> int:
    """Newest-first sort key from release year (or newest collection part)."""
    yr = entry.get("release_year")
    if yr is not None:
        try:
            return int(yr)
        except (TypeError, ValueError):
            pass
    best = 0
    for part in entry.get("parts") or []:
        py = part.get("year")
        if py is not None:
            try:
                best = max(best, int(py))
            except (TypeError, ValueError):
                continue
    return best


def enrich_tracking_entry(entry: dict) -> dict:
    out = dict(entry)
    complete = tracking_entry_is_complete(out)
    out["is_complete"] = complete
    if complete is True:
        out["completion_status"] = "complete"
    elif complete is False:
        out["completion_status"] = "incomplete"
    else:
        out["completion_status"] = "unknown"
    out["sort_year"] = tracking_entry_sort_year(out)
    return out


def filter_tracking_completion(
    entries: list[dict], completion: str = "all"
) -> list[dict]:
    key = (completion or "all").lower()
    if key == "complete":
        return [e for e in entries if e.get("is_complete") is True]
    if key == "incomplete":
        return [e for e in entries if e.get("is_complete") is not True]
    return entries


def sort_tracking_entries(entries: list[dict]) -> list[dict]:
    """Incomplete first, then complete; within each group newest release year first."""

    def sort_key(e: dict) -> tuple:
        complete = e.get("is_complete")
        # 0 = incomplete or unknown (first), 1 = complete (last)
        group = 1 if complete is True else 0
        year = -(e.get("sort_year") or 0)
        return (group, year, (e.get("title") or "").lower())

    return sorted(entries, key=sort_key)


def tracking_menu_button_label(entry: dict, *, max_len: int = 60) -> str:
    kind = entry.get("kind")
    title = (entry.get("title") or "?")[:22]
    if kind == "tv":
        ie = entry.get("indexed_episodes", 0)
        te = entry.get("tmdb_episodes")
        if te:
            return f"📺 {title} · {ie}/{te} ep"[:max_len]
        return f"📺 {title} · {ie} ep"[:max_len]
    if kind == "collection":
        ii = entry.get("indexed_parts", 0)
        tt = entry.get("total_parts", 0)
        up = entry.get("upcoming_count", 0)
        base = f"🎬 {title} · {ii}/{tt}"
        if up:
            base += f"+{up}⏳"
        return base[:max_len]
    if kind == "multipart":
        ii = entry.get("indexed_parts", 0)
        tt = entry.get("total_parts")
        if tt:
            return f"🎬 {title} · {ii}/{tt} pts"[:max_len]
        return f"🎬 {title} · {ii} pts"[:max_len]
    return title[:max_len]


def build_tracking_list_keyboard(
    entries: list[dict],
    *,
    page: int = 0,
    page_size: int = 12,
    filter_kind: str = "all",
    completion: str = "all",
) -> InlineKeyboardMarkup:
    start = page * page_size
    chunk = entries[start : start + page_size]
    rows = []
    for entry in chunk:
        cb = entry.get("callback")
        if cb:
            rows.append(
                [
                    InlineKeyboardButton(
                        tracking_menu_button_label(entry),
                        callback_data=cb,
                    )
                ]
            )
    nav = []
    comp = completion or "all"
    page_cb = f"{filter_kind}:{comp}"

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "« Prev", callback_data=f"tracking_page:{page - 1}:{page_cb}"
            )
        )
    if start + page_size < len(entries):
        nav.append(
            InlineKeyboardButton(
                "Next »", callback_data=f"tracking_page:{page + 1}:{page_cb}"
            )
        )
    if nav:
        rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(
                "All" if filter_kind != "all" else "• All",
                callback_data=f"tracking_filter:all:{comp}",
            ),
            InlineKeyboardButton(
                "TV" if filter_kind != "tv" else "• TV",
                callback_data=f"tracking_filter:tv:{comp}",
            ),
            InlineKeyboardButton(
                "Franchise" if filter_kind != "franchise" else "• Franchise",
                callback_data=f"tracking_filter:franchise:{comp}",
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                "Incomplete" if comp != "incomplete" else "• Incomplete",
                callback_data=f"tracking_filter:{filter_kind}:incomplete",
            ),
            InlineKeyboardButton(
                "Complete" if comp != "complete" else "• Complete",
                callback_data=f"tracking_filter:{filter_kind}:complete",
            ),
            InlineKeyboardButton(
                "Any" if comp != "all" else "• Any",
                callback_data=f"tracking_filter:{filter_kind}:all",
            ),
        ]
    )
    rows.append([InlineKeyboardButton("« Main menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)
