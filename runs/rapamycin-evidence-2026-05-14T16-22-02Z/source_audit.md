# Source-fact audit — rapamycin

**Snapshot:** 2026-05-14T16-22-02Z
**Facts inspected:** 7
**Survives:** 0   **Dies:** 2   **Needs extraction:** 5

Verdicts come from Gemma (judge model, temperature 0.0) comparing each fact's DB-stored value + subgroup attribution against the source paper's PubMed abstract. `dies` means the abstract contradicts the DB claim (wrong number, wrong subgroup, or wrong metric). `needs_extraction` means the abstract did not discuss the value directly.

---

## [?] rapamycin/transient/bitto_2016/lifespan_extension

- **Verdict:** `needs_extraction`
- **DB value:** 60.0%
- **PMID:** 27549339
- **Source quote:** Here we show that 3 months of rapamycin treatment is sufficient to increase life expectancy by up to 60% and improve measures of healthspan in middle-aged mice.
- **Reason:** While the abstract mentions a 60% increase in life expectancy for middle-aged mice, it does not specify the mouse strain (C57BL/6), the starting age (20 months), or the specific dose (8 mg/kg/day i.p.) required to verify the claim's precision.

---

## [?] rapamycin/transient/bitto_2016/lifespan_male

- **Verdict:** `needs_extraction`
- **DB value:** 52.0%
- **PMID:** 27549339
- **Source quote:** 3 months of rapamycin treatment is sufficient to increase life expectancy by up to 60% and improve measures of healthspan in middle-aged mice
- **Reason:** The abstract mentions an increase 'up to 60%' but does not specify the 52% value, the median lifespan metric, the specific dose (8 mg/kg/day), or the male-only subgroup.

---

## [FAIL] rapamycin/itp/harrison_2009/lifespan_female

- **Verdict:** `dies`
- **DB value:** 9.0%
- **PMID:** 19587680
- **Source quote:** On the basis of age at 90% mortality, rapamycin led to an increase of 14% for females and 9% for males.
- **Reason:** The 9% increase is attributed to males, not females, and refers to the age at 90% mortality rather than median lifespan.

---

## [FAIL] rapamycin/itp/harrison_2009/lifespan_male

- **Verdict:** `dies`
- **DB value:** 14.0%
- **PMID:** 19587680
- **Source quote:** On the basis of age at 90% mortality, rapamycin led to an increase of 14% for females and 9% for males.
- **Reason:** The abstract attributes the 14% increase to females, not males, and specifies the metric as 'age at 90% mortality' rather than 'median lifespan'.

---

## [?] rapamycin/immune/mannick_2014/influenza_vaccine_response

- **Verdict:** `needs_extraction`
- **DB value:** 20.0%
- **PMID:** 25540326
- **Source quote:** RAD001 enhanced the response to the influenza vaccine by about 20% at doses that were relatively well tolerated.
- **Reason:** While the abstract supports the 20% improvement and the intervention, it does not specify the population size (n=218) or the specific dosing regimens (0.5 mg daily, 5 mg weekly, or 20 mg weekly), which require extraction from the full text.

---

## [?] rapamycin/itp/miller_2014/dose_response_high_male

- **Verdict:** `needs_extraction`
- **DB value:** 23.0%
- **PMID:** 24472261
- **Source quote:** _none_
- **Reason:** The provided abstract is about infliximab for rheumatoid arthritis in humans and does not mention rapamycin, mice, or lifespan.

---

## [?] rapamycin/itp/miller_2014/dose_response_high_female

- **Verdict:** `needs_extraction`
- **DB value:** 26.0%
- **PMID:** 24472261
- **Source quote:** _none_
- **Reason:** The provided abstract is about infliximab dose optimization in rheumatoid arthritis patients and does not mention rapamycin or mouse lifespan.

