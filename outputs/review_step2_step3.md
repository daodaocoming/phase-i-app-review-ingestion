# Review of Step 2 and Step 3

## Review Summary

Step 2 and Step 3 now form a complete Phase I ingestion-and-storage design for the Apple App Store public customer-review RSS prototype.

The two steps are aligned around the same operating assumptions:

- one source: Apple App Store customer-review RSS/JSON
- small prototype cohort: 30 to 50 apps across multiple commercial verticals
- initial storefront: United States
- English-first review filtering
- recent-review ingestion rather than full historical backfill
- raw payload retention plus normalized relational storage
- idempotent ingestion using source-level uniqueness
- SQLite for local prototype, PostgreSQL-compatible logical model for later deployment

## Step 2 Completion Review

Step 2 is complete for the automated ingestion process.

It covers:

- source selection and endpoint format
- prototype scope
- fetch loop and pagination behavior
- retry, timeout, pacing, and structured logging expectations
- parser and normalization responsibilities
- deduplication and idempotent upsert behavior
- raw and normalized storage handoff
- operational run summary
- compliance and safety boundaries
- feasibility test
- risks and mitigations

Improvement made during review:

- The storage handoff was updated to match the Step 3 schema more precisely.
- `verticals`, `app_storefronts`, and `reviewers` were added to the Step 2 handoff contract.
- The review upsert key was clarified as `(source_platform, app_storefront_id, source_review_id)`, which is more robust than using only app id and review id because it preserves storefront-level source context.

Remaining caveat:

- The RSS source should still be treated as a prototype source pending legal/policy review and ongoing endpoint stability checks.

## Step 3 Completion Review

Step 3 is complete for the database layer.

It covers:

- SQLite prototype choice and PostgreSQL migration path
- relational schema design
- product-like app entities, public reviewer entities, review records, raw pages, ingestion runs, and quality flags
- normalization and performance tradeoffs
- uniqueness constraints and idempotent upsert strategy
- indexes for analytics
- common SQL query patterns
- downstream labeling, analytics, and model-training consumption
- privacy and governance expectations
- implementation verification

Implementation delivered:

- `outputs/phase_i_database_schema.sql`
- `outputs/step3_database_layer.md`

The SQL schema was later improved during Step 4 review to track rejected records. It now loads successfully into SQLite and creates:

- 9 tables
- 1 analytical view

## Completeness Against Project Brief

| Requirement | Status | Notes |
| --- | --- | --- |
| Relational schema reflecting products, reviews, users | Complete | Modeled as `apps`, `reviews`, and `reviewers`, with `verticals`, `app_storefronts`, and rejected-record tracking for source context |
| Balance normalization and performance | Complete | Moderate normalization plus indexes and a flat training view |
| SQL analytics compatibility | Complete | Includes common SQL query patterns and `training_review_dataset` view |
| Model training integration | Complete | Stable review ids, text, ratings, app, vertical, language, timestamps, and quality flags are available |
| SQLite vs PostgreSQL choice | Complete | SQLite recommended for Phase I; PostgreSQL migration path documented |
| Persistent storage of raw and structured data | Complete | `raw_feed_pages` plus `reviews` |
| Repeatable ingestion support | Complete | `ingestion_runs`, source uniqueness constraints, first/last seen fields |

## Recommended Next Improvements

The next useful improvements would belong to implementation planning rather than Step 2 or Step 3 rewriting:

- add a sample `config/apps.yaml` cohort file
- build a small ingestion proof of concept against 3 apps
- insert the feasibility-test output into the database
- export a sample CSV from `training_review_dataset`
- add a short README that explains how to initialize the SQLite database and run the ingestion test

No further changes are required for Step 2 and Step 3 as project-brief deliverables.
