# Top 3 interesting findings — caloric_restriction

**Snapshot:** 2026-05-15T18-54-38Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=caloric_restriction) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 24
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

---

## #1 — score 67 · effect_size

**Finding:** CR mice had 52% and 88% lower serum leptin at 6 and 12 weeks of age

- **Value:** 52.0%
- **Population:** male C57Bl/6J mice
- **Intervention:** 30% caloric restriction
- **Source:** *Caloric restriction leads to high marrow adiposity and low bone mass in growing mice* — Journal of Bone and Mineral Research (2010)
  · DOI: `10.1002/jbmr.82`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 33.0% (CR mice had 33% and 39% lower serum IGF-1 at 6 and 12 weeks ); 5.0 (bone marrow adiposity was elevated dramatically in CR versus)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=3 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #2 — score 60 · effect_size

**Finding:** proteome half-lives of old hearts significantly increased after short-term CR (30%)

- **Value:** 30.0%
- **Population:** old hearts
- **Intervention:** short-term caloric restriction
- **Source:** *Altered proteome turnover and remodeling by short‐term caloric restriction or rapamycin rejuvenate the aging heart* — Aging Cell (2014)
  · DOI: `10.1111/acel.12203`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 12.0% (proteome half-lives of old hearts significantly increased af)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=2 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #3 — score 50 · effect_size

**Finding:** In females, macroadenomas were markedly attenuated by VF- (1.33 ± 0.23 mean ± SE; P < 0.05), but not by caloric restriction (2.35 ± 0.25; P = 0.71), as compared with ad libitum (2.50 ± 0.34).

- **Value:** 1.33
- **Population:** Apc(1638N/+) female mice
- **Intervention:** visceral fat removal (VF-)
- **Source:** *Abdominal Obesity, Independent from Caloric Intake, Accounts for the Development of Intestinal Tumors in <i>Apc1638N/+</i> Female Mice* — Cancer Prevention Research (2013)
  · DOI: `10.1158/1940-6207.capr-12-0414`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 1.71 (In males, however, caloric restriction (1.71 ± 0.26; P < 0.0)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=2 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
