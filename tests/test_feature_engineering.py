from __future__ import annotations

import csv
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.build_ds_dataset import load_issue_keywords, main as build_dataset_main
from src.config_loader import load_config
from src.database import Database
from src.feature_engineering import (
    FEATURE_COLUMNS,
    build_feature_row,
    build_issue_signals,
    parse_timestamp_features,
    rating_to_weak_label,
)
from src.models import QualityFlag
from src.normalizer import normalize_review
from src.parser import extract_review_entries


ROOT = Path(__file__).resolve().parents[1]
KEYWORD_CONFIG = ROOT / "config/issue_keywords_v1.yaml"


@pytest.mark.parametrize(
    ("rating", "expected"),
    [
        (1, "negative"),
        (2, "negative"),
        (3, "neutral"),
        (4, "positive"),
        (5, "positive"),
    ],
)
def test_rating_to_weak_label(rating: int, expected: str) -> None:
    assert rating_to_weak_label(rating) == expected


def test_invalid_rating_is_rejected() -> None:
    with pytest.raises(ValueError, match="1 to 5"):
        rating_to_weak_label(0)


def test_issue_keyword_matching_respects_case_boundaries_and_phrases() -> None:
    _, keywords = load_issue_keywords(KEYWORD_CONFIG)
    signals = build_issue_signals(
        "LOGIN is broken after the latest version; the app crashes. "
        "The menu is difficult   to use, but adaptation is fine.",
        keywords,
    )
    assert signals["login_account"] == 1
    assert signals["update_version"] == 1
    assert signals["performance_crash"] == 1
    assert signals["usability_navigation"] == 1
    assert signals["ads"] == 0  # "ad" must not match inside "adaptation".


def test_feature_row_contains_flags_time_features_and_ordered_noise_reasons() -> None:
    _, keywords = load_issue_keywords(KEYWORD_CONFIG)
    source = {
        "review_id": 7,
        "source_review_id": "source-7",
        "app_name": "Example",
        "vertical_name": "Testing",
        "storefront": "us",
        "rating": 3,
        "title": "Great but terrible!",
        "body": "bad?",
        "detected_language": "unknown",
        "published_at": "2026-07-14T02:43:05Z",
    }
    row = build_feature_row(
        source,
        quality_flags={
            "rating_text_mismatch",
            "too_short_review",
            "non_english_or_unknown_language",
        },
        keyword_signals=keywords,
    )
    assert tuple(row) == FEATURE_COLUMNS
    assert row["published_year"] == 2026
    assert row["published_month"] == 7
    assert row["published_day_of_week"] == "Tuesday"
    assert row["published_hour"] == 2
    assert row["quality_flag_rating_text_mismatch"] == 1
    assert row["quality_flag_count"] == 3
    assert row["weak_label"] == "neutral"
    assert row["weak_label_needs_review"] == 1
    assert row["weak_label_noise_reasons"] == (
        "rating_text_mismatch|mixed_sentiment_keywords|neutral_rating|"
        "too_short_review|non_english_or_unknown_language"
    )


def test_timestamp_requires_iso_8601() -> None:
    with pytest.raises(ValueError, match="Invalid ISO 8601"):
        parse_timestamp_features("not-a-timestamp")


def _build_test_database(db_path: Path, sample_payload: dict) -> None:
    config = load_config(ROOT / "config/apps.yaml")
    app = config.apps[0]
    parsed = extract_review_entries(sample_payload)[0]
    base_review = normalize_review(parsed, app, "https://example.test")
    reviews = [
        replace(
            base_review,
            source_review_id="feature-1",
            rating=1,
            title="Crashes",
            body="The app crashes whenever I log in",
            body_char_count=33,
            detected_language="en",
        ),
        replace(
            base_review,
            source_review_id="feature-2",
            rating=5,
            title="Great",
            body="Great!",
            body_char_count=6,
            detected_language="en",
        ),
    ]
    with Database(db_path) as db:
        db.initialize(ROOT / "database/phase_i_database_schema.sql")
        db.seed_config(config)
        app_id, storefront_id = db.get_app_context(app)
        run_id = db.create_ingestion_run({"test": True})
        raw_id = db.insert_raw_feed_page(
            run_id=run_id,
            app_storefront_id=storefront_id,
            source_url="https://example.test",
            page_number=1,
            http_status=200,
            fetched_at="2026-01-01T00:00:00Z",
            response_hash="hash",
            response_body="{}",
            raw_file_path="data/raw/test.json",
        )
        with db.transaction():
            for index, review in enumerate(reviews):
                review_id, _ = db.upsert_review(
                    review=review,
                    app_id=app_id,
                    app_storefront_id=storefront_id,
                    reviewer_id=None,
                    run_id=run_id,
                    raw_page_id=raw_id,
                )
                if index == 1:
                    db.insert_quality_flags(
                        review_id,
                        [QualityFlag("too_short_review", "info", "test")],
                    )


def _run_cli(db_path: Path, output_path: Path, summary_path: Path) -> None:
    original_argv = sys.argv
    try:
        sys.argv = [
            "build_ds_dataset.py",
            "--db-path",
            str(db_path),
            "--output",
            str(output_path),
            "--summary-output",
            str(summary_path),
            "--keyword-config",
            str(KEYWORD_CONFIG),
        ]
        build_dataset_main()
    finally:
        sys.argv = original_argv


def test_dataset_cli_is_deterministic_unique_and_privacy_safe(
    tmp_path: Path,
    sample_payload: dict,
) -> None:
    db_path = tmp_path / "features.db"
    first_output = tmp_path / "first.csv"
    second_output = tmp_path / "second.csv"
    first_summary = tmp_path / "first.json"
    second_summary = tmp_path / "second.json"
    _build_test_database(db_path, sample_payload)

    _run_cli(db_path, first_output, first_summary)
    _run_cli(db_path, second_output, second_summary)

    assert first_output.read_bytes() == second_output.read_bytes()
    with first_output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert len({row["review_id"] for row in rows}) == 2
    assert list(rows[0]) == list(FEATURE_COLUMNS)
    assert rows[0]["weak_label"] == "negative"
    assert rows[0]["issue_performance_crash"] == "1"
    assert rows[0]["issue_login_account"] == "1"
    assert rows[1]["weak_label"] == "positive"
    assert rows[1]["weak_label_noise_reasons"] == "too_short_review"

    forbidden = {"reviewer_id", "author_label", "author_uri", "author_fingerprint"}
    assert forbidden.isdisjoint(rows[0])
    summary = json.loads(first_summary.read_text(encoding="utf-8"))
    assert summary["rows"] == 2
    assert summary["unique_review_ids"] == 2
    assert summary["apps"] == 1
    assert summary["verticals"] == 1
    assert summary["weak_label_counts"] == {"negative": 1, "positive": 1}
    assert summary["weak_label_needs_review_rows"] == 1
    assert summary["weak_label_needs_review_share"] == 0.5
