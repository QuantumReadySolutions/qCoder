from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from threading import Barrier
from typing import Any, Callable, Mapping

import pytest

import qcoder.current_loop_coordinator as coordinator_module
import qcoder.current_loop_contract_sidecar as sidecar_module
from qcoder.current_loop import CurrentLoopConflict, canonical_bytes
from qcoder.current_loop_contract import adjust
from qcoder.current_loop_contract_management import customer_contract_document
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_event_receipts import (
    EventReceiptError,
    event_receipt_snapshot,
    supersede_operation_receipt,
    validate_operation_receipt,
)
from qcoder.current_loop_recovery import recovery_contract_snapshot
from qcoder.current_loop_registration import (
    commit_registration_transaction,
    prepare_registration_transaction,
)
from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    EXPECTED_TOOLS,
    build_client_binding_descriptor,
)
from tests.current_loop_test_support import activate_reviewed_legacy_fixture


class FakeClock:
    def __init__(self, value: float = 100.0):
        self.value = value

    def __call__(self) -> float:
        return self.value


def _active(tmp_path: Path, *, clock: Callable[[], float] | None = None) -> CurrentLoopCoordinator:
    coordinator = CurrentLoopCoordinator(
        workspace_root=tmp_path,
        **({"clock": clock} if clock is not None else {}),
    )
    activated = activate_reviewed_legacy_fixture(
        coordinator,
        original_request="Use qCoder for this build. Track exact authorized outputs.",
    )
    assert activated["ok"] is True
    return coordinator


def _issue(
    coordinator: CurrentLoopCoordinator,
    *,
    roles: tuple[str, ...] = ("source",),
    category: str = "ide_write",
) -> dict[str, Any]:
    result = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        operation_category=category,
        output_role_ceiling=roles,
    )
    assert result["ok"] is True
    return result["details"]["operation_receipt"]


def _source_candidate(
    tmp_path: Path, *, name: str = "program.py", value: int = 1
) -> dict[str, Any]:
    source = tmp_path / name
    source.write_text(f"VALUE = {value}\n", encoding="utf-8")
    return {
        "role": "source",
        "path": str(source),
        "provenance": "assistant_created",
        "explicit_external": False,
    }


def _assert_receipt_valid(
    coordinator: CurrentLoopCoordinator,
    receipt: Mapping[str, Any],
) -> None:
    state = coordinator.store.read()
    validate_operation_receipt(
        receipt,
        loop_ref=str(state["loop_ref"]),
        workspace_binding=str(state["workspace_root"]),
        current_state_revision=int(state["state_revision"]),
        current_contract_revision=int(state["current_loop_contract"]["contract_revision"]),
        role="source",
        detected_format="python_source",
        current_time=coordinator.clock(),
    )


def test_single_repeated_mixed_and_concurrent_pure_reads_are_revision_neutral(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    receipt = _issue(coordinator)
    state = coordinator.store.read()
    contract_document = customer_contract_document(state["current_loop_contract"])
    before = canonical_bytes(state)
    before_revision = state["state_revision"]
    before_digest = state["state_digest"]
    before_pending = deepcopy(coordinator._coordinator_state(state).get("pending_checkpoint_input"))

    projections = (
        lambda: coordinator.status(),
        lambda: coordinator.contract_status(),
        lambda: coordinator.bounded_control_catalog(),
        lambda: coordinator.help(topic="overview"),
        lambda: coordinator.contract_review_customer_document(document=contract_document),
        lambda: coordinator.contract_apply_customer_document(
            document=contract_document,
            choice="cancel",
            explicit_authority=False,
        ),
        lambda: coordinator.contract_reset_to_preset(
            preset="assist",
            choice="cancel",
            explicit_authority=False,
        ),
        lambda: coordinator.contract_set_preset(
            preset="assist",
            expected_contract_revision=int(contract_document["expected_contract_revision"]),
        ),
        lambda: coordinator.contract_adjust(
            category="python_manifestation",
            dimension="collect",
            value="enabled",
            expected_contract_revision=int(contract_document["expected_contract_revision"]),
        ),
        lambda: coordinator.contract_set_generation_governance(
            governance="adaptive",
            expected_contract_revision=int(contract_document["expected_contract_revision"]),
        ),
        lambda: coordinator.evidence_view(view_id="current_build_facts"),
    )
    for projection in projections:
        assert projection()["ok"] is True
        assert canonical_bytes(coordinator.store.read()) == before
    for _ in range(32):
        assert coordinator.status()["ok"] is True
        assert coordinator.contract_status()["ok"] is True
    for index in range(35):
        assert projections[index % len(projections)]()["ok"] is True

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda index: projections[index % len(projections)]()["ok"],
                range(64),
            )
        )
    assert all(results)
    after = coordinator.store.read()
    assert canonical_bytes(after) == before
    assert after["state_revision"] == before_revision
    assert after["state_digest"] == before_digest
    assert coordinator._coordinator_state(after).get("pending_checkpoint_input") == before_pending
    _assert_receipt_valid(coordinator, receipt)

    registered = coordinator.register_artifacts(
        candidates=[_source_candidate(tmp_path)],
        operation_receipt_id=str(receipt["receipt_id"]),
    )
    assert registered["ok"] is True


def test_contract_editor_projection_is_authoritative_state_neutral(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _active(tmp_path)
    receipt = _issue(coordinator)
    before = canonical_bytes(coordinator.store.read())
    monkeypatch.setattr(
        sidecar_module,
        "launch_sidecar_process",
        lambda **_kwargs: {
            "local_only": True,
            "automatic_browser_opened": False,
            "synthetic_test_session": True,
        },
    )
    result = coordinator.open_contract_editor()
    assert result["ok"] is True
    assert canonical_bytes(coordinator.store.read()) == before
    _assert_receipt_valid(coordinator, receipt)


def test_pending_checkpoint_expected_revision_remains_exact_across_pure_reads(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    state = coordinator.store.read()

    def seed_pending_checkpoint(value: dict[str, Any]) -> Mapping[str, Any]:
        value["coordinator"]["pending_checkpoint_input"] = {
            "schema_id": "qcoder.current_loop.checkpoint_input.v1",
            "schema_version": 1,
            "status": "pending",
            "content_digest": "a" * 64,
            "semantic_contract_schema_id": "synthetic-focused-proof",
            "semantic_contract_schema_version": 1,
            "semantic_contract_digest": "b" * 64,
            "operation": "prepare_generation",
            "checkpoint_kind": "intent_review",
            "phase": "activated",
            "expected_state_revision": int(value["state_revision"]) + 1,
            "fields": [],
        }
        return value

    coordinator.store.update(
        seed_pending_checkpoint,
        expected_revision=int(state["state_revision"]),
    )
    receipt = _issue(coordinator)
    issued = coordinator.store.read()
    expected = issued["coordinator"]["pending_checkpoint_input"]["expected_state_revision"]
    assert expected == issued["state_revision"] == receipt["issued_state_revision"]
    before = canonical_bytes(issued)
    for _ in range(25):
        assert coordinator.status()["ok"] is True
        assert coordinator.contract_status()["ok"] is True
    after = coordinator.store.read()
    assert canonical_bytes(after) == before
    assert after["coordinator"]["pending_checkpoint_input"]["expected_state_revision"] == expected
    _assert_receipt_valid(coordinator, receipt)


def test_status_resume_branch_remains_authoritative_mutation(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    receipt = _issue(coordinator)
    candidate = _source_candidate(tmp_path)
    state = coordinator.store.read()
    transaction = prepare_registration_transaction(
        state=state,
        candidates=[candidate],
        workspace_root=tmp_path,
        operation_receipt_id=str(receipt["receipt_id"]),
        authorization_source="operation_receipt",
        enrollment_authority="current_loop_contract_assist",
        collect_permitted_roles=["source"],
        current_time=coordinator.clock(),
    )
    committed = commit_registration_transaction(store=coordinator.store, transaction=transaction)
    assert committed["derivation_required"] is True
    before = coordinator.store.read()
    assert before["registered_pending_derivation"] is not None
    result = coordinator.status()
    after = coordinator.store.read()
    assert result["ok"] is True
    assert result["details"]["pending_derivation_resumed"] is True
    assert after["state_revision"] > before["state_revision"]
    assert after["state_digest"] != before["state_digest"]
    assert after["registered_pending_derivation"] is None


def test_evidence_view_mixed_branch_mutates_only_when_it_resumes_derivation(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    narrowed = coordinator.contract_adjust(
        category="python_manifestation",
        dimension="assistant_derived_exposure",
        value="disabled",
        expected_contract_revision=1,
    )
    assert narrowed["ok"] is True
    assert coordinator.store.read()["current_loop_contract"]["effective_preset"] == "custom"
    receipt = _issue(coordinator)
    candidate = _source_candidate(tmp_path)
    state = coordinator.store.read()
    transaction = prepare_registration_transaction(
        state=state,
        candidates=[candidate],
        workspace_root=tmp_path,
        operation_receipt_id=str(receipt["receipt_id"]),
        authorization_source="operation_receipt",
        enrollment_authority="current_loop_contract_assist",
        collect_permitted_roles=["source"],
        current_time=coordinator.clock(),
    )
    commit_registration_transaction(store=coordinator.store, transaction=transaction)
    before = coordinator.store.read()
    assert before["registered_pending_derivation"] is not None
    projected = coordinator.evidence_view(view_id="current_build_facts")
    after = coordinator.store.read()
    assert projected["ok"] is True
    assert after["registered_pending_derivation"] is None
    assert after["state_revision"] > before["state_revision"]
    stable = canonical_bytes(after)
    assert coordinator.evidence_view(view_id="current_build_facts")["ok"] is True
    assert canonical_bytes(coordinator.store.read()) == stable


def test_atomic_issuance_is_one_commit_bound_to_final_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _active(tmp_path)
    before = coordinator.store.read()
    calls = 0
    original_update = coordinator.store.update

    def counted_update(
        mutator: Callable[[dict[str, Any]], Mapping[str, Any]],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return original_update(mutator, expected_revision=expected_revision)

    monkeypatch.setattr(coordinator.store, "update", counted_update)
    receipt = _issue(coordinator)
    after = coordinator.store.read()
    assert calls == 1
    assert after["state_revision"] == before["state_revision"] + 1
    assert receipt["issued_state_revision"] == after["state_revision"]
    assert after["operation_receipts"][receipt["receipt_id"]] == receipt
    assert coordinator._coordinator_state(after)["phase"] == "awaiting_local_artifacts"
    _assert_receipt_valid(coordinator, receipt)


def test_no_receipt_is_visible_before_commit_and_result_construction_is_nonpersisting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _active(tmp_path)
    original_result = coordinator._result
    observed: dict[str, Any] = {}

    def inspected_result(*args: Any, **kwargs: Any) -> dict[str, Any]:
        state = coordinator.store.read()
        issued = [
            value
            for value in state["operation_receipts"].values()
            if value.get("status") == "issued"
        ]
        observed["revision"] = state["state_revision"]
        observed["issued"] = deepcopy(issued)
        before = canonical_bytes(state)
        result = original_result(*args, **kwargs)
        observed["state_unchanged"] = canonical_bytes(coordinator.store.read()) == before
        return result

    monkeypatch.setattr(coordinator, "_result", inspected_result)
    receipt = _issue(coordinator)
    assert observed["issued"] == [receipt]
    assert observed["revision"] == receipt["issued_state_revision"]
    assert observed["state_unchanged"] is True


@pytest.mark.parametrize("failure_point", ("before_mutator", "after_mutator"))
def test_issuance_commit_fault_leaves_no_partial_or_ghost_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    coordinator = _active(tmp_path)
    before = canonical_bytes(coordinator.store.read())
    original_update = coordinator.store.update
    failed = False

    def interrupted_update(
        mutator: Callable[[dict[str, Any]], Mapping[str, Any]],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        nonlocal failed
        if not failed:
            failed = True
            if failure_point == "after_mutator":
                mutator(deepcopy(coordinator.store.read()))
            raise CurrentLoopConflict("concurrent_state_update")
        return original_update(mutator, expected_revision=expected_revision)

    monkeypatch.setattr(coordinator.store, "update", interrupted_update)
    result = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        output_role_ceiling=["source"],
    )
    assert result["ok"] is False
    assert result["details"]["operation_receipt_returned"] is False
    assert canonical_bytes(coordinator.store.read()) == before
    assert coordinator.store.read()["operation_receipts"] == {}


def test_precommit_receipt_creation_failure_is_retryable_without_duplicate_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _active(tmp_path)
    original_issue = coordinator_module.issue_operation_receipt
    calls = 0

    def fail_once(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise EventReceiptError("operation_receipt_invalid")
        return original_issue(**kwargs)

    monkeypatch.setattr(coordinator_module, "issue_operation_receipt", fail_once)
    failed = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        output_role_ceiling=["source"],
    )
    assert failed["ok"] is False
    assert coordinator.store.read()["operation_receipts"] == {}
    succeeded = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        output_role_ceiling=["source"],
    )
    assert succeeded["ok"] is True
    assert len(coordinator.store.read()["operation_receipts"]) == 1


def test_post_replace_error_reconciles_the_one_fully_committed_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _active(tmp_path)
    before_revision = coordinator.store.read()["state_revision"]
    original_update = coordinator.store.update

    def commit_then_report_error(
        mutator: Callable[[dict[str, Any]], Mapping[str, Any]],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        original_update(mutator, expected_revision=expected_revision)
        raise OSError("synthetic post-replace durability error")

    monkeypatch.setattr(coordinator.store, "update", commit_then_report_error)
    result = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        output_role_ceiling=["source"],
    )
    assert result["ok"] is True
    receipt = result["details"]["operation_receipt"]
    state = coordinator.store.read()
    assert state["state_revision"] == before_revision + 1
    assert receipt == state["operation_receipts"][receipt["receipt_id"]]
    _assert_receipt_valid(coordinator, receipt)


def test_competing_atomic_issuance_has_one_valid_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _active(tmp_path)
    barrier = Barrier(2)
    original_update = coordinator.store.update

    def racing_update(
        mutator: Callable[[dict[str, Any]], Mapping[str, Any]],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        barrier.wait(timeout=5)
        return original_update(mutator, expected_revision=expected_revision)

    monkeypatch.setattr(coordinator.store, "update", racing_update)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: coordinator.record_ide_authority(
                    allowed=True,
                    explicit_user_action=True,
                    output_role_ceiling=["source"],
                ),
                range(2),
            )
        )
    winners = [result for result in results if result["ok"] is True]
    losers = [result for result in results if result["ok"] is False]
    assert len(winners) == len(losers) == 1
    assert losers[0]["category"] == "client_state_conflict"
    receipt = winners[0]["details"]["operation_receipt"]
    assert list(coordinator.store.read()["operation_receipts"]) == [receipt["receipt_id"]]
    _assert_receipt_valid(coordinator, receipt)


def test_concurrent_contract_change_wins_cas_and_is_not_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _active(tmp_path)
    original_update = coordinator.store.update
    injected = False

    def inject_contract_change(
        mutator: Callable[[dict[str, Any]], Mapping[str, Any]],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        nonlocal injected
        if not injected:
            injected = True
            current = coordinator.store.read()
            outcome = adjust(
                current["current_loop_contract"],
                category="python_manifestation",
                dimension="assistant_derived_exposure",
                value="disabled",
                expected_contract_revision=int(
                    current["current_loop_contract"]["contract_revision"]
                ),
                provenance="customer_requested_narrowing",
            )

            def contract_mutation(value: dict[str, Any]) -> Mapping[str, Any]:
                value["current_loop_contract"] = deepcopy(outcome["contract"])
                return value

            original_update(
                contract_mutation,
                expected_revision=int(current["state_revision"]),
            )
        return original_update(mutator, expected_revision=expected_revision)

    monkeypatch.setattr(coordinator.store, "update", inject_contract_change)
    result = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        output_role_ceiling=["source"],
    )
    assert result["ok"] is False
    assert result["category"] == "client_state_conflict"
    state = coordinator.store.read()
    assert state["current_loop_contract"]["contract_revision"] == 2
    assert state["operation_receipts"] == {}


def test_real_binding_changes_invalidate_without_revision_fabrication(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    receipt = _issue(coordinator, roles=("source",))
    state = coordinator.store.read()
    common = {
        "current_state_revision": state["state_revision"],
        "current_contract_revision": state["current_loop_contract"]["contract_revision"],
        "current_time": coordinator.clock(),
    }
    cases = (
        (
            {
                "loop_ref": "loop-" + "f" * 32,
                "workspace_binding": state["workspace_root"],
                "role": "source",
                "detected_format": "python_source",
            },
            "operation_receipt_loop_mismatch",
        ),
        (
            {
                "loop_ref": state["loop_ref"],
                "workspace_binding": "/different/workspace",
                "role": "source",
                "detected_format": "python_source",
            },
            "operation_receipt_workspace_mismatch",
        ),
        (
            {
                "loop_ref": state["loop_ref"],
                "workspace_binding": state["workspace_root"],
                "role": "results",
                "detected_format": "json_results",
            },
            "operation_receipt_role_not_authorized",
        ),
        (
            {
                "loop_ref": state["loop_ref"],
                "workspace_binding": state["workspace_root"],
                "role": "source",
                "detected_format": "openqasm_2",
            },
            "operation_receipt_format_not_authorized",
        ),
    )
    for arguments, category in cases:
        with pytest.raises(EventReceiptError, match=category):
            validate_operation_receipt(receipt, **common, **arguments)
    with pytest.raises(EventReceiptError, match="operation_receipt_contract_stale"):
        validate_operation_receipt(
            receipt,
            loop_ref=str(state["loop_ref"]),
            workspace_binding=str(state["workspace_root"]),
            current_state_revision=int(state["state_revision"]),
            current_contract_revision=int(state["current_loop_contract"]["contract_revision"]) + 1,
            role="source",
            current_time=coordinator.clock(),
        )

    def change_phase_and_checkpoint(value: dict[str, Any]) -> Mapping[str, Any]:
        value["coordinator"]["phase"] = "generation_ready"
        value["coordinator"]["checkpoint_kind"] = "ide_authority"
        value["coordinator"]["state_status"] = "checkpoint_required"
        return value

    changed = coordinator.store.update(
        change_phase_and_checkpoint,
        expected_revision=int(state["state_revision"]),
    )
    with pytest.raises(EventReceiptError, match="operation_receipt_stale"):
        validate_operation_receipt(
            receipt,
            loop_ref=str(changed["loop_ref"]),
            workspace_binding=str(changed["workspace_root"]),
            current_state_revision=int(changed["state_revision"]),
            current_contract_revision=int(changed["current_loop_contract"]["contract_revision"]),
            role="source",
            current_time=coordinator.clock(),
        )

    tampered = deepcopy(receipt)
    tampered["authorized_output_role_ceiling"] = ["source", "results"]
    with pytest.raises(EventReceiptError, match="operation_receipt_digest_mismatch"):
        validate_operation_receipt(
            tampered,
            loop_ref=str(state["loop_ref"]),
            workspace_binding=str(state["workspace_root"]),
            current_state_revision=int(receipt["issued_state_revision"]),
            current_contract_revision=int(receipt["issued_contract_revision"]),
            role="source",
            current_time=coordinator.clock(),
        )


def test_superseded_receipt_replay_is_rejected() -> None:
    from qcoder.current_loop_event_receipts import issue_operation_receipt

    receipt = issue_operation_receipt(
        loop_ref="loop-" + "a" * 32,
        workspace_binding="/workspace",
        state_revision=5,
        contract_revision=1,
        operation_category="ide_write",
        output_role_ceiling=["source"],
        issued_at=100.0,
    )
    superseded = supersede_operation_receipt(
        receipt,
        successor_receipt_id="operation-receipt-successor",
        superseded_state_revision=6,
    )
    with pytest.raises(EventReceiptError, match="operation_receipt_replay_rejected"):
        validate_operation_receipt(
            superseded,
            loop_ref=str(receipt["loop_ref"]),
            workspace_binding=str(receipt["workspace_binding"]),
            current_state_revision=6,
            current_contract_revision=1,
            role="source",
            current_time=101.0,
        )


@pytest.mark.parametrize("material_change", ("contract", "phase", "checkpoint"))
def test_material_authority_change_never_offers_causal_continuation(
    tmp_path: Path,
    material_change: str,
) -> None:
    coordinator = _active(tmp_path)
    receipt = _issue(coordinator)
    current = coordinator.store.read()

    def mutate_authority(value: dict[str, Any]) -> Mapping[str, Any]:
        if material_change == "contract":
            outcome = adjust(
                value["current_loop_contract"],
                category="python_manifestation",
                dimension="assistant_derived_exposure",
                value="disabled",
                expected_contract_revision=int(value["current_loop_contract"]["contract_revision"]),
                provenance="customer_requested_narrowing",
            )
            value["current_loop_contract"] = deepcopy(outcome["contract"])
        elif material_change == "phase":
            value["coordinator"]["phase"] = "generation_ready"
            value["coordinator"]["state_status"] = "checkpoint_required"
            value["coordinator"]["checkpoint_kind"] = "ide_write_or_run"
        else:
            value["coordinator"]["checkpoint_kind"] = "ide_write_or_run"
        return value

    coordinator.store.update(
        mutate_authority,
        expected_revision=int(current["state_revision"]),
    )
    failed = coordinator.register_artifacts(
        candidates=[_source_candidate(tmp_path)],
        operation_receipt_id=str(receipt["receipt_id"]),
    )
    assert failed["ok"] is False
    assert failed["details"]["recovery_contract"]["strategy"] != "causal_continuation"
    assert failed["details"]["recovery_contract"].get("same_already_authorized_action") is not True


def test_loop_closure_and_replacement_invalidate_the_old_receipt(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    receipt = _issue(coordinator)
    closed = coordinator.abandon(explicit_authority=True)
    assert closed["ok"] is True
    replacement = _active(tmp_path)
    replacement_state = replacement.store.read()
    assert replacement_state["loop_ref"] != receipt["loop_ref"]
    with pytest.raises(EventReceiptError, match="operation_receipt_loop_mismatch"):
        validate_operation_receipt(
            receipt,
            loop_ref=str(replacement_state["loop_ref"]),
            workspace_binding=str(replacement_state["workspace_root"]),
            current_state_revision=int(replacement_state["state_revision"]),
            current_contract_revision=int(
                replacement_state["current_loop_contract"]["contract_revision"]
            ),
            role="source",
            current_time=replacement.clock(),
        )
    assert receipt["receipt_id"] not in replacement_state["operation_receipts"]


def _stale_only_recovery(
    tmp_path: Path,
) -> tuple[CurrentLoopCoordinator, dict[str, Any], dict[str, Any], dict[str, Any]]:
    coordinator = _active(tmp_path)
    receipt = _issue(coordinator)
    current = coordinator.store.read()

    def legacy_bookkeeping(value: dict[str, Any]) -> Mapping[str, Any]:
        value["coordinator"]["performance"]["coordinator_calls"] += 1
        return value

    coordinator.store.update(
        legacy_bookkeeping,
        expected_revision=int(current["state_revision"]),
    )
    candidate = _source_candidate(tmp_path)
    failed = coordinator.register_artifacts(
        candidates=[candidate],
        operation_receipt_id=str(receipt["receipt_id"]),
    )
    assert failed["category"] == "operation_receipt_stale"
    return coordinator, receipt, candidate, failed


def test_causal_recovery_continues_same_action_once_without_customer_or_native_approval(
    tmp_path: Path,
) -> None:
    coordinator, receipt, _candidate, failed = _stale_only_recovery(tmp_path)
    envelope = failed["customer_envelope"]
    serialized_customer = json.dumps(
        {
            "customer_interaction": failed["customer_interaction"],
            "customer_envelope": envelope,
        },
        sort_keys=True,
    )
    assert envelope["requires_customer_response"] is False
    assert envelope["interaction_kind"] == "no_customer_interaction_required"
    assert envelope["primary_next_invocation"] is None
    assert envelope["contract_summary_reference"] is None
    assert envelope["machine_block"] == {
        "full_machine_controls_available_in_coordinator_result": True,
    }
    assert "envelope_digest" not in envelope
    assert "interaction_digest" not in failed["customer_interaction"]
    assert "recovery-" not in serialized_customer
    assert str(receipt["receipt_id"]) not in serialized_customer
    assert "structured_argv" not in serialized_customer
    assert "expected_revision" not in serialized_customer
    assert "state_revision" not in serialized_customer
    assert "contract_revision" not in serialized_customer
    assert "controls_digest" not in serialized_customer
    assert "reference_digest" not in serialized_customer
    assert "native" not in serialized_customer.lower()
    assert failed["details"]["recovery_contract"]["native_ide_permission_auto_approved"] is False
    assert failed["details"]["recovery_contract"]["one_continuation_attempt"] is True

    state = coordinator.store.read()
    active = coordinator._coordinator_state(state)["active_recovery"]
    sealed = active["receipt_recovery_context"]["causal_action_binding"]
    assert sealed["operation"] == receipt["operation_category"]
    assert sealed["role_ceiling"] == receipt["authorized_output_role_ceiling"]
    assert sealed["format_ceiling"] == receipt["authorized_output_format_ceiling"]
    assert sealed["requested_destination"] == "active_loop_canonical_evidence_registry"
    assert sealed["artifact_binding"]["artifact_count"] == 1
    assert len(sealed["artifact_binding"]["artifact_set"][0]["content_digest"]) == 64
    assert active["strategy"] == "causal_continuation"
    continued = coordinator.execute_recovery_action(
        recovery_reference=str(active["reference"]),
        action="retry_registration",
        expected_contract_revision=int(state["current_loop_contract"]["contract_revision"]),
    )
    assert continued["ok"] is True
    final = coordinator.store.read()
    assert final["operation_receipts"][receipt["receipt_id"]]["status"] == "consumed"
    assert len(final["operation_receipts"]) == 1
    rebind = continued["details"]["registration_rebind"]
    assert rebind["authority_broadened"] is False
    assert rebind["expiry_extended"] is False
    assert rebind["issued_rebound_persisted_before_registration"] is False
    assert rebind["native_ide_permission_auto_approved"] is False


@pytest.mark.parametrize(
    "material_change",
    (
        "artifact_bytes",
        "artifact_path",
        "artifact_set",
        "role_ceiling",
        "format_ceiling",
        "workspace",
        "destination",
        "operation",
        "execution",
        "exposure",
    ),
)
def test_material_artifact_change_blocks_causal_continuation_and_second_retry(
    tmp_path: Path,
    material_change: str,
) -> None:
    coordinator, receipt, candidate, _failed = _stale_only_recovery(tmp_path)
    state = coordinator.store.read()
    active = coordinator._coordinator_state(state)["active_recovery"]
    path = Path(candidate["path"])
    if material_change == "artifact_bytes":
        path.write_text("VALUE = 2\n", encoding="utf-8")
    elif material_change == "artifact_path":
        path.rename(tmp_path / "moved.py")
    else:

        def mutate_sealed_action(value: dict[str, Any]) -> Mapping[str, Any]:
            recovery = value["coordinator"]["active_recovery"]
            context = recovery["receipt_recovery_context"]
            sealed = context["causal_action_binding"]
            if material_change == "artifact_set":
                second = tmp_path / "results.json"
                second.write_text('{"ok": true}\n', encoding="utf-8")
                context["candidates"].append(
                    {
                        "role": "results",
                        "path": str(second),
                        "provenance": "assistant_created",
                        "explicit_external": False,
                    }
                )
            elif material_change == "role_ceiling":
                sealed["role_ceiling"] = ["source", "results"]
            elif material_change == "format_ceiling":
                sealed["format_ceiling"]["source"] = ["python_source", "openqasm_2"]
            elif material_change == "workspace":
                sealed["workspace_binding"] = "/different/workspace"
            elif material_change == "destination":
                sealed["requested_destination"] = "different_destination"
            elif material_change == "operation":
                sealed["operation"] = "ide_execute"
            elif material_change == "execution":
                sealed["execution_requested"] = True
            elif material_change == "exposure":
                sealed["raw_exposure_requested"] = True
            return value

        coordinator.store.update(
            mutate_sealed_action,
            expected_revision=int(state["state_revision"]),
        )
        state = coordinator.store.read()
    blocked = coordinator.execute_recovery_action(
        recovery_reference=str(active["reference"]),
        action="retry_registration",
        expected_contract_revision=int(state["current_loop_contract"]["contract_revision"]),
    )
    assert blocked["ok"] is False
    assert blocked["category"] == "causal_continuation_blocked"
    assert blocked["details"]["retry_loop_permitted"] is False
    after = coordinator.store.read()
    assert coordinator._coordinator_state(after)["active_recovery"] is None
    assert after["operation_receipts"][receipt["receipt_id"]]["status"] == "issued"
    repeated = coordinator.execute_recovery_action(
        recovery_reference=str(active["reference"]),
        action="retry_registration",
        expected_contract_revision=int(after["current_loop_contract"]["contract_revision"]),
    )
    assert repeated["ok"] is False
    repeated_active = coordinator._coordinator_state(coordinator.store.read())["active_recovery"]
    assert not isinstance(
        repeated_active, Mapping
    ) or "retry_registration" not in repeated_active.get("alternatives", [])


def test_causal_registration_commit_race_blocks_without_ghost_rebound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator, receipt, _candidate, _failed = _stale_only_recovery(tmp_path)
    state = coordinator.store.read()
    active = coordinator._coordinator_state(state)["active_recovery"]
    original_commit = coordinator_module.commit_registration_transaction

    def raced_commit(
        *,
        store: Any,
        transaction: Mapping[str, Any],
        clock: Callable[[], float],
    ) -> dict[str, Any]:
        current = store.read()

        def real_authority_mutation(value: dict[str, Any]) -> Mapping[str, Any]:
            value["coordinator"]["checkpoint_kind"] = "ide_write_or_run"
            value["coordinator"]["state_status"] = "checkpoint_required"
            return value

        store.update(real_authority_mutation, expected_revision=int(current["state_revision"]))
        return original_commit(store=store, transaction=transaction, clock=clock)

    monkeypatch.setattr(coordinator_module, "commit_registration_transaction", raced_commit)
    blocked = coordinator.execute_recovery_action(
        recovery_reference=str(active["reference"]),
        action="retry_registration",
        expected_contract_revision=int(state["current_loop_contract"]["contract_revision"]),
    )
    assert blocked["category"] == "causal_continuation_blocked"
    receipts = coordinator.store.read()["operation_receipts"]
    assert list(receipts) == [receipt["receipt_id"]]
    assert receipts[receipt["receipt_id"]]["status"] == "issued"


def test_competing_consumption_is_single_use_even_for_idempotent_bytes(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    receipt = _issue(coordinator)
    candidate = _source_candidate(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: coordinator.register_artifacts(
                    candidates=[candidate],
                    operation_receipt_id=str(receipt["receipt_id"]),
                ),
                range(2),
            )
        )
    assert sum(result["ok"] is True for result in results) <= 1
    state_after_race = coordinator.store.read()
    assert (
        sum(
            activity.get("operation_receipt_id") == receipt["receipt_id"]
            for activity in state_after_race["activity_receipts"]
        )
        == 1
    )
    replay = coordinator.register_artifacts(
        candidates=[candidate],
        operation_receipt_id=str(receipt["receipt_id"]),
    )
    assert replay["ok"] is False
    assert coordinator.store.read()["operation_receipts"][receipt["receipt_id"]]["status"] == (
        "consumed"
    )


def test_expiry_is_not_extended_by_pure_reads_and_expired_receipt_fails_closed(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    coordinator = _active(tmp_path, clock=clock)
    receipt = _issue(coordinator)
    expires_at = receipt["expires_at"]
    before = canonical_bytes(coordinator.store.read())
    for _ in range(40):
        coordinator.status()
        coordinator.contract_status()
    assert canonical_bytes(coordinator.store.read()) == before
    assert (
        coordinator.store.read()["operation_receipts"][receipt["receipt_id"]]["expires_at"]
        == expires_at
    )
    clock.value = expires_at
    with pytest.raises(EventReceiptError, match="operation_receipt_expired"):
        _assert_receipt_valid(coordinator, receipt)
    rejected = coordinator.register_artifacts(
        candidates=[_source_candidate(tmp_path)],
        operation_receipt_id=str(receipt["receipt_id"]),
    )
    assert rejected["ok"] is False
    assert rejected["category"] == "operation_receipt_expired"
    assert rejected["details"]["recovery_contract"]["strategy"] != "causal_continuation"


def test_historical_a4_fixture_and_corrected_a5_status_detour(tmp_path: Path) -> None:
    baseline = {
        "authority_start_revision": 4,
        "receipt_issued_revision": 4,
        "receipt_commit_revision": 5,
        "coordinator_commit_revision": 6,
        "result_bookkeeping_revision": 7,
        "status_bookkeeping_revision": 8,
        "legacy_revision_tolerance": 3,
    }
    assert baseline["status_bookkeeping_revision"] > (
        baseline["receipt_issued_revision"] + baseline["legacy_revision_tolerance"]
    )

    coordinator = _active(tmp_path)
    receipt = _issue(coordinator)
    after_issuance = coordinator.store.read()
    assert receipt["issued_state_revision"] == after_issuance["state_revision"]
    before_status = canonical_bytes(after_issuance)
    assert coordinator.status()["ok"] is True
    assert canonical_bytes(coordinator.store.read()) == before_status
    registered = coordinator.register_artifacts(
        candidates=[_source_candidate(tmp_path)],
        operation_receipt_id=str(receipt["receipt_id"]),
    )
    assert registered["ok"] is True


def test_binding_v18_delta_preserves_exact_twelve_tool_inventory() -> None:
    descriptor = build_client_binding_descriptor(
        coordinator_prefix=["/runtime/python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v35"
    assert descriptor["schema_version"] == 33
    assert len(EXPECTED_TOOLS) == 12
    assert descriptor["qcoder_domain_tool_count"] == 12
    receipt = event_receipt_snapshot()
    assert receipt["schema_id"] == "qcoder.current_loop.operation_receipt.v6"
    assert receipt["revision_binding"] == "exact_authoritative_revision"
    assert receipt["time_expiry_required"] is True
    recovery = recovery_contract_snapshot()
    assert recovery["schema_id"] == "qcoder.current_loop.recovery.v5"
    assert recovery["retry_registration_causal_continuation"] == {
        "same_action_binding_required": True,
        "one_attempt": True,
        "material_change_blocks": True,
        "second_customer_approval_for_stale_only_receipt": False,
        "native_ide_permission_separate": True,
        "internal_choreography_customer_visible": False,
    }
