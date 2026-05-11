#!/usr/bin/env bash
# LOC gate — fail if agent/ exceeds the 3,000 LOC ceiling.
# Tests, docs, scripts, supplement plugins, and topic_pack TOML do not count.
set -euo pipefail

CEILING="${LOC_CEILING:-3000}"
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
