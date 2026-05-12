# Section 3 Review Bundle — 2026-05-12

Curated subset of `runs/rapamycin-s7-iter-13-2026-05-12T04-01-27Z/` for
human audit. Source-of-truth files live in that run dir; this folder is
a flat-read convenience copy.

## What you're reading

| # | File | What it is |
|---|---|---|
| 01 | `01_section3_prose.md` | The Section 3 markdown the writer emitted: Study Selection + Sentinel Recall + Corpus Characteristics + 5 blocked subsections pending Sprint 8. |
| 02 | `02_qa_report.md` | Sprint 7.6 audit artefact: per-include audit table (12 rows), sentinel-stage audit (4 rows), quality flags. |
| 03 | `03_manual_review_unclear.md` | 30 receipts flagged 'unclear' by the rule → judge → merge ladder, laid out for human spot-check. |
| 04 | `04_eligibility_summary.json` | Topline counts: hits / candidates / parsed / decisions. |
| 05 | `05_eligibility_receipts.json` | Full machine-readable eligibility decisions with mandatory-fields + evidence quotes per receipt. |

## Run pedigree

- **Run dir**: `runs/rapamycin-s7-iter-13-2026-05-12T04-01-27Z/`
- **Stack at run time**: Sprint 7.5b/c/d/e (MiMo + Gemma 4 31B; parallel
  judge with concurrency=5; sentinel injection; PDF parser; JSONL
  checkpoint).
- **Outcome**: 502 hits → 298 TA candidates → 261 OA located → 136
  parsed → 136 eligibility decisions: **12 INCLUDE / 94 EXCLUDE / 30
  UNCLEAR** → 12 eligible studies, 2015–2026, 12 distinct venues.

## ⚠️ Important caveat

iter-13 was generated **before** the Sprint 7.7 fixes committed at
[`1d69fcd`](https://github.com/DomLynch/Research-Agent-Bot-v4/commit/1d69fcd):

- **A** — judge prompt rewrite (reading discipline: title + Methods
  beat introductory framing)
- **B** — symmetric OR-merge (judge can't whitewash rule positives)
- **B.5** — title-only exclude-design check (prevented Harrison-2009
  from being rejected because its body cites prior meta-analyses)
- **C** — optional variance check (two prompt variants, unclear on
  disagreement)

Single-paper smoke test post-fix confirmed Harrison-2009 flips from
`exclude` (iter-13) → **`include` conf 1.00** under the new stack.

**iter-14 is firing now** under `caffeinate` with `--variance-check`
enabled. When it lands, it will supersede iter-13 and likely show 13+
includes including Harrison-2009. Until then, use iter-13 as the
current best-available snapshot.

## What to audit

1. **Spot-check the 12 includes** in `02_qa_report.md` per-include
   table. Verify each is a primary mouse rapamycin lifespan study with
   an extractable contrast.
2. **Sentinel-stage audit** in `02_qa_report.md`: confirm the
   2-primary-sentinels-missing flag (Harrison + Miller) was a known
   gap addressed by Sprint 7.7.
3. **Manual review queue** in `03_manual_review_unclear.md`: scan the
   30 unclear receipts for any that should clearly be include or
   exclude after human reading.
4. **Section 3 prose** in `01_section3_prose.md`: read as-is and
   verify all numeric claims trace back to receipts.
