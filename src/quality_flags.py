from __future__ import annotations

from src.models import NormalizedReview, QualityFlag


POSITIVE_TERMS = {"amazing", "awesome", "excellent", "fantastic", "great", "love", "perfect", "wonderful"}
NEGATIVE_TERMS = {"awful", "broken", "garbage", "hate", "horrible", "scam", "terrible", "trash", "worst"}


def build_quality_flags(review: NormalizedReview, *, duplicate_text: bool = False) -> list[QualityFlag]:
    flags: list[QualityFlag] = []
    if review.detected_language != "en":
        flags.append(QualityFlag("non_english_or_unknown_language", "info", review.detected_language))
    if review.body_char_count < 12:
        flags.append(QualityFlag("too_short_review", "info", f"body_char_count={review.body_char_count}"))
    if duplicate_text:
        flags.append(QualityFlag("duplicate_text_within_app", "warning", "Same normalized body exists for another source review id"))
    if not review.author_label and not review.author_uri:
        flags.append(QualityFlag("missing_author_metadata", "info", "Both author label and URI are absent"))
    if review.parser_fallback_used:
        flags.append(QualityFlag("parser_fallback_used", "info", "Feed entry was supplied as an object instead of a list"))

    words = {word.strip(".,!?;:'\"()[]{}") for word in review.body.lower().split()}
    has_positive = bool(words & POSITIVE_TERMS)
    has_negative = bool(words & NEGATIVE_TERMS)
    if review.rating is not None:
        if review.rating >= 4 and has_negative and not has_positive:
            flags.append(QualityFlag("rating_text_mismatch", "warning", "High rating with strongly negative keyword"))
        elif review.rating <= 2 and has_positive and not has_negative:
            flags.append(QualityFlag("rating_text_mismatch", "warning", "Low rating with strongly positive keyword"))
    return flags
