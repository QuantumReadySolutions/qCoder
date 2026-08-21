#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# -ne 11 ]]; then
  printf 'Usage: %s LABEL SECONDS NARRATION PROCESS_ATTEMPTS SAMPLER_EXECUTIONS INSTALLS MUTATIONS RERUNS COMPLETION_RETRIES DISCOVERY_COUNT FINAL_OUTCOME_OBSERVED\n' "$0" >&2
  exit 2
fi

workspace="/home/rob/projects/qcoder-wi0435-natural-cursor-workspace-v4"
requested_outcome="$1"
"$workspace/.venv/bin/python" "$(dirname "$0")/capture.py" \
  --workspace "$workspace" --label "$1" --wall-seconds "$2" \
  --procedure-narration "$3" --native-process-attempts "$4" \
  --sampler-executions "$5" --dependency-installations "$6" \
  --environment-mutations "$7" --execution-reruns "$8" \
  --completion-retries "$9" --workspace-discovery-actions "${10}" \
  --requested-outcome "$requested_outcome" --final-outcome-observed "${11}"
