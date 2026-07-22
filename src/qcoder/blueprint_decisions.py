"""Canonical stateless contracts for Algorithm Blueprint decision readiness."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re
import secrets
from typing import Any, Iterable

from qcoder.development_evidence import (
    ALIGNMENT_STATUSES,
    CHOICE_ORIGINS,
    EVIDENCE_CONFIDENCE_LABELS,
    MOTIF_REGISTRY,
    PROFILE_IDS,
)


DECISION_LOOP_GATE = "readiness_resolution_v1"
DECISION_LOOP_DISABLED = "disabled"
PROFILE_DECISION_CATALOG_ID = "profile_decision_catalog.v1"
PROFILE_DECISION_CATALOG_VERSION = 1
PROFILE_DECISION_ID_VERSION = "profile_decision_id.v1"
MOTIF_MAPPING_VERSION = "profile_decision_motif_mapping.v1"

READINESS_RESULTS = (
    "ready_to_generate",
    "ready_with_bounded_discretion",
    "blocked_pending_decisions",
)
RESOLUTION_STATES = (
    "proposed",
    "resolved",
    "unresolved",
    "conflicting",
    "evidence_deferred",
    "not_applicable",
)
USER_DISPOSITIONS = (
    "selected_choice",
    "bounded_alternatives",
    "bounded_value_range",
    "deferred_to_source_evidence",
    "deferred_to_later_evidence",
    "left_unresolved",
    "not_supplied",
)
GENERATION_EFFECTS = ("non_blocking", "bounded_discretion", "blocking")
RESOLUTION_CONTEXTS = ("blueprint_readiness", "source_alignment")
RESOLUTION_PHASES = ("propose", "confirm")
ACTION_IDS = (
    "accept_and_add_to_blueprint",
    "clarify_requirement",
    "constrain_next_generation",
    "compare_profile_supported_alternatives",
    "ask_assistant_to_regenerate",
    "request_logical_circuit_evidence",
    "leave_unresolved",
)
ACTION_DISPLAY_LABELS = {
    "accept_and_add_to_blueprint": "Accept and add to blueprint",
    "clarify_requirement": "Clarify the requirement",
    "constrain_next_generation": "Constrain the next generation",
    "compare_profile_supported_alternatives": "Compare profile-supported alternatives",
    "ask_assistant_to_regenerate": "Ask the assistant to regenerate",
    "request_logical_circuit_evidence": "Request logical-circuit evidence",
    "leave_unresolved": "Leave unresolved",
}

_DECISION_REFERENCE_PATTERN = re.compile(r"^decision-[A-Za-z0-9_-]{22,64}$")
_LINEAGE_REFERENCE_PATTERN = re.compile(r"^session-artifact-[0-9a-f]{16,64}$")
_OPAQUE_REFERENCE_PATTERN = re.compile(r"^(?:proposal|derived)-[A-Za-z0-9_-]{22,64}$")
_BOUND_TYPES = ("finite_alternative_set", "numeric_or_ordinal_range")
_NON_PROOF = (
    "Readiness is a deterministic catalog-relative handoff check. It is not correctness, "
    "completeness, implementation quality, execution readiness, run readiness, or assurance "
    "that an external assistant will comply."
)
_INTRODUCED_NON_CAUSAL = (
    "The selected source contains this bounded choice; the confirmed blueprint did not represent "
    "it. No authorship, intent, or causal attribution is made."
)


def _entry(
    profile_id: str,
    name: str,
    label: str,
    *,
    blueprint_fields: Iterable[str] = (),
    motifs: Iterable[str] = (),
    generation_relevant: bool = True,
    default_effect: str = "blocking",
    bound_types: Iterable[str] = (),
    alternatives: Iterable[str] = (),
    non_blocking_evidence_deferred: bool = False,
    future_stage: str = "python_source",
    actions: Iterable[str] = (
        "clarify_requirement",
        "constrain_next_generation",
        "compare_profile_supported_alternatives",
        "leave_unresolved",
    ),
) -> dict[str, Any]:
    canonical_motifs = list(motifs)
    if any(motif not in MOTIF_REGISTRY for motif in canonical_motifs):
        raise RuntimeError("profile_decision_motif_unknown")
    return {
        "profile_decision_id": f"{profile_id}.{name}",
        "catalog_id": PROFILE_DECISION_CATALOG_ID,
        "catalog_version": PROFILE_DECISION_CATALOG_VERSION,
        "decision_id_version": PROFILE_DECISION_ID_VERSION,
        "motif_mapping_version": MOTIF_MAPPING_VERSION,
        "display_label": label,
        "question": f"What explicit treatment should apply to {label.lower()}?",
        "profile_id": profile_id,
        "intent_fields": list(blueprint_fields),
        "blueprint_fields": list(blueprint_fields),
        "readiness_role": (
            "generation_relevant" if generation_relevant else "optional_observation"
        ),
        "applicability_rule": "applicable unless the explicitly supplied blueprint marks it not applicable",
        "generation_relevant": generation_relevant,
        "default_generation_effect": default_effect,
        "blocking_policy": (
            "block when missing, conflicting, unknown, or unbounded"
            if generation_relevant
            else "non-blocking at the current intent-to-source stage"
        ),
        "bounded_delegation_eligible": bool(tuple(bound_types)),
        "supported_bound_types": list(bound_types),
        "supported_alternatives": list(alternatives),
        "disallowed_categories": ["free_form_delegation", "unsupported_catalog_value"],
        "required_source_visible_evidence": [
            f"source-visible structure or configuration for {label.lower()}"
        ],
        "canonical_motif_ids": canonical_motifs,
        "compatibility_motif_aliases": [motif.rsplit(".", 1)[-1] for motif in canonical_motifs],
        "evidence_confidence_limitations": [
            "A catalog expectation is not an observation or proof of implementation behavior."
        ],
        "later_evidence_requirements": [future_stage],
        "non_blocking_evidence_deferred": non_blocking_evidence_deferred,
        "contextual_actions": list(actions),
        "canonical_order": 0,
        "non_proofs": [_NON_PROOF],
    }


def _generic_catalog() -> list[dict[str, Any]]:
    p = "generic_qiskit"
    return [
        _entry(
            p,
            "circuit_construction",
            "Circuit and register construction",
            blueprint_fields=("normalized_goal",),
            motifs=("qiskit.circuit.construction",),
            alternatives=("quantum_circuit", "explicit_registers"),
            bound_types=("finite_alternative_set",),
        ),
        _entry(
            p,
            "quantum_width",
            "Source-declared quantum width",
            blueprint_fields=("problem_size_meaning",),
            bound_types=("numeric_or_ordinal_range",),
        ),
        _entry(
            p,
            "classical_width",
            "Source-declared classical width",
            blueprint_fields=("measurement_plan",),
            bound_types=("numeric_or_ordinal_range",),
        ),
        _entry(
            p,
            "parameter_declaration",
            "Parameter declaration",
            blueprint_fields=("parameter_strategy",),
            motifs=("qiskit.parameter.use",),
            alternatives=("scalar_parameter", "parameter_vector"),
            bound_types=("finite_alternative_set",),
        ),
        _entry(
            p,
            "parameter_binding",
            "Parameter binding",
            blueprint_fields=("parameter_strategy",),
            motifs=("qiskit.parameter.use",),
            alternatives=("bind_before_return", "leave_symbolic"),
            bound_types=("finite_alternative_set",),
        ),
        _entry(
            p,
            "measurement_structure",
            "Measurement structure",
            blueprint_fields=("measurement_plan",),
            motifs=("qiskit.measurement.mapping",),
            alternatives=("explicit_measure", "measure_all"),
            bound_types=("finite_alternative_set",),
        ),
        _entry(
            p,
            "measurement_mapping",
            "Measurement mapping",
            blueprint_fields=("measurement_plan",),
            motifs=("qiskit.measurement.mapping",),
        ),
        _entry(
            p,
            "controlled_operations",
            "Controlled-operation treatment",
            motifs=("qiskit.controlled.operations",),
            generation_relevant=False,
            default_effect="non_blocking",
            non_blocking_evidence_deferred=True,
        ),
        _entry(
            p,
            "transpilation_configuration",
            "Transpilation configuration",
            generation_relevant=False,
            default_effect="non_blocking",
            non_blocking_evidence_deferred=True,
            future_stage="target_circuit",
        ),
        _entry(
            p,
            "pass_manager_configuration",
            "Pass-manager configuration",
            generation_relevant=False,
            default_effect="non_blocking",
            non_blocking_evidence_deferred=True,
            future_stage="target_circuit",
        ),
        _entry(
            p,
            "backend_reference",
            "Backend reference",
            blueprint_fields=("execution_intent",),
            generation_relevant=False,
            default_effect="non_blocking",
            non_blocking_evidence_deferred=True,
            future_stage="run_results",
        ),
        _entry(
            p,
            "simulator_reference",
            "Simulator reference",
            blueprint_fields=("execution_intent",),
            generation_relevant=False,
            default_effect="non_blocking",
            non_blocking_evidence_deferred=True,
            future_stage="run_results",
        ),
        _entry(
            p,
            "primitive_reference",
            "Primitive reference",
            blueprint_fields=("execution_intent",),
            generation_relevant=False,
            default_effect="non_blocking",
            non_blocking_evidence_deferred=True,
            future_stage="run_results",
        ),
        _entry(
            p,
            "shots",
            "Shot configuration",
            blueprint_fields=("execution_intent",),
            generation_relevant=False,
            default_effect="non_blocking",
            bound_types=("numeric_or_ordinal_range",),
            non_blocking_evidence_deferred=True,
            future_stage="run_results",
        ),
        _entry(
            p,
            "seed",
            "Seed configuration",
            generation_relevant=False,
            default_effect="non_blocking",
            bound_types=("numeric_or_ordinal_range",),
            non_blocking_evidence_deferred=True,
            future_stage="run_results",
        ),
        _entry(
            p,
            "execution_options",
            "Execution options",
            generation_relevant=False,
            default_effect="non_blocking",
            non_blocking_evidence_deferred=True,
            future_stage="run_results",
        ),
        _entry(
            p,
            "result_processing",
            "Result-processing structure",
            blueprint_fields=("desired_output",),
            motifs=("qiskit.result.processing",),
        ),
        _entry(
            p,
            "bit_order",
            "Bit-order and endian treatment",
            blueprint_fields=("measurement_plan",),
            motifs=("qiskit.measurement.mapping",),
            alternatives=("qiskit_display_order", "explicit_reversal"),
            bound_types=("finite_alternative_set",),
        ),
        _entry(
            p,
            "expected_output_evidence",
            "Expected output evidence",
            blueprint_fields=("desired_output",),
        ),
    ]


def _grover_catalog() -> list[dict[str, Any]]:
    p = "grover_search"
    return [
        _entry(
            p,
            "search_space_representation",
            "Search-space representation",
            blueprint_fields=("search_space_meaning",),
            alternatives=("computational_basis", "explicit_domain_mapping"),
            bound_types=("finite_alternative_set",),
        ),
        _entry(
            p,
            "marked_state_representation",
            "Marked-state representation",
            blueprint_fields=("marked_state_meaning",),
            alternatives=("predicate", "structural_marker"),
            bound_types=("finite_alternative_set",),
        ),
        _entry(
            p,
            "oracle_approach",
            "Oracle approach",
            blueprint_fields=("oracle_choice",),
            motifs=("grover.oracle.structure",),
            alternatives=("phase_oracle", "bit_flip_oracle"),
            bound_types=("finite_alternative_set",),
        ),
        _entry(
            p,
            "diffusion_structure",
            "Diffusion or amplitude-amplification structure",
            motifs=("grover.diffusion.amplification",),
        ),
        _entry(
            p,
            "iteration_policy",
            "Iteration policy",
            blueprint_fields=("iteration_assumption",),
            motifs=("grover.iteration.structure",),
            alternatives=("explicit_count", "bounded_formula"),
            bound_types=("finite_alternative_set", "numeric_or_ordinal_range"),
        ),
        _entry(
            p,
            "ancilla_treatment",
            "Ancilla treatment",
            blueprint_fields=("ancilla_policy",),
            alternatives=("none", "clean_ancilla", "workspace_ancilla"),
            bound_types=("finite_alternative_set",),
        ),
        _entry(
            p,
            "measurement_mapping",
            "Measurement mapping",
            blueprint_fields=("measurement_plan",),
            motifs=("qiskit.measurement.mapping",),
        ),
        _entry(
            p,
            "bit_order",
            "Bit-order treatment",
            blueprint_fields=("bit_order_expectation",),
            motifs=("qiskit.measurement.mapping",),
            alternatives=("qiskit_display_order", "explicit_reversal"),
            bound_types=("finite_alternative_set",),
        ),
        _entry(
            p,
            "backend_reference",
            "Backend reference",
            generation_relevant=False,
            default_effect="non_blocking",
            non_blocking_evidence_deferred=True,
            future_stage="run_results",
        ),
        _entry(
            p,
            "simulator_reference",
            "Simulator reference",
            generation_relevant=False,
            default_effect="non_blocking",
            non_blocking_evidence_deferred=True,
            future_stage="run_results",
        ),
        _entry(
            p,
            "shots",
            "Shot configuration",
            generation_relevant=False,
            default_effect="non_blocking",
            bound_types=("numeric_or_ordinal_range",),
            non_blocking_evidence_deferred=True,
            future_stage="run_results",
        ),
        _entry(
            p,
            "logical_circuit_evidence",
            "Logical-circuit evidence",
            generation_relevant=False,
            default_effect="non_blocking",
            non_blocking_evidence_deferred=True,
            future_stage="logical_circuit",
            actions=("request_logical_circuit_evidence", "leave_unresolved"),
        ),
    ]


def _qaoa_catalog() -> list[dict[str, Any]]:
    p = "qaoa"
    return [
        _entry(
            p,
            "problem_representation",
            "Problem representation",
            blueprint_fields=("optimization_problem",),
        ),
        _entry(
            p,
            "objective_representation",
            "Objective representation",
            blueprint_fields=("objective",),
        ),
        _entry(
            p,
            "cost_layer",
            "Cost-layer structure",
            blueprint_fields=("cost_encoding",),
            motifs=("qaoa.cost.layer",),
        ),
        _entry(
            p,
            "mixer",
            "Mixer structure",
            blueprint_fields=("mixer_choice",),
            motifs=("qaoa.mixer.layer",),
            alternatives=("x_mixer", "constraint_preserving_mixer"),
            bound_types=("finite_alternative_set",),
        ),
        _entry(
            p,
            "repetitions",
            "Repetitions or depth",
            blueprint_fields=("repetitions",),
            motifs=("qaoa.repetition.layer",),
            bound_types=("numeric_or_ordinal_range",),
        ),
        _entry(
            p,
            "parameter_declaration",
            "Parameter declaration",
            blueprint_fields=("parameter_strategy",),
            motifs=("qaoa.parameterized.layer",),
            alternatives=("scalar_parameters", "parameter_vector"),
            bound_types=("finite_alternative_set",),
        ),
        _entry(
            p,
            "parameter_binding",
            "Parameter binding",
            blueprint_fields=("parameter_strategy",),
            motifs=("qaoa.parameterized.layer",),
            alternatives=("bind_before_return", "leave_symbolic"),
            bound_types=("finite_alternative_set",),
        ),
        _entry(
            p,
            "initial_parameter_boundary",
            "Initial-parameter boundary",
            blueprint_fields=("initialization_strategy",),
            alternatives=("caller_supplied", "bounded_seed_values"),
            bound_types=("finite_alternative_set", "numeric_or_ordinal_range"),
        ),
        _entry(
            p,
            "optimizer_boundary",
            "Optimizer boundary",
            blueprint_fields=("optimizer_boundary",),
            alternatives=("external_optimizer", "fixed_parameters"),
            bound_types=("finite_alternative_set",),
        ),
        _entry(
            p,
            "backend_configuration",
            "Backend configuration",
            blueprint_fields=("backend_intent",),
            generation_relevant=False,
            default_effect="non_blocking",
            non_blocking_evidence_deferred=True,
            future_stage="run_results",
        ),
        _entry(
            p,
            "primitive_configuration",
            "Primitive configuration",
            generation_relevant=False,
            default_effect="non_blocking",
            non_blocking_evidence_deferred=True,
            future_stage="run_results",
        ),
        _entry(
            p,
            "shots",
            "Shot configuration",
            blueprint_fields=("shots",),
            generation_relevant=False,
            default_effect="non_blocking",
            bound_types=("numeric_or_ordinal_range",),
            non_blocking_evidence_deferred=True,
            future_stage="run_results",
        ),
        _entry(
            p,
            "measurement_structure",
            "Measurement structure",
            blueprint_fields=("measurement_plan",),
            motifs=("qiskit.measurement.mapping",),
        ),
        _entry(
            p,
            "candidate_interpretation",
            "Candidate interpretation",
            blueprint_fields=("result_post_processing",),
            motifs=("qiskit.result.processing",),
        ),
        _entry(
            p,
            "post_processing",
            "Post-processing",
            blueprint_fields=("result_post_processing",),
            motifs=("qiskit.result.processing",),
        ),
        _entry(
            p,
            "logical_circuit_evidence",
            "Logical-circuit evidence",
            generation_relevant=False,
            default_effect="non_blocking",
            non_blocking_evidence_deferred=True,
            future_stage="logical_circuit",
            actions=("request_logical_circuit_evidence", "leave_unresolved"),
        ),
        _entry(
            p,
            "run_evidence",
            "Run evidence",
            generation_relevant=False,
            default_effect="non_blocking",
            non_blocking_evidence_deferred=True,
            future_stage="run_results",
        ),
    ]


PROFILE_DECISION_CATALOG = {
    "generic_qiskit": _generic_catalog(),
    "grover_search": _grover_catalog(),
    "qaoa": _qaoa_catalog(),
}
for _profile_entries in PROFILE_DECISION_CATALOG.values():
    for _index, _definition in enumerate(_profile_entries, start=1):
        _definition["canonical_order"] = _index


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def consistency_digest(value: dict[str, Any]) -> str:
    clean = {key: item for key, item in value.items() if key != "consistency_digest"}
    return hashlib.sha256(canonical_json(clean).encode("utf-8")).hexdigest()


def with_consistency_digest(value: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(value)
    result["consistency_digest"] = consistency_digest(result)
    return result


def new_opaque_reference(prefix: str) -> str:
    if prefix not in {"decision", "proposal", "derived"}:
        raise ValueError("unsupported_reference_prefix")
    return f"{prefix}-{secrets.token_urlsafe(16)}"


def decision_reference_valid(value: object) -> bool:
    return isinstance(value, str) and bool(_DECISION_REFERENCE_PATTERN.fullmatch(value))


def lineage_reference_valid(value: object) -> bool:
    return isinstance(value, str) and bool(_LINEAGE_REFERENCE_PATTERN.fullmatch(value))


def catalog_entries(profile_id: str) -> list[dict[str, Any]]:
    if profile_id not in PROFILE_DECISION_CATALOG:
        raise ValueError("unsupported_algorithm_profile")
    return deepcopy(PROFILE_DECISION_CATALOG[profile_id])


def profile_decision_catalog_snapshot() -> dict[str, Any]:
    return {
        "catalog_id": PROFILE_DECISION_CATALOG_ID,
        "catalog_version": PROFILE_DECISION_CATALOG_VERSION,
        "decision_id_version": PROFILE_DECISION_ID_VERSION,
        "motif_mapping_version": MOTIF_MAPPING_VERSION,
        "profile_ids": list(PROFILE_IDS),
        "profiles": deepcopy(PROFILE_DECISION_CATALOG),
        "resolution_states": list(RESOLUTION_STATES),
        "user_dispositions": list(USER_DISPOSITIONS),
        "generation_effects": list(GENERATION_EFFECTS),
        "readiness_results": list(READINESS_RESULTS),
        "resolution_contexts": list(RESOLUTION_CONTEXTS),
        "resolution_phases": list(RESOLUTION_PHASES),
        "action_ids": list(ACTION_IDS),
        "action_display_labels": deepcopy(ACTION_DISPLAY_LABELS),
        "bound_types": list(_BOUND_TYPES),
        "decision_loop_gate": DECISION_LOOP_GATE,
        "decision_loop_disabled": DECISION_LOOP_DISABLED,
        "choice_origins": list(CHOICE_ORIGINS),
        "evidence_confidence_labels": list(EVIDENCE_CONFIDENCE_LABELS),
        "alignment_statuses": list(ALIGNMENT_STATUSES),
        "introduced_after_blueprint_language": _INTRODUCED_NON_CAUSAL,
        "retention": "process_and_discard",
        "hidden_lookup": False,
        "persistent": False,
        "later_stage_analyzers": [],
    }


def _catalog_by_id(profile_id: str) -> dict[str, dict[str, Any]]:
    return {item["profile_decision_id"]: item for item in catalog_entries(profile_id)}


def _dispositions_by_id(value: object) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(key): deepcopy(item) for key, item in value.items() if isinstance(item, dict)}
    if isinstance(value, list):
        return {
            str(item.get("profile_decision_id")): deepcopy(item)
            for item in value
            if isinstance(item, dict) and item.get("profile_decision_id")
        }
    raise ValueError("decision_dispositions_invalid")


def build_decision_records(
    *,
    profile_id: str,
    current_lineage_reference: str,
    parent_artifact_references: list[dict[str, Any]],
    dispositions: object = None,
    decision_references: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if not lineage_reference_valid(current_lineage_reference):
        raise ValueError("current_lineage_reference_invalid")
    supplied = _dispositions_by_id(dispositions)
    references = decision_references or {}
    compact_parent_references = []
    for parent in parent_artifact_references:
        if isinstance(parent, dict) and isinstance(parent.get("artifact_digest"), str):
            compact_parent_references.append(f"sha256:{parent['artifact_digest']}")
        elif isinstance(parent, dict) and isinstance(parent.get("artifact_ref"), str):
            compact_parent_references.append(parent["artifact_ref"])
        elif isinstance(parent, str):
            compact_parent_references.append(parent)
        else:
            raise ValueError("parent_artifact_reference_invalid")
    records = []
    for definition in catalog_entries(profile_id):
        decision_id = definition["profile_decision_id"]
        disposition = supplied.get(decision_id, {})
        decision_ref = disposition.get("decision_ref") or references.get(decision_id)
        if decision_ref is None:
            decision_ref = new_opaque_reference("decision")
        if not decision_reference_valid(decision_ref):
            raise ValueError("decision_ref_invalid")
        resolution_state = str(disposition.get("resolution_state") or "unresolved")
        user_disposition = str(disposition.get("user_disposition") or "not_supplied")
        generation_effect = str(
            disposition.get("generation_effect") or definition["default_generation_effect"]
        )
        record = {
            "section_type": "blueprint_decision_record",
            "schema_version": 1,
            "decision_ref": decision_ref,
            "profile_decision_id": decision_id,
            "selected_profile": profile_id,
            "contract_binding": {
                "catalog": f"{PROFILE_DECISION_CATALOG_ID}@{PROFILE_DECISION_CATALOG_VERSION}",
                "decision_ids": PROFILE_DECISION_ID_VERSION,
                "motifs": MOTIF_MAPPING_VERSION,
            },
            "blueprint_representation_state": str(
                disposition.get("blueprint_representation_state") or "not_represented"
            ),
            "resolution_state": resolution_state,
            "user_disposition": user_disposition,
            "generation_effect": generation_effect,
            "applicability": str(disposition.get("applicability") or "applicable"),
            "evidence_stage_capable_of_resolution": definition["later_evidence_requirements"][0],
            "parent_artifact_references": compact_parent_references,
            "current_lineage_reference": current_lineage_reference,
            "choice_origin": str(disposition.get("choice_origin") or "unknown"),
            "evidence_confidence": str(disposition.get("evidence_confidence") or "Not proven"),
            "alignment_status": str(disposition.get("alignment_status") or "not_applicable"),
            "non_proof_reference": "profile_decision_catalog.v1.non_proof",
        }
        optional_values = {
            "related_intent_references": disposition.get("related_intent_references"),
            "related_requirement_references": disposition.get("related_requirement_references"),
            "allowed_profile_alternatives": definition["supported_alternatives"],
            "user_approved_bounds": disposition.get("user_approved_bounds"),
            "explicitly_disallowed_choices": disposition.get("explicitly_disallowed_choices"),
            "selected_value": disposition.get("selected_value"),
            "related_canonical_motif_ids": definition["canonical_motif_ids"],
            "related_source_findings": disposition.get("related_source_findings"),
            "provenance_entries": disposition.get("provenance_entries"),
            "assumptions": disposition.get("assumptions"),
            "unresolved_questions": disposition.get("unresolved_questions"),
        }
        for key, value in optional_values.items():
            if value not in (None, [], {}):
                record[key] = deepcopy(value)
        error = decision_record_error(record)
        if error:
            raise ValueError(error)
        records.append(record)
    return records


_SHARED_DECISION_RECORD_FIELDS = (
    "selected_profile",
    "contract_binding",
    "parent_artifact_references",
    "current_lineage_reference",
    "non_proof_reference",
)


def pack_decision_record_set(
    *, profile_id: str, decision_records: list[dict[str, Any]]
) -> dict[str, Any]:
    if not decision_records:
        raise ValueError("blueprint_decision_records_missing")
    for record in decision_records:
        error = decision_record_error(record)
        if error:
            raise ValueError(error)
        if record["selected_profile"] != profile_id:
            raise ValueError("blueprint_decision_profile_mismatch")
    first = decision_records[0]
    shared = {key: deepcopy(first[key]) for key in _SHARED_DECISION_RECORD_FIELDS}
    if any(
        any(record.get(key) != shared[key] for key in _SHARED_DECISION_RECORD_FIELDS)
        for record in decision_records
    ):
        raise ValueError("blueprint_decision_record_shared_context_mismatch")
    compact = []
    for record in decision_records:
        item = {
            key: deepcopy(value)
            for key, value in record.items()
            if key not in _SHARED_DECISION_RECORD_FIELDS
        }
        item["shared_context_reference"] = "blueprint_decision_record_set.v1"
        compact.append(item)
    return with_consistency_digest(
        {
            "section_type": "blueprint_decision_record_set",
            "schema_version": 1,
            **shared,
            "records": compact,
        }
    )


def unpack_decision_record_set(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError("blueprint_decision_record_set_invalid")
    if (
        value.get("section_type") != "blueprint_decision_record_set"
        or value.get("schema_version") != 1
    ):
        raise ValueError("blueprint_decision_record_set_version_invalid")
    if value.get("consistency_digest") != consistency_digest(value):
        raise ValueError("blueprint_decision_record_set_altered")
    shared = {key: deepcopy(value.get(key)) for key in _SHARED_DECISION_RECORD_FIELDS}
    records = value.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("blueprint_decision_records_missing")
    result = []
    for compact in records:
        if (
            not isinstance(compact, dict)
            or compact.get("shared_context_reference") != "blueprint_decision_record_set.v1"
        ):
            raise ValueError("blueprint_decision_record_shared_context_invalid")
        record = {
            key: deepcopy(item)
            for key, item in compact.items()
            if key != "shared_context_reference"
        }
        record.update(deepcopy(shared))
        error = decision_record_error(record)
        if error:
            raise ValueError(error)
        result.append(record)
    return result


def _numeric_bound_error(bound: dict[str, Any]) -> str | None:
    lower = bound.get("lower_bound")
    upper = bound.get("upper_bound")
    if not isinstance(lower, (int, float)) or isinstance(lower, bool):
        return "bounded_value_range_invalid"
    if not isinstance(upper, (int, float)) or isinstance(upper, bool):
        return "bounded_value_range_invalid"
    if not math.isfinite(float(lower)) or not math.isfinite(float(upper)):
        return "bounded_value_range_non_finite"
    if lower > upper:
        return "bounded_value_range_invalid"
    if bound.get("domain") not in {"integer", "finite_number", "ordinal"}:
        return "bounded_value_range_domain_invalid"
    if bound.get("unit") not in {
        "count",
        "layers",
        "shots",
        "qubits",
        "classical_bits",
        "unitless",
    }:
        return "bounded_value_range_unit_invalid"
    if not isinstance(bound.get("lower_inclusive"), bool) or not isinstance(
        bound.get("upper_inclusive"), bool
    ):
        return "bounded_value_range_inclusivity_invalid"
    return None


def bound_error(bound: object, definition: dict[str, Any]) -> str | None:
    if not isinstance(bound, dict):
        return "bounded_delegation_missing"
    bound_type = bound.get("bound_type")
    if bound_type not in definition["supported_bound_types"]:
        return "bounded_delegation_type_unsupported"
    if bound_type == "finite_alternative_set":
        allowed = bound.get("allowed")
        if not isinstance(allowed, list) or not allowed:
            return "bounded_alternatives_empty"
        if len(allowed) != len(set(map(str, allowed))):
            return "bounded_alternatives_duplicate"
        if any(item not in definition["supported_alternatives"] for item in allowed):
            return "bounded_alternatives_outside_catalog"
    elif bound_type == "numeric_or_ordinal_range":
        error = _numeric_bound_error(bound)
        if error:
            return error
    else:
        return "bounded_delegation_type_unsupported"
    if not str(bound.get("source_visible_evidence_expected_later") or "").strip():
        return "bounded_delegation_evidence_rule_missing"
    if not str(bound.get("review_rule") or "").strip():
        return "bounded_delegation_review_rule_missing"
    return None


def decision_record_error(value: object) -> str | None:
    if not isinstance(value, dict):
        return "blueprint_decision_record_invalid"
    if value.get("section_type") != "blueprint_decision_record" or value.get("schema_version") != 1:
        return "blueprint_decision_record_version_invalid"
    profile_id = value.get("selected_profile")
    if profile_id not in PROFILE_IDS:
        return "blueprint_decision_profile_invalid"
    definitions = _catalog_by_id(str(profile_id))
    definition = definitions.get(str(value.get("profile_decision_id")))
    if definition is None:
        return "profile_decision_id_invalid"
    if not decision_reference_valid(value.get("decision_ref")):
        return "decision_ref_invalid"
    if not lineage_reference_valid(value.get("current_lineage_reference")):
        return "current_lineage_reference_invalid"
    binding = value.get("contract_binding")
    if (
        not isinstance(binding, dict)
        or binding.get("catalog")
        != f"{PROFILE_DECISION_CATALOG_ID}@{PROFILE_DECISION_CATALOG_VERSION}"
    ):
        return "profile_decision_catalog_mismatch"
    if binding.get("decision_ids") != PROFILE_DECISION_ID_VERSION:
        return "profile_decision_id_version_mismatch"
    if binding.get("motifs") != MOTIF_MAPPING_VERSION:
        return "profile_decision_motif_mapping_mismatch"
    if value.get("resolution_state") not in RESOLUTION_STATES:
        return "resolution_state_invalid"
    if value.get("user_disposition") not in USER_DISPOSITIONS:
        return "user_disposition_invalid"
    if value.get("generation_effect") not in GENERATION_EFFECTS:
        return "generation_effect_invalid"
    if value.get("choice_origin") not in CHOICE_ORIGINS:
        return "choice_origin_invalid"
    if value.get("evidence_confidence") not in EVIDENCE_CONFIDENCE_LABELS:
        return "evidence_confidence_invalid"
    if value.get("alignment_status") not in ALIGNMENT_STATUSES:
        return "alignment_status_invalid"
    if value.get("user_disposition") in {
        "bounded_alternatives",
        "bounded_value_range",
    }:
        return bound_error(value.get("user_approved_bounds"), definition)
    return None


def _blocked_summary(
    profile_id: str,
    records: list[dict[str, Any]],
    blocking_refs: list[str],
    diagnostics: list[str],
) -> dict[str, Any]:
    return {
        "section_type": "blueprint_readiness_summary",
        "schema_version": 1,
        "selected_profile": profile_id,
        "catalog_id": PROFILE_DECISION_CATALOG_ID,
        "catalog_version": PROFILE_DECISION_CATALOG_VERSION,
        "decision_id_version": PROFILE_DECISION_ID_VERSION,
        "motif_mapping_version": MOTIF_MAPPING_VERSION,
        "aggregate_readiness_result": "blocked_pending_decisions",
        "applicable_decision_references": [
            item["decision_ref"] for item in records if item.get("applicability") == "applicable"
        ],
        "blocking_decision_references": list(dict.fromkeys(blocking_refs)),
        "bounded_discretion_decision_references": [],
        "evidence_deferred_decision_references": [
            item["decision_ref"]
            for item in records
            if item.get("resolution_state") == "evidence_deferred"
        ],
        "unknown_applicability_diagnostics": diagnostics,
        "explanation": "Generation is blocked until every applicable generation-relevant decision has an authorized disposition under the supplied catalog.",
        "generation_context_eligibility": False,
        "applicable_user_controlled_actions": [
            "clarify_requirement",
            "constrain_next_generation",
            "compare_profile_supported_alternatives",
            "leave_unresolved",
        ],
        "non_proof": _NON_PROOF,
    }


def calculate_blueprint_readiness(
    *,
    profile_id: str,
    decision_records: list[dict[str, Any]],
    catalog_id: str = PROFILE_DECISION_CATALOG_ID,
    catalog_version: int = PROFILE_DECISION_CATALOG_VERSION,
    decision_id_version: str = PROFILE_DECISION_ID_VERSION,
    motif_mapping_version: str = MOTIF_MAPPING_VERSION,
    required_parents_present: bool = True,
) -> dict[str, Any]:
    if profile_id not in PROFILE_IDS:
        return _blocked_summary(profile_id, [], [], ["unsupported_profile"])
    diagnostics: list[str] = []
    blocking: list[str] = []
    if (
        catalog_id != PROFILE_DECISION_CATALOG_ID
        or catalog_version != PROFILE_DECISION_CATALOG_VERSION
        or decision_id_version != PROFILE_DECISION_ID_VERSION
        or motif_mapping_version != MOTIF_MAPPING_VERSION
    ):
        diagnostics.append("catalog_profile_or_mapping_version_mismatch")
    if not required_parents_present:
        diagnostics.append("required_parent_artifact_missing")
    definitions = _catalog_by_id(profile_id)
    by_id: dict[str, dict[str, Any]] = {}
    seen_refs: set[str] = set()
    for record in decision_records:
        error = decision_record_error(record)
        if error:
            diagnostics.append(error)
            if isinstance(record, dict) and decision_reference_valid(record.get("decision_ref")):
                blocking.append(str(record["decision_ref"]))
            continue
        decision_id = str(record["profile_decision_id"])
        if decision_id in by_id:
            diagnostics.append("duplicate_profile_decision_id")
            blocking.extend([by_id[decision_id]["decision_ref"], record["decision_ref"]])
        by_id[decision_id] = record
        if record["decision_ref"] in seen_refs:
            diagnostics.append("duplicate_or_inconsistent_decision_ref")
            blocking.append(record["decision_ref"])
        seen_refs.add(record["decision_ref"])
    for missing in sorted(set(definitions) - set(by_id)):
        diagnostics.append(f"missing_required_catalog_entry:{missing}")
    bounded: list[str] = []
    deferred: list[str] = []
    for decision_id, definition in definitions.items():
        record = by_id.get(decision_id)
        if record is None:
            continue
        ref = record["decision_ref"]
        applicability = record.get("applicability")
        if applicability == "not_applicable" or record["resolution_state"] == "not_applicable":
            continue
        if applicability != "applicable":
            diagnostics.append(f"unknown_applicability:{decision_id}")
            if definition["generation_relevant"]:
                blocking.append(ref)
            continue
        if record["resolution_state"] == "conflicting":
            blocking.append(ref)
            continue
        if not definition["generation_relevant"]:
            if record["resolution_state"] == "evidence_deferred":
                deferred.append(ref)
            continue
        disposition = record["user_disposition"]
        effect = record["generation_effect"]
        if disposition == "selected_choice" and record["resolution_state"] == "resolved":
            if effect != "non_blocking":
                diagnostics.append(f"resolved_generation_effect_invalid:{decision_id}")
                blocking.append(ref)
            continue
        if disposition in {"bounded_alternatives", "bounded_value_range"}:
            error = bound_error(record.get("user_approved_bounds"), definition)
            if error or effect != "bounded_discretion":
                diagnostics.append(error or f"bounded_generation_effect_invalid:{decision_id}")
                blocking.append(ref)
            else:
                bounded.append(ref)
            continue
        if disposition in {
            "deferred_to_source_evidence",
            "deferred_to_later_evidence",
        }:
            if (
                record["resolution_state"] == "evidence_deferred"
                and definition["non_blocking_evidence_deferred"]
                and effect == "non_blocking"
            ):
                deferred.append(ref)
            else:
                diagnostics.append(f"blocking_evidence_deferred:{decision_id}")
                blocking.append(ref)
            continue
        blocking.append(ref)
    if diagnostics or blocking:
        return _blocked_summary(profile_id, decision_records, blocking, diagnostics)
    readiness = "ready_with_bounded_discretion" if bounded else "ready_to_generate"
    return {
        "section_type": "blueprint_readiness_summary",
        "schema_version": 1,
        "selected_profile": profile_id,
        "catalog_id": PROFILE_DECISION_CATALOG_ID,
        "catalog_version": PROFILE_DECISION_CATALOG_VERSION,
        "decision_id_version": PROFILE_DECISION_ID_VERSION,
        "motif_mapping_version": MOTIF_MAPPING_VERSION,
        "aggregate_readiness_result": readiness,
        "applicable_decision_references": [
            item["decision_ref"]
            for item in decision_records
            if item.get("applicability") == "applicable"
        ],
        "blocking_decision_references": [],
        "bounded_discretion_decision_references": bounded,
        "evidence_deferred_decision_references": deferred,
        "unknown_applicability_diagnostics": [],
        "explanation": (
            "Generation may proceed only with every supplied bound copied exactly."
            if bounded
            else "No applicable generation-relevant decision remains unbounded."
        ),
        "generation_context_eligibility": True,
        "applicable_user_controlled_actions": [],
        "non_proof": _NON_PROOF,
    }


def _parent_references(parents: list[dict[str, Any]]) -> list[dict[str, str]]:
    references = []
    for parent in parents:
        if not isinstance(parent, dict):
            raise ValueError("resolution_parent_invalid")
        kind = str(parent.get("artifact_type") or parent.get("section_type") or "")
        digest = parent.get("artifact_digest")
        if not isinstance(digest, str) or len(digest) != 64:
            digest = hashlib.sha256(canonical_json(parent).encode("utf-8")).hexdigest()
        references.append({"parent_type": kind, "parent_digest": digest})
    return references


def _action_allowed(context: str, action: str) -> bool:
    if context == "blueprint_readiness":
        return action in {
            "clarify_requirement",
            "constrain_next_generation",
            "compare_profile_supported_alternatives",
            "leave_unresolved",
        }
    if context == "source_alignment":
        return action in ACTION_IDS
    return False


def _apply_proposed_updates(
    records: list[dict[str, Any]], updates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    result = deepcopy(records)
    by_ref = {item["decision_ref"]: item for item in result}
    allowed_fields = {
        "resolution_state",
        "user_disposition",
        "generation_effect",
        "user_approved_bounds",
        "explicitly_disallowed_choices",
        "selected_value",
        "blueprint_representation_state",
        "provenance_entries",
        "unresolved_questions",
    }
    for update in updates:
        ref = str(update.get("decision_ref") or "")
        if ref not in by_ref:
            raise ValueError("resolution_decision_ref_unknown")
        for key, value in update.items():
            if key in allowed_fields:
                by_ref[ref][key] = deepcopy(value)
        error = decision_record_error(by_ref[ref])
        if error:
            raise ValueError(error)
    return result


def propose_decision_resolution_pack(
    *,
    resolution_context: str,
    selected_action: str,
    profile_id: str,
    decision_records: list[dict[str, Any]],
    parent_artifacts: list[dict[str, Any]],
    selected_decision_references: list[str],
    proposed_updates: list[dict[str, Any]],
    source_finding_references: list[str] | None = None,
    current_lineage_reference: str,
    proposal_ref: str | None = None,
    prospective_derived_references: list[str] | None = None,
) -> dict[str, Any]:
    if not _action_allowed(resolution_context, selected_action):
        raise ValueError("resolution_action_not_applicable")
    if not lineage_reference_valid(current_lineage_reference):
        raise ValueError("current_lineage_reference_invalid")
    record_refs = {item.get("decision_ref") for item in decision_records}
    if not selected_decision_references or any(
        item not in record_refs for item in selected_decision_references
    ):
        raise ValueError("resolution_decision_ref_unknown")
    source_refs = list(source_finding_references or [])
    if resolution_context == "source_alignment" and not source_refs:
        raise ValueError("source_alignment_finding_required")
    if resolution_context == "blueprint_readiness" and source_refs:
        raise ValueError("blueprint_readiness_source_finding_forbidden")
    before = calculate_blueprint_readiness(profile_id=profile_id, decision_records=decision_records)
    after_records = _apply_proposed_updates(decision_records, proposed_updates)
    after = calculate_blueprint_readiness(profile_id=profile_id, decision_records=after_records)
    proposal_ref = proposal_ref or new_opaque_reference("proposal")
    if not _OPAQUE_REFERENCE_PATTERN.fullmatch(proposal_ref):
        raise ValueError("proposal_ref_invalid")
    derived_refs = prospective_derived_references or [new_opaque_reference("derived")]
    if any(not _OPAQUE_REFERENCE_PATTERN.fullmatch(item) for item in derived_refs):
        raise ValueError("derived_artifact_reference_invalid")
    definitions = _catalog_by_id(profile_id)
    alternatives = []
    for record in decision_records:
        if record["decision_ref"] not in selected_decision_references:
            continue
        definition = definitions[record["profile_decision_id"]]
        alternatives.extend(
            {
                "name": name,
                "decision_ref": record["decision_ref"],
                "provenance": "profile_decision_catalog.v1",
                "non_preference": "No alternative is ranked or preferred.",
            }
            for name in definition["supported_alternatives"]
        )
    pack = {
        "section_type": "decision_resolution_pack",
        "schema_version": 1,
        "resolution_context": resolution_context,
        "selected_profile": profile_id,
        "catalog_id": PROFILE_DECISION_CATALOG_ID,
        "catalog_version": PROFILE_DECISION_CATALOG_VERSION,
        "decision_id_version": PROFILE_DECISION_ID_VERSION,
        "motif_mapping_version": MOTIF_MAPPING_VERSION,
        "proposal_ref": proposal_ref,
        "selected_action": selected_action,
        "decision_references": list(selected_decision_references),
        "source_finding_references": source_refs,
        "required_parent_references": _parent_references(parent_artifacts),
        "current_lineage_reference": current_lineage_reference,
        "proposed_outcome": {"decision_updates": deepcopy(proposed_updates)},
        "before_and_after_preview": {
            "before": before,
            "after": after,
        },
        "decisions_changed": list(selected_decision_references),
        "decisions_unchanged": [
            item["decision_ref"]
            for item in decision_records
            if item["decision_ref"] not in selected_decision_references
        ],
        "requirements_unchanged": True,
        "remaining_unresolved_decisions": deepcopy(after["blocking_decision_references"]),
        "readiness_impact": {
            "before": before["aggregate_readiness_result"],
            "after": after["aggregate_readiness_result"],
        },
        "output_evidence_contract_impact": "preserve existing categories; add only decision-specific expected evidence when confirmed",
        "proposed_derived_artifact_types": [
            {
                "accept_and_add_to_blueprint": "implementation_blueprint",
                "clarify_requirement": "clarification_request",
                "constrain_next_generation": "generation_constraint_delta",
                "compare_profile_supported_alternatives": "profile_supported_alternatives_comparison",
                "ask_assistant_to_regenerate": "regeneration_handoff",
                "request_logical_circuit_evidence": "later_stage_evidence_request",
                "leave_unresolved": "unresolved_decision_outcome",
            }[selected_action]
        ],
        "prospective_derived_artifact_references": list(derived_refs),
        "explicit_confirmation_requirements": {
            "phase": "confirm",
            "confirmed": True,
            "selected_action": selected_action,
            "confirmation_payload": {"decision_updates": deepcopy(proposed_updates)},
            "all_parents_must_be_resupplied": True,
        },
        "profile_supported_alternatives": alternatives,
        "consistency_information": {
            "canonical_serialization": "sorted compact JSON",
            "server_lookup": False,
            "digest_is_not_signature_or_consent_proof": True,
        },
        "non_proofs": [_NON_PROOF, _INTRODUCED_NON_CAUSAL],
        "retention": "process_and_discard",
        "persistent": False,
        "executed": False,
    }
    return with_consistency_digest(pack)


def decision_resolution_pack_error(
    value: object,
    *,
    parent_artifacts: list[dict[str, Any]] | None = None,
    selected_action: str | None = None,
) -> str | None:
    if not isinstance(value, dict):
        return "decision_resolution_pack_invalid"
    if value.get("section_type") != "decision_resolution_pack" or value.get("schema_version") != 1:
        return "decision_resolution_pack_version_invalid"
    if value.get("resolution_context") not in RESOLUTION_CONTEXTS:
        return "decision_resolution_context_invalid"
    if value.get("selected_action") not in ACTION_IDS or not _action_allowed(
        str(value.get("resolution_context")), str(value.get("selected_action"))
    ):
        return "resolution_action_not_applicable"
    if selected_action is not None and value.get("selected_action") != selected_action:
        return "resolution_selected_action_mismatch"
    if (
        value.get("catalog_id") != PROFILE_DECISION_CATALOG_ID
        or value.get("catalog_version") != PROFILE_DECISION_CATALOG_VERSION
    ):
        return "resolution_catalog_mismatch"
    if (
        value.get("decision_id_version") != PROFILE_DECISION_ID_VERSION
        or value.get("motif_mapping_version") != MOTIF_MAPPING_VERSION
    ):
        return "resolution_version_mismatch"
    if not isinstance(value.get("consistency_digest"), str) or value[
        "consistency_digest"
    ] != consistency_digest(value):
        return "resolution_proposal_altered"
    if parent_artifacts is not None:
        try:
            actual = _parent_references(parent_artifacts)
        except ValueError:
            return "resolution_parent_invalid"
        if actual != value.get("required_parent_references"):
            return "resolution_parent_mismatch"
    return None


def _derived_base(
    *, pack: dict[str, Any], section_type: str, decision_records: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "section_type": section_type,
        "schema_version": 1,
        "derived_artifact_reference": pack["prospective_derived_artifact_references"][0],
        "selected_profile": pack["selected_profile"],
        "catalog_id": PROFILE_DECISION_CATALOG_ID,
        "catalog_version": PROFILE_DECISION_CATALOG_VERSION,
        "decision_id_version": PROFILE_DECISION_ID_VERSION,
        "motif_mapping_version": MOTIF_MAPPING_VERSION,
        "current_lineage_reference": pack["current_lineage_reference"],
        "parent_artifact_references": deepcopy(pack["required_parent_references"]),
        "decision_records": deepcopy(decision_records),
        "provenance_entries": [
            {
                "kind": "resolution_confirmation",
                "proposal_ref": pack["proposal_ref"],
                "selected_action": pack["selected_action"],
                "preserves_prior_source_provenance": True,
            }
        ],
        "retention": "process_and_discard",
        "persistent": False,
        "non_proofs": [_NON_PROOF, _INTRODUCED_NON_CAUSAL],
    }


def confirm_decision_resolution_pack(
    *,
    decision_resolution_pack: dict[str, Any],
    parent_artifacts: list[dict[str, Any]],
    decision_records: list[dict[str, Any]],
    selected_action: str,
    confirmed: bool,
    confirmation_payload: dict[str, Any],
) -> dict[str, Any]:
    if confirmed is not True:
        raise ValueError("explicit_resolution_confirmation_required")
    error = decision_resolution_pack_error(
        decision_resolution_pack,
        parent_artifacts=parent_artifacts,
        selected_action=selected_action,
    )
    if error:
        raise ValueError(error)
    expected_payload = decision_resolution_pack["explicit_confirmation_requirements"][
        "confirmation_payload"
    ]
    if confirmation_payload != expected_payload:
        raise ValueError("resolution_confirmation_payload_mismatch")
    updates = deepcopy(decision_resolution_pack["proposed_outcome"]["decision_updates"])
    updated_records = _apply_proposed_updates(decision_records, updates)
    readiness = calculate_blueprint_readiness(
        profile_id=decision_resolution_pack["selected_profile"],
        decision_records=updated_records,
    )
    action = decision_resolution_pack["selected_action"]
    section_type = {
        "accept_and_add_to_blueprint": "derived_implementation_blueprint",
        "clarify_requirement": "clarification_request",
        "constrain_next_generation": "generation_constraint_delta",
        "compare_profile_supported_alternatives": "profile_supported_alternatives_comparison",
        "ask_assistant_to_regenerate": "regeneration_handoff",
        "request_logical_circuit_evidence": "later_stage_evidence_request",
        "leave_unresolved": "unresolved_decision_outcome",
    }[action]
    artifact = _derived_base(
        pack=decision_resolution_pack,
        section_type=section_type,
        decision_records=updated_records,
    )
    artifact.update(
        {
            "selected_action": action,
            "blueprint_delta": deepcopy(updates),
            "requirements_unchanged": True,
            "readiness_summary": readiness,
            "source_findings_preserved": deepcopy(
                decision_resolution_pack["source_finding_references"]
            ),
            "profile_supported_alternatives": deepcopy(
                decision_resolution_pack["profile_supported_alternatives"]
            ),
            "actions_executed": False,
        }
    )
    if action == "ask_assistant_to_regenerate":
        artifact["assistant_invoked"] = False
        artifact["external_user_controlled_handoff"] = True
    if action == "request_logical_circuit_evidence":
        artifact["requested_stage"] = "logical_circuit"
        artifact["evidence_obtained"] = False
        artifact["later_stage_analysis_performed"] = False
    if action == "leave_unresolved":
        artifact["generation_context_pack_produced"] = False
    return {
        "decision_resolution_pack": deepcopy(decision_resolution_pack),
        "materialized_artifact": with_consistency_digest(artifact),
        "blueprint_readiness_summary": readiness,
        "parent_artifacts_mutated": False,
        "hidden_lookup_performed": False,
        "retained_artifacts": [],
        "retention": "process_and_discard",
    }
