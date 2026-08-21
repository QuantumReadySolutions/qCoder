from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

import qcoder.current_loop_coordinator as coordinator_module
from qcoder.context_bridge_mcp import EXPECTED_TOOLS
from qcoder.current_loop_artifact_satisfaction import evaluate_exact_artifact_satisfaction
from qcoder.current_loop_binding_mcp import (
    BEGIN_CURRENT_LOOP_TOOL_NAME,
    COMPLETE_CURRENT_STEP_TOOL_NAME,
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_result_manifest import (
    STRICT_RESULT_MANIFEST_SCHEMA_ID,
    StrictResultManifestError,
    normalize_strict_result_manifest,
)
from qcoder.framework_native_evidence import (
    FrameworkNativeEvidenceError,
    reconcile_framework_native_run,
)


SOURCE_REQUEST = (
    "Use qCoder to write a Qiskit program that prepares a Φ+ Bell state. "
    "Stop after generating the code."
)
SOURCE = (
    "from qiskit import QuantumCircuit\n"
    "circuit = QuantumCircuit(2, 2)\n"
    "circuit.h(0)\n"
    "circuit.cx(0, 1)\n"
    "circuit.measure_all()\n"
)
QASM = (
    'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\n'
    "h q[0];\ncx q[0],q[1];\nmeasure q -> c;\n"
)


def _call(root: Path, name: str, arguments: dict) -> dict:
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        workspace_root=root,
    )
    assert response is not None
    return response["result"]["structuredContent"]


def _begin(root: Path, request: str, *, target: str | None = None) -> dict:
    role, default_target = (
        ("circuit_qasm", "bell.qasm")
        if "QASM" in request
        else ("results", "result.json")
        if request.startswith("Run ")
        else ("source", "bell.py")
    )
    result = _call(
        root,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": request,
            "intended_artifact_paths": {role: target or default_target},
        },
    )
    assert result["ok"] is True, result
    return result


def _complete(
    root: Path,
    begun: dict,
    path: Path,
    *,
    disposition: str = "assistant_created",
) -> dict:
    return _call(
        root,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {
            "current_action_handle": begun["current_step_contract"]["permitted_native_action"][
                "current_action_handle"
            ],
            "artifact_path": path.relative_to(root).as_posix(),
            "artifact_disposition": disposition,
        },
    )


def _source_and_circuit(root: Path) -> tuple[dict, Path, Path]:
    begun = _begin(root, SOURCE_REQUEST)
    source = root / "bell.py"
    source.write_text(SOURCE, encoding="utf-8")
    assert _complete(root, begun, source)["ok"] is True
    qasm_step = _begin(root, "Now export the circuit as QASM.")
    qasm = root / "bell.qasm"
    qasm.write_text(QASM, encoding="utf-8")
    assert _complete(root, qasm_step, qasm)["ok"] is True
    return qasm_step, source, qasm


def _manifest(
    *,
    attempt: str = "native-attempt-0001",
    circuit_status: str = "current_step_contract",
    shots: int = 1_024,
) -> dict:
    return {
        "schema_id": STRICT_RESULT_MANIFEST_SCHEMA_ID,
        "schema_version": 3,
        "manifestation": "exact_result",
        "counts": {"00": shots // 2, "11": shots - shots // 2},
        "requested_shots": shots,
        "observed_shots": shots,
        "circuit_lineage": {"status": circuit_status},
        "source_lineage": {"status": "not_supplied"},
        "execution_configuration": {
            "status": "exact",
            "reference": "native-client-aer-simulator",
            "settings": {"backend": "aer_simulator", "shots": shots},
        },
        "execution_method": {
            "kind": "sampled_shots",
            "interface": "qiskit_backend_run",
            "backend_or_sampler": "qiskit_aer.AerSimulator",
        },
        "execution_observation": {
            "status": "client_reported_completed",
            "external_execution_attempt_count": 1,
            "dependency_installation_performed": False,
            "environment_mutated": False,
            "qcoder_independently_verified_execution": False,
        },
        "execution_attempt_id": attempt,
        "producer_provenance": {
            "kind": "native_client_external_execution",
            "method": "qiskit_aer",
        },
        "capture_provenance": {
            "kind": "explicit_selected_result_manifest",
            "method": "native_client_file_handoff",
        },
        "bit_register_ordering": {
            "status": "known",
            "convention": "qiskit_little_endian",
            "endianness": "little",
            "bit_order": ["q1", "q0"],
            "register_order": ["c"],
        },
        "warnings": [],
        "explicit_missingness": ["runtime_version"],
        "limitations": [],
        "non_claims": ["qCoder did not execute customer code."],
    }


def _run_step(root: Path, *, attempt: str = "native-attempt-0001") -> tuple[dict, Path]:
    begun = _begin(
        root,
        "Run it locally with 1,024 shots and save the result evidence.",
        target=f"{attempt}.json",
    )
    assert begun["current_step_contract"]["permitted_native_action"]["artifact_role"] == "results"
    result_path = root / f"{attempt}.json"
    result_path.write_text(json.dumps(_manifest(attempt=attempt), sort_keys=True), encoding="utf-8")
    return begun, result_path


def test_strict_source_circuit_result_is_one_current_causal_run(tmp_path: Path) -> None:
    _source_and_circuit(tmp_path)
    begun, result_path = _run_step(tmp_path)
    completed = _complete(tmp_path, begun, result_path)
    assert completed["ok"] is True, completed
    assert completed["current_step_status"] == "complete_resumable"
    assert completed["requested_customer_outcome_ready"] is True
    assert completed["current_run_summary"]["currency"] == "current"
    assert completed["current_run_summary"]["freshness"]["status"] == "fresh"
    assert completed["current_run_summary"]["count_projection"]["observed_shots"] == 1_024
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert state["latest_run_summary_reference"] is not None
    summary = json.loads(
        Path(
            state["run_summary_index"][state["latest_run_summary_reference"]]["local_path"]
        ).read_text(encoding="utf-8")
    )
    result_revision = state["evidence_registry"]["artifact_revisions"][
        state["evidence_registry"]["role_heads"]["results"]
    ]
    strict_binding = result_revision["strict_result_manifest_binding"]
    assert strict_binding["execution_method"]["kind"] == "sampled_shots"
    assert strict_binding["execution_observation"] == {
        "status": "client_reported_completed",
        "external_execution_attempt_count": 1,
        "dependency_installation_performed": False,
        "environment_mutated": False,
        "qcoder_independently_verified_execution": False,
    }
    assert summary["evidence_reconciliation"]["eligibility"] == {
        "valid_result_evidence": True,
        "current_run_evidence": True,
        "reproducibility_rich_run_evidence": True,
    }
    relationships = summary["evidence_reconciliation"]["relationships"]
    assert {item["relationship"] for item in relationships} >= {
        "derived_from",
        "executed_from",
        "captured_from",
        "produced",
    }
    assert state["coordinator"]["bootstrap_count"] == 1
    assert state["coordinator"]["request_baseline_count"] == 1


def test_source_and_circuit_replacement_invalidate_downstream_but_keep_history(
    tmp_path: Path,
) -> None:
    _source_and_circuit(tmp_path)
    begun, result_path = _run_step(tmp_path)
    assert _complete(tmp_path, begun, result_path)["ok"] is True
    before = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    old_heads = deepcopy(before["evidence_registry"]["role_heads"])
    old_summary = next(iter(before["run_summary_index"]))

    source_step = _begin(
        tmp_path,
        "Update the Python source to prepare a Ψ+ Bell state. Stop after generating the code.",
    )
    source = tmp_path / "bell.py"
    source.write_text(SOURCE + "circuit.x(0)\n", encoding="utf-8")
    assert _complete(tmp_path, source_step, source, disposition="assistant_modified")["ok"] is True
    source_state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert source_state["latest_run_summary_reference"] is None
    assert old_summary in source_state["run_summary_index"]
    assert source_state["run_summary_index"][old_summary]["currency"] != "current"
    assert (
        source_state["evidence_registry"]["role_heads"]["circuit_qasm"] == old_heads["circuit_qasm"]
    )
    assert source_state["evidence_registry"]["role_heads"]["results"] == old_heads["results"]

    qasm_step = _begin(tmp_path, "Now export the updated circuit as QASM.")
    qasm = tmp_path / "bell.qasm"
    qasm.write_text(QASM.replace("h q[0];", "x q[0];\nh q[0];"), encoding="utf-8")
    assert _complete(tmp_path, qasm_step, qasm, disposition="assistant_modified")["ok"] is True
    circuit_state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert circuit_state["latest_run_summary_reference"] is None
    assert circuit_state["evidence_registry"]["role_heads"]["results"] == old_heads["results"]
    assert old_summary in circuit_state["run_summary_index"]


@pytest.mark.parametrize(
    ("mutation", "category"),
    [
        (lambda value: value.update(counts={"00": -1}), "result_manifest_counts_invalid"),
        (
            lambda value: value.update(observed_shots=1_025),
            "result_manifest_observed_shots_contradiction",
        ),
        (
            lambda value: value.update(
                bit_register_ordering={
                    "status": "known",
                    "convention": "qiskit_little_endian",
                    "endianness": "big",
                    "bit_order": ["q1", "q0"],
                    "register_order": ["c"],
                }
            ),
            "result_manifest_bit_ordering_contradictory",
        ),
    ],
)
def test_malformed_manifests_fail_closed(mutation, category: str) -> None:
    value = _manifest(circuit_status="unknown")
    mutation(value)
    with pytest.raises(StrictResultManifestError, match=category):
        normalize_strict_result_manifest(value, artifact_revisions={})


def test_bare_counts_are_not_current_result_transport(tmp_path: Path) -> None:
    _source_and_circuit(tmp_path)
    begun = _begin(
        tmp_path,
        "Run it locally with 1,024 shots and save the result evidence.",
        target="bare-counts.json",
    )
    path = tmp_path / "bare-counts.json"
    path.write_text(json.dumps({"00": 512, "11": 512}), encoding="utf-8")
    failed = _complete(tmp_path, begun, path)
    assert failed["ok"] is False
    assert failed["category"] == "strict_result_manifest_required_for_current_result"
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert "results" not in state["evidence_registry"]["role_heads"]
    assert state["latest_run_summary_reference"] is None


def test_unknown_lineage_is_valid_but_not_current_for_claimed_circuit(tmp_path: Path) -> None:
    value = _manifest(circuit_status="unknown")
    normalized = normalize_strict_result_manifest(value, artifact_revisions={})
    assert normalized["circuit_lineage"]["status"] == "unknown"
    assert any("not inferred" in item for item in normalized["limitations"])


def test_unknown_lineage_registers_as_historical_without_current_run(tmp_path: Path) -> None:
    _source_and_circuit(tmp_path)
    begun, result_path = _run_step(tmp_path, attempt="native-attempt-unknown")
    value = _manifest(attempt="native-attempt-unknown", circuit_status="unknown")
    result_path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    completed = _complete(tmp_path, begun, result_path)
    assert completed["ok"] is True
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert "results" in state["evidence_registry"]["role_heads"]
    assert state["latest_run_summary_reference"] is None
    assert len(state["run_summary_index"]) == 1
    descriptor = next(iter(state["run_summary_index"].values()))
    assert descriptor["currency"] == "prior"
    assert descriptor["status"] == "stale"


def test_shots_only_rerun_reuses_exact_inputs_and_preserves_prior_run(tmp_path: Path) -> None:
    _source_and_circuit(tmp_path)
    first_step, first_path = _run_step(tmp_path, attempt="native-attempt-1024")
    assert _complete(tmp_path, first_step, first_path)["ok"] is True
    first_state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    first_summary = first_state["latest_run_summary_reference"]
    source_head = first_state["evidence_registry"]["role_heads"]["source"]
    circuit_head = first_state["evidence_registry"]["role_heads"]["circuit_qasm"]

    second_step = _begin(
        tmp_path,
        "Run the same circuit locally with 2,000 shots and save the result evidence.",
        target="native-attempt-2000.json",
    )
    second_path = tmp_path / "native-attempt-2000.json"
    second_path.write_text(
        json.dumps(_manifest(attempt="native-attempt-2000", shots=2_000), sort_keys=True),
        encoding="utf-8",
    )
    assert _complete(tmp_path, second_step, second_path)["ok"] is True
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert state["evidence_registry"]["role_heads"]["source"] == source_head
    assert state["evidence_registry"]["role_heads"]["circuit_qasm"] == circuit_head
    assert state["latest_run_summary_reference"] != first_summary
    assert first_summary in state["run_summary_index"]
    assert state["run_summary_index"][first_summary]["currency"] == "superseded"
    assert state["coordinator"]["bootstrap_count"] == 1
    assert state["coordinator"]["request_baseline_count"] == 1


def test_false_lineage_and_reused_attempts_fail_closed(tmp_path: Path) -> None:
    _source_and_circuit(tmp_path)
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    state = coordinator.store.read()
    circuit_id = state["evidence_registry"]["role_heads"]["circuit_qasm"]
    false = _manifest(circuit_status="unknown")
    false["circuit_lineage"] = {
        "status": "exact",
        "artifact_revision_id": circuit_id,
        "content_digest": "f" * 64,
    }
    with pytest.raises(StrictResultManifestError, match="result_manifest_false_circuit_lineage"):
        normalize_strict_result_manifest(
            false,
            artifact_revisions=state["evidence_registry"]["artifact_revisions"],
        )

    first_step, first_path = _run_step(tmp_path, attempt="reused-attempt")
    assert _complete(tmp_path, first_step, first_path)["ok"] is True
    second_step = _begin(
        tmp_path,
        "Run it locally again and save the result evidence.",
        target="reused-again.json",
    )
    second_path = tmp_path / "reused-again.json"
    second_path.write_text(
        json.dumps(_manifest(attempt="reused-attempt"), sort_keys=True), encoding="utf-8"
    )
    rejected = _complete(tmp_path, second_step, second_path)
    assert rejected["ok"] is False
    assert rejected["category"] == "result_manifest_execution_attempt_cross_request"


def test_preexisting_selected_source_satisfies_without_mutation_or_false_provenance(
    tmp_path: Path,
) -> None:
    path = tmp_path / "already_here.py"
    path.write_text(SOURCE, encoding="utf-8")
    before = path.stat()
    digest = sha256(path.read_bytes()).hexdigest()
    proof = evaluate_exact_artifact_satisfaction(
        workspace_root=tmp_path,
        path=path,
        role="source",
        origin="pre_existing",
        expected_content_digest=digest,
    )
    after = path.stat()
    assert proof["native_write_required"] is False
    assert proof["assistant_created_provenance_claimed"] is False
    assert (before.st_mtime_ns, before.st_mode, digest) == (
        after.st_mtime_ns,
        after.st_mode,
        sha256(path.read_bytes()).hexdigest(),
    )
    begun = _begin(tmp_path, SOURCE_REQUEST, target="already_here.py")
    completed = _complete(
        tmp_path,
        begun,
        path,
        disposition="pre_existing_exact_artifact",
    )
    assert completed["ok"] is True
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    source_revision = state["evidence_registry"]["artifact_revisions"][
        state["evidence_registry"]["role_heads"]["source"]
    ]
    assert source_revision["event_disposition"] == "selected"


def test_failed_registration_retries_same_result_without_rerun_and_rejects_changed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source_and_circuit(tmp_path)
    begun, result_path = _run_step(tmp_path, attempt="native-attempt-recovery")
    original_commit = coordinator_module.commit_registration_transaction
    calls = 0

    def fail_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected failure before registration commit")
        return original_commit(**kwargs)

    monkeypatch.setattr(coordinator_module, "commit_registration_transaction", fail_once)
    failed = _complete(tmp_path, begun, result_path)
    assert failed["ok"] is False
    assert failed["recovery"]["exact_artifact_bound_for_retry"] is True
    assert failed["recovery"]["external_execution_rerun_required"] is False
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert (
        state["coordinator"]["registration_recovery_pending"]["same_exact_artifact_required"]
        is True
    )
    completed = _complete(tmp_path, begun, result_path)
    assert completed["ok"] is True
    assert calls == 2
    duplicate = _complete(tmp_path, begun, result_path)
    assert duplicate["ok"] is True
    assert duplicate["duplicate_delivery_noop"] is True

    other = tmp_path / "other"
    other.mkdir()
    _source_and_circuit(other)
    changed_step, changed_path = _run_step(other, attempt="native-attempt-changed")
    calls = 0
    failed = _complete(other, changed_step, changed_path)
    assert failed["ok"] is False
    changed = _manifest(attempt="native-attempt-changed")
    changed["counts"] = {"00": 500, "11": 524}
    changed_path.write_text(json.dumps(changed, sort_keys=True), encoding="utf-8")
    rejected = _complete(other, changed_step, changed_path)
    assert rejected["ok"] is False
    assert rejected["category"] == "registration_recovery_artifact_mismatch"


def test_pennylane_explicit_manifest_is_current_without_qasm_or_qcoder_execution() -> None:
    result = reconcile_framework_native_run(
        circuit={
            "schema_id": "qcoder.framework_native.circuit_manifest.v1",
            "schema_version": 1,
            "framework": "pennylane",
            "framework_version": "0.41",
            "wires": 2,
            "operations": [
                {"name": "Hadamard", "wires": [0], "parameters": []},
                {"name": "CNOT", "wires": [0, 1], "parameters": []},
            ],
            "measurements": [{"kind": "counts", "wires": [0, 1]}],
        },
        result=_manifest(circuit_status="unknown"),
        loop_ref="loop-" + "a" * 32,
        workspace_binding="/bounded/workspace",
        state_revision=1,
        contract_revision=1,
    )
    assert result["current_run_evidence"] is True
    assert result["qasm_required"] is False
    assert result["qasm_conversion_performed"] is False
    assert result["semantic_equivalence_to_qasm_claimed"] is False
    assert result["native_execution_owned_by_qcoder"] is False


def test_strict_manifest_rejects_unbounded_configuration_shape() -> None:
    manifest = _manifest(circuit_status="unknown")
    manifest["execution_configuration"]["unexpected"] = "not part of the bounded contract"
    with pytest.raises(StrictResultManifestError) as exc_info:
        normalize_strict_result_manifest(manifest, artifact_revisions={})
    assert exc_info.value.category == "result_manifest_execution_configuration_invalid"


@pytest.mark.parametrize(
    ("mutation", "category"),
    [
        (
            lambda value: value["execution_observation"].update(
                dependency_installation_performed=True
            ),
            "result_manifest_dependency_installation_outside_current_step",
        ),
        (
            lambda value: value["execution_observation"].update(environment_mutated=True),
            "result_manifest_environment_mutation_outside_current_step",
        ),
        (
            lambda value: value["execution_observation"].update(external_execution_attempt_count=2),
            "result_manifest_external_execution_attempt_count_invalid",
        ),
        (
            lambda value: value["execution_observation"].update(
                qcoder_independently_verified_execution=True
            ),
            "result_manifest_qcoder_execution_verification_claim_invalid",
        ),
        (
            lambda value: value["execution_method"].update(
                kind="analytic_probabilities", backend_or_sampler=None
            ),
            "result_manifest_non_sampled_method_presented_as_sampled_shots",
        ),
        (
            lambda value: value["execution_method"].update(
                kind="deterministic_construction", backend_or_sampler=None
            ),
            "result_manifest_non_sampled_method_presented_as_sampled_shots",
        ),
        (
            lambda value: value["producer_provenance"].update(kind="hard_coded_counts"),
            "result_manifest_execution_provenance_contradiction",
        ),
    ],
)
def test_external_execution_manifest_contradictions_fail_closed(mutation, category: str) -> None:
    manifest = _manifest(circuit_status="unknown")
    mutation(manifest)
    with pytest.raises(StrictResultManifestError) as exc_info:
        normalize_strict_result_manifest(manifest, artifact_revisions={})
    assert exc_info.value.category == category


def test_current_result_requires_prepared_sampled_execution_evidence(tmp_path: Path) -> None:
    _source_and_circuit(tmp_path)
    begun, result_path = _run_step(tmp_path, attempt="native-attempt-insufficient")
    manifest = _manifest(attempt="native-attempt-insufficient")
    manifest["execution_configuration"] = {"status": "unknown"}
    result_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    before = deepcopy(CurrentLoopCoordinator(workspace_root=tmp_path).store.read())
    rejected = _complete(tmp_path, begun, result_path)
    assert rejected["ok"] is False
    assert rejected["category"] == "result_manifest_exact_execution_configuration_required"
    after = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert after == before
    assert after["latest_run_summary_reference"] is None


def test_result_step_contract_forbids_installation_and_requires_one_sampled_attempt(
    tmp_path: Path,
) -> None:
    _source_and_circuit(tmp_path)
    begun, _result_path = _run_step(tmp_path, attempt="native-attempt-contract")
    native = begun["current_step_contract"]["permitted_native_action"]
    execution = native["external_execution_contract"]
    assert execution == {
        "execution_owner": "native_client",
        "runtime": "already_prepared_and_prevalidated",
        "dependency_installation_permitted": False,
        "environment_mutation_permitted": False,
        "external_execution_attempts": "exactly_one",
        "required_method": "sampled_shots",
        "analytic_probability_substitution_permitted": False,
        "missing_runtime_disposition": "surface_blocker_without_execution",
        "qcoder_executes_customer_code": False,
    }
    artifact_contract = begun["current_step_contract"]["completion"]["artifact_contract"]
    assert artifact_contract["routine_success_customer_outcome"] == (
        "canonical_current_run_summary"
    )
    assert artifact_contract["qcoder_independently_verifies_external_execution"] is False
    happy_path = artifact_contract["contract"]["minimal_happy_path"]
    assert happy_path["execution_method"]["kind"] == "sampled_shots"
    assert happy_path["execution_configuration"]["status"] == "exact"
    assert happy_path["bit_register_ordering"]["status"] == "known"


def test_pennylane_manifest_rejects_nonfinite_parameters() -> None:
    with pytest.raises(FrameworkNativeEvidenceError) as exc_info:
        reconcile_framework_native_run(
            circuit={
                "schema_id": "qcoder.framework_native.circuit_manifest.v1",
                "schema_version": 1,
                "framework": "pennylane",
                "framework_version": "0.41",
                "wires": 1,
                "operations": [
                    {"name": "RX", "wires": [0], "parameters": [float("nan")]},
                ],
                "measurements": [{"kind": "counts", "wires": [0]}],
            },
            result=_manifest(circuit_status="unknown"),
            loop_ref="loop-" + "a" * 32,
            workspace_binding="/bounded/workspace",
            state_revision=1,
            contract_revision=1,
        )
    assert str(exc_info.value) == "framework_circuit_parameters_invalid"


def test_public_and_private_inventories_do_not_change() -> None:
    assert len(EXPECTED_TOOLS) == 12
    assert [item["name"] for item in binding_tool_descriptors()] == [
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
    ]


@pytest.mark.parametrize("adapter", ["cursor_desktop", "codex_cli_wsl2"])
def test_connected_client_adapter_converges_on_canonical_wi0435_semantics(
    tmp_path: Path, adapter: str
) -> None:
    root = tmp_path / adapter
    root.mkdir()
    _source_and_circuit(root)
    begun, result_path = _run_step(root, attempt="adapter-attempt-0001")
    assert _complete(root, begun, result_path)["ok"] is True
    state = CurrentLoopCoordinator(workspace_root=root).store.read()
    summary_reference = state["latest_run_summary_reference"]
    summary = json.loads(
        Path(state["run_summary_index"][summary_reference]["local_path"]).read_text(
            encoding="utf-8"
        )
    )
    projection = {
        "adapter_transport_only": adapter,
        "role_content_digests": {
            role: state["evidence_registry"]["artifact_revisions"][revision_id]["content_digest"]
            for role, revision_id in sorted(state["evidence_registry"]["role_heads"].items())
        },
        "manifest_schema": summary["evidence_reconciliation"]["schema_id"],
        "eligibility": summary["evidence_reconciliation"]["eligibility"],
        "relationships": sorted(
            item["relationship"] for item in summary["evidence_reconciliation"]["relationships"]
        ),
        "current_step_status": state["coordinator"]["current_step_status"],
        "bootstrap_count": state["coordinator"]["bootstrap_count"],
        "request_baseline_count": state["coordinator"]["request_baseline_count"],
        "native_execution_owned_by_qcoder": False,
        "client_classification_or_qualification_claimed": False,
    }
    (tmp_path / f"{adapter}.projection.json").write_text(
        json.dumps(projection, sort_keys=True), encoding="utf-8"
    )


def test_cursor_and_codex_adapter_projections_differ_only_by_transport_label(
    tmp_path: Path,
) -> None:
    for adapter in ("cursor_desktop", "codex_cli_wsl2"):
        test_connected_client_adapter_converges_on_canonical_wi0435_semantics(tmp_path, adapter)
    cursor = json.loads((tmp_path / "cursor_desktop.projection.json").read_text())
    codex = json.loads((tmp_path / "codex_cli_wsl2.projection.json").read_text())
    assert cursor.pop("adapter_transport_only") == "cursor_desktop"
    assert codex.pop("adapter_transport_only") == "codex_cli_wsl2"
    assert cursor == codex
