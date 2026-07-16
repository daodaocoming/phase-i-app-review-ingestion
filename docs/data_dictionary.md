# Data Dictionary

## Apple-to-Internal Mapping

| Apple JSON field | Internal field | Rule |
| --- | --- | --- |
| requested app id | `apps.source_app_id` | Stored as text |
| requested country | `app_storefronts.storefront` | Lowercase country/storefront code |
| `entry.id.label` | `reviews.source_review_id` | Required string |
| `entry.im:rating.label` | `reviews.rating` | Required integer 1-5 |
| `entry.title.label` | `reviews.title` | Trimmed; nullable |
| `entry.content.label` | `reviews.body` | Minimally cleaned; required |
| `entry.author.name.label` | `reviewers.author_label` | Public metadata; nullable |
| `entry.author.uri.label` | `reviewers.author_uri` | Public metadata; nullable |
| `entry.updated.label` | `reviews.published_at` | Parsed and converted to UTC ISO 8601 |
| `entry.im:version.label` | `reviews.app_version` | Nullable text |
| `entry.link.attributes.href` | `reviews.review_url` | Nullable text |
| `entry.im:voteCount.label` | `reviews.vote_count` | Nullable integer |
| `entry.im:voteSum.label` | `reviews.vote_sum` | Nullable integer |

## Tables

### `verticals`

Controlled business categories used for cohort balance and analysis.

### `apps`

One row per source app. `(source_platform, source_app_id)` is unique.

### `app_storefronts`

Country-specific collection settings for each app. `(app_id, storefront)` is unique.

### `reviewers`

Public author metadata only. `author_fingerprint` hashes source plus author URI, or label when URI is absent.

### `ingestion_runs`

One row per execution with status, timestamps, config snapshot, counters, and error summary.

### `raw_feed_pages`

Exact successful response body plus URL, status, hash, disk path, app/storefront, page number, run, and parse outcome.

### `reviews`

Canonical normalized reviews. Required semantic fields are source review id, rating, body, timestamp, app, storefront, endpoint, and lineage ids. The composite source key prevents duplicate reviews.

### `rejected_review_records`

Raw review objects that failed hard validation, with reason and run/page linkage.

### `review_quality_flags`

Soft, heuristic data-quality concerns associated with loaded reviews. `(review_id, flag_type)` is unique. These flags are not sentiment labels or ground-truth annotations.

### `ingestion_run_app_stats`

One row per app and ingestion run. It stores app-level page, parsed/inserted/updated/rejected review, quality-flag, failure, and status metrics for controlled validation.

### `training_review_dataset`

Flat SQL view joining reviews to app, vertical, and storefront metadata. It excludes public reviewer identity fields by design and exposes lineage ids for reproducibility. The default CSV exporter uses an explicit allowlist and does not export `reviewer_id`, `author_label`, `author_uri`, or `author_fingerprint`.

## Timestamp Convention

Application-generated timestamps use UTC ISO 8601 with `Z`. SQLite stores them as text. PostgreSQL should use `TIMESTAMPTZ`.

## Text Convention

Canonical review text preserves casing, punctuation, emoji, and expressive content. Only surrounding whitespace, repeated horizontal whitespace, and excessive line breaks are normalized.
