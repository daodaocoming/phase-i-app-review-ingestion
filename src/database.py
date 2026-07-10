from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.models import AppConfig, NormalizedReview, ProjectConfig, QualityFlag, RunStats
from src.utils import canonical_json, sha256_text, utc_now_iso


RSS_URL_TEMPLATE = (
    "https://itunes.apple.com/{storefront}/rss/customerreviews/"
    "page={page}/id={app_id}/sortby=mostrecent/json"
)


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            yield
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def initialize(self, schema_path: str | Path) -> None:
        schema = Path(schema_path).read_text(encoding="utf-8")
        self.connection.executescript(schema)
        self.connection.commit()

    def seed_config(self, config: ProjectConfig) -> dict[str, int]:
        now = utc_now_iso()
        with self.transaction():
            for app in config.apps:
                self.connection.execute(
                    "INSERT INTO verticals (vertical_name) VALUES (?) ON CONFLICT(vertical_name) DO NOTHING",
                    (app.vertical,),
                )
                vertical_id = self.connection.execute(
                    "SELECT vertical_id FROM verticals WHERE vertical_name = ?", (app.vertical,)
                ).fetchone()[0]
                self.connection.execute(
                    """
                    INSERT INTO apps (
                        source_platform, source_app_id, app_name, vertical_id, is_active, created_at, updated_at
                    ) VALUES ('apple_app_store', ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_platform, source_app_id) DO UPDATE SET
                        app_name = excluded.app_name,
                        vertical_id = excluded.vertical_id,
                        is_active = excluded.is_active,
                        updated_at = excluded.updated_at
                    """,
                    (app.app_id, app.app_name, vertical_id, int(app.enabled), now, now),
                )
                app_db_id = self.connection.execute(
                    "SELECT app_id FROM apps WHERE source_platform='apple_app_store' AND source_app_id=?",
                    (app.app_id,),
                ).fetchone()[0]
                self.connection.execute(
                    """
                    INSERT INTO app_storefronts (
                        app_id, storefront, expected_language, rss_url_template,
                        max_pages_per_run, is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(app_id, storefront) DO UPDATE SET
                        expected_language = excluded.expected_language,
                        rss_url_template = excluded.rss_url_template,
                        max_pages_per_run = excluded.max_pages_per_run,
                        is_active = excluded.is_active,
                        updated_at = excluded.updated_at
                    """,
                    (
                        app_db_id,
                        app.storefront,
                        app.expected_language,
                        RSS_URL_TEMPLATE,
                        config.settings.max_pages_per_app,
                        int(app.enabled),
                        now,
                        now,
                    ),
                )
        return {
            "verticals": self.scalar("SELECT COUNT(*) FROM verticals"),
            "apps": self.scalar("SELECT COUNT(*) FROM apps"),
            "storefronts": self.scalar("SELECT COUNT(*) FROM app_storefronts"),
        }

    def get_app_context(self, app: AppConfig) -> tuple[int, int]:
        row = self.connection.execute(
            """
            SELECT a.app_id, s.app_storefront_id
            FROM apps a
            JOIN app_storefronts s ON s.app_id = a.app_id
            WHERE a.source_platform='apple_app_store'
              AND a.source_app_id=? AND s.storefront=?
            """,
            (app.app_id, app.storefront),
        ).fetchone()
        if row is None:
            raise LookupError(f"App/storefront not seeded: {app.app_name}/{app.storefront}")
        return int(row["app_id"]), int(row["app_storefront_id"])

    def create_ingestion_run(self, config_snapshot: dict[str, object]) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO ingestion_runs (source_platform, run_status, started_at, config_snapshot)
            VALUES ('apple_app_store', 'running', ?, ?)
            """,
            (utc_now_iso(), canonical_json(config_snapshot)),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_ingestion_run(self, run_id: int, status: str, stats: RunStats, errors: list[str]) -> None:
        self.connection.execute(
            """
            UPDATE ingestion_runs SET
                run_status=?, completed_at=?, apps_requested=?, pages_fetched=?,
                reviews_parsed=?, reviews_inserted=?, reviews_updated=?, reviews_rejected=?,
                flags_created=?, failed_requests=?, error_summary=?
            WHERE ingestion_run_id=?
            """,
            (
                status,
                utc_now_iso(),
                stats.apps_attempted,
                stats.pages_fetched,
                stats.reviews_parsed,
                stats.reviews_inserted,
                stats.reviews_updated,
                stats.reviews_rejected,
                stats.flags_created,
                stats.failed_requests,
                json.dumps(errors, ensure_ascii=False) if errors else None,
                run_id,
            ),
        )
        self.connection.commit()

    def insert_raw_feed_page(
        self,
        *,
        run_id: int,
        app_storefront_id: int,
        source_url: str,
        page_number: int,
        http_status: int,
        fetched_at: str,
        response_hash: str,
        response_body: str,
        raw_file_path: str,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO raw_feed_pages (
                ingestion_run_id, app_storefront_id, source_url, page_number, http_status,
                fetched_at, response_hash, response_body, raw_file_path, parse_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                run_id,
                app_storefront_id,
                source_url,
                page_number,
                http_status,
                fetched_at,
                response_hash,
                response_body,
                raw_file_path,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def set_raw_page_status(self, raw_page_id: int, status: str, error: str | None = None) -> None:
        self.connection.execute(
            "UPDATE raw_feed_pages SET parse_status=?, parse_error=? WHERE raw_feed_page_id=?",
            (status, error, raw_page_id),
        )

    def upsert_reviewer(self, review: NormalizedReview) -> int | None:
        identity = review.author_uri or review.author_label
        if not identity:
            return None
        fingerprint = sha256_text(f"{review.source_platform}|{identity}")
        now = utc_now_iso()
        self.connection.execute(
            """
            INSERT INTO reviewers (
                source_platform, author_uri, author_label, author_fingerprint, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_platform, author_fingerprint) DO UPDATE SET
                author_uri=excluded.author_uri,
                author_label=excluded.author_label,
                updated_at=excluded.updated_at
            """,
            (review.source_platform, review.author_uri, review.author_label, fingerprint, now, now),
        )
        row = self.connection.execute(
            "SELECT reviewer_id FROM reviewers WHERE source_platform=? AND author_fingerprint=?",
            (review.source_platform, fingerprint),
        ).fetchone()
        return int(row[0])

    def duplicate_text_exists(
        self, *, app_storefront_id: int, body: str, source_review_id: str | None
    ) -> bool:
        row = self.connection.execute(
            """
            SELECT 1 FROM reviews
            WHERE app_storefront_id=? AND lower(trim(body))=lower(trim(?))
              AND source_review_id <> COALESCE(?, '')
            LIMIT 1
            """,
            (app_storefront_id, body, source_review_id),
        ).fetchone()
        return row is not None

    def upsert_review(
        self,
        *,
        review: NormalizedReview,
        app_id: int,
        app_storefront_id: int,
        reviewer_id: int | None,
        run_id: int,
        raw_page_id: int,
    ) -> tuple[int, bool]:
        existing = self.connection.execute(
            """
            SELECT review_id FROM reviews
            WHERE source_platform=? AND app_storefront_id=? AND source_review_id=?
            """,
            (review.source_platform, app_storefront_id, review.source_review_id),
        ).fetchone()
        now = utc_now_iso()
        self.connection.execute(
            """
            INSERT INTO reviews (
                source_platform, source_review_id, app_id, app_storefront_id, reviewer_id,
                rating, title, body, app_version, review_url, source_endpoint, published_at,
                detected_language, body_char_count, body_token_estimate, vote_count, vote_sum,
                raw_payload_hash, first_raw_feed_page_id, last_raw_feed_page_id,
                first_seen_run_id, last_seen_run_id, first_seen_at, last_seen_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_platform, app_storefront_id, source_review_id) DO UPDATE SET
                reviewer_id=excluded.reviewer_id,
                app_version=excluded.app_version,
                vote_count=excluded.vote_count,
                vote_sum=excluded.vote_sum,
                raw_payload_hash=excluded.raw_payload_hash,
                last_raw_feed_page_id=excluded.last_raw_feed_page_id,
                last_seen_run_id=excluded.last_seen_run_id,
                last_seen_at=excluded.last_seen_at,
                updated_at=excluded.updated_at
            """,
            (
                review.source_platform,
                review.source_review_id,
                app_id,
                app_storefront_id,
                reviewer_id,
                review.rating,
                review.title,
                review.body,
                review.app_version,
                review.review_url,
                review.source_endpoint,
                review.published_at,
                review.detected_language,
                review.body_char_count,
                review.body_token_estimate,
                review.vote_count,
                review.vote_sum,
                review.raw_payload_hash,
                raw_page_id,
                raw_page_id,
                run_id,
                run_id,
                now,
                now,
                now,
                now,
            ),
        )
        row = self.connection.execute(
            """
            SELECT review_id FROM reviews
            WHERE source_platform=? AND app_storefront_id=? AND source_review_id=?
            """,
            (review.source_platform, app_storefront_id, review.source_review_id),
        ).fetchone()
        return int(row[0]), existing is None

    def insert_rejected_review(
        self,
        *,
        run_id: int,
        raw_page_id: int,
        app_storefront_id: int,
        review: NormalizedReview,
        reasons: list[str],
    ) -> None:
        raw_payload = canonical_json(review.raw_record)
        self.connection.execute(
            """
            INSERT INTO rejected_review_records (
                ingestion_run_id, raw_feed_page_id, app_storefront_id, source_review_id,
                rejection_reason, rejection_details, raw_payload_hash, raw_payload, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                raw_page_id,
                app_storefront_id,
                review.source_review_id,
                reasons[0],
                json.dumps(reasons, ensure_ascii=False),
                review.raw_payload_hash,
                raw_payload,
                utc_now_iso(),
            ),
        )

    def insert_quality_flags(self, review_id: int, flags: list[QualityFlag]) -> int:
        created = 0
        for flag in flags:
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO review_quality_flags (
                    review_id, flag_type, flag_severity, flag_details, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (review_id, flag.flag_type, flag.severity, flag.details, utc_now_iso()),
            )
            created += cursor.rowcount
        return created

    def mark_storefront_success(self, app_storefront_id: int) -> None:
        self.connection.execute(
            "UPDATE app_storefronts SET last_successful_ingestion_at=?, updated_at=? WHERE app_storefront_id=?",
            (utc_now_iso(), utc_now_iso(), app_storefront_id),
        )
        self.connection.commit()

    def scalar(self, query: str, parameters: tuple[object, ...] = ()) -> int:
        row = self.connection.execute(query, parameters).fetchone()
        return int(row[0]) if row else 0
