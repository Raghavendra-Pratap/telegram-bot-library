"""Heuristic content-lane classification for mixed ingest (filename + file kind)."""
from __future__ import annotations

from pathlib import Path

from content_lanes import (
    LANE_ARCHIVE,
    LANE_COURSE,
    LANE_MEDIA,
    LANE_SHORTFORM,
    normalize_lane,
)
from course_parser import parse_lesson_filename

DOC_EXT = frozenset({".pdf", ".epub", ".mobi", ".azw3", ".djvu", ".cbz", ".cbr"})
VIDEO_EXT = frozenset({".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".ts"})
AUDIO_EXT = frozenset({".mp3", ".m4a", ".flac", ".wav", ".aac", ".ogg"})

# Short clips / reels naming patterns
_SHORTFORM_HINTS = (
    "reel",
    "shorts",
    "short",
    "clip",
    "tiktok",
    "status",
)


def classify_file_lane(
    file_name: str,
    *,
    file_kind: str | None = None,
    channel_lane: str | None = None,
) -> str:
    """
    Guess content lane from filename and kind.
    Used when indexing from the mixed ingest sink (not the channel's staging default).
    """
    name = (file_name or "").lower()
    ext = Path(file_name or "").suffix.lower()
    kind = (file_kind or "").lower()

    if ext in DOC_EXT or kind in ("document", "ebook"):
        return LANE_ARCHIVE

    parsed = parse_lesson_filename(file_name)
    if parsed.get("lesson_number") is not None or parsed.get("module_number") is not None:
        return LANE_COURSE

    stem = Path(file_name or "").stem.lower()
    if any(h in stem for h in _SHORTFORM_HINTS):
        return LANE_SHORTFORM

    if ext in VIDEO_EXT or ext in AUDIO_EXT or kind in ("video", "audio"):
        # Course-like folder paths: .../Module 01/02 - Lesson.mp4
        parts = Path(file_name or "").parts
        if len(parts) >= 2:
            parent = parts[-2].lower()
            if any(
                x in parent
                for x in ("module", "chapter", "lecture", "lesson", "course", "week")
            ):
                return LANE_COURSE
        return LANE_MEDIA

    if kind in ("image", "gif"):
        return LANE_ARCHIVE

    # Fallback: keep channel default if set, else media
    return normalize_lane(channel_lane)
