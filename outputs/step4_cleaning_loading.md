# Step 4: Automating Data Cleaning and Loading

## Objective

After reviews are retrieved from the Apple App Store RSS/JSON feed, the pipeline must convert raw source objects into trustworthy database records. This step is responsible for validating, cleaning, normalizing, loading, and verifying the data in a consistent and repeatable way.

The goal is not to make the text artificially neat. The goal is to preserve the user's original meaning while making the surrounding structure reliable enough for SQL analytics, labeling, and model training.

## Cleaning and Loading Workflow

The automated workflow should run in this order:

1. Create an `ingestion_runs` record with status `running`.
2. Fetch and store each RSS/JSON page in `raw_feed_pages`.
3. Parse each raw page into individual source review objects.
4. Validate required fields.
5. Normalize fields into the internal review shape.
6. Upsert valid records into `reviewers` and `reviews`.
7. Write soft quality issues to `review_quality_flags`.
8. Write hard failures to `rejected_review_records`.
9. Update run-level counts in `ingestion_runs`.
10. Run verification queries and mark the run `completed`, `completed_with_errors`, or `failed`.

This makes the process repeatable: the same source input and cleaning rules should produce the same normalized records and the same quality flags.

## Validation Rules

Validation is split into hard failures and soft warnings.

### Hard Failures

Hard failures prevent a record from being loaded into `reviews`. These records should be written to `rejected_review_records`.

| Condition | Reason |
| --- | --- |
| Missing review id | Cannot deduplicate or trace the record |
| Missing rating | Cannot use the review for rating-aware sentiment analysis |
| Rating is not an integer from 1 to 5 | Invalid categorical signal |
| Missing or empty body after trimming | No usable review text |
| Timestamp cannot be parsed | Cannot place feedback on a timeline |
| Review object is malformed | Cannot safely map source fields |

### Soft Warnings

Soft warnings allow the record to be inserted into `reviews`, but add one or more rows to `review_quality_flags`.

| Condition | Suggested flag |
| --- | --- |
| Detected language is not English | `non_english` |
| Very short review body | `short_body` |
| Missing author label or URI | `missing_author_metadata` |
| Same body appears many times | `duplicate_text` |
| Rating and text appear semantically inconsistent | `rating_text_mismatch` |
| Suspicious spam-like text | `possible_spam` |
| Parser had to apply fallback logic | `parse_warning` |

This separation matters because unusual records can still be valuable. A short angry review, a non-English review, or a rating/text mismatch might teach the model something, but downstream users should be able to filter or inspect it.

## Field Normalization

### Review ID

Convert the feed review id to a string and preserve it as `source_review_id`.

Do not generate a replacement id for missing source ids. Missing source ids are hard failures because deduplication depends on them.

### Rating

Convert the feed rating to an integer and enforce:

```text
1 <= rating <= 5
```

Ratings should be treated as categorical ordinal values, not as continuous sentiment scores. A 5-star review is more positive than a 4-star review, but the distance between 1 and 2 is not guaranteed to mean the same thing as the distance between 4 and 5.

### Text Fields

For `title` and `body`:

- trim leading and trailing whitespace
- normalize repeated line breaks
- preserve emojis
- preserve original casing
- preserve punctuation
- store empty titles as null if needed
- reject empty bodies

The pipeline should avoid lowercasing, stemming, removing punctuation, or stripping emojis at load time. Those are modeling choices, not ingestion choices.

### Timestamp

Parse the feed's `updated` timestamp and store it as UTC in `published_at`.

If using SQLite, store the normalized timestamp as ISO 8601 text. If using PostgreSQL later, store it as `TIMESTAMPTZ`.

### Reviewer Metadata

Use public feed fields only:

- `author_label`
- `author_uri`

Create a deterministic `author_fingerprint` from source platform plus author URI when available, otherwise source platform plus author label. This allows grouping repeated public author metadata without trying to identify the real person.

### Language

Detect language after text normalization and store it in `detected_language`.

For Phase I, English records should be preferred for the default training view, but non-English records should generally be flagged rather than deleted.

### Hashes

Compute hashes for:

- raw feed pages as `response_hash`
- raw review objects as `raw_payload_hash`
- rejected review objects as `raw_payload_hash`

Hashes help detect whether the source changed and help debug repeated runs.

## Loading Strategy

The loader should use database transactions. A practical unit of work is one raw feed page:

1. Insert or confirm the app and app/storefront metadata.
2. Insert the raw page.
3. Parse review objects from that page.
4. For each review object, validate and normalize fields.
5. Insert or update the reviewer.
6. Insert or update the review using:

```text
(source_platform, app_storefront_id, source_review_id)
```

7. Insert quality flags for loaded records when needed.
8. Insert rejected records for hard failures.
9. Commit the page transaction.

If a page-level parse fails, the pipeline should keep the raw page, set `parse_status = 'parse_error'`, increment the run error summary, and continue to the next app/page when possible.

## Upsert Behavior

When a review is seen for the first time:

- insert the normalized review
- set `first_seen_run_id`
- set `last_seen_run_id`
- set `first_seen_at`
- set `last_seen_at`

When a review already exists:

- update `app_version`
- update `vote_count`
- update `vote_sum`
- update `raw_payload_hash`
- update `last_seen_run_id`
- update `last_seen_at`
- update `updated_at`

Do not overwrite `first_seen_at`, `first_seen_run_id`, or the source review id. These fields preserve lineage.

## Verification Queries

The Phase I verification utilities are provided in:

```text
outputs/data_health_queries.sql
```

These queries check:

- ingestion run status and record counts
- raw page parse errors
- rejected review counts by reason
- loaded review counts by app and vertical
- rating distribution
- detected language distribution
- quality flags by type and severity
- records missing important optional metadata
- recent training-ready records

The goal is to quickly answer: Did the run work, what did it load, what did it reject, and is the result healthy enough for downstream use?

## Data Health Acceptance Checks

A Phase I ingestion run should pass these checks before being used for labeling or modeling:

- every requested app/storefront has at least one fetched raw page or a logged fetch error
- raw pages are stored even when parsing fails
- hard validation failures are visible in `rejected_review_records`
- loaded reviews have source ids, ratings, bodies, timestamps, and app/storefront links
- ratings are only 1 through 5
- duplicate reviews do not appear after repeated runs
- language distribution is visible
- quality flags are queryable
- the `training_review_dataset` view returns usable rows

## Why This Step Matters

This step defines the semantic integrity of the dataset. If ratings are parsed incorrectly, timestamps are inconsistent, duplicates inflate counts, or malformed records vanish without trace, the model will learn from distorted data.

Good cleaning and loading creates:

- faster modeling iteration because data exports are reliable
- better interpretability because every record is traceable to source and ingestion run
- safer collaboration because analysts can inspect quality flags and rejection reasons
- easier scaling because future sources can reuse the same validation and loading contract

## Phase I Deliverable

The completed cleaning and loading layer should deliver:

- deterministic validation rules
- minimal text normalization that preserves user meaning
- timestamp, rating, language, and reviewer normalization
- transaction-based loading into the Step 3 schema
- idempotent review upserts
- rejected-record tracking
- quality-flag tracking
- verification SQL utilities
- run-level status and count updates

This creates the bridge between raw web data and a trustworthy analytical dataset.
