# Alpha memo — fasting

**Headline:** Perfluoroalkyl substance exposure as a confounder in fasting glucose studies: implications for metabolic health research
**Alpha triage:** `high` (internal ranking; not a certainty claim)
**Confidence:** `frontier_hypothesis`
**Memo surface:** `subtopic rerun memo`
**Snapshot:** `2026-05-27T05-51-53Z`
**Run:** `fasting-evidence-2026-05-27T05-51-53Z`
**Direct source breadth:** `1` direct cited source(s)
**Source breadth:** `3/5` unique cited source(s)

## One-sentence thesis

The direct receipts support a narrow working claim: 1% increase in serum PFNA was significantly associated with 0.022% (95% CI: 0.007%, 0.037%) increment in fasting glucose levels; 1% increase in serum PFOA was significantly associated with 0.018% [95% CI: 0.004%, 0.033%] increment in fasting glucose levels. The context receipts provide source breadth and boundary checks, not independent confirmation of the lead claim.

## Why this is surprising

The useful signal is narrower than the topic label: the lead receipts support the core claim, while the added A/B context receipts define where that claim may generalize, fail, or need a separate extraction.

## Evidence receipts

- `fact_id=176202` (`B_context`) — 1% increase in serum PFNA was significantly associated with 0.022% (95% CI: 0.007%, 0.037%) increment in fasting glucose levels. DOI `10.1016/j.envint.2019.105295`
- `fact_id=176201` (`B_context`) — 1% increase in serum PFOA was significantly associated with 0.018% [95% CI: 0.004%, 0.033%] increment in fasting glucose levels. DOI `10.1016/j.envint.2019.105295`

## Context receipts

- `fact_id=169580` (`A_core`) — The overall pooled estimate for fasting compared to non-fasting indicated no significant difference in side effects (RR = 1.10; 95% CI: 0.77-1.59). DOI `10.3390/nu15122666`
- `fact_id=161503` (`A_core`) — a daily fasting interval and circadian alignment of feeding acted together to extend life span by 35% in male C57BL/6J mice DOI `10.1126/science.abk0297`

## What this changes

Treat this as a focused working signal, not a broad topic claim. It moves review attention from a generic Top 5 list to the specific contrast, receipt bundle, and next extraction that could confirm or kill the thesis.

## Limitations

- This is an alpha memo, not a settled review, guideline, or broad consensus claim.
- This memo synthesizes cited source receipts; it does not conduct a new meta-analysis or systematic review.
- Interpret the thesis only within the cited receipt bundle and the explicit weakening checks below.
- The core claim rests on 1 direct source paper(s); context receipts broaden the source bundle but are not convergent proof.
- Independent receipts fail to reproduce the claimed contrast.
- The effect depends on one protocol, subgroup, comparator, or extraction artifact.

## What would weaken this

- Independent receipts fail to reproduce the claimed contrast.
- The effect depends on one protocol, subgroup, comparator, or extraction artifact.

## Strongest counter-evidence

- `fact_id=169580` (`A_core`) — The overall pooled estimate for fasting compared to non-fasting indicated no significant difference in side effects (RR = 1.10; 95% CI: 0.77-1.59). Source: Therapeutic Fasting in Reducing Chemotherapy Side Effects in Cancer Patients: A Systematic Review and Meta-Analysis

## Next extraction

- Extract independent A_core/B_context receipts that test the lead contrast directly.
- Audit whether each direct receipt remains comparable on population, endpoint, comparator, and measurement method.
- Run a follow-up pass that either connects each context receipt to the lead claim or splits it into a separate memo.

## Receipt expansion candidates

- The lead thesis is thinner than the available corpus: it cites 2 bound receipt(s) while 4 A/B receipt(s) exist in this run.
- Candidate `fact_id=161503` (`A_core`) — a daily fasting interval and circadian alignment of feeding acted together to extend life span by 35% in male C57BL/6J mice
- Candidate `fact_id=169580` (`A_core`) — The overall pooled estimate for fasting compared to non-fasting indicated no significant difference in side effects (RR = 1.10; 95% CI: 0.77-1.59).

## Subtopic recommendations

- This topic looks broad/noisy enough that the next run should split it before trying to force one public thesis.
- `circadian_eating_time` — Circadian alignment of food intake and glycaemic control by time-restricted eating: A systematic review and meta-analysis
- `science_randomized_kilograms` — A randomized controlled trial to isolate the effects of fasting and energy restriction on weight loss and metabolic health in lean adults
- `trials_randomized_review` — Effect of vitamin E intake on glycemic control and insulin resistance in diabetic patients: an updated systematic review and meta-analysis of randomized controlled trials
- `novel_associations_its` — Distribution of novel and legacy per-/polyfluoroalkyl substances in serum and its associations with two glycemic biomarkers among Chinese adult men and women with normal blood gluc
- `enrolled_novel_262` — Long-Term Effects of a Novel Continuous Remote Care Intervention Including Nutritional Ketosis for the Management of Type 2 Diabetes: A 2-Year Non-randomized Clinical Trial

## Provenance / priority

- **Topic:** `fasting`
- **Author:** Dom Lynch
- **ORCID:** _not configured_
- **Version:** 1.0
- **License:** CC BY-NC 4.0
- **Canonical URL:** _not assigned_
- **Suggested citation:** Dom Lynch. (2026). Perfluoroalkyl substance exposure as a confounder in fasting glucose studies: implications for metabolic health research. ReseaRka Evidence Index. Version 1.0.
- **Run bundle SHA-256:** `06b6ed84c521c919c55196d00bf7dd20aa7729534f6f72c746204727555c9f9a`
- **Memo SHA-256:** `21aa0a99a533dc98c965a804fa75914bef636f0ea0bbad89dc936d050fb5f42c`
- **Priority note:** This memo records the first published framing, source bundle, and evidence receipts for this run. Reuse should cite the canonical version.
