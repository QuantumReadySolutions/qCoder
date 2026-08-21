#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# -lt 2 || $# -gt 3 ]]; then
  printf 'Usage: %s LABEL SECONDS_OR_TIMEOUT [complete|aborted|timeout]\n' "$0" >&2
  exit 2
fi

workspace="/home/rob/projects/qcoder-wi0435-natural-cursor-workspace-v5"
operator_run_dir="/home/rob/projects/_ops/qcoder/wi0435-evidence-reconciler-result-manifest-successor-v1/natural-cursor-run-v5"
requested_outcome="$1"
stage_status="${3:-complete}"
ask() {
  local prompt="$1"
  local value
  read -r -p "$prompt: " value
  printf '%s' "$value"
}
narration="$(ask 'Procedure narration observed (yes/no)')"
processes="$(ask 'Native process attempts (integer/unknown/not_observed)')"
samplers="$(ask 'Actual sampler executions (integer/unknown/not_observed)')"
installs="$(ask 'Dependency installations (integer/unknown/not_observed)')"
mutations="$(ask 'Environment mutations (integer/unknown/not_observed)')"
reruns="$(ask 'Execution reruns (integer/unknown/not_observed)')"
begins="$(ask 'qCoder begin calls (integer/unknown/not_observed)')"
completions="$(ask 'qCoder completion calls (integer/unknown/not_observed)')"
retries="$(ask 'qCoder completion retries (integer/unknown/not_observed)')"
cli_help="$(ask 'qCoder CLI/help invocations (integer/unknown/not_observed)')"
discovery="$(ask 'Target-selection discovery actions (integer/unknown/not_observed)')"
harness_reads="$(ask 'Harness-file reads (integer/unknown/not_observed)')"
outcome="$(ask 'Requested final outcome visible (yes/no)')"
"$workspace/.venv/bin/python" "$(dirname "$0")/capture.py" \
  --workspace "$workspace" --operator-run-dir "$operator_run_dir" \
  --label "$1" --wall-seconds "$2" --stage-status "$stage_status" \
  --procedure-narration "$narration" --native-process-attempts "$processes" \
  --sampler-executions "$samplers" --dependency-installations "$installs" \
  --environment-mutations "$mutations" --execution-reruns "$reruns" \
  --qcoder-begin-calls "$begins" --qcoder-completion-calls "$completions" \
  --completion-retries "$retries" --cli-help-invocations "$cli_help" \
  --workspace-discovery-actions "$discovery" --harness-file-reads "$harness_reads" \
  --requested-outcome "$requested_outcome" --final-outcome-observed "$outcome"
