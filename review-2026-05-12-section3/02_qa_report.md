# Corpus QA Report - rapamycin-s7-iter-13-2026-05-12T04-01-27Z

Topic: rapamycin

## Topline counts
- candidates: 298
- parsed (parsed=True): 136
- eligibility decisions: 136
  - include: 12
  - exclude: 94
  - unclear: 30
- declared sentinels: 4 (3 primary + 1 prior_meta)

## Per-include audit

| study_id | title | yr | venue | spec | interv | endp | ctrl | conf | chars | first evidence quote |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s009 | Long-term treatment of cancer-prone germline PTEN mutant mice with lo... | 2022 | The Journal of pathology | yes | yes | yes | yes | 1.00 | 58223 | Long-term treatment of cancer-prone germline PTEN mutant mice with low-dose rapamycin extends lifespan and de... |
| s101 | Premature recruitment of oocyte pool and increased mTOR activity in F... | 2018 | Scientific reports | yes | yes | yes | yes | 1.00 | 25804 | Fmr1 knockout (KO) mouse model |
| s103 | Lifespan-extending interventions induce consistent patterns of fatty ... | 2023 | Communications biology | yes | yes | yes | yes | 1.00 | 80000 | Differential Rank Conservation (DIRAC) analyses of mouse liver proteomics and transcriptomics data show that ... |
| s105 | Acarbose suppresses symptoms of mitochondrial disease in a mouse mode... | 2023 | Nature metabolism | yes | yes | yes | yes | 1.00 | 80000 | Rapamycin, a drug that increases lifespan and health during normative ageing, also increases survival and red... |
| s112 | The geroprotectors trametinib and rapamycin combine additively to ext... | 2025 | Nature aging | yes | yes | yes | yes | 1.00 | 80000 | we assessed survival and health of male and female mice treated with trametinib, rapamycin or their combinati... |
| s115 | Effects of rapamycin on growth hormone receptor knockout mice. | 2018 | Proceedings of the National Academy of Sciences of the United States of America | yes | yes | yes | yes | 1.00 | 5255 | Effects of rapamycin on growth hormone receptor knockout mice |
| s219 | Epigenetic aging signatures in mice livers are slowed by dwarfism, ca... | 2017 | Genome biology | yes | yes | yes | yes | 1.00 | 51704 | To examine whether epigenetic aging signatures are slowed by longevity-promoting interventions, we analyzed 2... |
| s230 | Health Effects of Long-Term Rapamycin Treatment: The Impact on Mouse ... | 2015 | PloS one | yes | yes | yes | yes | 1.00 | 54842 | enteric rapamycin was given to male and female C57BL/6J mice starting at 4 months of age and continued throug... |
| s235 | Transient rapamycin treatment during developmental stage extends life... | 2022 | EMBO reports | yes | yes | yes | yes | 1.00 | 80000 | Transient rapamycin treatment during developmental stage extends lifespan in Mus musculus and Drosophila mela... |
| s263 | SRN-901, a Novel Longevity Drug, Extends Lifespan and Healthspan by T... | 2026 | Drug design, development and therapy | yes | yes | yes | yes | 1.00 | 77026 | Eighteen-month-old C57BL/6 mice were treated until death |
| s268 | Dose-dependent effects of mTOR inhibition on weight and mitochondrial... | 2015 | Frontiers in genetics | yes | yes | yes | yes | 1.00 | 37179 | Dose-dependent effects of mTOR inhibition on weight and mitochondrial disease in mice. |
| s288 | Transient rapamycin treatment can increase lifespan and healthspan in... | 2016 | eLife | yes | yes | yes | yes | 1.00 | 80000 | Transient rapamycin treatment can increase lifespan and healthspan in middle-aged mice. |

## Sentinel-stage audit

| sentinel_id | role | stage | parsed? | elig | conf | reason / failure |
| --- | --- | --- | --- | --- | --- | --- |
| 10.1038/nature08221 | primary | retrieved+candidate | yes | unclear | 0.10 | low judge confidence 0.10; missing mandatory: species_match, intervention_match, endpoint... |
| 10.1093/gerona/glq178 | primary | retrieved+candidate | no | no-decision | - | html fetch failed: HTTPStatusError |
| 10.7554/elife.16351 | primary | retrieved+candidate | yes | include | 1.00 | judge included (conf 1.00); mandatory fields confirmed |
| 10.1093/gerona/glw153 | prior_meta | retrieved+candidate | no | no-parse | - | no parsed receipt |

## Quality flags

- 2 primary sentinel(s) did NOT land as include: ['10.1038/nature08221', '10.1093/gerona/glq178']
