# Weak-Label Quality Audit v1

Input SHA-256: `de4a00e7a7572334507c629ad2b3c2546a452f64a997396ae7e638fb25d12b52`  
Sample size: 150 (core=120, booster=30)  
Seed: `20260730`

## Sampling

The core sample is class/flag-stratified. The booster sample targets rare noise reasons, issue signals, broad terms, and App coverage. Neutral-unflagged is structurally unavailable because every three-star review carries `neutral_rating`.

## Agreement by weak-label class

| Class | Core n | Raw agreement | Weighted agreement | Unflagged agreement | Mixed | Unclear |
|---|---:|---:|---:|---:|---:|---:|
| negative | 40 | 87.5% | 93.3% | 95.0% | 2.5% | 0.0% |
| neutral | 40 | 55.0% | 55.0% | 0.0% | 52.5% | 0.0% |
| positive | 40 | 70.0% | 76.9% | 80.0% | 17.5% | 0.0% |

## Noise-indicator reliability

| Reason | n | Valid warning rate |
|---|---:|---:|
| rating_text_mismatch | 12 | 8.3% |
| mixed_sentiment_keywords | 14 | 21.4% |
| neutral_rating | 41 | 97.6% |
| too_short_review | 25 | 24.0% |
| non_english_or_unknown_language | 13 | 76.9% |

## Issue-signal reliability

| Signal | n | Relevant | Not relevant | Unclear |
|---|---:|---:|---:|---:|
| performance_crash | 8 | 62.5% | 3 | 0 |
| login_account | 16 | 75.0% | 4 | 0 |
| payment_billing | 9 | 88.9% | 1 | 0 |
| ads | 9 | 100.0% | 0 | 0 |
| update_version | 17 | 82.4% | 3 | 0 |
| delivery_service | 18 | 94.4% | 1 | 0 |
| usability_navigation | 8 | 87.5% | 1 | 0 |

### Broad terms

| Term | n | Relevant | Not relevant | Unclear |
|---|---:|---:|---:|---:|
| service | 11 | 90.9% | 1 | 0 |
| account | 11 | 81.8% | 2 | 0 |
| version | 8 | 75.0% | 2 | 0 |

## Training-data recommendation

Use English-interpretable, non-short negative, positive reviews with weak_label_needs_review=0; exclude the audit sample from training. Keep all failed classes in manual review until the rules are revised.

Class gates: negative=pass, neutral=fail, positive=fail.
Unflagged training gates: negative=pass, neutral=fail, positive=pass.
Issue-signal screening status (provisional; not permanent validation): performance_crash=refine, login_account=refine, payment_billing=candidate, ads=candidate, update_version=candidate, delivery_service=candidate, usability_navigation=candidate, service=candidate, account=candidate, version=refine.
Intra-annotator consistency recheck: **passed**; core fields agreement=100.0%, issue relevance agreement=99.6%.

## Limitations

This is a small, manually annotated diagnostic sample from the retained Apple RSS window. The booster strata are intentionally non-proportional, the annotation is single-person, and the 23-review recheck measures intra-annotator consistency rather than independent annotator agreement. Issue-signal rates are provisional and remain versioned, reviewable candidate rules.
