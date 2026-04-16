import re
import unicodedata
from typing import Any

DEFAULT_KEYWORD_PATTERNS: dict[str, tuple[str, ...]] = {
    "gold": (r"\bgold\b", r"\bxau/?usd\b", r"\bxau\b", r"\bbullion\b"),
    "fed": (r"\bfed\b", r"federal reserve"),
    "fomc": (r"\bfomc\b",),
    "inflation": (r"\binflation\b", r"\bcpi\b", r"\bpce\b"),
    "dxy": (r"\bdxy\b", r"dollar index"),
    "geopolit": (r"geopolit", r"\bsanction", r"\bmiddle east\b", r"\bukraine\b"),
    "war": (r"\bwar\b", r"\bconflict\b", r"\bmilitary\b", r"\bmissile\b"),
}

# Keep this aligned with the strategy's business requirements.
DEFAULT_RELEVANCE_KEYWORDS: tuple[str, ...] = tuple(DEFAULT_KEYWORD_PATTERNS.keys())


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def _flatten_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(_flatten_value(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_value(v) for v in value)
    return ""


def _news_text_blob(news_item: dict[str, Any]) -> str:
    fields_to_scan = (
        "title",
        "headline",
        "teaser",
        "summary",
        "body",
        "content",
        "topics",
        "channels",
        "tags",
        "stocks",
        "tickers",
        "symbols",
    )
    raw_text = " ".join(_flatten_value(news_item.get(field)) for field in fields_to_scan)
    return _normalize_text(raw_text)


def identify_matching_keywords(
    news_item: dict[str, Any],
    keyword_patterns: dict[str, tuple[str, ...]] | None = None,
) -> set[str]:
    patterns = keyword_patterns or DEFAULT_KEYWORD_PATTERNS
    text_blob = _news_text_blob(news_item)
    matches: set[str] = set()

    for keyword, compiled_patterns in patterns.items():
        if any(re.search(pattern, text_blob) for pattern in compiled_patterns):
            matches.add(keyword)

    return matches


def is_relevant_news(news_item: dict[str, Any], min_keyword_hits: int = 1) -> bool:
    return len(identify_matching_keywords(news_item)) >= min_keyword_hits


def filter_relevant_news(
    news_payload: list[dict[str, Any]] | dict[str, Any],
    min_keyword_hits: int = 1,
) -> list[dict[str, Any]]:
    if isinstance(news_payload, list):
        news_items = news_payload
    elif isinstance(news_payload, dict):
        news_items = news_payload.get("data") or news_payload.get("news") or []
    else:
        news_items = []

    filtered_news: list[dict[str, Any]] = []
    for item in news_items:
        matched_keywords = identify_matching_keywords(item)
        if len(matched_keywords) >= min_keyword_hits:
            filtered_news.append(
                {
                    **item,
                    "matched_keywords": sorted(matched_keywords),
                }
            )

    return filtered_news
