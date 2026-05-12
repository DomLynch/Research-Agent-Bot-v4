"""Writer prompts.

One module = all prompts. Topic-agnostic core prompt + topic-pack injection
for scope and citation-role registry (universal-no-hardcoding rule). Each
function returns the OpenAI-style messages list ready for `call_writer`.

The prompt enforces a **pre-results systematic review** stance:
the writer drafts the manuscript before the dataset is assembled, so every
empirical sentence must reference a structured evidence slot rather than
asserting a finished result. Prior syntheses must be acknowledged, never
erased.
"""
from __future__ import annotations

from agent.topic_pack import TopicPack

SYSTEM_WRITER = """You are an expert academic journal writer producing AAA-grade research-paper prose. Voice: calibrated, sober, third-person, present-tense for established mechanisms and past-tense for prior studies. No marketing language. No hedge stacking. No filler.

LENGTH DISCIPLINE: section word counts in the user request are HARD CEILINGS. A section that exceeds its cap fails the length gate. If you produce too much, ruthlessly compress — every sentence must earn its place. Compression should remove qualifying phrases, redundant transitions, and clauses that restate the previous sentence, NOT remove substantive content or citations.

HOSTAGE-TO-FACT PHRASING: avoid claims about what prior work has NOT done in absolute terms ("neither jointly modeled", "no synthesis has examined"). Frame the contribution positively: "Prior syntheses have not provided a fully powered, pre-specified joint moderator framework for X; the present work supplies that." Same content, smaller risk of being contradicted by a reviewer who knows a paper you missed.

FUTURE OUTCOMES: when describing what the planned analysis will produce, prefer "is designed to estimate / map / quantify" over "will identify / will reveal / will demonstrate". The former describes intent; the latter promises a result.

Hard rules:
1. Produce ONLY the requested sections in the requested order.
2. NEVER invent citation identifiers. Use the placeholder format [CIT:<short-keyword>] inline wherever a citation belongs (format example: [CIT:firstauthor-year-keyword]). These are resolved at compile time from the retrieval set. The exact anchor keys for the current topic are listed in the topic-pack block below.
3. EVIDENCE SLOTS ARE MANDATORY. Any sentence that asserts a quantitative result, an effect direction, or a moderator finding — INCLUDING topic sentences that open a paragraph and summary sentences that synthesize prior work ("Collectively, prior work shows …", "Treatment X reliably increases outcome Y …", "Policy P consistently lowers metric M …") — must contain at least one structured slot of the form [CIT:...], [N=...], [EFFECT=...], [CI=...], [MODEL=...], [PLACEHOLDER:...], or domain-neutral equivalents such as [K_STUDIES], [N_SCREENED], [N_ACCEPTED], [MODERATOR_P]. If a specific number is not known, use the slot, never invent. Multiple citations on the same claim go in SEPARATE bracket pairs separated by a space: `[CIT:author1-year|role] [CIT:author2-year|role]` — NOT compound brackets like `[CIT:foo; CIT:bar]`.
4. PRE-RESULTS MANUSCRIPT. This draft is written BEFORE the analysis runs. Frame contributions as the planned analysis, not as completed findings. Use future or conditional tense where the result would be reported ("The analysis will partition variance by …", "Mixed-effects models are specified to test …"). Do not state aggregate effect sizes, moderator outcomes, or sub-group differences as facts.
5. NEVER erase prior literature. If your training knowledge contains prior meta-analyses, systematic reviews, or quantitative syntheses on this topic, you MUST acknowledge them by author + year + [CIT:author-year-keyword] placeholder. Position THIS work as extending, refining, or stress-testing prior syntheses — never as the first.
6. FORBIDDEN NOVELTY PHRASES (will fail a downstream contract gate):
   "no synthesis has", "no prior synthesis", "first study to", "first to evaluate",
   "never been evaluated", "never previously", "full breadth", "definitively",
   "comprehensively examined", "comprehensive aggregation", "no comprehensive review".
   Use neutral framings instead: "Prior syntheses have identified … but uncertainty remains about …", "Existing meta-analyses have addressed X; this work extends to Y."
7. AVOID anaphoric reference sentences ("That work …", "This study …", "These findings …") that summarize a cited claim without their own inline [CIT:]. Either repeat the [CIT:] anchor inside the summary sentence or merge it with the originally citing sentence.
8. NEVER write scaffold language ("this paper will discuss", "in this section we explore", "as we will see below"). Produce the actual prose, not meta-commentary about the paper.
9. NEVER use Markdown headers inside section bodies. Separate sections only with a header line `===<NAME>===` followed by a blank line.
10. UNIVERSAL: this prompt must produce sound output for any research domain (biomedical, climate, materials, economics, social science). Avoid framings that only fit one domain.
"""


def _user_request(topic: str, section_specs: list[tuple[str, str]]) -> str:
    parts = ["Topic: " + topic, "", "Produce the following sections, in order:", ""]
    for name, spec in section_specs:
        parts.append(f"=== {name} ===")
        parts.append(spec)
        parts.append("")
    parts.append(
        "Output format: for each section, emit a header line `===<NAME>===` "
        "(exactly), then a blank line, then the prose. Separate sections with "
        "a single blank line. No other formatting."
    )
    return "\n".join(parts)


def _topic_pack_block(pack: TopicPack) -> str:
    """Render the topic-pack-driven constraints as a system-prompt addendum."""
    parts: list[str] = ["TOPIC-PACK CONSTRAINTS (must follow; downstream gates enforce):"]
    if pack.preferred_terms:
        parts.append(
            f"- Scope vocabulary: USE these terms — {', '.join(pack.preferred_terms)}."
        )
    if pack.discouraged_terms:
        parts.append(
            f"- Scope vocabulary: AVOID these terms (scope_consistency gate fires) — "
            f"{', '.join(pack.discouraged_terms)}."
        )
    if pack.endpoint:
        parts.append(f"- Primary endpoint: {pack.endpoint}.")
    if pack.primary_interventions:
        parts.append(
            f"- PRIMARY corpus interventions (eligible for pooled analysis): "
            f"{', '.join(pack.primary_interventions)}."
        )
    if pack.translational_only_interventions:
        parts.append(
            f"- TRANSLATIONAL-ONLY interventions (excluded from primary pooled "
            f"analysis; retained only for translational sensitivity layer or "
            f"discussion): {', '.join(pack.translational_only_interventions)}."
        )
    if pack.length_caps:
        cap_str = ", ".join(f"{k}={v}w" for k, v in sorted(pack.length_caps.items()))
        parts.append(f"- Length caps (length gate fires above): {cap_str}.")
    if pack.min_words_per_citation > 0:
        parts.append(
            f"- Citation density: minimum {pack.min_words_per_citation} words per "
            "[CIT:] bracket (citation_density gate fires below)."
        )
    if pack.cite_roles_allowed:
        parts.append(
            "- CITATION FORMAT: every citation MUST be [CIT:<key>|<role>]. The role "
            "is mandatory."
        )
        parts.append(f"  Allowed roles: {', '.join(pack.cite_roles_allowed)}.")
        parts.append(
            "  Choose the role that matches what the cited work IS — a primary "
            "experiment is 'primary-study', a meta-analysis is "
            "'prior-meta-analysis', a mechanism overview is 'mechanism-review', "
            "and so on. Mismatched roles fail the citation_role gate."
        )
    if pack.anchors:
        parts.append(
            "- ANCHOR CITATIONS (use these exact citation keys with the listed "
            "role; describe each work consistently with its role — e.g. do NOT "
            "call a primary-study a 'meta-analysis'):"
        )
        for key, role in sorted(pack.anchors.items()):
            parts.append(f"    [CIT:{key}|{role}]")
    return "\n".join(parts)


def writer_methods(
    topic: str, pack: TopicPack | None = None
) -> list[dict[str, str]]:
    """Section 2: produce Methods only.

    Universal structure: search strategy, eligibility, extraction, moderator
    coding, quality assessment, statistical synthesis, sensitivity analyses,
    tension-matrix construction. Topic-pack injects scope vocabulary, the
    moderator list, length caps, primary vs translational-only interventions,
    and method-citation anchors. The prompt is domain-agnostic: it instructs
    the writer to select the framework appropriate to the study designs in
    scope (animal vs human RCT vs observational vs non-clinical), citing the
    anchor that matches.
    """
    specs = [
        (
            "METHODS",
            "800-1,200 words. Write an implemented-protocol Methods section "
            "as ordered paragraphs (no markdown headers), one paragraph per "
            "component below. Each paragraph must contain at least one "
            "[CIT:<method-key>|method-citation] anchor drawn from the topic "
            "pack's anchor list (shown in the TOPIC-PACK CONSTRAINTS block "
            "above), OR a [PLACEHOLDER:...] slot when the operational detail "
            "is not yet pinned. Use planned-analysis voice ('will be', 'is "
            "designed to', 'pre-specifies') throughout — no retrospective "
            "claims. The prompt is DOMAIN-NEUTRAL: select the right tool for "
            "the topic and the study designs in scope; the topic-pack anchors "
            "are the only source of specific method-citation keys.\n\n"
            "FORBIDDEN OVERCLAIMS (must not appear unless the user has "
            "explicitly provided a registration record in TOPIC-PACK "
            "CONSTRAINTS):\n"
            "- Do NOT claim the protocol is registered in PROSPERO, OSF, or "
            "  any other registry.\n"
            "- Do NOT claim dual-reviewer extraction, dual-reviewer risk-of-"
            "  bias adjudication, or third-reviewer arbitration — those are "
            "  operational facts about a team you do not have. Use planned-"
            "  protocol voice ('will be extracted', 'will be assessed') "
            "  without naming staffing.\n"
            "- Do NOT claim a search has been executed or a date range "
            "  finalised; describe the search strategy in planning voice and "
            "  leave dates / databases as [PLACEHOLDER:...] until the "
            "  retrieval step has filled them in.\n"
            "If the topic pack contains a key named 'registration_id' in its "
            "method-citation anchors, you may cite it; otherwise the protocol "
            "is implemented in this pipeline only and must be described as "
            "such ('this synthesis was implemented using a reproducible "
            "evidence-contract pipeline and is reported against PRISMA 2020 "
            "where applicable').\n\n"
            "Components, in order:\n"
            "1. SEARCH STRATEGY — databases that will be queried, search-date "
            "range, query-term shape. Cite the topic-pack-supplied reporting "
            "framework appropriate to the domain. Use [PLACEHOLDER:databases], "
            "[PLACEHOLDER:date-range], [PLACEHOLDER:query-terms] when not pinned.\n"
            "2. ELIGIBILITY — inclusion and exclusion criteria framed in "
            "PICO/PECO terms appropriate to the domain. If the topic pack "
            "lists PRIMARY interventions, the eligibility statement must "
            "restrict the primary pooled corpus to those names. If the topic "
            "pack lists TRANSLATIONAL-ONLY interventions, they are explicitly "
            "excluded from the primary pooled analysis and are retained only "
            "for a pre-specified translational sensitivity layer. Scope "
            "vocabulary must match the topic pack's preferred_terms exactly "
            "(do not broaden, e.g. from a specific subject term to a parent "
            "category).\n"
            "3. DATA EXTRACTION — variables extracted from each included "
            "study; independent dual extraction; disagreement-resolution "
            "rule. Variables should be extracted in their ORIGINAL reported "
            "units; any categorization is pre-specified and accompanied by "
            "explicit conversion-assumption justification, with original-unit "
            "sensitivity checks to avoid artificial precision.\n"
            "4. MODERATOR CODING — the pre-specified moderators (drawn from "
            "topic-pack scope), their levels, and the rationale for each. "
            "Use [MODERATOR_P:<name>] for each. Do NOT introduce arbitrary "
            "numeric thresholds (e.g. arbitrary dose / concentration / "
            "magnitude breakpoints); use original-unit extraction with "
            "post-hoc category sensitivity.\n"
            "5. RISK-OF-BIAS / QUALITY — select the bias-assessment framework "
            "appropriate to the study designs in scope, citing the matching "
            "topic-pack method-citation anchor. The choice must match the "
            "designs the topic actually covers — different anchors apply to "
            "animal-intervention studies, human RCTs, non-randomized "
            "observational designs, and non-clinical empirical work. State "
            "the arbitration rule for discordant assessments.\n"
            "6. STATISTICAL SYNTHESIS — multi-level mixed-effects "
            "meta-regression specification: random-effects structure "
            "(study-ID, outcome-within-study), fixed-effects predictors "
            "(the coded moderators), variance estimator, degrees-of-freedom "
            "correction, and software / package. Cite the topic-pack-supplied "
            "method-citation anchors for each component (estimator, software, "
            "small-sample adjustment).\n"
            "7. SENSITIVITY ANALYSES — leave-one-out, influence diagnostics, "
            "publication-bias diagnostics, and heterogeneity quantification. "
            "Cite the topic-pack method anchors for each diagnostic. If the "
            "topic pack lists translational-only interventions, the "
            "sensitivity layer must include a translational evidence map "
            "that examines analog evidence at appropriate endpoints WITHOUT "
            "pooling it with the primary corpus.\n"
            "8. TENSION-MATRIX CONSTRUCTION — how moderator combinations "
            "define cells, which cells are plotted, how sparsely-populated "
            "cells are flagged, and how the matrix feeds back into the "
            "moderator interpretation and future-study recommendations.",
        ),
    ]
    system = SYSTEM_WRITER
    if pack:
        system = SYSTEM_WRITER + "\n\n" + _topic_pack_block(pack)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": _user_request(topic, specs)},
    ]


def writer_title_abstract_intro(
    topic: str, pack: TopicPack | None = None
) -> list[dict[str, str]]:
    """Iteration prompt: produce Title + Abstract + Introduction only (pre-results).

    FORBIDDEN OVERCLAIMS apply to every sub-section in this prompt and the
    writer_methods prompt: no claim of formal registration (PROSPERO, OSF,
    etc.) and no claim of dual-reviewer / third-reviewer staffing unless
    the topic pack supplies a registration_id anchor. Honest wording for
    this pipeline is "implemented-protocol" / "reproducible-pipeline" /
    "this synthesis uses an automated extraction pipeline".
    """
    specs = [
        (
            "TITLE",
            "One line, no period, at most 15 words. The title must NOT assert a "
            "moderator-specific conclusion (e.g. 'but Effects Diminish With X', "
            "'only when Y', 'fails to Z') because the analysis has not yet run. "
            "Use neutral, design-descriptive framing such as 'Heterogeneous Effects "
            "of X by Y, Z, and Treatment Timing' or 'Systematic Synthesis of X "
            "Across Y'. Reject generic 'a review of …' framings. Do NOT use the "
            "word 'pre-registered' or 'registered'.",
        ),
        (
            "ABSTRACT",
            "250-300 words total, unlabeled paragraphs covering, in order: "
            "(1) the precise research question. Open with an EXPLICIT interrogative "
            "framing ('How consistent is the effect of X on Y across …?', 'To what "
            "extent does …?'). Do NOT open with an implicit empirical assertion like "
            "'X consistently extends Y' — that triggers the evidence-slot gate. "
            "Briefly note why prior syntheses leave the question open; cite them with "
            "[CIT:]. "
            "(2) corpus shape and screening counts as bracketed placeholders "
            "([N_SCREENED]/[N_ACCEPTED]/[K_STUDIES]) — do not invent counts; "
            "(3) the planned analysis (mixed-effects models, moderator tests, "
            "tension matrix), NOT aggregate findings; "
            "(4) the design's pre-specified boundary conditions to interrogate "
            "(e.g. sex x strain x dose x timing) — framed as questions, not answers; "
            "(5) the next-study implication that would strengthen or refute findings "
            "produced by the planned analysis. Do NOT state aggregate effect sizes "
            "or moderator outcomes; use slots or pre-results framing throughout.",
        ),
        (
            "INTRODUCTION",
            "HARD FLOOR: 800 words minimum. HARD CEILING: 1,000 words. Across 4-6 "
            "paragraphs covering: (a) significance of the research question; (b) the "
            "prior synthesis landscape and its specific gaps — prior meta-analyses "
            "MUST be named by author + year + [CIT:] and their contribution "
            "acknowledged, never erased; (c) the contribution of THIS paper distinct "
            "from prior syntheses (extension, refinement, or stress-test); (d) scope "
            "and explicit non-goals. Cite prior work with [CIT:<keyword>] placeholders. "
            "Every empirical sentence — INCLUDING paragraph topic sentences and "
            "between-paragraph summary sentences — must contain at least one [CIT:] "
            "or other structured slot. If you produce less than 800 words for the "
            "Introduction, expand with additional landscape detail, additional "
            "moderator-specific gap analysis, and additional non-goals.",
        ),
    ]
    system = SYSTEM_WRITER
    if pack:
        system = SYSTEM_WRITER + "\n\n" + _topic_pack_block(pack)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": _user_request(topic, specs)},
    ]
