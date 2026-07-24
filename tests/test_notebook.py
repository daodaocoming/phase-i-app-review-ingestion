from __future__ import annotations

import csv
from pathlib import Path

import pytest

nbformat = pytest.importorskip("nbformat")
nbclient = pytest.importorskip("nbclient")

from scripts.build_ds_dataset import load_issue_keywords
from src.feature_engineering import FEATURE_COLUMNS, build_feature_row


ROOT = Path(__file__).resolve().parents[1]


def test_baseline_notebook_executes_from_start_to_finish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, keywords = load_issue_keywords(ROOT / "config/issue_keywords_v1.yaml")
    source_template = {
        "app_name": "Notebook Fixture",
        "vertical_name": "Testing",
        "storefront": "us",
        "title": "Fixture",
        "detected_language": "en",
    }
    sources = [
        {
            **source_template,
            "review_id": 1,
            "source_review_id": "fixture-1",
            "rating": 1,
            "body": "Terrible crash after login",
            "published_at": "2026-01-01T10:00:00Z",
        },
        {
            **source_template,
            "review_id": 2,
            "source_review_id": "fixture-2",
            "rating": 3,
            "body": "Some parts are great but other parts are terrible",
            "published_at": "2026-02-02T11:00:00Z",
        },
        {
            **source_template,
            "review_id": 3,
            "source_review_id": "fixture-3",
            "rating": 5,
            "body": "Excellent update",
            "published_at": "2026-03-03T12:00:00Z",
        },
    ]
    flags = [
        {"rating_text_mismatch"},
        set(),
        set(),
    ]
    rows = [
        build_feature_row(source, quality_flags=row_flags, keyword_signals=keywords)
        for source, row_flags in zip(sources, flags, strict=True)
    ]
    dataset_path = tmp_path / "notebook_fixture.csv"
    with dataset_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FEATURE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    monkeypatch.setenv("DS_DATASET_PATH", str(dataset_path))
    monkeypatch.setenv("MPLBACKEND", "Agg")
    monkeypatch.setenv("IPYTHONDIR", str(tmp_path / "ipython"))
    notebook = nbformat.read(
        ROOT / "notebooks/weak_label_baseline_v1.ipynb",
        as_version=4,
    )
    client = nbclient.NotebookClient(
        notebook,
        timeout=120,
        kernel_name="python3",
        resources={"metadata": {"path": str(ROOT)}},
    )
    executed = client.execute()
    code_cells = [cell for cell in executed.cells if cell.cell_type == "code"]
    assert code_cells
    assert all(cell.execution_count is not None for cell in code_cells)

