# Alpha memo — llm_evaluation_that

**Headline:** Llm evaluation: llm evaluation accuracy tasks accuracy is the shared direct-receipt signal
**Alpha score:** 90/100
**Alpha triage:** `high` (internal ranking; not a certainty claim)
**Confidence:** `evidence_backed_signal`
**Memo surface:** `subtopic rerun memo`
**Selected angle:** `source`
**Snapshot:** `llm_evaluation_that-evidence-2026-06-14T09-38-12Z`
**Run:** `llm_evaluation_that-evidence-2026-06-14T09-38-12Z`
**Direct source breadth:** `5` direct cited source(s)
**Source breadth:** `6/5` unique cited source(s)

## One-sentence thesis

Across 5 direct receipts sharing llm evaluation accuracy tasks as the evaluation shape and accuracy as the metric, GPT, GPT-4, Claude 3.5 Sonnet report comparable performance against stated baselines. Reported values include 98.83%, 81.3%, 97.0%, 88.57%, 79.5%.

## Why this is surprising

The signal is bounded to llm evaluation accuracy tasks accuracy: the receipts are comparable because they share the benchmark/task/metric shape, even though individual systems may differ.

## Evidence Landscape

**Bounded research question:** Do independent direct receipts on llm evaluation accuracy tasks continue to support a signal on accuracy for the cited systems when comparators are kept explicit?

## Evidence receipts

- `fact_id=llm_evaluation/auto/2025/accuracy_327318` (`A_core`) — Results: GPT achieved 98.83% accuracy (1,439/1,456) compared to Claude's 97.94% (1,426/1,456). doi=10.63858/jass.15.2.71
- `fact_id=llm_evaluation/auto/2025/accuracy_327058` (`A_core`) — GPT-4 achieved an initial accuracy of 81.3% (222/273; 95% CI: 76.3%-85.5%), compared to Claude Opus, which achieved an accuracy of 79.5% (217/273; 95% CI: 74.3%-83.9%). doi=10.1200/jco.2025.43.16_suppl.e13637
- `fact_id=llm_evaluation/auto/2025/accuracy_333571` (`A_core`) — Results: Claude 3.5 Sonnet achieved 97% accuracy (29/30 correct), while DeepSeek-R1 achieved 93.3% accuracy doi=10.33140/an.08.02.05
- `fact_id=llm_evaluation/auto/2025/accuracy_326986` (`A_core`) — GPT-4 achieved the highest diagnostic accuracy for VS at 97.14% (34/35), followed by Gemini at 88.57% (31/35), and Bing at 85.71% (30/35). doi=10.3390/diagnostics15222841
- `fact_id=llm_evaluation/auto/2023/accuracy_323347` (`A_core`) — Our scorer, with an achieved accuracy of 79.5%, significantly outper- forms GPT-4 as a judge (61.3%). doi=10.18653/v1/2024.naacl-long.256

## Context receipts

- `fact_id=llm_evaluation/auto/2025/accuracy_327347` (`A_core`) — With images, ChatGPT-4 achieved 63.7 % Top-1 accuracy versus Gemini's 71.2 % and experts' 87.5 %. doi=10.1109/icicis66182.2025.11313191

## What this changes

Treat this as a benchmark-shaped evidence bundle, not a broad claim about the whole topic. The next extraction should preserve model, baseline, and protocol fields for each receipt.

## Limitations

- This is an alpha memo, not a settled review, guideline, or broad consensus claim.
- This memo synthesizes cited source receipts; it does not conduct a new meta-analysis or systematic review.
- Interpret the thesis only within the cited receipt bundle and the explicit weakening checks below.
- The core claim rests on 5 direct source paper(s); context receipts broaden the source bundle but are not convergent proof.
- Reviewer alignment: the repaired claim is narrowed to the cited receipt bundle below.
- Independent receipts fail to reproduce the claimed contrast.
- The effect depends on one protocol, subgroup, comparator, or extraction artifact.

## What would weaken this

- Independent receipts fail to reproduce the claimed contrast.
- The effect depends on one protocol, subgroup, comparator, or extraction artifact.

## Strongest counter-evidence

- _No direct opposing receipt was selected by this run. Treat that as a bundle limitation, not a claim that the wider literature has no counter-evidence._

## Next extraction

- Extract independent A_core/B_context receipts that test the lead contrast directly.
- Audit whether each direct receipt remains comparable on population, endpoint, comparator, and measurement method.
- Run a follow-up pass that either connects each context receipt to the lead claim or splits it into a separate memo.

## Subtopic recommendations

- This topic looks broad/noisy enough that the next run should split it before trying to force one public thesis.
- `models_methods_baselines` — A Legal Fact-Finding Model Based on the T5 and LexiLaw Large Language Models

## Provenance / priority

- **Topic:** `llm_evaluation_that`
- **Author:** Dom Lynch
- **ORCID:** _not configured_
- **Version:** 1.0
- **License:** CC BY-NC 4.0
- **Canonical URL:** _not assigned_
- **Suggested citation:** Dom Lynch. (llm_). Llm evaluation: llm evaluation accuracy tasks accuracy is the shared direct-receipt signal. ReseaRka Evidence Index. Version 1.0.
- **Run bundle SHA-256:** `21cd88cc5608a4857b568ed2955b808db5e1db5eb7ff07a7aa15c13de3f15c51`
- **Memo SHA-256:** `81794bc2ad1957c4add971ef8a48cc0671943419880b5eff1fc7a532c667dc15`
- **Priority note:** This memo records the first published framing, source bundle, and evidence receipts for this run. Reuse should cite the canonical version.
