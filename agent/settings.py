"""Centralised settings.

One source of truth for every config value. Loaded once per process via
`load_settings()`. No global mutable state, no magic. Reads `.env` if
present; environment variables take precedence over `.env`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    if os.environ.get("RAB_SKIP_DOTENV") == "1":
        return
    env_path = _REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    return _env(name, str(default)).lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    mimo_api_key: str
    mimo_base_url: str
    mimo_model: str
    mimo_timeout_sec: float

    openrouter_api_key: str
    openrouter_base_url: str
    judge_model: str

    writer_max_retries: int

    researka_database_url: str
    researka_database_token: str

    ncbi_api_key: str
    semantic_scholar_api_key: str
    core_api_key: str
    crossref_polite_email: str
    unpaywall_email: str

    bot_enabled: bool
    daily_cost_cap_usd: float

    runs_dir: str

    loc_ceiling: int = 7500
    # Sprint 12.9 Researka-as-primary-spine flags. When `researka_spine_trust`
    # is true, the eligibility pipeline short-circuits the LLM judge for
    # candidates tagged with a "researka:*" source (trusting the Tier-1
    # curation); the universal evidence contract still gates final include.
    # `researka_spine_retmax` is the per-call total budget across Researka's
    # three lanes (established/discovery/semantic) — bumped from the default
    # 100 to give the spine more candidates to draw from.
    researka_spine_trust: bool = True
    researka_spine_retmax: int = 300
    # Sprint 12.9 Task C: dual-pass extraction with LLM-adjudicated
    # disagreements. When enabled, every extraction runs a primary pass
    # + a strict-verify pass; pool-critical disagreements trigger an
    # adjudicator call. Doubles LLM cost on the extraction step but
    # rescues parse_failed / no_numerics cases and lets Methods honestly
    # claim "dual independent extraction". Set EXTRACTION_DUAL_PASS=false
    # to revert to single-pass.
    extraction_dual_pass: bool = True

    @property
    def writer_configured(self) -> bool:
        return bool(self.mimo_api_key) and bool(self.mimo_base_url)

    @property
    def judge_configured(self) -> bool:
        return bool(self.openrouter_api_key) and bool(self.judge_model)

    @property
    def researka_configured(self) -> bool:
        return bool(self.researka_database_url) and bool(self.researka_database_token)


def load_settings() -> Settings:
    _load_dotenv()
    return Settings(
        # Writer is MiniMax M3 (Anthropic-compatible endpoint). MIMO_* are
        # accepted as legacy aliases, but MINIMAX_* win when both are set so a
        # stale MiMo key in an old .env can never shadow the live M3 config.
        mimo_api_key=_env("MINIMAX_API_KEY") or _env("MIMO_API_KEY"),
        mimo_base_url=(
            _env("MINIMAX_BASE_URL") or _env("MIMO_BASE_URL")
            or "https://api.minimax.io/anthropic"
        ),
        mimo_model=_env("MINIMAX_MODEL") or _env("MIMO_MODEL") or "MiniMax-M3",
        mimo_timeout_sec=_float(
            "MINIMAX_TIMEOUT_SEC", _float("MIMO_TIMEOUT_SEC", 300.0),
        ),
        openrouter_api_key=_env("OPENROUTER_API_KEY"),
        openrouter_base_url=_env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        judge_model=_env("JUDGE_MODEL", "google/gemma-4-31b-it"),
        writer_max_retries=_int("WRITER_MAX_RETRIES", 2),
        researka_database_url=_env("RESEARKA_DATABASE_URL", "https://database.researka.org"),
        researka_database_token=_env("RESEARKA_DATABASE_TOKEN"),
        ncbi_api_key=_env("NCBI_API_KEY"),
        semantic_scholar_api_key=_env("SEMANTIC_SCHOLAR_API_KEY"),
        core_api_key=_env("CORE_API_KEY"),
        crossref_polite_email=_env("CROSSREF_POLITE_EMAIL"),
        unpaywall_email=_env("UNPAYWALL_EMAIL"),
        bot_enabled=_bool("BOT_ENABLED", True),
        daily_cost_cap_usd=_float("DAILY_COST_CAP_USD", 25.0),
        runs_dir=_env("RUNS_DIR", "runs"),
        researka_spine_trust=_env("RESEARKA_SPINE_TRUST", "true").lower() != "false",
        researka_spine_retmax=_int("RESEARKA_SPINE_RETMAX", 300),
        extraction_dual_pass=_env("EXTRACTION_DUAL_PASS", "true").lower() != "false",
    )
