# Top 2 interesting findings — spermidine

**Snapshot:** 2026-05-15T11-14-25Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=spermidine) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 20
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 70 · effect_size

**Finding:** Pretreatment with Spd dramatically improved grain yield per plant of KDML105 from 17.7 to 28.7 g (62% increase)

- **Value:** 62.0%
- **Population:** rice cultivar KDML105
- **Intervention:** 1 mM spermidine pretreatment
- **Source:** *Effects of exogenous spermidine (Spd) on yield, yield-related parameters and mineral composition of rice ('Oryza sativa' L. ssp. 'indica') grains under salt stress* — Australian Journal of Crop Science (2013)

- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 16.0% (Pretreatment with Spd improved grain yield per plant of Pokk)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=2 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

### Lane — `rate`


## #2 — score 60 · rate

**Finding:** sym-homospermidine, which at 1mM gave rates 17% of the rate with spermidine

- **Value:** 17.0%
- **Population:** rat prostatic spermine synthase
- **Intervention:** sym-homospermidine
- **Source:** *[UE2014] - Loi de Titius - Bode* — The Biochemical journal (2015)
  · DOI: `10.1042/bj1970315`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 4.0% (N-(3-aminopropyl)-cadaverine, which at 1mM gave rates 4% of ); 2.0% (1,8-diamino-octane, which at 1mM gave rates 2% of the rate w)

- **Why it matters:** Direct evidence in the `rate` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=3 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
