from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
from typing import Any, Callable, Mapping

import pytest

import qcoder.current_loop_coordinator as coordinator_module
from qcoder.current_loop import (
    CurrentLoopConflict,
    CurrentLoopError,
    canonical_bytes,
)
from qcoder.current_loop_coordinator import (
    CurrentLoopCoordinator,
    recovery_action_executability_matrix,
)
from qcoder.current_loop_event_receipts import EventReceiptError
from qcoder.current_loop_evidence_processing import hosted_enrichment_status
from qcoder.current_loop_recovery import recovery_contract_snapshot
from qcoder.current_loop_registration import (
    commit_registration_transaction,
    prepare_registration_transaction,
)


class FakeClock:
    def __init__(self, value: float = 100.0):
        self.value = value

    def __call__(self) -> float:
        return self.value


def _active(
    tmp_path: Path,
    *,
    clock: Callable[[], float] | None = None,
) -> CurrentLoopCoordinator:
    coordinator = CurrentLoopCoordinator(
        workspace_root=tmp_path,
        **({"clock": clock} if clock is not None else {}),
    )
    result = coordinator.activate(
        original_request="Use qCoder for this exact bounded build.",
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    assert result["ok"] is True
    return coordinator


def _issue(coordinator: CurrentLoopCoordinator) -> dict[str, Any]:
    result = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        operation_category="ide_write",
        output_role_ceiling=("source",),
    )
    assert result["ok"] is True
    return result["details"]["operation_receipt"]


def _candidate(tmp_path: Path, *, name: str = "program.py") -> dict[str, Any]:
    path = tmp_path / name
    path.write_text("VALUE = 1\n", encoding="utf-8")
    return {
        "role": "source",
        "path": str(path),
        "provenance": "assistant_created",
        "explicit_external": False,
    }


def _prepare(
    coordinator: CurrentLoopCoordinator,
    receipt: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    current_time: float,
) -> dict[str, Any]:
    return prepare_registration_transaction(
        state=coordinator.store.read(),
        candidates=[candidate],
        workspace_root=coordinator.workspace_root,
        operation_receipt_id=str(receipt["receipt_id"]),
        authorization_source="operation_receipt",
        enrollment_authority="current_loop_contract_assist",
        collect_permitted_roles=["source"],
        current_time=current_time,
    )


def _stale_recovery(
    tmp_path: Path,
    *,
    clock: FakeClock | None = None,
) -> tuple[CurrentLoopCoordinator, dict[str, Any], dict[str, Any], dict[str, Any]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    coordinator = _active(tmp_path, clock=clock)
    receipt = _issue(coordinator)
    state = coordinator.store.read()

    def revision_advancing_bookkeeping(value: dict[str, Any]) -> Mapping[str, Any]:
        value["coordinator"]["performance"]["coordinator_calls"] += 1
        return value

    coordinator.store.update(
        revision_advancing_bookkeeping,
        expected_revision=int(state["state_revision"]),
    )
    candidate = _candidate(tmp_path)
    result = coordinator.register_artifacts(
        candidates=[candidate],
        operation_receipt_id=str(receipt["receipt_id"]),
    )
    assert result["category"] == "operation_receipt_stale"
    return coordinator, receipt, candidate, result


def _emitted_actions(result: Mapping[str, Any]) -> list[str]:
    alternatives = result.get("details", {}).get("recovery_contract", {}).get(
        "alternatives", []
    )
    return [
        str(item.get("action")) if isinstance(item, Mapping) else str(item)
        for item in alternatives
    ]


def test_complete_runtime_recovery_matrix_drives_emission_and_snapshot(tmp_path: Path) -> None:
    matrix = recovery_action_executability_matrix()
    assert matrix
    keys = {(row["category"], row["variant"], row["strategy"]) for row in matrix}
    assert len(keys) == len(matrix)
    assert recovery_contract_snapshot()["every_advertised_action_executable"] is all(
        action["executable_in_advertised_state"] is True
        and isinstance(action["handler"], str)
        and bool(action["handler"])
        for row in matrix
        for action in row["actions"]
    )

    checked = 0
    for index, row in enumerate(matrix):
        if row["variant"] == "unchanged_stale_receipt":
            continue
        if row["variant"] == "nonblocking_circuit_processing":
            continue
        workspace = tmp_path / f"matrix-{index}"
        workspace.mkdir()
        coordinator = _active(workspace)
        result = coordinator._recovery_result(
            operation="matrix_proof",
            category=str(row["category"]),
            phase="activated",
            elapsed=0.0,
            origin=(
                "hosted_transport"
                if row["variant"] == "hosted_failure"
                else "contract_or_authority"
            ),
            deterministic=row["variant"] != "hosted_failure",
            protected_call_attempted=row["variant"] == "hosted_failure",
            protected_non_success=(
                row["variant"] == "hosted_failure"
                and row["category"] == "protected_operation_rejected"
            ),
        )
        assert _emitted_actions(result) == row["advertised_alternatives"]
        active = coordinator._coordinator_state(coordinator.store.read()).get(
            "active_recovery"
        )
        if row["advertised_alternatives"]:
            assert isinstance(active, Mapping), row
            assert active["alternatives"] == row["advertised_alternatives"]
        else:
            assert active is None
        checked += 1
    assert checked >= 80


def test_retry_registration_is_exclusive_to_executable_stale_only_state(tmp_path: Path) -> None:
    excluded = {
        "operation_receipt_invalid",
        "operation_receipt_expired",
        "operation_receipt_contract_stale",
        "operation_receipt_role_not_authorized",
        "operation_receipt_format_not_authorized",
        "artifact_candidate_path_invalid",
        "selected_file_stale",
        "artifact_candidate_provenance_conflict",
        "operation_receipt_workspace_mismatch",
        "operation_receipt_loop_mismatch",
    }
    for index, category in enumerate(sorted(excluded)):
        workspace = tmp_path / f"excluded-{index}"
        workspace.mkdir()
        coordinator = _active(workspace)
        result = coordinator._recovery_result(
            operation="registration_failure",
            category=category,
            phase="activated",
            elapsed=0.0,
        )
        assert "retry_registration" not in _emitted_actions(result)

    coordinator, _receipt, _candidate_value, result = _stale_recovery(
        tmp_path / "eligible"
    )
    assert "retry_registration" in _emitted_actions(result)
    active = coordinator._coordinator_state(coordinator.store.read())["active_recovery"]
    assert active["category"] == "operation_receipt_stale"
    assert active["strategy"] == "causal_continuation"


def test_every_distinct_advertised_handler_executes_in_real_isolated_state(
    tmp_path: Path,
) -> None:
    matrix = recovery_action_executability_matrix()
    advertised = {
        action
        for row in matrix
        for action in row["advertised_alternatives"]
    }
    proved: set[str] = set()

    for action, category in {
        "continue_with_limitations": "circuit_format_unsupported",
        "provide_supported_circuit_artifact": "circuit_format_unsupported",
        "skip_current_artifact_derivation": "circuit_format_unsupported",
        "return_to_iteration_ready": "governing_blueprint_unavailable",
        "abandon_step": "unknown_local_internal",
    }.items():
        workspace = tmp_path / action
        workspace.mkdir()
        coordinator = _active(workspace)
        if action == "return_to_iteration_ready":
            state = coordinator.store.read()

            def enter_iteration(value: dict[str, Any]) -> Mapping[str, Any]:
                value["coordinator"]["phase"] = "evidence_processing"
                return value

            coordinator.store.update(
                enter_iteration,
                expected_revision=int(state["state_revision"]),
            )
        result = coordinator._recovery_result(
            operation="handler_proof",
            category=category,
            phase="activated",
            elapsed=0.0,
            alternatives=(action, "stop_loop"),
        )
        active = coordinator._coordinator_state(coordinator.store.read())["active_recovery"]
        assert action in _emitted_actions(result)
        executed = coordinator.execute_recovery_action(
            recovery_reference=str(active["reference"]),
            action=action,
            expected_contract_revision=int(
                coordinator.store.read()["current_loop_contract"]["contract_revision"]
            ),
        )
        assert executed["ok"] is True, executed
        proved.add(action)

    stop_workspace = tmp_path / "stop"
    stop_workspace.mkdir()
    stop = _active(stop_workspace)
    stop._recovery_result(
        operation="handler_proof",
        category="unknown_local_internal",
        phase="activated",
        elapsed=0.0,
    )
    stopped = stop.abandon(explicit_authority=True)
    assert stopped["ok"] is True
    assert not stop.store.state_path.exists()
    proved.add("stop_loop")

    stale_workspace = tmp_path / "retry-registration"
    stale_workspace.mkdir()
    stale, _receipt, _candidate_value, _result = _stale_recovery(stale_workspace)
    active = stale._coordinator_state(stale.store.read())["active_recovery"]
    continued = stale.execute_recovery_action(
        recovery_reference=str(active["reference"]),
        action="retry_registration",
        expected_contract_revision=int(
            stale.store.read()["current_loop_contract"]["contract_revision"]
        ),
    )
    assert continued["ok"] is True
    proved.add("retry_registration")

    for action in ("retry_hosted_enrichment", "skip_hosted_enrichment"):
        workspace = tmp_path / action
        workspace.mkdir()
        hosted = _active(workspace)
        state = hosted.store.read()

        def ready_for_hosted(value: dict[str, Any]) -> Mapping[str, Any]:
            value["coordinator"]["phase"] = "evidence_processing"
            value["coordinator"]["state_status"] = "ready"
            value["coordinator"]["checkpoint_kind"] = "none"
            value["coordinator"]["evidence_processing_complete"] = True
            value["hosted_enrichment"] = hosted_enrichment_status("available")
            return value

        hosted.store.update(
            ready_for_hosted,
            expected_revision=int(state["state_revision"]),
        )
        advertised_result = hosted.enrich_authorized_evidence()
        assert action in _emitted_actions(advertised_result)
        if action == "retry_hosted_enrichment":
            retried = hosted.enrich_authorized_evidence()
            assert retried["ok"] is False
            assert retried["category"] == "protected_service_unavailable"
        else:
            active = hosted._coordinator_state(hosted.store.read())["active_recovery"]
            skipped = hosted.execute_recovery_action(
                recovery_reference=str(active["reference"]),
                action=action,
                expected_contract_revision=int(
                    hosted.store.read()["current_loop_contract"]["contract_revision"]
                ),
            )
            assert skipped["ok"] is True
        proved.add(action)

    assert advertised <= proved


def test_normal_receipt_expiry_is_rechecked_inside_registration_cas(tmp_path: Path) -> None:
    clock = FakeClock()
    coordinator = _active(tmp_path, clock=clock)
    receipt = _issue(coordinator)
    transaction = _prepare(
        coordinator,
        receipt,
        _candidate(tmp_path),
        current_time=clock(),
    )
    before = canonical_bytes(coordinator.store.read())
    clock.value = float(receipt["expires_at"])
    with pytest.raises(EventReceiptError, match="operation_receipt_expired"):
        commit_registration_transaction(
            store=coordinator.store,
            transaction=transaction,
            clock=clock,
        )
    after = coordinator.store.read()
    assert canonical_bytes(after) == before
    assert after["operation_receipts"][receipt["receipt_id"]]["status"] == "issued"
    assert after["activity_receipts"] == []
    assert after["evidence_registry"]["artifact_revisions"] == {}


def test_receipt_valid_immediately_before_expiry_commits(tmp_path: Path) -> None:
    clock = FakeClock()
    coordinator = _active(tmp_path, clock=clock)
    receipt = _issue(coordinator)
    transaction = _prepare(
        coordinator,
        receipt,
        _candidate(tmp_path),
        current_time=clock(),
    )
    clock.value = math.nextafter(float(receipt["expires_at"]), -math.inf)
    result = commit_registration_transaction(
        store=coordinator.store,
        transaction=transaction,
        clock=clock,
    )
    assert result["committed"] is True
    assert result["activity_receipt"]["activity_status"] == (
        "successful_canonical_registration"
    )


@pytest.mark.parametrize(
    ("invalid_time", "category"),
    (
        (99.0, "operation_receipt_clock_invalid"),
        (float("nan"), "operation_receipt_expiry_invalid"),
        (float("inf"), "operation_receipt_expiry_invalid"),
    ),
)
def test_commit_clock_inversion_and_invalid_values_fail_closed(
    tmp_path: Path,
    invalid_time: float,
    category: str,
) -> None:
    clock = FakeClock()
    coordinator = _active(tmp_path, clock=clock)
    receipt = _issue(coordinator)
    transaction = _prepare(
        coordinator,
        receipt,
        _candidate(tmp_path),
        current_time=clock(),
    )
    before = canonical_bytes(coordinator.store.read())
    clock.value = invalid_time
    with pytest.raises(EventReceiptError, match=category):
        commit_registration_transaction(
            store=coordinator.store,
            transaction=transaction,
            clock=clock,
        )
    assert canonical_bytes(coordinator.store.read()) == before


def test_expiry_while_waiting_behind_competing_cas_attempt_fails_at_commit(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    coordinator = _active(tmp_path, clock=clock)
    receipt = _issue(coordinator)
    transaction = _prepare(
        coordinator,
        receipt,
        _candidate(tmp_path),
        current_time=clock(),
    )
    before = canonical_bytes(coordinator.store.read())
    entered = Event()
    release = Event()

    def blocking_failed_mutation(value: dict[str, Any]) -> Mapping[str, Any]:
        entered.set()
        assert release.wait(timeout=2.0)
        raise CurrentLoopError("injected_competing_cas_abort")

    with ThreadPoolExecutor(max_workers=2) as executor:
        blocker = executor.submit(
            coordinator.store.update,
            blocking_failed_mutation,
            expected_revision=int(transaction["expected_state_revision"]),
        )
        assert entered.wait(timeout=2.0)
        commit = executor.submit(
            commit_registration_transaction,
            store=coordinator.store,
            transaction=transaction,
            clock=clock,
        )
        clock.value = float(receipt["expires_at"])
        release.set()
        with pytest.raises(CurrentLoopError, match="injected_competing_cas_abort"):
            blocker.result(timeout=3.0)
        with pytest.raises(EventReceiptError, match="operation_receipt_expired"):
            commit.result(timeout=3.0)
    assert canonical_bytes(coordinator.store.read()) == before


def test_causal_continuation_expiry_is_rechecked_inside_canonical_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    coordinator, receipt, _candidate_value, _result = _stale_recovery(
        tmp_path,
        clock=clock,
    )
    active = coordinator._coordinator_state(coordinator.store.read())["active_recovery"]
    original_commit = coordinator_module.commit_registration_transaction

    def expire_at_commit(
        *,
        store: Any,
        transaction: Mapping[str, Any],
        clock: Callable[[], float],
    ) -> dict[str, Any]:
        assert transaction.get("causal_receipt_rebind") is not None
        coordinator.clock.value = float(receipt["expires_at"])
        return original_commit(store=store, transaction=transaction, clock=clock)

    monkeypatch.setattr(
        coordinator_module,
        "commit_registration_transaction",
        expire_at_commit,
    )
    blocked = coordinator.execute_recovery_action(
        recovery_reference=str(active["reference"]),
        action="retry_registration",
        expected_contract_revision=int(
            coordinator.store.read()["current_loop_contract"]["contract_revision"]
        ),
    )
    assert blocked["ok"] is False
    assert blocked["category"] == "causal_continuation_blocked"
    assert blocked["details"]["one_continuation_attempt_exhausted"] is True
    state = coordinator.store.read()
    assert state["operation_receipts"][receipt["receipt_id"]]["status"] == "issued"
    assert state["operation_receipts"][receipt["receipt_id"]]["expires_at"] == (
        receipt["expires_at"]
    )
    assert state["activity_receipts"] == []
    assert state["evidence_registry"]["artifact_revisions"] == {}


def _inject_recovery_schema(
    coordinator: CurrentLoopCoordinator,
    *,
    schema_id: str,
    schema_version: int,
    remove_field: str | None = None,
) -> dict[str, Any]:
    state = coordinator.store.read()

    def mutate(value: dict[str, Any]) -> Mapping[str, Any]:
        active = value["coordinator"]["active_recovery"]
        active["schema_id"] = schema_id
        active["schema_version"] = schema_version
        if remove_field is not None:
            active.pop(remove_field, None)
        return value

    coordinator.store.update(mutate, expected_revision=int(state["state_revision"]))
    return coordinator._coordinator_state(coordinator.store.read())["active_recovery"]


def test_legacy_v4_retry_registration_fails_schema_gate_without_mutation(
    tmp_path: Path,
) -> None:
    coordinator, _receipt, _candidate_value, _result = _stale_recovery(tmp_path)
    active = _inject_recovery_schema(
        coordinator,
        schema_id="qcoder.current_loop.recovery.v4",
        schema_version=4,
    )
    before = canonical_bytes(coordinator.store.read())
    rejected = coordinator.execute_recovery_action(
        recovery_reference=str(active["reference"]),
        action="retry_registration",
        expected_contract_revision=int(
            coordinator.store.read()["current_loop_contract"]["contract_revision"]
        ),
    )
    assert rejected["category"] == "unsupported_recovery_schema"
    assert rejected["details"]["recovery_action_executed"] is False
    assert canonical_bytes(coordinator.store.read()) == before


@pytest.mark.parametrize(
    ("action", "schema_id", "schema_version", "remove_field"),
    (
        ("stop_loop", "qcoder.current_loop.recovery.v4", 4, None),
        ("abandon_step", "qcoder.current_loop.recovery.v4", 4, None),
        ("abandon_step", "malformed.recovery", 5, None),
        ("abandon_step", "qcoder.current_loop.recovery.v5", 6, None),
        ("abandon_step", "qcoder.current_loop.recovery.v5", 5, "fingerprint"),
    ),
)
def test_all_recovery_action_paths_gate_unsupported_or_malformed_schema(
    tmp_path: Path,
    action: str,
    schema_id: str,
    schema_version: int,
    remove_field: str | None,
) -> None:
    coordinator = _active(tmp_path)
    coordinator._recovery_result(
        operation="schema_gate_proof",
        category="unknown_local_internal",
        phase="activated",
        elapsed=0.0,
    )
    active = _inject_recovery_schema(
        coordinator,
        schema_id=schema_id,
        schema_version=schema_version,
        remove_field=remove_field,
    )
    before = canonical_bytes(coordinator.store.read())
    if action == "stop_loop":
        rejected = coordinator.abandon(explicit_authority=True)
    else:
        rejected = coordinator.execute_recovery_action(
            recovery_reference=str(active["reference"]),
            action=action,
            expected_contract_revision=int(
                coordinator.store.read()["current_loop_contract"]["contract_revision"]
            ),
        )
    assert rejected["category"] == "unsupported_recovery_schema"
    assert rejected["details"]["legacy_authority_reinterpreted"] is False
    assert canonical_bytes(coordinator.store.read()) == before


def test_supported_v5_recovery_action_still_executes(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    coordinator._recovery_result(
        operation="schema_gate_proof",
        category="unknown_local_internal",
        phase="activated",
        elapsed=0.0,
    )
    state = coordinator.store.read()
    active = coordinator._coordinator_state(state)["active_recovery"]
    executed = coordinator.execute_recovery_action(
        recovery_reference=str(active["reference"]),
        action="abandon_step",
        expected_contract_revision=int(state["current_loop_contract"]["contract_revision"]),
    )
    assert executed["ok"] is True
    assert coordinator._coordinator_state(coordinator.store.read())["active_recovery"] is None


def test_lost_attempt_marker_cas_reports_no_continuation_attempt_consumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator, receipt, _candidate_value, _result = _stale_recovery(tmp_path)
    state = coordinator.store.read()
    active = coordinator._coordinator_state(state)["active_recovery"]
    original_update = coordinator.store.update
    lost = False

    def lose_marker_once(
        mutator: Callable[[dict[str, Any]], Mapping[str, Any]],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        nonlocal lost
        if not lost and getattr(mutator, "__name__", "") == "mark_continuation_attempt":
            lost = True
            raise CurrentLoopConflict("concurrent_state_update")
        return original_update(mutator, expected_revision=expected_revision)

    monkeypatch.setattr(coordinator.store, "update", lose_marker_once)
    blocked = coordinator.execute_recovery_action(
        recovery_reference=str(active["reference"]),
        action="retry_registration",
        expected_contract_revision=int(state["current_loop_contract"]["contract_revision"]),
    )
    assert blocked["category"] == "causal_continuation_blocked"
    assert blocked["details"]["one_continuation_attempt_exhausted"] is False
    assert blocked["details"]["continuation_attempt_consumed"] is False
    assert blocked["details"]["retry_loop_permitted"] is False
    assert coordinator.store.read()["operation_receipts"][receipt["receipt_id"]][
        "status"
    ] == "issued"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux source proof")
def test_linux_monotonic_clock_and_receipt_are_cross_process_compatible() -> None:
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    source_path = str(root / "src")
    environment["PYTHONPATH"] = (
        source_path
        if not environment.get("PYTHONPATH")
        else source_path + os.pathsep + environment["PYTHONPATH"]
    )
    issued = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json,time; "
                "from qcoder.current_loop_event_receipts import issue_operation_receipt; "
                "sample=time.monotonic(); "
                "receipt=issue_operation_receipt(loop_ref='loop-'+'a'*32, "
                "workspace_binding='/bounded/workspace', state_revision=7, "
                "contract_revision=3, operation_category='ide_write', "
                "output_role_ceiling=['source'], issued_at=sample); "
                "print(json.dumps({'sample':sample,'receipt':receipt},sort_keys=True))"
            ),
        ],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    first = json.loads(issued.stdout)
    validated = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json,sys,time; "
                "from qcoder.current_loop_event_receipts import "
                "EventReceiptError,validate_operation_receipt; "
                "payload=json.load(sys.stdin); receipt=payload['receipt']; now=time.monotonic(); "
                "validate_operation_receipt(receipt,loop_ref=receipt['loop_ref'], "
                "workspace_binding=receipt['workspace_binding'],current_state_revision=7, "
                "current_contract_revision=3,role='source',detected_format='python_source', "
                "current_time=now); inverted=None; "
                "\ntry: validate_operation_receipt(receipt,loop_ref=receipt['loop_ref'], "
                "workspace_binding=receipt['workspace_binding'],current_state_revision=7, "
                "current_contract_revision=3,role='source',detected_format='python_source', "
                "current_time=receipt['issued_at']-1.0)\n"
                "except EventReceiptError as exc: inverted=exc.category\n"
                "print(json.dumps({'sample':now,'validated':True,'inverted':inverted},sort_keys=True))"
            ),
        ],
        cwd=root,
        env=environment,
        check=True,
        input=json.dumps(first),
        capture_output=True,
        text=True,
    )
    second = json.loads(validated.stdout)
    assert second["sample"] >= first["sample"]
    assert second["validated"] is True
    assert second["inverted"] == "operation_receipt_clock_invalid"
