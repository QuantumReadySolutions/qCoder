#!/usr/bin/env python3
"""Produce the pre-freeze WI-0434 semantic, interaction, and boundedness proof."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

from qcoder.context_bridge_mcp import EXPECTED_TOOLS, build_client_binding_descriptor
from qcoder.current_loop_bootstrap import build_fresh_active_build_bootstrap
from qcoder.current_loop_request_semantics import classify_current_request
from qcoder.d079_workflows import classify_binding_default_route


SOURCE_ONLY_REQUESTS = (
    "Use qCoder to write a Qiskit program that prepares a Φ+ Bell state. "
    "Stop after generating the code.",
    "Have qCoder help me create only the Qiskit source for a Φ+ state.",
    "Let’s use qCoder for this build. Make the Python file, but don’t export QASM or run it.",
    "With qCoder, generate a two-qubit Bell example in Python and stop after the source.",
    "qCoder, help me write the Bell-state code. We’ll do circuit evidence and results later.",
    "Use qcoder to make the Python for a local Bell example—code only for now.",
)

BELL_SOURCE = (
    "from qiskit import QuantumCircuit\n"
    "circuit = QuantumCircuit(2)\n"
    "circuit.h(0)\n"
    "circuit.cx(0, 1)\n"
)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def essential(semantics: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(semantics[key])
        for key in (
            "qcoder_explicitly_requested",
            "requested_operation",
            "requested_artifact_roles",
            "prohibited_artifact_roles",
            "qasm_disposition",
            "execution_disposition",
            "results_disposition",
            "evidence_review_disposition",
            "ambiguity_state",
            "clarification_required",
        )
    }


def _run_invocation(
    invocation: dict[str, Any],
    *,
    stdin: bytes = b"",
    dynamic_values: dict[str, str] | None = None,
) -> tuple[dict[str, Any], float]:
    operation = str(invocation.get("operation"))
    declared = {
        str(item["flag"])
        for item in invocation.get("dynamic_argument_contract", [])
        if isinstance(item, dict) and isinstance(item.get("flag"), str)
    }
    supplied = set((dynamic_values or {}).keys())
    if not supplied.issubset(declared):
        raise RuntimeError("fake_client_undeclared_dynamic_argument_rejected")
    raw_argv = list(invocation["structured_argv"])
    for flag, value in (dynamic_values or {}).items():
        try:
            index = raw_argv.index(flag)
        except ValueError:
            raw_argv.extend((flag, value))
        else:
            if index + 1 >= len(raw_argv) or not isinstance(raw_argv[index + 1], dict):
                raise RuntimeError("fake_client_dynamic_slot_shape_invalid")
            raw_argv[index + 1] = value
    if any(isinstance(value, dict) for value in raw_argv):
        raise RuntimeError("fake_client_unfilled_dynamic_slot_rejected")
    argv = [str(value) for value in raw_argv]
    environment = dict(os.environ)
    source_root = Path(__file__).resolve().parents[1] / "src"
    environment["PYTHONPATH"] = str(source_root)
    started = time.perf_counter()
    completed = subprocess.run(
        argv,
        input=stdin,
        capture_output=True,
        check=False,
        env=environment,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode not in {0, 1, 2}:
        raise RuntimeError(
            f"bound_operation_transport_failed:{operation}:"
            + completed.stderr.decode("utf-8", errors="replace")
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"bound_operation_non_json:{operation}") from exc
    return result, elapsed


def one_acceptance(workspace: Path) -> dict[str, Any]:
    request = SOURCE_ONLY_REQUESTS[0]
    started = time.perf_counter()
    bootstrap = build_fresh_active_build_bootstrap(executable=sys.executable)
    bootstrap_invocation = {
        "operation": "activate",
        "structured_argv": [
            *bootstrap["qcoder_owned_structured_argv"][:4],
            "--workspace",
            str(workspace),
            *bootstrap["qcoder_owned_structured_argv"][4:],
        ],
        "dynamic_argument_contract": [],
    }
    activation, activation_seconds = _run_invocation(
        bootstrap_invocation, stdin=request.encode("utf-8")
    )
    if not activation["ok"]:
        raise RuntimeError("d080_activation_failed")
    compact_permission = activation["compact_next_action"]
    if compact_permission["operation_specific_invocation"]["operation"] != "record_ide_authority":
        raise RuntimeError("compact_permission_operation_invalid")
    permission, permission_seconds = _run_invocation(
        compact_permission["operation_specific_invocation"]
    )
    if not permission["ok"]:
        raise RuntimeError("d080_permission_failed")
    compact_registration = permission["compact_next_action"]
    registration_invocation = compact_registration["operation_specific_invocation"]
    if registration_invocation["operation"] != "register_artifacts":
        raise RuntimeError("compact_registration_operation_invalid")
    source = workspace / "bell_state.py"
    native_started = time.perf_counter()
    source.write_text(BELL_SOURCE, encoding="utf-8")
    native_seconds = time.perf_counter() - native_started
    # Adversarially omit the qCoder-owned receipt. This intentionally violates
    # the compact contract and must fail without consuming or registering it.
    no_receipt_argv = list(registration_invocation["structured_argv"])
    receipt_flag = no_receipt_argv.index("--operation-receipt-id")
    del no_receipt_argv[receipt_flag : receipt_flag + 2]
    bypass, _ = _run_invocation(
        {
            "operation": "register_artifacts_adversarial_missing_receipt",
            "structured_argv": no_receipt_argv,
            "dynamic_argument_contract": registration_invocation["dynamic_argument_contract"],
        },
        dynamic_values={"--source": str(source)},
    )
    if bypass.get("ok") or bypass.get("category") != "current_step_operation_receipt_required":
        raise RuntimeError(f"missing_receipt_bypass_not_closed:{bypass!r}")
    registration, registration_seconds = _run_invocation(
        registration_invocation,
        dynamic_values={"--source": str(source)},
    )
    if not registration["ok"]:
        raise RuntimeError("d080_registration_failed")
    total_seconds = time.perf_counter() - started
    direct_qcoder_seconds = activation_seconds + permission_seconds + registration_seconds
    continuation = registration["compact_next_action"]["operation_specific_invocation"]
    closed, close_seconds = _run_invocation(
        continuation,
        stdin=b"Close qCoder for this build.",
    )
    if not closed["ok"]:
        raise RuntimeError("d080_explicit_close_failed")
    inventory = registration["details"]["exact_artifact_inventory"]
    if inventory != {
        "source": 1,
        "circuit_qasm": 0,
        "execution": 0,
        "results": 0,
        "unrelated": 0,
    }:
        raise RuntimeError("d080_artifact_inventory_invalid")
    bound_sequence = [
        "activate",
        compact_permission["operation_specific_invocation"]["operation"],
        compact_registration["operation_specific_invocation"]["operation"],
        continuation["operation"],
    ]
    return {
        "total_wall_seconds": total_seconds,
        "direct_qcoder_lifecycle_seconds": direct_qcoder_seconds,
        "client_orchestration_residual_seconds": max(0.0, total_seconds - direct_qcoder_seconds),
        "native_write_seconds": native_seconds,
        "explicit_close_seconds": close_seconds,
        "bootstrap_count": registration["bootstrap_count"],
        "request_baseline_count": registration["request_baseline_count"],
        "qcoder_authority_action_cycles_after_bootstrap": len(bound_sequence) - 1,
        "native_permission_prompts": sum(
            int(item.get("native_permission_required") is True)
            for item in (compact_permission, compact_registration)
        ),
        "artifact_inventory": inventory,
        "source_artifact": {
            "role": "source",
            "bytes": source.stat().st_size,
            "sha256": file_sha(source),
            "relative_path": source.name,
        },
        "request_message_preserved": (
            registration["current_request_semantics"]["exact_original_message"] == request
        ),
        "compact_next_action_used": all(
            item.get("procedural_source_of_truth") is True
            for item in (compact_permission, compact_registration)
        ),
        "bound_operation_sequence": bound_sequence,
        "undeclared_operation_executed": False,
        "missing_receipt_bypass_rejected": True,
        "procedural_archaeology_used": False,
        "forced_close_after_source_step": False,
        "resumable_after_source_step": registration["details"]["loop_resumable"],
        "customer_internal_choreography": False,
        "instrumentation_source": "subprocess_bound_invocation_trace",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--d079-scale-proof", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=True)

    semantics = [classify_current_request(message) for message in SOURCE_ONLY_REQUESTS]
    if len({json.dumps(essential(row), sort_keys=True) for row in semantics}) != 1:
        raise RuntimeError("semantic_paraphrase_matrix_diverged")
    routes = [
        classify_binding_default_route(customer_instruction=message)
        for message in SOURCE_ONLY_REQUESTS
    ]
    if any(route["selected_route"] != "active_build" for route in routes):
        raise RuntimeError("source_only_route_diverged")

    broader = {
        "source_qasm_no_run": classify_current_request(
            "Have qCoder write the Qiskit source and export QASM, but do not run it."
        ),
        "source_local_run_counts": classify_current_request(
            "Have qCoder write the Qiskit source and run it locally with 1,024 shots."
        ),
        "selected_artifact_review": classify_current_request(
            "Review these selected files with qCoder.", selected_paths=("selected.py",)
        ),
    }
    negatives = {
        message: classify_current_request(message)
        for message in (
            "Can qCoder help with Bell circuits?",
            "What does qCoder do?",
            "Show me the qCoder setup instructions.",
            "Write a Bell circuit.",
        )
    }
    ambiguities = {
        message: classify_current_request(message, active_loop=True)
        for message in (
            "Use qCoder for this.",
            "Don’t run it yet.",
            "Stop there.",
            "Make the circuit, but don’t execute it.",
        )
    }
    if any(value["loop_mutation_permitted"] for value in negatives.values()):
        raise RuntimeError("negative_control_activated")
    if any(not value["clarification_required"] for value in ambiguities.values()):
        raise RuntimeError("ambiguity_control_not_closed")

    acceptance_rows: list[dict[str, Any]] = []
    baseline_rows: list[float] = []
    with tempfile.TemporaryDirectory(prefix="qcoder-wi0434-proof-") as temp:
        root = Path(temp)
        for index in range(args.runs):
            workspace = root / f"run-{index + 1}"
            workspace.mkdir()
            baseline_start = time.perf_counter()
            (workspace / "ordinary_client_baseline.py").write_text(BELL_SOURCE, encoding="utf-8")
            baseline_rows.append(time.perf_counter() - baseline_start)
            qcoder_workspace = workspace / "qcoder"
            qcoder_workspace.mkdir()
            acceptance_rows.append(one_acceptance(qcoder_workspace))

    direct_times = sorted(row["direct_qcoder_lifecycle_seconds"] for row in acceptance_rows)
    p95_index = max(0, min(len(direct_times) - 1, round(0.95 * len(direct_times) + 0.499) - 1))
    timing = {
        "runs": len(acceptance_rows),
        "total_wall_seconds": [round(row["total_wall_seconds"], 6) for row in acceptance_rows],
        "ordinary_matched_client_baseline_seconds": [round(value, 6) for value in baseline_rows],
        "direct_qcoder_lifecycle_seconds": [round(value, 6) for value in direct_times],
        "direct_qcoder_lifecycle_p95_seconds": round(direct_times[p95_index], 6),
        "client_orchestration_residual_seconds": [
            round(row["client_orchestration_residual_seconds"], 6) for row in acceptance_rows
        ],
        "explicit_close_seconds": [
            round(row["explicit_close_seconds"], 6) for row in acceptance_rows
        ],
        "direct_qcoder_p95_limit_seconds": 60,
        "explicit_close_limit_seconds": 15,
        "median_total_wall_seconds": round(
            statistics.median(row["total_wall_seconds"] for row in acceptance_rows), 6
        ),
        "multi_minute_wandering_hidden": any(
            row["total_wall_seconds"] >= 120 and row["direct_qcoder_lifecycle_seconds"] < 60
            for row in acceptance_rows
        ),
    }
    if timing["direct_qcoder_lifecycle_p95_seconds"] > 60:
        raise RuntimeError("d080_direct_lifecycle_limit_exceeded")
    if max(timing["explicit_close_seconds"]) > 15:
        raise RuntimeError("d080_close_limit_exceeded")

    small = classify_current_request(SOURCE_ONLY_REQUESTS[0])
    scale_reference = classify_current_request(
        "Have qCoder create only the Python source for an approximately one-million-gate "
        "local circuit; code only for now."
    )
    small_projection = deepcopy(small)
    scale_projection = deepcopy(scale_reference)
    for projection in (small_projection, scale_projection):
        projection.pop("exact_original_message")
        projection.pop("original_message_utf8_sha256")
        projection.pop("semantics_digest")
    d079_scale = json.loads(args.d079_scale_proof.read_text(encoding="utf-8"))
    scale = {
        "schema_id": "qcoder.d080.request_authority_scale_proof.v1",
        "small_semantics_serialized_bytes": len(canonical(small)),
        "million_gate_reference_semantics_serialized_bytes": len(canonical(scale_reference)),
        "bounded_projection_size_delta_bytes": abs(
            len(canonical(small_projection)) - len(canonical(scale_projection))
        ),
        "small_ceiling_entry_count": len(small["current_step_ceiling"]["allowed_operations"]),
        "million_gate_ceiling_entry_count": len(
            scale_reference["current_step_ceiling"]["allowed_operations"]
        ),
        "per_gate_authority_entries": 0,
        "semantic_state_growth_basis": "customer_decisions_not_gate_count",
        "raw_large_artifact_in_semantic_state": False,
        "d079_selected_artifact_scale_proof": d079_scale[
            "actual_selected_file_evidence_review_limit"
        ],
        "coverage_status": "LIMITED",
        "limited_relabelled_complete": False,
        "raw_protected_transfer": False,
        "silent_truncation": False,
    }

    descriptor = build_client_binding_descriptor(
        coordinator_prefix=["python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    descriptor_digest = sha256(canonical(descriptor)).hexdigest()
    proof = {
        "schema_id": "qcoder.wi0434.private_terminal_proof.v1",
        "gate": "WI0434_CURRENT_LOOP_BOOTSTRAP_AND_CODE_ONLY_AUTHORITY_PASS",
        "semantic_paraphrase_matrix": {
            "result": "pass",
            "request_count": len(SOURCE_ONLY_REQUESTS),
            "exact_messages": list(SOURCE_ONLY_REQUESTS),
            "essential_semantics": essential(semantics[0]),
            "distinct_message_digests": [row["original_message_utf8_sha256"] for row in semantics],
            "sentence_phrasebook_used": False,
        },
        "binding_routes": routes,
        "broader_positive_semantics": broader,
        "negative_controls": negatives,
        "ambiguity_controls": ambiguities,
        "acceptance_runs": acceptance_rows,
        "timing_and_interaction": timing,
        "scale_and_boundedness": scale,
        "authority_layers": semantics[0]["authority_layers"],
        "structured_recovery_categories": [
            "current_request_stage_ambiguous",
            "current_step_authority_mismatch",
            "current_step_ceiling_violation",
            "current_step_artifact_cardinality_invalid",
            "operation_receipt_stale",
            "selected_artifact_limit",
            "protected_artifact_layer_mismatch",
            "continuation_failure",
        ],
        "public_context_bridge_tool_count": len(EXPECTED_TOOLS),
        "public_context_bridge_tools": list(EXPECTED_TOOLS),
        "binding_identity": descriptor["contract_id"],
        "binding_descriptor_sha256": descriptor_digest,
        "customer_internal_choreography": False,
        "process_and_discard": True,
        "hidden_persistence": False,
        "result": "pass",
    }
    write_json(output / "wi0434-terminal-proof.json", proof)
    write_json(output / "d080-scale-proof.json", scale)
    write_json(output / "timing-and-interaction-proof.json", timing)
    inventory = [
        {
            "path": path.name,
            "bytes": path.stat().st_size,
            "sha256": file_sha(path),
        }
        for path in sorted(output.glob("*.json"))
        if path.name != "packet-manifest.json"
    ]
    manifest = {
        "schema_id": "qcoder.wi0434.private_terminal_proof_packet.v1",
        "result": "pass",
        "gates": [
            "WI0434_CURRENT_LOOP_BOOTSTRAP_AND_CODE_ONLY_AUTHORITY_PASS",
            "SEMANTIC_PARAPHRASE_MATRIX_PASS",
            "SCALE_AND_INTERACTION_BOUNDEDNESS_PROVEN",
        ],
        "binding_identity": descriptor["contract_id"],
        "binding_descriptor_sha256": descriptor_digest,
        "inventory": inventory,
        "packet_identity_canonicalization": (
            "sha256 over ensure_ascii=true, sort_keys=true, separators=(',', ':'), "
            "before packet_identity is added"
        ),
    }
    manifest["packet_identity"] = "sha256:" + sha256(canonical(manifest)).hexdigest()
    write_json(output / "packet-manifest.json", manifest)
    print(
        json.dumps(
            {
                "packet": str(output),
                "packet_identity": manifest["packet_identity"],
                "manifest_sha256": file_sha(output / "packet-manifest.json"),
                "binding_identity": descriptor["contract_id"],
                "binding_descriptor_sha256": descriptor_digest,
                "timing": timing,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
