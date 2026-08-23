# Phase I Final Project Report

## 1. Executive summary

This project built a reproducible pipeline for collecting Apple App Store reviews, validating and cleaning them, deriving transparent rating-based weak labels, auditing those labels, and evaluating a simple sentiment baseline. The frozen final model is a TF-IDF-only, class-weighted logistic regression trained on all 1,002 eligible binary examples after the documented exclusions.

The baseline transfers reasonably well across Apps, but the pooled score hides meaningful App-level variation. Headspace and Duolingo are the clearest weak cases, showing that App-specific language, mixed sentiment, and low-context reviews remain important failure modes. The final recommendation is to keep this model as a transparent baseline and invest next in independent labels, time-based validation, and App-aware error analysis rather than immediately adding model complexity.

## 2. Project scope and execution order

The completed story is:

```text
RSS source selection -> ingestion -> raw-page traceability -> parsing/normalization
-> validation and quality flags -> feature engineering -> weak-label audit
-> filtered binary baseline -> cross-App validation -> full-cohort final model
-> persisted inference pipeline
```

The ingestion and data-quality work is documented in `docs/` and the existing validation outputs. The modeling source of truth is the versioned v1 feature export, audit artifacts, and `issue_keywords_v2.yaml`.

## 3. Data and weak labels

Ratings 1–2 were mapped to `negative`, rating 3 to `neutral`, and ratings 4–5 to `positive`. Neutral reviews were excluded from binary modeling. The audit consisted of a deterministic 150-review sample. Audited IDs and duplicate normalized text groups were excluded from model data; 99 clear binary human-reviewed examples were retained only as a diagnostic.

The final filter leaves 1,002 rows: 575 negative and 427 positive. The frozen filtering sequence is audit exclusion, binary labels only, English/interpretable proxy, non-short reviews, and removal of `weak_label_needs_review` rows.

## 4. Baseline modeling

The predictor is normalized review text only. The shared pipeline applies NFKC normalization, case folding, whitespace normalization, word unigram/bigram TF-IDF, and class-weighted logistic regression. Rating-derived fields, App name, quality flags, weak-label metadata, and issue signals are excluded from predictors.

The issue signals were retained as error-analysis metadata. In the earlier controlled comparison, adding them reduced both Macro F1 and balanced accuracy, so they were not included in the frozen final model.

## 5. Frozen evaluation results

The in-distribution weak-label holdout produced Macro F1 `0.890` and balanced accuracy `0.882`. The 99-row human-reviewed diagnostic produced Macro F1 `0.953` and balanced accuracy `0.962`; this is a targeted, clear binary diagnostic rather than an independent benchmark.

The cross-App evaluation used leave-one-App-out folds. Each fold fit on 11 Apps and tested once on the held-out App. The pooled out-of-App result was Macro F1 `0.860` and balanced accuracy `0.851`. App-level Macro F1 averaged `0.820`, with median `0.847`, standard deviation `0.079`, and range `0.644–0.929`. App-level balanced accuracy averaged `0.838`, with range `0.623–0.949`.

### App-level cross-App performance

| Held-out App | Test N | Negative | Positive | Train N | Macro F1 | Balanced accuracy |
|---|---:|---:|---:|---:|---:|---:|
| Airbnb | 87 | 79 | 8 | 915 | 0.814 | 0.850 |
| Amazon | 83 | 66 | 17 | 919 | 0.845 | 0.794 |
| DoorDash | 79 | 36 | 43 | 923 | 0.848 | 0.854 |
| Duolingo | 121 | 25 | 96 | 881 | 0.697 | 0.804 |
| Facebook | 71 | 40 | 31 | 931 | 0.883 | 0.878 |
| Gmail | 73 | 56 | 17 | 929 | 0.863 | 0.856 |
| Google Maps | 83 | 58 | 25 | 919 | 0.880 | 0.863 |
| Headspace | 64 | 50 | 14 | 938 | 0.644 | 0.623 |
| Instagram | 111 | 71 | 40 | 891 | 0.797 | 0.779 |
| Spotify | 67 | 12 | 55 | 935 | 0.764 | 0.858 |
| Uber | 83 | 14 | 69 | 919 | 0.873 | 0.949 |
| Venmo | 80 | 68 | 12 | 922 | 0.929 | 0.944 |

## 6. What worked

- The ingestion and validation path preserves raw-page lineage and separates hard rejection from soft quality flags.
- The rating-derived label contract is simple, inspectable, and reproducible.
- Explicit audit exclusion and normalized-text grouping prevented audited examples from leaking into modeling.
- TF-IDF-only modeling is fast, easy to inspect, and strong enough to provide a useful baseline.
- Cross-App evaluation exposed weaknesses that the pooled metric would have hidden.

## 7. What did not work

- Adding provisional issue signals did not improve the frozen baseline metrics.
- Performance was not uniform across Apps. Headspace and Duolingo fell well below the pooled result.
- Rating-derived labels cannot resolve mixed sentiment, sarcasm, or reviews whose rating and text disagree.
- Short and App-specific reviews remain difficult for a vocabulary-based model.

## 8. Limitations

The primary target is weak agreement with rating, not independent sentiment truth. The human diagnostic is small, targeted, and restricted to clear binary cases. The data comes from a recent RSS review window and may not represent all users, languages, versions, or historical periods. Performance may drift as products and vocabulary change.

## 9. Recommended future work

1. Build a larger, independently labeled evaluation set with mixed and unclear cases retained as explicit categories.
2. Add time-based validation to measure version and vocabulary drift.
3. Track App-level metrics continuously and inspect low-performing Apps separately.
4. Compare multilingual or domain-adapted approaches only after the label and evaluation design is strengthened.
5. Validate probability calibration and establish a human-review threshold before any operational use.

## 10. Final handoff

The canonical model is `artifacts/final_tfidf_sentiment_pipeline.joblib`; its metadata records the input and artifact hashes. The final training cohort is in `artifacts/final_training_dataset.csv`. Use `scripts/predict_sentiment.py` for inference. Read [MODEL_CARD.md](MODEL_CARD.md) for model limitations and appropriate use, and follow [README.md](README.md) for the full execution order.

