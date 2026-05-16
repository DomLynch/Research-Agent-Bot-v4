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
**Sprint 70 in flight** (head ≈ `efbb7d1`, this commit pending) —
alpha-mode Researka pipeline working end-to-end: discovery (Sprint 63)
→ build_topic_evidence_run (with PICO enrichment Sprint 61, numeric
sanitizer Sprint 64 + 69, dedup + lanes + editorial Sprint 60, fact-id
binding Sprint 67) → opportunities gate (Sprint 59) → signal post
(Sprint 64 + 66 + 68 strict binding lock). One-command autonomous
curator cycle via `scripts/run_curator_cycle.py` (Sprint 65).
Sprints 45-68 each shipped + 4-way deployed (macbook + GitHub branch
+ GitHub main + VPS) — see `git log` for Sprint commits.

**Sprint 68 (shipped) closed earlier auditor gaps:** strict signal-
post binding (A_core/B_context only); universal epi ratio units
(OR/HR/RR/AOR/AHR/IRR/ROR/SMR/IPR → effect_size); position-aware
p-prefix detector; cycle runner failure propagation.

**Sprint 70 (in flight, this commit pending) closes the auditor's
remaining 2026-05-16 review gaps:**
- `agent/topic_discovery.py` — cross-topic paper anchorage dampening.
  When the same paper (by DOI / title key) sits in M ≥ 3 topics'
  top-K driver papers, its contribution to each topic's velocity is
  scaled by `1/sqrt(M)`. Closes the auditor case where a single
  2019 ACC/AHA cardiovascular guideline was the #1 driver of
  exercise, metformin, and caloric_restriction velocity rankings.
  Universal — structural over-citation signal, no domain literals.
- `scripts/regen_top_from_run.py` — offline regen tool that takes a
  run dir and re-renders `top_N.md` from existing `all_facts.json`
  using the current sanitizer/scoring/dedup pipeline. Used to land
  Sprint 69 fixes across all 40 historical runs without re-fetching
  from the DB.
- `tests/test_run_folder_top_n_integrity.py` — forward-looking gate
  that walks every `runs/*-evidence-*/top_*.md` with a matching
  `all_facts.json` and fails if any (Finding, Value) pair would be
  filtered by the current sanitizer. Forces operators to regen
  on-disk artifacts after sanitizer changes; closes the "code
  filters but artifact still shows the bad fact" loop.
- All 40 evidence runs regenerated; integrity gate passes
  end-to-end.
- Doc/state sync: PROJECT_STATE / AGENTS / loc_gate.sh comment text
  now reflect Sprint 70 head + 11,700 ceiling.

**Sprint 69 (shipped, head `efbb7d1`) closed the sirtuin top_5
artifact leaks the auditor caught in the 2026-05-15 review:**
- `agent/numeric_sanitizer.py` rule 3: capitalized 1-4 letter
  prefix + space/hyphen + integer value → cell-line / compound code
  (Cal 27, HCT 116, T47 D). Walk-stop in the original rule 1 misses
  these because the space breaks the token. Guarded by `_UNIT_FOLLOWS`
  so a value followed by %, µM, mg, fold, °C etc. is still recognised
  as a real measurement even when a capitalized prefix sits before
  it (IC50 SIRT2 0.25 µM stays a finding).
- `agent/numeric_sanitizer.py` rule 4: value + space + time unit
  → bare duration (72 h, 24 hours, 30 min, 8 days). Catches the
  duration-treated-as-effect case the extractor leaves with units
  field empty.
- Auditor verification: sirtuin top_5 leak gone — `whey for 72 h`
  (fid 17510) and `Cal 27 cell proliferation` (fid 15814) both
  filtered; IC50 0.25/0.78 µM measurements preserved.

Standing by for: Researka write-surface spec (publish path #1 on the
operator queue), cross-topic paper dedup in discovery (Sprint 70
candidate — the prior-auditor Priority 5 ACC/AHA anchoring problem
remains deferred), Tier-1 canonical curation for non-rapamycin
topics (DB-side, not v4), sirtuin-relevance semantic check for
APO10LA-style off-target findings (Sprint 70+ candidate).

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
