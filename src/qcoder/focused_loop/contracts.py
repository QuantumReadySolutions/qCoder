"""Frozen objective, execution-profile, resource and candidate records for the focused loop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from qcoder.focused_loop import identities
from qcoder.focused_loop.canonical import (
    FocusedLoopError,
    bounded_text,
    bounded_text_list,
    digest_excluding,
    enum_value,
    strict_bool,
    strict_float,
    strict_int,
    strict_mapping,
    strict_typed_object,
)

#: Single self-digest field name used by every record builder in this package.
RECORD_DIGEST_FIELD = "record_digest"

GIB = 1024**3

EVIDENCE_CLASS_EXACT_FAMILY_SPECIFIC = "exact_family_specific"
EVIDENCE_CLASSES = (EVIDENCE_CLASS_EXACT_FAMILY_SPECIFIC,)

ORDERING_ASSUMPTION_NATURAL_ORDER = "natural_order"
ORDERING_ASSUMPTIONS = (ORDERING_ASSUMPTION_NATURAL_ORDER,)

#: Only this confidence level is frozen for the regime; anything else fails closed.
SUPPORTED_CONFIDENCE_LEVELS = (identities.CONFIDENCE_LEVEL,)

#: Exact alpha per supported confidence level. Never computed as ``1 - level``:
#: float subtraction yields 0.050000000000000044 and would move the exact answer keys.
CONFIDENCE_ALPHA = {identities.CONFIDENCE_LEVEL: 0.05}

METHODS = (
    identities.METHOD_MPS_EXACT,
    identities.METHOD_MPS_APPROXIMATE,
    identities.METHOD_STABILIZER,
)

EXECUTION_LOCALITIES = ("local_process",)
SIMULATOR_FAMILIES = ("qiskit_aer",)
NOISE_MODELS = ("noiseless",)
CIRCUIT_FAMILY_CLASSES = ("clifford_only", "contains_non_clifford")

OBJECTIVE_QUANTITY = "stabilizer_predicate_satisfaction_probability"
OBJECTIVE_NON_GOALS = (
    "no_adaptive_shot_policy",
    "no_general_fidelity_estimate",
    "no_general_simulator_ranking",
    "no_process_fidelity_estimate",
    "no_remote_or_qpu_execution",
    "no_runtime_reconciliation",
    "no_state_fidelity_estimate",
)

LIMIT_SCOPES = ("host", "process", "container")

#: Observation-method identity -> whether the recorded numbers are synthetic test evidence.
RESOURCE_OBSERVATION_METHODS = {
    "synthetic_test_declaration_v1": True,
    "declared_operator_input_v1": False,
}
SYNTHETIC_RESOURCE_OBSERVATION_METHOD = "synthetic_test_declaration_v1"

#: Synthetic resource answer key frozen by the product specification.
SYNTHETIC_TOTAL_MEMORY_BYTES = 68_719_476_736
SYNTHETIC_AVAILABLE_FLOOR_BYTES = 42_949_672_960
SYNTHETIC_RESERVE_BYTES = 4_294_967_296
SYNTHETIC_SAFE_ENVELOPE_BYTES = 38_654_705_664
SYNTHETIC_LIMIT_SCOPE = "host"

PROVIDER_CLASSES = (
    "deterministic_local",
    "human",
    "ide_llm",
    "local_no_egress_model",
    "public_api_model",
    "qcoder_protected_service",
)

#: The only actions this loop can express. ``collect_more_shots`` is deliberately
#: absent: sampling state is a separate axis and is never an action.
SUPPORTED_ACTIONS = (
    "await_user_decision",
    "diagnostic_required",
    "stop_goal_met",
    "unsupported",
)

CANDIDATE_REQUIRED_FIELDS = ("candidate_id", "proposed_action", "rationale")
CANDIDATE_AUTHORITY_CLASS = "proposal_only"


def seal_record(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach the canonical self-digest to ``payload`` and return it."""
    payload[RECORD_DIGEST_FIELD] = digest_excluding(payload, field=RECORD_DIGEST_FIELD)
    return payload


def memory_band(byte_count: int) -> str:
    """Return the coarse, non-identifying memory band for ``byte_count``."""
    size = strict_int(byte_count, category="resource_byte_count_invalid", minimum=0)
    if size < 8 * GIB:
        return "lt_8gib"
    if size < 32 * GIB:
        return "ge_8gib_lt_32gib"
    if size < 128 * GIB:
        return "ge_32gib_lt_128gib"
    return "ge_128gib"


def confidence_alpha(confidence_level: float) -> float:
    """Return the exact one-sided alpha for a supported confidence level."""
    level = strict_float(confidence_level, category="confidence_level_unsupported")
    if level not in CONFIDENCE_ALPHA:
        raise FocusedLoopError("confidence_level_unsupported")
    return CONFIDENCE_ALPHA[level]


def build_evidence_objective(
    *,
    objective_id: str,
    quantity: str = OBJECTIVE_QUANTITY,
    exactness_policy: str = identities.EXACTNESS_POLICY_EXACT_REQUIRED,
    target_lower_bound: float = identities.TARGET_LOWER_BOUND,
    confidence_level: float = identities.CONFIDENCE_LEVEL,
    shots: int = identities.FIXED_SHOTS,
    non_goals: Sequence[str] = OBJECTIVE_NON_GOALS,
) -> dict[str, Any]:
    """Build the ``evidence_objective.v1`` record for this regime."""
    if exactness_policy != identities.EXACTNESS_POLICY_EXACT_REQUIRED:
        raise FocusedLoopError("objective_exactness_policy_unsupported")
    confidence_alpha(confidence_level)
    payload: dict[str, Any] = {
        "schema_id": identities.OBJECTIVE_SCHEMA_ID,
        "regime_id": identities.REGIME_ID,
        "objective_id": bounded_text(objective_id, category="objective_id_invalid"),
        "quantity": bounded_text(quantity, category="objective_quantity_invalid"),
        "exactness_policy": exactness_policy,
        "evidence_class": EVIDENCE_CLASS_EXACT_FAMILY_SPECIFIC,
        "result_protocol_id": identities.RESULT_PROTOCOL_SCHEMA_ID,
        "target_lower_bound": strict_float(
            target_lower_bound,
            category="objective_target_lower_bound_invalid",
            minimum=0.0,
            maximum=1.0,
        ),
        "confidence_level": float(confidence_level),
        "shots": strict_int(shots, category="objective_shots_invalid", minimum=1),
        "non_goals": bounded_text_list(list(non_goals), category="objective_non_goals_invalid"),
    }
    return seal_record(payload)


def build_execution_profile(
    *,
    profile_id: str,
    method: str,
    circuit_family_class: str,
    simulator_family: str = SIMULATOR_FAMILIES[0],
    execution_locality: str = EXECUTION_LOCALITIES[0],
    noise_model: str = NOISE_MODELS[0],
    ordering_assumption: str = ORDERING_ASSUMPTION_NATURAL_ORDER,
    simulator_available: bool = True,
    method_qualified: bool = True,
    result_protocol_capable: bool = True,
    mid_circuit_measurement: bool = False,
    reset_used: bool = False,
    dynamic_operations: bool = False,
) -> dict[str, Any]:
    """Build the ``execution_profile.v1`` record describing one candidate method."""
    payload: dict[str, Any] = {
        "schema_id": identities.EXECUTION_PROFILE_SCHEMA_ID,
        "regime_id": identities.REGIME_ID,
        "profile_id": bounded_text(profile_id, category="execution_profile_id_invalid"),
        "method": enum_value(method, allowed=METHODS, category="execution_profile_method_invalid"),
        "circuit_family_class": enum_value(
            circuit_family_class,
            allowed=CIRCUIT_FAMILY_CLASSES,
            category="execution_profile_family_class_invalid",
        ),
        "simulator_family": enum_value(
            simulator_family,
            allowed=SIMULATOR_FAMILIES,
            category="execution_profile_simulator_family_invalid",
        ),
        "execution_locality": enum_value(
            execution_locality,
            allowed=EXECUTION_LOCALITIES,
            category="execution_profile_locality_invalid",
        ),
        "noise_model": enum_value(
            noise_model,
            allowed=NOISE_MODELS,
            category="execution_profile_noise_model_invalid",
        ),
        "ordering_assumption": enum_value(
            ordering_assumption,
            allowed=ORDERING_ASSUMPTIONS,
            category="execution_profile_ordering_assumption_invalid",
        ),
        "simulator_available": strict_bool(
            simulator_available, category="execution_profile_availability_invalid"
        ),
        "method_qualified": strict_bool(
            method_qualified, category="execution_profile_qualification_invalid"
        ),
        "result_protocol_capable": strict_bool(
            result_protocol_capable, category="execution_profile_result_capability_invalid"
        ),
        "mid_circuit_measurement": strict_bool(
            mid_circuit_measurement, category="execution_profile_mid_circuit_invalid"
        ),
        "reset_used": strict_bool(reset_used, category="execution_profile_reset_invalid"),
        "dynamic_operations": strict_bool(
            dynamic_operations, category="execution_profile_dynamic_invalid"
        ),
    }
    return seal_record(payload)


def build_resource_receipt(
    *,
    receipt_id: str,
    total_memory_bytes: int,
    available_floor_bytes: int,
    reserve_bytes: int,
    limit_scope: str = SYNTHETIC_LIMIT_SCOPE,
    observation_method: str = SYNTHETIC_RESOURCE_OBSERVATION_METHOD,
) -> dict[str, Any]:
    """Build the ``resource_receipt.v1`` record and derive ``safe_envelope_bytes``."""
    method = enum_value(
        observation_method,
        allowed=tuple(RESOURCE_OBSERVATION_METHODS),
        category="resource_observation_method_unsupported",
    )
    total = strict_int(total_memory_bytes, category="resource_total_invalid", minimum=1)
    available = strict_int(available_floor_bytes, category="resource_available_invalid", minimum=1)
    reserve = strict_int(reserve_bytes, category="resource_reserve_invalid", minimum=0)
    if available > total:
        raise FocusedLoopError("resource_available_exceeds_total")
    if reserve >= available:
        raise FocusedLoopError("resource_reserve_exceeds_available")
    safe_envelope = available - reserve
    payload: dict[str, Any] = {
        "schema_id": identities.RESOURCE_RECEIPT_SCHEMA_ID,
        "regime_id": identities.REGIME_ID,
        "receipt_id": bounded_text(receipt_id, category="resource_receipt_id_invalid"),
        "limit_scope": enum_value(
            limit_scope, allowed=LIMIT_SCOPES, category="resource_limit_scope_invalid"
        ),
        "observation_method": method,
        "observation_is_synthetic": RESOURCE_OBSERVATION_METHODS[method],
        "real_machine_probe_performed": False,
        "total_memory_bytes": total,
        "available_floor_bytes": available,
        "reserve_bytes": reserve,
        "safe_envelope_bytes": safe_envelope,
        "safe_envelope_band": memory_band(safe_envelope),
    }
    return seal_record(payload)


def build_synthetic_resource_receipt(
    *, receipt_id: str = "synthetic_host_64gib_v1"
) -> dict[str, Any]:
    """Build the frozen synthetic resource receipt used by the focused-loop fixtures."""
    receipt = build_resource_receipt(
        receipt_id=receipt_id,
        total_memory_bytes=SYNTHETIC_TOTAL_MEMORY_BYTES,
        available_floor_bytes=SYNTHETIC_AVAILABLE_FLOOR_BYTES,
        reserve_bytes=SYNTHETIC_RESERVE_BYTES,
        limit_scope=SYNTHETIC_LIMIT_SCOPE,
        observation_method=SYNTHETIC_RESOURCE_OBSERVATION_METHOD,
    )
    if receipt["safe_envelope_bytes"] != SYNTHETIC_SAFE_ENVELOPE_BYTES:
        raise FocusedLoopError("resource_synthetic_answer_key_mismatch")
    return receipt


def ingest_candidate_recommendation(
    payload_text: str,
    *,
    provider_class: str,
) -> dict[str, Any]:
    """Ingest one typed candidate proposal. Proposal only: never evidence, never authority.

    The payload must be exactly one JSON object. Prose-wrapped JSON, duplicate keys,
    missing required fields, and non-object payloads are rejected with no side effect.
    No substring or heuristic extraction is ever attempted.
    """
    provider = enum_value(
        provider_class,
        allowed=PROVIDER_CLASSES,
        category="candidate_provider_class_unsupported",
    )
    parsed = strict_typed_object(payload_text, category="candidate_payload_invalid")
    fields = strict_mapping(
        parsed,
        required=CANDIDATE_REQUIRED_FIELDS,
        category="candidate_payload_invalid",
    )
    payload: dict[str, Any] = {
        "schema_id": identities.CANDIDATE_RECOMMENDATION_SCHEMA_ID,
        "regime_id": identities.REGIME_ID,
        "candidate_id": bounded_text(fields["candidate_id"], category="candidate_payload_invalid"),
        "provider_class": provider,
        "proposed_action": bounded_text(
            fields["proposed_action"], category="candidate_payload_invalid"
        ),
        "rationale": bounded_text(fields["rationale"], category="candidate_payload_invalid"),
        "authority_class": CANDIDATE_AUTHORITY_CLASS,
        "is_evidence": False,
        "confers_authority": False,
    }
    return seal_record(payload)


def validate_candidate_action(candidate: Mapping[str, Any]) -> str:
    """Return the proposed action of a well-formed candidate, or fail closed."""
    if (
        not isinstance(candidate, Mapping)
        or candidate.get("schema_id") != identities.CANDIDATE_RECOMMENDATION_SCHEMA_ID
    ):
        raise FocusedLoopError("candidate_record_invalid")
    if candidate.get("is_evidence") is not False or candidate.get("confers_authority") is not False:
        raise FocusedLoopError("candidate_record_invalid")
    return enum_value(
        candidate.get("proposed_action"),
        allowed=SUPPORTED_ACTIONS,
        category="candidate_action_unsupported",
    )
