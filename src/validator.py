from __future__ import annotations

from src.models import NormalizedReview, ValidationResult


def validate_review(review: NormalizedReview) -> ValidationResult:
    reasons: list[str] = []
    if not review.source_review_id:
        reasons.append("missing_review_id")
    if review.rating is None:
        reasons.append("missing_or_invalid_rating")
    elif not 1 <= review.rating <= 5:
        reasons.append("rating_out_of_range")
    if not review.body.strip():
        reasons.append("empty_body")
    if review.published_at is None:
        reasons.append("invalid_timestamp")
    if not isinstance(review.raw_record, dict):
        reasons.append("broken_record_structure")
    return ValidationResult(valid=not reasons, reasons=reasons)
