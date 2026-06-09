# Top 2 interesting findings — portfolio_returns

**Snapshot:** 2026-06-09T19-05-30Z
**Source:** Researka DB Tier-1 canonical (`GET /api/v1/topics/portfolio_returns/facts`) — hand-curated, validated.
**Facts inspected:** 3
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: model_context=2)

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `portfolio_returns`


## #1 — score 57 · portfolio_returns

**Finding:** the portfolio with the greatest EPU beta underperforms the portfolio with the lowest EPU beta by 5.53% per annum

- **Value:** 5.53%
- **Population:** Fama–French 25 size–momentum portfolios
- **Intervention:** portfolio with the greatest EPU beta
- **Alpha cues:** baseline
- **Source:** *The Asset-Pricing Implications of Government Economic Policy Uncertainty* — Management Science (2015)
  · DOI: `10.1287/mnsc.2014.2044`
- **Validator:** auto-tier1-promoter-2llm

- **Why it matters:** A 5.53% annual underperformance for high-EPU-beta portfolios shows that policy uncertainty exposure is a priced factor that can meaningfully erode returns for size-momentum strategies held by institutional allocators.
- **Caution:** The result relies on a single beta-sort across Fama-French 25 size-momentum portfolios in one sample, so it may not generalize across market regimes or alternative uncertainty proxies.
- **Next question:** Does the EPU-beta spread persist after controlling for Fama-French factor loadings, or is it simply compensation for systematic factor risk?

---

### Lane — `abnormal_returns`


## #2 — score 54 · abnormal_returns

**Finding:** earn abnormal returns of roughly 11 percent per year

- **Value:** 11.0%
- **Population:** firms
- **Intervention:** long-short portfolio strategy based on past track records
- **Alpha cues:** baseline
- **Source:** *Misvaluing Innovation* — Review of Financial Studies (2013)
  · DOI: `10.1093/rfs/hhs183`
- **Validator:** auto-tier1-promoter-2llm
- **Same-trial supporting numerics:** 11.0% (earns abnormal returns of roughly 11 percent per year)

- **Why it matters:** An 11% per-year abnormal return implies a specific firm-level signal produces returns large enough to attract significant capital and potentially face capacity constraints or rapid arbitrage.
- **Caution:** The abnormal-return estimate comes from a single study without disclosed factor-adjustment or out-of-sample testing, raising concerns about data-snooping and missing-risk explanations.
- **Next question:** Do these 11% abnormal returns survive transaction costs, factor-risk adjustment, and replication in subsequent out-of-sample periods?

---
