# Top 1 interesting findings — dasatinib

**Snapshot:** 2026-05-17T06-50-34Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=dasatinib) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 5
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: preclinical_cancer=1)

---

## #1 — score 59 · rate

**Finding:** Dasatinib, a multikinase inhibitor, was effective against 50% of DLBCL cell lines

- **Value:** 50.0%
- **Population:** DLBCL cell lines
- **Intervention:** dasatinib
- **Alpha cues:** low_signal_context
- **Source:** *Repurposing dasatinib for diffuse large B cell lymphoma* — Proceedings of the National Academy of Sciences (2019)
  · DOI: `10.1073/pnas.1905239116`
- **Validator:** researka-tier2

- **Why it matters:** Dasatinib's efficacy in 50% of DLBCL cell lines suggests it could offer a targeted treatment for a subset of patients with this aggressive lymphoma, potentially addressing unmet needs in refractory cases.
- **Caution:** This finding is based on in vitro cell line models with a single concentration, so it does not account for dose variability or physiological complexities that could affect clinical outcomes.
- **Next question:** What specific genetic or protein biomarkers in DLBCL cells correlate with dasatinib sensitivity to enable patient stratification?

---
