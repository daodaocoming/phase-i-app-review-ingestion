Subject: Weak-label quality audit completed

Hi John,

I completed the weak-label quality audit on a stratified sample of 150 reviews
from the 1,300-review feature dataset. The sample included negative, neutral,
and positive labels; flagged and unflagged reviews; all 12 Apps; all 11
verticals; the main noise reasons; and the issue signals. As expected, there
was no neutral-unflagged stratum because every three-star review is marked with
`neutral_rating`.

For quality control, I completed a 23-review single-annotator recheck. The
three core annotation fields had 100% agreement with kappa=1.00. Issue-signal
and broad-term relevance had 99.6% agreement overall, with one changed issue
relevance judgment.

The main findings are:

- Rating/text agreement was 93.3% for negative labels overall and 55.0% for
  neutral labels. Positive labels were 76.9% overall, but the unflagged
  positive stratum was 80.0%.
- Neutral reviews were highly ambiguous: 52.5% were manually judged mixed.
- Flagged reviews had a 37.5% disagreement-or-unclear rate versus 12.5% for
  unflagged reviews.
- `neutral_rating` and the non-English/unknown-language flag were useful
  warnings. `rating_text_mismatch`, `mixed_sentiment_keywords`, and
  `too_short_review` had low warning validity in this sample.
- The strongest issue signals were payment/billing, ads, update/version,
  delivery/service, and usability/navigation. Performance/crash and
  login/account should be refined. The broad terms `service` and `account`
  were reasonably reliable, while `version` was less reliable.

Based on the audit, I propose using only English-interpretable, non-short,
unflagged negative and positive reviews for a simple binary baseline, while
excluding neutral reviews and holding the audited 150 reviews out of training.
The performance/crash and login/account rules, plus the `version` term, should
be refined before they are used as modeling features. I have not expanded the
modeling scope beyond this baseline decision.

The detailed report and machine-readable summary are included in the PR:
`outputs/ds_v1/weak_label_audit_report.md` and
`outputs/ds_v1/weak_label_audit_report.json`.

Best,
Doris
