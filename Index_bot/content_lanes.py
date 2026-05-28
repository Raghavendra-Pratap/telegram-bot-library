"""Content lanes: policy defaults for channels and uploads."""
from __future__ import annotations

LANE_MEDIA = "media"
LANE_SHORTFORM = "shortform"
LANE_ADULT = "adult"
LANE_COURSE = "course"
LANE_ARCHIVE = "archive"

VALID_LANES = frozenset(
    {LANE_MEDIA, LANE_SHORTFORM, LANE_ADULT, LANE_COURSE, LANE_ARCHIVE}
)

LANE_LABELS = {
    LANE_MEDIA: "🎬 Media library",
    LANE_SHORTFORM: "📱 Shortform / reels",
    LANE_ADULT: "🔒 Adult vault",
    LANE_COURSE: "🎓 Courses",
    LANE_ARCHIVE: "📦 Archive",
}

# Where classified content is published (catalog / delivery channels).
DISTRIBUTION_LANE_LABELS = {
    LANE_MEDIA: "🎬 Media — movies & series",
    LANE_COURSE: "🎓 Courses — lessons & series",
    LANE_ARCHIVE: "📦 Archive — PDFs, ebooks, files",
    LANE_SHORTFORM: "📱 Shortform — reels & clips",
}


def normalize_lane(lane: str | None) -> str:
    v = (lane or LANE_MEDIA).strip().lower()
    return v if v in VALID_LANES else LANE_MEDIA


def lane_defaults(lane: str) -> dict:
    """Default ingest/distribution flags for a lane."""
    lane = normalize_lane(lane)
    if lane == LANE_MEDIA:
        return {
            "admin_only": False,
            "auto_tmdb": True,
            "default_library_public": False,
            "default_catalog_excluded": False,
        }
    if lane == LANE_SHORTFORM:
        return {
            "admin_only": True,
            "auto_tmdb": False,
            "default_library_public": False,
            "default_catalog_excluded": True,
        }
    if lane == LANE_ADULT:
        return {
            "admin_only": True,
            "auto_tmdb": False,
            "default_library_public": False,
            "default_catalog_excluded": True,
        }
    if lane == LANE_COURSE:
        return {
            "admin_only": True,
            "auto_tmdb": False,
            "default_library_public": False,
            "default_catalog_excluded": True,
        }
    # archive
    return {
        "admin_only": True,
        "auto_tmdb": False,
        "default_library_public": False,
        "default_catalog_excluded": True,
    }


def lane_allows_public_library(lane: str) -> bool:
    return normalize_lane(lane) == LANE_MEDIA


def lane_never_public(lane: str) -> bool:
    """Content that must not appear in user browse/search."""
    return normalize_lane(lane) == LANE_ADULT


def lane_allows_tmdb(lane: str) -> bool:
    """Manual or auto TMDB title mapping (portal pending + bot pick)."""
    return normalize_lane(lane) in (LANE_MEDIA, LANE_ADULT)


def lane_allows_watch_catalog(lane: str) -> bool:
    """Watch-channel catalog cards (Telegram .Media Library) — media lane only."""
    return normalize_lane(lane) == LANE_MEDIA


VAULT_LANES = (LANE_COURSE, LANE_ARCHIVE, LANE_ADULT, LANE_SHORTFORM)

# Lanes that can have a public watch/catalog channel (admin menu; not adult).
WATCH_LANE_OPTIONS = (LANE_MEDIA, LANE_COURSE, LANE_ARCHIVE, LANE_SHORTFORM)
