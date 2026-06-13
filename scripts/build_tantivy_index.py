"""Build the Tantivy paper-search index from exported papers.csv.

Default paths target the VPS volume from docs/live_search_codex_brief.md:
  /mnt/HC_Volume_106011525/search/papers.csv
  /mnt/HC_Volume_106011525/search/tantivy_papers

The build is idempotent when --replace is passed: the target index directory is
cleared first, then rebuilt from the CSV source of truth.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.live_search import create_index

_DEFAULT_CSV = Path("/mnt/HC_Volume_106011525/search/papers.csv")
_DEFAULT_INDEX = Path("/mnt/HC_Volume_106011525/search/tantivy_papers")
_TEXT_LIMIT = 4_000


def _clean(value: Any, *, limit: int | None = None) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    text = " ".join(text.split())
    return text[:limit] if limit is not None else text


def _int_or_zero(value: Any) -> int:
    if isinstance(value, bool) or value in (None, ""):
        return 0
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _paper_id(row: dict[str, str]) -> str:
    return _clean(
        row.get("id")
        or row.get("paper_id")
        or row.get("openalex_id")
        or row.get("doi")
        or row.get("pmid")
        or row.get("title"),
        limit=240,
    )


def _document(row: dict[str, str]) -> Any | None:
    title = _clean(row.get("title"), limit=1_000)
    if not title:
        return None
    from tantivy import Document

    return Document(
        paper_id=_paper_id(row),
        doi=_clean(row.get("doi"), limit=240),
        pmid=_clean(row.get("pmid"), limit=80),
        pmcid=_clean(row.get("pmcid"), limit=80),
        arxiv_id=_clean(row.get("arxiv_id"), limit=80),
        openalex_id=_clean(row.get("openalex_id"), limit=120),
        title=title,
        abstract=_clean(row.get("abstract"), limit=_TEXT_LIMIT),
        publication_year=_int_or_zero(row.get("publication_year")),
        journal_name=_clean(row.get("journal_name"), limit=300),
        type=_clean(row.get("type"), limit=120),
        cited_by_count=_int_or_zero(row.get("cited_by_count")),
    )


def build(csv_path: Path, index_path: Path, *, batch_size: int, replace: bool) -> dict[str, Any]:
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    if replace and index_path.exists():
        shutil.rmtree(index_path)
    index = create_index(index_path)
    writer = index.writer(heap_size=512_000_000)
    started = time.monotonic()
    rows = 0
    indexed = 0
    skipped = 0
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows += 1
            doc = _document(row)
            if doc is None:
                skipped += 1
                continue
            writer.add_document(doc)
            indexed += 1
            if indexed % batch_size == 0:
                writer.commit()
                print(f"[tantivy-index] indexed={indexed:,} rows={rows:,}", flush=True)
    writer.commit()
    elapsed = time.monotonic() - started
    meta = {
        "csv_path": str(csv_path),
        "index_path": str(index_path),
        "rows_read": rows,
        "rows_indexed": indexed,
        "rows_skipped_empty_title": skipped,
        "elapsed_seconds": round(elapsed, 3),
        "indexed_per_second": round(indexed / elapsed, 3) if elapsed else indexed,
    }
    (index_path / "researka_index_meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8",
    )
    return meta


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=_DEFAULT_CSV)
    parser.add_argument("--index", type=Path, default=_DEFAULT_INDEX)
    parser.add_argument("--batch-size", type=int, default=100_000)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    meta = build(args.csv, args.index, batch_size=args.batch_size, replace=args.replace)
    print(json.dumps(meta, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
