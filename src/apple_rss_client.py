from __future__ import annotations

import logging
import time
from typing import Any

import requests

from src.models import FetchResult


class AppleRSSClientError(RuntimeError):
    pass


class AppleRSSClient:
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    URL_TEMPLATE = (
        "https://itunes.apple.com/{storefront}/rss/customerreviews/"
        "page={page}/id={app_id}/sortby=mostrecent/json"
    )

    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        retry_count: int = 3,
        delay_seconds: float = 1.0,
        session: requests.Session | None = None,
        sleeper: Any = time.sleep,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.retry_count = retry_count
        self.delay_seconds = delay_seconds
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": "ScienciaAI-PhaseI-ResearchPrototype/1.0 (low-frequency public RSS ingestion)"}
        )
        self.sleeper = sleeper
        self.logger = logging.getLogger(__name__)

    def build_url(self, app_id: str, storefront: str, page: int) -> str:
        if page < 1:
            raise ValueError("page must be at least 1")
        return self.URL_TEMPLATE.format(storefront=storefront.lower(), page=page, app_id=app_id)

    def fetch_page(self, *, app_id: str, app_name: str, storefront: str, page: int) -> FetchResult:
        url = self.build_url(app_id, storefront, page)
        last_error: Exception | None = None

        if self.delay_seconds:
            self.sleeper(self.delay_seconds)

        for attempt in range(1, self.retry_count + 1):
            started = time.monotonic()
            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
                elapsed = time.monotonic() - started
                if response.status_code in self.RETRYABLE_STATUS_CODES:
                    raise requests.HTTPError(f"temporary HTTP {response.status_code}", response=response)
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise AppleRSSClientError(f"Malformed JSON from {url}: {exc}") from exc
                if not isinstance(payload, dict):
                    raise AppleRSSClientError(f"Expected a JSON object from {url}")

                self.logger.info(
                    "apple_page_fetched",
                    extra={
                        "app_name": app_name,
                        "app_id": app_id,
                        "page": page,
                        "status": response.status_code,
                        "elapsed_seconds": round(elapsed, 3),
                    },
                )
                return FetchResult(
                    url=url,
                    page_number=page,
                    status_code=response.status_code,
                    elapsed_seconds=elapsed,
                    payload=payload,
                    raw_text=response.text,
                )
            except (requests.RequestException, AppleRSSClientError) as exc:
                last_error = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                self.logger.warning(
                    "apple_page_fetch_failed",
                    extra={
                        "app_name": app_name,
                        "app_id": app_id,
                        "page": page,
                        "status": status,
                        "error": str(exc),
                    },
                )
                non_retryable_http = status is not None and status not in self.RETRYABLE_STATUS_CODES
                if isinstance(exc, AppleRSSClientError) or non_retryable_http or attempt == self.retry_count:
                    break
                self.sleeper(self.delay_seconds * (2 ** (attempt - 1)))

        raise AppleRSSClientError(
            f"Unable to fetch app={app_name} id={app_id} page={page}: {last_error}"
        ) from last_error
