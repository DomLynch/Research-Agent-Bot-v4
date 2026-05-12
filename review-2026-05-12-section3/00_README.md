# Section 3 Review Bundle - iter-15 + Sprint 7.8 post-contract analysis

Source: `runs/latest/` (-> `runs/rapamycin-s7-iter-15-...`)
QA report regenerated 2026-05-12 with Sprint 7.8 include-contract applied
retroactively. The on-disk `eligibility_receipts.json` still shows 22
includes (pre-contract); the QA report shows the 16 that pass the new
contract.

## Sprint 7.8 changes

A. include_contract.py - hard gates that demote any "include" to "unclear"
   when:
     parsed_text_adequate = False, OR
     char_count < 5000, OR
     < 2 non-title evidence quotes, OR
     no quote contains an endpoint term, OR
     no quote contains an intervention/control term.

B. Sentinel gate now 3-level: PASS / WARN / FAIL based on eligibility
   outcome (not just retrieval). PASS requires every primary sentinel
   to be CONFIRMED-INCLUDED. WARN if retrieved but unresolved. FAIL if
   any primary is not retrieved or actively excluded.

C. Lane classifier (A/B/C/D/E) with hard gates first (decision +
   char_count) before title heuristics. s237's 54-char "parse" now
   lands in E regardless of disease-model title terms.

D. Judge prompt asks for >= 2 quotes (1 methods + 1 results); should
   prevent the title-only-quote Bitto-style demotion in future runs.

## Post-contract corpus snapshot

iter-15 originally: 22 INCLUDE / 64 EXCLUDE / 45 UNCLEAR
After Sprint 7.8 contract: 16 INCLUDE / 64 EXCLUDE / 51 UNCLEAR

The 6 demoted includes were mostly Gemma being lazy with quotes (only
the title, or missing intervention/endpoint anchors). Includes that
SURVIVED the contract:

  Lane A (direct lifespan, primary pool eligible):  8
  Lane B (disease-model survival, gated entry):     3
  Lane C (secondary molecular, context only):       5

Lane A papers are the primary-effect-extraction candidates for Sprint 8.

## Sentinel-outcome table (Sprint 7.8 honest)

| Sentinel | Outcome | Lane / Reason |
|---|---|---|
| Harrison 2009 (Nature) | unclear (variance disagreement) | -- judge variants disagreed |
| Miller 2011 (J Gerontol) | no-decision (HTTP fetch failed) | -- retrieval-layer gap |
| Bitto 2016 (eLife) | included by judge, DEMOTED by contract (only 1 title quote) | E -- judge laziness |
| Swindell 2017 meta | no-parse | expected for prior_meta |

Old gate said PASS based on retrieval alone. New gate says WARN: 3/3
retrieved, but only 1 confirmed-included (Bitto, before contract
demotion). Post-contract: 0 confirmed primary sentinels. Gate FAIL.

## What you're reviewing

| File | Purpose |
|---|---|
| 01_section3_prose.md     | iter-15 prose (still pre-Sprint 7.8; mentions PASS) |
| 02_qa_report.md          | post-contract truth: 16 includes, lane-classified |
| 03_manual_review_unclear.md | 51 unclear receipts to spot-check |
| 04_eligibility_summary.json | pre-contract topline |
| 05_eligibility_receipts.json | pre-contract receipts |

## Lock decision

Pre-lock checklist:
- 16 lane-classified includes survive contract (8 in primary lane A)
- Sentinel gate honest: WARN (or FAIL post-contract); Harrison + Miller
  documented gaps
- Contract violations: 0
- s237 false-positive: caught by contract -> lane E

Recommend: run iter-16 (Sprint 7.8 stack live) to regenerate prose with
the new gate text + commit the demotion natively. Then spot-check the
8 Lane-A includes and decide whether to lock Section 3 v3 or fix Harrison
+ Miller first.
