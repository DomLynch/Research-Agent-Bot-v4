"""Sprint 23 — universal topic maturity router.

Maps a ReadinessReport (Sprint 16) to a recommended paper-type with
explicit section list + claim restrictions. The router prevents the
"k=1 paper claiming meta-analytic certainty" failure mode by tying
the output prose contract to the evidence ladder.

Universal: thresholds read count fields only; no domain literals.
The paper-type catalog is canonical across disciplines.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.readiness import ReadinessReport


@dataclass(frozen=True, slots=True)
class PaperType:
    name: str
    rationale: str
    recommended_sections: tuple[str, ...]
    forbidden_claims: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name, "rationale": self.rationale,
            "recommended_sections": list(self.recommended_sections),
            "forbidden_claims": list(self.forbidden_claims),
        }


# Canonical section sets per paper type. Every project that ships
# evidence gets at least Title / Abstract / Methods / Discussion;
# Results scales with k. Forbidden_claims are explicit "you must not
# write X" guardrails for the writer prompt.

_SECTIONS_CORPUS_SNAPSHOT: tuple[str, ...] = (
    "Title", "Abstract", "Background", "Methods", "Corpus Snapshot",
    "Discussion", "Limitations",
)
_SECTIONS_EVIDENCE_GAP: tuple[str, ...] = (
    "Title", "Abstract", "Introduction", "Methods", "Evidence Gap",
    "Discussion", "Limitations", "Future Research Directions",
)
_SECTIONS_SCOPING_REVIEW: tuple[str, ...] = (
    "Title", "Abstract", "Introduction", "Methods", "Study Selection",
    "Study Characteristics", "Narrative Synthesis", "Discussion",
    "Limitations", "Conclusion",
)
_SECTIONS_PILOT_META: tuple[str, ...] = (
    "Title", "Abstract", "Introduction", "Methods", "Study Selection",
    "Study Characteristics", "Pilot Pooled Effect", "Heterogeneity",
    "Sensitivity Analyses", "Discussion", "Limitations", "Conclusion",
)
_SECTIONS_FULL_META: tuple[str, ...] = (
    "Title", "Abstract", "Introduction", "Methods", "Study Selection",
    "Study Characteristics", "Primary Pooled Effect", "Heterogeneity",
    "Sensitivity Analyses", "Subgroup Analyses", "Publication Bias",
    "Certainty of Evidence", "Discussion", "Limitations", "Conclusion",
)


def select_paper_type(readiness: ReadinessReport) -> PaperType:
    """Choose a paper type from the readiness ladder + pool count."""
    level = readiness.level
    k_pool = readiness.counts.get("k_pool", 0)
    if level == 1:
        return PaperType(
            name="corpus-snapshot",
            rationale="L1 — pipeline has not produced receipts yet; only a "
                      "corpus-snapshot artifact is appropriate.",
            recommended_sections=_SECTIONS_CORPUS_SNAPSHOT,
            forbidden_claims=(
                "do not claim a synthesised effect",
                "do not cite any extracted numeric",
            ),
        )
    if level == 2:
        return PaperType(
            name="evidence-gap-report",
            rationale="L2 — eligibility surfaced no studies; the publishable "
                      "output is an evidence-gap framing.",
            recommended_sections=_SECTIONS_EVIDENCE_GAP,
            forbidden_claims=(
                "do not claim a synthesised effect",
                "do not summarise non-existent included studies",
            ),
        )
    if level in (3, 4):
        return PaperType(
            name="scoping-review",
            rationale=(
                f"L{level} — primary set exists but no parseable pool "
                f"({k_pool} effects); narrative synthesis only."
            ),
            recommended_sections=_SECTIONS_SCOPING_REVIEW,
            forbidden_claims=(
                "do not pool effects across studies",
                "do not claim heterogeneity has been quantified",
                "do not claim certainty-of-evidence grading",
            ),
        )
    if level == 5:
        return PaperType(
            name="pilot-meta-analysis",
            rationale=(
                f"L5 — pilot pool of {k_pool} effects; permitted to pool but "
                f"must explicitly frame as pilot and avoid subgroup claims."
            ),
            recommended_sections=_SECTIONS_PILOT_META,
            forbidden_claims=(
                "do not present subgroup analyses (k<3)",
                "do not claim absence of publication bias from k<3",
                "label the synthesis explicitly as a 'pilot pool'",
            ),
        )
    # level == 6
    if k_pool >= 10:
        return PaperType(
            name="meta-analysis-full",
            rationale=(
                f"L6 + k={k_pool} ≥ 10 — full meta-analysis including "
                f"subgroup + publication-bias diagnostics."
            ),
            recommended_sections=_SECTIONS_FULL_META,
            forbidden_claims=(),
        )
    return PaperType(
        name="meta-analysis-standard",
        rationale=(
            f"L6 + k={k_pool} (<10) — standard meta-analysis without "
            f"subgroup / Egger; the k base is too small for those tests."
        ),
        recommended_sections=tuple(
            s for s in _SECTIONS_FULL_META
            if s not in {"Subgroup Analyses", "Publication Bias"}
        ),
        forbidden_claims=(
            "do not present subgroup analyses unless k>=10 per stratum",
            "do not run Egger's test (requires k>=10 per cochrane handbook)",
        ),
    )


def writer_preamble(paper_type: PaperType) -> str:
    """Sprint 32 — render a writer-prompt preamble that carries the
    PaperType's framing constraints into the LLM's system message.

    Universal: every constraint is paper-type-canonical (no topic
    literals). When draft_main.py injects this preamble, the writer
    sees the paper-type contract BEFORE drafting prose — so a
    scoping-review topic doesn't accidentally produce "quantitative
    synthesis" titling.
    """
    if not paper_type.forbidden_claims and not paper_type.rationale:
        return ""
    lines = [
        f"PAPER-TYPE CONTRACT — this manuscript is a `{paper_type.name}` "
        f"output, NOT a generic systematic review.",
        f"Rationale: {paper_type.rationale}",
        "",
        "You MUST honor the following constraints when writing every "
        "section (title, abstract, methods, results, discussion):",
    ]
    for claim in paper_type.forbidden_claims:
        lines.append(f"  - {claim}")
    lines.append("")
    lines.append(
        "If any prior writer-template phrase would violate one of these "
        "constraints (e.g. 'quantitative synthesis' when k_pool=0; "
        "'meta-analysis' when the paper-type is scoping-review), "
        "substitute paper-type-appropriate wording."
    )
    return "\n".join(lines) + "\n"
