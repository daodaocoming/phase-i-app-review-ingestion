# Controlled Scale-Up Validation Report

- Database: `/Users/pc/Documents/code/phase-i-app-review-ingestion/database/validation_scale.db`
- Runs: 1, 2, 3
- DS readiness decision: **ready**

## Run summaries

| Run | Status | Apps | Pages | Parsed | Inserted | Updated | Rejected | Flags | Failed requests |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | completed | 12 | 24 | 1150 | 1150 | 0 | 0 | 157 | 0 |
| 2 | completed | 12 | 24 | 1200 | 100 | 1100 | 0 | 11 | 0 |
| 3 | completed | 12 | 24 | 1200 | 50 | 1150 | 0 | 9 | 0 |

## App-level outcomes in final run

| App | Vertical | Status | Pages | Parsed | Inserted | Updated | Rejected | Flags | Failures |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Airbnb | Travel | completed | 2 | 100 | 0 | 100 | 0 | 0 | 0 |
| Amazon | Shopping | completed | 2 | 100 | 0 | 100 | 0 | 0 | 0 |
| DoorDash | Food and Drink | completed | 2 | 100 | 0 | 100 | 0 | 0 | 0 |
| Duolingo | Education | completed | 2 | 100 | 0 | 100 | 0 | 0 | 0 |
| Facebook | Social | completed | 2 | 100 | 0 | 100 | 0 | 0 | 0 |
| Gmail | Productivity | completed | 2 | 100 | 0 | 100 | 0 | 0 | 0 |
| Google Maps | Navigation | completed | 2 | 100 | 0 | 100 | 0 | 0 | 0 |
| Headspace | Health and Fitness | completed | 2 | 100 | 0 | 100 | 0 | 0 | 0 |
| Instagram | Social | completed | 2 | 100 | 50 | 50 | 0 | 9 | 0 |
| Spotify | Music | completed | 2 | 100 | 0 | 100 | 0 | 0 | 0 |
| Uber | Mobility | completed | 2 | 100 | 0 | 100 | 0 | 0 | 0 |
| Venmo | Finance | completed | 2 | 100 | 0 | 100 | 0 | 0 | 0 |

## Final dataset

| Measure | Value |
| --- | ---: |
| Canonical reviews | 1300 |
| English, no-error export rows | 1259 |
| Apps represented | 12 |
| Verticals represented | 11 |
| Invalid required fields | 0 |

## Quality flags

Quality flags are transparent heuristics for review and filtering. They are not sentiment labels or ground-truth annotations.

| Flag type | Observed count |
| --- | ---: |
| `duplicate_text_within_app` | 5 |
| `non_english_or_unknown_language` | 111 |
| `rating_text_mismatch` | 111 |
| `too_short_review` | 263 |

## Repeated-review and source-window behavior

- Canonical rows: 1300
- Unique composite source keys: 1300
- Repeated observations recorded as updates: 2250

Changed source pages detected:

| App | Page | Runs | Response hash changed | Review window changed |
| --- | ---: | --- | --- | --- |
| Airbnb | 2 | 1, 2, 3 | True | False |
| Amazon | 1 | 1, 2, 3 | True | False |
| Amazon | 2 | 1, 2, 3 | True | True |
| DoorDash | 2 | 1, 2, 3 | True | False |
| Duolingo | 1 | 1, 2, 3 | True | True |
| Facebook | 1 | 1, 2, 3 | True | False |
| Gmail | 2 | 1, 2, 3 | True | False |
| Google Maps | 1 | 1, 2, 3 | True | False |
| Google Maps | 2 | 1, 2, 3 | True | False |
| Headspace | 2 | 1, 2, 3 | True | False |
| Instagram | 2 | 1, 2, 3 | True | True |
| Spotify | 2 | 1, 2, 3 | True | False |
| Uber | 1 | 1, 2, 3 | True | False |
| Venmo | 2 | 1, 2, 3 | True | False |

## Acceptance gates

| Gate | Result |
| --- | --- |
| `all_configured_apps_represented` | PASS |
| `at_least_six_verticals` | PASS |
| `at_least_1000_unique_reviews` | PASS |
| `no_duplicate_source_keys` | PASS |
| `no_invalid_required_fields` | PASS |
| `final_run_has_no_app_or_request_failures` | PASS |
