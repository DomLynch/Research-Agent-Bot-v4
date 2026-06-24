# Research Agent Bot v4 — Alpha-Memo Writer · Fresh-Dev Handover

> Written 2026-06-15 for a new engineer starting with clean eyes. Everything
> here is grounded in the actual repo + a live VPS/DB inspection on this date.
> Where the existing docs are **stale or wrong**, this file says so explicitly —
> read the "Traps" section before trusting `AGENTS.md` / `PROJECT_STATE.md`.

---

## 0. One-paragraph orientation

v4 is a Python pipeline that turns **already-extracted research facts** (stored
in a shared Postgres corpus DB) into **short "alpha memos"** and submits the
publishable ones to the **Researka** platform. It runs per domain
(longevity, AI, business, +others) on systemd timers on a VPS. The core
discipline: **LLM proposes, code disposes** — an LLM writes prose and proposes
theses, but deterministic gates decide what is allowed to publish. There are
**exactly two models**: a **writer** and a **judge**, from different families.

---

## 1. Read-first / canonical sources of truth

| Source | What it gives you | Trust level |
|---|---|---|
| `AGENTS.md` | Conventions, non-negotiables, architecture | ⚠️ mostly current, **model stack section is STALE** |
| `PROJECT_STATE.md` | Objective + full sprint history (89a latest) | ⚠️ current for paper pipeline; model names stale |
| `agent/settings.py` | The **real** env/config wiring | ✅ source of truth |
| `agent/llm_client.py` | The **real** 2-model stack | ✅ source of truth |
| `HANDOVER.md` (existing) | Legacy **paper-pipeline** review packet | ❌ outdated, ignore for alpha-memo work |
| knowledge MCP `get_playbook()` / `get_aaa_protocol()` | Dom's cross-project doctrine + AAA build standard | ✅ call at session start |

**Rule when docs and code disagree: code wins.** This repo has drifted faster
than its markdown.

---

## 2. ⚠️ Traps a fresh dev WILL hit (read this section twice)

1. **Model stack docs are stale.** `AGENTS.md` / `PROJECT_STATE.md` /
   `.env.example` say the writer is **"MiMo v2.5 Pro"**. **That is wrong.** The
   writer migrated to **MiniMax M3** on 2026-06-11 (MiMo was cancelled). The
   code is correct — `agent/settings.py:117` literally says *"Writer is MiniMax
   M3 … MIMO_* accepted as legacy aliases, but MINIMAX_* win when both set."*
   Internal field names are still `mimo_*` for back-compat; the **env keys** are
   `MINIMAX_API_KEY` / `MINIMAX_BASE_URL` / `MINIMAX_MODEL` (legacy `MIMO_*`
   still read). Endpoint is **Anthropic-compatible** (`/anthropic` → `POST
   /v1/messages`, `x-api-key` auth). **Do not "fix" the code to MiMo. Do not
   reroute the model stack without explicit owner approval — it is locked.**
2. **The corpus database is NOT this repo's code and NOT yours to mutate.** v4
   is a *client* of a separate service (`researka-database`, a uvicorn API on
   the VPS) that owns the ~25M-paper Postgres. Schema/index/ingestion belong to
   the DB dev. (See §6.)
3. **The macbook working tree gets re-parked onto a harness checkpoint branch**
   (`claude/<id>/main`). The canonical branch is **`feature/ai-research-agent`**;
   origin + VPS track it. Always confirm you're committing to the real branch.
4. **`HANDOVER.md`** in the repo root is a legacy paper-pipeline packet — this
   file (`HANDOVER_ALPHA_MEMO.md`) supersedes it for alpha-memo work.
5. **LOC gate is a hard CI gate.** `agent/` has a ceiling (currently **19,850**,
   `scripts/loc_gate.sh`). Adding code means deleting/earning headroom. Every
   bump historically had to "delete or prevent a fake-evidence failure mode."

---

## 3. What the bot is for (objective)

From `PROJECT_STATE.md` + `AGENTS.md`:

- **Primary:** produce **AAA-grade, source-grounded** research output in a small
  core. *"Main manuscript = argument. Supplement = audit. Compiler = truth. LLM
  = prose. Contract = enforcement."*
- **Curator-layer role (Sprint 39+):** on top of the paper pipeline, v4 reads
  per-paper receipts, computes per-topic 0–100 confidence snapshots, watches
  them move, and emits a prioritized **"publish these N"** digest.
- **Current focus (the alpha-memo product, Sprints 76–89a):** for each topic,
  build an evidence run → classify facts into lanes → let the writer propose a
  thesis → gate it structurally → if it passes, submit to Researka.
- **Design law:** **universal, no hardcoding.** No `if topic == "..."`. Domain
  vocabulary lives in `topic_packs/*.toml` (data), never in `agent/` (code).

---

## 4. The alpha-memo pipeline (end-to-end)

Linear data flow — a topic becomes a published memo via:

```
discover_topics()                      agent/topic_discovery.py:1322
   → ranked TopicCandidate tuples (velocity, fact_source_count)
build_topic_evidence_run.py main()     scripts/build_topic_evidence_run.py:1563
   → _fetch_facts() (Researka Tier-2 API) → pico_enrichment → classify_lanes()
     → run_frontier_review() (writer LLM)
   → writes run dir runs/<topic>-evidence-<ts>/:
       all_facts.json · fact_lanes.json · claims_index.json
       frontier_review.json · claim_cluster.json · MANIFEST.json
build_signal_post.py main()            scripts/build_signal_post.py:426
   → _render_signal_post() → write_signal_memo() (agent/signal_memo_writer.py)
   → write_publish_verdict() (agent/publish_tier.py:1314 → publish_verdict():974)
   → writes signal_post.md · alpha_memo.md · publish_verdict.json
   → (curation_brief.md if label == curation_needed)
build queue + cycle                    scripts/daily_alpha_publish_cycle.py
   → _build_queue():592 scans alpha_memo.md + publish_verdict.json, dedups by
     topic, sorts by tier+alpha_score → {ready_to_publish, agent_repair_needed,
     curation_needed}
   → run_cycle():3906 selects ≤1 ready memo/domain, optional _refresh_alpha_memo()
     (re-writes against reviewer feedback), submits if --submit, logs ledger
   → Researka platform → decision (accept/reject/revise) polled back
```

**Stage purposes:**
1. **Topic discovery** (`agent/topic_discovery.py`) — score seeds by paper
   velocity (FWCI × log(cited_by) × recency × quality), probe derived topics,
   rank by source availability.
2. **Evidence build** (`scripts/build_topic_evidence_run.py`) — fetch top-N
   facts from the corpus, enrich PICO, classify into lanes
   **A_core / B_context / C_noise / D_bad** (`agent/fact_lanes.py`), and run the
   **frontier review** (`agent/frontier_review.py` — writer LLM proposes
   thesis + next extractions; may cite **only** A/B fact-ids).
3. **Signal post + memo** (`scripts/build_signal_post.py` +
   `agent/signal_memo_writer.py`, 2,516 LOC) — render the human-facing
   `signal_post.md` and the full `alpha_memo.md`; attach a confidence label.
4. **Publish-tier gate** (`agent/publish_tier.py`, 1,318 LOC) — **purely
   structural** decision (no domain rules, no LLM): emits `decision ∈
   {ready_to_publish, agent_repair_needed, curation_needed}`, `publish_tier ∈
   {TIER_1,2,3}`, `blockers[]`, `alpha_score`. This is the safety spine.
5. **Daily cycle** (`scripts/daily_alpha_publish_cycle.py`, 4,529 LOC) — build
   queue, pick one, optionally repair, submit, ledger to
   `runs/_daily_ledger/<date>.json`. **Dry-run by default; only `--submit`
   actually posts.**

**Key run-dir artifacts:** `all_facts.json` (raw facts), `fact_lanes.json`
(A/B/C/D verdicts), `frontier_review.json` (writer thesis), `alpha_memo.md`
(the product), `publish_verdict.json` (the gate decision).

---

## 5. Code map (`agent/` = 71 modules, ~18.6k LOC; `scripts/` = 36, ~14.6k LOC)

Biggest/most important modules first:

| Module | LOC | Role |
|---|---|---|
| `scripts/daily_alpha_publish_cycle.py` | 4,529 | Orchestrates daily build→select→submit; ledger |
| `agent/signal_memo_writer.py` | 2,516 | Renders `alpha_memo.md` (headline, surprise, receipts, counters) |
| `scripts/build_topic_evidence_run.py` | 1,791 | Fetch+rank facts, lanes, frontier review → run dir |
| `agent/topic_discovery.py` | 1,482 | Velocity-scored topic discovery |
| `agent/publish_tier.py` | 1,318 | **Structural publish gate** (the safety spine) |
| `agent/business_research.py` | 880 | Business-domain specialist candidate builder |
| `scripts/run_curator_cycle.py` | 761 | One-command curator cycle runner |
| `scripts/build_signal_post.py` | 535 | signal_post.md + alpha_memo.md + verdict |
| `agent/claim_gates.py` | 498 | Deterministic gates policing LLM claims |

Functional groups in `agent/`:
- **Discovery/selection:** `topic_discovery`, `topic_pack`, `topic_synonyms`, `domain_profile`, `alpha_selector`, `fact_facets`
- **Sourcing/retrieval:** `source_corpus`, `researka_facts`, `researka_claims`, `full_text_fetch`, `full_text_parse`, `pdf_parse`
- **Screening/eligibility:** `screening`, `screening_rules`, `eligibility_rules`, `eligibility_judge`, `eligibility_merge`, `include_contract`, `sentinel_recall/repair`
- **Fact extraction/quality:** `effect_extraction`, `effect_pooling`, `effect_sizes`, `extraction_confidence`, `extraction_crosscheck`, `dual_agent_audit`, `numeric_role_classifier`, `numeric_sanitizer`
- **Evidence org/indexing:** `evidence_state`, `fact_lanes`, `evidence_index`, `evidence_delta`
- **Claim/truth assessment:** `claim_clusterer`, `consensus_split`, `claim_gates`, `source_audit`, `correction_proposer`, `curator_quality`, `citation_verify`
- **Opportunity/gate:** `frontier_input_pack`, `frontier_review`, `frontier_audit`, `gap_analyzer`, `publish_tier`, `quality_scorecard`
- **Authoring/prose:** `signal_memo_writer`, `prompts`, `placeholder_resolver`, `reference_resolver`, `methods_honesty`, `appendix_a`, `back_matter`, `cross_topic_synthesizer`
- **Results/output:** `results_packets/compiler/contract/writer`, `study_table`, `pico_enrichment`, `submission_package`, `research_object`
- **Infra:** `settings`, `llm_client`, `skill_loader`

`topic_packs/*.toml` = all domain data (cues, markers, eligibility terms,
publication metadata). Touch these, not code, for domain behavior.

---

## 6. The data layer (NOT this repo — a separate service)

- **Corpus:** ~**24.9M papers** in Postgres `researka_database` on the VPS,
  served by a uvicorn API (`researka-database` service). v4 calls it over HTTP.
- **Sources blended (9):** `pubmed`, `semanticscholar`, `openalex`,
  `openalex_ai_research`, `arxiv`, `biorxiv`, `medrxiv`, +2. (So PubMed and
  Semantic Scholar are already ingested — adding them isn't "new coverage.")
- **Extracted facts = the publishing currency:** ~**346k tier-2** + ~5k tier-1.
  By domain (tier-2): AI ≈ 127k, business ≈ 10.6k, longevity ≈ 5.4k (+ topic-
  tagged senescence/metformin/etc.), untagged ≈ 203k. **Only <2% of papers have
  facts extracted — the headroom is extraction, not more papers.**
- **The hot query** (`topic_papers.py` in the corpus API, not this repo) filters
  papers with `(title || abstract) ~* <topic_regex>` — accelerated by a
  **pg_trgm trigram index** on title+abstract. **Schema/index/ingestion are the
  DB dev's domain.** v4's only levers are the `--max-refresh-batches` /
  worker-concurrency knobs (how hard it hammers the API).

---

## 7. Run / test / deploy

**Run (dry-run by default; `--submit` is the only thing that posts):**
```bash
# build one topic's evidence run (no LLM if --no-frontier)
.venv/bin/python scripts/build_topic_evidence_run.py --topic rapamycin --domain longevity --top 5 --mode alpha
# daily publish cycle for a domain (safe — no --submit)
.venv/bin/python scripts/daily_alpha_publish_cycle.py --domain longevity_research --allow-tier2-repair
# the real submitting form (what the timers run):
#   ... --refresh-candidates --allow-tier2-repair --max-refresh-batches <N> --submit
```
Key flags: `--domain`, `--submit`, `--refresh-candidates`,
`--max-refresh-batches` (⚠️ default is **5**; the VPS timers historically ran
**500** = an aggressive backfill that can hammer the corpus API),
`--allow-tier2-repair` (repair entry only; final submit floors stay strict),
`--max-cost-usd`, `--published-topic-cooldown-days`.

**Env keys (NAMES ONLY — never commit values; `.env` is gitignored):**
- Writer (MiniMax M3): `MINIMAX_API_KEY`, `MINIMAX_BASE_URL`, `MINIMAX_MODEL`, `MINIMAX_TIMEOUT_SEC` (legacy `MIMO_*` aliases still read)
- Judge (Gemma 4 31B / OpenRouter): `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `JUDGE_MODEL`
- Corpus DB: `RESEARKA_DATABASE_URL`, `RESEARKA_DATABASE_TOKEN`
- Optional retrieval: `NCBI_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY`, `CORE_API_KEY`, `CROSSREF_POLITE_EMAIL`, `UNPAYWALL_EMAIL`
- Safety: `BOT_ENABLED`, `DAILY_COST_CAP_USD`, `WRITER_MAX_RETRIES`

**Test / quality gates (all must pass before commit):**
```bash
.venv/bin/python -m pytest -q          # ~93 test files
.venv/bin/python -m ruff check agent tests scripts
.venv/bin/python -m mypy agent          # strict
scripts/loc_gate.sh                     # agent/ ≤ 19,850 LOC hard gate
```
`pyproject.toml`: ruff (E,F,W,I,B,UP,SIM,RUF), mypy strict, pytest asyncio auto,
`@pytest.mark.live` opt-in for network tests.

**Deploy:** `deploy/systemd/` holds `researka-alpha-<domain>-research.{service,timer}`
(longevity, ai, business, marketing, management, finance, economics) + a
cache-warm unit. Each runs the publish cycle on a schedule with `--submit`,
6-hour wall-clock cost fence, EnvironmentFiles = repo `.env` +
`/etc/researka-agent-v4.env`. VPS path: `/root/Research-Agent-Bot-v4`.
Canonical git branch: **`feature/ai-research-agent`** (origin + VPS).

---

## 8. Current operational state (live, 2026-06-15)

- **Deployed commit:** `02d7d39` — macbook = GitHub = VPS, clean, in sync.
- **🔴 Publishing is currently blocked, and it is NOT a v4 code bug.** The corpus
  DB's trigram search index (`papers_title_abstract_trgm_idx`) is **invalid /
  mid-rebuild**, so every candidate-paper lookup falls back to a 12–20 min full
  scan of 24.9M rows → publish cycles exhaust before submitting → **0 real
  DOIs today.** Root cause: heavy business-corpus ingestion churn
  (101M inserts / 195M updates) wore the index out; the rebuild is ~¾ done.
- **Publish timers are intentionally paused** to let the rebuild finish (running
  them re-starves it). They must be **un-paused** (`systemctl start
  researka-alpha-*.timer`) once the index is `VALID`.
- **MiniMax M3 writer:** online.
- **Recent code work (committed, in 02d7d39):** opt-in advisories — citation-
  existence verifier (`agent/citation_verify.py`, with arXiv-DOI false-positive
  fix), evidence-map consensus split (`agent/consensus_split.py`), quality
  scorecard (`agent/quality_scorecard.py`); plus a fetch-worker concurrency cap.
  All OFF by default, env-gated, `suppress`-isolated, never touch the publish
  decision.

**Known structural limits (not bugs):**
- **Researka publishing gate:** rejects broad "evidence-map" memos; only narrow,
  coherent single-claim topics publish, and the coherent pool hits a ~30-day
  cooldown → throughput stalls.
- **Business is supply-limited:** ~10.6k facts vs AI's ~127k; needs econ-corpus
  ingestion (SSRN/RePEc/NBER), which is a DB-side effort, not a v4 patch.

---

## 9. Doctrine / non-negotiables (don't violate without explicit approval)

1. **Two models, different families.** Writer (MiniMax M3) ≠ Judge (Gemma).
   Model stack is **locked** — never reroute without explicit owner sign-off.
2. **LLM proposes, code disposes.** Counts/tables deterministic; prose is
   LLM but packet-scoped and never sees global state; one contract module gates
   ship; bounded **2-retry** judge→writer loop then publish as-is. No infinite
   repair, no scrubber, no backstop.
3. **Universal, no hardcoding.** No topic/domain literals in `agent/`; vocabulary
   lives in `topic_packs/*.toml`. (Legacy biomedical-leaning surfaces are
   inventoried in `PROJECT_STATE.md` — don't add new ones.)
4. **LOC ceiling** is a hard gate; new code must remove a fake-evidence failure
   mode, not buy prose.
5. **Advisory pattern** for new analyzers: OFF by default, env-gated,
   exception-isolated, write a sidecar JSON, **never change the publish
   `decision`.**
6. Python ≥ 3.11, stdlib-first, every dependency justified in `DECISIONS.md`,
   each compile step a pure function writing a sidecar (no global state).
7. Quality gates (pytest/ruff/mypy/loc_gate) **all green before commit**;
   commit ritual is "macbook = github = vps, clean, no dirt."

---

## 10. Suggested first moves for the fresh dev

1. Read this file → `agent/settings.py` + `agent/llm_client.py` (real config) →
   `agent/publish_tier.py` (the gate that defines "publishable").
2. Call knowledge MCP `get_playbook()` + `get_aaa_protocol()`.
3. Build one evidence run locally **without `--submit`** and read the resulting
   `alpha_memo.md` + `publish_verdict.json` to see the gate in action.
4. Do **not** touch the corpus DB; coordinate index/ingestion with the DB dev.
5. Highest-leverage product levers (per live data): (a) extract more facts from
   the 25M papers already held; (b) ingest open-access **full text** (currently
   thin — `paper_fulltext` ≈ 253 MB); (c) the Researka coherence/cooldown gate
   is the real throughput limiter — design around narrow single-claim topics.

---
*Grounded in: repo @ `02d7d39`, live VPS/DB inspection 2026-06-15, and the
locked model-stack decision (2026-06-11). Where this contradicts the older
markdown docs, this file is newer.*
