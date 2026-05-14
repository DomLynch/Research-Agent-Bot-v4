# Source-fact audit — rapamycin

**Snapshot:** 2026-05-14T16-22-02Z
**Facts inspected:** 7
**Survives:** 0   **Dies:** 3   **Needs extraction:** 4

Verdicts come from Gemma (judge model, temperature 0.0) comparing each fact's DB-stored value + subgroup attribution against the source paper's PubMed abstract. `dies` means the abstract contradicts the DB claim (wrong number, wrong subgroup, or wrong metric). `needs_extraction` means the abstract did not discuss the value directly.

---

## [?] rapamycin/transient/bitto_2016/lifespan_extension

- **Verdict:** `needs_extraction`
- **DB value:** 60.0%
- **PMID:** 27549339
- **Source quote:** 3 months of rapamycin treatment is sufficient to increase life expectancy by up to 60% and improve measures of healthspan in middle-aged mice
- **Reason:** While the abstract mentions a 60% increase in life expectancy for middle-aged mice, it does not specify the strain (C57BL/6), the starting age (20 months), or the specific dose (8 mg/kg/day i.p.) mentioned in the claim.

---

## [FAIL] rapamycin/transient/bitto_2016/lifespan_male

- **Verdict:** `dies`
- **DB value:** 52.0%
- **PMID:** 27549339
- **Source quote:** increase life expectancy by up to 60%
- **Reason:** The abstract states an increase of up to 60% in middle-aged mice, not specifically 52% in male C57BL/6 mice as claimed.

---

## [FAIL] rapamycin/itp/harrison_2009/lifespan_female

- **Verdict:** `dies`
- **DB value:** 9.0%
- **PMID:** 19587680
- **Source quote:** On the basis of age at 90% mortality, rapamycin led to an increase of 14% for females and 9% for males.
- **Reason:** The abstract reports a 14% increase for females based on age at 90% mortality, not a 9% increase in median lifespan as claimed, and attributes 9% to males, not females.

---

## [FAIL] rapamycin/itp/harrison_2009/lifespan_male

- **Verdict:** `dies`
- **DB value:** 14.0%
- **PMID:** 19587680
- **Source quote:** On the basis of age at 90% mortality, rapamycin led to an increase of 14% for females and 9% for males.
- **Reason:** The abstract attributes a 9% increase to males based on age at 90% mortality, not a 14% increase in median lifespan as claimed.

---

## [?] rapamycin/immune/mannick_2014/influenza_vaccine_response

- **Verdict:** `needs_extraction`
- **DB value:** 20.0%
- **PMID:** 25540326
- **Source quote:** RAD001 enhanced the response to the influenza vaccine by about 20% at doses that were relatively well tolerated.
- **Reason:** While the abstract confirms the 20% improvement, it does not specify the population size (n=218) or the specific dosing regimens (0.5 mg daily, 5 mg weekly, 20 mg weekly), which requires extraction from the full text.

---

## [?] rapamycin/itp/miller_2014/dose_response_high_male

- **Verdict:** `needs_extraction`
- **DB value:** 23.0%
- **PMID:** 24472261
- **Source quote:** Dose optimization of infliximab in patients with rheumatoid arthritis.
- **Reason:** The abstract discusses infliximab for rheumatoid arthritis and does not mention rapamycin, lifespan, or any related studies, so it cannot verify the fact.

---

## [?] rapamycin/itp/miller_2014/dose_response_high_female

- **Verdict:** `needs_extraction`
- **DB value:** 26.0%
- **PMID:** 24472261
- **Source quote:** Dose optimization of infliximab in patients with rheumatoid arthritis.
- **Reason:** The abstract discusses infliximab for rheumatoid arthritis and does not mention rapamycin, lifespan, mice, or the specific value of 26% lifespan extension.

