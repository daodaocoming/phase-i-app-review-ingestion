# Phase I Apple App Store Review Ingestion

This repository contains a runnable Phase I prototype for collecting recent public Apple App Store customer reviews, preserving raw responses, cleaning and validating review records, and loading an analytics-ready SQLite dataset.

It is intentionally a low-frequency public-data prototype. It does not use login automation, browser automation, CAPTCHA bypassing, proxies, account creation, or access-control evasion.

## Architecture

```text
config/apps.yaml
       |
       v
Apple RSS client -- retries / pacing / structured logs
       |
       +--> data/raw/*.json
       +--> raw_feed_pages
       |
       v
parser -> normalizer -> hard validator
                         |          |
                         |          +--> rejected_review_records
                         v
                  SQLite upsert -> reviews
                         |
                         +--> review_quality_flags
                         +--> training_review_dataset view
                                      |
                                      v
                         data/processed/training_reviews.csv
```

See [docs/architecture.md](docs/architecture.md) for component responsibilities.

## Setup

Python 3.11 or newer is required. A virtual environment is recommended because some system Python installations block global package installs.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The same install command was verified with Python 3.13.5 on July 5, 2026.

## Initialize SQLite

```bash
python scripts/init_db.py
```

This creates `database/app_reviews.db`, applies `database/phase_i_database_schema.sql`, and seeds verticals, apps, and storefronts from `config/apps.yaml`.

Use another database when needed:

```bash
python scripts/init_db.py --db-path database/demo.db
```

## Run Live Ingestion

Run the three-app prototype cohort with at most two pages per app:

```bash
python scripts/run_ingestion.py --max-pages 2
```

Useful filters and options:

```bash
python scripts/run_ingestion.py --app-id 570060128 --max-pages 1
python scripts/run_ingestion.py --storefront us --max-pages 1
python scripts/run_ingestion.py --dry-run --max-pages 1
python scripts/run_ingestion.py --db-path database/demo.db --log-level DEBUG
```

`--dry-run` fetches and parses but does not write raw files or SQLite records. Normal runs print apps attempted, pages fetched, raw pages saved, reviews parsed, inserted, updated, rejected, flags created, and failed requests.

## Inspect the Database

```bash
python scripts/inspect_database.py
```

The command displays table counts, reviews by app and vertical, the latest run summary, and a small review sample.

SQLite can also be queried directly:

```bash
sqlite3 database/app_reviews.db < outputs/data_health_queries.sql
```

## Export the Downstream Dataset

```bash
python scripts/export_training_dataset.py \
  --output data/processed/training_reviews.csv
```

For the heuristic English subset without error-severity flags:

```bash
python scripts/export_training_dataset.py \
  --english-only \
  --output data/processed/training_reviews_en.csv
```

## Run Tests

Tests use a local Apple-shaped JSON fixture and do not require network access.

```bash
python -m pytest -q
```

The suite covers metadata filtering, parsing, rating/timestamp normalization, hard rejection, quality flags, raw-page linkage, and idempotent upserts.

## Idempotency

Reviews are unique by:

```text
(source_platform, app_storefront_id, source_review_id)
```

Seeing the same review again updates mutable fields and `last_seen_*` lineage instead of creating a duplicate. New raw pages and ingestion runs are still retained because each fetch is a distinct observation. A changing RSS window can legitimately introduce previously unseen source review IDs on a later run.

## Raw Data Traceability

Every successful page is:

1. Written to `data/raw/` with app id, storefront, page, and a UTC retrieval timestamp.
2. Hashed with SHA-256.
3. Inserted into `raw_feed_pages` with URL, HTTP status, response body, file path, ingestion run, and parse status.
4. Linked to reviews through first/last raw page ids and first/last ingestion run ids.

Raw files are never intentionally overwritten.

## Validation and Quality Flags

Hard failures are stored in `rejected_review_records` and do not stop the whole run. Examples are missing review ID, invalid rating, empty body, or unparseable timestamp.

Soft flags preserve usable reviews while making concerns queryable:

| Flag | Meaning |
| --- | --- |
| `non_english_or_unknown_language` | Lightweight language heuristic did not confidently identify English |
| `too_short_review` | Body contains fewer than 12 characters |
| `duplicate_text_within_app` | Another source review id in the app/storefront has the same normalized body |
| `rating_text_mismatch` | Strong positive/negative keywords conflict with a low/high rating |
| `missing_author_metadata` | Both public author label and URI are absent |
| `parser_fallback_used` | Feed supplied a single entry object instead of the usual list |

These are transparent heuristics, not final classifiers.

## Add Another App

Add an item under `apps` in `config/apps.yaml` with all required fields:

```yaml
- app_id: "REAL_NUMERIC_APP_ID"
  app_name: Example App
  vertical: Retail
  storefront: us
  expected_language: en
  enabled: true
  notes: Reason for including the app.
```

Run `python scripts/init_db.py` again. Seeding is an upsert, so existing reviews are preserved.

## Apple RSS Limitations and Compliance

The customer-review RSS/JSON feed is a legacy public endpoint, not a guaranteed modern production API. It exposes a recent review window rather than a complete historical archive, and the returned window can shift between requests. Response shape or availability may change without notice.

The client uses a descriptive user agent, a one-second default delay, a 15-second timeout, at most three retries with exponential backoff, and a hard maximum of ten pages per app. Only network/transient errors, HTTP 429, and selected 5xx errors are retried.

Review current Apple terms and organizational policy before production use. The modern App Store Connect API is for app-owner/developer access and is not a replacement for arbitrary third-party public reviews.

## PostgreSQL Migration Path

The logical model is portable. A later deployment should convert ISO timestamp text to `TIMESTAMPTZ`, JSON text to `JSONB`, integer booleans to `BOOLEAN`, and SQLite upserts to equivalent PostgreSQL `ON CONFLICT` statements. The service layer is separated from SQL persistence so a PostgreSQL repository implementation can replace `src/database.py` without rewriting parsing and validation.

## Verified Prototype Result

On July 5, 2026, two network-enabled runs fetched two pages each for Facebook, Uber, and Duolingo. The database contains 12 raw pages, 400 unique reviews, and 52 quality flags. The training CSV export contains 400 rows. See [docs/feasibility_report.md](docs/feasibility_report.md) for exact run details and observed source inconsistency.
