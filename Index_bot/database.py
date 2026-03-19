"""
Database models and operations for the Index Bot
"""
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, joinedload
from datetime import datetime

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
    
    # Relationships
    uploads = relationship("FileUpload", back_populates="channel")


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
    
    # Relationships
    channel = relationship("Channel", back_populates="uploads")


class MovieSeries(Base):
    """Stores confirmed movie/series names and their metadata"""
    __tablename__ = 'movie_series'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    tmdb_id = Column(Integer)  # TMDB ID if available
    media_type = Column(String)  # 'movie' or 'series'
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Note: Relationship removed - FileUpload.confirmed_name is a string, not a foreign key
    # To get uploads for a movie, query FileUpload where confirmed_name == MovieSeries.name


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


class Database:
    """Database operations"""
    
    def __init__(self, db_path='index_bot.db'):
        self.engine = create_engine(f'sqlite:///{db_path}', echo=False)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        # Create default "All Channels" list if it doesn't exist
        self._ensure_default_list()
    
    def get_session(self):
        return self.Session()
    
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
            return channel
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def get_channel(self, channel_id):
        """Get channel by ID"""
        session = self.get_session()
        try:
            return session.query(Channel).filter_by(channel_id=str(channel_id)).first()
        finally:
            session.close()
    
    def get_all_channels(self):
        """Get all active channels"""
        session = self.get_session()
        try:
            return session.query(Channel).filter_by(is_active=True).all()
        finally:
            session.close()
    
    def add_file_upload(self, channel_id, message_id, file_name, file_size=None, file_id=None, parsed_name=None, auto_confirm=False):
        """Add a new file upload"""
        session = self.get_session()
        try:
            needs_confirmation = not (auto_confirm and parsed_name)
            is_confirmed = auto_confirm and parsed_name is not None
            
            upload = FileUpload(
                channel_id=str(channel_id),
                message_id=message_id,
                file_name=file_name,
                file_size=file_size,
                file_id=file_id,
                parsed_name=parsed_name,
                needs_confirmation=needs_confirmation,
                is_confirmed=is_confirmed,
                confirmed_name=parsed_name if is_confirmed else None
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
    
    def get_pending_confirmations(self, limit=50):
        """Get files that need admin confirmation"""
        session = self.get_session()
        try:
            return session.query(FileUpload).filter_by(
                needs_confirmation=True,
                is_confirmed=False
            ).limit(limit).all()
        finally:
            session.close()
    
    def search_files(self, search_term):
        """Search for files by name"""
        session = self.get_session()
        try:
            search_pattern = f"%{search_term.lower()}%"
            results = session.query(FileUpload).filter(
                (FileUpload.confirmed_name.ilike(search_pattern)) |
                (FileUpload.parsed_name.ilike(search_pattern)) |
                (FileUpload.file_name.ilike(search_pattern))
            ).all()
            return results
        finally:
            session.close()
    
    def get_upload_stats(self, movie_name):
        """Get statistics for a movie/series across all channels"""
        session = self.get_session()
        try:
            # Get all uploads with this name (confirmed or parsed)
            # Eagerly load channel relationship to avoid lazy loading issues
            uploads = session.query(FileUpload).options(
                joinedload(FileUpload.channel)
            ).filter(
                ((FileUpload.confirmed_name == movie_name) & (FileUpload.is_confirmed == True)) |
                (FileUpload.parsed_name == movie_name)
            ).all()
            
            # Group by channel and extract channel data while session is active
            channel_stats = {}
            for upload in uploads:
                channel_id = upload.channel_id
                if channel_id not in channel_stats:
                    # Extract channel data before session closes
                    channel = upload.channel
                    channel_stats[channel_id] = {
                        'count': 0,
                        'channel_id': channel_id,
                        'channel_title': channel.channel_title if channel else None,
                        'channel_username': channel.channel_username if channel else None,
                        'uploads': []
                    }
                channel_stats[channel_id]['count'] += 1
                # Store upload data (extract needed fields before session closes)
                upload_data = {
                    'id': upload.id,
                    'file_name': upload.file_name,
                    'uploaded_at': upload.uploaded_at,
                    'is_confirmed': upload.is_confirmed,
                    'message_id': upload.message_id
                }
                channel_stats[channel_id]['uploads'].append(upload_data)
            
            return {
                'total_uploads': len(uploads),
                'channels': channel_stats
            }
        finally:
            session.close()
    
    def get_library_view(self, movie_name):
        """Get detailed library view for a movie/series showing all uploads"""
        session = self.get_session()
        try:
            # Get all uploads with this name, eagerly load channel
            uploads = session.query(FileUpload).options(
                joinedload(FileUpload.channel)
            ).filter(
                ((FileUpload.confirmed_name == movie_name) & (FileUpload.is_confirmed == True)) |
                (FileUpload.parsed_name == movie_name)
            ).order_by(FileUpload.uploaded_at.desc()).all()
            
            # Extract data while session is active
            upload_data_list = []
            for upload in uploads:
                upload_data_list.append({
                    'id': upload.id,
                    'file_name': upload.file_name,
                    'uploaded_at': upload.uploaded_at,
                    'is_confirmed': upload.is_confirmed,
                    'message_id': upload.message_id,
                    'channel_id': upload.channel_id,
                    'channel_title': upload.channel.channel_title if upload.channel else None,
                    'channel_username': upload.channel.channel_username if upload.channel else None,
                })
            
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
                return existing
            
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
            return channel
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
    
    def search_files_in_channels(self, search_term, channel_ids=None):
        """Search for files in specific channels"""
        session = self.get_session()
        try:
            search_pattern = f"%{search_term.lower()}%"
            query = session.query(FileUpload).filter(
                (FileUpload.confirmed_name.ilike(search_pattern)) |
                (FileUpload.parsed_name.ilike(search_pattern)) |
                (FileUpload.file_name.ilike(search_pattern))
            )
            
            # Filter by channels if specified
            if channel_ids:
                query = query.filter(FileUpload.channel_id.in_(channel_ids))
            
            return query.all()
        finally:
            session.close()
    
    def get_upload_stats_in_channels(self, movie_name, channel_ids=None):
        """Get statistics for a movie/series in specific channels"""
        session = self.get_session()
        try:
            # Get all uploads with this name
            query = session.query(FileUpload).options(
                joinedload(FileUpload.channel)
            ).filter(
                ((FileUpload.confirmed_name == movie_name) & (FileUpload.is_confirmed == True)) |
                (FileUpload.parsed_name == movie_name)
            )
            
            # Filter by channels if specified
            if channel_ids:
                query = query.filter(FileUpload.channel_id.in_(channel_ids))
            
            uploads = query.all()
            
            # Group by channel and extract channel data while session is active
            channel_stats = {}
            for upload in uploads:
                channel_id = upload.channel_id
                if channel_id not in channel_stats:
                    # Extract channel data before session closes
                    channel = upload.channel
                    channel_stats[channel_id] = {
                        'count': 0,
                        'channel_id': channel_id,
                        'channel_title': channel.channel_title if channel else None,
                        'channel_username': channel.channel_username if channel else None,
                        'uploads': []
                    }
                channel_stats[channel_id]['count'] += 1
                # Store upload data (extract needed fields before session closes)
                upload_data = {
                    'id': upload.id,
                    'file_name': upload.file_name,
                    'uploaded_at': upload.uploaded_at,
                    'is_confirmed': upload.is_confirmed,
                    'message_id': upload.message_id
                }
                channel_stats[channel_id]['uploads'].append(upload_data)
            
            return {
                'total_uploads': len(uploads),
                'channels': channel_stats
            }
        finally:
            session.close()