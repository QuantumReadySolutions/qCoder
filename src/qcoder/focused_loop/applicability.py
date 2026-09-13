"""Five-gate method applicability for ``local_aer_stabilizer_clifford_memory_binding_v1``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from qcoder.focused_loop import identities
from qcoder.focused_loop.canonical import (
    FocusedLoopError,
    bounded_text,
    enum_value,
    strict_bool,
    strict_int,
)
from qcoder.focused_loop.contracts import METHODS, seal_record
from qcoder.focused_loop.mps_floor import compare_floor_to_envelope

#: The five independent gates. Availability alone can never select a method.
GATE_NAMES = (
    "available",
    "qualified",
    "family_applicable",
    "satisfies_exactness",
    "result_capable",
)

#: Feasibility values this regime can express. ``feasible`` is deliberately absent:
#: a payload-only lower bound below an envelope never proves feasibility, because
#: allocator, framework and workspace overhead are unmodeled.
FEASIBILITY_VALUES = (
    "infeasible_lower_bound_exceeds_envelope",
    "not_established",
    "unsupported",
    "diagnostic_required",
)
FEASIBILITY_INFEASIBLE = "infeasible_lower_bound_exceeds_envelope"
FEASIBILITY_NOT_ESTABLISHED = "not_established"
FEASIBILITY_UNSUPPORTED = "unsupported"

#: Never a valid feasibility value anywhere in this package.
FORBIDDEN_FEASIBILITY_VALUE = "feasible"

REJECTION_REASONS = (
    "exactness_policy_conflict",
    "family_not_applicable",
    "method_not_available",
    "method_not_qualified",
    "resource_lower_bound_exceeded",
    "result_protocol_not_supported",
)

#: Methods whose selection depends on the memory lower bound comparison.
_MEMORY_BOUND_METHODS = (identities.METHOD_MPS_EXACT, identities.METHOD_MPS_APPROXIMATE)


def _satisfies_exactness(*, method: str, exactness_policy: str) -> bool:
    if exactness_policy != identities.EXACTNESS_POLICY_EXACT_REQUIRED:
        raise FocusedLoopError("applicability_exactness_policy_unsupported")
    return method != identities.METHOD_MPS_APPROXIMATE


def evaluate_method_applicability(
    *,
    applicability_id: str,
    method: str,
    exactness_policy: str = identities.EXACTNESS_POLICY_EXACT_REQUIRED,
    available: bool = True,
    qualified: bool = True,
    family_applicable: bool = True,
    result_capable: bool = True,
    coefficient_floor: Mapping[str, Any] | None = None,
    safe_envelope_bytes: int | None = None,
) -> dict[str, Any]:
    """Evaluate the five independent gates for one method and build the record."""
    chosen = enum_value(method, allowed=METHODS, category="applicability_method_unsupported")
    gates = {
        "available": strict_bool(available, category="applicability_gate_invalid"),
        "qualified": strict_bool(qualified, category="applicability_gate_invalid"),
        "family_applicable": strict_bool(family_applicable, category="applicability_gate_invalid"),
        "satisfies_exactness": _satisfies_exactness(
            method=chosen, exactness_policy=exactness_policy
        ),
        "result_capable": strict_bool(result_capable, category="applicability_gate_invalid"),
    }
    if set(gates) != set(GATE_NAMES):
        raise FocusedLoopError("applicability_gate_set_invalid")

    comparison: dict[str, Any] | None = None
    feasibility = FEASIBILITY_NOT_ESTABLISHED
    if chosen in _MEMORY_BOUND_METHODS:
        if coefficient_floor is None or safe_envelope_bytes is None:
            raise FocusedLoopError("applicability_resource_evidence_missing")
        comparison = compare_floor_to_envelope(
            floor=coefficient_floor,
            safe_envelope_bytes=strict_int(
                safe_envelope_bytes, category="resource_safe_envelope_invalid", minimum=1
            ),
        )
        feasibility = (
            FEASIBILITY_INFEASIBLE
            if comparison["floor_exceeds_envelope"]
            else FEASIBILITY_NOT_ESTABLISHED
        )

    rejection_reason = _rejection_reason(method=chosen, gates=gates, comparison=comparison)
    if not gates["family_applicable"] and chosen == identities.METHOD_STABILIZER:
        feasibility = FEASIBILITY_UNSUPPORTED
    if feasibility not in FEASIBILITY_VALUES or feasibility == FORBIDDEN_FEASIBILITY_VALUE:
        raise FocusedLoopError("applicability_feasibility_value_invalid")

    payload: dict[str, Any] = {
        "schema_id": identities.METHOD_APPLICABILITY_SCHEMA_ID,
        "regime_id": identities.REGIME_ID,
        "applicability_id": bounded_text(
            applicability_id, category="applicability_id_invalid"
        ),
        "method": chosen,
        "exactness_policy": exactness_policy,
        "gates": gates,
        "gate_names": list(GATE_NAMES),
        "gates_all_passed": all(gates.values()),
        "feasibility": feasibility,
        "resource_comparison": comparison,
        "selected": all(gates.values()) and rejection_reason is None,
        "rejection_reason": rejection_reason,
        "limitations": [identities.AER_MPS_LIMITATION],
    }
    return seal_record(payload)


def _rejection_reason(
    *,
    method: str,
    gates: Mapping[str, bool],
    comparison: Mapping[str, Any] | None,
) -> str | None:
    """Return the single, highest-precedence rejection reason, or ``None``."""
    if not gates["family_applicable"]:
        return "family_not_applicable"
    if not gates["satisfies_exactness"]:
        return "exactness_policy_conflict"
    if not gates["available"]:
        return "method_not_available"
    if not gates["qualified"]:
        return "method_not_qualified"
    if not gates["result_capable"]:
        return "result_protocol_not_supported"
    if (
        method in _MEMORY_BOUND_METHODS
        and comparison is not None
        and comparison["floor_exceeds_envelope"]
    ):
        return "resource_lower_bound_exceeded"
    return None


def evaluate_regime_methods(
    *,
    applicability_prefix: str,
    coefficient_floor: Mapping[str, Any],
    safe_envelope_bytes: int,
    family_applicable: bool = True,
    methods: Sequence[str] = METHODS,
    exactness_policy: str = identities.EXACTNESS_POLICY_EXACT_REQUIRED,
) -> dict[str, dict[str, Any]]:
    """Evaluate every regime method against one resource envelope, keyed by method."""
    return {
        method: evaluate_method_applicability(
            applicability_id=f"{applicability_prefix}:{method}",
            method=method,
            exactness_policy=exactness_policy,
            family_applicable=family_applicable,
            coefficient_floor=coefficient_floor,
            safe_envelope_bytes=safe_envelope_bytes,
        )
        for method in methods
    }


def selected_method(evaluations: Mapping[str, Mapping[str, Any]]) -> str | None:
    """Return the single selected method, or ``None`` when nothing is selectable."""
    selected = sorted(
        method for method, record in evaluations.items() if record.get("selected") is True
    )
    if len(selected) > 1:
        raise FocusedLoopError("applicability_multiple_methods_selected")
    return selected[0] if selected else None
