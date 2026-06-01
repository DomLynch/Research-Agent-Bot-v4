# Top 1 interesting findings — therapeutic_plasma_exchange

**Snapshot:** 2026-05-26T19-50-19Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=therapeutic_plasma_exchange) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 7
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=1)

---

## #1 — score 100 · effect_size

**Finding:** a 33.3% reduction in the median number of therapeutic plasma exchange days (5.0 vs 7.5 days) vs placebo.

- **Value:** 33.3%
- **Population:** individuals with acquired thrombotic thrombocytopenic purpura (aTTP)
- **Intervention:** caplacizumab
- **Alpha cues:** functional_endpoint
- **Source:** *Caplacizumab prevents refractoriness and mortality in acquired thrombotic thrombocytopenic purpura: integrated analysis* — Blood Advances (2021)
  · DOI: `10.1182/bloodadvances.2020001834`
- **Validator:** researka-tier2

- **Why it matters:** Reducing therapeutic plasma exchange days by a third can lower treatment burden, hospital stays, and healthcare costs for aTTP patients.
- **Caution:** This finding is based on a single study (k=1), with a fixed dose model that may not capture variability in real-world practice.
- **Next question:** Does this shorter treatment duration affect long-term remission rates or survival outcomes in aTTP?

---
