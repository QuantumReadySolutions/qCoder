"""End-to-end regression for the a7 recovery-action result correction."""

from __future__ import annotations

from pathlib import Path

from qcoder.current_loop import canonical_bytes
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from tests.current_loop_test_support import activate_reviewed_legacy_fixture


def test_valid_v5_unsupported_recovery_action_emits_unsupported_action(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    coordinator = CurrentLoopCoordinator(
        workspace_root=workspace,
    )
    activation = activate_reviewed_legacy_fixture(
        coordinator,
        original_request="Use qCoder for this exact bounded build.",
    )
    assert activation["ok"] is True
    coordinator._recovery_result(
        operation="a7_recovery_action_result_semantic_regression",
        category="unknown_local_internal",
        phase="activated",
        elapsed=0.0,
    )

    state = coordinator.store.read()
    active = coordinator._coordinator_state(state)["active_recovery"]
    assert active["schema_id"] == "qcoder.current_loop.recovery.v5"
    assert active["schema_version"] == 5
    assert active["alternatives"] == ["abandon_step", "stop_loop"]

    before = canonical_bytes(state)
    result = coordinator.execute_recovery_action(
        recovery_reference=str(active["reference"]),
        action="retry_registration",
        expected_contract_revision=int(state["current_loop_contract"]["contract_revision"]),
    )
    after = canonical_bytes(coordinator.store.read())

    # These expectations are literal contract requirements. They do not call the
    # runtime classifier, recovery resolver, policy table, or implementation mapping.
    assert result["ok"] is False
    assert result["details"]["schema_gate_reason"] == ("recovery_action_not_permitted")
    assert (
        result["category"],
        result["result_semantic_classification"],
    ) == (
        "unsupported_action",
        "unsupported_action",
    )
    assert result["details"]["recovery_action_executed"] is False
    assert result["details"]["authoritative_state_mutated"] is False
    assert before == after
