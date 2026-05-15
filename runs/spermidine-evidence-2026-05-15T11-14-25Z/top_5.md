# Top 5 interesting findings — spermidine

**Snapshot:** 2026-05-15T11-14-25Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=spermidine) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 30
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `threshold`


## #1 — score 80 · threshold

**Finding:** high levels of total polyamines over 90 mg/kg were determined in mushrooms, green peppers, peas, citrus fruit, broad beans and tempeh with spermidine being predominant

- **Value:** 90.0mg/kg
- **Population:** plant-origin foods (mushrooms, green peppers, peas, citrus fruit, broad beans, tempeh)
- **Intervention:** —
- **Source:** *Occurrence of Polyamines in Foods and the Influence of Cooking Processes* — Foods (2021)
  · DOI: `10.3390/foods10081752`
- **Validator:** researka-tier2

- **Why it matters:** This data helps identify readily available foods rich in spermidine, supporting dietary strategies to boost polyamine intake for potential health benefits.
- **Caution:** The study only measured polyamine levels in select plant foods without linking them to human absorption or physiological effects.
- **Next question:** What is the bioavailability of spermidine from these specific foods in humans?

---

### Lane — `effect_size`


## #2 — score 80 · effect_size

**Finding:** the dry weight (DW) and fresh weight (FW) were reduced by 68.9% and 82%, respectively, compared with those of the normal-temperature controls.

- **Value:** 68.9%
- **Population:** lettuce seedlings under high-temperature stress
- **Intervention:** high-temperature stress
- **Source:** *Effects of exogenous spermidine on antioxidants and glyoxalase system of lettuce seedlings under high temperature* — Plant Signaling & Behavior (2020)
  · DOI: `10.1080/15592324.2020.1824697`
- **Validator:** researka-tier2

- **Why it matters:** The severe growth reduction under heat stress highlights the vulnerability of lettuce crops to climate change, urging adaptation strategies.
- **Caution:** Results are from controlled conditions with seedlings, which may not fully predict outcomes in mature plants or variable field environments.
- **Next question:** Can exogenous spermidine application reverse or mitigate this heat-induced growth penalty in lettuce?

---

## #3 — score 70 · effect_size

**Finding:** Pretreatment with Spd dramatically improved grain yield per plant of KDML105 from 17.7 to 28.7 g (62% increase)

- **Value:** 62.0%
- **Population:** rice cultivar KDML105
- **Intervention:** 1 mM spermidine pretreatment
- **Source:** *Effects of exogenous spermidine (Spd) on yield, yield-related parameters and mineral composition of rice ('Oryza sativa' L. ssp. 'indica') grains under salt stress* — Australian Journal of Crop Science (2013)

- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 16.0% (Pretreatment with Spd improved grain yield per plant of Pokk); 2.0 (Spd pretreatment slightly increased 2-acetyl-1-pyrroline (2-)

- **Why it matters:** This regimen provides a practical method for applying spermidine to enhance drought tolerance in turfgrass, relevant for water-scarce regions.
- **Caution:** The protocol uses specific concentrations and foliar application on creeping bentgrass, limiting generalizability to other plants or soil conditions.
- **Next question:** How does repeated spermidine treatment affect non-target organisms and soil microbial communities over time?

---

## #4 — score 70 · effect_size

**Finding:** Loss of polysomes with increased 80S monosomes in polyamine-depleted cells suggests a role in translation initiation.

- **Value:** 80.0
- **Population:** HeLa cells
- **Intervention:** SAT1 overexpression
- **Source:** *Depletion of cellular polyamines, spermidine and spermine, causes a total arrest in translation and growth in mammalian cells* — Proceedings of the National Academy of Sciences (2013)
  · DOI: `10.1073/pnas.1219002110`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 24.0 (Overexpression of SAT1 led to rapid depletion of spermidine )

- **Why it matters:** The significant yield increase in rice suggests spermidine could be a tool to boost productivity in drought-prone areas, aiding food security.
- **Caution:** Results are based on a single rice cultivar under controlled stress, and real-world variability might affect efficacy and consistency.
- **Next question:** Does spermidine-induced yield improvement compromise grain quality traits like nutrient content or taste?

---

### Lane — `regimen`


## #5 — score 75 · regimen

**Finding:** plants were treated with 200 mM GB or 0.1 mM Spd for 3 weeks by weekly foliar application before the exposure to drought stress.

- **Value:** 200.0OR
- **Population:** creeping bentgrass
- **Intervention:** 200 mM GB or 0.1 mM Spd
- **Source:** *Differential Effects of Glycine Betaine and Spermidine on Osmotic Adjustment and Antioxidant Defense Contributing to Improved Drought Tolerance in Creeping Bentgrass* — Journal of the American Society for Horticultural Science (2017)
  · DOI: `10.21273/jashs03962-16`
- **Validator:** researka-tier2

- **Why it matters:** This finding underscores spermidine's essential role in cellular protein synthesis, with implications for treating diseases linked to translation dysregulation.
- **Caution:** Observations are from HeLa cells, a cancer line, which may not reflect normal human cell physiology or in vivo translation mechanisms.
- **Next question:** How does spermidine depletion alter translation initiation dynamics in primary human cells under stress?

---
