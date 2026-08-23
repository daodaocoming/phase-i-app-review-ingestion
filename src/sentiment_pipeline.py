"""Shared preprocessing and frozen TF-IDF sentiment model definition."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline


DEFAULT_SEED = 20260730
TFIDF_KWARGS = {
    "ngram_range": (1, 2),
    "min_df": 2,
    "max_df": 0.95,
    "sublinear_tf": True,
    "lowercase": False,
}


def normalize_review_text(title: str = "", body: str = "") -> str:
    """Apply the exact text normalization contract used by training and inference."""

    combined = f"{title}\n{body}".strip()
    combined = unicodedata.normalize("NFKC", combined).casefold()
    return re.sub(r"\s+", " ", combined).strip()


class ReviewTextNormalizer(BaseEstimator, TransformerMixin):
    """Normalize raw strings, or mappings containing ``title`` and ``body``."""

    def fit(self, X: Any, y: Any = None) -> "ReviewTextNormalizer":
        return self

    def transform(self, X: Any) -> list[str]:
        normalized: list[str] = []
        for value in X:
            if isinstance(value, Mapping):
                normalized.append(
                    normalize_review_text(
                        str(value.get("title", "")),
                        str(value.get("body", "")),
                    )
                )
            else:
                normalized.append(normalize_review_text("", "" if value is None else str(value)))
        return normalized


def build_sentiment_pipeline(seed: int = DEFAULT_SEED) -> Pipeline:
    """Build the frozen final TF-IDF-only sentiment pipeline."""

    return Pipeline(
        steps=[
            ("normalize", ReviewTextNormalizer()),
            ("tfidf", TfidfVectorizer(**TFIDF_KWARGS)),
            (
                "classifier",
                LogisticRegression(
                    class_weight="balanced",
                    C=1.0,
                    solver="liblinear",
                    max_iter=1000,
                    random_state=seed,
                ),
            ),
        ]
    )

