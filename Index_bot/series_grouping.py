"""
Group pending uploads by show / movie prefix for bulk TMDB mapping.
"""
from __future__ import annotations

import re
from typing import Any

from name_parser import (
    fix_bypass_character_substitutions,
    strip_leading_index_parts,
    strip_leading_sequence_prefix,
)
from tmdb_helper import _normalize_title


def show_group_key(parsed: dict | None, file_name: str) -> str | None:
    """Stable key for grouping similar pending files (e.g. all Dhahanam episodes)."""
    parsed = parsed or {}
    if parsed.get("show_name"):
        return _normalize_title(parsed["show_name"])
    if parsed.get("media_type") == "tv" and parsed.get("name"):
        return _normalize_title(parsed["name"].split(" - ")[0].split(" · ")[0])
    base = fix_bypass_character_substitutions(
        re.sub(
            r"\.[^.]+$",
            "",
            strip_leading_sequence_prefix(file_name or ""),
            flags=re.I,
        )
    )
    m = re.search(
        r"^(.+?)(?:[.\s_-]+(?:s\d{1,2}[.\s_-]*e(?:p(?:isode)?)?[.\s_-]*\d{1,3}|\d{1,2}x\d{1,3}|e(?:p(?:isode)?)?[.\s_-]*\d{1,3}))",
        base,
        re.I,
    )
    if m:
        return _normalize_title(m.group(1))
    # Movie-style: strip year + quality tokens
    movie_title, _ = _extract_loose_title(base)
    if movie_title and len(movie_title) >= 3:
        return _normalize_title(movie_title)
    return None


def _extract_loose_title(base: str) -> tuple[str, None]:
    parts = strip_leading_index_parts([p for p in re.split(r"[._\s-]+", base) if p])
    title_parts: list[str] = []
    for part in parts:
        if re.fullmatch(r"(?:19|20)\d{2}", part, re.I):
            break
        if re.fullmatch(r"\d{3,4}p", part, re.I):
            break
        if re.fullmatch(r"e\d{1,3}", part, re.I):
            break
        title_parts.append(part)
    return " ".join(title_parts), None


def batched_pending_file_ids(
    groups: list[dict[str, Any]], *, min_count: int = 2
) -> set[int]:
    """File ids that belong to a multi-file batch (hide from single-file list)."""
    out: set[int] = set()
    for g in groups:
        if len(g.get("file_ids") or []) >= min_count:
            out.update(g["file_ids"])
    return out


def build_pending_groups(
    pending_files: list,
    *,
    parser,
    min_count: int = 2,
) -> list[dict[str, Any]]:
    """
    Cluster pending FileUpload rows by show_group_key.

    Returns all groups (each has ``group_id`` for callbacks). UI paginates batches.
    """
    buckets: dict[str, dict[str, Any]] = {}
    for upload in pending_files:
        parsed = parser.parse_name(upload.file_name)
        key = show_group_key(parsed, upload.file_name)
        if not key:
            continue
        if key not in buckets:
            show = parsed.get("show_name") or parsed.get("name") or key
            if parsed.get("media_type") == "tv":
                show = parsed.get("show_name") or show.split(" - ")[0]
            buckets[key] = {
                "match_key": key,
                "show_name": show,
                "media_type": parsed.get("media_type") or "movie",
                "file_ids": [],
                "files": [],
            }
        buckets[key]["file_ids"].append(upload.id)
        deferred = bool(getattr(upload, "pending_deferred_at", None))
        buckets[key].setdefault("deferred_count", 0)
        if deferred:
            buckets[key]["deferred_count"] += 1
        buckets[key]["files"].append(
            {"id": upload.id, "file_name": upload.file_name, "parsed": parsed}
        )

    groups = [g for g in buckets.values() if len(g["file_ids"]) >= min_count]
    for g in groups:
        g["deferred"] = g.get("deferred_count", 0) >= len(g["file_ids"])
    groups.sort(
        key=lambda g: (
            g.get("deferred", False),
            -len(g["file_ids"]),
            g["show_name"].lower(),
        )
    )
    for i, g in enumerate(groups):
        g["group_id"] = i
        n = len(g["file_ids"])
        kind = "📺" if g["media_type"] == "tv" else "🎬"
        defer_tag = " ⏭" if g.get("deferred") else ""
        g["label"] = (
            f"{kind} {g['show_name']} · {n} file{'s' if n != 1 else ''}{defer_tag}"
        )
    return groups


def sibling_pending_ids(
    pending_files: list,
    *,
    parser,
    anchor_file_id: int,
    anchor_parsed: dict | None,
    anchor_file_name: str,
) -> list[int]:
    """Other pending files in the same show group (excluding anchor)."""
    key = show_group_key(anchor_parsed, anchor_file_name)
    if not key:
        return []
    out: list[int] = []
    for upload in pending_files:
        if upload.id == anchor_file_id:
            continue
        p = parser.parse_name(upload.file_name)
        if show_group_key(p, upload.file_name) == key:
            out.append(upload.id)
    return out
