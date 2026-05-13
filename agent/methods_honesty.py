"""Rewrite Methods/Discussion overclaim verbs to honest tense.

The writer LLM produces methods + discussion prose using future-tense verbs
borrowed from systematic-review templates: "will be performed", "dual
extraction", "Egger's regression test", "leave-one-out", etc. The current
pipeline implements automated screen + automated extraction + automated
RoB notes only; the heavier moderator/sensitivity machinery is *planned*,
not built. Without correction, the manuscript overclaims the work.

Two-layer defence:

  1. `_UNIVERSAL_REWRITES` (below) — topic-neutral phrase patches the
     writer is likely to emit for ANY meta-analysis topic (dual
     extraction, full meta-regression apparatus, leave-one-out / Egger,
     PACKET anchor strips). Applied to every topic before pack rewrites.
  2. `pack.methods_honesty_rewrites` — topic-specific corrections
     (citation fixes, author swaps, corpus-state sentences). Lives in
     the topic-pack TOML.

Pack entries take precedence on key collision so a pack can override
a universal rewrite if it has a topic-specific reason to.

Universal: the baseline + the pack table together cover both axes.
Adding a new topic = declaring only the TOPIC-specific patches it needs;
the universal baseline applies for free.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.topic_pack import TopicPack

# Topic-neutral phrase patches — apply to every topic before the pack's
# topic-specific rewrites. The writer prompt (`system_writer.md` +
# `writer_section_methods.md`) is the FIRST line of defence; this is the
# safety net if the writer slips. Each entry's LHS must match a phrase
# the writer is likely to emit verbatim for any meta-analysis topic.
_UNIVERSAL_REWRITES: dict[str, str] = {
    # --- Methods overclaim verbs --------------------------------------
    "Extraction will be performed with independent dual extraction; disagreements will be resolved by consensus or, if necessary, by consulting a third party.":
        "Extraction is performed by a single automated pass over parsed full text under the universal evidence contract; every extraction (study_id, metric, treated/control values, n, evidence quotes, model, timestamps) is filed in `effect_extractions.json`. Independent dual extraction and third-party adjudication are planned for the pre-publication step.",
    "The statistical synthesis will employ a multi-level random-effects meta-regression model. The model will include random intercepts for study-ID and outcome-measure-within-study to account for dependency. Fixed-effects terms will include the pre-specified moderators. The restricted maximum likelihood (REML) estimator will be used for between-study variance, with the Hartung-Knapp adjustment for confidence intervals to address potential small-sample bias [CIT:hartung-knapp|method-citation]. The analysis will be conducted in R using the metafor package [CIT:viechtbauer-2010-metafor|method-citation]. Heterogeneity will be quantified using the I² statistic and prediction intervals [CIT:higgins-2003-i2|method-citation].":
        "The pipeline implements an inverse-variance random-effects pool over contract-passing effects within a single metric family; an inverse-variance point estimate is reported at k>=2. The full multi-level random-effects meta-regression (random intercepts for study-ID and outcome-measure-within-study, REML between-study variance, Hartung-Knapp adjustment [CIT:hartung-knapp|method-citation], metafor in R [CIT:viechtbauer-2010-metafor|method-citation], I² and prediction intervals [CIT:higgins-2003-i2|method-citation]) requires substantially larger k -- the field convention is typically k>=5-10 contract-passing effects per metric family before moderator inference is interpretable -- and is deferred until that threshold is met.",
    "Sensitivity analyses will include leave-one-out analysis, influence diagnostics (e.g., Cook's distance), and the inspection of funnel plots for asymmetry, with Egger's regression test to formally assess publication bias [CIT:egger-1997-funnel|method-citation].":
        "Sensitivity analyses (leave-one-out, influence diagnostics including Cook's distance, funnel-plot inspection for asymmetry, and Egger's regression test for publication bias [CIT:egger-1997-funnel|method-citation]) require a larger pool than the inverse-variance point estimate alone; the field convention is typically k>=5-10 contract-passing effects per metric family before these diagnostics are interpretable. The current iteration reports the inverse-variance point estimate but defers leave-one-out / influence / funnel / Egger until additional contract-passing effects accrue.",
    "The analysis will employ mixed-effects meta-regression models to partition variance in the standardized mean difference (SMD) of lifespan extension between studies.":
        "Mixed-effects meta-regression to partition SMD variance is a designed-for capability of the pipeline; an inverse-variance point estimate is reported at k>=2, while moderator meta-regression / leave-one-out / Egger's test follow the field convention of k>=5-10 contract-passing effects per metric family and are deferred until that threshold is met.",
    # --- Strip [PACKET:...] audit anchors from manuscript prose -------
    # These anchors belong in the supplement / audit trail, not in the
    # journal-facing argument. Maps to the supplement section + run-
    # audit appendix that actually holds the receipt.
    "[PACKET:study_selection]": "(Supplementary §S2-S3; Appendix A)",
    "[PACKET:corpus_characteristics]": "(Supplementary §S4; Appendix A)",
    "[PACKET:primary_effect]": "(Supplementary §S5/S5b; Appendix A)",
    "[PACKET:primary_pool_composition]": "(Supplementary §S4 and §S8; Appendix A)",
    "[PACKET:sentinel_recall]": "(Supplementary §S7; Appendix A)",
}


@dataclass(frozen=True, slots=True)
class HonestyResult:
    body: str
    rewrites_applied: tuple[str, ...]


def apply_honesty_rewrites(
    body: str, pack: TopicPack, *, max_passes: int = 3,
) -> HonestyResult:
    """Apply phrase -> replacement substitutions from the topic pack.

    Multi-pass to converge on chained rewrites (rewrite A's target
    introduces text that rewrite B should consume). Each source fires
    at most once globally — prevents A->B->A cycles. Passes stop early
    when a pass produces no new firings.

    Returns the rewritten body plus the list of original phrases that
    actually matched (so callers can verify the rewrites fired and an
    auditor can see which overclaim verbs were corrected).
    """
    # Pack rewrites take precedence on key collision (a pack can
    # override a universal entry when it has a topic-specific reason).
    merged: dict[str, str] = {**_UNIVERSAL_REWRITES, **pack.methods_honesty_rewrites}
    if not merged:
        return HonestyResult(body=body, rewrites_applied=())

    rewrites = sorted(
        merged.items(),
        key=lambda kv: -len(kv[0]),
    )
    applied: list[str] = []
    fired: set[str] = set()
    out = body
    for _ in range(max_passes):
        pass_fired = False
        for source, target in rewrites:
            if source and source not in fired and source in out:
                out = out.replace(source, target)
                applied.append(source)
                fired.add(source)
                pass_fired = True
        if not pass_fired:
            break
    return HonestyResult(body=out, rewrites_applied=tuple(applied))
