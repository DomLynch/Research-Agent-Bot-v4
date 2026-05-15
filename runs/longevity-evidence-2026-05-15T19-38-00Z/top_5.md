# Top 5 interesting findings — longevity

**Snapshot:** 2026-05-15T19-38-00Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=longevity) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 35
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

---

## #1 — score 80 · effect_size

**Finding:** genes correlated with bacterial pathogen resistance showed an 84% overlap with genes correlated with lifespan

- **Value:** 84.0%
- **Population:** nine long-lived Caenorhabditis elegans mutants from different pathways of lifespan extension
- **Intervention:** comparative transcriptomic analysis
- **Source:** *Genetic basis of enhanced stress resistance in long‐lived mutants highlights key role of innate immunity in determining longevity* — Aging Cell (2022)
  · DOI: `10.1111/acel.13740`
- **Validator:** researka-tier2

- **Why it matters:** The 84% overlap between pathogen resistance and lifespan genes in C. elegans suggests that targeting immune pathways could simultaneously combat infections and extend lifespan.
- **Caution:** The study is limited to nine mutants from different pathways, which may not represent natural genetic variation or translate to other species.
- **Next question:** Do these overlapping genes operate through conserved mechanisms in mammals, and can they be pharmacologically targeted for human longevity?

---

## #2 — score 80 · effect_size

**Finding:** we identified 276 genes whose rate of evolution positively correlates with maximum lifespan in primates.

- **Value:** 276.0g
- **Population:** primates
- **Intervention:** —
- **Source:** *Positive Selection and Enhancer Evolution Shaped Lifespan and Body Mass in Great Apes* — Molecular Biology and Evolution (2021)
  · DOI: `10.1093/molbev/msab369`
- **Validator:** researka-tier2

- **Why it matters:** Identifying 276 genes with evolution rates tied to primate lifespans offers clues to genetic adaptations underlying longevity in humans and close relatives.
- **Caution:** Correlation between gene evolution and lifespan does not prove causality; confounding factors like diet or environment could be involved.
- **Next question:** What specific functions do these genes perform, and how do they influence cellular aging or disease resistance in primates?

---

## #3 — score 80 · effect_size

**Finding:** most of the detected AA positions do not vary in extant human populations (81.2%) or have allele frequencies below 1% (99.78%).

- **Value:** 81.2%
- **Population:** human populations
- **Intervention:** —
- **Source:** *Comparative Analysis of Mammal Genomes Unveils Key Genomic Variability for Human Life Span* — Molecular Biology and Evolution (2021)
  · DOI: `10.1093/molbev/msab219`
- **Validator:** researka-tier2

- **Why it matters:** The high proportion of fixed or rare AA variants in humans indicates strong evolutionary pressure on longevity-related genes, limiting genetic diversity in aging traits.
- **Caution:** The analysis relies on existing population data, which might underrepresent rare variants or miss variations in under-studied groups.
- **Next question:** Are these conserved or rare variants functionally impactful, and do they correlate with known human longevity phenotypes?

---

## #4 — score 75 · effect_size

**Finding:** HSB-1 inhibition alters the expression of less than 500 genes in C. elegans

- **Value:** 500.0genes
- **Population:** C. elegans
- **Intervention:** HSB-1 inhibition
- **Source:** *HSB-1 Inhibition and HSF-1 Overexpression Trigger Overlapping Transcriptional Changes To Promote Longevity in <i>Caenorhabditis elegans</i>* — G3 Genes Genomes Genetics (2019)
  · DOI: `10.1534/g3.119.400044`
- **Validator:** researka-tier2

- **Why it matters:** HSB-1 inhibition's targeted effect on fewer than 500 genes in C. elegans suggests a precise way to modulate aging pathways with minimal side effects.
- **Caution:** C. elegans is a simple model; human biology involves greater complexity, so direct applications may not be feasible.
- **Next question:** Does HSB-1 inhibition actually extend C. elegans lifespan, and what are the key downstream genes or pathways involved?

---

## #5 — score 70 · effect_size

**Finding:** The median longevity after diagnosis of CKD was 1608 days [95% confidence interval 1344-1919]

- **Value:** 1608.0days
- **Population:** cats with chronic kidney disease
- **Intervention:** long-term oral meloxicam treatment
- **Source:** *A retrospective analysis of the effects of meloxicam on the longevity of aged cats with and without overt chronic kidney disease* — Journal of Feline Medicine and Surgery (2012)
  · DOI: `10.1177/1098612x12454418`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 22.0years (The median longevity in the non-renal group was 22 years [95); 18.6years (The median longevity in the renal group was 18.6 years [95% )

- **Why it matters:** The median post-diagnosis longevity of 1608 days for cats with CKD sets a clinical benchmark for managing feline kidney disease and setting owner expectations.
- **Caution:** The wide confidence interval reflects variability due to factors like treatment regimens, comorbidities, or cat breed, which were not fully controlled.
- **Next question:** What specific treatments or lifestyle changes can extend this longevity, and how do they vary by CKD stage or individual cat characteristics?

---
