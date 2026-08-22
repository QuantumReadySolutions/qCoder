#!/usr/bin/env bash
set -euo pipefail
umask 077

workspace="/home/rob/projects/qcoder-wi0435-natural-cursor-workspace-v7"
operator_run_dir="/home/rob/projects/_ops/qcoder/wi0435-evidence-reconciler-result-manifest-successor-v1/natural-cursor-run-v7"
"$workspace/.venv/bin/python" "$(dirname "$0")/seal.py" "$workspace" "$operator_run_dir"
