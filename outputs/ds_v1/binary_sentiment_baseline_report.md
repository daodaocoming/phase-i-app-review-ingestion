# Filtered Binary Sentiment Baseline

This is a fixed, transparent baseline for testing whether carefully filtered rating-derived weak labels support reproducible modeling. It is not a tuned production model.

## Provenance and filtering

Input SHA-256: `de4a00e7a7572334507c629ad2b3c2546a452f64a997396ae7e638fb25d12b52`  
Issue configuration: `issue_keywords_v2`  
Seed: `20260730`; split: `StratifiedGroupKFold first held-out fold`

| Step | Removed | Remaining | Negative | Positive |
|---|---:|---:|---:|---:|
| audit_excluded | 151 | 1149 | 621 | 486 |
| binary_labels_only | 42 | 1107 | 621 | 486 |
| english_interpretable_proxy | 26 | 1081 | 612 | 469 |
| non_short | 49 | 1032 | 602 | 430 |
| unflagged | 30 | 1002 | 575 | 427 |

## Class and App distribution

### Filtered Primary

Rows: **1002**; classes: `{'negative': 575, 'positive': 427}`

| App | Counts by label |
|---|---|
| Airbnb | `{'negative': 79, 'positive': 8}` |
| Amazon | `{'negative': 66, 'positive': 17}` |
| DoorDash | `{'negative': 36, 'positive': 43}` |
| Duolingo | `{'negative': 25, 'positive': 96}` |
| Facebook | `{'negative': 40, 'positive': 31}` |
| Gmail | `{'negative': 56, 'positive': 17}` |
| Google Maps | `{'negative': 58, 'positive': 25}` |
| Headspace | `{'negative': 50, 'positive': 14}` |
| Instagram | `{'negative': 71, 'positive': 40}` |
| Spotify | `{'negative': 12, 'positive': 55}` |
| Uber | `{'negative': 14, 'positive': 69}` |
| Venmo | `{'negative': 68, 'positive': 12}` |

### Training

Rows: **801**; classes: `{'negative': 460, 'positive': 341}`

| App | Counts by label |
|---|---|
| Airbnb | `{'negative': 63, 'positive': 7}` |
| Amazon | `{'negative': 53, 'positive': 13}` |
| DoorDash | `{'negative': 29, 'positive': 34}` |
| Duolingo | `{'negative': 20, 'positive': 77}` |
| Facebook | `{'negative': 32, 'positive': 24}` |
| Gmail | `{'negative': 45, 'positive': 13}` |
| Google Maps | `{'negative': 47, 'positive': 20}` |
| Headspace | `{'negative': 40, 'positive': 11}` |
| Instagram | `{'negative': 56, 'positive': 32}` |
| Spotify | `{'negative': 10, 'positive': 44}` |
| Uber | `{'negative': 11, 'positive': 56}` |
| Venmo | `{'negative': 54, 'positive': 10}` |

### Weak Label Holdout

Rows: **201**; classes: `{'negative': 115, 'positive': 86}`

| App | Counts by label |
|---|---|
| Airbnb | `{'negative': 16, 'positive': 1}` |
| Amazon | `{'negative': 13, 'positive': 4}` |
| DoorDash | `{'negative': 7, 'positive': 9}` |
| Duolingo | `{'negative': 5, 'positive': 19}` |
| Facebook | `{'negative': 8, 'positive': 7}` |
| Gmail | `{'negative': 11, 'positive': 4}` |
| Google Maps | `{'negative': 11, 'positive': 5}` |
| Headspace | `{'negative': 10, 'positive': 3}` |
| Instagram | `{'negative': 15, 'positive': 8}` |
| Spotify | `{'negative': 2, 'positive': 11}` |
| Uber | `{'negative': 3, 'positive': 13}` |
| Venmo | `{'negative': 14, 'positive': 2}` |

### Human Reviewed Diagnostic

Rows: **99**; classes: `{'negative': 69, 'positive': 30}`

| App | Counts by label |
|---|---|
| Airbnb | `{'negative': 6}` |
| Amazon | `{'negative': 7, 'positive': 1}` |
| DoorDash | `{'negative': 3, 'positive': 2}` |
| Duolingo | `{'negative': 4, 'positive': 4}` |
| Facebook | `{'negative': 2, 'positive': 4}` |
| Gmail | `{'negative': 10}` |
| Google Maps | `{'negative': 6}` |
| Headspace | `{'negative': 8}` |
| Instagram | `{'negative': 8, 'positive': 4}` |
| Spotify | `{'negative': 5, 'positive': 7}` |
| Uber | `{'negative': 1, 'positive': 6}` |
| Venmo | `{'negative': 9, 'positive': 2}` |

## Metrics

Rating, rating groups, `neutral_rating`, weak-label metadata, quality flags, App, and other rating-derived fields were excluded from predictors.

| Model | Evaluation set | Macro F1 | Balanced accuracy | Negative P/R | Positive P/R |
|---|---|---:|---:|---|---|
| tfidf_only | weak_label_holdout | 0.890 | 0.882 | 0.862/0.974 | 0.958/0.791 |
| tfidf_only | human_reviewed_diagnostic | 0.953 | 0.962 | 0.985/0.957 | 0.906/0.967 |
| tfidf_plus_issue_signals | weak_label_holdout | 0.870 | 0.863 | 0.852/0.948 | 0.918/0.779 |
| tfidf_plus_issue_signals | human_reviewed_diagnostic | 0.919 | 0.930 | 0.970/0.928 | 0.848/0.933 |

Metric delta (TF-IDF + v2 signals minus TF-IDF):

- `weak_label_holdout`: macro F1 `-0.020`, balanced accuracy `-0.019`
- `human_reviewed_diagnostic`: macro F1 `-0.035`, balanced accuracy `-0.031`

## Error review

### Weak Label Holdout

| App | True | Predicted | Margin | Text-only correct | Signals | Excerpt |
|---|---|---|---:|---|---|---|
| Google Maps | positive | negative | -1.879 | False | update_version|usability_navigation | My preferred Navigation App Generally, it is my preferred Navigation app. However, their most recent update has a few bugs. One of the most annoying ones is how their “Add Stop” feature no longer works correctly. It says… |
| DoorDash | positive | negative | -1.481 | False | payment_billing | Fee are too high and discount codes are never offered. Restaurants should deliver |
| Duolingo | positive | negative | -1.264 | False | login_account | A little problem I’m trying to get the account for my iPad but I forgot the password. When I press forgot password? I put in my email but then I would have no emails from Duolingo! Please help me as soon as possible! I’m… |
| Duolingo | negative | positive | +0.320 | False | usability_navigation | Great interface, exhausting add ons The best app for languages the widgets, gems, avatars, reminders, upgrades, notifications, unlockables etc etc are too much! I have premium, let me just hop on and learn languages. Pra… |
| DoorDash | negative | positive | +0.183 | False | — | adds on so much money in the end SO EXPENSIVE |
| Instagram | negative | positive | +0.177 | False | — | Me desactivan mis cuentas sin razón alguna Instagram: Me dirijo a ustedes con mucho respeto para solicitar una revisión a mis cuentas ya que fueron deshabilitadas sin previo aviso y yo no infringí ninguna norma y conside… |

### Human Reviewed Diagnostic

| App | True | Predicted | Margin | Text-only correct | Signals | Excerpt |
|---|---|---|---:|---|---|---|
| Spotify | negative | positive | +0.355 | False | — | I don’t like. I don’t like when I have a playlist and you can’t choose YouTube is better than spiteful |
| Amazon | positive | negative | -0.174 | True | payment_billing | The greatest one ⭐⭐⭐⭐⭐ Excellent product! It arrived on time, was exactly as described, and exceeded my expectations. The quality is great, it’s easy to use, and it works perfectly. I’m very happy with my purchase and wo… |
| DoorDash | negative | positive | +0.116 | True | delivery_service | Pat natale Always give driver wrong directions to my house |
| Spotify | positive | negative | -0.115 | True | ads|usability_navigation | The best app Spotify is one of the best platforms for listening to music and podcasts. It has a huge catalog, personalized recommendations and an easy-to-use interface. You can enjoy the free version with ads or subscrib… |
| Spotify | negative | positive | +0.088 | True | — | You already know Spotify is bad. I don’t need to tell you Spotify is horrible. You must already know. |

## Limitations

The primary holdout measures agreement with filtered weak labels, not independent sentiment truth. The audit diagnostic contains only clear positive/negative judgments and excludes mixed or unclear cases; it is small, targeted, and single-annotator. Issue rules are provisional, versioned candidates rather than permanently validated features.
