# Final TF-IDF Sentiment Baseline Model Card

## Model summary

`tfidf_sentiment_final_v1` is a frozen, transparent binary sentiment baseline. It combines the exact review-text normalization used during evaluation, a word/bi-gram TF-IDF vectorizer, and class-weighted logistic regression. It is a research and triage baseline, not a production-grade sentiment truth model.

The persisted artifact is [artifacts/final_tfidf_sentiment_pipeline.joblib](artifacts/final_tfidf_sentiment_pipeline.joblib), with provenance in [artifacts/final_tfidf_sentiment_pipeline.metadata.json](artifacts/final_tfidf_sentiment_pipeline.metadata.json).

## Training data

The source is the Phase I Apple App Store RSS review collection covering 12 Apps. The final cohort contains 1,002 reviews: 575 negative and 427 positive. The exact frozen cohort is generated as `artifacts/final_training_dataset.csv` so the final training step can be reproduced without relying on a changing RSS window. This source-text file is excluded from public GitHub commits.

The source feature export and audit artifacts are identified by SHA-256 in the model metadata. Review text is public-source content; the generated final training export excludes author metadata and was checked for URLs and email-address patterns before packaging. The training export should be distributed through controlled storage when exact retraining is approved.

## Weak-label definition

- Ratings 1–2 map to `negative`.
- Rating 3 maps to `neutral` and is excluded from binary training.
- Ratings 4–5 map to `positive`.

These are rating-derived weak labels, not independent human sentiment truth.

## Filtering and separation

The final cohort applies the frozen v1 rules in this order:

1. Exclude the 150-row audit sample and any normalized-text duplicate of an audited review.
2. Keep binary labels only.
3. Keep the English/interpretable proxy subset.
4. Remove short reviews.
5. Remove rows with `weak_label_needs_review`.

The 150 audited review IDs and their duplicate text groups are excluded from training. The 99 clear human-reviewed rows remain a secondary diagnostic only; they were not used for model selection, parameter tuning, or final fitting.

## Features and model

The model receives review text. Training combines title and body with a newline; inference accepts one raw review-text string. The shared preprocessing pipeline applies Unicode NFKC normalization, case folding, and whitespace collapsing before TF-IDF.

TF-IDF uses word unigrams and bigrams, `min_df=2`, `max_df=0.95`, sublinear term frequency, and `lowercase=False` because case folding is explicit. The classifier is `LogisticRegression(class_weight="balanced", C=1.0, solver="liblinear", max_iter=1000, random_state=20260730)`.

Rating, App name, quality flags, issue signals, and weak-label metadata are not model predictors.

## Frozen evaluation results

The full-cohort model is trained for reuse; the metrics below come from the previously frozen evaluation protocols and are not re-estimated on the training artifact.

| Evaluation | Macro F1 | Balanced accuracy | Interpretation |
|---|---:|---:|---|
| Weak-label holdout | 0.890 | 0.882 | Agreement with filtered weak labels |
| Human-reviewed diagnostic | 0.953 | 0.962 | Small, targeted, clear binary subset; not an independent benchmark |
| Cross-App pooled out-of-App | 0.860 | 0.851 | Leave-one-App-out pooled result |

### Cross-App results by held-out App

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

App-level Macro F1 has mean `0.820`, median `0.847`, standard deviation `0.079`, and range `0.644–0.929`. App-level balanced accuracy has mean `0.838` and range `0.623–0.949`. The App-level spread is materially important: Headspace and Duolingo are substantially weaker than the pooled result.

## Limitations and risks

- The target is a rating-derived weak label, so high scores do not establish true sentiment accuracy.
- Mixed sentiment, low-context reviews, App-specific terminology, comparative language, and possible irony can cause errors.
- Headspace and Duolingo show the clearest cross-App degradation; Spotify is also weaker than the pooled result.
- The English proxy is heuristic and the model should not be treated as multilingual.
- RSS provides a recent-review window rather than a complete historical population.
- Product versions, vocabulary, and review distributions can drift.
- Issue signals are retained for analysis, but their earlier negative metric delta means they are not part of this final model.

## Appropriate and inappropriate uses

Appropriate uses include aggregate sentiment summaries, exploratory trend monitoring, research baselines, and prioritizing reviews for human inspection. Predictions should be paired with confidence review and App-level monitoring.

The model should not be used for automatic user penalties, employment or eligibility decisions, medical or mental-health judgments, unattended production decisions, or claims about sentiment in non-English text.

## Reproduction

Install `requirements-ds.txt`, then run:

```bash
python scripts/train_final_sentiment_model.py \
  --filtered-input artifacts/final_training_dataset.csv
```

For normal use:

```bash
python scripts/predict_sentiment.py \
  --text "The latest update is excellent and easy to use."
```
