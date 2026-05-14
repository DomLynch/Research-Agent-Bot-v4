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
# -> 9500 (Sprint 46 DB-backed canonical claim feed:
# agent/researka_claims.py pulls GET /api/v1/topics/{topic}/facts and
# aggregates by canonical_phrase into gap-analyser-shaped claims with
# confidence derived from k_supp + CI presence + validator state +
# supersession. Replaces writer-receipt-derived snapshots, eliminating
# the writer-bug-corrupts-trigger failure mode that motivated the
# Sprints 14 / 26 / 32 / 37 patches — gap-analyser now reads from the
# curated Researka source of truth, not from receipts a buggy writer
# could poison.)
# -> 9700 (Sprint 49 frontier-model research-strategist layer:
# agent/frontier_review.py asks MiMo v2.5 Pro for the LENS over the
# deterministic top-N — non-obvious framing, tensions between specific
# studies, evidence gaps, 3 paper theses with novelty / evidence-
# strength / reviewer-risk scores + opportunity_score = strength *
# novelty / max(risk, 10). Prevents the "boring fact leaderboard
# masquerading as research output" failure mode: deterministic alone
# produces "rapamycin extends lifespan" (everyone knows that);
# deterministic + frontier produces "transient C57BL/6 effect sizes
# disagree with ITP feed-based UM-HET3 effects — timing/route/strain
# may dominate headline magnitude". Tolerant JSON parser, returns
# empty review with model='error:<reason>' on any failure so callers
# never crash.)
# -> 9750 (Sprint 50 tolerant JSON-truncation repair: live runs on
# longevity + fasting topics revealed MiMo can run out of tokens
# mid-stream — JSON ends inside an unclosed string and json.loads
# fails, silently collapsing all lens/tensions/gaps/theses fields to
# empty. _bracket_stack() + _try_repair_json() walk truncated text,
# find cut points after closing brackets / before commas, close the
# open bracket stack, and return the largest valid JSON prefix.
# raw_response surfaced in as_dict() for forensic audit. max_tokens
# bumped 3000 -> 4000 (MiMo runaway-safe ceiling per Sprint 14
# empirical calibration). Prevents the "silent lens loss when MiMo
# truncates" failure mode the auditor caught on the noisy-topic
# stress test.)
# Every new module under the higher cap must delete or prevent a
# fake-evidence failure mode (receipts, validators, provenance, typed
# contracts), not buy prose polish or speculative abstraction.
set -euo pipefail

CEILING="${LOC_CEILING:-9750}"
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
