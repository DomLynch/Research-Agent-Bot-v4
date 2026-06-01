# Top 1 interesting findings — senolytic

**Snapshot:** 2026-05-27T05-41-34Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=senolytic) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 20
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: regimen_or_dose=1)

---

## #1 — score 90 · effect_size

**Finding:** BMSC-derived osteoblasts from the navitoclax treated mice were impaired in their ability to produce a mineralized matrix (-88% females, -83% males)

- **Value:** -88.0%
- **Population:** aged female mice
- **Intervention:** navitoclax (ABT-263) 50 mg/kg body mass daily for 2 weeks
- **Alpha cues:** subgroup
- **Source:** *The Senolytic Drug Navitoclax (ABT-263) Causes Trabecular Bone Loss and Impaired Osteoprogenitor Function in Aged Mice* — Frontiers in Cell and Developmental Biology (2020)
  · DOI: `10.3389/fcell.2020.00354`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** -83.0% (BMSC-derived osteoblasts from the navitoclax treated mice we); -60.1% (navitoclax treatment decreased trabecular bone volume fracti); -45.6% (navitoclax treatment decreased trabecular bone volume fracti)

- **Why it matters:** Navitoclax-induced impairment of osteoblast function could worsen age-related bone loss, posing risks for senolytic therapy in osteoporosis-prone populations.
- **Caution:** This result is derived from a single study (k=1) using a mouse model with unspecified dosing, limiting direct applicability to humans.
- **Next question:** Can the bone formation deficit be reversed or prevented by adjusting navitoclax dosing or combining it with bone-anabolic agents?

---
