"""Deep-link payloads for catalog card buttons → open bot in private chat."""
from __future__ import annotations


def season_callback_value(season_number: int | None) -> int:
    return -1 if season_number is None else int(season_number)


def season_from_callback(value: int) -> int | None:
    return None if value < 0 else int(value)


def bot_start_url(bot_username: str, payload: str) -> str:
    return f"https://t.me/{bot_username.lstrip('@')}?start={payload}"


def watch_start_payload(content_title_id: int, season_number: int | None) -> str:
    sn = season_callback_value(season_number)
    return f"watch_{int(content_title_id)}_{sn}"


def watchlist_start_payload(content_title_id: int) -> str:
    return f"wl_{int(content_title_id)}"


def favorite_start_payload(content_title_id: int) -> str:
    return f"fav_{int(content_title_id)}"


def file_start_payload(upload_id: int) -> str:
    return f"file_{int(upload_id)}"


def parse_file_start_payload(payload: str) -> int | None:
    if not payload.startswith("file_"):
        return None
    try:
        return int(payload.split("_", 1)[1])
    except (ValueError, IndexError):
        return None


def parse_watch_start_payload(payload: str) -> tuple[int, int | None] | None:
    if not payload.startswith("watch_"):
        return None
    parts = payload.split("_")
    if len(parts) < 3:
        return None
    try:
        ct_id = int(parts[1])
        sn = int(parts[2])
    except ValueError:
        return None
    return ct_id, season_from_callback(sn)
