#!/usr/bin/env python3
"""Deterministic local mechanics timing for the D-135 successor."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from statistics import median

from qcoder.current_loop_binding_mcp import handle_binding_jsonrpc_message
from qcoder.current_loop_operator_timing import (
    consume_stdio_operator_timing,
    record_stdio_operator_timing,
)

ROOT = Path(__file__).resolve().parents[1]
REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a Φ+ Bell state. "
    "Before generating the code, help me review how you interpret my request and the important "
    "implementation choices."
)


def _proposal() -> dict:
    return json.loads(
        (ROOT / "src/qcoder/model_packs/wi0440_bell_review_before_generation_v1.json").read_text(
            encoding="utf-8"
        )
    )


def _summary(values: list[int]) -> dict[str, int]:
    ordered = sorted(values)
    p95 = ordered[max(0, min(len(ordered) - 1, (95 * len(ordered) + 99) // 100 - 1))]
    return {"median_ns": int(median(ordered)), "p95_ns": p95, "max_ns": max(ordered)}


def _call(root: Path, message_id: int, arguments: dict) -> dict:
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
    populations: dict[str, list[int]] = {
        name: []
        for name in (
            "clean_inline",
            "invented_target_convergence",
            "grounded_file_review",
            "projection_rendering",
            "inline_confirmation",
            "unsafe_target_convergence",
            "operator_receipt_create_consume",
        )
    }
    for index in range(repetitions):
        with tempfile.TemporaryDirectory(prefix="qcoder-d135-timing-") as temporary:
            base = Path(temporary)
            proposal = _proposal()
            started = time.perf_counter_ns()
            clean = _call(
                base / "clean",
                1,
                {"request_text": REQUEST, "connected_assistant_proposal": proposal},
            )
            populations["clean_inline"].append(time.perf_counter_ns() - started)
            render_started = time.perf_counter_ns()
            canonical_text = clean["content"][0]["text"].encode("utf-8")
            json.loads(json.dumps(clean["structuredContent"], sort_keys=True))
            if not canonical_text.startswith(b"## Goal and scope"):
                raise RuntimeError("canonical_render_invalid")
            populations["projection_rendering"].append(time.perf_counter_ns() - render_started)

            invented = deepcopy(proposal)
            invented["source_delivery"] = {"mode": "workspace_file", "target": "bell.py"}
            started = time.perf_counter_ns()
            _call(
                base / "invented",
                1,
                {"request_text": REQUEST, "connected_assistant_proposal": invented},
            )
            populations["invented_target_convergence"].append(time.perf_counter_ns() - started)

            file_request = (
                "Use qCoder to review a Qiskit Bell plan before generating source in bell.py."
            )
            file_proposal = deepcopy(proposal)
            file_proposal["constraints"] = []
            file_proposal["source_delivery"] = {"mode": "workspace_file", "target": "bell.py"}
            started = time.perf_counter_ns()
            _call(
                base / "file",
                1,
                {"request_text": file_request, "connected_assistant_proposal": file_proposal},
            )
            populations["grounded_file_review"].append(time.perf_counter_ns() - started)

            started = time.perf_counter_ns()
            _call(
                base / "clean",
                2,
                {
                    "review_action": "Use recommended choices",
                    "prior_result_token": clean["structuredContent"]["prior_result_token"],
                },
            )
            populations["inline_confirmation"].append(time.perf_counter_ns() - started)

            unsafe = deepcopy(proposal)
            unsafe["source_delivery"] = {"mode": "workspace_file", "target": "../escape.py"}
            started = time.perf_counter_ns()
            _call(
                base / "unsafe",
                1,
                {"request_text": REQUEST, "connected_assistant_proposal": unsafe},
            )
            populations["unsafe_target_convergence"].append(time.perf_counter_ns() - started)

            receipt_root = base / "receipt"
            receipt_root.mkdir()
            started = time.perf_counter_ns()
            record_stdio_operator_timing(
                state_root=receipt_root,
                setup_generation="a" * 64,
                session_sha256="b" * 64,
                operation_name="begin_current_loop",
                operation_entry_ns=1,
                processing_complete_ns=2,
                result_return_ns=3,
            )
            consume_stdio_operator_timing(
                state_root=receipt_root,
                setup_generation="a" * 64,
                session_sha256="b" * 64,
            )
            populations["operator_receipt_create_consume"].append(time.perf_counter_ns() - started)
    return {
        "schema_id": "qcoder.wi0440.d135.local_acceptance_timing.v1",
        "case_count": len(populations),
        "sample_count": repetitions * len(populations),
        "repetitions": repetitions,
        "timing": {name: _summary(values) for name, values in populations.items()},
        "protected_service_calls": 0,
        "measurement_scope": "qcoder_local_product_mechanics_only",
        "model_client_customer_timing": "not_measured",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=20)
    args = parser.parse_args()
    if not 3 <= args.repetitions <= 100:
        raise SystemExit("repetitions_must_be_between_3_and_100")
    print(json.dumps(run(args.repetitions), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
