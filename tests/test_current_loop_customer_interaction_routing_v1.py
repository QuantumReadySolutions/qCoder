from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    EXPECTED_TOOLS,
    build_client_activation_instructions,
    build_client_binding_descriptor,
)
from qcoder.current_loop import CurrentLoopError
from qcoder.current_loop_contract_sidecar import SidecarSession
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_quiet_workflow import COMPLETION_RECEIPT_SCHEMA_ID


REQUEST = (
    "Use qCoder for this build. Create and run one local Qiskit program. "
    "Keep qCoder quiet unless a material decision or real blocker requires me."
)
FINISH = (
    "Finish this loop without hosted enrichment, Build Review, Blueprint changes, or a new loop."
)


def _active(workspace: Path) -> CurrentLoopCoordinator:
    coordinator = CurrentLoopCoordinator(workspace_root=workspace)
    result = coordinator.activate(
        original_request=REQUEST,
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    assert result["ok"] is True
    return coordinator


def _contract(coordinator: CurrentLoopCoordinator) -> dict:
    return coordinator.store.read()["current_loop_contract"]


def test_catalog_advertises_complete_compact_governance_and_finish_routes(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    catalog = coordinator.bounded_control_catalog()
    controls = catalog["bounded_contract_controls"]
    governance = controls["set_generation_governance"]
    governance_contract = governance["bounded_control_input_contract"]
    assert governance["subcommand"] == "contract-set-generation-governance"
    assert governance["transport_classification"] == "local_only"
    assert governance_contract["current_generation_governance"] == "adaptive"
    options = {item["value"]: item for item in governance_contract["fields"][0]["accepted_values"]}
    assert set(options) == {"adaptive", "blueprint_required"}
    assert options["adaptive"]["change_disposition"] == "no_op"
    assert options["blueprint_required"]["change_disposition"] == "narrowing"
    assert options["blueprint_required"]["confirmation_required"] is False
    assert governance_contract["editable_document_round_trip_required"] is False
    assert governance_contract["contract_status_preflight_required"] is False
    assert governance["fixed_argument_values"]["--expected-contract-revision"] == 1
    assert governance["state_binding"]["workspace"] == str(tmp_path)
    assert governance["state_binding"]["loop_ref"] == coordinator.store.read()["loop_ref"]

    finish = controls["finish_loop"]
    finish_contract = finish["bounded_control_input_contract"]
    assert finish["subcommand"] == "complete-instruction"
    assert finish["input_channel"] == "exact_current_customer_instruction_stdin"
    assert finish["required_flag_contract"] == ["--instruction-stdin", "--stop"]
    assert finish_contract["ordinary_finish_route"] is True
    assert finish_contract["separate_build_review_decline_required"] is False
    assert finish_contract["customer_project_files_preserved"] is True
    assert finish_contract["contract_revision"] == 1
    assert finish["state_binding"]["revision"] == coordinator.store.read()["state_revision"]


def test_direct_governance_narrowing_no_op_broadening_and_confirmation(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    initial = coordinator.store.read()
    no_op = coordinator.contract_set_generation_governance(
        governance="adaptive",
        expected_contract_revision=1,
    )
    assert no_op["ok"] is True
    assert no_op["operation"] == "contract_set_generation_governance"
    assert no_op["details"]["disposition"] == "no_op"
    assert no_op["details"]["pending_proposal_created"] is False
    assert coordinator.store.read()["state_revision"] == initial["state_revision"]
    assert _contract(coordinator)["contract_revision"] == 1

    narrowed = coordinator.contract_set_generation_governance(
        governance="blueprint_required",
        expected_contract_revision=1,
    )
    assert narrowed["ok"] is True
    assert narrowed["details"]["disposition"] == "narrowing"
    assert narrowed["details"]["customer_document_round_trip_required"] is False
    assert narrowed["details"]["contract_status_preflight_required"] is False
    assert narrowed["details"]["contract_change_receipt"] is not None
    assert narrowed["details"]["pending_proposal"] is None
    assert _contract(coordinator)["generation_governance"] == "blueprint_required"
    assert _contract(coordinator)["contract_revision"] == 2
    assert narrowed["performance_diagnostics"]["total_operation_elapsed_seconds"] < 2

    proposed = coordinator.contract_set_generation_governance(
        governance="adaptive",
        expected_contract_revision=2,
    )
    assert proposed["ok"] is True
    assert proposed["category"] == "contract_broadening_proposed"
    assert proposed["details"]["disposition"] == "broadening"
    assert proposed["details"]["requires_explicit_customer_confirmation"] is True
    assert proposed["details"]["customer_document_round_trip_required"] is False
    assert _contract(coordinator)["generation_governance"] == "blueprint_required"
    assert _contract(coordinator)["contract_revision"] == 2
    assert _contract(coordinator)["pending_broadening_proposal"] is not None
    assert proposed["performance_diagnostics"]["total_operation_elapsed_seconds"] < 2

    confirmed = coordinator.contract_confirm_broadening(
        expected_contract_revision=2,
        explicit_authority=True,
    )
    assert confirmed["ok"] is True
    assert confirmed["details"]["authority_only"] is True
    assert confirmed["details"]["raw_policy_retransmitted"] is False
    assert _contract(coordinator)["generation_governance"] == "adaptive"
    assert _contract(coordinator)["contract_revision"] == 3


def test_governance_stale_revision_rejected_with_current_domain(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    result = coordinator.contract_set_generation_governance(
        governance="blueprint_required",
        expected_contract_revision=99,
    )
    assert result["ok"] is False
    assert result["category"] == "customer_contract_document_revision_stale"
    rejected = result["details"]["bounded_control_rejection"]
    assert rejected["expected_field_contract"]["accepted_values"]
    assert _contract(coordinator)["generation_governance"] == "adaptive"


def test_browser_and_ide_use_same_compact_governance_service(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    sidecar = SidecarSession(workspace=tmp_path, coordinator=coordinator)
    browser = sidecar.action(
        action="set_generation_governance",
        payload={"governance": "blueprint_required"},
        expected_contract_revision=1,
    )
    assert browser["ok"] is True
    assert browser["shared_contract_management_service"] is True
    assert _contract(coordinator)["generation_governance"] == "blueprint_required"
    ide = coordinator.contract_set_generation_governance(
        governance="adaptive",
        expected_contract_revision=2,
    )
    assert ide["details"]["same_management_service_as_browser"] is True
    assert ide["details"]["disposition"] == "broadening"


def test_direct_finish_cancels_pending_proposal_and_returns_completion_receipt(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    project_file = tmp_path / "customer-project.txt"
    project_file.write_text("customer-owned\n", encoding="utf-8")
    coordinator.contract_set_generation_governance(
        governance="blueprint_required",
        expected_contract_revision=1,
    )
    coordinator.contract_set_generation_governance(
        governance="adaptive",
        expected_contract_revision=2,
    )
    assert _contract(coordinator)["pending_broadening_proposal"] is not None
    sidecar = SidecarSession(workspace=tmp_path, coordinator=coordinator)

    result = coordinator.complete_instruction(
        exact_instruction=FINISH,
        stop_loop=True,
    )
    assert result["ok"] is True
    assert result["operation"] == "complete_instruction"
    assert result["phase"] == "completed"
    assert "closed" in result["customer_summary"].lower()
    assert "abandon" not in result["customer_summary"].lower()
    assert result["details"]["abandonment_selected"] is False
    assert result["details"]["customer_completion_copy_uses_abandonment_language"] is False
    assert result["details"]["pending_contract_proposal_cancelled_unapplied"] is True
    receipt = result["details"]["completion_receipt"]
    assert receipt["schema_id"] == COMPLETION_RECEIPT_SCHEMA_ID
    assert receipt["exact_instruction_utf8_sha256"] == sha256(FINISH.encode()).hexdigest()
    assert receipt["blueprint_unchanged"] is True
    assert receipt["hosted_enrichment_disposition"] == "not_requested"
    assert receipt["build_review_disposition"] == "not_requested"
    assert receipt["pending_contract_proposal_disposition"] == "cancelled_unapplied"
    assert receipt["pending_contract_proposal_applied"] is False
    assert receipt["next_loop_disposition"] == "do_not_start"
    assert receipt["cross_loop_carryover"] is False
    assert receipt["customer_project_files_preserved"] is True
    cleanup = result["details"]["loop_close_cleanup"]
    assert cleanup["state_deleted"] is True
    assert cleanup["future_loop_evidence_retained"] is False
    assert cleanup["user_project_files_deleted"] is False
    assert cleanup["loop_bound_sidecar_invalidated"] is True
    assert project_file.read_text(encoding="utf-8") == "customer-owned\n"
    with pytest.raises(CurrentLoopError, match="current_loop_not_active"):
        coordinator.store.read()
    with pytest.raises(ValueError, match="sidecar_loop_closed"):
        sidecar.validate_live_binding()


def test_complete_and_abandon_share_cleanup_but_keep_distinct_terminal_dispositions(
    tmp_path: Path,
) -> None:
    finish_workspace = tmp_path / "finish"
    abandon_workspace = tmp_path / "abandon"
    finish_workspace.mkdir()
    abandon_workspace.mkdir()
    finish_project = finish_workspace / "project.txt"
    abandon_project = abandon_workspace / "project.txt"
    finish_project.write_text("keep\n", encoding="utf-8")
    abandon_project.write_text("keep\n", encoding="utf-8")
    finished = _active(finish_workspace).complete_instruction(
        exact_instruction=FINISH,
        stop_loop=True,
    )
    abandoned = _active(abandon_workspace).abandon(explicit_authority=True)
    for result in (finished, abandoned):
        cleanup = result["details"]["loop_close_cleanup"]
        assert cleanup["state_deleted"] is True
        assert cleanup["future_loop_evidence_retained"] is False
        assert cleanup["user_project_files_deleted"] is False
        assert cleanup["loop_bound_sidecar_invalidated"] is True
        assert cleanup["directory_discovery_performed"] is False
    assert "closed" in finished["customer_summary"].lower()
    assert "abandon" not in finished["customer_summary"].lower()
    assert finished["phase"] == "completed"
    assert finished["details"]["completion_receipt"]["resulting_disposition"] == "stop_loop"
    assert "abandoned" in abandoned["customer_summary"].lower()
    assert abandoned["phase"] == "abandoned"
    assert "completion_receipt" not in abandoned["details"]
    assert finish_project.exists()
    assert abandon_project.exists()


def test_material_checkpoint_blocks_direct_finish_without_abandonment(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    state = coordinator.store.read()

    def mutator(value: dict) -> dict:
        value["coordinator"]["state_status"] = "checkpoint_required"
        value["coordinator"]["checkpoint_kind"] = "decision_resolution"
        return value

    coordinator.store.update(mutator, expected_revision=state["state_revision"])
    result = coordinator.complete_instruction(
        exact_instruction=FINISH,
        stop_loop=True,
    )
    assert result["ok"] is False
    assert result["category"] == "completion_material_proposal_pending"
    assert coordinator.store.read()["activation_state"] == "active"


def test_binding_v18_routes_governance_and_finish_without_document_fanout() -> None:
    binding = build_client_binding_descriptor(
        coordinator_prefix=["/runtime/python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    instructions = build_client_activation_instructions(
        base_url="https://example.invalid",
        token_file="/runtime/token",
        python_executable="/runtime/python",
    )
    normalized_instructions = " ".join(instructions.split())
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v43"
    assert binding["schema_version"] == 42
    assert len(EXPECTED_TOOLS) == 12
    assert "contract_management" in normalized_instructions
    assert "quiet_iteration_routing_contract" in normalized_instructions
    assert "referenced specialized contract" in normalized_instructions
    assert "verify SHA-256" in normalized_instructions
    assert "fail closed without inference" in normalized_instructions
