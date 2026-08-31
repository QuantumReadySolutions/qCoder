#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
from importlib.resources import files
import json
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from qcoder.current_loop_binding_mcp import handle_binding_jsonrpc_message
from qcoder.review_before_generation import build_first_value, render_first_value_markdown


EXACT_REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a Φ+ Bell state. "
    "Before generating the code, help me review how you interpret my request and the important "
    "implementation choices."
)


def _load(name: str) -> dict[str, Any]:
    return json.loads(files("qcoder").joinpath("model_packs", name).read_text(encoding="utf-8"))


def _set_item(proposal: dict[str, Any], group: int, item_id: str, value: str) -> None:
    next(item for item in proposal["review_groups"][group]["items"] if item["item_id"] == item_id)[
        "value"
    ] = value


def _proposal(request: str, algorithm: str = "Bell") -> dict[str, Any]:
    proposal = _load("wi0440_bell_review_before_generation_v1.json")
    proposal["exact_request_utf8_sha256"] = sha256(request.encode("utf-8")).hexdigest()
    if algorithm == "Bell":
        return proposal
    profile = _load("wi0440_review_before_generation_class_matrix_v1.json")["profiles"][algorithm]
    proposal["recommended_interpretation"] = profile["recommended_interpretation"]
    for item_id in (
        "intended_artifact",
        "quantum_scope",
        "classical_scope",
        "measurement_basis",
    ):
        _set_item(proposal, 0, item_id, profile[item_id])
    for item_id in ("construction", "measurement_mapping", "output_structure"):
        _set_item(proposal, 1, item_id, profile[item_id])
    for index, key in ((1, "construction"), (2, "measurement_mapping"), (3, "output_structure")):
        proposal["material_choices"][index]["recommended_value"] = profile[key]
    return proposal


def _binding_call(workspace: Path, request: str, proposal: dict[str, Any]) -> dict[str, Any]:
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "begin_current_loop",
                "arguments": {
                    "request_text": request,
                    "connected_assistant_proposal": proposal,
                },
            },
        },
        workspace_root=workspace,
    )
    if response is None:
        raise RuntimeError("binding_response_missing")
    payload = response["result"]["structuredContent"]
    if payload.get("ok") is not True:
        raise RuntimeError(str(payload.get("category") or "binding_failed"))
    return payload


def _percentile(values: list[float], percentage: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentage + 0.999999)))
    return ordered[index]


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "median_seconds": round(statistics.median(values), 6),
        "p95_seconds": round(_percentile(values, 0.95), 6),
        "maximum_seconds": round(max(values), 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic local WI-0440 timing acceptance without a client or network."
    )
    parser.add_argument("--repetitions", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 100:
        raise SystemExit("repetitions_must_be_between_1_and_100")

    matrix = _load("wi0440_review_before_generation_class_matrix_v1.json")
    cases = [(EXACT_REQUEST, "Bell")]
    cases.extend(
        (str(case["request"]), str(case["algorithm"]))
        for case in matrix["cases"]
        if case["variant"] != "material_blocker"
    )
    cases.extend(
        [
            (
                "Use qCoder to review my Bell Qiskit implementation choices before creating source.",
                "Bell",
            ),
            (
                "Create a Bell Qiskit program after qCoder checks the choices with me.",
                "Bell",
            ),
        ]
    )
    transaction: list[float] = []
    rendering: list[float] = []
    combined: list[float] = []
    revisions: set[str] = set()
    for _ in range(args.repetitions):
        for request, algorithm in cases:
            proposal = _proposal(request, algorithm)
            started = time.monotonic()
            first = build_first_value(request, deepcopy(proposal))
            render_first_value_markdown(first)
            rendering_elapsed = time.monotonic() - started
            with tempfile.TemporaryDirectory(prefix="qcoder-wi0440-acceptance-") as directory:
                started = time.monotonic()
                payload = _binding_call(Path(directory), request, deepcopy(proposal))
                transaction_elapsed = time.monotonic() - started
            transaction.append(transaction_elapsed)
            rendering.append(rendering_elapsed)
            combined.append(transaction_elapsed + rendering_elapsed)
            revisions.add(payload["review_before_generation"]["review_revision"])

    transaction_summary = _summary(transaction)
    rendering_summary = _summary(rendering)
    combined_summary = _summary(combined)
    within_budget = (
        combined_summary["median_seconds"] <= 10
        and combined_summary["p95_seconds"] <= 20
        and combined_summary["maximum_seconds"] <= 30
    )
    result = {
        "schema_id": "qcoder.wi0440.local_timing_acceptance.v1",
        "population_cases": len(cases),
        "repetitions": args.repetitions,
        "samples": len(combined),
        "unique_request_bound_revisions": len(revisions),
        "connected_assistant_model": "not_measured_fixture_driven_automation",
        "qcoder_local_transaction": transaction_summary,
        "protected_service_seconds": 0,
        "projection_and_rendering": rendering_summary,
        "combined_deterministic_qcoder_operation": combined_summary,
        "first_useful_interpretation": combined_summary,
        "first_material_decision": combined_summary,
        "first_useful_interpretation_budget_pass": within_budget,
        "first_material_decision_budget_pass": (
            combined_summary["median_seconds"] <= 15
            and combined_summary["p95_seconds"] <= 30
            and combined_summary["maximum_seconds"] <= 45
        ),
        "customer_visible_end_to_end": "pending_targeted_native_windows_cursor_repeat",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return (
        0
        if all(
            (
                result["first_useful_interpretation_budget_pass"],
                result["first_material_decision_budget_pass"],
            )
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
