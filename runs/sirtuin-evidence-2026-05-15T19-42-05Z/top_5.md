# Top 5 interesting findings — sirtuin

**Snapshot:** 2026-05-15T19-42-05Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=sirtuin) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 25
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

---

## #1 — score 80 · effect_size

**Finding:** Here we describe potent cambinol-based SIRT2 inhibitors, several of which show potency of ~600 nM with >300 to >800-fold selectivity over SIRT1 and 3, respectively.

- **Value:** 600.0nM
- **Population:** lymphoma and epithelial cancer cell lines
- **Intervention:** cambinol-based SIRT2 inhibitors
- **Source:** *Discovery of Selective SIRT2 Inhibitors as Therapeutic Agents in B-Cell Lymphoma and Other Malignancies* — Molecules (2020)
  · DOI: `10.3390/molecules25030455`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.25µM (compound 55 (IC50 SIRT2 0.25 µM and <25% inhibition at 50 µM); 0.78µM (compound 56 (IC50 SIRT2 0.78 µM and <25% inhibition at 50 µM)

- **Why it matters:** Selective SIRT2 inhibitors could lead to targeted cancer therapies with reduced off-target effects for lymphoma and epithelial cancers.
- **Caution:** These results are based solely on in vitro cell line studies (k=1), lacking validation in in vivo models or human tissues.
- **Next question:** Do these inhibitors retain their potency and selectivity in animal models, such as xenograft mice, before advancing to clinical trials?

---

## #2 — score 80 · effect_size

**Finding:** treatment with whey for 72 h inhibited cell proliferation (p < 0.001)

- **Value:** 72.0
- **Population:** human colon cancer cells HT-29, HCT 116, LoVo, SW480
- **Intervention:** whey from Mediterranean water buffalo milk
- **Source:** *SIRT3 and Metabolic Reprogramming Mediate the Antiproliferative Effects of Whey in Human Colon Cancer Cells* — Cancers (2021)
  · DOI: `10.3390/cancers13205196`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.01 (Transient SIRT3 gene silencing blocked the effects of whey o)

- **Why it matters:** Whey may serve as a dietary intervention to slow colon cancer progression, accessible for prevention strategies.
- **Caution:** The study uses only in vitro colon cancer cell lines, and the applied dose may not mirror human dietary intake or bioavailability.
- **Next question:** What specific whey components or mechanisms, potentially involving sirtuin modulation, drive the observed anti-proliferative effects?

---

## #3 — score 70 · effect_size

**Finding:** reduced hepatic tumorigenesis (65% reduction in volume)

- **Value:** 65.0%
- **Population:** C57Bl/6J mice
- **Intervention:** APO10LA supplementation (10 mg/kg diet)
- **Source:** *Lycopene Metabolite, Apo-10′-Lycopenoic Acid, Inhibits Diethylnitrosamine-Initiated, High Fat Diet–Promoted Hepatic Inflammation and Tumorigenesis in Mice* — Cancer Prevention Research (2013)
  · DOI: `10.1158/1940-6207.capr-13-0178`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 85.0% (reduced lung tumor incidence (85% reduction)); 50.0% (APO10LA supplementation (10 mg/kg diet) for 24 weeks signifi)

- **Why it matters:** A 65% reduction in liver tumor volume in mice indicates potential for new treatments targeting hepatocellular carcinoma.
- **Caution:** Mouse models like C57Bl/6J may not fully replicate human liver cancer biology, limiting translational certainty.
- **Next question:** How does this intervention interact with sirtuin pathways to reduce hepatic tumorigenesis, and is it effective in human-derived models?

---

## #4 — score 69 · effect_size

**Finding:** betaines showed the highest effect in reducing Cal 27 cell proliferation up to 72 h (p < 0.01).

- **Value:** 27.0
- **Population:** head and neck squamous cell carcinoma Cal 27 cell line
- **Intervention:** betaines
- **Source:** *Synergistic Effect of Dietary Betaines on SIRT1-Mediated Apoptosis in Human Oral Squamous Cell Carcinoma Cal 27* — Cancers (2020)
  · DOI: `10.3390/cancers12092468`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.001 (This effect was enhanced when betaines were administered in ); 0.05 (SIRT1 gene silencing by small interfering RNA decreased the )

- **Why it matters:** Betaines could be developed as novel therapeutics for head and neck squamous cell carcinoma, a challenging cancer type.
- **Caution:** The effect is observed only in the Cal 27 cell line (k=1), with unknown efficacy in diverse cancer models or in vivo settings.
- **Next question:** What is the mechanism by which betaines affect sirtuin activity or other pathways, and what are their optimal dosing and safety profiles?

---

## #5 — score 66 · effect_size

**Finding:** knockdown of SIRT1 resulted in 50% fewer animals developing tumors

- **Value:** 50.0%
- **Population:** orthotopic xenograft model
- **Intervention:** knockdown of SIRT1
- **Source:** *Antitumor Effect of SIRT1 Inhibition in Human HCC Tumor Models <i>In Vitro</i> and <i>In Vivo</i>* — Molecular Cancer Therapeutics (2013)
  · DOI: `10.1158/1535-7163.mct-12-0700`
- **Validator:** researka-tier2

- **Why it matters:** SIRT1 knockdown reducing tumor incidence by 50% highlights SIRT1 as a critical target for cancer prevention.
- **Caution:** Orthotopic xenograft models involve human cancer cells in mice, which may not account for immune interactions or long-term side effects.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
