import json
import sys
from typing import Any

import scripts.build_topic_evidence_run as er


def test_fetch_facts_records_search_trace(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """OpenSeeker-style trace: each query slice records kind/query/facts/status."""
    class _S:
        researka_database_url = "https://db.example"
        researka_database_token = "tok"

    monkeypatch.setattr(er, "load_settings", lambda: _S())
    monkeypatch.setattr(er, "_topic_fact_keys", lambda _t: ["k1"])
    monkeypatch.setattr(er, "_diverse_queries", lambda _t, **_kw: ["q1", "q2"])

    def _fake_fetch_one(job, _base, _hdr, _topic):  # type: ignore[no-untyped-def]
        kind, _value = job
        rows = [{"fact_id": "1"}] if kind == "tier1" else []
        return er.FetchResult(rows, "ok")

    monkeypatch.setattr(er, "_fetch_one", _fake_fetch_one)
    trace: list[dict[str, Any]] = []
    facts = er._fetch_facts("t", trace=trace)
    assert facts  # tier1 slice returned a fact
    assert trace, "search trace must record every query slice"
    kinds = {row["kind"] for row in trace}
    assert "tier1" in kinds
    assert all(set(row) == {"kind", "query", "facts", "status", "errors"} for row in trace)
    assert any(row["status"] == "ok" for row in trace)


def test_fetch_timeout_is_not_empty_evidence(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class _S:
        researka_database_url = "https://db.example"
        researka_database_token = "tok"

    monkeypatch.setattr(er, "load_settings", lambda: _S())
    monkeypatch.setattr(er, "_topic_fact_keys", lambda _t: ["k1"])
    monkeypatch.setattr(er, "_diverse_queries", lambda _t, **_kw: ["q1"])
    monkeypatch.setattr(
        er, "_fetch_one",
        lambda *_args: er.FetchResult([], "timeout", ("read_timeout",)),
    )

    trace: list[dict[str, Any]] = []
    assert er._fetch_facts("t", trace=trace) == []
    assert trace
    assert {row["status"] for row in trace} == {"timeout"}
    assert er._all_primary_fetches_failed(trace) is True


def test_empty_fact_run_writes_empty_frontier_sidecars(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    class _S:
        writer_configured = False

    def _fetch_empty(
        _topic: str, *, trace: list[dict[str, Any]], domain: str = "longevity",
    ) -> list[dict[str, Any]]:
        trace.append({
            "kind": "tier1", "query": "empty_topic", "facts": 0,
            "status": "ok", "errors": [],
        })
        return []

    monkeypatch.setattr(er, "_RUNS", tmp_path / "runs")
    monkeypatch.setattr(er, "_fetch_facts", _fetch_empty)
    monkeypatch.setattr(er, "load_settings", lambda: _S())
    monkeypatch.setattr(
        sys, "argv",
        ["build_topic_evidence_run.py", "--topic", "empty_topic", "--top", "5"],
    )

    assert er.main() == 0
    run_dir = next((tmp_path / "runs").glob("empty_topic-evidence-*"))
    review = json.loads((run_dir / "frontier_review.json").read_text())
    manifest = json.loads((run_dir / "MANIFEST.json").read_text())

    assert (run_dir / "frontier_review.md").exists()
    assert review["model"] == "error:no_facts"
    assert manifest["frontier_model"] == "error:no_facts"
    assert "frontier_json" in manifest["files"]


def test_primary_fetch_failure_does_not_write_empty_frontier(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    def _fetch_timeout(
        _topic: str, *, trace: list[dict[str, Any]], domain: str = "longevity",
    ) -> list[dict[str, Any]]:
        trace.append({
            "kind": "tier1", "query": "empty_topic", "facts": 0,
            "status": "timeout", "errors": ["ReadTimeout"],
        })
        return []

    monkeypatch.setattr(er, "_RUNS", tmp_path / "runs")
    monkeypatch.setattr(er, "_fetch_facts", _fetch_timeout)
    monkeypatch.setattr(
        sys, "argv",
        ["build_topic_evidence_run.py", "--topic", "empty_topic", "--top", "5"],
    )

    assert er.main() == 2
    run_dir = next((tmp_path / "runs").glob("empty_topic-evidence-*"))
    status = json.loads((run_dir / "retrieval_status.json").read_text())

    assert status == {"status": "failed", "reason": "all_primary_fetches_failed"}
    assert not (run_dir / "frontier_review.json").exists()


def test_child_topic_fetches_parent_facts_before_classifying(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    class _S:
        writer_configured = False

    calls: list[str] = []

    def _fetch(
        topic: str, *, trace: list[dict[str, Any]], domain: str = "longevity",
    ) -> list[dict[str, Any]]:
        calls.append(topic)
        trace.append({"kind": "normal", "query": topic, "facts": 1, "status": "ok", "errors": []})
        return [{
            "fact_id": topic,
            "canonical_phrase": f"{topic} improved bounded reliability",
            "source_paper": {"doi": f"10/{topic}", "title": topic},
        }]

    monkeypatch.setattr(er, "_RUNS", tmp_path / "runs")
    monkeypatch.setattr(er, "_fetch_facts", _fetch)
    monkeypatch.setattr(er, "load_settings", lambda: _S())
    monkeypatch.setattr(
        sys, "argv",
        [
            "build_topic_evidence_run.py",
            "--topic", "parent_bounded_child",
            "--parent-topic", "parent",
            "--top", "5",
            "--no-frontier",
        ],
    )

    assert er.main() == 0
    run_dir = next((tmp_path / "runs").glob("parent_bounded_child-evidence-*"))
    facts = json.loads((run_dir / "all_facts.json").read_text())

    assert calls == ["parent", "parent_bounded_child"]
    assert {f["fact_id"] for f in facts} == {"parent", "parent_bounded_child"}


def test_diverse_queries_use_data_facets_not_static_runtime_terms() -> None:
    queries = er._diverse_queries(
        "berberine", facets=("glucose metabolism", "randomized trials"),
    )

    assert "berberine" in queries
    assert "glucose metabolism" in queries
    assert "randomized trials" in queries
    assert not any(q == "berberine mortality" for q in queries)


def test_fetch_facts_expands_with_source_title_facets(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class _S:
        researka_database_url = "https://db.example"
        researka_database_token = "tok"

    calls: list[str] = []

    def _fake_fetch_one(job, _base, _hdr, _topic):  # type: ignore[no-untyped-def]
        _kind, query = job
        calls.append(query)
        if query == "berberine":
            return er.FetchResult([{
                "fact_id": "1",
                "canonical_phrase": "berberine improved a measured endpoint",
                "source_paper": {
                    "title": "Meta-analysis review: berberine improves glucose metabolism",
                },
            }], "ok")
        if query == "glucose metabolism":
            return er.FetchResult([{
                "fact_id": "2",
                "canonical_phrase": "glucose metabolism changed in an independent source",
                "source_paper": {"title": "Independent glucose metabolism trial"},
            }], "ok")
        return er.FetchResult([], "ok")

    monkeypatch.setattr(er, "load_settings", lambda: _S())
    monkeypatch.setattr(er, "_topic_fact_keys", lambda _t: [])
    monkeypatch.setattr(er, "_fetch_one", _fake_fetch_one)

    trace: list[dict[str, Any]] = []
    facts = er._fetch_facts("berberine", trace=trace)

    assert {fact["fact_id"] for fact in facts} == {"1", "2"}
    assert "glucose metabolism" in calls
    assert "meta analysis" not in calls
    assert "analysis review" not in calls
    assert any(row["query"] == "glucose metabolism" for row in trace)
