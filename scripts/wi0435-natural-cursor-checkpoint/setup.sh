#!/usr/bin/env bash
set -euo pipefail
umask 077

select_compatible_python() {
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
      command -v "$candidate"
      return 0
    fi
  done
  printf 'Python 3.11 or newer is required for this qCoder checkpoint.\n' >&2
  return 1
}

if [[ ${1:-} == "--select-python-only" ]]; then
  select_compatible_python
  exit 0
fi

if [[ $# -ne 1 ]]; then
  printf 'Usage: %s /absolute/path/to/context-bridge-token-file\n' "$0" >&2
  exit 2
fi

packet_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace="/home/rob/projects/qcoder-wi0435-natural-cursor-workspace-v4"
token_file="$1"
bootstrap_python="$(select_compatible_python)"
"$bootstrap_python" "$packet_root/helpers/prepare.py" preflight \
  --packet "$packet_root" --workspace "$workspace" --token-file "$token_file"
"$bootstrap_python" -m venv "$workspace/.venv"
"$workspace/.venv/bin/python" -m pip install --no-cache-dir \
  "$packet_root/artifacts/$("$bootstrap_python" "$packet_root/helpers/prepare.py" wheel-name --packet "$packet_root")"
"$workspace/.venv/bin/python" -m pip install --no-cache-dir \
  'qiskit==2.5.2' 'qiskit-aer==0.17.2'
"$workspace/.venv/bin/python" "$packet_root/helpers/prepare.py" configure \
  --packet "$packet_root" --workspace "$workspace" --token-file "$token_file" \
  --python "$workspace/.venv/bin/python"
"$workspace/.venv/bin/python" "$workspace/.qcoder-client-runtime/run-sampled-result.py" \
  preflight --identity "$workspace/.qcoder-client-runtime/runtime-identity.json"
"$workspace/.venv/bin/python" "$packet_root/helpers/prepare.py" installed-check \
  --packet "$packet_root" --workspace "$workspace" --token-file "$token_file"
printf 'Open a fresh Cursor Agent conversation in exactly:\n%s\n' "$workspace"
printf 'If the cursor command is installed, run: cursor %q\n' "$workspace"
