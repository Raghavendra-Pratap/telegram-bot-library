"""
Database models and operations for the Index Bot
"""
import json
import logging

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
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, joinedload, object_session
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

Base = declarative_base()


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
    # Last successful historical ingest from this channel as source (Telethon forward)
    historical_ingested_at = Column(DateTime, nullable=True)
    last_backfill_import_count = Column(Integer, default=0)

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

        engine_kwargs: dict = {'echo': False}
        if url.startswith('sqlite'):
            engine_kwargs['connect_args'] = {'check_same_thread': False}
        else:
            engine_kwargs['pool_pre_ping'] = True

        self.engine = create_engine(url, **engine_kwargs)
        Base.metadata.create_all(self.engine)
        self._migrate_channels_schema()
        self._migrate_file_uploads_schema()
        self._migrate_movie_series_schema()
        self._migrate_user_watchlist_schema()
        self.Session = sessionmaker(bind=self.engine)
        # Create default "All Channels" list if it doesn't exist
        self._ensure_default_list()
    
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
        except Exception as e:
            logger.warning(f"Channel schema migration skipped: {e}")

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
                        conn.execute(
                            text(
                                """
                                UPDATE file_uploads
                                SET library_visible = 1
                                WHERE is_confirmed = 1
                                  AND content_title_id IN (
                                    SELECT id FROM movie_series WHERE tmdb_id IS NOT NULL
                                  )
                                """
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

    @staticmethod
    def _subtitle_exclusion_filter():
        """SQLAlchemy filter: ignore subtitle sidecar files."""
        from media_utils import SUBTITLE_EXTENSIONS

        return and_(*[not_(FileUpload.file_name.ilike(f"%{ext}")) for ext in SUBTITLE_EXTENSIONS])

    @staticmethod
    def _library_visible_filter():
        """Only titles approved for public library browse (TMDB or custom name)."""
        return FileUpload.library_visible.is_(True)

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

    def get_watch_channel(self):
        """Watch/delivery channel from WATCH_CHANNEL_ID or is_watch_channel flag."""
        cid = (Config.WATCH_CHANNEL_ID or "").strip()
        if cid:
            return self.get_channel(cid)
        session = self.get_session()
        try:
            channel = session.query(Channel).filter_by(is_watch_channel=True).first()
            return self._channel_for_return(session, channel)
        finally:
            session.close()

    def set_watch_channel(self, channel_id):
        session = self.get_session()
        try:
            channel = session.query(Channel).filter_by(channel_id=str(channel_id)).first()
            if not channel:
                return None
            session.query(Channel).update({Channel.is_watch_channel: False})
            channel.is_watch_channel = True
            channel.is_active = True
            session.commit()
            return self._channel_for_return(session, channel)
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

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

    def get_library_catalog_slots(
        self, limit: int | None = 120, offset: int = 0
    ) -> list[dict]:
        """Distinct (content_title, season) slots with library-visible uploads."""
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
                .filter(self._library_visible_filter())
                .filter(MovieSeries.catalog_excluded.isnot(True))
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

    def count_uploads_in_catalog_slot(
        self, content_title_id: int, season_number: int | None
    ) -> int:
        session = self.get_session()
        try:
            q = (
                session.query(FileUpload)
                .filter_by(content_title_id=int(content_title_id))
                .filter(self._library_visible_filter())
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

    def get_pending_upload_requests(self, limit: int = 30) -> list:
        session = self.get_session()
        try:
            return (
                session.query(UploadRequest)
                .filter_by(status="pending")
                .order_by(UploadRequest.created_at.desc())
                .limit(limit)
                .all()
            )
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

            if row:
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
        if not content_title_id:
            return False
        ct = self.get_content_title(content_title_id)
        if not ct:
            return False
        return not bool(getattr(ct, "catalog_excluded", False))

    def get_content_title(self, content_title_id: int) -> MovieSeries | None:
        session = self.get_session()
        try:
            row = session.query(MovieSeries).filter_by(id=content_title_id).first()
            return self._channel_for_return(session, row)
        finally:
            session.close()

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
                query = query.filter(self._library_visible_filter())
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
                query = query.filter(self._library_visible_filter())
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
            pending = base.filter_by(needs_confirmation=True, is_confirmed=False).count()
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
    ):
        """Add a new file upload"""
        session = self.get_session()
        try:
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
            )
            session.add(upload)
            session.commit()
            return upload
        except Exception as e:
            session.rollback()
            raise e
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
                )
                if ct_row:
                    ct = session.query(MovieSeries).filter_by(id=ct_row.id).first()
            elif ct:
                ct.catalog_excluded = bool(catalog_excluded)

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
                .filter(self._subtitle_exclusion_filter())
                .count()
            )
        finally:
            session.close()

    def get_pending_confirmations(self, limit=50):
        """Get files that need admin confirmation"""
        session = self.get_session()
        try:
            q = (
                session.query(FileUpload)
                .filter_by(needs_confirmation=True, is_confirmed=False)
                .filter(self._subtitle_exclusion_filter())
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
                query = query.filter(self._library_visible_filter())
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
                query = query.filter(self._library_visible_filter())
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
                query = query.filter(self._library_visible_filter())
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
    
    def auto_register_channel(self, channel_id, channel_username=None, channel_title=None):
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
                session.commit()
                return self._channel_for_return(session, existing)
            
            # Create new channel
            channel = Channel(
                channel_id=str(channel_id),
                channel_username=channel_username,
                channel_title=channel_title,
                is_active=True
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
                query = query.filter(self._library_visible_filter())

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
                query = query.filter(self._library_visible_filter())
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