"""Run a frozen leave-one-App-out TF-IDF sentiment generalization experiment.

This experiment is intentionally separate from the v1 baseline.  It reuses the
v1 filtering and text-normalization contract, but never overwrites v1 outputs
and never uses the manually reviewed diagnostic rows for fitting or scoring.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_binary_sentiment_baseline import (  # noqa: E402
    DEFAULT_SEED,
    FORBIDDEN_PREDICTOR_FIELDS,
    ISSUE_SIGNAL_TYPES,
    TFIDF_KWARGS,
    _add_signals,
    _filter_flow,
    _load_audit,
    _metrics,
    _read_csv,
    load_issue_keywords,
    normalize_review_text,
)


SCHEMA_VERSION = "cross_app_generalization_v1"
DEFAULT_OUTPUT_DIR = "outputs/ds_v1"
FROZEN_REFERENCE_PATHS = (
    "data/processed/review_features_v1.csv",
    "data/processed/weak_label_audit_v1/sample_manifest.csv",
    "data/processed/weak_label_audit_v1/annotations.csv",
    "config/issue_keywords_v2.yaml",
    "outputs/ds_v1/binary_sentiment_baseline_report.md",
    "outputs/ds_v1/binary_sentiment_baseline_report.json",
    "outputs/ds_v1/binary_sentiment_baseline_predictions.csv",
    "outputs/ds_v1/weak_label_audit_report.md",
    "outputs/ds_v1/weak_label_audit_report.json",
)
DIAGNOSTIC_TAGS = (
    "app_specific_or_oov_terminology",
    "mixed_or_concessive_sentiment",
    "short_or_low_context",
    "implicit_ironic_or_comparative_expression",
    "possible_weak_label_ambiguity",
)


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _redact(text: str, limit: int = 260) -> str:
    text = re.sub(r"https?://\S+|www\.\S+", "[URL]", text)
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[EMAIL]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _text(row: dict[str, Any]) -> str:
    return row.get("normalized_text") or normalize_review_text(
        row.get("title", ""), row.get("body", "")
    )


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text, flags=re.UNICODE))


def _oov_rate(vectorizer: Any, text: str) -> float:
    analyzer = vectorizer.build_analyzer()
    tokens = analyzer(text)
    if not tokens:
        return 0.0
    return float(sum(token not in vectorizer.vocabulary_ for token in tokens) / len(tokens))


def _issue_names(row: dict[str, Any]) -> str:
    names = [signal for signal in ISSUE_SIGNAL_TYPES if row.get(f"issue_{signal}")]
    return "|".join(sorted(names))


def _diagnostic_tags(row: dict[str, Any], text: str, oov_rate: float) -> list[str]:
    tags: list[str] = []
    words = _word_count(text)
    if oov_rate >= 0.45:
        tags.append("app_specific_or_oov_terminology")
    if words <= 8:
        tags.append("short_or_low_context")
    if re.search(r"\b(but|though|although|however|yet|while)\b", text):
        tags.append("mixed_or_concessive_sentiment")
    if re.search(r"\b(better than|worse than|you already know|great\.\.\.|lol|sarcasm)\b", text):
        tags.append("implicit_ironic_or_comparative_expression")
    if row.get("weak_label_needs_review") in {"1", "true", "yes", 1, True}:
        tags.append("possible_weak_label_ambiguity")
    return tags


def _distribution(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    counts = Counter(row["weak_label"] for row in rows)
    return {
        "n": len(rows),
        "class_counts": dict(sorted(counts.items())),
        "class_proportions": {
            label: round(count / len(rows), 6) if rows else 0.0
            for label, count in sorted(counts.items())
        },
    }


def _frozen_references() -> dict[str, dict[str, Any]]:
    references: dict[str, dict[str, Any]] = {}
    for relative in FROZEN_REFERENCE_PATHS:
        path = _resolve(relative)
        if not path.is_file():
            raise FileNotFoundError(f"Frozen reference is missing: {relative}")
        references[relative] = {"sha256": _sha256(path), "bytes": path.stat().st_size}
    return references


def _prepare_rows(input_path: Path, audit_dir: Path, keyword_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = _read_csv(input_path)
    audit_rows, audit_ids = _load_audit(audit_dir)
    audit_groups = {
        hashlib.sha256(normalize_review_text(row.get("title", ""), row.get("body", "")).encode("utf-8")).hexdigest()
        for row in audit_rows
    }
    filtered, flow = _filter_flow(rows, audit_ids, audit_groups)
    _, keywords = load_issue_keywords(keyword_path)
    # Signals are retained as reporting metadata; they are never passed to the model.
    filtered = _add_signals(filtered, keywords)
    if not filtered:
        raise ValueError("Filtered model cohort is empty")
    return filtered, flow


def _fit_fold(train_rows: list[dict[str, Any]], test_rows: list[dict[str, Any]], seed: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    vectorizer = TfidfVectorizer(**TFIDF_KWARGS)
    train_text = [_text(row) for row in train_rows]
    test_text = [_text(row) for row in test_rows]
    matrix_train = vectorizer.fit_transform(train_text)
    matrix_test = vectorizer.transform(test_text)
    model = LogisticRegression(
        class_weight="balanced",
        C=1.0,
        solver="liblinear",
        max_iter=1000,
        random_state=seed,
    )
    y_train = [row["weak_label"] for row in train_rows]
    y_test = [row["weak_label"] for row in test_rows]
    model.fit(matrix_train, y_train)
    predictions = model.predict(matrix_test).tolist()
    margins = model.decision_function(matrix_test).tolist()
    metrics = _metrics(y_test, predictions)
    metrics["train_distribution"] = _distribution(train_rows)
    metrics["test_distribution"] = _distribution(test_rows)
    metrics["model"] = {
        "classifier": "LogisticRegression",
        "class_weight": "balanced",
        "C": 1.0,
        "solver": "liblinear",
        "max_iter": 1000,
        "tfidf": TFIDF_KWARGS,
        "feature_count": int(matrix_train.shape[1]),
        "tfidf_vocabulary_size": int(len(vectorizer.vocabulary_)),
    }
    output: list[dict[str, Any]] = []
    for row, predicted, margin in zip(test_rows, predictions, margins, strict=True):
        text = _text(row)
        output.append(
            {
                "review_id": row["review_id"],
                "held_out_app": row["app_name"],
                "true_label": row["weak_label"],
                "predicted_label": predicted,
                "decision_margin": float(margin),
                "correct": bool(predicted == row["weak_label"]),
                "word_count": _word_count(text),
                "oov_rate": round(_oov_rate(vectorizer, text), 6),
                "issue_signals": _issue_names(row),
            }
        )
    return metrics, output


def _error_review(rows_by_id: dict[str, dict[str, Any]], predictions: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    errors = [prediction for prediction in predictions if not prediction["correct"]]
    errors.sort(key=lambda item: (-abs(item["decision_margin"]), str(item["review_id"])))
    selected: list[dict[str, Any]] = []
    per_class: Counter[str] = Counter()
    for prediction in errors:
        label = prediction["true_label"]
        if per_class[label] >= max(1, limit // 2):
            continue
        row = rows_by_id[prediction["review_id"]]
        text = _text(row)
        tags = _diagnostic_tags(row, text, prediction["oov_rate"])
        selected.append(
            {
                key: prediction[key]
                for key in (
                    "review_id", "held_out_app", "true_label", "predicted_label",
                    "decision_margin", "word_count", "oov_rate", "issue_signals",
                )
            }
            | {
                "diagnostic_tags": tags,
                "diagnostic_note": "; ".join(tags) if tags else "manual review needed",
                "redacted_excerpt": _redact(f"{row.get('title', '')} {row.get('body', '')}"),
            }
        )
        per_class[label] += 1
        if len(selected) >= limit:
            break
    return selected


def _public_diagnostics(errors: list[dict[str, Any]]) -> dict[str, Any]:
    tag_counts = Counter(
        tag
        for error in errors
        for tag in error.get("diagnostic_tags", [])
    )
    return {
        "sampled_error_count": len(errors),
        "diagnostic_tag_counts": dict(sorted(tag_counts.items())),
    }


def _aggregate(folds: dict[str, dict[str, Any]]) -> dict[str, Any]:
    macro = [value["metrics"]["macro_f1"] for value in folds.values()]
    balanced = [value["metrics"]["balanced_accuracy"] for value in folds.values()]
    pooled_true: list[str] = []
    pooled_pred: list[str] = []
    for value in folds.values():
        pooled_true.extend(row["true_label"] for row in value["predictions"])
        pooled_pred.extend(row["predicted_label"] for row in value["predictions"])
    pooled = _metrics(pooled_true, pooled_pred)
    return {
        "app_count": len(folds),
        "per_app_macro_f1": {app: folds[app]["metrics"]["macro_f1"] for app in sorted(folds)},
        "per_app_balanced_accuracy": {app: folds[app]["metrics"]["balanced_accuracy"] for app in sorted(folds)},
        "macro_f1_mean": sum(macro) / len(macro),
        "macro_f1_median": sorted(macro)[len(macro) // 2] if len(macro) % 2 else (sorted(macro)[len(macro) // 2 - 1] + sorted(macro)[len(macro) // 2]) / 2,
        "macro_f1_std": (sum((item - sum(macro) / len(macro)) ** 2 for item in macro) / len(macro)) ** 0.5,
        "macro_f1_min": min(macro),
        "macro_f1_max": max(macro),
        "balanced_accuracy_mean": sum(balanced) / len(balanced),
        "balanced_accuracy_min": min(balanced),
        "balanced_accuracy_max": max(balanced),
        "pooled_metrics": pooled,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Cross-App TF-IDF Generalization",
        "",
        "This is a frozen leave-one-App-out evaluation of the simple TF-IDF-only baseline. Each model is fit on 11 Apps and evaluated once on the unseen App.",
        "",
        "## Protocol and frozen boundaries",
        "",
        f"Input SHA-256: `{report['provenance']['input_sha256']}`",
        f"Issue configuration: `{report['provenance']['issue_keyword_version']}` (signals retained for analysis only)",
        f"Seed: `{report['protocol']['seed']}`; folds: `{report['protocol']['fold_strategy']}`",
        f"Filtered rows: **{report['protocol']['filtered_rows']}**; held-out Apps: **{report['protocol']['app_count']}**",
        "",
        "The 99 clear human-reviewed examples are not used for fitting, model selection, or this evaluation; they remain a targeted diagnostic artifact. The existing baseline and audit artifacts were hash-checked before the run and are not overwritten.",
        "",
        "## Results by held-out App",
        "",
        "| Held-out App | Test N | Negative | Positive | Train N | Purged duplicate groups | Macro F1 | Balanced accuracy |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for app, fold in report["folds"].items():
        dist = fold["metrics"]["test_distribution"]["class_counts"]
        lines.append(
            f"| {app} | {fold['metrics']['n']} | {dist.get('negative', 0)} | {dist.get('positive', 0)} | {fold['train_rows']} | {fold['purged_duplicate_rows']} | {fold['metrics']['macro_f1']:.3f} | {fold['metrics']['balanced_accuracy']:.3f} |"
        )
    aggregate = report["aggregate_metrics"]
    lines += [
        "",
        "## Aggregate view",
        "",
        f"App-level Macro F1: mean `{aggregate['macro_f1_mean']:.3f}`, median `{aggregate['macro_f1_median']:.3f}`, SD `{aggregate['macro_f1_std']:.3f}`, range `{aggregate['macro_f1_min']:.3f}–{aggregate['macro_f1_max']:.3f}`.",
        f"App-level balanced accuracy: mean `{aggregate['balanced_accuracy_mean']:.3f}`, range `{aggregate['balanced_accuracy_min']:.3f}–{aggregate['balanced_accuracy_max']:.3f}`.",
        f"Pooled out-of-App Macro F1: `{aggregate['pooled_metrics']['macro_f1']:.3f}`; pooled balanced accuracy: `{aggregate['pooled_metrics']['balanced_accuracy']:.3f}`.",
        "",
        "These values answer a different question from the existing in-distribution weak-label holdout and are not directly comparable as equivalent benchmarks.",
        "",
        "## Weakest-App diagnostic",
        "",
    ]
    for app in report["weakest_app_diagnostics"]["apps"]:
        diagnosis = report["weakest_app_diagnostics"]["by_app"][app]
        lines += [
            f"### {app}",
            "",
            f"Macro F1 `{diagnosis['macro_f1']:.3f}`; balanced accuracy `{diagnosis['balanced_accuracy']:.3f}`. The sampled error count and diagnostic tags are descriptive; issue signals are interpretability metadata only.",
            "",
            "| Sampled errors | Diagnostic tags |",
            "|---:|---|",
        ]
        tag_counts = diagnosis["diagnostic_tag_counts"]
        lines.append(
            f"| {diagnosis['sampled_error_count']} | {', '.join(f'{tag} ({count})' for tag, count in tag_counts.items()) or 'manual review needed'} |"
        )
        lines.append("")
    lines += [
        "## Interpretation",
        "",
        "Issue signals remain available for analysis, reporting, and interpretability. Their earlier negative delta means they did not provide incremental predictive value on top of TF-IDF in that experiment; it does not show that the underlying issue concepts are useless.",
        "",
        "The primary labels remain filtered rating-derived weak labels, not independent sentiment truth. The targeted 99-row audit diagnostic is therefore not an independent benchmark.",
        "",
    ]
    return "\n".join(lines)


def _email(report: dict[str, Any]) -> str:
    aggregate = report["aggregate_metrics"]
    weakest = report["weakest_app_diagnostics"]["apps"]
    lines = [
        "Subject: Cross-App generalization follow-up",
        "",
        "Hi John,",
        "",
        "I ran the requested leave-one-App-out evaluation using the frozen TF-IDF-only baseline. Each fold trained on 11 Apps and evaluated on the unseen App; the filtered cohort, audit exclusions, normalized-text grouping, and rating-derived predictor exclusions were kept unchanged.",
        "",
        f"Across all 12 Apps, App-level Macro F1 was {aggregate['macro_f1_mean']:.3f} on average (SD {aggregate['macro_f1_std']:.3f}; range {aggregate['macro_f1_min']:.3f}–{aggregate['macro_f1_max']:.3f}) and balanced accuracy was {aggregate['balanced_accuracy_mean']:.3f} on average (range {aggregate['balanced_accuracy_min']:.3f}–{aggregate['balanced_accuracy_max']:.3f}). The pooled out-of-App Macro F1 was {aggregate['pooled_metrics']['macro_f1']:.3f} and pooled balanced accuracy was {aggregate['pooled_metrics']['balanced_accuracy']:.3f}.",
        "",
        "I am treating these as a transfer evaluation, not as a directly comparable replacement for the original weak-label holdout. The 99 manually reviewed examples remain a targeted diagnostic set and were not used as an independent benchmark, tuning set, or selection criterion.",
        "",
        "I also retained the issue signals for analysis and interpretability. The appropriate conclusion from the earlier comparison is that they did not add incremental predictive value on top of TF-IDF in that experiment, not that the signals themselves are unhelpful.",
        "",
        f"The weakest Apps by the reported diagnostic ranking were {', '.join(weakest)}. I reviewed sampled errors for short/low-context text, App-specific or out-of-vocabulary terminology, mixed or concessive sentiment, implicit/comparative phrasing, and possible weak-label ambiguity. The detailed examples and per-App class distributions are in the attached report.",
        "",
        "I have kept the baseline and audit artifacts frozen and have not introduced a more complex model or tuned against the diagnostic examples.",
        "",
        "Best,",
        "Doris",
        "",
    ]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    import sklearn

    input_path = _resolve(args.input)
    audit_dir = _resolve(args.audit_dir)
    keyword_path = _resolve(args.keyword_config)
    frozen = _frozen_references()
    filtered, filter_flow = _prepare_rows(input_path, audit_dir, keyword_path)
    apps = sorted({row["app_name"] for row in filtered})
    if len(apps) != 12:
        raise ValueError(f"Expected all 12 Apps, found {len(apps)}: {apps}")
    rows_by_id = {row["review_id"]: row for row in filtered}
    folds: dict[str, dict[str, Any]] = {}
    all_predictions: list[dict[str, Any]] = []
    for app in apps:
        test_rows = [row for row in filtered if row["app_name"] == app]
        test_groups = {row["text_group"] for row in test_rows}
        raw_train = [row for row in filtered if row["app_name"] != app]
        train_rows = [row for row in raw_train if row["text_group"] not in test_groups]
        purged = len(raw_train) - len(train_rows)
        if set(row["app_name"] for row in train_rows) & {app}:
            raise AssertionError("Held-out App crossed into training")
        train_groups = {row["text_group"] for row in train_rows}
        if train_groups & test_groups:
            raise AssertionError("Normalized text group crossed the App split")
        if Counter(row["weak_label"] for row in train_rows).keys() != {"negative", "positive"}:
            raise ValueError(f"Training fold for {app} does not contain both classes")
        metrics, predictions = _fit_fold(train_rows, test_rows, args.seed)
        for prediction in predictions:
            prediction["fold_train_rows"] = len(train_rows)
        folds[app] = {
            "held_out_app": app,
            "train_rows": len(train_rows),
            "test_rows": len(test_rows),
            "purged_duplicate_rows": purged,
            "test_text_groups": len(test_groups),
            "train_text_groups": len(train_groups),
            "metrics": metrics,
            "predictions": predictions,
        }
        all_predictions.extend(predictions)
    aggregate = _aggregate(folds)
    weakest = sorted(apps, key=lambda app: (folds[app]["metrics"]["macro_f1"], folds[app]["metrics"]["balanced_accuracy"], app))[:3]
    full_by_app = {
        app: {
            "macro_f1": folds[app]["metrics"]["macro_f1"],
            "balanced_accuracy": folds[app]["metrics"]["balanced_accuracy"],
            "errors": _error_review(
                rows_by_id,
                [prediction for prediction in folds[app]["predictions"] if not prediction["correct"]],
            ),
        }
        for app in weakest
    }
    public_by_app = {
        app: {
            "macro_f1": diagnosis["macro_f1"],
            "balanced_accuracy": diagnosis["balanced_accuracy"],
            **_public_diagnostics(diagnosis["errors"]),
        }
        for app, diagnosis in full_by_app.items()
    }
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "provenance": {
            "input": str(input_path.relative_to(ROOT) if input_path.is_relative_to(ROOT) else input_path),
            "input_sha256": _sha256(input_path),
            "audit_dir": str(audit_dir.relative_to(ROOT) if audit_dir.is_relative_to(ROOT) else audit_dir),
            "keyword_config": str(keyword_path.relative_to(ROOT) if keyword_path.is_relative_to(ROOT) else keyword_path),
            "issue_keyword_version": load_issue_keywords(keyword_path)[0],
            "sklearn_version": sklearn.__version__,
        },
        "frozen_references": frozen,
        "filter_flow": filter_flow,
        "protocol": {
            "fold_strategy": "leave-one-App-out; TF-IDF fit on other 11 Apps only",
            "seed": args.seed,
            "app_count": len(apps),
            "apps": apps,
            "filtered_rows": len(filtered),
            "all_rows_tested_once": len(all_predictions) == len(filtered) and len({row["review_id"] for row in all_predictions}) == len(filtered),
            "audit_diagnostic_used_for_modeling": False,
            "issue_signals_used_as_predictors": False,
        },
        "predictor_policy": {
            "text_field": "normalized_text (title + body)",
            "model_features": "TF-IDF only",
            "forbidden_fields": sorted(FORBIDDEN_PREDICTOR_FIELDS | {"app_name"}),
            "rating_derived_fields_excluded": True,
            "issue_signals_retained_for_analysis": True,
        },
        "folds": folds,
        "aggregate_metrics": aggregate,
        "weakest_app_diagnostics": {"apps": weakest, "by_app": public_by_app, "tag_vocabulary": list(DIAGNOSTIC_TAGS)},
    }
    out_dir = _resolve(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "cross_app_generalization_report.md"
    summary_path = out_dir / "cross_app_generalization_report.json"
    predictions_path = out_dir / "cross_app_generalization_predictions.csv"
    errors_path = out_dir / "cross_app_error_review.csv"
    email_path = out_dir / "cross_app_mentor_update_email.md"
    report_path.write_text(_markdown(report), encoding="utf-8")
    summary_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    prediction_fields = ["review_id", "held_out_app", "true_label", "predicted_label", "decision_margin", "correct", "word_count", "oov_rate", "issue_signals", "fold_train_rows"]
    with predictions_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=prediction_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row[field] for field in prediction_fields} for row in all_predictions)
    error_fields = ["review_id", "held_out_app", "true_label", "predicted_label", "decision_margin", "word_count", "oov_rate", "issue_signals", "diagnostic_tags", "diagnostic_note", "redacted_excerpt"]
    with errors_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=error_fields, lineterminator="\n")
        writer.writeheader()
        for app in weakest:
            for error in full_by_app[app]["errors"]:
                writer.writerow({**error, "diagnostic_tags": "|".join(error["diagnostic_tags"])})
    email_path.write_text(_email(report), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/processed/review_features_v1.csv")
    parser.add_argument("--audit-dir", default="data/processed/weak_label_audit_v1")
    parser.add_argument("--keyword-config", default="config/issue_keywords_v2.yaml")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    report = run(args)
    print(json.dumps({"schema_version": report["schema_version"], "aggregate_metrics": report["aggregate_metrics"]}, indent=2))


if __name__ == "__main__":
    main()
