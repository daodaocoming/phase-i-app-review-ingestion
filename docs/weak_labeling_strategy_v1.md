# Feature Engineering and Weak Labeling Strategy v1

## Purpose

This layer converts canonical App Store reviews into a deterministic,
privacy-safe dataset for exploratory analysis and simple downstream modeling.
The labels are weak labels derived from ratings. They are not manually verified
sentiment ground truth.

The v1 implementation deliberately stays simple. It does not use an LLM,
an agent workflow, a trained sentiment model, or an opaque confidence score.

## Rating-Based Weak Labels

| Rating | Weak label |
| ---: | --- |
| 1-2 | `negative` |
| 3 | `neutral` |
| 4-5 | `positive` |

Every row records `weak_label_source=rating_v1`. The source rating remains in
the analytical dataset for auditing, but it must not be supplied as a predictor
to a model trained to reproduce `weak_label`. Doing so would be direct target
leakage.

## Review and Noise Indicators

The rating-derived label is always retained. `weak_label_needs_review=1` means
one or more transparent heuristics indicate that the label may be noisy.
Reasons are written to `weak_label_noise_reasons` in a stable, pipe-delimited
order.

| Reason | Trigger | Interpretation |
| --- | --- | --- |
| `rating_text_mismatch` | Existing quality flag | Strong keyword polarity conflicts with a high or low rating |
| `mixed_sentiment_keywords` | Both positive and negative lexicon terms occur | The review may express multiple opinions |
| `neutral_rating` | Rating is 3 | The text may be positive, negative, neutral, or mixed |
| `too_short_review` | Existing short-review quality flag | The text provides little evidence for interpreting the rating |
| `non_english_or_unknown_language` | Language is not confidently English | English keyword heuristics may be incomplete or misleading |

Quality flags remain quality-review features. They do not replace the rating
rule and are not treated as sentiment labels.

## Feature Definitions

The dataset contains the review rating, App, vertical, storefront, publication
timestamp, title, and body, plus:

- title and body character counts, body word count, and punctuation counts;
- publication year, month, English weekday name, and hour;
- one binary feature for every supported quality flag;
- binary issue signals for performance/crash, login/account, payment/billing,
  ads, update/version, delivery/service, and usability/navigation;
- aggregate quality-flag and issue-signal counts.

Issue terms are defined in `config/issue_keywords_v1.yaml`. Matching is
case-insensitive, supports phrases separated by flexible whitespace, and uses
word boundaries so a term such as `ad` does not match `adaptation`.

Each canonical review produces exactly one row. Public reviewer labels, author
URIs, reviewer IDs, and author fingerprints are excluded.

### CSV Schema

| Column group | Columns | Type / convention |
| --- | --- | --- |
| Identity and context | `review_id`, `source_review_id`, `app_name`, `vertical_name`, `storefront` | Integer ID and UTF-8 text |
| Source fields | `rating`, `title`, `body`, `detected_language`, `published_at` | Rating 1-5; UTC ISO 8601 timestamp |
| Text features | `title_char_count`, `body_char_count`, `body_word_count`, `question_mark_count`, `exclamation_mark_count` | Non-negative integers |
| Time features | `published_year`, `published_month`, `published_day_of_week`, `published_hour` | Calendar values derived from `published_at` |
| Quality features | `quality_flag_<type>`, `quality_flag_count`, `has_any_quality_flag` | Binary indicators plus non-negative count |
| Issue features | `issue_<signal>`, `issue_signal_count` | Binary indicators plus non-negative count |
| Weak-label fields | `weak_label`, `weak_label_source`, `weak_label_needs_review`, `weak_label_noise_reasons` | Controlled strings, binary review indicator, pipe-delimited reasons |

The generated summary JSON records the complete ordered column list and the
CSV SHA-256 digest for reproducibility.

## Known Sources of Label Noise

The v1 heuristics expose some observable risk but cannot resolve meaning:

- A user may choose a rating that conflicts with the written review.
- A review may praise one feature while criticizing another.
- Three-star reviews are frequently ambiguous rather than truly neutral.
- Sarcasm can invert the apparent meaning of positive or negative words.
- Users can select the wrong star rating accidentally.
- Very short, emoji-only, or context-free reviews provide insufficient text.
- Non-English text may be missed or misread by the English keyword rules.
- Domain-specific language can carry sentiment that the small lexicons do not
  recognize.

Sarcasm and rating mistakes are documented limitations, not automatic flags.
Adding unreliable rules for them would create an impression of accuracy that
v1 does not have.

## Recommended Evaluation

Before using weak labels as training targets, draw a stratified manual sample
across label, App, vertical, text-length band, and review-reason category.
Annotators should assess rating/text agreement and mixed sentiment separately.
Report agreement and estimated precision for each stratum. Expand or revise
rules only after the review identifies a repeatable failure mode.

## Apple RSS Limitation

The source is a legacy public recent-review feed, not a complete historical
archive or a guaranteed production API. Returned review windows may change
between requests. The dataset therefore describes the observations retained by
this pipeline, not all historical reviews for the configured Apps.
