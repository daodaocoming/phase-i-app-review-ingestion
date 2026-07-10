from __future__ import annotations

from typing import Any

from src.models import ParsedReview


def _label(value: Any) -> Any:
    if isinstance(value, dict) and "label" in value:
        return value.get("label")
    return value


def _attribute(entry: dict[str, Any], field: str, attribute: str) -> Any:
    value = entry.get(field)
    if isinstance(value, dict):
        attributes = value.get("attributes")
        if isinstance(attributes, dict):
            return attributes.get(attribute)
    return None


def extract_review_entries(payload: dict[str, Any]) -> list[ParsedReview]:
    feed = payload.get("feed")
    if not isinstance(feed, dict):
        return []
    entries = feed.get("entry", [])
    if isinstance(entries, dict):
        entries = [entries]
        fallback = True
    else:
        fallback = False
    if not isinstance(entries, list):
        return []

    parsed: list[ParsedReview] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # Feed-level metadata does not contain review-specific fields.
        if not any(key in entry for key in ("im:rating", "content", "author", "im:version")):
            continue
        author = entry.get("author") if isinstance(entry.get("author"), dict) else {}
        parsed.append(
            ParsedReview(
                source_review_id=_label(entry.get("id")),
                rating_raw=_label(entry.get("im:rating")),
                title_raw=_label(entry.get("title")),
                body_raw=_label(entry.get("content")),
                author_label_raw=_label(author.get("name")),
                author_uri_raw=_label(author.get("uri")),
                published_at_raw=_label(entry.get("updated")),
                app_version_raw=_label(entry.get("im:version")),
                review_url_raw=_attribute(entry, "link", "href"),
                vote_count_raw=_label(entry.get("im:voteCount")),
                vote_sum_raw=_label(entry.get("im:voteSum")),
                raw_record=entry,
                parser_fallback_used=fallback,
            )
        )
    return parsed


def has_next_page(payload: dict[str, Any]) -> bool:
    feed = payload.get("feed")
    if not isinstance(feed, dict):
        return False
    links = feed.get("link", [])
    if isinstance(links, dict):
        links = [links]
    if not isinstance(links, list):
        return False
    for link in links:
        attributes = link.get("attributes", {}) if isinstance(link, dict) else {}
        if isinstance(attributes, dict) and attributes.get("rel") == "next":
            return bool(attributes.get("href"))
    return False
