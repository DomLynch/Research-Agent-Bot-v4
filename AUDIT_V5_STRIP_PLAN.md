# v4 Alpha-Memo Writer — Audit & v5 Strip Plan
Written 2026-06-15. Method: 8-auditor multi-agent sweep (104 sub-agents, ~5.5M tokens) over all 107 Python modules (~33k LOC), every proposed cut adversarially re-verified for reachability from the live `--submit` path (import graph **and** systemd/subprocess invocation), then synthesized. Headline claims independently re-verified by hand (see §8). **Audit-only: no code changed by this pass.**

---

## 1. Bottom line
**Cleanliness: 4/10. It is a spider web — but a *separable* one.**

v4 is **two disjoint systems sharing one repo**:

1. A **~15.7k-LOC live alpha-memo spine** — one `--submit` entrypoint → curator subprocess → evidence run → publish gate → memo writer → submit/poll/ledger. This delivers the *"publish the publishable"* half of the mission.
2. A **~17k-LOC fossilized island** — the legacy 9-step systematic-review / manuscript engine (PRISMA, eligibility, screening, full-text fetch, effect pooling, Section-3 writer, stitch/supplement, submission package) plus OFF-by-default advisory sidecars and orphan dev scripts. **Nothing on the submit path reaches it.**

The dead island alone eats **~4.2k of the `agent/` 19,000-LOC ceiling** for zero product value — which is *exactly* why `agent/` has zero headroom and the whole thing "feels bloated." The good news: the coupling between live and dead is almost entirely *internal to the dead island*, so it can be excised in one coordinated commit.

**The deeper problem — the mission is structurally absent (§3).** v4 does not do "deep smart search → novel memo." It does lexical regex over one corpus endpoint, ranks by citation *popularity* (the inverse of novelty), and literally deletes the word "novel" from memos to appease reviewers.

---

## 2. The numbers (verified reachability census)

| | Modules | LOC | Note |
|---|---|---|---|
| **LIVE-SET** (reachable from a `--submit` cycle) | 28 (20 agent + 8 scripts) | **~15,728** | the real product |
| **ORPHAN-SET** (no live caller) | ~70 | **~17,200** | legacy + advisory + dead scripts |
| — verified safe to delete now | 39 | ~14,373 | adversarially confirmed |
| — flagged, needs owner call | ~25 | ~3,000 | P5/P6 below |

**Concentration of bloat in the live set:** 5 files = **68% of the live LOC**:
`daily_alpha_publish_cycle.py` (3,984) · `signal_memo_writer.py` (2,199) · `build_topic_evidence_run.py` (1,771) · `topic_discovery.py` (1,502) · `publish_tier.py` (1,185). Each is 4–13× the 300-LOC smell ceiling.

**Three live entrypoint families** (not one — all systemd-driven):
- `daily_alpha_publish_cycle.py --submit` → `ai_research`, `longevity_research`
- `run_business_alpha_sweep.py --submit-after-consistent-passes 2` → `economics`, `finance`; (`marketing` runs it **without** `--submit`)
- `build_business_alpha_candidate.py` (no submit) → `business`, `management`
- `run_topic_discovery.py --warm-backlog` → cache-warm
- `researka-alpha-daily.service` → **`ExecStart=/bin/true`** (dead stub)

---

## 3. The mission gap — why it "isn't delivering deep, novel search"
This is the owner's real complaint, and stripping alone will *not* fix it. v4 only does the "publish" third of "deep smart search → innovative/novel short memo → publish."

**(1) Deep search is absent.** On the live path, `build_topic_evidence_run.py` does keyword-slice HTTP fan-out against ONE corpus endpoint (`/ai/results/search` + `/tier2/facts/search`), then filters client-side with a static synonym table + regex `\b` word-boundary matching. **No embeddings, no vector/semantic retrieval, no query-reformulation loop.** The 12-module multi-source retrieval stack (`agent/retrieval/*`) is import-loaded but **never queried** on the alpha path.

**(2) Novelty detection is absent — and inverted.** `topic_discovery._paper_score` ranks by `fwci · log(1+cited_by) · recency · quality` — that is citation **popularity**, which biases toward *already-established* work. `alpha_selector.accepted_shape_bonus` biases toward shapes Researka has *already accepted* (conformity). The only field literally named "novelty" is an **LLM self-rated int** in `frontier_review` (violates "code disposes"). And "novel" is in `topic_discovery`'s title **stopword list** *and* deleted from finished memos by `_soften_overclaim_language`.

**(3) Citation existence is unchecked.** `agent/citation_verify.py` — the exact "catch the ~40% hallucinated sources" capability your own memory flags as the gap — **has zero importers.** The gate (`publish_tier`) polices source coherence/shape/support but never asks "is this NEW vs prior art?" or "do these sources actually exist?"

**Downstream symptom:** the ~1,000 LOC of repick/floor/dispersion repair inside `signal_memo_writer.py` is the system compensating *at memo-render time* for upstream retrieval that produces incoherent receipt bundles. Fix the search and most of that repair machinery becomes unnecessary.

---

## 4. v5 architecture (smallest legible design)

| Component | Responsibility | Modules kept |
|---|---|---|
| **Orchestrator (submit spine)** | cost/dry-run fences, batch loop, retraction, preflight, submit/poll/decision-sync, ledger. Shrink 3,984 → ~600–800 LOC. | `daily_alpha_publish_cycle.py`, `domain_profile`, `alpha_selector`, `settings`, `llm_client`, **`submission_ledger.py` (new, extracted)** |
| **Deep Search** | query the read-only corpus + **semantic retrieval pass** + one query-reformulation loop | `run_curator_cycle`, `build_topic_evidence_run`, `run_topic_discovery`, `topic_discovery`, `researka_facts`, `researka_claims`, `topic_synonyms`, `retrieval/base` |
| **Evidence Classification** | PICO completion, numeric artifact removal, lane A/B/C/D, facet coherence. The genuinely clean doctrine core. | `pico_enrichment`, `numeric_sanitizer`, `numeric_role_classifier`, `fact_lanes`, `fact_facets` |
| **Novelty Engine (NEW)** | deterministic novelty disposition + citation-existence verification (§6) | **`novelty_gate.py` (new)**, `frontier_review`, `frontier_audit`, `frontier_input_pack` |
| **Publish Gate ("code disposes")** | single deterministic decision: `ready_to_publish \| agent_repair_needed \| curation_needed`. Split the 244-line `publish_verdict`. | `run_opportunities_gate`, `publish_tier`, `build_publish_queue`, **`gate_advisory.py` (new)** |
| **Memo Writer (LLM proposes prose)** | template a short memo from an already-selected receipt set. Collapse 2,199 → ~400–600 LOC. | `build_signal_post`, `signal_memo_writer` |
| **Cross-topic synthesis (optional)** | keep only if it converts to submissions; else cut | `cross_topic_synthesizer`, `run_cross_topic_synthesis` |

---

## 5. Strip plan (ordered, reversible, lowest-risk-first)
LOC numbers are estimates. Corrections from hand-verification (§8) are folded in.

| Phase | Action | ~LOC | Risk | Gate |
|---|---|---|---|---|
| **P1** | Delete zero-importer dead code: `consensus_split`, `claim_clusterer`, `risk_of_bias`, `skill_loader`, `appendix_a`, `prompts`, `back_matter`, `reference_resolver`. **Harvest** `citation_verify`'s existence logic into the Novelty Engine *before* deleting it. | ~1,217 | low | pytest/ruff/mypy/loc |
| **P2** | Delete OFF-by-default advisory sidecars + their CLIs: `gap_analyzer`+`run_gap_analysis`, `curator_quality`+`run_curator_quality`, `render_digest`. | ~538 | low | same |
| **P3** | Delete the legacy paper-pipeline island as ONE commit (incl. test files in the same commit or CI breaks). **⚠ co-delete `claim_gates` WITH `results_contract` + `draft_main`** (§8.2). | ~10,880 | med | full suite + loc |
| **P4** | Delete orphan fetcher **`agent/retrieval/europepmc.py`** (§8.3 — correct path). Do **not** touch the other retrieval adapters (import-loaded every run). | ~85 | low | same |
| **P5 (decision)** | Retire remaining legacy + multi-source stragglers (`results_contract`, `eligibility_rules`, `effect_sizes`, `evidence_index`, `include_contract`; legacy scripts; `retrieval/{semantic_scholar,biorxiv,researka,core}`). Adversarially flagged needs-human-call. | ~6,500 | med | owner confirm |
| **P6 (decision)** | Business/finance/economics sweep (`business_research`, `build_business_alpha_candidate`, `run_business_alpha_sweep`): **LIVE via enabled timers — do NOT delete.** Either park (disable timers → delete) or refactor 58 hardcoded domain literals into `topic_packs/*.toml`. | 0 | high | owner confirm |
| **P7** | Fix the writer-config drift: make `settings.py` read `MINIMAX_*` with `MIMO_*` fallback (§8.1). Drop dead settings (`loc_ceiling=7500` stale, `researka_spine_trust`, `extraction_dual_pass`). | ~15 | med | writer smoke test |
| **P8** | Split the 5 live giants in place (no behavior change): extract `submission_ledger` (~450) + **delete the ~120-LOC reviewer-appeasement scrubbers incl. `_soften_overclaim_language`**; migrate ~1,100 LOC receipt-repair out of `signal_memo_writer` into the gate; split `publish_verdict`; move `ai_research` axis special-casing behind `domain_profile`; merge the two duplicate queue builders. | ~1,500 | high | golden-memo + cycle tests |
| **P9** | **Build the Novelty Engine** (§6) — additive, the mission fix. | +600–900 | high | new golden tests |

**Net:** ~14.4k LOC verified-deletable now (P1–P4), another ~6.5k pending your P5/P6 calls, ~1.5k freed by P8 splits — funding the ~0.6–0.9k of *new* novelty code many times over. `agent/` goes from pinned-at-ceiling to roughly half-empty.

---

## 6. The Novelty Engine — what you actually asked for
Not fixable by stripping; needs a deliberate, deterministic component (so "code disposes," not an LLM vibe). Corpus stays read-only.

1. **Deep search:** replace lexical regex fan-out with **retrieve-then-rerank**. Keep the corpus API as the recall source, but (a) issue a semantic/embedding query if the corpus exposes one, else embed the returned candidate set client-side and rerank by query-vector cosine; (b) add ONE LLM query-reformulation loop (2–3 reformulations → dedup union) instead of the static synonym table.
2. **Novelty as a deterministic gate:** `novelty_score = f(` claim-frequency-in-corpus (rare (population/intervention/endpoint/direction) tuple = novel), embedding-distance-to-nearest-prior-art (far = novel), recency-of-first-appearance `)`. A memo only routes to `ready_to_publish` if it clears a TOML threshold — **replacing** velocity-as-popularity and accepted-shape conformity.
3. **Citation existence as a hard blocker:** revive `citation_verify.py` (or the OSS `AutoResearchClaw/literature/verify.py` existence-verifier in your memory) so every receipt DOI/source must verifiably exist in the corpus before submit — killing the ~40% hallucination risk.

Net: deep search becomes semantic + reformulated; novelty becomes a measured blocker; the system stops *deleting* the word "novel" and starts *earning* it.

---

## 7. Risks
- **P3 is irreversible-feeling but git-reversible** — it asserts the long-form paper product is dead. That is the one strategic call (see decision below).
- **Test co-deletion**: ~20 test files import the legacy island; they must die in the same commit or CI red-screens on missing imports.
- **`include_contract` / `claim_gates` / `results_contract`** are a tangled legacy trio — co-delete or co-keep, never split across phases.
- **P8 touches the live submit path** — gate behind the golden-memo + cycle test suites; do it after P3 so you're refactoring a smaller surface.
- **The corpus DB is a separate service** — none of this touches it. The current publishing block (invalid trigram index) is DB-side and unrelated.

---

## 8. Hand-verification log (claims I checked before trusting the synthesis)
**8.1 — Writer-config drift (corrects an overclaim).** The synthesis called P7 a flat "production writer down." Reality, verified in code:
- `agent/settings.py:117-120` reads the writer config from `MIMO_*` keys only; `_env` (`:33-34`) is a plain `os.environ.get` with **no `MIMO_→MINIMAX_` aliasing**; `_load_dotenv` (`:16-30`) copies `.env` verbatim.
- `writer_configured` (`:102-103`) requires `mimo_api_key`; `llm_client.py:156-157` raises `"Writer not configured: set MIMO_API_KEY and MIMO_BASE_URL"` when false.
- The repo `.env` defines `MINIMAX_API_KEY/BASE_URL/MODEL` + `MIMO_TIMEOUT_SEC` but **no `MIMO_API_KEY`**.
- **Therefore:** any run loading config from the repo `.env` alone (e.g. local macbook) has the writer **disabled**. The VPS units load an extra `EnvironmentFile=/etc/researka-agent-v4.env` not visible here, which may inject `MIMO_*` — so the VPS may be fine. **The verified fact is the *drift*:** the documented "MINIMAX_* win / MIMO_ legacy alias" behavior (in AGENTS.md, the prior handover, and memory) **does not exist in the code** — settings reads only `MIMO_*`. Trivial, permanent fix in P7.

**8.2 — `claim_gates` delete-ordering bug.** `agent/results_contract.py:25` does `from agent.claim_gates import GateViolation`. The synthesis put `claim_gates` in P3 but `results_contract` in P5 → P3 would break the import. Folded in: co-delete `claim_gates` with `results_contract` + `draft_main`.

**8.3 — Path typo.** Delete set said `agent/europepmc.py`; the real file is **`agent/retrieval/europepmc.py`**. Corrected in P4.

**8.4 — Confirmed sound:** subprocess invocation (`_run_subprocess` / `subprocess.Popen`, `daily_alpha_publish_cycle.py:82/86/329/2994`); the 3 live entrypoint families + `/bin/true` dead stub (untruncated `rg ExecStart deploy/systemd/*.service`); business-sweep correctly refuted as a cut (live via finance/economics timers); reachability census live-set (15,728) matches the live import+subprocess graph.
