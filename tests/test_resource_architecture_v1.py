from __future__ import annotations

from qcoder.blueprint_decisions import (
    CONSTRUCTION_POLICY_PATTERNS,
    LOGICAL_RESOURCE_ARCHITECTURES,
    QISKIT_CONSTRUCTION_ALIASES,
    QISKIT_CONSTRUCTION_FORMS,
    RESOURCE_ARCHITECTURE_SCOPE,
    build_resource_architecture,
    catalog_entries,
    resource_architecture_error,
)
from qcoder.context_loop import (
    build_circuit_manifestation,
    build_result_manifestation,
    context_loop_contract_snapshot,
)
from qcoder.source_evidence_depth import observe_qiskit_construction_form


SOURCE_REF = {"reference_id": "source-evidence-synthetic"}
CIRCUIT_REF = "session-artifact-1010101010101010"


def test_resource_architecture_layers_are_distinct_and_portable() -> None:
    architecture = build_resource_architecture(
        logical_resource_architecture="simple_flat",
        construction_form="direct_quantum_circuit",
        allowed_patterns=("direct_inline",),
        disallowed_patterns=(
            "avoid_opaque_or_unbounded_dynamic_construction",
        ),
    )
    assert resource_architecture_error(architecture) is None
    assert architecture["logical_resource_architecture"]["value"] == "simple_flat"
    assert architecture["construction_policy"]["allowed_patterns"] == [
        "direct_inline"
    ]
    assert architecture["sdk_manifestation"]["construction_form"] == (
        "direct_quantum_circuit"
    )
    assert architecture["scope"] == {
        "lineage": RESOURCE_ARCHITECTURE_SCOPE,
        "global_profile_default": False,
        "explorer_wide_restriction": False,
        "explicit_named_registers_supported": True,
        "pro_uses_same_logical_architecture_vocabulary": True,
    }
    assert architecture["portability"]["additional_sdks_implemented"] == []


def test_legacy_aliases_map_only_to_qiskit_manifestations() -> None:
    direct = build_resource_architecture(
        logical_resource_architecture="simple_flat",
        construction_form="quantum_circuit",
    )
    named = build_resource_architecture(
        logical_resource_architecture="named_logical_groups",
        construction_form="explicit_registers",
    )
    assert QISKIT_CONSTRUCTION_ALIASES == {
        "quantum_circuit": "direct_quantum_circuit",
        "explicit_registers": "explicit_named_registers",
    }
    assert direct["sdk_manifestation"] == {
        "sdk": "qiskit",
        "construction_form": "direct_quantum_circuit",
        "compatibility_alias": "quantum_circuit",
        "subordinate_to_logical_architecture": True,
    }
    assert named["sdk_manifestation"]["construction_form"] == (
        "explicit_named_registers"
    )
    assert named["logical_resource_architecture"]["value"] == (
        "named_logical_groups"
    )


def test_catalog_keeps_legacy_values_without_making_them_architecture_defaults() -> None:
    definition = next(
        item
        for item in catalog_entries("generic_qiskit")
        if item["profile_decision_id"]
        == "generic_qiskit.circuit_construction"
    )
    assert definition["supported_alternatives"] == [
        "quantum_circuit",
        "explicit_registers",
    ]
    assert definition["question"] == (
        "How should this circuit's logical resources be organized?"
    )
    assert definition["logical_resource_architecture_values"] == list(
        LOGICAL_RESOURCE_ARCHITECTURES
    )
    assert definition["construction_policy_patterns"] == list(
        CONSTRUCTION_POLICY_PATTERNS
    )
    assert definition["sdk_manifestation"]["construction_forms"] == list(
        QISKIT_CONSTRUCTION_FORMS
    )
    assert definition["scope"]["global_profile_default"] is False
    assert definition["scope"]["explorer_wide_restriction"] is False
    assert definition["scope"]["explicit_named_registers_supported"] is True
    assert definition["future_sdk_portability"]["additional_sdks_implemented"] == []


def test_direct_qiskit_constructor_is_observed_only_from_safe_ast() -> None:
    observation = observe_qiskit_construction_form(
        "from qiskit import QuantumCircuit\nqc = QuantumCircuit(2, 2)\n",
        source_reference=SOURCE_REF,
    )
    assert observation["construction_form_observation"] == (
        "direct_quantum_circuit"
    )
    assert observation["source_executed"] is False
    assert observation["effective_circuit_structure_proven"] is False


def test_explicit_named_register_constructor_is_observed_from_safe_ast() -> None:
    observation = observe_qiskit_construction_form(
        "\n".join(
            (
                "from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister",
                "logical = QuantumRegister(2, 'logical')",
                "observed = ClassicalRegister(2, 'observed')",
                "qc = QuantumCircuit(logical, observed)",
            )
        ),
        source_reference=SOURCE_REF,
    )
    assert observation["construction_form_observation"] == (
        "explicit_named_registers"
    )


def test_dynamic_or_unresolved_qiskit_constructor_remains_ambiguous() -> None:
    unresolved = observe_qiskit_construction_form(
        "from qiskit import QuantumCircuit\nqc = QuantumCircuit(factory())\n",
        source_reference=SOURCE_REF,
    )
    imported_helper = observe_qiskit_construction_form(
        "from helper import QuantumCircuit\nqc = QuantumCircuit(2, 2)\n",
        source_reference=SOURCE_REF,
    )
    assert unresolved["construction_form_observation"] == "ambiguous"
    assert imported_helper["construction_form_observation"] == "ambiguous"


def test_qasm_and_result_do_not_select_or_infer_resource_architecture() -> None:
    qasm = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
measure q[0] -> c[0];
measure q[1] -> c[1];
"""
    circuit = build_circuit_manifestation(
        qasm_text=qasm,
        stage="logical_circuit",
        artifact_ref=CIRCUIT_REF,
    )
    result = build_result_manifestation(
        counts={"00": 3, "11": 1},
        related_circuit_ref=CIRCUIT_REF,
    )
    assert circuit["python_constructor_form_inferred"] is False
    assert "construction_form" not in circuit
    assert result["result_observation_is_design_intent"] is False
    assert result["design_selection_effect"] == "none"


def test_context_loop_snapshot_is_additive_and_has_no_new_sdk() -> None:
    snapshot = context_loop_contract_snapshot()
    assert snapshot["schemas"]["resource_architecture"] == (
        "qcoder.resource_architecture.v1"
    )
    assert snapshot["resource_architecture"]["additional_sdks_implemented"] == []
