"""Local, stateless contracts for Explorer Context Loop v1.

Raw request text, QASM, circuit serializations, counts, and sampled bitstrings are
accepted only by local helpers. Hosted artifacts contain bounded manifestations.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
import re
import secrets
from typing import Any, Iterable, Mapping, Sequence

from qcoder.algorithm_blueprint import artifact_digest_matches, with_artifact_digest
from qcoder.blueprint_decisions import (
    ACTION_IDS,
    CONSTRUCTION_POLICY_PATTERNS,
    LOGICAL_RESOURCE_ARCHITECTURES,
    QISKIT_CONSTRUCTION_ALIASES,
    QISKIT_CONSTRUCTION_FORMS,
    RESOURCE_ARCHITECTURE_SCHEMA_ID,
    RESOURCE_ARCHITECTURE_SCOPE,
    consistency_digest,
    confirm_decision_resolution_pack,
    decision_resolution_pack_error,
    propose_decision_resolution_pack,
    with_consistency_digest,
)
from qcoder.development_evidence import (
    DEVELOPMENT_STAGES,
    PROFILE_IDS,
    RELATIONSHIP_TYPES,
    artifact_reference,
    validate_relationship_declaration,
)
from qcoder.current_loop import current_loop_contract_snapshot
from qcoder.engines.feature_extraction.qasm2_regex_parser import parse_qasm2_text
from qcoder.engines.feature_extraction.reps.depth import compute_depth_stats
from qcoder.engines.feature_extraction.reps.entangling_layers import (
    compute_entangling_layer_stats,
)
from qcoder.engines.review.counts_v0 import normalize_counts_v0


CONTEXT_LOOP_GATE = "current_build_context_v1"
CONTEXT_LOOP_DISABLED = "disabled"
REQUEST_BASELINE_SCHEMA_ID = "qcoder.request_baseline.v1"
GENERATION_POSTURE_SCHEMA_ID = "qcoder.generation_posture.v1"
EXPLORATORY_GENERATION_SCHEMA_ID = "qcoder.exploratory_generation_context.v1"
STAGE_AVAILABILITY_SCHEMA_ID = "qcoder.stage_availability.v1"
CIRCUIT_MANIFESTATION_SCHEMA_ID = "qcoder.circuit_manifestation.v1"
RESULT_MANIFESTATION_SCHEMA_ID = "qcoder.result_manifestation.v1"
LINEAGE_SCHEMA_ID = "qcoder.decision_evidence_lineage.v1"
CURRENT_BUILD_CONTEXT_SCHEMA_ID = "qcoder.current_build_context.v1"
PORTABLE_CURRENT_BUILD_CONTEXT_SCHEMA_ID = "qcoder.current_build_context.portable.v1"
CARRY_FORWARD_SCHEMA_ID = "qcoder.carry_forward_proposal.v1"
EVOLVED_BLUEPRINT_SCHEMA_ID = "qcoder.evolved_blueprint.v1"

PROVENANCE_ROLES = (
    "user_stated",
    "assistant_proposed",
    "profile_suggested",
    "qcoder_observed",
    "user_confirmed_carry_forward",
)
GENERATION_POSTURES = ("blueprint_guided", "exploratory_first_pass")
STAGE_AVAILABILITY_VALUES = (
    "available",
    "not_supplied",
    "not_constructed",
    "not_run",
    "unsupported",
    "not_applicable",
    "evidence_requested",
)
STAGE_IDENTITY_STATUSES = ("explicit", "unknown", "ambiguous")
RESOLUTION_CONTEXT = "current_build_context"

CIRCUIT_DISCLOSURE_CEILING = {
    "selected_artifacts": 1,
    "maximum_qasm_characters": 100_000,
    "maximum_operation_categories": 12,
    "maximum_controlled_operation_summaries": 4,
    "maximum_parameter_names": 8,
    "maximum_measurement_mappings": 8,
    "full_operation_sequence": False,
    "complete_graph": False,
    "arbitrary_parameter_values": False,
}
RESULT_DISCLOSURE_CEILING = {
    "selected_artifacts": 1,
    "maximum_input_outcomes": 1_024,
    "maximum_input_samples": 10_000,
    "maximum_disclosed_outcomes": 4,
    "outcome_labels_default": "withheld",
    "full_distribution": False,
    "raw_samples": False,
}
PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS = {
    "maximum_serialized_bytes": 262_144,
    "maximum_selected_file_bytes": 393_216,
    "maximum_json_nesting_depth": 16,
    "maximum_object_property_count": 4_096,
    "maximum_array_length": 128,
    "maximum_individual_text_field_length": 4_000,
    "maximum_total_text_size": 131_072,
    "maximum_artifact_references": 32,
    "maximum_decisions": 64,
    "maximum_lineage_links": 128,
    "maximum_stage_summaries": 6,
    "maximum_evidence_findings": 64,
    "maximum_proposal_before_after_entries": 64,
}
PORTABLE_BUNDLE_INVENTORY_STATUS = "candidate_pending_ide_materialization_proof"
PORTABLE_BUNDLE_FROZEN_STATUS = "frozen_for_companion_page_v1_candidate"
PORTABLE_BUNDLE_INVENTORY_STATUSES = (
    PORTABLE_BUNDLE_INVENTORY_STATUS,
    PORTABLE_BUNDLE_FROZEN_STATUS,
)
CURRENT_BUILD_EVIDENCE_PARENT_ORDER = (
    "request_baseline",
    "working_blueprint",
    "generation_context",
    "python_manifestation",
    "circuit_manifestation",
    "result_manifestation",
    "lineage",
)

_REFERENCE_PATTERN = re.compile(r"^session-artifact-[0-9a-f]{16,64}$")
_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_PARAMETER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_QREG = re.compile(r"^\s*qreg\s+([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*;\s*$", re.I)
_CREG = re.compile(r"^\s*creg\s+([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*;\s*$", re.I)
_MEASURE = re.compile(
    r"^\s*measure\s+([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*->\s*"
    r"([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*;\s*$",
    re.I,
)
_CONTROLLED_ARITIES = {
    "cx": (1, 1),
    "cy": (1, 1),
    "cz": (1, 1),
    "ch": (1, 1),
    "cp": (1, 1),
    "crx": (1, 1),
    "cry": (1, 1),
    "crz": (1, 1),
    "ccx": (2, 1),
    "cswap": (1, 2),
}
_NON_PROOFS = (
    "The supplied artifacts are bounded current-session evidence, not proof of correctness, "
    "completeness, algorithm identity, semantic equivalence, execution success, or run readiness.",
    "A stage manifestation does not prove that an adjacent artifact produced it or that qCoder "
    "generated, constructed, or ran the artifact.",
)
_PORTABLE_DANGEROUS_PROPERTY_NAMES = {
    "__proto__",
    "prototype",
    "constructor",
}
_PORTABLE_PROHIBITED_FIELDS = {
    "authorization",
    "credential",
    "credentials",
    "customer_identifier",
    "local_path",
    "password",
    "path",
    "private_prompt",
    "raw_bitstrings",
    "raw_circuit",
    "raw_circuit_serialization",
    "raw_counts",
    "raw_path",
    "raw_qasm",
    "raw_samples",
    "raw_source",
    "raw_source_text",
    "secret",
    "token",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def canonical_context_bridge_request_bytes(
    *, tool_name: str, tool_input: Mapping[str, Any]
) -> bytes:
    """Canonical semantic request representation used for transport consistency."""

    if tool_name != "create_implementation_blueprint":
        raise ValueError("portable_confirmation_tool_invalid")
    return (
        json.dumps(
            {"tool": tool_name, "input": deepcopy(dict(tool_input))},
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def canonical_context_bridge_request_sha256(
    *, tool_name: str, tool_input: Mapping[str, Any]
) -> str:
    return hashlib.sha256(
        canonical_context_bridge_request_bytes(
            tool_name=tool_name,
            tool_input=tool_input,
        )
    ).hexdigest()


def _new_artifact_reference() -> str:
    return f"session-artifact-{secrets.token_hex(16)}"


def _reference(value: str | None) -> str:
    result = value or _new_artifact_reference()
    artifact_reference(result)
    return result


def _text(value: object, *, field: str, maximum: int = 4_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}_required")
    result = value.strip()
    if len(result) > maximum:
        raise ValueError(f"{field}_too_large")
    return result


def _exact_text(value: object, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field}_required")
    if len(value) > maximum:
        raise ValueError(f"{field}_too_large")
    return value


def _exact_text_list(
    value: object,
    *,
    field: str,
    maximum_items: int = 64,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or len(value) > maximum_items:
        raise ValueError(f"{field}_invalid")
    return [_exact_text(item, field=field, maximum=1_000) for item in value]


def _text_list(value: object, *, field: str, maximum_items: int = 64) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or len(value) > maximum_items:
        raise ValueError(f"{field}_invalid")
    return [_text(item, field=field, maximum=1_000) for item in value]


def _artifact_ref_from(value: Mapping[str, Any]) -> str | None:
    direct = value.get("artifact_ref") or value.get("current_lineage_reference")
    if isinstance(direct, str) and _REFERENCE_PATTERN.fullmatch(direct):
        return direct
    nested = value.get("artifact_reference")
    if isinstance(nested, Mapping):
        reference_id = nested.get("reference_id")
        if isinstance(reference_id, str) and _REFERENCE_PATTERN.fullmatch(reference_id):
            return reference_id
    return None


def _artifact_descriptor(
    value: Mapping[str, Any], *, supplied_reference: str | None = None
) -> dict[str, Any]:
    reference_id = supplied_reference or _artifact_ref_from(value)
    if reference_id is None:
        raise ValueError("explicit_artifact_reference_required")
    artifact_reference(reference_id)
    digest = value.get("artifact_digest") or value.get("consistency_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        digest = hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
    return {
        "artifact_ref": reference_id,
        "artifact_type": str(
            value.get("artifact_type")
            or value.get("section_type")
            or value.get("schema_id")
            or "bounded_artifact"
        ),
        "digest": digest,
        "scope": "current_session",
        "retrievable": False,
    }


def build_request_baseline(
    *,
    original_request: str,
    explicit_constraints: Sequence[str] = (),
    explicit_choices: Sequence[str] = (),
    assistant_interpretation: Mapping[str, Any] | None = None,
    profile_suggestions: Sequence[str] = (),
    unresolved_questions: Sequence[str] = (),
    artifact_ref: str | None = None,
) -> dict[str, Any]:
    """Preserve one request locally without declaring it share-safe."""

    request = _exact_text(original_request, field="original_request", maximum=20_000)
    assistant = deepcopy(dict(assistant_interpretation or {}))
    if len(_canonical_json(assistant)) > 12_000:
        raise ValueError("assistant_interpretation_too_large")
    result = {
        "schema_id": REQUEST_BASELINE_SCHEMA_ID,
        "schema_version": 1,
        "artifact_type": "request_baseline",
        "artifact_ref": _reference(artifact_ref),
        "original_request": request,
        "explicit_constraints": _exact_text_list(
            explicit_constraints,
            field="explicit_constraints",
        ),
        "explicit_choices": _exact_text_list(
            explicit_choices,
            field="explicit_choices",
        ),
        "assistant_interpretation": assistant,
        "profile_suggestions": _text_list(profile_suggestions, field="profile_suggestions"),
        "unresolved_questions": _text_list(unresolved_questions, field="unresolved_questions"),
        "provenance_entries": [
            {
                "role": "user_stated",
                "fields": ["original_request", "explicit_constraints", "explicit_choices"],
            },
            {"role": "assistant_proposed", "fields": ["assistant_interpretation"]},
            {"role": "profile_suggested", "fields": ["profile_suggestions"]},
        ],
        "share_safe": False,
        "local_only": True,
        "retention": "caller_controlled_local_artifact",
        "non_proofs": list(_NON_PROOFS),
    }
    return with_artifact_digest(result)


def share_safe_request_baseline(
    baseline: Mapping[str, Any],
    *,
    include_selected_verbatim: bool = False,
    selected_verbatim: str | None = None,
    structural_summary: str | None = None,
) -> dict[str, Any]:
    if baseline.get("schema_id") != REQUEST_BASELINE_SCHEMA_ID or not artifact_digest_matches(
        baseline
    ):
        raise ValueError("request_baseline_invalid")
    original = str(baseline["original_request"])
    if include_selected_verbatim:
        selected = _exact_text(
            selected_verbatim,
            field="selected_verbatim",
            maximum=20_000,
        )
        if selected != original:
            raise ValueError("selected_request_text_mismatch")
        request_summary = selected
        withheld = False
        selection = "explicit_verbatim_selection"
    else:
        request_summary = _text(
            structural_summary
            or "Original request text withheld; use supplied constraints, choices, and questions.",
            field="structural_summary",
            maximum=2_000,
        )
        withheld = True
        selection = "bounded_structural_summary"
    result = {
        "schema_id": REQUEST_BASELINE_SCHEMA_ID,
        "schema_version": 1,
        "artifact_type": "request_baseline_handoff",
        "artifact_ref": baseline["artifact_ref"],
        "request_summary": request_summary,
        "original_request_text_withheld": withheld,
        "share_safe_selection": selection,
        "explicit_constraints": deepcopy(baseline.get("explicit_constraints", [])),
        "explicit_choices": deepcopy(baseline.get("explicit_choices", [])),
        "assistant_interpretation": deepcopy(baseline.get("assistant_interpretation", {})),
        "profile_suggestions": deepcopy(baseline.get("profile_suggestions", [])),
        "unresolved_questions": deepcopy(baseline.get("unresolved_questions", [])),
        "provenance_entries": deepcopy(baseline.get("provenance_entries", [])),
        "share_safe": True,
        "retention": "process_and_discard",
        "non_proofs": list(_NON_PROOFS),
    }
    return with_artifact_digest(result)


def build_generation_posture(
    *,
    posture: str,
    explicitly_authorized: bool = False,
    explicit_constraints: Sequence[str] = (),
    explicit_prohibitions: Sequence[str] = (),
    unresolved_assistant_choices: Sequence[str] = (),
    artifact_ref: str | None = None,
) -> dict[str, Any]:
    if posture not in GENERATION_POSTURES:
        raise ValueError("generation_posture_invalid")
    constraints = _text_list(explicit_constraints, field="explicit_constraints")
    prohibitions = _text_list(explicit_prohibitions, field="explicit_prohibitions")
    unresolved = _text_list(unresolved_assistant_choices, field="unresolved_assistant_choices")
    base = {
        "schema_id": GENERATION_POSTURE_SCHEMA_ID,
        "schema_version": 1,
        "artifact_type": "generation_posture",
        "artifact_ref": _reference(artifact_ref),
        "posture": posture,
        "independent_from_readiness": True,
        "explicitly_authorized": explicitly_authorized,
        "explicit_constraints": constraints,
        "explicit_prohibitions": prohibitions,
        "unresolved_assistant_choices": unresolved,
        "retention": "process_and_discard",
        "non_proofs": list(_NON_PROOFS),
    }
    if posture == "blueprint_guided":
        base["governing_blueprint_required"] = True
        return with_artifact_digest(base)
    if not explicitly_authorized or not constraints or not prohibitions:
        base.update(
            {
                "status": "clarification_required",
                "clarification_questions": [
                    "Explicitly authorize an exploratory first pass.",
                    "Supply at least one constraint and one prohibition for the proposal-generation contract.",
                ],
                "exploratory_context_produced": False,
            }
        )
        return with_artifact_digest(base)
    base.update(
        {
            "schema_id": EXPLORATORY_GENERATION_SCHEMA_ID,
            "artifact_type": "exploratory_generation_context",
            "status": "proposal_generation_ready",
            "non_governing": True,
            "assistant_choices_are_proposals": True,
            "assistant_proposals_are_user_intent": False,
            "automatic_blueprint_adoption": False,
            "bounded_discretion_claimed": False,
            "requires_later_human_review": True,
        }
    )
    return with_artifact_digest(base)


def determine_stage_availability(
    *,
    artifact_supplied: bool,
    artifact_validated: bool = False,
    supported: bool = True,
    explicit_state: str | None = None,
    evidence_requested: bool = False,
) -> str:
    if explicit_state is not None and explicit_state not in STAGE_AVAILABILITY_VALUES:
        raise ValueError("stage_availability_invalid")
    if evidence_requested:
        return "evidence_requested"
    if artifact_supplied:
        if not supported:
            return "unsupported"
        return "available" if artifact_validated else "unsupported"
    if explicit_state in {"not_constructed", "not_run", "not_applicable"}:
        return explicit_state
    return "not_supplied"


def build_stage_availability(
    stages: Mapping[str, Mapping[str, Any]], *, artifact_ref: str | None = None
) -> dict[str, Any]:
    unknown = set(stages) - set(DEVELOPMENT_STAGES)
    if unknown:
        raise ValueError("stage_availability_stage_invalid")
    values = {}
    for stage in DEVELOPMENT_STAGES:
        state = dict(stages.get(stage, {}))
        values[stage] = determine_stage_availability(
            artifact_supplied=bool(state.get("artifact_supplied")),
            artifact_validated=bool(state.get("artifact_validated")),
            supported=state.get("supported", True) is True,
            explicit_state=state.get("explicit_state"),
            evidence_requested=bool(state.get("evidence_requested")),
        )
    result = {
        "schema_id": STAGE_AVAILABILITY_SCHEMA_ID,
        "schema_version": 1,
        "artifact_type": "stage_availability",
        "artifact_ref": _reference(artifact_ref),
        "stages": values,
        "describes_evidence_availability_only": True,
        "proves_construction_or_execution": False,
        "retention": "process_and_discard",
    }
    return with_artifact_digest(result)


def build_stage_identity(
    *, stage: str | None = None, candidate_stages: Sequence[str] = ()
) -> dict[str, Any]:
    candidates = list(dict.fromkeys(candidate_stages))
    if stage is not None:
        if stage not in DEVELOPMENT_STAGES:
            raise ValueError("stage_identity_stage_invalid")
        return {"status": "explicit", "development_stage": stage, "candidates": [stage]}
    if any(item not in DEVELOPMENT_STAGES for item in candidates):
        raise ValueError("stage_identity_candidate_invalid")
    if len(candidates) > 1:
        return {"status": "ambiguous", "development_stage": None, "candidates": candidates}
    return {"status": "unknown", "development_stage": None, "candidates": candidates}


def _register_bases(lines: Iterable[str], pattern: re.Pattern[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    offset = 0
    for line in lines:
        match = pattern.match(line)
        if match and match.group(1) not in result:
            result[match.group(1)] = offset
            offset += int(match.group(2))
    return result


def build_circuit_manifestation(
    *,
    qasm_text: str,
    stage: str | None = None,
    candidate_stages: Sequence[str] = (),
    artifact_ref: str | None = None,
) -> dict[str, Any]:
    """Parse one local QASM2 artifact and emit a bounded non-reconstructive view."""

    if not isinstance(qasm_text, str) or not qasm_text.strip():
        raise ValueError("qasm_text_required")
    if len(qasm_text) > CIRCUIT_DISCLOSURE_CEILING["maximum_qasm_characters"]:
        raise ValueError("qasm_text_too_large")
    ir = parse_qasm2_text(qasm_text)
    if ir.qasm_format != "qasm2":
        raise ValueError("circuit_format_unsupported")
    counts = Counter(operation.name for operation in ir.operations)
    depth_stats = compute_depth_stats(ir)
    entangling_stats = compute_entangling_layer_stats(ir)
    gate_operations = [
        operation
        for operation in ir.operations
        if not (operation.is_measure or operation.is_barrier or operation.is_reset)
        and operation.qubits
    ]
    multi_qubit_operations = [
        operation for operation in gate_operations if len(operation.qubits) >= 2
    ]
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    maximum_categories = CIRCUIT_DISCLOSURE_CEILING["maximum_operation_categories"]
    inventory = [
        {"operation_category": name, "count": count} for name, count in ranked[:maximum_categories]
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
            for operation in ir.operations
            for parameter in operation.params
            for token in _PARAMETER_NAME.findall(parameter)
            if _SAFE_NAME.fullmatch(token) and token.lower() != "pi"
        }
    )[: CIRCUIT_DISCLOSURE_CEILING["maximum_parameter_names"]]
    lines = [line.split("//", 1)[0].strip() for line in qasm_text.splitlines()]
    q_bases = _register_bases(lines, _QREG)
    c_bases = _register_bases(lines, _CREG)
    mappings = []
    for line in lines:
        match = _MEASURE.match(line)
        if not match or match.group(1) not in q_bases or match.group(3) not in c_bases:
            continue
        mappings.append(
            {
                "logical_qubit_index": q_bases[match.group(1)] + int(match.group(2)),
                "classical_bit_index": c_bases[match.group(3)] + int(match.group(4)),
            }
        )
        if len(mappings) == CIRCUIT_DISCLOSURE_CEILING["maximum_measurement_mappings"]:
            break
    identity = build_stage_identity(stage=stage, candidate_stages=candidate_stages)
    result = {
        "schema_id": CIRCUIT_MANIFESTATION_SCHEMA_ID,
        "schema_version": 1,
        "artifact_type": "circuit_manifestation",
        "artifact_ref": _reference(artifact_ref),
        "stage_identity": identity,
        "stage_availability": "available",
        "representation_category": "qasm2_static_manifestation",
        "qubit_count": ir.n_qubits,
        "classical_bit_count": ir.n_cbits,
        "register_facts": {
            "quantum_register_count": len(ir.qregs),
            "classical_register_count": len(c_bases),
        },
        "operation_inventory": inventory,
        "operation_categories_truncated": len(ranked) > maximum_categories,
        "controlled_operation_summaries": controlled,
        "parameter_names": parameter_names,
        "measurement_mapping": mappings,
        "structural_metrics": {
            "width": ir.n_qubits,
            "classical_width": ir.n_cbits,
            "gate_count": len(gate_operations),
            "operation_count": len(ir.operations),
            "depth": depth_stats.real_depth,
            "sequential_gate_count": depth_stats.estimated_depth,
            "multi_qubit_gate_count": len(multi_qubit_operations),
            "entangling_operation_count": len(multi_qubit_operations),
            "entangling_depth": entangling_stats.entangling_depth,
            "measurement_count": sum(1 for operation in ir.operations if operation.is_measure),
        },
        "entangling_operation_structure_observed": bool(multi_qubit_operations),
        "output_state_entanglement_proven": False,
        "repeated_region_facts": [],
        "parser_limitations": [
            "Static QASM2 syntax only; custom or unsupported statements may be summarized as custom.",
            "Repeated operations are not inferred to be a semantic repeated region.",
            "Circuit stage identity is not guessed from structure.",
        ],
        "disclosure_ceiling": deepcopy(CIRCUIT_DISCLOSURE_CEILING),
        "raw_qasm_included": False,
        "full_operation_sequence_included": False,
        "reconstructive_graph_included": False,
        "source_or_circuit_executed": False,
        "python_constructor_form_inferred": False,
        "repository_scanned": False,
        "retention": "process_and_discard",
        "non_proofs": list(_NON_PROOFS),
    }
    return with_artifact_digest(result)


def _counts_from_samples(samples: Sequence[str]) -> dict[str, int]:
    if len(samples) > RESULT_DISCLOSURE_CEILING["maximum_input_samples"]:
        raise ValueError("sampled_bitstrings_too_large")
    counts: Counter[str] = Counter()
    for sample in samples:
        if not isinstance(sample, str) or not sample or set(sample) - {"0", "1"}:
            raise ValueError("sampled_bitstring_invalid")
        counts[sample] += 1
    if not counts:
        raise ValueError("sampled_bitstrings_required")
    return dict(counts)


def build_result_manifestation(
    *,
    counts: Mapping[str, int] | None = None,
    sampled_bitstrings: Sequence[str] | None = None,
    related_circuit_ref: str,
    user_provided_shots: int | None = None,
    safe_outcome_labels: bool = False,
    measurement_mapping_qualification: str = "Measurement mapping was explicitly supplied or remains unverified.",
    bit_order_qualification: str = "Bit order was explicitly supplied or remains unverified.",
    output_evidence_relationship: str = "bounded_current_result_observation",
    artifact_ref: str | None = None,
) -> dict[str, Any]:
    """Summarize one local result artifact without emitting its distribution."""

    if (counts is None) == (sampled_bitstrings is None):
        raise ValueError("exactly_one_result_artifact_required")
    artifact_reference(related_circuit_ref)
    raw_counts = (
        dict(counts) if counts is not None else _counts_from_samples(sampled_bitstrings or [])
    )
    if len(raw_counts) > RESULT_DISCLOSURE_CEILING["maximum_input_outcomes"]:
        raise ValueError("result_outcome_count_too_large")
    normalized = normalize_counts_v0(
        {
            "schema": "qcoder.counts.v0",
            "counts": raw_counts,
            "shots_total": user_provided_shots,
        }
    )
    values = normalized["counts"]
    observed_shots = sum(values.values())
    ranked = sorted(values.items(), key=lambda item: (-item[1], item[0]))
    maximum = RESULT_DISCLOSURE_CEILING["maximum_disclosed_outcomes"]
    summaries = []
    for rank, (label, value) in enumerate(ranked[:maximum], start=1):
        record: dict[str, Any] = {
            "rank": rank,
            "frequency_fraction": round(value / observed_shots, 6) if observed_shots else 0.0,
        }
        if safe_outcome_labels:
            record["safe_outcome_label"] = label
        summaries.append(record)
    probabilities = [
        value / observed_shots for value in values.values() if observed_shots and value
    ]
    entropy = -sum(probability * math.log2(probability) for probability in probabilities)
    top_fraction = summaries[0]["frequency_fraction"] if summaries else 0.0
    concentration = "high" if top_fraction >= 0.8 else "moderate" if top_fraction >= 0.4 else "low"
    result = {
        "schema_id": RESULT_MANIFESTATION_SCHEMA_ID,
        "schema_version": 1,
        "artifact_type": "result_manifestation",
        "artifact_ref": _reference(artifact_ref),
        "related_circuit_ref": related_circuit_ref,
        "development_stage": "run_results",
        "stage_availability": "available",
        "representation_category": ("counts" if counts is not None else "sampled_bitstrings"),
        "observed_outcome_count": len(values),
        "observed_shot_count": observed_shots,
        "declared_shot_value": (
            {
                "value": user_provided_shots,
                "evidence_confidence": "User-provided",
            }
            if user_provided_shots is not None
            else None
        ),
        "distribution_shape": {
            "concentration": concentration,
            "entropy_base2": round(entropy, 6),
            "bounded_outcome_summaries": summaries,
            "outcomes_truncated": len(ranked) > maximum,
            "labels_disclosed": safe_outcome_labels,
        },
        "measurement_mapping_qualification": _text(
            measurement_mapping_qualification,
            field="measurement_mapping_qualification",
            maximum=500,
        ),
        "bit_order_qualification": _text(
            bit_order_qualification, field="bit_order_qualification", maximum=500
        ),
        "output_evidence_contract_relationship": _text(
            output_evidence_relationship,
            field="output_evidence_relationship",
            maximum=200,
        ),
        "potentially_affected_decisions": [],
        "next_checks": [],
        "disclosure_ceiling": deepcopy(RESULT_DISCLOSURE_CEILING),
        "raw_counts_included": False,
        "raw_samples_included": False,
        "full_distribution_included": False,
        "result_executed_by_qcoder": False,
        "result_observation_is_design_intent": False,
        "design_selection_effect": "none",
        "retention": "process_and_discard",
        "non_proofs": list(_NON_PROOFS)
        + [
            "This observation does not establish causation, correctness, fidelity, backend quality, optimality, amplification success, solution quality, or quantum advantage."
        ],
    }
    return with_artifact_digest(result)


def build_decision_evidence_lineage(
    *,
    links: Sequence[Mapping[str, Any]],
    artifact_ref: str | None = None,
) -> dict[str, Any]:
    if len(links) > 128:
        raise ValueError("lineage_link_limit_exceeded")
    normalized = []
    for supplied in links:
        relationship = supplied.get("relationship")
        if validate_relationship_declaration(relationship) != "ok":
            raise ValueError("lineage_relationship_invalid")
        decision_refs = _text_list(
            supplied.get("decision_references", []),
            field="decision_references",
            maximum_items=32,
        )
        record = {
            "relationship": deepcopy(relationship),
            "decision_references": decision_refs,
            "explicitly_supplied": True,
            "non_transitive": True,
            "annotation": str(supplied.get("annotation") or "explicit current-session link")[:500],
        }
        normalized.append(record)
    normalized.sort(
        key=lambda item: (
            item["relationship"]["source"]["stage"],
            item["relationship"]["target"]["stage"],
            item["relationship"]["relationship_type"],
            _canonical_json(item["decision_references"]),
        )
    )
    result = {
        "schema_id": LINEAGE_SCHEMA_ID,
        "schema_version": 1,
        "artifact_type": "decision_evidence_lineage",
        "artifact_ref": _reference(artifact_ref),
        "canonical_relationship_vocabulary": list(RELATIONSHIP_TYPES),
        "links": normalized,
        "transitive_inference": False,
        "graph_traversal": False,
        "hidden_lookup": False,
        "persistent": False,
        "retention": "process_and_discard",
        "non_proofs": list(_NON_PROOFS),
    }
    return with_artifact_digest(result)


def build_current_build_context(
    *,
    profile_id: str,
    request_baseline: Mapping[str, Any],
    working_blueprint: Mapping[str, Any],
    stage_availability: Mapping[str, Any],
    lineage: Mapping[str, Any],
    artifact_references: Mapping[str, str],
    generation_context: Mapping[str, Any] | None = None,
    python_manifestation: Mapping[str, Any] | None = None,
    circuit_manifestation: Mapping[str, Any] | None = None,
    result_manifestation: Mapping[str, Any] | None = None,
    target_circuit_reference: Mapping[str, Any] | None = None,
    unresolved_questions: Sequence[str] = (),
    carry_forward_proposals: Sequence[Mapping[str, Any]] = (),
    evolved_blueprint: Mapping[str, Any] | None = None,
    artifact_ref: str | None = None,
) -> dict[str, Any]:
    if profile_id not in PROFILE_IDS:
        raise ValueError("unsupported_algorithm_profile")
    if request_baseline.get("artifact_type") != "request_baseline_handoff":
        raise ValueError("share_safe_request_baseline_required")
    if stage_availability.get("schema_id") != STAGE_AVAILABILITY_SCHEMA_ID:
        raise ValueError("stage_availability_required")
    if lineage.get("schema_id") != LINEAGE_SCHEMA_ID:
        raise ValueError("decision_evidence_lineage_required")
    supplied: dict[str, Mapping[str, Any] | None] = {
        "request_baseline": request_baseline,
        "working_blueprint": working_blueprint,
        "generation_context": generation_context,
        "python_manifestation": python_manifestation,
        "circuit_manifestation": circuit_manifestation,
        "result_manifestation": result_manifestation,
        "target_circuit": target_circuit_reference,
        "stage_availability": stage_availability,
        "lineage": lineage,
        "evolved_blueprint": evolved_blueprint,
    }
    descriptors = {}
    for name, value in supplied.items():
        if value is None:
            continue
        descriptors[name] = _artifact_descriptor(
            value, supplied_reference=artifact_references.get(name)
        )
    selected_summaries: dict[str, Any] = {}
    if circuit_manifestation is not None:
        selected_summaries["circuit"] = {
            "qubit_count": circuit_manifestation.get("qubit_count"),
            "classical_bit_count": circuit_manifestation.get("classical_bit_count"),
            "operation_inventory": deepcopy(circuit_manifestation.get("operation_inventory", [])),
            "stage_identity": deepcopy(circuit_manifestation.get("stage_identity")),
        }
    if result_manifestation is not None:
        selected_summaries["result"] = {
            "observed_outcome_count": result_manifestation.get("observed_outcome_count"),
            "observed_shot_count": result_manifestation.get("observed_shot_count"),
            "distribution_shape": deepcopy(result_manifestation.get("distribution_shape", {})),
            "measurement_mapping_qualification": result_manifestation.get(
                "measurement_mapping_qualification"
            ),
            "bit_order_qualification": result_manifestation.get("bit_order_qualification"),
        }
    result = {
        "schema_id": CURRENT_BUILD_CONTEXT_SCHEMA_ID,
        "schema_version": 1,
        "artifact_type": "current_build_context",
        "artifact_ref": _reference(artifact_ref),
        "profile_id": profile_id,
        "artifact_references": descriptors,
        "stage_availability": deepcopy(stage_availability["stages"]),
        "stage_identity": {
            name: deepcopy(value.get("stage_identity"))
            for name, value in (
                ("circuit", circuit_manifestation),
                ("target_circuit", target_circuit_reference),
            )
            if isinstance(value, Mapping)
        },
        "selected_share_safe_summaries": selected_summaries,
        "lineage_summary": {
            "artifact_ref": descriptors["lineage"]["artifact_ref"],
            "explicit_link_count": len(lineage.get("links", [])),
            "transitive_inference": False,
        },
        "unresolved_questions": _text_list(unresolved_questions, field="unresolved_questions"),
        "carry_forward_proposal_references": [
            str(item.get("proposal_ref"))
            for item in carry_forward_proposals
            if isinstance(item, Mapping) and item.get("proposal_ref")
        ],
        "customer_journey_qualifications": {
            "Requested": "Represented in the explicitly supplied Request Baseline.",
            "Assistant Interpreted": "Explicitly supplied assistant proposal; not hidden user intent.",
            "Implemented": "Represented in explicitly supplied Python source evidence.",
            "Constructed": "Represented in an explicitly supplied circuit manifestation.",
            "Observed": "Represented in explicitly supplied result evidence.",
            "Carry Forward": "Proposed or user-confirmed next design treatment.",
        },
        "non_governing": True,
        "children_flattened": False,
        "hidden_operation_calls": False,
        "hosted_extraction": False,
        "retrieval": False,
        "persistent": False,
        "retention": "process_and_discard",
        "non_proofs": list(_NON_PROOFS),
    }
    return with_artifact_digest(result)


def required_evidence_parent_descriptors(
    current_build_context: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Return the exact current-session parents needed by a carry-forward proposal."""

    if current_build_context.get("schema_id") != CURRENT_BUILD_CONTEXT_SCHEMA_ID:
        raise ValueError("current_build_context_required")
    references = current_build_context.get("artifact_references")
    if not isinstance(references, Mapping):
        raise ValueError("current_build_context_artifact_references_required")
    required: list[dict[str, str]] = []
    for name in CURRENT_BUILD_EVIDENCE_PARENT_ORDER:
        descriptor = references.get(name)
        if descriptor is None:
            continue
        if not isinstance(descriptor, Mapping):
            raise ValueError("current_build_context_artifact_reference_invalid")
        artifact_ref = descriptor.get("artifact_ref")
        digest = descriptor.get("digest")
        if (
            not isinstance(artifact_ref, str)
            or not _REFERENCE_PATTERN.fullmatch(artifact_ref)
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise ValueError("current_build_context_artifact_reference_invalid")
        required.append(
            {
                "parent_name": name,
                "artifact_ref": artifact_ref,
                "digest": digest,
            }
        )
    context_descriptor = _artifact_descriptor(current_build_context)
    required.append(
        {
            "parent_name": "current_build_context",
            "artifact_ref": context_descriptor["artifact_ref"],
            "digest": context_descriptor["digest"],
        }
    )
    return required


def evidence_parent_artifacts_error(
    current_build_context: Mapping[str, Any],
    parent_artifacts: object,
) -> str | None:
    """Validate explicit parents without lookup, retrieval, or retained state."""

    if not isinstance(parent_artifacts, list) or not parent_artifacts:
        return "evidence_parent_artifacts_required"
    try:
        required = required_evidence_parent_descriptors(current_build_context)
    except ValueError as exc:
        return str(exc)
    supplied_pairs: set[tuple[str, str]] = set()
    expected_by_ref: dict[str, set[str]] = {}
    for item in required:
        expected_by_ref.setdefault(item["artifact_ref"], set()).add(item["digest"])
    for parent in parent_artifacts:
        if not isinstance(parent, Mapping):
            return "evidence_parent_artifact_invalid"
        try:
            descriptor = _artifact_descriptor(parent)
        except ValueError:
            return "evidence_parent_artifact_reference_invalid"
        pair = (descriptor["artifact_ref"], descriptor["digest"])
        if pair in supplied_pairs:
            return "evidence_parent_artifact_duplicate"
        if descriptor["artifact_ref"] not in expected_by_ref:
            return "evidence_parent_artifact_unexpected"
        if descriptor["digest"] not in expected_by_ref[descriptor["artifact_ref"]]:
            return "evidence_parent_artifact_digest_mismatch"
        supplied_pairs.add(pair)
    expected_pairs = {(item["artifact_ref"], item["digest"]) for item in required}
    if expected_pairs - supplied_pairs:
        return "evidence_parent_artifact_missing"
    return None


def portable_current_build_context_field_inventory() -> list[dict[str, Any]]:
    """Machine-readable candidate inventory for passive local rendering."""

    def field(
        path: str,
        source: str,
        *,
        required: bool,
        maximum_size: int | None = None,
        maximum_collection_length: int | None = None,
        depth: int = 1,
        classification: str = "share_safe_structural",
        rendered: bool = True,
        user_text: bool = False,
        assistant_text: bool = False,
        opaque_references: bool = False,
        bounded_evidence: bool = False,
        prohibited: Sequence[str] = (),
    ) -> dict[str, Any]:
        return {
            "field_path": path,
            "source_contract": source,
            "required": required,
            "maximum_size": maximum_size,
            "maximum_collection_length": maximum_collection_length,
            "maximum_nesting_depth_contribution": depth,
            "share_safety_classification": classification,
            "rendered": rendered,
            "hidden": not rendered,
            "exportable": True,
            "may_contain_user_text": user_text,
            "may_contain_assistant_text": assistant_text,
            "may_contain_opaque_references": opaque_references,
            "may_contain_bounded_evidence": bounded_evidence,
            "prohibited_content": list(prohibited),
            "authenticity_meaning": "none",
            "protected_policy_dependency": "none",
        }

    text_limit = PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS["maximum_individual_text_field_length"]
    return [
        field("schema_id", "portable_envelope", required=True, rendered=False),
        field("schema_version", "portable_envelope", required=True, rendered=False),
        field("artifact_type", "portable_envelope", required=True, rendered=False),
        field("inventory_status", "portable_envelope", required=True, rendered=False),
        field(
            "source_current_build_context_reference",
            CURRENT_BUILD_CONTEXT_SCHEMA_ID,
            required=True,
            opaque_references=True,
            rendered=False,
        ),
        field("profile_id", CURRENT_BUILD_CONTEXT_SCHEMA_ID, required=True),
        field(
            "artifact_references[]",
            CURRENT_BUILD_CONTEXT_SCHEMA_ID,
            required=True,
            maximum_collection_length=PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS[
                "maximum_artifact_references"
            ],
            opaque_references=True,
        ),
        field(
            "stage_availability.*",
            STAGE_AVAILABILITY_SCHEMA_ID,
            required=True,
            maximum_collection_length=PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS[
                "maximum_stage_summaries"
            ],
        ),
        field(
            "stage_identity.*",
            CIRCUIT_MANIFESTATION_SCHEMA_ID,
            required=False,
            maximum_collection_length=PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS[
                "maximum_stage_summaries"
            ],
        ),
        field(
            "selected_share_safe_summaries.*",
            CURRENT_BUILD_CONTEXT_SCHEMA_ID,
            required=False,
            maximum_collection_length=PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS[
                "maximum_evidence_findings"
            ],
            bounded_evidence=True,
            prohibited=tuple(sorted(_PORTABLE_PROHIBITED_FIELDS)),
        ),
        field(
            "decision_records[]",
            "blueprint_decision_record.v1",
            required=False,
            maximum_collection_length=PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS["maximum_decisions"],
            maximum_size=text_limit,
            user_text=True,
            assistant_text=True,
            opaque_references=True,
            bounded_evidence=True,
        ),
        field(
            "decision_evidence_lineage",
            LINEAGE_SCHEMA_ID,
            required=True,
            opaque_references=True,
        ),
        field(
            "decision_evidence_lineage.links[]",
            LINEAGE_SCHEMA_ID,
            required=False,
            maximum_collection_length=PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS[
                "maximum_lineage_links"
            ],
            maximum_size=text_limit,
            opaque_references=True,
            bounded_evidence=True,
        ),
        field(
            "readiness",
            "blueprint_readiness_summary.v1",
            required=False,
            maximum_size=text_limit,
            bounded_evidence=True,
        ),
        field(
            "applicable_actions[]",
            CARRY_FORWARD_SCHEMA_ID,
            required=False,
            maximum_collection_length=len(ACTION_IDS),
            opaque_references=True,
        ),
        field(
            "carry_forward_proposal",
            CARRY_FORWARD_SCHEMA_ID,
            required=False,
            maximum_size=32_768,
            maximum_collection_length=PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS[
                "maximum_proposal_before_after_entries"
            ],
            user_text=True,
            assistant_text=True,
            opaque_references=True,
            bounded_evidence=True,
        ),
        field(
            "confirmation_transport",
            PORTABLE_CURRENT_BUILD_CONTEXT_SCHEMA_ID,
            required=False,
            maximum_size=PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS["maximum_serialized_bytes"],
            depth=10,
            classification="share_safe_confirmation_transport",
            rendered=False,
            user_text=True,
            assistant_text=True,
            opaque_references=True,
            bounded_evidence=True,
            prohibited=tuple(sorted(_PORTABLE_PROHIBITED_FIELDS)),
        ),
        field(
            "non_proofs[]",
            CURRENT_BUILD_CONTEXT_SCHEMA_ID,
            required=True,
            maximum_collection_length=16,
            maximum_size=text_limit,
        ),
        field("validation", "portable_envelope", required=True),
        field("transport", "portable_envelope", required=True),
        field("share_safety", "portable_envelope", required=True),
        field("retention", "portable_envelope", required=True),
        field("persistent", "portable_envelope", required=True),
        field("consistency_digest", "portable_envelope", required=True, rendered=False),
    ]


def _portable_projection(value: Mapping[str, Any], allowed_fields: Sequence[str]) -> dict[str, Any]:
    return {field: deepcopy(value[field]) for field in allowed_fields if field in value}


def _portable_json_interoperable_numbers(value: Any) -> Any:
    """Match browser JSON number serialization for portable consistency digests."""

    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_portable_json_interoperable_numbers(item) for item in value]
    if isinstance(value, tuple):
        return [_portable_json_interoperable_numbers(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _portable_json_interoperable_numbers(item) for key, item in value.items()}
    return value


def _portable_structure_error(value: object) -> str | None:
    limits = PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS
    counters = {"properties": 0, "text": 0}

    def inspect(item: object, *, depth: int, path: tuple[str, ...]) -> str | None:
        if depth > limits["maximum_json_nesting_depth"]:
            return "portable_bundle_nesting_too_deep"
        if isinstance(item, Mapping):
            counters["properties"] += len(item)
            if counters["properties"] > limits["maximum_object_property_count"]:
                return "portable_bundle_too_many_properties"
            for key, nested in item.items():
                if not isinstance(key, str):
                    return "portable_bundle_property_name_invalid"
                if key in _PORTABLE_DANGEROUS_PROPERTY_NAMES:
                    return "portable_bundle_dangerous_property"
                if key.lower() in _PORTABLE_PROHIBITED_FIELDS and nested is not False:
                    return "portable_bundle_prohibited_content"
                error = inspect(nested, depth=depth + 1, path=(*path, key))
                if error:
                    return error
            return None
        if isinstance(item, (list, tuple)):
            maximum = limits["maximum_array_length"]
            leaf = path[-1] if path else ""
            maximum = {
                "artifact_references": limits["maximum_artifact_references"],
                "decision_records": limits["maximum_decisions"],
                "links": limits["maximum_lineage_links"],
                "applicable_actions": len(ACTION_IDS),
            }.get(leaf, maximum)
            if len(item) > maximum:
                return "portable_bundle_collection_too_large"
            for nested in item:
                error = inspect(nested, depth=depth + 1, path=path)
                if error:
                    return error
            return None
        if isinstance(item, str):
            if len(item) > limits["maximum_individual_text_field_length"]:
                return "portable_bundle_text_field_too_large"
            counters["text"] += len(item)
            if counters["text"] > limits["maximum_total_text_size"]:
                return "portable_bundle_total_text_too_large"
            return None
        if item is None or isinstance(item, (bool, int)):
            return None
        if isinstance(item, float) and math.isfinite(item):
            return None
        return "portable_bundle_value_invalid"

    error = inspect(value, depth=1, path=())
    if error:
        return error
    try:
        serialized = _canonical_json(value).encode("utf-8")
    except (TypeError, ValueError):
        return "portable_bundle_not_json_serializable"
    if len(serialized) > limits["maximum_serialized_bytes"]:
        return "portable_bundle_serialized_size_exceeded"
    return None


def portable_confirmation_transport_error(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return "portable_confirmation_transport_invalid"
    if (
        value.get("schema_version") != 1
        or value.get("purpose") != "current_build_context_confirmation"
        or value.get("tool_name") != "create_implementation_blueprint"
    ):
        return "portable_confirmation_transport_version_invalid"
    tool_input = value.get("tool_input")
    if not isinstance(tool_input, Mapping):
        return "portable_confirmation_tool_input_invalid"
    if (
        tool_input.get("context_loop") != CONTEXT_LOOP_GATE
        or tool_input.get("resolution_context") != RESOLUTION_CONTEXT
        or tool_input.get("resolution_phase") != "confirm"
    ):
        return "portable_confirmation_gate_mismatch"
    selected_action = tool_input.get("selected_action")
    if selected_action not in ACTION_IDS:
        return "portable_confirmation_action_invalid"
    proposal = tool_input.get("decision_resolution_pack")
    parents = tool_input.get("evidence_parent_artifacts")
    context = tool_input.get("current_build_context")
    working_blueprint = tool_input.get("working_blueprint")
    record_set = tool_input.get("blueprint_decision_records")
    if not isinstance(proposal, dict):
        return "portable_confirmation_proposal_missing"
    if not isinstance(parents, list) or not isinstance(context, Mapping):
        return "portable_confirmation_parents_missing"
    if not isinstance(working_blueprint, Mapping) or not isinstance(record_set, Mapping):
        return "portable_confirmation_working_blueprint_missing"
    records = record_set.get("records")
    if not isinstance(records, list) or not records:
        return "portable_confirmation_decision_records_missing"
    if working_blueprint.get("blueprint_decision_records") != record_set:
        return "portable_confirmation_decision_records_mismatch"
    parent_error = evidence_parent_artifacts_error(context, parents)
    if parent_error:
        return parent_error
    proposal_error = decision_resolution_pack_error(
        proposal,
        parent_artifacts=parents,
        selected_action=str(selected_action),
    )
    if proposal_error:
        return proposal_error
    if tool_input.get("proposal_ref") != proposal.get("proposal_ref") or tool_input.get(
        "selected_action"
    ) != proposal.get("selected_action"):
        return "portable_confirmation_binding_mismatch"
    confirmation = tool_input.get("resolution_confirmation")
    if (
        not isinstance(confirmation, Mapping)
        or confirmation.get("confirmed") is not True
        or not isinstance(confirmation.get("confirmed_by"), str)
        or not str(confirmation.get("confirmed_by")).strip()
    ):
        return "portable_confirmation_explicit_marker_required"
    expected_payload = proposal.get("explicit_confirmation_requirements", {}).get(
        "confirmation_payload"
    )
    if tool_input.get("confirmation_payload") != expected_payload:
        return "portable_confirmation_payload_mismatch"
    try:
        request_bytes = canonical_context_bridge_request_bytes(
            tool_name="create_implementation_blueprint",
            tool_input=tool_input,
        )
    except (TypeError, ValueError):
        return "portable_confirmation_not_json_serializable"
    if len(request_bytes) > PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS["maximum_serialized_bytes"]:
        return "portable_confirmation_request_too_large"
    digest = value.get("canonical_request_sha256")
    expected_digest = hashlib.sha256(request_bytes).hexdigest()
    if digest != expected_digest:
        return "portable_confirmation_request_digest_mismatch"
    validation = value.get("validation")
    if validation != {
        "artifact_structure_validated": True,
        "relationships_and_consistency_references_validated": True,
        "digest_meaning": "deterministic_consistency_reference_only",
        "authentication_claim": False,
        "authorship_claim": False,
        "confirmation_inferred": False,
    }:
        return "portable_confirmation_validation_claim_invalid"
    return None


def portable_proposal_resupply_error(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return "portable_proposal_resupply_invalid"
    if (
        value.get("schema_version") != 1
        or value.get("purpose") != "current_build_context_proposal_resupply"
        or value.get("tool_name") != "create_implementation_blueprint"
    ):
        return "portable_proposal_resupply_version_invalid"
    tool_input = value.get("tool_input")
    proposal = value.get("carry_forward_proposal")
    if not isinstance(tool_input, Mapping) or not isinstance(proposal, dict):
        return "portable_proposal_resupply_input_invalid"
    if (
        tool_input.get("context_loop") != CONTEXT_LOOP_GATE
        or tool_input.get("resolution_context") != RESOLUTION_CONTEXT
        or tool_input.get("resolution_phase") != "propose"
    ):
        return "portable_proposal_resupply_gate_mismatch"
    if any(field in tool_input for field in ("resolution_confirmation", "confirmation_payload")):
        return "portable_proposal_resupply_confirmation_forbidden"
    parents = tool_input.get("evidence_parent_artifacts")
    context = tool_input.get("current_build_context")
    working_blueprint = tool_input.get("working_blueprint")
    record_set = tool_input.get("blueprint_decision_records")
    if not isinstance(parents, list) or not isinstance(context, Mapping):
        return "portable_proposal_resupply_parents_missing"
    if not isinstance(working_blueprint, Mapping) or not isinstance(record_set, Mapping):
        return "portable_proposal_resupply_working_blueprint_missing"
    if working_blueprint.get("blueprint_decision_records") != record_set:
        return "portable_proposal_resupply_decision_records_mismatch"
    parent_error = evidence_parent_artifacts_error(context, parents)
    if parent_error:
        return parent_error
    proposal_error = decision_resolution_pack_error(
        proposal,
        parent_artifacts=parents,
        selected_action=str(tool_input.get("selected_action")),
    )
    if proposal_error:
        return proposal_error
    if (
        tool_input.get("selected_action") != proposal.get("selected_action")
        or tool_input.get("selected_decision_references") != proposal.get("decision_references")
        or tool_input.get("proposed_updates")
        != proposal.get("proposed_outcome", {}).get("decision_updates")
    ):
        return "portable_proposal_resupply_binding_mismatch"
    digest = value.get("canonical_request_sha256")
    expected_digest = canonical_context_bridge_request_sha256(
        tool_name="create_implementation_blueprint",
        tool_input=tool_input,
    )
    if digest != expected_digest:
        return "portable_proposal_resupply_request_digest_mismatch"
    if value.get("validation") != {
        "artifact_structure_validated": True,
        "relationships_and_consistency_references_validated": True,
        "digest_meaning": "deterministic_consistency_reference_only",
        "authentication_claim": False,
        "authorship_claim": False,
        "confirmation_inferred": False,
    }:
        return "portable_proposal_resupply_validation_claim_invalid"
    return None


def portable_proposal_parent_resupply_error(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return "portable_proposal_parent_resupply_invalid"
    if (
        value.get("schema_version") != 1
        or value.get("purpose") != "current_build_context_proposal_parent_resupply"
        or value.get("tool_name") != "create_implementation_blueprint"
    ):
        return "portable_proposal_parent_resupply_version_invalid"
    tool_input = value.get("tool_input")
    if not isinstance(tool_input, Mapping):
        return "portable_proposal_parent_resupply_input_invalid"
    if (
        tool_input.get("context_loop") != CONTEXT_LOOP_GATE
        or tool_input.get("resolution_context") != RESOLUTION_CONTEXT
        or tool_input.get("resolution_phase") != "propose"
    ):
        return "portable_proposal_parent_resupply_gate_mismatch"
    prohibited = {
        "algorithm_intent_card",
        "intent_relationship",
        "selected_action",
        "selected_decision_references",
        "proposed_updates",
        "proposal_ref",
        "resolution_confirmation",
        "confirmation_payload",
        "decision_resolution_pack",
    }
    if prohibited.intersection(tool_input):
        return "portable_proposal_parent_resupply_overlay_forbidden"
    parents = tool_input.get("evidence_parent_artifacts")
    context = tool_input.get("current_build_context")
    working_blueprint = tool_input.get("working_blueprint")
    record_set = tool_input.get("blueprint_decision_records")
    if not isinstance(parents, list) or not isinstance(context, Mapping):
        return "portable_proposal_parent_resupply_parents_missing"
    if not isinstance(working_blueprint, Mapping) or not isinstance(record_set, Mapping):
        return "portable_proposal_parent_resupply_working_blueprint_missing"
    if working_blueprint.get("blueprint_decision_records") != record_set:
        return "portable_proposal_parent_resupply_decision_records_mismatch"
    parent_error = evidence_parent_artifacts_error(context, parents)
    if parent_error:
        return parent_error
    digest = value.get("canonical_parent_request_sha256")
    expected_digest = canonical_context_bridge_request_sha256(
        tool_name="create_implementation_blueprint",
        tool_input=tool_input,
    )
    if digest != expected_digest:
        return "portable_proposal_parent_resupply_request_digest_mismatch"
    if value.get("validation") != {
        "artifact_structure_validated": True,
        "relationships_and_consistency_references_validated": True,
        "digest_meaning": "deterministic_consistency_reference_only",
        "authentication_claim": False,
        "authorship_claim": False,
        "confirmation_inferred": False,
        "proposal_inferred": False,
    }:
        return "portable_proposal_parent_resupply_validation_claim_invalid"
    return None


def portable_current_build_context_error(value: object) -> str | None:
    if not isinstance(value, dict):
        return "portable_current_build_context_invalid"
    if (
        value.get("schema_id") != PORTABLE_CURRENT_BUILD_CONTEXT_SCHEMA_ID
        or value.get("schema_version") != 1
        or value.get("artifact_type") != "portable_current_build_context"
    ):
        return "portable_current_build_context_version_invalid"
    if value.get("inventory_status") not in PORTABLE_BUNDLE_INVENTORY_STATUSES:
        return "portable_bundle_inventory_status_invalid"
    structural_error = _portable_structure_error(value)
    if structural_error:
        return structural_error
    digest = value.get("consistency_digest")
    if not isinstance(digest, str) or digest != consistency_digest(value):
        return "portable_bundle_consistency_digest_invalid"
    confirmation_transport = value.get("confirmation_transport")
    if confirmation_transport is not None:
        transport_error = portable_confirmation_transport_error(confirmation_transport)
        if transport_error:
            return transport_error
    transport = value.get("transport")
    if isinstance(transport, Mapping):
        if transport.get("proposal_parent_resupply") is not None:
            transport_error = portable_proposal_parent_resupply_error(
                transport["proposal_parent_resupply"]
            )
            if transport_error:
                return transport_error
        if transport.get("proposal_resupply") is not None:
            transport_error = portable_proposal_resupply_error(transport["proposal_resupply"])
            if transport_error:
                return transport_error
    validation = value.get("validation")
    if not isinstance(validation, Mapping) or validation != {
        "artifact_structure_validated": True,
        "relationships_and_consistency_references_validated_within_supplied_bundle": True,
        "artifact_authenticated": False,
        "produced_by_qcoder_verified": False,
        "artifact_proven_unmodified": False,
        "customer_ownership_verified": False,
        "digest_meaning": "deterministic_consistency_reference_only",
    }:
        return "portable_bundle_validation_claim_invalid"
    return None


def attach_portable_proposal_parent_resupply(
    portable: Mapping[str, Any],
    *,
    tool_input: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach exact current-build parents for one later local proposal call."""

    if portable_current_build_context_error(dict(portable)):
        raise ValueError("portable_current_build_context_invalid")
    normalized_tool_input = _portable_json_interoperable_numbers(deepcopy(dict(tool_input)))
    result = deepcopy(dict(portable))
    result.pop("consistency_digest", None)
    transport = deepcopy(result["transport"])
    transport["proposal_parent_resupply"] = {
        "schema_version": 1,
        "purpose": "current_build_context_proposal_parent_resupply",
        "tool_name": "create_implementation_blueprint",
        "tool_input": normalized_tool_input,
        "canonical_parent_request_sha256": canonical_context_bridge_request_sha256(
            tool_name="create_implementation_blueprint",
            tool_input=normalized_tool_input,
        ),
        "validation": {
            "artifact_structure_validated": True,
            "relationships_and_consistency_references_validated": True,
            "digest_meaning": "deterministic_consistency_reference_only",
            "authentication_claim": False,
            "authorship_claim": False,
            "confirmation_inferred": False,
            "proposal_inferred": False,
        },
    }
    result["transport"] = transport
    result = with_consistency_digest(_portable_json_interoperable_numbers(result))
    error = portable_current_build_context_error(result)
    if error:
        raise ValueError(error)
    return result


def attach_portable_proposal_resupply(
    portable: Mapping[str, Any],
    *,
    tool_input: Mapping[str, Any],
    carry_forward_proposal: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach exact proposal inputs for a later explicit selected-file confirmation."""

    if portable_current_build_context_error(dict(portable)):
        raise ValueError("portable_current_build_context_invalid")
    normalized_tool_input = _portable_json_interoperable_numbers(deepcopy(dict(tool_input)))
    normalized_proposal = _portable_json_interoperable_numbers(
        deepcopy(dict(carry_forward_proposal))
    )
    result = deepcopy(dict(portable))
    result.pop("consistency_digest", None)
    transport = deepcopy(result["transport"])
    transport["proposal_resupply"] = {
        "schema_version": 1,
        "purpose": "current_build_context_proposal_resupply",
        "tool_name": "create_implementation_blueprint",
        "tool_input": normalized_tool_input,
        "carry_forward_proposal": normalized_proposal,
        "canonical_request_sha256": canonical_context_bridge_request_sha256(
            tool_name="create_implementation_blueprint",
            tool_input=normalized_tool_input,
        ),
        "validation": {
            "artifact_structure_validated": True,
            "relationships_and_consistency_references_validated": True,
            "digest_meaning": "deterministic_consistency_reference_only",
            "authentication_claim": False,
            "authorship_claim": False,
            "confirmation_inferred": False,
        },
    }
    result["transport"] = transport
    result = with_consistency_digest(_portable_json_interoperable_numbers(result))
    error = portable_current_build_context_error(result)
    if error:
        raise ValueError(error)
    return result


def attach_portable_confirmation_transport(
    portable: Mapping[str, Any],
    *,
    tool_input: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach one exact, share-safe confirmation request to a portable bundle."""

    if portable_current_build_context_error(dict(portable)):
        raise ValueError("portable_current_build_context_invalid")
    normalized_tool_input = _portable_json_interoperable_numbers(deepcopy(dict(tool_input)))
    request_digest = canonical_context_bridge_request_sha256(
        tool_name="create_implementation_blueprint",
        tool_input=normalized_tool_input,
    )
    result = deepcopy(dict(portable))
    result.pop("consistency_digest", None)
    result["confirmation_transport"] = {
        "schema_version": 1,
        "purpose": "current_build_context_confirmation",
        "tool_name": "create_implementation_blueprint",
        "tool_input": normalized_tool_input,
        "canonical_request_sha256": request_digest,
        "validation": {
            "artifact_structure_validated": True,
            "relationships_and_consistency_references_validated": True,
            "digest_meaning": "deterministic_consistency_reference_only",
            "authentication_claim": False,
            "authorship_claim": False,
            "confirmation_inferred": False,
        },
    }
    result = with_consistency_digest(_portable_json_interoperable_numbers(result))
    error = portable_current_build_context_error(result)
    if error:
        raise ValueError(error)
    return result


def freeze_portable_current_build_context_candidate(
    portable: Mapping[str, Any],
) -> dict[str, Any]:
    """Mark a proven bundle inventory as the companion-page v1 freeze candidate."""

    if portable_current_build_context_error(dict(portable)):
        raise ValueError("portable_current_build_context_invalid")
    result = deepcopy(dict(portable))
    result.pop("consistency_digest", None)
    result["inventory_status"] = PORTABLE_BUNDLE_FROZEN_STATUS
    result = with_consistency_digest(_portable_json_interoperable_numbers(result))
    error = portable_current_build_context_error(result)
    if error:
        raise ValueError(error)
    return result


def build_portable_current_build_context(
    *,
    current_build_context: Mapping[str, Any],
    decision_records: Sequence[Mapping[str, Any]] = (),
    decision_evidence_lineage: Mapping[str, Any],
    readiness: Mapping[str, Any] | None = None,
    applicable_actions: Sequence[Mapping[str, Any]] = (),
    carry_forward_proposal: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a supplied Current Build Context for inert, passive rendering."""

    if current_build_context.get("schema_id") != CURRENT_BUILD_CONTEXT_SCHEMA_ID:
        raise ValueError("current_build_context_required")
    if decision_evidence_lineage.get("schema_id") != LINEAGE_SCHEMA_ID:
        raise ValueError("decision_evidence_lineage_required")
    context_descriptor = _artifact_descriptor(current_build_context)
    references = current_build_context.get("artifact_references")
    if not isinstance(references, Mapping):
        raise ValueError("current_build_context_artifact_references_required")
    projected_decisions = [
        _portable_projection(
            item,
            (
                "decision_ref",
                "profile_decision_id",
                "semantic_classification",
                "semantic_role",
                "applicable_scope",
                "resolution_state",
                "user_disposition",
                "generation_effect",
                "selected_value",
                "allowed_choices",
                "bounds",
                "control_treatment",
                "resource_architecture",
                "provenance_entries",
                "unresolved_questions",
                "evidence_expectation",
                "future_review_rule",
                "remaining_non_proofs",
            ),
        )
        for item in decision_records
    ]
    projected_proposal = (
        deepcopy(dict(carry_forward_proposal)) if carry_forward_proposal is not None else None
    )
    result = {
        "schema_id": PORTABLE_CURRENT_BUILD_CONTEXT_SCHEMA_ID,
        "schema_version": 1,
        "artifact_type": "portable_current_build_context",
        "inventory_status": PORTABLE_BUNDLE_INVENTORY_STATUS,
        "source_current_build_context_reference": context_descriptor,
        "profile_id": current_build_context.get("profile_id"),
        "artifact_references": [
            {"name": name, **deepcopy(dict(descriptor))}
            for name, descriptor in sorted(references.items())
            if isinstance(descriptor, Mapping)
        ],
        "stage_availability": deepcopy(current_build_context.get("stage_availability", {})),
        "stage_identity": deepcopy(current_build_context.get("stage_identity", {})),
        "selected_share_safe_summaries": deepcopy(
            current_build_context.get("selected_share_safe_summaries", {})
        ),
        "decision_records": projected_decisions,
        "decision_evidence_lineage": {
            "artifact_ref": decision_evidence_lineage.get("artifact_ref"),
            "artifact_digest": decision_evidence_lineage.get("artifact_digest"),
            "links": deepcopy(decision_evidence_lineage.get("links", [])),
            "transitive_inference": False,
            "graph_traversal": False,
            "retrievable": False,
            "persistent": False,
        },
        "readiness": (
            _portable_projection(
                readiness,
                (
                    "aggregate_readiness_result",
                    "generation_context_eligibility",
                    "blocking_decision_references",
                    "bounded_discretion_decision_references",
                    "evidence_deferred_decision_references",
                    "non_proof",
                ),
            )
            if readiness is not None
            else None
        ),
        "applicable_actions": [
            _portable_projection(item, ("decision_ref", "action_ids"))
            for item in applicable_actions
        ],
        "carry_forward_proposal": projected_proposal,
        "non_proofs": list(current_build_context.get("non_proofs", _NON_PROOFS)),
        "validation": {
            "artifact_structure_validated": True,
            "relationships_and_consistency_references_validated_within_supplied_bundle": True,
            "artifact_authenticated": False,
            "produced_by_qcoder_verified": False,
            "artifact_proven_unmodified": False,
            "customer_ownership_verified": False,
            "digest_meaning": "deterministic_consistency_reference_only",
        },
        "transport": {
            "scope": "current_session",
            "user_controlled": True,
            "self_contained_for_passive_rendering": True,
            "retrievable": False,
            "authoritative": False,
            "file_export_suitable": True,
            "local_browser_import_candidate": True,
            "inert_text_only": True,
            "html_execution": False,
            "markdown_html_execution": False,
            "script_execution": False,
            "dynamic_import": False,
            "url_fetching": False,
            "expression_evaluation": False,
            "component_construction_from_imported_identifiers": False,
        },
        "share_safety": {
            "raw_source_included": False,
            "raw_qasm_included": False,
            "raw_circuit_serialization_included": False,
            "sensitive_raw_results_included": False,
            "raw_paths_included": False,
            "credentials_included": False,
            "proprietary_problem_data_included": False,
            "protected_policy_included": False,
        },
        "retention": "caller_controlled_portable_file",
        "persistent": False,
    }
    result = with_consistency_digest(_portable_json_interoperable_numbers(result))
    error = portable_current_build_context_error(result)
    if error:
        raise ValueError(error)
    return result


def canonical_portable_current_build_context_json(value: object) -> str:
    error = portable_current_build_context_error(value)
    if error:
        raise ValueError(error)
    return _canonical_json(value)


def context_loop_gate_matrix(
    *,
    context_loop: str | None,
    source_evidence_depth: str | None,
    decision_loop: str | None,
    supplied_children: Iterable[str] = (),
) -> dict[str, Any]:
    valid = {
        "context_loop": {None, CONTEXT_LOOP_DISABLED, CONTEXT_LOOP_GATE},
        "source_evidence_depth": {None, "disabled", "depth_v1"},
        "decision_loop": {None, "disabled", "readiness_resolution_v1"},
    }
    supplied = {
        "context_loop": context_loop,
        "source_evidence_depth": source_evidence_depth,
        "decision_loop": decision_loop,
    }
    diagnostics = [
        f"unsupported_{name}_gate" for name, value in supplied.items() if value not in valid[name]
    ]
    enabled = {
        "context_loop": context_loop == CONTEXT_LOOP_GATE,
        "source_evidence_depth": source_evidence_depth == "depth_v1",
        "decision_loop": decision_loop == "readiness_resolution_v1",
    }
    children = set(supplied_children)
    if enabled["context_loop"] and not children:
        diagnostics.append("context_loop_children_not_supplied")
    return {
        "context_loop": context_loop,
        "source_evidence_depth": source_evidence_depth,
        "decision_loop": decision_loop,
        "enabled": enabled,
        "supported": not any(item.startswith("unsupported_") for item in diagnostics),
        "diagnostics": diagnostics,
        "cascading_activation": False,
        "legacy_behavior_preserved": not any(enabled.values()),
    }


def build_carry_forward_proposal(
    *,
    selected_action: str,
    profile_id: str,
    decision_records: list[dict[str, Any]],
    parent_artifacts: list[dict[str, Any]],
    current_build_context: Mapping[str, Any],
    selected_decision_references: list[str],
    proposed_updates: list[dict[str, Any]],
    current_lineage_reference: str,
    remaining_uncertainty: Sequence[str],
    generation_context_effect: str,
    proposal_ref: str | None = None,
    prospective_derived_references: list[str] | None = None,
) -> dict[str, Any]:
    if selected_action not in ACTION_IDS:
        raise ValueError("unsupported_action")
    if current_build_context.get("schema_id") != CURRENT_BUILD_CONTEXT_SCHEMA_ID:
        raise ValueError("current_build_context_required")
    parent_error = evidence_parent_artifacts_error(current_build_context, parent_artifacts)
    if parent_error:
        raise ValueError(parent_error)
    pack = propose_decision_resolution_pack(
        resolution_context=RESOLUTION_CONTEXT,
        selected_action=selected_action,
        profile_id=profile_id,
        decision_records=decision_records,
        parent_artifacts=parent_artifacts,
        selected_decision_references=selected_decision_references,
        proposed_updates=proposed_updates,
        current_lineage_reference=current_lineage_reference,
        proposal_ref=proposal_ref,
        prospective_derived_references=prospective_derived_references,
    )
    pack["carry_forward_contract"] = CARRY_FORWARD_SCHEMA_ID
    pack["current_build_context_reference"] = current_build_context.get("artifact_ref")
    pack["evidence_parent_references"] = deepcopy(
        current_build_context.get("artifact_references", {})
    )
    pack["request_basis_reference"] = (
        current_build_context.get("artifact_references", {})
        .get("request_baseline", {})
        .get("artifact_ref")
    )
    pack["generation_context_effect"] = _text(
        generation_context_effect, field="generation_context_effect", maximum=1_000
    )
    pack["remaining_uncertainty"] = _text_list(remaining_uncertainty, field="remaining_uncertainty")
    pack["cross_stage_evidence_selects_action"] = False
    pack["user_selected_action"] = True
    pack["result_observation_is_design_intent"] = False
    pack["evidence_parent_requirements"] = required_evidence_parent_descriptors(
        current_build_context
    )
    resource_changes = pack.get("resource_architecture_changes") or []
    if resource_changes:
        change = resource_changes[0]
        selected_ref = change["decision_ref"]
        before_record = next(
            item for item in decision_records if item["decision_ref"] == selected_ref
        )
        explicitly_disallowed = list(before_record.get("explicitly_disallowed_choices") or [])
        before = change.get("before") or {}
        pack["resource_architecture_proposal"] = {
            "schema_id": RESOURCE_ARCHITECTURE_SCHEMA_ID,
            "before": {
                "selected_value": deepcopy(before.get("selected_value")),
                "resource_architecture": deepcopy(before.get("resource_architecture")),
                "allowed_qiskit_manifestations": [
                    "direct_quantum_circuit",
                    "explicit_named_registers",
                ],
                "construction_policy": {
                    "explicitly_disallowed_legacy_choices": explicitly_disallowed,
                    "dynamic_factory_policy_inferred": False,
                },
                "readiness": pack["readiness_impact"]["before"],
            },
            "proposed_after": deepcopy(change["proposed_after"]),
            "scope": RESOURCE_ARCHITECTURE_SCOPE,
            "qualifications": {
                "global_generic_qiskit_default": False,
                "explorer_wide_restriction": False,
                "explicit_named_registers_supported": True,
                "pro_uses_same_logical_architecture_vocabulary": True,
                "future_sdk_manifestations_may_differ": True,
                "circuit_or_qasm_proves_python_constructor": False,
                "result_evidence_selected_design": False,
                "direct_construction_superior_or_correct": False,
                "future_evolution_may_change_architecture_and_manifestation": True,
            },
            "readiness_scope": "current_generation_contract_only",
            "readiness_non_proofs": [
                "correctness",
                "completeness",
                "source_to_circuit_equivalence",
                "run_readiness",
                "manifestation_quality",
                "global_preference",
            ],
        }
    return with_consistency_digest(pack)


def materialize_evolved_blueprint(
    *,
    decision_resolution_pack: dict[str, Any],
    parent_artifacts: list[dict[str, Any]],
    working_blueprint: dict[str, Any],
    decision_records: list[dict[str, Any]],
    selected_action: str,
    confirmed: bool,
    confirmation_payload: dict[str, Any],
    provenance_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if decision_resolution_pack.get("resolution_context") != RESOLUTION_CONTEXT:
        raise ValueError("current_build_context_resolution_required")
    error = decision_resolution_pack_error(
        decision_resolution_pack,
        parent_artifacts=parent_artifacts,
        selected_action=selected_action,
    )
    if error:
        raise ValueError(error)
    parent_before = _canonical_json(working_blueprint)
    confirmed_result = confirm_decision_resolution_pack(
        decision_resolution_pack=decision_resolution_pack,
        parent_artifacts=parent_artifacts,
        decision_records=decision_records,
        selected_action=selected_action,
        confirmed=confirmed,
        confirmation_payload=confirmation_payload,
    )
    if _canonical_json(working_blueprint) != parent_before:
        raise RuntimeError("working_blueprint_mutated")
    materialized = confirmed_result["materialized_artifact"]
    evolved: dict[str, Any] | None = None
    if selected_action == "accept_and_add_to_blueprint":
        evolved = {
            "schema_id": EVOLVED_BLUEPRINT_SCHEMA_ID,
            "schema_version": 1,
            "artifact_type": "evolved_blueprint",
            "derived_artifact_reference": materialized["derived_artifact_reference"],
            "working_blueprint_parent": _artifact_descriptor(
                working_blueprint,
                supplied_reference=(
                    working_blueprint.get("artifact_ref")
                    if isinstance(working_blueprint.get("artifact_ref"), str)
                    else None
                ),
            ),
            "evidence_parent_references": deepcopy(
                decision_resolution_pack.get("evidence_parent_references", {})
            ),
            "requirements": deepcopy(working_blueprint.get("requirements", [])),
            "decision_records": deepcopy(materialized["decision_records"]),
            "resource_architecture_decisions": [
                deepcopy(item["resource_architecture"])
                for item in materialized["decision_records"]
                if isinstance(item.get("resource_architecture"), dict)
            ],
            "changed_decisions": deepcopy(decision_resolution_pack["decisions_changed"]),
            "unchanged_decisions": deepcopy(decision_resolution_pack["decisions_unchanged"]),
            "requirements_unchanged": True,
            "provenance_entries": [deepcopy(dict(item)) for item in provenance_entries]
            + [
                {
                    "role": "user_confirmed_carry_forward",
                    "proposal_ref": decision_resolution_pack["proposal_ref"],
                    "selected_action": selected_action,
                    "preserves_earlier_provenance": True,
                }
            ],
            "parent_mutated": False,
            "hidden_lookup_performed": False,
            "retention": "process_and_discard",
            "non_proofs": list(_NON_PROOFS),
        }
        evolved = with_artifact_digest(evolved)
    return {
        "decision_resolution_pack": deepcopy(decision_resolution_pack),
        "materialized_outcome": materialized,
        "evolved_blueprint": evolved,
        "parent_artifacts_mutated": False,
        "hidden_lookup_performed": False,
        "retained_artifacts": [],
        "retention": "process_and_discard",
    }


def context_loop_contract_snapshot() -> dict[str, Any]:
    from qcoder.current_loop_coordinator import coordinator_contract_snapshot

    return {
        "gate": CONTEXT_LOOP_GATE,
        "disabled": CONTEXT_LOOP_DISABLED,
        "schemas": {
            "request_baseline": REQUEST_BASELINE_SCHEMA_ID,
            "generation_posture": GENERATION_POSTURE_SCHEMA_ID,
            "exploratory_generation": EXPLORATORY_GENERATION_SCHEMA_ID,
            "stage_availability": STAGE_AVAILABILITY_SCHEMA_ID,
            "circuit_manifestation": CIRCUIT_MANIFESTATION_SCHEMA_ID,
            "result_manifestation": RESULT_MANIFESTATION_SCHEMA_ID,
            "decision_evidence_lineage": LINEAGE_SCHEMA_ID,
            "current_build_context": CURRENT_BUILD_CONTEXT_SCHEMA_ID,
            "portable_current_build_context": (PORTABLE_CURRENT_BUILD_CONTEXT_SCHEMA_ID),
            "carry_forward_proposal": CARRY_FORWARD_SCHEMA_ID,
            "evolved_blueprint": EVOLVED_BLUEPRINT_SCHEMA_ID,
            "resource_architecture": RESOURCE_ARCHITECTURE_SCHEMA_ID,
        },
        "provenance_roles": list(PROVENANCE_ROLES),
        "generation_postures": list(GENERATION_POSTURES),
        "stage_availability_values": list(STAGE_AVAILABILITY_VALUES),
        "stage_identity_statuses": list(STAGE_IDENTITY_STATUSES),
        "development_stages": list(DEVELOPMENT_STAGES),
        "canonical_relationship_values": list(RELATIONSHIP_TYPES),
        "profiles": list(PROFILE_IDS),
        "actions": list(ACTION_IDS),
        "resolution_context": RESOLUTION_CONTEXT,
        "resource_architecture": {
            "logical_resource_architectures": list(LOGICAL_RESOURCE_ARCHITECTURES),
            "construction_policy_patterns": list(CONSTRUCTION_POLICY_PATTERNS),
            "qiskit_construction_forms": list(QISKIT_CONSTRUCTION_FORMS),
            "qiskit_compatibility_aliases": deepcopy(QISKIT_CONSTRUCTION_ALIASES),
            "scope": RESOURCE_ARCHITECTURE_SCOPE,
            "additional_sdks_implemented": [],
        },
        "circuit_disclosure_ceiling": deepcopy(CIRCUIT_DISCLOSURE_CEILING),
        "result_disclosure_ceiling": deepcopy(RESULT_DISCLOSURE_CEILING),
        "current_build_evidence_parent_order": list(CURRENT_BUILD_EVIDENCE_PARENT_ORDER),
        "portable_current_build_context": {
            "inventory_status": PORTABLE_BUNDLE_INVENTORY_STATUS,
            "inventory_statuses": list(PORTABLE_BUNDLE_INVENTORY_STATUSES),
            "limits": deepcopy(PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS),
            "field_inventory": portable_current_build_context_field_inventory(),
            "transport_envelope": True,
            "deterministic_proposal_resupply": True,
            "deterministic_confirmation_transport": True,
            "local_selected_path_transmitted": False,
            "request_digest_meaning": "deterministic_consistency_reference_only",
            "canonical_stored_form": False,
            "authentication_meaning": "none",
            "protected_policy_dependency": "none",
        },
        "current_loop_continuity": current_loop_contract_snapshot(),
        "current_loop_orchestration": coordinator_contract_snapshot(),
        "raw_artifacts_hosted": False,
        "hidden_state": False,
        "persistence": False,
        "transitive_lineage": False,
        "non_proofs": list(_NON_PROOFS),
    }
