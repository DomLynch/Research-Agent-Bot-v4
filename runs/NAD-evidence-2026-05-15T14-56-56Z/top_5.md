# Top 4 interesting findings — NAD

**Snapshot:** 2026-05-15T14-56-56Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=NAD) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 24
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 70 · effect_size

**Finding:** 2,3-butanediol (maximal yield, 67%)

- **Value:** 67.0%
- **Population:** Lactococcus lactis engineered strains
- **Intervention:** Engineering of NAD+ cofactor recycling and overexpression of 2,3-butanediol biosynthesis pathways
- **Source:** *High Yields of 2,3-Butanediol and Mannitol in Lactococcus lactis through Engineering of NAD <sup>+</sup> Cofactor Recycling* — Applied and Environmental Microbiology (2011)
  · DOI: `10.1128/aem.05544-11`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 42.0% (mannitol (maximal yield, 42%))

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=2 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #2 — score 65 · effect_size

**Finding:** NAD(P)(H) pools in M. maripaludis measured to be <15% of that of Escherichia coli

- **Value:** 15.0%
- **Population:** Methanococcus maripaludis
- **Intervention:** none
- **Source:** *Engineering nonphotosynthetic carbon fixation for production of bioplastics by methanogenic archaea* — Proceedings of the National Academy of Sciences (2022)
  · DOI: `10.1073/pnas.2118638119`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #3 — score 60 · effect_size

**Finding:** women had higher plasma NAD+/NADH ratios than men (median 1.33 vs. 1.09, P<0.001)

- **Value:** 1.33
- **Population:** 205 probands without severe diseases (91 men, 114 women), 18-83 years old
- **Intervention:** N/A
- **Source:** *Sex-related differences in human plasma NAD+/NADH levels depend on age* — Bioscience Reports (2021)
  · DOI: `10.1042/bsr20200340`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

### Lane — `rate`


## #4 — score 56 · rate

**Finding:** RNAIII, a central quorum-sensing regulator of this bacterium's physiology, was found to be 5' NAD capped in a range from 10 to 35%

- **Value:** 5.0%
- **Population:** Staphylococcus aureus isolates
- **Intervention:** 5' NAD capping of RNAIII
- **Source:** *The 5′ NAD Cap of RNAIII Modulates Toxin Production in Staphylococcus aureus Isolates* — Journal of Bacteriology (2019)
  · DOI: `10.1128/jb.00591-19`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `rate` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
