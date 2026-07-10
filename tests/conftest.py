from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def sample_payload() -> dict:
    path = Path(__file__).parent / "fixtures" / "sample_apple_response.json"
    return json.loads(path.read_text(encoding="utf-8"))
