"""Run the reproducible filtered binary weak-label sentiment baseline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.feature_engineering import ISSUE_SIGNAL_TYPES, build_issue_signals  # noqa: E402


DEFAULT_SEED = 20260730
DEFAULT_N_SPLITS = 5
TFIDF_KWARGS = {
    "ngram_range": (1, 2),
    "min_df": 2,
    "max_df": 0.95,
    "sublinear_tf": True,
    "lowercase": False,
}
FORBIDDEN_PREDICTOR_FIELDS = {
    "rating",
    "weak_label",
    "weak_label_source",
    "weak_label_needs_review",
    "weak_label_noise_reasons",
    "neutral_rating",
    "rating_group",
}


def _resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [
            {str(key).lstrip("\ufeff"): (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def normalize_review_text(title: str, body: str) -> str:
    """Create the exact text used both for model input and split grouping."""

    combined = f"{title}\n{body}".strip()
    combined = unicodedata.normalize("NFKC", combined).casefold()
    return re.sub(r"\s+", " ", combined).strip()


def _bool_value(value: str) -> bool:
    return str(value).strip().lower() in {"1", "yes", "true"}


def _filter_flow(
    rows: list[dict[str, str]], audit_ids: set[str], audit_text_groups: set[str] | None = None
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    current = list(rows)
    flow: list[dict[str, Any]] = []

    def apply(name: str, predicate: Any) -> None:
        nonlocal current
        before = len(current)
        current = [row for row in current if predicate(row)]
        flow.append(
            {
                "step": name,
                "removed": before - len(current),
                "remaining": len(current),
                "class_counts": dict(sorted(Counter(row["weak_label"] for row in current).items())),
                "app_counts": dict(sorted(Counter(row["app_name"] for row in current).items())),
            }
        )

    audit_text_groups = audit_text_groups or set()
    apply(
        "audit_excluded",
        lambda row: row["review_id"] not in audit_ids
        and hashlib.sha256(
            normalize_review_text(row.get("title", ""), row.get("body", "")).encode("utf-8")
        ).hexdigest()
        not in audit_text_groups,
    )
    apply("binary_labels_only", lambda row: row["weak_label"] in {"negative", "positive"})
    apply(
        "english_interpretable_proxy",
        lambda row: row.get("detected_language") == "en"
        and row.get("quality_flag_non_english_or_unknown_language") == "0",
    )
    apply("non_short", lambda row: row.get("quality_flag_too_short_review") == "0")
    apply("unflagged", lambda row: row.get("weak_label_needs_review") == "0")
    return current, flow


def _add_signals(rows: Iterable[dict[str, str]], keyword_signals: dict[str, list[str]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        text = normalize_review_text(row.get("title", ""), row.get("body", ""))
        enriched["normalized_text"] = text
        enriched["text_group"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        signals = build_issue_signals(text, keyword_signals)
        enriched.update({f"issue_{name}": int(value) for name, value in signals.items()})
        output.append(enriched)
    return output


def _load_audit(
    sample_dir: Path,
) -> tuple[list[dict[str, Any]], set[str]]:
    manifest = _read_csv(sample_dir / "sample_manifest.csv")
    annotations = _read_csv(sample_dir / "annotations.csv")
    by_id = {row.get("sample_id", ""): row for row in annotations}
    if len(by_id) != len(annotations) or not by_id:
        raise ValueError("Audit annotations must contain unique, non-empty sample_id values")
    audit_rows: list[dict[str, Any]] = []
    audit_ids: set[str] = set()
    for manifest_row in manifest:
        sample_id = manifest_row.get("sample_id", "")
        if sample_id not in by_id:
            raise ValueError(f"Audit annotation missing sample_id {sample_id}")
        annotation = by_id[sample_id]
        row = {**manifest_row, **annotation}
        audit_rows.append(row)
        audit_ids.add(manifest_row["review_id"])
    if len(audit_ids) != len(manifest):
        raise ValueError("Audit manifest contains duplicate review IDs")
    return audit_rows, audit_ids


def _eligible_audit(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = []
    for row in rows:
        sentiment = row.get("apparent_sentiment", "").lower()
        if (
            sentiment in {"negative", "positive"}
            and row.get("mixed_sentiment", "").lower() in {"0", "no"}
            and row.get("appears_english", "").lower() in {"1", "yes"}
            and row.get("text_interpretable", "").lower() in {"1", "yes"}
        ):
            enriched = dict(row)
            enriched["manual_label"] = sentiment
            enriched["normalized_text"] = normalize_review_text(
                row.get("title", ""), row.get("body", "")
            )
            enriched["text_group"] = hashlib.sha256(
                enriched["normalized_text"].encode("utf-8")
            ).hexdigest()
            eligible.append(enriched)
    return eligible


def _metrics(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    from sklearn.metrics import balanced_accuracy_score, f1_score, precision_recall_fscore_support

    labels = ["negative", "positive"]
    precision, recall, fscore, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, zero_division=0
    )
    per_class = {
        label: {
            "precision": float(precision[index]),
            "recall": float(recall[index]),
            "f1": float(fscore[index]),
            "support": int(support[index]),
        }
        for index, label in enumerate(labels)
    }
    confusion = {
        actual: {predicted: 0 for predicted in labels}
        for actual in labels
    }
    for actual, predicted in zip(y_true, y_pred, strict=True):
        confusion[actual][predicted] += 1
    return {
        "n": len(y_true),
        "macro_f1": float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "per_class": per_class,
        "confusion_matrix": confusion,
    }


def _fit_models(
    train_rows: list[dict[str, Any]],
    eval_rows: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    seed: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from scipy import sparse
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    vectorizer = TfidfVectorizer(**TFIDF_KWARGS)
    train_text = [row["normalized_text"] for row in train_rows]
    eval_text = [row["normalized_text"] for row in eval_rows]
    audit_text = [row["normalized_text"] for row in audit_rows]
    matrix_train_text = vectorizer.fit_transform(train_text)
    matrix_eval_text = vectorizer.transform(eval_text)
    matrix_audit_text = vectorizer.transform(audit_text)

    def signal_matrix(rows: list[dict[str, Any]]) -> sparse.csr_matrix:
        return sparse.csr_matrix(
            [[int(row[f"issue_{signal}"]) for signal in ISSUE_SIGNAL_TYPES] for row in rows],
            dtype=float,
        )

    train_signal = signal_matrix(train_rows)
    eval_signal = signal_matrix(eval_rows)
    audit_signal = signal_matrix(audit_rows)
    feature_matrices = {
        "tfidf_only": (matrix_train_text, matrix_eval_text, matrix_audit_text),
        "tfidf_plus_issue_signals": (
            sparse.hstack([matrix_train_text, train_signal], format="csr"),
            sparse.hstack([matrix_eval_text, eval_signal], format="csr"),
            sparse.hstack([matrix_audit_text, audit_signal], format="csr"),
        ),
    }
    y_train = [row["weak_label"] for row in train_rows]
    y_eval = [row["weak_label"] for row in eval_rows]
    y_audit = [row["manual_label"] for row in audit_rows]
    results: dict[str, Any] = {}
    prediction_rows: list[dict[str, Any]] = []
    models: dict[str, Any] = {}
    for model_name, (x_train, x_eval, x_audit) in feature_matrices.items():
        model = LogisticRegression(
            class_weight="balanced",
            C=1.0,
            solver="liblinear",
            max_iter=1000,
            random_state=seed,
        )
        model.fit(x_train, y_train)
        eval_pred = model.predict(x_eval).tolist()
        audit_pred = model.predict(x_audit).tolist()
        eval_margin = model.decision_function(x_eval).tolist()
        audit_margin = model.decision_function(x_audit).tolist()
        results[model_name] = {
            "model": {
                "classifier": "LogisticRegression",
                "class_weight": "balanced",
                "C": 1.0,
                "solver": "liblinear",
                "max_iter": 1000,
                "tfidf": TFIDF_KWARGS,
                "feature_count": int(x_train.shape[1]),
                "tfidf_vocabulary_size": int(len(vectorizer.vocabulary_)),
            },
            "weak_label_holdout": _metrics(y_eval, eval_pred),
            "human_reviewed_diagnostic": _metrics(y_audit, audit_pred),
        }
        models[model_name] = {
            "eval_pred": eval_pred,
            "audit_pred": audit_pred,
            "eval_margin": eval_margin,
            "audit_margin": audit_margin,
        }

    for index, row in enumerate(eval_rows):
        prediction_rows.append(
            {
                "review_id": row["review_id"],
                "cohort": "weak_label_holdout",
                "app_name": row["app_name"],
                "label_source": "weak_label",
                "true_label": row["weak_label"],
                "text_only_prediction": models["tfidf_only"]["eval_pred"][index],
                "text_only_margin": models["tfidf_only"]["eval_margin"][index],
                "text_plus_issue_prediction": models["tfidf_plus_issue_signals"]["eval_pred"][index],
                "text_plus_issue_margin": models["tfidf_plus_issue_signals"]["eval_margin"][index],
                "issue_signals": "|".join(
                    signal for signal in ISSUE_SIGNAL_TYPES if row[f"issue_{signal}"]
                ),
            }
        )
    for index, row in enumerate(audit_rows):
        prediction_rows.append(
            {
                "review_id": row["review_id"],
                "cohort": "human_reviewed_diagnostic",
                "app_name": row["app_name"],
                "label_source": "manual_apparent_sentiment",
                "true_label": row["manual_label"],
                "text_only_prediction": models["tfidf_only"]["audit_pred"][index],
                "text_only_margin": models["tfidf_only"]["audit_margin"][index],
                "text_plus_issue_prediction": models["tfidf_plus_issue_signals"]["audit_pred"][index],
                "text_plus_issue_margin": models["tfidf_plus_issue_signals"]["audit_margin"][index],
                "issue_signals": "|".join(
                    signal for signal in ISSUE_SIGNAL_TYPES if row[f"issue_{signal}"]
                ),
            }
        )
    results["metric_deltas_augmented_minus_text"] = {
        cohort: {
            metric: results["tfidf_plus_issue_signals"][cohort][metric]
            - results["tfidf_only"][cohort][metric]
            for metric in ("macro_f1", "balanced_accuracy")
        }
        for cohort in ("weak_label_holdout", "human_reviewed_diagnostic")
    }
    results["_models"] = models
    return results, prediction_rows


def _redact_excerpt(row: dict[str, Any], limit: int = 220) -> str:
    text = re.sub(r"https?://\S+|www\.\S+", "[URL]", f"{row.get('title', '')} {row.get('body', '')}")
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[EMAIL]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _error_review(
    rows: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    *,
    prediction_field: str,
    margin_field: str,
) -> list[dict[str, Any]]:
    by_id = {row["review_id"]: row for row in rows}
    errors = [
        prediction
        for prediction in predictions
        if prediction[prediction_field] != prediction["true_label"]
    ]
    errors.sort(key=lambda row: (-abs(float(row[margin_field])), str(row["review_id"])))
    chosen: list[dict[str, Any]] = []
    per_class: Counter[str] = Counter()
    for prediction in errors:
        label = prediction["true_label"]
        if per_class[label] >= 3:
            continue
        row = by_id[prediction["review_id"]]
        chosen.append(
            {
                "review_id": prediction["review_id"],
                "app_name": prediction["app_name"],
                "true_label": label,
                "predicted_label": prediction[prediction_field],
                "decision_margin": prediction[margin_field],
                "text_only_correct": (
                    prediction["text_only_prediction"] == prediction["true_label"]
                ),
                "issue_signals": prediction["issue_signals"],
                "excerpt": _redact_excerpt(row),
            }
        )
        per_class[label] += 1
    return chosen


def _distribution(rows: Iterable[dict[str, Any]], label_key: str) -> dict[str, Any]:
    rows = list(rows)
    return {
        "n": len(rows),
        "class_counts": dict(sorted(Counter(row[label_key] for row in rows).items())),
        "app_counts": dict(sorted(Counter(row["app_name"] for row in rows).items())),
        "app_by_class": {
            app: dict(sorted(Counter(row[label_key] for row in rows if row["app_name"] == app).items()))
            for app in sorted({row["app_name"] for row in rows})
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Filtered Binary Sentiment Baseline",
        "",
        "This is a fixed, transparent baseline for testing whether carefully filtered rating-derived weak labels support reproducible modeling. It is not a tuned production model.",
        "",
        "## Provenance and filtering",
        "",
        f"Input SHA-256: `{report['provenance']['input_sha256']}`  ",
        f"Issue configuration: `{report['provenance']['issue_keyword_version']}`  ",
        f"Seed: `{report['split']['seed']}`; split: `{report['split']['strategy']}`",
        "",
        "| Step | Removed | Remaining | Negative | Positive |",
        "|---|---:|---:|---:|---:|",
    ]
    for step in report["filter_flow"]:
        counts = step["class_counts"]
        lines.append(
            f"| {step['step']} | {step['removed']} | {step['remaining']} | {counts.get('negative', 0)} | {counts.get('positive', 0)} |"
        )
    lines += ["", "## Class and App distribution", ""]
    for name, distribution in report["distributions"].items():
        lines.append(f"### {name.replace('_', ' ').title()}")
        lines.append("")
        lines.append(f"Rows: **{distribution['n']}**; classes: `{distribution['class_counts']}`")
        lines.append("")
        lines.append("| App | Counts by label |")
        lines.append("|---|---|")
        for app, counts in distribution["app_by_class"].items():
            lines.append(f"| {app} | `{counts}` |")
        lines.append("")
    lines += [
        "## Metrics",
        "",
        "Rating, rating groups, `neutral_rating`, weak-label metadata, quality flags, App, and other rating-derived fields were excluded from predictors.",
        "",
        "| Model | Evaluation set | Macro F1 | Balanced accuracy | Negative P/R | Positive P/R |",
        "|---|---|---:|---:|---|---|",
    ]
    for model_name in ("tfidf_only", "tfidf_plus_issue_signals"):
        for cohort in ("weak_label_holdout", "human_reviewed_diagnostic"):
            metrics = report["models"][model_name][cohort]
            negative = metrics["per_class"]["negative"]
            positive = metrics["per_class"]["positive"]
            lines.append(
                f"| {model_name} | {cohort} | {metrics['macro_f1']:.3f} | {metrics['balanced_accuracy']:.3f} | {negative['precision']:.3f}/{negative['recall']:.3f} | {positive['precision']:.3f}/{positive['recall']:.3f} |"
            )
    lines += ["", "Metric delta (TF-IDF + v2 signals minus TF-IDF):", ""]
    for cohort, delta in report["metric_deltas_augmented_minus_text"].items():
        lines.append(
            f"- `{cohort}`: macro F1 `{delta['macro_f1']:+.3f}`, balanced accuracy `{delta['balanced_accuracy']:+.3f}`"
        )
    lines += ["", "## Error review", ""]
    for cohort, errors in report["error_review"].items():
        lines.append(f"### {cohort.replace('_', ' ').title()}")
        lines.append("")
        lines.append("| App | True | Predicted | Margin | Text-only correct | Signals | Excerpt |")
        lines.append("|---|---|---|---:|---|---|---|")
        for error in errors:
            excerpt = error["excerpt"].replace("|", "\\|")
            lines.append(
                f"| {error['app_name']} | {error['true_label']} | {error['predicted_label']} | {float(error['decision_margin']):+.3f} | {error['text_only_correct']} | {error['issue_signals'] or '—'} | {excerpt} |"
            )
        if not errors:
            lines.append("| — | — | — | — | — | — | No sampled errors in this cohort. |")
        lines.append("")
    lines += [
        "## Limitations",
        "",
        "The primary holdout measures agreement with filtered weak labels, not independent sentiment truth. The audit diagnostic contains only clear positive/negative judgments and excludes mixed or unclear cases; it is small, targeted, and single-annotator. Issue rules are provisional, versioned candidates rather than permanently validated features.",
        "",
    ]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    from sklearn.model_selection import StratifiedGroupKFold
    import sklearn

    input_path = _resolve(args.input)
    sample_dir = _resolve(args.audit_dir)
    keyword_path = _resolve(args.keyword_config)
    rows = _read_csv(input_path)
    audit_rows, audit_ids = _load_audit(sample_dir)
    if not rows:
        raise ValueError("Feature dataset is empty")
    if not audit_ids.issubset({row["review_id"] for row in rows}):
        raise ValueError("Audit manifest contains review IDs absent from the feature dataset")
    keyword_version, keyword_signals = load_issue_keywords(keyword_path)
    audit_text_groups = {
        hashlib.sha256(
            normalize_review_text(row.get("title", ""), row.get("body", "")).encode("utf-8")
        ).hexdigest()
        for row in audit_rows
    }
    duplicate_audit_text_rows = sum(
        row["review_id"] not in audit_ids
        and hashlib.sha256(
            normalize_review_text(row.get("title", ""), row.get("body", "")).encode("utf-8")
        ).hexdigest()
        in audit_text_groups
        for row in rows
    )
    filtered_rows, filter_flow = _filter_flow(rows, audit_ids, audit_text_groups)
    filtered_rows = _add_signals(filtered_rows, keyword_signals)
    eligible_audit = _add_signals(_eligible_audit(audit_rows), keyword_signals)
    if not filtered_rows or not eligible_audit:
        raise ValueError("Filtered training or human-reviewed diagnostic cohort is empty")
    if {row["review_id"] for row in filtered_rows} & {row["review_id"] for row in eligible_audit}:
        raise ValueError("Training and audited diagnostic cohorts overlap")

    strata = [f"{row['weak_label']}|{row['app_name']}" for row in filtered_rows]
    groups = [row["text_group"] for row in filtered_rows]
    if min(Counter(strata).values()) < args.n_splits:
        raise ValueError("Each class×App stratum must have at least n_splits rows")
    splitter = StratifiedGroupKFold(
        n_splits=args.n_splits,
        shuffle=True,
        random_state=args.seed,
    )
    split_indices = list(
        splitter.split(
            X=[[0] for _ in filtered_rows],
            y=strata,
            groups=groups,
        )
    )
    train_indices, eval_indices = split_indices[args.held_out_fold]
    train_rows = [filtered_rows[index] for index in train_indices]
    eval_rows = [filtered_rows[index] for index in eval_indices]
    train_groups = {filtered_rows[index]["text_group"] for index in train_indices}
    eval_groups = {filtered_rows[index]["text_group"] for index in eval_indices}
    if train_groups & eval_groups:
        raise AssertionError("Normalized text group crossed the train/evaluation split")
    if train_groups & audit_text_groups or eval_groups & audit_text_groups:
        raise AssertionError("Audited normalized text group crossed into model data")
    model_results, prediction_rows = _fit_models(train_rows, eval_rows, eligible_audit, args.seed)
    model_payload = {key: value for key, value in model_results.items() if key != "_models"}
    prediction_by_cohort: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for prediction in prediction_rows:
        prediction_by_cohort[prediction["cohort"]].append(prediction)
    report: dict[str, Any] = {
        "schema_version": "binary_sentiment_baseline_v1",
        "provenance": {
            "input": str(input_path.relative_to(ROOT) if input_path.is_relative_to(ROOT) else input_path),
            "input_sha256": _sha256(input_path),
            "audit_manifest_sha256": _sha256(sample_dir / "sample_manifest.csv"),
            "audit_annotations_sha256": _sha256(sample_dir / "annotations.csv"),
            "issue_keyword_config": str(keyword_path.relative_to(ROOT) if keyword_path.is_relative_to(ROOT) else keyword_path),
            "issue_keyword_config_sha256": _sha256(keyword_path),
            "issue_keyword_version": keyword_version,
            "sklearn_version": sklearn.__version__,
        },
        "filter_flow": filter_flow,
        "audit_separation": {
            "audited_review_ids": len(audit_ids),
            "audited_text_groups": len(audit_text_groups),
            "duplicate_audit_text_rows_excluded": duplicate_audit_text_rows,
            "remaining_model_rows_with_audit_text_group": len(
                ({row["text_group"] for row in filtered_rows} & audit_text_groups)
            ),
        },
        "distributions": {
            "filtered_primary": _distribution(filtered_rows, "weak_label"),
            "training": _distribution(train_rows, "weak_label"),
            "weak_label_holdout": _distribution(eval_rows, "weak_label"),
            "human_reviewed_diagnostic": _distribution(eligible_audit, "manual_label"),
        },
        "split": {
            "strategy": "StratifiedGroupKFold first held-out fold",
            "n_splits": args.n_splits,
            "held_out_fold": args.held_out_fold,
            "seed": args.seed,
            "group_key": "sha256(normalize_review_text(title, body))",
            "stratification_key": "weak_label|app_name",
            "train_rows": len(train_rows),
            "evaluation_rows": len(eval_rows),
            "train_unique_text_groups": len(train_groups),
            "evaluation_unique_text_groups": len(eval_groups),
        },
        "predictor_policy": {
            "text_field": "normalized_text (title + body)",
            "issue_signal_fields": [f"issue_{signal}" for signal in ISSUE_SIGNAL_TYPES],
            "forbidden_fields": sorted(FORBIDDEN_PREDICTOR_FIELDS),
            "rating_derived_fields_excluded": True,
        },
        "models": model_payload,
        "metric_deltas_augmented_minus_text": model_payload["metric_deltas_augmented_minus_text"],
        "audit_diagnostic_eligibility": {
            "audited_rows": len(audit_rows),
            "eligible_rows": len(eligible_audit),
            "excluded_non_clear_binary_or_non_english_or_uninterpretable": len(audit_rows)
            - len(eligible_audit),
        },
        "error_review": {
            "weak_label_holdout": _error_review(
                eval_rows,
                prediction_by_cohort["weak_label_holdout"],
                prediction_field="text_plus_issue_prediction",
                margin_field="text_plus_issue_margin",
            ),
            "human_reviewed_diagnostic": _error_review(
                eligible_audit,
                prediction_by_cohort["human_reviewed_diagnostic"],
                prediction_field="text_plus_issue_prediction",
                margin_field="text_plus_issue_margin",
            ),
        },
    }
    report_path = _resolve(args.report)
    summary_path = _resolve(args.summary_output)
    predictions_path = _resolve(args.predictions_output)
    for path in (report_path, summary_path, predictions_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_markdown(report), encoding="utf-8")
    summary_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    fieldnames = [
        "review_id", "cohort", "app_name", "label_source", "true_label",
        "text_only_prediction", "text_only_margin", "text_plus_issue_prediction",
        "text_plus_issue_margin", "issue_signals",
    ]
    with predictions_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(prediction_rows)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/processed/review_features_v1.csv")
    parser.add_argument("--audit-dir", default="data/processed/weak_label_audit_v1")
    parser.add_argument("--keyword-config", default="config/issue_keywords_v2.yaml")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--n-splits", type=int, default=DEFAULT_N_SPLITS)
    parser.add_argument("--held-out-fold", type=int, default=0)
    parser.add_argument("--report", default="outputs/ds_v1/binary_sentiment_baseline_report.md")
    parser.add_argument("--summary-output", default="outputs/ds_v1/binary_sentiment_baseline_report.json")
    parser.add_argument("--predictions-output", default="outputs/ds_v1/binary_sentiment_baseline_predictions.csv")
    args = parser.parse_args()
    if args.n_splits < 2 or not 0 <= args.held_out_fold < args.n_splits:
        raise SystemExit("--n-splits must be >= 2 and --held-out-fold must be within the split range")
    report = run(args)
    print(json.dumps({"schema_version": report["schema_version"], "models": report["models"]}, indent=2))


if __name__ == "__main__":
    main()
