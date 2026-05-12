# Corpus QA Report - latest

Topic: rapamycin

## Topline counts
- candidates: 298
- parsed (parsed=True): 139
- eligibility decisions: 140
  - include: 22
  - exclude: 108
  - unclear: 9
- declared sentinels: 4 (3 primary + 1 prior_meta)

## Per-include audit

| study_id | lane | title | yr | spec | interv | endp | ctrl | conf | chars | first evidence quote |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s092 | A | Metformin potentiates nephrotoxicity by promoting NETosis i... | 2023 | yes | yes | yes | yes | 1.00 | 76604 | we treated mice with AKI induced by renal ischemia-reperfusion (I/R) with different drugs... |
| s094 | A | The mTOR pathway is necessary for survival of mice with sho... | 2020 | yes | yes | yes | yes | 1.00 | 80000 | 3-month-old wild type and second-generation telomerase-deﬁcient mice (G2 Terc−/−) in a C5... |
| s099 | A | High-content screening identifies ganoderic acid A as a sen... | 2025 | yes | yes | yes | yes | 1.00 | 80000 | As expected, rapamycin (100 μM) signiﬁcantly extended the median (12%) and maximum lifesp... |
| s101 | B | Premature recruitment of oocyte pool and increased mTOR act... | 2018 | yes | yes | yes | yes | 1.00 | 25804 | Breeding, histologic and mTOR signaling data were obtained at multiple time points in KO ... |
| s103 | A | Lifespan-extending interventions induce consistent patterns... | 2023 | yes | yes | yes | yes | 1.00 | 80000 | In this LC-M001 experiment, 48 mice were either untreated (Control) or subjected to one o... |
| s105 | B | Acarbose suppresses symptoms of mitochondrial disease in a ... | 2023 | yes | yes | yes | yes | 1.00 | 80000 | Rapamycin, a drug that increases lifespan and health during normative ageing, also increa... |
| s107 | A | Long-lasting geroprotection from brief rapamycin treatment ... | 2022 | yes | yes | yes | yes | 1.00 | 80000 | In mice, a 3-month, early treatment also induced a memory effect, with maintenance simila... |
| s109 | A | Inhibition of S6K lowers age-related inflammation and incre... | 2024 | yes | yes | yes | yes | 1.00 | 80000 | Rapamycin treatment also elevated Syntaxin 12/13 levels in mouse liver and prevented age-... |
| s112 | A | The geroprotectors trametinib and rapamycin combine additiv... | 2025 | yes | yes | yes | yes | 1.00 | 80000 | We measured the survival of mice on diets contain- ing only rapamycin (42 mg kg–1), the d... |
| s207 | A | Rapamycin extends murine lifespan but has limited effects o... | 2013 | yes | yes | yes | yes | 1.00 | 80000 | we performed to determine whether rapamycin slows the rate of aging in male C57BL/6J mice. |
| s218 | C | Diverse interventions that extend mouse lifespan suppress s... | 2017 | yes | yes | yes | yes | 1.00 | 69871 | One cohort was given encapsulated rapamycin (42 parts per million (ppm)) from 4 months of... |
| s219 | C | Epigenetic aging signatures in mice livers are slowed by dw... | 2017 | yes | yes | yes | yes | 1.00 | 51704 | we analyzed 28 additional methylomes from mice subjected to lifespan-extending conditions... |
| s227 | C | Mice fed rapamycin have an increase in lifespan associated ... | 2014 | yes | yes | yes | yes | 1.00 | 67976 | Two dietary regimens were used in this study: mice fed a commercial chow, LabDiet 5LG6-JL... |
| s230 | A | Health Effects of Long-Term Rapamycin Treatment: The Impact... | 2015 | yes | yes | yes | yes | 1.00 | 54842 | At four months of age 160 mice, 80 animals per sex, began receiving mouse chow (Purina 5L... |
| s235 | A | Transient rapamycin treatment during developmental stage ex... | 2022 | yes | yes | yes | yes | 1.00 | 80000 | Rapamycin (10 mg/kg) was administered daily in two distinct temporal windows, from postna... |
| s242 | B | Rapamycin extends lifespan and delays tumorigenesis in hete... | 2012 | yes | yes | yes | yes | 1.00 | 26363 | Mice of the first group (n=37) were given rapamycin in drinking water (approximately 1.5 ... |
| s244 | A | Rapamycin doses sufficient to extend lifespan do not compro... | 2013 | yes | yes | yes | yes | 1.00 | 80000 | Therefore, we tested whether rapamycin, at the same doses used to extend lifespan, affect... |
| s246 | A | BMAL1-dependent regulation of the mTOR signaling pathway de... | 2014 | yes | yes | yes | yes | 1.00 | 80000 | treatment with the mTORC1 inhibitor rapamycin increased lifespan of Bmal1−/− mice by 50% |
| s259 | A | p53 and rapamycin are additive. | 2015 | yes | yes | yes | yes | 1.00 | 46709 | Mice were fed chow containing empty Eudragit capsules (control) or capsules containing 14... |
| s263 | A | SRN-901, a Novel Longevity Drug, Extends Lifespan and Healt... | 2026 | yes | yes | yes | yes | 1.00 | 77026 | Rapamycin was mixed in food with a concentration of 14.4 ppm. |
| s268 | A | Dose-dependent effects of mTOR inhibition on weight and mit... | 2015 | yes | yes | yes | yes | 1.00 | 37179 | we compared the effects of dietary rapamycin at doses ranging from 14 to 378 PPM on devel... |
| s282 | B | Rapamycin increases lifespan and inhibits spontaneous tumor... | 2011 | yes | yes | yes | yes | 1.00 | 80000 | Daily administration of rapamycin, an inhibitor of the nutrient sensing mechanistic targe... |

## Sentinel-stage audit

| sentinel_id | role | stage | parsed? | elig | conf | reason / failure |
| --- | --- | --- | --- | --- | --- | --- |
| 10.1038/nature08221 | primary | retrieved+candidate | yes | unclear | 1.00 | include_contract failed: parsed_text_adequate=False; only 1 non-title evidence quote(s); ... |
| 10.1093/gerona/glq178 | primary | retrieved+candidate | no | unavailable | 1.00 | manual override (unavailable): Miller 2011 NIA-ITP follow-up. Located via PMC + Unpaywall... |
| 10.7554/elife.16351 | primary | retrieved+candidate | yes | unclear | 1.00 | include_contract failed: parsed_text_adequate=False; only 1 non-title evidence quote(s); ... |
| 10.1093/gerona/glw153 | prior_meta | retrieved+candidate | no | no-parse | - | no parsed receipt |

## Sentinel resolution status (manual overlay)

| sentinel_id | role | study_id | auto_decision | manual_status | action_required |
| --- | --- | --- | --- | --- | --- |
| 10.1038/nature08221 | primary | s086 | unclear | resolved_available_pending_contract | wire stable OA mirror or supply verified Nature PDF; until ... |
| 10.1093/gerona/glq178 | primary | s126 | unavailable | resolved_unavailable | supply institutional auth or licensed OUP feed |
| 10.7554/elife.16351 | primary | s288 | unclear | resolved_available_pending_contract | judge prompt stabilisation so this paper passes the univers... |
| 10.1093/gerona/glw153 | prior_meta | s136 | no-receipt | (no manual record) |  |

## Quality flags

- sentinel contract gaps remain: 2 primary sentinel(s) resolved_available_pending_contract (['10.1038/nature08221', '10.7554/elife.16351']); retrieval/parser must fix before the universal contract can pass.
