from __future__ import annotations

import copy
import json
from pathlib import Path

from src.apple_rss_client import AppleRSSClientError
from src.config_loader import load_config
from src.database import Database
from src.ingestion_service import IngestionService
from src.models import FetchResult
from src.validation_reporting import build_run_summary, build_validation_report, write_run_summary


ROOT = Path(__file__).resolve().parents[1]


class FixtureClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def fetch_page(self, *, app_id: str, app_name: str, storefront: str, page: int) -> FetchResult:
        payload = copy.deepcopy(self.payload)
        raw_text = json.dumps(payload, sort_keys=True)
        return FetchResult(
            url=f"https://example.test/{app_id}/{page}",
            page_number=page,
            status_code=200,
            elapsed_seconds=0.001,
            payload=payload,
            raw_text=raw_text,
        )


def test_repeated_runs_record_per_app_stats_and_source_window_changes(tmp_path: Path, sample_payload: dict) -> None:
    config = load_config(ROOT / "config/apps.yaml")
    apps = config.apps[:2]
    db_path = tmp_path / "validation.db"
    raw_dir = tmp_path / "raw"
    changed_payload = copy.deepcopy(sample_payload)
    changed_payload["feed"]["entry"][0]["id"]["label"] = "review-new-window"
    changed_payload["feed"]["link"] = [
        {"attributes": {"rel": "self", "href": "https://example.test/page=1"}}
    ]

    with Database(db_path) as db:
        db.initialize(ROOT / "database/phase_i_database_schema.sql")
        db.seed_config(config)
        first_run, first_stats = IngestionService(
            database=db, client=FixtureClient(sample_payload), raw_dir=raw_dir
        ).run(config, apps, max_pages=1)
        second_run, second_stats = IngestionService(
            database=db, client=FixtureClient(changed_payload), raw_dir=raw_dir
        ).run(config, apps, max_pages=1)

    assert first_stats.reviews_inserted == 4
    assert first_stats.reviews_updated == 0
    assert second_stats.reviews_inserted == 2
    assert second_stats.reviews_updated == 2

    summary = build_run_summary(db_path, second_run)
    assert summary["stats"]["apps_attempted"] == 2
    assert len(summary["apps"]) == 2
    assert all(app["pages_fetched"] == 1 for app in summary["apps"])
    assert all(app["reviews_parsed"] == 2 for app in summary["apps"])

    report = build_validation_report(db_path, [first_run, second_run])
    assert report["duplicate_behavior"]["canonical_reviews"] == 6
    assert report["duplicate_behavior"]["unique_source_keys"] == 6
    assert report["duplicate_behavior"]["repeated_observation_updates"] == 2
    assert report["window_changes"]
    assert all(change["review_window_changed"] for change in report["window_changes"])

    output = tmp_path / "run-summary.json"
    written = write_run_summary(db_path, second_run, output)
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["run_id"] == second_run
    assert written["status"] == "completed"


def test_failed_app_is_recorded_without_stopping_other_apps(tmp_path: Path, sample_payload: dict) -> None:
    config = load_config(ROOT / "config/apps.yaml")
    apps = config.apps[:2]

    class PartiallyFailingClient(FixtureClient):
        def fetch_page(self, *, app_id: str, app_name: str, storefront: str, page: int) -> FetchResult:
            if app_id == apps[0].app_id:
                raise AppleRSSClientError("fixture failure")
            return super().fetch_page(app_id=app_id, app_name=app_name, storefront=storefront, page=page)

    db_path = tmp_path / "failure.db"
    with Database(db_path) as db:
        db.initialize(ROOT / "database/phase_i_database_schema.sql")
        db.seed_config(config)
        run_id, stats = IngestionService(
            database=db,
            client=PartiallyFailingClient(sample_payload),
            raw_dir=tmp_path / "raw",
        ).run(config, apps, max_pages=1)

    assert stats.failed_requests == 1
    summary = build_run_summary(db_path, run_id)
    statuses = {app["app_name"]: app["run_status"] for app in summary["apps"]}
    assert statuses[apps[0].app_name] == "completed_with_errors"
    assert statuses[apps[1].app_name] == "completed"
