# Top 3 interesting findings — urolithin_A

**Snapshot:** 2026-05-27T09-35-54Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=urolithin_A) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 19
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=2, model_context=1)

---

## #1 — score 100 · effect_size

**Finding:** reduced mortality by 63% in the mouse model

- **Value:** 63.0%
- **Population:** mouse model of cisplatin-induced acute kidney injury
- **Intervention:** nanoparticle urolithin A
- **Alpha cues:** functional_endpoint
- **Source:** *Oral delivery of nanoparticle urolithin A normalizes cellular stress and improves survival in mouse model of cisplatin-induced AKI* — American Journal of Physiology-Renal Physiology (2019)
  · DOI: `10.1152/ajprenal.00346.2019`
- **Validator:** researka-tier2

- **Why it matters:** This finding implies Urolithin A could reduce fatal kidney damage in humans undergoing cisplatin chemotherapy, improving survival rates.
- **Caution:** The 63% mortality reduction was observed in a single mouse model, and human kidney physiology and cisplatin metabolism differ significantly.
- **Next question:** Does Urolithin A demonstrate similar nephroprotective effects in human clinical trials for acute kidney injury?

---

## #2 — score 76 · effect_size

**Finding:** significant improvements in muscle strength (∼12%) with intake of Urolithin A

- **Value:** 12.0%
- **Population:** middle-aged adults
- **Intervention:** Urolithin A (Mitopure)
- **Alpha cues:** translation_context
- **Source:** *Urolithin A improves muscle strength, exercise performance, and biomarkers of mitochondrial health in a randomized trial in middle-aged adults* — Cell Reports Medicine (2022)
  · DOI: `10.1016/j.xcrm.2022.100633`
- **Validator:** researka-tier2

- **Why it matters:** A 12% muscle strength boost in middle-aged adults suggests Urolithin A may delay age-related sarcopenia, supporting independent living and mobility.
- **Caution:** This improvement stems from one study with middle-aged adults, and the dose-response relationship and long-term effects are not yet defined.
- **Next question:** How does Urolithin A's muscle enhancement compare to established interventions like resistance training or protein supplementation in older populations?

---

## #3 — score 73 · effect_size

**Finding:** UA attenuated melanogenesis in B16 melanoma cells to 55.1 ± 3.8% of control at 10 μM.

- **Value:** 55.1%
- **Population:** B16 melanoma cells
- **Intervention:** Urolithin A at 10 μM
- **Alpha cues:** baseline
- **Source:** *Antimelanogenic Effect of Urolithin A and Urolithin B, the Colonic Metabolites of Ellagic Acid, in B16 Melanoma Cells* — Journal of Agricultural and Food Chemistry (2017)
  · DOI: `10.1021/acs.jafc.7b02442`
- **Validator:** researka-tier2

- **Why it matters:** Reducing melanogenesis by nearly 45% in melanoma cells highlights Urolithin A's potential for treating hyperpigmentation disorders or as a complementary anti-melanoma agent.
- **Caution:** The effect was measured in vitro with B16 cells at a specific dose, and in vivo efficacy, safety, and bioavailability in humans remain unverified.
- **Next question:** Can Urolithin A effectively inhibit melanogenesis in human skin models or in vivo without causing systemic toxicity?

---
