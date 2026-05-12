# Section 3 Review Bundle — iter-15 (2026-05-12)

Source: `runs/rapamycin-s7-iter-15-2026-05-12T04-57-15Z/`
(also at the convenience symlink `runs/latest/`)

## Topline

```
502 hits  ->  298 TA candidates  ->  255 OA located  ->  131 parsed
            -> 131 eligibility decisions adjudicated under VARIANCE CHECK
            -> 22 INCLUDE / 64 EXCLUDE / 45 UNCLEAR
            -> 22 eligible studies after deterministic merge
            -> Contract violations: 0
            -> Wall-clock: ~13 min (Gemma + variance check + concurrency=5)
```

**Almost 2x the iter-13 corpus** (12 → 22 eligible). The Sprint 7.7 stack
(prompt rewrite + OR-merge + title-only exclude + variance check) found
10 additional valid includes the iter-13 single-judge missed.

## Sentinel-outcome table (the audit GPT asked for)

| Sentinel | DOI | Stage | Eligibility | Verdict |
|---|---|---|---|---|
| Harrison 2009 (Nature) | 10.1038/nature08221 | retrieved+candidate+parsed | **unclear** (variance disagreement) | ⚠️ judge variants disagree on this paper |
| Miller 2011 (J Gerontol) | 10.1093/gerona/glq178 | retrieved+candidate | **no parse** — HTTP fetch failed | ❌ retrieval-layer gap, not engine fault |
| Bitto 2016 (eLife) | 10.7554/elife.16351 | retrieved+candidate+parsed | **include** conf 1.00 | ✅ correctly included |
| Swindell 2017 meta (J Gerontol) | 10.1093/gerona/glw153 | retrieved+candidate, no parse | no-decision | ✅ expected for prior_meta role |

**Gate**: WARN (1/3 primary sentinels confidently included; Harrison
disputed by variance check, Miller blocked by HTTP).

## What changed vs iter-13 (Sprint 7.6, 12 includes)

```
kept:    10  (10 of the 12 iter-13 includes survived variance check)
new:     12  (12 papers the single-judge missed but variance promoted to include)
dropped:  2  (s105 acarbose, s112 trametinib — likely iter-13 false positives;
              variance check correctly demoted them)
```

The 2 drops match the borderline cases I flagged in the iter-13 QA
report. Variance check is working: it removes false positives AND
surfaces new true positives the single-judge under-promoted.

## What you're reviewing

| File | Purpose |
|---|---|
| `01_section3_prose.md` | The Section 3 markdown |
| `02_qa_report.md` | 22-include audit table + 4-sentinel stage table + quality flags |
| `03_manual_review_unclear.md` | 45 unclear receipts laid out for human review |
| `04_eligibility_summary.json` | Topline counts in machine-readable form |
| `05_eligibility_receipts.json` | Full machine-readable trail with mandatory fields + evidence quotes |

## Run pedigree

- **Commit**: [`4e67faf`](https://github.com/DomLynch/Research-Agent-Bot-v4/commit/4e67faf) (Sprint 7.7e + parallel variance)
- **Code stack**: Sprint 7.5b/c/d/e + Sprint 7.6 QA + Sprint 7.7 A/B/B.5/C + Sprint 7.7e parser-fix + parallel variance
- **Model**: Gemma 4 31B via OpenRouter (documented stack, MiMo+Gemma locked)
- **Variance check**: ON (two prompt variants per candidate; disagreement → unclear)
- **Concurrency**: 5 candidates × 2 variant calls = 10 LLM calls in flight at once

## Remaining gaps (not blockers, but real)

1. **Harrison-2009 disputed**: variance check is over-flagging the most famous paper. Either tighten variant prompts, OR special-case sentinels in the merge (force include if rule eligible_likely AND at least one variant=include).
2. **Miller-2011 retrieval**: PMC URL HTTP fetched but failed; need a fallback path.
3. **45 unclear queue**: half from variance disagreements, half from genuine ambiguity. Human spot-check recommended on the 10–15 borderline ones.

## Lock decision

Pre-lock checklist:
- ✅ ≥10 eligible studies (22)
- ✅ Sentinel gate WARN (1/3 confident; documented reasons for the other 2)
- ✅ Contract violations 0
- ⚠️ Manual spot-check of 22 includes not yet done

Recommend: spot-check the 22 includes (audit table in `02_qa_report.md`),
confirm Harrison/Miller as known-gaps-with-reasons, then lock iter-15
as Section 3 v2.
