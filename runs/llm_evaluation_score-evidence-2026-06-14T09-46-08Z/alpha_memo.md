# Alpha memo — llm_evaluation_score

**Headline:** LLM-based methods and models improve accuracy across diverse evaluation tasks and benchmarks
**Alpha score:** 90/100
**Alpha triage:** `high` (internal ranking; not a certainty claim)
**Confidence:** `evidence_backed_signal`
**Memo surface:** `receipt map`
**Selected angle:** `source`
**Snapshot:** `llm_evaluation_score-evidence-2026-06-14T09-46-08Z`
**Run:** `llm_evaluation_score-evidence-2026-06-14T09-46-08Z`
**Direct source breadth:** `5` direct cited source(s)
**Source breadth:** `6/5` unique cited source(s)

## One-sentence thesis

Across 5 independently cited sources, the evidence converges on one bounded claim: lLM-based methods and models improve accuracy across diverse evaluation tasks and benchmarks. Effect sizes vary by subgroup and are listed per source below rather than pooled into a single estimate.

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

- `fact_id=llm_evaluation/auto/2025/accuracy_327613` (`B_context`) — Across 15 studies (43 effect sizes; 498 physicians; 7,274 case evaluations), LLM assistance significantly improved diagnostic accuracy compared to physicians without LLM support (Hedges g = 0.20, 95% CI 0.12-0.29; P < . Source: The Effect of LLM Assistance on Diagnostic Accuracy: A Meta-Analysis
- `fact_id=208458` (`B_context`) — When evaluated on the BIRD benchmark with Qwen2.5-72B-Instruct, SDE-SQL achieves an 8.02% relative improvement in execution accuracy over the vanilla Qwen2.5-72B-Instruct baseline, establishing a new state-of-the-art among methods based on Source: SDE-SQL: Enhancing Text-to-SQL Generation in Large Language Models via Self-Driven Exploration with SQL Probes

## Next extraction

- Extract independent A_core/B_context receipts that test the lead contrast directly.
- Audit whether each direct receipt remains comparable on population, endpoint, comparator, and measurement method.
- Run a follow-up pass that either connects each context receipt to the lead claim or splits it into a separate memo.

## Subtopic recommendations

- This topic looks broad/noisy enough that the next run should split it before trying to force one public thesis.
- `models_methods_baselines` — A Legal Fact-Finding Model Based on the T5 and LexiLaw Large Language Models

## Provenance / priority

- **Topic:** `llm_evaluation_score`
- **Author:** Dom Lynch
- **ORCID:** _not configured_
- **Version:** 1.0
- **License:** CC BY-NC 4.0
- **Canonical URL:** _not assigned_
- **Suggested citation:** Dom Lynch. (llm_). LLM-based methods and models improve accuracy across diverse evaluation tasks and benchmarks. ReseaRka Evidence Index. Version 1.0.
- **Run bundle SHA-256:** `d720b816992e732d9802c2203ea8f87854718af4be31bd37bf82b251c9b3d451`
- **Memo SHA-256:** `11dbc6dd7a08293fab4c4673d34ce5b69efe3f52618d20082c7ca61a395670d7`
- **Priority note:** This memo records the first published framing, source bundle, and evidence receipts for this run. Reuse should cite the canonical version.
