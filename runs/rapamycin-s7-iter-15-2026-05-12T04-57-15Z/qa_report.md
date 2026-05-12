# Corpus QA Report - latest

Topic: rapamycin

## Topline counts
- candidates: 298
- parsed (parsed=True): 131
- eligibility decisions: 131
  - include: 22
  - exclude: 64
  - unclear: 45
- declared sentinels: 4 (3 primary + 1 prior_meta)

## Per-include audit

| study_id | lane | title | yr | spec | interv | endp | ctrl | conf | chars | first evidence quote |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s009 | B | Long-term treatment of cancer-prone germline PTEN mutant mi... | 2022 | yes | yes | yes | yes | 1.00 | 58223 | Long-term treatment of cancer-prone germline PTEN mutant mice with low-dose rapamycin ext... |
| s019 | B | mTOR inhibitors rescue premature lethality and attenuate dy... | 2016 | yes | yes | yes | yes | 1.00 | 38646 | Aldehyde dehydrogenase 5a1-deficient ( aldh5a1 −/− ) mice, the murine orthologue of human... |
| s026 | E | Four anti-aging drugs and calorie-restricted diet produce p... | 2023 | yes | yes | yes | yes | 1.00 | 3474 | Four anti-aging drugs and calorie-restricted diet produce parallel effects in fat, brain,... |
| s098 | C | Unsupervised learning of aging principles from longitudinal... | 2022 | yes | yes | yes | yes | 1.00 | 80000 | In a subset of blood tests from the Mouse Phenome Database, dFI increased exponentially a... |
| s101 | B | Premature recruitment of oocyte pool and increased mTOR act... | 2018 | yes | yes | yes | yes | 1.00 | 25804 | Fmr1 knockout (KO) mouse model |
| s103 | A | Lifespan-extending interventions induce consistent patterns... | 2023 | yes | yes | yes | yes | 1.00 | 80000 | Differential Rank Conservation (DIRAC) analyses of mouse liver proteomics and transcripto... |
| s107 | A | Long-lasting geroprotection from brief rapamycin treatment ... | 2022 | yes | yes | yes | yes | 1.00 | 80000 | In mice, rapamycin can delay several age-related diseases |
| s115 | B | Effects of rapamycin on growth hormone receptor knockout mi... | 2018 | yes | yes | yes | yes | 1.00 | 5255 | Effects of rapamycin on growth hormone receptor knockout mice |
| s207 | A | Rapamycin extends murine lifespan but has limited effects o... | 2013 | yes | yes | yes | yes | 1.00 | 80000 | Rapamycin extends murine lifespan but has limited effects on aging |
| s218 | C | Diverse interventions that extend mouse lifespan suppress s... | 2017 | yes | yes | yes | yes | 1.00 | 69871 | Diverse interventions that extend mouse lifespan suppress shared age-associated epigeneti... |
| s219 | C | Epigenetic aging signatures in mice livers are slowed by dw... | 2017 | yes | yes | yes | yes | 1.00 | 51704 | Epigenetic aging signatures in mice livers are slowed by dwarfism, calorie restriction an... |
| s227 | C | Mice fed rapamycin have an increase in lifespan associated ... | 2014 | yes | yes | yes | yes | 1.00 | 67976 | Mice Fed Rapamycin Have an Increase in Lifespan Associated with Major Changes in the Live... |
| s230 | A | Health Effects of Long-Term Rapamycin Treatment: The Impact... | 2015 | yes | yes | yes | yes | 1.00 | 54842 | enteric rapamycin was given to male and female C57BL/6J mice starting at 4 months of age ... |
| s231 | B | The effect of a ketogenic diet and synergy with rapamycin i... | 2020 | yes | yes | yes | yes | 1.00 | 60244 | The effect of a ketogenic diet and synergy with rapamycin in a mouse model of breast canc... |
| s235 | A | Transient rapamycin treatment during developmental stage ex... | 2022 | yes | yes | yes | yes | 1.00 | 6598 | Transient rapamycin treatment during developmental stage extends lifespan in Mus musculus... |
| s237 | B | Rapamycin Reduces Carcinogenesis and Enhances Survival in M... | 2024 | yes | yes | yes | yes | 1.00 | 54 | Rapamycin Reduces Carcinogenesis and Enhances Survival in Mice when Administered after No... |
| s244 | A | Rapamycin doses sufficient to extend lifespan do not compro... | 2013 | yes | yes | yes | yes | 1.00 | 80000 | Rapamycin extends lifespan in mice |
| s259 | A | p53 and rapamycin are additive. | 2015 | yes | yes | yes | yes | 1.00 | 48995 | p53 enabled rapamycin-driven life span extension in mice. |
| s263 | A | SRN-901, a Novel Longevity Drug, Extends Lifespan and Healt... | 2026 | yes | yes | yes | yes | 1.00 | 77026 | 18-month-old mice fed a Western Diet |
| s268 | A | Dose-dependent effects of mTOR inhibition on weight and mit... | 2015 | yes | yes | yes | yes | 1.00 | 37179 | Dose-dependent effects of mTOR inhibition on weight and mitochondrial disease in mice. |
| s269 | C | Divergent tissue and sex effects of rapamycin on the protea... | 2014 | yes | yes | yes | yes | 1.00 | 73090 | Divergent tissue and sex effects of rapamycin on the proteasome-chaperone network of old ... |
| s288 | A | Transient rapamycin treatment can increase lifespan and hea... | 2016 | yes | yes | yes | yes | 1.00 | 80000 | Transient rapamycin treatment can increase lifespan and healthspan in middle-aged mice. |

## Sentinel-stage audit

| sentinel_id | role | stage | parsed? | elig | conf | reason / failure |
| --- | --- | --- | --- | --- | --- | --- |
| 10.1038/nature08221 | primary | retrieved+candidate | yes | unclear | 0.00 | proposal parse error: variance disagreement; low judge confidence 0.00; missing mandatory... |
| 10.1093/gerona/glq178 | primary | retrieved+candidate | no | no-decision | - | html fetch failed: HTTPStatusError |
| 10.7554/elife.16351 | primary | retrieved+candidate | yes | include | 1.00 | judge included (conf 1.00); mandatory fields confirmed |
| 10.1093/gerona/glw153 | prior_meta | retrieved+candidate | no | no-parse | - | no parsed receipt |

## Quality flags

- 2 primary sentinel(s) did NOT land as include: ['10.1038/nature08221', '10.1093/gerona/glq178']
