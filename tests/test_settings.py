"""Settings load + property tests — no network, no LLM calls."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent.settings import Settings, load_settings


def _clear_all(monkeypatch: pytest.MonkeyPatch) -> None:
    # Bypass .env loading so tests see a clean env, not whatever lives on disk.
    monkeypatch.setenv("RAB_SKIP_DOTENV", "1")
    for key in (
        "MIMO_API_KEY", "MIMO_BASE_URL", "MIMO_MODEL", "MIMO_TIMEOUT_SEC",
        "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "JUDGE_MODEL",
        "WRITER_MAX_RETRIES",
        "RESEARKA_DATABASE_URL", "RESEARKA_DATABASE_TOKEN",
        "NCBI_API_KEY", "SEMANTIC_SCHOLAR_API_KEY", "CORE_API_KEY",
        "CROSSREF_POLITE_EMAIL", "UNPAYWALL_EMAIL",
        "BOT_ENABLED", "DAILY_COST_CAP_USD", "RUNS_DIR",
    ):
        monkeypatch.delenv(key, raising=False)


def test_load_settings_returns_dataclass(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all(monkeypatch)
    assert isinstance(load_settings(), Settings)


def test_defaults_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all(monkeypatch)
    s = load_settings()
    assert s.mimo_base_url == "https://token-plan-sgp.xiaomimimo.com/v1"
    assert s.mimo_model == "mimo-v2.5-pro"
    assert s.judge_model == "google/gemma-4-31b-it"
    assert s.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert s.researka_database_url == "https://database.researka.org"
    assert s.writer_max_retries == 2
    assert s.daily_cost_cap_usd == 25.0
    assert s.bot_enabled is True
    assert s.runs_dir == "runs"
    assert s.loc_ceiling == 3000


def test_writer_configured_property(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all(monkeypatch)
    monkeypatch.setenv("MIMO_API_KEY", "tp-test")
    s = load_settings()
    assert s.writer_configured is True


def test_writer_not_configured_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all(monkeypatch)
    s = load_settings()
    assert s.writer_configured is False


def test_judge_configured_property(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    s = load_settings()
    assert s.judge_configured is True


def test_researka_configured_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all(monkeypatch)
    s = load_settings()
    assert s.researka_configured is False
    monkeypatch.setenv("RESEARKA_DATABASE_TOKEN", "tok-test")
    s2 = load_settings()
    assert s2.researka_configured is True


def test_bool_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all(monkeypatch)
    for true_val in ("1", "true", "yes", "on", "TRUE", "Yes"):
        monkeypatch.setenv("BOT_ENABLED", true_val)
        assert load_settings().bot_enabled is True
    for false_val in ("0", "false", "no", "off"):
        monkeypatch.setenv("BOT_ENABLED", false_val)
        assert load_settings().bot_enabled is False


def test_int_parsing_fallback_on_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all(monkeypatch)
    monkeypatch.setenv("WRITER_MAX_RETRIES", "not-a-number")
    assert load_settings().writer_max_retries == 2  # default


def test_settings_is_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all(monkeypatch)
    s = load_settings()
    with pytest.raises(FrozenInstanceError):
        s.mimo_api_key = "mutated"  # type: ignore[misc]
