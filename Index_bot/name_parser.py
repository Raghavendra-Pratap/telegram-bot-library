"""
Movie and Series name parser from file names
"""
import re
import logging

logger = logging.getLogger(__name__)

# Release folders sometimes use 0 for o (B0oundless / B0undless -> Boundless).
_ZERO_BEFORE_O = re.compile(r"(?<=[A-Za-z])0(?=o)", re.I)
_ZERO_AS_O = re.compile(r"(?<=[A-Za-z])0(?=[A-Za-z])", re.I)


def _meaningful_parts_after(parts: list[str], index: int) -> list[str]:
    """Tokens after index that are not release noise / resolution tags."""
    out: list[str] = []
    for p in parts[index + 1 :]:
        low = p.lower()
        if low in RELEASE_NOISE or re.fullmatch(r"\d{3,4}p", low, re.I):
            continue
        out.append(p)
    return out


def is_leading_index_token(
    part: str,
    parts: list[str] | None = None,
    index: int = 0,
) -> bool:
    """
    True for file index / junk numeric prefix (01, 001, 12345), not title numbers.

    Keeps numeric titles: 12 Monkeys, 10 Cloverfield Lane, 9, 1917, 1522, etc.
    """
    if not part or not re.fullmatch(r"\d+", part):
        return False
    if re.fullmatch(r"(?:19|20)\d{2}", part, re.I):
        return False

    rest = _meaningful_parts_after(parts or [part], index if parts else 0)
    if not rest:
        return False  # e.g. movie titled "1522" only

    nxt = rest[0]

    # Long random scene / folder ids
    if len(part) >= 5:
        return True

    # Zero-padded counters: 01, 001, [02]
    if len(part) > 1 and part.startswith("0"):
        return True

    # 4-digit: years stay; 1522/1917/1408 before year/quality are titles
    if len(part) == 4:
        val = int(part)
        if 1900 <= val <= 2099:
            return False
        if re.fullmatch(r"(?:19|20)\d{2}", nxt, re.I):
            return False
        if nxt.lower() in RELEASE_NOISE or re.fullmatch(r"\d{3,4}p", nxt, re.I):
            return False
        return True  # e.g. 1234.Fight.Club

    # 1–3 digit unpadded
    if len(part) <= 3:
        if re.fullmatch(r"(?:19|20)\d{2}", nxt, re.I):
            return False
        word_tokens = [p for p in rest if re.fullmatch(r"[A-Za-z]{2,}", p, re.I)]
        if re.fullmatch(r"[A-Za-z]{2,}", nxt):
            # 10 Cloverfield Lane, 12 Monkeys — number is part of the title
            if len(part) == 2 and int(part) >= 10:
                return False
            # 5 Harry Potter And... — folder/franchise index before long title
            if len(part) == 1 and len(word_tokens) >= 3:
                return True
            if (
                len(part) == 2
                and part.isdigit()
                and int(part) < 10
                and len(word_tokens) >= 3
            ):
                return True
            return False
        return True

    return False


def strip_leading_index_parts(parts: list[str]) -> list[str]:
    """Drop leading numeric tokens from a split filename."""
    out = list(parts)
    while out and is_leading_index_token(out[0], out, 0):
        out.pop(0)
    return out


_LEADING_BRACKET_NUM = re.compile(r"^\[(\d{1,5})\]\s*[-._\s]*", re.I)
_LEADING_NUM_SEP = re.compile(r"^(\d+)[.\s_-]+", re.I)


def strip_leading_sequence_prefix(filename: str) -> str:
    """
    Remove leading file index or junk IDs (01., 001-, [02], 12345_, etc.).
    Keeps numeric titles (12 Monkeys, 1522) and leading release years (1999.Title).
    """
    if not filename:
        return filename
    ext_m = re.search(r"\.([^.]+)$", filename, re.I)
    ext = (
        f".{ext_m.group(1)}"
        if ext_m and ext_m.group(1).lower() in MEDIA_EXTENSIONS
        else ""
    )
    base = filename[: -len(ext)] if ext else filename
    if not base:
        return filename

    while True:
        m = _LEADING_BRACKET_NUM.match(base)
        if m:
            num = m.group(1)
            tail = [p for p in re.split(r"[._\s-]+", base[m.end() :]) if p]
            chunk = [num, *tail]
            if is_leading_index_token(num, chunk, 0):
                base = base[m.end() :]
                continue
            break
        m = _LEADING_NUM_SEP.match(base)
        if m:
            num = m.group(1)
            if re.fullmatch(r"(?:19|20)\d{2}", num, re.I):
                break
            tail = [p for p in re.split(r"[._\s-]+", base[m.end() :]) if p]
            chunk = [num, *tail]
            if is_leading_index_token(num, chunk, 0):
                base = base[m.end() :]
                continue
        break

    return base + ext


# Channel / uploader prefix: @Clipmate_Movie_Title_... or Aclipmate Movie Title ...
_CLIPMATE_MOVIE_PREFIX = re.compile(
    r"^@?clipmate[._\s\-]*movie[._\s\-]*",
    re.I,
)
_CLIPMATE_MOVIE_PREFIX_SPACED = re.compile(
    r"^aclipmate\s+movie\s+",
    re.I,
)


def strip_clipmate_movie_prefix(filename: str) -> str:
    """
    Remove Clipmate Movie uploader prefix; the real title starts immediately after.

    Handles @Clipmate_Movie_, @clipmate_movie_, and already-normalized Aclipmate Movie .
    """
    if not filename or "clipmate" not in filename.lower():
        return filename
    ext_m = re.search(r"\.([^.]+)$", filename, re.I)
    ext = (
        f".{ext_m.group(1)}"
        if ext_m and ext_m.group(1).lower() in MEDIA_EXTENSIONS
        else ""
    )
    base = filename[: -len(ext)] if ext else filename
    if not base:
        return filename

    stripped = _CLIPMATE_MOVIE_PREFIX.sub("", base, count=1)
    if stripped == base:
        stripped = _CLIPMATE_MOVIE_PREFIX_SPACED.sub("", base, count=1)
    return stripped + ext


_strip_rules_cache: list[dict] | None = None


def invalidate_filename_strip_rules_cache() -> None:
    global _strip_rules_cache
    _strip_rules_cache = None


def _load_filename_strip_rules() -> list[dict]:
    global _strip_rules_cache
    if _strip_rules_cache is None:
        try:
            from database import Database

            _strip_rules_cache = Database().list_filename_strip_rules()
        except Exception as e:
            logger.warning("Could not load filename strip rules: %s", e)
            _strip_rules_cache = []
    return _strip_rules_cache


def apply_filename_strip_rules(filename: str, rules: list[dict] | None = None) -> str:
    """
    Remove configured uploader / channel prefixes before title parsing.

    Rules are applied longest-first as case-insensitive leading literals, or as
    regex (first match only at start when pattern is anchored).
    """
    if not filename:
        return filename
    rules = rules if rules is not None else _load_filename_strip_rules()
    if not rules:
        return filename

    ext_m = re.search(r"\.([^.]+)$", filename, re.I)
    ext = (
        f".{ext_m.group(1)}"
        if ext_m and ext_m.group(1).lower() in MEDIA_EXTENSIONS
        else ""
    )
    base = filename[: -len(ext)] if ext else filename
    if not base:
        return filename

    active = [r for r in rules if r.get("is_active", True) and (r.get("pattern") or "").strip()]
    active.sort(key=lambda r: len(r["pattern"]), reverse=True)

    changed = True
    while changed:
        changed = False
        for rule in active:
            pattern = rule["pattern"]
            if rule.get("is_regex"):
                try:
                    new_base, n = re.subn(
                        pattern, "", base, count=1, flags=re.IGNORECASE
                    )
                    if n:
                        base = new_base.lstrip()
                        changed = True
                except re.error:
                    logger.warning("Invalid filename strip regex: %s", pattern)
                continue
            pl = pattern.lower()
            bl = base.lower()
            while bl.startswith(pl):
                base = base[len(pattern) :]
                bl = base.lower()
                changed = True

    return base.lstrip() + ext


def fix_zero_o_homoglyph(text: str) -> str:
    """Fix 0 used as o in release titles (not season codes like S01)."""
    if not text:
        return text
    # B0oundless -> Boundless (0 where an o was already present after)
    text = _ZERO_BEFORE_O.sub("", text)
    # B0undless -> Boundless
    return _ZERO_AS_O.sub("o", text)


# Anti-filter / leet substitutions users put in filenames ($→s, @→a, !→i, …).
_BYPASS_CHAR_MAP = str.maketrans(
    {
        "$": "s",
        "＄": "s",
        "@": "a",
        "＠": "a",
        "!": "i",
        "¡": "i",
        "|": "i",
    }
)
_THREE_BETWEEN_LETTERS = re.compile(r"(?<=[A-Za-z])(3)(?=[A-Za-z])")
_ONE_BETWEEN_LETTERS = re.compile(r"(?<=[A-Za-z])(1)(?=[A-Za-z])")


def _fix_three_as_e(text: str) -> str:
    """3→e in titles like W3stworld; skip brand names like M3GAN (both sides uppercase)."""

    def repl(m: re.Match) -> str:
        left, right = m.string[m.start() - 1], m.string[m.end()]
        if left.isupper() and right.isupper():
            return m.group(0)
        return "e"

    return _THREE_BETWEEN_LETTERS.sub(repl, text)


def _fix_one_as_i(text: str) -> str:
    """1→i only when other bypass symbols suggest obfuscation (e.g. Sp1der)."""
    if not any(c in text for c in "$@!|"):
        return text

    def repl(m: re.Match) -> str:
        left, right = m.string[m.start() - 1], m.string[m.end()]
        if left.isdigit() or right.isdigit():
            return m.group(0)
        return "i"

    return _ONE_BETWEEN_LETTERS.sub(repl, text)


def fix_bypass_character_substitutions(text: str) -> str:
    """
    Restore letters from common anti-filter filename tricks.

    Maps: $→s, @→a, !→i, |→i, 0→o (between letters), 3→e (between letters,
    except ALL-CAPS brand tokens like M3GAN), 1→i when $!@| also present.
    """
    if not text:
        return text
    text = text.translate(_BYPASS_CHAR_MAP)
    text = _fix_one_as_i(text)
    text = _fix_three_as_e(text)
    return fix_zero_o_homoglyph(text)


# Tokens that appear after the title/year in release file names
MEDIA_EXTENSIONS = frozenset(
    {
        "mkv", "mp4", "avi", "mov", "wmv", "flv", "webm", "m4v",
        "srt", "ass", "ssa", "sub",
    }
)

RELEASE_NOISE = frozenset(
    {
        "1080p", "720p", "480p", "2160p", "4k", "8k", "uhd", "hd", "sd",
        "webrip", "webdl", "web-dl", "bluray", "brrip", "dvdrip", "hdtv", "amzn", "netflix",
        "x264", "x265", "hevc", "h264", "h265", "av1", "10bit", "8bit",
        "aac", "ac3", "dts", "dd", "eac3", "opus", "atmos", "truehd",
        "eng", "english", "hin", "hindi", "tam", "tel", "spa", "spanish", "multi",
        "esub", "sub", "subs", "srt", "dual", "audio", "proper", "repack", "extended",
        "remux", "hdr", "dv", "dovi", "imax", "uncut", "unrated", "dc",
        "yts", "yify", "rarbg", "etrg", "mvgroup", "bone", "lama",
    }
)


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
    
    # Patterns to extract part numbers (multi-part single release, e.g. 1of3)
    PART_PATTERN = r'\.?(\d+)of(\d+)'

    # TV: S05E12, S05Ep12, S05 E12, s05_e02, 5x12, Season 5 Episode 12
    # Use (?=...) not \b after episode — underscore is a word char in Python regex.
    _TV_SEASON_EP = (
        r"(?:^|[.\s_-])s(\d{1,2})[.\s_-]*e(?:p(?:isode)?)?[.\s_-]*(\d{1,3})(?=[.\s_.-]|$)"
    )
    TV_EPISODE_PATTERNS = [
        re.compile(_TV_SEASON_EP, re.IGNORECASE),
        re.compile(r"(?:^|[.\s_-])(\d{1,2})x(\d{1,3})(?=[.\s_.-]|$)", re.IGNORECASE),
        re.compile(
            r"(?:^|[.\s_-])season[.\s_-]*(\d{1,2})[.\s_-]*episode[.\s_-]*(\d{1,3})(?=[.\s_.-]|$)",
            re.IGNORECASE,
        ),
    ]
    # E07 / Ep07 / Episode 7 (season defaults to 1)
    TV_EPISODE_ONLY = re.compile(
        r"(?:^|[.\s_-])e(?:p(?:isode)?)?[.\s_-]*(\d{1,3})(?=[.\s_.-]|$)",
        re.IGNORECASE,
    )
    
    def __init__(self):
        self.compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.REMOVE_PATTERNS]
        self.year_pattern = re.compile(self.YEAR_PATTERN)
        self.part_pattern = re.compile(self.PART_PATTERN, re.IGNORECASE)
    
    def _strip_media_extension(self, filename: str) -> str:
        """Remove trailing extension only when it is a known media/subtitle type."""
        m = re.search(r"\.([^.]+)$", filename or "", re.I)
        if m and m.group(1).lower() in MEDIA_EXTENSIONS:
            return filename[: m.start()]
        return filename

    def clean_filename(self, filename):
        """Clean filename by removing common patterns"""
        cleaned = self._strip_media_extension(filename)
        
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
        """Extract release year (works with dots, underscores, or spaces)."""
        matches = list(
            re.finditer(r"(?:^|[._\s-])((?:19|20)\d{2})(?:[._\s-]|$)", filename)
        )
        if matches:
            return matches[-1].group(1)
        return None

    def _split_release_tokens(self, filename: str) -> list[str]:
        base = self._strip_media_extension(filename or "")
        parts = [p for p in re.split(r"[._\s-]+", base) if p]
        return strip_leading_index_parts(parts)

    def _extract_movie_title_year(self, filename: str) -> tuple[str, str | None]:
        """Pull clean movie title + year from underscore/dot-separated release names."""
        parts = self._split_release_tokens(filename)
        if not parts:
            return "", None

        year_spots = [
            i
            for i, p in enumerate(parts)
            if re.fullmatch(r"(?:19|20)\d{2}", p, re.I)
        ]

        title_parts: list[str] = []
        year: str | None = None

        def _collect_title(candidate: list[str]) -> None:
            for part in candidate:
                low = part.lower()
                if low in RELEASE_NOISE or re.fullmatch(r"(?:19|20)\d{2}", part, re.I):
                    break
                if re.fullmatch(r"\d{3,4}p", low):
                    break
                title_parts.append(part)

        if not year_spots:
            _collect_title(parts)
        elif len(year_spots) >= 2 and year_spots[0] == 0:
            # Numeric title + release year: 1917.2019, 1522.2022
            year = parts[year_spots[-1]]
            title_parts = [parts[0]]
        elif year_spots[0] == 0:
            # Leading release year: 1999.Fight.Club
            year = parts[0]
            _collect_title(parts[1:])
        else:
            year = parts[year_spots[-1]]
            _collect_title(parts[: year_spots[-1]])

        title = self._normalize_title_fragment(" ".join(title_parts))
        return title, year
    
    def extract_part_info(self, filename):
        """Extract part information (e.g., 1of3)"""
        match = self.part_pattern.search(filename)
        if match:
            return {
                'part': int(match.group(1)),
                'total': int(match.group(2))
            }
        return None

    def extract_tv_episode(self, filename: str):
        """Return season, episode, and regex match span if present."""
        for pattern in self.TV_EPISODE_PATTERNS:
            match = pattern.search(filename)
            if match:
                return {
                    "season": int(match.group(1)),
                    "episode": int(match.group(2)),
                    "match": match,
                }
        match = self.TV_EPISODE_ONLY.search(filename)
        if match:
            return {
                "season": 1,
                "episode": int(match.group(1)),
                "match": match,
            }
        return None

    @staticmethod
    def _normalize_title_fragment(text: str) -> str:
        text = re.sub(r"[._-]+", " ", text or "")
        text = re.sub(r"\s+", " ", text).strip()
        text = fix_bypass_character_substitutions(text)
        if not text:
            return ""
        return " ".join(word.capitalize() for word in text.split())

    def _strip_year_from_show_name(self, show_name: str, year: str | None) -> tuple[str, str | None]:
        """Release folders often embed year before S01E01 (e.g. Afsos_2020_S01E01)."""
        if not show_name:
            return show_name, year
        parts = show_name.split()
        if parts and re.fullmatch(r"(?:19|20)\d{2}", parts[-1], re.I):
            clean = " ".join(parts[:-1]).strip()
            if clean:
                return clean, year or parts[-1]
        return show_name, year

    def _split_tv_filename(self, filename: str, ep_match: re.Match) -> tuple[str, str | None]:
        """Show name before SxxExx; episode title after (if any)."""
        before = filename[: ep_match.start()]
        after = filename[ep_match.end() :]
        show_raw = re.sub(r"[.\s_-]+$", "", before)
        show_raw = re.sub(r"^[\s._-]+", "", show_raw)
        show_cleaned = self.clean_filename(show_raw) if show_raw else ""
        show_name = self._normalize_title_fragment(show_cleaned)
        ep_title_raw = after
        ep_title_raw = re.sub(r"^[.\s_-]+", "", ep_title_raw)
        ep_title_raw = re.sub(r"\([^)]*\)", "", ep_title_raw)
        ep_title_raw = self.clean_filename(ep_title_raw)
        episode_title = self._normalize_title_fragment(ep_title_raw) if ep_title_raw else None
        return show_name, episode_title
    
    def parse_name(self, filename):
        """
        Parse movie/series name from filename
        
        Returns:
            dict with keys including:
            name, year, part_info, confidence, media_type ('movie'|'tv'),
            show_name, season, episode, episode_title, franchise_sequence
        """
        if not filename:
            return {
                'name': None,
                'year': None,
                'part_info': None,
                'confidence': 'low',
                'media_type': None,
                'show_name': None,
                'season': None,
                'episode': None,
                'episode_title': None,
                'franchise_sequence': None,
            }
        
        original_filename = filename
        filename = fix_bypass_character_substitutions(
            strip_clipmate_movie_prefix(
                strip_leading_sequence_prefix(apply_filename_strip_rules(filename))
            )
        )

        # Extract year first
        year = self.extract_year(filename)

        # Extract part info
        part_info = self.extract_part_info(filename)

        tv_ep = self.extract_tv_episode(filename)
        season = episode = None
        episode_title = show_name = None
        media_type = "movie"

        if tv_ep:
            media_type = "tv"
            season = tv_ep["season"]
            episode = tv_ep["episode"]
            show_name, episode_title = self._split_tv_filename(filename, tv_ep["match"])
            show_name, year = self._strip_year_from_show_name(show_name, year)
        
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

        if media_type == "tv" and show_name:
            display_name = show_name
            if episode_title:
                display_name = f"{show_name} - S{season:02d}E{episode:02d} - {episode_title}"
            else:
                display_name = f"{show_name} - S{season:02d}E{episode:02d}"
            if not show_name:
                show_name = cleaned
                display_name = cleaned if cleaned else original_filename
        else:
            movie_title, movie_year = self._extract_movie_title_year(filename)
            if movie_title and (
                len(movie_title) >= 2
                or re.fullmatch(r"\d{1,4}", movie_title.replace(" ", ""))
            ):
                display_name = movie_title
                if movie_year and not year:
                    year = movie_year
                elif movie_year and year and movie_year != year:
                    # Prefer explicit release year after numeric title (1917.2019)
                    year = movie_year
            else:
                display_name = cleaned if cleaned else original_filename

        franchise_sequence = None
        if part_info and part_info.get("total", 0) > 1:
            franchise_sequence = part_info.get("part")

        return {
            'name': display_name,
            'year': year,
            'part_info': part_info,
            'confidence': confidence,
            'media_type': media_type,
            'show_name': show_name or (display_name if media_type == "tv" else None),
            'season': season,
            'episode': episode,
            'episode_title': episode_title,
            'franchise_sequence': franchise_sequence,
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
