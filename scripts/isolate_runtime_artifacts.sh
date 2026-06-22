#!/usr/bin/env bash
set -euo pipefail

dry_run=0
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=1
elif [[ $# -gt 0 ]]; then
  echo "usage: $0 [--dry-run]" >&2
  exit 2
fi

root="$(git rev-parse --show-toplevel)"
cd "$root"

exclude_file=".git/info/exclude"
exclude_patterns=(
  "runs/_daily_ledger/"
  "runs/_publish_queue.json"
  "runs/_publish_queue.json.tmp"
  "runs/_publish_queue.*.json"
  "runs/_publish_queue*.json.lock"
  "runs/_publish_queue*.json.tmp"
  "runs/_retracted_holds/"
  "runs/_topics_discovery/"
  "runs/_curator_cycles/"
  "runs/_business_diagnostics/"
  "runs/_ai_results_index_scale/"
  "runs/_domain_inventory/"
  "runs/latest [0-9]*"
)

tracked_count="$(git ls-files runs | wc -l | tr -d ' ')"
skip_count_before="$(
  git ls-files -v runs | awk '$1 == "S" {c++} END {print c + 0}'
)"

if [[ "$dry_run" -eq 0 ]]; then
  touch "$exclude_file"
  for pattern in "${exclude_patterns[@]}"; do
    grep -Fxq "$pattern" "$exclude_file" || printf '%s\n' "$pattern" >> "$exclude_file"
  done
  while IFS= read -r path; do
    git update-index --skip-worktree -- "$path"
  done < <(git ls-files runs)
fi

skip_count_after="$(
  git ls-files -v runs | awk '$1 == "S" {c++} END {print c + 0}'
)"

printf 'tracked_runs=%s\n' "$tracked_count"
printf 'skip_worktree_before=%s\n' "$skip_count_before"
printf 'skip_worktree_after=%s\n' "$skip_count_after"
printf 'dry_run=%s\n' "$dry_run"
