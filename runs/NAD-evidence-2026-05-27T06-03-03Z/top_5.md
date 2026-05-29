# Top 2 interesting findings — NAD

**Snapshot:** 2026-05-27T06-03-03Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=NAD) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 11
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=2)

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `threshold`


## #1 — score 92 · threshold

**Finding:** Clinical efficacy expressed by blood NAD concentration and physical performance reaches highest at a dose of 600 mg daily oral intake.

- **Value:** 600.0mg/day
- **Population:** 80 middle-aged healthy adults
- **Intervention:** 600 mg NMN daily
- **Alpha cues:** translation_context
- **Source:** *The efficacy and safety of β-nicotinamide mononucleotide (NMN) supplementation in healthy middle-aged adults: a randomized, multicenter, double-blind, placebo-controlled, parallel-group, dose-dependent clinical trial* — GeroScience (2022)
  · DOI: `10.1007/s11357-022-00705-1`
- **Validator:** researka-tier2

- **Why it matters:** This is worth checking because it ties 600 mg NMN daily in 80 middle-aged healthy adults to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

### Lane — `effect_size`


## #2 — score 82 · effect_size

**Finding:** Blood NAD concentrations were statistically significantly increased among all NMN-treated groups at day 30 and day 60 (all p ≤ 0.001).

- **Value:** 30.0
- **Population:** 80 middle-aged healthy adults
- **Intervention:** NMN supplementation at 300 mg, 600 mg, or 900 mg daily
- **Alpha cues:** translation_context
- **Source:** *The efficacy and safety of β-nicotinamide mononucleotide (NMN) supplementation in healthy middle-aged adults: a randomized, multicenter, double-blind, placebo-controlled, parallel-group, dose-dependent clinical trial* — GeroScience (2022)
  · DOI: `10.1007/s11357-022-00705-1`
- **Validator:** researka-tier2

- **Why it matters:** This is worth checking because it ties NMN supplementation at 300 mg, 600 mg, or 900 mg daily in 80 middle-aged healthy adults to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---
