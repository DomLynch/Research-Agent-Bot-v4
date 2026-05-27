# Top 2 interesting findings — dasatinib

**Snapshot:** 2026-05-27T09-28-15Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=dasatinib) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 20
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=2)

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 100 · effect_size

**Finding:** overall survival is 80.7%

- **Value:** 80.7%
- **Population:** adult Philadelphia-positive ALL patients
- **Intervention:** dasatinib and blinatumomab induction/consolidation
- **Alpha cues:** functional_endpoint
- **Source:** *Long-Term Results of the Dasatinib-Blinatumomab Protocol for Adult Philadelphia-Positive ALL* — Journal of Clinical Oncology (2023)
  · DOI: `10.1200/jco.23.01075`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 74.6% (event-free survival is 74.6%); 75.8% (disease-free survival is 75.8%)

- **Why it matters:** This high overall survival rate of 80.7% highlights dasatinib's effectiveness in improving long-term outcomes for adult Philadelphia-positive acute lymphoblastic leukemia patients, guiding treatment decisions in clinical practice.
- **Caution:** The finding is based on a single study model with a specific dosing regimen, which may not account for variability in real-world patient responses or other treatment protocols.
- **Next question:** What is the impact of dasatinib on survival when used in combination with chemotherapy or other targeted therapies in diverse patient populations?

---

### Lane — `rate`


## #2 — score 100 · rate

**Finding:** At 5 years, overall survival was 36% and up to 45% taking into account deaths unrelated to disease or treatment as competitors.

- **Value:** 36.0%
- **Population:** Patients older than 55 years with Philadelphia chromosome-positive ALL
- **Intervention:** Dasatinib 140 mg/day with low-intensity chemotherapy (vincristine, dexamethasone, cytarabine, asparaginase, methotrexate)
- **Alpha cues:** translation_context, functional_endpoint
- **Source:** *Dasatinib and low-intensity chemotherapy in elderly patients with Philadelphia chromosome–positive ALL* — Blood (2016)
  · DOI: `10.1182/blood-2016-02-700153`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 96.0% (Complete remission rate was 96%); 65.0% (65% of patients achieved a 3-log reduction in BCR-ABL1 trans)

- **Why it matters:** The 36-45% five-year survival rate in older patients with Philadelphia-positive ALL demonstrates dasatinib's potential to extend life in a high-risk demographic often undertreated due to age-related concerns.
- **Caution:** This rate is derived from a single cohort analysis that uses competing risk models, potentially introducing bias if assumptions about unrelated deaths are incorrect or not broadly applicable.
- **Next question:** How can treatment protocols be optimized to further enhance survival and reduce toxicity in elderly Ph+ ALL patients receiving dasatinib?

---
