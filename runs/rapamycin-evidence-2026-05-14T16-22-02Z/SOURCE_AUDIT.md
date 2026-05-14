# Source-fact audit — rapamycin frontier thesis #1

**Audit date:** 2026-05-14
**Auditor:** v4-curator (Claude Opus 4.7) + external auditor verification
**Status:** ⚠️ FRONTIER THESIS #1 DOES NOT SURVIVE SOURCE AUDIT

---

## The flagged claim

MiMo v2.5 Pro produced thesis #1 (opportunity score 100, novelty 82) on the
"sex × dose reversal" in rapamycin lifespan extension, citing:

- Harrison 2009 (Nature, 14 ppm ITP): **males 14% / females 9%** median lifespan
- Miller 2014 (Aging Cell, 42 ppm ITP): **females 26% / males 23%** median lifespan
- Inferred lens: "the sex×dose interaction reverses sign"

The DB facts MiMo consumed match those numbers exactly
(`runs/rapamycin-evidence-2026-05-14T16-22-02Z/all_facts.json`,
fact IDs `rapamycin/itp/harrison_2009/lifespan_{male,female}`).

## Source check against PubMed (PMID 19587680)

Direct lookup of the Harrison 2009 PubMed abstract returned:

> "rapamycin led to an increase of 14% for females and 9% for males"

and this number is attributed to **90th-percentile mortality**, not median
lifespan. The abstract notes "rapamycin extends median and maximal lifespan
of both male and female mice" without giving sex-stratified median percentages.

## Two errors in the Researka DB curation

1. **Sex flip.** The 14% applies to **females**, the 9% to **males** — opposite
   of what `rapamycin/itp/harrison_2009/lifespan_male` (14%) and
   `rapamycin/itp/harrison_2009/lifespan_female` (9%) record.
2. **Metric mislabeled.** The 14% / 9% are 90th-percentile mortality reductions,
   not median lifespan extensions. The DB tagged both as `claim_type=effect_size`
   in `sub_topic=lifespan` with no metric-type discriminator.

Curator id (`validator` field): `bootstrap-claude-opus-4-7-2026-05-09`.

## Effect on the frontier thesis

With the corrected values:
| Study | Dose (ppm) | Female | Male |
|---|---|---|---|
| Harrison 2009 (90th-percentile) | 14 | **14%** | **9%** |
| Miller 2014 (median) | 42 | 26% | 23% |

Females benefit more at **both** doses. **No sex×dose reversal.** The thesis
collapses on source audit.

## Salvageable elements that DO survive

Even with thesis #1 invalid, the other parts of the frontier review remain
worth keeping:

- The transient-vs-continuous dosing gap is still real: Bitto 2016 transient
  C57BL/6 ~60% vs Miller 2014 continuous UM-HET3 23–26%, confounded by strain,
  route, and protocol. This is thesis #2 in the review (opportunity 39).
- The Mannick 2014 RAD001 immune-rejuvenation translational bridge is still
  valid for thesis #3 (opportunity 54).
- The "next extractions" list (rapamycin blood levels by sex, body weight /
  metabolic phenotype, S6K1 / 4E-BP1 by sex) remains useful regardless of
  whether the reversal exists.

## Recommended action

1. **Researka DB**: file a correction issue for fact IDs
   `rapamycin/itp/harrison_2009/lifespan_male` and
   `rapamycin/itp/harrison_2009/lifespan_female` — swap the values and tag
   the metric as `90th_percentile_mortality_reduction`, not lifespan
   extension.
2. **v4 architecture**: build the source-audit layer the external auditor
   recommended. Pipeline:
   `frontier_review → source_audit → survives | dies | needs_extraction`.
   Each MiMo-claimed numeric or directional finding cross-checked against
   the source paper abstract / public record before being elevated to a
   publishable thesis.
3. **This run**: thesis #1 demoted from opportunity 100 → "audit-failed,
   do not surface as Researka top-5".

---

This is exactly the kind of self-correction the deterministic + frontier
+ audit pipeline is supposed to surface. The fact that the auditor caught
this on the first stress-test confirms the architecture is right, and the
source-audit layer is the next product capability.
