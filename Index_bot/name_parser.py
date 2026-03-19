"""
Movie and Series name parser from file names
"""
import re
import logging

logger = logging.getLogger(__name__)


class NameParser:
    """Extracts movie/series names from file names"""
    
    # Common patterns to remove from file names
    REMOVE_PATTERNS = [
        r'\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v)$',  # File extensions
        r'\.(x264|x265|HEVC|AV1|h264|h265)',  # Codecs
        r'\.(AAC|AC3|DTS|DD|EAC3|Opus)',  # Audio codecs
        r'\.(1080p|720p|480p|2160p|4K|8K)',  # Resolutions
        r'\.(BluRay|BRRip|WEBRip|DVDRip|HDTV|WEB-DL|AMZN|Netflix)',  # Sources
        r'\.(YTS|YIFY|RARBG|ETRG|MVGroup)',  # Release groups
        r'\.(MX|AM|AG|ME)',  # Site tags
        r'\[.*?\]',  # Brackets content
        r'\(.*?\)',  # Parentheses content (but keep year)
        r'\.(Sub|Subs|SRT|ASS|SSA)',  # Subtitle indicators
        r'\.(Dual|Multi|Audio)',  # Audio indicators
        r'\.(5\.1|2\.1|7\.1|DD\+)',  # Audio channels
        r'\.(Eng|English|Hindi|ita|ita eng)',  # Language tags
        r'\.(ESub|Sub ita)',  # Subtitle tags
        r'\.(Full Movie|Remastered|Anniversary Edition)',  # Descriptors
        r'\.(BONE|SWAXXON|iDN_CreW|MIRCrew|LAMA|EtHD)',  # Release groups
        r'\.(MVGroup\.org)',  # Specific tags
        r'\.(of\d+)',  # Part indicators like "1of3"
        r'^\d+of\d+\.',  # Part indicators at start
        r'-[A-Z0-9]+$',  # Trailing release group tags like "-SWAXXON", "-YTS"
        r'-[A-Z0-9]+\.',  # Release group tags with dot
    ]
    
    # Patterns to extract year (4 digits)
    YEAR_PATTERN = r'\b(19|20)\d{2}\b'
    
    # Patterns to extract part numbers
    PART_PATTERN = r'\.?(\d+)of(\d+)'
    
    def __init__(self):
        self.compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.REMOVE_PATTERNS]
        self.year_pattern = re.compile(self.YEAR_PATTERN)
        self.part_pattern = re.compile(self.PART_PATTERN, re.IGNORECASE)
    
    def clean_filename(self, filename):
        """Clean filename by removing common patterns"""
        cleaned = filename
        
        # Remove file extension first
        cleaned = re.sub(r'\.[^.]+$', '', cleaned)
        
        # Apply all removal patterns
        for pattern in self.compiled_patterns:
            cleaned = pattern.sub('', cleaned)
        
        # Clean up multiple dots and spaces
        cleaned = re.sub(r'\.+', '.', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = cleaned.strip(' .')
        
        # Remove trailing dashes, underscores, and special characters
        cleaned = re.sub(r'[-_]+$', '', cleaned)
        cleaned = cleaned.strip(' .')
        
        return cleaned
    
    def extract_year(self, filename):
        """Extract year from filename"""
        matches = self.year_pattern.findall(filename)
        if matches:
            # Return the full 4-digit year (last match is usually the release year)
            # Find the full year pattern, not just the prefix
            full_year_pattern = re.compile(r'\b(19|20)(\d{2})\b')
            full_matches = full_year_pattern.findall(filename)
            if full_matches:
                # Return the last full year found
                year_prefix, year_suffix = full_matches[-1]
                return year_prefix + year_suffix
        return None
    
    def extract_part_info(self, filename):
        """Extract part information (e.g., 1of3)"""
        match = self.part_pattern.search(filename)
        if match:
            return {
                'part': int(match.group(1)),
                'total': int(match.group(2))
            }
        return None
    
    def parse_name(self, filename):
        """
        Parse movie/series name from filename
        
        Returns:
            dict with keys: 'name', 'year', 'part_info', 'confidence'
        """
        if not filename:
            return {
                'name': None,
                'year': None,
                'part_info': None,
                'confidence': 'low'
            }
        
        original_filename = filename
        
        # Extract year first
        year = self.extract_year(filename)
        
        # Extract part info
        part_info = self.extract_part_info(filename)
        
        # Clean the filename
        cleaned = self.clean_filename(filename)
        
        # Remove year from cleaned name if present
        if year:
            # Remove the full 4-digit year
            cleaned = re.sub(rf'\b{year}\b', '', cleaned).strip(' .')
            # Also remove partial year matches that might remain
            cleaned = re.sub(r'\b(19|20)\d{0,2}\b', '', cleaned).strip(' .')
        
        # Remove part info from cleaned name
        if part_info:
            cleaned = re.sub(self.part_pattern, '', cleaned).strip(' .')
        
        # Final cleanup
        cleaned = re.sub(r'\.+', ' ', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = cleaned.strip()
        
        # Remove trailing artifacts
        cleaned = re.sub(r'\s+\d+\.\d+\s*$', '', cleaned)  # Remove trailing "5.1", "2.1" etc
        cleaned = re.sub(r'\s+\d+\s*$', '', cleaned)  # Remove trailing single numbers
        cleaned = re.sub(r'[-_]+$', '', cleaned)  # Remove trailing dashes/underscores
        cleaned = re.sub(r'^[-_]+', '', cleaned)  # Remove leading dashes/underscores
        cleaned = cleaned.strip()
        
        # Fix common parsing issues
        cleaned = re.sub(r'\bCiaericas\b', 'CIA Americas', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bOrg\b$', '', cleaned, flags=re.IGNORECASE).strip()
        
        # Determine confidence
        confidence = 'high'
        if not cleaned or len(cleaned) < 3:
            confidence = 'low'
            cleaned = original_filename  # Fallback to original if parsing fails
        
        # Capitalize properly (Title Case)
        if cleaned:
            words = cleaned.split()
            cleaned = ' '.join(word.capitalize() for word in words)
        
        return {
            'name': cleaned if cleaned else original_filename,
            'year': year,
            'part_info': part_info,
            'confidence': confidence
        }
    
    def format_display_name(self, parsed_data):
        """Format parsed data for display"""
        name = parsed_data['name']
        year = parsed_data.get('year')
        part_info = parsed_data.get('part_info')
        
        display_name = name
        if year:
            display_name += f" ({year})"
        if part_info:
            display_name += f" - Part {part_info['part']}/{part_info['total']}"
        
        return display_name


# Example usage and testing
if __name__ == '__main__':
    parser = NameParser()
    
    test_files = [
        "CIA.Americas.Secret.Warriors.1of3.x264.AC3.MVGroup.org.mkv",
        "Bono.Stories.Of.Surrender.2025.1080p.WEBRip.x264.AAC5.1-[YTS.MX].mp4",
        "The.Autopsy.Of.Jane.Doe.2016.1080p.BluRay.x264-[YTS.AG].mp4",
        "Jolly LLB (2025) Hindi 1080p WEBRip x264 DD 5.1 ESub.mkv",
        "Memoir of a Snail (2024) 1080p WEBRip x265 ENG EAC3 Sub ita - iDN_CreW.mkv"
    ]
    
    for filename in test_files:
        result = parser.parse_name(filename)
        print(f"\nOriginal: {filename}")
        print(f"Parsed: {result['name']}")
        print(f"Year: {result['year']}")
        print(f"Part: {result['part_info']}")
        print(f"Confidence: {result['confidence']}")
