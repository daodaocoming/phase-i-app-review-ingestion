from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config_loader import load_config
from src.database import Database


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize and seed the Phase I SQLite database.")
    parser.add_argument("--db-path", default="database/app_reviews.db")
    parser.add_argument("--config-path", default="config/apps.yaml")
    parser.add_argument("--schema-path", default="database/phase_i_database_schema.sql")
    args = parser.parse_args()

    config = load_config(ROOT / args.config_path)
    with Database(ROOT / args.db_path) as database:
        database.initialize(ROOT / args.schema_path)
        summary = database.seed_config(config)
    print(
        f"Initialized {args.db_path}: {summary['verticals']} verticals, "
        f"{summary['apps']} apps, {summary['storefronts']} storefronts."
    )


if __name__ == "__main__":
    main()
