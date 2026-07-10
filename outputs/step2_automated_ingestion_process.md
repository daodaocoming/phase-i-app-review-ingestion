# Step 2: Developing an Automated Ingestion Process

## Objective

The ingestion layer will programmatically collect recent public customer reviews from the Apple App Store customer-review RSS feed and convert them into normalized records for downstream storage, labeling, and model experimentation.

For Phase I, the system will use a deliberately small, controlled cohort of apps rather than attempting to collect the entire App Store. The prototype scope is:

- 30 to 50 manually selected iOS apps
- 6 commercial verticals, such as food delivery, retail, fintech, travel, mobility, productivity, health, education, social, and subscriptions
- United States storefront as the initial country configuration
- English-first review filtering for the first training-ready dataset
- Recent reviews only, based on the public RSS review window available for each app

This keeps the data source focused enough for a maintainable prototype while still giving the sentiment pipeline broad coverage beyond a single industry or user community.

## Selected Source

The ingestion process will use Apple's public customer-review RSS/JSON endpoint:

```text
https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json
```

Example:

```text
https://itunes.apple.com/us/rss/customerreviews/page=1/id=284882215/sortby=mostrecent/json
```

The feed returns review objects containing fields such as:

- app id, inferred from the requested endpoint
- storefront / country
- review id
- rating
- review title
- review text
- author label and author profile URI
- published / updated timestamp
- app version
- vote count and vote sum, when available
- pagination links such as first, next, and last

This endpoint should be treated as a legacy public feed rather than a guaranteed long-term production API. The modern App Store Connect API is designed for app owners and developers, so it is not appropriate for collecting arbitrary third-party app reviews. The Phase I design therefore includes a feasibility checkpoint and fallback planning instead of assuming permanent source stability.

## Ingestion Architecture

The ingestion module will be organized into clear components so that source logic, transformation logic, and storage logic can evolve independently.

### 1. Configuration Layer

The pipeline will be driven by a configuration file, for example `config/apps.yaml`, containing:

- app id
- app name
- vertical / business category
- storefront country code, initially `us`
- expected language, initially `en`
- enabled / disabled flag
- optional notes about why the app was selected

This avoids hardcoding app targets in the scraper and allows future teams to add, pause, or rebalance sources without changing ingestion code.

### 2. Fetch Layer

The fetcher will request each app's customer-review RSS pages in a controlled loop:

1. Load the configured app cohort.
2. For each app and storefront, request page 1 of the RSS/JSON feed.
3. Follow pagination links or iterate page numbers up to the available `last` page, with a conservative maximum of 10 pages per app per run.
4. Store the raw response payload for traceability.
5. Pass parsed review entries to the transformation layer.

The fetch layer should include:

- explicit timeout settings
- retry with exponential backoff for transient 429, 500, 502, 503, and 504 responses
- conservative request pacing between pages and apps
- source-specific user agent identifying the internal research prototype
- structured logging for app id, page, status code, duration, record count, and error class
- no login, no session simulation, no browser automation, and no HTML scraping of Apple's website

### 3. Parse and Normalize Layer

The parser will convert Apple RSS/JSON fields into a stable internal review model. Each normalized review should include:

```text
source_platform        = "apple_app_store"
source_endpoint        = requested feed URL
storefront             = country code, e.g. "us"
app_id                 = Apple app id
app_name               = configured app name
vertical               = configured business vertical
review_id              = feed entry id
review_url             = related review URL, when available
author_label           = feed author name
author_uri             = feed author URI, when available
rating                 = integer 1-5
title                  = review title
body                   = review text
app_version            = app version from the feed
published_at           = review updated timestamp parsed as UTC
vote_count             = integer, nullable
vote_sum               = integer, nullable
raw_payload_hash       = hash of the raw review object
ingested_at            = ingestion timestamp
```

The transformation layer should perform light cleaning only:

- trim leading and trailing whitespace
- normalize line breaks
- preserve emojis and original casing in the canonical text fields
- compute auxiliary fields such as character count, token estimate, and detected language
- reject records with missing review id, missing rating, or empty review body

The system should avoid aggressive text cleaning at ingestion time because downstream labeling and modeling teams may need the original wording, punctuation, emojis, and formatting signals.

### 4. Deduplication and Idempotency

The pipeline must be safe to run repeatedly. Deduplication will use a stable unique key:

```text
(source_platform, app_storefront_id, source_review_id)
```

On conflict, the storage layer should update mutable fields such as `app_version`, `vote_count`, `vote_sum`, `raw_payload_hash`, and `last_seen_at`, while preserving the original `first_seen_at`.

This supports:

- repeatable manual runs
- future scheduled ingestion
- recovery after partial failures
- incremental refreshes without duplicate training examples

### 5. Storage Handoff

For Phase I, the ingestion output should be written into a relational database. SQLite is acceptable for the prototype if the schema is kept PostgreSQL-compatible. PostgreSQL should be the preferred production target once the pipeline is scheduled or shared across teams.

The ingestion layer should hand off data to the database layer using the following logical tables:

- `verticals`: controlled business categories for cohort balancing and analysis
- `apps`: configured app metadata and vertical assignment
- `app_storefronts`: app/country ingestion settings, initially US storefront and English-first filtering
- `reviewers`: public author labels and author URIs from the feed, stored only as source metadata
- `ingestion_runs`: one row per pipeline execution
- `raw_feed_pages`: raw source responses by app, storefront, page, and run
- `reviews`: normalized deduplicated review records
- `rejected_review_records`: malformed or incomplete review entries that cannot be safely loaded
- `review_quality_flags`: optional validation flags such as non-English, empty body, duplicate text, parsing error, or suspicious rating/text mismatch

The ingestion process should write both raw and normalized data. Raw pages preserve auditability and make it possible to reparse historical responses if the normalization logic changes.

The database contract is defined in Step 3. The key review-level upsert constraint should be:

```text
(source_platform, app_storefront_id, source_review_id)
```

This ties deduplication to the exact source, app, and storefront while keeping the schema extensible for additional countries or future public review sources.

## Operational Behavior

Each run should produce a concise summary:

- run id
- started and completed timestamps
- number of apps requested
- number of feed pages fetched
- number of raw review entries parsed
- number of new reviews inserted
- number of existing reviews updated
- number of rejected or flagged records
- number of failed app/page requests
- error report grouped by status code or exception type

Logs should be machine-readable, preferably JSON lines, so that later scheduling or monitoring can consume them without redesigning the ingestion layer.

## Source Compliance and Safety

The ingestion process will use only the public RSS/JSON customer-review feed. It will not scrape Apple web pages, bypass access controls, simulate user sessions, or collect private user information.

The crawler will remain intentionally conservative:

- low request volume from a small app cohort
- request pacing between pages and apps
- retry limits and backoff rather than aggressive re-requesting
- source-specific configuration so ingestion can be disabled quickly if the feed changes
- documentation that this is a prototype source, not a guaranteed long-term production contract

Before moving beyond the prototype, the team should complete a legal and policy review of Apple's current terms and confirm whether the RSS feed remains acceptable for the intended usage.

## Feasibility Check for Phase I

Before implementing the full cohort, the team should run a short feasibility test:

1. Select 3 apps across 3 different verticals.
2. Fetch pages 1 to 2 for the US storefront.
3. Confirm that the feed returns review ids, ratings, title, body, author labels, timestamps, app versions, and pagination links.
4. Confirm that review volume and language distribution are sufficient for the prototype.
5. Confirm that repeated runs deduplicate records correctly.
6. Confirm that raw pages and normalized reviews are persisted.

The source should be accepted for Phase I if this test produces a usable sample with stable identifiers, parseable timestamps, rating coverage, and repeatable deduplication.

## Key Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| RSS endpoint changes or becomes unavailable | Ingestion may fail or lose coverage | Isolate source adapter, log schema errors, keep raw payloads, and maintain a fallback source evaluation path |
| Feed exposes only recent reviews | Dataset will not contain full review history | Position Phase I as recent-review ingestion; use scheduled runs to build history over time |
| App cohort bias | Dataset may overrepresent large consumer apps | Select apps across verticals and document cohort rationale |
| Language noise | Non-English reviews may enter the US storefront sample | Add language detection and quality flags rather than deleting all non-English text blindly |
| Duplicate or updated reviews | Repeated runs may inflate counts | Enforce unique key and upsert behavior |
| Over-cleaning text | Downstream sentiment signals may be lost | Preserve raw text and apply only minimal normalization |

## Phase I Deliverable

The completed ingestion component should deliver:

- a configurable app cohort file
- an Apple App Store RSS source adapter
- a paginated fetcher with timeout, pacing, retry, and structured logs
- a parser that maps RSS/JSON review entries into a stable internal schema
- deduplication using `(source_platform, app_storefront_id, source_review_id)`
- raw response persistence for auditability
- normalized relational storage suitable for SQLite in prototype and PostgreSQL in production
- a run summary report suitable for handoff to labeling, analytics, and modeling teams

This design creates a practical first ingestion layer: narrow enough to implement and validate quickly, but modular enough to support future scheduling, additional storefronts, broader app cohorts, and eventually additional public review sources.

## Verification Note

As of June 25, 2026, a live check of the example RSS/JSON endpoint returned recent App Store review entries and pagination metadata:

- Example feed: https://itunes.apple.com/us/rss/customerreviews/page=1/id=284882215/sortby=mostrecent/json
- Feed title observed: `iTunes Store: Customer Reviews`
- Pagination links observed: `first`, `last`, `previous`, and `next`
- Review fields observed: review id, rating, title, content, author label, updated timestamp, app version, vote count, and vote sum
