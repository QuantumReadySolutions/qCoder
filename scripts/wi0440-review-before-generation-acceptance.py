#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
from importlib.resources import files
import json
from pathlib import Path
import statistics
import tempfile
import time
from typing import Any

from qcoder.current_loop_binding_mcp import handle_binding_jsonrpc_message
from qcoder.review_before_generation import build_first_value, render_first_value_markdown


EXACT_REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a Φ+ Bell state. "
    "Before generating the code, help me review how you interpret my request and the important "
    "implementation choices."
)
OUTSIDE_OLD_VOCABULARY = (
    "Use qCoder before coding, show me your understanding and the key choices, then make the "
    "program after I agree.",
    "Use qCoder to lay out your reading and the important tradeoffs first; once I approve, "
    "produce the program.",
    "Use qCoder to tell me what you think I am asking for and how you would build it. Wait for "
    "my approval before creating it.",
)
D127_UNSAFE_VALUES = (
    'print("premature source")',
    "qc.append(HGate(), [0])",
    "for item in values: print(item)",
    "bell q[0], q[1];",
    "assert condition",
    "pass",
    "break",
    "continue",
    "global value",
    "nonlocal value",
    "type Alias = int",
    'f"{value}"',
    "value if ready else fallback",
    "delay[100ns] q[0];",
    'defcalgrammar "openpulse";',
    "defcal x $0 { play(frame, waveform); }",
    "let alias = q[0:1];",
    "int[32] count = 0;",
    "box[1us] { delay[100ns] q[0]; }",
    "cal { play(frame, waveform); }",
    "extern foo(int[32]) -> bit;",
    "const int[32] n = 2;",
)
D127_SPLIT_VALUES = (
    ["print", "(", '"premature source")'],
    ["bell q[0]", ",", "q[1]", ";"],
    ["OPEN", "QASM", "3", ";"],
    ["Use", "recommended", "choices"],
    ["Review", "or change", "choices"],
)


def _load(name: str) -> dict[str, Any]:
    return json.loads(files("qcoder").joinpath("model_packs", name).read_text(encoding="utf-8"))


def _proposal(request: str, algorithm: str = "Bell") -> dict[str, Any]:
    proposal = _load("wi0440_bell_review_before_generation_v1.json")
    proposal["customer_constraints"] = []
    if algorithm == "Bell":
        return proposal
    profile = _load("wi0440_review_before_generation_class_matrix_v1.json")["profiles"][algorithm]
    proposal["recommended_interpretation"] = profile["recommended_interpretation"]
    proposal["implementation_recommendations"] = [
        "Use Qiskit QuantumCircuit.",
        profile["quantum_scope"],
        profile["construction"],
        profile["measurement_mapping"],
        profile["output_structure"],
    ]
    proposal["output_artifact"] = profile["intended_artifact"]
    for index, key in ((1, "construction"), (2, "measurement_mapping"), (3, "output_structure")):
        proposal["material_choices"][index]["recommendation"] = profile[key]
    return proposal


def _binding_payload(
    workspace: Path,
    request: str | None,
    proposal: dict[str, Any] | None = None,
    **arguments: object,
) -> dict[str, Any]:
    call_arguments: dict[str, object] = dict(arguments)
    if request is not None:
        call_arguments["request_text"] = request
    if proposal is not None:
        call_arguments["connected_assistant_proposal"] = proposal
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "begin_current_loop", "arguments": call_arguments},
        },
        workspace_root=workspace,
    )
    if response is None:
        raise RuntimeError("binding_response_missing")
    return response["result"]["structuredContent"]


def _binding_call(
    workspace: Path,
    request: str | None,
    proposal: dict[str, Any] | None = None,
    **arguments: object,
) -> dict[str, Any]:
    payload = _binding_payload(workspace, request, proposal, **arguments)
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
        description="Run deterministic local WI-0440 timing acceptance without client or network."
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
    cases.extend((request, "Bell") for request in OUTSIDE_OLD_VOCABULARY)
    initial: list[float] = []
    confirmation: list[float] = []
    rendering: list[float] = []
    combined: list[float] = []
    transition: list[float] = []
    unsafe_rejection: list[float] = []
    tokens: set[str] = set()
    scenario_counts = {
        "review_first_value": 0,
        "duplicate_call": 0,
        "generic_proposal_rejection": 0,
        "unsafe_content_rejection": 0,
        "confirmation_without_replay": 0,
        "duplicate_confirmation": 0,
        "stale_token": 0,
        "source_modification": 0,
        "direct_generation_control": 0,
        "quiet_projection": 0,
        "split_source_rejection": 0,
        "fake_action_rejection": 0,
        "execution_authority_binding": 0,
        "empty_customer_constraints": 0,
        "material_customer_constraints": 0,
    }
    for _ in range(args.repetitions):
        for request, algorithm in cases:
            proposal = _proposal(request, algorithm)
            started = time.monotonic()
            first = build_first_value(request, deepcopy(proposal))
            markdown = render_first_value_markdown(first)
            rendering_elapsed = time.monotonic() - started
            if request == EXACT_REQUEST:
                headings = [line for line in markdown.splitlines() if line.startswith("## ")]
                if headings != [
                    "## Goal and scope",
                    "## Implementation",
                    "## Output and authority",
                ]:
                    raise RuntimeError("quiet_projection_group_contract_failed")
                scenario_counts["quiet_projection"] += 1
            with tempfile.TemporaryDirectory(prefix="qcoder-wi0440-acceptance-") as directory:
                started = time.monotonic()
                payload = _binding_call(Path(directory), request, deepcopy(proposal))
                initial_elapsed = time.monotonic() - started
            initial.append(initial_elapsed)
            rendering.append(rendering_elapsed)
            combined.append(initial_elapsed + rendering_elapsed)
            tokens.add(payload["prior_result_token"])
            scenario_counts["review_first_value"] += 1

        proposal = _proposal(EXACT_REQUEST)
        with tempfile.TemporaryDirectory(prefix="qcoder-wi0440-duplicate-") as directory:
            workspace = Path(directory)
            first = _binding_call(workspace, EXACT_REQUEST, deepcopy(proposal))
            started = time.monotonic()
            duplicate = _binding_call(workspace, EXACT_REQUEST, deepcopy(proposal))
            duplicate_elapsed = time.monotonic() - started
        if duplicate.get("category") != "review_before_generation_duplicate":
            raise RuntimeError("duplicate_call_not_idempotent")
        initial.append(duplicate_elapsed)
        rendering.append(0.0)
        combined.append(duplicate_elapsed)
        scenario_counts["duplicate_call"] += 1

        generic = _proposal(EXACT_REQUEST)
        generic["implementation_recommendations"] = ["A concrete option will be used."]
        with tempfile.TemporaryDirectory(prefix="qcoder-wi0440-generic-") as directory:
            started = time.monotonic()
            rejected = _binding_payload(Path(directory), EXACT_REQUEST, generic)
            generic_elapsed = time.monotonic() - started
        if rejected.get("ok") or rejected.get("category") != "review_proposal_not_substantive":
            raise RuntimeError("generic_proposal_not_rejected")
        initial.append(generic_elapsed)
        rendering.append(0.0)
        combined.append(generic_elapsed)
        scenario_counts["generic_proposal_rejection"] += 1

        for unsafe_value in ("QuantumCircuit(2, 2)", *D127_UNSAFE_VALUES):
            unsafe = _proposal(EXACT_REQUEST)
            unsafe["implementation_recommendations"][0] = unsafe_value
            with tempfile.TemporaryDirectory(prefix="qcoder-wi0440-unsafe-") as directory:
                started = time.monotonic()
                rejected = _binding_payload(Path(directory), EXACT_REQUEST, unsafe)
                unsafe_elapsed = time.monotonic() - started
            if (
                rejected.get("ok")
                or rejected.get("category") != "review_proposal_source_or_qasm_rejected"
            ):
                raise RuntimeError("unsafe_content_not_rejected")
            initial.append(unsafe_elapsed)
            rendering.append(0.0)
            combined.append(unsafe_elapsed)
            unsafe_rejection.append(unsafe_elapsed)
            scenario_counts["unsafe_content_rejection"] += 1

        for unsafe_values in D127_SPLIT_VALUES:
            scenario = (
                "fake_action_rejection"
                if unsafe_values[0] in {"Use", "Review"}
                else "split_source_rejection"
            )
            unsafe = _proposal(EXACT_REQUEST)
            unsafe["implementation_recommendations"][0:2] = unsafe_values
            with tempfile.TemporaryDirectory(prefix="qcoder-wi0440-split-unsafe-") as directory:
                started = time.monotonic()
                rejected = _binding_payload(Path(directory), EXACT_REQUEST, unsafe)
                rejected_elapsed = time.monotonic() - started
            if rejected.get("ok"):
                raise RuntimeError(f"{scenario}_not_rejected")
            unsafe_rejection.append(rejected_elapsed)
            scenario_counts[scenario] += 1

        execution_cases = (
            (EXACT_REQUEST, "not_requested", True),
            (
                "Use qCoder to review the Qiskit plan, then execute it after I approve.",
                "held_for_separate_authorization",
                True,
            ),
            (
                "Use qCoder to review the Qiskit plan; do not execute it.",
                "not_requested",
                True,
            ),
            (
                "Use qCoder to review the Qiskit plan; execution later.",
                "not_requested",
                True,
            ),
        )
        for execution_request, execution_state, expected_confirmable in execution_cases:
            execution_proposal = _proposal(execution_request)
            execution_proposal["execution_request"] = execution_state
            started = time.monotonic()
            execution_first = build_first_value(execution_request, execution_proposal)
            execution_elapsed = time.monotonic() - started
            if execution_first["confirmable"] is not expected_confirmable:
                raise RuntimeError("execution_authority_binding_failed")
            initial.append(execution_elapsed)
            rendering.append(0.0)
            combined.append(execution_elapsed)
            scenario_counts["execution_authority_binding"] += 1

        empty_constraints = _proposal(EXACT_REQUEST)
        started = time.monotonic()
        build_first_value(EXACT_REQUEST, empty_constraints)
        empty_elapsed = time.monotonic() - started
        initial.append(empty_elapsed)
        rendering.append(0.0)
        combined.append(empty_elapsed)
        scenario_counts["empty_customer_constraints"] += 1

        material_constraints = _load("wi0440_bell_review_before_generation_v1.json")
        started = time.monotonic()
        build_first_value(EXACT_REQUEST, material_constraints)
        material_elapsed = time.monotonic() - started
        initial.append(material_elapsed)
        rendering.append(0.0)
        combined.append(material_elapsed)
        scenario_counts["material_customer_constraints"] += 1

        with tempfile.TemporaryDirectory(prefix="qcoder-wi0440-confirm-") as directory:
            workspace = Path(directory)
            first = _binding_call(workspace, EXACT_REQUEST, deepcopy(proposal))
            token = first["prior_result_token"]
            started = time.monotonic()
            confirmed = _binding_call(
                workspace,
                None,
                review_action="Use recommended choices",
                prior_result_token=token,
            )
            confirmed_elapsed = time.monotonic() - started
            started = time.monotonic()
            duplicate_confirmation = _binding_call(
                workspace,
                None,
                review_action="Use recommended choices",
                prior_result_token=token,
            )
            duplicate_confirmation_elapsed = time.monotonic() - started
        if confirmed.get("category") != "review_confirmation_generation_ready":
            raise RuntimeError("confirmation_not_generation_ready")
        if duplicate_confirmation.get("category") != "review_confirmation_duplicate":
            raise RuntimeError("duplicate_confirmation_not_idempotent")
        confirmation.append(confirmed_elapsed)
        transition.append(confirmed_elapsed)
        confirmation.append(duplicate_confirmation_elapsed)
        transition.append(duplicate_confirmation_elapsed)
        scenario_counts["confirmation_without_replay"] += 1
        scenario_counts["duplicate_confirmation"] += 1

        with tempfile.TemporaryDirectory(prefix="qcoder-wi0440-stale-") as directory:
            workspace = Path(directory)
            _binding_call(workspace, EXACT_REQUEST, deepcopy(proposal))
            started = time.monotonic()
            stale = _binding_payload(
                workspace,
                None,
                review_action="Use recommended choices",
                prior_result_token="review-result-" + "0" * 64,
            )
            stale_elapsed = time.monotonic() - started
        if stale.get("category") != "review_confirmation_stale_token" or stale.get("ok"):
            raise RuntimeError("stale_token_not_rejected")
        confirmation.append(stale_elapsed)
        transition.append(stale_elapsed)
        scenario_counts["stale_token"] += 1

        modification_request = (
            "Use qCoder to review proposed Qiskit changes to selected.py before modifying source."
        )
        modification_proposal = _proposal(modification_request)
        modification_proposal["transaction_kind"] = "review_before_source_modification"
        with tempfile.TemporaryDirectory(prefix="qcoder-wi0440-modification-") as directory:
            workspace = Path(directory)
            (workspace / "selected.py").write_text("ORIGINAL\n", encoding="utf-8")
            started = time.monotonic()
            _binding_call(
                workspace,
                modification_request,
                modification_proposal,
                selected_artifact_paths=["selected.py"],
            )
            modification_elapsed = time.monotonic() - started
            if (workspace / "selected.py").read_text(encoding="utf-8") != "ORIGINAL\n":
                raise RuntimeError("source_modified_before_confirmation")
        initial.append(modification_elapsed)
        rendering.append(0.0)
        combined.append(modification_elapsed)
        scenario_counts["source_modification"] += 1

        direct_request = "Use qCoder to create a small Qiskit program in direct.py now."
        with tempfile.TemporaryDirectory(prefix="qcoder-wi0440-direct-") as directory:
            workspace = Path(directory)
            started = time.monotonic()
            direct = _binding_call(
                workspace,
                direct_request,
                intended_artifact_paths={"source": "direct.py"},
            )
            direct_elapsed = time.monotonic() - started
            if (workspace / "direct.py").exists():
                raise RuntimeError("direct_generation_control_created_source")
        if direct.get("review_before_generation") is not None:
            raise RuntimeError("direct_generation_control_received_review_ceremony")
        initial.append(direct_elapsed)
        rendering.append(0.0)
        combined.append(direct_elapsed)
        scenario_counts["direct_generation_control"] += 1

    initial_summary = _summary(initial)
    confirmation_summary = _summary(confirmation)
    rendering_summary = _summary(rendering)
    combined_summary = _summary(combined)
    transition_summary = _summary(transition)
    unsafe_rejection_summary = _summary(unsafe_rejection)
    first_budget = (
        combined_summary["median_seconds"] <= 10
        and combined_summary["p95_seconds"] <= 20
        and combined_summary["maximum_seconds"] <= 30
    )
    result = {
        "schema_id": "qcoder.wi0440.local_timing_acceptance.v2",
        "population_cases": (len(initial) + len(confirmation)) // args.repetitions,
        "repetitions": args.repetitions,
        "samples": len(initial) + len(confirmation),
        "unique_prior_result_tokens": len(tokens),
        "scenario_counts": scenario_counts,
        "connected_assistant_model": "not_measured_fixture_driven_automation",
        "qcoder_local_initial_transaction": initial_summary,
        "qcoder_local_confirmation_transaction": confirmation_summary,
        "protected_service_calls": 0,
        "protected_service_seconds": 0,
        "projection_and_rendering": rendering_summary,
        "combined_local_first_value": combined_summary,
        "generation_ready_transition": transition_summary,
        "unsafe_content_rejection": unsafe_rejection_summary,
        "first_useful_interpretation_budget_pass": first_budget,
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
        if result["first_useful_interpretation_budget_pass"]
        and result["first_material_decision_budget_pass"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
