#!/usr/bin/env python3
"""Deterministic local-only D-136 mechanics and timing acceptance."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from statistics import median

from qcoder.current_loop_binding_mcp import handle_binding_jsonrpc_message
from qcoder.current_loop_operator_timing import (
    consume_begin_attempt_ledger,
    record_begin_attempt,
)

GHZ_REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a three-qubit GHZ "
    "state. Before generating the code, help me review how you interpret my request and the "
    "important implementation choices."
)


def ghz_content(*, target: str | None = None) -> dict:
    return {
        "interpretation": (
            "Create a clear three-qubit GHZ Qiskit program and review its implementation plan "
            "before producing source."
        ),
        "implementation_recommendations": [
            {"label": "Framework", "value": "Use Qiskit QuantumCircuit."},
            {"label": "Registers", "value": "Use three qubits and three classical bits."},
            {
                "label": "Preparation",
                "value": "Apply H to q0, then CX from q0 to q1 and CX from q1 to q2.",
            },
            {
                "label": "Measurement",
                "value": "Measure all three qubits into matching classical bits.",
            },
        ],
        "output_artifact": "Readable Python source after confirmation",
        "limitations": ["The review does not claim hardware performance."],
        "blocking_question": None,
        "proposed_source_target": target,
    }


def _summary(values: list[int]) -> dict[str, int]:
    ordered = sorted(values)
    p95 = ordered[max(0, min(len(ordered) - 1, (95 * len(ordered) + 99) // 100 - 1))]
    return {"median_ns": int(median(ordered)), "p95_ns": p95, "max_ns": max(ordered)}


def _call(root: Path, arguments: dict, message_id: int = 1) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": message_id,
            "method": "tools/call",
            "params": {"name": "begin_current_loop", "arguments": arguments},
        },
        workspace_root=root,
    )
    if response is None:
        raise RuntimeError("missing_response")
    return response["result"]


def run(repetitions: int) -> dict:
    names = (
        "accepted_first_value",
        "projection_rendering",
        "invented_target_convergence",
        "material_blocker",
        "unsafe_rejection",
        "inline_confirmation",
        "operator_ledger_create_consume",
    )
    populations: dict[str, list[int]] = {name: [] for name in names}
    for _ in range(repetitions):
        with tempfile.TemporaryDirectory(prefix="qcoder-d136-timing-") as temporary:
            base = Path(temporary)
            arguments = {"request_text": GHZ_REQUEST, "review_content": ghz_content()}
            started = time.perf_counter_ns()
            accepted = _call(base / "accepted", arguments)
            populations["accepted_first_value"].append(time.perf_counter_ns() - started)

            started = time.perf_counter_ns()
            text = accepted["content"][0]["text"]
            json.dumps(accepted["structuredContent"], ensure_ascii=True, sort_keys=True)
            if not text.startswith("## Goal and scope"):
                raise RuntimeError("canonical_projection_invalid")
            populations["projection_rendering"].append(time.perf_counter_ns() - started)

            started = time.perf_counter_ns()
            invented = _call(
                base / "invented",
                {"request_text": GHZ_REQUEST, "review_content": ghz_content(target="invented.py")},
            )
            if "Proposed source target" in invented["content"][0]["text"]:
                raise RuntimeError("invented_target_not_converged")
            populations["invented_target_convergence"].append(time.perf_counter_ns() - started)

            blocker_content = ghz_content()
            blocker_content["blocking_question"] = "Which oracle behavior should be used?"
            started = time.perf_counter_ns()
            blocker = _call(
                base / "blocker",
                {
                    "request_text": "Use qCoder to review an underspecified Qiskit source plan before generation.",
                    "review_content": blocker_content,
                },
            )
            if (
                blocker["structuredContent"]["category"]
                != "review_before_generation_terminal_blocker"
            ):
                raise RuntimeError("material_blocker_invalid")
            populations["material_blocker"].append(time.perf_counter_ns() - started)

            unsafe_content = ghz_content()
            unsafe_content["implementation_recommendations"][1]["value"] = "print('unsafe')"
            started = time.perf_counter_ns()
            rejected = _call(
                base / "unsafe",
                {"request_text": GHZ_REQUEST, "review_content": unsafe_content},
            )
            if not rejected["isError"]:
                raise RuntimeError("unsafe_content_not_rejected")
            populations["unsafe_rejection"].append(time.perf_counter_ns() - started)

            started = time.perf_counter_ns()
            confirmed = _call(
                base / "accepted",
                {
                    "review_action": "Use recommended choices",
                    "prior_result_token": accepted["structuredContent"]["prior_result_token"],
                },
                2,
            )
            if (
                confirmed["structuredContent"]["generation_ready_context"]["category"]
                != "confirmed_plan_generation_ready_inline_source"
            ):
                raise RuntimeError("inline_confirmation_invalid")
            populations["inline_confirmation"].append(time.perf_counter_ns() - started)

            receipt_root = base / "ledger"
            receipt_root.mkdir()
            entry = time.perf_counter_ns()
            complete = max(time.perf_counter_ns(), entry + 1)
            returned = max(time.perf_counter_ns(), complete)
            started = time.perf_counter_ns()
            record_begin_attempt(
                state_root=receipt_root,
                setup_generation="a" * 64,
                session_sha256="b" * 64,
                status="accepted",
                category="review_before_generation_ready",
                operation_entry_ns=entry,
                processing_complete_ns=complete,
                result_return_ns=returned,
                semantic_revision_sha256="c" * 64,
            )
            consume_begin_attempt_ledger(
                state_root=receipt_root,
                setup_generation="a" * 64,
                session_sha256="b" * 64,
            )
            populations["operator_ledger_create_consume"].append(time.perf_counter_ns() - started)
    return {
        "schema_id": "qcoder.wi0440.d136.local_acceptance_timing.v1",
        "case_count": len(populations),
        "sample_count": repetitions * len(populations),
        "repetitions": repetitions,
        "timing": {name: _summary(values) for name, values in populations.items()},
        "protected_service_calls": 0,
        "measurement_scope": "qcoder_local_non_windows_environmental_preproof_only",
        "model_client_customer_timing": "not_measured",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=20)
    args = parser.parse_args()
    if not 20 <= args.repetitions <= 100:
        raise SystemExit("repetitions_must_be_between_20_and_100")
    print(json.dumps(run(args.repetitions), ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
