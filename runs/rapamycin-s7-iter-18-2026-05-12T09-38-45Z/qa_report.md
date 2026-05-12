# Corpus QA Report - latest

Topic: rapamycin

## Topline counts
- candidates: 298
- parsed (parsed=True): 71
- eligibility decisions: 71
  - include: 5
  - exclude: 61
  - unclear: 5
  - unavailable: 0
- declared sentinels: 4 (3 primary + 1 prior_meta)

## Per-include audit

| study_id | lane | title | yr | spec | interv | endp | ctrl | conf | chars | first evidence quote |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s009 | B | Long-term treatment of cancer-prone germline PTEN mutant mi... | 2022 | yes | yes | yes | yes | 1.00 | 58223 | we administered a low dose of rapamycin from the age of 6 weeks onwards to mice with hete... |
| s105 | B | Acarbose suppresses symptoms of mitochondrial disease in a ... | 2023 | yes | yes | yes | yes | 1.00 | 80000 | Furthermore, rapamycin and acarbose have additive effects in delaying neurological sympto... |
| s198 | C | Chemopreventive and chemotherapeutic actions of mTOR inhibi... | 2012 | yes | yes | yes | yes | 1.00 | 40558 | Tgfbr1 and Pten conditonal deletion (2cKO) mice were treated with Rapamycin before or aft... |
| s244 | C | Rapamycin doses sufficient to extend lifespan do not compro... | 2013 | yes | yes | yes | yes | 1.00 | 80000 | we tested whether rapamycin, at the same doses used to extend lifespan, affects mitochond... |
| s246 | A | BMAL1-dependent regulation of the mTOR signaling pathway de... | 2014 | yes | yes | yes | yes | 1.00 | 80000 | treatment with the mTORC1 inhibitor rapamycin increased lifespan of Bmal1−/− mice by 50% |

## Sentinel-stage audit

| sentinel_id | role | stage | parsed? | elig | conf | reason / failure |
| --- | --- | --- | --- | --- | --- | --- |
| 10.1038/nature08221 | primary | retrieved+candidate | yes | exclude | 1.00 | judge excluded (conf 1.00): The provided text is a reCAPTCHA challenge page and HTML boil... |
| 10.1093/gerona/glq178 | primary | retrieved+candidate | no | no-decision | - | html fetch failed: HTTPStatusError |
| 10.7554/elife.16351 | primary | retrieved+candidate | yes | unclear | 0.50 | low judge confidence 0.50 |
| 10.1093/gerona/glw153 | prior_meta | retrieved+candidate | no | no-parse | - | no parsed receipt |

## Sentinel resolution status (manual overlay)

| sentinel_id | role | study_id | auto_decision | manual_status | action_required |
| --- | --- | --- | --- | --- | --- |
| 10.1038/nature08221 | primary | s086 | exclude | resolved_available_pending_contract | wire stable OA mirror or supply verified Nature PDF; until ... |
| 10.1093/gerona/glq178 | primary | s126 | no-receipt | resolved_unavailable | supply institutional auth or licensed OUP feed |
| 10.7554/elife.16351 | primary | s288 | unclear | resolved_available_pending_contract | judge prompt stabilisation so this paper passes the univers... |
| 10.1093/gerona/glw153 | prior_meta | s136 | no-receipt | (no manual record) |  |

## Quality flags

- sentinel contract gaps remain: 2 primary sentinel(s) resolved_available_pending_contract (['10.1038/nature08221', '10.7554/elife.16351']); retrieval/parser must fix before the universal contract can pass.
