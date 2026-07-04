# Live Search — Codex execution brief

Self-contained handoff. Goal: make the v4 bot search the **full paper corpus** in
real time so every domain (longevity, AI, **and** business/economics/management/
finance/marketing) has useable data at scale — replacing the sparse pre-extracted
Tier-1/Tier-2 fetch that currently surfaces ~245 facts for a topic with tens of
thousands of papers. Constraints: minimal LOC, no bloat, reuse the existing v4
synthesis path, universal (no domain literals / silo hacks). Companion design doc:
`docs/multi_source_search_spec.md` (read it — this brief is the execution layer).

## Verified state (measured on `brain-vps`, 2026-06-13 — re-verify before acting)
- Postgres `researka_database.papers` = **24,817,207 rows**; columns include
  `id, doi, pmid, pmcid, arxiv_id, openalex_id, title, abstract, publication_year,
  journal_name, type, cited_by_count`. pgvector + pg_trgm installed.
- Domain coverage gap (root cause for business never publishing): by source —
  pubmed 21.6M, semanticscholar 1.74M, openalex_ai 1.37M, openalex 836k,
  biorxiv/medrxiv 416k, arxiv 46k, **openalex_econ_business 14,718**. So
  longevity/AI are covered; **business/econ is effectively empty**.
- Sanity: "metformin" appears in **36,192 titles** alone vs the 245 the old
  pipeline pulls → the problem is retrieval, not data.
- Fast disk: XFS volume at `/mnt/HC_Volume_106011525` (150 GB, ~60 GB free).
  Root disk `/` ~86% (≈41 GB free) — do not build large indexes on root.
- Cold corpus (for P1): storage box `rclone sb:researka-database/raw/` = 821 GiB
  raw dumps — `openalex/works` (595 GiB), pubmed, semantic_scholar, biorxiv.
  Remotes wired: `openalex, ss, ncbi, europepmc`.

## What is already done (on the volume, `/mnt/HC_Volume_106011525/search/`)
- `papers.csv` (29 GB) — full `papers` export (24.8M rows, all search columns).
- `papers.duckdb` (~39 GB) — the 24.8M-row table loaded into DuckDB. **NOTE:** the
  file may be locked / need WAL recovery because the FTS build was interrupted —
  treat `papers.csv` as the clean source of truth; rebuild the store if in doubt.
- `build_search_index.py`, `fts_build.py` — first attempts (see blocker below).

## The blocker (why this is being handed off)
DuckDB's `PRAGMA create_fts_index` (a SQL macro) does **not** scale to 24.8M docs
on this box: it ran **95+ CPU-min**, pinned RAM at the 20 GB limit (box has 30 GB),
CPU decayed 566%→142% as it thrashed on a ~3-billion-row term aggregation, and
never completed. **Decision needed: pick a search engine that builds an inverted
index at this scale in minutes, not hours.**

## Recommended approach (Codex to validate, then build)
**Use Tantivy** (Rust inverted-index lib; `pip install tantivy`) as the search
index — it is purpose-built for this, builds 24.8M docs in minutes, BM25 ranking,
compact on-disk index, no server. Build streaming from `papers.csv` (or stream
from Postgres) → Tantivy index on the volume. Alternatives to weigh and reject
with reasons: (a) DuckDB FTS — proven too slow here; (b) Postgres GIN tsvector —
keeps data in PG but the GIN index (~30–50 GB) is tight on the 41 GB-free root;
(c) Quickwit — Tantivy-based but heavier ops. Pick the leanest that passes the
acceptance tests; document the choice.

## Build requirements
- Index `title` + `abstract`; store `id` (+ minimal metadata for ranking:
  `publication_year, cited_by_count, type`) as fast fields. Do NOT store full text.
- Filter junk: index papers with a non-empty title; abstract optional (title-only
  rows still match). English analyzer + stemming + stopwords.
- Everything on the **volume**, never root. Resumable / idempotent build script.

## Integration with v4 (keep it minimal — this is the whole point)
New `agent/live_search.py`:
```python
def search(query: str, *, fields: list[str], k: int = 400) -> list[PaperRecord]
```
→ Tantivy BM25 top-k → quality pre-rank (`cited_by_count`, recency, `type`) →
return records. Swap the Tier-2 fetch in `scripts/build_topic_evidence_run.py`
(currently `agent/researka_facts.py` → `POST /api/v1/tier2/facts/search`) to call
`live_search.search(...)`. **Downstream is unchanged** — `agent/claim_clusterer.py`,
`agent/publish_tier.py`, `agent/signal_memo_writer.py` keep working if the
EvidenceBundle shape is preserved. Lazy per-paper fact extraction + cache as in the
design doc. Gate behind `LIVE_SEARCH=1`; keep the old path until parity (below).

## Acceptance tests (done-criteria)
- **AT-build:** index 24.8M docs completes in < 30 min, on the volume, < 60 GB.
- **AT-yield:** `search("metformin")` ≥ 20,000 papers; `search("minimum wage
  employment")` and `search("multi-agent systems")` each ≥ 2,000.
- **AT-latency:** p95 query < 1 s; full `search(k=400)` < 3 s.
- **AT-parity:** on 50 blind facts, A_core precision ≥ the current pipeline before
  retiring the Tier-2 path. Fully reversible (flag-gated).

## P1 (after P0 lands — unlocks business/econ; see design doc)
Stream the box's OpenAlex `works` dump, **filter by OpenAlex field** (economics,
business, management, finance, marketing, CS) → dedup (DOI/PMID/title) → add to the
index. New topics later = add the field id to a TOML allowlist. This is what takes
business from 14.7k → millions. Do NOT ingest all 275M — filter to target fields.

## Environment
- VPS: `ssh brain-vps` (key `~/.ssh/binance_futures_tool`). Repo
  `/root/Research-Agent-Bot-v4`, venv `.venv`. Postgres: `sudo -u postgres psql
  researka_database` (peer auth, local). Mac=GitHub=VPS on branch
  `feature/ai-research-agent`. Commit/deploy: push origin, `git reset --hard
  origin/feature/ai-research-agent` on the VPS.
