from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.feature_engineering import (  # noqa: E402
    FEATURE_COLUMNS,
    ISSUE_SIGNAL_TYPES,
    QUALITY_FLAG_TYPES,
    build_feature_row,
)


def _resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def load_issue_keywords(path: Path) -> tuple[str, dict[str, list[str]]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    version = payload.get("version")
    signals = payload.get("signals")
    if not isinstance(version, str) or not version:
        raise ValueError("Issue keyword config requires a non-empty version")
    if not isinstance(signals, dict):
        raise ValueError("Issue keyword config requires a signals mapping")
    normalized: dict[str, list[str]] = {}
    for name, terms in signals.items():
        if not isinstance(terms, list) or not all(isinstance(term, str) for term in terms):
            raise ValueError(f"Signal {name!r} must contain a list of strings")
        normalized[str(name)] = terms
    return version, normalized


def read_source_rows(
    db_path: Path,
) -> tuple[list[dict[str, Any]], dict[int, set[str]]]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT review_id, source_review_id, app_name, vertical_name,
                       storefront, rating, title, body, detected_language, published_at
                FROM training_review_dataset
                ORDER BY review_id
                """
            ).fetchall()
        ]
        flags: dict[int, set[str]] = defaultdict(set)
        for row in connection.execute(
            "SELECT review_id, flag_type FROM review_quality_flags ORDER BY review_id, flag_type"
        ):
            flags[int(row["review_id"])].add(str(row["flag_type"]))
        return rows, flags
    finally:
        connection.close()


def build_summary(
    rows: list[dict[str, Any]],
    *,
    input_db: str,
    output_csv: Path,
    keyword_version: str,
) -> dict[str, Any]:
    label_counts = Counter(row["weak_label"] for row in rows)
    flag_counts = {
        flag_type: sum(int(row[f"quality_flag_{flag_type}"]) for row in rows)
        for flag_type in QUALITY_FLAG_TYPES
    }
    issue_counts = {
        signal_type: sum(int(row[f"issue_{signal_type}"]) for row in rows)
        for signal_type in ISSUE_SIGNAL_TYPES
    }
    needs_review_rows = sum(int(row["weak_label_needs_review"]) for row in rows)
    noise_counts: Counter[str] = Counter()
    for row in rows:
        noise_counts.update(filter(None, str(row["weak_label_noise_reasons"]).split("|")))
    return {
        "schema_version": "review_features_v1",
        "weak_label_source": "rating_v1",
        "issue_keyword_version": keyword_version,
        "input_db": input_db,
        "output_csv": str(output_csv.relative_to(ROOT) if output_csv.is_relative_to(ROOT) else output_csv),
        "output_sha256": hashlib.sha256(output_csv.read_bytes()).hexdigest(),
        "rows": len(rows),
        "unique_review_ids": len({row["review_id"] for row in rows}),
        "apps": len({row["app_name"] for row in rows}),
        "verticals": len({row["vertical_name"] for row in rows}),
        "weak_label_counts": dict(sorted(label_counts.items())),
        "weak_label_needs_review_rows": needs_review_rows,
        "weak_label_needs_review_share": (
            needs_review_rows / len(rows) if rows else 0.0
        ),
        "quality_flag_counts": flag_counts,
        "issue_signal_counts": issue_counts,
        "weak_label_noise_reason_counts": dict(sorted(noise_counts.items())),
        "columns": list(FEATURE_COLUMNS),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the deterministic Feature Engineering & Weak Labeling v1 CSV."
    )
    parser.add_argument("--db-path", default="database/validation_scale.db")
    parser.add_argument("--output", default="data/processed/review_features_v1.csv")
    parser.add_argument(
        "--summary-output",
        default="outputs/ds_v1/feature_summary.json",
    )
    parser.add_argument(
        "--keyword-config",
        default="config/issue_keywords_v1.yaml",
    )
    args = parser.parse_args()

    db_path = _resolve(args.db_path)
    if not db_path.is_file():
        raise SystemExit(f"Database not found: {db_path}")
    output_path = _resolve(args.output)
    summary_path = _resolve(args.summary_output)
    keyword_version, keyword_signals = load_issue_keywords(_resolve(args.keyword_config))
    source_rows, flags_by_review = read_source_rows(db_path)

    feature_rows = [
        build_feature_row(
            row,
            quality_flags=flags_by_review.get(int(row["review_id"]), set()),
            keyword_signals=keyword_signals,
        )
        for row in source_rows
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FEATURE_COLUMNS)
        writer.writeheader()
        writer.writerows(feature_rows)

    summary = build_summary(
        feature_rows,
        input_db=args.db_path,
        output_csv=output_path,
        keyword_version=keyword_version,
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
