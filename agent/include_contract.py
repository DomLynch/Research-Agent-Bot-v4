"""Sprint 7.8 - Include Contract (post-merge "supreme court").

The Pass-3 deterministic merge produces draft include / exclude / unclear
verdicts. This module re-checks each include against hard rules that the
merge cannot enforce on field-flag arithmetic alone:

  1. parsed_text_adequate must be True (the rule already tracks this but
     does not gate; iter-15 surfaced s237 with char_count=54 sneaking
     through because parsed_text_adequate is not in MANDATORY_KEYS).
  2. char_count >= MIN_CHARS (default 5000).
  3. >= MIN_EVIDENCE_QUOTES non-title-duplicate evidence quotes.
  4. At least one evidence quote contains a topic-pack endpoint term
     (survival / lifespan / hazard / etc.) - prevents includes whose
     only quote is the title.
  5. At least one evidence quote contains a topic-pack intervention or
     control term - prevents includes where the judge never saw a
     methods passage.

Any include that fails any rule is demoted to 'unclear' with the
violations recorded in the receipt's reason.

Lane classification (A/B/C/D/E) is also computed here so the QA report
can split the primary-pool candidates from secondary/context studies.

Universal: every keyword list is topic-pack-driven; no biomedical
literals in this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent.screening import EligibilityReceipt, ParsedFullTextReceipt
from agent.topic_pack import TopicPack

Lane = Literal["A_direct_lifespan", "B_disease_model_survival",
               "C_secondary_molecular", "D_review_background", "E_exclude"]

MIN_CHARS = 5_000
MIN_EVIDENCE_QUOTES = 2

# Lane heuristics - title-keyword sets. Topic-pack-driven where possible;
# universal fallback when not.
_SECONDARY_MOLECULAR_TITLE_TERMS = (
    "proteom", "transcriptom", "metabolom", "lipidom", "epigenetic",
    "methylation", "methylome", "unsupervised", "principles",
    "dirac", "network", "signatures", "biomarker", "atlas",
)
_DISEASE_MODEL_TITLE_TERMS = (
    "cancer", "tumor", "tumour", "diabet", "alzheimer", "parkinson",
    "huntington", "model of", "disease model", "irradiation",
    "knockout", "mutant", "transgenic", "deficien",
)
_REVIEW_TITLE_TERMS = (
    "review", "meta-analysis", "commentary", "editorial",
    "perspective", "primer", "overview", "translational review",
)


@dataclass(frozen=True, slots=True)
class ContractResult:
    passes: bool
    violations: tuple[str, ...]


def _quote_has_term(quote: str, terms: tuple[str, ...]) -> bool:
    q = quote.casefold()
    return any(t.casefold() in q for t in terms if t)


def _is_title_quote(quote: str, title: str) -> bool:
    """Heuristic: quote is just the title (with trivial punctuation diffs)."""
    norm_q = "".join(c for c in quote.casefold() if c.isalnum())
    norm_t = "".join(c for c in title.casefold() if c.isalnum())
    return bool(norm_t) and (norm_q == norm_t or norm_q == norm_t[:len(norm_q)])


def validate_include(
    receipt: EligibilityReceipt,
    parsed: ParsedFullTextReceipt | None,
    candidate_title: str,
    pack: TopicPack,
) -> ContractResult:
    """Re-check an include verdict against the universal evidence
    contract. Returns ContractResult(passes=False, violations=...) for
    any fail; the caller is expected to demote the receipt to unclear if
    passes is False.

    Sprint 7.11.1: NO manual-override bypass. Every primary-pool include
    must pass the same universal contract — sentinels included. A human
    reviewer cannot launder unresolved evidence into the primary corpus;
    they can only resolve sentinel STATUS via the manual_resolution
    overlay channel (see agent/manual_resolution.py).
    """
    if receipt.decision != "include":
        return ContractResult(passes=True, violations=())
    violations: list[str] = []
    if not receipt.mandatory_fields.get("parsed_text_adequate", False):
        violations.append("parsed_text_adequate=False")
    char_count = parsed.char_count if parsed else 0
    if char_count < MIN_CHARS:
        violations.append(f"char_count {char_count} < {MIN_CHARS}")
    quotes = receipt.evidence_quotes
    non_title_quotes = tuple(q for q in quotes if not _is_title_quote(q, candidate_title))
    if len(non_title_quotes) < MIN_EVIDENCE_QUOTES:
        violations.append(
            f"only {len(non_title_quotes)} non-title evidence quote(s); "
            f"need >= {MIN_EVIDENCE_QUOTES}"
        )
    endpoint_terms = pack.eligibility_endpoint_terms
    if endpoint_terms and not any(_quote_has_term(q, endpoint_terms) for q in quotes):
        violations.append("no evidence quote contains a pre-specified endpoint term")
    methods_terms = pack.primary_interventions + pack.eligibility_control_terms
    if methods_terms and not any(_quote_has_term(q, methods_terms) for q in quotes):
        violations.append("no evidence quote contains intervention or control term")
    return ContractResult(passes=not violations, violations=tuple(violations))


def strict_a_core_check(
    decision: str,
    evidence_quotes: tuple[str, ...],
    pack: TopicPack,
) -> tuple[bool, tuple[str, ...]]:
    """Per-quote evidence audit for the A-core primary pool.

    A paper earns A-core only if its evidence quotes affirmatively
    demonstrate the CURRENT EXPERIMENT (not background or prior
    literature) used:
      - preferred species (mouse/murine)
      - primary intervention (rapamycin/sirolimus)
      - control arm
      - lifespan/survival endpoint
    Demote triggers:
      - any quote mentions only non-mouse species terms without a
        matching mouse term in the same quote (e.g. 'rapamycin
        extended C. elegans lifespan' but no mouse quote elsewhere)
      - any quote contains an omics/secondary-analysis marker that
        signals the paper is a downstream profile, not a primary
        lifespan study

    Returns (passes, demote_reasons). Caller routes failures to
    C_secondary_molecular instead of A_direct_lifespan."""
    if decision != "include":
        return False, ("decision != include",)
    quotes = tuple(q.casefold() for q in evidence_quotes)

    def _any(terms: tuple[str, ...]) -> bool:
        return any(any(t.casefold() in q for t in terms if t) for q in quotes)

    has_mouse = _any(pack.preferred_terms)
    has_intervention = _any(pack.primary_interventions)
    has_control = _any(pack.eligibility_control_terms)
    has_endpoint = _any(pack.eligibility_endpoint_terms)
    has_non_mouse = _any(pack.non_mouse_species_terms)
    has_secondary_marker = _any(pack.secondary_design_quote_markers)

    reasons: list[str] = []
    if not has_mouse:
        reasons.append("no quote names a mouse term")
    if not has_intervention:
        reasons.append("no quote names a primary intervention term")
    if not has_control:
        reasons.append("no quote names a control term")
    if not has_endpoint:
        reasons.append("no quote names a lifespan/survival term")
    if has_non_mouse and not has_mouse:
        reasons.append("quotes mention only non-mouse species")
    if has_secondary_marker:
        reasons.append("quotes signal secondary/omics design")

    return not reasons, tuple(reasons)


def has_genotype_modified_strain(
    evidence_quotes: tuple[str, ...], pack: TopicPack,
) -> bool:
    """True if any quote mentions a genotype-modified-strain marker.

    Used by freeze_primary_set to route demoted-from-A_core studies into
    the B_disease_model_survival sensitivity lane (preserving their
    inferential value) rather than C_secondary_contextual (which is for
    omics / off-design demotions). Universal: marker list lives in the
    topic pack under [strict_a_core] genotype_modified_strain_markers.
    """
    markers = pack.genotype_modified_strain_markers
    if not markers:
        return False
    quotes = tuple(q.casefold() for q in evidence_quotes)
    return any(
        any(m.casefold() in q for m in markers if m) for q in quotes
    )


def classify_lane(
    candidate_title: str, parsed_char_count: int,
    decision: str | None, pack: TopicPack,
) -> Lane:
    """Assign a corpus lane based on title heuristics + decision string.
    Lanes are mutually exclusive and ordered by primary-pool priority.

    Hard gates (checked before title heuristics):
      - decision in {exclude, unclear}   -> E
      - parsed_char_count < MIN_CHARS    -> E (prevents 54-char "parses"
        from landing in any primary lane via a title-keyword match)

    Title heuristics (in priority order):
      - review/meta-analysis terms       -> D
      - secondary-molecular markers      -> C
      - disease-model markers            -> B
      - default for confirmed includes   -> A
    """
    if decision in {"exclude", "unclear"}:
        return "E_exclude"
    if parsed_char_count < MIN_CHARS:
        return "E_exclude"
    title = (candidate_title or "").casefold()
    if any(t in title for t in _REVIEW_TITLE_TERMS):
        return "D_review_background"
    if any(t in title for t in _SECONDARY_MOLECULAR_TITLE_TERMS):
        return "C_secondary_molecular"
    if any(t in title for t in _DISEASE_MODEL_TITLE_TERMS):
        return "B_disease_model_survival"
    if decision == "include":
        return "A_direct_lifespan"
    return "E_exclude"


def demote_failed_includes(
    receipts: tuple[EligibilityReceipt, ...],
    parsed_by_id: dict[str, ParsedFullTextReceipt],
    titles_by_id: dict[str, str],
    pack: TopicPack,
) -> tuple[tuple[EligibilityReceipt, ...], dict[str, ContractResult]]:
    """Apply the contract to every include. Return (new_receipts, results).
    Any failing include is rebuilt with decision='unclear' and reason that
    names the contract violations."""
    results: dict[str, ContractResult] = {}
    new_receipts: list[EligibilityReceipt] = []
    for r in receipts:
        parsed = parsed_by_id.get(r.study_id)
        title = titles_by_id.get(r.study_id, "")
        res = validate_include(r, parsed, title, pack)
        results[r.study_id] = res
        if r.decision == "include" and not res.passes:
            new_receipts.append(
                EligibilityReceipt(
                    study_id=r.study_id, decision="unclear",
                    reason=(
                        "include_contract failed: " + "; ".join(res.violations)
                    ),
                    reviewer="include-contract",
                    confidence=r.confidence,
                    mandatory_fields=r.mandatory_fields,
                    evidence_quotes=r.evidence_quotes,
                    judge_model=r.judge_model,
                    rule_decision=r.rule_decision,
                    source_text_hash=r.source_text_hash,
                    timestamp_utc=r.timestamp_utc,
                )
            )
        else:
            new_receipts.append(r)
    return tuple(new_receipts), results
