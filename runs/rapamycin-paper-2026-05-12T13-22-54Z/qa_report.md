# Corpus QA Report - latest

Topic: rapamycin

## Topline counts
- candidates: 298
- parsed (parsed=True): 75
- eligibility decisions: 75
  - include: 8
  - exclude: 60
  - unclear: 7
  - unavailable: 0
- declared sentinels: 4 (3 primary + 1 prior_meta)

## Per-include audit

| study_id | lane | title | yr | spec | interv | endp | ctrl | conf | chars | first evidence quote |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s086 | A | Rapamycin fed late in life extends lifespan in genetically ... | 2009 | yes | yes | yes | yes | 1.00 | 33367 | We report here that rapamycin, an inhibitor of the mTOR pathway, extends median and maxim... |
| s105 | B | Acarbose suppresses symptoms of mitochondrial disease in a ... | 2023 | yes | yes | yes | yes | 1.00 | 80000 | Furthermore, rapamycin and acarbose have additive effects in delaying neurological sympto... |
| s230 | A | Health Effects of Long-Term Rapamycin Treatment: The Impact... | 2015 | yes | yes | yes | yes | 1.00 | 54286 | At four months of age 160 mice, 80 animals per sex, began receiving mouse chow (Purina 5L... |
| s235 | A | Transient rapamycin treatment during developmental stage ex... | 2022 | yes | yes | yes | yes | 1.00 | 80000 | Rapamycin (10 mg/kg) was administered daily in two distinct temporal windows, from postna... |
| s237 | B | Rapamycin Reduces Carcinogenesis and Enhances Survival in M... | 2024 | yes | yes | yes | yes | 1.00 | 43123 | Immediately after TBI, along with untreated control groups, animals were placed on chow c... |
| s244 | C | Rapamycin doses sufficient to extend lifespan do not compro... | 2013 | yes | yes | yes | yes | 1.00 | 80000 | we tested whether rapamycin, at the same doses used to extend lifespan, affects mitochond... |
| s246 | A | BMAL1-dependent regulation of the mTOR signaling pathway de... | 2014 | yes | yes | yes | yes | 1.00 | 80000 | treatment with the mTORC1 inhibitor rapamycin increased lifespan of Bmal1−/− mice by 50% |
| s288 | C | Transient rapamycin treatment can increase lifespan and hea... | 2016 | yes | yes | yes | yes | 1.00 | 80000 | we set out to investigate whether a single three-month treatment regimen can extend lifes... |

## Sentinel-stage audit

| sentinel_id | role | stage | parsed? | elig | conf | reason / failure |
| --- | --- | --- | --- | --- | --- | --- |
| 10.1038/nature08221 | primary | retrieved+candidate | yes | include | 1.00 | judge included (conf 1.00); mandatory fields confirmed |
| 10.1093/gerona/glq178 | primary | retrieved+candidate | yes | unclear | 1.00 | include_contract failed: char_count 4041 < 5000 |
| 10.7554/elife.16351 | primary | retrieved+candidate | yes | include | 1.00 | judge included (conf 1.00); mandatory fields confirmed |
| 10.1093/gerona/glw153 | prior_meta | retrieved+candidate | no | no-parse | - | no parsed receipt |

## Sentinel resolution status (manual overlay)

| sentinel_id | role | study_id | auto_decision | manual_status | action_required |
| --- | --- | --- | --- | --- | --- |
| 10.1038/nature08221 | primary | s086 | include | resolved_available | wire stable OA mirror or supply verified Nature PDF; until ... |
| 10.1093/gerona/glq178 | primary | s126 | unclear | resolved_unavailable | supply institutional auth or licensed OUP feed |
| 10.7554/elife.16351 | primary | s288 | include | resolved_available | judge prompt stabilisation so this paper passes the univers... |
| 10.1093/gerona/glw153 | prior_meta | s136 | no-receipt | (no manual record) |  |

## Quality flags

- 2 primary sentinel(s) UNRESOLVED (no auto verdict + no manual record): ['10.1038/nature08221', '10.7554/elife.16351']
