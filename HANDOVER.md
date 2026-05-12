# Research Agent Bot v4 — Project Handover

**Date:** 2026-05-12
**Purpose:** End-to-end audit packet for an external reviewer (GPT or human). Hand this whole file plus the current paper folder (`runs/latest/`) over and the reviewer can audit the code, the pipeline, and the manuscript without further onboarding.

---

## 1. What this project is

An automated synthesis pipeline that produces **journal-grade systematic-review / meta-analysis manuscripts** from a topic-pack TOML and a writer LLM. The current end-to-end run produces:

- `paper.md` — 16-section manuscript (~36 KB, ~4,300 words)
- `supplement.md` — supplementary information S1–S10 + S5b IV pool + S5c Researka cross-check audit (~10 KB)
- 4 JSON receipts (`eligibility_summary.json`, `primary_effect_input_set_strict.json`, `effect_extractions.json`, `effect_pool.json`)
- 1 audit sidecar (`extraction_crosscheck.json`)

The **AAA principle** (`AGENTS.md`):

> No LLM owns truth. No literal owns topic. No gate owns more than its rule. No section owns evidence outside its packet.
>
> LLM PROPOSES. CODE DISPOSES.

Counts and effect estimates are **deterministic** from JSON receipts; the writer LLM only emits prose into packet-scoped slots; a universal evidence contract gates includes; nothing topic-specific lives in `agent/` — domain vocabulary lives in `topic_packs/<topic>.toml`.

---

## 2. Current state (2026-05-12, post-Sprint 12.2)

### Pool & corpus

| Lane | Studies | k | Effect |
|---|---|---:|---|
| **A-core direct-lifespan** | s126 (Miller 2011), s235 (Hu 2022), s288 (Bitto 2016 — parse_failed) | 3 (2 poolable) | **inverse-variance pooled log_median_ratio = 0.104 (95% CI [-0.047, 0.255]; back-transformed median ratio 1.11; ~11% extension; CI overlaps null at k=2)** |
| **B sensitivity (genotype-modified)** | s246 (BMAL1−/−) | 1 | log_median_ratio = 0.388 (95% CI [-0.032, 0.808]) |
| **C secondary / contextual** | s086 (Harrison 2009, off-modal 90th-percentile family), s230 (Fischer 2015, no own survival numerics) | 2 | — |

PRISMA-style funnel: 502 records identified → 298 candidates → 256 OA full-text → 75 parsed → 8 auto-eligible → 4 strict A-core (post-genotype-routing: 3 wild-type A-core + 1 BMAL1 sensitivity).

### Audit posture

| Check | Result |
|---|---|
| **pytest** | 347 / 347 pass (0 failing) |
| **ruff** | clean (47 source files) |
| **mypy --strict** | clean (47 source files) |
| **LOC gate** | `agent/` = 6,760 / 7,500 (margin 740) |
| **Tri-sync** | macbook = origin/main = VPS (`brain-vps`) — all aligned |

### Final paper folder

`runs/latest/` symlinks to `runs/rapamycin-paper-2026-05-12T18-52-59Z/`:

```
paper.md                                  36,177 bytes
supplement.md                             10,549 bytes
extraction_crosscheck.json                 1,731 bytes  (Researka audit sidecar)
eligibility_summary.json                   PRISMA counts
primary_effect_input_set_strict.json       A/B/C lane structure
effect_extractions.json                    6 receipts, 4 contract-pass
effect_pool.json                           A-core k=2 + B sensitivity k=1 + pooled summary
```

---

## 3. Architecture

### 9-step pipeline (`AGENTS.md`)

```
1. EvidenceState.build(topic)         retrieval + parse + extract + SPAR
2. EvidenceState.freeze()             counts ONCE, immutable
3. compiler.render_supplement(state)  tables/counts/refs (deterministic)
4. section_packets.build(state)       per-outcome packets, accepted-only
5. writer.write_sections(packets)     LLM prose, packet-scoped
6. compiler.render_main(prose, state) stitched in schema order
7. editor_pass.polish(main_md)        LLM tone-only pass, no fact changes
8. contract.validate(main, supp, state)  10 fatal rules
9. verdict.emit(contract_result)      AAA only if contract PASS
```

### Module map (`agent/`, 36 modules, 6,760 LOC)

| Layer | Modules | Role |
|---|---|---|
| **Settings + topic pack** | `settings.py`, `topic_pack.py`, `skill_loader.py` | env vars + TOML loader + Markdown-skill loader (ARIS pattern) |
| **Retrieval (10 sources)** | `retrieval/` → `unified.py`, `base.py`, `pubmed.py`, `crossref.py`, `openalex.py`, `europepmc.py`, `semantic_scholar.py`, `core.py`, `biorxiv.py`, `osf.py`, `ctgov.py`, `researka.py` | unified parallel sweep with DOI/PMID dedup, sentinel injection, per-source failure isolation |
| **Screening + eligibility** | `screening.py`, `screening_rules.py`, `eligibility_rules.py`, `eligibility_judge.py`, `eligibility_merge.py`, `include_contract.py`, `manual_resolution.py` | 3-pass eligibility ladder (rule triage → Gemma judge → deterministic merge), universal evidence contract gates includes |
| **Full text + parse** | `full_text_fetch.py`, `full_text_parse.py`, `pdf_parse.py` | PMC + Unpaywall DOI resolution, PDF/XML parse, char_count + evidence-quote extraction |
| **Effect extraction + pool** | `effect_extraction.py`, `effect_pooling.py`, `effect_sizes.py` | MIMO writer prompt → JSON receipt → inverse-variance pool with median-family preference |
| **Sentinel + RoB** | `sentinel_recall.py`, `claim_gates.py` | sentinel-recall audit; rule-based RoB |
| **Manuscript builders** | `prompts.py`, `placeholder_resolver.py`, `methods_honesty.py`, `reference_resolver.py`, `back_matter.py`, `appendix_a.py`, `study_table.py` | universal token resolution + honesty rewrites + citation numbering + dynamic Appendix A + study-characteristics table |
| **Validation overlay** | `researka_facts.py`, `extraction_crosscheck.py` | Researka Tier 2 facts client + receipt-vs-canonical numerics cross-check |
| **Results contract** | `results_compiler.py`, `results_contract.py`, `results_packets.py`, `results_writer.py`, `evidence_state.py` | deterministic compile of counts/tables, contract validation, packet builder |

### Scripts (`scripts/`, 2,753 LOC)

```
run_eligibility.py    # CLI: retrieval → screening → parsing
freeze_primary_set.py # CLI: build strict A-core from eligibility receipts
extract_effects.py    # CLI: MIMO extraction (with 1-retry on parse-failure)
draft_main.py         # CLI: writer LLM section bundles (s1/s2/s6)
build_results.py      # CLI: regen section 3 (Results)
regen_section3.py     # CLI: re-run results writer with fresh receipts
stitch_paper.py       # CLI: stitch section bundles → paper.md (universal,
                      #      2-pass placeholder + honesty + Appendix A +
                      #      study table + citation resolution)
build_supplement.py   # CLI: render supplement.md from receipts
corpus_qa.py          # CLI: QA report generation
loc_gate.sh           # hard LOC ceiling check (7,500 in agent/)
```

### Topic packs (`topic_packs/`)

```
rapamycin.toml                       # the canonical topic data: scope vocabulary,
                                     # eligibility terms, sentinel list, strict
                                     # A-core gate, 21-entry bibliography,
                                     # placeholders, methods_honesty_rewrites,
                                     # preferred_metric_families,
                                     # genotype_modified_strain_markers, retrieval
                                     # sources, packet references
rapamycin_manual_resolutions.toml    # per-DOI manual status overlays
manual_full_text/rapamycin/          # 4 .txt files (Harrison, Miller, Hu, Bitto)
                                     # — full-text injections for papers the auto
                                     # retrieval cannot reach
skills/                              # ARIS Markdown-skill pattern (Sprint 11.6 + 12.1)
  system_writer.md                   # writer system prompt
  writer_section_methods.md          # 8-component Methods spec
  writer_section_title.md
  writer_section_abstract.md
  writer_section_introduction.md
  writer_section_discussion.md
  writer_section_limitations.md
  writer_section_conclusion.md
```

---

## 4. Universal-no-hardcoding principle (what to audit for)

`agent/` code must be **topic-agnostic**. All biomedical literals belong in `topic_packs/<topic>.toml`. Reviewers should grep `agent/` for `rapamycin`, `mouse`, `lifespan` etc. — the only legitimate hits are:
- module docstrings explaining what a class does
- argument default values that come from settings (e.g. `topic="rapamycin"` as a CLI default)

Receipt-derived prose (introduced Sprint 12.2):
| Placeholder | Source |
|---|---|
| `[N_SCREENED]`, `[N_ACCEPTED]`, `[K_STUDIES]` | `eligibility_summary.json` |
| `[STRICT_A_CORE_COUNT]`, `[STRICT_A_CORE_IDS]` | `strict.A_core_direct_lifespan` |
| `[K_POOLABLE]`, `[INCOMPLETE_RECOVERY_IDS]` | `effect_pool.json` + `effect_extractions.json` |
| `[PLACEHOLDER:<key>]`, `[MODERATOR_P:<key>]` | `topic_pack.placeholders[<key>]` |
| `[CIT:<key>\|<role>]` | `topic_pack.references_bibliography[<key>]` (numbered by first appearance) |
| `[PACKET:<id>]` | stripped to "(Supplementary §SX; Appendix A)" via honesty rewrites |

---

## 5. Model stack (non-negotiable)

| Role | Model | Where configured |
|---|---|---|
| **Writer** | MiMo v2.5 Pro (Xiaomi) via OpenAI-compatible endpoint | `Settings.mimo_model`, `MIMO_BASE_URL`, `MIMO_API_KEY` |
| **Judge** | Gemma 4 31B via OpenRouter (`google/gemma-4-31b-it`) | `Settings.judge_model`, `OPENROUTER_API_KEY` |
| **Correction loop** | Judge returns structured issues; MiMo rewrites; max 2 retries; then publish | `Settings.writer_max_retries` |

**Judge family ≠ writer family.** Strictly enforced.

---

## 6. Retrieval (10 sources, live-verified)

| Source | API | Auth | Status |
|---|---|---|---|
| PubMed | NCBI E-utilities | NCBI_API_KEY (boosts rate) | ✅ 502 hits |
| Crossref | `api.crossref.org/works` | polite-pool email | ✅ 86 unique |
| OpenAlex | `api.openalex.org/works` | polite-pool email | ⚠️ 0 hits (live probe; suspect query-shape) |
| Europe PMC | `ebi.ac.uk/europepmc/.../search` | none | ✅ 83 unique |
| Semantic Scholar | `api.semanticscholar.org/graph/v1` | SEMANTIC_SCHOLAR_API_KEY header | ✅ 24 unique |
| CORE | `api.core.ac.uk/v3/search/works` | Bearer CORE_API_KEY | ⚠️ 0 hits (live probe; suspect key/scope) |
| bioRxiv | Europe PMC `SRC:PPR` filter | none | ✅ 46 unique |
| OSF Preprints | `api.osf.io/v2/preprints/` | none | ⚪ 0 hits (expected — social-science slice) |
| ClinicalTrials.gov | `clinicaltrials.gov/api/v2/studies` | none | ✅ 4 hits |
| **Researka** | `database.researka.org/api/v1/search` | `X-Researka-Token` header | ✅ **93 unique (highest novelty %)** |

Unified deduped corpus: **827 unique hits** (PubMed-only baseline was 502 → +65% breadth gain from multi-source).

### Researka Tier 2 facts (Sprint 12.0)

- Endpoint: `POST /api/v1/tier2/facts/search` (verified live)
- Used by `agent/extraction_crosscheck.py` as a numerics validation overlay
- Current verdict on our 6 receipts: **0 matched, 0 discrepant, 4 no_canonical_fact, 2 no_receipt_numerics**
- Audit scaffold works; canonical-fact coverage of our specific A-core DOIs is sparse (Researka has Bitto 2016 / Miller 2014 ITP follow-up facts, but not the exact Miller 2011 / Hu 2022 / Harrison 2009 papers in %-units)

---

## 7. Sprint history (this session)

| Sprint | Headline | Key receipt change |
|---|---|---|
| 11.2 | Honesty: placeholder + moderator + tense resolvers | text-pass only |
| 11.2b | Trim paper folder to canonical 6-file shape | file hygiene |
| 11.3 | 9 new retrieval clients + 8-item reviewer honesty pass | retrieval 1→10 sources |
| 11.4 | Re-extraction k=1→k=2 + two-lane pool + dynamic Appendix A | first real k≥2 pool |
| 11.5 | k=1→k=3 unlock via manual full-text + median-family preference | Miller 2011 + Hu 2022 added |
| 11.6 | ARIS Markdown-skill pattern port (SYSTEM_WRITER) | infra only |
| 11.7 | Researka adapter rewrite to verified API shape (POST + X-Researka-Token) | +82 hits to corpus |
| 11.7A | Manuscript prose consistency repair (k=2 alignment) | multi-pass honesty engine |
| 12.0 | Researka Tier 2 facts cross-check (numerics validation overlay) | S5c block added |
| 12.1 | Complete ARIS skill-pattern port (−195 LOC in agent/prompts.py) | 7 prompts externalised |
| 12.2 | Universal corpus-prose tokens (no hardcoded study IDs) | receipt-driven prose |

---

## 8. Tests (347 total, 0 failing)

Located in `tests/` (5,606 LOC). Coverage areas:
- `test_topic_pack.py`, `test_settings.py` — config loaders
- `test_screening*.py`, `test_eligibility_*.py` — eligibility ladder
- `test_effect_extraction.py`, `test_effect_pooling.py` — extraction + pool logic (incl. median-family preference)
- `test_retrieval.py`, `test_retrieval_multisource.py` — all 10 sources mocked + Researka 3-lane parser
- `test_researka_facts.py` — Tier 2 facts client + crosscheck verdict matrix
- `test_skill_loader.py` — ARIS Markdown-skill loader + 7-prompt invariants
- `test_placeholder_resolver.py` — count + topic-pack + corpus-derived tokens
- `test_methods_honesty.py` — multi-pass + cycle prevention
- `test_reference_resolver.py` — `[CIT:]` → `[N]` numbering
- `test_back_matter.py`, `test_appendix_a.py`, `test_study_table.py` — dynamic renderers
- `test_build_supplement.py` — S1–S10 supplement generator
- `test_genotype_two_lane.py` — BMAL1 genotype-modified strain routing
- `test_extraction_prompt_steering.py` — prompt nudge for sample-size + metric-family preference

---

## 9. Known gaps + next-sprint backlog

| Gap | Honest framing | Sprint to fix |
|---|---|---|
| **s288 Bitto 2016 parse_failed** | MIMO returned malformed JSON after 2 attempts on a clean full-text. Retry with manual JSON repair OR different temperature. | 12.3 (small) |
| **s086 Harrison 2009 off-modal metric** | extracted as 90th-percentile; would add k=4 if median extracted from same paper. Manual prompt nudge to prefer median when both present. | 12.3 |
| **OpenAlex / CORE 0 hits** | live probe found 0 hits; suspect query-shape or scope mismatch. PubMed/Europe PMC/Researka/Crossref/Semantic Scholar/bioRxiv contribute the 827-hit corpus — OpenAlex+CORE are upside, not gating. | 12.4 (low-prio) |
| **Meta-regression / leave-one-out / Egger** | not implemented — current pool is k=2, well below the field convention of k≥5–10. Manuscript correctly defers these. | Sprint 13 (once k≥5) |
| **Human SYRCLE RoB adjudication** | automated rule-based screen only; full per-domain SYRCLE is flagged as "planned for pre-publication" in Methods. | external (human review) |
| **Dual extraction + 3rd-party adjudication** | single-pass MIMO extraction with receipt-level audit trail; manual dual review flagged as planned. | external (human review) |

---

## 10. Critical files for the auditor to read

### Manuscript output
- `runs/latest/paper.md` (the manuscript itself)
- `runs/latest/supplement.md` (S1–S10 + S5c cross-check)

### Architecture & doctrine
- `AGENTS.md` (project conventions, non-negotiables, model stack, 9-step pipeline)
- `PROJECT_STATE.md` (current sprint state)

### Universal-no-hardcoding spine
- `agent/topic_pack.py` (loader)
- `topic_packs/rapamycin.toml` (the canonical topic data — every domain literal lives here)
- `topic_packs/skills/*.md` (writer prompts as data)

### Receipt-driven prose generators (Sprint 12.x universal layer)
- `agent/placeholder_resolver.py` (count + corpus tokens)
- `agent/methods_honesty.py` (multi-pass honesty rewriter)
- `agent/reference_resolver.py` (`[CIT:]` → `[N]`)
- `agent/appendix_a.py` (dynamic Appendix A from receipts)
- `agent/study_table.py` (study-characteristics table)
- `agent/back_matter.py` (Data/Code/AI-use/Ethics/etc.)

### Validation overlay
- `agent/researka_facts.py` (Tier 2 facts client, live-verified)
- `agent/extraction_crosscheck.py` (numerics cross-check verdict matrix)

### Stitch (the single-command paper builder)
- `scripts/stitch_paper.py` (the 2-pass placeholder + honesty + Appendix-A + table + citation chain)

### Tests demonstrating contracts
- `tests/test_placeholder_resolver.py` (14 tests covering every token family)
- `tests/test_methods_honesty.py` (chained-rewrite + cycle-prevention)
- `tests/test_effect_pooling.py` (median-family preference)
- `tests/test_retrieval_multisource.py` (18 mocked-transport tests for 10 sources)
- `tests/test_researka_facts.py` (13 tests for Tier 2 facts + crosscheck)

---

## 11. Honest framing of where this stands

**Not** a publishable mid-tier meta-analysis of rapamycin lifespan as it stands today. The A-core inverse-variance pool is k=2 — credible but underpowered, with CI overlapping null.

**Is** a credible **living evidence-contract / reproducible extraction-audit pilot** — every count, effect estimate, and study attribution in the manuscript carries a receipt-trace; the pipeline can be replayed; the universal contract gates eligibility uniformly; multi-source retrieval is wired; the Researka audit scaffold exists for future canonical-fact validation.

**The next unlock** is corpus expansion (s288 retry + s086 median family) to push A-core k=2 → k=4. That's a 1–2 hour sprint with the current infrastructure.

---

## 12. How to reproduce

```bash
# Setup (one-time)
git clone https://github.com/DomLynch/Research-Agent-Bot-v4
cd Research-Agent-Bot-v4
pip install -r requirements.txt           # httpx, tomllib, pytest, etc.
cp .env.example .env                      # fill in API keys

# Replay the pipeline end-to-end
python3 scripts/run_eligibility.py --topic rapamycin --iter 21
python3 scripts/freeze_primary_set.py runs/<latest-s7-dir> --topic rapamycin
python3 scripts/extract_effects.py runs/<latest-s7-dir> --topic rapamycin
python3 scripts/draft_main.py --topic rapamycin --iter 21 --section title_abstract_intro
python3 scripts/draft_main.py --topic rapamycin --iter 21 --section methods
python3 scripts/build_results.py --topic rapamycin --iter 21
python3 scripts/draft_main.py --topic rapamycin --iter 21 --section discussion
python3 scripts/stitch_paper.py --topic rapamycin
python3 scripts/build_supplement.py runs/latest --topic rapamycin

# Audit
python3 -m pytest -q
python3 -m ruff check agent/ scripts/ tests/
python3 -m mypy --strict agent/
bash scripts/loc_gate.sh
```

---

## 13. What I'd ask GPT to audit

1. **Universal-no-hardcoding compliance.** Grep `agent/` for biomedical literals (rapamycin, mouse, lifespan, SYRCLE, etc.). Anything found in non-docstring code is a bug.
2. **Receipt-prose drift.** Does the manuscript prose contradict the JSON receipts? Compare `paper.md` claims against `effect_pool.json` + `primary_effect_input_set_strict.json` + `effect_extractions.json`. Sprint 12.2 fixed 5 known drift sites; look for more.
3. **Honesty / overclaim audit.** Scan `paper.md` for any tense that implies completed-but-not-actually-done analyses. Compare against the documented `forbidden_novelty_phrases` in `topic_pack` and the `methods_honesty_rewrites` table.
4. **Pool sanity.** Verify the inverse-variance computation in `agent/effect_pooling.py` (line ~80 onward) — log-ratio + SE from sample sizes — against the receipt values. Confirm CI bounds.
5. **Two-lane discipline.** Verify s246 BMAL1−/− is consistently described as B-lane sensitivity throughout (not A-core).
6. **Citation integrity.** Every `[N]` in the manuscript should resolve to a bibliography entry; no `[UNRESOLVED]` should remain. Verify the 19 cited references are real papers with real DOIs.
7. **Test coverage gaps.** What edge cases or contract violations are not tested?
8. **Architectural smells.** Anywhere `agent/` modules accumulate domain knowledge that should live in topic packs?

---

**Final paper for GPT to read:** `runs/latest/paper.md` (+ `supplement.md` for the audit trail).

**Repository:** https://github.com/DomLynch/Research-Agent-Bot-v4 (currently at commit `1e4e36c` on `main`).
