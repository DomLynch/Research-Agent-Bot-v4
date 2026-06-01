from typing import Any

import scripts.build_topic_evidence_run as er


def test_fetch_facts_records_search_trace(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """OpenSeeker-style trace: each query slice records kind/query/facts/status."""
    class _S:
        researka_database_url = "https://db.example"
        researka_database_token = "tok"

    monkeypatch.setattr(er, "load_settings", lambda: _S())
    monkeypatch.setattr(er, "_topic_fact_keys", lambda _t: ["k1"])
    monkeypatch.setattr(er, "_diverse_queries", lambda _t: ["q1", "q2"])

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
    monkeypatch.setattr(er, "_diverse_queries", lambda _t: ["q1"])
    monkeypatch.setattr(
        er, "_fetch_one",
        lambda *_args: er.FetchResult([], "timeout", ("read_timeout",)),
    )

    trace: list[dict[str, Any]] = []
    assert er._fetch_facts("t", trace=trace) == []
    assert trace
    assert {row["status"] for row in trace} == {"timeout"}
    assert er._all_primary_fetches_failed(trace) is True
