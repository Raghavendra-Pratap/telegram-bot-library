"""
File-metadata matcher with multiple matching strategies
"""
import logging
from typing import List, Dict, Optional, Tuple
from pathlib import Path

try:
    from Levenshtein import distance as levenshtein_distance
    LEVENSHTEIN_AVAILABLE = True
except ImportError:
    LEVENSHTEIN_AVAILABLE = False
    levenshtein_distance = None

from utils.file_scanner import FileInfo

logger = logging.getLogger(__name__)


class MetadataMatcher:
    """Match files to metadata entries"""
    
    def __init__(self, match_strategy: str = "exact", fuzzy_threshold: float = 0.8):
        """
        Initialize matcher
        
        Args:
            match_strategy: Matching strategy ("exact", "path", "fuzzy")
            fuzzy_threshold: Similarity threshold for fuzzy matching (0.0-1.0)
        """
        self.match_strategy = match_strategy
        self.fuzzy_threshold = fuzzy_threshold
    
    def match_file(self, file_info: FileInfo, metadata_entries: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """
        Match a file to a metadata entry
        
        Args:
            file_info: FileInfo object
            metadata_entries: List of metadata dictionaries
        
        Returns:
            Matched metadata entry or None
        """
        if self.match_strategy == "exact":
            return self._match_exact(file_info, metadata_entries)
        elif self.match_strategy == "path":
            return self._match_path(file_info, metadata_entries)
        elif self.match_strategy == "fuzzy":
            return self._match_fuzzy(file_info, metadata_entries)
        else:
            # Try all strategies in order
            match = self._match_exact(file_info, metadata_entries)
            if match:
                return match
            
            match = self._match_path(file_info, metadata_entries)
            if match:
                return match
            
            return self._match_fuzzy(file_info, metadata_entries)
    
    def _match_exact(self, file_info: FileInfo, metadata_entries: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Match by exact filename or file_path"""
        filename = file_info.filename
        relative_path = str(file_info.relative_path)
        
        for entry in metadata_entries:
            # Check filename column
            if 'filename' in entry:
                if entry['filename'].strip() == filename:
                    return entry
            
            # Check file_path column
            if 'file_path' in entry:
                entry_path = entry['file_path'].strip()
                if entry_path == relative_path or entry_path == filename:
                    return entry
        
        return None
    
    def _match_path(self, file_info: FileInfo, metadata_entries: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Match by path (exact or partial)"""
        relative_path = str(file_info.relative_path)
        filename = file_info.filename
        
        for entry in metadata_entries:
            # Check if file_path contains the entry path or vice versa
            if 'file_path' in entry:
                entry_path = entry['file_path'].strip()
                if entry_path in relative_path or relative_path in entry_path:
                    return entry
                if entry_path == filename:
                    return entry
            
            # Check filename
            if 'filename' in entry:
                entry_filename = entry['filename'].strip()
                if entry_filename in relative_path or relative_path.endswith(entry_filename):
                    return entry
        
        return None
    
    def _match_fuzzy(self, file_info: FileInfo, metadata_entries: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Match using fuzzy string matching"""
        if not LEVENSHTEIN_AVAILABLE:
            logger.warning("Levenshtein not available, falling back to path matching")
            return self._match_path(file_info, metadata_entries)
        
        filename = file_info.filename
        relative_path = str(file_info.relative_path)
        best_match = None
        best_score = 0.0
        
        for entry in metadata_entries:
            # Try matching against filename
            if 'filename' in entry:
                entry_filename = entry['filename'].strip()
                if entry_filename:
                    score = self._similarity(filename, entry_filename)
                    if score > best_score and score >= self.fuzzy_threshold:
                        best_score = score
                        best_match = entry
            
            # Try matching against file_path
            if 'file_path' in entry:
                entry_path = entry['file_path'].strip()
                if entry_path:
                    score = self._similarity(relative_path, entry_path)
                    if score > best_score and score >= self.fuzzy_threshold:
                        best_score = score
                        best_match = entry
        
        return best_match if best_score >= self.fuzzy_threshold else None
    
    def _similarity(self, s1: str, s2: str) -> float:
        """Calculate similarity between two strings (0.0-1.0)"""
        if not s1 or not s2:
            return 0.0
        
        max_len = max(len(s1), len(s2))
        if max_len == 0:
            return 1.0
        
        distance = levenshtein_distance(s1.lower(), s2.lower())
        similarity = 1.0 - (distance / max_len)
        return similarity
    
    def match_all(self, files: List[FileInfo], metadata_entries: List[Dict[str, str]]) -> Dict[FileInfo, Optional[Dict[str, str]]]:
        """
        Match all files to metadata entries
        
        Args:
            files: List of FileInfo objects
            metadata_entries: List of metadata dictionaries
        
        Returns:
            Dictionary mapping FileInfo to matched metadata (or None)
        """
        matches = {}
        matched_entries = set()
        
        for file_info in files:
            match = self.match_file(file_info, metadata_entries)
            matches[file_info] = match
            
            if match and '_row_number' in match:
                matched_entries.add(match['_row_number'])
        
        # Log unmatched files and entries
        unmatched_files = [f for f, m in matches.items() if m is None]
        unmatched_entries = [e for e in metadata_entries 
                            if e.get('_row_number') not in matched_entries]
        
        if unmatched_files:
            logger.warning(f"{len(unmatched_files)} files could not be matched to metadata")
        
        if unmatched_entries:
            logger.warning(f"{len(unmatched_entries)} metadata entries did not match any files")
        
        return matches

