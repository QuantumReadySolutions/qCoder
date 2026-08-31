"""Complete-circuit manifestation adapter for bounded OpenQASM 3 evidence."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import re
from typing import Any, Mapping

from qcoder.algorithm_blueprint import with_artifact_digest
from qcoder.context_loop import (
    CIRCUIT_DISCLOSURE_CEILING,
    CIRCUIT_MANIFESTATION_SCHEMA_ID,
    build_stage_identity,
)
from qcoder.engines.feature_extraction.openqasm3_static_evidence import (
    OPENQASM3_STATIC_EVIDENCE_SCHEMA_ID,
    validate_openqasm3_static_evidence,
)


_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PARAMETER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CONTROLLED_ARITIES = {
    "cx": (1, 1),
    "cy": (1, 1),
    "cz": (1, 1),
    "ch": (1, 1),
    "cp": (1, 1),
    "crx": (1, 1),
    "cry": (1, 1),
    "crz": (1, 1),
    "cu": (1, 1),
    "ccx": (2, 1),
    "cswap": (2, 1),
    "CX": (1, 1),
}


def build_openqasm3_circuit_manifestation(
    sidecar: Mapping[str, Any],
    *,
    stage: str | None = None,
    artifact_ref: str | None = None,
) -> dict[str, Any]:
    """Adapt only a complete D-118 sidecar into the existing manifestation schema."""

    validate_openqasm3_static_evidence(sidecar)
    if sidecar.get("schema_id") != OPENQASM3_STATIC_EVIDENCE_SCHEMA_ID:
        raise ValueError("openqasm3_sidecar_required")
    projection = sidecar.get("circuit_ir")
    if sidecar.get("file_status") != "supported" or not isinstance(projection, Mapping):
        raise ValueError("openqasm3_complete_circuit_ir_required")
    if sidecar["derived_facts"]["depth"]["exactness"] != "exact":
        raise ValueError("openqasm3_complete_manifestation_facts_required")
    operations = projection["operations"]
    counts = Counter(str(operation["name"]) for operation in operations)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    inventory = [
        {"operation_category": name, "count": count}
        for name, count in ranked[: CIRCUIT_DISCLOSURE_CEILING["maximum_operation_categories"]]
    ]
    controlled = []
    for name, count in ranked:
        if name not in _CONTROLLED_ARITIES:
            continue
        controls, targets = _CONTROLLED_ARITIES[name]
        controlled.append(
            {
                "operation_category": name,
                "control_arity": controls,
                "target_arity": targets,
                "occurrences": count,
            }
        )
        if len(controlled) == CIRCUIT_DISCLOSURE_CEILING["maximum_controlled_operation_summaries"]:
            break
    parameter_names = sorted(
        {
            token
            for operation in operations
            for parameter in operation["params"]
            for token in _PARAMETER_NAME.findall(parameter)
            if _SAFE_NAME.fullmatch(token) and token not in {"pi", "tau", "euler"}
        }
    )[: CIRCUIT_DISCLOSURE_CEILING["maximum_parameter_names"]]
    mappings = [
        {
            "logical_qubit_index": qubit,
            "classical_bit_index": classical,
        }
        for measurement in sidecar["measurements"]
        for qubit, classical in zip(
            measurement["quantum_targets"], measurement["classical_targets"], strict=True
        )
    ][: CIRCUIT_DISCLOSURE_CEILING["maximum_measurement_mappings"]]
    gate_operations = [
        operation
        for operation in operations
        if not (operation["is_measure"] or operation["is_barrier"] or operation["is_reset"])
        and operation["qubits"]
    ]
    multi_qubit_operations = [
        operation for operation in gate_operations if len(operation["qubits"]) >= 2
    ]
    facts = sidecar["derived_facts"]
    depth = facts["depth"]["value"]
    result = {
        "schema_id": CIRCUIT_MANIFESTATION_SCHEMA_ID,
        "schema_version": 1,
        "artifact_type": "circuit_manifestation",
        "artifact_ref": artifact_ref or "artifact-reference-not-supplied",
        "stage_identity": build_stage_identity(stage=stage, candidate_stages=()),
        "stage_availability": "available",
        "representation_category": "openqasm3_bounded_static_manifestation",
        "qubit_count": projection["n_qubits"],
        "classical_bit_count": projection["n_cbits"],
        "register_facts": {
            "quantum_register_count": len(projection["qregs"]),
            "classical_register_count": len(sidecar["classical_declarations"]),
        },
        "operation_inventory": inventory,
        "operation_categories_truncated": len(ranked)
        > CIRCUIT_DISCLOSURE_CEILING["maximum_operation_categories"],
        "controlled_operation_summaries": controlled,
        "parameter_names": parameter_names,
        "measurement_mapping": mappings,
        "structural_metrics": {
            "width": facts["quantum_width"]["value"],
            "classical_width": facts["classical_width"]["value"],
            "gate_count": len(gate_operations),
            "operation_count": facts["operation_count"]["value"],
            "depth": depth,
            "sequential_gate_count": len(gate_operations),
            "multi_qubit_gate_count": len(multi_qubit_operations),
            "entangling_operation_count": len(multi_qubit_operations),
            "entangling_depth": depth if multi_qubit_operations and depth is not None else 0,
            "measurement_count": facts["measurement_count"]["value"],
        },
        "entangling_operation_structure_observed": bool(multi_qubit_operations),
        "output_state_entanglement_proven": False,
        "repeated_region_facts": [],
        "parser_limitations": [
            "Bounded static OpenQASM 3.0 subset only; no source or circuit execution.",
            "Custom-gate calls remain call-level observations without primitive expansion.",
            "Circuit stage identity is not guessed from source structure.",
        ],
        "disclosure_ceiling": deepcopy(CIRCUIT_DISCLOSURE_CEILING),
        "raw_qasm_included": False,
        "full_operation_sequence_included": False,
        "reconstructive_graph_included": False,
        "source_or_circuit_executed": False,
        "python_constructor_form_inferred": False,
        "repository_scanned": False,
        "retention": "process_and_discard",
        "non_proofs": [
            "Circuit correctness and algorithm identity are not established.",
            "Execution behavior, hardware suitability, fidelity, and performance are not established.",
            "Observed OpenQASM structure does not establish user intent.",
        ],
    }
    return with_artifact_digest(result)
