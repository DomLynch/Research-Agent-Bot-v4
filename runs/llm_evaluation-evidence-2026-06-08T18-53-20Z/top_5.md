# Top 5 interesting findings — llm_evaluation

**Snapshot:** 2026-06-08T18-53-20Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=llm_evaluation) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 5
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: model_context=5)

---

## #1 — score 80 · accuracy

**Finding:** Failure-Trace Allocator achieves 80.69% accuracy versus 77.64%, 77.08%, and 75.14% for L1, S1, and TALE.

- **Value:** 80.69%
- **Population:** llm_evaluation GSM8K answer selection
- **Intervention:** Cohere command-r-plus-08-2024
- **Alpha cues:** baseline
- **Source:** *Selective Deferral for Budgeted LLM Answer Selection: Failure-Trace Signals under Matched-Budget Evaluation* —  (2026)
  · DOI: `10.21203/rs.3.rs-9783817/v1`
- **Validator:** researka-ai-results

- **Why it matters:** This is worth checking because it ties Cohere command-r-plus-08-2024 in llm_evaluation GSM8K answer selection to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

## #2 — score 80 · accuracy

**Finding:** On the GSM8K benchmark, Mistral-7B fine-tuned with PiSSA achieves an accuracy of 72.86%, surpassing LoRA's 67.7% by 5.16%.

- **Value:** 72.86%
- **Population:** llm_evaluation GSM8K GSM8K
- **Intervention:** Mistral-7B fine-tuned with PiSSA
- **Alpha cues:** baseline
- **Source:** *PiSSA: Principal Singular Values and Singular Vectors Adaptation of Large Language Models* — ArXiv (2024)
  · DOI: `10.48550/arxiv.2404.02948`
- **Validator:** researka-ai-results-exact

- **Why it matters:** This is worth checking because it ties Mistral-7B fine-tuned with PiSSA in llm_evaluation GSM8K GSM8K to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

## #3 — score 80 · accuracy

**Finding:** MuMath-Code-70B model achieves new state-of-the-art performance among open methods—achieving 90.7% on GSM8K

- **Value:** 90.7%
- **Population:** llm_evaluation GSM8K mathematical reasoning
- **Intervention:** MuMath-Code-70B
- **Alpha cues:** baseline
- **Source:** *MuMath-Code: Combining Tool-Use Large Language Models with Multi-perspective Data Augmentation for Mathematical Reasoning* — ArXiv (2024)
  · DOI: `10.48550/arxiv.2405.07551`
- **Validator:** researka-ai-results-exact

- **Why it matters:** This is worth checking because it ties MuMath-Code-70B in llm_evaluation GSM8K mathematical reasoning to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

## #4 — score 80 · accuracy

**Finding:** Through comprehensive evaluation on GSM8K, StrategyQA, and bAbI benchmarks using four state-of-the-art models (Gemma-3 27B, LLaMA-3.1 8B, Mistral 7B, and Qwen-2.5 14B), we demonstrate that CoS achieves 71.5% accuracy on GSM8K (1.0% absolute improvement), 90.0% on StrategyQA (2.5% improvement), and 19.0% on bAbI (65.2% relative improvement) compared to the strongest baselines.

- **Value:** 71.5%
- **Population:** llm_evaluation GSM8K GSM8K
- **Intervention:** LLaMA
- **Alpha cues:** baseline
- **Source:** *Chain of Simulation: A Dual-Mode Reasoning Framework for Large Language Models with Dynamic Problem Routing* — ArXiv (2026)
  · DOI: `10.48550/arxiv.2602.02842`
- **Validator:** researka-ai-results-exact

- **Why it matters:** This is worth checking because it ties LLaMA in llm_evaluation GSM8K GSM8K to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

## #5 — score 76 · accuracy

**Finding:** the maximum drop reaching 49.89% on GSM8K

- **Value:** 49.89%
- **Population:** llm_evaluation GSM8K mathematical reasoning
- **Intervention:** LLMs
- **Alpha cues:** baseline
- **Source:** *MSCR: Exploring the Vulnerability of LLMs' Mathematical Reasoning Abilities Using Multi-Source Candidate Replacement* — ArXiv (2025)
  · DOI: `10.48550/arxiv.2511.08055`
- **Validator:** researka-ai-results-exact

- **Why it matters:** This is worth checking because it ties LLMs in llm_evaluation GSM8K mathematical reasoning to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---
