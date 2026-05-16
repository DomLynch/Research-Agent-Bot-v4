# Top 4 interesting findings — autophagy

**Snapshot:** 2026-05-16T11-41-29Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=autophagy) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 14
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 63 · effect_size

**Finding:** autophagy flux was significantly less in injured versus uninjured muscles (-26%, P < 0.02).

- **Value:** -26.0%
- **Population:** mice
- **Intervention:** traumatic freeze injury
- **Source:** *Mitochondrial-specific autophagy linked to mitochondrial dysfunction following traumatic freeze injury in mice* — American Journal of Physiology-Cell Physiology (2019)
  · DOI: `10.1152/ajpcell.00123.2019`
- **Validator:** researka-tier2

- **Why it matters:** Reduced autophagy flux in injured muscles may explain poor recovery, pointing to autophagy modulation as a therapeutic target for muscle repair.
- **Caution:** The study used a mouse injury model, so findings may not directly apply to human muscle injuries due to species differences and model limitations.
- **Next question:** Can enhancing autophagy flux in injured muscles improve healing in mice, and does this translate to human clinical settings?

---

## #2 — score 60 · effect_size

**Finding:** 1.215 (1.149-1.286) (P < .001) in multivariate Cox regression analysis

- **Value:** 1.215HR
- **Population:** patients with lung adenocarcinoma
- **Intervention:** autophagy-related lncRNA survival model
- **Source:** *A novel autophagy‐related lncRNA survival model for lung adenocarcinoma* — Journal of Cellular and Molecular Medicine (2021)
  · DOI: `10.1111/jcmm.16582`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 1.256HR (1.256 (1.196-1.320) (P < .001) in univariate Cox regression )

- **Why it matters:** The hazard ratio indicates autophagy-related markers predict worse survival in lung adenocarcinoma, emphasizing autophagy's role in cancer prognosis.
- **Caution:** Multivariate Cox regression relies on observational data, which cannot establish causality and may be influenced by unmeasured confounders.
- **Next question:** What specific autophagy pathways drive poor outcomes in lung adenocarcinoma, and can inhibiting them improve patient survival?

---

### Lane — `mechanism`


## #3 — score 50 · mechanism

**Finding:** Inhibition of autophagy by silencing of the key autophagy gene, beclin 1 or 3-MA, further increased the cytotoxicity of this combinatorial treatment, suggesting that autophagy plays a cytoprotective role

- **Value:** 1.0OR
- **Population:** glioma cells
- **Intervention:** MK-2206 + gefitinib with autophagy inhibition (beclin 1 silencing or 3-MA)
- **Source:** *MK-2206, a Novel Allosteric Inhibitor of Akt, Synergizes with Gefitinib against Malignant Glioma via Modulating Both Autophagy and Apoptosis* — Molecular Cancer Therapeutics (2011)
  · DOI: `10.1158/1535-7163.mct-11-0606`
- **Validator:** researka-tier2

- **Why it matters:** Autophagy inhibition boosts cytotoxicity in glioma cells, suggesting it could enhance efficacy of existing cancer treatments when combined.
- **Caution:** Experiments were conducted in glioma cell lines in vitro, missing in vivo complexity and using doses that may not be clinically feasible.
- **Next question:** How does autophagy inhibition affect treatment efficacy and safety in animal models of glioma, and what are the risks of resistance or toxicity?

---

### Lane — `rate`


## #4 — score 40 · rate

**Finding:** a population (∼30%) of intracellular Mtb is tagged with ubiquitin and targeted to selective autophagy

- **Value:** 30.0%
- **Population:** intracellular Mtb in macrophages
- **Intervention:** ESX-1 secretion system perturbation
- **Source:** *Galectin-8 Senses Phagosomal Damage and Recruits Selective Autophagy Adapter TAX1BP1 To Control <i>Mycobacterium tuberculosis</i> Infection in Macrophages* — mBio (2021)
  · DOI: `10.1128/mbio.01871-20`
- **Validator:** —

- **Why it matters:** Only 30% of intracellular Mtb is targeted by autophagy in macrophages, revealing a gap in host defense that could be exploited for tuberculosis therapy.
- **Caution:** The rate was measured in isolated macrophages under controlled conditions, which may not reflect heterogeneity in human infections or bacterial diversity.
- **Next question:** What mechanisms govern ubiquitin tagging of Mtb for autophagy, and can interventions increase this targeting rate to improve bacterial clearance?

---
