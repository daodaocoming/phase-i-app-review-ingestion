from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.analyze_weak_label_audit import _validate_annotations, _wilson


def test_wilson_interval_handles_empty_and_full_counts() -> None:
    assert _wilson(0, 0)["estimate"] == 0.0
    interval = _wilson(10, 10)
    assert interval["estimate"] == 1.0
    assert 0.7 < interval["lower"] < 1.0
    assert interval["upper"] == 1.0


def test_annotation_validation_rejects_unknown_values() -> None:
    manifest = [{"sample_id": "audit_v1_001"}]
    annotation = {
        "sample_id": "audit_v1_001",
        "apparent_sentiment": "bad",
        "rating_label_agreement": "agree",
        "mixed_sentiment": "no",
        "appears_english": "yes",
        "text_interpretable": "yes",
        "annotation_notes": "",
    }
    for signal in (
        "performance_crash", "login_account", "payment_billing", "ads",
        "update_version", "delivery_service", "usability_navigation",
    ):
        annotation[f"issue_{signal}_relevance"] = "not_triggered"
    for term in ("service", "account", "version"):
        annotation[f"{term}_term_relevance"] = "not_triggered"
    with pytest.raises(ValueError, match="apparent_sentiment"):
        _validate_annotations(manifest, [annotation])
