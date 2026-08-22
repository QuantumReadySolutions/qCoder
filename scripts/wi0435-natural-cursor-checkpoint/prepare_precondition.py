from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from qcoder.current_loop_binding_mcp import handle_binding_jsonrpc_message
from qcoder.current_loop_coordinator import CurrentLoopCoordinator


SOURCE = (
    "from qiskit import QuantumCircuit\n"
    "circuit = QuantumCircuit(2, 2)\n"
    "circuit.h(0)\n"
    "circuit.cx(0, 1)\n"
    "circuit.measure([0, 1], [0, 1])\n"
)
QASM = (
    'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\n'
    "h q[0];\ncx q[0],q[1];\nmeasure q -> c;\n"
)


def _call(workspace: Path, name: str, arguments: dict) -> dict:
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        workspace_root=workspace,
    )
    if not isinstance(response, dict):
        raise SystemExit("Prepared Current Step call returned no response.")
    result = response.get("result", {}).get("structuredContent")
    if not isinstance(result, dict) or result.get("ok") is not True:
        category = result.get("category") if isinstance(result, dict) else "missing_result"
        raise SystemExit(f"Prepared Current Step failed: {category}")
    return result


def _write_exact(path: Path, content: str) -> None:
    if path.exists() or path.is_symlink():
        raise SystemExit("Prepared artifact target is not fresh.")
    path.write_text(content, encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--operator-run-dir", type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.absolute()
    operator_run_dir = args.operator_run_dir.absolute()
    if (
        workspace == operator_run_dir
        or workspace in operator_run_dir.parents
        or operator_run_dir in workspace.parents
    ):
        raise SystemExit("Prepared evidence directory must remain outside the Cursor workspace.")
    source = workspace / "bell.py"
    circuit = workspace / "bell.qasm"
    result = workspace / "bell-results-1024.json"
    _call(
        workspace,
        "begin_current_loop",
        {
            "request_text": (
                "Use qCoder to write a Qiskit program that prepares a Φ+ Bell state. "
                "Stop after generating the code."
            ),
            "intended_artifact_paths": {"source": source.name},
        },
    )
    _write_exact(source, SOURCE)
    _call(workspace, "complete_current_step", {})
    _call(
        workspace,
        "begin_current_loop",
        {
            "request_text": "Now export the circuit as QASM. Do not run it.",
            "intended_artifact_paths": {"circuit_qasm": circuit.name},
        },
    )
    _write_exact(circuit, QASM)
    _call(workspace, "complete_current_step", {})
    begun = _call(
        workspace,
        "begin_current_loop",
        {
            "request_text": (
                "Run the registered Bell circuit locally with 1,024 shots under the native "
                "client's controls. Save exact result evidence for this attempt, let qCoder "
                "validate it, and show the current Run Summary."
            ),
            "intended_artifact_paths": {"results": result.name},
        },
    )
    external = begun["current_step_contract"]["permitted_native_action"][
        "external_execution_contract"
    ]
    subprocess.run(
        [
            sys.executable,
            str(workspace / ".qcoder-client-runtime" / "run-sampled-result.py"),
            "run",
            "--qasm",
            str(circuit),
            "--result",
            str(result),
            "--shots",
            "1024",
            "--attempt-id",
            str(external["execution_attempt_identity"]),
            "--event-log",
            str(operator_run_dir / "execution-events.jsonl"),
        ],
        check=True,
    )
    completed = _call(workspace, "complete_current_step", {})
    if not isinstance(completed.get("current_run_summary"), dict):
        raise SystemExit("Prepared coherent Run Summary is unavailable.")
    state = CurrentLoopCoordinator(workspace_root=workspace).store.read()
    coordinator = state.get("coordinator", {})
    if (
        coordinator.get("bootstrap_count") != 1
        or coordinator.get("request_baseline_count") != 1
        or coordinator.get("current_step_status") != "complete_resumable"
    ):
        raise SystemExit("Prepared active-loop identity is invalid.")
    registry = state["evidence_registry"]
    revisions = registry["artifact_revisions"]
    identity = {
        "schema_id": "qcoder.wi0435.prepared_causal_history.v1",
        "bootstrap_count": 1,
        "request_baseline_count": 1,
        "current_step_status": "complete_resumable",
        "role_heads": {
            role: {
                "artifact_revision_id": revision_id,
                "content_digest": revisions[revision_id]["content_digest"],
            }
            for role, revision_id in sorted(registry["role_heads"].items())
        },
        "current_run_summary_reference": state.get("latest_run_summary_reference"),
        "prepared_external_execution_count": 1,
        "natural_cursor_evidence": False,
        "raw_artifacts_retained": False,
        "raw_state_retained": False,
    }
    identity_path = operator_run_dir / "prepared-precondition.json"
    identity_path.write_text(json.dumps(identity, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(identity_path, stat.S_IRUSR | stat.S_IWUSR)
    registration_ids = [
        event["event_id"]
        for event in registry.get("registration_events", [])
        if isinstance(event, dict) and isinstance(event.get("event_id"), str)
    ]
    watermark = {
        "offsets": {
            "mcp": (operator_run_dir / "mcp-events.jsonl").stat().st_size
            if (operator_run_dir / "mcp-events.jsonl").is_file()
            else 0,
            "execution": (operator_run_dir / "execution-events.jsonl").stat().st_size,
        },
        "registration_event_ids": registration_ids,
    }
    watermark_path = operator_run_dir / ".capture-watermark.json"
    watermark_path.write_text(json.dumps(watermark, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(watermark_path, stat.S_IRUSR | stat.S_IWUSR)
    print("PREPARED_CAUSAL_HISTORY_PASS")
    print(f"identity_sha256={sha256(identity_path.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
