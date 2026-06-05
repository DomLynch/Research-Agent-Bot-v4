"""Domain routing for specialist alpha-agent modules.

Domain metadata lives in `topic_packs/domains.toml`; code only resolves
paths and enforces dry-run fences. Default domain remains longevity.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PACK_DIR = _ROOT / "topic_packs"
_DOMAINS_TOML = _PACK_DIR / "domains.toml"
_DEFAULT_DOMAIN = "longevity"


@dataclass(frozen=True, slots=True)
class DomainProfile:
    slug: str
    display_name: str
    seed_topics_path: Path
    source_policy_path: Path
    claim_schema_path: Path
    dry_run_only: bool

    def as_metadata(self) -> dict[str, str | bool]:
        return {
            "slug": self.slug,
            "display_name": self.display_name,
            "seed_topics_path": self.seed_topics_path.name,
            "source_policy_path": self.source_policy_path.name,
            "claim_schema_path": self.claim_schema_path.name,
            "dry_run_only": self.dry_run_only,
        }


def _domains_raw(path: Path = _DOMAINS_TOML) -> dict[str, object]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        data = {}
    domains = data.get("domains") if isinstance(data, dict) else None
    return domains if isinstance(domains, dict) else {}


def domain_choices() -> tuple[str, ...]:
    choices = tuple(sorted(_domains_raw()))
    return choices or (_DEFAULT_DOMAIN,)


def load_domain_profile(slug: str | None = None) -> DomainProfile:
    key = (slug or _DEFAULT_DOMAIN).strip() or _DEFAULT_DOMAIN
    raw = _domains_raw().get(key)
    if not isinstance(raw, dict):
        raise ValueError(f"unknown domain: {key}")

    def _pack_path(field: str) -> Path:
        name = str(raw.get(field) or "").strip()
        if not name:
            raise ValueError(f"domain {key} missing {field}")
        return _PACK_DIR / name

    return DomainProfile(
        slug=key,
        display_name=str(raw.get("display_name") or key),
        seed_topics_path=_pack_path("seed_topics_path"),
        source_policy_path=_pack_path("source_policy_path"),
        claim_schema_path=_pack_path("claim_schema_path"),
        dry_run_only=bool(raw.get("dry_run_only", False)),
    )
