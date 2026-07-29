from __future__ import annotations

from pathlib import Path
import json

from qcoder.context_bridge_mcp import EXPECTED_TOOLS
from qcoder.current_loop import build_loop_instance_record
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_invocation import operation_transport_inventory


def _evidence_ready(tmp_path: Path) -> CurrentLoopCoordinator:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    activated = coordinator.activate(
        original_request="Use qCoder for this build and keep Build Review optional.",
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    assert activated["ok"] is True
    state = coordinator.store.read()
    record = build_loop_instance_record(
        loop_ref=state["loop_ref"],
        parent_loop_ref=None,
        generation_posture="exploratory_first_pass",
        label=None,
        governing_blueprint=None,
    )
    record_path = coordinator.store.state_path.with_name("synthetic-loop-record.json")
    record_path.write_text(json.dumps(record), encoding="utf-8")
    current = coordinator._coordinator_state(state)
    current.update(
        {
            "phase": "evidence_processing",
            "state_status": "ready",
            "checkpoint_kind": "none",
            "evidence_processing_complete": True,
        }
    )

    def mutate(value: dict) -> dict:
        value["generation_posture"] = "exploratory_first_pass"
        value["loop_instance_record_path"] = str(record_path)
        value["loop_instance_record_digest"] = record["artifact_digest"]
        value["coordinator"] = current
        return value

    coordinator.store.update(mutate, expected_revision=state["state_revision"])
    return coordinator


def test_build_review_offer_is_optional_and_decline_continues(tmp_path: Path) -> None:
    coordinator = _evidence_ready(tmp_path)
    status = coordinator.status()
    assert status["build_review_optional"] is True
    assert "decline-build-review" in status["next_invocation"]["allowed_subcommand_alternatives"]
    declined = coordinator.decline_build_review(explicit_authority=True)
    assert declined["ok"] is True
    assert declined["phase"] == "continuation_choice"
    assert declined["details"]["working_blueprint_unchanged"] is True
    assert declined["details"]["evolved_blueprint_created"] is False
    assert declined["details"]["hosted_operation_invoked"] is False
    assert declined["details"]["may_request_later"] is True


def test_review_may_be_requested_later_but_browser_never_hosts(tmp_path: Path) -> None:
    coordinator = _evidence_ready(tmp_path)
    coordinator.decline_build_review(explicit_authority=True)
    result = coordinator.review_build()
    # Exact parent evidence is deliberately absent in this fixture.  The call
    # reaches the existing review operation and fails closed rather than
    # inventing evidence or mutating a Blueprint.
    assert result["ok"] is False
    assert result["operation"] == "review_build"
    assert result["details"].get("evolved_blueprint_created") is None
    assert len(EXPECTED_TOOLS) == 12
    rows = {row["operation"]: row for row in operation_transport_inventory()["operations"]}
    assert rows["review_build"]["transport"] == "hosted_capable"
    assert rows["decline_build_review"]["transport"] == "local_only"
    assert rows["open_contract_editor"]["transport"] == "local_only"


def test_build_review_decline_without_authority_is_nonmutating(tmp_path: Path) -> None:
    coordinator = _evidence_ready(tmp_path)
    before = coordinator.store.read()
    declined = coordinator.decline_build_review(explicit_authority=False)
    assert declined["ok"] is True
    assert declined["state_status"] == "checkpoint_required"
    after = coordinator.store.read()
    assert after["saved_artifacts"] == before["saved_artifacts"]
    assert "evolved_blueprint" not in after["saved_artifacts"]
