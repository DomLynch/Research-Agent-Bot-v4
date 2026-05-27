# Top 3 interesting findings — berberine

**Snapshot:** 2026-05-27T08-45-58Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=berberine) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 17
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: biomarker=1, clinical_outcome=2)

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 72 · effect_size

**Finding:** TG (SMD: 0.94; 95%CI: 0.49,1.38; p = 0.00)

- **Value:** 0.94%
- **Population:** patients with metabolic disorders from included RCTs
- **Intervention:** berberine alone
- **Alpha cues:** translation_context
- **Source:** *Efficacy and Safety of Berberine Alone for Several Metabolic Disorders: A Systematic Review and Meta-Analysis of Randomized Clinical Trials* — Frontiers in Pharmacology (2021)
  · DOI: `10.3389/fphar.2021.653887`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 1.06% (TC (SMD: 1.06; 95%CI: 0.64, 1.48; p = 0.00)); 1.25% (HOMA-IR (SMD: 1.25; 95%CI: 0.25,2.24; p = 0.01)); 0.65% (FPG (SMD: 0.65; 95%CI: 0.28,1.03; p = 0.00)); -1.59% (HDL (SMD: -1.59; 95%CI: -2.32, -0.85; p = 0.00)); 1.77% (LDL (SMD: 1.77; 95%CI: 1.11,2.44; p = 0.00))

- **Why it matters:** Berberine's significant reduction in triglycerides (SMD 0.94) could aid in managing metabolic disorders by lowering cardiovascular risk factors in real-world clinical settings.
- **Caution:** The effect size (SMD 0.94) may be skewed by heterogeneity in study designs, dosing protocols, or patient demographics across the included RCTs.
- **Next question:** What is the optimal berberine dosage and long-term efficacy for triglyceride reduction in diverse metabolic disorder populations?

---

## #2 — score 60 · effect_size

**Finding:** berberine could reduce HbA1c (WMD = -0.63%, 95% CI (-0.72, -0.53))

- **Value:** -0.63%
- **Population:** patients with type 2 diabetes mellitus
- **Intervention:** berberine
- **Alpha cues:** baseline
- **Source:** *Glucose-lowering effect of berberine on type 2 diabetes: A systematic review and meta-analysis* — Frontiers in Pharmacology (2022)
  · DOI: `10.3389/fphar.2022.1015045`
- **Validator:** researka-tier2

- **Why it matters:** This is worth checking because it ties berberine in patients with type 2 diabetes mellitus to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

### Lane — `adverse`


## #3 — score 60 · adverse

**Finding:** the risk of hypoglycemia (RR = 0.48, 95% CI (0.21, 1.08), p = 0.08)

- **Value:** 0.48RR
- **Population:** patients with type 2 diabetes mellitus
- **Intervention:** berberine alone or in combination with oral hypoglycemic agents
- **Alpha cues:** baseline
- **Source:** *Glucose-lowering effect of berberine on type 2 diabetes: A systematic review and meta-analysis* — Frontiers in Pharmacology (2022)
  · DOI: `10.3389/fphar.2022.1015045`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.73RR (did not significantly increase the incidence of total advers)

- **Why it matters:** This is worth checking because it ties berberine alone or in combination with oral hypoglycemic agents in patients with type 2 diabetes mellitus to a source-backed effect.
- **Caution:** Do not overread this as settled: k=2 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---
