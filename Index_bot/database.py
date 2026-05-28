"""
Database models and operations for the Index Bot
"""
import json
import logging
import os
from pathlib import Path

from config import Config
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    ForeignKey,
    Text,
    inspect,
    text,
    func,
    and_,
    not_,
    or_,
    case,
)
from sqlalchemy import event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, joinedload, object_session
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

Base = declarative_base()

_FINGERPRINT_BATCH = 400


def _is_sqlite_locked(exc: BaseException) -> bool:
    return "database is locked" in str(exc).lower() or "database is busy" in str(
        exc
    ).lower()


def _sqlite_write_retry(func):
    """Retry commits on SQLITE_BUSY / locked (upload vs ingest overlap)."""

    def wrapper(*args, **kwargs):
        import time

        from sqlalchemy.exc import OperationalError

        last: BaseException | None = None
        for attempt in range(12):
            try:
                return func(*args, **kwargs)
            except OperationalError as e:
                last = e
                if not _is_sqlite_locked(e) or attempt >= 11:
                    raise
                time.sleep(min(2.0, 0.04 * (2**attempt)))
        if last:
            raise last

    return wrapper


class Channel(Base):
    """Stores information about monitored channels"""
    __tablename__ = 'channels'
    
    id = Column(Integer, primary_key=True)
    channel_id = Column(String, unique=True, nullable=False)
    channel_username = Column(String)
    channel_title = Column(String)
    added_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    # Dedicated historical-ingest sink (only one channel should be flagged)
    is_ingest_channel = Column(Boolean, default=False)
    # Public library delivery channel (copies without forward header)
    is_watch_channel = Column(Boolean, default=False)
    # Catalog/delivery channel for a content lane (media, course, archive, shortform)
    watch_for_lane = Column(String, nullable=True)
    # Last successful historical ingest from this channel as source (Telethon forward)
    historical_ingested_at = Column(DateTime, nullable=True)
    last_backfill_import_count = Column(Integer, default=0)
    # Content policy: media | shortform | adult | course | archive
    content_lane = Column(String, default="media", nullable=False)
    admin_only = Column(Boolean, default=False)
    # Bot is admin here and can publish catalog cards / files (distribution target).
    bot_can_post = Column(Boolean, default=False)
    # Poll new posts via Telethon user session when bot is not in the channel.
    telethon_watch_enabled = Column(Boolean, default=False)
    telethon_last_seen_message_id = Column(Integer, nullable=True)
    telethon_last_polled_at = Column(DateTime, nullable=True)
    telethon_last_poll_indexed = Column(Integer, default=0)
    
    # Relationships
    uploads = relationship(
        "FileUpload",
        foreign_keys="FileUpload.channel_id",
        back_populates="channel",
    )


class FileUpload(Base):
    """Stores information about uploaded files"""
    __tablename__ = 'file_uploads'
    
    id = Column(Integer, primary_key=True)
    channel_id = Column(String, ForeignKey('channels.channel_id'), nullable=False)
    message_id = Column(Integer, nullable=False)
    file_name = Column(String, nullable=False)
    file_size = Column(Integer)
    file_id = Column(String)  # Telegram file_id for downloading
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    
    # Parsed information
    parsed_name = Column(String)  # Extracted movie/series name
    confirmed_name = Column(String)  # Admin-confirmed name
    is_confirmed = Column(Boolean, default=False)
    needs_confirmation = Column(Boolean, default=False)
    # Shown in Browse / Full library only after TMDB link or admin custom title
    library_visible = Column(Boolean, default=False)
    # Original channel when post is a forward into the ingest channel (backfill)
    source_channel_id = Column(String, ForeignKey("channels.channel_id"), nullable=True)
    # Canonical title for grouping (movies + TV shows)
    content_title_id = Column(Integer, ForeignKey("movie_series.id"), nullable=True)
    # TV episode fields (null for movies)
    season_number = Column(Integer, nullable=True)
    episode_number = Column(Integer, nullable=True)
    episode_title = Column(String, nullable=True)
    # Post still exists in channel (False = deleted); NULL = not checked yet
    message_available = Column(Boolean, nullable=True)
    message_checked_at = Column(DateTime, nullable=True)
    # Copy posted to watch channel (no forward attribution)
    watch_channel_id = Column(String, ForeignKey("channels.channel_id"), nullable=True)
    watch_message_id = Column(Integer, nullable=True)
    # Push to end of Pending list until mapped (Skip for now)
    pending_deferred_at = Column(DateTime, nullable=True)
    # Upload pipeline
    content_fingerprint = Column(String, index=True, nullable=True)
    file_unique_id = Column(String, nullable=True)
    file_kind = Column(String, default="video", nullable=False)
    content_lane = Column(String, default="media", nullable=False)
    ingest_state = Column(String, default="normal", nullable=False)  # normal | duplicate_hold | skipped
    duplicate_of_upload_id = Column(Integer, ForeignKey("file_uploads.id"), nullable=True)
    upload_job_item_id = Column(Integer, ForeignKey("upload_job_items.id"), nullable=True)
    module_name = Column(String, nullable=True)
    lesson_sequence = Column(Integer, nullable=True)
    # Admin approved for public browse / watch delivery
    distribution_approved = Column(Boolean, default=False, nullable=False)
    # Rate-limited TMDB retry queue (transient API / network errors)
    tmdb_retry_after = Column(DateTime, nullable=True)
    tmdb_retry_count = Column(Integer, default=0, nullable=False)
    # Mixed ingest → bucket routing (Telethon forward to pipeline source channel)
    pipeline_route_status = Column(String, nullable=True)  # pending | routed | failed | skipped
    pipeline_route_target_channel_id = Column(String, nullable=True)
    pipeline_route_error = Column(String, nullable=True)
    
    # Relationships
    content_title = relationship("MovieSeries", foreign_keys=[content_title_id])
    channel = relationship(
        "Channel",
        foreign_keys=[channel_id],
        back_populates="uploads",
    )
    source_channel = relationship(
        "Channel",
        foreign_keys=[source_channel_id],
    )


class MovieSeries(Base):
    """
    Canonical library title — one row per movie or per TV series (not per episode).

    Movies: tmdb_title + optional franchise_sequence for sequels.
    TV: show-level row; episodes live on FileUpload (season/episode/episode_title).
    """
    __tablename__ = "movie_series"
    
    id = Column(Integer, primary_key=True)
    media_type = Column(String, nullable=False, default="movie")  # movie | tv
    name = Column(String, nullable=False)  # Parsed / local display name
    tmdb_id = Column(Integer, nullable=True)
    tmdb_title = Column(String, nullable=True)  # Official TMDB title for grouping
    release_year = Column(Integer, nullable=True)
    franchise_sequence = Column(Integer, nullable=True)  # Sequel / franchise index (movies)
    poster_path = Column(String, nullable=True)
    overview = Column(Text, nullable=True)
    vote_average = Column(String, nullable=True)
    genres = Column(Text, nullable=True)  # JSON array of genre names
    # Reels, lectures, images, etc. — in library but never watch-channel poster cards
    catalog_excluded = Column(Boolean, default=False, nullable=False)
    # Set only via Skip catalog — admin Non-catalog library browse
    indexed_only = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    uploads = relationship(
        "FileUpload",
        foreign_keys="FileUpload.content_title_id",
        back_populates="content_title",
    )


class TitleMappingHint(Base):
    """Remember TMDB picks per show/movie prefix to speed up bulk pending work."""
    __tablename__ = "title_mapping_hints"

    id = Column(Integer, primary_key=True)
    match_key = Column(String, unique=True, nullable=False)
    tmdb_id = Column(Integer, nullable=True)
    tmdb_title = Column(String, nullable=True)
    media_type = Column(String, nullable=False, default="tv")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FilenameStripRule(Base):
    """Leading strings to remove from filenames before title / TMDB parsing."""
    __tablename__ = "filename_strip_rules"

    id = Column(Integer, primary_key=True)
    pattern = Column(String, nullable=False)
    note = Column(String, nullable=True)
    is_regex = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class CustomList(Base):
    """Stores custom lists of channels for filtering"""
    __tablename__ = 'custom_lists'
    
    id = Column(Integer, primary_key=True)
    list_name = Column(String, nullable=False)
    created_by = Column(Integer)  # User ID who created the list
    created_at = Column(DateTime, default=datetime.utcnow)
    is_default = Column(Boolean, default=False)  # Default "All Channels" list
    
    # Store channel IDs as comma-separated string
    # Format: "channel_id1,channel_id2,channel_id3"
    channel_ids = Column(Text, nullable=False)


class UserFavorite(Base):
    """User-starred library titles."""
    __tablename__ = "user_favorites"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    content_title_id = Column(Integer, ForeignKey("movie_series.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserWatchlist(Base):
    __tablename__ = "user_watchlists"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    list_name = Column(String, nullable=False, default="My watchlist")
    created_at = Column(DateTime, default=datetime.utcnow)


class UserWatchlistItem(Base):
    __tablename__ = "user_watchlist_items"

    id = Column(Integer, primary_key=True)
    watchlist_id = Column(Integer, ForeignKey("user_watchlists.id"), nullable=False)
    content_title_id = Column(Integer, ForeignKey("movie_series.id"), nullable=False)
    watched = Column(Boolean, default=False, nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow)


class WatchCatalogPost(Base):
    """One poster card per movie or TV season in the watch channel."""
    __tablename__ = "watch_catalog_posts"

    id = Column(Integer, primary_key=True)
    content_title_id = Column(Integer, ForeignKey("movie_series.id"), nullable=False)
    season_number = Column(Integer, nullable=True)  # NULL = movie / whole title
    watch_channel_id = Column(String, ForeignKey("channels.channel_id"), nullable=False)
    message_id = Column(Integer, nullable=False)
    published_at = Column(DateTime, default=datetime.utcnow)


class BotUser(Base):
    """Telegram users who have used the bot (one-time welcome tracking)."""
    __tablename__ = "bot_users"

    user_id = Column(Integer, primary_key=True)
    welcomed_at = Column(DateTime, default=datetime.utcnow)


class PortalSession(Base):
    """Web watch portal login token (issued by /portal in Telegram)."""
    __tablename__ = "portal_sessions"

    token = Column(String, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


class UploadRequest(Base):
    """User-requested titles to upload (TMDB pick)."""
    __tablename__ = "upload_requests"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    tmdb_id = Column(Integer, nullable=True)
    media_type = Column(String, nullable=False, default="movie")
    tmdb_title = Column(String, nullable=False)
    release_year = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending | done | rejected
    created_at = Column(DateTime, default=datetime.utcnow)


class UploadJob(Base):
    """Bulk upload plan (courses, archives)."""
    __tablename__ = "upload_jobs"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    target_channel_id = Column(String, ForeignKey("channels.channel_id"), nullable=True)
    content_lane = Column(String, default="course", nullable=False)
    course_title = Column(String, nullable=True)
    status = Column(String, default="draft", nullable=False)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    notes = Column(Text, nullable=True)

    items = relationship("UploadJobItem", back_populates="job", cascade="all, delete-orphan")


class UploadJobItem(Base):
    """One file in an upload job plan."""
    __tablename__ = "upload_job_items"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("upload_jobs.id"), nullable=False, index=True)
    sequence = Column(Integer, default=0, nullable=False)
    module = Column(String, nullable=True)
    lesson_title = Column(String, nullable=True)
    file_name = Column(String, nullable=False)
    local_path = Column(Text, nullable=True)
    file_size = Column(Integer, nullable=True)
    content_fingerprint = Column(String, index=True, nullable=True)
    duplicate_of_upload_id = Column(Integer, ForeignKey("file_uploads.id"), nullable=True)
    decision = Column(String, default="pending", nullable=False)  # pending | skip | upload | force
    item_status = Column(String, default="planned", nullable=False)  # planned | uploaded | indexed | failed
    upload_id = Column(Integer, ForeignKey("file_uploads.id"), nullable=True)
    telegram_message_id = Column(Integer, nullable=True)
    error_message = Column(String, nullable=True)

    job = relationship("UploadJob", back_populates="items")


class PipelineUploadDefault(Base):
    """Per upload-type default source channel for Telethon upload jobs."""

    __tablename__ = "pipeline_upload_defaults"

    upload_type = Column(String, primary_key=True)
    source_channel_id = Column(String, ForeignKey("channels.channel_id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Database:
    """Database operations"""
    
    def __init__(self, db_path=None):
        """
        If DATABASE_URL is set in the environment (see Config), use PostgreSQL or any
        SQLAlchemy-supported URL. Otherwise use SQLite at db_path (default: Config.DB_PATH).
        """
        if db_path is None:
            db_path = Config.DB_PATH
        url = Config.DATABASE_URL
        if not url:
            url = f'sqlite:///{db_path}'

        engine_kwargs: dict = {"echo": False}
        if url.startswith("sqlite"):
            # SQLite is single-writer; enable WAL + busy timeout to reduce "database is locked".
            try:
                timeout_s = float(os.getenv("SQLITE_BUSY_TIMEOUT_S", "30").strip() or "30")
            except ValueError:
                timeout_s = 30.0
            engine_kwargs["connect_args"] = {
                "check_same_thread": False,
                "timeout": max(1.0, timeout_s),
            }
        else:
            engine_kwargs["pool_pre_ping"] = True
            try:
                engine_kwargs["pool_size"] = max(
                    1, int(os.getenv("DB_POOL_SIZE", "5").strip() or "5")
                )
                engine_kwargs["max_overflow"] = max(
                    0, int(os.getenv("DB_MAX_OVERFLOW", "10").strip() or "10")
                )
            except ValueError:
                engine_kwargs["pool_size"] = 5
                engine_kwargs["max_overflow"] = 10

        self.engine = create_engine(url, **engine_kwargs)
        if self.engine.dialect.name == "sqlite":
            try:
                self._configure_sqlite()
            except Exception as e:
                logger.warning("SQLite PRAGMA setup skipped: %s", e)
        Base.metadata.create_all(self.engine)
        self._migrate_channels_schema()
        self._migrate_file_uploads_schema()
        self._migrate_movie_series_schema()
        self._migrate_user_watchlist_schema()
        self._migrate_upload_pipeline_schema()
        self._migrate_portal_schema()
        self.Session = sessionmaker(bind=self.engine)
        try:
            self._backfill_bot_can_post()
        except Exception as e:
            logger.warning("bot_can_post backfill skipped: %s", e)
        # Create default "All Channels" list if it doesn't exist
        self._ensure_default_list()

    def _configure_sqlite(self) -> None:
        """Configure SQLite for better concurrency and fewer lock errors."""

        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):
            cur = dbapi_connection.cursor()
            try:
                # WAL allows concurrent readers during writes.
                cur.execute("PRAGMA journal_mode=WAL;")
                # Good trade-off for WAL workloads.
                cur.execute("PRAGMA synchronous=NORMAL;")
                # Busy timeout so writers wait instead of immediately failing.
                try:
                    timeout_ms = int(float(os.getenv("SQLITE_BUSY_TIMEOUT_S", "30")) * 1000)
                except ValueError:
                    timeout_ms = 30000
                cur.execute(f"PRAGMA busy_timeout={max(1000, timeout_ms)};")
                # Reduce fsync frequency, helps contention on some disks.
                cur.execute("PRAGMA wal_autocheckpoint=1000;")
            finally:
                cur.close()
    
    def _migrate_channels_schema(self):
        """Add columns to existing DBs without Alembic."""
        try:
            insp = inspect(self.engine)
            if "channels" not in insp.get_table_names():
                return
            col_names = {c["name"] for c in insp.get_columns("channels")}
            if "is_ingest_channel" not in col_names:
                if self.engine.dialect.name == "sqlite":
                    ddl = (
                        "ALTER TABLE channels ADD COLUMN is_ingest_channel "
                        "BOOLEAN DEFAULT 0"
                    )
                else:
                    ddl = (
                        "ALTER TABLE channels ADD COLUMN is_ingest_channel "
                        "BOOLEAN DEFAULT FALSE"
                    )
                with self.engine.begin() as conn:
                    conn.execute(text(ddl))
                logger.info("Migrated channels table: added is_ingest_channel")
            if "is_watch_channel" not in col_names:
                if self.engine.dialect.name == "sqlite":
                    ddl = (
                        "ALTER TABLE channels ADD COLUMN is_watch_channel "
                        "BOOLEAN DEFAULT 0"
                    )
                else:
                    ddl = (
                        "ALTER TABLE channels ADD COLUMN is_watch_channel "
                        "BOOLEAN DEFAULT FALSE"
                    )
                with self.engine.begin() as conn:
                    conn.execute(text(ddl))
                logger.info("Migrated channels table: added is_watch_channel")
            if "historical_ingested_at" not in col_names:
                with self.engine.begin() as conn:
                    conn.execute(
                        text("ALTER TABLE channels ADD COLUMN historical_ingested_at DATETIME")
                    )
                logger.info("Migrated channels table: added historical_ingested_at")
            if "last_backfill_import_count" not in col_names:
                ddl = (
                    "ALTER TABLE channels ADD COLUMN last_backfill_import_count "
                    "INTEGER DEFAULT 0"
                )
                with self.engine.begin() as conn:
                    conn.execute(text(ddl))
                logger.info("Migrated channels table: added last_backfill_import_count")
            bool_def = "BOOLEAN DEFAULT 0" if self.engine.dialect.name == "sqlite" else "BOOLEAN DEFAULT FALSE"
            if "telethon_watch_enabled" not in col_names:
                with self.engine.begin() as conn:
                    conn.execute(
                        text(
                            f"ALTER TABLE channels ADD COLUMN telethon_watch_enabled {bool_def}"
                        )
                    )
                logger.info("Migrated channels table: added telethon_watch_enabled")
            if "telethon_last_seen_message_id" not in col_names:
                with self.engine.begin() as conn:
                    conn.execute(
                        text(
                            "ALTER TABLE channels ADD COLUMN telethon_last_seen_message_id INTEGER"
                        )
                    )
                logger.info(
                    "Migrated channels table: added telethon_last_seen_message_id"
                )
                with self.engine.begin() as conn:
                    conn.execute(
                        text(
                            "UPDATE channels SET telethon_watch_enabled = 1 "
                            "WHERE COALESCE(is_ingest_channel, 0) = 0 "
                            "AND COALESCE(bot_can_post, 0) = 0"
                        )
                    )
            if "telethon_last_polled_at" not in col_names:
                with self.engine.begin() as conn:
                    conn.execute(
                        text("ALTER TABLE channels ADD COLUMN telethon_last_polled_at DATETIME")
                    )
                logger.info("Migrated channels table: added telethon_last_polled_at")
            if "telethon_last_poll_indexed" not in col_names:
                with self.engine.begin() as conn:
                    conn.execute(
                        text(
                            "ALTER TABLE channels ADD COLUMN telethon_last_poll_indexed "
                            "INTEGER DEFAULT 0"
                        )
                    )
                logger.info("Migrated channels table: added telethon_last_poll_indexed")
        except Exception as e:
            logger.warning(f"Channel schema migration skipped: {e}")

    @staticmethod
    def _sync_telethon_watch_on_channel(channel, *, bot_can_post: bool) -> None:
        if getattr(channel, "is_ingest_channel", False):
            channel.telethon_watch_enabled = False
        elif bot_can_post:
            channel.telethon_watch_enabled = False
        else:
            channel.telethon_watch_enabled = True

    def get_channel_monitoring_overview(self) -> dict:
        """Admin portal: bot-indexed vs Telethon member-watch channels."""
        from sqlalchemy import func

        session = self.get_session()
        try:
            upload_rows = (
                session.query(
                    FileUpload.channel_id,
                    func.count(FileUpload.id).label("cnt"),
                    func.max(FileUpload.uploaded_at).label("last_at"),
                )
                .filter(FileUpload.ingest_state != "skipped")
                .filter(self._subtitle_exclusion_filter())
                .group_by(FileUpload.channel_id)
                .all()
            )
            live_by_cid: dict[str, tuple[int, datetime | None]] = {}
            for r in upload_rows:
                if r.channel_id:
                    live_by_cid[str(r.channel_id)] = (
                        int(r.cnt or 0),
                        r.last_at,
                    )

            source_rows = (
                session.query(
                    FileUpload.source_channel_id,
                    func.count(FileUpload.id).label("cnt"),
                    func.max(FileUpload.uploaded_at).label("last_at"),
                )
                .filter(FileUpload.source_channel_id.isnot(None))
                .filter(FileUpload.ingest_state != "skipped")
                .filter(self._subtitle_exclusion_filter())
                .group_by(FileUpload.source_channel_id)
                .all()
            )
            source_by_cid: dict[str, tuple[int, datetime | None]] = {}
            for r in source_rows:
                if r.source_channel_id:
                    source_by_cid[str(r.source_channel_id)] = (
                        int(r.cnt or 0),
                        r.last_at,
                    )

            def _iso(dt: datetime | None) -> str | None:
                if not dt:
                    return None
                return dt.replace(microsecond=0).isoformat() + "Z"

            def _row(ch, *, mode: str) -> dict:
                cid = str(ch.channel_id)
                live_cnt, live_last = live_by_cid.get(cid, (0, None))
                src_cnt, src_last = source_by_cid.get(cid, (0, None))
                last_indexed = live_last
                if src_last and (not last_indexed or src_last > last_indexed):
                    last_indexed = src_last
                return {
                    "channel_id": cid,
                    "title": ch.channel_title or cid,
                    "username": ch.channel_username,
                    "content_lane": ch.content_lane or "media",
                    "mode": mode,
                    "is_active": bool(ch.is_active),
                    "bot_can_post": bool(ch.bot_can_post),
                    "telethon_watch": bool(ch.telethon_watch_enabled),
                    "indexed_count": live_cnt,
                    "backfill_count": int(ch.last_backfill_import_count or 0),
                    "last_indexed_at": _iso(last_indexed),
                    "last_backfill_at": _iso(ch.historical_ingested_at),
                    "last_pull_at": _iso(getattr(ch, "telethon_last_polled_at", None)),
                    "last_pull_indexed": int(getattr(ch, "telethon_last_poll_indexed", 0) or 0),
                    "last_seen_message_id": getattr(ch, "telethon_last_seen_message_id", None),
                    "is_ingest_sink": bool(ch.is_ingest_channel),
                }

            channels = (
                session.query(Channel).order_by(Channel.channel_title.asc()).all()
            )
            bot_indexed: list[dict] = []
            member_watch: list[dict] = []
            ingest_sinks: list[dict] = []
            for ch in channels:
                if getattr(ch, "is_ingest_channel", False):
                    ingest_sinks.append(_row(ch, mode="ingest_sink"))
                    continue
                if (
                    getattr(ch, "telethon_watch_enabled", False)
                    and not getattr(ch, "bot_can_post", False)
                ):
                    member_watch.append(_row(ch, mode="telethon_poll"))
                if getattr(ch, "bot_can_post", False) or live_by_cid.get(
                    str(ch.channel_id), (0, None)
                )[0] > 0:
                    bot_indexed.append(_row(ch, mode="bot_live"))

            return {
                "bot_indexed": bot_indexed,
                "member_watch": member_watch,
                "ingest_sinks": ingest_sinks,
            }
        finally:
            session.close()

    def list_telethon_watch_channels(self) -> list:
        """Active sources where the bot is not admin — polled via Telethon."""
        session = self.get_session()
        try:
            rows = (
                session.query(Channel)
                .filter(
                    Channel.is_active.is_(True),
                    Channel.is_ingest_channel.is_(False),
                    Channel.telethon_watch_enabled.is_(True),
                    Channel.bot_can_post.is_(False),
                )
                .all()
            )
            return [self._channel_for_return(session, r) for r in rows]
        finally:
            session.close()

    def set_telethon_poll_result(
        self,
        channel_id: str,
        *,
        last_seen_message_id: int | None = None,
        indexed_count: int = 0,
    ) -> None:
        session = self.get_session()
        try:
            ch = session.query(Channel).filter_by(channel_id=str(channel_id)).first()
            if not ch:
                return
            ch.telethon_last_polled_at = datetime.utcnow()
            ch.telethon_last_poll_indexed = int(indexed_count)
            if last_seen_message_id is not None:
                ch.telethon_last_seen_message_id = int(last_seen_message_id)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("set_telethon_poll_result failed: %s", e)
        finally:
            session.close()

    def set_telethon_last_seen_message_id(
        self, channel_id: str, message_id: int
    ) -> None:
        session = self.get_session()
        try:
            ch = session.query(Channel).filter_by(channel_id=str(channel_id)).first()
            if not ch:
                return
            ch.telethon_last_seen_message_id = int(message_id)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("set_telethon_last_seen_message_id failed: %s", e)
        finally:
            session.close()

    def set_telethon_watch_enabled(
        self, channel_id: str, enabled: bool
    ) -> None:
        session = self.get_session()
        try:
            ch = session.query(Channel).filter_by(channel_id=str(channel_id)).first()
            if not ch:
                return
            ch.telethon_watch_enabled = bool(enabled)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("set_telethon_watch_enabled failed: %s", e)
        finally:
            session.close()

    def get_channel_index_stats(self) -> dict[str, dict[str, int]]:
        """
        Per-channel counts for list badges.

        Returns {channel_id: {live, backfill}} where
        live = posts indexed in the channel; backfill = files attributed as source archive.
        """
        from sqlalchemy import func

        session = self.get_session()
        try:
            live_rows = (
                session.query(FileUpload.channel_id, func.count(FileUpload.id))
                .filter(self._subtitle_exclusion_filter())
                .group_by(FileUpload.channel_id)
                .all()
            )
            backfill_rows = (
                session.query(FileUpload.source_channel_id, func.count(FileUpload.id))
                .filter(FileUpload.source_channel_id.isnot(None))
                .filter(self._subtitle_exclusion_filter())
                .group_by(FileUpload.source_channel_id)
                .all()
            )
            out: dict[str, dict[str, int]] = {}
            for cid, n in live_rows:
                if cid:
                    out.setdefault(str(cid), {"live": 0, "backfill": 0})["live"] = int(n)
            for cid, n in backfill_rows:
                if cid:
                    out.setdefault(str(cid), {"live": 0, "backfill": 0})["backfill"] = int(
                        n
                    )
            return out
        finally:
            session.close()

    def mark_channel_historical_ingest(
        self,
        channel_id: str,
        *,
        imported_count: int = 0,
    ) -> None:
        """Record that a historical ingest run completed for this source channel."""
        session = self.get_session()
        try:
            channel = (
                session.query(Channel).filter_by(channel_id=str(channel_id)).first()
            )
            if not channel:
                return
            channel.historical_ingested_at = datetime.utcnow()
            channel.last_backfill_import_count = int(imported_count)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("mark_channel_historical_ingest failed: %s", e)
        finally:
            session.close()

    def _migrate_file_uploads_schema(self):
        """Add source_channel_id and remove subtitle-only rows from counts."""
        try:
            from media_utils import SUBTITLE_EXTENSIONS

            insp = inspect(self.engine)
            if "file_uploads" not in insp.get_table_names():
                return
            col_names = {c["name"] for c in insp.get_columns("file_uploads")}
            if "source_channel_id" not in col_names:
                with self.engine.begin() as conn:
                    conn.execute(
                        text(
                            "ALTER TABLE file_uploads ADD COLUMN source_channel_id VARCHAR"
                        )
                    )
                logger.info("Migrated file_uploads: added source_channel_id")

            # Drop previously indexed subtitle files
            with self.engine.begin() as conn:
                for ext in SUBTITLE_EXTENSIONS:
                    conn.execute(
                        text(
                            "DELETE FROM file_uploads WHERE lower(file_name) LIKE :pat"
                        ),
                        {"pat": f"%{ext}"},
                    )
        except Exception as e:
            logger.warning(f"File uploads schema migration skipped: {e}")

    def _migrate_movie_series_schema(self):
        """Expand movie_series + file_uploads for TMDB grouping and TV episodes."""
        try:
            insp = inspect(self.engine)
            if "movie_series" in insp.get_table_names():
                cols = {c["name"] for c in insp.get_columns("movie_series")}
                additions = {
                    "tmdb_title": "VARCHAR",
                    "release_year": "INTEGER",
                    "franchise_sequence": "INTEGER",
                    "poster_path": "VARCHAR",
                    "overview": "TEXT",
                    "vote_average": "VARCHAR",
                    "genres": "TEXT",
                    "updated_at": "DATETIME",
                    "catalog_excluded": "BOOLEAN DEFAULT 0",
                    "indexed_only": "BOOLEAN DEFAULT 0",
                }
                for col, sql_type in additions.items():
                    if col not in cols:
                        with self.engine.begin() as conn:
                            conn.execute(
                                text(f"ALTER TABLE movie_series ADD COLUMN {col} {sql_type}")
                            )
                        logger.info("Migrated movie_series: added %s", col)
                if "media_type" not in cols:
                    with self.engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE movie_series ADD COLUMN media_type VARCHAR "
                                "DEFAULT 'movie'"
                            )
                        )

            if "file_uploads" in insp.get_table_names():
                fcols = {c["name"] for c in insp.get_columns("file_uploads")}
                for col, sql_type in {
                    "content_title_id": "INTEGER",
                    "season_number": "INTEGER",
                    "episode_number": "INTEGER",
                    "episode_title": "VARCHAR",
                    "library_visible": "BOOLEAN DEFAULT 0",
                    "message_available": "BOOLEAN",
                    "message_checked_at": "DATETIME",
                    "watch_channel_id": "VARCHAR",
                    "watch_message_id": "INTEGER",
                    "pending_deferred_at": "DATETIME",
                }.items():
                    if col not in fcols:
                        with self.engine.begin() as conn:
                            if self.engine.dialect.name == "sqlite" and "BOOLEAN" in sql_type:
                                conn.execute(
                                    text(
                                        f"ALTER TABLE file_uploads ADD COLUMN {col} "
                                        f"{sql_type.replace('BOOLEAN', 'INTEGER')}"
                                    )
                                )
                            else:
                                conn.execute(
                                    text(f"ALTER TABLE file_uploads ADD COLUMN {col} {sql_type}")
                                )
                        logger.info("Migrated file_uploads: added %s", col)

                fcols = {c["name"] for c in insp.get_columns("file_uploads")}
                if "library_visible" in fcols:
                    with self.engine.begin() as conn:
                        library_true = (
                            "1" if self.engine.dialect.name == "sqlite" else "TRUE"
                        )
                        confirmed_cond = (
                            "is_confirmed = 1"
                            if self.engine.dialect.name == "sqlite"
                            else "is_confirmed IS TRUE"
                        )
                        conn.execute(
                            text(
                                """
                                UPDATE file_uploads
                                SET library_visible = {library_true}
                                WHERE {confirmed_cond}
                                  AND content_title_id IN (
                                    SELECT id FROM movie_series WHERE tmdb_id IS NOT NULL
                                  )
                                """.format(
                                    confirmed_cond=confirmed_cond,
                                    library_true=library_true,
                                )
                            )
                        )
        except Exception as e:
            logger.warning(f"Movie series schema migration skipped: {e}")

    def _migrate_user_watchlist_schema(self):
        """Add watched flag to watchlist items."""
        try:
            insp = inspect(self.engine)
            if "user_watchlist_items" not in insp.get_table_names():
                return
            col_names = {c["name"] for c in insp.get_columns("user_watchlist_items")}
            if "watched" not in col_names:
                if self.engine.dialect.name == "sqlite":
                    ddl = (
                        "ALTER TABLE user_watchlist_items ADD COLUMN watched "
                        "BOOLEAN DEFAULT 0 NOT NULL"
                    )
                else:
                    ddl = (
                        "ALTER TABLE user_watchlist_items ADD COLUMN watched "
                        "BOOLEAN DEFAULT FALSE NOT NULL"
                    )
                with self.engine.begin() as conn:
                    conn.execute(text(ddl))
                logger.info("Migrated user_watchlist_items: added watched")
        except Exception as e:
            logger.warning("User watchlist schema migration skipped: %s", e)

    def _migrate_upload_pipeline_schema(self):
        """Content lanes, fingerprints, upload jobs."""
        try:
            insp = inspect(self.engine)
            dialect = self.engine.dialect.name
            bool_type = "BOOLEAN DEFAULT 0" if dialect == "sqlite" else "BOOLEAN DEFAULT FALSE"

            if "channels" in insp.get_table_names():
                cols = {c["name"] for c in insp.get_columns("channels")}
                for col, sql in {
                    "content_lane": "VARCHAR DEFAULT 'media'",
                    "admin_only": bool_type,
                    "watch_for_lane": "VARCHAR",
                    "bot_can_post": bool_type,
                }.items():
                    if col not in cols:
                        with self.engine.begin() as conn:
                            conn.execute(text(f"ALTER TABLE channels ADD COLUMN {col} {sql}"))
                        logger.info("Migrated channels: added %s", col)

            if "file_uploads" in insp.get_table_names():
                fcols = {c["name"] for c in insp.get_columns("file_uploads")}
                additions = {
                    "content_fingerprint": "VARCHAR",
                    "file_unique_id": "VARCHAR",
                    "file_kind": "VARCHAR DEFAULT 'video'",
                    "content_lane": "VARCHAR DEFAULT 'media'",
                    "ingest_state": "VARCHAR DEFAULT 'normal'",
                    "duplicate_of_upload_id": "INTEGER",
                    "upload_job_item_id": "INTEGER",
                    "module_name": "VARCHAR",
                    "lesson_sequence": "INTEGER",
                    "distribution_approved": "BOOLEAN DEFAULT 0",
                    "tmdb_retry_after": "DATETIME",
                    "tmdb_retry_count": "INTEGER DEFAULT 0",
                    "pipeline_route_status": "VARCHAR",
                    "pipeline_route_target_channel_id": "VARCHAR",
                    "pipeline_route_error": "VARCHAR",
                }
                for col, sql_type in additions.items():
                    if col not in fcols:
                        with self.engine.begin() as conn:
                            conn.execute(
                                text(f"ALTER TABLE file_uploads ADD COLUMN {col} {sql_type}")
                            )
                        logger.info("Migrated file_uploads: added %s", col)

            if "pipeline_upload_defaults" not in insp.get_table_names():
                Base.metadata.create_all(
                    self.engine, tables=[PipelineUploadDefault.__table__]
                )
                logger.info("Created pipeline_upload_defaults table")
        except Exception as e:
            logger.warning("Upload pipeline schema migration skipped: %s", e)

    def _migrate_portal_schema(self):
        """Watch portal web sessions (create_all handles new installs)."""
        try:
            Base.metadata.create_all(self.engine, tables=[PortalSession.__table__])
        except Exception as e:
            logger.warning("Portal schema migration skipped: %s", e)

    def _backfill_bot_can_post(self):
        """Mark channels where the bot already posts or is configured for distribution."""
        session = self.get_session()
        try:
            from sqlalchemy import or_

            session.query(Channel).filter(
                or_(
                    Channel.is_ingest_channel.is_(True),
                    Channel.is_watch_channel.is_(True),
                    Channel.watch_for_lane.isnot(None),
                )
            ).update({Channel.bot_can_post: True}, synchronize_session=False)

            direct_ids = {
                row[0]
                for row in session.query(FileUpload.channel_id)
                .filter(FileUpload.channel_id.isnot(None))
                .distinct()
            }
            if direct_ids:
                session.query(Channel).filter(Channel.channel_id.in_(direct_ids)).update(
                    {Channel.bot_can_post: True}, synchronize_session=False
                )
            session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("bot_can_post backfill skipped: %s", e)
        finally:
            session.close()

    @staticmethod
    def _subtitle_exclusion_filter():
        """SQLAlchemy filter: ignore subtitle sidecar files."""
        from media_utils import SUBTITLE_EXTENSIONS

        return and_(*[not_(FileUpload.file_name.ilike(f"%{ext}")) for ext in SUBTITLE_EXTENSIONS])

    @staticmethod
    def _tmdb_pending_filter():
        """Pending list / TMDB retry: video & audio only — not images or GIFs."""
        return and_(
            Database._subtitle_exclusion_filter(),
            not_(FileUpload.file_kind.in_(("image", "gif"))),
        )

    @staticmethod
    def _library_visible_filter():
        """Only titles approved for public library browse (TMDB or custom name)."""
        return FileUpload.library_visible.is_(True)

    @staticmethod
    def _public_library_filter():
        """User-facing browse/search: no adult; non-media needs distribution approval."""
        from content_lanes import LANE_ADULT, LANE_MEDIA

        return and_(
            FileUpload.library_visible.is_(True),
            FileUpload.content_lane != LANE_ADULT,
            or_(
                FileUpload.content_lane == LANE_MEDIA,
                FileUpload.distribution_approved.is_(True),
            ),
        )

    @staticmethod
    def _media_browse_filter():
        """Movies & series only — excludes courses and other lanes."""
        from content_lanes import LANE_ADULT, LANE_MEDIA

        return and_(
            FileUpload.library_visible.is_(True),
            FileUpload.content_lane == LANE_MEDIA,
            FileUpload.content_lane != LANE_ADULT,
        )

    @staticmethod
    def _course_library_filter():
        """Published courses only (distribution approved)."""
        from content_lanes import LANE_ADULT, LANE_COURSE

        return and_(
            FileUpload.library_visible.is_(True),
            FileUpload.content_lane != LANE_ADULT,
            FileUpload.distribution_approved.is_(True),
            or_(
                FileUpload.content_lane == LANE_COURSE,
                func.lower(MovieSeries.media_type) == "course",
            ),
        )

    @staticmethod
    def _adult_library_filter():
        """Admin adult vault browse — lane adult (includes non–library-visible files)."""
        from content_lanes import LANE_ADULT

        return and_(
            FileUpload.content_lane == LANE_ADULT,
            FileUpload.ingest_state != "skipped",
        )

    @staticmethod
    def _archive_library_filter():
        from content_lanes import LANE_ARCHIVE

        return and_(
            FileUpload.content_lane == LANE_ARCHIVE,
            FileUpload.ingest_state != "skipped",
        )

    @staticmethod
    def _shortform_library_filter():
        from content_lanes import LANE_SHORTFORM

        return and_(
            FileUpload.content_lane == LANE_SHORTFORM,
            FileUpload.ingest_state != "skipped",
        )

    @staticmethod
    def _non_catalog_browse_filter():
        """Admin browse — titles explicitly marked Skip catalog (indexed_only)."""
        return and_(
            MovieSeries.indexed_only.is_(True),
            FileUpload.is_confirmed.is_(True),
            or_(
                FileUpload.ingest_state.is_(None),
                FileUpload.ingest_state != "skipped",
            ),
        )

    def _library_access_filter(self, *, public: bool = True):
        return self._public_library_filter() if public else self._library_visible_filter()

    def is_upload_publicly_accessible(self, upload) -> bool:
        """Whether a non-admin user may open this file via deep link or browse."""
        from content_lanes import LANE_ADULT, LANE_MEDIA, normalize_lane

        if not upload or not upload.library_visible:
            return False
        lane = normalize_lane(upload.content_lane)
        if lane == LANE_ADULT:
            return False
        if lane == LANE_MEDIA:
            return True
        return bool(upload.distribution_approved)

    def is_upload_accessible_for_user(self, upload, user_id: int | None) -> bool:
        """Public library rules, or admin access to adult-vault files."""
        from content_lanes import LANE_ADULT, normalize_lane
        from config import Config

        if not upload:
            return False
        if user_id and Config.is_admin(user_id):
            if (upload.ingest_state or "") == "skipped":
                return False
            if upload.needs_confirmation and not upload.is_confirmed:
                return True
            if normalize_lane(upload.content_lane) == LANE_ADULT:
                return True
            if upload.is_confirmed and upload.content_title_id:
                ct = self.get_content_title(upload.content_title_id)
                if ct and bool(getattr(ct, "indexed_only", False)):
                    return True
        return self.is_upload_publicly_accessible(upload)

    @staticmethod
    def _vault_lane_filter(lane: str):
        from content_lanes import normalize_lane

        return and_(
            FileUpload.content_lane == normalize_lane(lane),
            FileUpload.ingest_state != "skipped",
        )

    def _movie_name_filter(self, movie_name: str, session=None):
        """Match files by parsed name or linked content title."""
        clauses = [
            ((FileUpload.confirmed_name == movie_name) & (FileUpload.is_confirmed == True)),
            (FileUpload.parsed_name == movie_name),
        ]
        own_session = session is None
        if own_session:
            session = self.get_session()
        try:
            ct_ids = [
                r[0]
                for r in session.query(MovieSeries.id)
                .filter(
                    (MovieSeries.tmdb_title == movie_name) | (MovieSeries.name == movie_name)
                )
                .all()
            ]
            if ct_ids:
                clauses.append(FileUpload.content_title_id.in_(ct_ids))
        finally:
            if own_session:
                session.close()
        return or_(*clauses)

    def _build_channel_stats(self, uploads) -> dict:
        """Group uploads by source archive when set, else by post channel."""
        channel_stats: dict = {}
        for upload in uploads:
            group_id = upload.source_channel_id or upload.channel_id
            if group_id not in channel_stats:
                src = upload.source_channel
                ch = upload.channel
                if upload.source_channel_id and src:
                    channel_stats[group_id] = {
                        "channel_id": group_id,
                        "channel_title": src.channel_title,
                        "channel_username": src.channel_username,
                        "via_ingest_title": ch.channel_title if ch else None,
                        "count": 0,
                        "uploads": [],
                    }
                else:
                    channel_stats[group_id] = {
                        "channel_id": group_id,
                        "channel_title": ch.channel_title if ch else None,
                        "channel_username": ch.channel_username if ch else None,
                        "via_ingest_title": None,
                        "count": 0,
                        "uploads": [],
                    }
            channel_stats[group_id]["count"] += 1
            channel_stats[group_id]["uploads"].append(
                {
                    "id": upload.id,
                    "file_name": upload.file_name,
                    "uploaded_at": upload.uploaded_at,
                    "is_confirmed": upload.is_confirmed,
                    "message_id": upload.message_id,
                    "source_channel_id": upload.source_channel_id,
                    "season_number": upload.season_number,
                    "episode_number": upload.episode_number,
                    "episode_title": upload.episode_title,
                }
            )
        return channel_stats
    
    def get_session(self):
        return self.Session()

    @staticmethod
    def _channel_for_return(session, channel: Channel | None) -> Channel | None:
        """Detach channel so callers can read fields after the session is closed."""
        if channel is None:
            return None
        session.refresh(channel)
        session.expunge(channel)
        return channel

    @staticmethod
    def _detach_upload_graph(session, uploads: list) -> list:
        """Detach uploads and eager-loaded relations (shared channels expunged once)."""
        seen_rel: set[int] = set()
        for upload in uploads:
            for rel in (upload.channel, upload.source_channel, upload.content_title):
                if rel is None:
                    continue
                rid = id(rel)
                if rid in seen_rel:
                    continue
                if object_session(rel) is session:
                    session.expunge(rel)
                seen_rel.add(rid)
            if object_session(upload) is session:
                session.expunge(upload)
        return uploads

    @staticmethod
    def _upload_for_return(session, upload: FileUpload | None) -> FileUpload | None:
        """Load scalars and detach so callers can read fields after session.close()."""
        if upload is None:
            return None
        session.refresh(upload)
        Database._detach_upload_graph(session, [upload])
        return upload
    
    def add_channel(self, channel_id, channel_username=None, channel_title=None):
        """Add a new channel to monitor"""
        session = self.get_session()
        try:
            channel = Channel(
                channel_id=str(channel_id),
                channel_username=channel_username,
                channel_title=channel_title
            )
            session.add(channel)
            session.commit()
            return self._channel_for_return(session, channel)
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def get_channel(self, channel_id):
        """Get channel by ID"""
        session = self.get_session()
        try:
            channel = session.query(Channel).filter_by(channel_id=str(channel_id)).first()
            return self._channel_for_return(session, channel)
        finally:
            session.close()
    
    def get_all_channels(self):
        """Get all active channels"""
        return self.get_all_channels_registered(active_only=True)

    def get_all_channels_registered(self, active_only=False):
        """Get channels known to the bot (active only, or including deactivated)."""
        session = self.get_session()
        try:
            query = session.query(Channel)
            if active_only:
                query = query.filter_by(is_active=True)
            rows = query.order_by(Channel.channel_title).all()
            return [self._channel_for_return(session, ch) for ch in rows]
        finally:
            session.close()
    
    def get_channels_bot_can_post(self, active_only=True):
        """Channels where Index Bot can publish (distribution / upload targets)."""
        session = self.get_session()
        try:
            query = session.query(Channel).filter_by(bot_can_post=True)
            if active_only:
                query = query.filter_by(is_active=True)
            rows = query.order_by(Channel.channel_title).all()
            return [self._channel_for_return(session, ch) for ch in rows]
        finally:
            session.close()

    def set_channel_bot_can_post(self, channel_id, bot_can_post=True):
        session = self.get_session()
        try:
            channel = session.query(Channel).filter_by(channel_id=str(channel_id)).first()
            if not channel:
                return None
            channel.bot_can_post = bool(bot_can_post)
            self._sync_telethon_watch_on_channel(channel, bot_can_post=bool(bot_can_post))
            session.commit()
            return self._channel_for_return(session, channel)
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def get_channel_upload_count(self, channel_id, *, is_ingest: bool = False):
        """
        Indexed media files for a channel.

        Normal channels: posts in the channel + files attributed via source_channel_id (backfill).
        Ingest channel: only files posted in the ingest channel (not double-count sources).
        """
        cid = str(channel_id)
        session = self.get_session()
        try:
            query = session.query(FileUpload).filter(self._subtitle_exclusion_filter())
            if is_ingest:
                query = query.filter(FileUpload.channel_id == cid)
            else:
                query = query.filter(
                    (FileUpload.channel_id == cid) | (FileUpload.source_channel_id == cid)
                )
            return query.count()
        finally:
            session.close()

    def set_channel_active(self, channel_id, is_active=True):
        """Activate or deactivate a channel by Telegram channel id."""
        session = self.get_session()
        try:
            channel = session.query(Channel).filter_by(channel_id=str(channel_id)).first()
            if not channel:
                return None
            channel.is_active = is_active
            session.commit()
            return self._channel_for_return(session, channel)
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def get_ingest_channel_id(self) -> str | None:
        ch = self.get_ingest_channel()
        return str(ch.channel_id) if ch else None

    def get_ingest_channel(self):
        """Return the channel flagged as historical ingest sink, if any."""
        session = self.get_session()
        try:
            channel = session.query(Channel).filter_by(is_ingest_channel=True).first()
            return self._channel_for_return(session, channel)
        finally:
            session.close()

    def set_ingest_channel(self, channel_id):
        """Mark one channel as the historical ingest channel (clears flag on others)."""
        session = self.get_session()
        try:
            channel = session.query(Channel).filter_by(channel_id=str(channel_id)).first()
            if not channel:
                return None
            session.query(Channel).update({Channel.is_ingest_channel: False})
            channel.is_ingest_channel = True
            channel.is_active = True
            session.commit()
            return self._channel_for_return(session, channel)
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def get_watch_channel_for_lane(self, lane: str):
        """Channel assigned in admin UI for a watch/catalog lane."""
        from content_lanes import LANE_MEDIA, normalize_lane

        lane = normalize_lane(lane)
        session = self.get_session()
        try:
            channel = (
                session.query(Channel)
                .filter_by(watch_for_lane=lane, is_active=True)
                .first()
            )
            if channel:
                return self._channel_for_return(session, channel)
            if lane == LANE_MEDIA:
                channel = session.query(Channel).filter_by(is_watch_channel=True).first()
                if channel:
                    return self._channel_for_return(session, channel)
            return None
        finally:
            session.close()

    def get_watch_channel(self, content_lane: str | None = None):
        """Watch/delivery channel: admin-assigned lane first, then optional .env fallback."""
        from content_lanes import (
            LANE_ARCHIVE,
            LANE_COURSE,
            LANE_MEDIA,
            LANE_SHORTFORM,
            normalize_lane,
        )

        lane = normalize_lane(content_lane) if content_lane else LANE_MEDIA
        ch = self.get_watch_channel_for_lane(lane)
        if ch:
            return ch
        if lane != LANE_MEDIA:
            ch = self.get_watch_channel_for_lane(LANE_MEDIA)
            if ch:
                return ch
        lane_ids = {
            LANE_MEDIA: Config.WATCH_CHANNEL_ID,
            LANE_COURSE: Config.WATCH_CHANNEL_COURSE_ID or Config.WATCH_CHANNEL_ID,
            LANE_SHORTFORM: Config.WATCH_CHANNEL_SHORTFORM_ID or Config.WATCH_CHANNEL_ID,
            LANE_ARCHIVE: Config.WATCH_CHANNEL_ARCHIVE_ID or Config.WATCH_CHANNEL_ID,
        }
        cid = (lane_ids.get(lane) or Config.WATCH_CHANNEL_ID or "").strip()
        if cid:
            return self.get_channel(cid)
        return None

    def list_watch_lane_assignments(self) -> dict[str, Channel | None]:
        from content_lanes import WATCH_LANE_OPTIONS, normalize_lane

        out: dict[str, Channel | None] = {lane: None for lane in WATCH_LANE_OPTIONS}
        session = self.get_session()
        try:
            for row in session.query(Channel).filter(Channel.watch_for_lane.isnot(None)).all():
                lane = normalize_lane(row.watch_for_lane)
                if lane in out:
                    out[lane] = self._channel_for_return(session, row)
            if out.get("media") is None:
                legacy = session.query(Channel).filter_by(is_watch_channel=True).first()
                if legacy:
                    out["media"] = self._channel_for_return(session, legacy)
            return out
        finally:
            session.close()

    def set_watch_channel_for_lane(self, channel_id: str, lane: str):
        """Assign catalog/delivery channel for a content lane (admin menu)."""
        from content_lanes import LANE_MEDIA, normalize_lane

        lane = normalize_lane(lane)
        session = self.get_session()
        try:
            channel = session.query(Channel).filter_by(channel_id=str(channel_id)).first()
            if not channel:
                return None
            session.query(Channel).filter(Channel.watch_for_lane == lane).update(
                {Channel.watch_for_lane: None}
            )
            channel.watch_for_lane = lane
            channel.is_active = True
            if lane == LANE_MEDIA:
                session.query(Channel).update({Channel.is_watch_channel: False})
                channel.is_watch_channel = True
            session.commit()
            return self._channel_for_return(session, channel)
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def clear_watch_channel_for_lane(self, lane: str) -> None:
        from content_lanes import LANE_MEDIA, normalize_lane

        lane = normalize_lane(lane)
        session = self.get_session()
        try:
            session.query(Channel).filter(Channel.watch_for_lane == lane).update(
                {Channel.watch_for_lane: None}
            )
            if lane == LANE_MEDIA:
                session.query(Channel).update({Channel.is_watch_channel: False})
            session.commit()
        finally:
            session.close()

    def get_content_title_lane(self, content_title_id: int) -> str:
        """Primary lane for a title (from its uploads)."""
        from content_lanes import normalize_lane

        session = self.get_session()
        try:
            row = (
                session.query(FileUpload.content_lane)
                .filter_by(content_title_id=int(content_title_id))
                .filter(self._subtitle_exclusion_filter())
                .first()
            )
            if row and row[0]:
                return normalize_lane(row[0])
            ct = session.query(MovieSeries).filter_by(id=int(content_title_id)).first()
            if ct and ct.media_type == "course":
                return "course"
            return "media"
        finally:
            session.close()

    def set_watch_channel(self, channel_id):
        """Legacy default watch channel (= media lane)."""
        from content_lanes import LANE_MEDIA

        return self.set_watch_channel_for_lane(channel_id, LANE_MEDIA)

    def set_watch_publication(
        self, upload_id: int, watch_channel_id: str, watch_message_id: int
    ) -> None:
        session = self.get_session()
        try:
            upload = session.query(FileUpload).filter_by(id=upload_id).first()
            if not upload:
                return
            upload.watch_channel_id = str(watch_channel_id)
            upload.watch_message_id = int(watch_message_id)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("set_watch_publication failed: %s", e)
        finally:
            session.close()

    def get_unpublished_watch_uploads(self, limit: int = 200) -> list:
        session = self.get_session()
        try:
            rows = (
                session.query(FileUpload)
                .filter(self._library_visible_filter())
                .filter(self._subtitle_exclusion_filter())
                .filter(FileUpload.watch_message_id.is_(None))
                .filter(
                    or_(
                        FileUpload.message_available.is_(None),
                        FileUpload.message_available.is_(True),
                    )
                )
                .order_by(FileUpload.uploaded_at.desc())
                .limit(limit)
                .all()
            )
            for row in rows:
                session.expunge(row)
            return rows
        finally:
            session.close()

    def count_watch_published(self) -> int:
        session = self.get_session()
        try:
            return session.query(WatchCatalogPost).count()
        finally:
            session.close()

    def clear_watch_catalog_posts(self) -> int:
        """Remove publish registry (use after clearing the watch channel in Telegram)."""
        session = self.get_session()
        try:
            deleted = session.query(WatchCatalogPost).delete()
            session.commit()
            return int(deleted or 0)
        except Exception as e:
            session.rollback()
            logger.error("clear_watch_catalog_posts failed: %s", e)
            return 0
        finally:
            session.close()

    def list_watch_catalog_posts(self, limit: int = 500) -> list[WatchCatalogPost]:
        session = self.get_session()
        try:
            rows = (
                session.query(WatchCatalogPost)
                .order_by(WatchCatalogPost.published_at.desc())
                .limit(limit)
                .all()
            )
            for row in rows:
                session.expunge(row)
            return rows
        finally:
            session.close()

    def get_watch_catalog_post(
        self, content_title_id: int, season_number: int | None
    ) -> WatchCatalogPost | None:
        session = self.get_session()
        try:
            q = session.query(WatchCatalogPost).filter_by(
                content_title_id=int(content_title_id)
            )
            if season_number is None:
                q = q.filter(WatchCatalogPost.season_number.is_(None))
            else:
                q = q.filter(WatchCatalogPost.season_number == int(season_number))
            row = q.first()
            if row:
                session.expunge(row)
            return row
        finally:
            session.close()

    def delete_watch_catalog_post(
        self, content_title_id: int, season_number: int | None
    ) -> bool:
        session = self.get_session()
        try:
            q = session.query(WatchCatalogPost).filter_by(
                content_title_id=int(content_title_id)
            )
            if season_number is None:
                q = q.filter(WatchCatalogPost.season_number.is_(None))
            else:
                q = q.filter(WatchCatalogPost.season_number == int(season_number))
            row = q.first()
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error("delete_watch_catalog_post failed: %s", e)
            return False
        finally:
            session.close()

    def list_published_catalog_page(
        self,
        *,
        limit: int = 28,
        offset: int = 0,
        search: str | None = None,
        sort: str = "published_at",
        desc: bool = True,
    ) -> tuple[list[dict], int]:
        session = self.get_session()
        try:
            title_expr = func.coalesce(MovieSeries.tmdb_title, MovieSeries.name)
            base = session.query(WatchCatalogPost, MovieSeries).join(
                MovieSeries, WatchCatalogPost.content_title_id == MovieSeries.id
            )
            q = (search or "").strip()
            if q:
                like = f"%{q}%"
                base = base.filter(
                    or_(title_expr.ilike(like), MovieSeries.name.ilike(like))
                )
            total = int(base.with_entities(func.count(WatchCatalogPost.id)).scalar() or 0)

            sort_key = (sort or "published_at").lower()
            if sort_key == "title":
                order_col = title_expr
            elif sort_key == "year":
                order_col = MovieSeries.release_year
            elif sort_key == "rating":
                order_col = MovieSeries.vote_average
            else:
                order_col = WatchCatalogPost.published_at

            order = order_col.desc().nulls_last() if desc else order_col.asc().nulls_first()
            rows = base.order_by(order).offset(max(0, offset)).limit(max(1, limit)).all()
            items = []
            for post, ct in rows:
                items.append(
                    {
                        "content_title_id": post.content_title_id,
                        "season_number": post.season_number,
                        "message_id": post.message_id,
                        "watch_channel_id": post.watch_channel_id,
                        "published_at": (
                            post.published_at.isoformat() if post.published_at else None
                        ),
                        "title": ct.tmdb_title or ct.name or "?",
                        "media_type": (ct.media_type or "movie").lower(),
                        "release_year": ct.release_year,
                        "vote_average": ct.vote_average,
                        "poster_path": ct.poster_path,
                        "tmdb_id": ct.tmdb_id,
                    }
                )
            return items, total
        finally:
            session.close()

    def count_active_channels(self) -> int:
        session = self.get_session()
        try:
            return int(
                session.query(Channel)
                .filter(Channel.is_active.is_(True))
                .count()
            )
        finally:
            session.close()

    def save_watch_catalog_post(
        self,
        content_title_id: int,
        season_number: int | None,
        watch_channel_id: str,
        message_id: int,
    ) -> None:
        session = self.get_session()
        try:
            q = session.query(WatchCatalogPost).filter_by(
                content_title_id=int(content_title_id)
            )
            if season_number is None:
                q = q.filter(WatchCatalogPost.season_number.is_(None))
            else:
                q = q.filter(WatchCatalogPost.season_number == int(season_number))
            row = q.first()
            if not row:
                row = WatchCatalogPost(
                    content_title_id=int(content_title_id),
                    season_number=season_number,
                )
                session.add(row)
            row.watch_channel_id = str(watch_channel_id)
            row.message_id = int(message_id)
            row.published_at = datetime.utcnow()
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("save_watch_catalog_post failed: %s", e)
        finally:
            session.close()

    @staticmethod
    def _watch_catalog_title_filter():
        """Movie/Series titles eligible for watch-channel catalog cards."""
        return and_(
            MovieSeries.tmdb_id.isnot(None),
            MovieSeries.catalog_excluded.isnot(True),
            func.lower(MovieSeries.media_type).notin_(("course",)),
        )

    def get_library_catalog_slots(
        self, limit: int | None = 120, offset: int = 0
    ) -> list[dict]:
        """Distinct (content_title, season) slots eligible for watch catalog publish.

        Media lane uploads only, with a TMDB id on the title row.
        """
        session = self.get_session()
        try:
            rows = (
                session.query(
                    FileUpload.content_title_id,
                    FileUpload.season_number,
                    MovieSeries.media_type,
                )
                .join(MovieSeries, FileUpload.content_title_id == MovieSeries.id)
                .filter(FileUpload.content_title_id.isnot(None))
                .filter(self._media_browse_filter())
                .filter(self._watch_catalog_title_filter())
                .filter(self._subtitle_exclusion_filter())
                .all()
            )
            slots: dict[tuple, dict] = {}
            for ct_id, season, mt in rows:
                if not ct_id:
                    continue
                mt_l = (mt or "movie").lower()
                if mt_l in ("tv", "series"):
                    sn = int(season) if season is not None else 1
                    key = (ct_id, sn)
                else:
                    key = (ct_id, None)
                if key not in slots:
                    slots[key] = {
                        "content_title_id": ct_id,
                        "season_number": key[1],
                        "media_type": mt_l,
                    }
            out = sorted(
                slots.values(),
                key=lambda s: (s["content_title_id"], s.get("season_number") or 0),
            )
            if offset:
                out = out[offset:]
            if limit is not None:
                return out[:limit]
            return out
        finally:
            session.close()

    def count_library_catalog_slots(self) -> int:
        return len(self.get_library_catalog_slots(limit=None))

    def count_published_catalog_posts(self) -> int:
        session = self.get_session()
        try:
            return int(session.query(func.count(WatchCatalogPost.id)).scalar() or 0)
        finally:
            session.close()

    def count_unpublished_catalog_slots(self) -> int:
        """Slots in library without a watch-channel catalog post."""
        return max(
            0,
            self.count_library_catalog_slots() - self.count_published_catalog_posts(),
        )

    def get_unpublished_catalog_slots(self, limit: int | None = 100) -> list[dict]:
        """Unpublished slots; scans full library (not only the first N titles)."""
        slots = self.get_library_catalog_slots(limit=None)
        out = []
        for s in slots:
            existing = self.get_watch_catalog_post(
                s["content_title_id"], s.get("season_number")
            )
            if not existing:
                out.append(s)
            if limit is not None and len(out) >= limit:
                break
        return out

    def count_unpublished_catalog_slots(self) -> int:
        return len(self.get_unpublished_catalog_slots(limit=None))

    @staticmethod
    def _metadata_gap_clause(issue: str):
        no_tmdb = MovieSeries.tmdb_id.is_(None)
        no_poster = or_(
            MovieSeries.poster_path.is_(None),
            MovieSeries.poster_path == "",
        )
        key = (issue or "all").lower()
        if key == "no_tmdb":
            return no_tmdb
        if key == "no_poster":
            return no_poster
        if key == "no_both":
            return and_(no_tmdb, no_poster)
        return or_(no_tmdb, no_poster)

    @staticmethod
    def _metadata_gaps_library_filter():
        """Media library only — courses use Course library, not metadata gaps."""
        return Database._media_browse_filter()

    def _metadata_gaps_id_subquery(self, session, issue: str = "all"):
        return (
            session.query(MovieSeries.id.label("ct_id"))
            .join(FileUpload, FileUpload.content_title_id == MovieSeries.id)
            .filter(FileUpload.content_title_id.isnot(None))
            .filter(self._metadata_gaps_library_filter())
            .filter(func.lower(MovieSeries.media_type) != "course")
            .filter(MovieSeries.catalog_excluded.isnot(True))
            .filter(self._subtitle_exclusion_filter())
            .filter(self._metadata_gap_clause(issue))
            .group_by(MovieSeries.id)
            .subquery()
        )

    def count_metadata_gap_summary(self) -> dict[str, int]:
        """Library titles missing TMDB id and/or poster_path."""
        session = self.get_session()
        try:
            out: dict[str, int] = {}
            for key in ("all", "no_tmdb", "no_poster", "no_both"):
                subq = self._metadata_gaps_id_subquery(session, key)
                out[key] = int(
                    session.query(func.count()).select_from(subq).scalar() or 0
                )
            return {
                "missing_any": out["all"],
                "no_tmdb": out["no_tmdb"],
                "no_poster": out["no_poster"],
                "no_both": out["no_both"],
            }
        finally:
            session.close()

    def list_library_titles_missing_metadata(
        self,
        *,
        issue: str = "all",
        limit: int = 40,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        session = self.get_session()
        try:
            subq = self._metadata_gaps_id_subquery(session, issue)
            total = int(
                session.query(func.count()).select_from(subq).scalar() or 0
            )
            title_expr = func.lower(MovieSeries.name)
            id_rows = (
                session.query(subq.c.ct_id)
                .join(MovieSeries, MovieSeries.id == subq.c.ct_id)
                .order_by(title_expr)
                .offset(max(0, int(offset)))
                .limit(max(1, int(limit)))
                .all()
            )
            if not id_rows:
                return [], total
            ct_ids = [int(r[0]) for r in id_rows]
            upload_counts = dict(
                session.query(FileUpload.content_title_id, func.count(FileUpload.id))
                .filter(FileUpload.content_title_id.in_(ct_ids))
                .filter(self._metadata_gaps_library_filter())
                .filter(self._subtitle_exclusion_filter())
                .group_by(FileUpload.content_title_id)
                .all()
            )
            max_gap_names = 6
            file_names_by_ct: dict[int, list[str]] = {cid: [] for cid in ct_ids}
            name_rows = (
                session.query(
                    FileUpload.content_title_id,
                    FileUpload.file_name,
                    FileUpload.uploaded_at,
                )
                .filter(FileUpload.content_title_id.in_(ct_ids))
                .filter(FileUpload.ingest_state != "skipped")
                .filter(self._subtitle_exclusion_filter())
                .order_by(
                    FileUpload.content_title_id,
                    FileUpload.uploaded_at.desc(),
                )
                .all()
            )
            for ct_id, fname, _ in name_rows:
                cid = int(ct_id)
                bucket = file_names_by_ct.get(cid)
                if bucket is not None and len(bucket) < max_gap_names:
                    bucket.append((fname or "?").strip() or "?")
            rows = (
                session.query(MovieSeries)
                .filter(MovieSeries.id.in_(ct_ids))
                .all()
            )
            by_id = {int(r.id): r for r in rows}
            items: list[dict] = []
            for ct_id in ct_ids:
                ct = by_id.get(ct_id)
                if not ct:
                    continue
                gaps: list[str] = []
                if ct.tmdb_id is None:
                    gaps.append("no_tmdb")
                if not (ct.poster_path or "").strip():
                    gaps.append("no_poster")
                items.append(
                    {
                        "content_title_id": ct_id,
                        "title": ct.tmdb_title or ct.name or "?",
                        "name": ct.name,
                        "tmdb_title": ct.tmdb_title,
                        "media_type": (ct.media_type or "movie").lower(),
                        "tmdb_id": ct.tmdb_id,
                        "poster_path": ct.poster_path,
                        "release_year": ct.release_year,
                        "issues": gaps,
                        "upload_count": int(upload_counts.get(ct_id, 0)),
                        "file_names": file_names_by_ct.get(ct_id, []),
                        "file_names_extra": max(
                            0,
                            int(upload_counts.get(ct_id, 0))
                            - len(file_names_by_ct.get(ct_id, [])),
                        ),
                    }
                )
            return items, total
        finally:
            session.close()

    def count_uploads_in_catalog_slot(
        self, content_title_id: int, season_number: int | None
    ) -> int:
        session = self.get_session()
        try:
            q = (
                session.query(FileUpload)
                .filter_by(content_title_id=int(content_title_id))
                .filter(self._media_browse_filter())
                .filter(self._subtitle_exclusion_filter())
            )
            if season_number is not None:
                sn = int(season_number)
                q = q.filter(
                    or_(
                        FileUpload.season_number == sn,
                        and_(FileUpload.season_number.is_(None), sn == 1),
                    )
                )
            return q.count()
        finally:
            session.close()

    def user_needs_welcome(self, user_id: int) -> bool:
        session = self.get_session()
        try:
            return (
                session.query(BotUser).filter_by(user_id=int(user_id)).first() is None
            )
        finally:
            session.close()

    def mark_user_welcomed(self, user_id: int) -> None:
        session = self.get_session()
        try:
            if session.query(BotUser).filter_by(user_id=int(user_id)).first():
                return
            session.add(BotUser(user_id=int(user_id)))
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("mark_user_welcomed failed: %s", e)
        finally:
            session.close()

    def toggle_favorite(self, user_id: int, content_title_id: int) -> bool:
        """Return True if now favorited."""
        session = self.get_session()
        try:
            row = (
                session.query(UserFavorite)
                .filter_by(user_id=int(user_id), content_title_id=int(content_title_id))
                .first()
            )
            if row:
                session.delete(row)
                session.commit()
                return False
            session.add(
                UserFavorite(user_id=int(user_id), content_title_id=int(content_title_id))
            )
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error("toggle_favorite failed: %s", e)
            return False
        finally:
            session.close()

    def is_favorite(self, user_id: int, content_title_id: int) -> bool:
        session = self.get_session()
        try:
            return (
                session.query(UserFavorite)
                .filter_by(user_id=int(user_id), content_title_id=int(content_title_id))
                .first()
                is not None
            )
        finally:
            session.close()

    def is_on_watchlist(self, user_id: int, content_title_id: int) -> bool:
        session = self.get_session()
        try:
            return (
                session.query(UserWatchlistItem)
                .join(UserWatchlist, UserWatchlistItem.watchlist_id == UserWatchlist.id)
                .filter(
                    UserWatchlist.user_id == int(user_id),
                    UserWatchlistItem.content_title_id == int(content_title_id),
                )
                .first()
                is not None
            )
        finally:
            session.close()

    def toggle_watchlist_title(self, user_id: int, content_title_id: int) -> bool:
        """Return True if title is now on the user's default watchlist (watch later)."""
        wl_id = self.get_or_create_default_watchlist(user_id)
        session = self.get_session()
        try:
            row = (
                session.query(UserWatchlistItem)
                .filter_by(
                    watchlist_id=int(wl_id),
                    content_title_id=int(content_title_id),
                )
                .first()
            )
            if row:
                session.delete(row)
                session.commit()
                return False
            session.add(
                UserWatchlistItem(
                    watchlist_id=int(wl_id),
                    content_title_id=int(content_title_id),
                )
            )
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error("toggle_watchlist_title failed: %s", e)
            return self.is_on_watchlist(user_id, content_title_id)
        finally:
            session.close()

    def get_user_watchlist_titles(self, user_id: int, limit: int = 60) -> list[dict]:
        """Titles on the user's default watchlist for portal browse."""
        wl_id = self.get_or_create_default_watchlist(user_id)
        return self.get_watchlist_items(user_id, wl_id, limit=limit)

    def get_user_favorites(self, user_id: int, limit: int = 40) -> list[dict]:
        session = self.get_session()
        try:
            title_expr = func.coalesce(MovieSeries.tmdb_title, MovieSeries.name)
            rows = (
                session.query(
                    UserFavorite.content_title_id,
                    title_expr.label("title"),
                    MovieSeries.media_type,
                    MovieSeries.release_year,
                )
                .join(MovieSeries, UserFavorite.content_title_id == MovieSeries.id)
                .filter(UserFavorite.user_id == int(user_id))
                .order_by(UserFavorite.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "content_title_id": r.content_title_id,
                    "title": r.title,
                    "media_type": r.media_type,
                    "release_year": r.release_year,
                }
                for r in rows
            ]
        finally:
            session.close()

    def get_or_create_default_watchlist(self, user_id: int) -> int:
        session = self.get_session()
        try:
            row = (
                session.query(UserWatchlist)
                .filter_by(user_id=int(user_id))
                .order_by(UserWatchlist.id.asc())
                .first()
            )
            if row:
                return row.id
            row = UserWatchlist(user_id=int(user_id), list_name="My watchlist")
            session.add(row)
            session.commit()
            return row.id
        finally:
            session.close()

    def get_user_watchlists(self, user_id: int) -> list:
        session = self.get_session()
        try:
            return (
                session.query(UserWatchlist)
                .filter_by(user_id=int(user_id))
                .order_by(UserWatchlist.id.asc())
                .all()
            )
        finally:
            session.close()

    def create_user_watchlist(self, user_id: int, list_name: str) -> int | None:
        session = self.get_session()
        try:
            name = (list_name or "").strip()[:64]
            if not name:
                return None
            row = UserWatchlist(user_id=int(user_id), list_name=name)
            session.add(row)
            session.commit()
            return row.id
        except Exception as e:
            session.rollback()
            logger.error("create_user_watchlist failed: %s", e)
            return None
        finally:
            session.close()

    def add_watchlist_item(
        self, user_id: int, watchlist_id: int, content_title_id: int
    ) -> bool:
        session = self.get_session()
        try:
            wl = (
                session.query(UserWatchlist)
                .filter_by(id=int(watchlist_id), user_id=int(user_id))
                .first()
            )
            if not wl:
                return False
            exists = (
                session.query(UserWatchlistItem)
                .filter_by(
                    watchlist_id=int(watchlist_id),
                    content_title_id=int(content_title_id),
                )
                .first()
            )
            if exists:
                return True
            session.add(
                UserWatchlistItem(
                    watchlist_id=int(watchlist_id),
                    content_title_id=int(content_title_id),
                )
            )
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error("add_watchlist_item failed: %s", e)
            return False
        finally:
            session.close()

    def get_watchlist_items(self, user_id: int, watchlist_id: int, limit: int = 40) -> list:
        session = self.get_session()
        try:
            wl = (
                session.query(UserWatchlist)
                .filter_by(id=int(watchlist_id), user_id=int(user_id))
                .first()
            )
            if not wl:
                return []
            title_expr = func.coalesce(MovieSeries.tmdb_title, MovieSeries.name)
            rows = (
                session.query(
                    UserWatchlistItem.id,
                    UserWatchlistItem.content_title_id,
                    UserWatchlistItem.watched,
                    title_expr.label("title"),
                    MovieSeries.media_type,
                )
                .join(MovieSeries, UserWatchlistItem.content_title_id == MovieSeries.id)
                .filter(UserWatchlistItem.watchlist_id == int(watchlist_id))
                .order_by(UserWatchlistItem.added_at.desc())
                .limit(limit)
                .all()
            )
            ct_ids = [r.content_title_id for r in rows]
            lib_counts = self._library_upload_counts(session, ct_ids)
            return [
                {
                    "item_id": r.id,
                    "content_title_id": r.content_title_id,
                    "title": r.title,
                    "media_type": r.media_type,
                    "watched": bool(r.watched),
                    "in_library": lib_counts.get(r.content_title_id, 0) > 0,
                }
                for r in rows
            ]
        finally:
            session.close()

    def _library_upload_counts(self, session, content_title_ids: list[int]) -> dict[int, int]:
        if not content_title_ids:
            return {}
        rows = (
            session.query(FileUpload.content_title_id, func.count(FileUpload.id))
            .filter(
                FileUpload.content_title_id.in_(content_title_ids),
                self._library_visible_filter(),
            )
            .group_by(FileUpload.content_title_id)
            .all()
        )
        return {int(ct_id): int(n) for ct_id, n in rows}

    def count_library_uploads_for_content(self, content_title_id: int) -> int:
        session = self.get_session()
        try:
            return (
                session.query(FileUpload)
                .filter(
                    FileUpload.content_title_id == int(content_title_id),
                    self._library_visible_filter(),
                )
                .count()
            )
        finally:
            session.close()

    def toggle_watchlist_item_watched(self, user_id: int, item_id: int) -> bool | None:
        """Return new watched state, or None if not found."""
        session = self.get_session()
        try:
            row = (
                session.query(UserWatchlistItem)
                .join(UserWatchlist, UserWatchlistItem.watchlist_id == UserWatchlist.id)
                .filter(
                    UserWatchlistItem.id == int(item_id),
                    UserWatchlist.user_id == int(user_id),
                )
                .first()
            )
            if not row:
                return None
            row.watched = not bool(row.watched)
            session.commit()
            return bool(row.watched)
        except Exception as e:
            session.rollback()
            logger.error("toggle_watchlist_item_watched failed: %s", e)
            return None
        finally:
            session.close()

    def has_pending_upload_request(
        self, user_id: int, tmdb_id: int | None, media_type: str
    ) -> bool:
        if tmdb_id is None:
            return False
        session = self.get_session()
        try:
            return (
                session.query(UploadRequest)
                .filter_by(
                    user_id=int(user_id),
                    tmdb_id=int(tmdb_id),
                    media_type=(media_type or "movie").lower(),
                    status="pending",
                )
                .first()
                is not None
            )
        finally:
            session.close()

    def get_user_upload_requests(self, user_id: int, limit: int = 30) -> list:
        session = self.get_session()
        try:
            return (
                session.query(UploadRequest)
                .filter_by(user_id=int(user_id))
                .order_by(UploadRequest.created_at.desc())
                .limit(limit)
                .all()
            )
        finally:
            session.close()

    def create_upload_request(
        self,
        user_id: int,
        *,
        tmdb_id: int | None,
        media_type: str,
        tmdb_title: str,
        release_year: int | None = None,
    ) -> int | None:
        session = self.get_session()
        try:
            row = UploadRequest(
                user_id=int(user_id),
                tmdb_id=tmdb_id,
                media_type=(media_type or "movie").lower(),
                tmdb_title=(tmdb_title or "").strip(),
                release_year=release_year,
                status="pending",
            )
            session.add(row)
            session.commit()
            return row.id
        except Exception as e:
            session.rollback()
            logger.error("create_upload_request failed: %s", e)
            return None
        finally:
            session.close()

    def count_pending_upload_requests(self) -> int:
        session = self.get_session()
        try:
            return (
                session.query(UploadRequest)
                .filter_by(status="pending")
                .count()
            )
        finally:
            session.close()

    def get_pending_upload_requests(
        self, limit: int = 30, offset: int = 0
    ) -> list:
        session = self.get_session()
        try:
            q = (
                session.query(UploadRequest)
                .filter_by(status="pending")
                .order_by(UploadRequest.created_at.desc())
            )
            if offset:
                q = q.offset(max(0, int(offset)))
            if limit:
                q = q.limit(max(1, int(limit)))
            return q.all()
        finally:
            session.close()

    def get_upload_request(self, request_id: int):
        session = self.get_session()
        try:
            return session.query(UploadRequest).filter_by(id=request_id).first()
        finally:
            session.close()

    def set_upload_request_status(self, request_id: int, status: str) -> bool:
        session = self.get_session()
        try:
            row = session.query(UploadRequest).filter_by(id=request_id).first()
            if not row:
                return False
            row.status = status
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error("set_upload_request_status failed: %s", e)
            return False
        finally:
            session.close()
    
    def _reassign_content_title_id(self, session, from_id: int, to_id: int) -> None:
        """Point all library rows at another movie_series id (merge duplicates)."""
        if from_id == to_id:
            return
        for model in (FileUpload, UserFavorite, UserWatchlistItem, WatchCatalogPost):
            session.query(model).filter_by(content_title_id=from_id).update(
                {model.content_title_id: to_id},
                synchronize_session=False,
            )

    def upsert_content_title(
        self,
        *,
        local_name: str,
        media_type: str = "movie",
        tmdb_id: int | None = None,
        tmdb_title: str | None = None,
        release_year: int | None = None,
        franchise_sequence: int | None = None,
        poster_path: str | None = None,
        overview: str | None = None,
        vote_average: str | None = None,
        genres: list | str | None = None,
        catalog_excluded: bool | None = None,
        indexed_only: bool | None = None,
    ) -> MovieSeries | None:
        """Create or update a canonical library title (grouping key)."""
        canonical = (tmdb_title or local_name or "").strip()
        if not canonical:
            return None
        local_name = canonical
        media_type = (media_type or "movie").lower()
        if media_type in ("series", "show"):
            media_type = "tv"

        genres_json = None
        if genres is not None:
            genres_json = genres if isinstance(genres, str) else json.dumps(genres)

        session = self.get_session()
        try:
            row = None
            if tmdb_id is not None:
                row = (
                    session.query(MovieSeries)
                    .filter_by(tmdb_id=tmdb_id, media_type=media_type)
                    .first()
                )
            if not row:
                row = (
                    session.query(MovieSeries)
                    .filter_by(name=local_name, media_type=media_type)
                    .first()
                )
            # Legacy DB: unique on name only — reuse row even if media_type differs
            if not row and local_name:
                row = session.query(MovieSeries).filter_by(name=local_name).first()

            if row:
                if media_type and (row.media_type or "").lower() != media_type:
                    row.media_type = media_type
                dup = (
                    session.query(MovieSeries)
                    .filter(
                        MovieSeries.name == local_name,
                        MovieSeries.media_type == media_type,
                        MovieSeries.id != row.id,
                    )
                    .first()
                )
                if dup:
                    merge_from, merge_into = row.id, dup.id
                    if tmdb_id is not None and dup.tmdb_id and dup.tmdb_id != tmdb_id:
                        merge_from, merge_into = dup.id, row.id
                    self._reassign_content_title_id(session, merge_from, merge_into)
                    stale = session.query(MovieSeries).filter_by(id=merge_from).first()
                    if stale:
                        session.delete(stale)
                    session.flush()
                    row = session.query(MovieSeries).filter_by(id=merge_into).first()

                row.name = local_name
                if tmdb_id is not None:
                    row.tmdb_id = tmdb_id
                if tmdb_title:
                    row.tmdb_title = tmdb_title
                if release_year is not None:
                    row.release_year = release_year
                if franchise_sequence is not None:
                    row.franchise_sequence = franchise_sequence
                if poster_path:
                    row.poster_path = poster_path
                if overview:
                    row.overview = overview
                if vote_average is not None:
                    row.vote_average = vote_average
                if genres_json:
                    row.genres = genres_json
                if catalog_excluded is not None:
                    row.catalog_excluded = bool(catalog_excluded)
                if indexed_only is not None:
                    row.indexed_only = bool(indexed_only)
            else:
                row = MovieSeries(
                    name=local_name,
                    media_type=media_type,
                    tmdb_id=tmdb_id,
                    tmdb_title=tmdb_title,
                    release_year=release_year,
                    franchise_sequence=franchise_sequence,
                    poster_path=poster_path,
                    overview=overview,
                    vote_average=vote_average,
                    genres=genres_json,
                    catalog_excluded=bool(catalog_excluded) if catalog_excluded is not None else False,
                    indexed_only=bool(indexed_only) if indexed_only is not None else False,
                )
                session.add(row)
            session.commit()
            return self._channel_for_return(session, row)
        except Exception as e:
            session.rollback()
            logger.error("Error upserting content title: %s", e)
            raise
        finally:
            session.close()

    def upsert_movie_series(self, name, tmdb_id=None, media_type=None):
        """Backward-compatible wrapper."""
        mt = media_type or "movie"
        if mt == "tv":
            mt = "tv"
        elif mt:
            mt = "movie"
        return self.upsert_content_title(
            local_name=name,
            media_type=mt,
            tmdb_id=tmdb_id,
            tmdb_title=name if tmdb_id else None,
        )

    def is_catalog_publishable(self, content_title_id: int | None) -> bool:
        """Media lane + TMDB-mapped title, not excluded from catalog."""
        from content_lanes import lane_allows_watch_catalog, normalize_lane

        if not content_title_id:
            return False
        ct = self.get_content_title(content_title_id)
        if not ct or getattr(ct, "catalog_excluded", False):
            return False
        if not ct.tmdb_id:
            return False
        if (ct.media_type or "").lower() == "course":
            return False
        return lane_allows_watch_catalog(self.get_content_title_lane(content_title_id))

    def get_content_title(self, content_title_id: int) -> MovieSeries | None:
        session = self.get_session()
        try:
            row = session.query(MovieSeries).filter_by(id=content_title_id).first()
            return self._channel_for_return(session, row)
        finally:
            session.close()

    def cache_content_poster_path(self, content_title_id: int, poster_path: str) -> bool:
        """Persist TMDB poster path when cards/detail fetch live art (backfill gaps)."""
        path = (poster_path or "").strip()
        if not path:
            return False

        @_sqlite_write_retry
        def _write() -> bool:
            session = self.get_session()
            try:
                row = session.query(MovieSeries).filter_by(id=int(content_title_id)).first()
                if not row or (row.poster_path or "").strip():
                    return False
                row.poster_path = path[:500]
                session.commit()
                return True
            except Exception as e:
                session.rollback()
                logger.debug("cache_content_poster_path ct=%s: %s", content_title_id, e)
                return False
            finally:
                session.close()

        return _write()

    def get_movie_series(self, name):
        """Get TMDB metadata by local or TMDB title (first match)."""
        session = self.get_session()
        try:
            key = str(name).strip()
            row = (
                session.query(MovieSeries)
                .filter((MovieSeries.name == key) | (MovieSeries.tmdb_title == key))
                .first()
            )
            return self._channel_for_return(session, row)
        finally:
            session.close()

    @staticmethod
    def display_title_for_content(row: MovieSeries | None, fallback: str = "") -> str:
        if not row:
            return fallback
        if row.tmdb_title:
            if row.media_type == "movie" and row.franchise_sequence:
                return f"{row.tmdb_title} ({row.franchise_sequence})"
            return row.tmdb_title
        return row.name or fallback

    def get_library_browse_entries(
        self, limit=25, channel_ids=None, *, library_only: bool = True
    ) -> list[dict]:
        """Library browse rows: title, media_type, year, rating (one per content title)."""
        session = self.get_session()
        try:
            title_expr = func.coalesce(
                MovieSeries.tmdb_title,
                MovieSeries.name,
                FileUpload.confirmed_name,
            )
            query = (
                session.query(
                    MovieSeries.id.label("content_title_id"),
                    title_expr.label("title"),
                    MovieSeries.media_type,
                    MovieSeries.release_year,
                    MovieSeries.vote_average,
                    func.max(FileUpload.uploaded_at).label("latest"),
                )
                .join(MovieSeries, FileUpload.content_title_id == MovieSeries.id)
                .filter(title_expr.isnot(None))
                .filter(self._subtitle_exclusion_filter())
            )
            if library_only:
                query = query.filter(self._public_library_filter())
            if channel_ids:
                query = query.filter(
                    (FileUpload.channel_id.in_(channel_ids))
                    | (FileUpload.source_channel_id.in_(channel_ids))
                )
            rows = (
                query.group_by(MovieSeries.id)
                .order_by(func.max(FileUpload.uploaded_at).desc())
                .limit(limit)
                .all()
            )
            out: list[dict] = []
            for r in rows:
                if not r.title:
                    continue
                out.append(
                    {
                        "title": r.title,
                        "media_type": (r.media_type or "movie").lower(),
                        "release_year": r.release_year,
                        "vote_average": r.vote_average,
                        "content_title_id": r.content_title_id,
                    }
                )
            return out
        finally:
            session.close()

    def count_library_browse_titles(
        self, *, library_only: bool = True, browse_scope: str = "public"
    ) -> int:
        """Distinct content titles visible in public library browse."""
        session = self.get_session()
        try:
            title_expr = func.coalesce(
                MovieSeries.tmdb_title,
                MovieSeries.name,
                FileUpload.confirmed_name,
            )
            query = (
                session.query(func.count(func.distinct(MovieSeries.id)))
                .select_from(FileUpload)
                .join(MovieSeries, FileUpload.content_title_id == MovieSeries.id)
                .filter(title_expr.isnot(None))
                .filter(self._subtitle_exclusion_filter())
            )
            if library_only:
                scope = (browse_scope or "public").lower()
                if scope == "media":
                    query = query.filter(self._media_browse_filter())
                    query = query.filter(func.lower(MovieSeries.media_type) != "course")
                elif scope == "course":
                    query = query.filter(self._course_library_filter())
                elif scope == "adult":
                    query = query.filter(self._adult_library_filter())
                elif scope == "archive":
                    query = query.filter(self._archive_library_filter())
                elif scope == "shortform":
                    query = query.filter(self._shortform_library_filter())
                elif scope in ("non_catalog", "non-catalog", "noncatalog"):
                    query = query.filter(self._non_catalog_browse_filter())
                else:
                    query = query.filter(self._public_library_filter())
            return int(query.scalar() or 0)
        finally:
            session.close()

    def _apply_library_browse_filters(
        self,
        query,
        title_expr,
        *,
        library_only: bool,
        browse_scope: str = "public",
        media_type: str | None,
        min_year: int | None,
        max_year: int | None,
        min_rating: float | None,
        search: str | None = None,
    ):
        query = query.filter(title_expr.isnot(None)).filter(
            self._subtitle_exclusion_filter()
        )
        q = (search or "").strip()
        if q:
            like = f"%{q}%"
            query = query.filter(
                or_(title_expr.ilike(like), MovieSeries.name.ilike(like))
            )
        if library_only:
            scope = (browse_scope or "public").lower()
            if scope == "media":
                query = query.filter(self._media_browse_filter())
                query = query.filter(func.lower(MovieSeries.media_type) != "course")
            elif scope == "course":
                query = query.filter(self._course_library_filter())
            elif scope == "adult":
                query = query.filter(self._adult_library_filter())
            elif scope == "archive":
                query = query.filter(self._archive_library_filter())
            elif scope == "shortform":
                query = query.filter(self._shortform_library_filter())
            elif scope in ("non_catalog", "non-catalog", "noncatalog"):
                query = query.filter(self._non_catalog_browse_filter())
            else:
                query = query.filter(self._public_library_filter())
        if media_type and str(media_type).lower() not in ("all", ""):
            mt = str(media_type).lower()
            if mt == "tv":
                query = query.filter(
                    func.lower(MovieSeries.media_type).in_(["tv", "series"])
                )
            else:
                query = query.filter(func.lower(MovieSeries.media_type) == mt)
        if min_year is not None:
            query = query.filter(MovieSeries.release_year >= int(min_year))
        if max_year is not None:
            query = query.filter(MovieSeries.release_year <= int(max_year))
        if min_rating is not None:
            query = query.filter(MovieSeries.vote_average >= float(min_rating))
        return query

    def list_library_browse(
        self,
        *,
        limit: int = 28,
        offset: int = 0,
        library_only: bool = True,
        browse_scope: str = "public",
        media_type: str | None = None,
        min_year: int | None = None,
        max_year: int | None = None,
        min_rating: float | None = None,
        sort: str = "recent",
        desc: bool = True,
        search: str | None = None,
    ) -> tuple[list[dict], int]:
        """Paginated library browse with sort/filter."""
        session = self.get_session()
        try:
            title_expr = func.coalesce(
                MovieSeries.tmdb_title,
                MovieSeries.name,
                FileUpload.confirmed_name,
            )
            latest = func.max(FileUpload.uploaded_at).label("latest")
            base = (
                session.query(
                    MovieSeries.id.label("content_title_id"),
                    title_expr.label("title"),
                    MovieSeries.media_type,
                    MovieSeries.release_year,
                    MovieSeries.vote_average,
                    latest,
                )
                .join(MovieSeries, FileUpload.content_title_id == MovieSeries.id)
            )
            base = self._apply_library_browse_filters(
                base,
                title_expr,
                library_only=library_only,
                browse_scope=browse_scope,
                media_type=media_type,
                min_year=min_year,
                max_year=max_year,
                min_rating=min_rating,
                search=search,
            )
            count_q = self._apply_library_browse_filters(
                session.query(func.count(func.distinct(MovieSeries.id)))
                .select_from(FileUpload)
                .join(MovieSeries, FileUpload.content_title_id == MovieSeries.id),
                title_expr,
                library_only=library_only,
                browse_scope=browse_scope,
                media_type=media_type,
                min_year=min_year,
                max_year=max_year,
                min_rating=min_rating,
                search=search,
            )
            total = int(count_q.scalar() or 0)

            sort_key = (sort or "recent").lower()
            if sort_key == "title":
                order_col = title_expr
            elif sort_key == "year":
                order_col = MovieSeries.release_year
            elif sort_key == "rating":
                order_col = MovieSeries.vote_average
            else:
                order_col = latest

            if desc:
                order = order_col.desc().nulls_last()
            else:
                order = order_col.asc().nulls_first()

            rows = (
                base.group_by(MovieSeries.id)
                .order_by(order)
                .offset(max(0, int(offset)))
                .limit(max(1, int(limit)))
                .all()
            )
            out: list[dict] = []
            for r in rows:
                if not r.title:
                    continue
                out.append(
                    {
                        "title": r.title,
                        "media_type": (r.media_type or "movie").lower(),
                        "release_year": r.release_year,
                        "vote_average": r.vote_average,
                        "content_title_id": r.content_title_id,
                    }
                )
            return out, total
        finally:
            session.close()

    def get_channel_lane_counts(self) -> dict[str, int]:
        """Active registered channels grouped by content_lane."""
        session = self.get_session()
        try:
            rows = (
                session.query(Channel.content_lane, func.count(Channel.id))
                .filter(Channel.is_active.is_(True))
                .group_by(Channel.content_lane)
                .all()
            )
            return {str(lane or "media"): int(n) for lane, n in rows}
        finally:
            session.close()

    def get_vault_lane_counts(self) -> dict[str, int]:
        session = self.get_session()
        try:
            rows = (
                session.query(FileUpload.content_lane, func.count(FileUpload.id))
                .filter(self._subtitle_exclusion_filter())
                .filter(FileUpload.ingest_state != "skipped")
                .group_by(FileUpload.content_lane)
                .all()
            )
            return {str(lane or "media"): int(n) for lane, n in rows}
        finally:
            session.close()

    def list_vault_collections(
        self, lane: str, *, limit: int = 20, offset: int = 0
    ) -> list[dict]:
        """Grouped titles in a vault lane (courses, series-like groups)."""
        from content_lanes import normalize_lane

        lane = normalize_lane(lane)
        session = self.get_session()
        try:
            title_expr = func.coalesce(
                MovieSeries.tmdb_title,
                MovieSeries.name,
                FileUpload.parsed_name,
                FileUpload.file_name,
            )
            q = (
                session.query(
                    MovieSeries.id.label("content_title_id"),
                    title_expr.label("title"),
                    MovieSeries.media_type,
                    func.count(FileUpload.id).label("file_count"),
                    func.max(FileUpload.uploaded_at).label("latest"),
                )
                .outerjoin(MovieSeries, FileUpload.content_title_id == MovieSeries.id)
                .filter(self._subtitle_exclusion_filter())
                .filter(self._vault_lane_filter(lane))
                .filter(title_expr.isnot(None))
                .group_by(MovieSeries.id, title_expr, MovieSeries.media_type)
                .order_by(func.max(FileUpload.uploaded_at).desc())
            )
            if offset:
                q = q.offset(offset)
            rows = q.limit(limit).all()
            return [
                {
                    "content_title_id": r.content_title_id,
                    "title": r.title,
                    "media_type": (r.media_type or lane).lower(),
                    "file_count": int(r.file_count),
                }
                for r in rows
                if r.title
            ]
        finally:
            session.close()

    def list_vault_files(
        self,
        lane: str,
        *,
        limit: int = 15,
        offset: int = 0,
        content_title_id: int | None = None,
        search: str | None = None,
    ) -> list:
        from content_lanes import normalize_lane

        lane = normalize_lane(lane)
        session = self.get_session()
        try:
            q = (
                session.query(FileUpload)
                .options(joinedload(FileUpload.channel))
                .filter(self._subtitle_exclusion_filter())
                .filter(self._vault_lane_filter(lane))
            )
            if content_title_id is not None:
                q = q.filter(FileUpload.content_title_id == int(content_title_id))
            if search:
                pat = f"%{search.strip().lower()}%"
                q = q.filter(
                    or_(
                        FileUpload.file_name.ilike(pat),
                        FileUpload.parsed_name.ilike(pat),
                        FileUpload.confirmed_name.ilike(pat),
                    )
                )
            return (
                q.order_by(FileUpload.uploaded_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
        finally:
            session.close()

    def count_vault_files(
        self, lane: str, *, content_title_id: int | None = None
    ) -> int:
        from content_lanes import normalize_lane

        session = self.get_session()
        try:
            q = (
                session.query(FileUpload)
                .filter(self._subtitle_exclusion_filter())
                .filter(self._vault_lane_filter(normalize_lane(lane)))
            )
            if content_title_id is not None:
                q = q.filter(FileUpload.content_title_id == int(content_title_id))
            return q.count()
        finally:
            session.close()

    def get_tracking_tv_shows(self, limit: int = 80) -> list[dict]:
        """TV content titles that have at least one indexed upload."""
        session = self.get_session()
        try:
            title_expr = func.coalesce(MovieSeries.tmdb_title, MovieSeries.name)
            rows = (
                session.query(
                    MovieSeries.id,
                    title_expr.label("title"),
                    MovieSeries.tmdb_id,
                    MovieSeries.release_year,
                )
                .join(FileUpload, FileUpload.content_title_id == MovieSeries.id)
                .filter(MovieSeries.media_type == "tv")
                .filter(self._subtitle_exclusion_filter())
                .group_by(MovieSeries.id)
                .order_by(func.max(FileUpload.uploaded_at).desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "content_title_id": r.id,
                    "title": r.title,
                    "tmdb_id": r.tmdb_id,
                    "release_year": r.release_year,
                }
                for r in rows
                if r.title
            ]
        finally:
            session.close()

    def get_indexed_episode_stats(self, content_title_id: int) -> dict:
        """Distinct seasons/episodes indexed for a TV content title."""
        session = self.get_session()
        try:
            rows = (
                session.query(FileUpload.season_number, FileUpload.episode_number)
                .filter(FileUpload.content_title_id == content_title_id)
                .filter(self._subtitle_exclusion_filter())
                .all()
            )
            from tracking_stats import build_indexed_episode_stats

            return build_indexed_episode_stats(rows)
        finally:
            session.close()

    def batch_indexed_episode_stats(self, content_title_ids: list[int]) -> dict[int, dict]:
        """Episode stats for many TV titles in one query."""
        if not content_title_ids:
            return {}
        from collections import defaultdict

        from tracking_stats import build_indexed_episode_stats

        session = self.get_session()
        try:
            rows = (
                session.query(
                    FileUpload.content_title_id,
                    FileUpload.season_number,
                    FileUpload.episode_number,
                )
                .filter(FileUpload.content_title_id.in_([int(i) for i in content_title_ids]))
                .filter(self._subtitle_exclusion_filter())
                .all()
            )
            by_ct: dict[int, list] = defaultdict(list)
            for ct_id, season, episode in rows:
                by_ct[int(ct_id)].append((season, episode))
            return {
                ct_id: build_indexed_episode_stats(pairs)
                for ct_id, pairs in by_ct.items()
            }
        finally:
            session.close()

    def count_tracking_tv_shows(self) -> int:
        return len(self.get_tracking_tv_shows(limit=10000))

    def count_tracking_multipart_movies(self) -> int:
        return len(self.get_tracking_multipart_movies(limit=10000))

    def batch_indexed_episode_stats(self, content_title_ids: list[int]) -> dict[int, dict]:
        """Episode stats for many TV titles in one query."""
        if not content_title_ids:
            return {}
        from collections import defaultdict

        from tracking_stats import build_indexed_episode_stats

        session = self.get_session()
        try:
            rows = (
                session.query(
                    FileUpload.content_title_id,
                    FileUpload.season_number,
                    FileUpload.episode_number,
                )
                .filter(FileUpload.content_title_id.in_([int(i) for i in content_title_ids]))
                .filter(self._subtitle_exclusion_filter())
                .all()
            )
            by_ct: dict[int, list] = defaultdict(list)
            for ct_id, season, episode in rows:
                by_ct[int(ct_id)].append((season, episode))
            return {
                ct_id: build_indexed_episode_stats(pairs)
                for ct_id, pairs in by_ct.items()
            }
        finally:
            session.close()

    def count_tracking_tv_shows(self) -> int:
        return len(self.get_tracking_tv_shows(limit=10000))

    def count_tracking_multipart_movies(self) -> int:
        return len(self.get_tracking_multipart_movies(limit=10000))

    def get_indexed_movie_tmdb_ids(self) -> set[int]:
        """TMDB movie ids with at least one indexed upload."""
        session = self.get_session()
        try:
            rows = (
                session.query(MovieSeries.tmdb_id)
                .join(FileUpload, FileUpload.content_title_id == MovieSeries.id)
                .filter(MovieSeries.media_type == "movie")
                .filter(MovieSeries.tmdb_id.isnot(None))
                .filter(self._subtitle_exclusion_filter())
                .distinct()
                .all()
            )
            return {int(r[0]) for r in rows if r[0] is not None}
        finally:
            session.close()

    def get_tracking_multipart_movies(self, limit: int = 40) -> list[dict]:
        """Movies with franchise_sequence (multi-part single release)."""
        from name_parser import NameParser

        parser = NameParser()
        session = self.get_session()
        try:
            title_expr = func.coalesce(MovieSeries.tmdb_title, MovieSeries.name)
            rows = (
                session.query(
                    MovieSeries.id,
                    title_expr.label("title"),
                    MovieSeries.franchise_sequence,
                    MovieSeries.release_year,
                )
                .join(FileUpload, FileUpload.content_title_id == MovieSeries.id)
                .filter(MovieSeries.media_type == "movie")
                .filter(MovieSeries.franchise_sequence.isnot(None))
                .filter(self._subtitle_exclusion_filter())
                .group_by(MovieSeries.id)
                .order_by(func.max(FileUpload.uploaded_at).desc())
                .limit(limit)
                .all()
            )
            out = []
            for r in rows:
                uploads = (
                    session.query(FileUpload.file_name)
                    .filter_by(content_title_id=r.id)
                    .filter(self._subtitle_exclusion_filter())
                    .all()
                )
                part_nums: set[int] = set()
                total_parts = None
                if r.franchise_sequence is not None:
                    part_nums.add(int(r.franchise_sequence))
                for (fname,) in uploads:
                    pi = parser.extract_part_info(fname or "")
                    if pi:
                        part_nums.add(int(pi["part"]))
                        if pi.get("total"):
                            total_parts = max(total_parts or 0, int(pi["total"]))
                out.append(
                    {
                        "content_title_id": r.id,
                        "title": r.title,
                        "release_year": r.release_year,
                        "indexed_parts": part_nums,
                        "total_parts": total_parts,
                    }
                )
            return out
        finally:
            session.close()

    def get_movie_rows_for_tracking(self, limit: int = 120) -> list[dict]:
        """Movies with indexed uploads (for TMDB collection grouping)."""
        session = self.get_session()
        try:
            title_expr = func.coalesce(MovieSeries.tmdb_title, MovieSeries.name)
            rows = (
                session.query(
                    MovieSeries.id,
                    title_expr.label("title"),
                    MovieSeries.tmdb_id,
                    MovieSeries.franchise_sequence,
                )
                .join(FileUpload, FileUpload.content_title_id == MovieSeries.id)
                .filter(MovieSeries.media_type == "movie")
                .filter(MovieSeries.tmdb_id.isnot(None))
                .filter(self._subtitle_exclusion_filter())
                .group_by(MovieSeries.id)
                .order_by(func.max(FileUpload.uploaded_at).desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "content_title_id": r.id,
                    "title": r.title,
                    "tmdb_id": int(r.tmdb_id),
                    "franchise_sequence": r.franchise_sequence,
                }
                for r in rows
                if r.tmdb_id
            ]
        finally:
            session.close()

    def set_upload_message_status(
        self,
        upload_id: int,
        available: bool,
        *,
        checked_at: datetime | None = None,
    ) -> None:
        session = self.get_session()
        try:
            upload = session.query(FileUpload).filter_by(id=upload_id).first()
            if not upload:
                return
            upload.message_available = bool(available)
            upload.message_checked_at = checked_at or datetime.utcnow()
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("set_upload_message_status failed: %s", e)
        finally:
            session.close()

    def count_unavailable_uploads(self, channel_ids=None) -> int:
        session = self.get_session()
        try:
            query = (
                session.query(FileUpload)
                .filter(FileUpload.message_available.is_(False))
                .filter(self._subtitle_exclusion_filter())
            )
            if channel_ids:
                query = query.filter(
                    (FileUpload.channel_id.in_(channel_ids))
                    | (FileUpload.source_channel_id.in_(channel_ids))
                )
            return query.count()
        finally:
            session.close()

    def get_unavailable_uploads(self, limit: int = 40, channel_ids=None) -> list:
        session = self.get_session()
        try:
            query = (
                session.query(FileUpload)
                .options(
                    joinedload(FileUpload.channel),
                    joinedload(FileUpload.source_channel),
                    joinedload(FileUpload.content_title),
                )
                .filter(FileUpload.message_available.is_(False))
                .filter(self._subtitle_exclusion_filter())
                .order_by(FileUpload.message_checked_at.desc())
            )
            if channel_ids:
                query = query.filter(
                    (FileUpload.channel_id.in_(channel_ids))
                    | (FileUpload.source_channel_id.in_(channel_ids))
                )
            rows = query.limit(limit).all()
            return self._detach_upload_graph(session, rows)
        finally:
            session.close()

    def get_uploads_for_verify(
        self, *, limit: int = 500, stale_hours: float = 24
    ) -> list:
        """Uploads that were never checked or checked longer than stale_hours ago."""
        session = self.get_session()
        try:
            query = (
                session.query(FileUpload)
                .filter(self._subtitle_exclusion_filter())
                .order_by(
                    case((FileUpload.message_checked_at.is_(None), 0), else_=1),
                    FileUpload.message_checked_at.asc().nulls_first(),
                    FileUpload.uploaded_at.desc(),
                )
            )
            if stale_hours > 0:
                cutoff = datetime.utcnow() - timedelta(hours=stale_hours)
                query = query.filter(
                    or_(
                        FileUpload.message_checked_at.is_(None),
                        FileUpload.message_checked_at < cutoff,
                    )
                )
            rows = query.limit(limit).all()
            for row in rows:
                session.expunge(row)
            return rows
        finally:
            session.close()

    def get_library_uploads_for_content(
        self,
        content_title_id: int,
        channel_ids=None,
        *,
        library_only: bool = True,
        browse_scope: str | None = None,
        watchable_only: bool = False,
        season_number: int | None = None,
    ) -> list:
        """Library-visible uploads for a content title, with channel relations loaded."""
        session = self.get_session()
        try:
            query = (
                session.query(FileUpload)
                .options(
                    joinedload(FileUpload.channel),
                    joinedload(FileUpload.source_channel),
                )
                .filter(FileUpload.content_title_id == content_title_id)
                .filter(self._subtitle_exclusion_filter())
            )
            if library_only:
                scope = (browse_scope or "public").lower()
                if scope == "media":
                    query = query.filter(self._media_browse_filter())
                elif scope == "course":
                    query = query.filter(self._course_library_filter())
                elif scope == "adult":
                    query = query.filter(self._adult_library_filter())
                elif scope == "archive":
                    query = query.filter(self._archive_library_filter())
                elif scope == "shortform":
                    query = query.filter(self._shortform_library_filter())
                elif scope in ("non_catalog", "non-catalog", "noncatalog"):
                    query = query.join(
                        MovieSeries, FileUpload.content_title_id == MovieSeries.id
                    ).filter(
                        MovieSeries.indexed_only.is_(True),
                        FileUpload.is_confirmed.is_(True),
                        or_(
                            FileUpload.ingest_state.is_(None),
                            FileUpload.ingest_state != "skipped",
                        ),
                    )
                else:
                    query = query.filter(self._public_library_filter())
            if channel_ids:
                query = query.filter(
                    (FileUpload.channel_id.in_(channel_ids))
                    | (FileUpload.source_channel_id.in_(channel_ids))
                )
            if watchable_only:
                query = query.filter(
                    or_(
                        FileUpload.message_available.is_(None),
                        FileUpload.message_available.is_(True),
                    )
                )
            if season_number is not None:
                sn = int(season_number)
                query = query.filter(
                    or_(
                        FileUpload.season_number == sn,
                        and_(FileUpload.season_number.is_(None), sn == 1),
                    )
                )
            rows = (
                query.order_by(
                    FileUpload.season_number.asc().nulls_last(),
                    FileUpload.episode_number.asc().nulls_last(),
                    FileUpload.uploaded_at.desc(),
                )
                .all()
            )
            return self._detach_upload_graph(session, rows)
        finally:
            session.close()

    def list_uploads_for_content_admin(self, content_title_id: int) -> list:
        """All non-subtitle uploads for a title (admin remap / lane tools)."""
        session = self.get_session()
        try:
            rows = (
                session.query(FileUpload)
                .options(
                    joinedload(FileUpload.channel),
                    joinedload(FileUpload.source_channel),
                )
                .filter(FileUpload.content_title_id == int(content_title_id))
                .filter(self._subtitle_exclusion_filter())
                .order_by(
                    FileUpload.season_number.asc().nulls_last(),
                    FileUpload.episode_number.asc().nulls_last(),
                    FileUpload.uploaded_at.desc(),
                )
                .all()
            )
            return self._detach_upload_graph(session, rows)
        finally:
            session.close()

    def set_upload_content_lane(self, upload_id: int, lane: str) -> FileUpload | None:
        """Set content lane on one upload (e.g. move to adult vault)."""
        from content_lanes import LANE_ADULT, LANE_MEDIA, normalize_lane

        session = self.get_session()
        try:
            upload = session.query(FileUpload).filter_by(id=int(upload_id)).first()
            if not upload:
                return None
            lane = normalize_lane(lane)
            upload.content_lane = lane
            if lane == LANE_ADULT:
                upload.library_visible = False
                upload.distribution_approved = False
                upload.needs_confirmation = False
                upload.is_confirmed = True
            elif lane == LANE_MEDIA:
                upload.distribution_approved = bool(upload.library_visible)
            session.commit()
            return upload
        except Exception as e:
            session.rollback()
            logger.error("set_upload_content_lane: %s", e)
            return None
        finally:
            session.close()

    def queue_upload_for_tmdb_pending(self, upload_id: int) -> FileUpload | None:
        """Move a confirmed upload back to pending for TMDB mapping (media lane)."""
        from content_lanes import LANE_MEDIA, normalize_lane

        session = self.get_session()
        try:
            upload = session.query(FileUpload).filter_by(id=int(upload_id)).first()
            if not upload:
                return None
            if (upload.ingest_state or "") == "skipped":
                return None
            upload.content_lane = LANE_MEDIA
            upload.is_confirmed = False
            upload.needs_confirmation = True
            upload.library_visible = False
            upload.distribution_approved = False
            upload.pending_deferred_at = None
            upload.ingest_state = "normal"
            session.commit()
            return upload
        except Exception as e:
            session.rollback()
            logger.error("queue_upload_for_tmdb_pending: %s", e)
            return None
        finally:
            session.close()

    def get_distinct_titles(self, limit=25, channel_ids=None, *, library_only: bool = True):
        """Recently indexed title names for browse (legacy string list)."""
        return [
            e["title"]
            for e in self.get_library_browse_entries(
                limit=limit, channel_ids=channel_ids, library_only=library_only
            )
        ]

    def get_index_summary(self):
        """Counts for browse / stats menus."""
        session = self.get_session()
        try:
            base = session.query(FileUpload).filter(self._subtitle_exclusion_filter())
            total = base.count()
            confirmed = base.filter_by(is_confirmed=True).count()
            pending = base.filter_by(needs_confirmation=True, is_confirmed=False).filter(
                self._tmdb_pending_filter()
            ).count()
            unique = (
                session.query(FileUpload.content_title_id)
                .filter(self._subtitle_exclusion_filter())
                .filter(self._library_visible_filter())
                .distinct()
                .count()
            )
            return {
                "total_uploads": total,
                "confirmed": confirmed,
                "pending": pending,
                "unique_titles": unique,
            }
        finally:
            session.close()

    def add_file_upload(
        self,
        channel_id,
        message_id,
        file_name,
        file_size=None,
        file_id=None,
        parsed_name=None,
        auto_confirm=False,
        source_channel_id=None,
        content_title_id=None,
        season_number=None,
        episode_number=None,
        episode_title=None,
        library_visible=False,
        *,
        content_fingerprint=None,
        file_unique_id=None,
        file_kind="video",
        content_lane="media",
        ingest_state="normal",
        duplicate_of_upload_id=None,
        upload_job_item_id=None,
        module_name=None,
        lesson_sequence=None,
        pipeline_route_status=None,
        pipeline_route_target_channel_id=None,
    ):
        """Add a new file upload"""

        @_sqlite_write_retry
        def _write():
            session = self.get_session()
            try:
                lane = (content_lane or "media").lower()
                if ingest_state == "duplicate_hold":
                    needs_confirmation = False
                    is_confirmed = False
                    show_in_library = False
                else:
                    needs_confirmation = not (auto_confirm and parsed_name)
                    is_confirmed = auto_confirm and parsed_name is not None
                    show_in_library = bool(library_visible and is_confirmed)

                upload = FileUpload(
                    channel_id=str(channel_id),
                    message_id=message_id,
                    file_name=file_name,
                    file_size=file_size,
                    file_id=file_id,
                    parsed_name=parsed_name,
                    needs_confirmation=needs_confirmation,
                    is_confirmed=is_confirmed,
                    library_visible=show_in_library,
                    confirmed_name=parsed_name if is_confirmed else None,
                    source_channel_id=str(source_channel_id) if source_channel_id else None,
                    content_title_id=content_title_id,
                    season_number=season_number,
                    episode_number=episode_number,
                    episode_title=episode_title,
                    content_fingerprint=content_fingerprint,
                    file_unique_id=file_unique_id,
                    file_kind=file_kind or "video",
                    content_lane=lane,
                    ingest_state=ingest_state or "normal",
                    duplicate_of_upload_id=duplicate_of_upload_id,
                    upload_job_item_id=upload_job_item_id,
                    module_name=module_name,
                    lesson_sequence=lesson_sequence,
                    distribution_approved=bool(
                        show_in_library and (lane or "media") == "media"
                    ),
                    pipeline_route_status=pipeline_route_status,
                    pipeline_route_target_channel_id=(
                        str(pipeline_route_target_channel_id)
                        if pipeline_route_target_channel_id
                        else None
                    ),
                )
                session.add(upload)
                session.commit()
                return self._upload_for_return(session, upload)
            except Exception as e:
                session.rollback()
                raise e
            finally:
                session.close()

        return _write()

    def set_upload_pipeline_route(
        self,
        upload_id: int,
        *,
        status: str | None,
        target_channel_id: str | None = None,
        error: str | None = None,
    ) -> bool:
        session = self.get_session()
        try:
            row = session.query(FileUpload).filter_by(id=int(upload_id)).first()
            if not row:
                return False
            row.pipeline_route_status = status
            if target_channel_id is not None:
                row.pipeline_route_target_channel_id = (
                    str(target_channel_id) if target_channel_id else None
                )
            if error is not None:
                row.pipeline_route_error = (error or "")[:500] or None
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error("set_upload_pipeline_route: %s", e)
            return False
        finally:
            session.close()

    def relocate_upload_message(
        self, upload_id: int, channel_id: str, message_id: int
    ) -> bool:
        session = self.get_session()
        try:
            row = session.query(FileUpload).filter_by(id=int(upload_id)).first()
            if not row:
                return False
            row.channel_id = str(channel_id)
            row.message_id = int(message_id)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error("relocate_upload_message: %s", e)
            return False
        finally:
            session.close()

    def find_upload_pending_route(
        self, fingerprint: str, target_channel_id: str
    ):
        if not fingerprint or not target_channel_id:
            return None
        session = self.get_session()
        try:
            return (
                session.query(FileUpload)
                .filter_by(
                    content_fingerprint=fingerprint,
                    pipeline_route_status="pending",
                    pipeline_route_target_channel_id=str(target_channel_id),
                )
                .order_by(FileUpload.id.desc())
                .first()
            )
        finally:
            session.close()

    def list_pipeline_route_queue(self, *, limit: int = 20) -> list:
        session = self.get_session()
        try:
            return (
                session.query(FileUpload)
                .filter(FileUpload.pipeline_route_status == "pending")
                .order_by(FileUpload.uploaded_at.desc())
                .limit(limit)
                .all()
            )
        finally:
            session.close()
    
    def confirm_file_name(self, file_id, confirmed_name):
        """Confirm the name for a file"""
        session = self.get_session()
        try:
            upload = session.query(FileUpload).filter_by(id=file_id).first()
            if upload:
                upload.confirmed_name = confirmed_name
                upload.is_confirmed = True
                upload.needs_confirmation = False
                session.commit()
                return upload
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def apply_tmdb_pick(
        self,
        file_id: int,
        *,
        tmdb_id: int | None = None,
        tmdb_title: str | None = None,
        media_type: str = "movie",
        local_name: str | None = None,
        parsed_name: str | None = None,
        season_number=None,
        episode_number=None,
        episode_title=None,
        content_title_id: int | None = None,
        release_year=None,
        franchise_sequence=None,
        poster_path=None,
        overview=None,
        vote_average=None,
        genres=None,
        library_visible: bool = True,
        catalog_excluded: bool = False,
        indexed_only: bool = False,
    ):
        """Link file to TMDB (or custom title) and mark confirmed."""
        session = self.get_session()
        try:
            upload = session.query(FileUpload).filter_by(id=file_id).first()
            if not upload:
                return None

            ct = None
            if content_title_id:
                ct = session.query(MovieSeries).filter_by(id=content_title_id).first()
            if not ct and (local_name or tmdb_title):
                ct_row = self.upsert_content_title(
                    local_name=local_name or tmdb_title or "",
                    media_type=media_type,
                    tmdb_id=tmdb_id,
                    tmdb_title=tmdb_title,
                    release_year=release_year,
                    franchise_sequence=franchise_sequence,
                    poster_path=poster_path,
                    overview=overview,
                    vote_average=vote_average,
                    genres=genres,
                    catalog_excluded=catalog_excluded,
                    indexed_only=indexed_only,
                )
                if ct_row:
                    ct = session.query(MovieSeries).filter_by(id=ct_row.id).first()
            elif ct:
                ct.catalog_excluded = bool(catalog_excluded)
                if indexed_only:
                    ct.indexed_only = True
                elif not catalog_excluded:
                    ct.indexed_only = False

            if ct:
                upload.content_title_id = ct.id
            if season_number is not None:
                upload.season_number = season_number
            if episode_number is not None:
                upload.episode_number = episode_number
            if episode_title is not None:
                upload.episode_title = episode_title

            display = parsed_name or tmdb_title or local_name or upload.parsed_name
            upload.parsed_name = display
            upload.confirmed_name = display
            upload.is_confirmed = True
            upload.needs_confirmation = False
            upload.library_visible = bool(library_visible)
            upload.pending_deferred_at = None
            session.commit()
            session.refresh(upload)
            return upload
        except Exception as e:
            session.rollback()
            logger.error("apply_tmdb_pick failed: %s", e)
            raise
        finally:
            session.close()

    def defer_pending_files(self, file_ids: list[int]) -> int:
        """Move pending files to the end of the admin queue (Skip for now)."""
        if not file_ids:
            return 0
        session = self.get_session()
        try:
            now = datetime.utcnow()
            n = (
                session.query(FileUpload)
                .filter(
                    FileUpload.id.in_(file_ids),
                    FileUpload.needs_confirmation.is_(True),
                    FileUpload.is_confirmed.is_(False),
                )
                .update({FileUpload.pending_deferred_at: now}, synchronize_session=False)
            )
            session.commit()
            return int(n or 0)
        except Exception as e:
            session.rollback()
            logger.error("defer_pending_files failed: %s", e)
            raise
        finally:
            session.close()

    def count_pending_confirmations(self) -> int:
        session = self.get_session()
        try:
            return (
                session.query(FileUpload)
                .filter_by(needs_confirmation=True, is_confirmed=False)
                .filter(self._tmdb_pending_filter())
                .count()
            )
        finally:
            session.close()

    def auto_confirm_non_tmdb_pending(self) -> int:
        """Clear pending state for images/GIFs and legacy Telegram photo_*.jpg rows."""
        import re

        photo_re = re.compile(r"^photo_\d+\.(jpg|jpeg|png|webp)$", re.I)
        session = self.get_session()
        try:
            rows = (
                session.query(FileUpload)
                .filter_by(needs_confirmation=True, is_confirmed=False)
                .all()
            )
            n = 0
            for upload in rows:
                kind = (upload.file_kind or "").lower()
                if kind not in ("image", "gif") and not photo_re.match(
                    upload.file_name or ""
                ):
                    continue
                if kind not in ("image", "gif"):
                    upload.file_kind = "image"
                label = (upload.parsed_name or Path(upload.file_name).stem)[:200]
                upload.parsed_name = label
                upload.needs_confirmation = False
                upload.is_confirmed = True
                upload.confirmed_name = label
                upload.library_visible = False
                upload.tmdb_retry_after = None
                upload.tmdb_retry_count = 0
                n += 1
            if n:
                session.commit()
            return n
        except Exception as e:
            session.rollback()
            logger.error("auto_confirm_non_tmdb_pending failed: %s", e)
            return 0
        finally:
            session.close()
    
    def get_pending_confirmations(self, limit=50):
        """Get files that need admin confirmation"""
        session = self.get_session()
        try:
            q = (
                session.query(FileUpload)
                .filter_by(needs_confirmation=True, is_confirmed=False)
                .filter(self._tmdb_pending_filter())
                .order_by(
                    FileUpload.pending_deferred_at.asc().nullsfirst(),
                    FileUpload.uploaded_at.desc(),
                )
            )
            if limit is not None:
                q = q.limit(limit)
            return q.all()
        finally:
            session.close()
    
    def list_pending_confirmations_page(
        self, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[dict], int]:
        session = self.get_session()
        try:
            base = (
                session.query(FileUpload)
                .options(joinedload(FileUpload.channel))
                .filter_by(needs_confirmation=True, is_confirmed=False)
                .filter(self._tmdb_pending_filter())
            )
            total = base.count()
            rows = (
                base.order_by(
                    FileUpload.pending_deferred_at.asc().nullsfirst(),
                    FileUpload.uploaded_at.desc(),
                )
                .offset(max(0, int(offset)))
                .limit(max(1, int(limit)))
                .all()
            )
            items = []
            for u in rows:
                ch = u.channel
                items.append(
                    {
                        "id": u.id,
                        "file_name": u.file_name,
                        "parsed_name": u.parsed_name or u.file_name,
                        "content_lane": u.content_lane or "media",
                        "channel_id": u.channel_id,
                        "channel_title": (
                            ch.channel_title if ch else str(u.channel_id)
                        ),
                        "file_size": u.file_size,
                        "uploaded_at": (
                            u.uploaded_at.isoformat() if u.uploaded_at else None
                        ),
                        "deferred": bool(u.pending_deferred_at),
                    }
                )
            return items, int(total)
        finally:
            session.close()

    def skip_pending_upload(self, upload_id: int) -> bool:
        session = self.get_session()
        try:
            row = session.query(FileUpload).filter_by(id=int(upload_id)).first()
            if not row:
                return False
            row.needs_confirmation = False
            row.is_confirmed = False
            row.ingest_state = "skipped"
            row.library_visible = False
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error("skip_pending_upload failed: %s", e)
            return False
        finally:
            session.close()

    def set_upload_request_status(self, request_id: int, status: str) -> bool:
        session = self.get_session()
        try:
            row = session.query(UploadRequest).filter_by(id=int(request_id)).first()
            if not row:
                return False
            row.status = str(status)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error("set_upload_request_status failed: %s", e)
            return False
        finally:
            session.close()

    def refresh_pending_upload_from_meta(self, upload_id: int, meta: dict) -> str | None:
        """
        Re-apply TMDB index metadata to one pending upload.

        Returns ``matched``, ``still_pending``, or None if the row is missing / not pending.
        """
        from title_indexer import apply_index_metadata_to_upload

        session = self.get_session()
        try:
            upload = session.query(FileUpload).filter_by(id=upload_id).first()
            if not upload or not upload.needs_confirmation or upload.is_confirmed:
                return None
            outcome = apply_index_metadata_to_upload(upload, meta)
            session.commit()
            return outcome
        except Exception as e:
            session.rollback()
            logger.error("refresh_pending_upload_from_meta failed for #%s: %s", upload_id, e)
            raise
        finally:
            session.close()

    def get_file_upload(self, file_id: int) -> FileUpload | None:
        session = self.get_session()
        try:
            upload = (
                session.query(FileUpload)
                .options(
                    joinedload(FileUpload.channel),
                    joinedload(FileUpload.source_channel),
                )
                .filter_by(id=file_id)
                .first()
            )
            if upload is None:
                return None
            self._detach_upload_graph(session, [upload])
            return upload
        finally:
            session.close()

    def find_subtitle_sidecar_uploads(self, upload) -> list:
        """Subtitle files in the same channel(s) that share the video filename stem."""
        from pathlib import Path

        from sqlalchemy import or_

        from media_utils import SUBTITLE_EXTENSIONS

        if not upload or not upload.file_name:
            return []
        stem = Path(upload.file_name).stem.strip()
        if len(stem) < 2:
            return []
        channel_ids: list[int] = []
        for cid in (upload.source_channel_id, upload.channel_id):
            if cid and int(cid) not in channel_ids:
                channel_ids.append(int(cid))
        if not channel_ids:
            return []
        name_filters = [
            FileUpload.file_name.ilike(f"{stem}%{ext}") for ext in SUBTITLE_EXTENSIONS
        ]
        session = self.get_session()
        try:
            rows = (
                session.query(FileUpload)
                .filter(FileUpload.id != int(upload.id))
                .filter(FileUpload.channel_id.in_(channel_ids))
                .filter(or_(*name_filters))
                .order_by(FileUpload.uploaded_at.desc())
                .limit(8)
                .all()
            )
            self._detach_upload_graph(session, rows)
            return rows
        finally:
            session.close()

    def get_title_hint(self, match_key: str) -> TitleMappingHint | None:
        if not match_key:
            return None
        session = self.get_session()
        try:
            return (
                session.query(TitleMappingHint)
                .filter_by(match_key=match_key)
                .first()
            )
        finally:
            session.close()

    def save_title_hint(
        self,
        match_key: str,
        *,
        tmdb_id: int | None,
        tmdb_title: str | None,
        media_type: str = "tv",
    ) -> None:
        if not match_key:
            return
        session = self.get_session()
        try:
            row = session.query(TitleMappingHint).filter_by(match_key=match_key).first()
            if not row:
                row = TitleMappingHint(match_key=match_key)
                session.add(row)
            row.tmdb_id = tmdb_id
            row.tmdb_title = tmdb_title
            row.media_type = media_type or "tv"
            row.updated_at = datetime.utcnow()
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("save_title_hint failed: %s", e)
        finally:
            session.close()
    
    def search_files(self, search_term, *, library_only: bool = True):
        """Search for files by name"""
        session = self.get_session()
        try:
            search_pattern = f"%{search_term.lower()}%"
            query = session.query(FileUpload).filter(
                (FileUpload.confirmed_name.ilike(search_pattern))
                | (FileUpload.parsed_name.ilike(search_pattern))
                | (FileUpload.file_name.ilike(search_pattern))
            ).filter(self._subtitle_exclusion_filter())
            if library_only:
                query = query.filter(self._public_library_filter())
            results = query.all()
            return results
        finally:
            session.close()
    
    def get_upload_stats(self, movie_name, *, library_only: bool = True):
        """Get statistics for a movie/series across all channels"""
        session = self.get_session()
        try:
            # Get all uploads with this name (confirmed or parsed)
            # Eagerly load channel relationship to avoid lazy loading issues
            query = (
                session.query(FileUpload)
                .options(
                    joinedload(FileUpload.channel),
                    joinedload(FileUpload.source_channel),
                )
                .filter(self._movie_name_filter(movie_name))
                .filter(self._subtitle_exclusion_filter())
            )
            if library_only:
                query = query.filter(self._public_library_filter())
            uploads = query.all()
            channel_stats = self._build_channel_stats(uploads)
            return {"total_uploads": len(uploads), "channels": channel_stats}
        finally:
            session.close()
    
    def get_library_view(self, movie_name, channel_ids=None, *, library_only: bool = True):
        """Get detailed library view for a movie/series showing all uploads"""
        session = self.get_session()
        try:
            query = (
                session.query(FileUpload)
                .options(
                    joinedload(FileUpload.channel),
                    joinedload(FileUpload.source_channel),
                )
                .filter(self._movie_name_filter(movie_name))
                .filter(self._subtitle_exclusion_filter())
            )
            if library_only:
                query = query.filter(self._public_library_filter())
            if channel_ids:
                query = query.filter(
                    (FileUpload.channel_id.in_(channel_ids))
                    | (FileUpload.source_channel_id.in_(channel_ids))
                )
            uploads = query.order_by(FileUpload.uploaded_at.desc()).all()
            upload_data_list = []
            for upload in uploads:
                src = upload.source_channel
                ch = upload.channel
                upload_data_list.append(
                    {
                        "id": upload.id,
                        "file_name": upload.file_name,
                        "uploaded_at": upload.uploaded_at,
                        "is_confirmed": upload.is_confirmed,
                        "message_id": upload.message_id,
                        "channel_id": upload.channel_id,
                        "channel_title": ch.channel_title if ch else None,
                        "channel_username": ch.channel_username if ch else None,
                        "source_channel_id": upload.source_channel_id,
                        "source_channel_title": src.channel_title if src else None,
                        "source_channel_username": src.channel_username if src else None,
                    }
                )
            return upload_data_list
        finally:
            session.close()
    
    def file_exists(self, channel_id, message_id):
        """Check if a file upload already exists"""
        session = self.get_session()
        try:
            return session.query(FileUpload).filter_by(
                channel_id=str(channel_id),
                message_id=message_id
            ).first() is not None
        finally:
            session.close()
    
    def _ensure_default_list(self):
        """Create default 'All Channels' list if it doesn't exist"""
        session = self.get_session()
        try:
            default_list = session.query(CustomList).filter_by(is_default=True).first()
            if not default_list:
                default_list = CustomList(
                    list_name="All Channels",
                    channel_ids="",  # Empty means all channels
                    is_default=True
                )
                session.add(default_list)
                session.commit()
        except Exception as e:
            logger.error(f"Error creating default list: {e}")
            session.rollback()
        finally:
            session.close()
    
    def auto_register_channel(
        self,
        channel_id,
        channel_username=None,
        channel_title=None,
        *,
        bot_can_post=False,
    ):
        """Automatically register a channel when bot detects it"""
        session = self.get_session()
        try:
            # Check if channel already exists
            existing = session.query(Channel).filter_by(channel_id=str(channel_id)).first()
            if existing:
                # Update if needed
                if not existing.is_active:
                    existing.is_active = True
                if channel_title and not existing.channel_title:
                    existing.channel_title = channel_title
                if channel_username and not existing.channel_username:
                    existing.channel_username = channel_username
                if bot_can_post:
                    existing.bot_can_post = True
                self._sync_telethon_watch_on_channel(
                    existing, bot_can_post=bool(existing.bot_can_post)
                )
                session.commit()
                return self._channel_for_return(session, existing)
            
            # Create new channel
            channel = Channel(
                channel_id=str(channel_id),
                channel_username=channel_username,
                channel_title=channel_title,
                is_active=True,
                bot_can_post=bool(bot_can_post),
            )
            self._sync_telethon_watch_on_channel(
                channel, bot_can_post=bool(bot_can_post)
            )
            session.add(channel)
            session.commit()
            logger.info(f"Auto-registered channel: {channel_title or channel_id}")
            return self._channel_for_return(session, channel)
        except Exception as e:
            session.rollback()
            logger.error(f"Error auto-registering channel: {e}")
            raise
        finally:
            session.close()
    
    def create_custom_list(self, list_name, channel_ids, created_by):
        """Create a custom list"""
        session = self.get_session()
        try:
            # Check if list name already exists
            existing = session.query(CustomList).filter_by(list_name=list_name).first()
            if existing:
                return None  # List already exists
            
            # Convert channel_ids list to comma-separated string
            channel_ids_str = ','.join(str(cid) for cid in channel_ids)
            
            custom_list = CustomList(
                list_name=list_name,
                channel_ids=channel_ids_str,
                created_by=created_by
            )
            session.add(custom_list)
            session.commit()
            return custom_list
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()
    
    def get_custom_list(self, list_name):
        """Get a custom list by name"""
        session = self.get_session()
        try:
            return session.query(CustomList).filter_by(list_name=list_name).first()
        finally:
            session.close()
    
    def get_all_custom_lists(self):
        """Get all custom lists"""
        session = self.get_session()
        try:
            return session.query(CustomList).all()
        finally:
            session.close()
    
    def delete_custom_list(self, list_name):
        """Delete a custom list (cannot delete default list)"""
        session = self.get_session()
        try:
            custom_list = session.query(CustomList).filter_by(list_name=list_name).first()
            if custom_list:
                if custom_list.is_default:
                    return False  # Cannot delete default list
                session.delete(custom_list)
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()
    
    def get_channels_for_list(self, list_name):
        """Get channel IDs for a custom list"""
        session = self.get_session()
        try:
            custom_list = session.query(CustomList).filter_by(list_name=list_name).first()
            if not custom_list:
                return None
            
            if custom_list.is_default or not custom_list.channel_ids:
                # Default list or empty = all channels
                channels = session.query(Channel).filter_by(is_active=True).all()
                return [str(c.channel_id) for c in channels]
            
            # Return channel IDs from list
            return [cid.strip() for cid in custom_list.channel_ids.split(',') if cid.strip()]
        finally:
            session.close()
    
    def search_files_in_channels(self, search_term, channel_ids=None, *, library_only: bool = True):
        """Search for files in specific channels"""
        session = self.get_session()
        try:
            search_pattern = f"%{search_term.lower()}%"
            query = session.query(FileUpload).filter(
                (FileUpload.confirmed_name.ilike(search_pattern))
                | (FileUpload.parsed_name.ilike(search_pattern))
                | (FileUpload.file_name.ilike(search_pattern))
            ).filter(self._subtitle_exclusion_filter())
            if library_only:
                query = query.filter(self._public_library_filter())

            if channel_ids:
                query = query.filter(
                    (FileUpload.channel_id.in_(channel_ids))
                    | (FileUpload.source_channel_id.in_(channel_ids))
                )
            
            return query.all()
        finally:
            session.close()
    
    def get_upload_stats_in_channels(self, movie_name, channel_ids=None, *, library_only: bool = True):
        """Get statistics for a movie/series in specific channels"""
        session = self.get_session()
        try:
            query = (
                session.query(FileUpload)
                .options(
                    joinedload(FileUpload.channel),
                    joinedload(FileUpload.source_channel),
                )
                .filter(self._movie_name_filter(movie_name))
                .filter(self._subtitle_exclusion_filter())
            )
            if library_only:
                query = query.filter(self._public_library_filter())
            if channel_ids:
                query = query.filter(
                    (FileUpload.channel_id.in_(channel_ids))
                    | (FileUpload.source_channel_id.in_(channel_ids))
                )
            uploads = query.all()
            channel_stats = self._build_channel_stats(uploads)
            return {"total_uploads": len(uploads), "channels": channel_stats}
        finally:
            session.close()

    def get_channel_lane(self, channel_id: str) -> str:
        from content_lanes import normalize_lane

        session = self.get_session()
        try:
            ch = session.query(Channel).filter_by(channel_id=str(channel_id)).first()
            if ch and getattr(ch, "content_lane", None):
                return normalize_lane(ch.content_lane)
            return normalize_lane(None)
        finally:
            session.close()

    def set_channel_lane(self, channel_id: str, lane: str, *, admin_only: bool | None = None) -> bool:
        from content_lanes import lane_defaults, normalize_lane

        lane = normalize_lane(lane)
        session = self.get_session()
        try:
            ch = session.query(Channel).filter_by(channel_id=str(channel_id)).first()
            if not ch:
                return False
            ch.content_lane = lane
            ch.admin_only = (
                bool(lane_defaults(lane)["admin_only"])
                if admin_only is None
                else bool(admin_only)
            )
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error("set_channel_lane: %s", e)
            return False
        finally:
            session.close()

    def fingerprints_in_library(self, fingerprints: list[str]) -> set[str]:
        """Read-only batch: which content fingerprints already exist (for job planning)."""
        unique = [f for f in {f for f in fingerprints if f}]
        if not unique:
            return set()
        session = self.get_session()
        try:
            found: set[str] = set()
            for i in range(0, len(unique), _FINGERPRINT_BATCH):
                chunk = unique[i : i + _FINGERPRINT_BATCH]
                rows = (
                    session.query(FileUpload.content_fingerprint)
                    .filter(FileUpload.content_fingerprint.in_(chunk))
                    .filter(FileUpload.ingest_state != "skipped")
                    .filter(self._subtitle_exclusion_filter())
                    .distinct()
                    .all()
                )
                found.update(r[0] for r in rows if r[0])
            return found
        finally:
            session.close()

    def map_fingerprints_to_upload_ids(self, fingerprints: list[str]) -> dict[str, int]:
        """Read-only batch: fingerprint → one existing upload id (for job duplicate_of)."""
        unique = [f for f in {f for f in fingerprints if f}]
        if not unique:
            return {}
        session = self.get_session()
        try:
            out: dict[str, int] = {}
            for i in range(0, len(unique), _FINGERPRINT_BATCH):
                chunk = unique[i : i + _FINGERPRINT_BATCH]
                rows = (
                    session.query(FileUpload.content_fingerprint, func.min(FileUpload.id))
                    .filter(FileUpload.content_fingerprint.in_(chunk))
                    .filter(FileUpload.ingest_state != "skipped")
                    .filter(self._subtitle_exclusion_filter())
                    .group_by(FileUpload.content_fingerprint)
                    .all()
                )
                for fp, uid in rows:
                    if fp and uid:
                        out[str(fp)] = int(uid)
            return out
        finally:
            session.close()

    def find_upload_id_by_channel_basename_size(
        self,
        channel_id: str,
        file_name: str,
        file_size: int | None,
    ) -> int | None:
        """Match an indexed post in a channel by normalized basename (+ optional size)."""
        from fingerprint import normalize_basename

        norm = normalize_basename(file_name)
        if not norm or not channel_id:
            return None
        session = self.get_session()
        try:
            q = (
                session.query(FileUpload)
                .filter(FileUpload.channel_id == str(channel_id))
                .filter(FileUpload.ingest_state != "skipped")
                .filter(self._subtitle_exclusion_filter())
            )
            if file_size is not None:
                q = q.filter(FileUpload.file_size == int(file_size))
            rows = q.order_by(FileUpload.uploaded_at.desc()).limit(300).all()
            for row in rows:
                if normalize_basename(row.file_name or "") == norm:
                    return int(row.id)
            return None
        finally:
            session.close()

    def find_upload_via_prior_job_item(
        self,
        channel_id: str,
        file_name: str,
        file_size: int | None,
    ) -> int | None:
        """Link via a previous upload job item (same target channel, already indexed)."""
        from fingerprint import compute_content_fingerprint, normalize_basename

        norm = normalize_basename(file_name)
        leg_fp = compute_content_fingerprint(file_name, file_size)
        session = self.get_session()
        try:
            rows = (
                session.query(UploadJobItem)
                .join(UploadJob, UploadJobItem.job_id == UploadJob.id)
                .filter(UploadJob.target_channel_id == str(channel_id))
                .filter(UploadJobItem.upload_id.isnot(None))
                .filter(UploadJobItem.item_status.in_(("uploaded", "indexed")))
                .order_by(UploadJobItem.id.desc())
                .limit(400)
                .all()
            )
            for it in rows:
                it_fp = it.content_fingerprint or compute_content_fingerprint(
                    it.file_name, it.file_size
                )
                if it_fp == leg_fp:
                    return int(it.upload_id)
                if norm and normalize_basename(it.file_name or "") == norm:
                    if file_size is None or it.file_size == file_size:
                        return int(it.upload_id)
            return None
        finally:
            session.close()

    def resolve_library_upload_for_job_item(
        self,
        *,
        content_fingerprint: str | None,
        file_name: str,
        file_size: int | None,
        channel_id: str | None = None,
    ) -> int | None:
        """
        Find existing library upload for a planned file.
        Tries: stored fingerprint, size+name fingerprint (not SHA), channel basename, prior job link.
        """
        from fingerprint import compute_content_fingerprint

        fps: list[str] = []
        if content_fingerprint:
            fps.append(content_fingerprint)
        leg = compute_content_fingerprint(file_name, file_size)
        if leg not in fps:
            fps.append(leg)
        dup_map = self.map_fingerprints_to_upload_ids(fps)
        for fp in fps:
            if fp in dup_map:
                return dup_map[fp]
        if channel_id:
            uid = self.find_upload_id_by_channel_basename_size(
                channel_id, file_name, file_size
            )
            if uid:
                return uid
            uid = self.find_upload_via_prior_job_item(channel_id, file_name, file_size)
            if uid:
                return uid
        return None

    def find_uploads_by_fingerprint(
        self,
        fingerprint: str,
        *,
        exclude_upload_id: int | None = None,
        limit: int = 8,
        incoming_channel_id: str | None = None,
    ) -> list:
        if not fingerprint:
            return []
        session = self.get_session()
        try:
            q = (
                session.query(FileUpload)
                .options(
                    joinedload(FileUpload.channel),
                    joinedload(FileUpload.source_channel),
                )
                .filter(FileUpload.content_fingerprint == fingerprint)
                .filter(FileUpload.ingest_state != "skipped")
                .filter(self._subtitle_exclusion_filter())
            )
            if exclude_upload_id:
                q = q.filter(FileUpload.id != exclude_upload_id)
            rows = q.order_by(FileUpload.uploaded_at.desc()).limit(max(limit, 1) * 4).all()
            ingest_id = self.get_ingest_channel_id()
            if ingest_id:
                non_ingest = [u for u in rows if str(u.channel_id) != ingest_id]
                if (
                    incoming_channel_id
                    and str(incoming_channel_id) == ingest_id
                    and not non_ingest
                ):
                    # Re-forward into ingest only — not a library duplicate.
                    rows = []
                elif non_ingest:
                    rows = non_ingest + [
                        u for u in rows if str(u.channel_id) == ingest_id
                    ]
            out = rows[:limit]
            return self._detach_upload_graph(session, out)
        finally:
            session.close()

    def set_upload_tmdb_retry(
        self,
        upload_id: int,
        *,
        delay_seconds: float,
        retry_count: int,
    ) -> None:
        session = self.get_session()
        try:
            upload = session.query(FileUpload).filter_by(id=int(upload_id)).first()
            if not upload:
                return
            upload.tmdb_retry_count = int(retry_count)
            upload.tmdb_retry_after = datetime.utcnow() + timedelta(
                seconds=float(delay_seconds)
            )
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("set_upload_tmdb_retry failed: %s", e)
        finally:
            session.close()

    def clear_upload_tmdb_retry(
        self, upload_id: int, *, keep_count: bool = False
    ) -> None:
        session = self.get_session()
        try:
            upload = session.query(FileUpload).filter_by(id=int(upload_id)).first()
            if not upload:
                return
            upload.tmdb_retry_after = None
            if not keep_count:
                upload.tmdb_retry_count = 0
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("clear_upload_tmdb_retry failed: %s", e)
        finally:
            session.close()

    def enqueue_pending_tmdb_retries(
        self,
        upload_ids: list[int],
        *,
        stagger_seconds: float = 2.0,
        due_immediately: bool = False,
    ) -> int:
        if not upload_ids:
            return 0
        session = self.get_session()
        try:
            now = datetime.utcnow()
            n = 0
            for i, uid in enumerate(upload_ids):
                upload = session.query(FileUpload).filter_by(id=int(uid)).first()
                if not upload or not upload.needs_confirmation or upload.is_confirmed:
                    continue
                if due_immediately:
                    upload.tmdb_retry_after = now
                else:
                    upload.tmdb_retry_after = now + timedelta(
                        seconds=i * stagger_seconds
                    )
                upload.tmdb_retry_count = 0
                n += 1
            session.commit()
            return n
        except Exception as e:
            session.rollback()
            logger.error("enqueue_pending_tmdb_retries failed: %s", e)
            return 0
        finally:
            session.close()

    def count_due_tmdb_retries(self) -> int:
        session = self.get_session()
        try:
            now = datetime.utcnow()
            return (
                session.query(FileUpload)
                .filter_by(needs_confirmation=True, is_confirmed=False)
                .filter(FileUpload.tmdb_retry_after.isnot(None))
                .filter(FileUpload.tmdb_retry_after <= now)
                .filter(self._tmdb_pending_filter())
                .count()
            )
        finally:
            session.close()

    def count_pending_not_on_tmdb_retry_queue(self) -> int:
        session = self.get_session()
        try:
            return (
                session.query(FileUpload)
                .filter_by(needs_confirmation=True, is_confirmed=False)
                .filter(FileUpload.tmdb_retry_after.is_(None))
                .filter(self._tmdb_pending_filter())
                .count()
            )
        finally:
            session.close()

    def count_scheduled_tmdb_retries(self) -> int:
        session = self.get_session()
        try:
            return (
                session.query(FileUpload)
                .filter_by(needs_confirmation=True, is_confirmed=False)
                .filter(FileUpload.tmdb_retry_after.isnot(None))
                .filter(self._tmdb_pending_filter())
                .count()
            )
        finally:
            session.close()

    def get_pending_for_tmdb_wave(self, limit: int) -> list[int]:
        """Pending files not already on the TMDB retry queue (for campaign waves)."""
        session = self.get_session()
        try:
            rows = (
                session.query(FileUpload.id)
                .filter_by(needs_confirmation=True, is_confirmed=False)
                .filter(FileUpload.tmdb_retry_after.is_(None))
                .filter(self._tmdb_pending_filter())
                .order_by(FileUpload.uploaded_at.asc())
                .limit(max(1, limit))
                .all()
            )
            return [int(r[0]) for r in rows]
        finally:
            session.close()

    def clear_pending_tmdb_retry_schedules(self) -> int:
        """Remove TMDB retry schedule from all pending rows (between campaign cycles)."""
        session = self.get_session()
        try:
            n = (
                session.query(FileUpload)
                .filter_by(needs_confirmation=True, is_confirmed=False)
                .filter(FileUpload.tmdb_retry_after.isnot(None))
                .update({FileUpload.tmdb_retry_after: None}, synchronize_session=False)
            )
            session.commit()
            return int(n or 0)
        except Exception as e:
            session.rollback()
            logger.error("clear_pending_tmdb_retry_schedules failed: %s", e)
            return 0
        finally:
            session.close()

    def get_due_tmdb_retries(self, limit: int = 10) -> list[int]:
        session = self.get_session()
        try:
            now = datetime.utcnow()
            rows = (
                session.query(FileUpload.id)
                .filter_by(needs_confirmation=True, is_confirmed=False)
                .filter(FileUpload.tmdb_retry_after.isnot(None))
                .filter(FileUpload.tmdb_retry_after <= now)
                .filter(self._tmdb_pending_filter())
                .order_by(FileUpload.tmdb_retry_after.asc())
                .limit(max(1, limit))
                .all()
            )
            return [int(r[0]) for r in rows]
        finally:
            session.close()

    def count_duplicate_holds(self) -> int:
        session = self.get_session()
        try:
            return session.query(FileUpload).filter_by(ingest_state="duplicate_hold").count()
        finally:
            session.close()

    def resolve_duplicate_upload(self, upload_id: int, action: str) -> FileUpload | None:
        session = self.get_session()
        try:
            upload = session.query(FileUpload).filter_by(id=upload_id).first()
            if not upload or upload.ingest_state != "duplicate_hold":
                return None
            if action == "skip":
                upload.ingest_state = "skipped"
            else:
                upload.ingest_state = "normal"
                if action == "force":
                    upload.duplicate_of_upload_id = None
            session.commit()
            return upload
        except Exception as e:
            session.rollback()
            logger.error("resolve_duplicate_upload: %s", e)
            return None
        finally:
            session.close()

    def backfill_fingerprints(self, *, limit: int = 5000) -> int:
        from fingerprint import compute_content_fingerprint

        session = self.get_session()
        try:
            rows = (
                session.query(FileUpload)
                .filter(or_(FileUpload.content_fingerprint.is_(None), FileUpload.content_fingerprint == ""))
                .limit(limit)
                .all()
            )
            for u in rows:
                u.content_fingerprint = compute_content_fingerprint(
                    u.file_name, u.file_size, file_unique_id=u.file_unique_id
                )
            session.commit()
            return len(rows)
        except Exception as e:
            session.rollback()
            logger.error("backfill_fingerprints: %s", e)
            return 0
        finally:
            session.close()

    def list_pipeline_upload_defaults(self) -> list[dict]:
        from pipeline_setup import PIPELINE_UPLOAD_TYPES

        session = self.get_session()
        try:
            rows = {
                r.upload_type: r
                for r in session.query(PipelineUploadDefault).all()
            }
            out = []
            for ut, _label in PIPELINE_UPLOAD_TYPES:
                row = rows.get(ut)
                ch_id = row.source_channel_id if row else None
                if ut == "mixed" and not ch_id:
                    ch_id = self.get_ingest_channel_id()
                ch = self.get_channel(ch_id) if ch_id else None
                out.append(
                    {
                        "upload_type": ut,
                        "source_channel_id": ch_id,
                        "channel_title": ch.channel_title if ch else None,
                        "channel_username": ch.channel_username if ch else None,
                    }
                )
            return out
        finally:
            session.close()

    def get_pipeline_upload_default(self, upload_type: str) -> dict | None:
        from pipeline_setup import normalize_upload_type

        ut = normalize_upload_type(upload_type)
        session = self.get_session()
        try:
            row = session.query(PipelineUploadDefault).filter_by(upload_type=ut).first()
            if not row:
                return {"upload_type": ut, "source_channel_id": None}
            return {
                "upload_type": row.upload_type,
                "source_channel_id": row.source_channel_id,
            }
        finally:
            session.close()

    def set_pipeline_source_channel(
        self, upload_type: str, channel_id: str | None
    ) -> bool:
        from pipeline_setup import normalize_upload_type

        ut = normalize_upload_type(upload_type)
        session = self.get_session()
        try:
            row = session.query(PipelineUploadDefault).filter_by(upload_type=ut).first()
            if not row:
                row = PipelineUploadDefault(upload_type=ut)
                session.add(row)
            row.source_channel_id = str(channel_id) if channel_id else None
            row.updated_at = datetime.utcnow()
            session.commit()
            if ut == "mixed" and channel_id:
                self.set_ingest_channel(channel_id)
            return True
        except Exception as e:
            session.rollback()
            logger.error("set_pipeline_source_channel: %s", e)
            return False
        finally:
            session.close()

    def create_upload_job(
        self,
        name: str,
        *,
        target_channel_id: str | None = None,
        content_lane: str = "course",
        course_title: str | None = None,
        created_by: int | None = None,
        notes: str | None = None,
    ) -> UploadJob | None:
        from content_lanes import normalize_lane
        from pipeline_setup import resolve_source_channel_for_upload_type

        lane = normalize_lane(content_lane)
        if not target_channel_id:
            target_channel_id = resolve_source_channel_for_upload_type(lane, db=self)

        @_sqlite_write_retry
        def _write() -> UploadJob | None:
            session = self.get_session()
            try:
                job = UploadJob(
                    name=name[:200],
                    target_channel_id=str(target_channel_id) if target_channel_id else None,
                    content_lane=lane,
                    course_title=(course_title or name)[:200],
                    status="planned" if target_channel_id else "draft",
                    created_by=created_by,
                    notes=notes,
                )
                session.add(job)
                session.commit()
                session.refresh(job)
                return job
            except Exception as e:
                session.rollback()
                logger.error("create_upload_job: %s", e)
                return None
            finally:
                session.close()

        return _write()

    def get_upload_job(self, job_id: int) -> UploadJob | None:
        session = self.get_session()
        try:
            return session.query(UploadJob).filter_by(id=job_id).first()
        finally:
            session.close()

    def list_upload_jobs(self, *, limit: int = 20) -> list:
        session = self.get_session()
        try:
            return session.query(UploadJob).order_by(UploadJob.updated_at.desc()).limit(limit).all()
        finally:
            session.close()

    def set_upload_job_status(self, job_id: int, status: str) -> bool:
        @_sqlite_write_retry
        def _write() -> bool:
            session = self.get_session()
            try:
                job = session.query(UploadJob).filter_by(id=job_id).first()
                if job:
                    job.status = status
                    job.updated_at = datetime.utcnow()
                    session.commit()
                return True
            finally:
                session.close()

        try:
            return _write()
        except Exception as e:
            logger.warning("set_upload_job_status job=%s status=%s: %s", job_id, status, e)
            return False

    def set_upload_job_target(self, job_id: int, channel_id: str) -> bool:
        session = self.get_session()
        try:
            job = session.query(UploadJob).filter_by(id=int(job_id)).first()
            if not job:
                return False
            job.target_channel_id = str(channel_id)
            if job.status == "draft":
                job.status = "planned"
            job.updated_at = datetime.utcnow()
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error("set_upload_job_target: %s", e)
            return False
        finally:
            session.close()

    def refresh_upload_job_status(self, job_id: int) -> str:
        """Derive job status from item_status counts."""

        @_sqlite_write_retry
        def _write() -> str:
            summary = self.get_upload_job_summary(job_id)
            st = summary.get("statuses") or {}
            total = summary.get("total") or 0
            if total == 0:
                status = "planned"
            elif st.get("indexed", 0) >= total:
                status = "complete"
            elif st.get("failed", 0) > 0 and st.get("indexed", 0) + st.get("failed", 0) >= total:
                status = "failed"
            elif st.get("uploaded", 0) or st.get("indexed", 0):
                status = "uploading"
            else:
                status = "planned"
            self.set_upload_job_status(job_id, status)
            return status

        return _write()

    def link_duplicate_hold_to_existing(self, hold_id: int, existing_id: int) -> bool:
        """Skip duplicate hold and point at the canonical indexed file."""
        session = self.get_session()
        try:
            hold = session.query(FileUpload).filter_by(id=int(hold_id)).first()
            existing = session.query(FileUpload).filter_by(id=int(existing_id)).first()
            if not hold or not existing:
                return False
            if hold.ingest_state != "duplicate_hold":
                return False
            hold.ingest_state = "skipped"
            hold.duplicate_of_upload_id = int(existing_id)
            hold.library_visible = False
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error("link_duplicate_hold_to_existing: %s", e)
            return False
        finally:
            session.close()

    def count_public_archive_files(self) -> int:
        from content_lanes import LANE_ARCHIVE

        session = self.get_session()
        try:
            return (
                session.query(FileUpload)
                .filter(self._public_library_filter())
                .filter(FileUpload.content_lane == LANE_ARCHIVE)
                .filter(self._subtitle_exclusion_filter())
                .count()
            )
        finally:
            session.close()

    def list_public_archive_files(
        self,
        *,
        limit: int = 15,
        offset: int = 0,
        search: str | None = None,
    ) -> list:
        from content_lanes import LANE_ARCHIVE

        session = self.get_session()
        try:
            q = (
                session.query(FileUpload)
                .filter(self._public_library_filter())
                .filter(FileUpload.content_lane == LANE_ARCHIVE)
                .filter(self._subtitle_exclusion_filter())
            )
            if search:
                term = f"%{search.strip()}%"
                q = q.filter(
                    or_(
                        FileUpload.file_name.ilike(term),
                        FileUpload.parsed_name.ilike(term),
                        FileUpload.confirmed_name.ilike(term),
                    )
                )
            return (
                q.order_by(FileUpload.uploaded_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
        finally:
            session.close()

    def add_upload_job_items(self, job_id: int, rows: list[dict]) -> int:
        from fingerprint import compute_content_fingerprint

        prepared: list[tuple[dict, str]] = []
        for row in rows:
            fn = (row.get("file_name") or "").strip()
            if not fn:
                continue
            size = row.get("file_size")
            fp = row.get("content_fingerprint") or compute_content_fingerprint(fn, size)
            prepared.append((row, fp))

        @_sqlite_write_retry
        def _write() -> int:
            session = self.get_session()
            try:
                job = session.query(UploadJob).filter_by(id=job_id).first()
                if not job:
                    return 0
                channel_id = (
                    str(job.target_channel_id) if job.target_channel_id else None
                )
                session.query(UploadJobItem).filter_by(job_id=job_id).delete()
                added = 0
                for row, fp in prepared:
                    fn = (row.get("file_name") or "").strip()
                    dup_id = self.resolve_library_upload_for_job_item(
                        content_fingerprint=fp,
                        file_name=fn,
                        file_size=row.get("file_size"),
                        channel_id=channel_id,
                    )
                    session.add(
                        UploadJobItem(
                            job_id=job_id,
                            sequence=int(row.get("sequence") or added + 1),
                            module=row.get("module"),
                            lesson_title=(row.get("lesson_title") or Path(fn).stem)[:200],
                            file_name=fn,
                            local_path=row.get("local_path"),
                            file_size=row.get("file_size"),
                            content_fingerprint=fp,
                            duplicate_of_upload_id=dup_id,
                            decision="skip" if dup_id else "upload",
                        )
                    )
                    added += 1
                job.updated_at = datetime.utcnow()
                if added:
                    job.status = "planned"
                session.commit()
                return added
            except Exception as e:
                session.rollback()
                logger.error("add_upload_job_items: %s", e)
                return 0
            finally:
                session.close()

        return _write()

    def get_upload_job_items(self, job_id: int, *, decision: str | None = None, limit: int | None = None) -> list:
        session = self.get_session()
        try:
            q = session.query(UploadJobItem).filter_by(job_id=job_id).order_by(UploadJobItem.sequence.asc())
            if decision:
                q = q.filter_by(decision=decision)
            if limit:
                q = q.limit(limit)
            return q.all()
        finally:
            session.close()

    def get_upload_job_summary(self, job_id: int) -> dict:
        session = self.get_session()
        try:
            items = session.query(UploadJobItem).filter_by(job_id=job_id).all()
            by_dec: dict[str, int] = {}
            by_status: dict[str, int] = {}
            for it in items:
                by_dec[it.decision] = by_dec.get(it.decision, 0) + 1
                by_status[it.item_status] = by_status.get(it.item_status, 0) + 1
            return {"total": len(items), "decisions": by_dec, "statuses": by_status}
        finally:
            session.close()

    def recheck_upload_job_library_matches(self, job_id: int) -> dict[str, int]:
        """Refresh duplicate_of_upload_id from library (multi-strategy match)."""
        items = self.get_upload_job_items(job_id)
        if not items:
            return {"new": 0, "dup": 0, "total": 0}

        job = self.get_upload_job(job_id)
        channel_id = (
            str(job.target_channel_id) if job and job.target_channel_id else None
        )
        resolutions: list[tuple[int, int | None]] = []
        for it in items:
            dup_id = self.resolve_library_upload_for_job_item(
                content_fingerprint=it.content_fingerprint,
                file_name=it.file_name,
                file_size=it.file_size,
                channel_id=channel_id,
            )
            resolutions.append((int(it.id), dup_id))

        @_sqlite_write_retry
        def _write() -> dict[str, int]:
            session = self.get_session()
            new_n = dup_n = 0
            try:
                for item_id, dup_id in resolutions:
                    row = session.query(UploadJobItem).filter_by(id=item_id).first()
                    if not row:
                        continue
                    was_dup = row.duplicate_of_upload_id
                    row.duplicate_of_upload_id = int(dup_id) if dup_id else None
                    if dup_id:
                        dup_n += 1
                        if not was_dup and row.decision in ("upload", "pending"):
                            row.decision = "skip"
                    else:
                        new_n += 1
                session.commit()
                return {"new": new_n, "dup": dup_n, "total": len(items)}
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        try:
            return _write()
        except Exception as e:
            logger.warning("recheck_upload_job_library_matches job=%s: %s", job_id, e)
            return {"new": 0, "dup": 0, "total": len(items)}

    def skip_all_duplicate_job_items(self, job_id: int) -> tuple[int, int]:
        """Mark in-library duplicates as skip. Returns (changed_count, total_duplicates)."""

        @_sqlite_write_retry
        def _write() -> tuple[int, int]:
            session = self.get_session()
            try:
                changed = total = 0
                for it in session.query(UploadJobItem).filter_by(job_id=job_id).all():
                    if not it.duplicate_of_upload_id:
                        continue
                    total += 1
                    if it.decision != "skip":
                        it.decision = "skip"
                        changed += 1
                session.commit()
                return changed, total
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        try:
            return _write()
        except Exception as e:
            logger.warning("skip_all_duplicate_job_items job=%s: %s", job_id, e)
            return 0, 0

    def upload_anyway_duplicate_job_items(self, job_id: int) -> tuple[int, int]:
        """Re-upload in-library duplicates anyway. Returns (changed_count, total_duplicates)."""

        @_sqlite_write_retry
        def _write() -> tuple[int, int]:
            session = self.get_session()
            try:
                changed = total = 0
                for it in session.query(UploadJobItem).filter_by(job_id=job_id).all():
                    if not it.duplicate_of_upload_id:
                        continue
                    total += 1
                    if it.decision not in ("upload", "force"):
                        it.decision = "force"
                        changed += 1
                session.commit()
                return changed, total
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        try:
            return _write()
        except Exception as e:
            logger.warning("upload_anyway_duplicate_job_items job=%s: %s", job_id, e)
            return 0, 0

    def upload_all_non_duplicate_job_items(self, job_id: int) -> int:
        """Mark items not in library as upload (used at job create / refresh)."""
        @_sqlite_write_retry
        def _write() -> int:
            session = self.get_session()
            try:
                n = 0
                for it in session.query(UploadJobItem).filter_by(job_id=job_id).all():
                    if not it.duplicate_of_upload_id and it.decision != "upload":
                        it.decision = "upload"
                        n += 1
                session.commit()
                return n
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        try:
            return _write()
        except Exception as e:
            logger.warning("upload_all_non_duplicate_job_items job=%s: %s", job_id, e)
            return 0

    def mark_job_item_uploaded(self, item_id: int, message_id: int) -> bool:
        @_sqlite_write_retry
        def _write() -> bool:
            session = self.get_session()
            try:
                it = session.query(UploadJobItem).filter_by(id=item_id).first()
                if it:
                    it.item_status = "uploaded"
                    it.telegram_message_id = message_id
                    session.commit()
                return True
            finally:
                session.close()

        try:
            return _write()
        except Exception as e:
            logger.warning(
                "mark_job_item_uploaded item=%s msg=%s: %s", item_id, message_id, e
            )
            return False

    def link_job_item_to_upload(
        self,
        item_id: int,
        upload_id: int,
        message_id: int | None = None,
        *,
        refresh_job: bool = True,
    ) -> None:
        @_sqlite_write_retry
        def _write() -> int | None:
            session = self.get_session()
            try:
                it = session.query(UploadJobItem).filter_by(id=item_id).first()
                if not it:
                    return None
                it.upload_id = upload_id
                it.item_status = "indexed"
                if message_id is not None:
                    it.telegram_message_id = message_id
                job_id = it.job_id
                session.commit()
                return job_id
            finally:
                session.close()

        job_id = _write()
        if refresh_job and job_id:
            self.refresh_upload_job_status(job_id)

    def get_job_item_for_ingest(self, item_id: int) -> UploadJobItem | None:
        session = self.get_session()
        try:
            return (
                session.query(UploadJobItem)
                .options(joinedload(UploadJobItem.job))
                .filter_by(id=item_id)
                .first()
            )
        finally:
            session.close()

    def match_pending_job_item(self, channel_id: str, file_name: str, file_size: int | None) -> UploadJobItem | None:
        from fingerprint import compute_content_fingerprint

        fp = compute_content_fingerprint(file_name, file_size)
        session = self.get_session()
        try:
            jobs = (
                session.query(UploadJob)
                .filter(UploadJob.status.in_(["planned", "uploading"]))
                .all()
            )
            job_ids = [j.id for j in jobs if not j.target_channel_id or str(j.target_channel_id) == str(channel_id)]
            if not job_ids:
                return None
            return (
                session.query(UploadJobItem)
                .options(joinedload(UploadJobItem.job))
                .filter(UploadJobItem.job_id.in_(job_ids))
                .filter(UploadJobItem.decision.in_(["upload", "force"]))
                .filter(or_(UploadJobItem.content_fingerprint == fp, UploadJobItem.file_name == file_name))
                .filter(UploadJobItem.item_status.in_(["planned", "uploaded"]))
                .order_by(UploadJobItem.sequence.asc())
                .first()
            )
        finally:
            session.close()

    def map_upload_display_names(self, upload_ids: list[int]) -> dict[int, str]:
        """Batch lookup for job detail: upload id → short library label."""
        ids = [int(x) for x in {int(i) for i in upload_ids if i}]
        if not ids:
            return {}
        session = self.get_session()
        try:
            out: dict[int, str] = {}
            for i in range(0, len(ids), _FINGERPRINT_BATCH):
                chunk = ids[i : i + _FINGERPRINT_BATCH]
                rows = session.query(FileUpload).filter(FileUpload.id.in_(chunk)).all()
                for row in rows:
                    label = (
                        (row.confirmed_name or row.parsed_name or row.file_name or "")[:80]
                    ).strip()
                    if label:
                        out[int(row.id)] = label
            return out
        finally:
            session.close()

    def list_course_titles(self, *, limit: int = 40) -> list:
        session = self.get_session()
        try:
            return (
                session.query(MovieSeries)
                .filter(MovieSeries.media_type == "course")
                .order_by(MovieSeries.name.asc())
                .limit(limit)
                .all()
            )
        finally:
            session.close()

    def get_course_uploads(self, content_title_id: int, *, limit: int = 500) -> list:
        session = self.get_session()
        try:
            return (
                session.query(FileUpload)
                .filter_by(content_title_id=int(content_title_id))
                .filter(FileUpload.content_lane == "course")
                .filter(self._subtitle_exclusion_filter())
                .order_by(FileUpload.lesson_sequence, FileUpload.episode_number)
                .limit(limit)
                .all()
            )
        finally:
            session.close()

    def upsert_course_title(self, course_name: str) -> MovieSeries:
        session = self.get_session()
        try:
            name = (course_name or "Course").strip()[:200]
            row = (
                session.query(MovieSeries)
                .filter(MovieSeries.media_type == "course")
                .filter(or_(MovieSeries.name == name, MovieSeries.tmdb_title == name))
                .first()
            )
            if row:
                return row
            row = MovieSeries(name=name, tmdb_title=name, media_type="course", catalog_excluded=True)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def promote_content_title_to_library(
        self,
        content_title_id: int,
        *,
        to_media_lane: bool = False,
        approve_distribution: bool = True,
    ) -> int:
        """Mark all uploads for a title public in browse; optional lane→media."""
        from content_lanes import LANE_ADULT, LANE_MEDIA, normalize_lane

        session = self.get_session()
        try:
            uploads = (
                session.query(FileUpload)
                .filter_by(content_title_id=int(content_title_id))
                .filter(self._subtitle_exclusion_filter())
                .all()
            )
            ct = session.query(MovieSeries).filter_by(id=int(content_title_id)).first()
            n = 0
            for u in uploads:
                if normalize_lane(u.content_lane) == LANE_ADULT:
                    continue
                u.is_confirmed = True
                u.needs_confirmation = False
                u.library_visible = True
                if approve_distribution:
                    u.distribution_approved = True
                if to_media_lane:
                    u.content_lane = LANE_MEDIA
                if not u.confirmed_name:
                    u.confirmed_name = u.parsed_name
                n += 1
            if ct and to_media_lane:
                ct.catalog_excluded = False
                if ct.media_type == "course":
                    ct.media_type = "movie"
            session.commit()
            return n
        except Exception as e:
            session.rollback()
            logger.error("promote_content_title_to_library: %s", e)
            return 0
        finally:
            session.close()

    def promote_upload_to_library(
        self,
        upload_id: int,
        *,
        to_media_lane: bool = False,
    ) -> FileUpload | None:
        from content_lanes import LANE_ADULT, LANE_MEDIA, normalize_lane

        session = self.get_session()
        try:
            upload = session.query(FileUpload).filter_by(id=int(upload_id)).first()
            if not upload:
                return None
            if normalize_lane(upload.content_lane) == LANE_ADULT:
                return None
            upload.is_confirmed = True
            upload.needs_confirmation = False
            upload.library_visible = True
            upload.distribution_approved = True
            upload.ingest_state = "normal"
            if to_media_lane:
                upload.content_lane = LANE_MEDIA
            if not upload.confirmed_name:
                upload.confirmed_name = upload.parsed_name
            if upload.content_title_id:
                ct = session.query(MovieSeries).filter_by(id=upload.content_title_id).first()
                if ct:
                    ct.indexed_only = False
                    ct.catalog_excluded = False
                    if to_media_lane and ct.media_type == "course":
                        ct.media_type = "movie"
            session.commit()
            return upload
        except Exception as e:
            session.rollback()
            logger.error("promote_upload_to_library: %s", e)
            return None
        finally:
            session.close()

    def create_portal_session(self, user_id: int, *, hours: int = 72) -> str:
        import secrets
        from datetime import timedelta

        token = secrets.token_urlsafe(32)
        session = self.get_session()
        try:
            session.add(
                PortalSession(
                    token=token,
                    user_id=int(user_id),
                    expires_at=datetime.utcnow() + timedelta(hours=hours),
                )
            )
            session.commit()
            return token
        except Exception as e:
            session.rollback()
            logger.error("create_portal_session: %s", e)
            return ""
        finally:
            session.close()

    def get_portal_user_id(self, token: str) -> int | None:
        if not token:
            return None
        session = self.get_session()
        try:
            row = session.query(PortalSession).filter_by(token=token.strip()).first()
            if not row:
                return None
            if row.expires_at and row.expires_at < datetime.utcnow():
                session.delete(row)
                session.commit()
                return None
            return int(row.user_id)
        finally:
            session.close()

    def find_content_title_by_tmdb(
        self, tmdb_id: int, media_type: str | None = None
    ) -> MovieSeries | None:
        if not tmdb_id:
            return None
        mt = (media_type or "").strip().lower()
        if mt == "series":
            mt = "tv"
        session = self.get_session()
        try:
            q = session.query(MovieSeries).filter(MovieSeries.tmdb_id == int(tmdb_id))
            if mt in ("movie", "tv", "course"):
                q = q.filter(MovieSeries.media_type == mt)
            return q.order_by(MovieSeries.updated_at.desc()).first()
        finally:
            session.close()

    def list_filename_strip_rules(self, *, active_only: bool = True) -> list:
        session = self.get_session()
        try:
            q = session.query(FilenameStripRule).order_by(
                FilenameStripRule.created_at.asc()
            )
            if active_only:
                q = q.filter(FilenameStripRule.is_active.is_(True))
            rows = q.all()
            return [
                {
                    "id": r.id,
                    "pattern": r.pattern,
                    "note": r.note,
                    "is_regex": bool(r.is_regex),
                    "is_active": bool(r.is_active),
                    "created_at": r.created_at,
                }
                for r in rows
            ]
        finally:
            session.close()

    def add_filename_strip_rule(
        self,
        pattern: str,
        *,
        note: str | None = None,
        is_regex: bool = False,
    ) -> dict | None:
        pattern = (pattern or "").replace("\r", "").replace("\n", "")
        if not pattern or not pattern.strip():
            return None
        session = self.get_session()
        try:
            existing = (
                session.query(FilenameStripRule)
                .filter(FilenameStripRule.pattern == pattern)
                .first()
            )
            if existing:
                existing.is_active = True
                if note:
                    existing.note = note[:200]
                existing.is_regex = bool(is_regex)
                session.commit()
                return {
                    "id": existing.id,
                    "pattern": existing.pattern,
                    "note": existing.note,
                    "is_regex": bool(existing.is_regex),
                    "is_active": True,
                }
            row = FilenameStripRule(
                pattern=pattern[:500],
                note=(note or "")[:200] or None,
                is_regex=bool(is_regex),
            )
            session.add(row)
            session.commit()
            return {
                "id": row.id,
                "pattern": row.pattern,
                "note": row.note,
                "is_regex": bool(row.is_regex),
                "is_active": True,
            }
        except Exception as e:
            session.rollback()
            logger.error("add_filename_strip_rule failed: %s", e)
            raise
        finally:
            session.close()

    def delete_filename_strip_rule(self, rule_id: int) -> bool:
        session = self.get_session()
        try:
            row = session.query(FilenameStripRule).filter_by(id=int(rule_id)).first()
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error("delete_filename_strip_rule failed: %s", e)
            return False
        finally:
            session.close()