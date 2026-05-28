"""Smart ingest: fingerprints, content lanes, course jobs."""
from __future__ import annotations

import logging
from typing import Any

from content_lanes import LANE_COURSE, LANE_MEDIA, lane_defaults, normalize_lane
from course_parser import parse_lesson_filename
from fingerprint import compute_content_fingerprint
from title_indexer import build_index_metadata

logger = logging.getLogger(__name__)

VIDEO_EXT = frozenset({".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".ts"})
AUDIO_EXT = frozenset({".mp3", ".m4a", ".flac", ".wav", ".aac", ".ogg"})
DOC_EXT = frozenset({".pdf", ".epub", ".mobi", ".azw3", ".djvu", ".cbz", ".cbr"})
IMAGE_EXT = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"})


def detect_file_kind(file_name: str, *, telegram_kind: str | None = None) -> str:
    ext = (file_name or "").rsplit(".", 1)[-1].lower() if "." in (file_name or "") else ""
    dotted = f".{ext}" if ext else ""
    if telegram_kind == "photo":
        return "image"
    if telegram_kind == "animation":
        return "gif"
    if telegram_kind == "audio":
        return "audio"
    if telegram_kind == "video":
        return "video"
    if dotted in IMAGE_EXT:
        return "image"
    if dotted in DOC_EXT:
        return "ebook" if dotted in {".epub", ".mobi", ".azw3"} else "document"
    if dotted in AUDIO_EXT:
        return "audio"
    if dotted in VIDEO_EXT:
        return "video"
    return "other"


def extract_message_file(message) -> dict | None:
    """Pull indexable file fields from a channel post."""
    file_name = None
    file_size = None
    file_id = None
    file_unique_id = None
    telegram_kind = None

    if message.document:
        f = message.document
        file_name = f.file_name
        file_size = f.file_size
        file_id = f.file_id
        file_unique_id = getattr(f, "file_unique_id", None)
        telegram_kind = "document"
    elif message.video:
        f = message.video
        file_name = f.file_name or f"video_{message.message_id}.mp4"
        file_size = f.file_size
        file_id = f.file_id
        file_unique_id = getattr(f, "file_unique_id", None)
        telegram_kind = "video"
    elif message.audio:
        f = message.audio
        file_name = f.file_name or f"audio_{message.message_id}.mp3"
        file_size = f.file_size
        file_id = f.file_id
        file_unique_id = getattr(f, "file_unique_id", None)
        telegram_kind = "audio"
    elif getattr(message, "photo", None):
        photos = message.photo
        if photos:
            f = photos[-1]
            file_name = f"photo_{message.message_id}.jpg"
            file_size = f.file_size
            file_id = f.file_id
            file_unique_id = getattr(f, "file_unique_id", None)
            telegram_kind = "photo"
    elif getattr(message, "animation", None):
        f = message.animation
        file_name = getattr(f, "file_name", None) or f"anim_{message.message_id}.mp4"
        file_size = f.file_size
        file_id = f.file_id
        file_unique_id = getattr(f, "file_unique_id", None)
        telegram_kind = "animation"

    if not file_name:
        return None
    return {
        "file_name": file_name,
        "file_size": file_size,
        "file_id": file_id,
        "file_unique_id": file_unique_id,
        "file_kind": detect_file_kind(file_name, telegram_kind=telegram_kind),
    }


def policy_channel_id(channel_id: str, source_channel_id: str | None) -> str:
    return str(source_channel_id or channel_id)


def build_course_index_metadata(
    file_name: str,
    *,
    db,
    job_item,
    course_title: str,
) -> dict[str, Any]:
    parsed = parse_lesson_filename(file_name)
    if job_item:
        if job_item.module:
            parsed["module"] = job_item.module
        if job_item.lesson_title:
            parsed["lesson_title"] = job_item.lesson_title
        seq = job_item.sequence
    else:
        seq = parsed.get("lesson_number")

    ct = db.upsert_course_title(course_title)
    mod_num = parsed.get("module_number")
    lesson_num = parsed.get("lesson_number")
    lesson_title = parsed.get("lesson_title") or file_name
    module_name = parsed.get("module")
    display = lesson_title
    if module_name:
        display = f"{module_name} · {lesson_title}"

    return {
        "parsed_name": display,
        "auto_confirm": True,
        "library_visible": False,
        "needs_tmdb_pick": False,
        "content_title_id": ct.id,
        "season_number": mod_num,
        "episode_number": lesson_num,
        "episode_title": lesson_title[:200] if lesson_title else None,
        "module_name": module_name,
        "lesson_sequence": seq,
        "media_type": "course",
    }


def build_static_file_metadata(
    file_name: str, *, db, file_kind: str = "image"
) -> dict[str, Any]:
    """Auto-index images/GIFs without TMDB."""
    from pathlib import Path as _Path

    label = _Path(file_name or "image").stem[:200] or file_name[:200]
    ct = db.upsert_content_title(
        local_name=label,
        media_type="movie",
        catalog_excluded=True,
    )
    return {
        "parsed_name": label,
        "auto_confirm": True,
        "library_visible": False,
        "needs_tmdb_pick": False,
        "content_title_id": ct.id if ct else None,
        "season_number": None,
        "episode_number": None,
        "episode_title": None,
        "module_name": None,
        "lesson_sequence": None,
        "media_type": "movie",
    }


def build_lane_index_metadata(
    file_name: str,
    content_lane: str,
    *,
    parser,
    tmdb_helper,
    db,
    job_item=None,
    course_title: str | None = None,
) -> dict[str, Any]:
    lane = normalize_lane(content_lane)
    defaults = lane_defaults(lane)

    if lane == LANE_COURSE:
        title = course_title or (job_item.job.course_title if job_item and job_item.job else None) or "Course"
        return build_course_index_metadata(
            file_name, db=db, job_item=job_item, course_title=title
        )

    if not defaults["auto_tmdb"] or lane != LANE_MEDIA:
        parsed = parser.parse_name(file_name)
        local = parsed.get("show_name") or parsed.get("name") or file_name
        ct = db.upsert_content_title(
            local_name=local[:200],
            media_type="movie",
            catalog_excluded=True,
        )
        return {
            "parsed_name": local[:200],
            "auto_confirm": True,
            "library_visible": False,
            "needs_tmdb_pick": False,
            "content_title_id": ct.id if ct else None,
            "season_number": parsed.get("season"),
            "episode_number": parsed.get("episode"),
            "episode_title": parsed.get("episode_title"),
            "module_name": None,
            "lesson_sequence": None,
            "media_type": parsed.get("media_type") or "movie",
        }

    meta = build_index_metadata(file_name, parser=parser, tmdb_helper=tmdb_helper, db=db)
    meta["module_name"] = None
    meta["lesson_sequence"] = None
    return meta


def index_channel_upload(
    db,
    parser,
    tmdb_helper,
    *,
    channel_id: str,
    message_id: int,
    source_channel_id: str | None,
    extracted: dict,
    refresh_job_on_link: bool = True,
) -> tuple[Any | None, dict]:
    """
    Full ingest path. Returns (upload, info dict).
    upload is None if skipped as duplicate_hold without row, or duplicate skipped.
    """
    file_name = extracted["file_name"]
    prep = prepare_ingest(
        db,
        channel_id=channel_id,
        source_channel_id=source_channel_id,
        file_name=file_name,
        file_size=extracted.get("file_size"),
        file_unique_id=extracted.get("file_unique_id"),
        file_kind=extracted.get("file_kind"),
    )
    lane = prep["content_lane"]
    job_item = prep["job_item"]
    dupes = prep["duplicates"]
    file_kind = extracted.get("file_kind", "video")

    if prep["hold_duplicate"] and not job_item:
        dup_id = dupes[0].id if dupes else None
        upload = db.add_file_upload(
            channel_id=channel_id,
            message_id=message_id,
            file_name=file_name,
            file_size=extracted.get("file_size"),
            file_id=extracted.get("file_id"),
            parsed_name=file_name,
            auto_confirm=False,
            source_channel_id=source_channel_id,
            content_fingerprint=prep["content_fingerprint"],
            file_unique_id=extracted.get("file_unique_id"),
            file_kind=extracted.get("file_kind", "video"),
            content_lane=lane,
            ingest_state="duplicate_hold",
            duplicate_of_upload_id=dup_id,
        )
        return upload, {"status": "duplicate_hold", "prep": prep}

    course_title = None
    if job_item and job_item.job:
        course_title = job_item.job.course_title

    meta = (
        build_static_file_metadata(
            file_name, db=db, file_kind=file_kind
        )
        if file_kind in ("image", "gif")
        else build_lane_index_metadata(
            file_name,
            lane,
            parser=parser,
            tmdb_helper=tmdb_helper,
            db=db,
            job_item=job_item,
            course_title=course_title,
        )
    )

    upload = db.add_file_upload(
        channel_id=channel_id,
        message_id=message_id,
        file_name=file_name,
        file_size=extracted.get("file_size"),
        file_id=extracted.get("file_id"),
        parsed_name=meta["parsed_name"],
        auto_confirm=meta["auto_confirm"],
        library_visible=meta.get("library_visible", False),
        source_channel_id=source_channel_id,
        content_title_id=meta.get("content_title_id"),
        season_number=meta.get("season_number"),
        episode_number=meta.get("episode_number"),
        episode_title=meta.get("episode_title"),
        content_fingerprint=prep["content_fingerprint"],
        file_unique_id=extracted.get("file_unique_id"),
        file_kind=extracted.get("file_kind", "video"),
        content_lane=lane,
        ingest_state="normal",
        upload_job_item_id=job_item.id if job_item else None,
        module_name=meta.get("module_name"),
        lesson_sequence=meta.get("lesson_sequence"),
    )
    if job_item and upload:
        db.link_job_item_to_upload(
            job_item.id,
            upload.id,
            message_id,
            refresh_job=refresh_job_on_link,
        )
    route_info = {}
    if upload:
        from pipeline_router import maybe_queue_route_after_index

        route_info = maybe_queue_route_after_index(db, upload)
    return upload, {"status": "indexed", "meta": meta, "prep": prep, "route": route_info}


def reindex_existing_upload(db, parser, tmdb_helper, upload_id: int) -> bool:
    """Apply lane indexing to a duplicate_hold row after admin approves."""
    upload = db.get_file_upload(upload_id)
    if not upload:
        return False
    extracted = {
        "file_name": upload.file_name,
        "file_size": upload.file_size,
        "file_id": upload.file_id,
        "file_unique_id": upload.file_unique_id,
        "file_kind": upload.file_kind or "video",
    }
    prep = prepare_ingest(
        db,
        channel_id=upload.channel_id,
        source_channel_id=upload.source_channel_id,
        file_name=upload.file_name,
        file_size=upload.file_size,
        file_unique_id=upload.file_unique_id,
    )
    job_item = db.match_pending_job_item(
        upload.channel_id, upload.file_name, upload.file_size
    )
    course_title = job_item.job.course_title if job_item and job_item.job else None
    meta = build_lane_index_metadata(
        upload.file_name,
        prep["content_lane"],
        parser=parser,
        tmdb_helper=tmdb_helper,
        db=db,
        job_item=job_item,
        course_title=course_title,
    )
    from database import FileUpload

    session = db.get_session()
    try:
        row = session.query(FileUpload).filter_by(id=upload_id).first()
        if not row:
            return False
        row.parsed_name = meta["parsed_name"]
        row.content_title_id = meta.get("content_title_id")
        row.season_number = meta.get("season_number")
        row.episode_number = meta.get("episode_number")
        row.episode_title = meta.get("episode_title")
        row.module_name = meta.get("module_name")
        row.lesson_sequence = meta.get("lesson_sequence")
        row.content_lane = prep["content_lane"]
        row.content_fingerprint = prep["content_fingerprint"]
        row.ingest_state = "normal"
        row.needs_confirmation = not meta["auto_confirm"]
        row.is_confirmed = bool(meta["auto_confirm"])
        row.library_visible = bool(meta.get("library_visible") and meta["auto_confirm"])
        row.confirmed_name = meta["parsed_name"] if meta["auto_confirm"] else None
        session.commit()
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


def resolve_content_lane_for_ingest(
    db,
    *,
    channel_id: str,
    file_name: str,
    file_kind: str | None = None,
) -> str:
    """Channel staging lane, or classifier override on mixed ingest sink."""
    from config import Config

    pol = str(channel_id)
    channel_lane = db.get_channel_lane(pol)
    ch = db.get_channel(pol)
    if not ch:
        return channel_lane
    if getattr(ch, "is_ingest_channel", False) or Config.PIPELINE_CLASSIFY_INGEST:
        from content_classifier import classify_file_lane

        return classify_file_lane(
            file_name, file_kind=file_kind, channel_lane=channel_lane
        )
    return channel_lane


def prepare_ingest(
    db,
    *,
    channel_id: str,
    source_channel_id: str | None,
    file_name: str,
    file_size: int | None,
    file_unique_id: str | None = None,
    file_kind: str | None = None,
) -> dict[str, Any]:
    pol = policy_channel_id(channel_id, source_channel_id)
    lane = resolve_content_lane_for_ingest(
        db, channel_id=pol, file_name=file_name, file_kind=file_kind
    )
    fp = compute_content_fingerprint(file_name, file_size, file_unique_id=file_unique_id)
    dupes = db.find_uploads_by_fingerprint(
        fp, limit=5, incoming_channel_id=channel_id
    )
    job_item = db.match_pending_job_item(channel_id, file_name, file_size)
    return {
        "policy_channel_id": pol,
        "content_lane": lane,
        "content_fingerprint": fp,
        "duplicates": dupes,
        "job_item": job_item,
        "hold_duplicate": bool(dupes) and not job_item,
    }
