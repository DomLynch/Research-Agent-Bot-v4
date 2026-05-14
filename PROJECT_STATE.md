# PROJECT_STATE.md

## Current Objective
Build v07 (`synthesis-lite`) — greenfield, AAA-grade output.

**Role evolution (Sprint 39+):** v4 has additively become the
**curator / editor layer for the Researka platform** alongside the
synthesis-lite paper pipeline. The paper-writer pipeline below is
preserved and still operational; on top of it, v4 now also reads the
per-paper receipts it produces, computes per-topic 0..100 confidence
snapshots, watches them move over time, and emits a prioritized
"publish these N items" digest (Sprint 44, `agent/gap_analyzer.py`).
v4 emits opportunities; v3 (separate ~25k LOC writer) acts on user
queries independently — v4 does not trigger v3.

## Success Condition (current — staged CLI pipeline)
The pipeline is invoked stage-by-stage via individual scripts; a
single-command runner shipped in Sprint 15 (`build_topic_paper.py`).
For topic `<T>`:

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

Or via the single-command runner (Sprint 15+36, parallelised drafts):
```bash
python3 scripts/build_topic_paper.py --topic <T>
```

End-to-end success produces, under `runs/<topic>-paper-<utc-stamp>/`:
- `paper.md` (manuscript: Title + Abstract + Introduction + Methods +
  Results + Discussion + Limitations + Conclusion + Appendix A run
  audit + References + 6-block back-matter)
- `supplement.md` (S1–S10 with auto-rendered receipt cross-references)
- 4 JSON receipts the manuscript carries cross-references to:
  `eligibility_summary.json`, `primary_effect_input_set_strict.json`,
  `effect_extractions.json`, `effect_pool.json`
- `extraction_crosscheck.json` (Researka Tier 2 audit sidecar)
- `.stages/` (s1/s2/s3/s6/s7 intermediates — Sprint 38 consolidation)

Wall-clock ≤ 10 min. Cost ≤ $0.50/run (MiMo + Gemma).

**Cutover gate**: every stage exits 0 + the run-folder integrity test
(`tests/test_run_folder_integrity.py`) passes for the topic.

## Evidence-Index Pipeline (Sprint 39+, curator layer)
Runs alongside the paper pipeline above. Per topic, on each refresh:
```bash
python3 scripts/build_evidence_index.py --topic <T>
# writes runs/_index/<T>/<ts>.json + <ts>_movers.json + _latest_snapshot.json
```
Across all topics, on cadence:
```bash
python3 scripts/run_gap_analysis.py
# writes runs/_index/_digest_<ts>.json — top-N PublishOpportunity list
```
Operator reviews the digest, picks which items to push to Researka.
DB integration (Researka DB Sprint 2) will swap
`_latest_snapshot_path()` from local file → HTTP; analysis logic,
scoring, thresholds, and digest schema stay put.

## Build Order (12 steps — sequential, verify each)
1. ✅ **Foundation** — settings.py, env, scaffolding, smoke test
2. ✅ Retrieval base — httpx wrapper + cache + retry
3. ✅ Retrieval sources — PubMed, OpenAlex, Europe PMC, ClinicalTrials, Researka DB
4. ✅ paper_parser.py — PMC XML + DOI metadata
5. ✅ quant_extract.py — regex + LLM hybrid
6. ✅ spar_judge.py — Gemma judge + bounded 2-retry correction loop
7. ✅ tension_matrix.py — pairwise + self-pair assert
8. ✅ section_packets.py — per-outcome-class packets
9. ✅ evidence_state.py — orchestration + freeze() invariant
10. ✅ compiler.py + writer.py + editor_pass.py
11. ✅ contract.py — 10 fatal rules + verdict.py
12. ✅ Tests (unit + golden) + supplement plugins + cutover validation

## Current Sprint
**Sprint 44 landed** (commit `fc01fdf`) — `agent/gap_analyzer.py` emits
typed `PublishOpportunity` payloads gated on `publication_opportunity`
flags + `|delta_points| ≥ 10` strong-mover triggers, capped at top-5
per digest, priority-sorted, malformed-JSON tolerant. Standing by for
Researka DB Sprint 2 (`/api/v1/topics/{topic}/claims`).

## Definition of Done (Current Gate)
- [x] Fresh `runs/latest` contains `paper.md`, `supplement.md`, and the
      canonical JSON receipt sidecars named in the paper.
- [x] `pytest tests/test_run_folder_integrity.py` passes.
- [x] `pytest -q`, `ruff check agent tests`, and `mypy agent` pass.
- [x] No rendered manuscript/supplement prose claims absent run-folder files.
- [ ] AGENTS.md, PROJECT_STATE.md, and HANDOVER.md match the current runner and
      artifact shape.
- [ ] Researka DB Sprint 2 endpoint live → swap gap-analyser data source
- [ ] Digest renderer (markdown view of `_digest_<ts>.json`) for
      operator curation review

## Decisions Locked
- 2 models only (MiMo writer / Gemma judge+editor) — model stack is
  locked; never route LLM calls elsewhere without explicit approval
- Bounded 2-retry correction loop, no infinite repair
- Researka Database is source #16, called in parallel
- Sequential build, one step at a time, perfect before advancing
- Topic_pack TOML format reused from v06 (data, not code)
- Manuscript schema: 11 main sections + 8 supplement blocks (locked above)
- Dual-pass extraction with cross-family adjudicator (Sprint 28)
- Publication-opportunity trigger: confidence ≥ 70 AND k_pool ≥ 2
- Strong-mover trigger: |delta_points| ≥ 10 between snapshots
- Top-N cap: 5 opportunities per digest
- LOC ceiling: **9,400 hard gate in `agent/`** (cap history 3,000 →
  5,000 → 7,500 → 7,600 → 7,700 → 7,800 → 7,900 → 8,000 → 8,200 →
  8,400 → 8,500 → 8,700 → 8,900 → 9,000 → 9,200 → 9,400 — every bump
  documented in `scripts/loc_gate.sh`). New modules under the higher
  cap must delete or prevent a fake-evidence failure mode (contracts,
  validators, receipts, provenance, typed contracts) — not buy prose
  polish or speculation.

## Verification Commands
```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check agent tests
.venv/bin/python -m mypy agent
scripts/loc_gate.sh
```
