# Top 2 interesting findings — NAD

**Snapshot:** 2026-05-17T06-45-15Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=NAD) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 14
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: model_context=2)

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 82 · effect_size

**Finding:** women had higher plasma NAD+/NADH ratios than men (median 1.33 vs. 1.09, P<0.001)

- **Value:** 1.33
- **Population:** 205 probands without severe diseases (91 men, 114 women), 18-83 years old
- **Intervention:** N/A
- **Alpha cues:** subgroup, translation_context
- **Source:** *Sex-related differences in human plasma NAD+/NADH levels depend on age* — Bioscience Reports (2021)
  · DOI: `10.1042/bsr20200340`
- **Validator:** researka-tier2

- **Why it matters:** Higher NAD+/NADH ratios in women may indicate sex-based metabolic differences that influence healthspan or response to NAD+-modulating therapies.
- **Caution:** This cross-sectional observation from a single study with a broad age range cannot infer causality or account for hormonal dynamics over time.
- **Next question:** Do the observed sex differences in NAD+ ratios correlate with variations in mitochondrial function or clinical outcomes in aging-related diseases?

---

### Lane — `rate`


## #2 — score 56 · rate

**Finding:** RNAIII, a central quorum-sensing regulator of this bacterium's physiology, was found to be 5' NAD capped in a range from 10 to 35%

- **Value:** 5.0%
- **Population:** Staphylococcus aureus isolates
- **Intervention:** 5' NAD capping of RNAIII
- **Alpha cues:** baseline
- **Source:** *The 5′ NAD Cap of RNAIII Modulates Toxin Production in Staphylococcus aureus Isolates* — Journal of Bacteriology (2019)
  · DOI: `10.1128/jb.00591-19`
- **Validator:** researka-tier2

- **Why it matters:** NAD capping of RNAIII in Staphylococcus aureus suggests a novel regulatory layer in bacterial communication, potentially affecting infection pathogenesis and treatment targets.
- **Caution:** The study relied on laboratory isolates with variable NAD capping rates (10-35%), which may not accurately represent bacterial behavior in host tissues.
- **Next question:** How does NAD capping of RNAIII influence the stability or function of this regulator during Staphylococcus aureus infection in vivo?

---
