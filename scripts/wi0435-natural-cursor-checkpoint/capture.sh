#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# -lt 2 || $# -gt 4 ]]; then
  printf 'Usage: %s LABEL SECONDS_OR_TIMEOUT [complete|aborted|timeout] [yes|no|not_observed]\n' "$0" >&2
  exit 2
fi

workspace="/home/rob/projects/qcoder-wi0435-natural-cursor-workspace-v6"
operator_run_dir="/home/rob/projects/_ops/qcoder/wi0435-evidence-reconciler-result-manifest-successor-v1/natural-cursor-run-v6"
stage_status="${3:-complete}"
narration="${4:-not_observed}"
"$workspace/.venv/bin/python" "$(dirname "$0")/capture.py" \
  --workspace "$workspace" --operator-run-dir "$operator_run_dir" \
  --label "$1" --wall-seconds "$2" --stage-status "$stage_status" \
  --procedure-narration "$narration"
