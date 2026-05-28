"""
Library watch UI: title → episode (TV) → quality variant → delivery detail.
"""
from __future__ import annotations

import logging
from html import escape
from typing import Any

from file_variant import extract_quality_label, format_file_size, quality_sort_key
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError

logger = logging.getLogger(__name__)

EpisodeKey = tuple[int | None, int | None]


def channel_message_link(channel_id: str | None, message_id: int | None) -> str | None:
    """Deep link to a channel post (private supergroups use t.me/c/...)."""
    if not channel_id or message_id is None:
        return None
    cid = str(channel_id)
    if cid.startswith("-100"):
        internal = cid[4:]
    elif cid.startswith("-"):
        internal = cid[1:]
    else:
        internal = cid
    return f"https://t.me/c/{internal}/{message_id}"


def channel_public_link(username: str | None, message_id: int | None) -> str | None:
    if not username or message_id is None:
        return None
    user = username.lstrip("@")
    return f"https://t.me/{user}/{message_id}"


def upload_channel_label(upload) -> str:
    ch = getattr(upload, "channel", None)
    if ch and ch.channel_username:
        return f"@{ch.channel_username}"
    if ch and ch.channel_title:
        t = ch.channel_title
        return t if len(t) <= 20 else t[:17] + "…"
    return "channel"


def is_combined_episode_key(season: int | None, episode: int | None) -> bool:
    """Season packs / multi-episode files indexed without per-episode numbers."""
    return season is None and episode is None


def episode_label(season: int | None, episode: int | None, episode_title: str | None = None) -> str:
    if is_combined_episode_key(season, episode):
        return "Multi-episode pack"
    if season is not None and episode is not None:
        base = f"S{int(season):02d}E{int(episode):02d}"
        if episode_title:
            et = episode_title if len(episode_title) <= 24 else episode_title[:21] + "…"
            return f"{base} — {et}"
        return base
    if episode is not None:
        return f"Episode {episode}"
    if season is not None:
        return f"Season {int(season)} pack"
    return "Special"


def _episode_sort_key(key: EpisodeKey) -> tuple:
    season, episode = key
    if is_combined_episode_key(season, episode):
        return (1, 0, 0)
    return (0, season or 0, episode or 0)


def group_tv_episodes(uploads: list) -> list[tuple[EpisodeKey, list]]:
    buckets: dict[EpisodeKey, list] = {}
    for u in uploads:
        key: EpisodeKey = (u.season_number, u.episode_number)
        buckets.setdefault(key, []).append(u)
    items = list(buckets.items())
    items.sort(key=lambda kv: _episode_sort_key(kv[0]))
    return items


def is_poster_sidecar_upload(upload) -> bool:
    """Poster images indexed beside video — not watchable as episodes."""
    name = (getattr(upload, "file_name", None) or "").lower()
    return "poster" in name and name.endswith((".jpg", ".jpeg", ".png", ".webp"))


def filter_watchable_media_uploads(uploads: list) -> list:
    return filter_deliverable_uploads(uploads)


def filter_deliverable_uploads(uploads: list) -> list:
    """Video/audio plus documents/images (PDFs, ebooks) — not poster sidecars."""
    out = []
    for u in uploads:
        if is_poster_sidecar_upload(u):
            continue
        kind = (getattr(u, "file_kind", None) or "video").lower()
        if kind in ("video", "audio", "document", "image"):
            out.append(u)
            continue
        name = (getattr(u, "file_name", None) or "").lower()
        if any(name.endswith(ext) for ext in (".pdf", ".epub", ".mobi", ".cbz", ".cbr", ".zip")):
            out.append(u)
    return out


def sort_variants(uploads: list) -> list:
    return sorted(
        uploads,
        key=lambda u: quality_sort_key(u.file_name, u.file_size),
    )


def dedupe_upload_variants(uploads: list) -> list:
    """One button per quality+size (avoids twin rows for duplicate index rows)."""
    out: list = []
    seen: set[tuple[str, int]] = set()
    for u in sort_variants(uploads):
        key = (extract_quality_label(u.file_name), int(u.file_size or 0))
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


def pick_best_upload(uploads: list):
    """Highest-quality variant for bulk send."""
    variants = dedupe_upload_variants(filter_watchable_media_uploads(uploads))
    return variants[0] if variants else None


def format_variant_button_label(upload, *, admin: bool = False) -> str:
    q = extract_quality_label(upload.file_name)
    size = format_file_size(upload.file_size)
    if admin:
        ch = upload_channel_label(upload)
        label = f"{q} · {size} · {ch}"
        if len(label) > 60:
            label = f"{q} · {size}"
        return label
    return f"{q} · {size}"


def upload_copy_ref(upload) -> tuple[int | str, int]:
    """Chat id + message id of the indexed media post (not catalog poster cards)."""
    cid, mid = upload.channel_id, upload.message_id
    try:
        return int(cid), int(mid)
    except (TypeError, ValueError):
        return cid, int(mid)


def upload_stream_channel_ids(upload) -> list[str]:
    """Channel ids to try for Telethon download (source first when forwarded)."""
    out: list[str] = []
    for cid in (getattr(upload, "source_channel_id", None), upload.channel_id):
        if not cid:
            continue
        s = str(cid)
        if s not in out:
            out.append(s)
    return out


def upload_copy_candidates(upload) -> list[tuple[int | str, int]]:
    """Ordered sources to copy the actual file from."""
    mid = int(upload.message_id)
    out: list[tuple[int | str, int]] = []
    seen: set[tuple[str, int]] = set()
    for cid in upload_stream_channel_ids(upload):
        try:
            key = (str(int(cid)), mid)
            chat: int | str = int(cid)
        except (TypeError, ValueError):
            key = (str(cid), mid)
            chat = cid
        if key in seen:
            continue
        seen.add(key)
        out.append((chat, mid))
    if not out:
        out.append(upload_copy_ref(upload))
    return out


def copy_delivery_error_hint(exc: BaseException) -> str:
    msg = str(exc).lower()
    if "not enough rights" in msg or "have no rights" in msg or "forbidden" in msg:
        return (
            "The bot needs permission to read the library channel. "
            "Ask an admin to add the bot as admin there."
        )
    if "message_id_invalid" in msg or "message not found" in msg or "can't be copied" in msg:
        return "This file is no longer in the channel — try another version."
    return "Could not send this file — try another version."


def build_episode_nav_rows(
    ct_id: int,
    context,
    current_key: EpisodeKey,
    *,
    browse_idx: int | None = None,
    include_episodes: bool = True,
    include_send_all: bool = False,
) -> list[list[InlineKeyboardButton]]:
    """Prev/next episode and episode list (TV hub rows)."""
    episode_keys: list[EpisodeKey] = context.user_data.get("watch_episode_keys") or []
    if not episode_keys:
        return []

    try:
        pos = episode_keys.index(current_key)
    except ValueError:
        return []

    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if pos > 0:
        s, e = episode_keys[pos - 1]
        sp, ep = _ep_callback_parts(s, e)
        nav.append(
            InlineKeyboardButton(
                "◀ Prev",
                callback_data=f"watch_ep:{ct_id}:{sp}:{ep}",
            )
        )
    if pos < len(episode_keys) - 1:
        s, e = episode_keys[pos + 1]
        sp, ep = _ep_callback_parts(s, e)
        nav.append(
            InlineKeyboardButton(
                "Next ▶",
                callback_data=f"watch_ep:{ct_id}:{sp}:{ep}",
            )
        )
    if nav:
        rows.append(nav)

    if include_send_all and len(episode_keys) > 1:
        rows.append(
            [
                InlineKeyboardButton(
                    "📦 Send all episodes",
                    callback_data=f"watch_all:{ct_id}",
                )
            ]
        )

    idx = browse_idx if browse_idx is not None else context.user_data.get("watch_browse_idx")
    if include_episodes and idx is not None:
        rows.append(
            [InlineKeyboardButton("📋 Episodes", callback_data=f"watch_title:{idx}")]
        )
    return rows


def build_episode_hub_text(
    title: str,
    *,
    episode_line: str | None = None,
    sent_episode_line: str | None = None,
    simple_prompt: bool = True,
    files_above: bool = False,
) -> str:
    lines: list[str] = []
    if sent_episode_line:
        if files_above:
            lines.append(f"✅ <b>{escape(sent_episode_line)}</b> shared above.")
        else:
            lines.append(f"✅ <b>{escape(sent_episode_line)}</b> shared.")
        lines.append("")
    lines.append(f"<b>▶ {escape(title)}</b>")
    if episode_line:
        lines.append(f"<i>{escape(episode_line)}</i>")
    lines.append("")
    if simple_prompt:
        lines.append("Tap a version to receive the file:")
    else:
        lines.append("Choose a version to receive the file:")
    return "\n".join(lines)


def build_episode_hub_keyboard(
    variants: list,
    ct_id: int,
    context,
    current_key: EpisodeKey,
    *,
    browse_idx: int | None = None,
    back_cb: str | None = None,
    back_label: str = "« Back",
    admin: bool = False,
    include_favorites: bool = True,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for u in variants:
        rows.append(
            [
                InlineKeyboardButton(
                    f"▶ {format_variant_button_label(u, admin=admin)}",
                    callback_data=f"watch_pick:{u.id}",
                )
            ]
        )
    rows.extend(
        build_episode_nav_rows(
            ct_id,
            context,
            current_key,
            browse_idx=browse_idx,
        )
    )
    if back_cb:
        rows.append([InlineKeyboardButton(back_label, callback_data=back_cb)])
    if include_favorites:
        rows.append(
            [
                InlineKeyboardButton(
                    "⭐ Favorite", callback_data=f"watch_fav:{ct_id}"
                ),
                InlineKeyboardButton(
                    "📋 Watchlist", callback_data=f"watch_wl:{ct_id}"
                ),
            ]
        )
    rows.append([InlineKeyboardButton("« Main menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def build_bulk_share_summary_text(
    title: str,
    sent_count: int,
    *,
    failed: int = 0,
) -> str:
    """Summary hub after Send all episodes — no per-episode picker copy."""
    lines = [
        f"✅ <b>{sent_count} episode(s)</b> shared above.",
        "",
        f"<b>▶ {escape(title)}</b>",
    ]
    if failed:
        lines.extend(
            [
                "",
                f"<i>{failed} episode(s) could not be shared — open Episodes to try those.</i>",
            ]
        )
    return "\n".join(lines)


def build_bulk_share_summary_keyboard(
    ct_id: int,
    *,
    browse_idx: int | None = None,
    back_cb: str | None = None,
    back_label: str = "« Episodes",
    include_favorites: bool = True,
) -> InlineKeyboardMarkup:
    """Navigation only — no version or prev/next after bulk share."""
    rows: list[list[InlineKeyboardButton]] = []
    if browse_idx is not None:
        rows.append(
            [InlineKeyboardButton("📋 Episodes", callback_data=f"watch_title:{browse_idx}")]
        )
    elif back_cb:
        rows.append([InlineKeyboardButton(back_label, callback_data=back_cb)])
    if include_favorites:
        rows.append(
            [
                InlineKeyboardButton(
                    "⭐ Favorite", callback_data=f"watch_fav:{ct_id}"
                ),
                InlineKeyboardButton(
                    "📋 Watchlist", callback_data=f"watch_wl:{ct_id}"
                ),
            ]
        )
    rows.append([InlineKeyboardButton("« Main menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


async def deliver_upload_to_chat(
    bot: Bot,
    chat_id: int | str,
    upload,
    ct,
    *,
    quality: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Copy the channel media into the user's DM (no forward header)."""
    from telegram_flood import throttle

    caption = build_user_delivery_caption(upload, ct, quality=quality)
    last_exc: BaseException | None = None

    for from_chat_id, message_id in upload_copy_candidates(upload):
        for use_caption in (True, False):
            kwargs: dict[str, Any] = {
                "chat_id": chat_id,
                "from_chat_id": from_chat_id,
                "message_id": message_id,
            }
            if use_caption and caption:
                kwargs["caption"] = caption
                kwargs["parse_mode"] = ParseMode.HTML
            if reply_markup is not None:
                kwargs["reply_markup"] = reply_markup

            try:
                await throttle(chat_id)
                return await bot.copy_message(**kwargs)
            except BadRequest as e:
                last_exc = e
                err = str(e).lower()
                logger.warning(
                    "copy_message %s/%s caption=%s: %s",
                    from_chat_id,
                    message_id,
                    use_caption,
                    e,
                )
                if use_caption and (
                    "caption" in err or "entities" in err or "parse" in err
                ):
                    continue
                break
            except TelegramError as e:
                last_exc = e
                logger.warning(
                    "copy_message %s/%s failed: %s", from_chat_id, message_id, e
                )
                break

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("No copy source for upload")


def build_title_hub_text(entry: dict, ct, stats: dict) -> str:
    title = escape(entry.get("title") or "?")
    mt = (entry.get("media_type") or (ct.media_type if ct else "movie") or "movie").lower()
    icon = "📺" if mt in ("tv", "series") else "🎬"
    kind = "TV series" if mt in ("tv", "series") else "Movie"
    lines = [
        f"<b>{icon} {title}</b>",
        f"<i>{kind}</i>",
    ]
    yr = entry.get("release_year") or (ct.release_year if ct else None)
    vote = entry.get("vote_average") or (ct.vote_average if ct else None)
    meta = []
    if yr:
        meta.append(str(yr))
    if vote not in (None, ""):
        try:
            meta.append(f"★{float(vote):.1f}")
        except (TypeError, ValueError):
            pass
    if meta:
        lines.append(" · ".join(meta))
    lines.append("")
    lines.append(f"<b>{stats.get('total_uploads', 0)}</b> watchable version(s) available")
    if stats.get("unavailable"):
        lines.append(
            f"<i>{stats['unavailable']} removed from channel (hidden from Watch)</i>"
        )
    lines.append("")
    lines.append("Choose <b>▶ Watch</b> to pick episode and quality.")
    return "\n".join(lines)


def build_episode_list_text(title: str) -> str:
    return (
        f"<b>📺 {escape(title)}</b>\n\n"
        "Choose an episode or a <b>multi-episode pack</b>,\n"
        "or tap <b>📦 Send all episodes</b> below."
    )


def build_quality_list_text(
    title: str,
    *,
    episode_line: str | None = None,
    variant_count: int = 0,
    simple_prompt: bool = False,
) -> str:
    lines = [f"<b>▶ {escape(title)}</b>"]
    if episode_line:
        lines.append(f"<i>{escape(episode_line)}</i>")
    lines.append("")
    if simple_prompt:
        lines.append("Tap a version to receive the file:")
    else:
        lines.append(
            f"<b>{variant_count}</b> version(s) — tap to receive the file:"
        )
    return "\n".join(lines)


def message_link_for_upload(upload) -> str | None:
    """Best-effort Telegram link to the indexed channel post for this file."""
    ch = upload.channel
    ch_id = upload.channel_id
    if ch and ch.channel_username:
        link = channel_public_link(ch.channel_username, upload.message_id)
        if link:
            return link
    return channel_message_link(ch_id, upload.message_id)


def _ep_callback_parts(season: int | None, episode: int | None) -> tuple[int, int]:
    return (
        season if season is not None else -1,
        episode if episode is not None else -1,
    )


def parse_ep_callback_parts(season_part: int, episode_part: int) -> EpisodeKey:
    return (
        None if season_part < 0 else season_part,
        None if episode_part < 0 else episode_part,
    )


def _display_title(upload, ct) -> str:
    return (
        (ct.tmdb_title if ct and ct.tmdb_title else None)
        or upload.confirmed_name
        or upload.parsed_name
        or "?"
    )


def build_user_delivery_caption(upload, ct, *, quality: str) -> str:
    """Minimal caption on copied files — version details live on the hub message."""
    title = escape(_display_title(upload, ct))
    lines = [f"<b>{title}</b>"]
    if is_combined_episode_key(upload.season_number, upload.episode_number):
        lines.append(escape(episode_label(None, None)))
    elif upload.season_number is not None or upload.episode_number is not None:
        lines.append(
            escape(
                episode_label(
                    upload.season_number,
                    upload.episode_number,
                    upload.episode_title,
                )
            )
        )
    return "\n".join(lines)


def build_delivery_text(upload, ct, *, quality: str, admin: bool = False) -> str:
    title = escape(_display_title(upload, ct))
    lines = [f"<b>{title}</b>", ""]
    if upload.season_number is not None or upload.episode_number is not None:
        lines.append(
            f"📅 {escape(episode_label(upload.season_number, upload.episode_number, upload.episode_title))}"
        )
    lines.append(f"🎞 <b>Quality:</b> {escape(quality)}")
    lines.append(f"📦 <b>Size:</b> {escape(format_file_size(upload.file_size))}")
    if not admin:
        return "\n".join(lines)
    ch = upload_channel_label(upload)
    lines.append(f"📺 <b>Channel:</b> {escape(ch)}")
    if upload.uploaded_at:
        lines.append(f"🕐 {upload.uploaded_at.strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append("")
    lines.append(f"<code>{escape(upload.file_name)}</code>")
    return "\n".join(lines)
