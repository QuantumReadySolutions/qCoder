from __future__ import annotations

from copy import deepcopy
from itertools import permutations
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from qcoder.algorithm_blueprint import with_artifact_digest
from qcoder.current_loop import (
    CurrentLoopStore,
    activate_current_loop,
    propose_selected_artifact_authorization,
    set_artifact_authorization,
    update_selected_artifact_authorization,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_evidence_processing import (
    ARTIFACT_FORMAT_CONTRACT_SCHEMA_ID,
    EvidenceProcessingError,
    artifact_format_contract_snapshot,
    detect_exact_artifact_format,
    evidence_processing_contract_snapshot,
    failure_provenance,
    recovery_action_contract_snapshot,
    registration_format_outcome,
)
from qcoder.current_loop_invocation import (
    HOSTED_CAPABLE,
    LOCAL_ONLY,
    operation_transport_inventory,
)


class RejectingProtectedTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        self.calls.append((tool_name, deepcopy(dict(arguments))))
        return {"ok": False, "error_category": "protected_authority_missing"}


class RejectSecondProtectedTransport(RejectingProtectedTransport):
    def call(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        self.calls.append((tool_name, deepcopy(dict(arguments))))
        if len(self.calls) == 1:
            return {
                "ok": True,
                "result_review_context_card": with_artifact_digest(
                    {
                        "artifact_type": "result_review_context_card",
                        "artifact_ref": "session-artifact-" + "b" * 16,
                        "share_safe": True,
                    }
                ),
            }
        return {"ok": False, "error_category": "protected_authority_missing"}


def _write_artifacts(workspace: Path, *, qasm_version: int) -> list[dict[str, Any]]:
    source = workspace / "program.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    qasm = workspace / "circuit.qasm"
    qasm.write_text(
        ('OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\n')
        if qasm_version == 2
        else 'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nh q[0];\ncx q[0],q[1];\n',
        encoding="utf-8",
    )
    results = workspace / "results.json"
    results.write_text(
        json.dumps(
            {
                "counts": {"00": 500, "11": 524},
                "shots": 1024,
                "backend": "local_simulator",
            }
        ),
        encoding="utf-8",
    )
    return [
        {"artifact_role": "source", "artifact_type": "source", "local_path": str(source)},
        {
            "artifact_role": "circuit_qasm",
            "artifact_type": "circuit_qasm",
            "local_path": str(qasm),
        },
        {"artifact_role": "results", "artifact_type": "results", "local_path": str(results)},
    ]


def _processing_coordinator(
    tmp_path: Path,
    *,
    qasm_version: int,
    transport: RejectingProtectedTransport | None = None,
    role_order: tuple[str, ...] = ("source", "circuit_qasm", "results"),
) -> CurrentLoopCoordinator:
    workspace = tmp_path / f"qasm-{qasm_version}"
    workspace.mkdir()
    activate_current_loop(
        workspace_root=workspace,
        generation_posture="exploratory_first_pass",
        explicit_authority=True,
        request_baseline_digest="a" * 64,
    )
    store = CurrentLoopStore.for_workspace(workspace)
    state = store.read()
    artifacts = _write_artifacts(workspace, qasm_version=qasm_version)
    by_role = {item["artifact_role"]: item for item in artifacts}
    proposed = propose_selected_artifact_authorization(
        loop_ref=str(state["loop_ref"]),
        proposed_artifacts=[by_role[role] for role in role_order],
    )
    approved = update_selected_artifact_authorization(
        proposed,
        action="approve_all",
        explicit_action_provenance="direct_user_action",
    )
    state = set_artifact_authorization(
        store=store,
        authorization=approved,
        expected_revision=int(state["state_revision"]),
    )
    coordinator = CurrentLoopCoordinator(
        workspace_root=workspace,
        transport=transport,
    )
    protocol = coordinator._initial_coordinator_state(
        phase="evidence_processing",
        state_status="ready",
        checkpoint_kind="none",
        summary="Exact artifacts are authorized.",
    )
    current = coordinator.store.read()

    def set_protocol(value: dict[str, Any]) -> Mapping[str, Any]:
        value["coordinator"] = deepcopy(protocol)
        return value

    coordinator.store.update(set_protocol, expected_revision=int(current["state_revision"]))
    return coordinator


def test_format_contract_is_client_visible_and_qasm2_only_for_structural_analysis(
    tmp_path: Path,
) -> None:
    snapshot = artifact_format_contract_snapshot()
    assert snapshot["schema_id"] == ARTIFACT_FORMAT_CONTRACT_SCHEMA_ID
    circuit = next(row for row in snapshot["roles"] if row["role"] == "circuit_qasm")
    assert circuit["accepted_automatic_registration_formats"] == ["openqasm_2"]
    assert circuit["local_derivation_formats"] == ["openqasm_2"]
    assert circuit["producer_requirements"]["header"] == "OPENQASM 2.0;"
    qasm2 = tmp_path / "two.qasm"
    qasm3 = tmp_path / "three.qasm"
    qasm2.write_text("OPENQASM 2.0;\nqreg q[1];\n", encoding="utf-8")
    qasm3.write_text("OPENQASM 3.0;\nqubit q;\n", encoding="utf-8")
    assert detect_exact_artifact_format(qasm2, "circuit_qasm") == "openqasm_2"
    assert detect_exact_artifact_format(qasm3, "circuit_qasm") == "openqasm_3"
    outcome = registration_format_outcome(
        path=qasm3,
        role="circuit_qasm",
        provenance="assistant_operation_receipt",
    )
    assert outcome["automatic_registration_supported"] is False
    assert outcome["registration_disposition"] == "unsupported_format"
    assert outcome["exact_declared_artifact_only"] is True


def test_qiskit_qasm2_and_qasm3_serializations_are_distinguished(tmp_path: Path) -> None:
    qiskit = pytest.importorskip("qiskit")
    qasm2 = pytest.importorskip("qiskit.qasm2")
    qasm3 = pytest.importorskip("qiskit.qasm3")
    circuit = qiskit.QuantumCircuit(2, 2)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.measure([0, 1], [0, 1])
    qasm2_path = tmp_path / "qiskit-two.qasm"
    qasm3_path = tmp_path / "qiskit-three.qasm"
    qasm2_path.write_text(qasm2.dumps(circuit), encoding="utf-8")
    qasm3_path.write_text(qasm3.dumps(circuit), encoding="utf-8")
    assert detect_exact_artifact_format(qasm2_path, "circuit_qasm") == "openqasm_2"
    assert detect_exact_artifact_format(qasm3_path, "circuit_qasm") == "openqasm_3"


def test_qasm3_isolated_local_processing_keeps_result_and_run_summary(
    tmp_path: Path,
) -> None:
    coordinator = _processing_coordinator(tmp_path, qasm_version=3)
    result = coordinator.process_authorized_artifacts()
    assert result["ok"] is True
    assert result["details"]["local_processing"] == {
        "transport": LOCAL_ONLY,
        "protected_calls_attempted": 0,
        "per_item_isolation": True,
        "successful_outcomes_persisted": True,
    }
    by_role = {item["role"]: item for item in result["details"]["per_item_outcomes"]}
    assert by_role["source"]["status"] == "completed"
    assert by_role["circuit_qasm"]["status"] == "unsupported_format"
    assert by_role["circuit_qasm"]["safe_error_category"] == "circuit_format_unsupported"
    assert by_role["results"]["status"] == "completed"
    assert result["details"]["run_summary"]["automatic_preparation"] is True
    state = coordinator.store.read()
    assert "result_manifestation" in state["saved_artifacts"]
    assert state["latest_run_summary_reference"] is None
    assert len(state["run_summary_index"]) == 1
    descriptor = next(iter(state["run_summary_index"].values()))
    assert descriptor["currency"] == "prior"
    assert "circuit_manifestation" not in state["saved_artifacts"]
    assert state["hosted_enrichment"]["status"] == "available"
    summary = json.loads(Path(descriptor["local_path"]).read_text(encoding="utf-8"))
    assert any(
        "Circuit structural evidence is unavailable" in limitation
        for limitation in summary["limitations"]
    )
    assert summary["circuit_relationship"]["structural_metrics_reused_by_reference"] is False
    recovery = result["details"]["recovery_contract"]
    assert recovery["zero_non_executable_alternatives"] is True
    assert {item["action"] for item in recovery["alternatives"]} == {
        "continue_with_limitations",
        "provide_supported_circuit_artifact",
        "skip_current_artifact_derivation",
        "stop_loop",
    }


@pytest.mark.parametrize(
    "role_order",
    list(permutations(("source", "circuit_qasm", "results"))),
)
def test_qasm3_per_item_isolation_is_order_independent(
    tmp_path: Path,
    role_order: tuple[str, ...],
) -> None:
    coordinator = _processing_coordinator(
        tmp_path,
        qasm_version=3,
        role_order=role_order,
    )
    result = coordinator.process_authorized_artifacts()
    assert result["ok"] is True
    outcomes = {item["role"]: item["status"] for item in result["details"]["per_item_outcomes"]}
    assert outcomes == {
        "source": "completed",
        "circuit_qasm": "unsupported_format",
        "results": "completed",
    }
    state = coordinator.store.read()
    assert state["latest_run_summary_reference"] is None
    assert len(state["run_summary_index"]) == 1


def test_qasm2_full_local_processing_and_no_hosted_call(tmp_path: Path) -> None:
    transport = RejectingProtectedTransport()
    coordinator = _processing_coordinator(
        tmp_path,
        qasm_version=2,
        transport=transport,
    )
    result = coordinator.process_authorized_artifacts()
    assert result["ok"] is True
    assert transport.calls == []
    assert {item["status"] for item in result["details"]["per_item_outcomes"]} == {"completed"}
    assert "circuit_manifestation" in coordinator.store.read()["saved_artifacts"]
    assert result["details"]["run_summary"]["automatic_preparation"] is True


def test_hosted_rejection_preserves_local_evidence_and_has_executable_skip(
    tmp_path: Path,
) -> None:
    transport = RejectingProtectedTransport()
    coordinator = _processing_coordinator(
        tmp_path,
        qasm_version=2,
        transport=transport,
    )
    coordinator.process_authorized_artifacts()
    before = coordinator.store.read()
    result_ref = before["saved_artifacts"]["result_manifestation"]["artifact_digest"]
    summary_ref = before["latest_run_summary_reference"]
    rejected = coordinator.enrich_authorized_evidence()
    assert rejected["ok"] is False
    assert rejected["details"]["failure_provenance"] == {
        "schema_id": "qcoder.current_loop.failure_provenance.v1",
        "schema_version": 1,
        "origin": "hosted_operation",
        "safe_category": "protected_authority_missing",
        "protected_call_attempted": True,
        "protected_non_success": True,
    }
    after = coordinator.store.read()
    assert after["saved_artifacts"]["result_manifestation"]["artifact_digest"] == result_ref
    assert after["latest_run_summary_reference"] == summary_ref
    assert after["hosted_enrichment"]["status"] == "rejected"
    alternatives = rejected["details"]["recovery_contract"]["alternatives"]
    skip = next(item for item in alternatives if item["action"] == "skip_hosted_enrichment")
    invocation = skip["invocation"]
    assert invocation["transport_classification"] == LOCAL_ONLY
    assert invocation["operation"] == "execute_recovery_action"


def test_second_hosted_call_failure_preserves_first_enrichment_and_local_summary(
    tmp_path: Path,
) -> None:
    transport = RejectSecondProtectedTransport()
    coordinator = _processing_coordinator(
        tmp_path,
        qasm_version=2,
        transport=transport,
    )
    coordinator.process_authorized_artifacts()
    coordinator._save_artifact(
        "working_blueprint",
        with_artifact_digest(
            {
                "artifact_type": "implementation_blueprint",
                "artifact_ref": "session-artifact-" + "c" * 16,
            }
        ),
        "working-blueprint.json",
    )
    coordinator._save_artifact(
        "output_evidence_contract",
        with_artifact_digest(
            {
                "artifact_type": "output_evidence_contract",
                "artifact_ref": "session-artifact-" + "d" * 16,
            }
        ),
        "output-evidence-contract.json",
    )
    rejected = coordinator.enrich_authorized_evidence()
    assert rejected["ok"] is False
    state = coordinator.store.read()
    assert "result_review_context_card" in state["saved_artifacts"]
    assert "result_manifestation" in state["saved_artifacts"]
    assert state["latest_run_summary_reference"] is None
    assert len(state["run_summary_index"]) == 1
    assert state["hosted_enrichment"]["status"] == "rejected"


def test_local_exception_can_never_claim_protected_rejection(tmp_path: Path) -> None:
    coordinator = _processing_coordinator(tmp_path, qasm_version=2)
    result = coordinator._exception_result(
        "process_authorized_artifacts",
        ValueError("unrestricted private detail"),
        coordinator.clock(),
    )
    assert result["category"] == "unknown_local_internal"
    provenance = result["details"]["failure_provenance"]
    assert provenance["origin"] == "unknown_local_internal"
    assert provenance["protected_call_attempted"] is False
    assert provenance["protected_non_success"] is False
    with pytest.raises(ValueError, match="protected_category_provenance_invalid"):
        failure_provenance(
            origin="unknown_local_internal",
            category="protected_operation_rejected",
            protected_call_attempted=False,
            protected_non_success=False,
        )
    with pytest.raises(ValueError, match="protected_category_provenance_invalid"):
        EvidenceProcessingError(
            "protected_operation_rejected",
            origin="unknown_local_internal",
        )


def test_recovery_refresh_does_not_execute_and_selected_skip_does(
    tmp_path: Path,
) -> None:
    transport = RejectingProtectedTransport()
    coordinator = _processing_coordinator(
        tmp_path,
        qasm_version=2,
        transport=transport,
    )
    coordinator.process_authorized_artifacts()
    rejected = coordinator.enrich_authorized_evidence()
    active = deepcopy(coordinator._coordinator_state(coordinator.store.read())["active_recovery"])
    refreshed = coordinator.status()
    assert refreshed["details"]["recovery_refresh"]["executes_selected_action"] is False
    assert coordinator._coordinator_state(coordinator.store.read())["active_recovery"] == active
    skip = next(
        item
        for item in rejected["details"]["recovery_contract"]["alternatives"]
        if item["action"] == "skip_hosted_enrichment"
    )
    executed = coordinator.execute_recovery_action(
        recovery_reference=str(skip["recovery_reference"]),
        action="skip_hosted_enrichment",
        expected_contract_revision=int(
            coordinator.store.read()["current_loop_contract"]["contract_revision"]
        ),
    )
    assert executed["ok"] is True
    assert coordinator.store.read()["hosted_enrichment"]["status"] == "skipped"
    assert coordinator._coordinator_state(coordinator.store.read())["active_recovery"] is None


def test_inventory_and_contract_separate_local_and_hosted_stages() -> None:
    inventory = {row["operation"]: row for row in operation_transport_inventory()["operations"]}
    assert inventory["process_authorized_artifacts"]["transport"] == LOCAL_ONLY
    assert inventory["enrich_authorized_evidence"]["transport"] == HOSTED_CAPABLE
    assert inventory["execute_recovery_action"]["transport"] == LOCAL_ONLY
    contract = evidence_processing_contract_snapshot()
    assert contract["local_stage"]["protected_calls_permitted"] is False
    assert contract["hosted_stage"]["optional"] is True
    recovery = recovery_action_contract_snapshot()
    assert recovery["refresh_executes_action"] is False
    assert recovery["selection_requires_qcoder_owned_recovery_reference"] is True


def test_explicit_external_selection_survives_normalization_and_local_processing(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    fixtures = tmp_path / "public-fixtures"
    fixtures.mkdir()
    activate_current_loop(
        workspace_root=workspace,
        generation_posture="exploratory_first_pass",
        explicit_authority=True,
        request_baseline_digest="a" * 64,
    )
    coordinator = CurrentLoopCoordinator(workspace_root=workspace)
    source = fixtures / "bell.py"
    source.write_text(
        "from qiskit import QuantumCircuit\nqc = QuantumCircuit(2, 2)\nqc.h(0)\nqc.cx(0, 1)\nqc.measure([0, 1], [0, 1])\n",
        encoding="utf-8",
    )
    qasm = fixtures / "bell.qasm"
    qasm.write_text(
        'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q -> c;\n',
        encoding="utf-8",
    )
    results = fixtures / "counts.json"
    results.write_text('{"counts": {"00": 512, "11": 512}}\n', encoding="utf-8")
    candidates = [
        {
            "path": str(source),
            "role": "source",
            "artifact_type": "source",
            "provenance": "user_selected",
            "explicit_external": True,
        },
        {
            "path": str(qasm),
            "role": "circuit_qasm",
            "artifact_type": "circuit_qasm",
            "provenance": "user_selected",
            "explicit_external": True,
        },
        {
            "path": str(results),
            "role": "results",
            "artifact_type": "results",
            "provenance": "user_selected",
            "explicit_external": True,
        },
    ]
    normalized = coordinator._normalize_candidates(candidates)
    assert all(item["external"] is True for item in normalized)
    assert all(item["explicit_external"] is True for item in normalized)

    store = coordinator.store
    state = store.read()
    proposed = propose_selected_artifact_authorization(
        loop_ref=str(state["loop_ref"]),
        proposed_artifacts=[
            {
                "artifact_role": item["role"],
                "artifact_type": item["artifact_type"],
                "local_path": item["path"],
            }
            for item in normalized
        ],
    )
    approved = update_selected_artifact_authorization(
        proposed,
        action="approve_all",
        explicit_action_provenance="direct_user_action",
    )
    state = set_artifact_authorization(
        store=store,
        authorization=approved,
        expected_revision=int(state["state_revision"]),
    )
    protocol = coordinator._initial_coordinator_state(
        phase="evidence_processing",
        state_status="ready",
        checkpoint_kind="none",
        summary="Exact external public fixtures are authorized.",
    )
    protocol["artifact_candidates"] = normalized

    def set_protocol(value: dict[str, Any]) -> Mapping[str, Any]:
        value["coordinator"] = deepcopy(protocol)
        return value

    coordinator.store.update(set_protocol, expected_revision=int(state["state_revision"]))
    result = coordinator.process_authorized_artifacts()

    assert result["ok"] is True, result
    assert result["details"]["local_processing"]["protected_calls_attempted"] == 0
    assert set(result["details"]["extracted_roles"]) >= {
        "source_evidence",
        "python_manifestation",
        "circuit_manifestation",
        "result_manifestation",
    }
    assert result["details"]["raw_source_sent"] is False
    assert result["details"]["raw_qasm_sent"] is False
    assert result["details"]["raw_results_sent"] is False
    serialized = json.dumps(result, sort_keys=True)
    assert str(source) not in serialized
    assert str(qasm) not in serialized
    assert str(results) not in serialized
