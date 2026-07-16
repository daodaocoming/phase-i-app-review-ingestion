from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.database import Database


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Phase I ingestion data and health.")
    parser.add_argument("--db-path", default="database/app_reviews.db")
    parser.add_argument("--sample-size", type=int, default=5)
    args = parser.parse_args()

    with Database(ROOT / args.db_path) as db:
        tables = {
            "apps": "apps",
            "storefronts": "app_storefronts",
            "ingestion_runs": "ingestion_runs",
            "raw_pages": "raw_feed_pages",
            "valid_reviews": "reviews",
            "rejected_records": "rejected_review_records",
            "quality_flags": "review_quality_flags",
        }
        print("Database counts")
        for label, table in tables.items():
            print(f"  {label}: {db.scalar(f'SELECT COUNT(*) FROM {table}')}")

        print("\nReviews by app and vertical")
        rows = db.connection.execute(
            """
            SELECT a.app_name, v.vertical_name, COUNT(r.review_id) AS review_count
            FROM apps a
            JOIN verticals v ON v.vertical_id=a.vertical_id
            LEFT JOIN reviews r ON r.app_id=a.app_id
            GROUP BY a.app_id, a.app_name, v.vertical_name
            ORDER BY a.app_name
            """
        ).fetchall()
        for row in rows:
            print(f"  {row['app_name']} ({row['vertical_name']}): {row['review_count']}")

        latest = db.connection.execute(
            "SELECT * FROM ingestion_runs ORDER BY ingestion_run_id DESC LIMIT 1"
        ).fetchone()
        print("\nMost recent ingestion run")
        if latest:
            fields = (
                "ingestion_run_id", "run_status", "started_at", "completed_at", "apps_requested",
                "pages_fetched", "reviews_parsed", "reviews_inserted", "reviews_updated",
                "reviews_rejected", "flags_created", "failed_requests",
            )
            for field in fields:
                print(f"  {field}: {latest[field]}")
        else:
            print("  No ingestion runs recorded.")

        if latest:
            print("\nMost recent app-level outcomes")
            app_rows = db.connection.execute(
                """
                SELECT x.run_status, x.pages_fetched, x.reviews_parsed, x.reviews_inserted,
                       x.reviews_updated, x.reviews_rejected, x.flags_created,
                       x.failed_requests, a.app_name
                FROM ingestion_run_app_stats x
                JOIN apps a ON a.app_id=x.app_id
                WHERE x.ingestion_run_id=?
                ORDER BY a.app_name
                """,
                (latest["ingestion_run_id"],),
            ).fetchall()
            for row in app_rows:
                print(
                    f"  {row['app_name']}: {row['run_status']} | pages={row['pages_fetched']} | "
                    f"parsed={row['reviews_parsed']} | inserted={row['reviews_inserted']} | "
                    f"updated={row['reviews_updated']} | rejected={row['reviews_rejected']} | "
                    f"flags={row['flags_created']} | failures={row['failed_requests']}"
                )

        print("\nReview sample")
        samples = db.connection.execute(
            """
            SELECT app_name, rating, title, substr(body, 1, 140) AS body, published_at
            FROM training_review_dataset ORDER BY published_at DESC LIMIT ?
            """,
            (args.sample_size,),
        ).fetchall()
        if not samples:
            print("  No reviews loaded.")
        for row in samples:
            print(f"  [{row['app_name']}] {row['rating']} stars | {row['title'] or '(no title)'}")
            print(f"    {row['body']} ({row['published_at']})")


if __name__ == "__main__":
    main()
