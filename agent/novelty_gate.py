"""Deterministic novelty gate — *code disposes* on "is this NEW vs prior art?".

The writer LLM proposes a thesis; this module decides, from corpus-grounded
counts and the run's own facts, whether the lead claim is novel enough to
publish and whether its cited sources verifiably exist. It replaces the old
implicit bias toward citation *popularity* (``topic_discovery._paper_score``)
and conformity (``alpha_selector.accepted_shape_bonus``) with an explicit,
measured novelty disposition.

Design contract (mirrors the rest of the gate):
  - **Pure**: every function here is a pure function of its inputs — no network,
    no disk. The online inputs (corpus prior-art count, citation existence) are
    gathered by the caller and persisted to ``novelty.json``; the publish gate
    reads that sidecar offline and calls :func:`novelty_blockers`.
  - **Deterministic**: same inputs -> same score and blockers. No LLM here.
  - **Bounded & conservative**: every component is clamped to ``[0, 1]``; missing
    inputs degrade toward "novel / not-blocked" so an outage never silently
    blocks a real memo (network failure -> ``corpus_prior_art_count = None`` ->
    scarcity neutralised, never a false ``insufficient_novelty``).
  - **Universal**: no domain literals; thresholds/weights live in
    ``topic_packs/publish_tier.toml``.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

INSUFFICIENT_NOVELTY = "insufficient_novelty"
CITATION_HALLUCINATED = "citation_hallucinated"


@dataclass(frozen=True, slots=True)
class NoveltyConfig:
    """Thresholds/weights, sourced from publish_tier.toml ([novelty])."""

    saturation_count: int = 40   # corpus prior-art sources at/above which scarcity -> 0
    weight_scarcity: float = 0.5
    weight_distinctiveness: float = 0.3
    weight_recency: float = 0.2
    min_score: int = 45          # score below this -> INSUFFICIENT_NOVELTY blocker
    recency_window_years: int = 3  # newest source within this of `now` == fully fresh
    recency_decay_years: int = 12  # older than now-this == recency 0.0


def novelty_config_from_dict(section: Mapping[str, object]) -> NoveltyConfig:
    """Build a NoveltyConfig from a parsed publish_tier.toml [novelty] section.

    Pure: the caller reads the TOML; this only coerces. Unknown/garbled values
    fall back to the dataclass defaults.
    """
    d = NoveltyConfig()

    def _i(key: str, default: int) -> int:
        v = section.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) else default

    def _f(key: str, default: float) -> float:
        v = section.get(key)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default

    return NoveltyConfig(
        saturation_count=_i("saturation_count", d.saturation_count),
        weight_scarcity=_f("weight_scarcity", d.weight_scarcity),
        weight_distinctiveness=_f("weight_distinctiveness", d.weight_distinctiveness),
        weight_recency=_f("weight_recency", d.weight_recency),
        min_score=_i("min_score", d.min_score),
        recency_window_years=_i("recency_window_years", d.recency_window_years),
        recency_decay_years=_i("recency_decay_years", d.recency_decay_years),
    )


@dataclass(frozen=True, slots=True)
class NoveltyReport:
    score: int                       # 0..100 composite
    scarcity: float                  # 0..1 — rarer in corpus == higher
    distinctiveness: float           # 0..1 — less like the run's other facts == higher
    recency: float                   # 0..1 — newer frontier == higher
    corpus_prior_art_count: int | None
    citation_hallucinated: bool
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "scarcity": round(self.scarcity, 3),
            "distinctiveness": round(self.distinctiveness, 3),
            "recency": round(self.recency, 3),
            "corpus_prior_art_count": self.corpus_prior_art_count,
            "citation_hallucinated": self.citation_hallucinated,
            "blockers": list(self.blockers),
        }


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _scarcity(corpus_prior_art_count: int | None, saturation: int) -> float:
    """Fewer existing corpus sources on this claim -> more novel.

    ``None`` (count unavailable, e.g. corpus outage) -> neutral 0.5, never a
    false novelty failure.
    """
    if corpus_prior_art_count is None:
        return 0.5
    if saturation <= 0:
        return 0.0
    return _clamp01(1.0 - corpus_prior_art_count / saturation)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _distinctiveness(
    lead_shape: frozenset[str], other_shapes: tuple[frozenset[str], ...],
) -> float:
    """How unlike the run's *other* A-core facts the lead claim is.

    1.0 when the lead is the only fact or shares little with the rest; lower as
    the lead becomes one-of-many identical-shape facts (a crowded, non-novel
    finding). Mean Jaccard overlap, inverted.
    """
    if not lead_shape or not other_shapes:
        return 1.0
    mean_overlap = sum(_jaccard(lead_shape, s) for s in other_shapes) / len(other_shapes)
    return _clamp01(1.0 - mean_overlap)


def _recency(newest_source_year: int | None, now_year: int, cfg: NoveltyConfig) -> float:
    """Newer research frontier -> more novel. Linear decay across the window."""
    if newest_source_year is None or now_year <= 0:
        return 0.5
    age = now_year - newest_source_year
    if age <= cfg.recency_window_years:
        return 1.0
    if age >= cfg.recency_decay_years:
        return 0.0
    span = cfg.recency_decay_years - cfg.recency_window_years
    return _clamp01(1.0 - (age - cfg.recency_window_years) / span) if span > 0 else 0.0


def compute_novelty(
    *,
    corpus_prior_art_count: int | None,
    lead_shape: frozenset[str],
    other_shapes: tuple[frozenset[str], ...],
    newest_source_year: int | None,
    now_year: int,
    citation_hallucinated: bool,
    cfg: NoveltyConfig,
) -> NoveltyReport:
    """Deterministic novelty disposition. Pure function of its inputs."""
    scarcity = _scarcity(corpus_prior_art_count, cfg.saturation_count)
    distinct = _distinctiveness(lead_shape, other_shapes)
    recency = _recency(newest_source_year, now_year, cfg)

    weights = cfg.weight_scarcity + cfg.weight_distinctiveness + cfg.weight_recency
    if weights <= 0:
        composite = 0.0
    else:
        composite = (
            cfg.weight_scarcity * scarcity
            + cfg.weight_distinctiveness * distinct
            + cfg.weight_recency * recency
        ) / weights
    score = round(100 * _clamp01(composite))

    return NoveltyReport(
        score=score,
        scarcity=scarcity,
        distinctiveness=distinct,
        recency=recency,
        corpus_prior_art_count=corpus_prior_art_count,
        citation_hallucinated=citation_hallucinated,
        blockers=_blockers(score, citation_hallucinated, cfg),
    )


def _blockers(score: int, citation_hallucinated: bool, cfg: NoveltyConfig) -> tuple[str, ...]:
    out: list[str] = []
    if score < cfg.min_score:
        out.append(INSUFFICIENT_NOVELTY)
    if citation_hallucinated:
        out.append(CITATION_HALLUCINATED)
    return tuple(out)


def novelty_blockers(report: Mapping[str, object], cfg: NoveltyConfig) -> list[str]:
    """Re-derive blockers from a persisted novelty.json report, offline.

    The publish gate calls this. Trusts the report's score/citation flag (they
    were computed by :func:`compute_novelty` during the online build) but
    re-applies the *current* threshold so config changes take effect without a
    rerun. Missing/garbled report -> no blockers (advisory-safe).
    """
    if not isinstance(report, dict):
        return []
    score = report.get("score")
    hallucinated = bool(report.get("citation_hallucinated"))
    score_int = score if isinstance(score, int) else cfg.min_score
    return list(_blockers(score_int, hallucinated, cfg))
