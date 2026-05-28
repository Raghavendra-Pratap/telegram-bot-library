"""
Watch channel catalog cards: one poster post per movie or TV season.
"""
from __future__ import annotations

import asyncio

import json
import logging
from html import escape

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError

from config import Config
from database import Database
from telegram_flood import (
    batch_pause,
    flood_edit_message_caption,
    flood_edit_message_media,
    flood_send_message,
    flood_send_photo,
    is_unchanged_message_error,
    parse_retry_after_seconds,
    parse_retry_after_text,
    watch_channel_chat_id,
)
from telegram_tags import join_hashtags, to_telegram_year_hashtag
from tmdb_helper import best_poster_url, poster_image_url, tmdb_helper, tmdb_web_url
from watch_deep_links import (
    bot_start_url,
    favorite_start_payload,
    season_callback_value,
    season_from_callback,
    watch_start_payload,
    watchlist_start_payload,
)

logger = logging.getLogger(__name__)

def build_catalog_caption(
    content_title,
    *,
    season_number: int | None = None,
    enrichment: dict | None = None,
    file_count: int = 0,
) -> str:
    en = enrichment or {}
    mt = (content_title.media_type if content_title else "movie") or "movie"
    is_tv = mt in ("tv", "series")
    title = escape(
        (content_title.tmdb_title if content_title else None)
        or content_title.name
        or "?"
    )
    yr = content_title.release_year if content_title else None
    year_suffix = f" ({yr})" if yr else ""
    lines = []
    if is_tv and season_number is not None:
        sname = en.get("season_name") or f"Season {season_number}"
        lines.append(f"<b>📺 {title}{year_suffix}</b>")
        lines.append(f"<b>{escape(str(sname))}</b>")
    else:
        lines.append(f"<b>🎬 {title}{year_suffix}</b>")

    vote = en.get("vote_average")
    if vote in (None, "") and content_title:
        vote = content_title.vote_average
    if vote not in (None, ""):
        try:
            lines.append(f"⭐ <b>{float(vote):.1f}</b> / 10")
        except (TypeError, ValueError):
            pass

    genres = en.get("genres")
    if not genres and content_title and content_title.genres:
        try:
            genres = json.loads(content_title.genres)
        except (json.JSONDecodeError, TypeError):
            genres = []
    if genres:
        lines.append(f"🏷 {join_hashtags(genres, limit=6)}")

    directors = en.get("directors") or []
    if directors:
        lines.append(f"🎬 {join_hashtags(directors, limit=3)}")

    writers = en.get("writers") or []
    if writers and not directors:
        lines.append(f"✍️ {join_hashtags(writers, limit=3)}")

    cast = en.get("cast") or []
    if cast:
        lines.append(f"👥 {join_hashtags(cast, limit=6)}")

    if yr:
        lines.append(f"release year: {to_telegram_year_hashtag(yr)}")

    overview = en.get("overview") or (content_title.overview if content_title else "")
    overview = " ".join((overview or "").split())
    if overview:
        overview = escape(overview)
        if len(overview) > 700:
            overview = overview[:699] + "…"
        lines.append(f"\n<b>Plot</b>\n{overview}")

    if content_title and content_title.tmdb_id:
        page = tmdb_web_url(
            {
                "tmdb_id": content_title.tmdb_id,
                "media_type": "tv" if is_tv else "movie",
            }
        )
        if page:
            lines.append(f'\n<a href="{escape(page)}">TMDB</a>')

    if file_count:
        lines.append(f"📦 <b>{file_count}</b> version(s) available")

    return "\n".join(lines)


def build_catalog_keyboard(
    content_title_id: int,
    season_number: int | None,
    *,
    bot_username: str | None,
) -> InlineKeyboardMarkup:
    sn = season_callback_value(season_number)
    username = (bot_username or "").strip().lstrip("@")
    if username:
        rows = [
            [
                InlineKeyboardButton(
                    "⭐ Favorite",
                    url=bot_start_url(username, favorite_start_payload(content_title_id)),
                ),
                InlineKeyboardButton(
                    "📋 Watchlist",
                    url=bot_start_url(username, watchlist_start_payload(content_title_id)),
                ),
            ],
            [
                InlineKeyboardButton(
                    "▶️ Watch",
                    url=bot_start_url(
                        username, watch_start_payload(content_title_id, season_number)
                    ),
                ),
            ],
        ]
    else:
        rows = [
            [
                InlineKeyboardButton("⭐ Favorite", callback_data=f"watch_fav:{content_title_id}"),
                InlineKeyboardButton(
                    "📋 Watchlist", callback_data=f"watch_wl:{content_title_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "▶️ Watch", callback_data=f"watch_go:{content_title_id}:{sn}"
                ),
            ],
        ]
    return InlineKeyboardMarkup(rows)


async def resolve_bot_username(bot: Bot, hint: str | None = None) -> str | None:
    username = (hint or getattr(bot, "username", None) or "").strip().lstrip("@")
    if username:
        return username
    try:
        me = await bot.get_me()
        return (me.username or "").strip() or None
    except TelegramError:
        return None


async def upgrade_channel_card_keyboard(
    bot: Bot,
    message,
    content_title_id: int,
    season_number: int | None,
    *,
    bot_username: str | None = None,
) -> bool:
    """Replace legacy callback buttons with t.me deep links on a channel catalog post."""
    if not message or not message.message_id:
        return False
    username = await resolve_bot_username(bot, bot_username)
    if not username:
        return False
    keyboard = build_catalog_keyboard(
        content_title_id, season_number, bot_username=username
    )
    try:
        from telegram_flood import call_with_flood_retry

        await call_with_flood_retry(
            lambda: bot.edit_message_reply_markup(
                chat_id=message.chat_id,
                message_id=message.message_id,
                reply_markup=keyboard,
            ),
            chat_id=message.chat_id,
            label="edit_catalog_keyboard",
        )
        return True
    except TelegramError as e:
        logger.warning("upgrade_channel_card_keyboard failed: %s", e)
        return False


async def upgrade_all_catalog_keyboards(
    bot: Bot, db: Database, *, bot_username: str | None = None
) -> tuple[int, int]:
    """Upgrade every known catalog post in the watch channel to URL buttons."""
    username = await resolve_bot_username(bot, bot_username)
    if not username:
        return 0, 0
    ok = fail = 0
    for row in db.list_watch_catalog_posts(limit=500):
        try:
            markup = build_catalog_keyboard(
                row.content_title_id,
                row.season_number,
                bot_username=username,
            )
            from telegram_flood import call_with_flood_retry

            await call_with_flood_retry(
                lambda ch=row.watch_channel_id, mid=row.message_id, mk=markup: bot.edit_message_reply_markup(
                    chat_id=int(ch),
                    message_id=int(mid),
                    reply_markup=mk,
                ),
                chat_id=row.watch_channel_id,
                label="upgrade_catalog_keyboard",
            )
            ok += 1
        except TelegramError as e:
            logger.warning(
                "upgrade catalog keyboard ct=%s: %s", row.content_title_id, e
            )
            fail += 1
    return ok, fail


def _is_missing_channel_message_error(exc: BaseException) -> bool:
    """Telegram errors when the catalog post was deleted from the channel."""
    msg = str(exc).lower()
    return (
        "message_id_invalid" in msg
        or "message to edit not found" in msg
        or "message can't be edited" in msg
        or "message not found" in msg
        or "there is no message" in msg
        or "chat not found" in msg
    )


def _bad_poster_url_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "wrong type of the web page content" in msg or "failed to get http url content" in msg


def _is_no_media_to_edit_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "there is no media in the message" in msg or "message is not modified" in msg


def _parse_ct_genres(content_title) -> list:
    if not content_title or not content_title.genres:
        return []
    try:
        parsed = json.loads(content_title.genres)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _db_enrichment_for_persist(
    ct, enrichment: dict, season_number: int | None
) -> dict:
    """Show-level TMDB fields for DB; season cards keep season art only on Telegram."""
    mt = (ct.media_type or "movie").lower()
    if (
        mt in ("tv", "series")
        and season_number is not None
        and ct.tmdb_id
        and tmdb_helper.enabled
    ):
        show = tmdb_helper.build_catalog_enrichment(
            tmdb_id=int(ct.tmdb_id),
            media_type=mt,
            season_number=None,
        )
        if show:
            return show
    return enrichment


def _persist_catalog_enrichment(
    db: Database, ct, enrichment: dict, *, season_number: int | None
):
    if not enrichment or not ct:
        return ct
    row = _db_enrichment_for_persist(ct, enrichment, season_number)
    genres = row.get("genres") or _parse_ct_genres(ct)
    name = (ct.tmdb_title or ct.name or "").strip()
    if not name:
        return ct
    vote = row.get("vote_average")
    if vote in (None, ""):
        vote = ct.vote_average
    overview = (row.get("overview") or ct.overview or "").strip() or None
    poster_path = row.get("poster_path") or ct.poster_path
    if not poster_path and row.get("backdrop_path"):
        poster_path = row.get("backdrop_path")
    updated = db.upsert_content_title(
        local_name=name,
        media_type=ct.media_type or "movie",
        tmdb_id=ct.tmdb_id,
        tmdb_title=row.get("tmdb_title") or ct.tmdb_title,
        release_year=row.get("release_year")
        if row.get("release_year") is not None
        else ct.release_year,
        poster_path=poster_path,
        overview=overview,
        vote_average=vote,
        genres=genres or None,
    )
    if updated and getattr(updated, "id", None):
        fresh = db.get_content_title(int(updated.id))
        return fresh or updated
    return ct


def _catalog_poster_url(enrichment: dict, ct, *, size: str = "w500") -> str | None:
    meta = {
        "poster_path": enrichment.get("poster_path") or ct.poster_path,
        "backdrop_path": enrichment.get("backdrop_path"),
        "media_type": (ct.media_type or "movie").lower(),
    }
    return best_poster_url(meta, size=size) or poster_image_url(meta, size=size)


async def _send_new_catalog_post(
    bot: Bot,
    *,
    dest,
    poster: str | None,
    caption: str,
    keyboard: InlineKeyboardMarkup,
) -> int:
    if poster:
        try:
            msg = await flood_send_photo(
                bot,
                dest,
                photo=poster,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            return int(msg.message_id)
        except (BadRequest, TelegramError) as e:
            if not _bad_poster_url_error(e):
                raise
            logger.warning(
                "catalog poster URL rejected, sending text-only: %s", poster[:80]
            )
    msg = await flood_send_message(
        bot,
        dest,
        caption,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )
    return int(msg.message_id)


async def _refresh_catalog_post_in_place(
    bot: Bot,
    *,
    edit_chat: int,
    message_id: int,
    poster: str | None,
    caption: str,
    keyboard: InlineKeyboardMarkup,
) -> bool:
    """Edit an existing channel card. Returns False if caller should repost."""
    try:
        if poster:
            await flood_edit_message_media(
                bot,
                edit_chat,
                message_id,
                photo=poster,
                caption=caption,
                reply_markup=keyboard,
            )
        else:
            await flood_edit_message_caption(
                bot,
                edit_chat,
                message_id,
                caption,
                reply_markup=keyboard,
            )
        return True
    except BadRequest as e:
        if is_unchanged_message_error(e):
            return True
        if poster and (
            _is_no_media_to_edit_error(e) or _bad_poster_url_error(e)
        ):
            try:
                await flood_edit_message_caption(
                    bot,
                    edit_chat,
                    message_id,
                    caption,
                    reply_markup=keyboard,
                )
                return True
            except BadRequest as e2:
                if is_unchanged_message_error(e2):
                    return True
            except TelegramError:
                pass
            return False
        if _is_missing_channel_message_error(e):
            return False
        logger.warning("refresh catalog post %s failed (%s)", message_id, e)
        return False
    except TelegramError as e:
        if poster and _bad_poster_url_error(e):
            return False
        logger.warning("refresh catalog post %s failed (%s)", message_id, e)
        return False


async def publish_catalog_slot(
    bot: Bot,
    db: Database,
    content_title_id: int,
    season_number: int | None,
    *,
    bot_username: str | None = None,
    force: bool = False,
    post_new: bool = False,
) -> tuple[bool, str]:
    from content_lanes import LANE_MEDIA, lane_allows_watch_catalog, normalize_lane

    lane = normalize_lane(db.get_content_title_lane(content_title_id))
    if not lane_allows_watch_catalog(lane):
        return False, f"Only {LANE_MEDIA} lane titles can publish watch catalog cards"
    watch_ch = db.get_watch_channel(lane)
    if not watch_ch:
        return False, f"Watch channel not configured for lane {lane}"

    existing = db.get_watch_catalog_post(content_title_id, season_number)
    if not force and not post_new and existing:
        return True, "Already published"

    ct = db.get_content_title(content_title_id)
    if not ct:
        return False, "Title not found"
    if getattr(ct, "catalog_excluded", False):
        return True, "Excluded"

    mt = (ct.media_type or "movie").lower()
    if mt == "course":
        return False, "Courses do not publish catalog cards"
    if not ct.tmdb_id:
        return False, "TMDB mapping required before publishing"
    enrichment: dict = {}
    if ct.tmdb_id and tmdb_helper.enabled:
        enrichment = tmdb_helper.build_catalog_enrichment(
            tmdb_id=int(ct.tmdb_id),
            media_type=mt,
            season_number=season_number if mt in ("tv", "series") else None,
        )
        if enrichment:
            ct = _persist_catalog_enrichment(
                db, ct, enrichment, season_number=season_number
            )

    poster = _catalog_poster_url(enrichment, ct, size="w500")
    file_count = db.count_uploads_in_catalog_slot(content_title_id, season_number)
    caption = build_catalog_caption(
        ct,
        season_number=season_number,
        enrichment=enrichment,
        file_count=file_count,
    )
    username = await resolve_bot_username(bot, bot_username)
    keyboard = build_catalog_keyboard(
        content_title_id, season_number, bot_username=username
    )
    dest = watch_channel_chat_id(watch_ch)
    channel_id = int(watch_ch.channel_id)
    refresh_in_place = force and not post_new
    had_registry = bool(existing)

    if refresh_in_place and existing and existing.message_id:
        edit_chat = int(existing.watch_channel_id or channel_id)
        updated = await _refresh_catalog_post_in_place(
            bot,
            edit_chat=edit_chat,
            message_id=int(existing.message_id),
            poster=poster,
            caption=caption,
            keyboard=keyboard,
        )
        if updated:
            db.save_watch_catalog_post(
                content_title_id,
                season_number,
                str(channel_id),
                int(existing.message_id),
            )
            return True, "Updated"
        logger.info(
            "catalog post %s refresh failed, reposting",
            existing.message_id,
        )

    try:
        new_mid = await _send_new_catalog_post(
            bot,
            dest=dest,
            poster=poster,
            caption=caption,
            keyboard=keyboard,
        )
        db.save_watch_catalog_post(
            content_title_id,
            season_number,
            str(watch_ch.channel_id),
            new_mid,
        )
        if refresh_in_place and had_registry:
            return True, "Reposted"
        return True, "Published"
    except (BadRequest, TelegramError) as e:
        logger.warning("publish catalog failed: %s", e)
        ra = parse_retry_after_seconds(e)
        if ra is not None:
            return False, f"Flood control exceeded. Retry in {int(ra)} seconds"
        return False, str(e)


async def publish_catalog_batch(
    bot: Bot,
    db: Database,
    *,
    limit: int = 25,
    delay_s: float | None = None,
    bot_username: str | None = None,
    progress_callback=None,
    republish: bool = False,
    post_new: bool = False,
    slots: list[dict] | None = None,
    progress_base: int = 0,
) -> tuple[int, int, list[str], int]:
    """Publish catalog cards.

    republish=True — all library slots. post_new=True — always send new channel posts.
    refresh (republish + not post_new) — edit live posts; repost if message missing.
  Optional ``slots`` — publish this chunk only (used by publish_catalog_all).
    """
    if delay_s is None:
        delay_s = Config.TELEGRAM_PUBLISH_DELAY
    if slots is None:
        if republish:
            slots = db.get_library_catalog_slots(limit=limit)
        else:
            slots = db.get_unpublished_catalog_slots(limit=limit)
    ok = fail = 0
    updated = reposted = published = 0
    errors: list[str] = []
    use_force = republish or post_new
    for i, slot in enumerate(slots):
        success, msg = await publish_catalog_slot(
            bot,
            db,
            slot["content_title_id"],
            slot.get("season_number"),
            bot_username=bot_username,
            force=use_force,
            post_new=post_new,
        )
        if success:
            ok += 1
            if msg == "Updated":
                updated += 1
            elif msg == "Reposted":
                reposted += 1
            elif msg == "Published":
                published += 1
        else:
            fail += 1
            if msg != "Already published":
                errors.append(msg[:100])
        if progress_callback:
            await progress_callback(
                progress_base + i + 1, progress_base + len(slots), ok, fail
            )
        if i + 1 < len(slots):
            extra = 0.0
            if not success:
                ra = parse_retry_after_text(msg)
                if ra is not None:
                    extra = ra + 2.0
            await batch_pause(delay_s + extra)
    stats = {"updated": updated, "reposted": reposted, "published": published}
    return ok, fail, errors, len(slots), stats


_catalog_publish_lock = asyncio.Lock()


def catalog_queue_total(
    db: Database,
    *,
    republish: bool = False,
    post_new: bool = False,
    cap: int | None = None,
) -> int:
    """How many catalog slots will be processed for this publish run."""
    if republish or post_new:
        n = db.count_library_catalog_slots()
    else:
        n = db.count_unpublished_catalog_slots()
    if cap and cap > 0:
        n = min(n, cap)
    return n


async def publish_catalog_all(
    bot: Bot,
    db: Database,
    *,
    batch_size: int | None = None,
    max_total: int | None = None,
    delay_s: float | None = None,
    bot_username: str | None = None,
    progress_callback=None,
    republish: bool = False,
    post_new: bool = False,
) -> tuple[int, int, list[str], int, dict]:
    """
    Publish the full catalog queue in chunks (default 50 cards per chunk).

    Keeps going until no slots remain (new publish) or the library is exhausted
    (republish/refresh). Does not hold the exclusive job lock — caller should
  enqueue with exclusive=False so ingest / other lanes keep running.
    """
    batch_size = batch_size or Config.WATCH_CATALOG_PUBLISH_BATCH_SIZE
    if batch_size < 1:
        batch_size = 50
    cap = (
        max_total
        if max_total is not None
        else Config.WATCH_CATALOG_PUBLISH_MAX_TOTAL
    )

    async with _catalog_publish_lock:
        return await _publish_catalog_all_locked(
            bot,
            db,
            batch_size=batch_size,
            cap=cap,
            delay_s=delay_s,
            bot_username=bot_username,
            progress_callback=progress_callback,
            republish=republish,
            post_new=post_new,
        )


async def _publish_catalog_all_locked(
    bot: Bot,
    db: Database,
    *,
    batch_size: int,
    cap: int,
    delay_s: float | None,
    bot_username: str | None,
    progress_callback,
    republish: bool,
    post_new: bool,
) -> tuple[int, int, list[str], int, dict]:
    total_ok = total_fail = 0
    all_errors: list[str] = []
    queue_total = catalog_queue_total(
        db, republish=republish, post_new=post_new, cap=cap
    )
    agg = {
        "updated": 0,
        "reposted": 0,
        "published": 0,
        "batches": 0,
        "queue_total": queue_total,
    }
    offset = 0

    async def _progress(done: int, _batch_total: int, ok: int, fail: int) -> None:
        if progress_callback:
            await progress_callback(
                done,
                total_ok + ok,
                total_fail + fail,
                agg["batches"] + 1,
                queue_total,
            )

    while True:
        if cap and total_ok + total_fail >= cap:
            break

        chunk_limit = batch_size
        if cap:
            chunk_limit = min(batch_size, cap - total_ok - total_fail)

        if republish or post_new:
            chunk = db.get_library_catalog_slots(limit=chunk_limit, offset=offset)
            offset += len(chunk)
        else:
            chunk = db.get_unpublished_catalog_slots(limit=chunk_limit)

        if not chunk:
            break

        ok, fail, errors, n, stats = await publish_catalog_batch(
            bot,
            db,
            delay_s=delay_s,
            bot_username=bot_username,
            progress_callback=_progress,
            republish=republish,
            post_new=post_new,
            slots=chunk,
            progress_base=total_ok + total_fail,
        )
        total_ok += ok
        total_fail += fail
        all_errors.extend(errors)
        for k in ("updated", "reposted", "published"):
            agg[k] += stats.get(k, 0)
        agg["batches"] += 1

        if n == 0 or n < chunk_limit:
            break

        await asyncio.sleep(1.5)

    return total_ok, total_fail, all_errors[:20], total_ok + total_fail, agg


async def publish_unpublished_catalog_batch(
    bot: Bot,
    db: Database,
    **kwargs,
) -> tuple[int, int, list[str]]:
    ok, fail, errors, _total, _stats = await publish_catalog_batch(bot, db, **kwargs)
    return ok, fail, errors


async def maybe_auto_publish_catalog_for_upload(
    bot: Bot,
    db: Database,
    upload_id: int,
    *,
    library_visible: bool,
    bot_username: str | None = None,
) -> None:
    if not Config.AUTO_PUBLISH_WATCH or not library_visible:
        return
    upload = db.get_file_upload(upload_id)
    if not upload or not upload.content_title_id:
        return
    if not db.is_catalog_publishable(upload.content_title_id):
        return
    ct = db.get_content_title(upload.content_title_id)
    if not ct:
        return
    mt = (ct.media_type or "movie").lower()
    season = None
    if mt in ("tv", "series"):
        season = upload.season_number if upload.season_number is not None else 1
    try:
        await publish_catalog_slot(
            bot,
            db,
            upload.content_title_id,
            season,
            bot_username=bot_username,
        )
    except Exception as e:
        logger.warning("auto catalog publish failed: %s", e)


async def unpublish_catalog_slot(
    bot: Bot,
    db: Database,
    content_title_id: int,
    season_number: int | None,
) -> tuple[bool, str]:
    """Delete Telegram catalog card and remove publish registry."""
    existing = db.get_watch_catalog_post(content_title_id, season_number)
    if not existing:
        return False, "Not published"

    chat = existing.watch_channel_id
    msg_id = existing.message_id
    if chat and msg_id:
        try:
            await bot.delete_message(chat_id=int(chat), message_id=int(msg_id))
        except (BadRequest, TelegramError) as e:
            logger.warning(
                "unpublish delete_message failed ct=%s season=%s: %s",
                content_title_id,
                season_number,
                e,
            )

    if not db.delete_watch_catalog_post(content_title_id, season_number):
        return False, "Failed to remove publish record"
    return True, "Unpublished"
