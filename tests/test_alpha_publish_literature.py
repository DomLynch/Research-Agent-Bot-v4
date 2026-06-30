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


def test_select_boundary_papers_preserves_fact_backed_floor_before_metadata() -> None:
    topic = "supply_chain_resilience_performance"
    fact_backed = [
        {
            "doi": f"10.7000/scr-{idx}",
            "title": title,
            "source_fact": {
                "canonical_phrase": phrase,
                "population": "firms",
                "intervention": "supply chain resilience",
                "endpoint": endpoint,
                "source_tier": "fullraw_abstract",
            },
        }
        for idx, (title, endpoint, phrase) in enumerate((
            (
                "Evaluating supply resilience performance during operational shocks",
                "business outcome",
                "relative weights for resilience criteria were estimated during shocks",
            ),
            (
                "Supply chain resilience and firm performance",
                "firm performance",
                "supply chain resilience did not significantly improve firm performance",
            ),
            (
                "Factors affecting supply chain resilience and supply chain performance",
                "supply chain performance",
                "collaboration had positive significant effects on supply chain performance",
            ),
            (
                "Resilience effects on supply chain performance of manufacturers",
                "supply chain performance",
                "agility significantly affected supply chain performance",
            ),
            (
                "Supply chain disruption and performance of manufacturing firms",
                "supply chain performance",
                "resilience had a significant positive effect on supply chain performance",
            ),
            (
                "Relational practices in supply chain resilience for performance",
                "supply chain performance",
                "network practices moderated the resilience to performance relationship",
            ),
        ))
    ]
    metadata_only = [
        {
            "doi": f"10.7000/meta-{idx}",
            "title": title,
            "source_fact": {
                "canonical_phrase": f"Title-level source match: {title}",
                "endpoint": "source-literature relevance",
                "source_tier": "paper_metadata",
            },
        }
        for idx, title in enumerate((
            "Industry 4.0 enables supply chain resilience and supply chain performance",
            "Exposure to risks: what matters most to supply chain resilience performance",
            "Forecasting supply chain resilience performance using grey prediction",
        ))
    ]

    selected = literature.select_boundary_papers(
        topic,
        [*fact_backed[:3], *metadata_only[:2], *fact_backed[3:], metadata_only[2]],
        5,
        strict_topic_coverage=True,
    )

    assert len(selected) == 5
    assert literature.substantive_fact_count(selected) == 5
    assert literature.source_identity_count(selected, require_substantive=True) == 5
    assert all(
        paper["source_fact"]["source_tier"] == "fullraw_abstract"
        for paper in selected
    )


def test_non_bio_selection_prefers_second_directional_receipt() -> None:
    topic = "digital_transformation_firm"
    papers = [
        {
            "doi": f"10.8100/dtf-{idx}",
            "title": title,
            "source_fact": {
                "canonical_phrase": phrase,
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": endpoint,
                "source_tier": "fullraw_abstract",
            },
        }
        for idx, (title, endpoint, phrase) in enumerate((
            (
                "Digital transformation and firm profitability",
                "firm profitability",
                "digital transformation significantly increases firm profitability",
            ),
            (
                "Digital transformation firm implementation context",
                "implementation context",
                "digital transformation adoption varies across firm settings",
            ),
            (
                "Digital transformation firm operating model",
                "operating model",
                "digital transformation changes operating model descriptions",
            ),
            (
                "Digital transformation firm governance context",
                "governance context",
                "digital transformation governance differs across firms",
            ),
            (
                "Digital transformation firm capability map",
                "capability map",
                "digital transformation capability bundles are described in firms",
            ),
            (
                "Digital transformation and firm revenue",
                "firm revenue",
                "digital transformation increased firm revenue by 12 percent",
            ),
        ), start=1)
    ]

    selected = literature.select_boundary_papers(
        topic, papers, 5, profile_slug="business_research",
    )
    roles = [
        literature._paper_evidence_role(paper, topic, "business_research")
        for paper in selected
    ]

    assert len(selected) == 5
    assert literature.substantive_fact_count(selected) == 5
    assert literature.source_identity_count(selected, require_substantive=True) == 5
    assert "10.8100/dtf-6" in {paper["doi"] for paper in selected}
    assert roles.count("directional association") == 2
    assert literature.boundary_quality(
        topic, papers, 5, profile_slug="business_research",
    ) == (True, "ok")


def test_fullraw_relevant_papers_honors_researka_variant_cap(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fullraw(query: str, _limit: int) -> list[dict[str, Any]]:
        calls.append(query)
        return []

    monkeypatch.setenv("RESEARKA_FULLRAW_MAX_VARIANTS", "1")
    monkeypatch.setattr(literature, "_fullraw_topic_papers", fullraw)

    assert literature._fullraw_relevant_papers(
        "platform_strategy_network_effects", 5, set(),
    ) == []
    assert calls == ["platform strategy network performance"]
