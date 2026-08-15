#!/usr/bin/env python3
"""Produce sealed WI-0432/WI-0433 terminal and scale proof inputs."""

from __future__ import annotations

import argparse
import importlib
import json
import re
import resource
import sys
import time
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from qcoder.blueprint_decisions import catalog_entries
from qcoder.context_bridge_mcp import EXPECTED_TOOLS
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.d079_workflows import D079WorkflowError


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def protected_transport(protected_root: Path):
    sys.path.insert(0, str(protected_root))
    sys.path.insert(0, str(protected_root / "src"))
    module = importlib.import_module("research.protected_qrs_service_v0.hosted_mcp_pilot")
    gate = module.HostedMCPPilotGate(
        enabled=True,
        operator_allowlisted=True,
        consent_state="accepted",
        granted_scopes=(module.HOSTED_MCP_REQUIRED_SCOPE,),
        entitlement_category="internal_platform_pilot",
        rate_limit_allowed=True,
        coarse_client_version="0.6.0a13+d079-private",
    )

    class Transport:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def call(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
            request = deepcopy(dict(arguments))
            serialized_request = json.dumps(request, sort_keys=True)
            evidence_call = name in {
                "get_guided_evidence_context",
                "create_result_review_context_card",
            }
            result = module.handle_hosted_mcp_internal_request(
                tool_name=name, request_body=request, gate=gate
            )
            self.calls.append(
                {
                    "tool_name": name,
                    "status_code": result.status_code,
                    "input_bytes": len(canonical(request)),
                    "safe_error_category": result.response.get("error_category"),
                    "retention": result.response.get("retention"),
                    "retained_artifact_count": len(result.retained_artifacts),
                    "evidence_payload_local_path_detected": bool(
                        evidence_call
                        and re.search(r"(?:[A-Za-z]:\\\\|/(?:home|Users|mnt|tmp|var)/)", serialized_request)
                    ),
                    "evidence_payload_selected_raw_source_detected": bool(
                        evidence_call
                        and (
                            "QuantumCircuit(4, 4)" in serialized_request
                            or "NEIGHBOR_MARKER" in serialized_request
                            or "OPENQASM 2.0" in serialized_request
                        )
                    ),
                }
            )
            return deepcopy(result.response)

    return Transport()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protected-root", type=Path, required=True)
    parser.add_argument("--scale-gates", type=int, default=1_000_000)
    args = parser.parse_args()
    out = args.output.absolute()
    out.mkdir(parents=True, exist_ok=True)
    fixtures = out / "proof-fixtures"
    fixtures.mkdir(exist_ok=True)

    selected = fixtures / "selected_customer_program.py"
    selected.write_text(
        "from qiskit import QuantumCircuit\n"
        "circuit = QuantumCircuit(4, 4)\n"
        "circuit.h(0)\n"
        "circuit.cx(0, 1)\n"
        "circuit.measure(range(4), range(4))\n",
        encoding="utf-8",
    )
    neighbor = fixtures / "not_selected_neighbor.py"
    neighbor.write_text("NEIGHBOR_MARKER_MUST_NEVER_CROSS_BOUNDARY = True\n", encoding="utf-8")

    transport = protected_transport(args.protected_root)
    coordinator = CurrentLoopCoordinator(
        workspace_root=fixtures / "connected-assistant-workspace", transport=transport
    )
    customer_request = (
        "Help me design a four-qubit circuit that creates a correlated pair, leaves two "
        "qubits available for later work, and measures all four. Use readable Qiskit code. "
        "Do not edit or run anything yet; show me what you understood and ask before continuing."
    )
    facts = {
        item["profile_decision_id"]: f"Explicit customer treatment: {item['display_label']}"
        for item in catalog_entries("generic_qiskit")
        if item["generation_relevant"]
    }
    blueprint_context = {
        "explicit_user_facts": facts,
        "assistant_structuring": {
            "normalized_goal": "four-qubit readable Qiskit circuit with one correlated pair",
            "problem_size_meaning": "four logical qubits",
            "framework_requirement": "readable Qiskit and Python",
            "measurement_plan": "measure all four qubits with explicit classical mapping",
            "execution_intent": "construction only; the IDE or customer decides whether to run",
            "desired_output": "readable Python source and counts-compatible results",
        },
        "assistant_implementation_proposals": {
            "circuit_construction": "direct QuantumCircuit with readable operations",
            "measurement_structure": "explicit final measurement",
            "result_processing": "counts-compatible result representation",
        },
        "customer_dispositions": {},
        "current_step_controls": [
            "do not edit or run anything yet",
            "show me what you understood",
            "ask before continuing",
        ],
    }
    prepared_execution = coordinator.execute_connected_assistant_workflow(
        customer_instruction=customer_request,
        blueprint_context=blueprint_context,
    )
    proposal = prepared_execution["workflow_result"]
    # Proposals remain distinct from confirmed customer facts. The explicit facts above
    # make readiness deterministic; the implementation proposals remain subordinate.
    confirmed_execution = coordinator.execute_connected_assistant_workflow(
        customer_instruction=customer_request,
        proposal=proposal,
        confirmation=proposal["confirmation_requirements"],
    )
    confirmed = confirmed_execution["workflow_result"]
    blueprint_call_receipts = deepcopy(transport.calls)
    transport.calls.clear()
    negatives: dict[str, Any] = {}
    for name, field, value in (
        ("stale_revision", "artifact_revision", 0),
        ("wrong_reference", "artifact_identity", "proposal-wrongwrongwrongwrong22"),
        ("digest_mismatch", "proposal_digest", "0" * 64),
        ("missing_review_assertion", "exact_proposal_reviewed", False),
    ):
        altered = deepcopy(proposal["confirmation_requirements"])
        altered[field] = value
        try:
            coordinator.confirm_connected_assistant_blueprint(
                proposal=proposal, confirmation=altered
            )
        except D079WorkflowError as exc:
            negatives[name] = exc.recovery
        else:
            raise RuntimeError(f"negative unexpectedly succeeded: {name}")

    for name, mutator in (
        (
            "projection_mismatch",
            lambda value: value["customer_confirmation_projection"].__setitem__(
                "what_you_said", "altered display envelope"
            ),
        ),
        (
            "identity_envelope_mismatch",
            lambda value: (
                value.__setitem__("artifact_identity", "proposal-alteredEnvelopeIdentity"),
                value["confirmation_requirements"].__setitem__(
                    "artifact_identity", "proposal-alteredEnvelopeIdentity"
                ),
            ),
        ),
    ):
        altered_proposal = deepcopy(proposal)
        mutator(altered_proposal)
        try:
            coordinator.confirm_connected_assistant_blueprint(
                proposal=altered_proposal,
                confirmation=altered_proposal["confirmation_requirements"],
            )
        except D079WorkflowError as exc:
            negatives[name] = exc.recovery
        else:
            raise RuntimeError(f"negative unexpectedly succeeded: {name}")

    revision = coordinator.revise_connected_assistant_blueprint(
        proposal=proposal,
        semantic_changes={
            "assistant_structuring": {
                **blueprint_context["assistant_structuring"],
                "desired_output": "readable Python source plus an explicit counts contract",
            }
        },
    )
    revised_proposal = revision["proposal"]
    try:
        coordinator.confirm_connected_assistant_blueprint(
            proposal=revised_proposal,
            confirmation=proposal["confirmation_requirements"],
        )
    except D079WorkflowError as exc:
        negatives["old_confirmation_on_revised_proposal"] = exc.recovery
    else:
        raise RuntimeError("old confirmation unexpectedly confirmed revised proposal")

    evidence_execution = coordinator.execute_connected_assistant_workflow(
        customer_instruction="Review these selected files with qCoder.",
        selected_paths=[str(selected)],
    )
    evidence = evidence_execution["workflow_result"]
    if any(item["evidence_payload_local_path_detected"] for item in transport.calls):
        raise RuntimeError("local path crossed protected boundary")
    if any(item["evidence_payload_selected_raw_source_detected"] for item in transport.calls):
        raise RuntimeError("raw or neighboring source crossed protected boundary")

    scale = fixtures / "million_gate_scale.qasm"
    start = time.monotonic()
    with scale.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write('OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\n')
        block = "x q[0];\n" * 10_000
        whole, remainder = divmod(args.scale_gates, 10_000)
        for _ in range(whole):
            handle.write(block)
        handle.write("x q[0];\n" * remainder)
    reproduced_gate_count = 0
    with scale.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line == "x q[0];\n":
                reproduced_gate_count += 1
    protected_calls_before_scale = len(transport.calls)
    try:
        coordinator.execute_connected_assistant_workflow(
            customer_instruction="Review this selected file with qCoder.",
            selected_paths=[str(scale)],
        )
    except D079WorkflowError as exc:
        if exc.recovery.get("reason_category") != "selected_artifact_limit":
            raise
        scale_receipt = deepcopy(exc.recovery["limit_receipt"])
    else:
        raise RuntimeError("million-gate selected artifact unexpectedly bypassed local limit")
    if len(transport.calls) != protected_calls_before_scale:
        raise RuntimeError("limited raw artifact reached protected transport")
    elapsed = time.monotonic() - start
    semantic_scale_request = (
        "Design a bounded semantic handling plan for an approximately million-gate selected circuit. "
        "Do not edit or run anything yet."
    )
    semantic_execution = coordinator.execute_connected_assistant_workflow(
        customer_instruction=semantic_scale_request,
        blueprint_context=blueprint_context,
    )
    semantic_proposal = semantic_execution["workflow_result"]
    semantic_confirmed_execution = coordinator.execute_connected_assistant_workflow(
        customer_instruction=semantic_scale_request,
        proposal=semantic_proposal,
        confirmation=semantic_proposal["confirmation_requirements"],
    )
    semantic_confirmed = semantic_confirmed_execution["workflow_result"]
    scale_metrics = {
        "schema_id": "qcoder.d079.composite_scale_proof.v2",
        "semantic_decision_state_boundedness": {
            "fixture_gate_magnitude_reference": reproduced_gate_count,
            "intent_card_serialized_bytes": len(
                canonical(semantic_confirmed["algorithm_intent_card"])
            ),
            "blueprint_semantic_serialized_bytes": len(
                canonical(semantic_confirmed["implementation_blueprint"])
            ),
            "proposal_semantic_body_serialized_bytes": len(
                canonical(semantic_proposal)
            ),
            "decision_count": len(semantic_proposal["decision_records"]),
            "semantic_state_growth_basis": "canonical_meaningful_decisions_not_individual_gates",
            "raw_scale_artifact_in_semantic_state": False,
        },
        "actual_selected_file_evidence_review_limit": {
            **scale_receipt,
            "actual_file_bytes": scale.stat().st_size,
            "reproduced_fixture_gate_count": reproduced_gate_count,
            "fixture_construction": "fixed OpenQASM header plus exactly N literal x q[0] lines",
            "actual_production_path": "current-loop connected-assistant-workflow -> local_first_evidence_review",
            "extractor_gate_processing_claimed": False,
            "coverage_status": "LIMITED",
            "protected_request_bytes": 0,
            "no_downstream_complete_relabel": True,
        },
        "processing_wall_seconds": round(elapsed, 6),
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "accepted_scale_outcome": "B_explicit_supported_selected_artifact_limit",
    }

    write_json(out / "wi0432-terminal-proof.json", {
        "gate": "WI0432_IDE_FIRST_BLUEPRINT_DECISION_AND_CONFIRMATION_PASS",
        "ordinary_customer_request": customer_request,
        "proposal": proposal,
        "binding_owned_preparation_execution": prepared_execution,
        "confirmed_derived_artifact": confirmed,
        "binding_owned_confirmation_execution": confirmed_execution,
        "revision_proof": revision,
        "protected_call_receipts": blueprint_call_receipts,
        "negative_proofs": negatives,
        "customer_supplied_internal_choreography": False,
        "authority_separation": confirmed["confirmed_semantic_child"]["authority"],
        "retention": "process_and_discard",
    })
    write_json(out / "wi0433-terminal-proof.json", {
        "gate": "WI0433_LOCAL_FIRST_CONNECTED_ASSISTANT_EVIDENCE_REVIEW_PASS",
        "ordinary_customer_instruction": "Review this selected file with qCoder.",
        "workflow_result": evidence,
        "binding_owned_execution": evidence_execution,
        "protected_call_receipts": transport.calls,
        "selected_path_crossed_protected_boundary": False,
        "raw_artifact_crossed_protected_boundary": False,
        "neighbor_inspected": False,
        "retention": "process_and_discard",
    })
    write_json(out / "large-artifact-scale-proof.json", scale_metrics)

    inventory = []
    for path in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "packet-manifest.json"):
        inventory.append(
            {"path": str(path.relative_to(out)), "bytes": path.stat().st_size, "sha256": sha(path)}
        )
    manifest = {
        "schema_id": "qcoder.d079.integrated_terminal_proof_packet.v1",
        "result": "pass",
        "gates": [
            "WI0432_IDE_FIRST_BLUEPRINT_DECISION_AND_CONFIRMATION_PASS",
            "WI0433_LOCAL_FIRST_CONNECTED_ASSISTANT_EVIDENCE_REVIEW_PASS",
            "LARGE_ARTIFACT_BOUNDEDNESS_PROVEN",
        ],
        "public_context_bridge_tool_count": len(EXPECTED_TOOLS),
        "public_context_bridge_tools": list(EXPECTED_TOOLS),
        "protected_source_path": str(args.protected_root.absolute()),
        "inventory": inventory,
        "packet_identity_canonicalization": (
            "sha256 of RFC-8259-compatible UTF-8 JSON serialized with ensure_ascii=true, "
            "sort_keys=true, separators=(',', ':'), over the complete manifest object "
            "before packet_identity is added"
        ),
    }
    manifest["packet_identity"] = "sha256:" + sha256(canonical(manifest)).hexdigest()
    write_json(out / "packet-manifest.json", manifest)
    print(json.dumps({
        "packet": str(out),
        "packet_identity": manifest["packet_identity"],
        "manifest_sha256": sha(out / "packet-manifest.json"),
        "scale": scale_metrics,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
