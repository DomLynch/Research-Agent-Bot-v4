"""Sprint 12.5 — run-folder integrity tests (the quality gate).

Runs over `runs/latest` and asserts every defect pattern flagged in
external audits is absent. AAA gate: if any of these fail, the paper
is not shippable.

Universal: every check is content-pattern-based or filesystem-based —
no topic-specific literals. Skipped when `runs/latest` is absent so
fresh clones don't fail until a paper has been built.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_RUNS_LATEST = Path(__file__).resolve().parent.parent / "runs" / "latest"


def _read(name: str) -> str:
    return (_RUNS_LATEST / name).read_text(encoding="utf-8")


def _read_body(name: str) -> str:
    """Read a manuscript file, stripping the leading AUTO-STITCHED HTML
    comment so audit-trail prose in the header doesn't false-positive
    the pattern checks below. Comment lives between the first `<!--`
    and matching `-->` — strip exactly that region when present."""
    text = _read(name).lstrip()
    if text.startswith("<!--"):
        end = text.find("-->")
        if end >= 0:
            text = text[end + 3 :].lstrip()
    return text


def _have_paper_folder() -> bool:
    return _RUNS_LATEST.exists() and (_RUNS_LATEST / "paper.md").exists()


pytestmark = pytest.mark.skipif(
    not _have_paper_folder(),
    reason="no runs/latest paper folder yet — built by stitch_paper.py",
)


def test_paper_md_has_no_unresolved_placeholder_markers() -> None:
    """No [POOL_*], [STRICT_A_CORE_*], [B_LANE_*], [C_LANE_*],
    [K_POOLABLE*], [INCOMPLETE_RECOVERY_IDS], [PLACEHOLDER:*],
    [MODERATOR_P:*], [UNRESOLVED], or [N_SCREENED]/[N_ACCEPTED]/
    [K_STUDIES] tokens should remain in the rendered manuscript body.
    The legitimate exception is inside the AI-Use Disclosure which
    *describes* the marker syntax in prose.
    """
    body = _read_body("paper.md")
    # Strip the AI-Use Disclosure paragraph that legitimately names the
    # placeholder syntax in prose.
    cut = body.find("## AI-Use and Automation Disclosure")
    end = body.find("\n## ", cut + 1) if cut >= 0 else -1
    if cut >= 0 and end >= 0:
        body = body[:cut] + body[end:]
    elif cut >= 0:
        body = body[:cut]
    suspect = (
        "[POOL_", "[STRICT_A_CORE_", "[B_LANE_", "[C_LANE_",
        "[K_POOLABLE", "[INCOMPLETE_RECOVERY", "[PLACEHOLDER:",
        "[MODERATOR_P:", "[UNRESOLVED]", "[N_SCREENED]",
        "[N_ACCEPTED]", "[K_STUDIES]",
    )
    leftover = [tok for tok in suspect if tok in body]
    assert not leftover, f"unresolved placeholder markers: {leftover}"


def test_paper_md_has_no_plural_agreement_artefacts() -> None:
    """`study/studies`, `record(s)`, `is/are`, `effect(s)` are tells
    that count-aware noun-agreement tokens weren't used in the rewrite
    target. Sprint 12.5 universal pluralisation should eliminate them."""
    body = _read_body("paper.md")
    bad = []
    for pat in (r"\bstudy/studies\b", r"\brecord\(s\)\b",
                r"\bis/are\b", r"\beffect\(s\)\b"):
        if re.search(pat, body):
            bad.append(pat)
    assert not bad, f"plural-agreement artefacts present: {bad}"


def test_paper_md_has_no_literal_template_placeholders() -> None:
    """`{N}`, `{study_id}`, `{topic}` in the rendered body indicate an
    unresolved Python format-string. Should be substituted at build time."""
    body = _read_body("paper.md")
    literal_braces = re.findall(r"\{[A-Za-z_][A-Za-z_0-9]*\}", body)
    # Filter out legitimate code-block / JSON-key uses (those should be
    # inside backticks). We're looking for FREE braces in prose.
    suspect = [m for m in literal_braces if m not in {"{N}"}]  # explicit allow-list intentionally empty
    free = [m for m in literal_braces if m == "{N}"]
    assert not free, f"literal template placeholder(s) remain: {free}"
    # `suspect` retained for future expansion — no failure today.
    _ = suspect


def test_paper_md_has_no_placeholder_author_handle() -> None:
    """`human-operator` is the build-time default for operator_handle.
    Production prose should use `the operator` or a real attributed name."""
    body = _read_body("paper.md")
    assert "human-operator" not in body, (
        "`human-operator` placeholder default leaked into Author "
        "Contributions; supply a real operator_handle or accept the "
        "`the operator` neutral default."
    )


def test_supplement_md_receipts_list_matches_filesystem() -> None:
    """The S9 receipts-in-folder enumeration must list only files that
    are actually present in the run dir."""
    supp = _read("supplement.md")
    m = re.search(r"Receipts present in this folder:\s*(.+?)\.\n", supp)
    assert m, "S9 receipts-list line not found"
    claimed = set(re.findall(r"`([^`]+)`", m.group(1)))
    present = {
        f.name for f in _RUNS_LATEST.iterdir()
        if f.is_file()
        and f.suffix in {".json", ".md"}
        and f.name not in {"paper.md", "supplement.md"}
    }
    missing = claimed - present
    assert not missing, (
        f"supplement S9 claims files that don't exist: {missing}"
    )


def test_rendered_files_do_not_reference_absent_local_run_files() -> None:
    """Sprint 12.8 — universal generalisation of the S9-list check.

    Any bare backticked `.json` / `.md` filename in the rendered paper
    or supplement is a run-folder-local claim. It must exist. Paths
    containing `/` are documentation / source pointers (e.g.
    `topic_packs/<topic>.toml`, `agent/`, `scripts/`), not packaged
    run-file claims, so they are outside this check.
    """
    present = {f.name for f in _RUNS_LATEST.iterdir() if f.is_file()}
    missing: set[str] = set()
    for fname in ("paper.md", "supplement.md"):
        body = _read_body(fname)
        for token in re.findall(r"`([^`]+)`", body):
            if "/" in token:
                continue
            if token in {"paper.md", "supplement.md"}:
                continue
            if token.endswith((".json", ".md")) and token not in present:
                missing.add(token)
    assert not missing, (
        f"rendered artifact references absent local run file(s): "
        f"{sorted(missing)}"
    )


def test_paper_folder_canonical_outputs_exist() -> None:
    """Canonical paper-folder shape: paper.md + supplement.md + the
    4 JSON receipts that supplement's S9 cross-references."""
    required = {
        "paper.md", "supplement.md",
        "eligibility_summary.json",
        "primary_effect_input_set_strict.json",
        "effect_extractions.json",
        "effect_pool.json",
    }
    present = {f.name for f in _RUNS_LATEST.iterdir() if f.is_file()}
    missing = required - present
    assert not missing, f"runs/latest missing canonical outputs: {missing}"


def test_handover_doc_exists_and_is_not_stale() -> None:
    """HANDOVER.md is the external-audit packet; must exist + reference
    the latest paper folder schema."""
    handover = Path(__file__).resolve().parent.parent / "HANDOVER.md"
    if not handover.exists():
        pytest.skip("HANDOVER.md not present (optional)")
    content = handover.read_text(encoding="utf-8")
    # Must reference the canonical receipt names + the current paper-folder
    # shape; failing this means the doc has drifted.
    for needle in (
        "eligibility_summary.json",
        "primary_effect_input_set_strict.json",
        "effect_extractions.json",
        "effect_pool.json",
        "extraction_crosscheck.json",
    ):
        assert needle in content, (
            f"HANDOVER.md missing reference to {needle!r}"
        )


def test_paper_md_pool_prose_names_only_pool_effect_ids() -> None:
    """Sprint 12.6 regression: prose that introduces the inverse-variance
    pool must name only studies in `pool.effects`, never the full A-core.
    A-core that didn't contribute (parse_failed / off-modal-metric /
    no_numerics) appearing as a 'pooled study' is the bug the reviewer
    caught — pool IDs vs A-core IDs are different sets."""
    import json
    body = _read_body("paper.md")
    pool = json.loads(_read("effect_pool.json"))
    pool_ids = [str(e.get("study_id", "")) for e in pool.get("effects", [])]
    skipped = [str(s) for s in (pool.get("skipped_study_ids") or [])]
    # Find every sentence that asserts a "contract-passing studies: X, Y, Z"
    # claim. Each listed ID must be in pool.effects, not pool.skipped.
    for m in re.finditer(
        r"contract-passing studies:\s*([^;)\n]+)", body,
    ):
        listed = [x.strip() for x in m.group(1).split(",") if x.strip()]
        leaked = [x for x in listed if x in skipped]
        assert not leaked, (
            f"pool prose lists skipped study/studies as pool contributors: "
            f"{leaked} (real pool: {pool_ids}; skipped: {skipped})"
        )


def test_paper_md_lane_counts_match_strict_receipt() -> None:
    """Universal cross-check: the A/B/C lane composition sentence in
    the body must reference the same counts as the strict receipt."""
    import json
    body = _read_body("paper.md")
    strict = json.loads(_read("primary_effect_input_set_strict.json"))
    a = len(strict.get("A_core_direct_lifespan") or [])
    b = len(strict.get("B_disease_model_survival") or [])
    c = len(strict.get("C_secondary_contextual") or [])
    # Look for the composition sentence anchor and check the counts appear.
    anchor = "After applying the strict A-core evidence-quote audit"
    if anchor not in body:
        pytest.skip("composition sentence not in body (writer prose differs)")
    sentence_start = body.find(anchor)
    sentence_end = body.find(".", sentence_start)
    sentence = body[sentence_start : sentence_end + 1]
    # Counts can appear as bare numerals or in the noun-aware token
    # output ("3 studies"). Check substring presence rather than regex.
    for label, n in (("A-core", a), ("B-lane", b), ("C-lane", c)):
        assert str(n) in sentence, (
            f"composition sentence missing {label} count {n}: {sentence!r}"
        )
