from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from src.quality_flags import NEGATIVE_TERMS, POSITIVE_TERMS


WEAK_LABEL_SOURCE = "rating_v1"

QUALITY_FLAG_TYPES = (
    "non_english_or_unknown_language",
    "too_short_review",
    "duplicate_text_within_app",
    "rating_text_mismatch",
    "missing_author_metadata",
    "parser_fallback_used",
)

ISSUE_SIGNAL_TYPES = (
    "performance_crash",
    "login_account",
    "payment_billing",
    "ads",
    "update_version",
    "delivery_service",
    "usability_navigation",
)

NOISE_REASON_ORDER = (
    "rating_text_mismatch",
    "mixed_sentiment_keywords",
    "neutral_rating",
    "too_short_review",
    "non_english_or_unknown_language",
)

BASE_COLUMNS = (
    "review_id",
    "source_review_id",
    "app_name",
    "vertical_name",
    "storefront",
    "rating",
    "title",
    "body",
    "detected_language",
    "published_at",
    "title_char_count",
    "body_char_count",
    "body_word_count",
    "question_mark_count",
    "exclamation_mark_count",
    "published_year",
    "published_month",
    "published_day_of_week",
    "published_hour",
)

FEATURE_COLUMNS = (
    *BASE_COLUMNS,
    *(f"quality_flag_{flag_type}" for flag_type in QUALITY_FLAG_TYPES),
    "quality_flag_count",
    "has_any_quality_flag",
    *(f"issue_{signal_type}" for signal_type in ISSUE_SIGNAL_TYPES),
    "issue_signal_count",
    "weak_label",
    "weak_label_source",
    "weak_label_needs_review",
    "weak_label_noise_reasons",
)


def rating_to_weak_label(rating: int) -> str:
    if rating in (1, 2):
        return "negative"
    if rating == 3:
        return "neutral"
    if rating in (4, 5):
        return "positive"
    raise ValueError(f"Rating must be an integer from 1 to 5, received {rating!r}")


def parse_timestamp_features(value: str) -> dict[str, int | str]:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid ISO 8601 published_at value: {value!r}") from exc
    return {
        "published_year": timestamp.year,
        "published_month": timestamp.month,
        "published_day_of_week": timestamp.strftime("%A"),
        "published_hour": timestamp.hour,
    }


def _compile_terms(terms: Sequence[str]) -> re.Pattern[str]:
    expressions: list[str] = []
    for term in terms:
        normalized = " ".join(str(term).strip().split())
        if not normalized:
            continue
        escaped = re.escape(normalized).replace(r"\ ", r"\s+")
        expressions.append(rf"(?<!\w){escaped}(?!\w)")
    if not expressions:
        return re.compile(r"(?!x)x")
    return re.compile("|".join(expressions), flags=re.IGNORECASE)


def build_issue_signals(
    text: str,
    keyword_signals: Mapping[str, Sequence[str]],
) -> dict[str, int]:
    unknown = set(keyword_signals) - set(ISSUE_SIGNAL_TYPES)
    missing = set(ISSUE_SIGNAL_TYPES) - set(keyword_signals)
    if unknown or missing:
        raise ValueError(
            "Issue keyword config must exactly match v1 signals; "
            f"missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    return {
        signal_type: int(bool(_compile_terms(keyword_signals[signal_type]).search(text)))
        for signal_type in ISSUE_SIGNAL_TYPES
    }


def sentiment_keyword_presence(text: str) -> tuple[bool, bool]:
    positive = bool(_compile_terms(sorted(POSITIVE_TERMS)).search(text))
    negative = bool(_compile_terms(sorted(NEGATIVE_TERMS)).search(text))
    return positive, negative


def weak_label_noise_reasons(
    *,
    rating: int,
    text: str,
    detected_language: str | None,
    quality_flags: set[str],
) -> list[str]:
    reasons: set[str] = set()
    if "rating_text_mismatch" in quality_flags:
        reasons.add("rating_text_mismatch")
    has_positive, has_negative = sentiment_keyword_presence(text)
    if has_positive and has_negative:
        reasons.add("mixed_sentiment_keywords")
    if rating == 3:
        reasons.add("neutral_rating")
    if "too_short_review" in quality_flags:
        reasons.add("too_short_review")
    if detected_language != "en" or "non_english_or_unknown_language" in quality_flags:
        reasons.add("non_english_or_unknown_language")
    return [reason for reason in NOISE_REASON_ORDER if reason in reasons]


def build_feature_row(
    source: Mapping[str, Any],
    *,
    quality_flags: set[str],
    keyword_signals: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    rating = int(source["rating"])
    title = source.get("title") or ""
    body = source.get("body") or ""
    combined_text = f"{title}\n{body}".strip()

    unknown_flags = quality_flags - set(QUALITY_FLAG_TYPES)
    if unknown_flags:
        raise ValueError(f"Unsupported quality flags for v1: {sorted(unknown_flags)}")

    flag_features = {
        f"quality_flag_{flag_type}": int(flag_type in quality_flags)
        for flag_type in QUALITY_FLAG_TYPES
    }
    signals = build_issue_signals(combined_text, keyword_signals)
    signal_features = {
        f"issue_{signal_type}": signals[signal_type]
        for signal_type in ISSUE_SIGNAL_TYPES
    }
    noise_reasons = weak_label_noise_reasons(
        rating=rating,
        text=combined_text,
        detected_language=source.get("detected_language"),
        quality_flags=quality_flags,
    )

    feature_row: dict[str, Any] = {
        "review_id": source["review_id"],
        "source_review_id": source["source_review_id"],
        "app_name": source["app_name"],
        "vertical_name": source["vertical_name"],
        "storefront": source["storefront"],
        "rating": rating,
        "title": title,
        "body": body,
        "detected_language": source.get("detected_language") or "unknown",
        "published_at": source["published_at"],
        "title_char_count": len(title),
        "body_char_count": len(body),
        "body_word_count": len(re.findall(r"\b[\w']+\b", body, flags=re.UNICODE)),
        "question_mark_count": combined_text.count("?"),
        "exclamation_mark_count": combined_text.count("!"),
        **parse_timestamp_features(source["published_at"]),
        **flag_features,
        "quality_flag_count": len(quality_flags),
        "has_any_quality_flag": int(bool(quality_flags)),
        **signal_features,
        "issue_signal_count": sum(signals.values()),
        "weak_label": rating_to_weak_label(rating),
        "weak_label_source": WEAK_LABEL_SOURCE,
        "weak_label_needs_review": int(bool(noise_reasons)),
        "weak_label_noise_reasons": "|".join(noise_reasons),
    }
    return {column: feature_row[column] for column in FEATURE_COLUMNS}

