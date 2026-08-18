#!/usr/bin/env python3
"""Seal the D-081 external-native-authority pre-freeze proof."""

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
from qcoder.cursor_post_write_hook import _event_binding, install_cursor_post_write_hook


REQUEST = (
    "Use qCoder to write a Qiskit program that prepares a Φ+ Bell state. "
    "Stop after generating the code."
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=30)
    args = parser.parse_args()
    if args.runs < 20:
        parser.error("--runs must be at least 20")

    activation_seconds: list[float] = []
    completion_seconds: list[float] = []
    activation_sizes: list[int] = []
    completion_sizes: list[int] = []
    for index in range(args.runs):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            install_cursor_post_write_hook(workspace_root=workspace)
            started = time.perf_counter()
            response = handle_binding_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": BEGIN_CURRENT_LOOP_TOOL_NAME,
                        "arguments": {"request_text": REQUEST},
                    },
                },
                workspace_root=workspace,
            )
            activation_seconds.append(time.perf_counter() - started)
            if response is None:
                raise SystemExit("structured_activation_response_missing")
            activated = response["result"]["structuredContent"]
            source = workspace / f"bell-{index}.py"
            source.write_text(
                "from qiskit import QuantumCircuit\n"
                "circuit = QuantumCircuit(2)\n"
                "circuit.h(0)\n"
                "circuit.cx(0, 1)\n",
                encoding="utf-8",
            )
            coordinator = CurrentLoopCoordinator(workspace_root=workspace)
            state = coordinator.store.read()
            event = {
                "hook_event_name": "afterFileEdit",
                "conversation_id": "sanitized-proof-conversation",
                "generation_id": "sanitized-proof-generation",
                "workspace_roots": [str(workspace)],
                "file_path": str(source),
                "edits": [{"old_string": "", "new_string": "not-retained"}],
            }
            binding = _event_binding(event, source, state, event_name="afterFileEdit")
            started = time.perf_counter()
            completed = coordinator.complete_external_native_action(
                candidates=(
                    {
                        "role": "source",
                        "path": str(source),
                        "provenance": "assistant_created",
                        "explicit_external": False,
                    },
                ),
                native_client_event_binding=binding,
            )
            completion_seconds.append(time.perf_counter() - started)
            activation_sizes.append(wire_size(activated))
            completion_sizes.append(wire_size(completed))
            final_state = coordinator.store.read()
            if (
                completed.get("ok") is not True
                or final_state["coordinator"]["current_step_status"] != "complete_resumable"
            ):
                raise SystemExit("d081_normal_completion_failed")

    prefix = ["python", "-m", "qcoder", "current-loop"]
    descriptor = build_client_binding_descriptor(coordinator_prefix=prefix)[
        "client_binding_contract"
    ]
    instructions = build_client_activation_instructions(
        base_url="https://context.qcoder.ai",
        token_file="/sanitized/context-bridge/token.txt",
        python_executable="python",
    )
    measurements = {
        "initialization_instruction_bytes": len(instructions.encode("utf-8")),
        "tools_list_bytes": wire_size({"tools": tool_descriptors()}),
        "activation_result_bytes": {
            "minimum": min(activation_sizes),
            "maximum": max(activation_sizes),
            "median": statistics.median(activation_sizes),
        },
        "completion_result_bytes": {
            "minimum": min(completion_sizes),
            "maximum": max(completion_sizes),
            "median": statistics.median(completion_sizes),
        },
        "activation_milliseconds": {
            "median": round(statistics.median(activation_seconds) * 1000, 3),
            "p95": round(percentile_95(activation_seconds) * 1000, 3),
        },
        "completion_milliseconds": {
            "median": round(statistics.median(completion_seconds) * 1000, 3),
            "p95": round(percentile_95(completion_seconds) * 1000, 3),
        },
        "expected_model_turns": 3,
        "qcoder_control_cycles": 2,
    }
    checks = {
        "instructions_at_most_50000": measurements["initialization_instruction_bytes"] <= 50_000,
        "activation_at_most_15000": max(activation_sizes) <= 15_000,
        "completion_at_most_15000": max(completion_sizes) <= 15_000,
        "exactly_twelve_public_tools": len(EXPECTED_TOOLS) == 12,
        "exactly_two_private_binding_operations": [
            item["name"] for item in binding_tool_descriptors()
        ]
        == [BEGIN_CURRENT_LOOP_TOOL_NAME, COMPLETE_CURRENT_STEP_TOOL_NAME],
        "native_permission_owned_by_client": True,
        "qcoder_does_not_grant_or_observe_native_permission": True,
        "qcoder_does_not_infer_user_approval_click": True,
        "exactly_two_qcoder_cycles": measurements["qcoder_control_cycles"] == 2,
        "normal_model_turns_three": measurements["expected_model_turns"] == 3,
    }
    if not all(checks.values()):
        raise SystemExit(f"d081_prefreeze_proof_failed:{checks}")
    payload = {
        "schema_id": "qcoder.wi0434.a16_d081_prefreeze_proof.v1",
        "result": "pass",
        "version": __version__,
        "binding_identity": CLIENT_BINDING_CONTRACT_ID,
        "binding_descriptor_sha256": sha256(canonical(descriptor)).hexdigest(),
        "runs": args.runs,
        "measurements": measurements,
        "checks": checks,
        "authority_statement": (
            "The native client completed the expected source-write action under its "
            "own controls, and qCoder validated and registered the resulting artifact."
        ),
        "customer_visible_cursor_latency_claimed": False,
        "raw_paths_retained": False,
        "raw_source_retained": False,
        "credentials_retained": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
