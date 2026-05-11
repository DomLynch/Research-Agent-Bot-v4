"""Gate tests — pure regex, no network."""
from __future__ import annotations

from agent.claim_gates import (
    gate_anchor_role_in_prose,
    gate_citation_role,
    gate_evidence_slot,
    gate_novelty_claim,
    gate_scope_consistency,
    gate_title_claim,
    run_all_gates,
)
from agent.topic_pack import load_topic_pack

# ---------- evidence_slot --------------------------------------------------

def test_evidence_slot_passes_when_slot_present() -> None:
    s = {"ABSTRACT": "The effect is substantial [CIT:harrison-2009-rapamycin] in this corpus."}
    assert gate_evidence_slot(s) == []


def test_evidence_slot_fails_on_ungrounded_claim() -> None:
    s = {"ABSTRACT": "The effect is substantial and consistent across cohorts."}
    v = gate_evidence_slot(s)
    assert len(v) == 1
    assert v[0].gate == "evidence_slot"
    assert v[0].location == "ABSTRACT"


def test_evidence_slot_passes_pure_methodology() -> None:
    s = {"METHODS": "Studies were coded for mouse strain, sex, dose, and treatment age."}
    # No empirical claim → no slot needed
    assert gate_evidence_slot(s) == []


def test_evidence_slot_passes_planned_analysis_framing() -> None:
    s = {"ABSTRACT": "The analysis will partition between-study variance by moderator."}
    assert gate_evidence_slot(s) == []


def test_evidence_slot_passes_generic_finding_word_without_magnitude() -> None:
    # Was a false positive in iter-02: word "Findings" alone is not a result claim.
    s = {"ABSTRACT": "Findings that survive robustness checks would motivate replication."}
    assert gate_evidence_slot(s) == []


def test_evidence_slot_passes_reported_by_with_citation() -> None:
    # Was a false positive in iter-02 due to sentence splitter cutting on "et al."
    s = {
        "INTRODUCTION": (
            "The foundational mouse result reported by Harrison et al. "
            "[CIT:harrison-2009-itp] showed that rapamycin extends median lifespan."
        )
    }
    # Sentence splitter must keep this as ONE sentence, which contains [CIT:].
    assert gate_evidence_slot(s) == []


def test_evidence_slot_passes_methodological_definition() -> None:
    # "primary endpoint is operationalized as median or maximum lifespan extension"
    # is a design definition, not a result claim.
    s = {
        "METHODS": (
            "The primary endpoint is lifespan or survival, operationalized as either "
            "median or maximum lifespan extension, reported as a ratio relative to controls."
        )
    }
    assert gate_evidence_slot(s) == []


def test_evidence_slot_fires_on_increased_outcome_noun() -> None:
    # "burden" is a domain-specific outcome noun; lives in rapamycin pack, not universal core.
    pack = load_topic_pack("rapamycin")
    s = {"ABSTRACT": "Long-lived cohorts exhibit increased neoplastic burden across strains."}
    v = gate_evidence_slot(s, pack)
    assert len(v) >= 1, "increased <outcome> should trigger the gate when pack supplied"


def test_evidence_slot_fires_on_magnitude_with_compound_outcome() -> None:
    s = {"ABSTRACT": "Rapamycin produces a consistent lifespan-extending effect across strains."}
    v = gate_evidence_slot(s)
    assert len(v) >= 1, "magnitude + lifespan-extending effect should trigger"


def test_evidence_slot_passes_planned_quantification() -> None:
    # "The analysis will quantify the aggregate effect size" — design language, exempt.
    s = {"INTRODUCTION": "The analysis will quantify the aggregate effect size across outcomes."}
    assert gate_evidence_slot(s) == []


def test_evidence_slot_still_fires_when_result_lacks_planned_framing() -> None:
    # "extends lifespan in mice" uses pack-driven biomedical triggers.
    pack = load_topic_pack("rapamycin")
    s = {"INTRODUCTION": "Rapamycin extends lifespan in mice."}
    assert gate_evidence_slot(s, pack) != []


def test_evidence_slot_universal_only_passes_biomedical_phrase() -> None:
    # Without pack, biomedical-specific terms are NOT in the universal core,
    # so a biomedical-only sentence doesn't fire. This is the universality proof:
    # other domains plug in their own triggers via their topic pack.
    s = {"INTRODUCTION": "Rapamycin extends lifespan in mice."}
    assert gate_evidence_slot(s, None) == []


def test_evidence_slot_universal_catches_generic_claim() -> None:
    # Universal core still catches non-biomedical empirical patterns.
    s = {"INTRODUCTION": "Studies show a substantial effect across cohorts."}
    v = gate_evidence_slot(s, None)
    assert len(v) >= 1, "universal core should catch 'studies show substantial effect'"


def test_evidence_slot_passes_question_framing() -> None:
    # "To what extent does X extend Y" is a question, not a claim.
    s = {"ABSTRACT": "To what extent does rapamycin consistently extend lifespan across models?"}
    assert gate_evidence_slot(s) == []


def test_evidence_slot_passes_remains_unclear_framing() -> None:
    s = {"ABSTRACT": "Whether rapamycin extends lifespan in non-mammalian models remains unresolved."}
    assert gate_evidence_slot(s) == []


def test_evidence_slot_fires_on_bare_percentage_even_in_question() -> None:
    # Quantitative literals always need a slot, even inside question framing.
    s = {"ABSTRACT": "To what extent does rapamycin produce a 30% lifespan increase across cohorts?"}
    assert gate_evidence_slot(s) != []


def test_evidence_slot_passes_conditional_interpretation() -> None:
    # "would indicate substantial heterogeneity" is design language, not a result.
    s = {"INTRODUCTION": (
        "A significant random effect for study ID would indicate substantial "
        "unexplained heterogeneity in the model."
    )}
    assert gate_evidence_slot(s) == []


def test_evidence_slot_passes_analysis_aims_to_identify() -> None:
    s = {"INTRODUCTION": (
        "The analysis aims to provide a clearer map of efficacy, identifying contexts "
        "of maximal effect and those where the effect is attenuated."
    )}
    assert gate_evidence_slot(s) == []


def test_evidence_slot_accepts_multiple_slot_shapes() -> None:
    for slot in ("[CIT:foo]", "[N=42]", "[EFFECT=0.3]", "[CI=0.1-0.5]", "[N_SCREENED]",
                 "[K_STUDIES]", "[MODERATOR_P]", "[PLACEHOLDER:tbd]"):
        s = {"INTRODUCTION": f"Rapamycin extends lifespan {slot} across strains."}
        assert gate_evidence_slot(s) == [], f"slot {slot!r} should have passed"


def test_evidence_slot_skips_title() -> None:
    s = {"TITLE": "Rapamycin extends murine lifespan"}
    # Even with empirical trigger, TITLE is exempt from this gate
    assert gate_evidence_slot(s) == []


# ---------- novelty_claim --------------------------------------------------

def test_novelty_claim_fires_on_forbidden_phrases() -> None:
    for phrase in (
        "no synthesis has quantitatively aggregated the data",
        "this is the first study to evaluate moderators",
        "the field has never been evaluated",
        "full breadth of the literature",
        "definitively resolves the question",
        "comprehensively examined moderator effects",
    ):
        s = {"INTRODUCTION": phrase + "."}
        v = gate_novelty_claim(s)
        assert len(v) >= 1, f"phrase {phrase!r} should have triggered a violation"


def test_novelty_claim_passes_safer_framing() -> None:
    s = {"INTRODUCTION": (
        "Prior syntheses have identified sex and genotype heterogeneity "
        "[CIT:swindell-2017], but uncertainty remains about treatment timing."
    )}
    assert gate_novelty_claim(s) == []


# ---------- title_claim ----------------------------------------------------

def test_title_claim_fires_on_moderator_conclusion() -> None:
    bad_titles = [
        "Rapamycin Extends Murine Lifespan but Effects Diminish With Late-Onset Administration",
        "Rapamycin Only In Female Cohorts",
        "Rapamycin Fails to Extend Lifespan in Aged Mice",
        "Intervention X Is Ineffective Against Outcome Y",
        "Treatment Effects Abolished At Advanced Age",
    ]
    for t in bad_titles:
        s = {"TITLE": t}
        v = gate_title_claim(s)
        assert len(v) == 1, f"title {t!r} should have triggered title_claim"


def test_title_claim_passes_neutral_framing() -> None:
    good_titles = [
        "Rapamycin Extends Murine Lifespan With Heterogeneous Effects by Sex, Genotype, and Timing",
        "Systematic Synthesis of Intervention X Across Cohort, Dose, and Timing",
        "Heterogeneous Effects of Treatment Y in Aged Mice",
    ]
    for t in good_titles:
        s = {"TITLE": t}
        assert gate_title_claim(s) == [], f"title {t!r} should have passed"


# ---------- run_all --------------------------------------------------------

def test_run_all_gates_aggregates() -> None:
    s = {
        "TITLE": "Drug X But Effects Diminish in Subgroup Y",
        "ABSTRACT": "No synthesis has aggregated these data.",
        "INTRODUCTION": "The effect is substantial across cohorts.",
    }
    v = run_all_gates(s)
    gates_hit = {x.gate for x in v}
    assert gates_hit == {"title_claim", "novelty_claim", "evidence_slot"}


def test_run_all_gates_empty_when_clean() -> None:
    s = {
        "TITLE": "Heterogeneous Effects of Drug X by Y and Z",
        "ABSTRACT": "Prior syntheses [CIT:foo-2020] identified gaps. The analysis will test moderators.",
        "INTRODUCTION": "Earlier work [CIT:bar-2018] established the question.",
    }
    assert run_all_gates(s) == []


# ---------- novelty: seminal/groundbreaking expansions ---------------------

def test_novelty_claim_fires_on_seminal_meta_analysis() -> None:
    s = {"INTRODUCTION": "The seminal meta-analysis by Harrison et al. (2009) found rapamycin extends lifespan."}
    v = gate_novelty_claim(s)
    assert len(v) >= 1


def test_novelty_claim_fires_on_groundbreaking() -> None:
    s = {"INTRODUCTION": "This groundbreaking study revealed lifespan extension."}
    v = gate_novelty_claim(s)
    assert len(v) >= 1


# ---------- citation_role --------------------------------------------------

def test_citation_role_passes_when_no_pack_supplied() -> None:
    s = {"INTRODUCTION": "Prior work [CIT:foo-2020] established gaps."}
    assert gate_citation_role(s, None) == []


def test_citation_role_fires_on_missing_role() -> None:
    pack = load_topic_pack("rapamycin")
    s = {"INTRODUCTION": "Earlier work [CIT:harrison-2009-rapamycin] showed lifespan extension."}
    v = gate_citation_role(s, pack)
    assert len(v) == 1
    assert v[0].gate == "citation_role"
    assert "missing |role" in v[0].message


def test_citation_role_passes_when_role_correct() -> None:
    pack = load_topic_pack("rapamycin")
    s = {"INTRODUCTION": "Earlier work [CIT:harrison-2009-rapamycin|primary-study] showed lifespan extension."}
    assert gate_citation_role(s, pack) == []


def test_citation_role_fires_on_unknown_role() -> None:
    pack = load_topic_pack("rapamycin")
    s = {"INTRODUCTION": "Earlier work [CIT:foo-2020|invented-role] noted gaps."}
    v = gate_citation_role(s, pack)
    assert any("not in allowed list" in x.message for x in v)


def test_citation_role_fires_on_anchor_role_mismatch() -> None:
    # Harrison is anchor-tagged as primary-study; calling it prior-meta-analysis fails.
    pack = load_topic_pack("rapamycin")
    s = {"INTRODUCTION": "Earlier [CIT:harrison-2009-rapamycin|prior-meta-analysis] noted gaps."}
    v = gate_citation_role(s, pack)
    assert any("anchor expects role" in x.message for x in v)


# ---------- scope_consistency ----------------------------------------------

def test_scope_consistency_fires_on_discouraged_term() -> None:
    pack = load_topic_pack("rapamycin")
    s = {"INTRODUCTION": "The intervention was tested across multiple mammalian models."}
    v = gate_scope_consistency(s, pack)
    assert any("mammalian" in x.message for x in v)


def test_scope_consistency_passes_with_preferred_term() -> None:
    pack = load_topic_pack("rapamycin")
    s = {"INTRODUCTION": "The intervention was tested in murine cohorts of varied genetic background."}
    assert gate_scope_consistency(s, pack) == []


# ---------- anchor_role_in_prose -------------------------------------------

def test_anchor_role_in_prose_catches_harrison_meta_analysis_mistake() -> None:
    pack = load_topic_pack("rapamycin")
    s = {"INTRODUCTION": "The seminal meta-analysis by Harrison et al. (2009) demonstrated lifespan extension."}
    v = gate_anchor_role_in_prose(s, pack)
    assert any("Harrison" in x.message and "primary-study" in x.message for x in v)


def test_anchor_role_in_prose_passes_correct_genre() -> None:
    pack = load_topic_pack("rapamycin")
    s = {"INTRODUCTION": "The prior meta-analysis by Swindell (2017) aggregated mouse lifespan data."}
    # Swindell is the prior-meta-analysis anchor — calling it a meta-analysis is correct
    v = gate_anchor_role_in_prose(s, pack)
    assert v == []


def test_anchor_role_in_prose_skipped_without_pack() -> None:
    s = {"INTRODUCTION": "The meta-analysis by Harrison demonstrated lifespan extension."}
    assert gate_anchor_role_in_prose(s, None) == []


# ---------- compound citation handling -------------------------------------

def test_citation_role_handles_compound_bracket() -> None:
    pack = load_topic_pack("rapamycin")
    s = {"INTRODUCTION": (
        "Prior work [CIT:harrison-2009-rapamycin|primary-study; "
        "CIT:swindell-2017-meta|prior-meta-analysis] established the base evidence."
    )}
    # Both citations parse cleanly with correct roles → no violations
    assert gate_citation_role(s, pack) == []


def test_citation_role_catches_role_error_in_compound() -> None:
    pack = load_topic_pack("rapamycin")
    s = {"INTRODUCTION": (
        "[CIT:harrison-2009-rapamycin|prior-meta-analysis; "
        "CIT:swindell-2017-meta|prior-meta-analysis]"
    )}
    # Harrison wrongly tagged — should fire on Harrison only
    v = gate_citation_role(s, pack)
    assert any("harrison-2009-rapamycin" in x.message for x in v)
    assert not any("swindell-2017-meta" in x.message and "expects role" in x.message for x in v)


# ---------- how-framing question exemption ---------------------------------

def test_evidence_slot_passes_how_consistent_question() -> None:
    s = {"ABSTRACT": "How consistent is the effect of rapamycin on murine lifespan across cohorts?"}
    assert gate_evidence_slot(s) == []


# ---------- length + citation_density --------------------------------------

def test_length_gate_fires_when_section_over_cap() -> None:
    from agent.claim_gates import gate_length
    pack = load_topic_pack("rapamycin")
    s = {"ABSTRACT": "word " * 400}  # 400 words, cap 300
    v = gate_length(s, pack)
    assert any("ABSTRACT is 400 words" in x.message for x in v)


def test_length_gate_passes_when_under_cap() -> None:
    from agent.claim_gates import gate_length
    pack = load_topic_pack("rapamycin")
    s = {"ABSTRACT": "word " * 250}  # 250 words, cap 300
    assert gate_length(s, pack) == []


def test_length_gate_skipped_without_pack() -> None:
    from agent.claim_gates import gate_length
    s = {"ABSTRACT": "word " * 10000}
    assert gate_length(s, None) == []


def test_citation_density_fires_when_over_cited() -> None:
    from agent.claim_gates import gate_citation_density
    pack = load_topic_pack("rapamycin")  # min 45 words/bracket
    body = ("word " * 90) + " ".join("[CIT:foo|primary-study]" for _ in range(5))
    s = {"ABSTRACT": body}
    v = gate_citation_density(s, pack)
    assert any("ABSTRACT cites every" in x.message for x in v)


def test_citation_density_passes_when_sparse() -> None:
    from agent.claim_gates import gate_citation_density
    pack = load_topic_pack("rapamycin")
    body = ("word " * 200) + " [CIT:foo|primary-study]"
    s = {"INTRODUCTION": body}
    assert gate_citation_density(s, pack) == []
