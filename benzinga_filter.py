import re
import unicodedata
from typing import Any
from xml.etree import ElementTree

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


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1].lower()
    return tag.lower()


def _split_tokens(value: str) -> list[str]:
    return [token.strip() for token in re.split(r"[;,|]", value) if token.strip()]


def parse_benzinga_xml_news(xml_content: str) -> list[dict[str, Any]]:
    """Parse Benzinga XML payload into a normalized list of news dictionaries."""
    root = ElementTree.fromstring(xml_content)
    candidate_nodes: list[ElementTree.Element] = []
    for node in root.iter():
        tag = _local_name(node.tag)
        if tag in {"item", "news", "article"}:
            candidate_nodes.append(node)

    parsed_items: list[dict[str, Any]] = []
    for item in candidate_nodes:
        parsed: dict[str, Any] = {
            "title": "",
            "headline": "",
            "summary": "",
            "body": "",
            "topics": [],
            "tags": [],
            "tickers": [],
            "symbols": [],
        }
        for child in item.iter():
            tag = _local_name(child.tag)
            text = (child.text or "").strip()
            attrib_text = " ".join(
                value.strip()
                for value in child.attrib.values()
                if isinstance(value, str) and value.strip()
            )
            value = text or attrib_text
            if not value:
                continue

            if tag in {"title", "headline"}:
                parsed[tag] = value
            elif tag in {"summary", "teaser", "description"}:
                parsed["summary"] = value
            elif tag in {"body", "content"}:
                parsed["body"] = value
            elif tag in {"topic", "topics", "channel"}:
                parsed["topics"].extend(_split_tokens(value))
            elif tag in {"tag", "tags"}:
                parsed["tags"].extend(_split_tokens(value))
            elif tag in {"ticker", "symbol", "stock"}:
                tickers = _split_tokens(value)
                parsed["tickers"].extend(tickers)
                parsed["symbols"].extend(tickers)

        if parsed["title"] or parsed["headline"] or parsed["summary"] or parsed["body"]:
            parsed_items.append(parsed)

    return parsed_items
