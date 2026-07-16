# Architecture

## Component Boundaries

```text
apps.yaml
  -> config_loader
  -> ingestion_service
       -> apple_rss_client
       -> raw JSON file
       -> parser
       -> normalizer
       -> validator
       -> database
       -> quality_flags
  -> SQLite training view
  -> per-run JSON summary and validation report
  -> CSV exporter
```

- `config_loader.py`: validates YAML and returns typed app/settings objects.
- `apple_rss_client.py`: builds URLs, performs paced HTTP requests, logs timing, and retries transient failures.
- `parser.py`: reads Apple feed structure and returns only review-like entries.
- `normalizer.py`: minimally cleans text, converts numbers, normalizes timestamps to UTC, hashes source objects, and applies lightweight language detection.
- `validator.py`: classifies hard failures that cannot safely enter `reviews`.
- `quality_flags.py`: adds explainable heuristic warnings without deleting usable reviews or creating sentiment labels.
- `database.py`: initializes SQLite, seeds configuration, records runs/raw pages, and performs transactional review upserts.
- `ingestion_service.py`: coordinates the end-to-end workflow while isolating failures by app/page/review.
- `scripts/`: provides student-friendly CLI entry points.

## Run Lifecycle

1. Load and filter enabled applications.
2. Create an `ingestion_runs` row with `running` status.
3. Fetch one page with timeout, pacing, and bounded retry.
4. Write the exact JSON response to disk and `raw_feed_pages`.
5. Parse review entries; feed metadata is ignored.
6. Normalize and hard-validate each review.
7. Send invalid reviews to `rejected_review_records`.
8. Upsert valid reviewers/reviews and add heuristic quality flags.
9. Commit page processing and continue until no entries/no next link/max pages.
10. Update aggregate and per-app run counters and final status.
11. Write a summary artifact that preserves app-level outcomes and source-page observations.

## Failure Behavior

- One malformed review is rejected without aborting its page.
- A page-processing exception marks that raw page `parse_error` and keeps its source response.
- A failed endpoint stops that app but lets later apps continue.
- Fatal orchestration errors mark the run `failed`.
- Partial request failures produce `completed_with_errors`.

## Idempotency and Lineage

The database uniqueness key is `(source_platform, app_storefront_id, source_review_id)`. Upserts preserve first-seen run/page/timestamp and update last-seen run/page/timestamp. A composite foreign key enforces that `reviews.app_id` matches the app owned by `reviews.app_storefront_id`.

## Security and Scope

The system accesses public RSS/JSON only. It contains no credentials, browser automation, anti-bot bypass, proxy rotation, or access-control evasion. Reviewer metadata is limited to the public label and URI supplied in the feed.
