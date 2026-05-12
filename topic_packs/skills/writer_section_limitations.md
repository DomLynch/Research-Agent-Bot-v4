---
name: writer_section_limitations
description: User-prompt spec for the Limitations section. 200-400 words, one paragraph, specific pipeline-output limitations (corpus size, sentinel recall, k_studies, metric-family discipline, automated RoB, manual full-text overrides). No vague filler.
allowed-tools: none
---
200-400 words, one paragraph. Name SPECIFIC limitations from this pipeline's outputs: corpus size + sentinel-recall gate ([PACKET:sentinel_recall]); k_studies from [PACKET:primary_effect] and its inference implications; metric-family discipline (90th-percentile vs median ratios are pooled separately, no cross-family inference); automated risk-of-bias adjudication without explicit human arbitration; any manual full-text overrides ([PACKET:study_selection]) — documented source recovery, not eligibility override. Do NOT use vague 'further research is needed' filler; name the specific missing data.
