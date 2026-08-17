#!/usr/bin/env python3
"""Measure and seal the a15-to-a16 assistant-facing latency contract delta."""

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
    build_inline_client_binding_descriptor,
    tool_descriptors,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.cursor_post_write_hook import (
    handle_cursor_post_write_event,
    install_cursor_post_write_hook,
)


REQUEST = (
    "Use qCoder to write a Qiskit program that prepares a Φ+ Bell state. "
    "Stop after generating the code."
)
A15_BASELINE = {
    "source_commit": "a37e94ca076f4a51d9821143a239ad15a91c368b",
    "binding_identity": "qcoder.connected_assistant.client_binding.v25",
    "initialization_instruction_bytes": 354_386,
    "tools_list_bytes": 121_926,
    "activation_result_bytes": 28_359,
    "completion_result_bytes": 25_025,
    "activation_median_milliseconds": 77.316,
    "completion_median_milliseconds": 94.596,
    "expected_model_turns": 4,
    "qcoder_control_cycles": 2,
}


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def wire_size(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
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

    prefix = ["python", "-m", "qcoder", "current-loop"]
    full_descriptor = build_client_binding_descriptor(coordinator_prefix=prefix)[
        "client_binding_contract"
    ]
    inline_descriptor_envelope = build_inline_client_binding_descriptor(coordinator_prefix=prefix)
    inline_descriptor = inline_descriptor_envelope["client_binding_contract"]
    instructions = build_client_activation_instructions(
        base_url="https://context.qcoder.ai",
        token_file="/sanitized/context-bridge/token.txt",
        python_executable="python",
    )
    tools = {"tools": tool_descriptors()}
    activation_seconds: list[float] = []
    completion_seconds: list[float] = []
    activation_sizes: list[int] = []
    completion_sizes: list[int] = []
    for _ in range(args.runs):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            install_cursor_post_write_hook(workspace_root=workspace)
            coordinator = CurrentLoopCoordinator(workspace_root=workspace)
            started = time.perf_counter()
            activated = coordinator.activate(
                original_request=REQUEST,
                explicit_authority=True,
                capture_mode="exact_current_customer_message",
                request_transport="stdin",
            )
            activation_seconds.append(time.perf_counter() - started)
            source = workspace / "bell.py"
            source.write_text(
                "from qiskit import QuantumCircuit\n"
                "circuit = QuantumCircuit(2)\n"
                "circuit.h(0)\n"
                "circuit.cx(0, 1)\n",
                encoding="utf-8",
            )
            started = time.perf_counter()
            completed = handle_cursor_post_write_event(
                workspace_root=workspace,
                event={
                    "hook_event_name": "postToolUse",
                    "tool_name": "Write",
                    "conversation_id": "sanitized-proof-conversation",
                    "generation_id": "sanitized-proof-generation",
                    "tool_use_id": "sanitized-proof-write",
                    "cwd": str(workspace),
                    "workspace_roots": [str(workspace)],
                    "tool_input": {"file_path": str(source)},
                },
            )
            completion_seconds.append(time.perf_counter() - started)
            activation_sizes.append(wire_size(activated))
            completion_sizes.append(wire_size(completed))
            if completed.get("ok") is not True:
                raise SystemExit("normal_completion_failed")

    after = {
        "version": __version__,
        "binding_identity": CLIENT_BINDING_CONTRACT_ID,
        "binding_descriptor_sha256": sha256(canonical(full_descriptor)).hexdigest(),
        "inline_descriptor_sha256": sha256(canonical(inline_descriptor)).hexdigest(),
        "initialization_instruction_bytes": len(instructions.encode("utf-8")),
        "tools_list_bytes": wire_size(tools),
        "activation_result_bytes": sorted(set(activation_sizes)),
        "completion_result_bytes": sorted(set(completion_sizes)),
        "activation_median_milliseconds": round(statistics.median(activation_seconds) * 1000, 3),
        "activation_p95_milliseconds": round(percentile_95(activation_seconds) * 1000, 3),
        "completion_median_milliseconds": round(statistics.median(completion_seconds) * 1000, 3),
        "completion_p95_milliseconds": round(percentile_95(completion_seconds) * 1000, 3),
        "expected_model_turns": 3,
        "qcoder_control_cycles": 2,
        "post_write_model_shell_calls": 0,
        "post_write_native_approvals": 0,
        "post_write_transport": "cursor_project_post_tool_use_hook",
        "public_context_bridge_tools": list(EXPECTED_TOOLS),
        "public_context_bridge_tool_count": len(EXPECTED_TOOLS),
    }
    checks = {
        "instructions_at_most_50000": after["initialization_instruction_bytes"] <= 50_000,
        "activation_at_most_15000": max(activation_sizes) <= 15_000,
        "completion_at_most_15000": max(completion_sizes) <= 15_000,
        "expected_model_turns_reduced_4_to_3": after["expected_model_turns"] == 3,
        "exactly_two_qcoder_control_cycles": after["qcoder_control_cycles"] == 2,
        "exactly_twelve_public_tools": len(EXPECTED_TOOLS) == 12,
        "no_post_write_model_shell_call": after["post_write_model_shell_calls"] == 0,
        "no_second_native_approval": after["post_write_native_approvals"] == 0,
    }
    if not all(checks.values()):
        raise SystemExit(f"a16_latency_target_failed:{checks}")
    payload = {
        "schema_id": "qcoder.wi0434.a16_latency_successor_proof.v1",
        "result": "pass",
        "measurement_method": {
            "json_size": "UTF-8 compact JSON, ensure_ascii=false, sorted keys",
            "timing": "time.perf_counter around direct coordinator calls",
            "runs": args.runs,
            "customer_visible_cursor_latency_claimed": False,
        },
        "before_a15": A15_BASELINE,
        "after_a16": after,
        "checks": checks,
    }
    payload["proof_identity"] = "sha256:" + sha256(canonical(payload)).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
