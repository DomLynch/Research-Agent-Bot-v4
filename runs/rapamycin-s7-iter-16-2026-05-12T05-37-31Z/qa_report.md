# Corpus QA Report - rapamycin-s7-iter-16-2026-05-12T05-37-31Z

Topic: rapamycin

## Topline counts
- candidates: 298
- parsed (parsed=True): 134
- eligibility decisions: 134
  - include: 20
  - exclude: 102
  - unclear: 12
- declared sentinels: 4 (3 primary + 1 prior_meta)

## Per-include audit

| study_id | lane | title | yr | spec | interv | endp | ctrl | conf | chars | first evidence quote |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s092 | A | Metformin potentiates nephrotoxicity by promoting NETosis i... | 2023 | yes | yes | yes | yes | 1.00 | 76604 | we treated mice with AKI induced by renal ischemia-reperfusion (I/R) with different drugs... |
| s094 | A | The mTOR pathway is necessary for survival of mice with sho... | 2020 | yes | yes | yes | yes | 1.00 | 80000 | 3-month-old wild type and second-generation telomerase-deﬁcient mice (G2 Terc−/−) in a C5... |
| s098 | C | Unsupervised learning of aging principles from longitudinal... | 2022 | yes | yes | yes | yes | 1.00 | 80000 | dFI changed along with hallmarks of aging, including frailty index, molecular markers of ... |
| s099 | A | High-content screening identifies ganoderic acid A as a sen... | 2025 | yes | yes | yes | yes | 1.00 | 80000 | As expected, rapamycin (100 μM) signiﬁcantly extended the median (12%) and maximum lifesp... |
| s101 | B | Premature recruitment of oocyte pool and increased mTOR act... | 2018 | yes | yes | yes | yes | 1.00 | 26334 | Breeding, histologic and mTOR signaling data were obtained at multiple time points in KO ... |
| s103 | A | Lifespan-extending interventions induce consistent patterns... | 2023 | yes | yes | yes | yes | 1.00 | 80000 | Differential Rank Conservation (DIRAC) analyses of mouse liver proteomics and transcripto... |
| s105 | B | Acarbose suppresses symptoms of mitochondrial disease in a ... | 2023 | yes | yes | yes | yes | 1.00 | 80000 | Daily administration of rapamycin, an inhibitor of the nutrient sensing mechanistic targe... |
| s107 | A | Long-lasting geroprotection from brief rapamycin treatment ... | 2022 | yes | yes | yes | yes | 1.00 | 80000 | In mice, a 3-month, early treatment also induced a memory effect, with maintenance simila... |
| s109 | A | Inhibition of S6K lowers age-related inflammation and incre... | 2024 | yes | yes | yes | yes | 1.00 | 80000 | Rapamycin treatment also elevated Syntaxin 12/13 levels in mouse liver and prevented age-... |
| s112 | A | The geroprotectors trametinib and rapamycin combine additiv... | 2025 | yes | yes | yes | yes | 1.00 | 80000 | We measured the survival of mice on diets contain- ing only rapamycin (42 mg kg–1), the d... |
| s207 | A | Rapamycin extends murine lifespan but has limited effects o... | 2013 | yes | yes | yes | yes | 1.00 | 80000 | we performed to determine whether rapamycin slows the rate of aging in male C57BL/6J mice. |
| s216 | A | Rapamycin, Acarbose and 17α-estradiol share common mechanis... | 2022 | yes | yes | yes | yes | 1.00 | 72127 | Rapa inhibits the activity of the mammalian target of rapamycin (mTOR), leading at optima... |
| s218 | C | Diverse interventions that extend mouse lifespan suppress s... | 2017 | yes | yes | yes | yes | 1.00 | 69871 | One cohort was given encapsulated rapamycin (42 parts per million (ppm)) from 4 months of... |
| s219 | C | Epigenetic aging signatures in mice livers are slowed by dw... | 2017 | yes | yes | yes | yes | 1.00 | 51704 | To examine whether epigenetic aging signatures are slowed by longevity-promoting interven... |
| s227 | C | Mice fed rapamycin have an increase in lifespan associated ... | 2014 | yes | yes | yes | yes | 1.00 | 67976 | Two dietary regimens were used in this study: mice fed a commercial chow, LabDiet 5LG6-JL... |
| s230 | A | Health Effects of Long-Term Rapamycin Treatment: The Impact... | 2015 | yes | yes | yes | yes | 1.00 | 54842 | At four months of age 160 mice, 80 animals per sex, began receiving mouse chow (Purina 5L... |
| s246 | A | BMAL1-dependent regulation of the mTOR signaling pathway de... | 2014 | yes | yes | yes | yes | 1.00 | 80000 | treatment with the mTORC1 inhibitor rapamycin increased lifespan of Bmal1−/− mice by 50% |
| s259 | A | p53 and rapamycin are additive. | 2015 | yes | yes | yes | yes | 1.00 | 46709 | Mice were fed chow containing empty Eudragit capsules (control) or capsules containing 14... |
| s263 | A | SRN-901, a Novel Longevity Drug, Extends Lifespan and Healt... | 2026 | yes | yes | yes | yes | 1.00 | 76323 | Rapamycin was mixed in food with a concentration of 14.4 ppm. |
| s268 | A | Dose-dependent effects of mTOR inhibition on weight and mit... | 2015 | yes | yes | yes | yes | 1.00 | 37179 | we compared the effects of dietary rapamycin at doses ranging from 14 to 378 PPM on devel... |

## Sentinel-stage audit

| sentinel_id | role | stage | parsed? | elig | conf | reason / failure |
| --- | --- | --- | --- | --- | --- | --- |
| 10.1038/nature08221 | primary | retrieved+candidate | yes | exclude | 1.00 | judge excluded (conf 1.00): The provided text is a reCAPTCHA challenge page and contains ... |
| 10.1093/gerona/glq178 | primary | retrieved+candidate | no | no-decision | - | html fetch failed: HTTPStatusError |
| 10.7554/elife.16351 | primary | retrieved+candidate | yes | unclear | 0.50 | low judge confidence 0.50 |
| 10.1093/gerona/glw153 | prior_meta | retrieved+candidate | no | no-parse | - | no parsed receipt |

## Quality flags

- 3 primary sentinel(s) did NOT land as include: ['10.1038/nature08221', '10.1093/gerona/glq178', '10.7554/elife.16351']
