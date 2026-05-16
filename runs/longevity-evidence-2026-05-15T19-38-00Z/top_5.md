# Top 3 interesting findings — longevity

**Snapshot:** 2026-05-15T19-38-00Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=longevity) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 29
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

---

## #1 — score 60 · effect_size

**Finding:** offspring enjoy a 30% reduced standardized mortality rate

- **Value:** 30.0%
- **Population:** offspring in long-lived families from Leiden Longevity Study
- **Intervention:** genetic enrichment for longevity
- **Source:** *Hallmark Features of Immunosenescence Are Absent in Familial Longevity* — The Journal of Immunology (2010)
  · DOI: `10.4049/jimmunol.1001629`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #2 — score 60 · effect_size

**Finding:** DMSO concentrations up to 2% DMSO did not affect longevity in wild-type worms

- **Value:** 2.0%
- **Population:** wild-type C. elegans
- **Intervention:** DMSO concentrations up to 2%
- **Source:** *Effect of DMSO on lifespan and physiology in C. elegans: Implications for use of DMSO as a solvent for compound delivery* — PubMed (2022)
  · DOI: `10.17912/micropub.biology.000634`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #3 — score 60 · effect_size

**Finding:** above 16.5%, relative longevity showed a positive relation with harvest moisture content

- **Value:** 16.5%
- **Population:** rice seeds from 20 accessions of five variety groups
- **Intervention:** drying at 45°C
- **Source:** *Improvement in rice seed storage longevity from high-temperature drying is a consistent positive function of harvest moisture content above a critical value* — Seed Science Research (2018)
  · DOI: `10.1017/s0960258518000211`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 16.5% (below 16.5%, relative longevity did not differ with harvest )

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=2 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
