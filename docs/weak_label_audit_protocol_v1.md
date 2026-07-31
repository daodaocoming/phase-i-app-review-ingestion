# Weak-Label Quality Audit Protocol v1

## Scope

This audit evaluates the rating-derived weak labels and transparent issue/noise
heuristics in `review_features_v1.csv`. It is a validation artifact, not a new
training dataset. The audited 150 review IDs should remain held out from any
future model evaluation or training experiment.

The current frame contains 1,300 reviews, 683 negative, 83 neutral, and 534
positive weak labels. There are 241 rows with `weak_label_needs_review=1`.
Every neutral row is flagged because the `neutral_rating` reason is automatic;
there is therefore no neutral-unflagged stratum.

## Sampling

Run:

```bash
python scripts/create_weak_label_audit.py \
  --input data/processed/review_features_v1.csv \
  --keyword-config config/issue_keywords_v1.yaml \
  --seed 20260730
```

The tool writes a reproducible manifest, annotation template, and metadata
under `data/processed/weak_label_audit_v1/`. It uses a 120-row
class/flag-stratified core and a 30-row diagnostic booster. The booster covers
all 14 mixed-keyword rows when available, at least 8 examples of each issue
signal, at least 12 mismatch/non-English examples and 15 short-review examples,
and at least 8 occurrences each of `service`, `account`, and `version`. All
12 Apps and 11 verticals must have at least 8 sampled rows.

The core sample supports class-level estimates. The booster is deliberately
non-proportional and is used for low-frequency signal diagnostics, not as an
unbiased population estimate.

## Annotation procedure

1. Read the title and body first, without using rating or weak-label fields.
2. Record `apparent_sentiment` as the dominant attitude: negative, neutral,
   positive, or unclear.
3. Mark `mixed_sentiment=yes` only when substantive positive and negative
   opinions coexist; intensity alone is not mixed sentiment.
4. Record `text_interpretable` and `appears_english`.
5. Reveal the rating-derived fields and record `rating_label_agreement`.
   Use `unclear` when the text is mixed, too short, or not interpretable.
6. For each triggered issue signal, mark `relevant` when the review actually
   describes that issue category, `not_relevant` when the keyword is merely
   contextual, and `unclear` when the text does not resolve the meaning.
   Leave non-triggered signals as `not_triggered`.
7. Evaluate `service`, `account`, and `version` separately at the term level.

The analyzer accepts both the template's text values and spreadsheet-friendly
`1/0` values (`1` means agree/yes/relevant; `0` means disagree/no/not relevant).
For an untriggered signal or term, `0` is normalized to `not_triggered`.

After the first pass, wait at least 24 hours and create a 23-row recheck:

```bash
python scripts/analyze_weak_label_audit.py \
  --sample-dir data/processed/weak_label_audit_v1 \
  --annotations data/processed/weak_label_audit_v1/annotations.csv
```

Fill `recheck_template.csv` independently, then run the same command with
`--recheck-annotations`.

## Analysis and decision rules

The report calculates class agreement, a rating/text confusion matrix, mixed
and unclear rates, warning validity for each noise reason, issue-signal
relevance, broad-term relevance, and single-annotator recheck agreement.

Use the following gates consistently:

- A weak-label class passes when weighted agreement is at least 80% and unclear
  sentiment is at most 10%.
- An issue signal or broad term is retained as a candidate feature at 80%+
  relevance, refined at 60–79%, and removed from v2 below 60%.
- Initial training candidates are English-interpretable negative/positive rows
  with `weak_label_needs_review=0`; neutral rows enter only if the neutral gate
  passes. Noise flags are not rewritten into manual sentiment labels.

The final report must state that the RSS source is a retained recent-review
window and that the audit is small, targeted, and single-annotator with a 15%
recheck.
