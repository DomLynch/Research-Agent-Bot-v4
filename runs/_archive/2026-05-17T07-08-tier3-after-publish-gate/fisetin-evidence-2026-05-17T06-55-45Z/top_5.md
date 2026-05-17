# Top 2 interesting findings — fisetin

**Snapshot:** 2026-05-17T06-55-45Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=fisetin) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 13
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: model_context=1, preclinical_cancer=1)

---

## #1 — score 75 · effect_size

**Finding:** fisetin and myricetin at 8 µg/mL inhibited the growth of S. mutans by 81% and 86%, respectively.

- **Value:** 86.0%
- **Population:** Streptococcus mutans
- **Intervention:** myricetin at 8 µg/mL
- **Alpha cues:** baseline
- **Source:** *Bactericidal effect of extracts and metabolites of Robinia pseudoacacia L. on Streptococcus mutans and Porphyromonas gingivalis causing dental plaque and periodontal inflammatory diseases.* — Molecules (Basel, Switzerland) (2015)
  · DOI: `10.3390/molecules20046128`
- **Validator:** researka-tier2

- **Why it matters:** Fisetin and myricetin effectively inhibit Streptococcus mutans growth, highlighting their potential as natural agents for preventing dental cavities in oral hygiene products.
- **Caution:** This in vitro study used a single concentration (8 µg/mL) and model bacteria, so results may not directly apply to human oral conditions or varying doses.
- **Next question:** Can these compounds maintain their antibacterial efficacy in vivo, such as in animal models of dental plaque or human clinical trials?

---

## #2 — score 66 · effect_size

**Finding:** Intraperitoneal treatment of nude mice with fisetin at 30mg/kg resulted in a 35.7% (P < 0.001) inhibition of tumor growth.

- **Value:** 35.7%
- **Population:** nude mice
- **Intervention:** fisetin at 30mg/kg
- **Alpha cues:** baseline
- **Source:** *Fisetin, a dietary flavonoid, induces apoptosis of cancer cells by inhibiting HSF1 activity through blocking its binding to the hsp70 promoter.* — Carcinogenesis (2015)
  · DOI: `10.1093/carcin/bgv045`
- **Validator:** researka-tier2

- **Why it matters:** Fisetin's tumor growth inhibition in nude mice suggests it could be developed as an anti-cancer therapy, offering a potential new treatment avenue.
- **Caution:** The study relied on immunodeficient nude mice and a specific intraperitoneal dose (30mg/kg), which may not reflect human immune responses or optimal dosing.
- **Next question:** What are the underlying molecular mechanisms of fisetin's anti-tumor activity, and does it show efficacy in immunocompetent models or human cancer cell lines?

---
