**Verdict:** Block.

**Main blocker:** Only 2 of 26 normalized facts are A-core and finance-relevant; the other 24 are medical/clinical noise (COVID, colposcopy, brain MRI, ADEM, athletes) entirely off-topic. Even the 2 A-core facts are near-duplicates from the same 2013 source reporting the same ~11% abnormal return, providing no breadth of evidence.

**Gate correctness:** Correct. Missing-core-field diagnostics confirm severe gaps: 18 facts lack comparator, 9 lack intervention, 3 lack study_design. Top clusters collapse to a single source with one repeated finding, violating single-source/diversity requirements.

**Next data/extraction fix:** (1) Re-run the trace restricting `source_topic` to finance/asset-pricing corpora to eliminate medical contamination. (2) Extract explicit intervention/comparator pairs — e.g., specific signal (momentum, value, quality) vs. named benchmark (CAPM, Fama-French factors), with risk-adjusted alpha, t-stats, and sample period. (3) Require ≥3 independent sources across asset classes or geographies before re-evaluating.