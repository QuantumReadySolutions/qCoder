from __future__ import annotations

import json
from pathlib import Path

from qcoder.context_bridge_mcp import (
    build_client_activation_instructions,
    build_client_binding_descriptor,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop import CurrentLoopError
from qcoder.current_loop_invocation import (
    HOSTED_CAPABLE,
    INVOCATION_CONTRACT_SCHEMA_ID,
    LOCAL_ONLY,
    build_operation_invocation,
    operation_transport_inventory,
)


def _legacy(subcommand: str) -> dict[str, object]:
    return {
        "subcommand": subcommand,
        "required_flags": [],
        "argument_values": [],
        "allowed_subcommand_alternatives": [],
        "token_contents_embedded": False,
    }


def _bind(subcommand: str, *, staged_operation: str | None = None) -> dict[str, object]:
    return build_operation_invocation(
        _legacy(subcommand),
        executable="/opt/qCoder Runtime/python",
        workspace="/tmp/work space",
        base_url="https://preview-api.qcoder.ai",
        token_file="/home/customer/.qcoder/context-bridge/token.txt",
        state_revision=7,
        loop_ref="loop-123",
        checkpoint="none",
        staged_operation=staged_operation,
    )


def test_inventory_is_complete_deterministic_and_diagnostics_only() -> None:
    first = operation_transport_inventory()
    second = operation_transport_inventory()
    assert first == second
    assert first["diagnostics_only"] is True
    assert first["assistant_constructs_commands_from_inventory"] is False
    assert len(first["inventory_digest"]) == 64
    assert {row["subcommand"] for row in first["operations"]} == {
        "status",
        "activate",
        "prepare-generation",
        "record-ide-authority",
        "register-artifacts",
        "authorize-artifacts",
        "process-authorized-artifacts",
        "enrich-authorized-evidence",
        "execute-recovery-action",
        "review-build",
        "continue-unchanged",
        "propose-change",
        "confirm-change",
        "start-next",
        "stage-checkpoint-input",
        "approve-checkpoint-input",
        "decline-checkpoint-input",
        "standalone-review",
        "attach-to-loop",
        "abandon",
        "contract-status",
        "contract-review-document",
        "contract-apply-document",
        "contract-reset-preset",
        "bounded-control-catalog",
        "contract-set-preset",
        "contract-adjust",
        "contract-confirm-broadening",
        "evidence-exclude",
        "evidence-restore",
        "evidence-delete",
        "open-contract-editor",
        "evidence-view",
        "decline-build-review",
        "prepare-adaptive-intent",
        "contract-set-generation-governance",
        "help",
        "complete-instruction",
    }


def test_all_local_only_invocations_exclude_hosted_transport() -> None:
    inventory = operation_transport_inventory()
    for row in inventory["operations"]:
        if row["transport"] != LOCAL_ONLY:
            continue
        invocation = _bind(row["subcommand"])["operation_specific_invocation"]
        assert invocation["schema_id"] == INVOCATION_CONTRACT_SCHEMA_ID
        assert invocation["transport_classification"] == LOCAL_ONLY
        assert invocation["hosted_access_permitted"] is False
        assert invocation["hosted_transport_argument_names"] == []
        argv = invocation["qcoder_owned_argv_prefix"]
        assert "--base-url" not in argv
        assert "--token-file" not in argv


def test_hosted_invocations_own_exact_transport_and_platform_serialization() -> None:
    for subcommand in (
        "prepare-generation",
        "enrich-authorized-evidence",
        "review-build",
        "propose-change",
        "confirm-change",
    ):
        invocation = _bind(subcommand)["operation_specific_invocation"]
        assert invocation["transport_classification"] == HOSTED_CAPABLE
        assert invocation["hosted_access_permitted"] is True
        assert invocation["hosted_transport_argument_names"] == [
            "--base-url",
            "--token-file",
        ]
        argv = invocation["qcoder_owned_argv_prefix"]
        assert argv[-4:] == [
            "--base-url",
            "https://preview-api.qcoder.ai",
            "--token-file",
            "/home/customer/.qcoder/context-bridge/token.txt",
        ]
        assert "'/opt/qCoder Runtime/python'" in invocation["platform_serialization"]["posix"]
        assert (
            '"\\/opt\\/qCoder Runtime\\/python"'.replace("\\/", "/")
            in (invocation["platform_serialization"]["windows"])
        )
        assert invocation["platform_serialization"]["assistant_reserializes"] is False


def test_staged_approval_transport_is_derived_from_qcoder_owned_operation() -> None:
    local = _bind("approve-checkpoint-input", staged_operation="continue_unchanged")[
        "operation_specific_invocation"
    ]
    hosted = _bind("approve-checkpoint-input", staged_operation="prepare_generation")[
        "operation_specific_invocation"
    ]
    assert local["transport_classification"] == LOCAL_ONLY
    assert "--token-file" not in local["qcoder_owned_argv_prefix"]
    assert hosted["transport_classification"] == HOSTED_CAPABLE
    assert "--token-file" in hosted["qcoder_owned_argv_prefix"]


def test_qcoder_owned_boolean_flags_and_dynamic_slots_are_not_appended_by_client() -> None:
    legacy = _legacy("activate")
    legacy["required_flags"] = [
        "--posture",
        "--approve-posture",
        "--posture-provenance",
    ]
    legacy["argument_values"] = [
        {
            "flag": "--posture",
            "value_source": "explicit_bounded_customer_choice",
            "allowed_values": ["exploratory_first_pass", "blueprint_guided"],
        }
    ]
    invocation = build_operation_invocation(
        legacy,
        executable="/runtime/python",
        workspace="/tmp/workspace",
        base_url="https://preview-api.qcoder.ai",
        token_file="/home/customer/.qcoder/context-bridge/token.txt",
        state_revision=4,
        loop_ref="loop-4",
        checkpoint="posture",
    )["operation_specific_invocation"]
    assert invocation["assistant_appends_qcoder_owned_flags"] is False
    assert "--approve-posture" in invocation["structured_argv"]
    assert any(
        isinstance(item, dict) and item.get("value_slot") == "posture"
        for item in invocation["structured_argv"]
    )
    assert "--expected-revision" in invocation["qcoder_owned_argv_prefix"]
    assert "--expected-loop-ref" in invocation["qcoder_owned_argv_prefix"]
    assert "--expected-checkpoint" in invocation["qcoder_owned_argv_prefix"]


def test_revision_loop_and_checkpoint_replay_fail_closed(tmp_path: Path) -> None:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    staged = coordinator.activate(
        original_request="Use qCoder for this build. Create one circuit.",
        generation_posture=None,
        explicit_authority=False,
    )
    binding = staged["next_invocation"]["operation_specific_invocation"]["state_binding"]
    coordinator.validate_invocation_binding(
        expected_revision=binding["revision"],
        expected_loop_ref=binding["loop_ref"],
        expected_checkpoint=binding["checkpoint"],
    )
    coordinator.activate(
        original_request=None,
        generation_posture=None,
        explicit_authority=True,
    )
    try:
        coordinator.validate_invocation_binding(
            expected_revision=binding["revision"],
            expected_loop_ref=binding["loop_ref"],
            expected_checkpoint=binding["checkpoint"],
        )
    except CurrentLoopError as exc:
        assert exc.category == "operation_invocation_revision_mismatch"
    else:
        raise AssertionError("stale invocation unexpectedly accepted")


def test_binding_v7_has_no_global_transport_routing_or_ambiguous_instruction(
    tmp_path: Path,
) -> None:
    instructions = build_client_activation_instructions(
        base_url="https://configured.example.invalid",
        token_file=tmp_path / "token file.txt",
        python_executable=tmp_path / "runtime folder" / "python",
    )
    lowered = instructions.lower()
    assert "pass transport_arguments exactly where supported" not in instructions
    assert '"transport_arguments"' not in instructions
    assert "append these hosted flags" not in lowered
    assert "determine whether this operation uses hosted transport" not in lowered
    assert "each supplied structured invocation" in instructions
    descriptor = build_client_binding_descriptor(
        coordinator_prefix=["/runtime/python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    assert descriptor["contract_id"] == "qcoder.connected_assistant.client_binding.v15"
    assert descriptor["schema_version"] == 15
    assert descriptor["operation_invocation_contract"]["global_transport_argument_array"] is False
    assert descriptor["operation_transport_inventory"]["diagnostics_only"] is True
    assert (
        descriptor["bootstrap_invocation_contract"][
            "coordinator_prefix_is_command_construction_primitive"
        ]
        is False
    )
    assert (
        descriptor["invocation_lifecycle_contract"]["gap_between_bootstrap_and_post_result"]
        is False
    )
    assert "transport_arguments" not in json.dumps(descriptor)


def test_ready_protocols_emit_operation_specific_invocations(tmp_path: Path) -> None:
    coordinator = CurrentLoopCoordinator(
        workspace_root=tmp_path,
        hosted_base_url="https://configured.example.invalid",
        hosted_token_file=tmp_path / "token.txt",
    )
    local = coordinator._result_without_state(
        operation="matrix",
        ok=True,
        phase="activated",
        state_status="ready",
        checkpoint_kind="none",
        summary="local",
    )
    hosted = coordinator._result_without_state(
        operation="matrix",
        ok=True,
        phase="evidence_processing",
        state_status="ready",
        checkpoint_kind="none",
        summary="hosted",
    )
    local_contract = local["next_invocation"]["operation_specific_invocation"]
    hosted_contract = hosted["next_invocation"]["operation_specific_invocation"]
    assert local_contract["transport_classification"] == LOCAL_ONLY
    assert "--token-file" not in local_contract["qcoder_owned_argv_prefix"]
    assert hosted_contract["transport_classification"] == LOCAL_ONLY
    assert "--token-file" not in hosted_contract["qcoder_owned_argv_prefix"]
    assert hosted_contract["state_binding"]["revision"] == 1
