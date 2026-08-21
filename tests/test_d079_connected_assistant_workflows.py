from __future__ import annotations

import json
import io
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from qcoder.blueprint_decisions import catalog_entries
from qcoder.cli import _cmd_current_loop
from qcoder.context_bridge_mcp import (
    CLIENT_ACTIVATION_INSTRUCTIONS,
    EXPECTED_TOOLS,
    build_client_binding_descriptor,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_invocation import HOSTED_CAPABLE, operation_transport_inventory
from qcoder.d079_workflows import (
    D079WorkflowError,
    _assert_protected_projection,
    binding_default_routing_contract,
    classify_binding_default_route,
    confirm_ide_first_blueprint,
    prepare_ide_first_blueprint,
    review_selected_files_with_qcoder,
    revise_ide_first_blueprint,
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
    assert (
        layers["assistant_implementation_proposals"]["generic_qiskit.result_processing"]
        == "counts dictionary"
    )
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
    assert result["semantic_layers"]["durable_blueprint_constraints"] == ["ask before continuing"]


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
                "circuit_construction": {"disposition": "explicitly_bounded_or_delegated"}
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
    ("mutation", "category"),
    [
        ("projection", "confirmation_projection_mismatch"),
        ("artifact_identity", "artifact_identity_mismatch"),
        ("requirements", "confirmation_requirements_mismatch"),
    ],
)
def test_confirmation_rederives_identity_and_presentation_envelopes(
    mutation: str, category: str
) -> None:
    proposal = _proposal()
    tampered = deepcopy(proposal)
    if mutation == "projection":
        tampered["customer_confirmation_projection"]["what_you_said"] = "altered display"
    elif mutation == "artifact_identity":
        altered = "proposal-alteredEnvelopeIdentity"
        tampered["artifact_identity"] = altered
        tampered["confirmation_requirements"]["artifact_identity"] = altered
    else:
        tampered["confirmation_requirements"]["artifact_revision"] = 99
    with pytest.raises(D079WorkflowError) as raised:
        confirm_ide_first_blueprint(
            proposal=tampered,
            confirmation=tampered["confirmation_requirements"],
        )
    assert raised.value.recovery["reason_category"] == category
    assert raised.value.recovery["fail_closed"] is True


@pytest.mark.parametrize(
    ("field", "replacement", "category"),
    [
        (
            "artifact_identity",
            "proposal-wrongwrongwrongwrong22",
            "incorrect_confirmation_reference",
        ),
        ("artifact_revision", 0, "stale_revision"),
        (
            "parent_lineage_identity",
            "session-artifact-ffffffffffffffff",
            "missing_or_stale_lineage",
        ),
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
        confirm_ide_first_blueprint(proposal=b, confirmation=a["confirmation_requirements"])


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


def test_ambiguous_catalog_alias_fails_with_all_collisions_and_stable_identity() -> None:
    with pytest.raises(D079WorkflowError) as raised:
        _proposal(explicit_user_facts={"measurement_plan": "measure all"})
    recovery = raised.value.recovery
    assert recovery["reason_category"] == "ambiguous_decision_alias"
    assert recovery["details"]["ambiguous_alias"] == "measurement_plan"
    assert recovery["details"]["colliding_profile_decision_ids"] == [
        "generic_qiskit.bit_order",
        "generic_qiskit.classical_width",
        "generic_qiskit.measurement_mapping",
        "generic_qiskit.measurement_structure",
    ]
    assert recovery["details"]["customer_must_supply_internal_identity"] is False
    unique = _proposal(
        explicit_user_facts={
            **_all_explicit_facts(),
            "circuit_construction": "explicit readable construction",
        }
    )
    assert any(
        item["profile_decision_id"] == "generic_qiskit.circuit_construction"
        for item in unique["decision_records"]
    )


@pytest.mark.parametrize(
    "wording",
    [
        "Do not edit or run.",
        "Do not run or edit.",
        "Do not edit or run anything.",
        "Do not run or edit anything.",
        "Do not edit or run anything yet.",
        "DO NOT RUN OR EDIT ANYTHING YET!",
    ],
)
def test_coordinated_temporary_edit_run_controls_are_both_non_durable(wording: str) -> None:
    proposal = _proposal(customer_request=f"Build a circuit. {wording}")
    assert proposal["temporary_authority_actions"] == ["edit", "run"]
    assert proposal["semantic_layers"]["durable_blueprint_constraints"] == []


def test_blueprint_revision_has_exact_parent_bounded_diff_and_fresh_confirmation() -> None:
    original = _proposal()
    unchanged = revise_ide_first_blueprint(
        proposal=original,
        semantic_changes={
            "assistant_structuring": original["semantic_layers"]["assistant_structuring"]
        },
    )
    assert unchanged["material_revision_created"] is False
    revised_result = revise_ide_first_blueprint(
        proposal=original,
        semantic_changes={"assistant_structuring": {"goal": "revised semantic goal"}},
    )
    revised = revised_result["proposal"]
    assert revised["artifact_revision"] == original["artifact_revision"] + 1
    assert revised["parent_artifact"]["artifact_ref"] == original["artifact_identity"]
    assert revised_result["semantic_diff"][0]["bounded_field"] == (
        "semantic_layers.assistant_structuring"
    )
    assert (
        revised["semantic_layers"]["current_step_authority_controls"]
        == (original["semantic_layers"]["current_step_authority_controls"])
    )
    with pytest.raises(D079WorkflowError):
        confirm_ide_first_blueprint(
            proposal=revised,
            confirmation=original["confirmation_requirements"],
        )
    confirmed = confirm_ide_first_blueprint(
        proposal=revised,
        confirmation=revised["confirmation_requirements"],
    )
    assert confirmed["parent_artifact_identity"] == revised["artifact_identity"]


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
        review_selected_files_with_qcoder(selected_paths=[str(selected)], protected_call=incomplete)


def test_scale_limit_receipt_is_explicit_not_silent(tmp_path: Path) -> None:
    fixture = tmp_path / "scale.qasm"
    fixture.write_text("OPENQASM 2.0;\nqreg q[1];\n" + "x q[0];\n" * 10_000, encoding="utf-8")
    result = scale_limit_receipt(selected_path=str(fixture), effective_gate_magnitude=1_000_000)
    assert result["coverage_status"] == "limited"
    assert result["silent_truncation"] is False
    assert result["raw_artifact_remained_local"] is True
    assert result["protected_request_bytes"] == 0


def test_real_local_first_path_returns_structured_selected_artifact_limit(tmp_path: Path) -> None:
    fixture = tmp_path / "selected-million-scale.qasm"
    gate_count = 20_000
    fixture.write_text(
        'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\n' + "x q[0];\n" * gate_count,
        encoding="utf-8",
    )
    with pytest.raises(D079WorkflowError) as raised:
        review_selected_files_with_qcoder(
            selected_paths=[str(fixture)],
            protected_call=lambda *_: pytest.fail("protected call must not be reached"),
        )
    receipt = raised.value.recovery["limit_receipt"]
    assert sum(1 for line in fixture.read_text().splitlines() if line == "x q[0];") == gate_count
    assert receipt["coverage_status"] == "LIMITED"
    assert receipt["selected_artifacts"][0]["raw_artifact_bytes"] == fixture.stat().st_size
    assert receipt["raw_artifact_remained_local"] is True
    assert receipt["protected_request_bytes"] == 0
    assert receipt["silent_truncation"] is False
    assert receipt["downstream_complete_status_permitted"] is False


def test_public_tool_inventory_remains_exactly_twelve() -> None:
    assert len(EXPECTED_TOOLS) == 12
    assert "review_selected_files_with_qcoder" not in EXPECTED_TOOLS
    assert "prepare_ide_first_blueprint" not in EXPECTED_TOOLS
    descriptor = build_client_binding_descriptor(coordinator_prefix=["python", "-m", "qcoder"])[
        "client_binding_contract"
    ]
    assert descriptor["contract_id"] == "qcoder.connected_assistant.client_binding.v38"
    assert descriptor["d079_orchestration"]["public_tool_count"] == 12
    assert (
        descriptor["d079_orchestration"]["blueprint_workflow"]["decision_aware_by_default"] is True
    )
    assert (
        descriptor["d079_orchestration"]["evidence_review_workflow"]["repository_discovery"]
        is False
    )
    invocation = descriptor["d079_orchestration"]["binding_owned_local_invocation"]
    assert invocation["operation"] == "connected-assistant-workflow"
    assert invocation["qcoder_owned_argv"] == [
        "python",
        "-m",
        "qcoder",
        "current-loop",
        "connected-assistant-workflow",
        "--operation-input-stdin",
    ]
    assert invocation["customer_constructs_input_envelope"] is False
    assert invocation["public_mcp_tool_added"] is False
    normalized_instructions = " ".join(CLIENT_ACTIVATION_INSTRUCTIONS.split()).casefold()
    assert "decision-aware workflow by default" in normalized_instructions
    assert "Review these selected files with qCoder" in CLIENT_ACTIVATION_INSTRUCTIONS
    assert "Never scan the repository" in CLIENT_ACTIVATION_INSTRUCTIONS


def test_m4_blueprint_named_route_precedes_generic_single_capability() -> None:
    request = "Help me design a Bell-state Qiskit program. Do not edit or run anything yet."
    decision = classify_binding_default_route(customer_instruction=request)
    assert decision == {
        "schema_id": "qcoder.connected_assistant.route_decision.v1",
        "selected_route": "named_d079_workflow",
        "action": "execute_binding_owned_current_loop_operation",
        "operation": "connected_assistant_workflow",
        "subcommand": "connected-assistant-workflow",
        "matched_named_workflow": "algorithm_blueprint_generation_context",
        "workflow": "ide_first_blueprint_decision_and_confirmation",
        "named_d079_route_preceded_generic_single_capability": True,
        "customer_constructs_operation_envelope": False,
        "raw_mcp_default_entrypoint": False,
        "deterministic_single_route": True,
        "routing_contract": "qcoder.connected_assistant.default_workstyle_routing.v1",
    }
    contract = binding_default_routing_contract()
    assert contract["deterministic_single_route"] is True
    assert contract["dual_action_permitted"] is False
    assert contract["recursive_routing_permitted"] is False
    assert contract["selected_action_cardinality"] == "exactly_one"
    assert contract["named_workflow_precedence"]["precedes"] == (
        "generic_single_capability_fallthrough"
    )
    assert contract["customer_inputs_exclude"] == [
        "qcoder_current_loop_command",
        "operation_input_json",
        "decision_loop_flag",
        "mcp_tool_name",
        "decision_id",
        "digest",
        "lineage_identity",
    ]
    scale_decision = classify_binding_default_route(
        customer_instruction=(
            "Design a bounded semantic handling plan for an approximately million-gate "
            "selected circuit. Do not edit or run anything yet."
        )
    )
    assert scale_decision["matched_named_workflow"] == ("algorithm_blueprint_generation_context")


def test_m4_evidence_named_route_precedes_raw_mcp_and_retains_selection_authority(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "selected.py"
    selected.write_text("x = 1\n", encoding="utf-8")
    decision = classify_binding_default_route(
        customer_instruction="Review these selected files with qCoder.",
        selected_paths=[str(selected)],
    )
    assert decision["selected_route"] == "named_d079_workflow"
    assert decision["matched_named_workflow"] == "selected_file_evidence_review"
    assert decision["operation"] == "connected_assistant_workflow"
    assert decision["raw_mcp_default_entrypoint"] is False
    route = binding_default_routing_contract()["named_workflows"]["selected_file_evidence_review"]
    assert route["native_client_selected_paths_required"] is True
    assert route["customer_constructs_operation_envelope"] is False


def test_m4_generic_active_and_inactive_routes_are_deterministic_fallthroughs() -> None:
    generic = classify_binding_default_route(
        customer_instruction="Create a prompt context with qCoder."
    )
    assert generic["selected_route"] == "single_capability"
    assert generic["action"] == "use_applicable_mcp_tool"
    assert generic["raw_mcp_default_entrypoint"] is True
    active = classify_binding_default_route(
        customer_instruction="Use qCoder for this build. Help me plan the work."
    )
    assert active["selected_route"] == "single_capability"
    assert active["action"] == "use_applicable_mcp_tool"
    assert active["raw_mcp_default_entrypoint"] is True
    inactive = classify_binding_default_route(customer_instruction="")
    assert inactive["selected_route"] == "available_inactive"
    for decision in (generic, active, inactive):
        assert decision["deterministic_single_route"] is True
        assert decision["matched_named_workflow"] is None


def test_m4_operation_inventory_and_activation_instructions_are_consistent() -> None:
    inventory = operation_transport_inventory()
    row = next(
        item
        for item in inventory["operations"]
        if item["operation"] == "connected_assistant_workflow"
    )
    assert row == {
        "operation": "connected_assistant_workflow",
        "subcommand": "connected-assistant-workflow",
        "transport": HOSTED_CAPABLE,
        "binding_owned_internal_operation": True,
        "public_context_bridge_tool": False,
        "input_channel": "binding_constructed_utf8_json_stdin",
        "customer_constructs_input_envelope": False,
        "composes_existing_context_bridge_tools": True,
    }
    descriptor = build_client_binding_descriptor(
        coordinator_prefix=["python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    structured = descriptor["workstyle_routes"]["named_d079_workflow"]
    assert structured == descriptor["d079_orchestration"]["default_routing"]
    instructions = CLIENT_ACTIVATION_INSTRUCTIONS
    normalized = " ".join(instructions.split()).casefold()
    assert instructions.index("Named D-079 workflow override") < instructions.index(
        "Single capability fallthrough"
    )
    assert "do not begin with or expose raw individual mcp-tool choreography" in normalized
    assert "Single capability: for an explicit bounded" not in instructions
    assert len(EXPECTED_TOOLS) == 12
    assert "connected_assistant_workflow" not in EXPECTED_TOOLS
    assert "connected-assistant-workflow" not in EXPECTED_TOOLS


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
    selected.write_text(
        "from qiskit import QuantumCircuit\nqc=QuantumCircuit(1)\n", encoding="utf-8"
    )
    reviewed = coordinator.review_customer_selected_files(selected_paths=[str(selected)])
    assert confirmed["generation_context"]["generation_ready"] is True
    assert reviewed["status"] == "result_review_ready"
    assert len(EXPECTED_TOOLS) == 12


def test_binding_owned_ordinary_language_operation_routes_both_workflows(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class Transport:
        def call(self, name: str, arguments: object) -> dict[str, object]:
            return _protected(calls)(name, arguments)

    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path, transport=Transport())
    planned = coordinator.execute_connected_assistant_workflow(
        customer_instruction=(
            "Help me design a measured Qiskit circuit. Do not edit or run anything yet."
        ),
        blueprint_context={
            "explicit_user_facts": _all_explicit_facts(),
            "assistant_structuring": {"goal": "measured circuit"},
            "assistant_implementation_proposals": {},
            "customer_dispositions": {},
        },
    )
    assert planned["selected_workflow"] == "ide_first_blueprint_decision_and_confirmation"
    assert planned["binding_owned_local_invocation"] is True
    assert planned["workflow_result"]["temporary_authority_actions"] == ["edit", "run"]
    selected = tmp_path / "selected.py"
    selected.write_text("x = 1\n", encoding="utf-8")
    reviewed = coordinator.execute_connected_assistant_workflow(
        customer_instruction="Review these selected files with qCoder.",
        selected_paths=[str(selected)],
    )
    assert reviewed["selected_workflow"] == "local_first_evidence_review"
    assert reviewed["terminal_state"] == "Result Review"
    assert reviewed["workflow_result"]["status"] == "result_review_ready"
    assert len(EXPECTED_TOOLS) == 12


def test_exact_binding_owned_cli_invocation_executes_ordinary_language_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Input:
        def __init__(self, payload: dict[str, object]) -> None:
            self.buffer = io.BytesIO(json.dumps(payload).encode())

        def isatty(self) -> bool:
            return False

    instruction = "Design a measured Qiskit circuit. Do not edit or run anything yet."
    monkeypatch.setattr(
        sys,
        "stdin",
        Input(
            {
                "customer_instruction": instruction,
                "blueprint_context": {
                    "explicit_user_facts": _all_explicit_facts(),
                    "assistant_structuring": {"goal": "measured circuit"},
                    "assistant_implementation_proposals": {},
                    "customer_dispositions": {},
                },
            }
        ),
    )
    result = _cmd_current_loop(
        [
            "--workspace",
            str(tmp_path),
            "connected-assistant-workflow",
            "--operation-input-stdin",
        ]
    )
    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["selected_workflow"] == "ide_first_blueprint_decision_and_confirmation"
    assert (
        output["workflow_result"]["semantic_layers"]["original_customer_request_verbatim"]
        == instruction
    )
    assert output["workflow_result"]["temporary_authority_actions"] == ["edit", "run"]
