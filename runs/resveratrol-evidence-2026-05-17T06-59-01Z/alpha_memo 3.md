# Alpha memo — resveratrol

**Headline:** Resveratrol may be context-specific, not broadly generalizable
**Alpha score:** 80/100
**Confidence:** `frontier_hypothesis`
**Memo surface:** `context dependence memo`
**Snapshot:** `2026-05-17T06-59-01Z`
**Run:** `resveratrol-evidence-2026-05-17T06-59-01Z`
**Source thesis:** Resveratrol at 75 mg twice daily as a targeted intervention for bone resorption in postmenopausal women: evidence from T-score and collagen telopeptide data

## One-sentence thesis

The lead signal sits beside A/B receipts across overweight and insulin-resistant subjects, AOM + DSS mouse model of colitis, and pregnant nonhuman primates; publish it as a context-dependence signal rather than a broad claim.

## Why this is surprising

Resveratrol's effects are strikingly tissue- and population-specific, with evidence showing bone protection in postmenopausal women but paradoxical fetal pancreatic hypertrophy in primates, while failing to reduce hepatic fat in insulin-resistant adults—suggesting that metabolic context dictates efficacy.

Known / obvious (do not republish): Resveratrol is a natural polyphenol with general antioxidant and anti-inflammatory properties; Resveratrol is studied for potential anti-aging and cardioprotective effects

Real tension: Fact 13393 (no liver fat reduction in overweight insulin-resistant subjects) vs. facts 4434 and 4433 (bone benefits in postmenopausal women), indicating divergent metabolic outcomes across populations

## Evidence receipts

- `fact_id=4434` (`A_core`) — an improvement in T-score (+0.070 ± 0.018) DOI `10.1002/jbmr.4115`
- `fact_id=4433` (`A_core`) — a 7.24% reduction in C-terminal telopeptide type-1 collagen levels, a bone resorption marker DOI `10.1002/jbmr.4115`

## What this changes

Treat this as a focused working signal, not a broad topic claim. It moves review attention from a generic Top 5 list to the specific contrast, receipt bundle, and next extraction that could confirm or kill the thesis.

## What would weaken this

- For the bone health thesis, reviewers may challenge the evidence strength due to reliance on a single study with a specific dose (75 mg twice daily) and lack of comparative dose data
- For the fetal thesis, objections could include the high resveratrol dose (0.37% in diet) in primates not translating to human equivalent doses, and the limited sample size typical of primate studies

## Strongest counter-evidence

- `fact_id=13393` (`A_core`) — Liver fat content decreased in placebo group (-0.7%) but not in resveratrol group (-0.03%), P=.018 for ITT population. Source: Effects of resveratrol supplementation on liver fat content in overweight and insulin‐resistant subjects: A randomized, double‐blind, placeb

## Next extraction

- Studies on resveratrol's impact on blood pressure at doses ≥300 mg/day, as hinted by meta-analytic trends
- Research on resveratrol nanodispersion or conjugated formulations for improved bioavailability in bone-targeting applications
- Clinical trials assessing resveratrol effects on AMPK phosphorylation and sperm quality in male fertility contexts

## Supporting Top cards

- Liver fat content decreased in placebo group (-0.7%) but not in resveratrol group (-0.03%), P=.018 for ITT population. _(alpha cues: contrast, translation_context)_
- fetal pancreatic mass was enlarged by 42%, _(alpha cues: translation_context)_
- a 7.24% reduction in C-terminal telopeptide type-1 collagen levels, a bone resorption marker _(alpha cues: baseline)_
- Significantly higher (90%) bioconversion of resveratrol was achieved with α-d-glucose as the sugar donor _(alpha cues: low_signal_context)_
- Tumor incidence is reduced from 80% in mice treated with azoxymethane (AOM) + DSS to 20% in mice treated with AOM + DSS + resveratrol (300 ppm). _(alpha cues: baseline)_

## Receipt expansion candidates

- The lead thesis is thinner than the available corpus: it cites 2 bound receipt(s) while 7 A/B receipt(s) exist in this run.
- Candidate `fact_id=13393` (`A_core`) — Liver fat content decreased in placebo group (-0.7%) but not in resveratrol group (-0.03%), P=.018 for ITT population.
- Candidate `fact_id=5625` (`A_core`) — Tumor incidence is reduced from 80% in mice treated with azoxymethane (AOM) + DSS to 20% in mice treated with AOM + DSS + resveratrol (300 ppm).
- Candidate `fact_id=9267` (`A_core`) — fetal pancreatic mass was enlarged by 42%,
- Candidate `fact_id=9268` (`A_core`) — resveratrol resulted in 30% maternal weight loss
- Candidate `fact_id=18722` (`B_context`) — Significantly higher (90%) bioconversion of resveratrol was achieved with α-d-glucose as the sugar donor

## Subtopic recommendations

- This topic looks broad/noisy enough that the next run should split it before trying to force one public thesis.
- `cultured_smooth_muscle` — Resveratrol causes cell cycle arrest, decreased collagen synthesis, and apoptosis in rat intestinal smooth muscle cells
- `albumin_nanoparticles_glycyrrhizic` — Resveratrol-loaded glycyrrhizic acid-conjugated human serum albumin nanoparticles wrapping resveratrol nanoparticles: Preparation, characterization, and targeting effect on liver t
- `pharmacists_mcf_proteins` — Comparative Insilico Docking Analysis of Curcumin and Resveratrol on Breast Cancer Proteins and their Synergistic Effect on MCF-7 Cell Line
- `trials_reviews_review` — Effect of resveratrol on blood pressure: A systematic review and meta-analysis of randomized, controlled, clinical trials
- `cellular_oxidative_kinase` — Resveratrol Improves Boar Sperm Quality via 5<mml:math xmlns:mml="http://www.w3.org/1998/Math/MathML" id="M1"><mml:msup><mml:mrow/><mml:mrow><mml:mo>′</mml:mo></mml:mrow></mml:msup

## Provenance / priority

- **Topic:** `resveratrol`
- **Author:** Dom Lynch
- **ORCID:** _not configured_
- **Version:** 1.0
- **License:** CC BY-NC 4.0
- **Canonical URL:** _not assigned_
- **Suggested citation:** Dom Lynch. (2026). Resveratrol may be context-specific, not broadly generalizable. ReseaRka Evidence Index. Version 1.0.
- **Run bundle SHA-256:** `f0d283905e5e256c1679409c9e27c9d38ebfb7297f6ef193a2eda61336778eb7`
- **Memo SHA-256:** `fd07d1bada3332de7f557ab4ddd0641960932018cd1c50f998a4615e8e14ec65`
- **Priority note:** This memo records the first published framing, source bundle, and evidence receipts for this run. Reuse should cite the canonical version.
