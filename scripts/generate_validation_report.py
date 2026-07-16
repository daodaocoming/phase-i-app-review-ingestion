from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.validation_reporting import build_validation_report, write_validation_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a repeated-run Phase I validation report.")
    parser.add_argument("--db-path", default="database/validation_scale.db")
    parser.add_argument("--run-id", action="append", type=int, required=True, help="Run ID to include; repeatable.")
    parser.add_argument("--output", default="outputs/validation/controlled_scale_validation.md")
    parser.add_argument("--json-output", help="Optional path for the machine-readable report.")
    args = parser.parse_args()

    db_path = ROOT / args.db_path
    report = write_validation_report(db_path, args.run_id, ROOT / args.output)
    if args.json_output:
        json_path = ROOT / args.json_output
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": args.output,
        "json_output": args.json_output,
        "run_ids": args.run_id,
        "ready_for_ds": report["ready_for_ds"],
    }, indent=2))


if __name__ == "__main__":
    main()
