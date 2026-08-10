from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from scripts.run_binary_sentiment_baseline import (
    ISSUE_SIGNAL_TYPES,
    _filter_flow,
    _fit_models,
    load_issue_keywords,
    normalize_review_text,
    run,
)
from src.feature_engineering import build_issue_signals


ROOT = Path(__file__).resolve().parents[1]


def _row(review_id: int, label: str, app: str = "App") -> dict[str, str]:
    row = {
        "review_id": str(review_id),
        "app_name": app,
        "weak_label": label,
        "title": label,
        "body": f"This is a {label} review with enough repeated text for modeling.",
        "detected_language": "en",
        "quality_flag_non_english_or_unknown_language": "0",
        "quality_flag_too_short_review": "0",
        "weak_label_needs_review": "0",
    }
    return row


def _signal_row(review_id: int, label: str, text: str) -> dict[str, object]:
    row: dict[str, object] = {
        "review_id": str(review_id),
        "app_name": "App",
        "weak_label": label,
        "title": "",
        "body": text,
        "normalized_text": normalize_review_text("", text),
        "text_group": str(review_id),
        "manual_label": label,
    }
    row.update({f"issue_{signal}": 0 for signal in ISSUE_SIGNAL_TYPES})
    return row


def test_normalization_is_shared_text_group_contract() -> None:
    assert normalize_review_text(" Hello ", "WORLD\n\n!") == "hello world !"
    assert normalize_review_text("Café", "") == normalize_review_text("café", "")


def test_v2_issue_rules_narrow_audited_false_positive_contexts() -> None:
    _, keywords = load_issue_keywords(ROOT / "config/issue_keywords_v2.yaml")
    false_positive_texts = {
        "performance_crash": "Restaurant service was slow and the account was frozen.",
        "login_account": "I look forward to log in every day and every account has a feature.",
        "update_version": "The free version has ads.",
    }
    for signal, text in false_positive_texts.items():
        assert build_issue_signals(text, keywords)[signal] == 0

    genuine = "The app is crashing, I am locked out and the latest version broke it."
    signals = build_issue_signals(genuine, keywords)
    assert signals["performance_crash"] == 1
    assert signals["login_account"] == 1
    assert signals["update_version"] == 1


def test_filter_flow_excludes_audit_then_applies_binary_gates() -> None:
    rows = [
        {
            **_row(1, "negative"),
            "review_id": "1",
        },
        {
            **_row(2, "neutral"),
            "review_id": "2",
        },
        {
            **_row(3, "positive"),
            "review_id": "3",
            "quality_flag_too_short_review": "1",
        },
    ]
    filtered, flow = _filter_flow(rows, {"1"})
    assert [row["review_id"] for row in filtered] == []
    assert [step["remaining"] for step in flow] == [2, 1, 1, 0, 0]


def test_fit_models_returns_both_comparable_evaluations() -> None:
    pytest.importorskip("sklearn")
    train = []
    for index in range(8):
        label = "negative" if index % 2 == 0 else "positive"
        text = "awful broken crash" if label == "negative" else "excellent reliable success"
        train.append(_signal_row(index, label, f"{text} token{index}"))
    evaluation = [
        _signal_row(20, "negative", "awful broken"),
        _signal_row(21, "positive", "excellent reliable"),
    ]
    audit = [
        _signal_row(30, "negative", "awful crash"),
        _signal_row(31, "positive", "excellent success"),
    ]
    results, predictions = _fit_models(train, evaluation, audit, 20260730)
    assert set(results) == {"tfidf_only", "tfidf_plus_issue_signals", "metric_deltas_augmented_minus_text", "_models"}
    assert results["tfidf_only"]["weak_label_holdout"]["n"] == 2
    assert results["tfidf_plus_issue_signals"]["human_reviewed_diagnostic"]["n"] == 2
    assert len(predictions) == 4


def test_real_baseline_is_leakage_safe_and_reports_expected_cohorts(tmp_path: Path) -> None:
    pytest.importorskip("sklearn")
    report = run(
        Namespace(
            input=str(ROOT / "data/processed/review_features_v1.csv"),
            audit_dir=str(ROOT / "data/processed/weak_label_audit_v1"),
            keyword_config=str(ROOT / "config/issue_keywords_v2.yaml"),
            seed=20260730,
            n_splits=5,
            held_out_fold=0,
            report=str(tmp_path / "report.md"),
            summary_output=str(tmp_path / "report.json"),
            predictions_output=str(tmp_path / "predictions.csv"),
        )
    )
    assert report["filter_flow"][-1]["remaining"] == 1002
    assert report["audit_separation"]["duplicate_audit_text_rows_excluded"] == 1
    assert report["audit_separation"]["remaining_model_rows_with_audit_text_group"] == 0
    assert report["distributions"]["human_reviewed_diagnostic"]["n"] == 99
    assert report["split"]["train_rows"] + report["split"]["evaluation_rows"] == 1002
    assert report["split"]["train_unique_text_groups"] == report["split"]["train_rows"]
    assert report["split"]["evaluation_unique_text_groups"] == report["split"]["evaluation_rows"]
    assert report["predictor_policy"]["rating_derived_fields_excluded"] is True
    assert (tmp_path / "predictions.csv").is_file()
