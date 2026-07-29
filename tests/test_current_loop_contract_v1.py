from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from qcoder.current_loop import (
    CURRENT_LOOP_STATE_SCHEMA_ID,
    CurrentLoopStore,
    activate_current_loop,
    migrate_current_loop_state,
)
from qcoder.current_loop_contract import (
    CONTRACT_SCHEMA_ID,
    CurrentLoopContractError,
    adjust,
    classify_change,
    compile_preset,
    confirm_broadening,
    contract_error,
    contract_snapshot,
    new_contract,
    permits,
    set_preset,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator


REQUEST = "Use qCoder for this build. Keep the evidence path local."


def test_contract_presets_are_complete_and_keep_exposure_dimensions_distinct() -> None:
    evidence = compile_preset("evidence_only")
    assist = compile_preset("assist")
    assert set(evidence["categories"]) == set(contract_snapshot()["evidence_categories"])
    for policy in (evidence, assist):
        for row in policy["categories"].values():
            assert set(row) == {
                "collect",
                "derive",
                "expose",
                "recommend",
                "prepare",
                "request_application_or_execution",
            }
            exposure = row["expose"]
            assert set(exposure) == {
                "local_qcoder",
                "local_presentation",
                "connected_assistant",
            }
            assert set(exposure["connected_assistant"]) == {"raw", "derived"}
    assert assist["categories"]["derived_metrics"]["expose"]["connected_assistant"] == {
        "raw": "disabled",
        "derived": "standing",
    }
    assert evidence["categories"]["derived_metrics"]["expose"]["connected_assistant"] == {
        "raw": "disabled",
        "derived": "on_request",
    }
    assert classify_change(assist, evidence) == "narrowing"
    assert classify_change(evidence, assist) == "broadening"


def test_narrowing_applies_and_broadening_requires_authority() -> None:
    contract = new_contract(
        baseline_digest="a" * 64,
        capture_provenance="exact_current_customer_message",
        activation_revision=1,
    )
    narrowed = set_preset(
        contract,
        preset="evidence_only",
        expected_contract_revision=1,
        provenance="customer_requested_narrowing",
    )
    assert narrowed["disposition"] == "narrowing"
    assert narrowed["contract"]["contract_revision"] == 2
    assert narrowed["contract"]["dependent_views_stale"] is True
    proposed = set_preset(
        narrowed["contract"],
        preset="assist",
        expected_contract_revision=2,
        provenance="explicit_customer_selection",
    )
    assert proposed["disposition"] == "broadening"
    assert proposed["contract"]["contract_revision"] == 2
    with pytest.raises(CurrentLoopContractError, match="authority_required"):
        confirm_broadening(
            proposed["contract"],
            expected_contract_revision=2,
            explicit_authority=False,
        )
    confirmed = confirm_broadening(
        proposed["contract"],
        expected_contract_revision=2,
        explicit_authority=True,
    )
    assert confirmed["contract_revision"] == 3
    assert confirmed["pending_broadening_proposal"] is None


def test_adjustment_is_bounded_and_raw_assistant_exposure_ceiling_fails() -> None:
    contract = new_contract(
        baseline_digest="b" * 64,
        capture_provenance="exact_current_customer_message",
        activation_revision=1,
    )
    result = adjust(
        contract,
        category="derived_metrics",
        dimension="assistant_derived_exposure",
        value="on_request",
        expected_contract_revision=1,
        provenance="explicit_customer_selection",
    )
    assert result["disposition"] == "narrowing"
    with pytest.raises(CurrentLoopContractError, match="raw_exposure_ceiling"):
        adjust(
            result["contract"],
            category="derived_metrics",
            dimension="assistant_raw_exposure",
            value="on_request",
            expected_contract_revision=2,
            provenance="explicit_customer_selection",
        )


def test_exact_message_activation_creates_assist_receipt_and_defers_posture(
    tmp_path: Path,
) -> None:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    result = coordinator.activate(
        original_request=REQUEST,
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    assert result["ok"] is True
    assert result["phase"] == "activated"
    assert result["details"]["assist_ready"] is True
    assert result["details"]["posture_deferred"] is True
    assert result["details"]["original_request"] == REQUEST
    receipt = result["details"]["activation_receipt"]
    assert receipt["preset"] == "assist"
    assert receipt["authority_exclusions"]
    state = coordinator.store.read()
    assert state["schema_id"] == CURRENT_LOOP_STATE_SCHEMA_ID
    assert state["generation_posture"] is None
    assert state["current_loop_contract"]["schema_id"] == CONTRACT_SCHEMA_ID
    assert state["current_loop_contract"]["cross_loop_inheritance"] is False
    assert state["automatic_reopen"] is False
    controls = result["bounded_contract_controls"]
    assert set(controls) == {
        "inspect",
        "set_preset",
        "adjust",
        "confirm_broadening",
        "exclude",
        "restore",
        "delete",
        "stop_loop",
    }
    assert all(item["transport_classification"] == "local_only" for item in controls.values())
    assert all("--base-url" not in item["structured_argv"] for item in controls.values())
    assert controls["set_preset"]["fixed_argument_values"]["--expected-contract-revision"] == 1
    assert controls["exclude"]["fixed_argument_values"]["--expected-contract-revision"] == 1
    assert controls["restore"]["fixed_argument_values"]["--expected-contract-revision"] == 1
    assert controls["delete"]["fixed_argument_values"]["--expected-contract-revision"] == 1


def test_review_required_path_stays_non_authoritative(tmp_path: Path) -> None:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    result = coordinator.activate(
        original_request=REQUEST,
        explicit_authority=True,
        capture_mode="review_required",
        request_transport="stdin",
    )
    assert result["ok"] is True
    assert result["checkpoint_kind"] == "activation_request_baseline_review"
    assert coordinator.store.read()["state_kind"] == "pending_activation"


def test_v2_active_state_migrates_atomically_without_inheritance(tmp_path: Path) -> None:
    activated = activate_current_loop(
        workspace_root=tmp_path,
        generation_posture=None,
        explicit_authority=True,
        request_baseline_digest="c" * 64,
    )
    store = CurrentLoopStore.for_workspace(tmp_path)
    v3 = activated["state"]
    v2 = deepcopy(v3)
    v2["schema_id"] = "qcoder.current_loop.local_state.v2"
    v2["schema_version"] = 2
    v2.pop("current_loop_contract")
    v2.pop("operation_receipts")
    v2.pop("activity_receipts")
    from qcoder.current_loop import _state_digest

    v2["state_digest"] = _state_digest(v2)
    store.replace(v2, expected_revision=v3["state_revision"])
    migrated = migrate_current_loop_state(store)
    assert migrated["schema_id"] == CURRENT_LOOP_STATE_SCHEMA_ID
    assert migrated["current_loop_contract"]["effective_preset"] == "assist"
    assert migrated["current_loop_contract"]["change_history"] == []
    assert migrated["current_loop_contract"]["evidence_exclusions"] == {}
    assert contract_error(migrated["current_loop_contract"]) is None


def test_contract_enforcement_blocks_excluded_reference() -> None:
    contract = new_contract(
        baseline_digest="d" * 64,
        capture_provenance="exact_current_customer_message",
        activation_revision=1,
    )
    contract["evidence_exclusions"]["session-artifact-" + "a" * 32] = {
        "artifact_reference": "session-artifact-" + "a" * 32,
        "artifact_digest": "e" * 64,
        "reason": "customer_excluded",
        "excluded_at_contract_revision": 2,
    }
    assert (
        permits(
            contract,
            category="python_manifestation",
            dimension="collect",
            artifact_reference="session-artifact-" + "a" * 32,
        )
        is False
    )


def test_evidence_controls_are_bound_to_contract_revision(tmp_path: Path) -> None:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    activated = coordinator.activate(
        original_request=REQUEST,
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    reference = next(
        item["artifact_reference"]
        for item in activated["saved_artifact_references"]
        if item["role"] == "request_baseline"
    )
    stale = coordinator.evidence_exclude(
        artifact_reference=reference,
        reason="not_relevant",
        expected_contract_revision=99,
    )
    assert stale["ok"] is False
    assert stale["category"] == "contract_revision_stale"
    excluded = coordinator.evidence_exclude(
        artifact_reference=reference,
        reason="not_relevant",
        expected_contract_revision=1,
    )
    assert excluded["ok"] is True
    assert coordinator.store.read()["current_loop_contract"]["contract_revision"] == 2
    restored = coordinator.evidence_restore(
        artifact_reference=reference,
        expected_contract_revision=2,
    )
    assert restored["ok"] is True
    assert coordinator.store.read()["current_loop_contract"]["contract_revision"] == 3
