# Cross-App TF-IDF Generalization

This is a frozen leave-one-App-out evaluation of the simple TF-IDF-only baseline. Each model is fit on 11 Apps and evaluated once on the unseen App.

## Protocol and frozen boundaries

Input SHA-256: `de4a00e7a7572334507c629ad2b3c2546a452f64a997396ae7e638fb25d12b52`
Issue configuration: `issue_keywords_v2` (signals retained for analysis only)
Seed: `20260730`; folds: `leave-one-App-out; TF-IDF fit on other 11 Apps only`
Filtered rows: **1002**; held-out Apps: **12**

The 99 clear human-reviewed examples are not used for fitting, model selection, or this evaluation; they remain a targeted diagnostic artifact. The existing baseline and audit artifacts were hash-checked before the run and are not overwritten.

## Results by held-out App

| Held-out App | Test N | Negative | Positive | Train N | Purged duplicate groups | Macro F1 | Balanced accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|
| Airbnb | 87 | 79 | 8 | 915 | 0 | 0.814 | 0.850 |
| Amazon | 83 | 66 | 17 | 919 | 0 | 0.845 | 0.794 |
| DoorDash | 79 | 36 | 43 | 923 | 0 | 0.848 | 0.854 |
| Duolingo | 121 | 25 | 96 | 881 | 0 | 0.697 | 0.804 |
| Facebook | 71 | 40 | 31 | 931 | 0 | 0.883 | 0.878 |
| Gmail | 73 | 56 | 17 | 929 | 0 | 0.863 | 0.856 |
| Google Maps | 83 | 58 | 25 | 919 | 0 | 0.880 | 0.863 |
| Headspace | 64 | 50 | 14 | 938 | 0 | 0.644 | 0.623 |
| Instagram | 111 | 71 | 40 | 891 | 0 | 0.797 | 0.779 |
| Spotify | 67 | 12 | 55 | 935 | 0 | 0.764 | 0.858 |
| Uber | 83 | 14 | 69 | 919 | 0 | 0.873 | 0.949 |
| Venmo | 80 | 68 | 12 | 922 | 0 | 0.929 | 0.944 |

## Aggregate view

App-level Macro F1: mean `0.820`, median `0.847`, SD `0.079`, range `0.644–0.929`.
App-level balanced accuracy: mean `0.838`, range `0.623–0.949`.
Pooled out-of-App Macro F1: `0.860`; pooled balanced accuracy: `0.851`.

These values answer a different question from the existing in-distribution weak-label holdout and are not directly comparable as equivalent benchmarks.

## Weakest-App diagnostic

### Headspace

Macro F1 `0.644`; balanced accuracy `0.623`. The sampled error count and diagnostic tags are descriptive; issue signals are interpretability metadata only.

| Sampled errors | Diagnostic tags |
|---:|---|
| 6 | app_specific_or_oov_terminology (3), mixed_or_concessive_sentiment (3) |

### Duolingo

Macro F1 `0.697`; balanced accuracy `0.804`. The sampled error count and diagnostic tags are descriptive; issue signals are interpretability metadata only.

| Sampled errors | Diagnostic tags |
|---:|---|
| 6 | app_specific_or_oov_terminology (3), mixed_or_concessive_sentiment (3), short_or_low_context (1) |

### Spotify

Macro F1 `0.764`; balanced accuracy `0.858`. The sampled error count and diagnostic tags are descriptive; issue signals are interpretability metadata only.

| Sampled errors | Diagnostic tags |
|---:|---|
| 5 | app_specific_or_oov_terminology (1) |

## Interpretation

Issue signals remain available for analysis, reporting, and interpretability. Their earlier negative delta means they did not provide incremental predictive value on top of TF-IDF in that experiment; it does not show that the underlying issue concepts are useless.

The primary labels remain filtered rating-derived weak labels, not independent sentiment truth. The targeted 99-row audit diagnostic is therefore not an independent benchmark.
