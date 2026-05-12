# Corpus QA Report - latest

Topic: rapamycin

## Topline counts
- candidates: 298
- parsed (parsed=True): 69
- eligibility decisions: 69
  - include: 3
  - exclude: 62
  - unclear: 4
  - unavailable: 0
- declared sentinels: 4 (3 primary + 1 prior_meta)

## Per-include audit

| study_id | lane | title | yr | spec | interv | endp | ctrl | conf | chars | first evidence quote |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s107 | C | Long-lasting geroprotection from brief rapamycin treatment ... | 2022 | yes | yes | yes | yes | 1.00 | 76105 | Here we show that geroprotective effects of chronic rapamycin treatment can be obtained w... |
| s246 | A | BMAL1-dependent regulation of the mTOR signaling pathway de... | 2014 | yes | yes | yes | yes | 1.00 | 80000 | treatment with the mTORC1 inhibitor rapamycin increased lifespan of Bmal1−/− mice by 50% |
| s293 | B | MKK6 deficiency promotes cardiac dysfunction through MKK3-p... | 2022 | yes | yes | yes | yes | 1.00 | 80000 | Cardiac hypertrophy in MKK6 KO mice is reverted by knocking out either p38γ or p38δ or by... |

## Sentinel-stage audit

| sentinel_id | role | stage | parsed? | elig | conf | reason / failure |
| --- | --- | --- | --- | --- | --- | --- |
| 10.1038/nature08221 | primary | retrieved+candidate | yes | unclear | 0.00 | low judge confidence 0.00; missing mandatory: control_present |
| 10.1093/gerona/glq178 | primary | retrieved+candidate | no | no-decision | - | html fetch failed: HTTPStatusError |
| 10.7554/elife.16351 | primary | retrieved+candidate | yes | exclude | 0.30 | merged checklist excluder: combination-only without isolated intervention arm |
| 10.1093/gerona/glw153 | prior_meta | retrieved+candidate | no | no-parse | - | no parsed receipt |

## Sentinel resolution status (manual overlay)

| sentinel_id | role | study_id | auto_decision | manual_status | action_required |
| --- | --- | --- | --- | --- | --- |
| 10.1038/nature08221 | primary | s086 | unclear | resolved_available_pending_contract | wire stable OA mirror or supply verified Nature PDF; until ... |
| 10.1093/gerona/glq178 | primary | s126 | no-receipt | resolved_unavailable | supply institutional auth or licensed OUP feed |
| 10.7554/elife.16351 | primary | s288 | exclude | resolved_available_pending_contract | judge prompt stabilisation so this paper passes the univers... |
| 10.1093/gerona/glw153 | prior_meta | s136 | no-receipt | (no manual record) |  |

## Quality flags

- sentinel contract gaps remain: 2 primary sentinel(s) resolved_available_pending_contract (['10.1038/nature08221', '10.7554/elife.16351']); retrieval/parser must fix before the universal contract can pass.
