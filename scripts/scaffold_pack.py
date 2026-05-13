"""Sprint 12.9 Task D: auto-generate a draft topic pack from a keyword.

Queries the Researka curated index for tier-1 papers matching the
topic, picks the top hits as sentinels + anchors + bibliography,
and emits a draft `topic_packs/<topic>.toml` the operator can
hand-edit before running the pipeline.

Universal: the scaffold reads only the Researka /api/v1/papers/topic
response shape (id/doi/title/journal/year/topic_score) and the
operator's CLI flags. No biomedical literals in code — sensible
biomedical defaults (mouse + lifespan vocabulary) are applied
because Researka's curation is anti-aging-focused, but every default
is overridable via CLI flags so a non-biomedical topic still
produces a valid pack.

Usage:
    python scripts/scaffold_pack.py --topic "NMN" \\
        --primary-interventions "nicotinamide mononucleotide,NMN" \\
        --output topic_packs/nmn.toml

    # Override defaults explicitly:
    python scripts/scaffold_pack.py --topic "caloric restriction" \\
        --species "rhesus,macaque,primate" \\
        --endpoint "survival" \\
        --primary-interventions "caloric restriction,CR,dietary restriction"
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.settings import load_settings


def _toml_str(s: str) -> str:
    """Escape a string for TOML basic-string emission."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _anchor_key(doi: str | None, year: int | None, title: str) -> str:
    """Build a stable anchor key from paper metadata. Format:
    `<first-noun-word>-<year>-<topic-hash>`. Universal — derived from
    the paper's own metadata; no biomedical literals."""
    first_word = re.findall(r"[A-Za-z]+", title)[:1]
    stem = (first_word[0].lower() if first_word else "paper")[:24]
    yr = year or 0
    suffix = (re.sub(r"\W+", "", doi or "")[-4:] or "anon").lower()
    return f"{stem}-{yr}-{suffix}"


def _fetch_curated(
    settings: Any, topic: str, *, limit: int,
) -> list[dict[str, Any]]:
    """Hit POST /api/v1/papers/topic and return the curated paper list.
    Sorted by (tier asc, topic_score desc, quality_score desc) so
    tier-1 highest-relevance papers come first."""
    body = {"topic": topic, "limit": limit, "include_facts": False}
    headers = {
        "X-Researka-Token": settings.researka_database_token,
        "Content-Type": "application/json",
    }
    url = f"{settings.researka_database_url.rstrip('/')}/api/v1/papers/topic"
    r = httpx.post(url, json=body, headers=headers, timeout=30.0)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        return []
    data.sort(key=lambda p: (
        int(p.get("tier") or 99),
        -float(p.get("topic_score") or 0.0),
        -float(p.get("quality_score") or 0.0),
    ))
    return data


def _render(
    *, topic: str, display_name: str, primary_interventions: list[str],
    species_terms: list[str], endpoint: str, papers: list[dict[str, Any]],
    sentinel_n: int, anchor_n: int,
) -> str:
    """Render a draft TOML using paper metadata for sentinels + anchors
    + bibliography. Sensible biomedical defaults fill the rest;
    operator hand-edits before the pipeline runs."""
    sentinels = [p for p in papers[:sentinel_n] if p.get("doi")]
    anchor_pool = [p for p in papers[sentinel_n: sentinel_n + anchor_n] if p.get("doi")]

    interv_list = ", ".join(f'"{_toml_str(t)}"' for t in primary_interventions)
    species_list = ", ".join(f'"{_toml_str(t)}"' for t in species_terms)
    endpoint_terms = [
        endpoint, "survival", "longevity", "mortality", "median survival",
    ]
    endpoint_list = ", ".join(f'"{_toml_str(t)}"' for t in endpoint_terms)
    # When no curated sentinels are available, emit an empty array
    # (not `[""]`) so the loaded pack's sentinel_primary is genuinely
    # empty — the sentinel-recall gate will then surface the missing-
    # curation case explicitly instead of trying to look up a blank DOI.
    sentinel_block = (
        "\n    " + ",\n    ".join(
            f'"{_toml_str(p["doi"])}"' for p in sentinels
        ) + "\n"
        if sentinels else ""
    )

    # Anchor + bibliography blocks share keys. Build them together.
    anchor_lines: list[str] = []
    bib_lines: list[str] = []
    for p in anchor_pool:
        key = _anchor_key(p.get("doi"), p.get("publication_year"), p.get("title") or "")
        anchor_lines.append(f'"{_toml_str(key)}" = "primary-study"')
        title = _toml_str((p.get("title") or "").strip())
        journal = _toml_str((p.get("journal_name") or "").strip())
        year = p.get("publication_year") or "(n.d.)"
        doi = _toml_str(p.get("doi") or "")
        bib_lines.append(
            f'"{_toml_str(key)}" = "{title}. {journal}. {year}. doi:{doi}."'
        )
    anchors_block = "\n".join(anchor_lines) or "# (no anchor papers returned by curated index)"
    bib_block = "\n".join(bib_lines) or "# (no bibliography entries auto-generated)"

    return f'''# Topic pack: {topic} — auto-generated draft (Sprint 12.9 Task D scaffold).
# Edit before running the pipeline. The scaffold seeds the structural
# fields; topic-specific overclaim corrections (methods_honesty_rewrites)
# and the pack-specific back_matter prose still benefit from
# hand-tuning after the first render audit.

topic = "{_toml_str(topic)}"
display_name = "{_toml_str(display_name)}"

[scope]
primary_system = "{_toml_str(species_terms[0]) if species_terms else "mouse"}"
preferred_terms = [{species_list}]
discouraged_terms = []
endpoint = "{_toml_str(endpoint)}"
primary_interventions = [{interv_list}]
translational_only_interventions = []

[cite_roles]
default = "literature-reference"
allowed = [
    "primary-study", "prior-meta-analysis", "narrative-review",
    "systematic-review", "mechanism-review", "clinical-trial",
    "protocol-registration", "method-citation", "literature-reference",
]

# Auto-generated from Researka topic-curated papers (next-tier after sentinels).
[anchors]
{anchors_block}

[length_caps]
abstract = 300
introduction = 1000
methods = 1200

[retrieval]
sources = [
    "pubmed", "crossref", "openalex", "europepmc", "semantic_scholar",
    "core", "biorxiv", "osf", "ctgov", "researka",
]

[density]
min_words_per_citation = 45

[empirical_triggers]
outcome_nouns_extra = ["{_toml_str(endpoint)}", "survival", "longevity", "mortality"]
direction_verbs_extra = ["extends", "extend", "prolongs", "prolong"]
subjects_extra = []

[extraction]
preferred_metric_families = ["median_{_toml_str(endpoint)}", "median_survival"]

[eligibility]
endpoint_terms = [{endpoint_list}]
control_terms = ["control", "vehicle", "placebo", "untreated", "wild-type"]
exclude_design_terms = [
    "systematic review", "meta-analysis", "narrative review",
    "scoping review", "in vitro", "cell line", "case report",
]
combination_terms = ["combined with", "combination with", "plus ", "co-treatment"]
min_text_chars = 2000

# Auto-selected from top topic-scored curated papers.
[sentinel_recall]
primary = [{sentinel_block}]
prior_meta = []

[strict_a_core]
non_mouse_species_terms = [
    "c. elegans", "caenorhabditis", "drosophila", "saccharomyces",
    "yeast", "zebrafish", "human subjects", "clinical trial",
]
secondary_design_quote_markers = [
    "proteomic", "transcriptomic", "metabolomic", "lipidomic",
    "methylation", "epigenetic",
]

# Auto-generated bibliography from Researka curated papers.
[references.bibliography]
{bib_block}

[placeholders]
"databases" = "PubMed, Crossref, OpenAlex, Europe PMC, Semantic Scholar, CORE, bioRxiv/medRxiv, OSF Preprints, ClinicalTrials.gov, and the Researka tier-1 curated index"
"date-range" = "(set this to your final retrieval window)"
"query-terms" = "(record the exact Boolean composition used at retrieval time)"
"minimum-studies-per-cell" = "k < 3 studies per moderator cell"
"MODERATOR_P:dose" = "dose level"
"MODERATOR_P:sex" = "biological sex"
"MODERATOR_P:treatment_initiation_age" = "age at treatment initiation"

# Empty initially; populate iteratively as render audits surface drift.
[methods_honesty_rewrites]

# Neutral defaults — replace with topic-appropriate ethics + conflicts
# wording once the topic is known to the operator.
[back_matter]
ethics_statement = """This synthesis re-analyses previously published data. No new primary data collection was conducted. Per-study ethical and licensing statements remain with the original publications cited herein."""
conflicts_statement = """The operator declares no financial conflicts of interest related to the subject matter of this synthesis or to the cited primary studies. The pipeline is open-source and reusable across topics; no commercial relationship influenced the eligibility rules or the manuscript framing for the present synthesis."""
'''


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--topic", required=True, help="Topic keyword (e.g. 'NMN').")
    p.add_argument(
        "--display-name", default=None,
        help="Pretty display name (defaults to title-cased --topic).",
    )
    p.add_argument(
        "--primary-interventions", default=None,
        help="Comma-separated list. Defaults to --topic itself.",
    )
    p.add_argument(
        "--species", default="mouse,mice,murine",
        help="Comma-separated preferred-species/system terms.",
    )
    p.add_argument(
        "--endpoint", default="lifespan",
        help="Primary endpoint noun (e.g. 'lifespan', 'survival').",
    )
    p.add_argument("--sentinel-n", type=int, default=3)
    p.add_argument("--anchor-n", type=int, default=15)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()

    settings = load_settings()
    if not settings.researka_configured:
        print("[scaffold] RESEARKA_DATABASE_URL/TOKEN not set; aborting.", file=sys.stderr)
        return 1

    primary_int = (
        [t.strip() for t in args.primary_interventions.split(",") if t.strip()]
        if args.primary_interventions else [args.topic.strip()]
    )
    species = [t.strip() for t in args.species.split(",") if t.strip()]
    display = args.display_name or args.topic.strip().title()
    output = args.output or Path(__file__).resolve().parent.parent / "topic_packs" / f"{args.topic.lower().replace(' ', '_')}.toml"

    print(f"[scaffold] querying Researka for topic: {args.topic!r}")
    papers = _fetch_curated(settings, args.topic, limit=args.limit)
    print(f"[scaffold] received {len(papers)} curated papers")
    if not papers:
        print("[scaffold] no curated papers returned; pack will lack sentinels.", file=sys.stderr)

    body = _render(
        topic=args.topic, display_name=display,
        primary_interventions=primary_int, species_terms=species,
        endpoint=args.endpoint, papers=papers,
        sentinel_n=args.sentinel_n, anchor_n=args.anchor_n,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(body, encoding="utf-8")
    print(f"[scaffold] wrote {output} ({len(body)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
