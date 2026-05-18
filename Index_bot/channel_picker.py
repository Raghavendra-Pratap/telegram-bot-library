"""
Paginated, searchable inline channel lists (Telegram 100-button limit safe).
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import Config

DEFAULT_PAGE_SIZE = 15


def filter_channels(channels: list, query: str | None) -> list:
    q = (query or "").strip().lower()
    if not q:
        return list(channels)
    out = []
    for ch in channels:
        title = (getattr(ch, "channel_title", None) or "").lower()
        user = (getattr(ch, "channel_username", None) or "").lower()
        cid = str(getattr(ch, "channel_id", "") or "")
        if q in title or (user and q in user) or q in cid.lstrip("-"):
            out.append(ch)
    return out


def paginate(items: list, page: int, page_size: int | None = None) -> tuple[list, int, int]:
    page_size = page_size or Config.CHANNEL_PICKER_PAGE_SIZE
    if not items:
        return [], 0, 1
    pages = max(1, (len(items) + page_size - 1) // page_size)
    page = max(0, min(page, pages - 1))
    return items[page * page_size : (page + 1) * page_size], page, pages


def build_channel_picker(
    channels: list,
    *,
    page: int = 0,
    query: str | None = None,
    callback_prefix: str,
    pick_prefix: str,
    label_fn,
    exclude_ids: set[str] | None = None,
    extra_top: list[list[InlineKeyboardButton]] | None = None,
    back_callback: str = "main_menu",
    back_label: str = "« Back",
    search_callback: str | None = None,
    title_line: str = "",
) -> tuple[str, InlineKeyboardMarkup]:
    """
    Build message text + keyboard for a searchable channel list.

    callback_prefix: e.g. ``bfch`` → page nav uses ``bfch_page:2:query_b64`` (query optional).
    pick_prefix: e.g. ``backfill_pick`` → ``backfill_pick:{channel_id}``.
    """
    exclude_ids = exclude_ids or set()
    filtered = [
        ch
        for ch in filter_channels(channels, query)
        if str(getattr(ch, "channel_id", "")) not in exclude_ids
    ]
    chunk, page, pages = paginate(filtered, page)

    lines = [title_line] if title_line else []
    if query:
        lines.append(f'Filter: <b>"{query}"</b> · <b>{len(filtered)}</b> match(es)')
    lines.append(f"Page <b>{page + 1}</b> / <b>{pages}</b> · <b>{len(filtered)}</b> channel(s)")
    if not chunk:
        lines.append("\n<i>No channels match. Try another search or clear the filter.</i>")

    keyboard: list[list[InlineKeyboardButton]] = list(extra_top or [])
    q_token = _encode_query(query) if query else ""
    for ch in chunk:
        keyboard.append(
            [
                InlineKeyboardButton(
                    label_fn(ch),
                    callback_data=f"{pick_prefix}:{ch.channel_id}",
                )
            ]
        )
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "« Prev",
                callback_data=f"{callback_prefix}_page:{page - 1}:{q_token}",
            )
        )
    if page + 1 < pages:
        nav.append(
            InlineKeyboardButton(
                "Next »",
                callback_data=f"{callback_prefix}_page:{page + 1}:{q_token}",
            )
        )
    if nav:
        keyboard.append(nav)
    tool = []
    if search_callback:
        tool.append(
            InlineKeyboardButton("🔍 Search", callback_data=search_callback)
        )
        if query:
            tool.append(
                InlineKeyboardButton(
                    "✕ Clear search",
                    callback_data=f"{callback_prefix}_page:0:",
                )
            )
    if tool:
        keyboard.append(tool)
    keyboard.append([InlineKeyboardButton(back_label, callback_data=back_callback)])
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


def _encode_query(query: str | None) -> str:
    if not query:
        return ""
    import base64

    return base64.urlsafe_b64encode(query.encode("utf-8")[:40]).decode("ascii").rstrip("=")


def decode_query_token(token: str) -> str | None:
    if not token:
        return None
    import base64

    pad = "=" * (-len(token) % 4)
    try:
        return base64.urlsafe_b64decode(token + pad).decode("utf-8")
    except Exception:
        return None


def parse_picker_page_callback(data: str, prefix: str) -> tuple[int, str | None] | None:
    """Parse ``{prefix}_page:2:optional_query_token``."""
    head = f"{prefix}_page:"
    if not data.startswith(head):
        return None
    rest = data[len(head) :]
    parts = rest.split(":", 1)
    try:
        page = int(parts[0])
    except ValueError:
        return None
    query = decode_query_token(parts[1]) if len(parts) > 1 else None
    return page, query
