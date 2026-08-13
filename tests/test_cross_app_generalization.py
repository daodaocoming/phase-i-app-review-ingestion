from __future__ import annotations

from argparse import Namespace
import json
from pathlib import Path

import pytest

from scripts.run_cross_app_generalization import (
    _diagnostic_tags,
    _fit_fold,
    _oov_rate,
    run,
)


ROOT = Path(__file__).resolve().parents[1]


def _row(review_id: int, label: str, app: str, text: str) -> dict[str, object]:
    return {
        "review_id": str(review_id),
        "app_name": app,
        "weak_label": label,
        "normalized_text": text,
        "text_group": str(review_id),
        "title": "",
        "body": text,
        "weak_label_needs_review": "0",
    }


def test_oov_rate_uses_training_vocabulary() -> None:
    pytest.importorskip("sklearn")
    train = [
        _row(1, "negative", "A", "awful broken common"),
        _row(2, "negative", "A", "awful broken common"),
        _row(3, "positive", "A", "excellent reliable common"),
        _row(4, "positive", "A", "excellent reliable common"),
    ]
    test = [
        _row(5, "negative", "B", "awful unfamiliarword common"),
        _row(6, "positive", "B", "excellent unfamiliarword common"),
    ]
    _, predictions = _fit_fold(train, test, 20260730)
    assert predictions[0]["oov_rate"] > 0


def test_diagnostic_tags_are_deterministic() -> None:
    row = {"weak_label_needs_review": "1"}
    tags = _diagnostic_tags(row, "great but broken", 0.5)
    assert tags == [
        "app_specific_or_oov_terminology",
        "short_or_low_context",
        "mixed_or_concessive_sentiment",
        "possible_weak_label_ambiguity",
    ]


def test_real_cross_app_run_is_separate_and_covers_all_apps(tmp_path: Path) -> None:
    pytest.importorskip("sklearn")
    report = run(
        Namespace(
            input=str(ROOT / "data/processed/review_features_v1.csv"),
            audit_dir=str(ROOT / "data/processed/weak_label_audit_v1"),
            keyword_config=str(ROOT / "config/issue_keywords_v2.yaml"),
            seed=20260730,
            output_dir=str(tmp_path),
        )
    )
    assert report["schema_version"] == "cross_app_generalization_v1"
    assert report["protocol"]["app_count"] == 12
    assert report["protocol"]["filtered_rows"] == 1002
    assert report["protocol"]["all_rows_tested_once"] is True
    assert report["protocol"]["audit_diagnostic_used_for_modeling"] is False
    assert report["protocol"]["issue_signals_used_as_predictors"] is False
    assert len(report["weakest_app_diagnostics"]["apps"]) == 3
    assert (tmp_path / "cross_app_generalization_report.md").is_file()
    assert (tmp_path / "cross_app_mentor_update_email.md").is_file()
    public_report = json.loads((tmp_path / "cross_app_generalization_report.json").read_text())
    assert "redacted_excerpt" not in json.dumps(public_report)
    assert "review_id" not in json.dumps(public_report["weakest_app_diagnostics"])
