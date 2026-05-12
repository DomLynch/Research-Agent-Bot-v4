# Manual Review Queue - latest

4 receipts flagged 'unclear' by the rule -> judge -> deterministic merge. Sorted by study_id.

### s069 - Intermittent rapamycin feeding recapitulates some effects of continuous treatment while maintaining...
- year: 2024  venue: Molecular metabolism
- doi: 10.1016/j.molmet.2024.101902  pmid: 38360109
- confidence: 0.10
- rule_decision: unclear  reviewer: llm-judge
- missing mandatory: parsed_text_adequate, control_present, species_match, rapalog_only_intervention, combination_only_no_isolated_arm
- merge reason: low judge confidence 0.10; missing mandatory: species_match, control_present
- evidence quotes (first 3):
    - (none)

### s086 - Rapamycin fed late in life extends lifespan in genetically heterogeneous mice.
- year: 2009  venue: Nature
- doi: 10.1038/nature08221  pmid: 19587680
- confidence: 0.00
- rule_decision: unclear  reviewer: llm-judge
- missing mandatory: control_present, rapalog_only_intervention, combination_only_no_isolated_arm
- merge reason: low judge confidence 0.00; missing mandatory: control_present
- evidence quotes (first 3):
    - (none)

### s243 - Rapamycin extends life span of Rb1+/- mice by inhibiting neuroendocrine tumors.
- year: 2013  venue: Aging
- doi: 10.18632/aging.100533  pmid: 23454836
- confidence: 1.00
- rule_decision: eligible_likely  reviewer: include-contract
- missing mandatory: rapalog_only_intervention, combination_only_no_isolated_arm
- merge reason: include_contract failed: no evidence quote contains a pre-specified endpoint term
- evidence quotes (first 3):
    - Beginning at 9 weeks of age until death, we fed Rb1 +/− mice a diet without or with eRapa at 14 mg/kg food, which results in an approximate dose of 2.24 mg/kg body weight per day
    - The Eudragit control-fed mice had a shorter mean life span than the eRapa-fed cohort for both females (377.5 versus 411 days) and males (mean age is 368.8 versus 419.8 days).

### s244 - Rapamycin doses sufficient to extend lifespan do not compromise muscle mitochondrial content or end...
- year: 2013  venue: Aging
- doi: 10.18632/aging.100576  pmid: 23929887
- confidence: 1.00
- rule_decision: eligible_likely  reviewer: include-contract
- missing mandatory: rapalog_only_intervention, combination_only_no_isolated_arm
- merge reason: include_contract failed: no evidence quote contains a pre-specified endpoint term
- evidence quotes (first 3):
    - Rapamycin treatment (2 mg/kg daily by intraperitoneal injection) decreased the mRNA expression of genes involved in mitochondrial biogenesis
    - rapamycin-treated mice had endurance equivalent to that of untreated controls
