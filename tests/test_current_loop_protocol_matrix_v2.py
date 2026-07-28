from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from qcoder.cli import main as cli_main
from qcoder.current_loop import CurrentLoopError, GENERATION_POSTURES
from qcoder.current_loop_coordinator import (
    CHECKPOINT_KINDS,
    PHASES,
    PERMITTED_INPUT_SOURCE_CATEGORIES,
    CurrentLoopCoordinator,
)


ACTIVE_NONTERMINAL_PHASES = tuple(
    phase for phase in PHASES if phase not in {"completed", "abandoned"}
)
NONACTION_RECOVERY_STATUSES = ("stale", "blocked", "conflict", "corrupt")
CHECKPOINT_PHASES = {
    "activation_request_baseline_review": "activated",
    "activation": "activated",
    "posture": "activated",
    "intent_review": "intent_review",
    "decision_resolution": "intent_review",
    "ide_write_or_run": "generation_ready",
    "artifact_review": "artifact_authorization",
    "checkpoint_input_review": "intent_review",
    "governing_change_confirmation": "change_confirmation",
    "privacy_or_trust": "evidence_processing",
    "none": "continuation_choice",
}


def _synthetic_result(
    coordinator: CurrentLoopCoordinator,
    *,
    phase: str,
    state_status: str,
    checkpoint_kind: str,
    category: str | None = None,
) -> dict[str, Any]:
    return coordinator._result_without_state(
        operation="protocol_matrix_test",
        ok=state_status not in NONACTION_RECOVERY_STATUSES,
        phase=phase,
        state_status=state_status,
        checkpoint_kind=checkpoint_kind,
        category=category,
        summary=(f"Synthetic protocol matrix state {phase}/{state_status}/{checkpoint_kind}."),
    )


def _assert_actionable_protocol(result: Mapping[str, Any]) -> None:
    assert result["supported_next_action"]
    assert isinstance(result["next_invocation"], Mapping)
    assert result["no_action_reason"] is None
    assert result["no_action_disposition"] is None
    assert isinstance(result["permitted_input_source"], str)
    assert result["permitted_input_source"]
    source = result["input_source_disposition"]
    assert source["schema_id"] == ("qcoder.current_loop.permitted_input_source_disposition.v1")
    assert source["schema_version"] == 1
    assert source["permitted_source"] == result["permitted_input_source"]
    assert source["categories"]
    assert set(source["categories"]) <= set(PERMITTED_INPUT_SOURCE_CATEGORIES)
    assert "no_input_permitted_or_required" not in source["categories"]
    semantics = result["bounded_input_semantics"]
    assert semantics["input_required"] is True
    assert semantics["arbitrary_free_text_in_argv_permitted"] is False
    assert semantics["customer_types_coordinator_command"] is False
    assert semantics["assistant_may_infer_input_or_authority"] is False
    assert semantics["qcoder_held_values_retransmitted"] is False
    assert result["prohibited_derivations"] == [
        "conversation_reconstruction",
        "transcript_search",
        "source_or_package_inspection",
        "qcoder_local_state_inspection",
    ]
    assert result["protocol_binding"]["current_local_state_is_canonical"] is True
    assert result["required_authority_disposition"]["content_submission_grants_authority"] is False


@pytest.mark.parametrize("phase", ACTIVE_NONTERMINAL_PHASES)
def test_every_active_ready_phase_has_a_complete_protocol(
    tmp_path: Path,
    phase: str,
) -> None:
    result = _synthetic_result(
        CurrentLoopCoordinator(workspace_root=tmp_path),
        phase=phase,
        state_status="ready",
        checkpoint_kind="none",
    )
    _assert_actionable_protocol(result)


@pytest.mark.parametrize("checkpoint_kind", CHECKPOINT_KINDS)
def test_every_checkpoint_kind_has_a_complete_protocol(
    tmp_path: Path,
    checkpoint_kind: str,
) -> None:
    result = _synthetic_result(
        CurrentLoopCoordinator(workspace_root=tmp_path),
        phase=CHECKPOINT_PHASES[checkpoint_kind],
        state_status="checkpoint_required",
        checkpoint_kind=checkpoint_kind,
    )
    _assert_actionable_protocol(result)


@pytest.mark.parametrize("phase", ACTIVE_NONTERMINAL_PHASES)
@pytest.mark.parametrize("state_status", NONACTION_RECOVERY_STATUSES)
def test_every_nonaction_recovery_state_has_an_explicit_disposition(
    tmp_path: Path,
    phase: str,
    state_status: str,
) -> None:
    result = _synthetic_result(
        CurrentLoopCoordinator(workspace_root=tmp_path),
        phase=phase,
        state_status=state_status,
        checkpoint_kind="privacy_or_trust",
    )
    assert result["supported_next_action"] is None
    assert result["next_invocation"] is None
    assert result["permitted_input_source"] == "no_input_permitted_or_required"
    assert result["input_source_disposition"]["categories"] == ["no_input_permitted_or_required"]
    assert result["bounded_input_semantics"]["input_required"] is False
    disposition = result["no_action_disposition"]
    assert disposition["reason"] == (f"state_status_{state_status}_requires_bounded_recovery")
    assert disposition["assistant_should_stop"] is True
    assert disposition["current_build_complete"] is False
    assert disposition["new_loop_may_be_started"] is False


@pytest.mark.parametrize("phase", ("completed", "abandoned"))
def test_terminal_phase_dispositions_cannot_masquerade_as_active(
    tmp_path: Path,
    phase: str,
) -> None:
    result = _synthetic_result(
        CurrentLoopCoordinator(workspace_root=tmp_path),
        phase=phase,
        state_status="ready",
        checkpoint_kind="none",
    )
    assert result["terminal"] is True
    assert result["supported_next_action"] is None
    assert result["next_invocation"] is None
    assert result["no_action_disposition"]["assistant_should_stop"] is True
    assert result["no_action_disposition"]["current_build_complete"] is (phase == "completed")
    assert result["no_action_disposition"]["prior_branch_closed"] is True


def test_posture_checkpoint_is_bounded_enumerated_and_status_reemits_it(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "posture-protocol"
    workspace.mkdir()
    request = "Use qCoder for this build. Create one synthetic circuit."
    capture_argv = [
        "current-loop",
        "--workspace",
        str(workspace),
        "activate",
        "--request",
        request,
    ]
    assert cli_main(capture_argv) == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["checkpoint_kind"] == "activation_request_baseline_review"

    approve_argv = [
        "current-loop",
        "--workspace",
        str(workspace),
        "activate",
        "--approve",
    ]
    assert cli_main(approve_argv) == 0
    posture = json.loads(capsys.readouterr().out)
    assert posture["phase"] == "activated"
    assert posture["checkpoint_kind"] == "posture"
    assert posture["supported_next_action"] == ("obtain_separate_generation_posture_authority")
    assert posture["permitted_input_source"] == (
        "explicit_customer_bounded_posture_choice_or_explicitly_accepted_supported_recommendation"
    )
    assert posture["input_source_disposition"]["categories"] == [
        "bounded_enumerated_customer_choice",
        "authority_only_approval",
    ]
    assert posture["bounded_input_semantics"]["accepted_values"]["generation_posture"] == list(
        GENERATION_POSTURES
    )
    assert posture["bounded_input_semantics"]["content_transport"] == "none"
    assert posture["next_invocation"]["argument_values"][0]["allowed_values"] == list(
        GENERATION_POSTURES
    )

    assert cli_main(["current-loop", "--workspace", str(workspace), "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["permitted_input_source"] == posture["permitted_input_source"]
    assert status["input_source_disposition"] == posture["input_source_disposition"]
    assert status["bounded_input_semantics"] == posture["bounded_input_semantics"]
    assert status["next_invocation"] == posture["next_invocation"]

    selection_argv = [
        "current-loop",
        "--workspace",
        str(workspace),
        "activate",
        "--posture",
        "exploratory_first_pass",
        "--approve-posture",
        "--posture-provenance",
        "user_confirmed_assistant_recommendation",
    ]
    assert cli_main(selection_argv) == 0
    selected = json.loads(capsys.readouterr().out)
    assert selected["phase"] == "intent_review"
    assert selected["details"]["generation_posture"] == "exploratory_first_pass"


def _validate_mutated(result: Mapping[str, Any]) -> None:
    CurrentLoopCoordinator._validate_protocol_disposition(
        phase=str(result["phase"]),
        state_status=str(result["state_status"]),
        checkpoint_kind=str(result["checkpoint_kind"]),
        protocol=result,
    )


def test_cross_field_invariants_fail_closed(tmp_path: Path) -> None:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    posture = _synthetic_result(
        coordinator,
        phase="activated",
        state_status="ready",
        checkpoint_kind="posture",
    )
    missing_source = deepcopy(posture)
    missing_source["permitted_input_source"] = None
    with pytest.raises(
        CurrentLoopError,
        match="coordinator_protocol_permitted_input_source_missing",
    ):
        _validate_mutated(missing_source)

    posture_transport = deepcopy(posture)
    posture_transport["input_source_disposition"]["categories"].append("checkpoint_input_transport")
    with pytest.raises(
        CurrentLoopError,
        match="coordinator_protocol_posture_transport_invalid",
    ):
        _validate_mutated(posture_transport)

    staged = _synthetic_result(
        coordinator,
        phase="intent_review",
        state_status="ready",
        checkpoint_kind="intent_review",
    )
    staged["input_source_disposition"]["categories"] = ["qcoder_managed_canonical_reference"]
    with pytest.raises(
        CurrentLoopError,
        match="coordinator_protocol_checkpoint_input_source_mismatch",
    ):
        _validate_mutated(staged)

    approval = _synthetic_result(
        coordinator,
        phase="intent_review",
        state_status="checkpoint_required",
        checkpoint_kind="checkpoint_input_review",
    )
    approval["next_invocation"]["staged_values_retransmitted"] = True
    with pytest.raises(
        CurrentLoopError,
        match="coordinator_protocol_content_retransmission_invalid",
    ):
        _validate_mutated(approval)

    no_action = _synthetic_result(
        coordinator,
        phase="intent_review",
        state_status="blocked",
        checkpoint_kind="privacy_or_trust",
    )
    no_action["next_invocation"] = {"subcommand": "prepare-generation"}
    with pytest.raises(
        CurrentLoopError,
        match="coordinator_protocol_no_action_invocation_invalid",
    ):
        _validate_mutated(no_action)

    next_loop = _synthetic_result(
        coordinator,
        phase="next_loop_ready",
        state_status="ready",
        checkpoint_kind="none",
    )
    next_loop["next_invocation"]["allowed_subcommand_alternatives"].append("propose_change")
    with pytest.raises(
        CurrentLoopError,
        match="coordinator_protocol_closed_branch_reopened",
    ):
        _validate_mutated(next_loop)
