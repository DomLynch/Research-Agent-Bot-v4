#!/usr/bin/env bash
# LOC gate — fail if agent/ exceeds the 7,700 LOC ceiling.
# Tests, docs, scripts, supplement plugins, and topic_pack TOML do not count.
# Cap history: 3000 (initial) -> 5000 (Sprint-6 truth patch) -> 7500
# (Sprint 11.1 manuscript completion: narrative writers + reference resolver
# + supplement generator) -> 7600 (Sprint 14 MiMo→Gemma writer fallback:
# prevents SECTIONS_PENDING markers shipping in paper.md when MiMo runs
# away on a section) -> 7700 (Sprint 16 readiness classifier L1..L6:
# prevents L3-prose-without-numbers shipping as if it were L6 evidence).
# Every new module under the higher cap must delete or prevent a
# fake-evidence failure mode (receipts, validators, provenance, typed
# contracts), not buy prose polish or speculative abstraction.
set -euo pipefail

CEILING="${LOC_CEILING:-7700}"
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
