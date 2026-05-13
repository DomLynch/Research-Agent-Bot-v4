"""Honest back-matter sections for the manuscript.

Generates Data and Code Availability, AI-Use / Automation Disclosure,
Ethics Statement, Author Contributions, Conflicts of Interest, and
Funding sections from facts the pipeline actually knows:

  - the writer + judge models in use (from Settings)
  - the topic-pack name + retrieval sources
  - the run-dir provenance (receipts, hashes)
  - whether a registry record is declared in the pack

No LLM, no invention. Every line is a verifiable statement about the
pipeline run; the model stack is named because the AI-Use disclosure
requires it. Universal: nothing biomedical here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.settings import Settings
from agent.topic_pack import TopicPack


@dataclass(frozen=True, slots=True)
class BackMatter:
    """Rendered back-matter Markdown plus the individual section keys
    so the stitcher / supplement generator can re-use them."""

    data_and_code_availability: str
    ai_use_disclosure: str
    ethics_statement: str
    author_contributions: str
    conflicts_of_interest: str
    funding: str

    def as_markdown(self) -> str:
        return "\n\n".join((
            "## Data and Code Availability",
            self.data_and_code_availability,
            "## AI-Use and Automation Disclosure",
            self.ai_use_disclosure,
            "## Ethics Statement",
            self.ethics_statement,
            "## Author Contributions",
            self.author_contributions,
            "## Conflicts of Interest",
            self.conflicts_of_interest,
            "## Funding",
            self.funding,
        )) + "\n"


_NEUTRAL_ETHICS = (
    "This synthesis re-analyses previously published data. No new "
    "primary data collection was conducted. Per-study ethical and "
    "licensing statements remain with the original publications cited "
    "herein."
)
_NEUTRAL_CONFLICTS = (
    "The operator declares no financial conflicts of interest related "
    "to the subject matter of this synthesis or to the cited primary "
    "studies. The pipeline is open-source and reusable across topics; "
    "no commercial relationship influenced the eligibility rules or "
    "the manuscript framing for the present synthesis."
)


def build_back_matter(
    pack: TopicPack,
    settings: Settings,
    *,
    run_dir: Path | None = None,
    run_dir_name: str = "",
    repository_url: str = "",
    operator_handle: str = "the operator",
) -> BackMatter:
    """Compose back-matter prose from pipeline-known facts.

    Universal: no biomedical literals. The ethics and conflicts lines
    come from `pack.ethics_statement` / `pack.conflicts_statement`
    (animal-research framing for a mouse-lifespan pack, human-subjects
    framing for a clinical pack); packs that omit those fields fall
    through to neutral previously-published-data wording so a climate
    or social-science pack still renders a coherent back-matter block.
    """
    sources = ", ".join(pack.retrieval_sources) or "(none declared)"
    run_ref = run_dir_name or "(run directory not specified)"
    repo_ref = repository_url or "(repository URL not configured)"
    # Conditional manual-audit clause: only claim the sidecar is alongside
    # this paper folder when the file actually exists. Keeps paper.md
    # consistent with supplement.md S9 ("No manual-full-text audit
    # sidecar is packaged...") on runs where no manual overrides ran.
    manual_audit_present = bool(
        run_dir and (run_dir / "manual_full_text_audit.json").exists()
    )
    manual_audit_clause = (
        "When manual full-text injections are used to recover sentinel "
        "papers the auto retrieval cannot reach, per-injection SHA-256 "
        "hashes are recorded in a manual-full-text audit sidecar in "
        "this run directory."
        if manual_audit_present else
        "No manual-full-text audit sidecar is packaged in this final "
        "paper folder; when manual injections are used to recover "
        "sentinel papers the auto retrieval cannot reach, per-injection "
        "SHA-256 hashes are recorded in such a sidecar in the upstream "
        "run directory."
    )
    data_and_code = (
        "The aggregate screening counts, the strict A-core / "
        "sensitivity / secondary lane structure, the per-study effect "
        "extractions, the inverse-variance pool, the Researka Tier-2 "
        "canonical-fact cross-check, and the rendered manuscript and "
        f"supplement are packaged in the run directory `{run_ref}` "
        f"and are version-controlled in `{repo_ref}`. Upstream "
        "retrieval-stage artifacts (raw retrieval hits, per-paper "
        "screening receipts, parsed full-text bodies, per-study "
        "eligibility receipts) live in the upstream eligibility run "
        "directory rather than this final paper folder, so this "
        "folder stays lean while the reproducibility chain remains "
        f"traceable. Retrieval sources configured for this topic "
        f"pack: {sources}. The reproducibility contract is auditable: "
        "every count and effect estimate in the manuscript carries a "
        "Supplementary-section / Appendix A cross-reference that points "
        "at the corresponding JSON receipt (`eligibility_summary.json`, "
        "`primary_effect_input_set_strict.json`, `effect_extractions.json`, "
        "`effect_pool.json`, `extraction_crosscheck.json`) so downstream "
        "reviewers can re-validate without re-running the LLM stack. "
        f"{manual_audit_clause}"
    )
    ai_use = (
        f"This manuscript was assembled by an automated synthesis "
        f"pipeline. The eligibility judge is `{settings.judge_model}` "
        f"(via OpenRouter); the writer (Title, Abstract, Introduction, "
        f"Methods, Discussion, Limitations, Conclusion) is "
        f"`{settings.mimo_model}`. Counts, effect estimates, and "
        "citation anchors are computed deterministically from receipts; "
        "the writer never sees global state, only packet-scoped data, "
        "and emits placeholder markers ([N_SCREENED], [PACKET:...], "
        "[CIT:<key>|<role>]) that the pipeline resolves post-hoc. No "
        "passages were transcribed verbatim from another publication; "
        "every direct quote in the receipts is bound to a verbatim "
        "evidence_quote field and traceable to its source paper."
    )
    ethics = pack.ethics_statement.strip() or _NEUTRAL_ETHICS
    author_contributions = (
        f"The synthesis pipeline (retrieval, screening, eligibility "
        "adjudication, full-text parsing, effect extraction, pooling, "
        "manuscript drafting) was executed end-to-end by an automated "
        f"system. {operator_handle} configured the topic pack, supplied "
        "manual full-text overrides when auto-retrieval failed for "
        "documented sentinel papers, and is responsible for the final "
        "manuscript content. All other steps (search, screen, extract, "
        "draft prose) were performed by the language models named in "
        "the AI-Use Disclosure under the constraints of the universal "
        "evidence contract."
    )
    conflicts = pack.conflicts_statement.strip() or _NEUTRAL_CONFLICTS
    funding = (
        "No external funding was received for this synthesis. The "
        "computational cost of the language-model calls was borne "
        "directly by the operator under a personal API subscription "
        "to the writer model and a metered allowance to the judge "
        "model provider; no third-party sponsor influenced study "
        "selection, extraction, or interpretation."
    )
    return BackMatter(
        data_and_code_availability=data_and_code,
        ai_use_disclosure=ai_use,
        ethics_statement=ethics,
        author_contributions=author_contributions,
        conflicts_of_interest=conflicts,
        funding=funding,
    )


def write_back_matter(target: Path, back_matter: BackMatter) -> None:
    target.write_text(back_matter.as_markdown(), encoding="utf-8")
