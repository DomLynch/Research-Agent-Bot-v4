from __future__ import annotations

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

    def fake_run(cmd: list[str], *, check: bool) -> SimpleNamespace:
        calls.append(cmd)
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
