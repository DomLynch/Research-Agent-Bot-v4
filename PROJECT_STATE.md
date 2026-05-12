# PROJECT_STATE.md

## Current Objective
Build v07 (`synthesis-lite`) — greenfield, AAA-grade output.

## Success Condition (current — staged CLI pipeline)
The pipeline is invoked stage-by-stage via individual scripts; a
single-command runner is on the Sprint-13 backlog. For topic `<T>`:

```bash
python3 scripts/run_eligibility.py    --topic <T> --iter <N>
python3 scripts/freeze_primary_set.py runs/<latest-s7-dir> --topic <T>
python3 scripts/extract_effects.py    runs/<latest-s7-dir> --topic <T>
python3 scripts/draft_main.py         --topic <T> --iter <N> --section title_abstract_intro
python3 scripts/draft_main.py         --topic <T> --iter <N> --section methods
python3 scripts/build_results.py      --topic <T> --iter <N>
python3 scripts/draft_main.py         --topic <T> --iter <N> --section discussion
python3 scripts/stitch_paper.py       --topic <T>
python3 scripts/build_supplement.py   runs/latest --topic <T>
```

End-to-end success produces, under `runs/<topic>-paper-<utc-stamp>/`:
- `paper.md` (manuscript: Title + Abstract + Introduction + Methods +
  Results + Discussion + Limitations + Conclusion + Appendix A run
  audit + References + 6-block back-matter)
- `supplement.md` (S1–S10 with auto-rendered receipt cross-references)
- 4 JSON receipts that the manuscript carries cross-references to:
  `eligibility_summary.json`, `primary_effect_input_set_strict.json`,
  `effect_extractions.json`, `effect_pool.json`
- `extraction_crosscheck.json` (Researka Tier 2 audit sidecar)

Wall-clock ≤ 10 min. Cost ≤ $0.50/run (MiMo + Gemma).

**Cutover gate**: every stage exits 0 + the run-folder integrity test
(`tests/test_run_folder_integrity.py`) passes for the topic.

## Build Order (12 steps — sequential, verify each)
1. ⏳ **Foundation** — settings.py, env, scaffolding, smoke test
2. ⬜ Retrieval base — httpx wrapper + cache + retry
3. ⬜ Retrieval sources — PubMed, OpenAlex, Europe PMC, ClinicalTrials, Researka DB
4. ⬜ paper_parser.py — PMC XML + DOI metadata
5. ⬜ quant_extract.py — regex + LLM hybrid
6. ⬜ spar_judge.py — Gemma judge + bounded 2-retry correction loop
7. ⬜ tension_matrix.py — pairwise + self-pair assert
8. ⬜ section_packets.py — per-outcome-class packets
9. ⬜ evidence_state.py — orchestration + freeze() invariant
10. ⬜ compiler.py + writer.py + editor_pass.py
11. ⬜ contract.py — 10 fatal rules + verdict.py
12. ⬜ Tests (unit + golden) + supplement plugins + cutover validation

## Current Step
**Step 1 — Foundation. In progress.**

## Definition of Done (Step 1)
- [ ] `Settings` dataclass loads `.env` cleanly
- [ ] MiMo + OpenRouter + Researka URL/token + NCBI/SS/CORE/Crossref/Unpaywall
      keys all wired
- [ ] `pytest tests/test_settings.py` green
- [ ] `scripts/loc_gate.sh` passes (foundation LOC well under 3,000)
- [ ] `ruff check agent tests` clean
- [ ] `mypy agent` clean
- [ ] `.env` populated (not committed); `.env.example` documented
- [ ] AGENTS.md + PROJECT_STATE.md locked

## Decisions Locked
- 2 models only (MiMo writer / Gemma judge+editor)
- Bounded 2-retry correction loop, no infinite repair
- Researka Database is source #16, called in parallel
- Sequential build, one step at a time, perfect before advancing
- Topic_pack TOML format reused from v06 (data, not code)
- Manuscript schema: 11 main sections + 8 supplement blocks (locked above)
- LOC ceiling: **7,500 hard gate in `agent/`** (raised from 3,000 → 5,000
  → 7,500 across Sprint 6 and Sprint 11.1). New modules under the higher
  cap must delete or prevent a fake-evidence failure mode (contracts,
  validators, receipts, provenance) — not buy prose polish or speculation.

## Verification Commands
```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check agent tests
.venv/bin/python -m mypy agent
scripts/loc_gate.sh
```
