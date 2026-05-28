"""
TMDB API helper for movie/series name validation and enrichment
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
import urllib.error
import urllib.parse
import urllib.request
from html import escape
from typing import Any

from config import Config
from name_parser import fix_bypass_character_substitutions

logger = logging.getLogger(__name__)

try:
    from tmdbv3api import TMDb, Movie, TV

    TMDB_AVAILABLE = True
except ImportError:
    TMDB_AVAILABLE = False
    logger.warning("tmdbv3api not available. TMDB features will use REST API only.")


def _normalize_title(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def split_title_year(title: str) -> tuple[str, int | None]:
    """Pull a trailing release year out of a title (e.g. 'Afsos 2020' -> 'Afsos', 2020)."""
    raw = (title or "").strip()
    if not raw:
        return "", None
    m = re.match(r"^(.*?)[\s._-]+((?:19|20)\d{2})\s*$", raw)
    if m and m.group(1).strip():
        return m.group(1).strip(), int(m.group(2))
    return raw, None


def search_title_without_leading_number(title: str) -> str | None:
    """
    If title starts with a folder/franchise index (5 Harry Potter), return the rest.
    Keeps numeric titles: 12 Monkeys, 10 Cloverfield Lane, 9, 1917.
    """
    base, _yr = split_title_year((title or "").strip())
    if not base:
        return None
    m = re.match(r"^(\d{1,3})\s+(.+)$", base)
    if not m:
        return None
    num, rest = m.group(1), m.group(2).strip()
    if not rest or re.fullmatch(r"(?:19|20)\d{2}", num, re.I):
        return None
    word_tokens = [w for w in rest.split() if re.fullmatch(r"[A-Za-z]{2,}", w)]
    if len(word_tokens) <= 1:
        return None  # 12 Monkeys, 1522-only paths
    if len(num) == 2 and int(num) >= 10:
        return None  # 10 Cloverfield Lane, 12 Monkeys
    if len(num) <= 2 and int(num) < 10:
        return rest
    return None


def _typo_search_variants(base: str) -> list[str]:
    """Common release-name typos / missing words for TMDB."""
    out: list[str] = []
    if re.search(r"phoneix", base, re.I):
        out.append(re.sub(r"phoneix", "phoenix", base, flags=re.I))
    if re.search(r"harry\s*potter", base, re.I) and re.search(
        r"order\s+of", base, re.I
    ):
        if not re.search(r"order\s+of\s+the", base, re.I):
            out.append(
                re.sub(
                    r"\bAnd\s+Order\s+Of\b",
                    "and the Order of the",
                    base,
                    count=1,
                    flags=re.I,
                )
            )
        out.append("Harry Potter and the Order of the Phoenix")
    if re.search(r"\barea\b", base, re.I) and "ares" not in base.lower():
        fixed = re.sub(r"\barea\b", "Ares", base, flags=re.I)
        if fixed.lower() != base.lower():
            out.append(fixed)
    if re.search(r"\btron\b", base, re.I):
        if re.search(r"\barea\b", base, re.I):
            out.append("Tron Ares")
            out.append("TRON: Ares")
    return out


def title_search_variants(title: str) -> list[str]:
    """Build TMDB search queries from a cleaned title (apostrophe / word trims)."""
    if not title:
        return []
    base, _yr = split_title_year(title.strip())
    without_num = search_title_without_leading_number(base)
    # Prefer search without folder index (5 Harry Potter -> Harry Potter), then with
    variants: list[str] = []
    if without_num and without_num.lower() != base.lower():
        variants.append(without_num)
    variants.append(base)

    fixed = fix_bypass_character_substitutions(base)
    if fixed != base:
        variants.append(fixed)
    if without_num:
        fixed_wo = fix_bypass_character_substitutions(without_num)
        if fixed_wo != without_num:
            variants.append(fixed_wo)

    for v in _typo_search_variants(base):
        variants.append(v)
    if without_num:
        for v in _typo_search_variants(without_num):
            variants.append(v)

    # A Widows Game -> A Widow's Game
    if re.search(r"\bWidows\b", base, re.I):
        variants.append(re.sub(r"\bWidows\b", "Widow's", base, flags=re.I))
    if re.search(r"\bWidow\b", base, re.I) and "Widow's" not in base:
        variants.append(re.sub(r"\bWidow\b", "Widow's", base, count=1, flags=re.I))
    # Drop leading article for search
    m = re.match(r"^(The|A|An)\s+(.+)$", base, re.I)
    if m:
        variants.append(m.group(2))
    if without_num:
        m2 = re.match(r"^(The|A|An)\s+(.+)$", without_num, re.I)
        if m2:
            variants.append(m2.group(2))
    # Unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        key = v.lower()
        if key not in seen and len(v) >= 2:
            seen.add(key)
            out.append(v)
    return out


def _overview_snip(text: str | None, max_len: int = 22) -> str:
    t = " ".join((text or "").split())
    if not t:
        return ""
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def tmdb_web_url(s: dict) -> str:
    tid = s.get("tmdb_id")
    if not tid:
        return ""
    path = "tv" if (s.get("media_type") or "").lower() in ("tv", "series") else "movie"
    return f"https://www.themoviedb.org/{path}/{tid}"


def poster_image_url(s: dict, *, size: str = "w342") -> str | None:
    pp = s.get("poster_path")
    if not pp:
        return None
    if str(pp).startswith("http"):
        return str(pp)
    return f"https://image.tmdb.org/t/p/{size}{pp}"


def suggestion_has_poster_art(s: dict) -> bool:
    """True when TMDB returned a poster image path."""
    pp = s.get("poster_path")
    if pp is None:
        return False
    s_pp = str(pp).strip()
    return bool(s_pp) and s_pp.lower() not in ("null", "none")


def sort_suggestions_poster_first(suggestions: list[dict]) -> list[dict]:
    """Stable sort: results with poster art first; saved hints tie-break within each tier."""
    indexed = list(enumerate(suggestions))
    indexed.sort(
        key=lambda t: (
            0 if suggestion_has_poster_art(t[1]) else 1,
            0 if t[1].get("from_hint") else 1,
            t[0],
        )
    )
    return [s for _, s in indexed]


def best_poster_url(s: dict, *, size: str = "w342") -> str | None:
    """Poster first, then backdrop if TMDB has no poster art."""
    url = poster_image_url(s, size=size)
    if url:
        return url
    bp = s.get("backdrop_path")
    if bp:
        return poster_image_url({"poster_path": bp}, size="w500")
    return None


def format_suggestion_card_caption(s: dict, index: int, *, overview_chars: int = 900) -> str:
    """Single suggestion card: title, year, rating, id, plot (for one Telegram message)."""
    kind = "Movie" if s.get("media_type") == "movie" else "TV series"
    title = escape((s.get("title") or "?").strip())
    yr = escape(str(s.get("year") or "?"))
    tid = s.get("tmdb_id")
    vote_s = ""
    vote = s.get("vote_average")
    if vote not in (None, ""):
        try:
            vote_s = f"\n⭐ <b>{float(vote):.1f}</b> / 10 on TMDB"
        except (TypeError, ValueError):
            pass
    page = tmdb_web_url(s)
    link = f'\n<a href="{escape(page)}">Open on TMDB</a>' if page else ""
    hint = "⭐ <i>Saved from your last pick</i>\n\n" if s.get("from_hint") else ""
    overview = (s.get("overview") or "").strip()
    if overview:
        overview = escape(overview)
        if len(overview) > overview_chars:
            overview = overview[: overview_chars - 1] + "…"
        plot_block = f"\n\n<b>Plot</b>\n{overview}"
    else:
        plot_block = "\n\n<i>No plot listed on TMDB.</i>"
    return (
        f"{hint}<b>{index}. {kind}</b>\n"
        f"<b>{title}</b> ({yr})\n"
        f"TMDB ID: <code>#{tid}</code>{vote_s}{plot_block}{link}"
    )


def format_suggestions_detail_html(
    suggestions: list[dict],
    *,
    max_items: int = 5,
    overview_chars: int = 300,
) -> str:
    """Readable plot + links in the message body (not on tiny buttons)."""
    blocks: list[str] = []
    for i, s in enumerate(suggestions[:max_items], 1):
        kind = "Movie" if s.get("media_type") == "movie" else "TV"
        title = escape((s.get("title") or "?").strip())
        yr = escape(str(s.get("year") or "?"))
        tid = s.get("tmdb_id")
        vote = s.get("vote_average")
        vote_s = ""
        if vote not in (None, ""):
            try:
                vote_s = f" · ★{float(vote):.1f}"
            except (TypeError, ValueError):
                pass
        url = tmdb_web_url(s)
        link = f' · <a href="{escape(url)}">TMDB page</a>' if url else ""
        overview = (s.get("overview") or "").strip()
        if overview:
            overview = escape(overview)
            if len(overview) > overview_chars:
                overview = overview[: overview_chars - 1] + "…"
        else:
            overview = "<i>No overview on TMDB</i>"
        blocks.append(
            f"<b>{i}.</b> {kind}: <b>{title}</b> ({yr}) · <code>#{tid}</code>{vote_s}{link}\n"
            f"{overview}"
        )
    return "\n\n".join(blocks)


def suggestion_pick_button_label(s: dict, index: int, *, max_len: int = 64) -> str:
    """Compact picker — match number to the list / poster captions above."""
    title = (s.get("title") or "?").strip()
    if len(title) > 24:
        title = title[:21] + "…"
    yr = s.get("year") or "?"
    tid = s.get("tmdb_id")
    vote_s = ""
    vote = s.get("vote_average")
    if vote not in (None, ""):
        try:
            vote_s = f" ★{float(vote):.1f}"
        except (TypeError, ValueError):
            pass
    mark = "⭐" if s.get("from_hint") else str(index)
    label = f"{mark}. {title} ({yr}) #{tid}{vote_s}"
    if len(label) > max_len:
        label = f"{mark}. {title[:14]}… #{tid}"
    return label


def suggestion_button_label(s: dict, *, max_len: int = 64) -> str:
    """Telegram button text with TMDB id + hints so duplicate titles are distinguishable."""
    kind = "🎬" if s.get("media_type") == "movie" else "📺"
    title = (s.get("title") or "?").strip()
    yr = s.get("year") or "?"
    prefix = "⭐ " if s.get("from_hint") else ""
    tid = s.get("tmdb_id")
    id_part = f" #{tid}" if tid else ""

    extras: list[str] = []
    vote = s.get("vote_average")
    if vote not in (None, ""):
        try:
            extras.append(f"★{float(vote):.1f}")
        except (TypeError, ValueError):
            pass
    orig = (s.get("original_title") or "").strip()
    if orig and _normalize_title(orig) != _normalize_title(title):
        extras.append(orig[:14] + ("…" if len(orig) > 14 else ""))
    snip = s.get("overview_snip") or _overview_snip(s.get("overview"))
    if snip and not extras:
        extras.append(snip)
    elif snip and len(extras) == 1:
        extras.append(snip[:18] + ("…" if len(snip) > 18 else ""))

    suffix = f" · {' · '.join(extras[:2])}" if extras else ""
    label = f"{prefix}{kind} {title} ({yr}){id_part}{suffix}"
    if len(label) > max_len:
        label = f"{prefix}{kind} {title} ({yr}){id_part}"
    if len(label) > max_len:
        label = label[: max_len - 1] + "…"
    return label


def movie_release_status(release_date: str | None) -> str:
    """
    Classify a TMDB movie for collection tracking.

    Returns:
        released — in theaters / past release date
        upcoming — release date in the future
        announced — no date yet (planned sequel on TMDB)
    """
    raw = (release_date or "").strip()
    if not raw:
        return "announced"
    try:
        rd = date.fromisoformat(raw[:10])
    except ValueError:
        return "announced"
    if rd > date.today():
        return "upcoming"
    return "released"


def titles_match(a: str, b: str) -> bool:
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def _is_transient_network_error(exc: BaseException | str | None) -> bool:
    msg = str(exc or "").lower()
    return any(
        m in msg
        for m in (
            "connection reset",
            "timed out",
            "timeout",
            "connection refused",
            "network is unreachable",
            "errno 54",
            "errno 60",
            "broken pipe",
        )
    )


class TMDBHelper:
    """Helper class for TMDB API operations"""

    def __init__(self):
        self.enabled = False
        self.tmdb = None
        self.movie_api = None
        self.tv_api = None
        self._last_api_error: str | None = None
        self._details_cache: dict[tuple[str, int], dict] = {}
        self._tv_tracking_cache: dict[int, dict] = {}
        self._collection_cache: dict[int, dict] = {}
        self._movie_collection_cache: dict[int, int | None] = {}
        self._api_key = (Config.TMDB_API_KEY or "").strip()

        if not self._api_key or self._api_key == "your_tmdb_api_key":
            return

        self.enabled = True
        if TMDB_AVAILABLE:
            try:
                self.tmdb = TMDb()
                self.tmdb.api_key = self._api_key
                self.tmdb.language = "en"
                self.movie_api = Movie()
                self.tv_api = TV()
                logger.info("TMDB API initialized successfully")
            except Exception as e:
                logger.error("Failed to initialize tmdbv3api: %s", e)

    def _api_get(self, path: str, **params: Any) -> dict | list | None:
        if not self.enabled:
            return None
        params = {k: v for k, v in params.items() if v is not None}
        params["api_key"] = self._api_key
        params.setdefault("language", "en")
        url = f"https://api.themoviedb.org/3{path}?{urllib.parse.urlencode(params)}"
        last_err: Exception | None = None
        max_attempts = 4
        for attempt in range(max_attempts):
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "IndexBot/1.0 (+https://github.com)",
                    },
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    self._last_api_error = None
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                body = e.read()[:200]
                logger.error("TMDB HTTP %s %s: %s", e.code, path, body)
                self._last_api_error = f"HTTP {e.code}"
                return None
            except Exception as e:
                last_err = e
                self._last_api_error = str(e)
                if attempt < max_attempts - 1 and _is_transient_network_error(e):
                    time.sleep(min(4.0, 0.5 * (2**attempt)))
                    continue
                break
        logger.error("TMDB request %s failed after retries: %s", path, last_err)
        return None

    def ping(self) -> dict[str, Any]:
        """Quick connectivity check for portal health / diagnostics."""
        if not self.enabled:
            return {"ok": False, "error": "TMDB_API_KEY not configured"}
        data = self._api_get("/configuration")
        if data:
            return {"ok": True}
        return {"ok": False, "error": self._last_api_error or "unknown error"}

    def _parse_search_results(
        self, payload: dict | None, media_type: str, *, limit: int = 8
    ) -> list[dict]:
        if not payload or "results" not in payload:
            return []
        out = []
        for item in payload["results"][:limit]:
            if media_type == "movie":
                title = item.get("title")
                date = item.get("release_date") or ""
            else:
                title = item.get("name")
                date = item.get("first_air_date") or ""
            if not title:
                continue
            overview = (item.get("overview") or "").strip()
            if media_type == "movie":
                original = item.get("original_title") or ""
            else:
                original = item.get("original_name") or ""
            out.append(
                {
                    "tmdb_id": item.get("id"),
                    "title": title,
                    "media_type": media_type,
                    "year": date[:4] if date else None,
                    "overview": overview,
                    "overview_snip": _overview_snip(overview),
                    "original_title": original or None,
                    "vote_average": item.get("vote_average"),
                    "poster_path": item.get("poster_path"),
                }
            )
        return out

    def search_movie_suggestions(self, name: str, year: int | None = None, limit: int = 6) -> list[dict]:
        if not self.enabled or not name:
            return []
        params: dict[str, Any] = {"query": name, "include_adult": "false"}
        if year:
            params["year"] = year
        data = self._api_get("/search/movie", **params)
        return self._parse_search_results(data if isinstance(data, dict) else None, "movie", limit=limit)

    def search_tv_suggestions(self, name: str, year: int | None = None, limit: int = 6) -> list[dict]:
        if not self.enabled or not name:
            return []
        params: dict[str, Any] = {"query": name, "include_adult": "false"}
        if year:
            params["first_air_date_year"] = year
        data = self._api_get("/search/tv", **params)
        return self._parse_search_results(data if isinstance(data, dict) else None, "tv", limit=limit)

    def _search_media_suggestions_page(
        self,
        path: str,
        media_type: str,
        name: str,
        year: int | None,
        page: int,
    ) -> tuple[list[dict], int]:
        """One TMDB search page (up to 20 results)."""
        if not self.enabled or not name:
            return [], 1
        params: dict[str, Any] = {
            "query": name,
            "page": max(1, int(page)),
            "include_adult": "false",
        }
        if media_type == "movie" and year:
            params["year"] = year
        elif media_type == "tv" and year:
            params["first_air_date_year"] = year
        data = self._api_get(path, **params)
        if not isinstance(data, dict):
            return [], 1
        items = self._parse_search_results(data, media_type, limit=20)
        total_pages = max(1, int(data.get("total_pages") or 1))
        return items, total_pages

    def _collect_pick_stream(
        self,
        query: str,
        *,
        filter_type: str = "all",
        year: int | None = None,
        max_items: int,
    ) -> list[dict]:
        """Walk TMDB search pages (TV + movie) until max_items unique suggestions."""
        if not self.enabled or not query or max_items <= 0:
            return []
        clean_query, embedded_year = split_title_year(query)
        query = clean_query or query
        if embedded_year is not None and year is None:
            year = embedded_year
        ft = (filter_type or "all").lower()
        if ft not in ("all", "tv", "movie"):
            ft = "all"
        seen: set[tuple] = set()
        out: list[dict] = []
        variants = title_search_variants(query) or [query]

        for variant in variants:
            tv_page = movie_page = 1
            tv_total = movie_total = 1
            tv_exhausted = movie_exhausted = False
            while len(out) < max_items and not (tv_exhausted and movie_exhausted):
                progressed = False
                if ft in ("all", "tv") and not tv_exhausted:
                    items, tv_total = self._search_media_suggestions_page(
                        "/search/tv", "tv", variant, year, tv_page
                    )
                    tv_page += 1
                    if tv_page > tv_total:
                        tv_exhausted = True
                    for item in items:
                        key = (item.get("media_type"), item.get("tmdb_id"))
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(item)
                        progressed = True
                        if len(out) >= max_items:
                            return out
                if ft in ("all", "movie") and not movie_exhausted:
                    items, movie_total = self._search_media_suggestions_page(
                        "/search/movie", "movie", variant, year, movie_page
                    )
                    movie_page += 1
                    if movie_page > movie_total:
                        movie_exhausted = True
                    for item in items:
                        key = (item.get("media_type"), item.get("tmdb_id"))
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(item)
                        progressed = True
                        if len(out) >= max_items:
                            return out
                if not progressed and tv_exhausted and movie_exhausted:
                    break
            if out:
                break
        return sort_suggestions_poster_first(out)

    def search_pick_page(
        self,
        query: str,
        *,
        page: int = 1,
        per_page: int | None = None,
        filter_type: str = "all",
        media_type: str | None = None,
        year: int | None = None,
    ) -> dict[str, Any]:
        """
        Paginated TMDB results for manual pick UI (portal + bot load-more).

        Returns one page of suggestions plus has_more for a Load more control.
        """
        from config import Config

        per_page = max(1, int(per_page or Config.TMDB_PICK_PAGE_SIZE))
        page = max(1, int(page))
        end = page * per_page
        stream = self._collect_pick_stream(
            query,
            filter_type=filter_type,
            year=year,
            max_items=end + 1,
        )
        start = end - per_page
        items = sort_suggestions_poster_first(stream[start:end])
        has_more = len(stream) > end
        return {
            "items": items,
            "page": page,
            "per_page": per_page,
            "has_more": has_more,
            "next_page": page + 1 if has_more else None,
            "filter_type": (filter_type or "all").lower(),
        }

    def search_suggestions_multi(
        self,
        query: str,
        *,
        media_type: str | None = None,
        year: int | None = None,
        limit: int = 6,
    ) -> list[dict]:
        """Try title variants (and year/no-year) until TMDB returns results."""
        if not self.enabled or not query:
            return []
        self._last_api_error = None
        clean_query, embedded_year = split_title_year(query)
        query = clean_query or query
        if embedded_year is not None and year is None:
            year = embedded_year
        mt = (media_type or "").lower()
        seen: set[tuple] = set()
        merged: list[dict] = []

        def _fetch(variant: str, yr: int | None) -> list[dict]:
            if mt in ("tv", "series"):
                return self.search_tv_suggestions(variant, yr, limit=limit)
            if mt == "movie":
                return self.search_movie_suggestions(variant, yr, limit=limit)
            half = max(4, limit // 2)
            movies = self.search_movie_suggestions(variant, yr, limit=half)
            tv = self.search_tv_suggestions(variant, yr, limit=half)
            return self._merge_suggestion_lists(movies, tv, limit=limit)

        def _merge(batch: list[dict]) -> bool:
            for item in batch:
                key = (item.get("media_type"), item.get("tmdb_id"))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= limit:
                    return True
            return False

        stop_search = False
        for variant in title_search_variants(query):
            if stop_search:
                break
            years = [year, None] if year else [None]
            for yr in years:
                batch = _fetch(variant, yr)
                if not batch and self._last_api_error:
                    if not merged and _is_transient_network_error(self._last_api_error):
                        stop_search = True
                        break
                    continue
                if _merge(batch):
                    return merged[:limit]
            if merged:
                break
        return merged[:limit]

    def _merge_suggestion_lists(
        self, *batches: list[dict], limit: int
    ) -> list[dict]:
        seen: set[tuple] = set()
        merged: list[dict] = []
        for batch in batches:
            for item in batch or []:
                key = (item.get("media_type"), item.get("tmdb_id"))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= limit:
                    return merged
        return merged

    def search_suggestions_for_pick(
        self,
        query: str,
        *,
        media_type: str | None = None,
        year: int | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """
        Search for manual pick UI — merges preferred type + the other (e.g. TV + movies).

        Avoids cases like "One Piece" where movie spin-offs fill all slots and the TV
        series is missing.
        """
        from config import Config

        lim = max(6, int(limit or Config.TMDB_PICK_SUGGESTION_LIMIT))
        picked = self.search_pick_page(
            query,
            page=1,
            per_page=lim,
            filter_type="all",
            media_type=media_type,
            year=year,
        )
        return picked.get("items") or []

    def get_suggestions(
        self,
        query: str,
        *,
        media_type: str | None = None,
        year: int | None = None,
        limit: int = 6,
    ) -> list[dict]:
        """Return TMDB search suggestions for movies and/or TV."""
        return self.search_suggestions_multi(
            query, media_type=media_type, year=year, limit=limit
        )

    def pick_best_match(
        self, suggestions: list[dict], query: str, *, media_type: str | None = None
    ) -> dict | None:
        if not suggestions:
            return None
        mt = (media_type or "").lower()
        filtered = suggestions
        if mt in ("tv", "series"):
            filtered = [s for s in suggestions if s.get("media_type") == "tv"]
        elif mt == "movie":
            filtered = [s for s in suggestions if s.get("media_type") == "movie"]
        if not filtered:
            filtered = suggestions
        for s in filtered:
            if titles_match(query, s.get("title", "")):
                return s
        return filtered[0]

    def search_movie(self, name, year=None):
        suggestions = self.search_movie_suggestions(name, year, limit=3)
        if not suggestions:
            return None
        s = suggestions[0]
        return {
            "id": s["tmdb_id"],
            "title": s["title"],
            "year": s.get("year"),
            "type": "movie",
        }

    def search_tv(self, name, year=None):
        suggestions = self.search_tv_suggestions(name, year, limit=3)
        if not suggestions:
            return None
        s = suggestions[0]
        return {
            "id": s["tmdb_id"],
            "title": s["title"],
            "year": s.get("year"),
            "type": "tv",
        }

    def search(self, name, year=None):
        if not self.enabled:
            return None
        movie_result = self.search_movie(name, year)
        if movie_result:
            return movie_result
        return self.search_tv(name, year)

    def validate_tv_show(self, show_name, year=None):
        if not self.enabled or not show_name:
            return None
        suggestions = self.search_tv_suggestions(show_name, year, limit=5)
        match = self.pick_best_match(suggestions, show_name, media_type="tv")
        if not match:
            return None
        return {
            "correct_name": match["title"],
            "tmdb_id": match["tmdb_id"],
            "media_type": "tv",
            "year": match.get("year"),
        }

    def validate_name(self, parsed_name, year=None, *, media_type: str | None = None):
        if not self.enabled or not parsed_name:
            return None
        mt = (media_type or "").lower()
        if mt in ("tv", "series"):
            return self.validate_tv_show(parsed_name, year)
        if mt == "movie":
            suggestions = self.search_movie_suggestions(parsed_name, year, limit=5)
            match = self.pick_best_match(suggestions, parsed_name, media_type="movie")
        else:
            suggestions = self.get_suggestions(parsed_name, year=year, limit=8)
            match = self.pick_best_match(suggestions, parsed_name, media_type=mt or None)
        if not match:
            return None
        return {
            "correct_name": match["title"],
            "tmdb_id": match["tmdb_id"],
            "media_type": match["media_type"],
            "year": match.get("year"),
        }

    @staticmethod
    def _normalize_details(obj) -> dict:
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return obj
        return {k: getattr(obj, k, None) for k in dir(obj) if not k.startswith("_")}

    def fetch_movie_details(self, tmdb_id: int) -> dict | None:
        if not self.enabled or not tmdb_id:
            return None
        cache_key = ("movie", int(tmdb_id))
        if cache_key in self._details_cache:
            return self._details_cache[cache_key]
        data = self._api_get(f"/movie/{tmdb_id}")
        if isinstance(data, dict) and data.get("id"):
            genres = [g.get("name") for g in data.get("genres") or [] if g.get("name")]
            release = data.get("release_date") or ""
            year = release[:4] if release else None
            out = {
                "tmdb_title": data.get("title"),
                "release_year": int(year) if year and year.isdigit() else None,
                "overview": data.get("overview"),
                "poster_path": data.get("poster_path"),
                "backdrop_path": data.get("backdrop_path"),
                "vote_average": str(data.get("vote_average") or ""),
                "genres": genres,
            }
            self._details_cache[cache_key] = out
            return out
        return None

    def fetch_credits(self, tmdb_id: int, *, media_type: str = "movie") -> dict:
        """Cast & crew snippets for catalog cards."""
        if not self.enabled or not tmdb_id:
            return {}
        path = (
            f"/tv/{int(tmdb_id)}/credits"
            if media_type in ("tv", "series")
            else f"/movie/{int(tmdb_id)}/credits"
        )
        data = self._api_get(path)
        if not isinstance(data, dict):
            return {}
        cast = [
            c.get("name")
            for c in (data.get("cast") or [])[:8]
            if c.get("name")
        ]
        crew = data.get("crew") or []
        directors = [
            c.get("name")
            for c in crew
            if c.get("job") == "Director" and c.get("name")
        ][:3]
        writers = [
            c.get("name")
            for c in crew
            if c.get("job") in ("Writer", "Screenplay", "Story") and c.get("name")
        ][:3]
        return {"cast": cast, "directors": directors, "writers": writers}

    def fetch_tv_season_details(
        self, tv_tmdb_id: int, season_number: int
    ) -> dict | None:
        if not self.enabled or not tv_tmdb_id:
            return None
        cache_key = ("tv_season", int(tv_tmdb_id), int(season_number))
        if cache_key in self._details_cache:
            return self._details_cache[cache_key]
        data = self._api_get(f"/tv/{int(tv_tmdb_id)}/season/{int(season_number)}")
        if not isinstance(data, dict):
            return None
        episode_names: dict[int, str] = {}
        for ep in data.get("episodes") or []:
            num = ep.get("episode_number")
            name = (ep.get("name") or "").strip()
            if num is not None and name:
                episode_names[int(num)] = name
        out = {
            "name": data.get("name"),
            "overview": data.get("overview"),
            "poster_path": data.get("poster_path"),
            "episode_count": data.get("episode_count"),
            "season_number": season_number,
            "episode_names": episode_names,
        }
        self._details_cache[cache_key] = out
        return out

    def get_tv_episode_name(
        self, tv_tmdb_id: int, season_number: int, episode_number: int
    ) -> str | None:
        season = self.fetch_tv_season_details(int(tv_tmdb_id), int(season_number))
        if not season:
            return None
        return (season.get("episode_names") or {}).get(int(episode_number))

    def build_catalog_enrichment(
        self, *, tmdb_id: int, media_type: str, season_number: int | None = None
    ) -> dict:
        """Merge details + credits (+ TV season) for watch catalog cards."""
        mt = (media_type or "movie").lower()
        base: dict = {}
        if mt in ("tv", "series"):
            base = self.fetch_tv_details(tmdb_id) or {}
            if season_number is not None:
                season = self.fetch_tv_season_details(tmdb_id, int(season_number))
                if season:
                    if season.get("overview"):
                        base["overview"] = season["overview"]
                    if season.get("poster_path"):
                        base["poster_path"] = season["poster_path"]
                    base["season_name"] = season.get("name")
                    base["episode_count"] = season.get("episode_count")
        else:
            base = self.fetch_movie_details(tmdb_id) or {}
        credits = self.fetch_credits(tmdb_id, media_type=mt)
        base.update(credits)
        return base

    def fetch_tv_details(self, tmdb_id: int) -> dict | None:
        if not self.enabled or not tmdb_id:
            return None
        cache_key = ("tv", int(tmdb_id))
        if cache_key in self._details_cache:
            return self._details_cache[cache_key]
        data = self._api_get(f"/tv/{tmdb_id}")
        if isinstance(data, dict) and data.get("id"):
            genres = [g.get("name") for g in data.get("genres") or [] if g.get("name")]
            air = data.get("first_air_date") or ""
            year = air[:4] if air else None
            out = {
                "tmdb_title": data.get("name"),
                "release_year": int(year) if year and year.isdigit() else None,
                "overview": data.get("overview"),
                "poster_path": data.get("poster_path"),
                "backdrop_path": data.get("backdrop_path"),
                "vote_average": str(data.get("vote_average") or ""),
                "genres": genres,
            }
            self._details_cache[cache_key] = out
            return out
        return None

    def fetch_tv_tracking(self, tv_tmdb_id: int) -> dict | None:
        """Season/episode totals for admin tracking (cached)."""
        if not self.enabled or not tv_tmdb_id:
            return None
        tid = int(tv_tmdb_id)
        if tid in self._tv_tracking_cache:
            return self._tv_tracking_cache[tid]
        data = self._api_get(f"/tv/{tid}")
        if not isinstance(data, dict) or not data.get("id"):
            return None
        seasons: list[dict] = []
        for s in data.get("seasons") or []:
            sn = s.get("season_number")
            if sn is None or int(sn) < 1:
                continue
            seasons.append(
                {
                    "season_number": int(sn),
                    "episode_count": int(s.get("episode_count") or 0),
                    "name": (s.get("name") or "").strip(),
                }
            )
        seasons.sort(key=lambda x: x["season_number"])
        season_ep_total = sum(s["episode_count"] for s in seasons)
        api_ep_total = int(data.get("number_of_episodes") or 0)
        out = {
            "tmdb_id": tid,
            "name": data.get("name"),
            "number_of_seasons": len(seasons),
            "number_of_episodes": season_ep_total or api_ep_total,
            "seasons": seasons,
        }
        self._tv_tracking_cache[tid] = out
        return out

    def fetch_collection_by_id(self, collection_id: int) -> dict | None:
        if not self.enabled or not collection_id:
            return None
        cid = int(collection_id)
        if cid in self._collection_cache:
            return self._collection_cache[cid]
        data = self._api_get(f"/collection/{cid}")
        if not isinstance(data, dict) or not data.get("id"):
            return None
        parts = []
        for p in data.get("parts") or []:
            if not p.get("id"):
                continue
            if (p.get("media_type") or "movie") == "collection":
                continue
            release_date = (p.get("release_date") or "").strip() or None
            rd_year = release_date[:4] if release_date and len(release_date) >= 4 else None
            status = movie_release_status(release_date)
            parts.append(
                {
                    "tmdb_id": int(p["id"]),
                    "title": p.get("title") or "?",
                    "year": rd_year,
                    "release_date": release_date,
                    "release_status": status,
                }
            )
        parts.sort(
            key=lambda x: (
                {"released": 0, "upcoming": 1, "announced": 2}.get(
                    x.get("release_status"), 1
                ),
                x.get("release_date") or "9999",
                x.get("title") or "",
            )
        )
        out = {
            "collection_id": cid,
            "name": data.get("name") or "Collection",
            "parts": parts,
        }
        self._collection_cache[cid] = out
        return out

    def fetch_collection_for_movie(self, movie_tmdb_id: int) -> dict | None:
        """TMDB belongs_to_collection for a movie, with full parts list."""
        if not self.enabled or not movie_tmdb_id:
            return None
        mid = int(movie_tmdb_id)
        if mid in self._movie_collection_cache:
            cid = self._movie_collection_cache[mid]
            return self.fetch_collection_by_id(cid) if cid else None
        data = self._api_get(f"/movie/{mid}")
        if not isinstance(data, dict):
            self._movie_collection_cache[mid] = None
            return None
        belongs = data.get("belongs_to_collection")
        if not belongs or not belongs.get("id"):
            self._movie_collection_cache[mid] = None
            return None
        cid = int(belongs["id"])
        self._movie_collection_cache[mid] = cid
        coll = self.fetch_collection_by_id(cid)
        if coll and not coll.get("name"):
            coll["name"] = belongs.get("name") or "Collection"
        return coll


tmdb_helper = TMDBHelper()
