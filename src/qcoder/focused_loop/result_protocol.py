"""Exact stabilizer-predicate result protocol, Clopper-Pearson bound, and decision records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

from qcoder.focused_loop import identities
from qcoder.focused_loop.canonical import (
    FocusedLoopError,
    bounded_text,
    enum_value,
    strict_float,
    strict_int,
)
from qcoder.focused_loop.contracts import (
    SUPPORTED_ACTIONS,
    SUPPORTED_CONFIDENCE_LEVELS,
    confidence_alpha,
    seal_record,
)
from qcoder.focused_loop.fixtures import COUNTS_BITSTRING_ORDERING

RESULT_PROTOCOL_VERSION = "1"
ESTIMATOR_ID = "clopper_pearson_one_sided_exact_lower_bound_v1"
INTERVAL_KIND = "one_sided_exact_clopper_pearson_lower_bound"
INTERVAL_SEMANTICS = (
    "one_sided_lower_confidence_bound_on_the_probability_that_a_single_shot_"
    "satisfies_every_declared_exact_parity_constraint"
)
QUANTITY = "stabilizer_predicate_satisfaction_probability"

EVIDENCE_CONCLUSIONS = ("target_met", "target_not_met", "inconclusive", "unsupported")

#: Sampling state is a separate axis from the conclusion and from the action.
SAMPLING_STATES = (
    "sampling_sufficient_stop_sampling",
    "collect_more_shots",
    "sampling_state_undetermined",
)

EVIDENCE_STATES = ("valid_current", "invalid", "stale", "ambiguous_ordering", "unbound")
EXECUTION_STATES = ("completed_success", "completed_failure", "not_run", "aborted")

#: Bounded statements of what this protocol never claims.
NON_CLAIMS = (
    "not_a_general_fidelity_estimator",
    "not_a_global_state_equality_proof",
    "not_general_simulator_validation",
    "not_noise_characterization",
    "not_process_fidelity",
    "not_qpu_reliability",
    "not_state_fidelity",
    "not_universal_clifford_correctness",
)

MAX_REPORTED_VIOLATED_CONSTRAINTS = 16

#: ``(evidence_conclusion, sampling_state) -> (action, rationale)``. The only source of
#: next actions. ``collect_more_shots`` is a sampling state and never an action, and no
#: predicate violation can ever map to further sampling or to a method change.
ACTION_TABLE: Mapping[tuple[str, str], tuple[str, str]] = {
    ("target_met", "sampling_sufficient_stop_sampling"): (
        "stop_goal_met",
        "exact_target_lower_bound_attained_at_declared_fixed_shots",
    ),
    ("target_not_met", "sampling_sufficient_stop_sampling"): (
        "unsupported",
        "exact_predicate_violation_requires_investigation",
    ),
    ("inconclusive", "collect_more_shots"): (
        "await_user_decision",
        "clean_evidence_below_declared_fixed_shots_requires_user_authorization",
    ),
    ("inconclusive", "sampling_sufficient_stop_sampling"): (
        "await_user_decision",
        "sampling_finished_without_attaining_declared_target",
    ),
    ("unsupported", "sampling_state_undetermined"): (
        "diagnostic_required",
        "evidence_not_valid_current_and_bound",
    ),
}

def combination_valid(
    *, evidence_conclusion: str, sampling_state: str, action: str
) -> bool:
    """Return whether the ``(conclusion, sampling_state, action)`` triple is permitted."""
    entry = ACTION_TABLE.get((evidence_conclusion, sampling_state))
    return entry is not None and entry[0] == action


_BETA_TINY = 1e-300
_BETA_EPSILON = 3e-16
_BETA_MAX_ITERATIONS = 400
_BISECTION_ITERATIONS = 200


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    """Lentz continued fraction for the regularized incomplete beta function."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _BETA_TINY:
        d = _BETA_TINY
    d = 1.0 / d
    result = d
    for step in range(1, _BETA_MAX_ITERATIONS):
        even = 2 * step
        numerator = step * (b - step) * x / ((qam + even) * (a + even))
        d = 1.0 + numerator * d
        if abs(d) < _BETA_TINY:
            d = _BETA_TINY
        c = 1.0 + numerator / c
        if abs(c) < _BETA_TINY:
            c = _BETA_TINY
        d = 1.0 / d
        result *= d * c
        numerator = -(a + step) * (qab + step) * x / ((a + even) * (qap + even))
        d = 1.0 + numerator * d
        if abs(d) < _BETA_TINY:
            d = _BETA_TINY
        c = 1.0 + numerator / c
        if abs(c) < _BETA_TINY:
            c = _BETA_TINY
        d = 1.0 / d
        delta = d * c
        result *= delta
        if abs(delta - 1.0) < _BETA_EPSILON:
            return result
    raise FocusedLoopError("clopper_pearson_beta_did_not_converge")


def regularized_incomplete_beta(*, a: float, b: float, x: float) -> float:
    """Return ``I_x(a, b)``, the regularized incomplete beta function."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    if x < (a + 1.0) / (a + b + 2.0):
        front = math.exp(log_front + a * math.log(x) + b * math.log1p(-x))
        return front * _beta_continued_fraction(a, b, x) / a
    back = math.exp(log_front + b * math.log1p(-x) + a * math.log(x))
    return 1.0 - back * _beta_continued_fraction(b, a, 1.0 - x) / b


def _beta_quantile(*, alpha: float, a: float, b: float) -> float:
    low = 0.0
    high = 1.0
    for _ in range(_BISECTION_ITERATIONS):
        middle = 0.5 * (low + high)
        if regularized_incomplete_beta(a=a, b=b, x=middle) < alpha:
            low = middle
        else:
            high = middle
    return 0.5 * (low + high)


def clopper_pearson_lower_bound(
    *,
    successes: int,
    trials: int,
    confidence_level: float = identities.CONFIDENCE_LEVEL,
) -> float:
    """Return the one-sided exact Clopper-Pearson lower confidence bound.

    ``trials`` must be at least one and ``successes`` must lie in ``[0, trials]``. The
    all-success bound is the closed form ``alpha ** (1 / n)``; otherwise the bound is the
    Beta quantile ``BetaInv(alpha; k, n - k + 1)``. ``k == 0`` yields ``0.0``.
    """
    level = strict_float(confidence_level, category="result_protocol_confidence_level_unsupported")
    if level not in SUPPORTED_CONFIDENCE_LEVELS:
        raise FocusedLoopError("result_protocol_confidence_level_unsupported")
    alpha = confidence_alpha(level)
    sample_size = strict_int(trials, category="result_protocol_sample_size_invalid", minimum=1)
    count = strict_int(successes, category="result_protocol_success_count_invalid", minimum=0)
    if count > sample_size:
        raise FocusedLoopError("result_protocol_success_count_exceeds_sample")
    if count == 0:
        return 0.0
    if count == sample_size:
        return alpha ** (1.0 / sample_size)
    return _beta_quantile(alpha=alpha, a=float(count), b=float(sample_size - count + 1))


def _answer_key_fields(answer_key: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], int, int]:
    if not isinstance(answer_key, Mapping) or answer_key.get("schema_id") != (
        identities.ANSWER_KEY_SCHEMA_ID
    ):
        raise FocusedLoopError("result_protocol_answer_key_invalid")
    constraints = answer_key.get("parity_constraints")
    support = answer_key.get("valid_support")
    width = answer_key.get("classical_register_width")
    if (
        not isinstance(constraints, Sequence)
        or not constraints
        or not isinstance(support, Mapping)
        or not isinstance(width, int)
        or isinstance(width, bool)
    ):
        raise FocusedLoopError("result_protocol_answer_key_invalid")
    size = support.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise FocusedLoopError("result_protocol_answer_key_invalid")
    return list(constraints), int(width), int(size)


def _bit_at(outcome: str, *, bit_index: int, width: int) -> str:
    """Read ``c[bit_index]`` from a counts key under the recorded counts ordering."""
    return outcome[width - 1 - bit_index]


def evaluate_predicate_satisfaction(
    *,
    counts: Mapping[str, int],
    answer_key: Mapping[str, Any],
    bitstring_ordering: str,
) -> dict[str, Any]:
    """Evaluate the exact parity constraints over every accepted shot.

    Returns the pure evaluation: accepted shots, satisfying shots, point estimate,
    observed distinct outcomes, and the bounded violated-constraint set.
    """
    if bitstring_ordering != COUNTS_BITSTRING_ORDERING:
        raise FocusedLoopError("result_protocol_bitstring_ordering_unsupported")
    constraints, width, support_size = _answer_key_fields(answer_key)
    if not isinstance(counts, Mapping) or not counts:
        raise FocusedLoopError("result_protocol_counts_invalid")

    accepted = 0
    satisfying = 0
    violated: set[str] = set()
    outcomes: set[str] = set()
    for outcome, count in counts.items():
        if not isinstance(outcome, str) or len(outcome) != width or set(outcome) - {"0", "1"}:
            raise FocusedLoopError("result_protocol_outcome_invalid")
        shots = strict_int(count, category="result_protocol_count_invalid", minimum=0)
        if shots == 0:
            continue
        accepted += shots
        outcomes.add(outcome)
        failed = [
            str(constraint["constraint_id"])
            for constraint in constraints
            if _bit_at(outcome, bit_index=int(constraint["left_bit"]), width=width)
            != _bit_at(outcome, bit_index=int(constraint["right_bit"]), width=width)
        ]
        if failed:
            violated.update(failed)
        else:
            satisfying += shots
    if accepted == 0:
        raise FocusedLoopError("result_protocol_sample_size_invalid")
    return {
        "shots_evaluated": accepted,
        "satisfying_shots": satisfying,
        "point_estimate": satisfying / accepted,
        "distinct_outcomes_observed": len(outcomes),
        "allowed_support_size": support_size,
        "violations": {
            "count": accepted - satisfying,
            "constraint_ids": sorted(violated)[:MAX_REPORTED_VIOLATED_CONSTRAINTS],
            "distinct_constraint_count": len(violated),
        },
    }


def _decide(
    *,
    evidence_state: str,
    execution_state: str,
    shots_evaluated: int,
    satisfying_shots: int,
    lower_bound: float | None,
    target_lower_bound: float,
    required_shots: int,
) -> tuple[str, str, str | None]:
    """Return ``(evidence_conclusion, sampling_state, unsupported_reason)``."""
    if evidence_state != "valid_current":
        return "unsupported", "sampling_state_undetermined", f"evidence_{evidence_state}"
    if execution_state != "completed_success":
        return "unsupported", "sampling_state_undetermined", f"execution_{execution_state}"
    if satisfying_shots != shots_evaluated:
        # An observed exact contradiction. More shots can never erase it.
        return "target_not_met", "sampling_sufficient_stop_sampling", None
    if shots_evaluated > required_shots:
        return (
            "unsupported",
            "sampling_state_undetermined",
            "shot_count_exceeds_declared_fixed_shots",
        )
    if shots_evaluated < required_shots:
        return "inconclusive", "collect_more_shots", None
    if lower_bound is not None and lower_bound >= target_lower_bound:
        return "target_met", "sampling_sufficient_stop_sampling", None
    return "inconclusive", "sampling_sufficient_stop_sampling", None


def build_analysis_result(
    *,
    analysis_id: str,
    counts: Mapping[str, int],
    answer_key: Mapping[str, Any],
    bitstring_ordering: str = COUNTS_BITSTRING_ORDERING,
    evidence_state: str = "valid_current",
    execution_state: str = "completed_success",
    target_lower_bound: float = identities.TARGET_LOWER_BOUND,
    confidence_level: float = identities.CONFIDENCE_LEVEL,
    required_shots: int = identities.FIXED_SHOTS,
) -> dict[str, Any]:
    """Build the ``analysis_result.v1`` record for one evaluated result."""
    state = enum_value(
        evidence_state, allowed=EVIDENCE_STATES, category="result_protocol_evidence_state_invalid"
    )
    execution = enum_value(
        execution_state,
        allowed=EXECUTION_STATES,
        category="result_protocol_execution_state_invalid",
    )
    target = strict_float(
        target_lower_bound,
        category="result_protocol_target_invalid",
        minimum=0.0,
        maximum=1.0,
    )
    shots = strict_int(required_shots, category="result_protocol_required_shots_invalid", minimum=1)
    evaluation = evaluate_predicate_satisfaction(
        counts=counts, answer_key=answer_key, bitstring_ordering=bitstring_ordering
    )
    usable = state == "valid_current" and execution == "completed_success"
    lower_bound = (
        clopper_pearson_lower_bound(
            successes=evaluation["satisfying_shots"],
            trials=evaluation["shots_evaluated"],
            confidence_level=confidence_level,
        )
        if usable
        else None
    )
    conclusion, sampling_state, unsupported_reason = _decide(
        evidence_state=state,
        execution_state=execution,
        shots_evaluated=evaluation["shots_evaluated"],
        satisfying_shots=evaluation["satisfying_shots"],
        lower_bound=lower_bound,
        target_lower_bound=target,
        required_shots=shots,
    )
    interval = (
        None
        if lower_bound is None
        else {
            "kind": INTERVAL_KIND,
            "level": float(confidence_level),
            "lower": lower_bound,
        }
    )
    payload: dict[str, Any] = {
        "schema_id": identities.ANALYSIS_RESULT_SCHEMA_ID,
        "regime_id": identities.REGIME_ID,
        "analysis_id": bounded_text(analysis_id, category="result_protocol_analysis_id_invalid"),
        "result_protocol_id": identities.RESULT_PROTOCOL_SCHEMA_ID,
        "result_protocol_version": RESULT_PROTOCOL_VERSION,
        "quantity": QUANTITY,
        "reference_digest": answer_key["record_digest"],
        "reference_fixture_id": answer_key["fixture_id"],
        "estimator_id": ESTIMATOR_ID,
        "counts_bitstring_ordering": bitstring_ordering,
        "declared_fixed_shots": shots,
        "target_lower_bound": target,
        "shots_evaluated": evaluation["shots_evaluated"],
        "satisfying_shots": evaluation["satisfying_shots"],
        "point_estimate": evaluation["point_estimate"],
        "interval": interval,
        "interval_semantics": INTERVAL_SEMANTICS,
        "violations": evaluation["violations"],
        "distinct_outcomes_observed": evaluation["distinct_outcomes_observed"],
        "allowed_support_size": evaluation["allowed_support_size"],
        "evidence_state": state,
        "execution_state": execution,
        "evidence_conclusion": conclusion,
        "sampling_state": sampling_state,
        "unsupported_reason": unsupported_reason,
        "non_claims": list(NON_CLAIMS),
    }
    return seal_record(payload)


def build_next_action(
    *,
    action_id: str,
    analysis_result: Mapping[str, Any],
    user_selected_action: str | None = None,
) -> dict[str, Any]:
    """Build the separate ``next_action.v1`` record from an analysis result.

    The conclusion is never rewritten by a user selection: any user choice is preserved
    in its own field alongside the derived action. No batch size is ever emitted.
    """
    if not isinstance(analysis_result, Mapping) or analysis_result.get("schema_id") != (
        identities.ANALYSIS_RESULT_SCHEMA_ID
    ):
        raise FocusedLoopError("next_action_analysis_result_invalid")
    conclusion = enum_value(
        analysis_result.get("evidence_conclusion"),
        allowed=EVIDENCE_CONCLUSIONS,
        category="next_action_conclusion_invalid",
    )
    sampling_state = enum_value(
        analysis_result.get("sampling_state"),
        allowed=SAMPLING_STATES,
        category="next_action_sampling_state_invalid",
    )
    entry = ACTION_TABLE.get((conclusion, sampling_state))
    if entry is None:
        raise FocusedLoopError("next_action_combination_unsupported")
    action, rationale = entry
    if action not in SUPPORTED_ACTIONS:
        raise FocusedLoopError("next_action_action_unsupported")
    selected = (
        None
        if user_selected_action is None
        else enum_value(
            user_selected_action,
            allowed=SUPPORTED_ACTIONS,
            category="next_action_user_selection_unsupported",
        )
    )
    payload: dict[str, Any] = {
        "schema_id": identities.NEXT_ACTION_SCHEMA_ID,
        "regime_id": identities.REGIME_ID,
        "action_id": bounded_text(action_id, category="next_action_id_invalid"),
        "analysis_result_digest": analysis_result["record_digest"],
        "evidence_conclusion": conclusion,
        "sampling_state": sampling_state,
        "action": action,
        "combination_valid": combination_valid(
            evidence_conclusion=conclusion, sampling_state=sampling_state, action=action
        ),
        "rationale": rationale,
        "user_selected_action": selected,
        "user_selection_rewrites_conclusion": False,
        "automatic_execution": False,
    }
    return seal_record(payload)
