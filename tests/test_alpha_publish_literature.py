import json
import urllib.request
from typing import Any

from pytest import MonkeyPatch

from scripts import alpha_publish_literature as literature


class _Response:
    def __init__(self, payload: list[dict[str, Any]]) -> None:
        self._payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_fetch_papers_enriches_fullraw_metadata_with_adjacent_fact_rows(
    monkeypatch: MonkeyPatch,
) -> None:
    topic = "platform_strategy_network_effects"
    meta_title = "Platform strategy network effects overview"
    fact_rows: list[dict[str, Any]] = []
    title_suffixes = ("overview", "adoption", "governance", "pricing", "complementors")
    for idx, suffix in enumerate(title_suffixes):
        paper_id = "meta-0" if idx == 0 else f"fact-{idx}"
        title = meta_title if idx == 0 else f"Platform strategy network effects {suffix}"
        fact_rows.append({
            "paper_id": paper_id,
            "canonical_phrase": (
                f"platform strategy network effects changed firm performance "
                f"metric {idx}"
            ),
            "population": f"business platform sample {idx}",
            "intervention": "platform strategy network effects",
            "metric": f"firm performance metric {idx}",
            "source_tier": "tier2",
            "paper": {
                "id": paper_id,
                "doi": f"10.1000/platform-{idx}",
                "title": title,
                "publication_year": 2020 + idx,
            },
        })

    monkeypatch.setattr(
        literature,
        "_fullraw_relevant_papers",
        lambda _topic, _limit, _seen: [{
            "id": "meta-0",
            "title": meta_title,
            "url": "https://example.test/platform-meta",
            "source_fact": {
                "canonical_phrase": f"Title-level source match: {meta_title}",
                "endpoint": "source-literature relevance",
                "source_tier": "paper_metadata",
            },
        }],
    )

    def urlopen(request: Any, *, timeout: float) -> _Response:
        body = json.loads(request.data.decode("utf-8"))
        if body["query"] == meta_title:
            assert timeout == 8.0
            return _Response(fact_rows)
        return _Response([])

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    settings = type("Settings", (), {
        "researka_database_url": "https://database.example",
        "researka_database_token": "token",
    })()

    papers = literature.fetch_papers(
        topic,
        5,
        domain="business_research",
        settings_loader=lambda: settings,
    )

    selected = literature.select_boundary_papers(
        topic,
        papers,
        5,
        strict_topic_coverage=True,
    )
    assert len(selected) == 5
    assert literature.substantive_fact_count(selected) == 5
    assert literature.source_identity_count(selected, require_substantive=True) == 5
    assert literature.boundary_quality(
        topic,
        papers,
        5,
        strict_topic_coverage=True,
        profile_slug="business_research",
    ) == (True, "ok")
