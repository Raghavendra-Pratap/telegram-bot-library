"""
TMDB API helper for movie/series name validation and enrichment
"""
import logging
from config import Config

logger = logging.getLogger(__name__)

try:
    from tmdbv3api import TMDb, Movie, TV
    TMDB_AVAILABLE = True
except ImportError:
    TMDB_AVAILABLE = False
    logger.warning("tmdbv3api not available. TMDB features will be disabled.")


class TMDBHelper:
    """Helper class for TMDB API operations"""
    
    def __init__(self):
        self.enabled = False
        self.tmdb = None
        self.movie_api = None
        self.tv_api = None
        
        if not TMDB_AVAILABLE:
            return
        
        if Config.TMDB_API_KEY and Config.TMDB_API_KEY != 'your_tmdb_api_key':
            try:
                self.tmdb = TMDb()
                self.tmdb.api_key = Config.TMDB_API_KEY
                self.tmdb.language = 'en'
                self.movie_api = Movie()
                self.tv_api = TV()
                self.enabled = True
                logger.info("TMDB API initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize TMDB API: {e}")
    
    def search_movie(self, name, year=None):
        """Search for a movie by name"""
        if not self.enabled:
            return None
        
        try:
            if year:
                # Try with year first for better accuracy
                results = self.movie_api.search(name)
                for result in results:
                    if result.release_date and result.release_date.startswith(str(year)):
                        return {
                            'id': result.id,
                            'title': result.title,
                            'year': result.release_date[:4] if result.release_date else None,
                            'type': 'movie'
                        }
            
            # Fallback to general search
            results = self.movie_api.search(name)
            if results:
                result = results[0]  # Get best match
                return {
                    'id': result.id,
                    'title': result.title,
                    'year': result.release_date[:4] if result.release_date else None,
                    'type': 'movie'
                }
        except Exception as e:
            logger.error(f"Error searching movie '{name}': {e}")
        
        return None
    
    def search_tv(self, name, year=None):
        """Search for a TV series by name"""
        if not self.enabled:
            return None
        
        try:
            if year:
                results = self.tv_api.search(name)
                for result in results:
                    if result.first_air_date and result.first_air_date.startswith(str(year)):
                        return {
                            'id': result.id,
                            'title': result.name,
                            'year': result.first_air_date[:4] if result.first_air_date else None,
                            'type': 'tv'
                        }
            
            # Fallback to general search
            results = self.tv_api.search(name)
            if results:
                result = results[0]  # Get best match
                return {
                    'id': result.id,
                    'title': result.name,
                    'year': result.first_air_date[:4] if result.first_air_date else None,
                    'type': 'tv'
                }
        except Exception as e:
            logger.error(f"Error searching TV '{name}': {e}")
        
        return None
    
    def search(self, name, year=None):
        """
        Search for both movie and TV series
        Returns the best match (prefers movies)
        """
        if not self.enabled:
            return None
        
        # Try movie first
        movie_result = self.search_movie(name, year)
        if movie_result:
            return movie_result
        
        # Try TV
        tv_result = self.search_tv(name, year)
        if tv_result:
            return tv_result
        
        return None
    
    def validate_name(self, parsed_name, year=None):
        """
        Validate and get correct name from TMDB
        Returns dict with validated name and TMDB ID, or None
        """
        if not self.enabled or not parsed_name:
            return None
        
        # Try searching
        result = self.search(parsed_name, year)
        
        if result:
            return {
                'correct_name': result['title'],
                'tmdb_id': result['id'],
                'media_type': result['type'],
                'year': result.get('year')
            }
        
        return None


# Global instance
tmdb_helper = TMDBHelper()
