from __future__ import annotations

from copy import deepcopy

import pytest

from qcoder.blueprint_decisions import (
    ACTION_IDS,
    RESOLUTION_CONTEXTS,
    build_resource_architecture,
    build_decision_records,
    catalog_entries,
    consistency_digest,
)
from qcoder.context_bridge_mcp import (
    EXPECTED_TOOLS,
    PROMPT_CONTEXT_MODES,
    post_context_bridge,
    tool_descriptors,
    validate_optional_payload,
)
from qcoder.context_loop import (
    CIRCUIT_DISCLOSURE_CEILING,
    CONTEXT_LOOP_GATE,
    CURRENT_BUILD_CONTEXT_SCHEMA_ID,
    GENERATION_POSTURES,
    PROVENANCE_ROLES,
    RESULT_DISCLOSURE_CEILING,
    PORTABLE_BUNDLE_FROZEN_STATUS,
    PORTABLE_BUNDLE_INVENTORY_STATUS,
    PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS,
    PORTABLE_CURRENT_BUILD_CONTEXT_SCHEMA_ID,
    STAGE_AVAILABILITY_VALUES,
    STAGE_IDENTITY_STATUSES,
    attach_portable_confirmation_transport,
    build_carry_forward_proposal,
    build_circuit_manifestation,
    build_current_build_context,
    build_decision_evidence_lineage,
    build_generation_posture,
    build_portable_current_build_context,
    build_request_baseline,
    build_result_manifestation,
    build_stage_availability,
    build_stage_identity,
    canonical_context_bridge_request_sha256,
    context_loop_contract_snapshot,
    context_loop_gate_matrix,
    canonical_portable_current_build_context_json,
    determine_stage_availability,
    materialize_evolved_blueprint,
    evidence_parent_artifacts_error,
    freeze_portable_current_build_context_candidate,
    portable_confirmation_transport_error,
    portable_current_build_context_error,
    portable_current_build_context_field_inventory,
    required_evidence_parent_descriptors,
    share_safe_request_baseline,
)
from qcoder.development_evidence import (
    PROFILE_IDS,
    RELATIONSHIP_TYPES,
    relationship_declaration,
)


LINEAGE_REF = "session-artifact-0123456789abcdef"
REQUEST_REF = "session-artifact-1111111111111111"
BLUEPRINT_REF = "session-artifact-2222222222222222"
POSTURE_REF = "session-artifact-3333333333333333"
STAGES_REF = "session-artifact-4444444444444444"
LINEAGE_ARTIFACT_REF = "session-artifact-5555555555555555"
CIRCUIT_REF = "session-artifact-6666666666666666"
RESULT_REF = "session-artifact-7777777777777777"
CONTEXT_REF = "session-artifact-8888888888888888"

QASM = """OPENQASM 2.0;
include "qelib1.inc";
qreg logical[3];
creg observed[3];
h logical[0];
cx logical[0],logical[1];
cx logical[0],logical[2];
rz(theta) logical[2];
measure logical[0] -> observed[0];
measure logical[1] -> observed[1];
measure logical[2] -> observed[2];
"""


def _ready_dispositions(profile: str) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for definition in catalog_entries(profile):
        if definition["generation_relevant"]:
            result[definition["profile_decision_id"]] = {
                "resolution_state": "resolved",
                "user_disposition": "selected_choice",
                "generation_effect": "non_blocking",
                "selected_value": "synthetic_choice",
                "blueprint_representation_state": "represented",
                "choice_origin": "blueprint_confirmed",
                "evidence_confidence": "User-provided",
                "alignment_status": "appears_aligned",
            }
        else:
            result[definition["profile_decision_id"]] = {
                "resolution_state": "evidence_deferred",
                "user_disposition": "deferred_to_later_evidence",
                "generation_effect": "non_blocking",
                "selected_value": "not_applicable_at_source_stage",
                "blueprint_representation_state": "deferred",
                "choice_origin": "profile_expected",
                "evidence_confidence": "Not proven",
                "alignment_status": "requires_next_stage_evidence",
            }
    return result


def _request_handoff() -> dict[str, object]:
    baseline = build_request_baseline(
        original_request="Prepare a bounded synthetic Qiskit circuit proposal.",
        explicit_constraints=["Use three logical qubits."],
        explicit_choices=["Return a circuit without execution."],
        assistant_interpretation={
            "summary": "Propose static circuit construction for later review.",
            "provenance_role": "assistant_proposed",
        },
        profile_suggestions=["generic_qiskit"],
        artifact_ref=REQUEST_REF,
    )
    return share_safe_request_baseline(
        baseline,
        structural_summary="Prepare a three-qubit static circuit proposal for review.",
    )


def _stages(*, results: bool = True) -> dict[str, object]:
    return build_stage_availability(
        {
            "human_intent": {"artifact_supplied": True, "artifact_validated": True},
            "python_source": {"artifact_supplied": True, "artifact_validated": True},
            "logical_circuit": {"artifact_supplied": True, "artifact_validated": True},
            "target_circuit": {"artifact_supplied": False},
            "run_results": (
                {"artifact_supplied": True, "artifact_validated": True}
                if results
                else {"artifact_supplied": False, "explicit_state": "not_run"}
            ),
            "next_human_intent": {"artifact_supplied": False},
        },
        artifact_ref=STAGES_REF,
    )


def _lineage() -> dict[str, object]:
    links = [
        {
            "relationship": relationship_declaration(
                relationship_type="implements",
                source_stage="human_intent",
                target_stage="python_source",
                source_reference_id=REQUEST_REF,
                target_reference_id="session-artifact-9999999999999999",
                supplied_evidence_basis="Explicitly supplied current-session artifacts.",
                declaration_state="observed",
                non_proof="The link does not prove completeness or authorship.",
            ),
            "decision_references": [],
        },
        {
            "relationship": relationship_declaration(
                relationship_type="represented_as",
                source_stage="python_source",
                target_stage="logical_circuit",
                source_reference_id="session-artifact-9999999999999999",
                target_reference_id=CIRCUIT_REF,
                supplied_evidence_basis="Comparable width and measurement fields were explicitly supplied.",
                declaration_state="observed",
                non_proof="The link does not prove source-to-circuit equivalence.",
            ),
            "decision_references": [],
        },
    ]
    return build_decision_evidence_lineage(
        links=list(reversed(links)), artifact_ref=LINEAGE_ARTIFACT_REF
    )


def _working_blueprint() -> dict[str, object]:
    return {
        "artifact_type": "implementation_blueprint",
        "schema_version": 1,
        "artifact_ref": BLUEPRINT_REF,
        "artifact_digest": "a" * 64,
        "profile_id": "generic_qiskit",
        "requirements": ["Use three logical qubits."],
        "confirmation_state": "confirmed",
    }


def _current_context(
    *, results: bool = True
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    circuit = build_circuit_manifestation(
        qasm_text=QASM, stage="logical_circuit", artifact_ref=CIRCUIT_REF
    )
    result = build_result_manifestation(
        counts={"000": 24, "111": 40},
        related_circuit_ref=CIRCUIT_REF,
        user_provided_shots=64,
        artifact_ref=RESULT_REF,
    )
    lineage = _lineage()
    references = {
        "request_baseline": REQUEST_REF,
        "working_blueprint": BLUEPRINT_REF,
        "stage_availability": STAGES_REF,
        "lineage": LINEAGE_ARTIFACT_REF,
        "circuit_manifestation": CIRCUIT_REF,
    }
    kwargs: dict[str, object] = {}
    if results:
        references["result_manifestation"] = RESULT_REF
        kwargs["result_manifestation"] = result
    context = build_current_build_context(
        profile_id="generic_qiskit",
        request_baseline=_request_handoff(),
        working_blueprint=_working_blueprint(),
        stage_availability=_stages(results=results),
        lineage=lineage,
        artifact_references=references,
        circuit_manifestation=circuit,
        unresolved_questions=["Should the observed controlled structure carry forward?"],
        artifact_ref=CONTEXT_REF,
        **kwargs,
    )
    return context, circuit, result


def _evidence_parents(
    context: dict[str, object],
    circuit: dict[str, object],
    result: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    parents = [
        _request_handoff(),
        _working_blueprint(),
        circuit,
        _lineage(),
        context,
    ]
    if result is not None and "result_manifestation" in context["artifact_references"]:
        parents.insert(3, result)
    return parents


def test_exact_context_loop_inventories_are_additive() -> None:
    snapshot = context_loop_contract_snapshot()
    assert snapshot["gate"] == CONTEXT_LOOP_GATE
    assert PROVENANCE_ROLES == (
        "user_stated",
        "assistant_proposed",
        "profile_suggested",
        "qcoder_observed",
        "user_confirmed_carry_forward",
    )
    assert GENERATION_POSTURES == ("blueprint_guided", "exploratory_first_pass")
    assert STAGE_AVAILABILITY_VALUES == (
        "available",
        "not_supplied",
        "not_constructed",
        "not_run",
        "unsupported",
        "not_applicable",
        "evidence_requested",
    )
    assert STAGE_IDENTITY_STATUSES == ("explicit", "unknown", "ambiguous")
    assert len(RELATIONSHIP_TYPES) == 9
    assert len(ACTION_IDS) == 7
    assert RESOLUTION_CONTEXTS == (
        "blueprint_readiness",
        "source_alignment",
        "current_build_context",
    )
    assert PROFILE_IDS == ("generic_qiskit", "grover_search", "qaoa")
    assert len(EXPECTED_TOOLS) == 12
    assert len(PROMPT_CONTEXT_MODES) == 5


def test_request_baseline_preserves_local_text_and_withholds_it_by_default() -> None:
    baseline = build_request_baseline(
        original_request="Keep this exact local request private.",
        explicit_constraints=["No execution."],
        assistant_interpretation={"proposal": "Static construction only."},
        profile_suggestions=["generic_qiskit"],
        artifact_ref=REQUEST_REF,
    )
    assert baseline["original_request"] == "Keep this exact local request private."
    assert baseline["share_safe"] is False
    handoff = share_safe_request_baseline(baseline, structural_summary="Static request summary.")
    assert handoff["original_request_text_withheld"] is True
    assert "Keep this exact" not in str(handoff)
    with pytest.raises(ValueError, match="selected_request_text_mismatch"):
        share_safe_request_baseline(
            baseline, include_selected_verbatim=True, selected_verbatim="Altered text."
        )


def test_generation_posture_is_explicit_and_independent_from_readiness() -> None:
    guided = build_generation_posture(posture="blueprint_guided", artifact_ref=POSTURE_REF)
    assert guided["independent_from_readiness"] is True
    clarification = build_generation_posture(
        posture="exploratory_first_pass", explicitly_authorized=False
    )
    assert clarification["status"] == "clarification_required"
    exploratory = build_generation_posture(
        posture="exploratory_first_pass",
        explicitly_authorized=True,
        explicit_constraints=["Use Qiskit circuit construction."],
        explicit_prohibitions=["Do not execute or select a backend."],
        unresolved_assistant_choices=["Gate layout remains a proposal."],
    )
    assert exploratory["artifact_type"] == "exploratory_generation_context"
    assert exploratory["non_governing"] is True
    assert exploratory["assistant_proposals_are_user_intent"] is False
    assert exploratory["automatic_blueprint_adoption"] is False


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"artifact_supplied": False}, "not_supplied"),
        ({"artifact_supplied": False, "explicit_state": "not_constructed"}, "not_constructed"),
        ({"artifact_supplied": False, "explicit_state": "not_run"}, "not_run"),
        ({"artifact_supplied": False, "explicit_state": "not_applicable"}, "not_applicable"),
        ({"artifact_supplied": False, "evidence_requested": True}, "evidence_requested"),
        ({"artifact_supplied": True, "artifact_validated": True}, "available"),
        ({"artifact_supplied": True, "supported": False}, "unsupported"),
    ],
)
def test_stage_availability_rules_are_deterministic(
    kwargs: dict[str, object], expected: str
) -> None:
    assert determine_stage_availability(**kwargs) == expected


def test_stage_identity_is_separate_and_never_guessed() -> None:
    assert build_stage_identity(stage="logical_circuit")["status"] == "explicit"
    assert build_stage_identity()["status"] == "unknown"
    ambiguous = build_stage_identity(candidate_stages=["logical_circuit", "target_circuit"])
    assert ambiguous == {
        "status": "ambiguous",
        "development_stage": None,
        "candidates": ["logical_circuit", "target_circuit"],
    }


def test_circuit_manifestation_is_bounded_non_reconstructive_and_non_executing() -> None:
    artifact = build_circuit_manifestation(
        qasm_text=QASM, stage="logical_circuit", artifact_ref=CIRCUIT_REF
    )
    assert artifact["qubit_count"] == 3
    assert artifact["classical_bit_count"] == 3
    assert artifact["parameter_names"] == ["theta"]
    assert len(artifact["measurement_mapping"]) == 3
    assert artifact["controlled_operation_summaries"] == [
        {
            "operation_category": "cx",
            "control_arity": 1,
            "target_arity": 1,
            "occurrences": 2,
        }
    ]
    serialized = str(artifact).lower()
    assert "openqasm" not in serialized
    assert "qreg logical" not in serialized
    assert artifact["raw_qasm_included"] is False
    assert artifact["full_operation_sequence_included"] is False
    assert artifact["reconstructive_graph_included"] is False
    assert artifact["source_or_circuit_executed"] is False
    assert (
        len(artifact["operation_inventory"])
        <= CIRCUIT_DISCLOSURE_CEILING["maximum_operation_categories"]
    )


def test_result_manifestation_withholds_distribution_and_labels_by_default() -> None:
    artifact = build_result_manifestation(
        counts={"000": 12, "001": 3, "110": 1},
        related_circuit_ref=CIRCUIT_REF,
        user_provided_shots=16,
        artifact_ref=RESULT_REF,
    )
    assert artifact["observed_outcome_count"] == 3
    assert artifact["declared_shot_value"]["evidence_confidence"] == "User-provided"
    assert artifact["raw_counts_included"] is False
    assert artifact["full_distribution_included"] is False
    summaries = artifact["distribution_shape"]["bounded_outcome_summaries"]
    assert len(summaries) <= RESULT_DISCLOSURE_CEILING["maximum_disclosed_outcomes"]
    assert all("safe_outcome_label" not in item for item in summaries)
    assert all("outcome_label" not in item for item in summaries)
    assert "outcome_values" not in artifact["distribution_shape"]


def test_sampled_bitstrings_are_aggregated_locally_and_not_emitted() -> None:
    artifact = build_result_manifestation(
        sampled_bitstrings=["0", "1", "1"],
        related_circuit_ref=CIRCUIT_REF,
        artifact_ref=RESULT_REF,
    )
    assert artifact["representation_category"] == "sampled_bitstrings"
    assert artifact["observed_shot_count"] == 3
    assert artifact["raw_samples_included"] is False


def test_lineage_is_canonical_directional_order_independent_and_non_transitive() -> None:
    first = _lineage()
    links = list(reversed(first["links"]))
    second = build_decision_evidence_lineage(links=links, artifact_ref=LINEAGE_ARTIFACT_REF)
    assert first["links"] == second["links"]
    assert first["transitive_inference"] is False
    assert first["graph_traversal"] is False
    assert all(item["explicitly_supplied"] for item in first["links"])


def test_current_build_context_references_children_and_preserves_missing_result() -> None:
    context, _circuit, _result = _current_context(results=False)
    assert context["schema_id"] == CURRENT_BUILD_CONTEXT_SCHEMA_ID
    assert "result_manifestation" not in context["artifact_references"]
    assert context["stage_availability"]["run_results"] == "not_run"
    assert context["children_flattened"] is False
    assert context["hidden_operation_calls"] is False
    assert context["retrieval"] is False
    assert context["persistent"] is False


@pytest.mark.parametrize(
    ("context_gate", "source_gate", "decision_gate"),
    [
        (None, None, None),
        (CONTEXT_LOOP_GATE, None, None),
        (None, "depth_v1", None),
        (None, None, "readiness_resolution_v1"),
        (CONTEXT_LOOP_GATE, "depth_v1", None),
        (CONTEXT_LOOP_GATE, None, "readiness_resolution_v1"),
        (None, "depth_v1", "readiness_resolution_v1"),
        (CONTEXT_LOOP_GATE, "depth_v1", "readiness_resolution_v1"),
    ],
)
def test_gate_matrix_has_no_cascading_activation(
    context_gate: str | None, source_gate: str | None, decision_gate: str | None
) -> None:
    result = context_loop_gate_matrix(
        context_loop=context_gate,
        source_evidence_depth=source_gate,
        decision_loop=decision_gate,
        supplied_children=["stage_availability"] if context_gate else [],
    )
    assert result["supported"] is True
    assert result["cascading_activation"] is False
    assert result["enabled"] == {
        "context_loop": context_gate == CONTEXT_LOOP_GATE,
        "source_evidence_depth": source_gate == "depth_v1",
        "decision_loop": decision_gate == "readiness_resolution_v1",
    }


def test_unsupported_gate_and_missing_children_return_bounded_diagnostics() -> None:
    unsupported = context_loop_gate_matrix(
        context_loop="future", source_evidence_depth=None, decision_loop=None
    )
    assert unsupported["supported"] is False
    missing = context_loop_gate_matrix(
        context_loop=CONTEXT_LOOP_GATE,
        source_evidence_depth=None,
        decision_loop=None,
    )
    assert missing["diagnostics"] == ["context_loop_children_not_supplied"]


def test_carry_forward_proposal_and_evolved_blueprint_are_stateless_and_idempotent() -> None:
    context, circuit, result = _current_context()
    parent = _working_blueprint()
    records = build_decision_records(
        profile_id="generic_qiskit",
        current_lineage_reference=LINEAGE_REF,
        parent_artifact_references=[parent],
        dispositions=_ready_dispositions("generic_qiskit"),
    )
    target = next(
        item
        for item in records
        if item["profile_decision_id"] == "generic_qiskit.controlled_operations"
    )
    target.update(
        {
            "semantic_classification": "decision_candidate",
            "semantic_role": "Bound controlled subroutine in this three-qubit builder.",
            "applicable_scope": "Only the explicitly supplied three-qubit builder role.",
            "relationship_to_requirement": "Refines requirement req-controlled-subroutine.",
            "related_requirement_references": ["req-controlled-subroutine"],
            "evidence_expectation": ["Future source exposes the selected controlled structure."],
            "future_review_rule": "Compare future supplied source and circuit manifestations with this role.",
            "remaining_non_proofs": ["No correctness or algorithm identity is established."],
            "unresolved_questions": ["Should this bounded role carry forward?"],
            "available_control_treatments": ["keep_fixed", "defer"],
            "resolution_state": "unresolved",
            "user_disposition": "left_unresolved",
            "generation_effect": "blocking",
            "blueprint_representation_state": "not_represented",
            "provenance_entries": [
                {"role": "qcoder_observed", "circuit_ref": CIRCUIT_REF},
                {"role": "qcoder_observed", "result_ref": RESULT_REF},
            ],
        }
    )
    update = {
        "decision_ref": target["decision_ref"],
        "semantic_classification": "blueprint_decision",
        "control_treatment": "keep_fixed",
        "semantic_role": target["semantic_role"],
        "applicable_scope": target["applicable_scope"],
        "relationship_to_requirement": target["relationship_to_requirement"],
        "related_requirement_references": target["related_requirement_references"],
        "evidence_expectation": target["evidence_expectation"],
        "future_review_rule": target["future_review_rule"],
        "remaining_non_proofs": target["remaining_non_proofs"],
        "resolution_state": "resolved",
        "user_disposition": "selected_choice",
        "generation_effect": "non_blocking",
        "selected_value": "controlled_subroutine_for_supplied_builder_role",
        "blueprint_representation_state": "represented_in_derived_blueprint",
        "provenance_entries": deepcopy(target["provenance_entries"]),
        "unresolved_questions": [],
    }
    parents = _evidence_parents(context, circuit, result)
    pack = build_carry_forward_proposal(
        selected_action="accept_and_add_to_blueprint",
        profile_id="generic_qiskit",
        decision_records=records,
        parent_artifacts=parents,
        current_build_context=context,
        selected_decision_references=[target["decision_ref"]],
        proposed_updates=[update],
        current_lineage_reference=LINEAGE_REF,
        remaining_uncertainty=["Logical correctness and runtime behavior remain unproven."],
        generation_context_effect="Future generation keeps the supplied role fixed.",
        proposal_ref="proposal-0123456789abcdefghijkl",
        prospective_derived_references=["derived-0123456789abcdefghijkl"],
    )
    assert pack["resolution_context"] == "current_build_context"
    assert pack["user_selected_action"] is True
    assert pack["cross_stage_evidence_selects_action"] is False
    confirmation_payload = pack["explicit_confirmation_requirements"]["confirmation_payload"]
    first = materialize_evolved_blueprint(
        decision_resolution_pack=pack,
        parent_artifacts=parents,
        working_blueprint=parent,
        decision_records=records,
        selected_action="accept_and_add_to_blueprint",
        confirmed=True,
        confirmation_payload=confirmation_payload,
        provenance_entries=target["provenance_entries"],
    )
    second = materialize_evolved_blueprint(
        decision_resolution_pack=deepcopy(pack),
        parent_artifacts=deepcopy(parents),
        working_blueprint=deepcopy(parent),
        decision_records=deepcopy(records),
        selected_action="accept_and_add_to_blueprint",
        confirmed=True,
        confirmation_payload=deepcopy(confirmation_payload),
        provenance_entries=deepcopy(target["provenance_entries"]),
    )
    assert first == second
    assert first["evolved_blueprint"]["parent_mutated"] is False
    assert first["evolved_blueprint"]["provenance_entries"][-1]["role"] == (
        "user_confirmed_carry_forward"
    )
    assert first["hidden_lookup_performed"] is False
    assert first["retained_artifacts"] == []
    assert parent == _working_blueprint()


def test_altered_or_missing_parent_confirmation_is_rejected() -> None:
    context, circuit, result = _current_context()
    parent = _working_blueprint()
    records = build_decision_records(
        profile_id="generic_qiskit",
        current_lineage_reference=LINEAGE_REF,
        parent_artifact_references=[parent],
        dispositions=_ready_dispositions("generic_qiskit"),
    )
    target = records[0]
    pack = build_carry_forward_proposal(
        selected_action="leave_unresolved",
        profile_id="generic_qiskit",
        decision_records=records,
        parent_artifacts=_evidence_parents(context, circuit, result),
        current_build_context=context,
        selected_decision_references=[target["decision_ref"]],
        proposed_updates=[{"decision_ref": target["decision_ref"]}],
        current_lineage_reference=LINEAGE_REF,
        remaining_uncertainty=["User disposition remains unresolved."],
        generation_context_effect="No generation-context change.",
    )
    altered = deepcopy(pack)
    altered["generation_context_effect"] = "Altered"
    with pytest.raises(ValueError, match="resolution_proposal_altered"):
        materialize_evolved_blueprint(
            decision_resolution_pack=altered,
            parent_artifacts=_evidence_parents(context, circuit, result),
            working_blueprint=parent,
            decision_records=records,
            selected_action="leave_unresolved",
            confirmed=True,
            confirmation_payload=pack["explicit_confirmation_requirements"]["confirmation_payload"],
            provenance_entries=[],
        )
    with pytest.raises(ValueError, match="resolution_parent_mismatch"):
        materialize_evolved_blueprint(
            decision_resolution_pack=pack,
            parent_artifacts=[parent],
            working_blueprint=parent,
            decision_records=records,
            selected_action="leave_unresolved",
            confirmed=True,
            confirmation_payload=pack["explicit_confirmation_requirements"]["confirmation_payload"],
            provenance_entries=[],
        )


def test_circuit_construction_carry_forward_requires_layered_resource_architecture() -> None:
    context, circuit, result = _current_context()
    parent = _working_blueprint()
    records = build_decision_records(
        profile_id="generic_qiskit",
        current_lineage_reference=LINEAGE_REF,
        parent_artifact_references=[parent],
        dispositions=_ready_dispositions("generic_qiskit"),
    )
    target = next(
        item
        for item in records
        if item["profile_decision_id"] == "generic_qiskit.circuit_construction"
    )
    target.update(
        {
            "semantic_classification": "decision_candidate",
            "semantic_role": "Organize logical resources for this current build.",
            "applicable_scope": "Current lineage and next generation contract only.",
            "relationship_to_requirement": "Refines requirement req-resource-layout.",
            "related_requirement_references": ["req-resource-layout"],
            "evidence_expectation": ["Future source shows the selected Qiskit manifestation."],
            "future_review_rule": (
                "Compare future source evidence with the confirmed architecture."
            ),
            "remaining_non_proofs": [
                "No correctness or source-to-circuit equivalence is established."
            ],
            "resolution_state": "unresolved",
            "user_disposition": "left_unresolved",
            "generation_effect": "bounded_discretion",
            "provenance_entries": [{"role": "qcoder_observed", "source_ref": "source-safe-ref"}],
        }
    )
    common = {
        "decision_ref": target["decision_ref"],
        "semantic_classification": "blueprint_decision",
        "control_treatment": "keep_fixed",
        "semantic_role": target["semantic_role"],
        "applicable_scope": target["applicable_scope"],
        "relationship_to_requirement": target["relationship_to_requirement"],
        "related_requirement_references": target["related_requirement_references"],
        "evidence_expectation": target["evidence_expectation"],
        "future_review_rule": target["future_review_rule"],
        "remaining_non_proofs": target["remaining_non_proofs"],
        "resolution_state": "resolved",
        "user_disposition": "selected_choice",
        "generation_effect": "non_blocking",
        "selected_value": "quantum_circuit",
        "blueprint_representation_state": "represented_in_derived_blueprint",
        "provenance_entries": deepcopy(target["provenance_entries"]),
        "unresolved_questions": [],
    }
    parents = _evidence_parents(context, circuit, result)
    with pytest.raises(ValueError, match="resource_architecture_invalid"):
        build_carry_forward_proposal(
            selected_action="accept_and_add_to_blueprint",
            profile_id="generic_qiskit",
            decision_records=records,
            parent_artifacts=parents,
            current_build_context=context,
            selected_decision_references=[target["decision_ref"]],
            proposed_updates=[common],
            current_lineage_reference=LINEAGE_REF,
            remaining_uncertainty=["Correctness remains unproven."],
            generation_context_effect="Resolve only the current generation contract.",
        )

    layered = deepcopy(common)
    layered["resource_architecture"] = build_resource_architecture(
        logical_resource_architecture="simple_flat",
        construction_form="quantum_circuit",
        allowed_patterns=("direct_inline",),
        disallowed_patterns=("avoid_opaque_or_unbounded_dynamic_construction",),
    )
    pack = build_carry_forward_proposal(
        selected_action="accept_and_add_to_blueprint",
        profile_id="generic_qiskit",
        decision_records=records,
        parent_artifacts=parents,
        current_build_context=context,
        selected_decision_references=[target["decision_ref"]],
        proposed_updates=[layered],
        current_lineage_reference=LINEAGE_REF,
        remaining_uncertainty=["Correctness remains unproven."],
        generation_context_effect="Resolve only the current generation contract.",
    )
    proposal = pack["resource_architecture_proposal"]
    assert proposal["before"]["logical_resource_architecture"] == "unresolved"
    assert proposal["proposed_after"]["logical_resource_architecture"]["value"] == ("simple_flat")
    assert proposal["qualifications"]["global_generic_qiskit_default"] is False
    assert proposal["qualifications"]["explicit_named_registers_supported"] is True
    assert pack["result_observation_is_design_intent"] is False


def test_current_build_proposal_requires_exact_explicit_evidence_parents() -> None:
    context, circuit, result = _current_context()
    parents = _evidence_parents(context, circuit, result)
    required = required_evidence_parent_descriptors(context)
    assert [item["parent_name"] for item in required] == [
        "request_baseline",
        "working_blueprint",
        "circuit_manifestation",
        "result_manifestation",
        "lineage",
        "current_build_context",
    ]
    assert evidence_parent_artifacts_error(context, parents) is None
    assert evidence_parent_artifacts_error(context, []) == ("evidence_parent_artifacts_required")
    assert evidence_parent_artifacts_error(context, parents[:-1]) == (
        "evidence_parent_artifact_missing"
    )
    assert evidence_parent_artifacts_error(context, parents + [parents[0]]) == (
        "evidence_parent_artifact_duplicate"
    )
    unexpected = deepcopy(parents)
    unexpected.append(
        {
            "artifact_type": "unrelated",
            "artifact_ref": "session-artifact-aaaaaaaaaaaaaaaa",
        }
    )
    assert evidence_parent_artifacts_error(context, unexpected) == (
        "evidence_parent_artifact_unexpected"
    )


def test_portable_current_build_context_is_bounded_and_not_authenticity_proof() -> None:
    context, _circuit, _result = _current_context()
    lineage = _lineage()
    records = build_decision_records(
        profile_id="generic_qiskit",
        current_lineage_reference=LINEAGE_REF,
        parent_artifact_references=[_working_blueprint()],
        dispositions=_ready_dispositions("generic_qiskit"),
    )
    portable = build_portable_current_build_context(
        current_build_context=context,
        decision_records=records,
        decision_evidence_lineage=lineage,
        readiness={
            "aggregate_readiness_result": "ready_to_generate",
            "generation_context_eligibility": True,
            "blocking_decision_references": [],
            "bounded_discretion_decision_references": [],
            "evidence_deferred_decision_references": [],
            "non_proof": "Readiness is not correctness or run readiness.",
        },
        applicable_actions=[
            {
                "decision_ref": records[0]["decision_ref"],
                "action_ids": ["leave_unresolved"],
                "private_rule": "must not be exported",
            }
        ],
    )
    assert portable["schema_id"] == PORTABLE_CURRENT_BUILD_CONTEXT_SCHEMA_ID
    assert portable["inventory_status"] == PORTABLE_BUNDLE_INVENTORY_STATUS
    assert portable["validation"]["artifact_structure_validated"] is True
    assert portable["validation"]["artifact_authenticated"] is False
    assert portable["validation"]["produced_by_qcoder_verified"] is False
    assert portable["transport"]["self_contained_for_passive_rendering"] is True
    assert portable["transport"]["url_fetching"] is False
    assert portable["share_safety"]["raw_source_included"] is False
    assert portable["applicable_actions"][0] == {
        "decision_ref": records[0]["decision_ref"],
        "action_ids": ["leave_unresolved"],
    }
    assert portable_current_build_context_error(portable) is None
    assert canonical_portable_current_build_context_json(portable) == (
        canonical_portable_current_build_context_json(deepcopy(portable))
    )
    inventory = portable_current_build_context_field_inventory()
    assert inventory
    assert all(item["authenticity_meaning"] == "none" for item in inventory)
    assert all(item["protected_policy_dependency"] == "none" for item in inventory)


def test_portable_current_build_context_normalizes_integral_floats_before_digest() -> None:
    context, _circuit, _result = _current_context()
    context["selected_share_safe_summaries"]["result"]["distribution_shape"][
        "entropy_base2"
    ] = 1.0
    portable = build_portable_current_build_context(
        current_build_context=context,
        decision_evidence_lineage=_lineage(),
    )

    entropy = portable["selected_share_safe_summaries"]["result"][
        "distribution_shape"
    ]["entropy_base2"]
    assert entropy == 1
    assert isinstance(entropy, int)
    assert '"entropy_base2":1' in canonical_portable_current_build_context_json(portable)
    assert portable["consistency_digest"] == consistency_digest(portable)


def test_portable_confirmation_transport_preserves_exact_resupplied_parents() -> None:
    context, circuit, result = _current_context()
    records = build_decision_records(
        profile_id="generic_qiskit",
        current_lineage_reference=LINEAGE_REF,
        parent_artifact_references=[_working_blueprint()],
        dispositions=_ready_dispositions("generic_qiskit"),
    )
    target = next(
        item
        for item in records
        if item["profile_decision_id"] == "generic_qiskit.controlled_operations"
    )
    target.update(
        {
            "semantic_classification": "decision_candidate",
            "semantic_role": "Preserve the supplied controlled-operation role.",
            "applicable_scope": "Current lineage and next generation contract only.",
            "relationship_to_requirement": "Refines requirement req-controlled-role.",
            "related_requirement_references": ["req-controlled-role"],
            "evidence_expectation": ["Future source represents the confirmed role."],
            "future_review_rule": "Review against later supplied source and circuit evidence.",
            "remaining_non_proofs": ["No correctness or equivalence is established."],
            "resolution_state": "unresolved",
            "user_disposition": "left_unresolved",
            "generation_effect": "bounded_discretion",
            "provenance_entries": [{"role": "qcoder_observed", "circuit_ref": CIRCUIT_REF}],
        }
    )
    update = {
        **deepcopy(target),
        "semantic_classification": "blueprint_decision",
        "control_treatment": "keep_fixed",
        "resolution_state": "resolved",
        "user_disposition": "selected_choice",
        "generation_effect": "non_blocking",
        "selected_value": "supplied_controlled_role",
        "blueprint_representation_state": "represented_in_derived_blueprint",
        "unresolved_questions": [],
    }
    record_set = {
        "artifact_type": "blueprint_decision_record_set",
        "schema_version": 1,
        "records": records,
    }
    working_blueprint = deepcopy(_working_blueprint())
    working_blueprint["blueprint_decision_records"] = record_set
    working_blueprint["blueprint_decision_records"]["schema_version"] = 1.0
    parents = _evidence_parents(context, circuit, result)
    parents[1] = deepcopy(working_blueprint)
    proposal = build_carry_forward_proposal(
        selected_action="accept_and_add_to_blueprint",
        profile_id="generic_qiskit",
        decision_records=records,
        parent_artifacts=parents,
        current_build_context=context,
        selected_decision_references=[target["decision_ref"]],
        proposed_updates=[update],
        current_lineage_reference=LINEAGE_REF,
        remaining_uncertainty=["Correctness and runtime behavior remain unproven."],
        generation_context_effect="Fix only this decision in the next generation contract.",
        proposal_ref="proposal-portable-confirmation-01",
        prospective_derived_references=["derived-portable-confirmation-01"],
    )
    tool_input = {
        "context_loop": CONTEXT_LOOP_GATE,
        "decision_loop": "readiness_resolution_v1",
        "current_lineage_reference": LINEAGE_REF,
        "resolution_phase": "confirm",
        "resolution_context": "current_build_context",
        "selected_action": "accept_and_add_to_blueprint",
        "proposal_ref": proposal["proposal_ref"],
        "decision_resolution_pack": proposal,
        "resolution_confirmation": {"confirmed": True, "confirmed_by": "Rob"},
        "confirmation_payload": proposal["explicit_confirmation_requirements"][
            "confirmation_payload"
        ],
        "current_build_context": context,
        "evidence_parent_artifacts": parents,
        "working_blueprint": working_blueprint,
        "blueprint_decision_records": record_set,
    }
    portable = build_portable_current_build_context(
        current_build_context=context,
        decision_records=records,
        decision_evidence_lineage=_lineage(),
        carry_forward_proposal=proposal,
    )
    transported = attach_portable_confirmation_transport(
        portable,
        tool_input=tool_input,
    )
    assert portable_confirmation_transport_error(transported["confirmation_transport"]) is None
    assert transported["confirmation_transport"]["tool_input"] == tool_input
    assert isinstance(
        transported["confirmation_transport"]["tool_input"][
            "blueprint_decision_records"
        ]["schema_version"],
        int,
    )
    assert (
        len(transported["confirmation_transport"]["tool_input"]["evidence_parent_artifacts"]) == 6
    )
    assert transported["confirmation_transport"]["canonical_request_sha256"] == (
        canonical_context_bridge_request_sha256(
            tool_name="create_implementation_blueprint",
            tool_input=transported["confirmation_transport"]["tool_input"],
        )
    )
    assert portable_current_build_context_error(transported) is None

    frozen = freeze_portable_current_build_context_candidate(transported)
    assert frozen["inventory_status"] == PORTABLE_BUNDLE_FROZEN_STATUS
    assert portable_current_build_context_error(frozen) is None

    changed = deepcopy(transported["confirmation_transport"])
    changed["tool_input"]["selected_action"] = "leave_unresolved"
    changed["canonical_request_sha256"] = canonical_context_bridge_request_sha256(
        tool_name="create_implementation_blueprint",
        tool_input=changed["tool_input"],
    )
    assert portable_confirmation_transport_error(changed) == ("resolution_selected_action_mismatch")


def test_portable_current_build_context_rejects_limits_and_dangerous_properties() -> None:
    context, _circuit, _result = _current_context()
    portable = build_portable_current_build_context(
        current_build_context=context,
        decision_evidence_lineage=_lineage(),
    )
    dangerous = deepcopy(portable)
    dangerous["transport"]["__proto__"] = {}
    dangerous["consistency_digest"] = consistency_digest(dangerous)
    assert portable_current_build_context_error(dangerous) == ("portable_bundle_dangerous_property")
    oversized = deepcopy(portable)
    oversized["non_proofs"] = [
        "x" * (PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS["maximum_individual_text_field_length"] + 1)
    ]
    oversized["consistency_digest"] = consistency_digest(oversized)
    assert portable_current_build_context_error(oversized) == (
        "portable_bundle_text_field_too_large"
    )
    prohibited = deepcopy(portable)
    prohibited["raw_qasm"] = "withheld"
    prohibited["consistency_digest"] = consistency_digest(prohibited)
    assert portable_current_build_context_error(prohibited) == (
        "portable_bundle_prohibited_content"
    )


def test_adapter_inventory_and_context_loop_schemas_are_additive() -> None:
    descriptors = {item["name"]: item for item in tool_descriptors()}
    assert len(descriptors) == 12
    assert "context_loop" in descriptors["create_context_session_card"]["inputSchema"]["properties"]
    assert "anyOf" in descriptors["create_context_session_card"]["inputSchema"]
    assert validate_optional_payload(_request_handoff()) == "ok"
    assert validate_optional_payload({"raw_qasm": "withheld"}) == "forbidden_input_value"
    assert validate_optional_payload({"counts": {"0": 1}}) == "forbidden_input_value"


def test_adapter_withholds_unselected_request_text_before_transport(tmp_path) -> None:
    token = tmp_path / "token"
    token.write_text("synthetic-token-value", encoding="utf-8")
    token.chmod(0o600)
    captured: dict[str, object] = {}

    class _Response:
        status = 200
        headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return b'{"ok":true}'

    def opener(request, timeout):
        captured["body"] = request.data.decode("utf-8")
        captured["timeout"] = timeout
        return _Response()

    response = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token,
        tool_name="create_algorithm_intent_card",
        artifact_text=None,
        tool_arguments={
            "context_loop": CONTEXT_LOOP_GATE,
            "original_user_intent": "Verbatim local request that must not cross.",
            "request_share_safe_summary": "Bounded selected request summary.",
            "request_text_share_safe": False,
            "profile_id": "generic_qiskit",
        },
        opener=opener,
    )
    assert response["ok"] is True
    assert "Verbatim local request" not in str(captured["body"])
    assert "Bounded selected request summary" in str(captured["body"])


def test_adapter_accepts_structured_context_loop_diff_without_legacy_sides(tmp_path) -> None:
    token = tmp_path / "token"
    token.write_text("synthetic-token-value", encoding="utf-8")
    token.chmod(0o600)
    captured: dict[str, object] = {}

    class _Response:
        status = 200
        headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return b'{"ok":true}'

    def opener(request, timeout):
        captured["body"] = request.data.decode("utf-8")
        captured["timeout"] = timeout
        return _Response()

    response = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token,
        tool_name="create_single_loop_evidence_diff",
        artifact_text=None,
        tool_arguments={
            "context_loop": CONTEXT_LOOP_GATE,
            "current_build_context": {"artifact_ref": "session-artifact-context"},
            "decision_evidence_lineage": {"links": []},
            "decision_records": [{"decision_ref": "decision-context-loop"}],
        },
        opener=opener,
    )

    assert response["ok"] is True
    assert '"before"' not in str(captured["body"])
    assert '"after"' not in str(captured["body"])


def test_adapter_keeps_legacy_diff_side_requirement(tmp_path) -> None:
    token = tmp_path / "token"
    token.write_text("synthetic-token-value", encoding="utf-8")
    token.chmod(0o600)

    response = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token,
        tool_name="create_single_loop_evidence_diff",
        artifact_text="Share-safe current evidence summary.",
        before={"summary": "before only"},
    )

    assert response["ok"] is False
    assert response["error_category"] == "missing_explicit_diff_side"


def test_no_pro_enterprise_or_persistence_surface_is_introduced() -> None:
    snapshot = context_loop_contract_snapshot()
    serialized = str(snapshot).lower()
    assert snapshot["persistence"] is False
    assert snapshot["hidden_state"] is False
    assert "project_history" not in serialized
    assert "organization_policy" not in serialized
    assert snapshot["raw_artifacts_hosted"] is False
