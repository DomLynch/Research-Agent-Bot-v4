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
**Sprint 83 shipped** — longevity alpha Top 5 scoring pass:
- `agent/alpha_selector.py` now exposes deterministic `alpha_cues()`
  and clamps positive/negative weighted cues to 0..100. Code remains
  universal; cue vocabulary and weights live in
  `topic_packs/alpha_selection.toml`.
- `topic_packs/alpha_selection.toml` adds data-level cues for
  translational context, functional endpoints, timing/reversal, and
  low-signal assay context. Functional endpoints now outrank generic
  magnitude when the evidence is A/B-bound.
- `scripts/build_topic_evidence_run.py` renders `Alpha cues` per card
  and excludes context-poor numeric fragments from operator-facing
  Top cards after the A/B lane filter.
- Fresh curator cycle retained at `runs/_curator_cycles/2026-05-16T18-01-38Z.*`.
  Ran metformin, mTOR, rapamycin, autophagy, exercise. `runs/latest`
  points to the newest fresh run:
  `exercise-evidence-2026-05-16T18-12-38Z`.
- Concrete output improvements: exercise mortality moved to #1;
  metformin cancer mortality moved to #1; mTOR mortality moved to #1;
  rapamycin lifespan cards all show endpoint / subgroup / timing cues;
  autophagy numeric-only Cox fragment was removed from Top cards.

**Sprint 82 shipped** — mTOR-specific render-regression lock:
- Added `test_mtor_mortality_survival_editorial_swap_regression` in
  `tests/test_top5_rendering.py`. It uses the historical mTOR
  mortality / HNSCC survival card pair and asserts the MiMo
  "Why it matters" text remains bound to the correct fact after lane
  grouping reorders cards.
- This is a test-only lock for the concrete auditor complaint; no
  production code or topic-specific runtime rule was added.
- Full local quality gate rerun after the test: `pytest -q`, ruff,
  mypy, LOC, and run-folder integrity.

**Sprint 81 shipped** — retained live proof artifacts for the Sprint 80
frontier-citation and Sprint 79 render-order fixes:
- Fresh telomere artifact retained at
  `runs/telomere-evidence-2026-05-16T17-06-09Z/`. Gate output:
  A=6, B=8, C=5, D=17; lead thesis `survives`; `signal_post.md`
  confidence is `evidence_backed_signal`; cited fact IDs are
  `6907, 6908, 11257, 3475`.
- Fresh mTOR artifact retained at
  `runs/mtor-evidence-2026-05-16T17-08-58Z/`. The current strict
  A/B + coherent-theme filter emits two cards, not the historical
  four-card noisy surface. Both retained cards' MiMo "Why it matters"
  blocks describe their own findings, closing the previous render-order
  swap without preserving stale bad artifacts.
- Removed stale telomere artifact
  `runs/telomere-evidence-2026-05-16T16-11-07Z/`, which still showed
  `evidence_binding_failed` and contradicted Sprint 80.
- `runs/latest` now points to the newest retained evidence run:
  `mtor-evidence-2026-05-16T17-08-58Z`.

**Sprint 80 shipped** — frontier citation-recovery + proof hygiene:
- Fixed a real telomere regression where MiMo's JSON truncated inside
  thesis `rationale` before `cited_fact_ids`; the tolerant parser kept
  the thesis but left citations empty, so the binding gate correctly
  downgraded it. `agent/frontier_review.py` now recovers structural
  `fact <id>` references from thesis prose, and for single-thesis
  truncated reviews from the top-level lens/tensions/gaps, filtered
  strictly to A/B EVIDENCE facts.
- Added a universal non-biomedical regression test:
  `test_truncated_single_thesis_recovers_evidence_fact_refs` uses
  carbon-tax fact IDs and proves ALPHA HINT ids are not promoted to
  citations.
- Replayed the captured bad telomere raw response: recovered non-empty
  citations. Fresh telomere run at `2026-05-16T16-30-34Z` returned
  `evidence_backed_signal` with lead citations `6907, 6908, 11257`.
- Fresh mTOR run at `2026-05-16T16-30-34Z` verified the editorial
  card text is bound to each card's own fact; the ad hoc verification
  folders were removed afterward to keep `runs/` clean.
- Tightened `agent/fact_facets.py` fallback selection to avoid the
  mypy `max(..., key=...)` type edge and empty-priority runtime edge.

**Sprint 79 shipped** — coherent alpha Top 5 curation layer:
- Fixed render-time editorial leakage when lane grouping reorders cards;
  each card now resolves MiMo editorial text by original fact index, not
  rendered rank.
- Added data-driven broad-theme grouping:
  `agent/fact_facets.py` loads facet markers and theme groups from
  `topic_packs/facets.toml`; code contains no domain vocabulary.
- Added data-driven alpha boosts:
  `agent/alpha_selector.py` loads contrast/subgroup markers from
  `topic_packs/alpha_selection.toml`.
- Regenerated via the normal curator cycle at 2026-05-16T16:02:45Z.
  Current kept runs: autophagy, exercise, rapamycin, telomere,
  metformin. `runs/latest` points to the newest metformin run.

**Sprint 78 shipped** — fresh curator top-5 artifact refresh and run-folder cleanup:
- Re-ran `scripts/run_curator_cycle.py --top 5 --cooldown-hours 0` on
  `main` at 2026-05-16T15:10:57Z.
- Current kept evidence runs are exercise, mtor, rapamycin, metformin,
  and caloric_restriction from 2026-05-16T15:11–15:22Z.
- `runs/latest` points to
  `runs/caloric_restriction-evidence-2026-05-16T15-22-02Z`.
- `runs/_curator_cycles` and `runs/_topics_discovery` retain only the
  matching current cycle/discovery summaries.

**Sprint 77 shipped (head `03ea912`)** — closed signal-post truth gaps
around adjacent-signal rendering and label consistency.

**Sprint 76 shipped (head `ab50be8`)** — alpha-mode Researka evidence pipeline is
lane-gated at the top-card surface: discovery (Sprint 63 + Sprint 70
anchorage dampening) → build_topic_evidence_run (PICO enrichment
Sprint 61, numeric sanitizer Sprint 64 + 69, same-paper dedup +
editorial Sprint 60, **A_core/B_context-only top_N ranking Sprint 71**)
→ opportunities gate (Sprint 59) → signal post (Sprint 64 + 66 + 68
strict binding lock). One-command autonomous curator cycle via
`scripts/run_curator_cycle.py` (Sprint 65).

**Sprint 76 (shipped, head `ab50be8`) — adjacent-signal surfacing
without evidence leakage:**
- `scripts/build_signal_post.py` now renders an "Adjacent signals to
  consider" section from top-magnitude C/D-lane facts. These are
  explicitly labeled research prompts, **not cited evidence**.
- Live 3-topic trace on Sprint 76: telomere and autophagy promoted to
  `evidence_backed_signal`; sirtuin honestly rendered `# No signal`
  with adjacent prompts instead of fake evidence.
- `tests/test_signal_post_adjacent.py` locks the ordering, lane
  exclusion, and non-evidence wording.

**Sprint 75 (shipped, head `63acaef`) — closes the
2026-05-16 auditor's "yield gap" critique. The system is safe
(refuses bad evidence) but was suppressing real product because
MiMo (frontier reviewer) was seeing ALL facts — including D_bad —
and forming theses around them, which the binding gate then
correctly killed:**
- `agent/frontier_review.py` — `run_frontier_review` now takes
  `(evidence_facts, alpha_hints)` separately. EVIDENCE FACTS (A_core
  / B_context lane) get fact-id tags and are the ONLY ids MiMo may
  cite. ALPHA HINTS (C_noise / D_bad_extraction) are rendered as
  untagged phrases under an "INSPIRATION ONLY, MAY NOT BE CITED"
  block and feed `next_extractions` only. The system prompt's hard-
  rule #4 spells this out.
- `scripts/build_topic_evidence_run.py` — caller splits facts via
  `classify_lanes(facts, topic)` before invoking the frontier
  reviewer.
- `scripts/build_signal_post.py` — new alpha label
  `curation_needed` fires when bound_count == 0 AND MiMo emitted
  actionable `next_extractions`. Constructive replacement for the
  pessimistic `evidence_binding_failed` label. New
  `_curation_brief()` writes `curation_brief.md` listing the
  unbound cited fact-ids + MiMo's targeted extractions — turns
  noisy alpha into a bounded curation task.
- `scripts/build_signal_post.py` logger fix — `[signal-post]`
  print now uses the actually-rendered label (with binding +
  hints override applied), not the pre-binding base. Was an
  audit-trust hazard: log said `frontier_hypothesis` while
  signal_post.md said `evidence_binding_failed`.
- `scripts/run_curator_cycle.py` — `curation_needed` added to the
  marker scan list so cycle summary surfaces it correctly.
- 1 new test `test_build_messages_evidence_vs_hints_boundary` locks
  the dual-block boundary: hint phrases do NOT carry fact-ids and
  appear under `ALPHA HINTS (INSPIRATION ONLY, MAY NOT BE CITED)`;
  system prompt contains `cited_fact_ids must reference only ids
  from EVIDENCE`.
- Bonus housekeeping: 48 untracked macOS Finder code/config duplicates
  (`* 2.py`, `* 2.toml`) deleted. Test count dropped from 1341 to
  932 because pytest was silently collecting + passing the dupes
  against the OLD function signatures. Current canonical gate:
  945 passed, 1 xfailed.

**Sprint 73 (shipped, head `bc08c83`) — closed the
2026-05-16 auditor's locality bug + over-claim correction:**
- `agent/numeric_role_classifier.py` — regimen-marker check is now
  LOCALITY-AWARE. Markers must sit within a window of [-15, +25]
  chars around the value, not anywhere in the phrase. Closes the
  auditor's three failing cases verbatim:
  `Mediterranean diet reduced LDL by 30%` → `effect_size`,
  `policy protocol cut emissions by 8%` → `effect_size`,
  `training regimen improved VO2max by 12%` → `effect_size`.
  All six positive regimen cases (carbon restriction, austerity
  protocol, load conditions, VO2max regimen, caloric restriction,
  CR conditions) still return `regimen`.
- 4 new negative tests in `tests/test_numeric_role_classifier.py`
  lock the locality contract.
- Honest correction: the previous Sprint 72 summary claimed "zero
  biomedical literals in `agent/`" — that was an overclaim. The
  marker vocabulary in `topic_packs/role_markers.toml` is now
  universal-only, but `agent/` still contains domain-leaning
  surfaces outside the role classifier:
  * `agent/risk_of_bias.py` — `SYRCLE` / `Cochrane-RoB-2` /
    `ROBINS-I` framework definitions (these are named tools for
    biomedical research; turning them into a data file is a
    separate sprint).
  * `agent/include_contract.py` — disease-term lists
    (`cancer / tumor / diabet / alzheimer / parkinson`) used to
    gate include eligibility for current rapamycin-era data.
  * `agent/source_audit.py`, `agent/effect_extraction.py`,
    `agent/eligibility_merge.py`, `agent/back_matter.py`,
    `agent/methods_honesty.py`, `agent/topic_synonyms.py`,
    `agent/evidence_index.py` — biomedical examples in
    docstrings / prompts (`mice`, `rapamycin/sirolimus`,
    `lifespan`, `mortality`).
  These are scheduled for moving to topic-pack data files in
  Sprint 74+. The Sprint 72 universal-no-hardcoding sweep was
  scoped to the role classifier only.

**Sprint 72 (shipped, head `665a5de`) — closes the auditor's
strictest reading of universal-no-hardcoding for the role
classifier:**
- Marker vocabulary moved out of code into data:
  `topic_packs/role_markers.toml` is now the single source of truth
  for the regimen / sample-size word lists. `agent/numeric_role_
  classifier.py` reads via `_load_role_markers()` (lru-cached;
  degrades to empty sets on missing/malformed file). The classifier
  is now pure logic; vocabulary is data.
- Structural contract lock — `tests/test_numeric_role_classifier.py
  ::test_loaded_role_markers_have_no_biomedical_literals` walks the
  loaded TOML and asserts no clinical / animal-husbandry / drug /
  disease literal leaked in. Any future regression is a CI failure.
- 3 missing universal fixtures the auditor flagged are now
  explicitly in `tests/test_numeric_sanitizer.py`: Sweden carbon
  tax for 30 years (climate duration), 15% YoY revenue (business
  growth), 5.25% Fed Funds rate (finance policy rate). Plus a
  Q3-2024 quarter-year identifier fixture documenting that
  `Q3 2024` -> 2024 is correctly flagged as an identifier-embed
  by the same Sprint 69 rule that catches `MCF 7`.

**Sprint 71 closed the MiMo hook review issues from 2026-05-16:**
- `scripts/build_topic_evidence_run.py` now ranks `top_N.md` cards only
  from facts whose current lane verdict is `A_core` or `B_context`.
  `D_bad_extraction` and `C_noise` facts remain in receipts for audit,
  but cannot appear as operator-facing top findings.
- `scripts/regen_top_from_run.py` uses the same lane-aware path and
  updates `MANIFEST.json` `top_md.sha256` after overwriting `top_N.md`.
- `tests/test_run_folder_top_n_integrity.py` now has two checks:
  sanitizer-artifact rejection and lane-bindability rejection. This
  catches p-values, regimens, doses, durations, and off-topic C-lane
  facts that are syntactically valid numbers but not top findings.
- All 40 canonical regen-able evidence runs were regenerated. Some
  historical runs now honestly render fewer than five cards when the
  pool has fewer than five A/B facts.
- The discovery queue was regenerated at
  `runs/_topics_discovery/2026-05-16T10-22-24Z.json`.
- `PROJECT_STATE.md`, `AGENTS.md`, and `scripts/loc_gate.sh` now agree
  on the 11,700 LOC ceiling and current Sprint 71 state.
- `agent/numeric_role_classifier.py` universal-marker sweep — dropped
  biomedical/clinical-specific markers that leaked into the role
  classifier during Sprint 64:
  * `_REGIMEN_MARKERS`: removed `"feeding"`, `"feed"`, `"of ad lib"`,
    `"of ad libitum"` (animal-husbandry Latin). Kept universal
    `"restriction"`, `"restricted"`, `"diet"`, `"conditions"`,
    `"regimen"`, `"protocol"`.
  * `_SAMPLE_SIZE_MARKERS`: removed `"patients"`, `"volunteers"`
    (clinical-trial vocabulary). Kept universal `"n="`, `"n ="`,
    `"participants"`, `"subjects"`.
  * 7 new tests in `tests/test_numeric_role_classifier.py` cover
    carbon-restriction (climate), budget-protocol (public finance),
    engineering-load (engineering), training-regimen (sports),
    survey-respondents (social science), economics-subjects, plus a
    negative test that locks the dropped markers as no-ops. Closes
    the universal-no-hardcoding contract that the 2026-05-16 audit
    flagged.

**Sprint 70 (shipped) added cross-topic paper anchorage dampening:**
when the same paper (by DOI / title key) sits in M ≥ 3 topics' top-K
driver papers, its velocity contribution is scaled by `1/sqrt(M)`.
This reduces broad-review/guideline dominance but does not fully
suppress it; the refreshed queue still shows the 2019 ACC/AHA guideline
as a leading paper for several topics. Stronger anchor suppression
remains an open discovery-quality item.

**Sprint 68/69 (shipped) closed earlier auditor gaps:** strict signal-
post binding (A_core/B_context only); universal epi ratio units
(OR/HR/RR/AOR/AHR/IRR/ROR/SMR/IPR → effect_size); position-aware
p-prefix detector; cycle runner failure propagation; and the sirtuin
`72 h` / `Cal 27` sanitizer leaks.

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
operator queue), stronger discovery anchor suppression, Tier-1
canonical curation for non-rapamycin topics (DB-side, not v4), and
sirtuin-relevance semantic checks for APO10LA-style off-target findings.

## Definition of Done (Current Gate)
- [x] Fresh `runs/latest` contains `paper.md`, `supplement.md`, and the
      canonical JSON receipt sidecars named in the paper.
- [x] `pytest tests/test_run_folder_integrity.py` passes.
- [x] `pytest -q`, `ruff check agent tests`, and `mypy agent` pass.
- [x] No rendered manuscript/supplement prose claims absent run-folder files.
- [x] AGENTS.md and PROJECT_STATE.md match the current runner and
      artifact shape.
- [ ] HANDOVER.md is still a legacy paper-pipeline external-review
      packet and needs refresh before reuse.
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
- LOC ceiling: **14,000 hard gate in `agent/`** (Sprint 74 operator-
  approved bump from 11,700 to give headroom for the universal-no-
  hardcoding refactors of `include_contract.py` and `risk_of_bias.py`).
  Full cap history is
  documented in `scripts/loc_gate.sh`. New modules under the higher cap
  must delete or prevent a fake-evidence failure mode (contracts,
  validators, receipts, provenance, typed contracts) — not buy prose
  polish or speculation.

## Verification Commands
```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check agent tests
.venv/bin/python -m mypy agent
scripts/loc_gate.sh
```
