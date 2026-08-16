"""Test-only Current Loop setup for pre-D-080 subsystem regressions."""

from __future__ import annotations

from qcoder.current_loop_coordinator import CurrentLoopCoordinator


def activate_reviewed_legacy_fixture(
    coordinator: CurrentLoopCoordinator,
    *,
    original_request: str,
) -> dict:
    """Create a reviewed, non-customer legacy subsystem fixture.

    Production's exact-message entry may not bypass D-080 semantics. Older
    subsystem tests still need a generic active loop to isolate their receipt,
    evidence, recovery, and contract behavior, so they establish that state
    explicitly after canonical Request Baseline review.
    """

    staged = coordinator.activate(
        original_request=original_request,
        capture_mode="review_required",
        request_transport="stdin",
    )
    assert staged["checkpoint_kind"] == "activation_request_baseline_review"
    activated = coordinator.activate(
        explicit_authority=True,
        generation_posture="exploratory_first_pass",
        explicit_posture_authority=True,
        posture_authority_provenance="user_confirmed_assistant_recommendation",
    )
    assert activated["ok"] is True
    state = coordinator.store.read()
    current = coordinator._coordinator_state(state)
    current.update(
        {
            "phase": "intent_review",
            "state_status": "ready",
            "checkpoint_kind": "none",
            "customer_summary": "Reviewed legacy subsystem test fixture is ready.",
        }
    )
    coordinator._replace_coordinator(current)
    coordinator._adaptive_intent_contract(coordinator.store.read(), initialize=True)
    return coordinator.status()
