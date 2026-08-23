"""Train and persist the frozen full-cohort TF-IDF sentiment pipeline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_binary_sentiment_baseline import (  # noqa: E402
    DEFAULT_SEED,
    _add_signals,
    _filter_flow,
    _load_audit,
    _read_csv,
    load_issue_keywords,
)
from src.sentiment_pipeline import (  # noqa: E402
    TFIDF_KWARGS,
    build_sentiment_pipeline,
    normalize_review_text,
)


EXPECTED_ROWS = 1002
EXPECTED_CLASS_COUNTS = {"negative": 575, "positive": 427}
MODEL_VERSION = "tfidf_sentiment_final_v1"


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raw_text(row: dict[str, Any]) -> str:
    return f"{row.get('title', '')}\n{row.get('body', '')}".strip()


def _write_training_dataset(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["review_id", "app_name", "title", "body", "weak_label"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def run(args: argparse.Namespace) -> dict[str, Any]:
    import joblib
    import sklearn

    filtered_input = getattr(args, "filtered_input", None)
    input_path = _resolve(filtered_input or args.input)
    audit_dir = _resolve(args.audit_dir)
    keyword_path = _resolve(args.keyword_config)
    model_path = _resolve(args.model_output)
    metadata_path = _resolve(args.metadata_output)
    dataset_path = _resolve(args.dataset_output)

    rows = _read_csv(input_path)
    if filtered_input:
        # This mode consumes the packaged, already-filtered 1,002-row cohort.
        # It is useful for a fresh clone where the original ignored source export
        # and manual audit files are not available.
        if (audit_dir / "sample_manifest.csv").is_file() and (audit_dir / "annotations.csv").is_file():
            audit_rows, audit_ids = _load_audit(audit_dir)
            audit_text_groups = {
                hashlib.sha256(
                    normalize_review_text(row.get("title", ""), row.get("body", "")).encode("utf-8")
                ).hexdigest()
                for row in audit_rows
            }
        else:
            audit_rows = []
            audit_ids = set()
            audit_text_groups = set()
        filtered_rows = []
        for row in rows:
            enriched = dict(row)
            text = normalize_review_text(row.get("title", ""), row.get("body", ""))
            enriched["normalized_text"] = text
            enriched["text_group"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
            filtered_rows.append(enriched)
        filter_flow = [
            {
                "step": "pre_filtered_final_cohort",
                "removed": 0,
                "remaining": len(filtered_rows),
                "class_counts": dict(sorted(Counter(row["weak_label"] for row in filtered_rows).items())),
            }
        ]
    else:
        audit_rows, audit_ids = _load_audit(audit_dir)
        _, keyword_signals = load_issue_keywords(keyword_path)
        audit_text_groups = {
            hashlib.sha256(
                normalize_review_text(row.get("title", ""), row.get("body", "")).encode("utf-8")
            ).hexdigest()
            for row in audit_rows
        }
        filtered_rows, filter_flow = _filter_flow(rows, audit_ids, audit_text_groups)
        filtered_rows = _add_signals(filtered_rows, keyword_signals)

    class_counts = dict(sorted(Counter(row["weak_label"] for row in filtered_rows).items()))
    if len(filtered_rows) != EXPECTED_ROWS or class_counts != EXPECTED_CLASS_COUNTS:
        raise ValueError(
            f"Frozen final cohort mismatch: rows={len(filtered_rows)}, classes={class_counts}; "
            f"expected rows={EXPECTED_ROWS}, classes={EXPECTED_CLASS_COUNTS}"
        )
    if {row["review_id"] for row in filtered_rows} & audit_ids:
        raise AssertionError("Audited review IDs entered the final training cohort")
    if {row["text_group"] for row in filtered_rows} & audit_text_groups:
        raise AssertionError("Audited normalized text entered the final training cohort")

    model = build_sentiment_pipeline(args.seed)
    model.fit([_raw_text(row) for row in filtered_rows], [row["weak_label"] for row in filtered_rows])

    model_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    if dataset_path.resolve() != input_path.resolve():
        _write_training_dataset(dataset_path, filtered_rows)

    keyword_version, _ = load_issue_keywords(keyword_path)
    metadata: dict[str, Any] = {
        "schema_version": "final_sentiment_model_v1",
        "model_version": MODEL_VERSION,
        "model_path": str(model_path.relative_to(ROOT) if model_path.is_relative_to(ROOT) else model_path),
        "model_sha256": _sha256(model_path),
        "training_dataset_path": str(dataset_path.relative_to(ROOT) if dataset_path.is_relative_to(ROOT) else dataset_path),
        "training_dataset_sha256": _sha256(dataset_path),
        "input": str(input_path.relative_to(ROOT) if input_path.is_relative_to(ROOT) else input_path),
        "input_sha256": _sha256(input_path),
        "audit_manifest_sha256": (
            _sha256(audit_dir / "sample_manifest.csv")
            if (audit_dir / "sample_manifest.csv").is_file()
            else None
        ),
        "audit_annotations_sha256": (
            _sha256(audit_dir / "annotations.csv")
            if (audit_dir / "annotations.csv").is_file()
            else None
        ),
        "input_mode": "pre_filtered_final_cohort" if filtered_input else "full_feature_export_with_audit_exclusion",
        "issue_keyword_version": keyword_version,
        "issue_keyword_config_sha256": _sha256(keyword_path),
        "training_rows": len(filtered_rows),
        "class_counts": class_counts,
        "audit_rows_excluded": len(audit_rows),
        "audit_ids_excluded": len(audit_ids),
        "filter_flow": filter_flow,
        "preprocessing": {
            "input_contract": "raw review text; training combines title and body with a newline",
            "normalization": ["NFKC", "casefold", "collapse whitespace"],
            "tfidf": TFIDF_KWARGS,
        },
        "classifier": {
            "name": "LogisticRegression",
            "class_weight": "balanced",
            "C": 1.0,
            "solver": "liblinear",
            "max_iter": 1000,
            "random_state": args.seed,
        },
        "predictor_policy": {
            "features": ["normalized review text TF-IDF"],
            "excluded": ["rating", "App", "quality flags", "issue signals", "weak-label metadata"],
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/processed/review_features_v1.csv")
    parser.add_argument("--filtered-input", help="Packaged final cohort; skips the source filtering/audit lookup")
    parser.add_argument("--audit-dir", default="data/processed/weak_label_audit_v1")
    parser.add_argument("--keyword-config", default="config/issue_keywords_v2.yaml")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--model-output", default="artifacts/final_tfidf_sentiment_pipeline.joblib")
    parser.add_argument("--metadata-output", default="artifacts/final_tfidf_sentiment_pipeline.metadata.json")
    parser.add_argument("--dataset-output", default="artifacts/final_training_dataset.csv")
    args = parser.parse_args()
    metadata = run(args)
    print(json.dumps({key: metadata[key] for key in ("model_version", "training_rows", "class_counts", "model_sha256")}, indent=2))


if __name__ == "__main__":
    main()
