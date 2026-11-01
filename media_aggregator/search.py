"""Search ranking, query normalization, fuzzy matching, and result deduplication engine."""

from __future__ import annotations

import difflib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from media_aggregator.models import MediaItem, MediaType

logger = logging.getLogger("media_aggregator.search")

COMMON_ARTICLES = {"the", "a", "an"}
MEDIA_TYPE_HINTS = {
    "movie": MediaType.MOVIE,
    "movies": MediaType.MOVIE,
    "film": MediaType.MOVIE,
    "films": MediaType.MOVIE,
    "series": MediaType.SERIES,
    "tvshow": MediaType.SERIES,
    "tvseries": MediaType.SERIES,
    "anime": MediaType.ANIME,
}


@dataclass
class ParsedQuery:
    """Structured representation of a user search query."""
    raw: str
    clean: str
    normalized: str
    normalized_no_articles: str
    tokens: List[str]
    target_year: Optional[int] = None
    target_type: Optional[MediaType] = None


def normalize_title(title: str) -> str:
    """Normalize title for comparison: lowercase, remove accents, and strip punctuation."""
    if not title:
        return ""
    # Decompose unicode characters into base letters + combining marks
    text = unicodedata.normalize("NFKD", title)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    # Replace non-alphanumeric and underscore with spaces
    text = re.sub(r"[^\w\s]|_", " ", text)
    # Collapse multiple spaces
    return " ".join(text.split())


def strip_articles(norm_title: str) -> str:
    """Strip common leading articles ('the', 'a', 'an') from normalized title."""
    words = norm_title.split()
    if words and words[0] in COMMON_ARTICLES:
        return " ".join(words[1:])
    return norm_title


def parse_search_query(query: str) -> ParsedQuery:
    """Extract release year, media type hints, and normalized query tokens from raw query."""
    raw = (query or "").strip()
    working = raw

    # 1. Extract 4-digit release year (e.g. "Spider-Man 2002", "Inception (2010)")
    target_year: Optional[int] = None
    year_match = re.search(r"\b(19\d\d|20\d\d)\b", working)
    if year_match:
        try:
            year_val = int(year_match.group(1))
            if 1900 <= year_val <= 2099:
                target_year = year_val
                # Remove year from working title
                working = re.sub(r"\b" + re.escape(year_match.group(1)) + r"\b", " ", working)
        except ValueError:
            pass

    # 2. Extract media type hint (e.g. "Avatar movie", "Batman animated series")
    target_type: Optional[MediaType] = None
    working_words = working.split()
    cleaned_words = []
    for w in working_words:
        w_lower = w.lower().strip("()")
        if w_lower in MEDIA_TYPE_HINTS and target_type is None:
            target_type = MEDIA_TYPE_HINTS[w_lower]
        else:
            cleaned_words.append(w)

    clean = " ".join(cleaned_words).strip(" -:,_()")
    # If stripping everything emptied the clean query, revert to raw working
    if not clean:
        clean = raw

    normalized = normalize_title(clean)
    normalized_no_articles = strip_articles(normalized)
    tokens = [t for t in normalized.split() if t]

    return ParsedQuery(
        raw=raw,
        clean=clean,
        normalized=normalized,
        normalized_no_articles=normalized_no_articles,
        tokens=tokens,
        target_year=target_year,
        target_type=target_type,
    )


def score_search_result(item: MediaItem, parsed_query: ParsedQuery) -> float:
    """Calculate relevance score for a MediaItem against a ParsedQuery.
    
    Higher score indicates greater relevance.
    Exact title matches score in tier 900-1100+.
    Partial/token matches score in tier 400-800.
    Fuzzy/typo matches score in tier 350-600.
    """
    if not item or not item.title:
        return 0.0

    raw_item_title = item.title.strip()
    norm_item_title = normalize_title(raw_item_title)
    norm_item_no_articles = strip_articles(norm_item_title)
    item_tokens = norm_item_title.split()

    if not norm_item_title:
        return 0.0

    score = 0.0
    norm_q = parsed_query.normalized
    norm_q_no_art = parsed_query.normalized_no_articles
    q_tokens = parsed_query.tokens

    # -------------------------------------------------------------
    # Tier 1: Exact Matches (Base: 9,200.0 - 10,000.0)
    # -------------------------------------------------------------
    if parsed_query.clean.lower() == raw_item_title.lower():
        score = 10000.0
    elif norm_q == norm_item_title:
        score = 9800.0
    elif norm_q_no_art and norm_q_no_art == norm_item_no_articles:
        score = 9500.0
    elif item.original_title and norm_q in (normalize_title(item.original_title), strip_articles(normalize_title(item.original_title))):
        score = 9300.0
    elif any(norm_q in (normalize_title(a), strip_articles(normalize_title(a))) for a in (item.aliases or [])):
        score = 9200.0

    # -------------------------------------------------------------
    # Tier 2: Prefix, Suffix, Substring, and Token Alignment Matches (Base: 3,500.0 - 5,000.0)
    # -------------------------------------------------------------
    if score == 0.0 and norm_q:
        # Prefix match (e.g. query "Breaking Bad" matching "Breaking Bad: Minisodes")
        if norm_item_title.startswith(norm_q):
            extra_words = max(0, len(item_tokens) - len(q_tokens))
            score = max(4200.0, 5000.0 - (extra_words * 40.0))
        # Prefix match without leading articles (e.g. "The It Show" vs "It Show: Special")
        elif norm_q_no_art and norm_item_no_articles.startswith(norm_q_no_art):
            extra_words = max(0, len(norm_item_no_articles.split()) - len(norm_q_no_art.split()))
            score = max(4000.0, 4800.0 - (extra_words * 40.0))
        # Query starts with item title (e.g. query "The It Show", item title "The It")
        elif norm_q.startswith(norm_item_title):
            score = 4400.0
        # Substring match with word boundaries
        elif re.search(r"\b" + re.escape(norm_q) + r"\b", norm_item_title):
            extra_words = max(0, len(item_tokens) - len(q_tokens))
            score = max(3600.0, 4200.0 - (extra_words * 30.0))

    # -------------------------------------------------------------
    # Tier 3: Token / Word Set Overlap Matches (Base: 1,000.0 - 2,800.0)
    # -------------------------------------------------------------
    if score == 0.0 and q_tokens:
        q_token_set = set(q_tokens)
        item_token_set = set(item_tokens)
        matched_tokens = q_token_set.intersection(item_token_set)

        if matched_tokens:
            overlap_ratio = len(matched_tokens) / len(q_token_set)
            # Check if all query words appear in item title
            if overlap_ratio >= 1.0:
                # Check if words appear in exact same relative order
                q_pattern = r".*?".join(re.escape(t) for t in q_tokens)
                if re.search(r"\b" + q_pattern + r"\b", norm_item_title):
                    score = 2800.0 - (max(0, len(item_tokens) - len(q_tokens)) * 30.0)
                else:
                    score = 2500.0 - (max(0, len(item_tokens) - len(q_tokens)) * 30.0)
            else:
                # Partial token overlap
                score = 1000.0 + (overlap_ratio * 1000.0) - (max(0, len(item_tokens) - len(matched_tokens)) * 15.0)

    # -------------------------------------------------------------
    # Tier 4: Fuzzy Sequence Matching (Typo Tolerance) (Base: 500.0 - 1,800.0)
    # -------------------------------------------------------------
    # Run sequence matcher if score is below exact match tier
    if norm_q and norm_item_title:
        full_sim = difflib.SequenceMatcher(None, norm_q, norm_item_title).ratio()
        if norm_q_no_art and norm_item_no_articles:
            no_art_sim = difflib.SequenceMatcher(None, norm_q_no_art, norm_item_no_articles).ratio()
            best_sim = max(full_sim, no_art_sim)
        else:
            best_sim = full_sim

        if best_sim >= 0.85:
            fuzzy_score = 1800.0 * best_sim
            score = max(score, fuzzy_score)
        elif best_sim >= 0.70 and score < 1200.0:
            fuzzy_score = 1200.0 * best_sim
            score = max(score, fuzzy_score)

    # If still 0, check token-level fuzzy match for typos (e.g. "breking" -> "breaking")
    if score < 1200.0 and q_tokens and item_tokens:
        token_matches = 0
        for qt in q_tokens:
            if any(difflib.SequenceMatcher(None, qt, it).ratio() >= 0.82 for it in item_tokens):
                token_matches += 1
        if token_matches > 0:
            token_ratio = token_matches / len(q_tokens)
            if token_ratio >= 0.8:
                score = max(score, 1400.0 * token_ratio)

    # -------------------------------------------------------------
    # Adjustments: Year, Media Type, and Quality Signals
    # -------------------------------------------------------------
    # 1. Year matching adjustment
    if parsed_query.target_year and item.year:
        item_year_val = _extract_item_year(item.year)
        if item_year_val:
            diff = abs(item_year_val - parsed_query.target_year)
            if diff == 0:
                score += 150.0
            elif diff == 1:
                score += 50.0
            else:
                score -= min(100.0, diff * 15.0)

    # 2. Media type matching adjustment
    if parsed_query.target_type:
        if item.type == parsed_query.target_type:
            score += 100.0
        else:
            score -= 100.0

    # 3. Secondary Quality & Popularity Signals (capped to prevent overtaking relevance)
    quality_bonus = 0.0

    # IMDb rating (0.0 to 10.0 -> max 40 points)
    if item.imdb_rating:
        try:
            r_val = float(item.imdb_rating)
            quality_bonus += min(40.0, max(0.0, r_val * 4.0))
        except ValueError:
            pass

    # Complete visual metadata (has poster)
    if item.poster and (item.poster.startswith("http://") or item.poster.startswith("https://")):
        quality_bonus += 15.0

    # Complete description (has synopsis)
    if item.synopsis and len(item.synopsis) > 20:
        quality_bonus += 10.0

    # Series popularity signal: series with known episode breakdown
    if item.type == MediaType.SERIES and item.episodes:
        quality_bonus += min(15.0, len(item.episodes) * 0.5)

    score += quality_bonus

    return round(score, 2)


def _extract_item_year(year_str: str) -> Optional[int]:
    """Parse start year from year or releaseInfo strings (e.g. '2008', '2008-2013')."""
    if not year_str:
        return None
    m = re.search(r"\b(19\d\d|20\d\d)\b", year_str)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def merge_and_deduplicate_results(items: List[MediaItem]) -> List[MediaItem]:
    """Deduplicate media items by IMDb ID or normalized title + year + type, merging rich metadata."""
    if not items:
        return []

    merged_by_id: Dict[str, MediaItem] = {}
    id_alias_map: Dict[str, str] = {}  # alternative_key -> primary_id

    for item in items:
        if not item or not item.title:
            continue

        item_id = item.id.strip() if item.id else ""
        norm_title = normalize_title(item.title)
        item_year = str(_extract_item_year(item.year) or "")
        title_key = f"{item.type.value}:{norm_title}:{item_year}"

        # Determine if this item maps to an already seen primary ID
        primary_id = None
        if item_id and item_id in merged_by_id:
            primary_id = item_id
        elif title_key in id_alias_map:
            primary_id = id_alias_map[title_key]

        if primary_id and primary_id in merged_by_id:
            # Merge item into existing primary record
            existing = merged_by_id[primary_id]
            _merge_media_item(existing, item)
            if item_id:
                id_alias_map[item_id] = primary_id
            id_alias_map[title_key] = primary_id
        else:
            # New primary record
            key = item_id if item_id else title_key
            merged_by_id[key] = item.model_copy(deep=True)
            if item_id:
                id_alias_map[item_id] = key
            id_alias_map[title_key] = key

    return list(merged_by_id.values())


def _merge_media_item(target: MediaItem, source: MediaItem) -> None:
    """Enrich target MediaItem with fields from source if target is missing them."""
    # Keep IMDb ID if target has non-IMDb ID and source has IMDb ID
    if source.id.startswith("tt") and not target.id.startswith("tt"):
        target.id = source.id

    # Fallback for year
    if not target.year and source.year:
        target.year = source.year

    # Fallback for poster
    if not target.poster and source.poster:
        target.poster = source.poster

    # Fallback for background
    if not target.background and source.background:
        target.background = source.background

    # Fallback / longer synopsis
    if not target.synopsis:
        target.synopsis = source.synopsis
    elif source.synopsis and len(source.synopsis) > len(target.synopsis):
        target.synopsis = source.synopsis

    # Higher or fallback IMDb rating
    if source.imdb_rating and not target.imdb_rating:
        target.imdb_rating = source.imdb_rating
    elif source.imdb_rating and target.imdb_rating:
        try:
            if float(source.imdb_rating) > float(target.imdb_rating):
                target.imdb_rating = source.imdb_rating
        except ValueError:
            pass

    # Combine genres and cast without duplicates
    if source.genres:
        existing_genres = set(target.genres)
        for g in source.genres:
            if g not in existing_genres:
                target.genres.append(g)
                existing_genres.add(g)

    if source.cast:
        existing_cast = set(target.cast)
        for c in source.cast:
            if c not in existing_cast:
                target.cast.append(c)
                existing_cast.add(c)

    if not target.director and source.director:
        target.director = source.director

    if not target.runtime and source.runtime:
        target.runtime = source.runtime

    if not target.original_title and source.original_title:
        target.original_title = source.original_title

    if source.aliases:
        existing_aliases = set(target.aliases)
        for a in source.aliases:
            if a not in existing_aliases:
                target.aliases.append(a)
                existing_aliases.add(a)

    # Combine episodes
    if source.episodes:
        existing_ep_ids = {ep.id for ep in target.episodes}
        for ep in source.episodes:
            if ep.id not in existing_ep_ids:
                target.episodes.append(ep)
                existing_ep_ids.add(ep.id)


def rank_search_results(
    items: List[MediaItem],
    query: str,
    media_type: Optional[MediaType] = None,
) -> List[MediaItem]:
    """Score and rank media items globally by relevance, typo tolerance, and quality signals."""
    if not items or not query:
        return []

    parsed_query = parse_search_query(query)
    if not parsed_query.normalized:
        return []

    # If caller explicitly provided media_type override, apply it
    if media_type and not parsed_query.target_type:
        parsed_query.target_type = media_type

    # Deduplicate before ranking
    unique_items = merge_and_deduplicate_results(items)

    scored_items: List[Tuple[float, float, str, MediaItem]] = []
    for item in unique_items:
        score = score_search_result(item, parsed_query)
        # Parse imdb rating as tie-breaker
        rating_val = 0.0
        if item.imdb_rating:
            try:
                rating_val = float(item.imdb_rating)
            except ValueError:
                pass
        scored_items.append((score, rating_val, item.title, item))

    # Sort descending by:
    # 1. Relevance score
    # 2. IMDb rating
    # 3. Alphabetical title (ascending) as stable tie-breaker
    scored_items.sort(key=lambda x: (-x[0], -x[1], x[2]))

    # Provider diversity on first page (top 5 items):
    # If one ID prefix / provider origin dominates 4+ slots on page 1,
    # but there is another provider's item within the same tier (score >= top_score * 0.75),
    # ensure diversity is promoted to page 1.
    if len(scored_items) > 3:
        page_items = scored_items[:5]
        prefixes = [item[3].id.split(":")[0] if ":" in item[3].id else ("tt" if item[3].id.startswith("tt") else "other") for item in page_items]
        if len(set(prefixes)) == 1 and len(scored_items) > 5:
            dom_prefix = prefixes[0]
            for idx in range(5, len(scored_items)):
                cand = scored_items[idx]
                cand_prefix = cand[3].id.split(":")[0] if ":" in cand[3].id else ("tt" if cand[3].id.startswith("tt") else "other")
                if cand_prefix != dom_prefix and cand[0] >= (scored_items[4][0] * 0.75):
                    promoted = scored_items.pop(idx)
                    scored_items.insert(4, promoted)
                    break

    return [x[3] for x in scored_items]
