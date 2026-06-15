# Signal — llm_evaluation_score

_Snapshot:_ `2026-06-14T09-46-08Z`

## Source-bound llm evaluation score signal across independent receipts

## Why this is surprising

Frontier review skipped; using deterministic gate audit.

Real tension: the reviewer returned no thesis, but the lane gate found an independently sourced A_core receipt cluster. Publish only the bounded claim those receipts share.

## Evidence

- Results: GPT achieved 98.83% accuracy (1,439/1,456) compared to Claude's 97.94% (1,426/1,456). **[98.83%]** (Journal of Advanced Spine Surgery 2025)
- GPT-4 achieved an initial accuracy of 81.3% (222/273; 95% CI: 76.3%-85.5%), compared to Claude Opus, which achieved an accuracy of 79.5% (217/273; 95% CI: 74.3%-83.9%). **[81.3%]** (Journal of Clinical Oncology 2025)
- Results: Claude 3.5 Sonnet achieved 97% accuracy (29/30 correct), while DeepSeek-R1 achieved 93.3% accuracy **[97%]** (Advances in Neurology and Neuroscience 2025)
- Our scorer, with an achieved accuracy of 79.5%, significantly outper- forms GPT-4 as a judge (61.3%). **[79.5%]** (Proceedings of the 2024 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies (Volume 1: Long Papers) 2023)

## Confidence — `evidence_backed_signal`

**High — evidence-backed signal.** Cited facts pass source-audit lane gates with A_core density and matched metric families.

## Adjacent signals to consider

_These facts did NOT bind to the A_core/B_context lane this run — they are research prompts, NOT cited evidence. Triage and re-extract carefully before treating any of these as alpha:_

- Notably, all LLMs outperformed human trainees, who had an average score of 426.8 ± 25.9 (all P values < 0.001), although the gap narrowed for the most complex questions.
  - source: `10.1186/s12909-026-08704-y` (fact_id=`llm_evaluation/auto/2026/score_209545`, lane=`C_noise`)
- We have evaluated S YM G EN on a dataset comprising 2,237,915 binary functions across four architectures (x86-64, x86-32, ARM, MIPS) with four levels of optimizations (O0-O3) where it surpasses the st
  - source: `10.14722/ndss.2025.240797` (fact_id=`llm_evaluation/auto/2025/precision_327411`, lane=`C_noise`)
- Extensive evaluation demonstrates that our attack reliably generates functional malware across diverse task specifications and categories, outperforming jailbreaking methods by +365.79% and undergroun
  - source: `10.48550/arxiv.2507.02057` (fact_id=`llm_evaluation/auto/2025/correctness_326106`, lane=`C_noise`)

## Next question

What replicates this signal in independent cohorts?
