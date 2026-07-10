from __future__ import annotations

from dataclasses import replace

from src.models import AppConfig
from src.normalizer import normalize_review
from src.parser import extract_review_entries
from src.validator import validate_review


APP = AppConfig("123", "Fixture", "Testing", "us", "en", True, "")


def test_valid_review_passes(sample_payload: dict) -> None:
    review = normalize_review(extract_review_entries(sample_payload)[0], APP, "https://example.test")
    assert validate_review(review).valid is True


def test_missing_and_invalid_required_fields_are_rejected(sample_payload: dict) -> None:
    review = normalize_review(extract_review_entries(sample_payload)[0], APP, "https://example.test")
    broken = replace(review, source_review_id=None, rating=7, body="", published_at=None)
    result = validate_review(broken)
    assert result.valid is False
    assert set(result.reasons) == {
        "missing_review_id",
        "rating_out_of_range",
        "empty_body",
        "invalid_timestamp",
    }
