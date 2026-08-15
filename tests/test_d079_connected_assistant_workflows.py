from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from qcoder.blueprint_decisions import catalog_entries
from qcoder.context_bridge_mcp import (
    CLIENT_ACTIVATION_INSTRUCTIONS,
    EXPECTED_TOOLS,
    build_client_binding_descriptor,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.d079_workflows import (
    D079WorkflowError,
    _assert_protected_projection,
    confirm_ide_first_blueprint,
    prepare_ide_first_blueprint,
    review_selected_files_with_qcoder,
    scale_limit_receipt,
)


def _all_explicit_facts() -> dict[str, str]:
    return {
        item["profile_decision_id"]: f"customer choice for {item['display_label']}"
        for item in catalog_entries("generic_qiskit")
        if item["generation_relevant"]
    }


def _proposal(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "customer_request": (
            "Build a four-qubit circuit and measure it. Do not edit yet; show me the evidence and stop."
        ),
        "explicit_user_facts": _all_explicit_facts(),
        "assistant_structuring": {"goal": "four-qubit measured circuit"},
        "assistant_implementation_proposals": {
            "result_processing": "counts dictionary",
        },
        "customer_dispositions": {},
    }
    values.update(changes)
    return prepare_ide_first_blueprint(**values)  # type: ignore[arg-type]


def _protected(calls: list[tuple[str, dict[str, object]]]):
    def invoke(tool_name: str, arguments: object) -> dict[str, object]:
        calls.append((tool_name, deepcopy(dict(arguments))))  # type: ignore[arg-type]
        status = (
            "assistant_context_ready"
            if tool_name == "get_guided_evidence_context"
            else "result_review_context_card_ready"
        )
        return {
            "tool_name": tool_name,
            "ok": True,
            "context_status": status,
            "retention": "process_and_discard",
            "retained_artifacts": [],
        }

    return invoke


def test_decision_aware_default_preserves_six_semantic_layers_and_temporary_control() -> None:
    result = _proposal()
    layers = result["semantic_layers"]
    assert result["decision_aware_path"] == "readiness_resolution_v1"
    assert result["customer_choreography_required"] is False
    assert layers["original_customer_request_verbatim"].endswith(
        "Do not edit yet; show me the evidence and stop."
    )
    assert layers["explicit_user_facts"] != layers["assistant_structuring"]
    assert layers["assistant_implementation_proposals"]["generic_qiskit.result_processing"] == "counts dictionary"
    assert layers["customer_confirmation"] == "not_yet_confirmed"
    assert "Do not edit yet" in layers["current_step_authority_controls"]
    assert "show me the evidence and stop" in layers["current_step_authority_controls"]
    assert layers["durable_blueprint_constraints"] == []
    assert result["authority"]["qcoder_edit_authority"] is False
    assert result["authority"]["qcoder_run_authority"] is False
    projection = json.dumps(result["customer_confirmation_projection"], sort_keys=True)
    assert "decision-" not in projection
    assert "proposal-" not in projection
    assert "digest" not in projection


def test_control_enters_durable_intent_only_when_explicitly_promoted() -> None:
    result = _proposal(
        current_step_controls=["ask before continuing"],
        explicitly_promoted_controls=["ask before continuing"],
    )
    assert result["semantic_layers"]["durable_blueprint_constraints"] == [
        "ask before continuing"
    ]


def test_stable_decision_identity_uses_catalog_and_lineage_not_order_or_wording() -> None:
    lineage = "session-artifact-0123456789abcdef"
    a = _proposal(current_lineage_reference=lineage)
    b = _proposal(
        current_lineage_reference=lineage,
        assistant_structuring={"goal": "same semantics with different wording"},
    )
    a_refs = {x["profile_decision_id"]: x["decision_ref"] for x in a["decision_records"]}
    b_refs = {x["profile_decision_id"]: x["decision_ref"] for x in reversed(b["decision_records"])}
    assert a_refs == b_refs
    assert all(value.startswith("decision-") for value in a_refs.values())


def test_assistant_proposal_requires_explicit_acceptance_and_is_not_confirmation() -> None:
    blocked = prepare_ide_first_blueprint(
        customer_request="Build a circuit.",
        explicit_user_facts={},
        assistant_structuring={"profile": "generic"},
        assistant_implementation_proposals={
            item["profile_decision_id"]: "assistant candidate"
            for item in catalog_entries("generic_qiskit")
            if item["generation_relevant"]
        },
        customer_dispositions={},
    )
    assert blocked["readiness"]["aggregate_readiness_result"] == "blocked_pending_decisions"
    with pytest.raises(D079WorkflowError, match="unresolved_blocking_decision"):
        confirm_ide_first_blueprint(
            proposal=blocked,
            confirmation=blocked["confirmation_requirements"],
        )


def test_bounded_delegation_is_decision_specific_and_unbounded_delegation_fails() -> None:
    facts = _all_explicit_facts()
    facts.pop("generic_qiskit.circuit_construction")
    bounded = _proposal(
        explicit_user_facts=facts,
        customer_dispositions={
            "circuit_construction": {
                "disposition": "explicitly_bounded_or_delegated",
                "bounds": {
                    "bound_type": "finite_alternative_set",
                    "allowed": ["quantum_circuit", "explicit_registers"],
                    "source_visible_evidence_expected_later": "selected Python source",
                    "review_rule": "compare the selected construction to this finite set",
                },
            }
        },
    )
    target = next(
        item
        for item in bounded["decision_records"]
        if item["profile_decision_id"] == "generic_qiskit.circuit_construction"
    )
    assert target["generation_effect"] == "bounded_discretion"
    assert target["user_approved_bounds"]["allowed"] == [
        "quantum_circuit",
        "explicit_registers",
    ]
    with pytest.raises(D079WorkflowError) as raised:
        _proposal(
            explicit_user_facts=facts,
            customer_dispositions={
                "circuit_construction": {
                    "disposition": "explicitly_bounded_or_delegated"
                }
            },
        )
    assert raised.value.recovery["reason_category"] == "unbounded_or_ineligible_delegation"


def test_exact_confirmation_creates_immutable_child_and_usable_generation_artifacts() -> None:
    proposal = _proposal()
    before = deepcopy(proposal)
    confirmed = confirm_ide_first_blueprint(
        proposal=proposal, confirmation=proposal["confirmation_requirements"]
    )
    assert proposal == before
    assert confirmed["parent_artifact_identity"] == proposal["artifact_identity"]
    assert confirmed["artifact_revision"] == 2
    assert confirmed["parent_mutated"] is False
    assert confirmed["implementation_blueprint"]["layer"] == "implementation_blueprint"
    assert confirmed["generation_context"]["generation_ready"] is True
    assert confirmed["authority"]["confirmation_grants_edit_or_run"] is False


@pytest.mark.parametrize(
    ("field", "replacement", "category"),
    [
        ("artifact_identity", "proposal-wrongwrongwrongwrong22", "incorrect_confirmation_reference"),
        ("artifact_revision", 0, "stale_revision"),
        ("parent_lineage_identity", "session-artifact-ffffffffffffffff", "missing_or_stale_lineage"),
        ("proposal_digest", "0" * 64, "digest_mismatch"),
        ("exact_proposal_reviewed", False, "missing_review_assertion"),
    ],
)
def test_confirmation_binding_failures_are_structured(
    field: str, replacement: object, category: str
) -> None:
    proposal = _proposal()
    confirmation = deepcopy(proposal["confirmation_requirements"])
    confirmation[field] = replacement
    with pytest.raises(D079WorkflowError) as raised:
        confirm_ide_first_blueprint(proposal=proposal, confirmation=confirmation)
    assert raised.value.recovery["reason_category"] == category
    assert raised.value.recovery["bounded_field"] == field
    assert raised.value.recovery["fail_closed"] is True


def test_confirmation_for_a_cannot_confirm_b_and_changed_proposal_needs_review() -> None:
    lineage = "session-artifact-0123456789abcdef"
    a = _proposal(current_lineage_reference=lineage)
    b = _proposal(
        current_lineage_reference=lineage,
        assistant_structuring={"goal": "changed proposal B"},
    )
    with pytest.raises(D079WorkflowError, match="incorrect_confirmation_reference"):
        confirm_ide_first_blueprint(
            proposal=b, confirmation=a["confirmation_requirements"]
        )


def test_missing_lineage_and_wrong_artifact_layer_recover_fail_closed() -> None:
    proposal = _proposal()
    missing = deepcopy(proposal)
    del missing["confirmation_requirements"]
    with pytest.raises(D079WorkflowError) as raised:
        confirm_ide_first_blueprint(proposal=missing, confirmation={})
    assert raised.value.recovery["reason_category"] == "missing_lineage"
    with pytest.raises(D079WorkflowError) as raised:
        confirm_ide_first_blueprint(
            proposal={"schema_id": "qcoder.generation_context.v1"}, confirmation={}
        )
    assert raised.value.recovery["wrong_artifact_layer"] == "qcoder.generation_context.v1"


def test_malformed_and_unknown_fields_have_actionable_recovery() -> None:
    with pytest.raises(D079WorkflowError) as raised:
        _proposal(customer_request="")
    assert raised.value.recovery["bounded_field"] == "customer_request"
    with pytest.raises(D079WorkflowError) as raised:
        _proposal(explicit_user_facts={"fixture-17": "not canonical"})
    assert raised.value.recovery["reason_category"] == "unknown_decision_field"
    assert raised.value.recovery["valid_portions_may_be_retained"] is True


def test_local_first_review_is_exact_bounded_share_safe_and_terminal(tmp_path: Path) -> None:
    selected = tmp_path / "selected.py"
    selected.write_text(
        "from qiskit import QuantumCircuit\nqc = QuantumCircuit(2, 2)\nqc.h(0)\nqc.measure([0,1],[0,1])\n",
        encoding="utf-8",
    )
    neighbor = tmp_path / "neighbor.py"
    neighbor.write_text("raise RuntimeError('must not be read')\n", encoding="utf-8")
    calls: list[tuple[str, dict[str, object]]] = []
    result = review_selected_files_with_qcoder(
        selected_paths=[str(selected)], protected_call=_protected(calls)
    )
    assert result["status"] == "result_review_ready"
    assert result["continuation"]["calls"] == [
        "get_guided_evidence_context",
        "create_result_review_context_card",
    ]
    assert result["continuation"]["terminal"] == "Result Review"
    receipt = result["local_processing_receipt"]
    assert receipt["selected_artifact_count"] == 1
    assert receipt["repository_discovery_performed"] is False
    assert receipt["neighboring_file_inspection_performed"] is False
    transmitted = json.dumps(calls, sort_keys=True)
    assert str(selected) not in transmitted
    assert str(neighbor) not in transmitted
    assert "QuantumCircuit(2, 2)" not in transmitted
    assert result["retention"] == "process_and_discard"
    assert result["persistent"] is False


def test_protected_path_or_raw_misroute_is_rejected_toward_local_recovery() -> None:
    for payload in (
        {"path": "/home/customer/private.py"},
        {"raw_qasm": "OPENQASM 2.0;"},
        {"summary": "C:\\Users\\Rob\\private.py"},
    ):
        with pytest.raises(D079WorkflowError) as raised:
            _assert_protected_projection(payload)
        assert "local" in raised.value.recovery["recovery_category"]
        assert raised.value.recovery["valid_portions_may_be_retained"] is True


def test_local_extraction_limit_and_protected_rejection_preserve_safe_recovery(
    tmp_path: Path,
) -> None:
    oversized = tmp_path / "large.py"
    oversized.write_text("x=1\n" * 30_000, encoding="utf-8")
    with pytest.raises(D079WorkflowError) as raised:
        review_selected_files_with_qcoder(
            selected_paths=[str(oversized)], protected_call=lambda *_: {}
        )
    assert raised.value.recovery["required_local_preprocessing"] == "local_qcoder_evidence"

    selected = tmp_path / "selected.py"
    selected.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(D079WorkflowError) as raised:
        review_selected_files_with_qcoder(
            selected_paths=[str(selected)],
            protected_call=lambda *_: (_ for _ in ()).throw(RuntimeError("rejected")),
        )
    assert raised.value.recovery["valid_portions_may_be_retained"] is True


def test_continuation_failure_is_not_misreported_as_terminal(tmp_path: Path) -> None:
    selected = tmp_path / "selected.py"
    selected.write_text("x = 1\n", encoding="utf-8")

    def incomplete(tool: str, _arguments: object) -> dict[str, object]:
        return {
            "tool_name": tool,
            "ok": True,
            "context_status": "wrong_state",
            "retention": "process_and_discard",
            "retained_artifacts": [],
        }

    with pytest.raises(D079WorkflowError, match="continuation_failure"):
        review_selected_files_with_qcoder(
            selected_paths=[str(selected)], protected_call=incomplete
        )


def test_scale_limit_receipt_is_explicit_not_silent(tmp_path: Path) -> None:
    fixture = tmp_path / "scale.qasm"
    fixture.write_text("OPENQASM 2.0;\nqreg q[1];\n" + "x q[0];\n" * 10_000, encoding="utf-8")
    result = scale_limit_receipt(selected_path=str(fixture), effective_gate_magnitude=1_000_000)
    assert result["coverage_status"] == "limited"
    assert result["silent_truncation"] is False
    assert result["raw_artifact_remained_local"] is True
    assert result["protected_request_bytes"] == 0


def test_public_tool_inventory_remains_exactly_twelve() -> None:
    assert len(EXPECTED_TOOLS) == 12
    assert "review_selected_files_with_qcoder" not in EXPECTED_TOOLS
    assert "prepare_ide_first_blueprint" not in EXPECTED_TOOLS
    descriptor = build_client_binding_descriptor(coordinator_prefix=["python", "-m", "qcoder"])[
        "client_binding_contract"
    ]
    assert descriptor["contract_id"] == "qcoder.connected_assistant.client_binding.v20"
    assert descriptor["d079_orchestration"]["public_tool_count"] == 12
    assert descriptor["d079_orchestration"]["blueprint_workflow"]["decision_aware_by_default"] is True
    assert descriptor["d079_orchestration"]["evidence_review_workflow"]["repository_discovery"] is False
    assert "decision-aware workflow by default" in CLIENT_ACTIVATION_INSTRUCTIONS
    assert "Review these selected files with qCoder" in CLIENT_ACTIVATION_INSTRUCTIONS
    assert "Never scan the repository" in CLIENT_ACTIVATION_INSTRUCTIONS


def test_production_relevant_coordinator_path_owns_both_workflows(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class Transport:
        def call(self, name: str, arguments: object) -> dict[str, object]:
            return _protected(calls)(name, arguments)

    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path, transport=Transport())
    proposal = coordinator.prepare_connected_assistant_blueprint(
        customer_request="Build a measured circuit, then ask before editing.",
        explicit_user_facts=_all_explicit_facts(),
        assistant_structuring={"goal": "measured circuit"},
        assistant_implementation_proposals={},
        customer_dispositions={},
    )
    confirmed = coordinator.confirm_connected_assistant_blueprint(
        proposal=proposal,
        confirmation=proposal["confirmation_requirements"],
        materialize_canonical_artifacts=False,
    )
    selected = tmp_path / "selected.py"
    selected.write_text("from qiskit import QuantumCircuit\nqc=QuantumCircuit(1)\n", encoding="utf-8")
    reviewed = coordinator.review_customer_selected_files(selected_paths=[str(selected)])
    assert confirmed["generation_context"]["generation_ready"] is True
    assert reviewed["status"] == "result_review_ready"
    assert len(EXPECTED_TOOLS) == 12
