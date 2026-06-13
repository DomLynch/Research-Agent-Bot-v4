"""Flag-gated Tantivy live-search adapter.

Indexes the exported paper corpus as title+abstract BM25 and returns compact
paper records. Runtime callers must opt in with LIVE_SEARCH=1 and point
LIVE_SEARCH_INDEX_PATH at an existing index; the legacy Tier-2 path remains the
default until parity is proven.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

_DEFAULT_FIELDS = ("title", "abstract")
_ANALYZER = "researka_en"
_WORD = re.compile(r"[a-z0-9]+")


class LiveSearchUnavailable(RuntimeError):
    """Raised when live search was requested but the local index is unusable."""


@dataclass(frozen=True, slots=True)
class PaperRecord:
    paper_id: str
    title: str
    abstract: str
    publication_year: int | None = None
    cited_by_count: int = 0
    paper_type: str = ""
    doi: str = ""
    pmid: str = ""
    pmcid: str = ""
    arxiv_id: str = ""
    openalex_id: str = ""
    journal_name: str = ""
    score: float = 0.0


def enabled() -> bool:
    return os.environ.get("LIVE_SEARCH", "").strip().lower() in {"1", "true", "yes", "on"}


def default_index_path() -> Path:
    raw = os.environ.get("LIVE_SEARCH_INDEX_PATH", "").strip()
    return Path(raw or "/mnt/HC_Volume_106011525/search/tantivy_papers")


def _tantivy() -> Any:
    try:
        import tantivy
    except ImportError as exc:
        raise LiveSearchUnavailable("tantivy package is not installed") from exc
    return tantivy


def _register_analyzer(index: Any) -> None:
    tantivy = _tantivy()
    analyzer = (
        tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.simple())
        .filter(tantivy.Filter.lowercase())
        .filter(tantivy.Filter.stopword("English"))
        .filter(tantivy.Filter.stemmer("English"))
        .build()
    )
    index.register_tokenizer(_ANALYZER, analyzer)


def build_schema() -> Any:
    tantivy = _tantivy()
    builder = tantivy.SchemaBuilder()
    for name in (
        "paper_id", "doi", "pmid", "pmcid", "arxiv_id", "openalex_id",
        "journal_name", "type",
    ):
        builder.add_text_field(name, stored=True)
    builder.add_text_field(
        "title", stored=True, tokenizer_name=_ANALYZER,
    )
    builder.add_text_field(
        "abstract", stored=False, tokenizer_name=_ANALYZER,
    )
    builder.add_integer_field("publication_year", stored=True, fast=True)
    builder.add_integer_field("cited_by_count", stored=True, fast=True)
    return builder.build()


def create_index(path: Path) -> Any:
    path.mkdir(parents=True, exist_ok=True)
    tantivy = _tantivy()
    index = tantivy.Index(build_schema(), path=str(path), reuse=True)
    _register_analyzer(index)
    return index


def open_index(path: Path | None = None) -> Any:
    target = path or default_index_path()
    if not target.exists():
        raise LiveSearchUnavailable(f"index path does not exist: {target}")
    tantivy = _tantivy()
    index = tantivy.Index.open(str(target))
    _register_analyzer(index)
    return index


def _first(doc: dict[str, Any], key: str, default: Any = "") -> Any:
    value = doc.get(key)
    if isinstance(value, list):
        return value[0] if value else default
    return value if value is not None else default


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _int_or_zero(value: Any) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else 0


def _quality_score(record: PaperRecord, bm25: float) -> float:
    recency = 0.0
    if record.publication_year is not None:
        recency = max(0.0, min(1.0, (record.publication_year - 1990) / 35.0))
    citations = min(2.0, record.cited_by_count / 500.0)
    primary_bonus = 0.25 if record.paper_type.lower() in {
        "article", "journal-article", "research-article", "proceedings-article",
    } else 0.0
    return bm25 + citations + recency + primary_bonus


def _record_from_doc(doc: dict[str, Any], bm25: float) -> PaperRecord:
    year = _int_or_none(_first(doc, "publication_year"))
    cited = _int_or_zero(_first(doc, "cited_by_count"))
    raw = PaperRecord(
        paper_id=str(_first(doc, "paper_id")),
        title=str(_first(doc, "title")),
        abstract="",
        publication_year=year,
        cited_by_count=cited,
        paper_type=str(_first(doc, "type")),
        doi=str(_first(doc, "doi")),
        pmid=str(_first(doc, "pmid")),
        pmcid=str(_first(doc, "pmcid")),
        arxiv_id=str(_first(doc, "arxiv_id")),
        openalex_id=str(_first(doc, "openalex_id")),
        journal_name=str(_first(doc, "journal_name")),
        score=bm25,
    )
    return replace(raw, score=_quality_score(raw, bm25))


def search(
    query: str, *, fields: list[str] | None = None, k: int = 400,
    index_path: Path | None = None,
) -> list[PaperRecord]:
    """Return top-k paper records from the local Tantivy index."""
    clean_query = query.strip()
    if not clean_query:
        return []
    index = open_index(index_path)
    wanted = [f for f in (fields or list(_DEFAULT_FIELDS)) if f in _DEFAULT_FIELDS]
    if not wanted:
        wanted = list(_DEFAULT_FIELDS)
    query_obj = index.parse_query(clean_query[:512], wanted)
    searcher = index.searcher()
    results = searcher.search(query_obj, max(k * 5, k))
    records: list[PaperRecord] = []
    for bm25, address in results.hits:
        doc = searcher.doc(address).to_dict()
        record = _record_from_doc(doc, float(bm25))
        if record.paper_id or record.title:
            records.append(record)
    records.sort(key=lambda r: r.score, reverse=True)
    return records[:k]


def paper_to_fact(record: PaperRecord, topic: str) -> dict[str, Any]:
    """Project a paper hit into the existing fact-shaped downstream contract."""
    title = record.title.strip()
    phrase = title or f"Paper matched live search query for {topic}"
    return {
        "fact_id": f"live:{record.paper_id or record.doi or title[:80]}",
        "topic": topic,
        "sub_topic": "paper_match",
        "source_paper": {
            "paper_id": record.paper_id,
            "doi": record.doi,
            "pmid": record.pmid,
            "pmcid": record.pmcid,
            "arxiv_id": record.arxiv_id,
            "openalex_id": record.openalex_id,
            "title": title,
            "journal": record.journal_name,
            "year": record.publication_year,
        },
        "claim_type": "paper_match",
        "numeric_value": None,
        "units": "",
        "ci_lower": None,
        "ci_upper": None,
        "population": topic,
        "intervention": topic,
        "comparator": "",
        "endpoint": "literature_match",
        "canonical_phrase": phrase,
        "canonical_year": record.publication_year,
        "validator": "tantivy-live-search",
        "superseded_by": None,
        "_tier": "live_search",
        "cited_by_count": record.cited_by_count,
        "paper_type": record.paper_type,
        "search_score": record.score,
    }


def facts_from_records(records: list[PaperRecord], topic: str) -> list[dict[str, Any]]:
    return [paper_to_fact(record, topic) for record in records]


def broad_yield(records: list[PaperRecord], query: str) -> int:
    """Cheap title-token yield for smoke tests without storing abstracts."""
    terms = {w for w in _WORD.findall(query.lower()) if len(w) >= 3}
    if not terms:
        return len(records)
    return sum(
        1 for record in records
        if terms & set(_WORD.findall(record.title.lower()))
    )
