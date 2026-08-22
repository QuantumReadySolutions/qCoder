from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

import qcoder.current_loop_coordinator as coordinator_module
import qcoder.current_loop_result_controls as result_controls_module
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
    bound_attempt = begun["current_step_contract"]["permitted_native_action"][
        "external_execution_contract"
    ]["execution_attempt_identity"]
    result_path = root / f"{attempt}.json"
    result_path.write_text(
        json.dumps(_manifest(attempt=bound_attempt), sort_keys=True), encoding="utf-8"
    )
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


def test_active_loop_replacement_reuses_registered_targets_and_reports_currentness(
    tmp_path: Path,
) -> None:
    _source_and_circuit(tmp_path)
    begun, result_path = _run_step(tmp_path)
    assert _complete(tmp_path, begun, result_path)["ok"] is True
    before = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    old_heads = deepcopy(before["evidence_registry"]["role_heads"])
    old_summaries = set(before["run_summary_index"])
    baseline_descriptor = deepcopy(before["saved_artifacts"]["request_baseline"])

    source_request = (
        "Change the Python source to prepare a Ψ+ Bell state. Stop after the source; "
        "then tell me whether the earlier circuit and result remain current and preserve "
        "their history."
    )
    source_step = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {"request_text": source_request},
    )
    assert source_step["ok"] is True, source_step
    active_source_semantics = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()[
        "coordinator"
    ]["current_request_semantics"]
    assert active_source_semantics["requested_operation"] == "source_generation"
    assert active_source_semantics["currentness_projection_requested"] is True
    assert source_step["details"]["active_loop_target_continuity"]["source"] == {
        "binding_mode": "registered_current_role_head_exact_target",
        "artifact_revision_id": old_heads["source"],
        "workspace_discovery_performed": False,
    }
    target = source_step["current_step_contract"]["permitted_native_action"][
        "exact_artifact_target"
    ]
    assert target["workspace_relative_path"] == "bell.py"
    assert target["selection"] == "registered_current_role_head_no_discovery"
    assert target["replacement_target_model_selection_required"] is False
    (tmp_path / "bell.py").write_text(SOURCE + "circuit.x(0)\n", encoding="utf-8")
    source_completed = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {"artifact_disposition": "assistant_modified"},
    )
    assert source_completed["ok"] is True, source_completed
    assert source_completed["causal_currentness"]["active_goal_eligibility"] == {
        "source": True,
        "circuit_qasm": False,
        "results": False,
        "current_run_summary": False,
    }
    assert source_completed["causal_currentness"]["history_deleted_or_rewritten"] is False

    after_source = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert after_source["coordinator"]["bootstrap_count"] == 1
    assert after_source["coordinator"]["request_baseline_count"] == 1
    assert after_source["saved_artifacts"]["request_baseline"] == baseline_descriptor
    assert (
        after_source["evidence_registry"]["role_heads"]["circuit_qasm"] == old_heads["circuit_qasm"]
    )
    assert after_source["evidence_registry"]["role_heads"]["results"] == old_heads["results"]
    assert old_summaries.issubset(after_source["run_summary_index"])
    assert after_source["latest_run_summary_reference"] is None

    qasm_request = (
        "Export the updated circuit as QASM. Do not run it; then tell me whether the "
        "earlier result is current for this new circuit."
    )
    qasm_step = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {"request_text": qasm_request},
    )
    assert qasm_step["ok"] is True, qasm_step
    active_qasm_semantics = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()[
        "coordinator"
    ]["current_request_semantics"]
    assert active_qasm_semantics["requested_operation"] == "qasm_export"
    assert (
        qasm_step["current_step_contract"]["permitted_native_action"]["exact_artifact_target"][
            "workspace_relative_path"
        ]
        == "bell.qasm"
    )
    (tmp_path / "bell.qasm").write_text(
        QASM.replace("h q[0];", "x q[0];\nh q[0];"), encoding="utf-8"
    )
    qasm_completed = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {"artifact_disposition": "assistant_modified"},
    )
    assert qasm_completed["ok"] is True, qasm_completed
    assert qasm_completed["causal_currentness"]["active_goal_eligibility"]["results"] is False
    assert qasm_completed["causal_currentness"]["historical_run_summaries_preserved"] >= 1
    after_qasm = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert after_qasm["evidence_registry"]["role_heads"]["results"] == old_heads["results"]
    assert after_qasm["latest_run_summary_reference"] is None


@pytest.mark.parametrize(
    ("target", "category"),
    [
        ("neighbor.py", "active_loop_replacement_target_requires_exact_customer_selection"),
        ("../escape.py", "intended_artifact_path_must_be_workspace_relative"),
        ("*.py", "intended_artifact_path_discovery_expression_prohibited"),
    ],
)
def test_active_loop_replacement_target_mismatch_fails_before_mutation(
    tmp_path: Path, target: str, category: str
) -> None:
    source_step = _begin(tmp_path, SOURCE_REQUEST)
    source = tmp_path / "bell.py"
    source.write_text(SOURCE, encoding="utf-8")
    assert _complete(tmp_path, source_step, source)["ok"] is True
    before = (tmp_path / ".qcoder" / "current-loop" / "state.json").read_bytes()
    result = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": "Change the Python source to prepare a Ψ+ Bell state.",
            "intended_artifact_paths": {"source": target},
        },
    )
    assert result["ok"] is False
    assert result["category"] == category
    assert result["state_mutated"] is False
    assert (tmp_path / ".qcoder" / "current-loop" / "state.json").read_bytes() == before


def test_active_loop_replacement_explicitly_named_new_target_is_bounded(
    tmp_path: Path,
) -> None:
    source_step = _begin(tmp_path, SOURCE_REQUEST)
    source = tmp_path / "bell.py"
    source.write_text(SOURCE, encoding="utf-8")
    assert _complete(tmp_path, source_step, source)["ok"] is True
    result = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": "Replace the Python source at replacement.py and stop after source.",
            "intended_artifact_paths": {"source": "replacement.py"},
        },
    )
    assert result["ok"] is True, result
    assert (
        result["current_step_contract"]["permitted_native_action"]["exact_artifact_target"][
            "workspace_relative_path"
        ]
        == "replacement.py"
    )
    active_semantics = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()["coordinator"][
        "current_request_semantics"
    ]
    assert active_semantics["execution_disposition"] == ("prohibited_for_current_step")


def test_active_loop_matching_current_target_does_not_become_file_review(
    tmp_path: Path,
) -> None:
    source_step = _begin(tmp_path, SOURCE_REQUEST)
    source = tmp_path / "bell.py"
    source.write_text(SOURCE, encoding="utf-8")
    assert _complete(tmp_path, source_step, source)["ok"] is True
    result = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": (
                "Change the Python source to prepare a Ψ+ Bell state. Stop after the source; "
                "then tell me whether the earlier circuit and result remain current and "
                "preserve their history."
            ),
            "intended_artifact_paths": {"source": "bell.py"},
        },
    )
    assert result["ok"] is True, result
    assert result.get("customer_summary") != "Which exact files should qCoder review?"
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert state["coordinator"]["current_request_semantics"]["requested_operation"] == (
        "source_generation"
    )


def test_active_loop_replacement_refuses_aliased_or_changed_current_head(
    tmp_path: Path,
) -> None:
    source_step = _begin(tmp_path, SOURCE_REQUEST)
    source = tmp_path / "bell.py"
    source.write_text(SOURCE, encoding="utf-8")
    assert _complete(tmp_path, source_step, source)["ok"] is True
    before = (tmp_path / ".qcoder" / "current-loop" / "state.json").read_bytes()
    outside = tmp_path / "outside.py"
    outside.write_text(SOURCE, encoding="utf-8")
    source.unlink()
    source.symlink_to(outside)
    result = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {"request_text": "Change the Python source to prepare a Ψ+ Bell state."},
    )
    assert result["ok"] is False
    assert result["category"] == "current_role_target_file_unavailable"
    assert result["state_mutated"] is False
    assert (tmp_path / ".qcoder" / "current-loop" / "state.json").read_bytes() == before


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
    value = _manifest(
        attempt=begun["current_step_contract"]["permitted_native_action"][
            "external_execution_contract"
        ]["execution_attempt_identity"],
        circuit_status="unknown",
    )
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


LINEAGE_CONTROL_REQUEST = (
    "Use qCoder to evaluate the exact selected files fixtures/bare-counts.json and "
    "fixtures/unknown-result-manifest.json as result evidence controls. Do not execute "
    "anything, infer lineage, or claim either belongs to the registered circuit."
)


def _selected_control_fixtures(root: Path, *, attempt: str = "selected-control-unknown") -> None:
    fixtures = root / "fixtures"
    fixtures.mkdir(exist_ok=True)
    (fixtures / "bare-counts.json").write_text(
        json.dumps({"00": 8, "11": 8}, sort_keys=True), encoding="utf-8"
    )
    (fixtures / "unknown-result-manifest.json").write_text(
        json.dumps(_manifest(attempt=attempt, circuit_status="unknown", shots=32), sort_keys=True),
        encoding="utf-8",
    )


def test_exact_two_selected_result_controls_are_bounded_read_only_terminal_projection(
    tmp_path: Path,
) -> None:
    _source_and_circuit(tmp_path)
    begun, result_path = _run_step(tmp_path)
    assert _complete(tmp_path, begun, result_path)["ok"] is True
    _selected_control_fixtures(tmp_path)
    before = deepcopy(CurrentLoopCoordinator(workspace_root=tmp_path).store.read())
    response = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": LINEAGE_CONTROL_REQUEST,
            "selected_artifact_paths": [
                "fixtures/bare-counts.json",
                "fixtures/unknown-result-manifest.json",
            ],
        },
    )
    assert response["ok"] is True, response
    assert response["operation"] == "evaluate_selected_result_evidence_controls"
    assert response["selected_artifact_count"] == 2
    assert response["execution_performed"] is False
    assert response["state_mutated"] is False
    assert response["workspace_discovery_performed"] is False
    assert response["cli_or_help_required"] is False
    assert response["package_or_state_inspection_required"] is False
    assert [item["disposition"] for item in response["controls"]] == [
        "strict_manifest_and_causal_lineage_required",
        "explicit_selected_historical_non_current_only",
    ]
    assert response["controls"][0]["valid_result_evidence"] is False
    assert response["controls"][1]["circuit_lineage_status"] == "unknown"
    assert all(item["current_result_evidence"] is False for item in response["controls"])
    assert all(item["registered"] is False for item in response["controls"])
    assert (
        response["current_result"]["artifact_revision_id"]
        == before["evidence_registry"]["role_heads"]["results"]
    )
    assert response["current_result"]["unchanged"] is True
    assert response["current_request_semantics"]["requested_operation"] == (
        "selected_result_evidence_controls"
    )
    assert response["current_request_semantics"]["execution_disposition"] == (
        "prohibited_for_current_step"
    )
    assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == before

    replay = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": LINEAGE_CONTROL_REQUEST,
            "selected_artifact_paths": [
                "fixtures/bare-counts.json",
                "fixtures/unknown-result-manifest.json",
            ],
        },
    )
    assert replay["projection_digest"] == response["projection_digest"]
    assert replay["state_mutated"] is False
    assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == before


@pytest.mark.parametrize(
    ("paths", "category"),
    [
        (["fixtures/bare-counts.json"], "exact_selected_artifact_path_count_invalid"),
        (
            ["fixtures/bare-counts.json", "fixtures/bare-counts.json"],
            "selected_artifact_duplicate_path",
        ),
        (
            ["../bare-counts.json", "fixtures/unknown-result-manifest.json"],
            "intended_artifact_path_must_be_workspace_relative",
        ),
        (
            ["fixtures/*.json", "fixtures/unknown-result-manifest.json"],
            "intended_artifact_path_discovery_expression_prohibited",
        ),
        (
            ["/tmp/bare-counts.json", "fixtures/unknown-result-manifest.json"],
            "intended_artifact_path_must_be_workspace_relative",
        ),
        (
            ["fixtures/bare-counts.json", "fixtures/missing.json"],
            "selected_artifact_exact_file_required",
        ),
        (
            [
                "fixtures/bare-counts.json",
                "fixtures/unknown-result-manifest.json",
                "fixtures/surplus.json",
            ],
            "exact_selected_artifact_path_count_invalid",
        ),
    ],
)
def test_selected_result_control_path_failures_preserve_state(
    tmp_path: Path, paths: list[str], category: str
) -> None:
    _source_and_circuit(tmp_path)
    _selected_control_fixtures(tmp_path)
    (tmp_path / "fixtures" / "surplus.json").write_text("{}", encoding="utf-8")
    before = deepcopy(CurrentLoopCoordinator(workspace_root=tmp_path).store.read())
    response = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {"request_text": LINEAGE_CONTROL_REQUEST, "selected_artifact_paths": paths},
    )
    assert response["ok"] is False
    assert response["category"] == category
    assert response["state_mutated"] is False
    assert response["workspace_discovery_permitted"] is False
    assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == before


def test_selected_result_control_changed_bytes_fail_before_state_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source_and_circuit(tmp_path)
    _selected_control_fixtures(tmp_path)
    before = deepcopy(CurrentLoopCoordinator(workspace_root=tmp_path).store.read())
    original_read = result_controls_module._read_exact
    calls = 0

    def changed_between_validation_reads(path: Path) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 3:
            (tmp_path / "fixtures" / "bare-counts.json").write_text(
                json.dumps({"00": 7, "11": 9}, sort_keys=True), encoding="utf-8"
            )
        return original_read(path)

    monkeypatch.setattr(result_controls_module, "_read_exact", changed_between_validation_reads)
    response = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": LINEAGE_CONTROL_REQUEST,
            "selected_artifact_paths": [
                "fixtures/bare-counts.json",
                "fixtures/unknown-result-manifest.json",
            ],
        },
    )
    assert response["ok"] is False
    assert response["category"] == "selected_result_control_bytes_changed"
    assert response["state_mutated"] is False
    assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == before


def test_selected_result_controls_reject_neighbor_symlink_false_lineage_and_prior_attempt(
    tmp_path: Path,
) -> None:
    _source_and_circuit(tmp_path)
    registered_step, registered_path = _run_step(tmp_path, attempt="already-registered")
    assert _complete(tmp_path, registered_step, registered_path)["ok"] is True
    registered_state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    registered_attempt = registered_state["evidence_registry"]["artifact_revisions"][
        registered_state["evidence_registry"]["role_heads"]["results"]
    ]["strict_result_manifest_binding"]["execution_attempt_id"]
    _selected_control_fixtures(tmp_path, attempt=registered_attempt)
    fixtures = tmp_path / "fixtures"
    (fixtures / "neighbor.json").write_text(
        (fixtures / "unknown-result-manifest.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    outside = tmp_path / "outside.json"
    outside.write_text(
        (fixtures / "unknown-result-manifest.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (fixtures / "linked.json").symlink_to(outside)
    before = deepcopy(CurrentLoopCoordinator(workspace_root=tmp_path).store.read())
    cases = [
        (
            ["fixtures/bare-counts.json", "fixtures/neighbor.json"],
            "selected_result_control_path_not_named_by_customer",
        ),
        (
            ["fixtures/bare-counts.json", "fixtures/linked.json"],
            "selected_artifact_exact_file_required",
        ),
        (
            ["fixtures/bare-counts.json", "fixtures/unknown-result-manifest.json"],
            "selected_result_control_attempt_already_registered",
        ),
    ]
    for paths, category in cases:
        response = _call(
            tmp_path,
            BEGIN_CURRENT_LOOP_TOOL_NAME,
            {"request_text": LINEAGE_CONTROL_REQUEST, "selected_artifact_paths": paths},
        )
        assert response["ok"] is False
        assert response["category"] == category
        assert response["state_mutated"] is False
        assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == before

    false_manifest = _manifest(attempt="selected-control-false", circuit_status="unknown")
    false_manifest["circuit_lineage"] = {
        "status": "exact",
        "artifact_revision_id": before["evidence_registry"]["role_heads"]["circuit_qasm"],
        "content_digest": "f" * 64,
    }
    (fixtures / "unknown-result-manifest.json").write_text(
        json.dumps(false_manifest, sort_keys=True), encoding="utf-8"
    )
    false = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": LINEAGE_CONTROL_REQUEST,
            "selected_artifact_paths": [
                "fixtures/bare-counts.json",
                "fixtures/unknown-result-manifest.json",
            ],
        },
    )
    assert false["ok"] is False
    assert false["category"] == "result_manifest_false_circuit_lineage"
    assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == before


def test_natural_preexisting_source_selection_binds_and_completes_without_write(
    tmp_path: Path,
) -> None:
    initial = _begin(tmp_path, SOURCE_REQUEST)
    (tmp_path / "bell.py").write_text(SOURCE, encoding="utf-8")
    assert _complete(tmp_path, initial, tmp_path / "bell.py")["ok"] is True
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    selected = fixtures / "preexisting_bell.py"
    selected.write_text(SOURCE, encoding="utf-8")
    before = (selected.read_bytes(), selected.stat().st_mtime_ns, selected.stat().st_mode)
    request = (
        "Use qCoder for a source-only Bell step. The exact selected file "
        "fixtures/preexisting_bell.py already exists; if it satisfies the source role, "
        "accept it without rewriting it or claiming the assistant created it."
    )
    begun = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": request,
            "selected_artifact_paths": ["fixtures/preexisting_bell.py"],
        },
    )
    assert begun["ok"] is True, begun
    action = begun["current_step_contract"]["permitted_native_action"]
    assert action["native_write_required"] is False
    assert action["preexisting_exact_artifact_satisfaction"] is True
    assert action["exact_artifact_target"]["workspace_relative_path"] == (
        "fixtures/preexisting_bell.py"
    )
    completed = _call(tmp_path, COMPLETE_CURRENT_STEP_TOOL_NAME, {})
    assert completed["ok"] is True, completed
    after = (selected.read_bytes(), selected.stat().st_mtime_ns, selected.stat().st_mode)
    assert after == before
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    revision = state["evidence_registry"]["artifact_revisions"][
        state["evidence_registry"]["role_heads"]["source"]
    ]
    assert revision["event_disposition"] == "selected"
    assert state["coordinator"]["bootstrap_count"] == 1
    assert state["coordinator"]["request_baseline_count"] == 1


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
        json.dumps(
            _manifest(
                attempt=second_step["current_step_contract"]["permitted_native_action"][
                    "external_execution_contract"
                ]["execution_attempt_identity"],
                shots=2_000,
            ),
            sort_keys=True,
        ),
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
        json.dumps(
            _manifest(
                attempt=first_step["current_step_contract"]["permitted_native_action"][
                    "external_execution_contract"
                ]["execution_attempt_identity"]
            ),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    rejected = _complete(tmp_path, second_step, second_path)
    assert rejected["ok"] is False
    assert rejected["category"] == "result_manifest_execution_attempt_mismatch"


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
    changed = _manifest(
        attempt=changed_step["current_step_contract"]["permitted_native_action"][
            "external_execution_contract"
        ]["execution_attempt_identity"]
    )
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
    manifest = _manifest(
        attempt=begun["current_step_contract"]["permitted_native_action"][
            "external_execution_contract"
        ]["execution_attempt_identity"]
    )
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
        "execution_attempt_identity": execution["execution_attempt_identity"],
        "requested_shots": 1_024,
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
    _selected_control_fixtures(root, attempt=f"{adapter}-unknown-control")
    controls = _call(
        root,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": LINEAGE_CONTROL_REQUEST,
            "selected_artifact_paths": [
                "fixtures/bare-counts.json",
                "fixtures/unknown-result-manifest.json",
            ],
        },
    )
    assert controls["ok"] is True
    assert controls["state_mutated"] is False
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
        "selected_result_control_dispositions": [
            item["disposition"] for item in controls["controls"]
        ],
        "selected_result_control_current_result_unchanged": controls["current_result"]["unchanged"],
        "selected_result_control_execution_performed": controls["execution_performed"],
        "selected_result_control_workspace_discovery_performed": controls[
            "workspace_discovery_performed"
        ],
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
