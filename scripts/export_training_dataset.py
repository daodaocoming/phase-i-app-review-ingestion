from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.database import Database


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the training_review_dataset view to CSV.")
    parser.add_argument("--db-path", default="database/app_reviews.db")
    parser.add_argument("--output", default="data/processed/training_reviews.csv")
    parser.add_argument("--english-only", action="store_true")
    args = parser.parse_args()

    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    query = "SELECT * FROM training_review_dataset"
    if args.english_only:
        query += " WHERE detected_language='en' AND has_error_flag=0"
    query += " ORDER BY published_at DESC"

    with Database(ROOT / args.db_path) as db:
        cursor = db.connection.execute(query)
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)
    print(f"Exported {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
