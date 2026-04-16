from __future__ import annotations

import os
import re
import unicodedata
from html import unescape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import requests
from dotenv import dotenv_values

DEFAULT_NEWS_KEYWORDS = (
    "gold",
    "fed",
    "fomc",
    "inflation",
    "dxy",
    "geopolit",
    "war",
)
DEFAULT_ACCEPT = "application/xml"
DEFAULT_DISPLAY_OUTPUT = "full"
DEFAULT_PAGE_SIZE = 25
DEFAULT_TIMEOUT = 20


def _parse_csv(value: str | None, default: tuple[str, ...]) -> list[str]:
    if not value:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _resolve_env_path(explicit_path: str | None = None) -> Path | None:
    candidates: list[Path] = []

    if explicit_path:
        candidates.append(Path(explicit_path).expanduser())

    env_override = os.getenv("MARIA_HELENA_ENV_PATH", "").strip()
    if env_override:
        candidates.append(Path(env_override).expanduser())

    candidates.extend(
        [
            Path("/root/maria-helena/.env"),
            Path(__file__).resolve().with_name(".env"),
        ]
    )

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


def load_runtime_config(explicit_env_path: str | None = None) -> dict[str, Any]:
    env_path = _resolve_env_path(explicit_env_path)
    dotenv_data = dotenv_values(str(env_path)) if env_path else {}

    api_key = (os.getenv("BENZINGA_API_KEY") or dotenv_data.get("BENZINGA_API_KEY") or "").strip()
    keywords = _parse_csv(
        os.getenv("BENZINGA_NEWS_KEYWORDS") or dotenv_data.get("BENZINGA_NEWS_KEYWORDS"),
        DEFAULT_NEWS_KEYWORDS,
    )

    return {
        "env_path": str(env_path) if env_path else None,
        "api_key": api_key,
        "keywords": keywords,
        "topics": _parse_csv(
            os.getenv("BENZINGA_TOPICS") or dotenv_data.get("BENZINGA_TOPICS"),
            tuple(keywords),
        ),
        "topic_group_by": (
            os.getenv("BENZINGA_TOPIC_GROUP_BY")
            or dotenv_data.get("BENZINGA_TOPIC_GROUP_BY")
            or "or"
        ).strip(),
        "accept": (
            os.getenv("BENZINGA_ACCEPT")
            or dotenv_data.get("BENZINGA_ACCEPT")
            or DEFAULT_ACCEPT
        ).strip(),
        "display_output": (
            os.getenv("BENZINGA_DISPLAY_OUTPUT")
            or dotenv_data.get("BENZINGA_DISPLAY_OUTPUT")
            or DEFAULT_DISPLAY_OUTPUT
        ).strip(),
        "page_size": int(
            os.getenv("BENZINGA_PAGE_SIZE")
            or dotenv_data.get("BENZINGA_PAGE_SIZE")
            or DEFAULT_PAGE_SIZE
        ),
        "timeout": int(
            os.getenv("BENZINGA_TIMEOUT")
            or dotenv_data.get("BENZINGA_TIMEOUT")
            or DEFAULT_TIMEOUT
        ),
        "preview_limit": int(
            os.getenv("BENZINGA_PREVIEW_LIMIT")
            or dotenv_data.get("BENZINGA_PREVIEW_LIMIT")
            or 5
        ),
        "minimum_keyword_matches": int(
            os.getenv("BENZINGA_MIN_KEYWORD_MATCHES")
            or dotenv_data.get("BENZINGA_MIN_KEYWORD_MATCHES")
            or 1
        ),
    }


def _strip_html(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text or "")
    return unescape(no_tags)


def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^a-z0-9]+", " ", without_accents.lower())
    return " ".join(cleaned.split())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _direct_child_text(element: ET.Element, child_name: str) -> str:
    for child in list(element):
        if _local_name(child.tag) == child_name:
            return " ".join("".join(child.itertext()).split())
    return ""


def _extract_name_list_from_json(values: list[dict[str, Any]] | None) -> list[str]:
    if not values:
        return []
    names = []
    for value in values:
        name = str(value.get("name", "")).strip()
        if name:
            names.append(name)
    return names


def _extract_stock_list_from_json(values: list[dict[str, Any]] | None) -> list[str]:
    if not values:
        return []
    stocks = []
    for value in values:
        name = str(value.get("name", "")).strip()
        if name:
            stocks.append(name)
    return stocks


def _extract_nested_names(element: ET.Element, container_name: str) -> list[str]:
    names: list[str] = []

    for child in list(element):
        if _local_name(child.tag) != container_name:
            continue

        direct_name = _direct_child_text(child, "name")
        if direct_name:
            names.append(direct_name)

        for nested in list(child):
            if _local_name(nested.tag) == "name":
                value = " ".join("".join(nested.itertext()).split())
                if value:
                    names.append(value)
                continue

            nested_name = _direct_child_text(nested, "name")
            if nested_name:
                names.append(nested_name)

    return list(dict.fromkeys(names))


def normalize_news_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "author": str(item.get("author", "")).strip(),
        "created": str(item.get("created", "")).strip(),
        "updated": str(item.get("updated", "")).strip(),
        "title": str(item.get("title", "")).strip(),
        "teaser": str(item.get("teaser", "")).strip(),
        "body": str(item.get("body", "")).strip(),
        "url": str(item.get("url", "")).strip(),
        "channels": _extract_name_list_from_json(item.get("channels")),
        "tags": _extract_name_list_from_json(item.get("tags")),
        "stocks": _extract_stock_list_from_json(item.get("stocks")),
    }


def parse_benzinga_json(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and payload.get("ok") is False:
        errors = payload.get("errors", [])
        raise RuntimeError(f"Benzinga retornou erro: {errors}")

    if not isinstance(payload, list):
        raise ValueError("Resposta JSON inesperada da Benzinga.")

    return [normalize_news_item(item) for item in payload if isinstance(item, dict)]


def _candidate_xml_items(root: ET.Element) -> list[ET.Element]:
    candidates: list[ET.Element] = []

    for element in root.iter():
        child_names = {_local_name(child.tag) for child in list(element)}
        if "title" in child_names and (
            "body" in child_names
            or "teaser" in child_names
            or "url" in child_names
            or "created" in child_names
        ):
            candidates.append(element)

    candidate_ids = {id(element) for element in candidates}
    deepest_candidates: list[ET.Element] = []

    for element in candidates:
        has_nested_candidate = any(
            desc is not element and id(desc) in candidate_ids for desc in element.iter()
        )
        if not has_nested_candidate:
            deepest_candidates.append(element)

    return deepest_candidates


def parse_benzinga_xml(payload: str) -> list[dict[str, Any]]:
    root = ET.fromstring(payload)
    news_items: list[dict[str, Any]] = []

    for element in _candidate_xml_items(root):
        news_items.append(
            {
                "id": _direct_child_text(element, "id"),
                "author": _direct_child_text(element, "author"),
                "created": _direct_child_text(element, "created"),
                "updated": _direct_child_text(element, "updated"),
                "title": _direct_child_text(element, "title"),
                "teaser": _direct_child_text(element, "teaser"),
                "body": _direct_child_text(element, "body"),
                "url": _direct_child_text(element, "url"),
                "channels": _extract_nested_names(element, "channels"),
                "tags": _extract_nested_names(element, "tags"),
                "stocks": _extract_nested_names(element, "stocks"),
            }
        )

    return news_items


def parse_benzinga_response(response: requests.Response) -> list[dict[str, Any]]:
    content_type = response.headers.get("content-type", "").lower()
    body = response.text.strip()

    if "xml" in content_type or body.startswith("<"):
        return parse_benzinga_xml(body)

    return parse_benzinga_json(response.json())


def build_searchable_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("title", ""),
        item.get("teaser", ""),
        _strip_html(item.get("body", "")),
        " ".join(item.get("channels", [])),
        " ".join(item.get("tags", [])),
        " ".join(item.get("stocks", [])),
    ]
    return normalize_text(" ".join(part for part in parts if part))


def _keyword_matches_tokens(keyword: str, tokens: list[str], normalized_text: str) -> bool:
    keyword = normalize_text(keyword)
    if not keyword:
        return False

    if " " in keyword:
        return f" {keyword} " in f" {normalized_text} "

    if len(keyword) >= 5:
        return any(token == keyword or token.startswith(keyword) for token in tokens)

    return keyword in tokens


def find_matching_keywords(item: dict[str, Any], keywords: list[str]) -> list[str]:
    normalized_text = build_searchable_text(item)
    tokens = normalized_text.split()

    matches = [
        keyword
        for keyword in keywords
        if _keyword_matches_tokens(keyword, tokens, normalized_text)
    ]

    return list(dict.fromkeys(matches))


def filter_relevant_news(
    news_items: list[dict[str, Any]],
    keywords: list[str],
    minimum_keyword_matches: int = 1,
) -> list[dict[str, Any]]:
    filtered_items: list[dict[str, Any]] = []

    for item in news_items:
        matched_keywords = find_matching_keywords(item, keywords)
        if len(matched_keywords) < minimum_keyword_matches:
            continue

        enriched = dict(item)
        enriched["matched_keywords"] = matched_keywords
        enriched["relevance_score"] = len(matched_keywords)
        filtered_items.append(enriched)

    return filtered_items


def fetch_news_items(config: dict[str, Any]) -> list[dict[str, Any]]:
    if not config.get("api_key"):
        raise RuntimeError("BENZINGA_API_KEY não configurada.")

    response = requests.get(
        "https://api.benzinga.com/api/v2/news",
        headers={"accept": config["accept"]},
        params={
            "token": config["api_key"],
            "topics": ",".join(config["topics"]),
            "topic_group_by": config["topic_group_by"],
            "pageSize": config["page_size"],
            "displayOutput": config["display_output"],
        },
        timeout=config["timeout"],
    )
    response.raise_for_status()
    return parse_benzinga_response(response)


def fetch_relevant_news(config: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    runtime_config = config or load_runtime_config()
    all_news = fetch_news_items(runtime_config)
    filtered_news = filter_relevant_news(
        all_news,
        runtime_config["keywords"],
        runtime_config["minimum_keyword_matches"],
    )
    return all_news, filtered_news, runtime_config
