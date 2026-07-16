-- Latest ingestion runs.
SELECT
    ingestion_run_id,
    run_status,
    started_at,
    completed_at,
    apps_requested,
    pages_fetched,
    reviews_parsed,
    reviews_inserted,
    reviews_updated,
    reviews_rejected
FROM ingestion_runs
ORDER BY started_at DESC
LIMIT 20;

-- App-level outcomes for the latest validation runs.
SELECT
    x.ingestion_run_id,
    a.app_name,
    v.vertical_name,
    x.run_status,
    x.pages_requested,
    x.pages_fetched,
    x.reviews_parsed,
    x.reviews_inserted,
    x.reviews_updated,
    x.reviews_rejected,
    x.flags_created,
    x.failed_requests,
    x.error_summary
FROM ingestion_run_app_stats x
JOIN apps a ON a.app_id = x.app_id
JOIN verticals v ON v.vertical_id = a.vertical_id
ORDER BY x.ingestion_run_id DESC, a.app_name;

-- Raw page parse status.
SELECT
    parse_status,
    COUNT(*) AS page_count
FROM raw_feed_pages
GROUP BY parse_status
ORDER BY page_count DESC;

-- Rejected records by reason.
SELECT
    rejection_reason,
    COUNT(*) AS rejected_count
FROM rejected_review_records
GROUP BY rejection_reason
ORDER BY rejected_count DESC;

-- Loaded reviews by vertical and app.
SELECT
    v.vertical_name,
    a.app_name,
    s.storefront,
    COUNT(*) AS review_count,
    MIN(r.published_at) AS earliest_review_at,
    MAX(r.published_at) AS latest_review_at
FROM reviews r
JOIN apps a
    ON a.app_id = r.app_id
JOIN verticals v
    ON v.vertical_id = a.vertical_id
JOIN app_storefronts s
    ON s.app_storefront_id = r.app_storefront_id
GROUP BY v.vertical_name, a.app_name, s.storefront
ORDER BY review_count DESC;

-- Rating distribution.
SELECT
    rating,
    COUNT(*) AS review_count
FROM reviews
GROUP BY rating
ORDER BY rating;

-- Detected language distribution.
SELECT
    COALESCE(detected_language, 'unknown') AS detected_language,
    COUNT(*) AS review_count
FROM reviews
GROUP BY COALESCE(detected_language, 'unknown')
ORDER BY review_count DESC;

-- Quality flags by type and severity.
SELECT
    flag_type,
    flag_severity,
    COUNT(*) AS flag_count
FROM review_quality_flags
GROUP BY flag_type, flag_severity
ORDER BY flag_count DESC;

-- Loaded records missing optional reviewer metadata.
SELECT
    COUNT(*) AS reviews_without_reviewer
FROM reviews
WHERE reviewer_id IS NULL;

-- Duplicate review body candidates within the same app/storefront.
SELECT
    app_id,
    app_storefront_id,
    body,
    COUNT(*) AS duplicate_count
FROM reviews
GROUP BY app_id, app_storefront_id, body
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC
LIMIT 50;

-- Training-ready sample.
SELECT
    review_id,
    source_review_id,
    app_name,
    vertical_name,
    storefront,
    rating,
    title,
    body,
    published_at,
    detected_language
FROM training_review_dataset
WHERE detected_language = 'en'
  AND has_error_flag = 0
ORDER BY published_at DESC
LIMIT 100;
