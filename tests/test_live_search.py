from __future__ import annotations

import csv
from pathlib import Path

import pytest

from agent import live_search
from scripts.build_tantivy_index import build


def _write_papers_csv(path: Path) -> None:
    rows = [
        {
            "id": "p1",
            "doi": "10.1/met",
            "pmid": "1",
            "pmcid": "",
            "arxiv_id": "",
            "openalex_id": "W1",
            "title": "Metformin improves survival in an aging cohort",
            "abstract": "A metformin trial reports survival and mortality outcomes.",
            "publication_year": "2022",
            "journal_name": "Journal A",
            "type": "article",
            "cited_by_count": "250",
        },
        {
            "id": "p2",
            "doi": "10.1/wage",
            "pmid": "",
            "pmcid": "",
            "arxiv_id": "",
            "openalex_id": "W2",
            "title": "Minimum wage employment effects across service firms",
            "abstract": "Minimum wage policy and employment outcomes.",
            "publication_year": "2021",
            "journal_name": "Journal B",
            "type": "article",
            "cited_by_count": "100",
        },
        {
            "id": "p3",
            "doi": "10.1/blank",
            "pmid": "",
            "pmcid": "",
            "arxiv_id": "",
            "openalex_id": "W3",
            "title": "",
            "abstract": "Skipped because title is empty.",
            "publication_year": "2020",
            "journal_name": "Journal C",
            "type": "article",
            "cited_by_count": "1",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_tantivy_index_builds_and_searches_fixture(tmp_path: Path) -> None:
    pytest.importorskip("tantivy")
    csv_path = tmp_path / "papers.csv"
    index_path = tmp_path / "tantivy"
    _write_papers_csv(csv_path)

    meta = build(csv_path, index_path, batch_size=1, replace=True)
    hits = live_search.search(
        "metformin survival", fields=["title", "abstract"], k=5,
        index_path=index_path,
    )

    assert meta["rows_read"] == 3
    assert meta["rows_indexed"] == 2
    assert meta["rows_skipped_empty_title"] == 1
    assert hits
    assert hits[0].paper_id == "p1"
    assert hits[0].abstract == ""
    assert hits[0].publication_year == 2022
    assert (index_path / "researka_index_meta.json").exists()


def test_paper_record_projects_to_existing_fact_shape() -> None:
    record = live_search.PaperRecord(
        paper_id="p1",
        title="Minimum wage employment effects",
        abstract="",
        publication_year=2021,
        cited_by_count=42,
        paper_type="article",
        doi="10.1/wage",
        journal_name="Economics Journal",
    )

    fact = live_search.paper_to_fact(record, "minimum_wage")

    assert fact["_tier"] == "live_search"
    assert fact["fact_id"] == "live:p1"
    assert fact["source_paper"]["doi"] == "10.1/wage"
    assert fact["source_paper"]["title"] == "Minimum wage employment effects"
    assert fact["population"] == "minimum_wage"
    assert fact["intervention"] == "minimum_wage"
