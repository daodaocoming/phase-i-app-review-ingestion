from __future__ import annotations

import csv
import sys
from pathlib import Path

from src.config_loader import load_config
from src.database import Database
from src.normalizer import normalize_review
from src.parser import extract_review_entries


ROOT = Path(__file__).resolve().parents[1]


def test_default_training_export_excludes_reviewer_metadata(tmp_path: Path, sample_payload: dict) -> None:
    config = load_config(ROOT / "config/apps.yaml")
    app = config.apps[0]
    db_path = tmp_path / "export.db"
    output_path = tmp_path / "training.csv"
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
        review = normalize_review(extract_review_entries(sample_payload)[0], app, "https://example.test")
        with db.transaction():
            reviewer_id = db.upsert_reviewer(review)
            db.upsert_review(
                review=review,
                app_id=app_id,
                app_storefront_id=storefront_id,
                reviewer_id=reviewer_id,
                run_id=run_id,
                raw_page_id=raw_id,
            )

    sys.path.insert(0, str(ROOT))
    from scripts.export_training_dataset import main

    original_argv = sys.argv
    try:
        sys.argv = [
            "export_training_dataset.py",
            "--db-path",
            str(db_path),
            "--output",
            str(output_path),
        ]
        main()
    finally:
        sys.argv = original_argv

    with output_path.open(newline="", encoding="utf-8") as handle:
        columns = next(csv.reader(handle))
    assert "reviewer_id" not in columns
    assert "author_label" not in columns
    assert "author_uri" not in columns
    assert "author_fingerprint" not in columns
    assert "source_review_id" in columns
