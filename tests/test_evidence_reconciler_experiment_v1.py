from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from qcoder.current_loop import CurrentLoopError, CurrentLoopStore
from qcoder.current_loop_artifact_satisfaction import evaluate_exact_artifact_satisfaction
from qcoder.current_loop_evidence_reconciler import reconcile_current_evidence
from qcoder.current_loop_registration import (
    commit_registration_transaction,
    prepare_registration_transaction,
)
from qcoder.current_loop_result_manifest import (
    STRICT_RESULT_MANIFEST_SCHEMA_ID,
    StrictResultManifestError,
    normalize_strict_result_manifest,
)
from qcoder.current_loop_run_summary import run_summary_error
from qcoder.framework_native_evidence import (
    FrameworkNativeEvidenceError,
    reconcile_framework_native_run,
    validate_framework_circuit_manifest,
)
from qcoder.current_loop_goal_facade import (
    evaluate_current_run_goal,
    reconcile_completed_goal,
)
from tests.test_current_loop_evidence_revision_v1 import (
    _authorize,
    _coordinator,
    _read_summary,
    _run_iteration,
    _write_iteration,
    _write_strict_result_manifest,
)


def _strict_manifest(
    *,
    circuit_revision_id: str | None,
    circuit_digest: str,
    source_revision_id: str | None = None,
    source_digest: str | None = None,
    counts: dict[str, int] | None = None,
    observed_shots: int = 1024,
    requested_shots: int = 1024,
    lineage_status: str = "exact",
) -> dict:
    settings = {"backend": "AerSimulator", "shots": requested_shots}
    lineage = {"status": lineage_status}
    if lineage_status == "exact":
        lineage.update(
            {
                "artifact_revision_id": circuit_revision_id,
                "content_digest": circuit_digest,
                "source_artifact_revision_id": source_revision_id,
                "source_content_digest": source_digest,
            }
        )
        lineage = {key: value for key, value in lineage.items() if value is not None}
    return {
        "schema_id": STRICT_RESULT_MANIFEST_SCHEMA_ID,
        "schema_version": 1,
        "manifestation": "exact_result",
        "counts": counts or {"00": 520, "11": 504},
        "requested_shots": requested_shots,
        "observed_shots": observed_shots,
        "circuit_lineage": lineage,
        "execution_configuration": {
            "status": "exact",
            "reference": "aer-local-1024",
            "digest": sha256(
                json.dumps(settings, separators=(",", ":"), sort_keys=True).encode()
            ).hexdigest(),
            "settings": settings,
        },
        "execution_attempt_id": "attempt-bell-001",
        "producer": {
            "kind": "native_client_external_execution",
            "capture_method": "explicit_result_artifact",
            "identity": "qiskit-aer",
        },
        "bit_register_ordering": {
            "status": "known",
            "convention": "qiskit classical-register display order",
        },
        "warnings": [],
        "explicit_missingness": ["runtime_version", "operating_system"],
        "limitations": ["Execution environment fields not supplied remain missing."],
        "non_claims": ["qCoder did not execute the circuit."],
    }


def _register_one(coordinator, candidate: dict, *, role: str):
    authority = _authorize(coordinator, iteration=2, roles=(role,))
    receipt = authority["details"]["operation_receipt"]
    return coordinator.register_artifacts(
        candidates=[candidate], operation_receipt_id=receipt["receipt_id"]
    )


def test_gate0_source_edit_does_not_compose_old_circuit_and_result_as_current(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    _run_iteration(coordinator, _write_iteration(tmp_path, iteration=1), iteration=1)
    prior = coordinator.store.read()["latest_run_summary_reference"]
    source = tmp_path / "bell.py"
    source.write_text(
        "from qiskit import QuantumCircuit\nTARGET = 'psi_plus'\nqc = QuantumCircuit(2)\n",
        encoding="utf-8",
    )
    result = _register_one(
        coordinator,
        {
            "path": str(source),
            "role": "source",
            "artifact_type": "source",
            "provenance": "assistant_modified",
        },
        role="source",
    )
    assert result["ok"] is True
    state = coordinator.store.read()
    assert state["latest_run_summary_reference"] is None
    assert state["run_summary_index"][prior]["currency"] == "superseded"
    snapshot = state["evidence_registry"]["snapshots"][
        state["evidence_registry"]["current_presentation_snapshot_id"]
    ]
    assert snapshot["evidence_reconciliation"]["eligibility"]["current_run_evidence"] is False


def test_gate0_new_circuit_does_not_inherit_old_result(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    _run_iteration(coordinator, _write_iteration(tmp_path, iteration=1), iteration=1)
    qasm = tmp_path / "bell.qasm"
    qasm.write_text(
        'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\nx q[0];\nh q[0];\n',
        encoding="utf-8",
    )
    result = _register_one(
        coordinator,
        {
            "path": str(qasm),
            "role": "circuit_qasm",
            "artifact_type": "circuit_qasm",
            "provenance": "assistant_modified",
        },
        role="circuit_qasm",
    )
    assert result["ok"] is True
    state = coordinator.store.read()
    assert state["latest_run_summary_reference"] is None
    snapshot = state["evidence_registry"]["snapshots"][
        state["evidence_registry"]["current_presentation_snapshot_id"]
    ]
    assert snapshot["evidence_reconciliation"]["eligibility"]["current_run_evidence"] is False


def test_gate0_arbitrary_top_level_json_is_rejected_before_registration(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    result_path = tmp_path / "results.json"
    result_path.write_text('{"00": 520, "11": 504}\n', encoding="utf-8")
    before = coordinator.store.read()
    rejected = _register_one(
        coordinator,
        {
            "path": str(result_path),
            "role": "results",
            "artifact_type": "results",
            "provenance": "assistant_created",
        },
        role="results",
    )
    after = coordinator.store.read()
    assert rejected["ok"] is False
    assert rejected["category"] == "artifact_format_unsupported"
    assert after["evidence_registry"]["role_heads"] == before["evidence_registry"]["role_heads"]


def test_strict_manifest_rejects_malformed_counts_shots_and_false_lineage() -> None:
    circuit_id = "artifact-revision-circuit"
    source_id = "artifact-revision-source"
    revisions = {
        circuit_id: {"logical_role": "circuit_qasm", "content_digest": "c" * 64},
        source_id: {"logical_role": "source", "content_digest": "s" * 64},
    }
    malformed = _strict_manifest(
        circuit_revision_id=circuit_id,
        circuit_digest="c" * 64,
        source_revision_id=source_id,
        source_digest="s" * 64,
        counts={"00": -1, "11": 1025},
    )
    with pytest.raises(StrictResultManifestError, match="result_manifest_counts_invalid"):
        normalize_strict_result_manifest(malformed, artifact_revisions=revisions)
    contradictory = _strict_manifest(
        circuit_revision_id=circuit_id,
        circuit_digest="c" * 64,
        counts={"00": 1, "11": 1},
        observed_shots=3,
        requested_shots=3,
    )
    with pytest.raises(
        StrictResultManifestError, match="result_manifest_observed_shots_contradiction"
    ):
        normalize_strict_result_manifest(contradictory, artifact_revisions=revisions)
    false_lineage = _strict_manifest(
        circuit_revision_id=circuit_id,
        circuit_digest="d" * 64,
    )
    with pytest.raises(StrictResultManifestError, match="result_manifest_false_circuit_lineage"):
        normalize_strict_result_manifest(false_lineage, artifact_revisions=revisions)


def test_unknown_lineage_is_valid_but_not_current_for_claimed_circuit() -> None:
    manifest = _strict_manifest(
        circuit_revision_id=None,
        circuit_digest="",
        lineage_status="unknown",
    )
    normalized = normalize_strict_result_manifest(manifest, artifact_revisions={})
    reconciled = reconcile_current_evidence(
        role_revision_set={"results": "artifact-revision-result"},
        artifact_revisions={
            "artifact-revision-result": {
                "logical_role": "results",
                "content_digest": "r" * 64,
            }
        },
        normalized_result_manifest=normalized,
    )
    assert reconciled["eligibility"] == {
        "valid_result_evidence": True,
        "current_run_evidence": False,
        "reproducibility_rich_run_evidence": False,
    }
    assert not any(
        item["relationship"] in {"executed_from", "derived_from", "reused_input"}
        for item in reconciled["relationships"]
    )


def test_strict_manifest_rejects_unbounded_or_nonlist_missingness() -> None:
    manifest = _strict_manifest(
        circuit_revision_id=None,
        circuit_digest="",
        lineage_status="unknown",
    )
    manifest["explicit_missingness"] = "environment"
    with pytest.raises(
        StrictResultManifestError,
        match="result_manifest_explicit_missingness_invalid",
    ):
        normalize_strict_result_manifest(manifest, artifact_revisions={})
    manifest["explicit_missingness"] = ["x" * 1_025]
    with pytest.raises(
        StrictResultManifestError,
        match="result_manifest_explicit_missingness_invalid",
    ):
        normalize_strict_result_manifest(manifest, artifact_revisions={})


def test_shots_only_rerun_reuses_exact_circuit_and_preserves_prior_run(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    _run_iteration(coordinator, _write_iteration(tmp_path, iteration=1), iteration=1)
    first_state = coordinator.store.read()
    first_summary = first_state["latest_run_summary_reference"]
    source_head = first_state["evidence_registry"]["role_heads"]["source"]
    circuit_head = first_state["evidence_registry"]["role_heads"]["circuit_qasm"]
    result_path = tmp_path / "results.json"
    _write_strict_result_manifest(
        source=tmp_path / "bell.py",
        qasm=tmp_path / "bell.qasm",
        result=result_path,
        counts={"00": 1010, "11": 990},
        iteration=2,
    )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["requested_shots"] = 2000
    payload["observed_shots"] = 2000
    payload["execution_configuration"]["settings"]["shots"] = 2000
    payload["execution_configuration"]["digest"] = sha256(
        json.dumps(
            payload["execution_configuration"]["settings"],
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    result_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    registered = _register_one(
        coordinator,
        {
            "path": str(result_path),
            "role": "results",
            "artifact_type": "results",
            "provenance": "assistant_modified",
        },
        role="results",
    )
    assert registered["ok"] is True
    state = coordinator.store.read()
    assert state["evidence_registry"]["role_heads"]["source"] == source_head
    assert state["evidence_registry"]["role_heads"]["circuit_qasm"] == circuit_head
    assert state["latest_run_summary_reference"] != first_summary
    assert state["run_summary_index"][first_summary]["currency"] == "superseded"
    current = _read_summary(state, state["latest_run_summary_reference"])
    assert current["count_projection"]["observed_shots"] == 2000
    assert current["evidence_classification"] == "reproducibility_rich_run_evidence"
    relationship_kinds = {
        item["relationship"] for item in current["evidence_reconciliation"]["relationships"]
    }
    assert {
        "derived_from",
        "executed_from",
        "captured_from",
        "produced",
        "configured_by",
        "reused_input",
    } <= relationship_kinds
    assert len(current["evidence_reconciliation"]["entities"]) <= 8


@pytest.mark.parametrize(
    "role,suffix,content",
    [
        ("source", ".py", "VALUE = 1\n"),
        ("circuit_qasm", ".qasm", "OPENQASM 2.0;\nqreg q[1];\n"),
        ("results", ".json", '{"counts":{"0":1}}\n'),
    ],
)
def test_preexisting_exact_artifact_satisfies_without_mutation(
    tmp_path: Path, role: str, suffix: str, content: str
) -> None:
    path = tmp_path / f"artifact{suffix}"
    path.write_text(content, encoding="utf-8")
    before = path.stat()
    result = evaluate_exact_artifact_satisfaction(
        workspace_root=tmp_path,
        path=path,
        role=role,
        origin="pre_existing",
    )
    after = path.stat()
    assert result["disposition"] == "pre_existing_exact_artifact"
    assert result["native_write_permission_required"] is False
    assert (before.st_mtime_ns, before.st_size, before.st_ino) == (
        after.st_mtime_ns,
        after.st_size,
        after.st_ino,
    )


def test_registration_failure_before_commit_recovers_without_execution_rerun(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    candidates = _write_iteration(tmp_path, iteration=1)
    authority = _authorize(coordinator, iteration=1)
    receipt_id = authority["details"]["operation_receipt"]["receipt_id"]
    before = coordinator.store.read()
    transaction = prepare_registration_transaction(
        state=before,
        candidates=candidates,
        workspace_root=tmp_path,
        operation_receipt_id=receipt_id,
        authorization_source="operation_receipt",
        enrollment_authority="current_loop_contract_assist",
        collect_permitted_roles=("source", "circuit_qasm", "results"),
    )
    assert coordinator.store.read()["evidence_registry"]["role_heads"] == {}
    execution_attempts = 1
    restarted = _coordinator_from_existing(tmp_path)
    recovered = commit_registration_transaction(store=restarted.store, transaction=transaction)
    assert recovered["new_revision_count"] == 3
    assert execution_attempts == 1
    with pytest.raises(CurrentLoopError, match="client_state_conflict"):
        commit_registration_transaction(store=restarted.store, transaction=transaction)


def test_mismatched_retry_artifact_is_rejected_without_execution_rerun(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    candidates = _write_iteration(tmp_path, iteration=1)
    authority = _authorize(coordinator, iteration=1)
    receipt_id = authority["details"]["operation_receipt"]["receipt_id"]
    before = coordinator.store.read()
    transaction = prepare_registration_transaction(
        state=before,
        candidates=candidates,
        workspace_root=tmp_path,
        operation_receipt_id=receipt_id,
        authorization_source="operation_receipt",
        enrollment_authority="current_loop_contract_assist",
        collect_permitted_roles=("source", "circuit_qasm", "results"),
    )
    execution_attempts = 1
    Path(candidates[2]["path"]).write_text('{"counts":{"00":1}}\n', encoding="utf-8")
    with pytest.raises(CurrentLoopError, match="selected_file_stale"):
        commit_registration_transaction(store=coordinator.store, transaction=transaction)
    after = coordinator.store.read()
    assert after["state_revision"] == before["state_revision"]
    assert after["operation_receipts"][receipt_id]["status"] == "issued"
    assert after["evidence_registry"]["role_heads"] == {}
    assert execution_attempts == 1


def _coordinator_from_existing(workspace: Path):
    from qcoder.current_loop_coordinator import CurrentLoopCoordinator

    return CurrentLoopCoordinator(workspace_root=workspace)


def test_stale_lock_file_does_not_deadlock_new_process_style_store_access(tmp_path: Path) -> None:
    store = CurrentLoopStore.for_workspace(tmp_path)
    store.lock_path.parent.mkdir(parents=True)
    store.lock_path.write_text("abandoned prior process marker", encoding="utf-8")
    with store.lock():
        assert store.lock_path.is_file()


def test_framework_native_pennylane_run_never_requires_qasm() -> None:
    circuit = {
        "schema_id": "qcoder.framework_native.circuit_manifest.v1",
        "schema_version": 1,
        "framework": "pennylane",
        "framework_version": "0.40",
        "wires": 2,
        "operations": [
            {"name": "Hadamard", "wires": [0]},
            {"name": "CNOT", "wires": [0, 1]},
        ],
        "measurements": [{"kind": "counts", "wires": [0, 1]}],
    }
    result = _strict_manifest(
        circuit_revision_id=None,
        circuit_digest="0" * 64,
        source_revision_id=None,
        source_digest=None,
    )
    reconciled = reconcile_framework_native_run(
        circuit=circuit,
        result=result,
        loop_ref="loop-framework-native-test",
        workspace_binding="workspace-framework-native-test",
        state_revision=4,
        contract_revision=1,
    )
    assert reconciled["current_run_evidence"] is True
    assert reconciled["qasm_required"] is False
    assert reconciled["qasm_conversion_performed"] is False
    assert reconciled["semantic_equivalence_to_qasm_claimed"] is False
    assert reconciled["run_summary"]["schema_id"] == "qcoder.current_loop.run_summary.v2"
    assert reconciled["run_summary"]["evidence_classification"] == (
        "reproducibility_rich_run_evidence"
    )
    assert run_summary_error(reconciled["run_summary"]) is None


def test_framework_native_manifest_drops_extra_fields_and_rejects_unbounded_data() -> None:
    circuit = {
        "schema_id": "qcoder.framework_native.circuit_manifest.v1",
        "schema_version": 1,
        "framework": "pennylane",
        "wires": 2,
        "operations": [{"name": "Hadamard", "wires": [0], "unrelated_raw_data": "not retained"}],
        "measurements": [{"kind": "counts", "wires": [0, 1], "extra": "not retained"}],
    }
    normalized = validate_framework_circuit_manifest(circuit)
    assert normalized["operations"] == [{"name": "Hadamard", "wires": [0], "parameters": []}]
    assert normalized["measurements"] == [{"kind": "counts", "wires": [0, 1]}]
    circuit["operations"][0]["name"] = "x" * 257
    with pytest.raises(FrameworkNativeEvidenceError, match="framework_circuit_text_invalid"):
        validate_framework_circuit_manifest(circuit)


def test_private_one_goal_facade_has_one_external_boundary_and_no_public_surface(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    candidates = _write_iteration(tmp_path, iteration=1)
    _run_iteration(coordinator, candidates[:2], iteration=1)
    state = coordinator.store.read()
    evaluated = evaluate_current_run_goal(state=state, requested_shots=2000)
    action = evaluated["native_action_boundary"]
    assert action["native_execution_owner"] == "client_or_customer"
    assert action["qcoder_executes_customer_code"] is False
    assert evaluated["public_operation_added"] is False
    assert evaluated["public_cli_command_added"] is False
    source_id = state["evidence_registry"]["role_heads"]["source"]
    circuit_id = state["evidence_registry"]["role_heads"]["circuit_qasm"]
    result = _strict_manifest(
        circuit_revision_id=circuit_id,
        circuit_digest=state["evidence_registry"]["artifact_revisions"][circuit_id][
            "content_digest"
        ],
        source_revision_id=source_id,
        source_digest=state["evidence_registry"]["artifact_revisions"][source_id]["content_digest"],
        counts={"00": 1006, "11": 994},
        observed_shots=2000,
        requested_shots=2000,
    )
    first = reconcile_completed_goal(state=state, action=action, result_manifest=result)
    second = reconcile_completed_goal(
        state=state,
        action=deepcopy(action),
        result_manifest=deepcopy(result),
    )
    assert first == second
    assert first["reconciliation"]["eligibility"]["current_run_evidence"] is True
    assert first["external_execution_rerun"] is False


def test_cli_native_and_cursor_adapter_fixtures_converge_on_canonical_evidence(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    _run_iteration(coordinator, _write_iteration(tmp_path, iteration=1)[:2], iteration=1)
    state = coordinator.store.read()
    action = evaluate_current_run_goal(state=state, requested_shots=1024)["native_action_boundary"]
    source_id = state["evidence_registry"]["role_heads"]["source"]
    circuit_id = state["evidence_registry"]["role_heads"]["circuit_qasm"]
    manifest = _strict_manifest(
        circuit_revision_id=circuit_id,
        circuit_digest=state["evidence_registry"]["artifact_revisions"][circuit_id][
            "content_digest"
        ],
        source_revision_id=source_id,
        source_digest=state["evidence_registry"]["artifact_revisions"][source_id]["content_digest"],
    )
    canonical_by_client = {
        client: reconcile_completed_goal(
            state=deepcopy(state),
            action=deepcopy(action),
            result_manifest=deepcopy(manifest),
        )
        for client in ("codex_cli_native", "cursor_desktop_fixture")
    }
    assert canonical_by_client["codex_cli_native"] == canonical_by_client["cursor_desktop_fixture"]
