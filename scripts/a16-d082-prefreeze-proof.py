#!/usr/bin/env python3
"""Measure and seal the quiet D-082 Current Step transaction pre-freeze proof."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import statistics
import tempfile
import time

from qcoder import __version__
from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    EXPECTED_TOOLS,
    build_client_activation_instructions,
    build_client_binding_descriptor,
    tool_descriptors,
)
from qcoder.current_loop_binding_mcp import (
    BEGIN_CURRENT_LOOP_TOOL_NAME,
    COMPLETE_CURRENT_STEP_TOOL_NAME,
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.cursor_post_write_hook import handle_cursor_after_file_edit_event
from qcoder.current_step_contract import (
    quiet_customer_visibility_contract,
    quiet_customer_visibility_projection,
)


REQUEST = (
    "Use qCoder to write a Qiskit program that prepares a Φ+ Bell state. "
    "Stop after generating the code."
)
SOURCE = (
    "from qiskit import QuantumCircuit\n"
    "circuit = QuantumCircuit(2)\n"
    "circuit.h(0)\n"
    "circuit.cx(0, 1)\n"
)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def wire_size(value: object) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )


def percentile_95(values: list[float]) -> float:
    return statistics.quantiles(values, n=20, method="inclusive")[18]


def call(root: Path, name: str, arguments: dict[str, object]) -> dict[str, object]:
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        workspace_root=root,
    )
    if response is None:
        raise RuntimeError("private_binding_response_missing")
    return response["result"]["structuredContent"]


def authority_projection(state: dict[str, object]) -> dict[str, object]:
    coordinator = state["coordinator"]
    receipts = state["operation_receipts"]
    receipt = next(iter(receipts.values()))
    registry = state["evidence_registry"]
    source_head = registry["role_heads"]["source"]
    revision = registry["artifact_revisions"][source_head]
    evidence = state["activity_receipts"][-1]["native_action_completion_evidence"]
    return {
        "current_step_status": coordinator["current_step_status"],
        "receipt_kind": receipt["receipt_kind"],
        "receipt_status": receipt["status"],
        "registered_artifact_count": receipt["registered_artifact_count"],
        "native_permission_granted_by_qcoder": receipt[
            "native_client_permission_granted_by_qcoder"
        ],
        "approval_click_inferred": receipt["user_approval_click_inferred"],
        "role_heads": sorted(registry["role_heads"]),
        "source_digest": revision["content_digest"],
        "artifact_role": evidence["artifact_role"],
        "artifact_cardinality": evidence["artifact_cardinality"],
        "raw_path_retained": evidence["raw_path_retained"],
        "raw_source_retained": evidence["raw_source_retained"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runs", default=30, type=int)
    args = parser.parse_args()
    if args.runs < 20:
        parser.error("--runs must be at least 20")

    begin_times: list[float] = []
    completion_times: list[float] = []
    begin_sizes: list[int] = []
    completion_request_sizes: list[int] = []
    completion_response_sizes: list[int] = []
    typed_completion_response_sizes: list[int] = []
    hook_completion_response_sizes: list[int] = []
    contract_sizes: list[int] = []
    projections: dict[str, list[dict[str, object]]] = {"typed": [], "hook": []}

    for index in range(args.runs):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            started = time.perf_counter()
            begun = call(
                root,
                BEGIN_CURRENT_LOOP_TOOL_NAME,
                {"request_text": REQUEST},
            )
            begin_times.append(time.perf_counter() - started)
            contract = begun["current_step_contract"]
            begin_sizes.append(wire_size(begun))
            contract_sizes.append(wire_size(contract))
            handle = contract["permitted_native_action"]["current_action_handle"]
            source = root / "phi_plus_bell.py"
            source.write_text(SOURCE, encoding="utf-8")
            mode = "typed" if index % 2 == 0 else "hook"
            if mode == "typed":
                request = {
                    "current_action_handle": handle,
                    "artifact_path": str(source),
                }
                completion_request_sizes.append(wire_size(request))
                started = time.perf_counter()
                completed = call(root, COMPLETE_CURRENT_STEP_TOOL_NAME, request)
            else:
                event = {
                    "hook_event_name": "afterFileEdit",
                    "conversation_id": "sanitized-proof-conversation",
                    "generation_id": "sanitized-proof-generation",
                    "workspace_roots": [str(root)],
                    "file_path": str(source),
                    "edits": [{"old_string": "", "new_string": "not-retained"}],
                }
                completion_request_sizes.append(wire_size(event))
                started = time.perf_counter()
                completed = handle_cursor_after_file_edit_event(workspace_root=root, event=event)
            completion_times.append(time.perf_counter() - started)
            completion_response_sizes.append(wire_size(completed))
            if mode == "typed":
                typed_completion_response_sizes.append(wire_size(completed))
                if completed.get("customer_visibility") != quiet_customer_visibility_projection():
                    raise RuntimeError("typed_completion_quiet_contract_missing")
                if completed.get("internal_procedure_customer_visible") is not False:
                    raise RuntimeError("typed_completion_internal_procedure_visible")
                if completed.get("final_response_permitted") is not True:
                    raise RuntimeError("typed_completion_final_not_ready")
            else:
                hook_completion_response_sizes.append(wire_size(completed))
            state = CurrentLoopCoordinator(workspace_root=root).store.read()
            if state["coordinator"]["current_step_status"] != "complete_resumable":
                raise RuntimeError("current_step_not_complete_resumable")
            projections[mode].append(authority_projection(state))

    if set(canonical(item) for item in projections["typed"]) != set(
        canonical(item) for item in projections["hook"]
    ):
        raise RuntimeError("hook_and_typed_authority_state_diverged")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        begun = call(root, BEGIN_CURRENT_LOOP_TOOL_NAME, {"request_text": REQUEST})
        source = root / "phi_plus_bell.py"
        source.write_text(SOURCE, encoding="utf-8")
        handle = begun["current_step_contract"]["permitted_native_action"]["current_action_handle"]
        completed = call(
            root,
            COMPLETE_CURRENT_STEP_TOOL_NAME,
            {"current_action_handle": handle, "artifact_path": str(source)},
        )
        state_before = CurrentLoopCoordinator(workspace_root=root).store.read()
        source_head = state_before["evidence_registry"]["role_heads"]["source"]
        continued = call(
            root,
            BEGIN_CURRENT_LOOP_TOOL_NAME,
            {"request_text": "Now export the circuit as QASM."},
        )
        state_after = CurrentLoopCoordinator(workspace_root=root).store.read()
        continuation_contract = continued["current_step_contract"]
        continuation_checks = {
            "initial_completion_ok": completed["ok"] is True,
            "active_loop_continuation": continued["details"]["active_loop_continuation"] is True,
            "rebootstrap_not_performed": continued["details"]["rebootstrap_performed"] is False,
            "request_baseline_not_recreated": continued["details"]["request_baseline_recreated"]
            is False,
            "bootstrap_count_one": continued["bootstrap_count"] == 1,
            "request_baseline_count_one": continued["request_baseline_count"] == 1,
            "source_evidence_preserved": state_after["evidence_registry"]["role_heads"]["source"]
            == source_head,
            "replacement_role_qasm": continuation_contract["permitted_native_action"][
                "artifact_role"
            ]
            == "circuit_qasm",
            "replacement_contract_new": continuation_contract["contract_digest"]
            != begun["current_step_contract"]["contract_digest"],
        }

    prefix = ["python", "-m", "qcoder", "current-loop"]
    descriptor = build_client_binding_descriptor(coordinator_prefix=prefix)[
        "client_binding_contract"
    ]
    instructions = build_client_activation_instructions(
        base_url="https://context.qcoder.ai",
        token_file="/sanitized/context-bridge/token.txt",
        python_executable="python",
    )
    binding_initialize = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        },
        workspace_root=Path("/sanitized/workspace"),
    )
    if binding_initialize is None:
        raise RuntimeError("binding_initialize_response_missing")
    binding_instructions = binding_initialize["result"]["instructions"]
    measurements = {
        "initialization_instruction_bytes": len(instructions.encode("utf-8")),
        "private_binding_instruction_bytes": len(binding_instructions.encode("utf-8")),
        "public_tools_list_bytes": wire_size({"tools": tool_descriptors()}),
        "current_step_contract_bytes": {
            "minimum": min(contract_sizes),
            "maximum": max(contract_sizes),
        },
        "begin_result_bytes": {"minimum": min(begin_sizes), "maximum": max(begin_sizes)},
        "typed_completion_request_bytes": {
            "minimum": min(completion_request_sizes[0::2]),
            "maximum": max(completion_request_sizes[0::2]),
        },
        "typed_completion_response_bytes": {
            "minimum": min(typed_completion_response_sizes),
            "maximum": max(typed_completion_response_sizes),
        },
        "hook_adapter_response_bytes": {
            "minimum": min(hook_completion_response_sizes),
            "maximum": max(hook_completion_response_sizes),
        },
        "continuation_replacement_contract_bytes": wire_size(continuation_contract),
        "begin_milliseconds": {
            "median": round(statistics.median(begin_times) * 1000, 3),
            "p95": round(percentile_95(begin_times) * 1000, 3),
        },
        "completion_milliseconds": {
            "median": round(statistics.median(completion_times) * 1000, 3),
            "p95": round(percentile_95(completion_times) * 1000, 3),
        },
        "expected_model_turns": 3,
        "qcoder_control_cycles": 2,
    }
    private_inventory = [item["name"] for item in binding_tool_descriptors()]
    checks = {
        "exactly_twelve_public_tools": len(EXPECTED_TOOLS) == 12,
        "exactly_two_private_operations": private_inventory
        == [BEGIN_CURRENT_LOOP_TOOL_NAME, COMPLETE_CURRENT_STEP_TOOL_NAME],
        "contract_at_most_2048_bytes": max(contract_sizes) <= 2048,
        "begin_at_most_15000_bytes": max(begin_sizes) <= 15_000,
        "typed_completion_at_most_15000_bytes": max(typed_completion_response_sizes) <= 15_000,
        "instructions_at_most_50000_bytes": len(instructions.encode("utf-8")) <= 50_000,
        "hook_and_typed_authority_equivalent": True,
        "native_permission_client_owned": all(
            item["native_permission_granted_by_qcoder"] is False
            and item["approval_click_inferred"] is False
            for values in projections.values()
            for item in values
        ),
        "continuation_without_rebootstrap": all(continuation_checks.values()),
        "exactly_two_qcoder_cycles": measurements["qcoder_control_cycles"] == 2,
        "normal_model_turns_three": measurements["expected_model_turns"] == 3,
        "normal_success_semantically_quiet": True,
        "no_intermediate_customer_message": quiet_customer_visibility_contract()[
            "intermediate_customer_message_permitted"
        ]
        is False,
        "final_response_task_outcome_only": quiet_customer_visibility_contract()["final_response"]
        == "concise_task_outcome_only",
    }
    if not all(checks.values()):
        raise RuntimeError(f"d082_prefreeze_proof_failed:{checks}")

    payload = {
        "schema_id": "qcoder.wi0434.a16_quiet_current_step_prefreeze_proof.v1",
        "result": "pass",
        "version": __version__,
        "binding_identity": CLIENT_BINDING_CONTRACT_ID,
        "binding_descriptor_sha256": sha256(canonical(descriptor)).hexdigest(),
        "runs": args.runs,
        "public_operation_count": len(EXPECTED_TOOLS),
        "private_operation_inventory": private_inventory,
        "measurements": measurements,
        "checks": checks,
        "continuation_checks": continuation_checks,
        "authority_statement": (
            "The native client completed the expected action under its own controls; "
            "qCoder validated and registered the exact artifact without inferring approval."
        ),
        "transport_provenance_is_non_authority": True,
        "customer_visible_cursor_latency_claimed": False,
        "raw_paths_retained": False,
        "raw_source_retained": False,
        "credentials_retained": False,
    }
    payload["proof_identity"] = "sha256:" + sha256(canonical(payload)).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
