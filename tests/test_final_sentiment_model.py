from __future__ import annotations

import csv
from argparse import Namespace
from pathlib import Path

import pytest

from scripts.predict_sentiment import predict_texts
from scripts.train_final_sentiment_model import run
from src.sentiment_pipeline import build_sentiment_pipeline, normalize_review_text


ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_normalizes_raw_text_and_mapping_inputs() -> None:
    pipeline = build_sentiment_pipeline()
    texts = ["Terrible crash after login", "Excellent reliable success"]
    pipeline.fit(texts * 3, ["negative", "positive"] * 3)
    assert pipeline.predict(["  TERRIBLE\ncrash after login "])[0] == "negative"
    assert normalize_review_text("Café", "") == normalize_review_text("café", "")


def test_final_training_writes_model_dataset_and_metadata(tmp_path: Path) -> None:
    pytest.importorskip("joblib")
    metadata = run(
        Namespace(
            input=str(ROOT / "data/processed/review_features_v1.csv"),
            audit_dir=str(ROOT / "data/processed/weak_label_audit_v1"),
            keyword_config=str(ROOT / "config/issue_keywords_v2.yaml"),
            seed=20260730,
            model_output=str(tmp_path / "model.joblib"),
            metadata_output=str(tmp_path / "model.metadata.json"),
            dataset_output=str(tmp_path / "dataset.csv"),
        )
    )
    assert metadata["training_rows"] == 1002
    assert metadata["class_counts"] == {"negative": 575, "positive": 427}
    assert Path(metadata["model_path"]).is_absolute() or (tmp_path / "model.joblib").is_file()
    assert (tmp_path / "model.metadata.json").is_file()
    assert sum(1 for _ in csv.DictReader((tmp_path / "dataset.csv").open())) == 1002


def test_saved_model_prediction_is_stable(tmp_path: Path) -> None:
    pytest.importorskip("joblib")
    run(
        Namespace(
            input=str(ROOT / "data/processed/review_features_v1.csv"),
            audit_dir=str(ROOT / "data/processed/weak_label_audit_v1"),
            keyword_config=str(ROOT / "config/issue_keywords_v2.yaml"),
            seed=20260730,
            model_output=str(tmp_path / "model.joblib"),
            metadata_output=str(tmp_path / "model.metadata.json"),
            dataset_output=str(tmp_path / "dataset.csv"),
        )
    )
    first = predict_texts(["Excellent reliable success"] * 2, tmp_path / "model.joblib")
    second = predict_texts(["Excellent reliable success"] * 2, tmp_path / "model.joblib")
    assert first == second
    assert first[0]["model_version"] == "tfidf_sentiment_final_v1"


def test_empty_inference_text_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        predict_texts(["  "], tmp_path / "missing.joblib")
