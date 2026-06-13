# Multi-Source Evidence Corpus + Live Search — Build Spec

Hand-off spec for Codex. Goal: replace the sparse pre-extracted Tier-1/Tier-2
pipeline with a unified, deduped, field-tagged, **searchable** corpus across all
domains (longevity, AI, economics, business, management, org-behaviour, finance,
marketing, + new topics added by config), queried in real time.

## 0. Verified context (measured on the server, 2026-06-13)
- Postgres `researka_database`: **24.8M papers** (`papers` table), pgvector +
  pg_trgm installed. Source mix is biomedical-heavy: PubMed 21.6M,
  semanticscholar 1.74M, openalex_ai 1.37M, openalex 836k, biorxiv/medrxiv 416k,
  arxiv 46k, **openalex_econ_business 14.7k** (business/econ is effectively empty
  — that is why those domains never publish).
- Metformin sanity check: **36,192 papers** with "metformin" in the *title* alone
  vs the **245** the current pipeline surfaces → retrieval starvation, not data.
- Storage box `sb:` (rclone, `u591223.your-storagebox.de`): 1 TiB, 821 GiB used.
  `sb:researka-database/raw/` = 821 GiB of raw dumps: `openalex/works` (595 GiB,
  2,128 files), `pubmed`, `semantic_scholar`, `biorxiv`. Remotes already wired:
  `openalex`, `ss`, `ncbi`, `europepmc`.
- Fast disk: XFS volume `/mnt/HC_Volume_106011525` (150 GB). Root disk is 99%
  full — Postgres must move to the volume regardless.

## 1. Principle
More databases ≠ more papers. OpenAlex + Semantic Scholar are near-supersets;
extra sources are mostly duplicates. The metric is **unique papers with an
abstract, in target fields, after dedup** — never source count. So the pipeline
is built around **normalize → dedup → field-filter**, and each source earns its
place only by unique-after-dedup yield.

## 2. Architecture
```
connectors (per source) ──▶ normalize (unified record) ──▶ dedup (merge by id) ──▶
field-filter (domain allowlist) ──▶ Parquet shards on the volume ──▶
DuckDB FTS (+ optional vectors) ──▶ live_search(query, fields, k) ──▶
[existing] densest_claim_cluster → publish_tier → signal_memo_writer
```
Keep Postgres for transactional v4 state (runs, fact_cache). The **search corpus**
is a separate lean DuckDB/Parquet layer on the volume — fast, compact, cheap, and
includes a re-export of the existing 24.8M so there is ONE search surface.

## 3. Unified paper record (normalization target)
```
PaperRecord:
  paper_id: str            # stable internal id = first available of doi|pmid|pmcid|arxiv|openalex
  doi, pmid, pmcid, arxiv_id, openalex_id, ss_id: str|None
  title: str
  abstract: str|None       # reconstructed from OpenAlex inverted-index where needed
  year: int|None
  venue: str|None
  type: str|None           # journal-article, preprint, ...
  cited_by_count: int|None
  fields: list[str]        # normalized domain tags (see §6)
  sources: list[str]       # every source that contributed (provenance)
  full_text_ref: dict|None # {source, id} pointer — NOT the text (fetch on demand)
```

## 4. Connector interface
Each source is one small module implementing:
```python
class Connector(Protocol):
    name: str
    def iter_papers(self, *, since: date|None = None) -> Iterator[RawPaper]: ...
    def normalize(self, raw: RawPaper) -> PaperRecord: ...
```
Connectors stream from the box (rclone cat / sequential read) or the live API —
never load a whole dump into RAM. **Build these first (priority order):**
1. `openalex` — breadth, all fields; reconstruct abstracts from inverted index;
   carry `topics`/`primary_topic.field` for §6 filtering. *(filtered, not all)*
2. `semantic_scholar` — coverage/overlap; has abstracts.
3. `pes2o` / OpenScholar datastore — ~45M cleaned **open-access full text**
   (extraction depth; sets `full_text_ref`).
4. `repec` / EconPapers — economics depth OpenAlex under-covers.
   (PubMed/biorxiv already ingested; keep as connectors for refresh.)

## 5. Dedup (the part that makes N sources coherent)
Merge key precedence: `doi → pmid → pmcid → arxiv_id → openalex_id →
normalized_title+year`. `normalized_title` = lowercase, strip punctuation/
whitespace, collapse spaces. On collision, merge: keep the **richest abstract**,
**union** `fields` and `sources`, prefer the record with full text. Emit dedup
metrics per run (unique kept, dupes folded, by source).

## 6. Field filter (drives multi-domain, config-not-code)
A TOML allowlist maps OpenAlex topic/field IDs → target domains:
`longevity, ai, economics, business, management, org_behaviour, finance,
marketing`. Keep a paper if any of its `fields` is in the allowlist. **Adding a
new topic = add its OpenAlex field id to the TOML, re-run the OpenAlex shard.**
Drop the biomedical bulk already covered by PubMed to control size.

## 7. Index (on the volume, compact)
- Storage: **Parquet shards** (zstd), partitioned by source, columns = the
  PaperRecord minus `full_text_ref` body. Title+abstract for ~60–90M unique
  papers compresses to ~50–90 GB → fits the 150 GB volume.
- Search: **DuckDB FTS** (`PRAGMA create_fts_index`) over `title || ' ' ||
  abstract`, BM25 ranking. Millisecond queries, no server.
- **Do NOT store full text in the index** — store `full_text_ref`; fetch full
  text on demand only for the ~k papers being extracted per query.
- Phase-2 semantic: DuckDB-VSS or LanceDB vector index over embeddings of the
  retrieved-and-extracted set; embed incrementally, not all 90M up front.

## 8. Pipeline (streaming, resumable, idempotent)
`scripts/build_search_corpus.py --source <name> [--since DATE]`:
stream dump → normalize → field-filter → write per-shard Parquet → after all
shards, run dedup-merge pass → (re)build FTS index. Checkpoint per source-shard
so a crash resumes; re-running a source is idempotent (replace its shard).

## 9. Integration with v4 (minimal LOC)
New `agent/live_search.py`:
```python
async def search(query: str, *, fields: list[str], k: int = 400) -> list[PaperRecord]
```
runs DuckDB FTS → top-k → quality pre-rank (cited_by_count, year, type) → returns
records. The fetch step in `scripts/build_topic_evidence_run.py` calls this
instead of the Tier-2 API; **downstream `claim_clusterer.py`, `publish_tier.py`,
`signal_memo_writer.py` are unchanged** (EvidenceBundle shape preserved). Lazy
fact extraction + cache (`fact_cache` table) as in the live-search spec. Gate
behind `LIVE_SEARCH=1`; keep the old path until parity passes (§12).

## 10. Phasing
- **P0 (free, today):** export existing 24.8M Postgres → Parquet + DuckDB FTS on
  the volume. Instantly fixes **longevity + AI** (metformin 245 → 36k+). No box,
  no new disk.
- **P1:** OpenAlex connector, field-filtered → unlocks **economics, business,
  management, finance, marketing** (the empty domains).
- **P2:** peS2o/OpenScholar full text + RePEc → extraction depth + econ depth.
- **P3:** vector layer for semantic recall.

## 11. Acceptance tests
- **AT-1 yield:** each target domain returns ≥ 2,000 candidate papers for a
  flagship query (e.g. metformin / "minimum wage employment" / "multi-agent
  systems"). Business/econ goes from ~15k total to ≥ 2M papers.
- **AT-2 dedup:** cross-source dedup folds ≥ 30% on the OpenAlex∩PubMed overlap;
  no record has a null merge key.
- **AT-3 attribution:** every returned `paper_id` resolves to a real record;
  every `field` came from source data (no fabricated tags).
- **AT-4 latency:** warm FTS query p95 < 1 s; full `search()` (k=400) < 3 s.
- **AT-5 parity:** on 50 blind facts, A_core precision ≥ the current pipeline
  before retiring the Tier-2 path.

## 12. Risks / decisions
- Abstract reconstruction (OpenAlex inverted index) must be correct — unit-test it.
- Size discipline: title+abstract only in the index; full text on demand; drop
  biomedical OpenAlex dupes. Re-check volume headroom after P1.
- Keep the old Tier-2 pipeline behind the flag; cut over per-domain only when
  AT-1..5 pass. Fully reversible.
