from __future__ import annotations

from pathlib import Path

import pytest

from qcoder.context_loop import build_circuit_manifestation, build_result_manifestation
from qcoder.current_loop import read_run_summaries, save_run_summary
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_contract import new_contract
from qcoder.current_loop_run_summary import (
    EVIDENCE_VIEW_IDS,
    RUN_SUMMARY_MAX_TOP_OUTCOMES,
    RunSummaryError,
    build_evidence_view,
    build_run_summary,
    mark_run_summary_stale,
    run_summary_contract_snapshot,
    run_summary_error,
)
from tests.current_loop_test_support import activate_reviewed_legacy_fixture


QASM = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0],q[1];
measure q -> c;
"""


def _active(tmp_path: Path) -> CurrentLoopCoordinator:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    result = activate_reviewed_legacy_fixture(
        coordinator,
        original_request="Use qCoder to track this exact synthetic run.",
    )
    assert result["ok"] is True
    return coordinator


def _summary(coordinator: CurrentLoopCoordinator, *, outcomes: int = 2) -> dict:
    state = coordinator.store.read()
    circuit = build_circuit_manifestation(qasm_text=QASM, stage="logical_circuit")
    counts = {format(index, "08b"): index + 1 for index in range(outcomes)}
    result = build_result_manifestation(
        counts=counts,
        related_circuit_ref=circuit["artifact_ref"],
        user_provided_shots=sum(counts.values()),
    )
    return build_run_summary(
        loop_ref=state["loop_ref"],
        workspace_binding=state["workspace_root"],
        state_revision=state["state_revision"],
        contract_revision=state["current_loop_contract"]["contract_revision"],
        result_payload={
            "counts": counts,
            "shots": sum(counts.values()),
            "backend": "synthetic_local_simulator",
            "seed": 42,
            "bond_dimension": 16,
        },
        result_manifestation=result,
        circuit_manifestation=circuit,
        operation_lineage={
            "status": "recorded",
            "operation_receipt_id": "operation-receipt-synthetic",
            "activity_digest": "a" * 64,
        },
    )


def test_run_summary_is_bounded_execution_evidence(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    summary = _summary(coordinator, outcomes=20)
    assert run_summary_error(summary) is None
    assert summary["schema_id"] == "qcoder.current_loop.run_summary.v2"
    assert summary["blueprint_mutated"] is False
    assert summary["evolved_blueprint_created"] is False
    assert summary["raw_result_artifact_embedded"] is False
    assert summary["complete_raw_counts_embedded"] is False
    assert len(summary["count_projection"]["top_outcomes"]) == RUN_SUMMARY_MAX_TOP_OUTCOMES
    assert summary["count_projection"]["omitted_outcome_count"] == 12
    assert summary["execution_observations"]["backend"]["value"] == ("synthetic_local_simulator")
    assert summary["execution_observations"]["bond_dimension"]["value"] == 16
    assert "runtime_version" in summary["missing_execution_fields"]
    assert (
        summary["circuit_relationship"]["circuit_structure_proves_output_state_entanglement"]
        is False
    )


def test_summary_storage_is_exact_indexed_and_cross_loop_bound(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    summary = _summary(coordinator)
    state = coordinator.store.read()
    saved = save_run_summary(
        store=coordinator.store,
        summary=summary,
        destination=coordinator.artifact_directory / f"{summary['artifact_ref']}.json",
        expected_revision=state["state_revision"],
    )
    assert saved["artifact_reference"] == summary["artifact_ref"]
    state = coordinator.store.read()
    assert state["latest_run_summary_reference"] == summary["artifact_ref"]
    assert read_run_summaries(state) == [summary]
    replay = _summary(coordinator)
    replay["loop_ref"] = "loop-" + "b" * 32
    from qcoder.algorithm_blueprint import with_artifact_digest

    replay = with_artifact_digest(
        {key: value for key, value in replay.items() if key != "artifact_digest"}
    )
    with pytest.raises(Exception):
        save_run_summary(
            store=coordinator.store,
            summary=replay,
            destination=coordinator.artifact_directory / f"{replay['artifact_ref']}.json",
            expected_revision=state["state_revision"],
        )


def test_evidence_view_domain_answers_and_missing_evidence(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    state = coordinator.store.read()
    circuit = build_circuit_manifestation(qasm_text=QASM)
    summary = _summary(coordinator)
    all_views = {
        view: build_evidence_view(
            view_id=view,
            contract=state["current_loop_contract"],
            run_summaries=[summary],
            circuit_manifestation=circuit,
            baseline_reference="session-artifact-" + "a" * 32,
            evidence_limitations=[],
        )
        for view in EVIDENCE_VIEW_IDS
    }
    assert all_views["gate_count"]["answer"] == 2
    assert all_views["circuit_width"]["answer"] == 2
    assert all_views["circuit_depth"]["answer"] == 2
    assert all_views["execution_backend"]["answer"] == "synthetic_local_simulator"
    assert all_views["shot_count"]["answer"] == 3
    assert all_views["bond_dimension"]["answer"] == 16
    assert all_views["top_results"]["answer"]
    assert all_views["concise_loop_summary"]["answer"]["blueprint"] is False
    missing = build_evidence_view(
        view_id="top_results",
        contract=state["current_loop_contract"],
        run_summaries=[],
        circuit_manifestation=None,
        baseline_reference=None,
        evidence_limitations=["No authorized result."],
    )
    assert missing["status"] == "missing"
    assert "No authorized run result" in missing["answer"]


def test_multiple_run_requires_selection_and_stale_summary_is_honest(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    state = coordinator.store.read()
    first = _summary(coordinator)
    second = _summary(coordinator)
    ambiguous = build_evidence_view(
        view_id="top_results",
        contract=state["current_loop_contract"],
        run_summaries=[first, second],
        circuit_manifestation=None,
        baseline_reference=None,
        evidence_limitations=[],
    )
    assert ambiguous["status"] == "selection_required"
    selected = build_evidence_view(
        view_id="top_results",
        contract=state["current_loop_contract"],
        run_summaries=[first, second],
        circuit_manifestation=None,
        baseline_reference=None,
        evidence_limitations=[],
        selected_run_reference=second["artifact_ref"],
    )
    assert selected["status"] == "available"
    stale = mark_run_summary_stale(first, reasons=["source_evidence_excluded"])
    assert stale["freshness"]["status"] == "stale"
    assert run_summary_error(stale) is None


def test_exclude_restore_delete_updates_dependent_summary_integrity(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    circuit = build_circuit_manifestation(qasm_text=QASM)
    result = build_result_manifestation(
        counts={"00": 2, "11": 2},
        related_circuit_ref=circuit["artifact_ref"],
        user_provided_shots=4,
    )
    coordinator._save_artifact("circuit_manifestation", circuit, "circuit-manifestation.json")
    coordinator._save_artifact("result_manifestation", result, "result-manifestation.json")
    state = coordinator.store.read()
    summary = build_run_summary(
        loop_ref=state["loop_ref"],
        workspace_binding=state["workspace_root"],
        state_revision=state["state_revision"],
        contract_revision=state["current_loop_contract"]["contract_revision"],
        result_payload={"counts": {"00": 2, "11": 2}, "shots": 4},
        result_manifestation=result,
        circuit_manifestation=circuit,
    )
    save_run_summary(
        store=coordinator.store,
        summary=summary,
        destination=coordinator.artifact_directory / f"{summary['artifact_ref']}.json",
        expected_revision=state["state_revision"],
    )
    state = coordinator.store.read()
    excluded = coordinator.evidence_exclude(
        artifact_reference=result["artifact_ref"],
        reason="customer_excluded",
        expected_contract_revision=state["current_loop_contract"]["contract_revision"],
    )
    assert excluded["ok"] is True
    stale = read_run_summaries(coordinator.store.read())[0]
    assert stale["freshness"]["status"] == "stale"
    state = coordinator.store.read()
    restored = coordinator.evidence_restore(
        artifact_reference=result["artifact_ref"],
        expected_contract_revision=state["current_loop_contract"]["contract_revision"],
    )
    assert restored["ok"] is True
    refreshed = read_run_summaries(coordinator.store.read())[0]
    assert refreshed["freshness"]["status"] == "fresh"
    state = coordinator.store.read()
    deleted = coordinator.evidence_delete(
        artifact_reference=result["artifact_ref"],
        expected_contract_revision=state["current_loop_contract"]["contract_revision"],
        explicit_authority=True,
    )
    assert deleted["ok"] is True
    after_delete = read_run_summaries(coordinator.store.read())[0]
    assert after_delete["freshness"]["status"] == "stale"
    assert result["artifact_ref"] not in {
        descriptor["artifact_reference"]
        for descriptor in coordinator.store.read()["saved_artifacts"].values()
    }


def test_summary_contract_has_no_optimization_or_raw_boundary() -> None:
    contract = run_summary_contract_snapshot()
    assert contract["raw_result_artifact_embedded"] is False
    assert contract["cross_loop_evidence"] is False
    with pytest.raises(RunSummaryError):
        build_evidence_view(
            view_id="invent_backend",
            contract=new_contract(
                baseline_digest="a" * 64,
                capture_provenance="exact_current_customer_message",
                activation_revision=1,
            ),
            run_summaries=[],
            circuit_manifestation=None,
            baseline_reference=None,
            evidence_limitations=[],
        )
