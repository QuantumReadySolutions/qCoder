from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import pytest

from qcoder.cli import main as cli_main
from qcoder.current_loop import canonical_bytes
from qcoder.current_loop_checkpoint_input import (
    CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_ID,
    CHECKPOINT_INPUT_OPERATIONS,
    checkpoint_input_construction,
    decode_checkpoint_input,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator


CHECKPOINT_ROWS = (
    ("prepare_generation", "intent_review"),
    ("prepare_generation", "decision_resolution"),
    ("prepare_generation", "posture"),
    ("continue_unchanged", "governing_change_confirmation"),
    ("propose_change", "governing_change_confirmation"),
    ("confirm_change", "governing_change_confirmation"),
)


def _black_box_payload(
    serialized_construction: str,
    supplied_values: Mapping[str, object],
) -> bytes:
    """Consume only client-visible construction data and synthetic values."""

    construction = json.loads(serialized_construction)
    assert construction["schema_id"] == CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_ID
    declared = {item["name"]: item for item in construction["accepted_value_fields"]}
    fields: list[dict[str, object]] = []
    for name, value in supplied_values.items():
        assert name in declared
        fields.append(
            {
                "name": name,
                "value": value,
                "provenance": declared[name]["allowed_provenance"][0],
            }
        )
    assert all(
        not item["required"] or item["name"] in supplied_values for item in declared.values()
    )
    payload = deepcopy(construction["fixed_payload"])
    payload[construction["assistant_supplied_property"]] = fields
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _required_values(operation: str) -> dict[str, object]:
    return {
        "prepare_generation": {
            "profile_id": "generic_qiskit",
            "proposed_interpretation": {"summary": "`00` and `11` $(printf inert) Ω 😀"},
        },
        "continue_unchanged": {"user_statement": "Decline and continue unchanged."},
        "propose_change": {
            "decision_ref": "decision-00000000000000000000000000000001",
            "selected_action": "accept_and_add_to_blueprint",
            "proposed_value": {"shots": 1024},
            "control_treatment": "keep_fixed",
        },
        "confirm_change": {"semantic_confirmation": "Confirm this exact proposal."},
    }[operation]


@pytest.mark.parametrize(("operation", "checkpoint_kind"), CHECKPOINT_ROWS)
def test_binding_completeness_matrix_is_black_box_constructible(
    operation: str,
    checkpoint_kind: str,
) -> None:
    construction = checkpoint_input_construction(
        operation=operation,
        checkpoint_kind=checkpoint_kind,
        workspace_binding="/synthetic/workspace",
        loop_ref="loop-00000000000000000000000000000001",
        phase=(
            "intent_review"
            if operation == "prepare_generation"
            else (
                "continuation_choice"
                if operation in {"continue_unchanged", "propose_change"}
                else "change_confirmation"
            )
        ),
        expected_state_revision=9,
    )
    serialized = json.dumps(construction, ensure_ascii=False)
    payload = _black_box_payload(serialized, _required_values(operation))
    decoded = json.loads(payload.decode("utf-8"))
    assert decoded["binding"]["operation"] == operation
    assert decoded["binding"]["checkpoint_kind"] == checkpoint_kind
    assert decoded["binding"]["expected_state_revision"] == 9
    assert construction["stage_invocation"]["required_flags"] == [
        "--checkpoint-input-stdin or --checkpoint-input-file"
    ]
    assert construction["stage_invocation"]["operation_or_checkpoint_flags_required"] is False
    assert construction["digest_semantics"]["assistant_computes_digest"] is False
    digest = construction.pop("construction_digest")
    assert sha256(canonical_bytes(construction)).hexdigest() == digest


def _activated_coordinator(workspace: Path) -> tuple[CurrentLoopCoordinator, dict[str, Any]]:
    workspace.mkdir()
    coordinator = CurrentLoopCoordinator(workspace_root=workspace)
    request = "Use qCoder for this build. Create one synthetic circuit."
    captured = coordinator.activate(original_request=request)
    assert captured["checkpoint_kind"] == "activation_request_baseline_review"
    activated = coordinator.activate(
        explicit_authority=True,
        generation_posture="exploratory_first_pass",
        explicit_posture_authority=True,
        posture_authority_provenance="user_confirmed_assistant_recommendation",
    )
    return coordinator, activated


def test_serialized_result_is_sufficient_and_cli_metadata_is_not_duplicated(
    tmp_path: Path,
) -> None:
    coordinator, result = _activated_coordinator(tmp_path / "binding")
    construction = result["checkpoint_input_construction"]
    payload = _black_box_payload(
        json.dumps(construction, ensure_ascii=False),
        _required_values("prepare_generation"),
    )
    staged = coordinator.stage_checkpoint_input(
        operation=None,
        checkpoint_kind=None,
        payload=decode_checkpoint_input(payload),
        transport="stdin",
    )
    assert staged["ok"] is True
    assert staged["checkpoint_kind"] == "checkpoint_input_review"
    assert staged["details"]["complete_values_displayed"] is True
    assert staged["details"]["authority_granted"] is False
    assert staged["details"]["protected_call_performed"] is False


def test_cli_stages_generated_payload_without_operation_or_checkpoint_flags(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "cli-binding"
    _coordinator, result = _activated_coordinator(workspace)
    payload = _black_box_payload(
        json.dumps(result["checkpoint_input_construction"], ensure_ascii=False),
        _required_values("prepare_generation"),
    )

    class _Stdin:
        buffer = BytesIO(payload)

        @staticmethod
        def isatty() -> bool:
            return False

    monkeypatch.setattr(sys, "stdin", _Stdin())
    assert (
        cli_main(
            [
                "current-loop",
                "--workspace",
                str(workspace),
                "stage-checkpoint-input",
                "--checkpoint-input-stdin",
            ]
        )
        == 0
    )
    staged = json.loads(capsys.readouterr().out)
    assert staged["checkpoint_kind"] == "checkpoint_input_review"
    assert staged["details"]["authority_granted"] is False


@pytest.mark.parametrize(
    ("mutation", "category"),
    (
        (
            {"checkpoint_kind": "governing_change_confirmation"},
            "checkpoint_input_checkpoint_mismatch",
        ),
        ({"expected_state_revision": 999}, "checkpoint_input_state_revision_stale"),
    ),
)
def test_structural_mismatch_is_sanitized_and_emits_no_hosted_action(
    tmp_path: Path,
    mutation: Mapping[str, object],
    category: str,
) -> None:
    coordinator, result = _activated_coordinator(tmp_path / category)
    construction = deepcopy(result["checkpoint_input_construction"])
    construction["fixed_payload"]["binding"].update(mutation)
    payload = _black_box_payload(
        json.dumps(construction, ensure_ascii=False),
        _required_values("prepare_generation"),
    )
    rejected = coordinator.stage_checkpoint_input(
        operation=None,
        checkpoint_kind=None,
        payload=decode_checkpoint_input(payload),
        transport="stdin",
    )
    assert rejected["ok"] is False
    assert rejected["category"] == category
    diagnostic = rejected["details"]["structural_error"]
    assert diagnostic["error_code"] == category
    assert diagnostic["assistant_should_stop"] is True
    assert diagnostic["hosted_operation_permitted"] is False
    assert rejected["supported_next_action"] == "refresh_bounded_recovery"
    invocation = rejected["next_invocation"]["operation_specific_invocation"]
    assert invocation["operation"] == "status"
    assert invocation["transport_classification"] == "local_only"
    assert invocation["hosted_access_permitted"] is False
    assert "summary" not in json.dumps(diagnostic)


def test_posture_transport_is_enum_only_in_transition_protocol(tmp_path: Path) -> None:
    coordinator, _result = _activated_coordinator(tmp_path / "posture")
    checkpoint = coordinator._checkpoint_result(
        operation="prepare_generation",
        phase="intent_review",
        checkpoint_kind="posture",
        summary="Separate posture authority required.",
        elapsed=0.0,
        category="posture_transition_authority_required",
    )
    assert checkpoint["supported_next_action"] == ("obtain_separate_generation_posture_authority")
    assert checkpoint["input_source_disposition"]["categories"] == [
        "bounded_enumerated_customer_choice",
        "authority_only_approval",
    ]
    assert checkpoint["checkpoint_input_construction"] is None
    assert checkpoint["next_invocation"]["subcommand"] == "prepare-generation"
    assert "--use-current-intent" in checkpoint["next_invocation"]["required_flags"]
    assert "checkpoint_input_transport" not in checkpoint["input_source_disposition"]["categories"]


def test_compatibility_operation_duplication_mismatch_fails_closed(
    tmp_path: Path,
) -> None:
    coordinator, result = _activated_coordinator(tmp_path / "operation-mismatch")
    payload = _black_box_payload(
        json.dumps(result["checkpoint_input_construction"], ensure_ascii=False),
        _required_values("prepare_generation"),
    )
    rejected = coordinator.stage_checkpoint_input(
        operation="confirm_change",
        checkpoint_kind="intent_review",
        payload=decode_checkpoint_input(payload),
        transport="stdin",
    )
    assert rejected["category"] == "checkpoint_input_operation_mismatch"
    assert rejected["details"]["structural_error"]["hosted_operation_permitted"] is False


def test_operation_inventory_is_complete() -> None:
    assert {operation for operation, _kind in CHECKPOINT_ROWS} == set(CHECKPOINT_INPUT_OPERATIONS)
