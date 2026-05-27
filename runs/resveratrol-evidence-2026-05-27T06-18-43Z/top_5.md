# Top 1 interesting findings — resveratrol

**Snapshot:** 2026-05-27T06-18-43Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=resveratrol) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 39
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: model_context=1)

---

## #1 — score 68 · effect_size

**Finding:** we observed a reduction of the viral titer by 80% with resveratrol

- **Value:** 80.0%
- **Population:** HCoV-229E coronavirus in vitro
- **Intervention:** resveratrol
- **Alpha cues:** low_signal_context
- **Source:** *Resveratrol Inhibits HCoV-229E and SARS-CoV-2 Coronavirus Replication In Vitro* — Viruses (2021)
  · DOI: `10.3390/v13020354`
- **Validator:** researka-tier2

- **Why it matters:** This finding suggests resveratrol could be a viable antiviral candidate against coronaviruses, aiding in the development of treatments for similar respiratory viruses like SARS-CoV-2.
- **Caution:** The result is from a single in vitro study (k=1) with unspecified dosing, which limits its direct translation to human health outcomes without further validation.
- **Next question:** What are the in vivo efficacy and safety profiles of resveratrol against coronaviruses, and what is the optimal therapeutic dose for potential human use?

---
