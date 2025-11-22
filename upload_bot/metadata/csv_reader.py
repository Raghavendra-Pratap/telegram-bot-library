"""
CSV metadata reader
"""
import csv
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class CSVMetadataReader:
    """Read metadata from CSV files"""
    
    def __init__(self, csv_path: Path):
        """
        Initialize CSV reader
        
        Args:
            csv_path: Path to CSV file
        """
        self.csv_path = Path(csv_path)
        
        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {self.csv_path}")
    
    def read(self) -> List[Dict[str, str]]:
        """
        Read metadata from CSV file
        
        Returns:
            List of dictionaries, each representing a row with column names as keys
        """
        metadata = []
        
        try:
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                # Try to detect delimiter
                sample = f.read(1024)
                f.seek(0)
                sniffer = csv.Sniffer()
                delimiter = sniffer.sniff(sample).delimiter
                
                reader = csv.DictReader(f, delimiter=delimiter)
                
                for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                    # Clean up row values (strip whitespace)
                    cleaned_row = {k.strip(): v.strip() if v else "" for k, v in row.items()}
                    cleaned_row['_row_number'] = row_num
                    metadata.append(cleaned_row)
        
        except Exception as e:
            logger.error(f"Error reading CSV file {self.csv_path}: {e}")
            raise
        
        logger.info(f"Read {len(metadata)} metadata entries from {self.csv_path}")
        return metadata
    
    def get_columns(self) -> List[str]:
        """
        Get column names from CSV file
        
        Returns:
            List of column names
        """
        try:
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                sample = f.read(1024)
                f.seek(0)
                sniffer = csv.Sniffer()
                delimiter = sniffer.sniff(sample).delimiter
                
                reader = csv.DictReader(f, delimiter=delimiter)
                return list(reader.fieldnames) if reader.fieldnames else []
        except Exception as e:
            logger.error(f"Error reading CSV columns: {e}")
            return []

