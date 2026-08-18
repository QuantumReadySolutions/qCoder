from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
import time
from typing import Any

import pytest

import qcoder.current_loop_derivation as derivation_module
from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    EXPECTED_TOOLS,
    build_client_binding_descriptor,
)
from qcoder.current_loop import (
    CURRENT_LOOP_STATE_MAX_BYTES,
    CURRENT_LOOP_STATE_SCHEMA_ID,
    CurrentLoopError,
    _state_digest,
    canonical_bytes,
    migrate_current_loop_state,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_contract_management import (
    customer_contract_document,
    reset_customer_contract_document,
)
from qcoder.current_loop_contract_sidecar import SidecarSession
from qcoder.current_loop_derivation import (
    derive_pending_snapshot,
    promote_derivation_snapshot,
)
from qcoder.current_loop_freshness import run_summary_status
from qcoder.current_loop_registration import (
    LOGICAL_ROLES,
    commit_registration_transaction,
    prepare_registration_transaction,
)
from qcoder.current_loop_run_summary import (
    RUN_SUMMARY_SCHEMA_ID,
    RunSummaryError,
    validate_run_summary_snapshot_binding,
)
from qcoder.current_loop_vocabulary import vocabulary_snapshot
from tests.current_loop_test_support import activate_reviewed_legacy_fixture

REQUEST = "Use qCoder for this build context with the established evidence-revision contract."


def _fields() -> dict[str, dict[str, Any]]:
    return {
        "profile_id": {
            "value": "generic_qiskit",
            "provenance": "qcoder_classified",
            "material": False,
        },
        "qubits": {"value": 2, "provenance": "user_stated", "material": False},
        "simulator": {
            "value": "local simulator",
            "provenance": "user_stated",
            "material": False,
        },
        "shots": {"value": 1024, "provenance": "user_stated", "material": False},
        "measurement": {
            "value": "both qubits",
            "provenance": "derived",
            "material": False,
        },
        "output": {
            "value": "counts",
            "provenance": "user_stated",
            "material": False,
        },
    }


def _coordinator(workspace: Path) -> CurrentLoopCoordinator:
    coordinator = CurrentLoopCoordinator(workspace_root=workspace)
    activated = activate_reviewed_legacy_fixture(
        coordinator,
        original_request=REQUEST,
    )
    assert activated["ok"] is True
    assert coordinator.prepare_adaptive_intent(fields=_fields())["ok"] is True
    return coordinator


def _write_iteration(
    workspace: Path,
    *,
    iteration: int,
    alternate_source_path: bool = False,
) -> list[dict[str, Any]]:
    source = workspace / ("alternate.py" if alternate_source_path else "bell.py")
    qasm = workspace / "bell.qasm"
    result = workspace / "results.json"
    psi = iteration == 2
    source.write_text(
        "from qiskit import QuantumCircuit\n"
        f"TARGET = {'psi_plus' if psi else 'phi_plus'}\n"
        "circuit = QuantumCircuit(2, 2)\n",
        encoding="utf-8",
    )
    qasm.write_text(
        'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\n'
        + ("x q[0];\n" if psi else "")
        + "h q[0];\ncx q[0],q[1];\nmeasure q -> c;\n",
        encoding="utf-8",
    )
    counts = {"01": 492, "10": 532} if psi else {"00": 500 + iteration, "11": 524 - iteration}
    result.write_text(
        json.dumps(
            {"counts": counts, "shots": 1024, "backend": "AerSimulator"},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    disposition = "assistant_created" if iteration == 1 else "assistant_modified"
    return [
        {
            "path": str(source),
            "role": "source",
            "artifact_type": "source",
            "provenance": disposition,
        },
        {
            "path": str(qasm),
            "role": "circuit_qasm",
            "artifact_type": "circuit_qasm",
            "provenance": disposition,
        },
        {
            "path": str(result),
            "role": "results",
            "artifact_type": "results",
            "provenance": disposition,
        },
    ]


def _authorize(
    coordinator: CurrentLoopCoordinator,
    *,
    iteration: int,
    roles: tuple[str, ...] = ("source", "circuit_qasm", "results"),
) -> Mapping[str, Any]:
    return coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        operation_category="ide_execute",
        output_role_ceiling=roles,
        exact_iteration_instruction=(
            None if iteration == 1 else f"Modify and run iteration {iteration}."
        ),
    )


def _run_iteration(
    coordinator: CurrentLoopCoordinator,
    candidates: list[dict[str, Any]],
    *,
    iteration: int,
) -> Mapping[str, Any]:
    authority = _authorize(coordinator, iteration=iteration)
    assert authority["ok"] is True
    receipt = authority["details"]["operation_receipt"]
    result = coordinator.register_artifacts(
        candidates=candidates,
        operation_receipt_id=receipt["receipt_id"],
    )
    assert result["ok"] is True
    return result


def _read_summary(state: Mapping[str, Any], reference: str) -> dict[str, Any]:
    descriptor = state["run_summary_index"][reference]
    return json.loads(Path(descriptor["local_path"]).read_text(encoding="utf-8"))


def test_canonical_vocabulary_binding_and_state_v9_are_identical(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    binding = build_client_binding_descriptor(
        coordinator_prefix=["python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    vocabulary = vocabulary_snapshot()
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v29"
    assert binding["canonical_current_loop_vocabulary"] == vocabulary
    assert (
        binding["contract_sidecar"]["accepted_domains"]["canonical_evidence_vocabulary"]
        == vocabulary
    )
    assert coordinator.store.read()["schema_id"] == CURRENT_LOOP_STATE_SCHEMA_ID
    assert len(EXPECTED_TOOLS) == 12
    assert vocabulary["persisted_bare_provenance_field_permitted"] is False


def test_three_same_path_iterations_create_coherent_snapshots(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    for iteration in (1, 2, 3):
        result = _run_iteration(
            coordinator,
            _write_iteration(tmp_path, iteration=iteration),
            iteration=iteration,
        )
        assert result["details"]["artifact_review_conversation_required"] is False
        assert result["customer_interaction"]["requires_customer_response"] is False
    state = coordinator.store.read()
    registry = state["evidence_registry"]
    assert len(registry["snapshots"]) == 3
    assert len(state["run_summary_index"]) == 3
    assert state["registered_pending_derivation"] is None
    events = registry["registration_events"]
    by_revision = [
        event["event_disposition"] for event in events if event["logical_role"] == "results"
    ]
    assert by_revision == ["created", "modified", "modified"]
    currencies = [descriptor["currency"] for descriptor in state["run_summary_index"].values()]
    assert currencies.count("current") == 1
    assert currencies.count("superseded") == 2
    for snapshot in registry["snapshots"].values():
        summary = _read_summary(state, snapshot["run_summary_reference"])
        assert summary["schema_id"] == RUN_SUMMARY_SCHEMA_ID
        assert validate_run_summary_snapshot_binding(summary, snapshot) is None
    current_reference = state["latest_run_summary_reference"]
    computed = run_summary_status(state, summary_reference=current_reference)
    assert computed["is_current_run_summary"] is True
    assert len(canonical_bytes(state)) <= CURRENT_LOOP_STATE_MAX_BYTES


def test_same_role_new_path_moves_head_without_discovery(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    _run_iteration(
        coordinator,
        _write_iteration(tmp_path, iteration=1),
        iteration=1,
    )
    before = coordinator.store.read()["evidence_registry"]["role_heads"]["source"]
    _run_iteration(
        coordinator,
        _write_iteration(tmp_path, iteration=2, alternate_source_path=True),
        iteration=2,
    )
    state = coordinator.store.read()
    after = state["evidence_registry"]["role_heads"]["source"]
    assert before != after
    revision = state["evidence_registry"]["artifact_revisions"][after]
    assert Path(revision["exact_path"]).name == "alternate.py"
    assert revision["event_disposition"] == "created"
    assert state["directory_scan_performed"] is False
    assert state["watcher_active"] is False


def test_registration_failure_has_receipt_escrow_and_no_success_effects(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    candidates = _write_iteration(tmp_path, iteration=1)
    qasm = tmp_path / "bell.qasm"
    qasm.write_text("OPENQASM 3.0;\nqubit[2] q;\n", encoding="utf-8")
    authority = _authorize(coordinator, iteration=1)
    receipt_id = authority["details"]["operation_receipt"]["receipt_id"]
    before = coordinator.store.read()
    result = coordinator.register_artifacts(
        candidates=candidates,
        operation_receipt_id=receipt_id,
    )
    after = coordinator.store.read()
    assert result["ok"] is False
    assert result["category"] == "artifact_format_unsupported"
    assert after["operation_receipts"][receipt_id]["status"] == "issued"
    assert after["activity_receipts"] == before["activity_receipts"]
    assert after["evidence_registry"]["role_heads"] == before["evidence_registry"]["role_heads"]
    assert after["registered_pending_derivation"] is None
    alternatives = result["details"]["recovery_contract"]["alternatives"]
    assert alternatives
    assert all(item["invocation"]["structured_argv"] for item in alternatives)


def test_interruption_after_registration_resumes_without_new_receipt(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    candidates = _write_iteration(tmp_path, iteration=1)
    authority = _authorize(coordinator, iteration=1)
    receipt_id = authority["details"]["operation_receipt"]["receipt_id"]
    state = coordinator.store.read()
    transaction = prepare_registration_transaction(
        state=state,
        candidates=candidates,
        workspace_root=tmp_path,
        operation_receipt_id=receipt_id,
        authorization_source="operation_receipt",
        enrollment_authority="current_loop_contract_assist",
        collect_permitted_roles=LOGICAL_ROLES,
    )
    commit = commit_registration_transaction(
        store=coordinator.store,
        transaction=transaction,
    )
    interrupted = coordinator.store.read()
    assert (
        interrupted["registered_pending_derivation"]["snapshot_id"] == commit["pending_snapshot_id"]
    )
    receipt_count = len(interrupted["operation_receipts"])
    resumed = CurrentLoopCoordinator(workspace_root=tmp_path).status()
    final = coordinator.store.read()
    assert resumed["ok"] is True
    assert resumed["details"]["pending_derivation_resumed"] is True
    assert resumed["details"]["registration_repeated"] is False
    assert len(final["operation_receipts"]) == receipt_count
    assert final["operation_receipts"][receipt_id]["status"] == "consumed"
    assert final["registered_pending_derivation"] is None


def test_one_failed_revision_promotes_partial_snapshot_and_summary(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    candidates = _write_iteration(tmp_path, iteration=1)
    authority = _authorize(coordinator, iteration=1)
    receipt_id = authority["details"]["operation_receipt"]["receipt_id"]
    state = coordinator.store.read()
    transaction = prepare_registration_transaction(
        state=state,
        candidates=candidates,
        workspace_root=tmp_path,
        operation_receipt_id=receipt_id,
        authorization_source="operation_receipt",
        enrollment_authority="current_loop_contract_assist",
        collect_permitted_roles=LOGICAL_ROLES,
    )
    commit_registration_transaction(store=coordinator.store, transaction=transaction)
    (tmp_path / "bell.qasm").write_text("OPENQASM 3.0;\nqubit[2] q;\n", encoding="utf-8")
    registered = coordinator.store.read()
    derivation = derive_pending_snapshot(
        state=registered,
        artifact_directory=coordinator.artifact_directory,
    )
    result = promote_derivation_snapshot(
        store=coordinator.store,
        derivation=derivation,
        artifact_directory=coordinator.artifact_directory,
    )
    assert result["snapshot_status"] == "partial"
    assert result["run_summary_reference"] is not None
    statuses = {
        outcome["role"]: outcome["status"] for outcome in result["processing_outcomes"].values()
    }
    assert statuses["source"] == "completed"
    assert statuses["results"] == "completed"
    assert statuses["circuit_qasm"] == "failed_local"


def test_v8_migration_and_inconsistent_migration_fail_closed(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    store = coordinator.store
    current = store.read()
    old = deepcopy(current)
    old["schema_id"] = "qcoder.current_loop.local_state.v8"
    old["schema_version"] = 8
    old.pop("evidence_registry")
    old.pop("registered_pending_derivation")
    old.pop("current_evidence_status")
    old["state_digest"] = _state_digest(old)
    store.replace(old, expected_revision=current["state_revision"])
    migrated = migrate_current_loop_state(store)
    assert migrated["schema_id"] == "qcoder.current_loop.local_state.v9"
    assert migrated["evidence_registry"]["role_heads"] == {}

    broken = deepcopy(migrated)
    broken["schema_id"] = "qcoder.current_loop.local_state.v8"
    broken["schema_version"] = 8
    broken.pop("evidence_registry")
    broken.pop("registered_pending_derivation")
    broken.pop("current_evidence_status")
    broken["saved_artifacts"]["result_manifestation"] = {
        "artifact_reference": "session-artifact-" + "a" * 32,
        "artifact_digest": "b" * 64,
        "file_digest": "c" * 64,
        "local_path": str(tmp_path / ".qcoder" / "current-loop" / "missing.json"),
        "status": "fresh",
    }
    broken["state_digest"] = _state_digest(broken)
    broken = store.replace(broken, expected_revision=migrated["state_revision"])
    with pytest.raises(
        CurrentLoopError,
        match="current_loop_state_migration_requires_fresh_loop",
    ):
        migrate_current_loop_state(store)
    preserved = (
        tmp_path
        / ".qcoder"
        / "current-loop"
        / f"state.v8-preserved-{broken['state_digest'][:16]}.json"
    )
    assert preserved.is_file()


def test_loop_close_purges_qcoder_evidence_and_preserves_project_files(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    candidates = _write_iteration(tmp_path, iteration=1)
    _run_iteration(coordinator, candidates, iteration=1)
    state = coordinator.store.read()
    qcoder_paths = {
        Path(descriptor["local_path"])
        for snapshot in state["evidence_registry"]["snapshots"].values()
        for descriptor in snapshot["manifestation_revision_set"].values()
    }
    qcoder_paths.update(
        Path(descriptor["local_path"]) for descriptor in state["run_summary_index"].values()
    )
    result = coordinator.complete_instruction(
        exact_instruction=(
            "Finish this qCoder loop without hosted enrichment, Build Review, "
            "Blueprint changes, or a new loop."
        ),
        stop_loop=True,
    )
    assert result["ok"] is True
    assert result["details"]["loop_close_cleanup"]["future_loop_evidence_retained"] is False
    assert all(not path.exists() for path in qcoder_paths)
    assert all(Path(item["path"]).exists() for item in candidates)
    with pytest.raises(CurrentLoopError, match="current_loop_not_active"):
        coordinator.store.read()


def test_retention_keeps_at_least_two_iterations_inside_state_budget(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    for iteration in range(1, 11):
        candidates = _write_iteration(tmp_path, iteration=iteration)
        candidates[0]["path"] = str(tmp_path / "bell.py")
        _run_iteration(coordinator, candidates, iteration=iteration)
    state = coordinator.store.read()
    registry = state["evidence_registry"]
    by_role = {
        role: [
            revision
            for revision in registry["artifact_revisions"].values()
            if revision["logical_role"] == role
        ]
        for role in LOGICAL_ROLES
    }
    assert all(len(revisions) <= 8 for revisions in by_role.values())
    assert 2 <= len(registry["snapshots"]) <= 16
    assert len(state["run_summary_index"]) <= 16
    assert len(canonical_bytes(state)) <= CURRENT_LOOP_STATE_MAX_BYTES
    assert registry["revision_tombstones"]


def test_worst_case_three_changing_roles_stay_inside_registration_headroom(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    for iteration in range(1, 13):
        candidates = _write_iteration(tmp_path, iteration=iteration)
        source = Path(candidates[0]["path"])
        source.write_text(
            "from qiskit import QuantumCircuit\n"
            f"ITERATION = {iteration}\n"
            "circuit = QuantumCircuit(2, 2)\n",
            encoding="utf-8",
        )
        qasm = Path(candidates[1]["path"])
        qasm.write_text(
            'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\n'
            f"// iteration {iteration}\n"
            "h q[0];\ncx q[0],q[1];\nmeasure q -> c;\n",
            encoding="utf-8",
        )
        result = _run_iteration(
            coordinator,
            candidates,
            iteration=iteration,
        )
        assert result["ok"] is True
        assert len(canonical_bytes(coordinator.store.read())) <= (CURRENT_LOOP_STATE_MAX_BYTES)
    state = coordinator.store.read()
    registry = state["evidence_registry"]
    assert len(registry["snapshots"]) == 5
    assert len(state["run_summary_index"]) == 5
    assert all(
        sum(
            revision["logical_role"] == role for revision in registry["artifact_revisions"].values()
        )
        <= 5
        for role in LOGICAL_ROLES
    )


def test_contract_management_metadata_preserves_worst_case_evidence_headroom(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    for iteration in range(1, 13):
        candidates = _write_iteration(tmp_path, iteration=iteration)
        Path(candidates[0]["path"]).write_text(
            "from qiskit import QuantumCircuit\n"
            f"ITERATION = {iteration}\n"
            "circuit = QuantumCircuit(2, 2)\n",
            encoding="utf-8",
        )
        Path(candidates[1]["path"]).write_text(
            'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\n'
            f"// iteration {iteration}\n"
            "h q[0];\ncx q[0],q[1];\nmeasure q -> c;\n",
            encoding="utf-8",
        )
        assert _run_iteration(coordinator, candidates, iteration=iteration)["ok"] is True

    narrowed = reset_customer_contract_document(
        coordinator.store.read()["current_loop_contract"],
        preset="evidence_only",
    )
    applied = coordinator.contract_apply_customer_document(
        document=narrowed,
        choice="apply_narrowing",
        explicit_authority=False,
    )
    assert applied["ok"] is True
    broadened = reset_customer_contract_document(
        coordinator.store.read()["current_loop_contract"],
        preset="assist",
    )
    proposed = coordinator.contract_apply_customer_document(
        document=broadened,
        choice="create_broadening_proposal",
        explicit_authority=False,
    )
    assert proposed["ok"] is True
    state_bytes = len(canonical_bytes(coordinator.store.read()))
    assert state_bytes <= CURRENT_LOOP_STATE_MAX_BYTES
    assert CURRENT_LOOP_STATE_MAX_BYTES - state_bytes >= 8_192
    state_before_help = canonical_bytes(coordinator.store.read())
    help_timings = []
    for _ in range(5):
        started = time.perf_counter()
        help_result = coordinator.help(topic="overview")
        help_timings.append(time.perf_counter() - started)
        assert len(json.dumps(help_result, indent=2, sort_keys=True).encode()) <= 32 * 1024
    assert max(help_timings) <= 2.0
    assert canonical_bytes(coordinator.store.read()) == state_before_help


def test_cross_surface_contract_changes_govern_future_evidence_updates(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    sidecar = SidecarSession(workspace=tmp_path, coordinator=coordinator)
    first = _run_iteration(
        coordinator,
        _write_iteration(tmp_path, iteration=1),
        iteration=1,
    )
    assert first["details"]["assistant_context_update"] is not None

    narrow = customer_contract_document(coordinator.store.read()["current_loop_contract"])
    narrow["customer_settings"]["preset"] = "custom"
    narrow["customer_settings"]["evidence_categories"]["result_manifestation"][
        "derived_assistant_exposure"
    ] = "disabled"
    narrowed = coordinator.contract_apply_customer_document(
        document=narrow,
        choice="apply_narrowing",
        explicit_authority=False,
        surface="ide",
    )
    assert narrowed["ok"] is True
    narrowed_revision = coordinator.store.read()["current_loop_contract"]["contract_revision"]
    assert sidecar.snapshot()["contract_revision"] == narrowed_revision

    second = _run_iteration(
        coordinator,
        _write_iteration(tmp_path, iteration=2),
        iteration=2,
    )
    assert second["details"]["assistant_context_update"] is None
    assert second["details"]["run_summary_reference"] is not None

    broaden = customer_contract_document(coordinator.store.read()["current_loop_contract"])
    broaden["customer_settings"]["evidence_categories"]["result_manifestation"][
        "derived_assistant_exposure"
    ] = "standing"
    proposed = sidecar.action(
        action="apply_document",
        payload={
            "document_json": json.dumps(broaden, sort_keys=True),
            "choice": "create_broadening_proposal",
        },
        expected_contract_revision=narrowed_revision,
    )
    assert proposed["ok"] is True
    assert coordinator.store.read()["current_loop_contract"]["contract_revision"] == (
        narrowed_revision
    )
    confirmed = coordinator.contract_confirm_broadening(
        expected_contract_revision=narrowed_revision,
        explicit_authority=True,
        surface="ide",
    )
    assert confirmed["ok"] is True

    third = _run_iteration(
        coordinator,
        _write_iteration(tmp_path, iteration=3),
        iteration=3,
    )
    assert third["details"]["assistant_context_update"] is not None
    assert third["details"]["assistant_context_update"]["raw_artifacts_remain_local"] is True


def test_generation_mixing_validator_rejects_wrong_result_parent(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    _run_iteration(coordinator, _write_iteration(tmp_path, iteration=1), iteration=1)
    _run_iteration(coordinator, _write_iteration(tmp_path, iteration=2), iteration=2)
    state = coordinator.store.read()
    snapshots = sorted(
        state["evidence_registry"]["snapshots"].values(),
        key=lambda item: item["creation_state_revision"],
    )
    current = deepcopy(snapshots[-1])
    current["manifestation_revision_set"]["result_manifestation"] = deepcopy(
        snapshots[0]["manifestation_revision_set"]["result_manifestation"]
    )
    summary = _read_summary(state, snapshots[-1]["run_summary_reference"])
    assert (
        validate_run_summary_snapshot_binding(summary, current)
        == "run_summary_manifestation_revision_set_mismatch"
    )


def test_identical_revision_derivation_has_deterministic_manifestation_reference(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    _run_iteration(coordinator, _write_iteration(tmp_path, iteration=1), iteration=1)
    first = coordinator.store.read()
    first_snapshot = first["evidence_registry"]["snapshots"][
        first["evidence_registry"]["current_presentation_snapshot_id"]
    ]
    _run_iteration(coordinator, _write_iteration(tmp_path, iteration=2), iteration=2)
    _run_iteration(coordinator, _write_iteration(tmp_path, iteration=3), iteration=3)
    final = coordinator.store.read()
    third_snapshot = final["evidence_registry"]["snapshots"][
        final["evidence_registry"]["current_presentation_snapshot_id"]
    ]
    for role in ("source_evidence", "python_manifestation", "circuit_manifestation"):
        assert (
            first_snapshot["manifestation_revision_set"][role]["manifestation_revision_id"]
            == third_snapshot["manifestation_revision_set"][role]["manifestation_revision_id"]
        )


def test_one_iteration_may_span_multiple_receipts_without_generation_mixing(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    candidates = _write_iteration(tmp_path, iteration=1)
    source_authority = _authorize(coordinator, iteration=1, roles=("source",))
    source_receipt = source_authority["details"]["operation_receipt"]["receipt_id"]
    source_result = coordinator.register_artifacts(
        candidates=[candidates[0]],
        operation_receipt_id=source_receipt,
    )
    assert source_result["ok"] is True
    remainder_authority = _authorize(
        coordinator,
        iteration=2,
        roles=("circuit_qasm", "results"),
    )
    remainder_receipt = remainder_authority["details"]["operation_receipt"]["receipt_id"]
    remainder_result = coordinator.register_artifacts(
        candidates=candidates[1:],
        operation_receipt_id=remainder_receipt,
    )
    assert remainder_result["ok"] is True
    state = coordinator.store.read()
    current = state["evidence_registry"]["snapshots"][
        state["evidence_registry"]["current_presentation_snapshot_id"]
    ]
    assert set(current["role_revision_set"]) == set(LOGICAL_ROLES)
    summary = _read_summary(state, current["run_summary_reference"])
    assert validate_run_summary_snapshot_binding(summary, current) is None
    assert {
        state["operation_receipts"][source_receipt]["status"],
        state["operation_receipts"][remainder_receipt]["status"],
    } == {"consumed"}


def test_pending_current_view_is_honest_and_status_resumes_exact_snapshot(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    _run_iteration(coordinator, _write_iteration(tmp_path, iteration=1), iteration=1)
    candidates = _write_iteration(tmp_path, iteration=2)
    authority = _authorize(coordinator, iteration=2)
    receipt_id = authority["details"]["operation_receipt"]["receipt_id"]
    state = coordinator.store.read()
    transaction = prepare_registration_transaction(
        state=state,
        candidates=candidates,
        workspace_root=tmp_path,
        operation_receipt_id=receipt_id,
        authorization_source="operation_receipt",
        enrollment_authority="current_loop_contract_assist",
        collect_permitted_roles=LOGICAL_ROLES,
    )
    commit_registration_transaction(store=coordinator.store, transaction=transaction)
    pending_view = coordinator.evidence_view(view_id="full_run_summary")
    assert pending_view["ok"] is True
    assert pending_view["details"]["registered_newer_pending"] is True
    assert pending_view["details"]["current_run_summary_reference"] is None
    assert pending_view["details"]["evidence_view"]["newer_iteration_status"] == "pending"
    pending_help = coordinator.help(topic="overview")["details"]["help"]["evidence_status"]
    assert pending_help["presentation_currency"] == "prior_newer_pending"
    assert pending_help["newer_iteration_status"] == "pending"
    assert pending_help["only_prior_run_summary_available"] is True
    assert pending_help["warnings"] == [
        {
            "object": "registered_evidence",
            "status": "pending",
            "reason": "Newer exact evidence is registered and awaiting local derivation.",
        }
    ]
    resumed = coordinator.status()
    assert resumed["details"]["pending_derivation_resumed"] is True
    current = coordinator.evidence_view(view_id="full_run_summary")
    assert current["details"]["registered_newer_pending"] is False
    assert current["details"]["current_run_summary_reference"] is not None


def test_summary_failure_preserves_explicit_prior_but_never_selects_it_as_latest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _coordinator(tmp_path)
    _run_iteration(coordinator, _write_iteration(tmp_path, iteration=1), iteration=1)
    prior_state = coordinator.store.read()
    prior_reference = prior_state["latest_run_summary_reference"]

    def fail_summary(**_kwargs: Any) -> dict[str, Any]:
        raise RunSummaryError("synthetic_run_summary_failure")

    monkeypatch.setattr(derivation_module, "build_run_summary", fail_summary)
    second = _run_iteration(
        coordinator,
        _write_iteration(tmp_path, iteration=2),
        iteration=2,
    )
    assert second["details"]["snapshot_status"] == "partial"
    state = coordinator.store.read()
    assert state["latest_run_summary_reference"] is None
    assert state["run_summary_index"][prior_reference]["currency"] == ("prior_newer_failed")
    assert state["latest_assistant_context_update"]["newer_iteration_status"] == "failed"
    failed_help = coordinator.help(topic="overview")["details"]["help"]["evidence_status"]
    assert failed_help["newer_iteration_status"] == "failed"
    assert failed_help["only_prior_run_summary_available"] is True
    assert {item["object"] for item in failed_help["warnings"]} == {
        "current_evidence_snapshot",
        "newer_evidence_snapshot",
    }
    current = coordinator.evidence_view(view_id="full_run_summary")
    assert current["details"]["current_run_summary_reference"] is None
    explicit_prior = coordinator.evidence_view(
        view_id="full_run_summary",
        selected_run_reference=prior_reference,
    )
    assert explicit_prior["details"]["selected_prior_summary_explicitly"] is True
    assert explicit_prior["details"]["evidence_view"]["presentation_currency"] == (
        "prior_newer_failed"
    )


def test_exclude_restore_and_delete_current_manifestation_are_snapshot_bound(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    _run_iteration(coordinator, _write_iteration(tmp_path, iteration=1), iteration=1)
    state = coordinator.store.read()
    contract_revision = state["current_loop_contract"]["contract_revision"]
    snapshot = state["evidence_registry"]["snapshots"][
        state["evidence_registry"]["current_presentation_snapshot_id"]
    ]
    result_revision = snapshot["role_revision_set"]["results"]
    excluded = coordinator.evidence_exclude(
        artifact_reference=result_revision,
        reason="customer_excluded",
        expected_contract_revision=contract_revision,
    )
    assert excluded["ok"] is True
    excluded_state = coordinator.store.read()
    assert excluded_state["latest_run_summary_reference"] is None
    assert (
        excluded_state["evidence_registry"]["artifact_revisions"][result_revision][
            "revision_status"
        ]
        == "excluded"
    )
    restored = coordinator.evidence_restore(
        artifact_reference=result_revision,
        expected_contract_revision=excluded_state["current_loop_contract"]["contract_revision"],
    )
    assert restored["ok"] is True
    restored_state = coordinator.store.read()
    assert restored_state["latest_run_summary_reference"] is not None
    result_manifestation = snapshot["manifestation_revision_set"]["result_manifestation"]
    deleted = coordinator.evidence_delete(
        artifact_reference=result_manifestation["artifact_reference"],
        expected_contract_revision=restored_state["current_loop_contract"]["contract_revision"],
        explicit_authority=True,
    )
    assert deleted["ok"] is True
    assert not Path(result_manifestation["local_path"]).exists()
    deleted_state = coordinator.store.read()
    deleted_snapshot = deleted_state["evidence_registry"]["snapshots"][snapshot["snapshot_id"]]
    assert deleted_snapshot["snapshot_status"] == "partial"
    assert "result_manifestation" not in deleted_snapshot["manifestation_revision_set"]


def test_exact_selected_qasm3_fallback_promotes_partial_snapshot(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    candidates = _write_iteration(tmp_path, iteration=1)
    (tmp_path / "bell.qasm").write_text(
        "OPENQASM 3.0;\nqubit[2] q;\n",
        encoding="utf-8",
    )
    proposed = coordinator.register_artifacts(candidates=candidates)
    assert proposed["details"]["review_authorized"] is False
    approved = coordinator.authorize_artifacts(
        action="approve_all",
        explicit_action_provenance="direct_user_action",
    )
    assert approved["ok"] is True
    processed = coordinator.process_authorized_artifacts()
    assert processed["ok"] is True
    assert processed["details"]["snapshot_status"] == "partial"
    outcomes = {item["role"]: item for item in processed["details"]["processing_outcomes"]}
    assert outcomes["circuit_qasm"]["status"] == "unsupported_format"
    assert outcomes["results"]["status"] == "completed"
    assert processed["details"]["run_summary_reference"] is not None
