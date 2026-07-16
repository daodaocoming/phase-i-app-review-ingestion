from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AppConfig:
    app_id: str
    app_name: str
    vertical: str
    storefront: str = "us"
    expected_language: str = "en"
    enabled: bool = True
    notes: str = ""


@dataclass(frozen=True)
class PipelineSettings:
    max_pages_per_app: int = 2
    timeout_seconds: float = 15.0
    retry_count: int = 3
    delay_seconds: float = 1.0


@dataclass(frozen=True)
class ProjectConfig:
    apps: list[AppConfig]
    settings: PipelineSettings


@dataclass(frozen=True)
class FetchResult:
    url: str
    page_number: int
    status_code: int
    elapsed_seconds: float
    payload: dict[str, Any]
    raw_text: str


@dataclass(frozen=True)
class ParsedReview:
    source_review_id: str | None
    rating_raw: Any
    title_raw: Any
    body_raw: Any
    author_label_raw: Any
    author_uri_raw: Any
    published_at_raw: Any
    app_version_raw: Any
    review_url_raw: Any
    vote_count_raw: Any
    vote_sum_raw: Any
    raw_record: dict[str, Any]
    parser_fallback_used: bool = False


@dataclass(frozen=True)
class NormalizedReview:
    source_platform: str
    source_endpoint: str
    storefront: str
    source_app_id: str
    app_name: str
    vertical: str
    source_review_id: str | None
    review_url: str | None
    author_label: str | None
    author_uri: str | None
    rating: int | None
    title: str | None
    body: str
    app_version: str | None
    published_at: str | None
    vote_count: int | None
    vote_sum: int | None
    raw_payload_hash: str
    ingested_at: str
    detected_language: str
    body_char_count: int
    body_token_estimate: int
    parser_fallback_used: bool
    raw_record: dict[str, Any]


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QualityFlag:
    flag_type: str
    severity: str
    details: str


@dataclass
class AppRunStats:
    pages_requested: int = 0
    pages_fetched: int = 0
    reviews_parsed: int = 0
    reviews_inserted: int = 0
    reviews_updated: int = 0
    reviews_rejected: int = 0
    flags_created: int = 0
    failed_requests: int = 0
    flag_counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class RunStats:
    apps_attempted: int = 0
    pages_fetched: int = 0
    raw_pages_saved: int = 0
    reviews_parsed: int = 0
    reviews_inserted: int = 0
    reviews_updated: int = 0
    reviews_rejected: int = 0
    flags_created: int = 0
    failed_requests: int = 0
    flag_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, int]:
        return self.__dict__.copy()
