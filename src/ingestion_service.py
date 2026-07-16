from __future__ import annotations

import json
import logging
from pathlib import Path

from src.apple_rss_client import AppleRSSClient, AppleRSSClientError
from src.database import Database
from src.models import AppConfig, AppRunStats, ProjectConfig, RunStats
from src.normalizer import normalize_review
from src.parser import extract_review_entries, has_next_page
from src.quality_flags import build_quality_flags
from src.utils import compact_timestamp, ensure_parent, sha256_text, utc_now_iso
from src.validator import validate_review


class IngestionService:
    def __init__(
        self,
        *,
        database: Database,
        client: AppleRSSClient,
        raw_dir: str | Path = "data/raw",
    ) -> None:
        self.database = database
        self.client = client
        self.raw_dir = Path(raw_dir)
        self.logger = logging.getLogger(__name__)

    def run(self, config: ProjectConfig, apps: list[AppConfig], max_pages: int) -> tuple[int, RunStats]:
        stats = RunStats()
        errors: list[str] = []
        snapshot = {
            "apps": [app.__dict__ for app in apps],
            "max_pages": max_pages,
            "settings": config.settings.__dict__,
        }
        run_id = self.database.create_ingestion_run(snapshot)

        try:
            for app in apps:
                stats.apps_attempted += 1
                app_db_id, storefront_id = self.database.get_app_context(app)
                app_stats = AppRunStats(pages_requested=max_pages)
                app_stat_id = self.database.create_run_app_stat(
                    run_id=run_id,
                    app_id=app_db_id,
                    app_storefront_id=storefront_id,
                    pages_requested=max_pages,
                )
                app_had_success = False
                app_had_error = False
                for page in range(1, max_pages + 1):
                    try:
                        result = self.client.fetch_page(
                            app_id=app.app_id,
                            app_name=app.app_name,
                            storefront=app.storefront,
                            page=page,
                        )
                    except AppleRSSClientError as exc:
                        stats.failed_requests += 1
                        app_stats.failed_requests += 1
                        app_stats.errors.append(str(exc))
                        errors.append(f"{app.app_name}: {exc}")
                        app_had_error = True
                        break

                    stats.pages_fetched += 1
                    app_stats.pages_fetched += 1
                    fetched_at = utc_now_iso()
                    response_hash = sha256_text(result.raw_text)
                    raw_path = self._save_raw_page(app, page, result.raw_text)
                    stats.raw_pages_saved += 1
                    raw_page_id = self.database.insert_raw_feed_page(
                        run_id=run_id,
                        app_storefront_id=storefront_id,
                        source_url=result.url,
                        page_number=page,
                        http_status=result.status_code,
                        fetched_at=fetched_at,
                        response_hash=response_hash,
                        response_body=result.raw_text,
                        raw_file_path=str(raw_path),
                    )

                    entries = []
                    try:
                        entries = extract_review_entries(result.payload)
                        stats.reviews_parsed += len(entries)
                        app_stats.reviews_parsed += len(entries)
                        page_inserted = 0
                        page_updated = 0
                        page_rejected = 0
                        page_flags = 0
                        with self.database.transaction():
                            for parsed in entries:
                                normalized = normalize_review(parsed, app, result.url)
                                validation = validate_review(normalized)
                                if not validation.valid:
                                    self.database.insert_rejected_review(
                                        run_id=run_id,
                                        raw_page_id=raw_page_id,
                                        app_storefront_id=storefront_id,
                                        review=normalized,
                                        reasons=validation.reasons,
                                    )
                                    page_rejected += 1
                                    continue

                                duplicate = self.database.duplicate_text_exists(
                                    app_storefront_id=storefront_id,
                                    body=normalized.body,
                                    source_review_id=normalized.source_review_id,
                                )
                                reviewer_id = self.database.upsert_reviewer(normalized)
                                review_id, inserted = self.database.upsert_review(
                                    review=normalized,
                                    app_id=app_db_id,
                                    app_storefront_id=storefront_id,
                                    reviewer_id=reviewer_id,
                                    run_id=run_id,
                                    raw_page_id=raw_page_id,
                                )
                                if inserted:
                                    page_inserted += 1
                                else:
                                    page_updated += 1
                                flags = build_quality_flags(normalized, duplicate_text=duplicate)
                                page_flags += self.database.insert_quality_flags(review_id, flags)
                                for flag in flags:
                                    app_stats.flag_counts[flag.flag_type] = (
                                        app_stats.flag_counts.get(flag.flag_type, 0) + 1
                                    )
                                    stats.flag_counts[flag.flag_type] = stats.flag_counts.get(flag.flag_type, 0) + 1
                            self.database.set_raw_page_status(raw_page_id, "parsed")
                        stats.reviews_inserted += page_inserted
                        stats.reviews_updated += page_updated
                        stats.reviews_rejected += page_rejected
                        stats.flags_created += page_flags
                        app_stats.reviews_inserted += page_inserted
                        app_stats.reviews_updated += page_updated
                        app_stats.reviews_rejected += page_rejected
                        app_stats.flags_created += page_flags
                        app_had_success = True
                    except Exception as exc:
                        with self.database.transaction():
                            self.database.set_raw_page_status(raw_page_id, "parse_error", str(exc))
                        error_message = f"{app.app_name} page {page}: {exc}"
                        errors.append(error_message)
                        app_stats.errors.append(error_message)
                        app_had_error = True
                        self.logger.exception(
                            "page_processing_failed",
                            extra={"app_name": app.app_name, "app_id": app.app_id, "page": page, "error": str(exc)},
                        )

                    if not entries or not has_next_page(result.payload):
                        break
                if app_had_success:
                    self.database.mark_storefront_success(storefront_id)
                app_status = "completed_with_errors" if app_had_error else "completed"
                self.database.finish_run_app_stat(stat_id=app_stat_id, status=app_status, stats=app_stats)

            status = "completed_with_errors" if errors else "completed"
        except Exception as exc:
            errors.append(f"fatal: {exc}")
            status = "failed"
            self.logger.exception("ingestion_run_failed", extra={"error": str(exc)})
        self.database.finish_ingestion_run(run_id, status, stats, errors)
        return run_id, stats

    def _save_raw_page(self, app: AppConfig, page: int, raw_text: str) -> Path:
        filename = f"app_{app.app_id}_{app.storefront}_page_{page}_{compact_timestamp()}.json"
        path = self.raw_dir / filename
        ensure_parent(path)
        # Validate that the exact response can be represented as JSON before writing it.
        json.loads(raw_text)
        path.write_text(raw_text, encoding="utf-8")
        return path
