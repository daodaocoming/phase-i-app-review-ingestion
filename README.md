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

For the Feature Engineering and Weak Labeling v1 notebook, install the
separate DS dependencies:

```bash
python -m pip install -r requirements-ds.txt
```

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

Run the controlled 12-app validation cohort with at most two pages per app:

```bash
python scripts/run_ingestion.py --max-pages 2
```

For controlled scale-up validation, use one database across repeated runs:

```bash
python scripts/init_db.py --db-path database/validation_scale.db
python scripts/run_ingestion.py \
  --db-path database/validation_scale.db \
  --raw-dir data/raw/validation_scale \
  --max-pages 2
python scripts/generate_validation_report.py \
  --db-path database/validation_scale.db \
  --run-id 1 --run-id 2 --run-id 3 \
  --output outputs/validation/controlled_scale_validation.md
```

Each non-dry run writes a machine-readable summary under
`outputs/validation/run_summaries/` unless `--summary-output` is supplied.

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

## Build the Feature and Weak-Label Dataset

The v1 DS layer maps ratings 1-2 to `negative`, 3 to `neutral`, and 4-5 to
`positive`. It adds transparent text, time, quality-flag, and issue-keyword
features while keeping possible label noise separately reviewable.

```bash
python scripts/build_ds_dataset.py \
  --db-path database/validation_scale.db \
  --output data/processed/review_features_v1.csv \
  --summary-output outputs/ds_v1/feature_summary.json
```

Then open and run `notebooks/weak_label_baseline_v1.ipynb` from the repository
root. The notebook performs descriptive analysis only. Because the weak label
is derived directly from the rating, rating must not be used as a predictor in
later models.

See [docs/weak_labeling_strategy_v1.md](docs/weak_labeling_strategy_v1.md) for
the label rules, feature definitions, noise limitations, and recommended manual
evaluation.

## Run the Weak-Label Quality Audit

Create the reproducible 150-review audit sample and annotation template:

```bash
python scripts/create_weak_label_audit.py \
  --input data/processed/review_features_v1.csv \
  --seed 20260730
```

Fill `data/processed/weak_label_audit_v1/annotation_template.csv` and save it
as `annotations.csv`. The analyzer validates the controlled values and writes
the report only after all 150 rows are annotated:

```bash
python scripts/analyze_weak_label_audit.py \
  --annotations data/processed/weak_label_audit_v1/annotations.csv
```

The audit files remain separate from `review_features_v1.csv`; the 150 audited
review IDs must be held out from model training and the primary weak-label
split. Clear positive/negative audited rows may be used only as a secondary
human-reviewed diagnostic set; mixed and unclear rows remain outside binary
evaluation.

## Run the Filtered Binary Baseline

The baseline uses the audited-v1 feature export as an immutable input, applies
the versioned `issue_keywords_v2.yaml` rules, and excludes the audit IDs before
filtering to English, non-short, unflagged negative and positive reviews:

```bash
python scripts/run_binary_sentiment_baseline.py
```

The command writes Markdown/JSON analysis and prediction artifacts under
`outputs/ds_v1/`. It compares TF-IDF alone with TF-IDF plus the provisional v2
issue signals, uses class-weighted logistic regression, keeps normalized-text
duplicates in one split, and reports both a weak-label holdout and the
secondary human-reviewed diagnostic.

## Run the Cross-App Generalization Evaluation

The follow-up evaluation keeps the v1 baseline and audit artifacts frozen and
tests transfer to an unseen product. It runs leave-one-App-out across all 12
Apps: each fold fits the TF-IDF-only, class-weighted logistic-regression model
on the other 11 Apps and evaluates once on the held-out App. Issue signals are
retained as error-analysis metadata, but are not predictors in this experiment.
The 99 clear human-reviewed rows are not used for fitting, selection, or
benchmarking.

```bash
python scripts/run_cross_app_generalization.py
```

The command writes `cross_app_generalization_report.md/.json`, per-review
predictions, a sampled weakest-App error review, and an English mentor update
under `outputs/ds_v1/`. The report includes class distributions, Macro F1 and
balanced accuracy by held-out App, pooled and App-level summaries, frozen-file
hashes, and deterministic diagnostic tags for short, mixed, OOV, comparative,
or potentially ambiguous examples. The public report contains aggregate and
tag-level diagnostics only; per-review predictions, excerpts, and the mentor
email draft are local-only artifacts.

## Train the Final Frozen Model

The final model is deliberately the existing TF-IDF-only baseline. It is fit
once on the full filtered binary cohort (1,002 rows: 575 negative and 427
positive) after all audit, language, short-text, and weak-label quality
exclusions. It does not use App, rating, quality flags, issue signals, or
manual-review labels as predictors.

For the original source export, audit files, and full provenance checks, run:

```bash
python scripts/train_final_sentiment_model.py
```

The command writes the canonical artifacts under `artifacts/`:

```text
artifacts/final_tfidf_sentiment_pipeline.joblib
artifacts/final_tfidf_sentiment_pipeline.metadata.json
artifacts/final_training_dataset.csv
```

The final cohort can be distributed through controlled storage when exact
retraining is required. Because it contains source review text, it is ignored
by Git and should not be committed to a public repository. From a fresh clone,
place the approved cohort at the documented path before running:

```bash
python scripts/train_final_sentiment_model.py \
  --filtered-input artifacts/final_training_dataset.csv
```

The metadata records the input, training cohort, audit separation, dependency
versions, model parameters, and SHA-256 hashes. The frozen evaluation metrics
remain the metrics in `outputs/ds_v1/binary_sentiment_baseline_report.md` and
`outputs/ds_v1/cross_app_generalization_report.md`; the full-cohort fit is not
treated as a new test result.

## Run Inference

The persisted Pipeline contains normalization, TF-IDF, and classification, so
inference applies the same transformations as training:

```bash
python scripts/predict_sentiment.py \
  --text "The latest update is excellent and easy to use."
```

For a CSV with a `review_text` column:

```bash
python scripts/predict_sentiment.py \
  --input-csv new_reviews.csv \
  --text-column review_text \
  --output-csv predictions.csv
```

See [MODEL_CARD.md](MODEL_CARD.md) for the label contract, limitations, and
appropriate uses. See [FINAL_REPORT.md](FINAL_REPORT.md) for the complete
project story and conclusions.

## Recommended End-to-End Order

For a new data build, the intended order is:

```text
ingestion -> export -> feature engineering -> weak-label audit
-> filtered baseline -> cross-App validation -> final full-cohort fit
-> inference -> tests
```

The baseline and cross-App reports are frozen evidence. Do not use the
human-reviewed examples for model selection or tuning, and do not replace the
TF-IDF-only final model with a more complex experiment as part of this handoff.

## Reproducibility and Data Handling

Raw pages, SQLite databases, generated CSVs, and manual audit working files are
ignored because they may contain local or source-derived data. The generated
`artifacts/final_training_dataset.csv` is the minimal handoff dataset needed to
reproduce the final fit, but it is intentionally excluded from a public GitHub
commit because it contains review text. If the cohort is distributed through
controlled storage, use the SHA-256 in the model metadata and place it at the
documented path before training.

Before handoff, check for credentials and local artifacts, then confirm:

```bash
git status --short
python -m pytest -q
```

The only canonical final model is
`artifacts/final_tfidf_sentiment_pipeline.joblib`; prior reports remain as
historical, frozen evaluation evidence rather than competing final models.

## Run Tests

Tests use a local Apple-shaped JSON fixture and do not require network access.

```bash
python -m pytest -q
```

The suite covers metadata filtering, parsing, rating/timestamp normalization, hard rejection, heuristic quality flags, raw-page linkage, per-app run accounting, privacy-safe exports, and idempotent upserts.

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

These are transparent heuristics for quality review and filtering, not sentiment labels, ground-truth annotations, or final classifiers.

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

The controlled validation cohort contains 12 enabled apps across multiple verticals.
Keep this manifest stable while comparing repeated runs.

## Apple RSS Limitations and Compliance

The customer-review RSS/JSON feed is a legacy public endpoint, not a guaranteed modern production API. It exposes a recent review window rather than a complete historical archive, and the returned window can shift between requests. Response shape or availability may change without notice.

The client uses a descriptive user agent, a one-second default delay, a 15-second timeout, at most three retries with exponential backoff, and a hard maximum of ten pages per app. Only network/transient errors, HTTP 429, and selected 5xx errors are retried.

Review current Apple terms and organizational policy before production use. The modern App Store Connect API is for app-owner/developer access and is not a replacement for arbitrary third-party public reviews.

## PostgreSQL Migration Path

The logical model is portable. A later deployment should convert ISO timestamp text to `TIMESTAMPTZ`, JSON text to `JSONB`, integer booleans to `BOOLEAN`, and SQLite upserts to equivalent PostgreSQL `ON CONFLICT` statements. The service layer is separated from SQL persistence so a PostgreSQL repository implementation can replace `src/database.py` without rewriting parsing and validation.

## Verified Prototype Result

The early July 5, 2026 feasibility run covered Facebook, Uber, and Duolingo;
those results remain documented in
[docs/feasibility_report.md](docs/feasibility_report.md).

The current controlled validation uses the exact 12-App cohort committed in
`config/apps.yaml`, with two pages per App and three repeated runs against the
same database. It produced 1,300 canonical reviews across 12 Apps and 11
verticals. The machine-readable run summaries preserve the full config snapshot
used by each run. See
[outputs/validation/controlled_scale_validation.md](outputs/validation/controlled_scale_validation.md)
for the current acceptance results and observed source-window changes.
