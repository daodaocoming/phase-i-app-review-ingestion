"""Run inference with the persisted final TF-IDF sentiment pipeline."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def _load_model(model_path: Path) -> tuple[Any, str]:
    import joblib

    if not model_path.is_file():
        raise FileNotFoundError(f"Model artifact not found: {model_path}")
    model = joblib.load(model_path)
    metadata_path = model_path.with_name(f"{model_path.stem}.metadata.json")
    model_version = "unknown"
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        model_version = str(metadata.get("model_version", model_version))
    return model, model_version


def predict_texts(texts: list[str], model_path: str | Path) -> list[dict[str, Any]]:
    if not texts:
        return []
    if any(not str(text).strip() for text in texts):
        raise ValueError("Review text must not be empty")
    model, model_version = _load_model(_resolve(model_path))
    labels = model.predict(texts).tolist()
    probabilities = model.predict_proba(texts)
    classes = [str(value) for value in model.classes_]
    class_index = {label: index for index, label in enumerate(classes)}
    predictions: list[dict[str, Any]] = []
    for text, label, probability in zip(texts, labels, probabilities, strict=True):
        predicted = str(label)
        predictions.append(
            {
                "review_text": text,
                "predicted_label": predicted,
                "positive_probability": float(probability[class_index.get("positive", 0)]),
                "negative_probability": float(probability[class_index.get("negative", 0)]),
                "model_version": model_version,
            }
        )
    return predictions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="One review text to classify")
    source.add_argument("--input-csv", help="CSV containing review text")
    parser.add_argument("--text-column", default="review_text")
    parser.add_argument("--output-csv", help="Write batch predictions to CSV")
    parser.add_argument("--model", default="artifacts/final_tfidf_sentiment_pipeline.joblib")
    args = parser.parse_args()

    if args.text is not None:
        print(json.dumps(predict_texts([args.text], args.model)[0], ensure_ascii=False, indent=2))
        return

    input_path = _resolve(args.input_csv)
    with input_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or args.text_column not in reader.fieldnames:
            raise SystemExit(f"CSV is missing required text column: {args.text_column}")
        rows = list(reader)
    predictions = predict_texts([row[args.text_column] for row in rows], args.model)
    if args.output_csv:
        output_path = _resolve(args.output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fields = list(rows[0].keys()) + [
            "predicted_label",
            "positive_probability",
            "negative_probability",
            "model_version",
        ] if rows else [
            args.text_column,
            "predicted_label",
            "positive_probability",
            "negative_probability",
            "model_version",
        ]
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row, prediction in zip(rows, predictions, strict=True):
                writer.writerow({**row, **{key: value for key, value in prediction.items() if key != "review_text"}})
    else:
        print(json.dumps(predictions, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
