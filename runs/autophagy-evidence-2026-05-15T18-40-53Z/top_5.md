# Top 5 interesting findings — autophagy

**Snapshot:** 2026-05-15T18-40-53Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=autophagy) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 16
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `duration`


## #1 — score 66 · duration

**Finding:** At 48 hours following the combinatorial treatment, the level of LC3-II began to decrease but Bim was significantly elevated, suggesting a switch from autophagy to apoptosis

- **Value:** 48.0hours
- **Population:** glioma cells
- **Intervention:** MK-2206 + gefitinib
- **Source:** *MK-2206, a Novel Allosteric Inhibitor of Akt, Synergizes with Gefitinib against Malignant Glioma via Modulating Both Autophagy and Apoptosis* — Molecular Cancer Therapeutics (2011)
  · DOI: `10.1158/1535-7163.mct-11-0606`
- **Validator:** researka-tier2

- **Why it matters:** This switch from autophagy to apoptosis after 48 hours in glioma cells may explain why combinatorial therapies lose efficacy over time, informing treatment scheduling.
- **Caution:** The finding is limited to in vitro glioma cells at a single time point, which may not replicate in vivo dynamics or patient variability.
- **Next question:** What molecular signals drive this autophagy-to-apoptosis switch, and can timing be optimized to prolong therapeutic benefits?

---

### Lane — `effect_size`


## #2 — score 64 · effect_size

**Finding:** Ulk1 knockouts had contractile weakness compared with littermate controls (-27%, P < 0.02).

- **Value:** -27.0%
- **Population:** Ulk1 knockout mice and littermate controls
- **Intervention:** Ulk1 deficiency
- **Source:** *Mitochondrial-specific autophagy linked to mitochondrial dysfunction following traumatic freeze injury in mice* — American Journal of Physiology-Cell Physiology (2019)
  · DOI: `10.1152/ajpcell.00123.2019`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** -26.0% (autophagy flux was significantly less in injured versus unin)

- **Why it matters:** Ulk1 knockout causing contractile weakness highlights autophagy's role in muscle function, suggesting potential targets for muscle disorders.
- **Caution:** The study relies on a mouse genetic model, which may not fully capture human muscle physiology or disease complexity.
- **Next question:** Does Ulk1 deficiency specifically impair autophagy in muscle tissue, and can this be reversed with autophagy activators?

---

## #3 — score 60 · effect_size

**Finding:** 1.215 (1.149-1.286) (P < .001) in multivariate Cox regression analysis

- **Value:** 1.215HR
- **Population:** patients with lung adenocarcinoma
- **Intervention:** autophagy-related lncRNA survival model
- **Source:** *A novel autophagy‐related lncRNA survival model for lung adenocarcinoma* — Journal of Cellular and Molecular Medicine (2021)
  · DOI: `10.1111/jcmm.16582`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 1.256HR (1.256 (1.196-1.320) (P < .001) in univariate Cox regression )

- **Why it matters:** The hazard ratio indicates a strong link between autophagy markers and survival in lung adenocarcinoma, aiding prognostic stratification.
- **Caution:** This is observational data from a multivariate analysis, potentially confounded by unmeasured factors like treatment regimens.
- **Next question:** Which autophagy proteins contribute most to this risk, and are they druggable in clinical settings?

---

### Lane — `threshold`


## #4 — score 56 · threshold

**Finding:** TXA1 induced autophagy of melanoma cells at the GI50 concentration (3.6 μM)

- **Value:** 3.6μM
- **Population:** A375-C5 melanoma cells
- **Intervention:** TXA1
- **Source:** *Modulation of Autophagy by a Thioxanthone Decreases the Viability of Melanoma Cells* — Molecules (2016)
  · DOI: `10.3390/molecules21101343`
- **Validator:** researka-tier2

- **Why it matters:** Identifying the 3.6 μM GI50 for TXA1-induced autophagy helps optimize drug dosing for melanoma therapy development.
- **Caution:** The threshold is specific to A375-C5 cells and may not apply to other melanoma lines or in vivo environments.
- **Next question:** How does autophagy induction at this dose correlate with melanoma cell death or resistance in combination treatments?

---

## #5 — score 56 · threshold

**Finding:** APP-CTF (apparent EC(50) of ∼20 μM)

- **Value:** 20.0μM
- **Population:** cell lines and primary neuronal cultures
- **Intervention:** SMER28
- **Source:** *A small‐molecule enhancer of autophagy decreases levels of Aβ and APP‐CTF <b> <i>via</i> Atg5‐dependent autophagy pathway </b>* — The FASEB Journal (2011)
  · DOI: `10.1096/fj.10-175158`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 10.0μM (Aβ peptide (apparent EC(50) of ∼10 μM))

- **Why it matters:** The ∼20 μM EC50 for APP-CTF provides a reference for modulating autophagy in neuronal studies, relevant to neurodegenerative disease research.
- **Caution:** The apparent EC50 is from varied cell lines and cultures, which may introduce variability in standard applications.
- **Next question:** Does this EC50 hold in disease models like Alzheimer's, and how does APP-CTF's autophagy induction affect neuronal survival?

---
