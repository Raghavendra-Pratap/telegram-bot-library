"""
Tree builder for creating folder structure metadata
"""
import logging
from typing import List, Dict, Optional
from pathlib import Path

from utils.file_scanner import FileInfo

logger = logging.getLogger(__name__)


class TreeBuilder:
    """Builds tree structure metadata from files"""
    
    @staticmethod
    def build_tree_path(file_info: FileInfo) -> str:
        """
        Build tree path string from file info
        
        Args:
            file_info: FileInfo object
        
        Returns:
            Tree path string (e.g., "root/folder1/subfolder")
        """
        return file_info.tree_name if file_info.tree_name else "root"
    
    @staticmethod
    def format_tree_caption(file_info: FileInfo, include_filename: bool = True) -> str:
        """
        Format tree path as caption text
        
        Args:
            file_info: FileInfo object
            include_filename: Include filename in caption
        
        Returns:
            Formatted caption string
        """
        tree_path = TreeBuilder.build_tree_path(file_info)
        
        parts = []
        if tree_path and tree_path != "root":
            parts.append(f"📁 {tree_path}")
        
        if include_filename:
            parts.append(f"📄 {file_info.filename}")
        
        return "\n".join(parts) if parts else file_info.filename
    
    @staticmethod
    def format_tree_separator(tree_path: str) -> str:
        """
        Format tree path as separator message
        
        Args:
            tree_path: Tree path string
        
        Returns:
            Formatted separator string
        """
        if not tree_path or tree_path == "root":
            return "📁 Root"
        
        return f"📁 {tree_path}"
    
    @staticmethod
    def group_by_tree(files: List[FileInfo]) -> Dict[str, List[FileInfo]]:
        """
        Group files by tree path
        
        Args:
            files: List of FileInfo objects
        
        Returns:
            Dictionary mapping tree paths to file lists
        """
        groups = {}
        
        for file_info in files:
            tree_path = TreeBuilder.build_tree_path(file_info)
            if tree_path not in groups:
                groups[tree_path] = []
            groups[tree_path].append(file_info)
        
        return groups
    
    @staticmethod
    def get_tree_hierarchy(files: List[FileInfo]) -> Dict[str, int]:
        """
        Get tree hierarchy depth levels
        
        Args:
            files: List of FileInfo objects
        
        Returns:
            Dictionary mapping tree paths to depth levels
        """
        hierarchy = {}
        
        for file_info in files:
            tree_path = TreeBuilder.build_tree_path(file_info)
            if tree_path:
                depth = len(tree_path.split("/"))
                hierarchy[tree_path] = depth
        
        return hierarchy

