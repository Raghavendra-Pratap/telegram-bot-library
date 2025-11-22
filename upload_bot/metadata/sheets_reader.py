"""
Google Sheets metadata reader
"""
import logging
from typing import List, Dict, Optional
from pathlib import Path

try:
    import gspread
    from google.oauth2.service_account import Credentials
    from google.auth.exceptions import GoogleAuthError
    SHEETS_AVAILABLE = True
except ImportError:
    SHEETS_AVAILABLE = False
    gspread = None
    Credentials = None
    GoogleAuthError = Exception

logger = logging.getLogger(__name__)


class GoogleSheetsReader:
    """Read metadata from Google Sheets"""
    
    def __init__(self, sheet_url_or_id: str, credentials_path: Optional[Path] = None, 
                 sheet_name: Optional[str] = None):
        """
        Initialize Google Sheets reader
        
        Args:
            sheet_url_or_id: Google Sheets URL or spreadsheet ID
            credentials_path: Path to service account credentials JSON file
            sheet_name: Name of the sheet tab (if None, uses first sheet)
        """
        if not SHEETS_AVAILABLE:
            raise ImportError(
                "Google Sheets support requires gspread. "
                "Install with: pip install gspread google-auth"
            )
        
        self.sheet_url_or_id = sheet_url_or_id
        self.credentials_path = Path(credentials_path) if credentials_path else None
        self.sheet_name = sheet_name
        
        # Extract spreadsheet ID from URL if needed
        self.spreadsheet_id = self._extract_spreadsheet_id(sheet_url_or_id)
        
        # Initialize client
        self.client = None
        self._authenticate()
    
    def _extract_spreadsheet_id(self, url_or_id: str) -> str:
        """Extract spreadsheet ID from URL or return as-is if already an ID"""
        if url_or_id.startswith('http'):
            # Extract ID from URL
            # Format: https://docs.google.com/spreadsheets/d/{ID}/edit
            parts = url_or_id.split('/')
            try:
                idx = parts.index('d')
                return parts[idx + 1]
            except (ValueError, IndexError):
                raise ValueError(f"Could not extract spreadsheet ID from URL: {url_or_id}")
        return url_or_id
    
    def _authenticate(self):
        """Authenticate with Google Sheets API"""
        try:
            if self.credentials_path and self.credentials_path.exists():
                # Use service account
                scope = ['https://spreadsheets.google.com/feeds',
                        'https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_file(
                    str(self.credentials_path),
                    scopes=scope
                )
                self.client = gspread.authorize(creds)
                logger.info("Authenticated with Google Sheets using service account")
            else:
                # Try to use default credentials (for development)
                self.client = gspread.service_account()
                logger.info("Authenticated with Google Sheets using default credentials")
        except Exception as e:
            logger.error(f"Failed to authenticate with Google Sheets: {e}")
            raise
    
    def read(self) -> List[Dict[str, str]]:
        """
        Read metadata from Google Sheet
        
        Returns:
            List of dictionaries, each representing a row with column names as keys
        """
        if not self.client:
            raise RuntimeError("Not authenticated with Google Sheets")
        
        try:
            # Open spreadsheet
            spreadsheet = self.client.open_by_key(self.spreadsheet_id)
            
            # Get worksheet
            if self.sheet_name:
                worksheet = spreadsheet.worksheet(self.sheet_name)
            else:
                worksheet = spreadsheet.sheet1  # First sheet
            
            # Get all records
            records = worksheet.get_all_records()
            
            # Convert to list of dicts with cleaned values
            metadata = []
            for row_num, record in enumerate(records, start=2):  # Start at 2 (header is row 1)
                cleaned_row = {k.strip(): str(v).strip() if v else "" for k, v in record.items()}
                cleaned_row['_row_number'] = row_num
                metadata.append(cleaned_row)
            
            logger.info(f"Read {len(metadata)} metadata entries from Google Sheet")
            return metadata
        
        except Exception as e:
            logger.error(f"Error reading Google Sheet: {e}")
            raise
    
    def get_columns(self) -> List[str]:
        """
        Get column names from Google Sheet
        
        Returns:
            List of column names
        """
        if not self.client:
            raise RuntimeError("Not authenticated with Google Sheets")
        
        try:
            spreadsheet = self.client.open_by_key(self.spreadsheet_id)
            
            if self.sheet_name:
                worksheet = spreadsheet.worksheet(self.sheet_name)
            else:
                worksheet = spreadsheet.sheet1
            
            # Get first row (headers)
            headers = worksheet.row_values(1)
            return [h.strip() for h in headers] if headers else []
        
        except Exception as e:
            logger.error(f"Error reading Google Sheet columns: {e}")
            return []

