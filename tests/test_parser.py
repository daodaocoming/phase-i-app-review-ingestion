from __future__ import annotations

from src.models import AppConfig
from src.normalizer import normalize_review
from src.parser import extract_review_entries, has_next_page


APP = AppConfig(
    app_id="123",
    app_name="Fixture App",
    vertical="Testing",
    storefront="us",
    expected_language="en",
    enabled=True,
    notes="fixture",
)


def test_extracts_reviews_without_treating_metadata_as_review(sample_payload: dict) -> None:
    reviews = extract_review_entries(sample_payload)
    assert len(reviews) == 2
    assert [review.source_review_id for review in reviews] == ["review-1001", "review-1002"]
    assert has_next_page(sample_payload) is True


def test_rating_and_timestamp_are_normalized(sample_payload: dict) -> None:
    parsed = extract_review_entries(sample_payload)[0]
    normalized = normalize_review(parsed, APP, "https://example.test/feed")
    assert normalized.rating == 5
    assert normalized.published_at == "2026-06-25T17:00:00Z"
    assert normalized.body == "I love this app. It works perfectly!"
    assert normalized.detected_language == "en"


def test_single_entry_object_uses_documented_fallback(sample_payload: dict) -> None:
    sample_payload["feed"]["entry"] = sample_payload["feed"]["entry"][0]
    reviews = extract_review_entries(sample_payload)
    assert len(reviews) == 1
    assert reviews[0].parser_fallback_used is True
