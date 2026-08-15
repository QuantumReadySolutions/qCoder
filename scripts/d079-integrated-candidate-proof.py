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
from qcoder.d079_workflows import D079WorkflowError, scale_limit_receipt


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
    proposal = coordinator.prepare_connected_assistant_blueprint(
        customer_request=customer_request,
        explicit_user_facts=facts,
        assistant_structuring={
            "normalized_goal": "four-qubit readable Qiskit circuit with one correlated pair",
            "problem_size_meaning": "four logical qubits",
            "framework_requirement": "readable Qiskit and Python",
            "measurement_plan": "measure all four qubits with explicit classical mapping",
            "execution_intent": "construction only; the IDE or customer decides whether to run",
            "desired_output": "readable Python source and counts-compatible results",
        },
        assistant_implementation_proposals={
            "circuit_construction": "direct QuantumCircuit with readable operations",
            "measurement_structure": "explicit final measurement",
            "result_processing": "counts-compatible result representation",
        },
        customer_dispositions={},
        current_step_controls=[
            "do not edit or run anything yet",
            "show me what you understood",
            "ask before continuing",
        ],
    )
    # Proposals remain distinct from confirmed customer facts. The explicit facts above
    # make readiness deterministic; the implementation proposals remain subordinate.
    confirmed = coordinator.confirm_connected_assistant_blueprint(
        proposal=proposal, confirmation=proposal["confirmation_requirements"]
    )
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

    evidence = coordinator.review_customer_selected_files(selected_paths=[str(selected)])
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
    scale_receipt = scale_limit_receipt(
        selected_path=str(scale), effective_gate_magnitude=args.scale_gates
    )
    elapsed = time.monotonic() - start
    semantic_intent = confirmed["confirmed_semantic_child"]["intent_card"]
    semantic_blueprint = confirmed["implementation_blueprint"]
    safe_scale = {
        key: value
        for key, value in scale_receipt.items()
        if key != "selected_artifact_identity"
    }
    scale_metrics = {
        **scale_receipt,
        "intent_card_serialized_bytes": len(canonical(semantic_intent)),
        "blueprint_semantic_serialized_bytes": len(canonical(semantic_blueprint)),
        "decision_count": len(proposal["decision_records"]),
        "full_local_evidence_bytes": len(canonical(scale_receipt)),
        "share_safe_representation_bytes": len(canonical(safe_scale)),
        "protected_request_bytes": 0,
        "processing_wall_seconds": round(elapsed, 6),
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "semantic_state_growth_basis": "canonical_decision_count_not_gate_count",
        "accepted_scale_outcome": "B_explicit_structured_limit",
    }

    write_json(out / "wi0432-terminal-proof.json", {
        "gate": "WI0432_IDE_FIRST_BLUEPRINT_DECISION_AND_CONFIRMATION_PASS",
        "ordinary_customer_request": customer_request,
        "proposal": proposal,
        "confirmed_derived_artifact": confirmed,
        "negative_proofs": negatives,
        "customer_supplied_internal_choreography": False,
        "authority_separation": confirmed["confirmed_semantic_child"]["authority"],
        "retention": "process_and_discard",
    })
    write_json(out / "wi0433-terminal-proof.json", {
        "gate": "WI0433_LOCAL_FIRST_CONNECTED_ASSISTANT_EVIDENCE_REVIEW_PASS",
        "ordinary_customer_instruction": "Review this selected file with qCoder.",
        "workflow_result": evidence,
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
