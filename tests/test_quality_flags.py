from __future__ import annotations

from dataclasses import replace

from src.models import AppConfig
from src.normalizer import normalize_review
from src.parser import extract_review_entries
from src.quality_flags import build_quality_flags


APP = AppConfig("123", "Fixture", "Testing", "us", "en", True, "")


def flag_names(review, duplicate: bool = False) -> set[str]:
    return {flag.flag_type for flag in build_quality_flags(review, duplicate_text=duplicate)}


def test_soft_flags_are_transparent_and_composable(sample_payload: dict) -> None:
    review = normalize_review(extract_review_entries(sample_payload)[0], APP, "https://example.test")
    altered = replace(
        review,
        body="terrible",
        body_char_count=8,
        detected_language="unknown",
        author_label=None,
        author_uri=None,
        rating=5,
        parser_fallback_used=True,
    )
    assert flag_names(altered, duplicate=True) == {
        "non_english_or_unknown_language",
        "too_short_review",
        "duplicate_text_within_app",
        "rating_text_mismatch",
        "missing_author_metadata",
        "parser_fallback_used",
    }


def test_positive_text_with_low_rating_is_mismatch(sample_payload: dict) -> None:
    review = normalize_review(extract_review_entries(sample_payload)[0], APP, "https://example.test")
    altered = replace(review, rating=1, body="This is an excellent and amazing app")
    assert "rating_text_mismatch" in flag_names(altered)
