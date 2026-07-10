from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from src.config_loader import load_config
from src.database import Database
from src.normalizer import normalize_review
from src.parser import extract_review_entries


ROOT = Path(__file__).resolve().parents[1]


def test_idempotent_upsert_updates_timestamps_and_raw_linkage(tmp_path: Path, sample_payload: dict) -> None:
    config = load_config(ROOT / "config/apps.yaml")
    app = config.apps[0]
    db_path = tmp_path / "test.db"
    with Database(db_path) as db:
        db.initialize(ROOT / "database/phase_i_database_schema.sql")
        db.seed_config(config)
        app_id, storefront_id = db.get_app_context(app)
        normalized = normalize_review(
            extract_review_entries(sample_payload)[0], app, "https://example.test/page=1"
        )

        run1 = db.create_ingestion_run({"test": 1})
        raw1 = db.insert_raw_feed_page(
            run_id=run1,
            app_storefront_id=storefront_id,
            source_url="https://example.test/page=1",
            page_number=1,
            http_status=200,
            fetched_at="2026-01-01T00:00:00Z",
            response_hash="hash-1",
            response_body="{}",
            raw_file_path="data/raw/one.json",
        )
        with db.transaction():
            reviewer = db.upsert_reviewer(normalized)
            review_id, inserted = db.upsert_review(
                review=normalized,
                app_id=app_id,
                app_storefront_id=storefront_id,
                reviewer_id=reviewer,
                run_id=run1,
                raw_page_id=raw1,
            )
        assert inserted is True
        first = db.connection.execute("SELECT * FROM reviews WHERE review_id=?", (review_id,)).fetchone()

        run2 = db.create_ingestion_run({"test": 2})
        raw2 = db.insert_raw_feed_page(
            run_id=run2,
            app_storefront_id=storefront_id,
            source_url="https://example.test/page=1",
            page_number=1,
            http_status=200,
            fetched_at="2026-01-02T00:00:00Z",
            response_hash="hash-2",
            response_body="{}",
            raw_file_path="data/raw/two.json",
        )
        with db.transaction():
            same_review_id, inserted_again = db.upsert_review(
                review=normalized,
                app_id=app_id,
                app_storefront_id=storefront_id,
                reviewer_id=reviewer,
                run_id=run2,
                raw_page_id=raw2,
            )
        second = db.connection.execute("SELECT * FROM reviews WHERE review_id=?", (review_id,)).fetchone()

        assert inserted_again is False
        assert same_review_id == review_id
        assert db.scalar("SELECT COUNT(*) FROM reviews") == 1
        assert second["first_raw_feed_page_id"] == raw1
        assert second["last_raw_feed_page_id"] == raw2
        assert second["first_seen_run_id"] == run1
        assert second["last_seen_run_id"] == run2
        assert second["last_seen_at"] > first["last_seen_at"]
        assert second["updated_at"] > first["updated_at"]


def test_rejected_record_links_to_run_and_raw_page(tmp_path: Path, sample_payload: dict) -> None:
    config = load_config(ROOT / "config/apps.yaml")
    app = config.apps[0]
    with Database(tmp_path / "test.db") as db:
        db.initialize(ROOT / "database/phase_i_database_schema.sql")
        db.seed_config(config)
        _, storefront_id = db.get_app_context(app)
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
        review = normalize_review(extract_review_entries(sample_payload)[0], app, "https://example.test")
        with db.transaction():
            db.insert_rejected_review(
                run_id=run_id,
                raw_page_id=raw_id,
                app_storefront_id=storefront_id,
                review=review,
                reasons=["forced_test_rejection"],
            )
        row = db.connection.execute("SELECT * FROM rejected_review_records").fetchone()
        assert row["ingestion_run_id"] == run_id
        assert row["raw_feed_page_id"] == raw_id
        assert row["rejection_reason"] == "forced_test_rejection"


def test_review_cannot_use_storefront_from_another_app(tmp_path: Path, sample_payload: dict) -> None:
    config = load_config(ROOT / "config/apps.yaml")
    app = config.apps[0]
    other_app = config.apps[1]
    with Database(tmp_path / "test.db") as db:
        db.initialize(ROOT / "database/phase_i_database_schema.sql")
        db.seed_config(config)
        app_id, _ = db.get_app_context(app)
        _, other_storefront_id = db.get_app_context(other_app)
        run_id = db.create_ingestion_run({"test": True})
        raw_id = db.insert_raw_feed_page(
            run_id=run_id,
            app_storefront_id=other_storefront_id,
            source_url="https://example.test",
            page_number=1,
            http_status=200,
            fetched_at="2026-01-01T00:00:00Z",
            response_hash="hash",
            response_body="{}",
            raw_file_path="data/raw/test.json",
        )
        review = normalize_review(extract_review_entries(sample_payload)[0], app, "https://example.test")
        with pytest.raises(sqlite3.IntegrityError):
            with db.transaction():
                db.upsert_review(
                    review=review,
                    app_id=app_id,
                    app_storefront_id=other_storefront_id,
                    reviewer_id=None,
                    run_id=run_id,
                    raw_page_id=raw_id,
                )
