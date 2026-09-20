"""Integrated Phase A proof for the first focused-loop vertical.

This composes the deterministic substrate (fixture, objective, chi claim, coefficient
floor, applicability, result protocol) with the executor concern set (inert plan,
separate authority, bounded executor, sibling receipt, strict-manifest join, reuse) and
asserts the acceptance predicates that only appear when the parts are wired together:
P11, P12, P13, P18, P19, P20, P21, P22, P23 and P24.

The executor runs through an explicitly injected fake backend in this file. That remains
intentional Phase A compatibility evidence even when Aer is installed for the conference
proof; real Aer execution is proven separately by the conference real-Aer test module.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import inspect
from typing import Any

import pytest

from qcoder.executors.aer_stabilizer_v1 import (
    AttemptLedger,
    BackendRequest,
    BackendSample,
    InvocationCounter,
    compute_circuit_digest,
    execute_focused_plan,
)
from qcoder.focused_loop import applicability as ap
from qcoder.focused_loop import fixtures as fx
from qcoder.focused_loop import identities as ids
from qcoder.focused_loop import mps_floor as mf
from qcoder.focused_loop import privacy, result_protocol as rp, reuse
from qcoder.focused_loop.attempt_join import (
    join_attempt_records,
    rebind_receipt_result_manifest_digest,
)
from qcoder.focused_loop.authority import build_execution_authority
from qcoder.focused_loop.canonical import FocusedLoopError
from qcoder.focused_loop.contracts import (
    build_execution_profile,
    build_synthetic_resource_receipt,
)
from qcoder.focused_loop.plan import build_execution_plan
from tests.focused_loop_manifest_v3_test_support import (
    build_strict_result_manifest_payload,
    circuit_artifact_revisions,
    join_receipt_to_strict_result_manifest,
    normalize_through_strict_manifest_v3,
)

CIRCUIT_PATH = "circuits/fx_clif_accept_01.qasm"
ATTEMPT = "execution-attempt-phase-a-integrated-1"
RUNTIME_VERSIONS = {"python": "3.14.3", "qiskit": "2.4.1", "qiskit_aer": "0.17.0"}
CLASSICAL_WIDTH = 12
PAIR_COUNT = 6

# The fixture's declared counts ordering places c[0] at the rightmost character.
BIT_ORDER = [f"c[{index}]" for index in range(CLASSICAL_WIDTH)]
REGISTER_ORDER = ["c"]


def _outcome(pair_bits: str) -> str:
    """Render a 12-bit outcome key from six per-pair bits, honouring c0-rightmost."""
    assert len(pair_bits) == PAIR_COUNT
    bits = [0] * CLASSICAL_WIDTH
    for index, value in enumerate(pair_bits):
        bits[2 * index] = int(value)
        bits[2 * index + 1] = int(value)
    return "".join(str(bits[CLASSICAL_WIDTH - 1 - position]) for position in range(CLASSICAL_WIDTH))


def _violating_outcome() -> str:
    """A key that breaks exactly the first Bell-pair equality constraint."""
    bits = [0] * CLASSICAL_WIDTH
    bits[1] = 1
    return "".join(str(bits[CLASSICAL_WIDTH - 1 - position]) for position in range(CLASSICAL_WIDTH))


VALID_COUNTS = {
    _outcome("000000"): 150,
    _outcome("101010"): 150,
    _outcome("111111"): 150,
    _outcome("010101"): 148,
}


def _fake_backend(counts: Mapping[str, int]):
    def factory(request: BackendRequest) -> BackendSample:
        assert request.method_id == ids.METHOD_STABILIZER
        assert request.shots == ids.FIXED_SHOTS
        assert request.noise == "none"
        return BackendSample(
            counts=dict(counts),
            backend_or_sampler="aer_simulator_stabilizer",
            interface="qiskit_aer.AerSimulator.run",
            runtime_versions=dict(RUNTIME_VERSIONS),
            peak_memory_bytes=None,
        )

    return factory


def _refusing_backend(request: BackendRequest) -> BackendSample:
    raise AssertionError("the backend must not be reached")


class Vertical:
    """The deterministic pre-execution chain for one nested-Bell family instance."""

    def __init__(self, parameters: fx.NestedBellFamilyParameters, root: Path) -> None:
        self.parameters = parameters
        self.material = fx.materialize_fixture(parameters)
        self.qasm = self.material["qasm"]
        self.pairs = fx.nested_pairs(parameters)

        self.resource_receipt = build_synthetic_resource_receipt()
        self.safe_envelope = self.resource_receipt["safe_envelope_bytes"]
        self.floor = mf.build_coefficient_floor(
            qubit_count=parameters.qubit_count, pairs=self.pairs
        )
        self.chi_claim = self.material["chi_required_claim"]
        self.evaluations = ap.evaluate_regime_methods(
            applicability_prefix=f"{parameters.fixture_id}-app",
            coefficient_floor=self.floor,
            safe_envelope_bytes=self.safe_envelope,
        )
        self.method = ap.selected_method(self.evaluations)
        self.profile = build_execution_profile(
            profile_id="local-aer-stabilizer-v1",
            method=ids.METHOD_STABILIZER,
            circuit_family_class="clifford_only",
        )

        path = root / CIRCUIT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.qasm, encoding="utf-8")
        self.root = root

        self.plan = build_execution_plan(
            objective_digest=self.material["objective_digest"],
            circuit_digest=self.material["qasm_digest"],
            circuit_path=CIRCUIT_PATH,
            profile_digest=self.profile["record_digest"],
            seed=7,
        )

    def authority(self, *, attempt: str = ATTEMPT, now: float = 1000.0) -> dict[str, Any]:
        return build_execution_authority(
            plan_digest=self.plan["plan_digest"],
            attempt_identity=attempt,
            expires_at=now + 600.0,
        )

    def execute(
        self,
        *,
        counts: Mapping[str, int] = VALID_COUNTS,
        authority: Mapping[str, Any] | None = None,
        ledger: AttemptLedger | None = None,
        counter: InvocationCounter | None = None,
        backend: Any = None,
        now: float = 1000.0,
    ):
        return execute_focused_plan(
            plan=self.plan,
            authority=self.authority(now=now) if authority is None else authority,
            workspace_root=self.root,
            accepted_circuit_digest=self.material["qasm_digest"],
            expected_objective_digest=self.material["objective_digest"],
            expected_profile_digest=self.profile["record_digest"],
            planned_runtime_versions=RUNTIME_VERSIONS,
            now=now,
            ledger=ledger,
            backend_factory=_fake_backend(counts) if backend is None else backend,
            invocation_counter=counter,
            clock=_monotonic_stub(),
        )


def _monotonic_stub():
    """Deterministic monotonic clock so elapsed time never depends on the machine."""
    ticks = iter([0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5])

    def clock() -> float:
        try:
            return next(ticks)
        except StopIteration:  # pragma: no cover - defensive
            return 1.5

    return clock


@pytest.fixture
def vertical(tmp_path: Path) -> Vertical:
    return Vertical(fx.PRIMARY_FAMILY_PARAMETERS, tmp_path)


def test_deterministic_prechain_rejects_mps_and_selects_stabilizer(vertical: Vertical) -> None:
    """P1/P2/P3/P5/P7 composed: exact answer keys drive method selection."""
    assert vertical.chi_claim["chi_required"] == 32_768
    assert vertical.chi_claim["evidence_class"] == "exact_family_specific"
    assert ids.AER_MPS_LIMITATION in vertical.chi_claim["limitations"]
    assert vertical.floor["payload_floor_bytes"] == 45_812_985_536
    assert set(ids.MPS_FLOOR_EXCLUSIONS).issubset(set(vertical.floor["exclusions"]))
    assert vertical.safe_envelope == 38_654_705_664
    assert vertical.floor["payload_floor_bytes"] - vertical.safe_envelope == 7_158_279_872

    exact = vertical.evaluations[ids.METHOD_MPS_EXACT]
    assert exact["feasibility"] == "infeasible_lower_bound_exceeds_envelope"
    assert exact["rejection_reason"] == "resource_lower_bound_exceeded"
    assert vertical.evaluations[ids.METHOD_MPS_APPROXIMATE]["rejection_reason"] == (
        "exactness_policy_conflict"
    )
    assert vertical.method == ids.METHOD_STABILIZER

    stabilizer = vertical.evaluations[ids.METHOD_STABILIZER]
    assert set(stabilizer["gate_names"]) == {
        "available",
        "family_applicable",
        "qualified",
        "result_capable",
        "satisfies_exactness",
    }
    assert all(stabilizer["gates"][gate] is True for gate in stabilizer["gate_names"])
    assert stabilizer["gates_all_passed"] is True
    assert stabilizer["selected"] is True
    # Availability alone never selects: exact MPS passes every gate and is still refused.
    assert exact["gates_all_passed"] is True
    assert exact["selected"] is False
    # No method may ever be reported as outright feasible from a lower bound alone.
    assert all(item["feasibility"] != "feasible" for item in vertical.evaluations.values())


def test_committed_plan_is_inert_and_executes_nothing(vertical: Vertical) -> None:
    """P11: committing a plan is not execution."""
    counter = InvocationCounter()
    assert vertical.plan["plan_state"] == "inert"
    assert vertical.plan["settings"]["shots"] == ids.FIXED_SHOTS
    assert vertical.plan["method_id"] == ids.METHOD_STABILIZER
    assert counter.count == 0


def test_missing_authority_refuses_and_never_reaches_backend(vertical: Vertical) -> None:
    """P12: no authority means no execution, and the backend is never called."""
    counter = InvocationCounter()
    with pytest.raises(FocusedLoopError) as caught:
        execute_focused_plan(
            plan=vertical.plan,
            authority=None,
            workspace_root=vertical.root,
            accepted_circuit_digest=vertical.material["qasm_digest"],
            expected_objective_digest=vertical.material["objective_digest"],
            expected_profile_digest=vertical.profile["record_digest"],
            planned_runtime_versions=RUNTIME_VERSIONS,
            now=1000.0,
            backend_factory=_refusing_backend,
            invocation_counter=counter,
        )
    assert caught.value.category == "executor_authority_missing"
    assert counter.count == 0


def test_bounded_execution_produces_conforming_receipt(vertical: Vertical) -> None:
    """P13: one attempt, exact plan match, no environment mutation."""
    counter = InvocationCounter()
    qasm_before = (vertical.root / CIRCUIT_PATH).read_text(encoding="utf-8")
    outcome = vertical.execute(counter=counter)

    assert outcome.status == "completed"
    assert counter.count == 1
    receipt = outcome.receipt
    assert receipt["plan_digest"] == vertical.plan["plan_digest"]
    assert receipt["attempt_identity"] == ATTEMPT
    assert receipt["actual_method"] == ids.METHOD_STABILIZER
    assert receipt["actual_settings"]["shots"] == ids.FIXED_SHOTS
    assert receipt["deviation"]["detected"] is False
    assert receipt["deviation"]["fields"] == []
    assert receipt["plan_match_verified_in_process"] is True
    assert sum(outcome.counts.values()) == ids.FIXED_SHOTS
    assert len(outcome.counts) <= ids.STRICT_RESULT_MANIFEST_MAX_OUTCOMES
    # The executor must not touch the bound artifact or the environment.
    assert (vertical.root / CIRCUIT_PATH).read_text(encoding="utf-8") == qasm_before


def test_generic_attempt_join_is_production_and_v3_independent(vertical: Vertical) -> None:
    """The plan/authority/receipt join is production logic and needs no manifest."""
    outcome = vertical.execute()
    joined = join_attempt_records(
        plan=vertical.plan,
        authority=vertical.authority(),
        receipt=outcome.receipt,
        planned_runtime_versions=RUNTIME_VERSIONS,
    )
    assert joined["plan_digest"] == vertical.plan["plan_digest"]
    assert joined["attempt_identity"] == ATTEMPT
    assert joined["deviation"]["detected"] is False
    assert joined["independent_verification_claimed"] is False
    assert joined["plan_match_verified_in_process"] is True
    for required_join in ("plan_digest", "authority_plan_digest", "authority_digest"):
        assert required_join in joined["joins_verified"]


def test_receipt_joins_real_strict_result_manifest_v3(vertical: Vertical) -> None:
    """P14: the sibling receipt composes with the real, unmodified v3 validator.

    This is compatibility evidence gathered from test support, not production
    integration; the Phase A production substrate imports no current-loop module.
    """
    outcome = vertical.execute()
    revisions = circuit_artifact_revisions(
        artifact_revision_id="rev-1", circuit_digest=vertical.material["qasm_digest"]
    )
    payload = build_strict_result_manifest_payload(
        receipt=outcome.receipt,
        counts=outcome.counts,
        circuit_artifact_revision_id="rev-1",
        circuit_digest=vertical.material["qasm_digest"],
        backend_or_sampler=outcome.backend_or_sampler,
        interface=outcome.interface,
        execution_configuration_reference="local-aer-stabilizer-v1",
        bit_order=BIT_ORDER,
        register_order=REGISTER_ORDER,
    )
    normalized = normalize_through_strict_manifest_v3(payload, artifact_revisions=revisions)

    assert normalized["schema_id"] == ids.STRICT_RESULT_MANIFEST_SCHEMA_ID
    assert normalized["observed_shots"] == ids.FIXED_SHOTS
    assert normalized["requested_shots"] == ids.FIXED_SHOTS
    assert normalized["execution_method"]["kind"] == "sampled_shots"
    # v3 keeps its client-reported compatibility fact; the sibling receipt is stronger.
    assert normalized["execution_observation"]["qcoder_independently_verified_execution"] is False
    assert outcome.receipt["plan_match_verified_in_process"] is True

    bound = rebind_receipt_result_manifest_digest(
        receipt=outcome.receipt, result_manifest_digest=normalized["manifest_digest"]
    )
    join = join_receipt_to_strict_result_manifest(
        plan=vertical.plan,
        authority=vertical.authority(),
        receipt=bound,
        manifest_payload=payload,
        artifact_revisions=revisions,
        planned_runtime_versions=RUNTIME_VERSIONS,
    )
    assert join["manifest_digest"] == normalized["manifest_digest"]
    assert join["plan_digest"] == vertical.plan["plan_digest"]
    assert join["attempt_identity"] == ATTEMPT
    assert join["deviation"]["detected"] is False
    for required_join in ("plan_digest", "attempt_identity", "execution_attempt_id"):
        assert required_join in join["joins_verified"]


def test_clean_598_shot_result_is_target_met(vertical: Vertical) -> None:
    """P18/P21: all 598 shots satisfy the predicate; the three axes stay separate."""
    outcome = vertical.execute()
    analysis = rp.build_analysis_result(
        analysis_id="analysis-1",
        counts=outcome.counts,
        answer_key=vertical.material["answer_key"],
    )
    assert analysis["shots_evaluated"] == 598
    assert analysis["satisfying_shots"] == 598
    assert analysis["point_estimate"] == 1.0
    assert analysis["interval"]["lower"] == 0.9950029413057535
    assert analysis["interval"]["level"] == 0.95
    assert analysis["evidence_conclusion"] == "target_met"
    assert analysis["sampling_state"] == "sampling_sufficient_stop_sampling"
    assert analysis["violations"]["count"] == 0
    assert analysis["allowed_support_size"] == 64
    declared = set(analysis["non_claims"])
    for forbidden in (
        "not_state_fidelity",
        "not_process_fidelity",
        "not_noise_characterization",
        "not_universal_clifford_correctness",
        "not_general_simulator_validation",
    ):
        assert forbidden in declared

    action = rp.build_next_action(action_id="action-1", analysis_result=analysis)
    assert action["action"] == "stop_goal_met"
    assert action["combination_valid"] is True
    # Conclusion, sampling state and action remain three separately addressable facts.
    assert action["action"] != analysis["evidence_conclusion"]
    assert action["action"] != analysis["sampling_state"]
    assert "collect_more_shots" not in set(rp.SUPPORTED_ACTIONS)


def test_predicate_violation_never_asks_for_more_shots(vertical: Vertical) -> None:
    """P19: an observed contradiction is not an approximation diagnosis."""
    counts = dict(VALID_COUNTS)
    first = _outcome("000000")
    counts[first] -= 3
    counts[_violating_outcome()] = 3
    outcome = vertical.execute(counts=counts)
    analysis = rp.build_analysis_result(
        analysis_id="analysis-violation",
        counts=outcome.counts,
        answer_key=vertical.material["answer_key"],
    )
    assert analysis["shots_evaluated"] == 598
    assert analysis["satisfying_shots"] == 595
    assert analysis["violations"]["count"] == 3
    assert analysis["evidence_conclusion"] == "target_not_met"
    assert analysis["sampling_state"] == "sampling_sufficient_stop_sampling"
    assert analysis["sampling_state"] != "collect_more_shots"

    action = rp.build_next_action(action_id="action-violation", analysis_result=analysis)
    assert action["action"] == "unsupported"
    assert action["action"] not in {"run_selected_method", "change_method_or_settings"}
    rendered = repr(analysis) + repr(action)
    assert "systematic_approximation" not in rendered
    assert "collect_more_shots" not in rendered


def test_violation_rate_cannot_be_repaired_by_more_shots(vertical: Vertical) -> None:
    """A fixed violation rate stays target_not_met at every sample size."""
    for scale in (1, 10, 100):
        trials = 598 * scale
        violations = 1 * scale
        assert rp.clopper_pearson_lower_bound(
            successes=trials - violations, trials=trials
        ) < 0.9990
        analysis = rp.build_analysis_result(
            analysis_id=f"analysis-scale-{scale}",
            counts={_outcome("000000"): trials - violations, _violating_outcome(): violations},
            answer_key=vertical.material["answer_key"],
            required_shots=trials,
        )
        assert analysis["evidence_conclusion"] == "target_not_met"


def test_undersized_clean_evidence_is_inconclusive(vertical: Vertical) -> None:
    """P20: fewer than 598 clean shots never claims the target and never auto-runs."""
    analysis = rp.build_analysis_result(
        analysis_id="analysis-short",
        counts={_outcome("000000"): 300, _outcome("111111"): 100},
        answer_key=vertical.material["answer_key"],
        required_shots=598,
    )
    assert analysis["shots_evaluated"] == 400
    assert analysis["violations"]["count"] == 0
    assert analysis["evidence_conclusion"] == "inconclusive"
    assert analysis["sampling_state"] == "collect_more_shots"

    action = rp.build_next_action(action_id="action-short", analysis_result=analysis)
    assert action["action"] != "run_selected_method"
    assert "batch" not in repr(action).lower()


def test_equivalent_repeat_request_reuses_result_without_second_execution(
    vertical: Vertical,
) -> None:
    """P22: the repeat request reuses the accepted result and executes nothing."""
    counter = InvocationCounter()
    ledger = AttemptLedger.empty()
    outcome = vertical.execute(counter=counter, ledger=ledger)
    assert counter.count == 1

    identity = reuse.build_reuse_identity(
        objective_digest=vertical.material["objective_digest"],
        circuit_digest=vertical.material["qasm_digest"],
        plan_digest=vertical.plan["plan_digest"],
        profile_digest=vertical.profile["record_digest"],
        runtime_versions=RUNTIME_VERSIONS,
    )
    accepted = {
        "identity": identity,
        "currentness": "current",
        "result_manifest_digest": "b" * 64,
        "receipt_digest": outcome.receipt["receipt_digest"],
        "attempt_identity": ATTEMPT,
    }
    decision = reuse.decide_result_reuse(request_identity=identity, accepted_result=accepted)
    assert decision["action"] == "reuse_existing_result"
    assert decision["new_execution_attempts_required"] == 0
    assert counter.count == 1, "reuse must not execute again"

    # A stale accepted result must be refused rather than softened into reuse.
    with pytest.raises(FocusedLoopError) as caught:
        reuse.decide_result_reuse(
            request_identity=identity, accepted_result={**accepted, "currentness": "stale"}
        )
    assert caught.value.category == "reuse_accepted_result_not_current"

    # The single-use attempt identity cannot fund a second execution.
    with pytest.raises(FocusedLoopError):
        vertical.execute(counter=counter, ledger=outcome.ledger)
    assert counter.count == 1


def test_heldout_family_instance_uses_the_same_code_path(tmp_path: Path) -> None:
    """P24: family-level behaviour with no fixture id or digest special casing."""
    primary = Vertical(fx.PRIMARY_FAMILY_PARAMETERS, tmp_path / "primary")
    heldout = Vertical(fx.HELDOUT_FAMILY_PARAMETERS, tmp_path / "heldout")

    assert heldout.material["qasm_digest"] != primary.material["qasm_digest"]
    assert fx.nested_pairs(heldout.parameters)[0] == (27, 28)
    for instance in (primary, heldout):
        assert instance.chi_claim["chi_required"] == 32_768
        assert instance.floor["payload_floor_bytes"] == 45_812_985_536
        assert instance.evaluations[ids.METHOD_MPS_EXACT]["rejection_reason"] == (
            "resource_lower_bound_exceeded"
        )
        assert instance.evaluations[ids.METHOD_MPS_APPROXIMATE]["rejection_reason"] == (
            "exactness_policy_conflict"
        )
        assert instance.method == ids.METHOD_STABILIZER
        assert fx.valid_support_size(instance.parameters) == 64

    outcome = heldout.execute()
    analysis = rp.build_analysis_result(
        analysis_id="analysis-heldout",
        counts=outcome.counts,
        answer_key=heldout.material["answer_key"],
    )
    assert analysis["evidence_conclusion"] == "target_met"
    assert analysis["interval"]["lower"] == 0.9950029413057535


def test_identities_are_stable_across_independent_derivations(tmp_path: Path) -> None:
    """P23: the same question answered twice yields identical digests."""
    first = Vertical(fx.PRIMARY_FAMILY_PARAMETERS, tmp_path / "a")
    second = Vertical(fx.PRIMARY_FAMILY_PARAMETERS, tmp_path / "b")
    for key in ("qasm_digest", "objective_digest", "answer_key_digest", "fixture_manifest_digest"):
        assert first.material[key] == second.material[key]
    assert first.plan["plan_digest"] == second.plan["plan_digest"]
    assert first.chi_claim["record_digest"] == second.chi_claim["record_digest"]
    assert compute_circuit_digest(first.qasm) == first.material["qasm_digest"]


def test_model_and_protected_projections_withhold_raw_evidence(vertical: Vertical) -> None:
    """P25: the decision projections carry the derived envelope, never raw evidence."""
    for destination in ("model_decision_context", "protected_service"):
        projected = privacy.project_record(vertical.resource_receipt, destination=destination)
        rendered = repr(projected)
        assert "total_memory_bytes" not in projected
        assert "available_floor_bytes" not in projected
        assert str(vertical.resource_receipt["total_memory_bytes"]) not in rendered
        assert projected["safe_envelope_bytes"] == vertical.safe_envelope
        privacy.assert_no_prohibited_keys(projected, destination=destination)


def test_phase_a_harness_keeps_fake_backend_explicit() -> None:
    """Phase A's historical composition proof remains explicitly fake-backed.

    Aer availability in the conference environment must not retroactively turn this
    file into real-execution evidence.
    """
    source = inspect.getsource(Vertical.execute)
    assert "backend_factory=_fake_backend(counts) if backend is None else backend" in source
