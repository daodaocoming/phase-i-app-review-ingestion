from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
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
SEED = 20260730
CORE_SIZE = 120
BOOSTER_SIZE = 30
TOTAL_SIZE = CORE_SIZE + BOOSTER_SIZE


def _resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def _text(row: dict[str, str]) -> str:
    return f"{row.get('title', '')}\n{row.get('body', '')}".strip()


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(" ".join(term.strip().split())).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<!\w){escaped}(?!\w)", flags=re.IGNORECASE)


def _matched_terms(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if _term_pattern(term).search(text)]


def _load_rows(path: Path) -> tuple[list[dict[str, str]], str]:
    raw = path.read_bytes()
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"Input CSV is empty: {path}")
    required = {
        "review_id",
        "app_name",
        "vertical_name",
        "weak_label",
        "weak_label_needs_review",
        "weak_label_noise_reasons",
    }
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"Input CSV is missing columns: {sorted(missing)}")
    ids = [row["review_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Input CSV contains duplicate review_id values")
    return rows, hashlib.sha256(raw).hexdigest()


def _load_issue_keywords(path: Path) -> tuple[str, dict[str, list[str]]]:
    """Read the deliberately simple v1 YAML without adding a runtime dependency."""
    version = ""
    signals: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("version:"):
            version = stripped.split(":", 1)[1].strip().strip("\"'")
        elif line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            current = stripped[:-1]
            signals[current] = []
        elif current and stripped.startswith("-"):
            signals[current].append(stripped[1:].strip().strip("\"'"))
    if not version or set(signals) != set(ISSUE_SIGNAL_TYPES):
        raise ValueError(
            f"Issue keyword config must define version and exactly v1 signals; got {sorted(signals)}"
        )
    return version, signals


def _stable_rank(rows: list[dict[str, str]], seed: int) -> dict[str, float]:
    rank: dict[str, float] = {}
    for row in rows:
        rank[row["review_id"]] = random.Random(f"{seed}:{row['review_id']}").random()
    return rank


def _take_cell(
    pool: list[dict[str, str]],
    count: int,
    rank: dict[str, float],
) -> list[dict[str, str]]:
    if len(pool) < count:
        raise ValueError(f"Requested {count} rows but only {len(pool)} are available")
    return sorted(pool, key=lambda row: rank[row["review_id"]])[:count]


def _core_sample(rows: list[dict[str, str]], rank: dict[str, float]) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for label in ("negative", "positive"):
        for flagged, count in (("0", 20), ("1", 20)):
            selected.extend(
                _take_cell(
                    [
                        row
                        for row in rows
                        if row["weak_label"] == label
                        and row["weak_label_needs_review"] == flagged
                    ],
                    count,
                    rank,
                )
            )
    selected.extend(
        _take_cell(
            [row for row in rows if row["weak_label"] == "neutral"],
            40,
            rank,
        )
    )

    # Enforce minimum App coverage with swaps inside the same label/flag cell.
    selected_ids = {row["review_id"] for row in selected}
    for _ in range(200):
        app_counts = Counter(row["app_name"] for row in selected)
        deficient = sorted(app for app, count in app_counts.items() if count < 5)
        all_apps = sorted({row["app_name"] for row in rows})
        deficient.extend(app for app in all_apps if app not in app_counts)
        deficient = sorted(set(deficient))
        if not deficient:
            break
        target_app = deficient[0]
        candidate = min(
            (
                row
                for row in rows
                if row["app_name"] == target_app
                and row["review_id"] not in selected_ids
                and (
                    row["weak_label"] in {"negative", "positive", "neutral"}
                )
            ),
            key=lambda row: rank[row["review_id"]],
            default=None,
        )
        if candidate is None:
            raise ValueError(f"Cannot reach core App coverage for {target_app}")
        replaceable = [
            row
            for row in selected
            if row["app_name"] != target_app
            and app_counts[row["app_name"]] > 5
            and row["weak_label"] == candidate["weak_label"]
            and row["weak_label_needs_review"] == candidate["weak_label_needs_review"]
        ]
        if not replaceable:
            raise ValueError(
                f"Cannot swap a row to reach core App coverage for {target_app}"
            )
        old = max(replaceable, key=lambda row: rank[row["review_id"]])
        selected[selected.index(old)] = candidate
        selected_ids.remove(old["review_id"])
        selected_ids.add(candidate["review_id"])
    else:
        raise ValueError("Core App coverage did not converge")
    if len(selected) != CORE_SIZE:
        raise AssertionError(f"Core sample has {len(selected)} rows")
    return selected


def _booster_goals(rows: list[dict[str, str]], selected: list[dict[str, str]]) -> dict[str, int]:
    current = selected
    goals: dict[str, int] = {}
    for reason, target in (
        ("mixed_sentiment_keywords", 14),
        ("rating_text_mismatch", 12),
        ("neutral_rating", 40),
        ("too_short_review", 15),
        ("non_english_or_unknown_language", 12),
    ):
        goals[f"reason:{reason}"] = max(
            0, target - sum(reason in r["weak_label_noise_reasons"].split("|") for r in current)
        )
    for signal in ISSUE_SIGNAL_TYPES:
        goals[f"signal:{signal}"] = max(
            0, 8 - sum(int(r[f"issue_{signal}"]) for r in current)
        )
    for term in BROAD_TERMS:
        goals[f"term:{term}"] = max(
            0,
            8
            - sum(
                term in json.loads(r["matched_issue_terms_json"]).get("update_version", [])
                or term in json.loads(r["matched_issue_terms_json"]).get("login_account", [])
                or term in json.loads(r["matched_issue_terms_json"]).get("delivery_service", [])
                for r in current
            ),
        )
    return goals


def _booster_sample(
    rows: list[dict[str, str]],
    core: list[dict[str, str]],
    rank: dict[str, float],
) -> list[dict[str, str]]:
    selected = list(core)
    selected_ids = {row["review_id"] for row in selected}
    all_apps = sorted({row["app_name"] for row in rows})
    for _ in range(BOOSTER_SIZE):
        goals = _booster_goals(rows, selected)
        app_counts = Counter(row["app_name"] for row in selected)
        candidates = [row for row in rows if row["review_id"] not in selected_ids]
        if not candidates:
            raise ValueError("Not enough unique rows to build booster sample")

        def score(row: dict[str, str]) -> tuple[int, float]:
            reasons = set(row["weak_label_noise_reasons"].split("|"))
            terms = set(sum(json.loads(row["matched_issue_terms_json"]).values(), []))
            points = 0
            for reason in NOISE_REASONS:
                if reason in reasons and goals[f"reason:{reason}"] > 0:
                    points += 3000 if reason == "mixed_sentiment_keywords" else 150
            for signal in ISSUE_SIGNAL_TYPES:
                if int(row[f"issue_{signal}"]) and goals[f"signal:{signal}"] > 0:
                    points += 500 if signal in {"performance_crash", "usability_navigation"} else 100
            for term in BROAD_TERMS:
                if term in terms and goals[f"term:{term}"] > 0:
                    points += 500 if term == "version" else 100
            if app_counts[row["app_name"]] < 8:
                points += 10
            return points, -rank[row["review_id"]]

        best = max(candidates, key=score)
        selected.append(best)
        selected_ids.add(best["review_id"])
    def constraint_score(candidate_rows: list[dict[str, str]]) -> int:
        goals = _booster_goals(rows, candidate_rows)
        app_counts = Counter(row["app_name"] for row in candidate_rows)
        app_deficit = sum(
            max(0, 8 - app_counts[app])
            for app in {row["app_name"] for row in rows}
        )
        return sum(goals.values()) * 100 + app_deficit

    # Repair the greedy result with deterministic one-for-one swaps. This keeps
    # the primary core strata fixed while resolving a missed rare target.
    for _ in range(100):
        current_score = constraint_score(selected)
        if current_score == 0:
            break
        selected_booster = selected[CORE_SIZE:]
        selected_ids = {row["review_id"] for row in selected}
        candidates = [row for row in rows if row["review_id"] not in selected_ids]
        best_swap: tuple[int, str, dict[str, str], dict[str, str]] | None = None
        for old in selected_booster:
            for candidate in candidates:
                trial = [row for row in selected if row["review_id"] != old["review_id"]]
                trial.append(candidate)
                score_value = constraint_score(trial)
                if score_value < current_score:
                    key = (score_value, candidate["review_id"])
                    if best_swap is None or key < (best_swap[0], best_swap[1]):
                        best_swap = (score_value, candidate["review_id"], old, candidate)
        if best_swap is None:
            break
        _, _, old, candidate = best_swap
        selected[selected.index(old)] = candidate

    unmet = {key: value for key, value in _booster_goals(rows, selected).items() if value}
    if unmet:
        raise ValueError(f"Booster coverage targets are unmet: {unmet}")
    if any(Counter(r["app_name"] for r in selected)[app] < 8 for app in all_apps):
        raise ValueError("Total sample does not cover every App at least 8 times")
    return selected[CORE_SIZE:]


def _augment_rows(
    rows: list[dict[str, str]],
    *,
    keyword_signals: dict[str, list[str]],
    role: str,
    rank: dict[str, float],
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for row in rows:
        augmented = dict(row)
        matched = {
            signal: _matched_terms(_text(row), keyword_signals[signal])
            for signal in ISSUE_SIGNAL_TYPES
        }
        augmented["matched_issue_terms_json"] = json.dumps(
            matched, ensure_ascii=False, sort_keys=True
        )
        augmented["sample_role"] = role
        augmented["selection_rank"] = f"{rank[row['review_id']]:.12f}"
        output.append(augmented)
    return output


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a deterministic weak-label audit sample.")
    parser.add_argument("--input", default="data/processed/review_features_v1.csv")
    parser.add_argument("--keyword-config", default="config/issue_keywords_v1.yaml")
    parser.add_argument("--output-dir", default="data/processed/weak_label_audit_v1")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    input_path = _resolve(args.input)
    output_dir = _resolve(args.output_dir)
    rows, input_sha256 = _load_rows(input_path)
    keyword_version, keyword_signals = _load_issue_keywords(_resolve(args.keyword_config))
    rank = _stable_rank(rows, args.seed)
    augmented_rows = _augment_rows(rows, keyword_signals=keyword_signals, role="", rank=rank)
    core_ids = {row["review_id"] for row in _core_sample(augmented_rows, rank)}
    core = [row for row in augmented_rows if row["review_id"] in core_ids]
    booster = _booster_sample(augmented_rows, core, rank)
    sampled = _augment_rows(core, keyword_signals=keyword_signals, role="core", rank=rank)
    sampled.extend(_augment_rows(booster, keyword_signals=keyword_signals, role="booster", rank=rank))
    sampled.sort(key=lambda row: (row["sample_role"], rank[row["review_id"]]))
    for index, row in enumerate(sampled, start=1):
        row["sample_id"] = f"audit_v1_{index:03d}"

    manifest_columns = [
        "sample_id", "sample_role", "review_id", "source_review_id", "app_name",
        "vertical_name", "storefront", "rating", "title", "body", "detected_language",
        "published_at", "weak_label", "weak_label_needs_review", "weak_label_noise_reasons",
        *[f"issue_{signal}" for signal in ISSUE_SIGNAL_TYPES],
        "issue_signal_count", "matched_issue_terms_json", "selection_rank",
    ]
    annotation_columns = [
        "sample_id", "app_name", "vertical_name", "title", "body", "detected_language",
        "matched_issue_terms_json",
        "apparent_sentiment", "rating_label_agreement", "mixed_sentiment", "appears_english",
        "text_interpretable",
        *[f"issue_{signal}_relevance" for signal in ISSUE_SIGNAL_TYPES],
        "service_term_relevance", "account_term_relevance", "version_term_relevance",
        "annotation_notes",
        "rating", "weak_label", "weak_label_needs_review", "weak_label_noise_reasons",
        *[f"issue_{signal}" for signal in ISSUE_SIGNAL_TYPES],
    ]
    _write_csv(output_dir / "sample_manifest.csv", sampled, manifest_columns)
    _write_csv(
        output_dir / "annotation_template.csv",
        [
            {**{column: row.get(column, "") for column in annotation_columns}, "sample_id": row["sample_id"]}
            for row in sampled
        ],
        annotation_columns,
    )
    metadata = {
        "schema_version": "weak_label_audit_v1",
        "input_csv": str(input_path.relative_to(ROOT) if input_path.is_relative_to(ROOT) else input_path),
        "input_sha256": input_sha256,
        "keyword_version": keyword_version,
        "seed": args.seed,
        "core_size": len(core),
        "booster_size": len(booster),
        "total_size": len(sampled),
        "label_counts": dict(sorted(Counter(row["weak_label"] for row in sampled).items())),
        "flag_counts": dict(sorted(Counter(row["weak_label_needs_review"] for row in sampled).items())),
        "population_label_counts": dict(sorted(Counter(row["weak_label"] for row in augmented_rows).items())),
        "population_label_flag_counts": dict(sorted(Counter(
            f"{row['weak_label']}|{row['weak_label_needs_review']}" for row in augmented_rows
        ).items())),
        "app_counts": dict(sorted(Counter(row["app_name"] for row in sampled).items())),
        "vertical_counts": dict(sorted(Counter(row["vertical_name"] for row in sampled).items())),
        "noise_reason_counts": dict(sorted(Counter(
            reason
            for row in sampled
            for reason in filter(None, row["weak_label_noise_reasons"].split("|"))
        ).items())),
        "issue_signal_counts": {
            signal: sum(int(row[f"issue_{signal}"]) for row in sampled)
            for signal in ISSUE_SIGNAL_TYPES
        },
        "files": ["sample_manifest.csv", "annotation_template.csv"],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "sample_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
