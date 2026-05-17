# Top 2 interesting findings — spermidine

**Snapshot:** 2026-05-17T07-01-13Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=spermidine) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 18
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: model_context=2)

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 70 · effect_size

**Finding:** Pretreatment with Spd dramatically improved grain yield per plant of KDML105 from 17.7 to 28.7 g (62% increase)

- **Value:** 62.0%
- **Population:** rice cultivar KDML105
- **Intervention:** 1 mM spermidine pretreatment
- **Alpha cues:** baseline
- **Source:** *Effects of exogenous spermidine (Spd) on yield, yield-related parameters and mineral composition of rice ('Oryza sativa' L. ssp. 'indica') grains under salt stress* — Australian Journal of Crop Science (2013)

- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 16.0% (Pretreatment with Spd improved grain yield per plant of Pokk)

- **Why it matters:** Spermidine pretreatment can dramatically boost rice grain yield, presenting a feasible agricultural intervention to improve food security in staple crops.
- **Caution:** The effect was observed in only one rice cultivar (KDML105), limiting generalizability without testing across diverse varieties or field conditions.
- **Next question:** What molecular mechanisms drive this yield increase, and can the effect be replicated in other rice cultivars or under varying environmental stresses?

---

### Lane — `rate`


## #2 — score 60 · rate

**Finding:** sym-homospermidine, which at 1mM gave rates 17% of the rate with spermidine

- **Value:** 17.0%
- **Population:** rat prostatic spermine synthase
- **Intervention:** sym-homospermidine
- **Alpha cues:** baseline
- **Source:** *[UE2014] - Loi de Titius - Bode* — The Biochemical journal (2015)
  · DOI: `10.1042/bj1970315`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 4.0% (N-(3-aminopropyl)-cadaverine, which at 1mM gave rates 4% of ); 2.0% (1,8-diamino-octane, which at 1mM gave rates 2% of the rate w)

- **Why it matters:** The low activity of sym-homospermidine relative to spermidine at 1mM highlights enzyme specificity, which could inform drug design targeting polyamine metabolism.
- **Caution:** The assay used isolated rat prostatic spermine synthase in vitro, so the 17% rate may not reflect physiological concentrations or in vivo enzyme behavior.
- **Next question:** How does sym-homospermidine interact with spermidine in cellular systems, and does it modulate polyamine pathways in humans or animal models?

---
