# Live Feasibility Report

## Test Context

- Test date: July 5, 2026
- Successful run window: 2026-07-05 12:51:35Z to 12:52:01Z
- Python: 3.13.5 (project supports 3.11+)
- Storefront: United States (`us`)
- Maximum pages: 2 per app per run
- Request delay: 1 second
- Timeout: 15 seconds
- Retry count: 3

## Tested Apps

| App | Apple app id | Vertical |
| --- | --- | --- |
| Facebook | `284882215` | Social |
| Uber | `368677368` | Mobility |
| Duolingo | `570060128` | Education |

## Endpoint Pattern

```text
https://itunes.apple.com/{storefront}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json
```

For each app, pages 1 and 2 of the `us` endpoint were attempted.

## Actual Results

An initial run from the restricted execution sandbox could not resolve `itunes.apple.com`. It was correctly recorded as run 1 with `completed_with_errors`, 3 failed app requests, and no fabricated data. After network permission was enabled, two live runs completed successfully.

| Run | Status | Apps | Pages fetched | Parsed | Inserted | Updated | Rejected | New flags | Failed requests |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | completed | 3 | 6 | 300 | 300 | 0 | 0 | 39 | 0 |
| 3 | completed | 3 | 6 | 300 | 100 | 200 | 0 | 13 | 0 |

Final database state after both successful runs:

- 12 raw feed pages stored in SQLite and `data/raw/`
- 400 unique reviews
- 0 hard-rejected real records
- 52 quality flags
- 400 exported training rows
- 0 reviews missing required source id, valid rating, non-empty body, or timestamp

## JSON and Pagination Observations

The JSON structure was usable for all six pages in each successful run. Review objects were found under `feed.entry`. Every tested response exposed feed links with `alternate`, `self`, `first`, `last`, `previous`, and `next` relations, so pagination was observable.

Recovered review fields included:

- source review id
- 1-5 rating
- title and body
- public author label and URI when present
- updated timestamp
- app version
- review link when present
- vote count and vote sum

Each tested page returned 50 review entries.

## Idempotency Observation

The second live run updated 200 existing reviews and inserted 100 previously unseen source review IDs. Database inspection showed 400 rows and 400 distinct composite source keys, so no duplicate review rows were created.

The 100 new IDs all belonged to Duolingo. Its second run returned an older, different review window:

- first observed Duolingo window: July 1 to July 4, 2026
- second newly observed Duolingo window: June 29 to July 2, 2026

This is an important source inconsistency: identical page URLs can expose a changing or cache-dependent recent window. Raw response hashes differed across all repeated requests. The pipeline handled this safely by retaining both observations and deduplicating stable source review IDs.

## Quality Observations

The final 52 flags were:

| Flag | Count |
| --- | ---: |
| `too_short_review` | 29 |
| `non_english_or_unknown_language` | 17 |
| `rating_text_mismatch` | 6 |

These are heuristic review aids, not model labels. No live records failed the required-field validation rules during this small run.

## Suitability Decision

The source is suitable for a low-frequency Phase I prototype because:

- it is publicly accessible without login in the tested environment
- the payload is structured JSON
- stable review IDs support deduplication
- ratings, text, timestamps, app versions, and storefront context are available
- two pages across three verticals produced enough data for a meaningful prototype

It is not sufficient as a guaranteed long-term production API because:

- it is a legacy public RSS endpoint without a modern service guarantee
- it provides a recent window, not complete history
- the observed Duolingo window changed between near-consecutive runs
- response availability or shape may change without notice
- organizational legal/policy approval is still required before production deployment

## Controlled Scale-Up Validation

The next validation uses a fixed 12-app cohort across 11 verticals, two pages per
app, and three repeated runs against the same SQLite database. Each run writes a
small JSON summary with app-level counters and retained raw-page observations.
The final Markdown report compares response hashes and parsed review-ID sets for
the same app/page so changing recent-review windows are visible.

The default downstream export deliberately excludes `reviewer_id`, `author_label`,
`author_uri`, and `author_fingerprint`. Quality flags remain heuristic review
signals and must not be used as sentiment labels without a separate labeling or
weak-labeling design.

## Recommendation

Proceed with this source for teaching, feasibility, and low-frequency prototype ingestion. Schedule conservative periodic runs if building a rolling history, monitor raw-page schema and review-window behavior, and keep the source adapter replaceable.
