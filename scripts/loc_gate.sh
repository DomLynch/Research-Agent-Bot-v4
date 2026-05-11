#!/usr/bin/env bash
# LOC gate — fail if agent/ exceeds the 5,000 LOC ceiling.
# Tests, docs, scripts, supplement plugins, and topic_pack TOML do not count.
# Cap raised from 3000 -> 5000 once Sprint-6 truth-patch landed; every new
# module under the higher cap must delete or prevent a fake-evidence failure
# mode (receipts, validators, provenance), not buy prose polish.
set -euo pipefail

CEILING="${LOC_CEILING:-5000}"
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
