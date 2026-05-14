#!/usr/bin/env bash
# LOC gate — fail if agent/ exceeds the 9,400 LOC ceiling.
# Tests, docs, scripts, supplement plugins, and topic_pack TOML do not count.
# Cap history: 3000 (initial) -> 5000 (Sprint-6 truth patch) -> 7500
# (Sprint 11.1 manuscript completion: narrative writers + reference resolver
# + supplement generator) -> 7600 (Sprint 14 MiMo→Gemma writer fallback:
# prevents SECTIONS_PENDING markers shipping in paper.md when MiMo runs
# away on a section) -> 7700 (Sprint 16 readiness classifier L1..L6:
# prevents L3-prose-without-numbers shipping as if it were L6 evidence)
# -> 7800 (Sprint 18 sentinel repair plan: makes silently-missing
# canonical anchor papers actionable instead of unspoken)
# -> 7900 (Sprint 19 extraction confidence: derives per-study 0..1
# confidence + needs_human_audit flag from dual-pass provenance —
# prevents low-confidence extractions sliding into the pool silent)
# -> 8000 (Sprint 20 manual-audit overlay: per-run JSON capturing
# human decisions on flagged extractions + sentinels — turns Sprint
# 18 + 19 fail-states into closable audit-trail items)
# -> 8200 (Sprint 21 risk-of-bias adapter: canonical SYRCLE / Cochrane-
# RoB-2 / ROBINS-I item lists + per-study assessment loader +
# markdown renderer — prevents the "no RoB section" silent gap that
# is desk-rejection grounds at any synthesis-eligible journal)
# -> 8400 (Sprint 22 submission package: cover letter, title page,
# PRISMA-2020 checklist, manifest bundle — prevents the "operator
# submits without a checklist" failure mode that triggers desk
# return at most synthesis journals)
# -> 8500 (Sprint 23 maturity router: maps readiness + pool count to
# a paper-type with explicit section list + forbidden-claims —
# prevents the "k=1 paper claiming meta-analytic certainty" failure
# mode by tying prose contract to evidence ladder)
# -> 8700 (Sprint 24 Researka publishing object model: typed
# EvidenceReceipt / ClaimCard / StudyCard schemas + bundler — turns
# the existing per-receipt artifacts into a single typed upload unit
# for Researka-style portals, locking the data contract)
# -> 8900 (Sprint 27 dual-agent extraction audit: parses the dual-pass
# reviewer-provenance tag into a per-study agent-review state with
# per-field agreement booleans — surfaces the cross-check layer that
# was previously hidden inside the reviewer string)
# -> 9000 (Sprints 31-35: bridge the engine→writer truth gap. Paper-
# type-aware writer preamble (maturity_router.writer_preamble) + mid-
# sentence-truncation hard gate + universal honesty rewrites for the
# 'single LLM' / 'human review' wording. Prevents writer from emitting
# 'quantitative synthesis' titling when k_pool=0.)
# -> 9200 (Sprint 39 Evidence Index pivot: agent/evidence_index.py
# adds typed ClaimAtom + EvidenceIndex layer aggregating paper-folder
# receipts into a per-topic 0..100 confidence snapshot. Strategic
# product reset — paper writer becomes one export module; the living
# evidence map becomes the core product. Sprints 40-41 fold delta
# detection + CLI within this cap.)
# -> 9400 (Sprint 44 v4 gap-analyser: agent/gap_analyzer.py emits
# typed PublishOpportunity payloads that gate when v3 should write a
# paper. Prevents the "v3 writes a manuscript with no evidence-based
# signal" failure mode by tying the trigger to receipt-derived
# confidence + delta thresholds.)
# Every new module under the higher cap must delete or prevent a
# fake-evidence failure mode (receipts, validators, provenance, typed
# contracts), not buy prose polish or speculative abstraction.
set -euo pipefail

CEILING="${LOC_CEILING:-9400}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

COUNT=$(find "$ROOT/agent" -name "*.py" -not -path "*/__pycache__/*" 2>/dev/null \
    | xargs -I {} cat "{}" 2>/dev/null \
    | wc -l \
    | tr -d ' ')

if [ "$COUNT" -gt "$CEILING" ]; then
    echo "FAIL: agent/ LOC = $COUNT exceeds ceiling $CEILING" >&2
    exit 1
fi

echo "OK: agent/ LOC = $COUNT / $CEILING"
