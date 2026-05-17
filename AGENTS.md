# AGENTS.md

## Purpose
Research Agent Bot v4 (`synthesis-lite`) produces AAA-grade, source-grounded
research papers in a deliberately small core. Main manuscript = argument.
Supplement = audit. Compiler = truth. LLM = prose. Contract = enforcement.

**No LLM owns truth. No literal owns topic. No gate owns more than its rule.
No section owns evidence outside its packet.**

## Current State — 2026-05-17 (Sprint 89 context-memo publish surface)
- LOC ceiling: **14,000 in `agent/`** (hard gate, `scripts/loc_gate.sh`).
  See the cap-doctrine header in `loc_gate.sh` for the full bump
  history. Every module under the higher cap must delete or prevent a
  fake-evidence failure mode (typed contract, validator, receipt,
  provenance) — not buy prose polish or speculative abstraction.
- Universal-no-hardcoding: topic packs own domain vocabulary, anchors,
  sentinels, eligibility terms, metric families, ethics + conflicts
  back-matter prose. Known legacy biomedical-bearing `agent/` surfaces
  remain inventoried in `PROJECT_STATE.md`; do not add new ones.
- Build mode: sequential sprints, verify before advancing.
- Curator-layer role (Sprint 39+): on top of the paper pipeline, v4
  also reads per-paper receipts, computes per-topic 0..100 confidence
  snapshots, and emits a prioritized publish-opportunity digest.
- Quality gates: `pytest -q`, `ruff check agent tests scripts`,
  `mypy agent`, and `scripts/loc_gate.sh` must all pass before commit.
  For paper runs, `tests/test_run_folder_integrity.py` must pass
  against `runs/latest`; for evidence runs,
  `tests/test_run_folder_top_n_integrity.py` must pass against all
  canonical regen-able `top_N.md` artifacts.

## Hard Rule
```text
LLM PROPOSES. CODE DISPOSES.
- Counts and tables: deterministic, computed once in EvidenceState.freeze()
- Prose: LLM, packet-scoped, never sees global state
- Contract: ONE module, 10 fatal rules, nothing else gates ship
- Correction: bounded 2-retry judge→writer loop, then publish as-is
```

## Model Stack — 2 models only
- **Writer**: MiMo v2.5 Pro (Xiaomi, OpenAI-compatible). Base URL via
  `MIMO_BASE_URL`. Model id via `MIMO_MODEL`.
- **Judge + Editor pass**: Gemma 4 31B via OpenRouter (`google/gemma-4-31b-it`).
- **Correction loop**: judge returns structured issues; MiMo rewrites; max
  `WRITER_MAX_RETRIES` (default 2) attempts; then publish.

Judge family ≠ writer family. Non-negotiable.

## Data Sources (16)
PubMed, OpenAlex, Europe PMC, ClinicalTrials.gov, Crossref, Unpaywall,
Semantic Scholar, CORE, OSF Preprints, bioRxiv/medRxiv, plus 5 secondary,
plus **Researka Database** (source #16, internal canonical hot index at
`https://database.researka.org/api/v1/search`). All called in parallel,
deduped by DOI/PMID, ranked at union.

## Non-Negotiables
1. Judge model family ≠ writer model family. Always.
2. **Universal-no-hardcoding**: every prompt, gate, denylist, and rule is
   topic-agnostic. Multi-domain anchors when examples needed.
3. **No regression**: every new run must not worsen P1, numeric traceability,
   consistency audit, citation leakage, word count, or orphan citations vs
   the baseline pinned in `docs/no_regression_baseline.txt`.
4. **No backstop. No repair loop** beyond the bounded 2-retry judge→writer
   correction. Under-floor section = contract FAIL.
5. **No scrubber.** If a section breaks contract, paper does not ship AAA.
6. Python ≥ 3.11. Stdlib first. Every new dependency justified in `DECISIONS.md`.
7. Each compile step is a pure function of its inputs and writes a sidecar
   JSON. No global state. No big-bang refactors.

## Session Start
- Read this file and `PROJECT_STATE.md` before code changes.
- Call `get_playbook()` and `get_aaa_protocol()` via knowledge MCP.
- Confirm current sprint + step + Definition of Done.

## Verification Commands
```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check agent tests
.venv/bin/python -m mypy agent
scripts/loc_gate.sh
```

## Architecture (9-step pipeline)
```
1. EvidenceState.build(topic)        retrieval + parse + extract + SPAR
2. EvidenceState.freeze()            counts ONCE, immutable
3. compiler.render_supplement(state) tables/counts/refs (deterministic)
4. section_packets.build(state)      per-outcome packets, accepted-only
5. writer.write_sections(packets)    LLM prose, packet-scoped
6. compiler.render_main(prose, state) stitched in schema order
7. editor_pass.polish(main_md)       LLM tone-only pass, no fact changes
8. contract.validate(main, supp, state) 10 fatal rules
9. verdict.emit(contract_result)     AAA only if contract PASS
```

## Manuscript Schema (locked 2026-05-11)
### Main (11 sections)
Abstract · Introduction · Methods · Results · Boundary-condition synthesis ·
Discussion · Limitations · Conclusion · Data/code availability ·
Short AI-use disclosure · References

### Supplement
AI-use architecture · Model names · LLM call count · Patch trail
(judge→writer corrections) · Researka submitter block · Full rejected
evidence table · Full provenance bundle · Certification language
