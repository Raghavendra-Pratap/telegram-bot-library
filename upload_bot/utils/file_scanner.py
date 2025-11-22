"""
File scanner to read directory structure and collect file information
"""
import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class FileInfo:
    """Information about a file"""
    
    def __init__(self, file_path: Path, root_path: Path):
        self.file_path = file_path
        self.root_path = root_path
        self.relative_path = file_path.relative_to(root_path)
        self.filename = file_path.name
        self.size = file_path.stat().st_size
        self.modified_time = datetime.fromtimestamp(file_path.stat().st_mtime)
        self.extension = file_path.suffix.lower()
        self.is_file = file_path.is_file()
        self.is_dir = file_path.is_dir()
        
        # Build tree path (folder structure)
        parts = self.relative_path.parts[:-1] if self.is_file else self.relative_path.parts
        self.tree_path = "/".join(parts) if parts else ""
        self.tree_name = self.tree_path if self.tree_path else "root"
    
    def __repr__(self):
        return f"FileInfo(path={self.relative_path}, size={self.size}, tree={self.tree_name})"


class FileScanner:
    """Scans directory structure and collects file information"""
    
    def __init__(self, root_path: Path, include_hidden: bool = False):
        """
        Initialize file scanner
        
        Args:
            root_path: Root directory to scan
            include_hidden: Include hidden files/directories
        """
        self.root_path = Path(root_path).resolve()
        self.include_hidden = include_hidden
        
        if not self.root_path.exists():
            raise ValueError(f"Root path does not exist: {self.root_path}")
        
        if not self.root_path.is_dir():
            raise ValueError(f"Root path is not a directory: {self.root_path}")
    
    def scan(self, recursive: bool = True, file_extensions: Optional[List[str]] = None) -> List[FileInfo]:
        """
        Scan directory for files
        
        Args:
            recursive: Scan subdirectories recursively
            file_extensions: Optional list of file extensions to include (e.g., ['.jpg', '.pdf'])
                           If None, includes all files
        
        Returns:
            List of FileInfo objects
        """
        files = []
        
        if recursive:
            pattern = "**/*"
        else:
            pattern = "*"
        
        try:
            for item in self.root_path.glob(pattern):
                # Skip hidden files if not included
                if not self.include_hidden and item.name.startswith('.'):
                    continue
                
                # Skip if not a file
                if not item.is_file():
                    continue
                
                # Filter by extension if specified
                if file_extensions:
                    if item.suffix.lower() not in file_extensions:
                        continue
                
                try:
                    file_info = FileInfo(item, self.root_path)
                    files.append(file_info)
                except (OSError, PermissionError) as e:
                    logger.warning(f"Cannot access file {item}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error scanning directory {self.root_path}: {e}")
            raise
        
        logger.info(f"Scanned {len(files)} files from {self.root_path}")
        return files
    
    def get_tree_structure(self, files: List[FileInfo]) -> Dict[str, List[FileInfo]]:
        """
        Group files by tree path (folder structure)
        
        Args:
            files: List of FileInfo objects
        
        Returns:
            Dictionary mapping tree paths to lists of files
        """
        tree_structure = {}
        
        for file_info in files:
            tree_path = file_info.tree_name
            if tree_path not in tree_structure:
                tree_structure[tree_path] = []
            tree_structure[tree_path].append(file_info)
        
        return tree_structure
    
    def get_file_by_path(self, files: List[FileInfo], path: str) -> Optional[FileInfo]:
        """
        Find a file by relative path or filename
        
        Args:
            files: List of FileInfo objects
            path: Relative path or filename to search for
        
        Returns:
            FileInfo if found, None otherwise
        """
        # Try exact path match first
        for file_info in files:
            if str(file_info.relative_path) == path:
                return file_info
            if file_info.filename == path:
                return file_info
        
        return None

