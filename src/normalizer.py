from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.models import AppConfig, NormalizedReview, ParsedReview
from src.utils import canonical_json, clean_text, sha256_text, utc_now_iso


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def normalize_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def detect_language(text: str) -> str:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return "unknown"
    ascii_letters = sum(char.isascii() for char in letters)
    ascii_ratio = ascii_letters / len(letters)
    lower = f" {text.lower()} "
    english_markers = (" the ", " and ", " is ", " it ", " app ", " this ", " great ", " love ", " bad ", " good ")
    if ascii_ratio >= 0.9 and (len(letters) >= 12 or any(marker in lower for marker in english_markers)):
        return "en"
    return "unknown"


def normalize_review(parsed: ParsedReview, app: AppConfig, source_endpoint: str) -> NormalizedReview:
    body = clean_text(parsed.body_raw) or ""
    title = clean_text(parsed.title_raw, empty_as_none=True)
    author_label = clean_text(parsed.author_label_raw, empty_as_none=True)
    author_uri = clean_text(parsed.author_uri_raw, empty_as_none=True)
    raw_json = canonical_json(parsed.raw_record)
    return NormalizedReview(
        source_platform="apple_app_store",
        source_endpoint=source_endpoint,
        storefront=app.storefront,
        source_app_id=app.app_id,
        app_name=app.app_name,
        vertical=app.vertical,
        source_review_id=clean_text(parsed.source_review_id, empty_as_none=True),
        review_url=clean_text(parsed.review_url_raw, empty_as_none=True),
        author_label=author_label,
        author_uri=author_uri,
        rating=_safe_int(parsed.rating_raw),
        title=title,
        body=body,
        app_version=clean_text(parsed.app_version_raw, empty_as_none=True),
        published_at=normalize_timestamp(parsed.published_at_raw),
        vote_count=_safe_int(parsed.vote_count_raw),
        vote_sum=_safe_int(parsed.vote_sum_raw),
        raw_payload_hash=sha256_text(raw_json),
        ingested_at=utc_now_iso(),
        detected_language=detect_language(f"{title or ''} {body}".strip()),
        body_char_count=len(body),
        body_token_estimate=len(body.split()),
        parser_fallback_used=parsed.parser_fallback_used,
        raw_record=parsed.raw_record,
    )
