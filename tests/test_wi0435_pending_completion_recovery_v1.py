from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from qcoder.context_bridge_mcp import EXPECTED_TOOLS
from qcoder.current_loop_binding_mcp import (
    BEGIN_CURRENT_LOOP_TOOL_NAME,
    COMPLETE_CURRENT_STEP_TOOL_NAME,
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_pending_completion import (
    PendingCompletionError,
    validate_pending_completion_checkpoint,
)
from qcoder.current_loop_result_manifest import STRICT_RESULT_MANIFEST_SCHEMA_ID

SOURCE_REQUEST = "Use qCoder to write a Bell-state program. Stop after generating the code."
SOURCE = "from qiskit import QuantumCircuit\nqc=QuantumCircuit(2)\nqc.h(0)\nqc.cx(0,1)\n"
QASM = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\nh q[0];\ncx q[0],q[1];\n'


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


def _begin(root: Path, request: str, role: str, path: str) -> dict:
    result = _call(
        root,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {"request_text": request, "intended_artifact_paths": {role: path}},
    )
    assert result["ok"] is True, result
    return result


def _prepare_result_step(root: Path) -> tuple[dict, Path, bytes]:
    _begin(root, SOURCE_REQUEST, "source", "bell.py")
    (root / "bell.py").write_text(SOURCE, encoding="utf-8")
    assert _call(root, COMPLETE_CURRENT_STEP_TOOL_NAME, {})["ok"] is True
    _begin(root, "Now export the circuit as QASM. Do not run it.", "circuit_qasm", "bell.qasm")
    (root / "bell.qasm").write_text(QASM, encoding="utf-8")
    assert _call(root, COMPLETE_CURRENT_STEP_TOOL_NAME, {})["ok"] is True
    result_step = _begin(
        root,
        "Run the registered circuit locally with 2,000 shots and save exact result evidence.",
        "results",
        "result-2000.json",
    )
    execution = result_step["current_step_contract"]["permitted_native_action"][
        "external_execution_contract"
    ]
    manifest = {
        "schema_id": STRICT_RESULT_MANIFEST_SCHEMA_ID,
        "schema_version": 3,
        "manifestation": "exact_result",
        "counts": {"00": 1000, "11": 1000},
        "requested_shots": 2000,
        "observed_shots": 2000,
        "circuit_lineage": {"status": "current_step_contract"},
        "source_lineage": {"status": "not_supplied"},
        "execution_configuration": {
            "status": "exact",
            "reference": "prepared-aer-runtime",
            "settings": {"backend": "aer_simulator", "shots": 2000},
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
        "execution_attempt_id": execution["execution_attempt_identity"],
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
    raw = json.dumps(manifest, sort_keys=True).encode("utf-8")
    result_path = root / "result-2000.json"
    result_path.write_bytes(raw)
    return result_step, result_path, raw


def test_later_turn_direct_completion_and_restart_preserve_single_bootstrap(tmp_path: Path) -> None:
    _step, path, raw = _prepare_result_step(tmp_path)
    before = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert before["coordinator"]["pending_completion_checkpoint"]["status"] == "pending"
    assert before["coordinator"]["current_step_status"] == "awaiting_external_client_action"
    restarted_result = _call(tmp_path, COMPLETE_CURRENT_STEP_TOOL_NAME, {})
    assert restarted_result["ok"] is True
    assert restarted_result["current_step_status"] == "complete_resumable"
    assert restarted_result["current_run_summary"]["count_projection"]["observed_shots"] == 2000
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert path.read_bytes() == raw
    assert state["coordinator"]["bootstrap_count"] == 1
    assert state["coordinator"]["request_baseline_count"] == 1
    assert state["coordinator"]["pending_completion_checkpoint"] is None
    assert len(state["coordinator"]["pending_completion_history"]) == 3
    duplicate = _call(tmp_path, COMPLETE_CURRENT_STEP_TOOL_NAME, {})
    assert duplicate["ok"] is True
    assert duplicate["duplicate_delivery_noop"] is True


def test_compatible_begin_during_pending_only_projects_direct_completion(tmp_path: Path) -> None:
    _prepare_result_step(tmp_path)
    before = deepcopy(CurrentLoopCoordinator(workspace_root=tmp_path).store.read())
    resumed = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {"request_text": "Resume from the exact saved result. Do not run again."},
    )
    assert resumed["ok"] is True
    assert resumed["category"] == "pending_completion_already_active"
    assert resumed["pending_completion"] == {
        "checkpoint_digest": before["coordinator"]["pending_completion_checkpoint"][
            "checkpoint_digest"
        ],
        "sole_next_qcoder_operation": COMPLETE_CURRENT_STEP_TOOL_NAME,
        "canonical_arguments": {},
        "external_execution_rerun_permitted": False,
        "state_or_help_archaeology_required": False,
    }
    assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == before


def test_checkpoint_tampering_fails_without_completion_mutation(tmp_path: Path) -> None:
    _step, _path, _raw = _prepare_result_step(tmp_path)
    before = deepcopy(CurrentLoopCoordinator(workspace_root=tmp_path).store.read())

    def stale(value: dict) -> dict:
        value["coordinator"]["pending_completion_checkpoint"]["authority_state_revision"] -= 1
        return value

    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    coordinator.store.update(stale, expected_revision=before["state_revision"])
    tampered = deepcopy(coordinator.store.read())
    rejected = _call(tmp_path, COMPLETE_CURRENT_STEP_TOOL_NAME, {})
    assert rejected["ok"] is False
    assert rejected["category"] in {
        "pending_completion_checkpoint_invalid",
        "pending_completion_checkpoint_stale",
    }
    assert coordinator.store.read() == tampered


def test_private_surface_advertises_direct_pending_completion_without_new_tool() -> None:
    assert len(EXPECTED_TOOLS) == 12
    descriptors = binding_tool_descriptors()
    assert [item["name"] for item in descriptors] == [
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
    ]
    completion = descriptors[1]
    assert completion["inputSchema"]["required"] == []
    assert "pending completion" in completion["description"]


def test_missing_ambiguous_stale_cross_loop_and_cross_request_checkpoints_fail_closed(
    tmp_path: Path,
) -> None:
    _prepare_result_step(tmp_path)
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    state = coordinator.store.read()
    current = state["coordinator"]
    now = coordinator.clock()

    missing = deepcopy(current)
    missing["pending_completion_checkpoint"] = None
    with pytest.raises(PendingCompletionError, match="pending_completion_checkpoint_missing"):
        validate_pending_completion_checkpoint(state=state, coordinator=missing, current_time=now)

    ambiguous_state = deepcopy(state)
    receipt = next(
        value for value in state["operation_receipts"].values() if value.get("status") == "issued"
    )
    ambiguous_state["operation_receipts"]["second-issued"] = deepcopy(receipt)
    with pytest.raises(PendingCompletionError, match="pending_completion_checkpoint_ambiguous"):
        validate_pending_completion_checkpoint(
            state=ambiguous_state, coordinator=current, current_time=now
        )

    stale_state = deepcopy(state)
    stale_state["state_revision"] += 1
    with pytest.raises(PendingCompletionError, match="pending_completion_checkpoint_stale"):
        validate_pending_completion_checkpoint(
            state=stale_state, coordinator=current, current_time=now
        )

    cross_loop = deepcopy(state)
    cross_loop["loop_ref"] = "different-loop"
    with pytest.raises(PendingCompletionError, match="pending_completion_checkpoint_stale"):
        validate_pending_completion_checkpoint(
            state=cross_loop, coordinator=current, current_time=now
        )

    cross_request = deepcopy(current)
    cross_request["current_request_semantics"]["original_message_utf8_sha256"] = "f" * 64
    with pytest.raises(PendingCompletionError, match="pending_completion_checkpoint_stale"):
        validate_pending_completion_checkpoint(
            state=state, coordinator=cross_request, current_time=now
        )

    with pytest.raises(PendingCompletionError, match="operation_receipt_expired"):
        validate_pending_completion_checkpoint(
            state=state, coordinator=current, current_time=float(receipt["expires_at"]) + 1.0
        )
