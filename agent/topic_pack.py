"""Topic-pack loader.

Per-topic configuration lives in `topic_packs/<topic>.toml` (data, not code).
Each pack defines:
  - scope.preferred_terms / discouraged_terms   (scope_consistency gate)
  - cite_roles.allowed + cite_roles.default     (citation_role gate)
  - anchors                                     (anchor_role_in_prose gate)

Universal: this loader is topic-agnostic. Adding a new topic = adding a new
TOML file. No code changes.
"""
from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

_PACK_DIR = Path(__file__).resolve().parent.parent / "topic_packs"


@dataclass(frozen=True, slots=True)
class TopicPack:
    topic: str
    display_name: str
    primary_system: str
    preferred_terms: tuple[str, ...]
    discouraged_terms: tuple[str, ...]
    endpoint: str
    cite_role_default: str
    cite_roles_allowed: tuple[str, ...]
    anchors: Mapping[str, str]
    length_caps: Mapping[str, int]
    min_words_per_citation: int
    outcome_nouns_extra: tuple[str, ...]
    direction_verbs_extra: tuple[str, ...]
    subjects_extra: tuple[str, ...]

    @property
    def has_scope_rules(self) -> bool:
        return bool(self.preferred_terms or self.discouraged_terms)

    @property
    def has_cite_roles(self) -> bool:
        return bool(self.cite_roles_allowed)

    @property
    def has_length_caps(self) -> bool:
        return bool(self.length_caps)


def load_topic_pack(topic: str, *, pack_dir: Path | None = None) -> TopicPack | None:
    base = pack_dir or _PACK_DIR
    path = base / f"{topic}.toml"
    if not path.exists():
        return None
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    scope = raw.get("scope", {})
    cite = raw.get("cite_roles", {})
    density = raw.get("density", {})
    triggers = raw.get("empirical_triggers", {})
    return TopicPack(
        topic=str(raw.get("topic", topic)),
        display_name=str(raw.get("display_name", topic.title())),
        primary_system=str(scope.get("primary_system", "")),
        preferred_terms=tuple(scope.get("preferred_terms", [])),
        discouraged_terms=tuple(scope.get("discouraged_terms", [])),
        endpoint=str(scope.get("endpoint", "")),
        cite_role_default=str(cite.get("default", "literature-reference")),
        cite_roles_allowed=tuple(cite.get("allowed", [])),
        anchors=MappingProxyType(dict(raw.get("anchors", {}))),
        length_caps=MappingProxyType({k: int(v) for k, v in raw.get("length_caps", {}).items()}),
        min_words_per_citation=int(density.get("min_words_per_citation", 0)),
        outcome_nouns_extra=tuple(triggers.get("outcome_nouns_extra", [])),
        direction_verbs_extra=tuple(triggers.get("direction_verbs_extra", [])),
        subjects_extra=tuple(triggers.get("subjects_extra", [])),
    )
