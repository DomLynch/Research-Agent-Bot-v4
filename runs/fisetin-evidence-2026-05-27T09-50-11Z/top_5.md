# Top 1 interesting findings — fisetin

**Snapshot:** 2026-05-27T09-50-11Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=fisetin) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 17
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: model_context=1)

---

## #1 — score 87 · effect_size

**Finding:** Only quercetin and fisetin inhibited DENV-2 and DENV-3 infection in the absence or presence of enhancing antibody (>90%, p<0.001);

- **Value:** 90.0%
- **Population:** Human U937-DC-SIGN macrophages infected with dengue virus serotypes 2 or 3
- **Intervention:** quercetin and fisetin
- **Alpha cues:** translation_context
- **Source:** *&lt;p&gt;Antiviral and immunomodulatory effects of polyphenols on macrophages infected with dengue virus serotypes 2 and 3 enhanced or not with antibodies&lt;/p&gt;* — Infection and Drug Resistance (2019)
  · DOI: `10.2147/idr.s210890`
- **Validator:** researka-tier2

- **Why it matters:** Fisetin's strong inhibition of dengue virus in human macrophages indicates its potential as an antiviral agent to reduce dengue severity in high-burden regions.
- **Caution:** This finding is based on a single in vitro study using a specific cell line, so it may not reflect real-world human immune responses or dose-dependent effects in vivo.
- **Next question:** How does fisetin perform in animal models of dengue infection, and what are the safe and effective doses for potential therapeutic application?

---
