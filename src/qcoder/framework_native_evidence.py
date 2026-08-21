"""Explicit framework-native evidence envelopes without a QASM requirement."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
import json
from typing import Any

from qcoder.algorithm_blueprint import with_artifact_digest
from qcoder.context_loop import build_result_manifestation
from qcoder.current_loop_evidence_reconciler import reconcile_current_evidence
from qcoder.current_loop_result_manifest import normalize_strict_result_manifest
from qcoder.current_loop_run_summary import build_run_summary


FRAMEWORK_MANIFEST_SCHEMA_ID = "qcoder.framework_native.circuit_manifest.v1"
MAX_FRAMEWORK_OPERATIONS = 4_096
MAX_FRAMEWORK_MEASUREMENTS = 32
MAX_FRAMEWORK_WIRES = 4_096
MAX_FRAMEWORK_TEXT_BYTES = 256


class FrameworkNativeEvidenceError(ValueError):
    pass


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _bounded_text(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > MAX_FRAMEWORK_TEXT_BYTES
    ):
        raise FrameworkNativeEvidenceError("framework_circuit_text_invalid")
    return value


def _bounded_wires(value: object, *, wire_count: int) -> list[int]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > wire_count
        or any(not isinstance(wire, int) or isinstance(wire, bool) for wire in value)
        or any(wire < 0 or wire >= wire_count for wire in value)
    ):
        raise FrameworkNativeEvidenceError("framework_circuit_wires_invalid")
    return list(value)


def validate_framework_circuit_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    if (
        value.get("schema_id") != FRAMEWORK_MANIFEST_SCHEMA_ID
        or value.get("schema_version") != 1
        or value.get("framework") not in {"pennylane"}
        or not isinstance(value.get("operations"), list)
        or not isinstance(value.get("wires"), int)
        or isinstance(value.get("wires"), bool)
        or value.get("wires", 0) < 1
        or value.get("wires", 0) > MAX_FRAMEWORK_WIRES
    ):
        raise FrameworkNativeEvidenceError("framework_circuit_manifest_invalid")
    wire_count = int(value["wires"])
    operations = value["operations"]
    if not operations or len(operations) > MAX_FRAMEWORK_OPERATIONS:
        raise FrameworkNativeEvidenceError("framework_circuit_operations_invalid")
    normalized_operations = []
    for operation in operations:
        if (
            not isinstance(operation, Mapping)
            or not isinstance(operation.get("name"), str)
            or not isinstance(operation.get("wires"), list)
        ):
            raise FrameworkNativeEvidenceError("framework_circuit_operation_invalid")
        parameters = operation.get("parameters", [])
        if (
            not isinstance(parameters, list)
            or len(parameters) > 32
            or any(
                not isinstance(item, (str, int, float, bool))
                or (isinstance(item, str) and len(item.encode("utf-8")) > MAX_FRAMEWORK_TEXT_BYTES)
                for item in parameters
            )
        ):
            raise FrameworkNativeEvidenceError("framework_circuit_parameters_invalid")
        normalized_operations.append(
            {
                "name": _bounded_text(operation["name"]),
                "wires": _bounded_wires(operation["wires"], wire_count=wire_count),
                "parameters": deepcopy(parameters),
            }
        )
    measurements = value.get("measurements", [])
    if not isinstance(measurements, list) or len(measurements) > MAX_FRAMEWORK_MEASUREMENTS:
        raise FrameworkNativeEvidenceError("framework_circuit_measurements_invalid")
    normalized_measurements = []
    for measurement in measurements:
        if not isinstance(measurement, Mapping):
            raise FrameworkNativeEvidenceError("framework_circuit_measurement_invalid")
        normalized_measurements.append(
            {
                "kind": _bounded_text(measurement.get("kind")),
                "wires": _bounded_wires(measurement.get("wires"), wire_count=wire_count),
            }
        )
    normalized = {
        "schema_id": FRAMEWORK_MANIFEST_SCHEMA_ID,
        "schema_version": 1,
        "framework": "pennylane",
        "framework_version": value.get("framework_version"),
        "wires": wire_count,
        "operations": normalized_operations,
        "measurements": normalized_measurements,
        "qasm_conversion_performed": False,
        "semantic_equivalence_to_qasm_claimed": False,
        "raw_customer_execution_owned_by_qcoder": False,
    }
    normalized["manifest_digest"] = _digest(normalized)
    return normalized


def reconcile_framework_native_run(
    *,
    circuit: Mapping[str, Any],
    result: Mapping[str, Any],
    loop_ref: str,
    workspace_binding: str,
    state_revision: int,
    contract_revision: int,
) -> dict[str, Any]:
    normalized_circuit = validate_framework_circuit_manifest(circuit)
    circuit_revision_id = "artifact-revision-" + normalized_circuit["manifest_digest"][:32]
    revisions = {
        circuit_revision_id: {
            "logical_role": "framework_circuit",
            "content_digest": normalized_circuit["manifest_digest"],
        }
    }
    result_value = deepcopy(dict(result))
    result_value["circuit_lineage"] = {
        "status": "exact",
        "artifact_revision_id": circuit_revision_id,
        "content_digest": normalized_circuit["manifest_digest"],
    }
    normalized_result = normalize_strict_result_manifest(
        result_value,
        artifact_revisions=revisions,
    )
    result_revision_id = "artifact-revision-" + normalized_result["manifest_digest"][:32]
    revisions[result_revision_id] = {
        "logical_role": "results",
        "content_digest": normalized_result["manifest_digest"],
    }
    role_revision_set = {
        "framework_circuit": circuit_revision_id,
        "results": result_revision_id,
    }
    reconciliation = reconcile_current_evidence(
        role_revision_set=role_revision_set,
        artifact_revisions=revisions,
        normalized_result_manifest=normalized_result,
        active_goal="current_framework_native_run_evidence",
    )
    circuit_manifestation = with_artifact_digest(
        {
            "schema_id": "qcoder.current_loop.framework_circuit_manifestation.v1",
            "schema_version": 1,
            "artifact_type": "circuit_manifestation",
            "artifact_ref": "session-artifact-" + normalized_circuit["manifest_digest"][:32],
            "representation_category": "explicit_framework_native_manifestation",
            "framework": normalized_circuit["framework"],
            "framework_manifest_digest": normalized_circuit["manifest_digest"],
            "structural_metrics": {
                "width": normalized_circuit["wires"],
                "operation_count": len(normalized_circuit["operations"]),
                "gate_count": len(normalized_circuit["operations"]),
            },
            "qasm_required": False,
            "qasm_conversion_performed": False,
            "semantic_equivalence_to_qasm_claimed": False,
            "native_execution_owned_by_qcoder": False,
            "raw_framework_artifact_embedded": False,
        }
    )
    result_manifestation = build_result_manifestation(
        counts=normalized_result["counts"],
        related_circuit_ref=circuit_manifestation["artifact_ref"],
        user_provided_shots=normalized_result["observed_shots"],
    )
    run_summary = build_run_summary(
        loop_ref=loop_ref,
        workspace_binding=workspace_binding,
        state_revision=state_revision,
        contract_revision=contract_revision,
        result_payload={
            "counts": normalized_result["counts"],
            "shots": normalized_result["observed_shots"],
            **normalized_result["execution_configuration"]["settings"],
        },
        result_manifestation=result_manifestation,
        circuit_manifestation=circuit_manifestation,
        artifact_revision_bindings=role_revision_set,
        artifact_revision_digests={
            role: revisions[revision_id]["content_digest"]
            for role, revision_id in role_revision_set.items()
        },
        manifestation_revision_bindings={
            "circuit_manifestation": circuit_revision_id,
            "result_manifestation": result_revision_id,
        },
        derivation_version="qcoder.framework_native.evidence_derivation.v1",
        evidence_reconciliation=reconciliation,
    )
    return {
        "schema_id": "qcoder.framework_native.run_evidence.v1",
        "framework_circuit": normalized_circuit,
        "result_manifest": normalized_result,
        "run_summary": run_summary,
        "current_run_evidence": True,
        "qasm_required": False,
        "qasm_conversion_performed": False,
        "semantic_equivalence_to_qasm_claimed": False,
        "native_execution_owned_by_qcoder": False,
        "raw_protected_transfer_performed": False,
    }
