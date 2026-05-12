# Corpus QA Report - rapamycin-s7-iter-15-2026-05-12T04-57-15Z

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

| study_id | title | yr | venue | spec | interv | endp | ctrl | conf | chars | first evidence quote |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s009 | Long-term treatment of cancer-prone germline PTEN mutant mice with lo... | 2022 | The Journal of pathology | yes | yes | yes | yes | 1.00 | 58223 | Long-term treatment of cancer-prone germline PTEN mutant mice with low-dose rapamycin extends lifespan and de... |
| s019 | mTOR inhibitors rescue premature lethality and attenuate dysregulatio... | 2016 | Journal of inherited metabolic disease | yes | yes | yes | yes | 1.00 | 38646 | Aldehyde dehydrogenase 5a1-deficient ( aldh5a1 −/− ) mice, the murine orthologue of human succinic semialdehy... |
| s026 | Four anti-aging drugs and calorie-restricted diet produce parallel ef... | 2023 | GeroScience | yes | yes | yes | yes | 1.00 | 3474 | Four anti-aging drugs and calorie-restricted diet produce parallel effects in fat, brain, muscle, macrophages... |
| s098 | Unsupervised learning of aging principles from longitudinal data. | 2022 | Nature communications | yes | yes | yes | yes | 1.00 | 80000 | In a subset of blood tests from the Mouse Phenome Database, dFI increased exponentially and predicted the rem... |
| s101 | Premature recruitment of oocyte pool and increased mTOR activity in F... | 2018 | Scientific reports | yes | yes | yes | yes | 1.00 | 25804 | Fmr1 knockout (KO) mouse model |
| s103 | Lifespan-extending interventions induce consistent patterns of fatty ... | 2023 | Communications biology | yes | yes | yes | yes | 1.00 | 80000 | Differential Rank Conservation (DIRAC) analyses of mouse liver proteomics and transcriptomics data show that ... |
| s107 | Long-lasting geroprotection from brief rapamycin treatment in early a... | 2022 | Nature aging | yes | yes | yes | yes | 1.00 | 80000 | In mice, rapamycin can delay several age-related diseases |
| s115 | Effects of rapamycin on growth hormone receptor knockout mice. | 2018 | Proceedings of the National Academy of Sciences of the United States of America | yes | yes | yes | yes | 1.00 | 5255 | Effects of rapamycin on growth hormone receptor knockout mice |
| s207 | Rapamycin extends murine lifespan but has limited effects on aging. | 2013 | The Journal of clinical investigation | yes | yes | yes | yes | 1.00 | 80000 | Rapamycin extends murine lifespan but has limited effects on aging |
| s218 | Diverse interventions that extend mouse lifespan suppress shared age-... | 2017 | Genome biology | yes | yes | yes | yes | 1.00 | 69871 | Diverse interventions that extend mouse lifespan suppress shared age-associated epigenetic changes at critica... |
| s219 | Epigenetic aging signatures in mice livers are slowed by dwarfism, ca... | 2017 | Genome biology | yes | yes | yes | yes | 1.00 | 51704 | Epigenetic aging signatures in mice livers are slowed by dwarfism, calorie restriction and rapamycin treatmen... |
| s227 | Mice fed rapamycin have an increase in lifespan associated with major... | 2014 | PloS one | yes | yes | yes | yes | 1.00 | 67976 | Mice Fed Rapamycin Have an Increase in Lifespan Associated with Major Changes in the Liver Transcriptome |
| s230 | Health Effects of Long-Term Rapamycin Treatment: The Impact on Mouse ... | 2015 | PloS one | yes | yes | yes | yes | 1.00 | 54842 | enteric rapamycin was given to male and female C57BL/6J mice starting at 4 months of age and continued throug... |
| s231 | The effect of a ketogenic diet and synergy with rapamycin in a mouse ... | 2020 | PloS one | yes | yes | yes | yes | 1.00 | 60244 | The effect of a ketogenic diet and synergy with rapamycin in a mouse model of breast cancer. |
| s235 | Transient rapamycin treatment during developmental stage extends life... | 2022 | EMBO reports | yes | yes | yes | yes | 1.00 | 6598 | Transient rapamycin treatment during developmental stage extends lifespan in Mus musculus and Drosophila mela... |
| s237 | Rapamycin Reduces Carcinogenesis and Enhances Survival in Mice when A... | 2024 | Radiation research | yes | yes | yes | yes | 1.00 | 54 | Rapamycin Reduces Carcinogenesis and Enhances Survival in Mice when Administered after Nonlethal Total-Body I... |
| s244 | Rapamycin doses sufficient to extend lifespan do not compromise muscl... | 2013 | Aging | yes | yes | yes | yes | 1.00 | 80000 | Rapamycin extends lifespan in mice |
| s259 | p53 and rapamycin are additive. | 2015 | Oncotarget | yes | yes | yes | yes | 1.00 | 48995 | p53 enabled rapamycin-driven life span extension in mice. |
| s263 | SRN-901, a Novel Longevity Drug, Extends Lifespan and Healthspan by T... | 2026 | Drug design, development and therapy | yes | yes | yes | yes | 1.00 | 77026 | 18-month-old mice fed a Western Diet |
| s268 | Dose-dependent effects of mTOR inhibition on weight and mitochondrial... | 2015 | Frontiers in genetics | yes | yes | yes | yes | 1.00 | 37179 | Dose-dependent effects of mTOR inhibition on weight and mitochondrial disease in mice. |
| s269 | Divergent tissue and sex effects of rapamycin on the proteasome-chape... | 2014 | Frontiers in molecular neuroscience | yes | yes | yes | yes | 1.00 | 73090 | Divergent tissue and sex effects of rapamycin on the proteasome-chaperone network of old mice. |
| s288 | Transient rapamycin treatment can increase lifespan and healthspan in... | 2016 | eLife | yes | yes | yes | yes | 1.00 | 80000 | Transient rapamycin treatment can increase lifespan and healthspan in middle-aged mice. |

## Sentinel-stage audit

| sentinel_id | role | stage | parsed? | elig | conf | reason / failure |
| --- | --- | --- | --- | --- | --- | --- |
| 10.1038/nature08221 | primary | retrieved+candidate | yes | unclear | 0.00 | proposal parse error: variance disagreement; low judge confidence 0.00; missing mandatory... |
| 10.1093/gerona/glq178 | primary | retrieved+candidate | no | no-decision | - | html fetch failed: HTTPStatusError |
| 10.7554/elife.16351 | primary | retrieved+candidate | yes | include | 1.00 | judge included (conf 1.00); mandatory fields confirmed |
| 10.1093/gerona/glw153 | prior_meta | retrieved+candidate | no | no-parse | - | no parsed receipt |

## Quality flags

- 2 primary sentinel(s) did NOT land as include: ['10.1038/nature08221', '10.1093/gerona/glq178']
