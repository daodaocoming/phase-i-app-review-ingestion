from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.parser import extract_review_entries


def _json_or_default(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _raw_observations(connection: sqlite3.Connection, run_ids: list[int]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in run_ids)
    rows = connection.execute(
        f"""
        SELECT p.ingestion_run_id, p.raw_feed_page_id, p.app_storefront_id, p.page_number,
               p.response_hash, p.parse_status, p.response_body,
               a.app_name, a.source_app_id, s.storefront
        FROM raw_feed_pages p
        JOIN app_storefronts s ON s.app_storefront_id = p.app_storefront_id
        JOIN apps a ON a.app_id = s.app_id
        WHERE p.ingestion_run_id IN ({placeholders})
        ORDER BY p.ingestion_run_id, a.app_name, p.page_number
        """,
        run_ids,
    ).fetchall()
    observations: list[dict[str, Any]] = []
    for row in rows:
        review_ids: list[str] = []
        parse_error: str | None = None
        try:
            payload = json.loads(row["response_body"])
            review_ids = [entry.source_review_id for entry in extract_review_entries(payload) if entry.source_review_id]
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            parse_error = str(exc)
        observations.append(
            {
                "run_id": row["ingestion_run_id"],
                "raw_page_id": row["raw_feed_page_id"],
                "app_storefront_id": row["app_storefront_id"],
                "app_name": row["app_name"],
                "source_app_id": row["source_app_id"],
                "storefront": row["storefront"],
                "page_number": row["page_number"],
                "response_hash": row["response_hash"],
                "parse_status": row["parse_status"],
                "entry_count": len(review_ids),
                "review_ids": review_ids,
                "parse_error": parse_error,
            }
        )
    return observations


def build_run_summary(db_path: str | Path, run_id: int) -> dict[str, Any]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        run = connection.execute(
            "SELECT * FROM ingestion_runs WHERE ingestion_run_id=?", (run_id,)
        ).fetchone()
        if run is None:
            raise ValueError(f"Ingestion run not found: {run_id}")

        app_rows = connection.execute(
            """
            SELECT x.*, a.app_name, a.source_app_id, v.vertical_name, s.storefront
            FROM ingestion_run_app_stats x
            JOIN apps a ON a.app_id=x.app_id
            JOIN verticals v ON v.vertical_id=a.vertical_id
            JOIN app_storefronts s ON s.app_storefront_id=x.app_storefront_id
            WHERE x.ingestion_run_id=?
            ORDER BY a.app_name
            """,
            (run_id,),
        ).fetchall()
        observations = _raw_observations(connection, [run_id])
        pages_by_app: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for observation in observations:
            page = dict(observation)
            page.pop("review_ids", None)
            pages_by_app[observation["app_name"]].append(page)

        apps: list[dict[str, Any]] = []
        for row in app_rows:
            item = dict(row)
            item["flag_counts"] = _json_or_default(item.get("flag_counts"), {})
            item["errors"] = _json_or_default(item.pop("error_summary", None), [])
            item["pages"] = pages_by_app.get(item["app_name"], [])
            apps.append(item)

        return {
            "run_id": run_id,
            "status": run["run_status"],
            "started_at": run["started_at"],
            "completed_at": run["completed_at"],
            "config": _json_or_default(run["config_snapshot"], {}),
            "stats": {
                "apps_attempted": run["apps_requested"],
                "pages_fetched": run["pages_fetched"],
                "reviews_parsed": run["reviews_parsed"],
                "reviews_inserted": run["reviews_inserted"],
                "reviews_updated": run["reviews_updated"],
                "reviews_rejected": run["reviews_rejected"],
                "flags_created": run["flags_created"],
                "failed_requests": run["failed_requests"],
                "flags_by_type": _json_or_default(run["flag_counts"], {}),
                "errors": _json_or_default(run["error_summary"], []),
            },
            "apps": apps,
        }
    finally:
        connection.close()


def write_run_summary(db_path: str | Path, run_id: int, output_path: str | Path) -> dict[str, Any]:
    summary = build_run_summary(db_path, run_id)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def _window_changes(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        grouped[
            (
                observation["app_storefront_id"],
                observation["page_number"],
                observation["run_id"],
            )
        ].append(observation)

    by_page: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for (app_storefront_id, page_number, _), items in grouped.items():
        by_page[(app_storefront_id, page_number)].extend(items)

    changes: list[dict[str, Any]] = []
    for (app_storefront_id, page_number), items in by_page.items():
        if len(items) < 2:
            continue
        # The raw page body is the source of truth; compare both its hash and
        # parsed review IDs across repeated runs.
        hashes = {item["response_hash"] for item in items}
        review_sets = {tuple(sorted(item["review_ids"])) for item in items}
        if len(hashes) > 1 or len(review_sets) > 1:
            changes.append(
                {
                    "app_name": items[0]["app_name"],
                    "app_storefront_id": app_storefront_id,
                    "page_number": page_number,
                    "runs": sorted(item["run_id"] for item in items),
                    "response_hash_changed": len(hashes) > 1,
                    "review_window_changed": len(review_sets) > 1,
                    "entry_counts": {str(item["run_id"]): item["entry_count"] for item in items},
                }
            )
    return sorted(changes, key=lambda item: (item["app_name"], item["page_number"]))


def build_validation_report(db_path: str | Path, run_ids: list[int]) -> dict[str, Any]:
    if not run_ids:
        raise ValueError("At least one run ID is required")
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        summaries = [build_run_summary(db_path, run_id) for run_id in run_ids]
        observations = _raw_observations(connection, run_ids)
        final = connection.execute(
            """
            SELECT
                COUNT(*) AS total_reviews,
                COUNT(DISTINCT source_platform || '|' || app_storefront_id || '|' || source_review_id) AS unique_source_keys,
                SUM(CASE WHEN source_review_id IS NULL OR rating IS NULL OR body IS NULL OR length(trim(body))=0 OR published_at IS NULL THEN 1 ELSE 0 END) AS invalid_required,
                COUNT(DISTINCT app_id) AS apps_represented
            FROM reviews
            """
        ).fetchone()
        clean = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM training_review_dataset
            WHERE detected_language='en' AND has_error_flag=0
            """
        ).fetchone()["count"]
        vertical_count = connection.execute(
            """SELECT COUNT(DISTINCT v.vertical_id)
               FROM reviews r JOIN apps a ON a.app_id=r.app_id
               JOIN verticals v ON v.vertical_id=a.vertical_id"""
        ).fetchone()[0]
        flag_counts: dict[str, int] = defaultdict(int)
        for summary in summaries:
            for flag_type, count in summary["stats"]["flags_by_type"].items():
                flag_counts[flag_type] += int(count)
        expected_apps = max((summary["stats"]["apps_attempted"] for summary in summaries), default=0)
        gates = {
            "all_configured_apps_represented": final["apps_represented"] >= expected_apps,
            "at_least_six_verticals": vertical_count >= 6,
            "at_least_1000_unique_reviews": final["unique_source_keys"] >= 1000,
            "no_duplicate_source_keys": final["total_reviews"] == final["unique_source_keys"],
            "no_invalid_required_fields": (final["invalid_required"] or 0) == 0,
            "final_run_has_no_app_or_request_failures": summaries[-1]["status"] == "completed"
            and summaries[-1]["stats"]["failed_requests"] == 0,
        }
        return {
            "db_path": str(db_path),
            "run_ids": run_ids,
            "runs": summaries,
            "window_changes": _window_changes(observations),
            "duplicate_behavior": {
                "canonical_reviews": final["total_reviews"],
                "unique_source_keys": final["unique_source_keys"],
                "repeated_observation_updates": sum(
                    summary["stats"]["reviews_updated"] for summary in summaries
                ),
            },
            "quality_flags_by_type": dict(sorted(flag_counts.items())),
            "export": {
                "all_rows": final["total_reviews"],
                "english_without_error_rows": clean,
                "apps_represented": final["apps_represented"],
                "verticals_represented": vertical_count,
                "invalid_required_fields": final["invalid_required"] or 0,
            },
            "acceptance_gates": gates,
            "ready_for_ds": all(gates.values()),
        }
    finally:
        connection.close()


def write_validation_report(db_path: str | Path, run_ids: list[int], output_path: str | Path) -> dict[str, Any]:
    report = build_validation_report(db_path, run_ids)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_validation_markdown(report), encoding="utf-8")
    return report


def render_validation_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Controlled Scale-Up Validation Report",
        "",
        f"- Database: `{report['db_path']}`",
        f"- Runs: {', '.join(str(run_id) for run_id in report['run_ids'])}",
        f"- DS readiness decision: **{'ready' if report['ready_for_ds'] else 'not ready'}**",
        "",
        "## Run summaries",
        "",
        "| Run | Status | Apps | Pages | Parsed | Inserted | Updated | Rejected | Flags | Failed requests |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for summary in report["runs"]:
        stats = summary["stats"]
        lines.append(
            f"| {summary['run_id']} | {summary['status']} | {stats['apps_attempted']} | "
            f"{stats['pages_fetched']} | {stats['reviews_parsed']} | {stats['reviews_inserted']} | "
            f"{stats['reviews_updated']} | {stats['reviews_rejected']} | {stats['flags_created']} | "
            f"{stats['failed_requests']} |"
        )

    final_run = report["runs"][-1]
    lines.extend([
        "",
        "## App-level outcomes in final run",
        "",
        "| App | Vertical | Status | Pages | Parsed | Inserted | Updated | Rejected | Flags | Failures |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for app in final_run["apps"]:
        lines.append(
            f"| {app['app_name']} | {app['vertical_name']} | {app['run_status']} | "
            f"{app['pages_fetched']} | {app['reviews_parsed']} | {app['reviews_inserted']} | "
            f"{app['reviews_updated']} | {app['reviews_rejected']} | {app['flags_created']} | "
            f"{app['failed_requests']} |"
        )

    lines.extend([
        "",
        "## Final dataset",
        "",
        "| Measure | Value |",
        "| --- | ---: |",
        f"| Canonical reviews | {report['export']['all_rows']} |",
        f"| English, no-error export rows | {report['export']['english_without_error_rows']} |",
        f"| Apps represented | {report['export']['apps_represented']} |",
        f"| Verticals represented | {report['export']['verticals_represented']} |",
        f"| Invalid required fields | {report['export']['invalid_required_fields']} |",
        "",
        "## Quality flags",
        "",
        "Quality flags are transparent heuristics for review and filtering. They are not sentiment labels or ground-truth annotations.",
        "",
        "| Flag type | Observed count |",
        "| --- | ---: |",
    ])
    for flag_type, count in report["quality_flags_by_type"].items():
        lines.append(f"| `{flag_type}` | {count} |")

    lines.extend(["", "## Repeated-review and source-window behavior", ""])
    duplicate = report["duplicate_behavior"]
    lines.extend([
        f"- Canonical rows: {duplicate['canonical_reviews']}",
        f"- Unique composite source keys: {duplicate['unique_source_keys']}",
        f"- Repeated observations recorded as updates: {duplicate['repeated_observation_updates']}",
        "",
    ])
    if report["window_changes"]:
        lines.append("Changed source pages detected:")
        lines.append("")
        lines.append("| App | Page | Runs | Response hash changed | Review window changed |")
        lines.append("| --- | ---: | --- | --- | --- |")
        for change in report["window_changes"]:
            lines.append(
                f"| {change['app_name']} | {change['page_number']} | {', '.join(map(str, change['runs']))} | "
                f"{change['response_hash_changed']} | {change['review_window_changed']} |"
            )
    else:
        lines.append("No changed source page or review window was detected across the selected runs.")

    lines.extend(["", "## Acceptance gates", "", "| Gate | Result |", "| --- | --- |"])
    for gate, passed in report["acceptance_gates"].items():
        lines.append(f"| `{gate}` | {'PASS' if passed else 'FAIL'} |")
    lines.append("")
    return "\n".join(lines)
