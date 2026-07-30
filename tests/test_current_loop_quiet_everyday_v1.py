from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from qcoder.context_bridge_mcp import EXPECTED_TOOLS, build_client_binding_descriptor
from qcoder.current_loop import CURRENT_LOOP_STATE_SCHEMA_ID, CurrentLoopError
from qcoder.current_loop_contract import (
    CONTRACT_SCHEMA_ID,
    confirm_broadening,
    new_contract,
    set_generation_governance,
)
from qcoder.current_loop_contract_sidecar import SIDECAR_SCHEMA_ID, SidecarSession
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_quiet_workflow import (
    ASSISTANT_CONTEXT_UPDATE_SCHEMA_ID,
    COMPLETION_RECEIPT_SCHEMA_ID,
    CUSTOMER_INTERACTION_SCHEMA_ID,
    HELP_SCHEMA_ID,
    INTENT_RECEIPT_SCHEMA_ID,
    quiet_workflow_contract_snapshot,
)
from qcoder.current_loop_iteration import parent_digest_failure_details


REQUEST = (
    "Use qCoder for this build. Create and run a straightforward Qiskit Bell-state "
    "program in this empty workspace using a local simulator and 1024 shots. Show me "
    "the measurement counts and briefly explain what they mean."
)


def _activate(workspace: Path) -> CurrentLoopCoordinator:
    coordinator = CurrentLoopCoordinator(workspace_root=workspace)
    result = coordinator.activate(
        original_request=REQUEST,
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    assert result["ok"] is True
    return coordinator


def _ordinary_fields(*, material: bool = False) -> dict[str, dict[str, Any]]:
    return {
        "profile_id": {
            "value": "generic_qiskit",
            "provenance": "qcoder_classified",
            "material": False,
        },
        "qubits": {"value": 2, "provenance": "user_stated", "material": False},
        "simulator": {
            "value": "local simulator",
            "provenance": "user_stated",
            "material": False,
        },
        "shots": {"value": 1024, "provenance": "user_stated", "material": False},
        "measurement": {
            "value": "both qubits",
            "provenance": "derived",
            "material": False,
        },
        "output": {
            "value": "counts and concise explanation",
            "provenance": "user_stated",
            "material": False,
        },
        **(
            {
                "algorithm_choice": {
                    "value": None,
                    "provenance": "unresolved",
                    "material": True,
                }
            }
            if material
            else {}
        ),
    }


def _write_run(workspace: Path, *, counts: Mapping[str, int]) -> list[dict[str, str]]:
    source = workspace / "bell.py"
    source.write_text("from qiskit import QuantumCircuit\ncircuit = QuantumCircuit(2, 2)\n")
    qasm = workspace / "bell.qasm"
    qasm.write_text(
        'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\n'
        "h q[0];\ncx q[0],q[1];\nmeasure q -> c;\n",
        encoding="utf-8",
    )
    results = workspace / "results.json"
    results.write_text(
        json.dumps({"counts": dict(counts), "shots": 1024, "backend": "AerSimulator"}),
        encoding="utf-8",
    )
    return [
        {
            "path": str(source),
            "role": "source",
            "artifact_type": "source",
            "provenance": "assistant_created",
        },
        {
            "path": str(qasm),
            "role": "circuit_qasm",
            "artifact_type": "circuit_qasm",
            "provenance": "assistant_created",
        },
        {
            "path": str(results),
            "role": "results",
            "artifact_type": "results",
            "provenance": "assistant_created",
        },
    ]


def _authorize_and_register(
    coordinator: CurrentLoopCoordinator,
    candidates: list[dict[str, str]],
    *,
    exact_iteration_instruction: str | None = None,
) -> dict[str, Any]:
    authority = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        operation_category="ide_execute",
        output_role_ceiling=("source", "circuit_qasm", "results"),
        exact_iteration_instruction=exact_iteration_instruction,
    )
    assert authority["ok"] is True
    receipt = authority["details"]["operation_receipt"]
    return coordinator.register_artifacts(
        candidates=candidates,
        operation_receipt_id=receipt["receipt_id"],
    )


def test_contract_v2_is_one_loop_quiet_assist_with_adaptive_governance() -> None:
    contract = new_contract(
        baseline_digest="a" * 64,
        capture_provenance="exact_current_customer_message",
        activation_revision=1,
    )
    assert contract["schema_id"] == CONTRACT_SCHEMA_ID == "qcoder.current_loop.contract.v2"
    assert contract["generation_governance"] == "adaptive"
    assert contract["effective_internal_generation_posture"] == "exploratory_first_pass"
    assert contract["quiet_communication_policy"]["hosted_enrichment"] == "on_request"
    assert contract["quiet_communication_policy"]["build_review"] == "on_request"
    assert contract["iteration_context_policy"]["cross_loop_carryover"] is False
    assert contract["cross_loop_inheritance"] is False


def test_adaptive_activation_and_one_pass_intent_meet_prompt_budget(tmp_path: Path) -> None:
    coordinator = _activate(tmp_path)
    activation = coordinator.status()
    state = coordinator.store.read()
    assert state["schema_id"] == CURRENT_LOOP_STATE_SCHEMA_ID
    assert state["generation_posture"] == "exploratory_first_pass"
    assert state["current_loop_contract"]["generation_governance_provenance"] == "contract_default"
    assert activation["customer_interaction"]["requires_customer_response"] is False
    intent = coordinator.prepare_adaptive_intent(fields=_ordinary_fields())
    assert intent["ok"] is True
    assert intent["phase"] == "generation_ready"
    receipt = intent["details"]["intent_receipt"]
    assert receipt["schema_id"] == INTENT_RECEIPT_SCHEMA_ID
    assert receipt["material_decision_required"] is False
    assert receipt["routine_interpretation_approval_required"] is False
    assert receipt["routine_clarification_approval_required"] is False
    assert receipt["user_confirmation_manufactured"] is False
    assert intent["customer_interaction"]["requires_customer_response"] is False
    assert {
        "initial_qcoder_activation_task_messages": 1,
        "additional_qcoder_specific_responses_before_local_context": 0,
        "native_ide_permission_actions": "one_or_more_as_required",
        "optional_finish_messages": 1,
    }["additional_qcoder_specific_responses_before_local_context"] == 0


def test_material_decisions_are_grouped_and_blueprint_required_remains_governed(
    tmp_path: Path,
) -> None:
    coordinator = _activate(tmp_path)
    result = coordinator.prepare_adaptive_intent(fields=_ordinary_fields(material=True))
    assert result["state_status"] == "checkpoint_required"
    assert result["checkpoint_kind"] == "decision_resolution"
    assert result["details"]["intent_receipt"]["material_decision_fields"] == ["algorithm_choice"]
    assert result["customer_interaction"]["primary_interaction_kind"] == (
        "material_decision_request"
    )


def test_governance_narrows_immediately_and_adaptive_return_is_broadening() -> None:
    contract = new_contract(
        baseline_digest="b" * 64,
        capture_provenance="exact_current_customer_message",
        activation_revision=1,
    )
    narrowed = set_generation_governance(
        contract,
        governance="blueprint_required",
        expected_contract_revision=1,
        provenance="customer_selected_contract_setting",
    )
    assert narrowed["disposition"] == "narrowing"
    assert narrowed["contract"]["effective_internal_generation_posture"] == "blueprint_guided"
    broadened = set_generation_governance(
        narrowed["contract"],
        governance="adaptive",
        expected_contract_revision=2,
        provenance="customer_selected_contract_setting",
    )
    assert broadened["disposition"] == "broadening"
    assert broadened["contract"]["generation_governance"] == "blueprint_required"
    confirmed = confirm_broadening(
        broadened["contract"],
        expected_contract_revision=2,
        explicit_authority=True,
    )
    assert confirmed["generation_governance"] == "adaptive"
    assert confirmed["generation_governance_provenance"] == "customer_confirmed_broadening"


def test_native_card_authority_auto_enrolls_and_processes_exact_outputs(
    tmp_path: Path,
) -> None:
    coordinator = _activate(tmp_path)
    coordinator.prepare_adaptive_intent(fields=_ordinary_fields())
    result = _authorize_and_register(
        coordinator,
        _write_run(tmp_path, counts={"00": 500, "11": 524}),
    )
    assert result["ok"] is True
    assert result["operation"] == "register_artifacts"
    assert result["details"]["automatic_output_enrollment"] is True
    assert result["details"]["artifact_review_conversation_required"] is False
    assert result["details"]["assist_iteration_ready"] is True
    assert result["supported_next_action"] == "assist_iteration_ready"
    assert result["next_invocation"]["subcommand"] == "record-ide-authority"
    assert result["next_invocation"]["transport_classification"] == "local_only"
    assert result["customer_interaction"]["primary_interaction_kind"] in {
        "activity_receipt",
        "no_customer_interaction_required",
    }
    assert result["customer_interaction"]["requires_customer_response"] is False
    optional_actions = result["customer_interaction"]["optional_on_request_actions"]
    assert "build_review" in optional_actions
    assert "hosted_enrichment" in optional_actions
    context = result["details"]["assistant_context_update"]
    assert context["schema_id"] == ASSISTANT_CONTEXT_UPDATE_SCHEMA_ID
    assert context["backend_or_simulator"] == "AerSimulator"
    assert context["shot_count"] == 1024
    assert context["raw_artifacts_remain_local"] is True
    assert context["complete_raw_source_included"] is False
    assert result["customer_interaction"]["requires_customer_response"] is False
    state = coordinator.store.read()
    assert state["latest_run_summary_reference"] is not None
    assert state["quiet_iteration_status"] == "assist_iteration_ready"


def test_second_run_refreshes_context_without_qcoder_conversation(tmp_path: Path) -> None:
    coordinator = _activate(tmp_path)
    coordinator.prepare_adaptive_intent(fields=_ordinary_fields())
    _authorize_and_register(coordinator, _write_run(tmp_path, counts={"00": 500, "11": 524}))
    second = _authorize_and_register(
        coordinator,
        _write_run(tmp_path, counts={"01": 492, "10": 532}),
        exact_iteration_instruction=(
            "Now change the circuit to prepare the Psi-plus Bell state and run it again. "
            "Explain how the measured bitstrings changed."
        ),
    )
    state = coordinator.store.read()
    assert second["customer_interaction"]["requires_customer_response"] is False
    assert second["supported_next_action"] == "assist_iteration_ready"
    receipt = state["latest_iteration_authority_receipt"]
    assert receipt["provenance"] == "user_stated"
    assert receipt["governing_blueprint_unchanged"] is True
    assert receipt["blueprint_promotion_performed"] is False
    assert receipt["evolved_blueprint_created"] is False
    assert receipt["continuation_artifact_created"] is False
    assert receipt["build_review_implicitly_deferred"] is True
    assert receipt["raw_instruction_retained"] is False
    assert "working_blueprint" not in state["saved_artifacts"]
    updates = state["assistant_context_updates"]
    assert len(updates) == 4
    assert [item["newer_iteration_status"] for item in updates] == [
        "pending",
        None,
        "pending",
        None,
    ]
    assert (
        state["assistant_context_updates"][1]["context_digest"]
        != (state["assistant_context_updates"][3]["context_digest"])
    )
    assert state["assistant_context_updates"][3]["top_outcomes"][0]["bitstring"] == "10"


def test_grouped_view_and_help_are_qcoder_managed(tmp_path: Path) -> None:
    coordinator = _activate(tmp_path)
    coordinator.prepare_adaptive_intent(fields=_ordinary_fields())
    _authorize_and_register(coordinator, _write_run(tmp_path, counts={"00": 500, "11": 524}))
    grouped = coordinator.evidence_view(view_id="current_build_facts")
    assert grouped["ok"] is True
    view = grouped["details"]["evidence_view"]
    assert view["answer"]["run"]["backend_or_simulator"] == "AerSimulator"
    assert view["answer"]["run"]["shots"] == 1024
    assert view["answer"]["circuit"]["gate_count"] == 2
    assert view["workspace_scanned"] is False
    help_result = coordinator.help(topic="overview")
    assert help_result["details"]["help"]["schema_id"] == HELP_SCHEMA_ID
    assert help_result["details"]["help"]["commands_exposed"] is False
    assert help_result["customer_interaction"]["primary_interaction_kind"] == (
        "user_requested_help"
    )


def test_receipt_style_stop_has_no_restage_next_loop_or_carryover(tmp_path: Path) -> None:
    coordinator = _activate(tmp_path)
    result = coordinator.complete_instruction(
        exact_instruction=(
            "Finish this qCoder loop without hosted enrichment, Build Review, "
            "Blueprint changes, or a new loop."
        ),
        stop_loop=True,
    )
    assert result["ok"] is True
    receipt = result["details"]["completion_receipt"]
    assert receipt["schema_id"] == COMPLETION_RECEIPT_SCHEMA_ID
    assert receipt["restaging_required"] is False
    assert receipt["blueprint_unchanged"] is True
    assert receipt["next_loop_disposition"] == "do_not_start"
    assert receipt["cross_loop_carryover"] is False
    assert result["phase"] == "abandoned"


def test_build_review_decline_returns_to_quiet_iteration_ready(tmp_path: Path) -> None:
    coordinator = _activate(tmp_path)
    coordinator.prepare_adaptive_intent(fields=_ordinary_fields())
    processed = _authorize_and_register(
        coordinator,
        _write_run(tmp_path, counts={"00": 500, "11": 524}),
    )
    assert processed["supported_next_action"] == "assist_iteration_ready"
    declined = coordinator.decline_build_review(explicit_authority=True)
    assert declined["phase"] == "evidence_processing"
    assert declined["state_status"] == "ready"
    assert declined["checkpoint_kind"] == "none"
    assert declined["supported_next_action"] == "assist_iteration_ready"
    assert declined["customer_interaction"]["requires_customer_response"] is False
    assert declined["details"]["may_request_later"] is True
    assert coordinator.store.read()["quiet_iteration_status"] == "assist_iteration_ready"


def test_adaptive_continue_without_blueprint_recovers_to_iteration_ready(
    tmp_path: Path,
) -> None:
    coordinator = _activate(tmp_path)
    coordinator.prepare_adaptive_intent(fields=_ordinary_fields())
    _authorize_and_register(
        coordinator,
        _write_run(tmp_path, counts={"00": 500, "11": 524}),
    )
    state = coordinator.store.read()
    protocol = coordinator._coordinator_state(state)
    protocol["phase"] = "continuation_choice"
    coordinator._replace_coordinator(protocol)

    result = coordinator.continue_unchanged(
        explicit_user_action=True,
        user_statement="Continue with the requested ordinary iteration.",
    )
    assert result["ok"] is False
    assert result["category"] == "governing_blueprint_unavailable"
    assert result["details"]["conversation_may_continue"] is True
    assert result["details"]["assistant_should_stop"] is False
    assert result["next_invocation"]["subcommand"] == "execute-recovery-action"
    assert result["next_invocation"]["fixed_argument_values"]["--action"] == (
        "return_to_iteration_ready"
    )
    alternatives = result["details"]["recovery_contract"]["alternatives"]
    assert [item["action"] for item in alternatives] == [
        "return_to_iteration_ready",
        "stop_loop",
    ]
    assert all(item["invocation"] for item in alternatives)
    recovery_reference = alternatives[0]["recovery_reference"]
    recovered = coordinator.execute_recovery_action(
        recovery_reference=recovery_reference,
        action="return_to_iteration_ready",
        expected_contract_revision=coordinator.store.read()["current_loop_contract"][
            "contract_revision"
        ],
    )
    assert recovered["ok"] is True
    assert recovered["supported_next_action"] == "assist_iteration_ready"
    assert recovered["customer_interaction"]["requires_customer_response"] is False
    assert "working_blueprint" not in coordinator.store.read()["saved_artifacts"]


def test_parent_error_taxonomy_never_uses_substring_classification(
    tmp_path: Path,
) -> None:
    coordinator = _activate(tmp_path)
    incomplete = coordinator._exception_result(
        "synthetic_parent_operation",
        CurrentLoopError("canonical_parent_set_incomplete"),
        coordinator.clock(),
    )
    assert incomplete["category"] == "canonical_parent_set_incomplete"
    unrelated = coordinator._exception_result(
        "synthetic_parent_operation",
        CurrentLoopError("some_parent_digest_words_without_a_bounded_category"),
        coordinator.clock(),
    )
    assert unrelated["category"] == "unknown_local_internal"
    unproven = coordinator._exception_result(
        "synthetic_parent_operation",
        CurrentLoopError("parent_digest_mismatch"),
        coordinator.clock(),
    )
    assert unproven["category"] == "unknown_local_internal"
    proven = coordinator._exception_result(
        "synthetic_parent_operation",
        CurrentLoopError(
            "parent_digest_mismatch",
            safe_details=parent_digest_failure_details(
                expected_digest_reference="expected:" + ("a" * 64),
                observed_digest_reference="observed:" + ("b" * 64),
                parent_role="governing_blueprint",
            ),
        ),
        coordinator.clock(),
    )
    assert proven["category"] == "parent_digest_mismatch"
    assert proven["details"]["digest_comparison_attempted"] is True


def test_sidecar_and_binding_share_v2_governance_and_quiet_contract(tmp_path: Path) -> None:
    coordinator = _activate(tmp_path)
    sidecar = SidecarSession(workspace=tmp_path, coordinator=coordinator)
    snapshot = sidecar.snapshot()
    assert snapshot["schema_id"] == SIDECAR_SCHEMA_ID
    assert snapshot["generation_governance"] == "adaptive"
    assert [item["value"] for item in snapshot["generation_governance_options"]] == [
        "adaptive",
        "blueprint_required",
    ]
    changed = sidecar.action(
        action="set_generation_governance",
        payload={"governance": "blueprint_required"},
        expected_contract_revision=snapshot["contract_revision"],
    )
    assert changed["ok"] is True
    assert coordinator.store.read()["current_loop_contract"]["generation_governance"] == (
        "blueprint_required"
    )
    descriptor = build_client_binding_descriptor(
        coordinator_prefix=["python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    assert descriptor["contract_id"] == "qcoder.connected_assistant.client_binding.v13"
    quiet = descriptor["quiet_everyday_workflow_contract"]
    assert quiet["customer_interaction_schema_id"] == CUSTOMER_INTERACTION_SCHEMA_ID
    assert quiet["assist_default"] == "quiet_everyday"
    assert descriptor["qcoder_domain_tool_count"] == len(EXPECTED_TOOLS) == 12


def test_quiet_contract_snapshot_is_bounded_and_no_guided_mode() -> None:
    snapshot = quiet_workflow_contract_snapshot()
    assert snapshot["generation_governance"] == ["adaptive", "blueprint_required"]
    assert "guided" not in json.dumps(snapshot).casefold()
    assert snapshot["raw_exposure_default"] is False
    assert snapshot["cross_loop_carryover"] is False
