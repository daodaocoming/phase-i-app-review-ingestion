# Step 1: Identifying a Suitable Data Source

## Recommendation

The recommended Phase I source is the Apple App Store public customer-review RSS/JSON feed.

This is the strongest prototype candidate because it provides public, structured user-generated reviews across many non-gaming commercial domains while still keeping the technical scope manageable.

## Why This Source Fits the Project

The project needs review data that can support sentiment understanding, product feedback analysis, and downstream model training. App Store reviews are a good fit because each review typically includes:

- app context
- 1 to 5 star rating
- review title
- review body
- public author label
- published or updated timestamp
- app version
- country/storefront context

This gives the pipeline both text and natural weak labels. The text helps train or evaluate sentiment and topic models, while the rating gives a structured signal that can be used for sampling, quality checks, dashboards, and weak supervision.

## Prototype Scope

The system should not attempt to collect the full App Store. The Phase I source scope should be:

- 30 to 50 manually selected apps
- roughly 6 commercial verticals
- United States storefront first
- English-first review filtering
- recent reviews available through the RSS feed

Candidate verticals:

- food delivery and retail
- banking and fintech
- airlines, hotels, and travel
- ride-hailing and logistics
- education and productivity
- fitness, health, and wellness
- social, subscription, and consumer software

This remains a single-source prototype while avoiding the narrowness of a gaming-only review ecosystem.

## Endpoint Pattern

The ingestion process will use the public RSS/JSON customer-review feed:

```text
https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json
```

Example:

```text
https://itunes.apple.com/us/rss/customerreviews/page=1/id=284882215/sortby=mostrecent/json
```

## Selection Criteria Review

| Criterion | Assessment |
| --- | --- |
| Sufficient volume | Strong for popular consumer apps; should be verified during feasibility testing |
| Public accessibility | Public RSS/JSON feed can be requested without login |
| Stable structure | Structured JSON feed is easier to parse than HTML |
| Sentiment relevance | Strong: each review includes text plus a 1 to 5 star rating |
| Domain breadth | Strong: apps span many commercial verticals |
| Prototype feasibility | Strong: small cohort and pagination-limited fetches are practical |
| Long-term guarantee | Moderate risk: the feed should be treated as a legacy public endpoint, not a guaranteed modern production API |

## Important Caveat

The modern App Store Connect API is intended for app owners and developers. It is not suitable for collecting arbitrary third-party app reviews across the App Store.

For this prototype, the correct target is the public customer-review RSS/JSON feed. This should be positioned as:

```text
Best prototype candidate, conditional on a short feasibility test.
```

It should not be positioned as:

```text
Guaranteed production-grade long-term source.
```

## Feasibility Gate

Before building the full cohort, run a small feasibility check:

1. Choose 3 apps across 3 verticals.
2. Fetch pages 1 and 2 from the US storefront.
3. Confirm review ids, ratings, title, body, author labels, timestamps, app versions, and pagination links.
4. Confirm that repeated fetches produce stable identifiers.
5. Confirm that the returned review volume is enough for a Phase I prototype.
6. Confirm that source usage remains consistent with current legal and policy guidance.

## Final Source Decision

Apple App Store public customer-review RSS should be used for Phase I because it gives the team a practical, structured, multi-domain review source with natural sentiment labels. The source has enough richness to support meaningful downstream modeling work, while still being simple enough to teach, implement, validate, and maintain as the first entry point of the broader data pipeline.
