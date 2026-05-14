# Source-fact audit — rapamycin

**Snapshot:** 2026-05-14T16-22-02Z
**Facts inspected:** 7
**Survives:** 2   **Dies:** 2   **Needs extraction:** 3

Verdicts come from Gemma (judge model, temperature 0.0) comparing each fact's DB-stored value + subgroup attribution against the source paper's PubMed abstract. `dies` means the abstract contradicts the DB claim (wrong number, wrong subgroup, or wrong metric). `needs_extraction` means the abstract did not discuss the value directly.

---

## [?] rapamycin/transient/bitto_2016/lifespan_extension

- **Verdict:** `needs_extraction`
- **DB value:** 60.0%
- **PMID:** 27549339
- **Source quote:** 3 months of rapamycin treatment is sufficient to increase life expectancy by up to 60% and improve measures of healthspan in middle-aged mice
- **Reason:** The abstract confirms the 60% value and the general population, but does not specify the mouse strain (C57BL/6), the exact dose (8 mg/kg/day), or the starting age (20 months).

---

## [?] rapamycin/transient/bitto_2016/lifespan_male

- **Verdict:** `needs_extraction`
- **DB value:** 52.0%
- **PMID:** 27549339
- **Source quote:** 3 months of rapamycin treatment is sufficient to increase life expectancy by up to 60% and improve measures of healthspan in middle-aged mice
- **Reason:** The abstract mentions an increase 'up to 60%' but does not specify the 52% value, the male subgroup, the specific strain, or the dose.

---

## [FAIL] rapamycin/itp/harrison_2009/lifespan_female

- **Verdict:** `dies`
- **DB value:** 9.0%
- **PMID:** 19587680
- **Source quote:** On the basis of age at 90% mortality, rapamycin led to an increase of 14% for females and 9% for males.
- **Reason:** The abstract attributes the 9% increase to males, not females, and specifies the metric as 'age at 90% mortality' rather than 'median lifespan'.

---

## [FAIL] rapamycin/itp/harrison_2009/lifespan_male

- **Verdict:** `dies`
- **DB value:** 14.0%
- **PMID:** 19587680
- **Source quote:** On the basis of age at 90% mortality, rapamycin led to an increase of 14% for females and 9% for males.
- **Reason:** The abstract attributes the 14% increase to females and 9% to males, and specifies the metric as 'age at 90% mortality' rather than median lifespan.

---

## [?] rapamycin/immune/mannick_2014/influenza_vaccine_response

- **Verdict:** `needs_extraction`
- **DB value:** 20.0%
- **PMID:** 25540326
- **Source quote:** RAD001 enhanced the response to the influenza vaccine by about 20% at doses that were relatively well tolerated.
- **Reason:** The abstract supports the 20% improvement in elderly volunteers, but it does not specify the sample size (n=218) or the specific dosing regimens (0.5 mg daily, 5 mg weekly, or 20 mg weekly).

---

## [OK] rapamycin/itp/miller_2014/dose_response_high_male

- **Verdict:** `survives`
- **DB value:** 23.0%
- **PMID:** 24472261
- **Source quote:** Rapamycin at 42 ppm leads to 26% increase in median lifespan in females and 23% in males
- **Reason:** The text explicitly confirms that rapamycin at 42 ppm increased the median lifespan of male mice by 23%.

---

## [OK] rapamycin/itp/miller_2014/dose_response_high_female

- **Verdict:** `survives`
- **DB value:** 26.0%
- **PMID:** 24472261
- **Source quote:** Rapamycin at 42 ppm leads to 26% increase in median lifespan in females
- **Reason:** The text explicitly confirms that rapamycin at 42 ppm increased the median lifespan of female mice by 26%.

