from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.apple_rss_client import AppleRSSClient, AppleRSSClientError
from src.config_loader import load_config
from src.database import Database
from src.ingestion_service import IngestionService
from src.logging_utils import configure_logging
from src.parser import extract_review_entries, has_next_page
from src.validation_reporting import write_run_summary


def select_apps(config, app_ids: list[str] | None, storefront: str | None):
    selected = [app for app in config.apps if app.enabled]
    if app_ids:
        selected = [app for app in selected if app.app_id in set(app_ids)]
    if storefront:
        selected = [app for app in selected if app.storefront == storefront.lower()]
    if not selected:
        raise SystemExit("No enabled applications matched the supplied filters.")
    return selected


def dry_run(client: AppleRSSClient, apps, max_pages: int) -> None:
    summary = {"apps_attempted": 0, "pages_fetched": 0, "reviews_parsed": 0, "failed_requests": 0}
    for app in apps:
        summary["apps_attempted"] += 1
        for page in range(1, max_pages + 1):
            try:
                result = client.fetch_page(
                    app_id=app.app_id, app_name=app.app_name, storefront=app.storefront, page=page
                )
            except AppleRSSClientError:
                summary["failed_requests"] += 1
                break
            entries = extract_review_entries(result.payload)
            summary["pages_fetched"] += 1
            summary["reviews_parsed"] += len(entries)
            if not entries or not has_next_page(result.payload):
                break
    print(json.dumps({"dry_run": True, **summary}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and ingest Apple App Store customer reviews.")
    parser.add_argument("--app-id", action="append", help="Only ingest this Apple app id; repeatable.")
    parser.add_argument("--storefront", help="Only ingest the configured storefront.")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse without writing files or SQLite.")
    parser.add_argument("--db-path", default="database/app_reviews.db")
    parser.add_argument("--config-path", default="config/apps.yaml")
    parser.add_argument("--schema-path", default="database/phase_i_database_schema.sql")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument(
        "--summary-output",
        help="Write a JSON run summary to this path; defaults to outputs/validation/run_summaries/run_<id>.json.",
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    configure_logging(args.log_level, ROOT / "logs/ingestion.log")
    config = load_config(ROOT / args.config_path)
    apps = select_apps(config, args.app_id, args.storefront)
    max_pages = args.max_pages or config.settings.max_pages_per_app
    if not 1 <= max_pages <= 10:
        raise SystemExit("--max-pages must be between 1 and 10")
    client = AppleRSSClient(
        timeout_seconds=config.settings.timeout_seconds,
        retry_count=config.settings.retry_count,
        delay_seconds=config.settings.delay_seconds,
    )

    if args.dry_run:
        dry_run(client, apps, max_pages)
        return

    with Database(ROOT / args.db_path) as database:
        database.initialize(ROOT / args.schema_path)
        database.seed_config(config)
        service = IngestionService(database=database, client=client, raw_dir=ROOT / args.raw_dir)
        run_id, stats = service.run(config, apps, max_pages)
        status = database.connection.execute(
            "SELECT run_status FROM ingestion_runs WHERE ingestion_run_id=?", (run_id,)
        ).fetchone()[0]
    summary_path = (
        ROOT / args.summary_output
        if args.summary_output
        else ROOT / "outputs/validation/run_summaries" / f"run_{run_id}.json"
    )
    write_run_summary(ROOT / args.db_path, run_id, summary_path)
    print(json.dumps({"run_id": run_id, "status": status, "summary_output": str(summary_path), **stats.as_dict()}, indent=2))


if __name__ == "__main__":
    main()
