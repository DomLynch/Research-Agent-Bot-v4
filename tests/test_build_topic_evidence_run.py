

def test_fetch_facts_records_search_trace(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """OpenSeeker-style trace: each query slice records kind/query/facts/status."""
    import build_topic_evidence_run as er

    class _S:
        researka_database_url = "https://db.example"
        researka_database_token = "tok"

    monkeypatch.setattr(er, "load_settings", lambda: _S())
    monkeypatch.setattr(er, "_topic_fact_keys", lambda _t: ["k1"])
    monkeypatch.setattr(er, "_diverse_queries", lambda _t: ["q1", "q2"])

    def _fake_fetch_one(job, _base, _hdr, _topic):  # type: ignore[no-untyped-def]
        kind, _value = job
        return [{"fact_id": "1"}] if kind == "tier1" else []

    monkeypatch.setattr(er, "_fetch_one", _fake_fetch_one)
    trace: list[dict] = []
    facts = er._fetch_facts("t", trace=trace)
    assert facts  # tier1 slice returned a fact
    assert trace, "search trace must record every query slice"
    kinds = {row["kind"] for row in trace}
    assert "tier1" in kinds
    assert all(set(row) == {"kind", "query", "facts", "status"} for row in trace)
    assert any(row["status"] == "ok" for row in trace)
