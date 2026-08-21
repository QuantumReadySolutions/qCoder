#!/usr/bin/env bash
set -euo pipefail
umask 077

workspace="/home/rob/projects/qcoder-wi0435-natural-cursor-workspace-v4"
"$workspace/.venv/bin/python" "$(dirname "$0")/seal.py" "$workspace"
