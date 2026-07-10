PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS verticals (
    vertical_id INTEGER PRIMARY KEY,
    vertical_name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS apps (
    app_id INTEGER PRIMARY KEY,
    source_platform TEXT NOT NULL DEFAULT 'apple_app_store',
    source_app_id TEXT NOT NULL,
    app_name TEXT NOT NULL,
    vertical_id INTEGER NOT NULL,
    developer_name TEXT,
    app_store_url TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vertical_id) REFERENCES verticals(vertical_id),
    UNIQUE (source_platform, source_app_id)
);

CREATE TABLE IF NOT EXISTS app_storefronts (
    app_storefront_id INTEGER PRIMARY KEY,
    app_id INTEGER NOT NULL,
    storefront TEXT NOT NULL,
    expected_language TEXT NOT NULL DEFAULT 'en',
    rss_url_template TEXT NOT NULL,
    max_pages_per_run INTEGER NOT NULL DEFAULT 10 CHECK (max_pages_per_run BETWEEN 1 AND 10),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    last_successful_ingestion_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (app_id) REFERENCES apps(app_id),
    UNIQUE (app_id, storefront),
    UNIQUE (app_storefront_id, app_id)
);

CREATE TABLE IF NOT EXISTS reviewers (
    reviewer_id INTEGER PRIMARY KEY,
    source_platform TEXT NOT NULL DEFAULT 'apple_app_store',
    author_uri TEXT,
    author_label TEXT,
    author_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_platform, author_fingerprint)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    ingestion_run_id INTEGER PRIMARY KEY,
    source_platform TEXT NOT NULL DEFAULT 'apple_app_store',
    run_status TEXT NOT NULL CHECK (run_status IN ('running', 'completed', 'completed_with_errors', 'failed')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    config_snapshot TEXT,
    apps_requested INTEGER NOT NULL DEFAULT 0 CHECK (apps_requested >= 0),
    pages_fetched INTEGER NOT NULL DEFAULT 0 CHECK (pages_fetched >= 0),
    reviews_parsed INTEGER NOT NULL DEFAULT 0 CHECK (reviews_parsed >= 0),
    reviews_inserted INTEGER NOT NULL DEFAULT 0 CHECK (reviews_inserted >= 0),
    reviews_updated INTEGER NOT NULL DEFAULT 0 CHECK (reviews_updated >= 0),
    reviews_rejected INTEGER NOT NULL DEFAULT 0 CHECK (reviews_rejected >= 0),
    flags_created INTEGER NOT NULL DEFAULT 0 CHECK (flags_created >= 0),
    failed_requests INTEGER NOT NULL DEFAULT 0 CHECK (failed_requests >= 0),
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS raw_feed_pages (
    raw_feed_page_id INTEGER PRIMARY KEY,
    ingestion_run_id INTEGER NOT NULL,
    app_storefront_id INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    page_number INTEGER NOT NULL CHECK (page_number >= 1),
    http_status INTEGER,
    fetched_at TEXT NOT NULL,
    response_hash TEXT NOT NULL,
    response_body TEXT NOT NULL,
    raw_file_path TEXT NOT NULL,
    parse_status TEXT NOT NULL DEFAULT 'pending' CHECK (parse_status IN ('pending', 'parsed', 'parse_error', 'skipped')),
    parse_error TEXT,
    FOREIGN KEY (ingestion_run_id) REFERENCES ingestion_runs(ingestion_run_id),
    FOREIGN KEY (app_storefront_id) REFERENCES app_storefronts(app_storefront_id),
    UNIQUE (ingestion_run_id, app_storefront_id, page_number)
);

CREATE TABLE IF NOT EXISTS reviews (
    review_id INTEGER PRIMARY KEY,
    source_platform TEXT NOT NULL DEFAULT 'apple_app_store',
    source_review_id TEXT NOT NULL,
    app_id INTEGER NOT NULL,
    app_storefront_id INTEGER NOT NULL,
    reviewer_id INTEGER,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title TEXT,
    body TEXT NOT NULL CHECK (length(trim(body)) > 0),
    app_version TEXT,
    review_url TEXT,
    source_endpoint TEXT NOT NULL,
    published_at TEXT NOT NULL,
    detected_language TEXT,
    body_char_count INTEGER CHECK (body_char_count IS NULL OR body_char_count >= 0),
    body_token_estimate INTEGER CHECK (body_token_estimate IS NULL OR body_token_estimate >= 0),
    vote_count INTEGER CHECK (vote_count IS NULL OR vote_count >= 0),
    vote_sum INTEGER CHECK (vote_sum IS NULL OR vote_sum >= 0),
    raw_payload_hash TEXT,
    first_raw_feed_page_id INTEGER NOT NULL,
    last_raw_feed_page_id INTEGER NOT NULL,
    first_seen_run_id INTEGER NOT NULL,
    last_seen_run_id INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (app_id) REFERENCES apps(app_id),
    FOREIGN KEY (app_storefront_id, app_id) REFERENCES app_storefronts(app_storefront_id, app_id),
    FOREIGN KEY (reviewer_id) REFERENCES reviewers(reviewer_id),
    FOREIGN KEY (first_raw_feed_page_id) REFERENCES raw_feed_pages(raw_feed_page_id),
    FOREIGN KEY (last_raw_feed_page_id) REFERENCES raw_feed_pages(raw_feed_page_id),
    FOREIGN KEY (first_seen_run_id) REFERENCES ingestion_runs(ingestion_run_id),
    FOREIGN KEY (last_seen_run_id) REFERENCES ingestion_runs(ingestion_run_id),
    UNIQUE (source_platform, app_storefront_id, source_review_id)
);

CREATE TABLE IF NOT EXISTS rejected_review_records (
    rejected_review_record_id INTEGER PRIMARY KEY,
    ingestion_run_id INTEGER NOT NULL,
    raw_feed_page_id INTEGER,
    app_storefront_id INTEGER NOT NULL,
    source_review_id TEXT,
    rejection_reason TEXT NOT NULL,
    rejection_details TEXT,
    raw_payload_hash TEXT,
    raw_payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (ingestion_run_id) REFERENCES ingestion_runs(ingestion_run_id),
    FOREIGN KEY (raw_feed_page_id) REFERENCES raw_feed_pages(raw_feed_page_id),
    FOREIGN KEY (app_storefront_id) REFERENCES app_storefronts(app_storefront_id)
);

CREATE TABLE IF NOT EXISTS review_quality_flags (
    review_quality_flag_id INTEGER PRIMARY KEY,
    review_id INTEGER NOT NULL,
    flag_type TEXT NOT NULL,
    flag_severity TEXT NOT NULL CHECK (flag_severity IN ('info', 'warning', 'error')),
    flag_details TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (review_id) REFERENCES reviews(review_id),
    UNIQUE (review_id, flag_type)
);

CREATE INDEX IF NOT EXISTS idx_apps_vertical_id ON apps(vertical_id);
CREATE INDEX IF NOT EXISTS idx_app_storefronts_storefront ON app_storefronts(storefront);
CREATE INDEX IF NOT EXISTS idx_raw_feed_pages_run ON raw_feed_pages(ingestion_run_id);
CREATE INDEX IF NOT EXISTS idx_reviews_app_published ON reviews(app_id, published_at);
CREATE INDEX IF NOT EXISTS idx_reviews_storefront_published ON reviews(app_storefront_id, published_at);
CREATE INDEX IF NOT EXISTS idx_reviews_rating ON reviews(rating);
CREATE INDEX IF NOT EXISTS idx_reviews_language ON reviews(detected_language);
CREATE INDEX IF NOT EXISTS idx_rejected_review_records_run ON rejected_review_records(ingestion_run_id);
CREATE INDEX IF NOT EXISTS idx_review_quality_flags_review ON review_quality_flags(review_id);

CREATE VIEW IF NOT EXISTS training_review_dataset AS
SELECT
    r.review_id,
    r.source_platform,
    r.source_review_id,
    a.source_app_id,
    a.app_name,
    v.vertical_name,
    s.storefront,
    r.rating,
    r.title,
    r.body,
    r.app_version,
    r.published_at,
    r.detected_language,
    r.body_char_count,
    r.body_token_estimate,
    r.vote_count,
    r.vote_sum,
    r.first_seen_at,
    r.last_seen_at,
    r.first_seen_run_id,
    r.last_seen_run_id,
    r.first_raw_feed_page_id,
    r.last_raw_feed_page_id,
    CASE WHEN EXISTS (
        SELECT 1 FROM review_quality_flags qf
        WHERE qf.review_id = r.review_id AND qf.flag_severity = 'error'
    ) THEN 1 ELSE 0 END AS has_error_flag
FROM reviews r
JOIN apps a ON a.app_id = r.app_id
JOIN verticals v ON v.vertical_id = a.vertical_id
JOIN app_storefronts s ON s.app_storefront_id = r.app_storefront_id;
