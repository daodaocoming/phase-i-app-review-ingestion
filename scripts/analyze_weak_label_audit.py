from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.feature_engineering import ISSUE_SIGNAL_TYPES  # noqa: E402

NOISE_REASONS = (
    "rating_text_mismatch",
    "mixed_sentiment_keywords",
    "neutral_rating",
    "too_short_review",
    "non_english_or_unknown_language",
)
BROAD_TERMS = ("service", "account", "version")
SENTIMENT_VALUES = {"negative", "neutral", "positive", "mixed", "unclear"}
AGREEMENT_VALUES = {"agree", "disagree", "unclear"}
YES_NO_UNCLEAR = {"yes", "no", "unclear"}
RELEVANCE_VALUES = {"relevant", "not_relevant", "unclear", "not_triggered"}


def _resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [
            {key.lstrip("\ufeff"): value.strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def _read_metadata(sample_dir: Path) -> dict[str, Any]:
    return json.loads((sample_dir / "sample_metadata.json").read_text(encoding="utf-8"))


def _split_reasons(value: str) -> set[str]:
    return set(filter(None, value.split("|")))


def _wilson(successes: int, total: int, z: float = 1.96) -> dict[str, float | int]:
    if total == 0:
        return {"successes": 0, "total": 0, "estimate": 0.0, "lower": 0.0, "upper": 0.0}
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return {
        "successes": successes,
        "total": total,
        "estimate": p,
        "lower": max(0.0, center - margin),
        "upper": min(1.0, center + margin),
    }


def _canonical_agreement(value: str) -> str:
    return {
        "1": "agree", "yes": "agree", "agree": "agree",
        "0": "disagree", "no": "disagree", "disagree": "disagree",
        "": "unclear",
    }.get(value.lower(), value.lower())


def _canonical_yes_no(value: str) -> str:
    return {"1": "yes", "yes": "yes", "0": "no", "no": "no", "": "unclear"}.get(
        value.lower(), value.lower()
    )


def _canonical_sentiment(value: str) -> str:
    return {"": "unclear", "mixed": "mixed"}.get(value.lower(), value.lower())


def _canonical_relevance(value: str, *, triggered: bool) -> str:
    normalized = value.lower()
    if normalized in {"1", "yes", "relevant"}:
        return "relevant"
    if normalized in {"0", "no", "not_relevant"}:
        return "not_relevant" if triggered else "not_triggered"
    if normalized == "not_triggered":
        return "not_triggered"
    return "unclear"


def _is_mixed(row: dict[str, str]) -> bool:
    return row["mixed_sentiment"] == "yes" or row["apparent_sentiment"] == "mixed"


def _validate_annotations(
    manifest: list[dict[str, str]], annotations: list[dict[str, str]], *, require_all: bool = True
) -> dict[str, dict[str, str]]:
    manifest_by_id = {row["sample_id"]: row for row in manifest}
    manifest_ids = set(manifest_by_id)
    by_id = {row.get("sample_id", ""): dict(row) for row in annotations}
    if len(by_id) != len(annotations):
        raise ValueError("Annotation file contains duplicate or blank sample_id values")
    if require_all and set(by_id) != manifest_ids:
        missing = sorted(manifest_ids - set(by_id))
        extra = sorted(set(by_id) - manifest_ids)
        raise ValueError(f"Annotation IDs do not match manifest; missing={missing[:5]}, extra={extra[:5]}")
    if not require_all and not set(by_id).issubset(manifest_ids):
        extra = sorted(set(by_id) - manifest_ids)
        raise ValueError(f"Recheck annotations contain unknown sample IDs: {extra[:5]}")
    required = {
        "apparent_sentiment", "rating_label_agreement", "mixed_sentiment",
        "appears_english", "text_interpretable", "annotation_notes",
    }
    required.update(f"issue_{signal}_relevance" for signal in ISSUE_SIGNAL_TYPES)
    required.update(f"{term}_term_relevance" for term in BROAD_TERMS)
    missing_columns = required - set(annotations[0]) if annotations else required
    if missing_columns:
        raise ValueError(f"Annotation file is missing columns: {sorted(missing_columns)}")
    for sample_id, row in by_id.items():
        row["apparent_sentiment"] = _canonical_sentiment(row["apparent_sentiment"])
        row["rating_label_agreement"] = _canonical_agreement(row["rating_label_agreement"])
        for field in ("mixed_sentiment", "appears_english", "text_interpretable"):
            row[field] = _canonical_yes_no(row[field])
        if row["apparent_sentiment"] not in SENTIMENT_VALUES:
            raise ValueError(f"Invalid apparent_sentiment for {sample_id}")
        if row["rating_label_agreement"] not in AGREEMENT_VALUES:
            raise ValueError(f"Invalid rating_label_agreement for {sample_id}")
        for field in ("mixed_sentiment", "appears_english", "text_interpretable"):
            if row[field] not in YES_NO_UNCLEAR:
                raise ValueError(f"Invalid {field} for {sample_id}")
        for signal in ISSUE_SIGNAL_TYPES:
            row[f"issue_{signal}_relevance"] = _canonical_relevance(
                row[f"issue_{signal}_relevance"],
                triggered=manifest_by_id[sample_id][f"issue_{signal}"] == "1",
            )
            if row[f"issue_{signal}_relevance"] not in RELEVANCE_VALUES:
                raise ValueError(f"Invalid issue relevance for {sample_id}/{signal}")
        for term in BROAD_TERMS:
            matched_terms = json.loads(manifest_by_id[sample_id]["matched_issue_terms_json"])
            term_triggered = any(term in values for values in matched_terms.values())
            row[f"{term}_term_relevance"] = _canonical_relevance(
                row[f"{term}_term_relevance"], triggered=term_triggered
            )
            if row[f"{term}_term_relevance"] not in RELEVANCE_VALUES:
                raise ValueError(f"Invalid broad-term relevance for {sample_id}/{term}")
    return by_id


def _merge(manifest: list[dict[str, str]], annotations: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    return [{**row, **annotations[row["sample_id"]]} for row in manifest]


def _agreement_by_class(rows: list[dict[str, str]], metadata: dict[str, Any]) -> dict[str, Any]:
    core = [row for row in rows if row["sample_role"] == "core"]
    result: dict[str, Any] = {}
    population = metadata.get("population_label_flag_counts", {})
    for label in ("negative", "neutral", "positive"):
        label_rows = [row for row in core if row["weak_label"] == label]
        raw_success = sum(row["rating_label_agreement"] == "agree" for row in label_rows)
        weighted = 0.0
        weights: dict[str, float] = {}
        strata: dict[str, Any] = {}
        for flag in ("0", "1"):
            stratum = [row for row in label_rows if row["weak_label_needs_review"] == flag]
            strata[flag] = {
                "agreement": _wilson(
                    sum(row["rating_label_agreement"] == "agree" for row in stratum), len(stratum)
                ),
                "mixed_rate": _wilson(sum(_is_mixed(row) for row in stratum), len(stratum)),
            }
            population_n = int(population.get(f"{label}|{flag}", 0))
            if population_n and stratum:
                weights[flag] = population_n / sum(
                    int(population.get(f"{label}|{other}", 0)) for other in ("0", "1")
                )
                weighted += weights[flag] * sum(
                    row["rating_label_agreement"] == "agree" for row in stratum
                ) / len(stratum)
        result[label] = {
            "raw": _wilson(raw_success, len(label_rows)),
            "weighted_estimate": weighted,
            "stratum_weights": weights,
            "strata": strata,
            "mixed_rate": _wilson(
                sum(_is_mixed(row) for row in label_rows), len(label_rows)
            ),
            "unclear_sentiment_rate": _wilson(
                sum(row["apparent_sentiment"] == "unclear" for row in label_rows), len(label_rows)
            ),
        }
    return result


def _confusion(rows: list[dict[str, str]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        result[row["weak_label"]][row["apparent_sentiment"]] += 1
    return {label: dict(sorted(values.items())) for label, values in sorted(result.items())}


def _noise_reliability(rows: list[dict[str, str]]) -> dict[str, Any]:
    conditions = {
        "rating_text_mismatch": lambda row: row["rating_label_agreement"] == "disagree",
        "mixed_sentiment_keywords": lambda row: _is_mixed(row),
        "neutral_rating": lambda row: (
            row["apparent_sentiment"] != "neutral"
            or _is_mixed(row)
            or row["rating_label_agreement"] != "agree"
        ),
        "too_short_review": lambda row: (
            row["text_interpretable"] == "no" or row["apparent_sentiment"] == "unclear"
        ),
        "non_english_or_unknown_language": lambda row: (
            row["appears_english"] == "no" or row["text_interpretable"] == "no"
        ),
    }
    result = {}
    for reason, condition in conditions.items():
        flagged = [row for row in rows if reason in _split_reasons(row["weak_label_noise_reasons"])]
        result[reason] = {
            "valid_warning_rate": _wilson(sum(condition(row) for row in flagged), len(flagged)),
            "n": len(flagged),
        }
    return result


def _flagged_comparison(rows: list[dict[str, str]]) -> dict[str, Any]:
    core = [row for row in rows if row["sample_role"] == "core"]
    result = {}
    for flag in ("0", "1"):
        group = [row for row in core if row["weak_label_needs_review"] == flag]
        result[flag] = {
            "n": len(group),
            "disagreement_or_unclear": _wilson(
                sum(
                    row["rating_label_agreement"] != "agree"
                    or row["apparent_sentiment"] == "unclear"
                    for row in group
                ),
                len(group),
            ),
        }
    if result["0"]["n"] and result["1"]["n"]:
        result["disagreement_or_unclear_point_difference"] = (
            result["1"]["disagreement_or_unclear"]["estimate"]
            - result["0"]["disagreement_or_unclear"]["estimate"]
        )
    return result


def _signal_reliability(rows: list[dict[str, str]]) -> dict[str, Any]:
    result = {}
    for signal in ISSUE_SIGNAL_TYPES:
        triggered = [row for row in rows if row[f"issue_{signal}"] == "1"]
        relevant = sum(row[f"issue_{signal}_relevance"] == "relevant" for row in triggered)
        result[signal] = {
            "relevance": _wilson(relevant, len(triggered)),
            "not_relevant": sum(row[f"issue_{signal}_relevance"] == "not_relevant" for row in triggered),
            "unclear": sum(row[f"issue_{signal}_relevance"] == "unclear" for row in triggered),
        }
    terms: dict[str, Any] = {}
    for term in BROAD_TERMS:
        triggered = [
            row
            for row in rows
            if term in sum(json.loads(row["matched_issue_terms_json"]).values(), [])
        ]
        field = f"{term}_term_relevance"
        relevant = sum(row[field] == "relevant" for row in triggered)
        terms[term] = {
            "relevance": _wilson(relevant, len(triggered)),
            "not_relevant": sum(row[field] == "not_relevant" for row in triggered),
            "unclear": sum(row[field] == "unclear" for row in triggered),
        }
    return {"signals": result, "broad_terms": terms}


def _decision_summary(agreement: dict[str, Any], signals: dict[str, Any], qc: dict[str, Any] | None) -> dict[str, Any]:
    class_gate = {
        label: agreement[label]["weighted_estimate"] >= 0.80
        and agreement[label]["unclear_sentiment_rate"]["estimate"] <= 0.10
        for label in agreement
    }
    training_class_gate = {}
    for label, values in agreement.items():
        unflagged = values["strata"].get("0", {})
        training_class_gate[label] = bool(
            unflagged.get("agreement", {}).get("total", 0)
            and unflagged["agreement"]["estimate"] >= 0.80
            and unflagged["mixed_rate"]["estimate"] <= 0.20
        )
    signal_gate = {
        name: details["relevance"]["estimate"] >= 0.80
        for name, details in signals["signals"].items()
    }
    term_gate = {
        name: details["relevance"]["estimate"] >= 0.80
        for name, details in signals["broad_terms"].items()
    }
    qc_pass = None if qc is None else (
        qc.get("overall_percent_agreement", 0.0) >= 0.80
        and qc.get("kappa", {}).get("rating_label_agreement", 0.0) >= 0.60
    )
    passing_labels = [label for label, passed in training_class_gate.items() if passed]
    if passing_labels:
        label_text = ", ".join(passing_labels)
        training_rule = (
            f"Use English-interpretable, non-short {label_text} reviews with "
            "weak_label_needs_review=0; exclude the audit sample from training. "
            "Keep all failed classes in manual review until the rules are revised."
        )
    else:
        training_rule = (
            "Do not use any weak-label class for automatic training yet; keep the "
            "audited rows as a validation set and revise the weak-label rules."
        )
    return {
        "class_gate": class_gate,
        "training_class_gate": training_class_gate,
        "signal_gate": signal_gate,
        "broad_term_gate": term_gate,
        "qc_pass": qc_pass,
        "qc_status": "pending_recheck" if qc is None else ("passed" if qc_pass else "failed"),
        "recommended_training_rule": training_rule,
    }


def _recheck_metrics(
    annotations: dict[str, dict[str, str]], recheck: dict[str, dict[str, str]]
) -> dict[str, Any]:
    core_fields = ["apparent_sentiment", "rating_label_agreement", "mixed_sentiment"]
    relevance_fields = [
        *[f"issue_{signal}_relevance" for signal in ISSUE_SIGNAL_TYPES],
        *[f"{term}_term_relevance" for term in BROAD_TERMS],
    ]
    fields = [*core_fields, *relevance_fields]
    out: dict[str, Any] = {}
    for field in fields:
        pairs = [
            (annotations[sample_id][field], row[field])
            for sample_id, row in recheck.items()
        ]
        agree = sum(left == right for left, right in pairs)
        categories = sorted({value for pair in pairs for value in pair})
        observed = agree / len(pairs) if pairs else 0.0
        expected = 0.0
        for category in categories:
            left_share = sum(left == category for left, _ in pairs) / len(pairs)
            right_share = sum(right == category for _, right in pairs) / len(pairs)
            expected += left_share * right_share
        out[field] = {"percent_agreement": observed, "kappa": (observed - expected) / (1 - expected) if expected < 1 else 1.0, "n": len(pairs)}
    out["overall_percent_agreement"] = sum(
        out[field]["percent_agreement"] for field in core_fields
    ) / len(core_fields)
    out["relevance_overall_percent_agreement"] = sum(
        out[field]["percent_agreement"] for field in relevance_fields
    ) / len(relevance_fields)
    out["kappa"] = {field: out[field]["kappa"] for field in fields}
    out["relevance_kappa_mean"] = sum(out[field]["kappa"] for field in relevance_fields) / len(relevance_fields)
    return out


def _write_recheck_template(
    manifest: list[dict[str, str]], annotations: dict[str, dict[str, str]], output: Path, seed: int
) -> None:
    import random

    by_label: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in manifest:
        by_label[row["weak_label"]].append(row)
    rng = random.Random(seed + 1)
    chosen: list[dict[str, str]] = []
    for label, count in (("negative", 8), ("neutral", 7), ("positive", 8)):
        chosen.extend(rng.sample(by_label[label], count))
    rng.shuffle(chosen)
    columns = [
        "sample_id", "app_name", "vertical_name", "title", "body", "detected_language",
        "matched_issue_terms_json",
        "apparent_sentiment", "rating_label_agreement", "mixed_sentiment", "appears_english",
        "text_interpretable",
        *[f"issue_{signal}_relevance" for signal in ISSUE_SIGNAL_TYPES],
        "service_term_relevance", "account_term_relevance", "version_term_relevance", "annotation_notes",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in chosen:
            writer.writerow({
                "sample_id": row["sample_id"],
                "app_name": row["app_name"],
                "vertical_name": row["vertical_name"],
                "title": row.get("title", ""),
                "body": row.get("body", ""),
                "detected_language": row.get("detected_language", ""),
                "matched_issue_terms_json": row.get("matched_issue_terms_json", ""),
            })


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Weak-Label Quality Audit v1",
        "",
        f"Input SHA-256: `{report['input_sha256']}`  ",
        f"Sample size: {report['sample_size']} (core={report['core_size']}, booster={report['booster_size']})  ",
        f"Seed: `{report['seed']}`",
        "",
        "## Sampling",
        "",
        "The core sample is class/flag-stratified. The booster sample targets rare noise reasons, issue signals, broad terms, and App coverage. Neutral-unflagged is structurally unavailable because every three-star review carries `neutral_rating`.",
        "",
        "## Agreement by weak-label class",
        "",
        "| Class | Core n | Raw agreement | Weighted agreement | Unflagged agreement | Mixed | Unclear |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, values in report["agreement_by_class"].items():
        lines.append(
            f"| {label} | {values['raw']['total']} | {values['raw']['estimate']:.1%} | {values['weighted_estimate']:.1%} | {values['strata'].get('0', {}).get('agreement', {}).get('estimate', 0.0):.1%} | {values['mixed_rate']['estimate']:.1%} | {values['unclear_sentiment_rate']['estimate']:.1%} |"
        )
    lines += ["", "## Noise-indicator reliability", "", "| Reason | n | Valid warning rate |", "|---|---:|---:|"]
    for reason, values in report["noise_reliability"].items():
        lines.append(f"| {reason} | {values['n']} | {values['valid_warning_rate']['estimate']:.1%} |")
    lines += ["", "## Issue-signal reliability", "", "| Signal | n | Relevant | Not relevant | Unclear |", "|---|---:|---:|---:|---:|"]
    for signal, values in report["signal_reliability"]["signals"].items():
        lines.append(f"| {signal} | {values['relevance']['total']} | {values['relevance']['estimate']:.1%} | {values['not_relevant']} | {values['unclear']} |")
    lines += ["", "### Broad terms", "", "| Term | n | Relevant | Not relevant | Unclear |", "|---|---:|---:|---:|---:|"]
    for term, values in report["signal_reliability"]["broad_terms"].items():
        lines.append(f"| {term} | {values['relevance']['total']} | {values['relevance']['estimate']:.1%} | {values['not_relevant']} | {values['unclear']} |")
    lines += ["", "## Training-data recommendation", "", report["decisions"]["recommended_training_rule"], ""]
    lines.append("Class gates: " + ", ".join(f"{key}={'pass' if value else 'fail'}" for key, value in report["decisions"]["class_gate"].items()) + ".")
    lines.append("Unflagged training gates: " + ", ".join(f"{key}={'pass' if value else 'fail'}" for key, value in report["decisions"]["training_class_gate"].items()) + ".")
    lines.append("Signal gates: " + ", ".join(f"{key}={'pass' if value else 'review'}" for key, value in report["decisions"]["signal_gate"].items()) + ".")
    if "recheck_qc" in report:
        lines.append(
            f"Recheck QC: **{report['decisions']['qc_status']}**; core fields agreement="
            f"{report['recheck_qc']['overall_percent_agreement']:.1%}, issue relevance agreement="
            f"{report['recheck_qc']['relevance_overall_percent_agreement']:.1%}."
        )
    else:
        lines.append(f"Recheck QC: **{report['decisions']['qc_status']}**.")
    lines += ["", "## Limitations", "", "This is a small, manually annotated diagnostic sample from the retained Apple RSS window. The booster strata are intentionally non-proportional, and the annotation is single-person with a 15% recheck.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a completed weak-label audit.")
    parser.add_argument("--sample-dir", default="data/processed/weak_label_audit_v1")
    parser.add_argument("--annotations", default="data/processed/weak_label_audit_v1/annotations.csv")
    parser.add_argument("--recheck-annotations")
    parser.add_argument("--recheck-output", default="data/processed/weak_label_audit_v1/recheck_template.csv")
    parser.add_argument("--report", default="outputs/ds_v1/weak_label_audit_report.md")
    parser.add_argument("--summary-output", default="outputs/ds_v1/weak_label_audit_report.json")
    args = parser.parse_args()

    sample_dir = _resolve(args.sample_dir)
    manifest = _read_csv(sample_dir / "sample_manifest.csv")
    metadata = _read_metadata(sample_dir)
    annotations_path = _resolve(args.annotations)
    if not annotations_path.is_file():
        _write_recheck_template(manifest, {}, _resolve(args.recheck_output), int(metadata["seed"]))
        raise SystemExit(
            f"Annotations are not complete. Fill {annotations_path}; a recheck template was created at {_resolve(args.recheck_output)}."
        )
    annotations_rows = _read_csv(annotations_path)
    annotations = _validate_annotations(manifest, annotations_rows)
    merged = _merge(manifest, annotations)
    qc = None
    if args.recheck_annotations:
        recheck_rows = _read_csv(_resolve(args.recheck_annotations))
        recheck = _validate_annotations(manifest, recheck_rows, require_all=False)
        qc = _recheck_metrics(annotations, recheck)
    report: dict[str, Any] = {
        "schema_version": "weak_label_audit_report_v1",
        "input_sha256": metadata["input_sha256"],
        "seed": metadata["seed"],
        "sample_size": len(merged),
        "core_size": sum(row["sample_role"] == "core" for row in merged),
        "booster_size": sum(row["sample_role"] == "booster" for row in merged),
        "agreement_by_class": _agreement_by_class(merged, metadata),
        "confusion_matrix": _confusion(merged),
        "noise_reliability": _noise_reliability(merged),
        "flagged_comparison": _flagged_comparison(merged),
        "signal_reliability": _signal_reliability(merged),
    }
    if qc is not None:
        report["recheck_qc"] = qc
    report["decisions"] = _decision_summary(report["agreement_by_class"], report["signal_reliability"], qc)
    report_path = _resolve(args.report)
    summary_path = _resolve(args.summary_output)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_markdown(report), encoding="utf-8")
    summary_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_recheck_template(manifest, annotations, _resolve(args.recheck_output), int(metadata["seed"]))
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
