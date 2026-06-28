from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace
from typing import Any

from scripts import run_alpha_cache_warm as warm


def test_default_cache_warm_domains_cover_unique_v4_seed_sets() -> None:
    assert warm._default_domains() == (
        "ai_research",
        "business_research",
        "economics_research",
        "finance_research",
        "longevity_research",
        "management_research",
        "marketing_research",
    )


def test_cache_warmer_runs_each_domain_and_fails_loud(monkeypatch: Any) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], *, check: bool, timeout: float | None) -> SimpleNamespace:
        calls.append(cmd)
        assert timeout == 900.0
        rc = 2 if cmd[cmd.index("--domain") + 1] == "finance_research" else 0
        return SimpleNamespace(returncode=rc)

    monkeypatch.setattr(sys, "argv", [
        "run_alpha_cache_warm.py",
        "--domains",
        "business_research,finance_research",
        "--top",
        "3",
        "--derived-topic-limit",
        "9",
        "--fact-probe-topics",
        "7",
    ])
    monkeypatch.setattr("scripts.run_alpha_cache_warm.subprocess.run", fake_run)

    assert warm.main() == 2
    assert [cmd[cmd.index("--domain") + 1] for cmd in calls] == [
        "business_research",
        "finance_research",
    ]
    assert all("--warm-backlog" in cmd for cmd in calls)
    assert all(cmd[cmd.index("--top") + 1] == "3" for cmd in calls)
    assert all(cmd[cmd.index("--derived-topic-limit") + 1] == "9" for cmd in calls)
    assert all(cmd[cmd.index("--fact-probe-topics") + 1] == "7" for cmd in calls)


def test_cache_warmer_continues_after_domain_timeout(monkeypatch: Any) -> None:
    calls: list[str] = []

    def fake_run(cmd: list[str], *, check: bool, timeout: float | None) -> SimpleNamespace:
        domain = cmd[cmd.index("--domain") + 1]
        calls.append(domain)
        assert timeout == 5.0
        if domain == "business_research":
            raise subprocess.TimeoutExpired(cmd, timeout)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sys, "argv", [
        "run_alpha_cache_warm.py",
        "--domains",
        "business_research,finance_research",
        "--per-domain-timeout-seconds",
        "5",
    ])
    monkeypatch.setattr("scripts.run_alpha_cache_warm.subprocess.run", fake_run)

    assert warm.main() == 2
    assert calls == ["business_research", "finance_research"]


def test_cache_warmer_treats_timeout_after_fullraw_progress_as_success(
    tmp_path: Any, monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_run(cmd: list[str], *, check: bool, timeout: float | None) -> SimpleNamespace:
        domain = cmd[cmd.index("--domain") + 1]
        calls.append(domain)
        assert timeout == 5.0
        if domain == "business_research":
            cache = tmp_path / "runs" / "_fullraw_in_progress_sweeps.json"
            cache.parent.mkdir(parents=True)
            cache.write_text('{"queued": {"event": {"status": "async_queued"}}}', encoding="utf-8")
            raise subprocess.TimeoutExpired(cmd, timeout)
        return SimpleNamespace(returncode=0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "run_alpha_cache_warm.py",
        "--domains",
        "business_research,finance_research",
        "--per-domain-timeout-seconds",
        "5",
    ])
    monkeypatch.setattr("scripts.run_alpha_cache_warm.subprocess.run", fake_run)

    assert warm.main() == 0
    assert calls == ["business_research", "finance_research"]
