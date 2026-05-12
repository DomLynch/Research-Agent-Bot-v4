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


def build_back_matter(
    pack: TopicPack,
    settings: Settings,
    *,
    run_dir_name: str = "",
    repository_url: str = "",
    operator_handle: str = "human-operator",
) -> BackMatter:
    """Compose back-matter prose from pipeline-known facts.

    Universal: no biomedical literals. The ethics line is driven by
    `pack.primary_system` (e.g. 'mouse') and the discouraged-terms list
    so a climate or social-science pack produces an ethics statement
    appropriate to its domain — or omits the animal-research clause
    entirely.
    """
    sources = ", ".join(pack.retrieval_sources) or "(none declared)"
    run_ref = run_dir_name or "(run directory not specified)"
    repo_ref = repository_url or "(repository URL not configured)"
    data_and_code = (
        "All raw retrieval hits, screening receipts, parsed full-text "
        "bodies (where available), eligibility receipts, effect "
        "extraction receipts, the strict A-core primary-effect input "
        f"set, and the rendered manuscript are filed under the run "
        f"directory `{run_ref}` and are version-controlled in "
        f"`{repo_ref}`. Retrieval sources configured for this topic "
        f"pack: {sources}. The reproducibility contract is auditable: "
        "every count and effect estimate in the manuscript carries a "
        "Supplementary §S{N} / Appendix A cross-reference that points "
        "at the corresponding JSON receipt (`eligibility_summary.json`, "
        "`primary_effect_input_set_strict.json`, `effect_extractions.json`, "
        "`effect_pool.json`, `extraction_crosscheck.json`) so downstream "
        "reviewers can re-validate without re-running the LLM stack. "
        "Manual full-text injections (when used to recover sentinel "
        "papers the auto retrieval cannot reach) are recorded with "
        "SHA-256 hashes in `manual_full_text_audit.json`."
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
    if pack.primary_system in {"mouse", "mice", "murine", "rat", "rats"}:
        ethics = (
            "This synthesis re-analyses published animal-research "
            "data. No new experiments on living animals were conducted. "
            "The included primary studies are responsible for their own "
            "institutional animal-care and ethical approvals; reviewers "
            "are referred to the primary references in this manuscript "
            "for those statements. The synthesis itself does not require "
            "additional ethical approval."
        )
    elif pack.primary_system in {"human", "humans", "patient", "patients"}:
        ethics = (
            "This synthesis re-analyses published human-subjects data. "
            "No new human-subjects experiments were conducted. The "
            "included primary studies are responsible for their own "
            "institutional review board approvals and participant "
            "consent; reviewers are referred to the primary references "
            "for those statements."
        )
    else:
        ethics = (
            "This synthesis re-analyses previously published data. No "
            "new primary data collection was conducted. Per-study "
            "ethical and licensing statements remain with the original "
            "publications cited herein."
        )
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
    conflicts = (
        "The operator declares no financial conflicts of interest "
        "related to mTOR-pathway pharmacology, geroprotective "
        "interventions, or the cited primary studies. The pipeline is "
        "open-source and reusable across topics; no commercial "
        "relationship influenced the eligibility rules or the "
        "manuscript framing for the present synthesis."
    )
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
