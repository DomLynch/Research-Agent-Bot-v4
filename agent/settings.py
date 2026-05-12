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
        mimo_api_key=_env("MIMO_API_KEY"),
        mimo_base_url=_env("MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"),
        mimo_model=_env("MIMO_MODEL", "mimo-v2.5-pro"),
        mimo_timeout_sec=_float("MIMO_TIMEOUT_SEC", 300.0),
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
    )
