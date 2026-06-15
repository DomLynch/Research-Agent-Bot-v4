# No signal — model_eval_score

_Snapshot:_ `2026-06-14T09-43-57Z`

**No publishable thesis.** MiMo declined to elevate a finding from this evidence pool — typically because facts are too noisy, too narrow, or off-target for the topic.

## MiMo's note

Frontier review skipped; using deterministic gate audit.

## Adjacent signals to consider

_These facts did NOT bind to the A_core/B_context lane this run — they are research prompts, NOT cited evidence. Triage and re-extract carefully before treating any of these as alpha:_

- Our system obtains a 0.289 overall score in the leaderboard, an improvement of 183% compared to the baseline, and a ROUGE-1 score of 0.444, achieving a second place performance in the shared task.
  - source: `10.18653/v1/2024.bionlp-1.61` (fact_id=`208031`, lane=`C_noise`)
- MCCoder achieves a 131.77% improvement on complex tasks in the MCEVAL dataset.
  - source: `10.1109/case58245.2025.11163835` (fact_id=`220335`, lane=`C_noise`)
- on real hallucinations from RLHF-aligned models, embedding methods yield 100% FPR at target coverage
  - source: `10.48550/arxiv.2512.15068` (fact_id=`220009`, lane=`C_noise`)

See `frontier_review.md` for the raw lens + tensions, and `top_5.md` for the deterministic top-5.
