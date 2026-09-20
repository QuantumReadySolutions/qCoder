"""Actual local Qiskit Aer proof for the D-143 IQT conference branch.

Unlike the Phase A integrated test, this module never substitutes the fake backend for
the success path. It requires the exact locally prepared Qiskit/Aer versions, executes
the frozen 598-shot stabilizer plan through the default aer_stabilizer_v1 adapter, binds
the sibling receipt to the accepted strict-result-manifest v3 compatibility validator,
checks the exact predicate, and proves exact-identity reuse without a second execution.

The socket sentinels are proof guards: any Python socket connection attempt during the
bounded execution fails the test. They do not make a general claim about arbitrary
third-party native code; the executor's static package-isolation proof separately shows
that qCoder imports no remote/provider networking surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import importlib.metadata
import os
from pathlib import Path
import socket
from typing import Any, Mapping

import pytest

import qcoder.executors.aer_stabilizer_v1 as aer_exec
from qcoder.executors.aer_stabilizer_v1 import (
    BackendRequest,
    BackendSample,
    InvocationCounter,
    execute_focused_plan,
)
from qcoder.focused_loop import applicability as ap
from qcoder.focused_loop import fixtures as fx
from qcoder.focused_loop import identities as ids
from qcoder.focused_loop import mps_floor as mf
from qcoder.focused_loop import result_protocol as rp
from qcoder.focused_loop import reuse
from qcoder.focused_loop.attempt_join import rebind_receipt_result_manifest_digest
from qcoder.focused_loop.authority import AttemptLedger, build_execution_authority
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

EXPECTED_QISKIT = "2.5.2"
EXPECTED_QISKIT_AER = "0.17.2"
NOW = 1_000.0
BIT_ORDER = [f"c[{index}]" for index in range(12)]
REGISTER_ORDER = ["c"]


@dataclass(frozen=True)
class PreparedCase:
    root: Path
    material: Mapping[str, Any]
    profile: Mapping[str, Any]
    plan: Mapping[str, Any]
    authority: Mapping[str, Any]
    runtime_versions: Mapping[str, str]


def _runtime_versions() -> dict[str, str]:
    try:
        observed = {
            "qiskit": importlib.metadata.version("qiskit"),
            "qiskit_aer": importlib.metadata.version("qiskit-aer"),
        }
    except importlib.metadata.PackageNotFoundError as exc:
        raise AssertionError(
            "conference_real_aer_environment_missing: install the exact conference "
            "Qiskit/Aer requirements before running this proof"
        ) from exc
    assert observed == {
        "qiskit": EXPECTED_QISKIT,
        "qiskit_aer": EXPECTED_QISKIT_AER,
    }
    return observed


def _source_hashes() -> dict[str, str]:
    roots = {
        Path(fx.__file__).resolve().parent,
        Path(aer_exec.__file__).resolve().parent,
    }
    files = sorted({path for root in roots for path in root.glob("*.py")})
    return {str(path): sha256(path.read_bytes()).hexdigest() for path in files}


def _workspace_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _prepare(
    *,
    parameters: fx.NestedBellFamilyParameters,
    root: Path,
    seed: int,
    attempt_identity: str,
) -> PreparedCase:
    material = fx.materialize_fixture(parameters)
    resource_receipt = build_synthetic_resource_receipt(
        receipt_id=f"{parameters.fixture_id}:conference-resource"
    )
    floor = mf.build_coefficient_floor(
        qubit_count=parameters.qubit_count,
        pairs=fx.nested_pairs(parameters),
    )
    evaluations = ap.evaluate_regime_methods(
        applicability_prefix=f"{parameters.fixture_id}-conference",
        coefficient_floor=floor,
        safe_envelope_bytes=resource_receipt["safe_envelope_bytes"],
    )
    assert ap.selected_method(evaluations) == ids.METHOD_STABILIZER
    assert evaluations[ids.METHOD_MPS_EXACT]["rejection_reason"] == (
        "resource_lower_bound_exceeded"
    )
    assert evaluations[ids.METHOD_MPS_APPROXIMATE]["rejection_reason"] == (
        "exactness_policy_conflict"
    )

    profile = build_execution_profile(
        profile_id="local-aer-stabilizer-v1",
        method=ids.METHOD_STABILIZER,
        circuit_family_class="clifford_only",
    )
    circuit_path = (
        "circuits/" + parameters.fixture_id.casefold().replace("-", "_") + ".qasm"
    )
    target = root / circuit_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(material["qasm"], encoding="utf-8")

    plan = build_execution_plan(
        objective_digest=material["objective_digest"],
        circuit_digest=material["qasm_digest"],
        circuit_path=circuit_path,
        profile_digest=profile["record_digest"],
        seed=seed,
        max_wall_seconds=60.0,
        max_memory_bytes=2 * 1024**3,
    )
    authority = build_execution_authority(
        plan_digest=plan["plan_digest"],
        attempt_identity=attempt_identity,
        expires_at=NOW + 600.0,
    )
    return PreparedCase(
        root=root,
        material=material,
        profile=profile,
        plan=plan,
        authority=authority,
        runtime_versions=_runtime_versions(),
    )


def _deny_network(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("conference_real_aer_network_connection_attempted")


def _execute_real(
    *,
    case: PreparedCase,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, InvocationCounter, Mapping[str, Any], Mapping[str, Any]]:
    source_before = _source_hashes()
    workspace_before = _workspace_hashes(case.root)
    environment_before = dict(os.environ)

    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    monkeypatch.setattr(socket, "create_connection", _deny_network)

    counter = InvocationCounter()
    outcome = execute_focused_plan(
        plan=case.plan,
        authority=case.authority,
        workspace_root=case.root,
        accepted_circuit_digest=case.material["qasm_digest"],
        expected_objective_digest=case.material["objective_digest"],
        expected_profile_digest=case.profile["record_digest"],
        planned_runtime_versions=case.runtime_versions,
        now=NOW,
        ledger=AttemptLedger.empty(),
        invocation_counter=counter,
    )

    assert outcome.status == "completed"
    assert counter.count == 1
    assert outcome.backend_or_sampler == "aer_simulator_stabilizer"
    assert outcome.interface == "qiskit_aer.AerSimulator.run"
    assert outcome.receipt["actual_method"] == ids.METHOD_STABILIZER
    assert outcome.receipt["actual_settings"]["shots"] == 598
    assert outcome.receipt["runtime_versions"] == case.runtime_versions
    assert outcome.receipt["deviation"] == {"detected": False, "fields": []}
    assert outcome.receipt["plan_match_verified_in_process"] is True
    assert sum(outcome.counts.values()) == 598
    assert len(outcome.counts) <= 64

    assert _source_hashes() == source_before
    assert _workspace_hashes(case.root) == workspace_before
    assert dict(os.environ) == environment_before

    analysis = rp.build_analysis_result(
        analysis_id=f"{case.material['declared_inputs']['fixture_id']}:conference-analysis",
        counts=outcome.counts,
        answer_key=case.material["answer_key"],
    )
    action = rp.build_next_action(
        action_id=f"{case.material['declared_inputs']['fixture_id']}:conference-action",
        analysis_result=analysis,
    )
    assert analysis["shots_evaluated"] == 598
    assert analysis["satisfying_shots"] == 598
    assert analysis["interval"]["lower"] == 0.9950029413057535
    assert analysis["evidence_conclusion"] == "target_met"
    assert analysis["sampling_state"] == "sampling_sufficient_stop_sampling"
    assert action["action"] == "stop_goal_met"
    return outcome, counter, analysis, action


def test_primary_real_aer_receipt_manifest_analysis_and_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _prepare(
        parameters=fx.PRIMARY_FAMILY_PARAMETERS,
        root=tmp_path / "primary",
        seed=7,
        attempt_identity="conference-real-aer-primary-0001",
    )
    assert case.material["chi_required_claim"]["chi_required"] == 32_768
    assert case.material["coefficient_floor"]["payload_floor_bytes"] == 45_812_985_536

    outcome, counter, real_analysis, _action = _execute_real(
        case=case, monkeypatch=monkeypatch
    )

    revisions = circuit_artifact_revisions(
        artifact_revision_id="conference-primary-rev-1",
        circuit_digest=case.material["qasm_digest"],
    )
    payload = build_strict_result_manifest_payload(
        receipt=outcome.receipt,
        counts=outcome.counts,
        circuit_artifact_revision_id="conference-primary-rev-1",
        circuit_digest=case.material["qasm_digest"],
        backend_or_sampler=outcome.backend_or_sampler,
        interface=outcome.interface,
        execution_configuration_reference="local-aer-stabilizer-v1",
        bit_order=BIT_ORDER,
        register_order=REGISTER_ORDER,
    )
    manifest = normalize_through_strict_manifest_v3(payload, artifact_revisions=revisions)
    assert manifest["requested_shots"] == 598
    assert manifest["observed_shots"] == 598

    bound_receipt = rebind_receipt_result_manifest_digest(
        receipt=outcome.receipt,
        result_manifest_digest=manifest["manifest_digest"],
    )
    joined = join_receipt_to_strict_result_manifest(
        plan=case.plan,
        authority=case.authority,
        receipt=bound_receipt,
        manifest_payload=payload,
        artifact_revisions=revisions,
        planned_runtime_versions=case.runtime_versions,
    )
    assert joined["attempt_identity"] == case.authority["attempt_identity"]
    assert joined["manifest_digest"] == manifest["manifest_digest"]
    assert joined["deviation"]["detected"] is False

    identity = reuse.build_reuse_identity(
        objective_digest=case.material["objective_digest"],
        circuit_digest=case.material["qasm_digest"],
        plan_digest=case.plan["plan_digest"],
        profile_digest=case.profile["record_digest"],
        runtime_versions=case.runtime_versions,
    )
    accepted = {
        "identity": identity,
        "currentness": "current",
        "result_manifest_digest": manifest["manifest_digest"],
        "receipt_digest": bound_receipt["receipt_digest"],
        "attempt_identity": case.authority["attempt_identity"],
    }
    decision = reuse.decide_result_reuse(
        request_identity=identity,
        accepted_result=accepted,
    )
    assert decision["action"] == "reuse_existing_result"
    assert decision["new_execution_attempts_required"] == 0
    assert counter.count == 1

    with pytest.raises(FocusedLoopError) as excinfo:
        execute_focused_plan(
            plan=case.plan,
            authority=case.authority,
            workspace_root=case.root,
            accepted_circuit_digest=case.material["qasm_digest"],
            expected_objective_digest=case.material["objective_digest"],
            expected_profile_digest=case.profile["record_digest"],
            planned_runtime_versions=case.runtime_versions,
            now=NOW,
            ledger=outcome.ledger,
            invocation_counter=counter,
        )
    assert excinfo.value.category == "execution_attempt_identity_already_consumed"
    assert counter.count == 1

    fake_authority = build_execution_authority(
        plan_digest=case.plan["plan_digest"],
        attempt_identity="conference-fake-comparison-primary-0001",
        expires_at=NOW + 600.0,
    )
    first_valid_outcome = fx.allowed_outcomes(fx.PRIMARY_FAMILY_PARAMETERS)[0]

    def fake_backend(request: BackendRequest) -> BackendSample:
        assert request.shots == 598
        return BackendSample(
            counts={first_valid_outcome: 598},
            backend_or_sampler="phase_a_injected_fake_backend",
            interface="phase_a_fake.run",
            runtime_versions=case.runtime_versions,
        )

    fake = execute_focused_plan(
        plan=case.plan,
        authority=fake_authority,
        workspace_root=case.root,
        accepted_circuit_digest=case.material["qasm_digest"],
        expected_objective_digest=case.material["objective_digest"],
        expected_profile_digest=case.profile["record_digest"],
        planned_runtime_versions=case.runtime_versions,
        now=NOW,
        backend_factory=fake_backend,
    )
    fake_analysis = rp.build_analysis_result(
        analysis_id="conference-fake-comparison-analysis",
        counts=fake.counts,
        answer_key=case.material["answer_key"],
    )
    assert fake_analysis["evidence_conclusion"] == real_analysis["evidence_conclusion"]
    assert fake_analysis["sampling_state"] == real_analysis["sampling_state"]
    assert fake_analysis["interval"]["lower"] == real_analysis["interval"]["lower"]
    assert fake_analysis["shots_evaluated"] == real_analysis["shots_evaluated"] == 598


@pytest.mark.parametrize(
    ("parameters", "seed", "attempt_identity"),
    [
        (fx.PRIMARY_FAMILY_PARAMETERS, 11, "conference-real-aer-primary-0002"),
        (fx.PRIMARY_FAMILY_PARAMETERS, 19, "conference-real-aer-primary-0003"),
        (fx.HELDOUT_FAMILY_PARAMETERS, 23, "conference-real-aer-heldout-0001"),
    ],
)
def test_real_aer_repeatability_with_fresh_attempt_identity(
    parameters: fx.NestedBellFamilyParameters,
    seed: int,
    attempt_identity: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _prepare(
        parameters=parameters,
        root=tmp_path / attempt_identity,
        seed=seed,
        attempt_identity=attempt_identity,
    )
    outcome, counter, analysis, action = _execute_real(
        case=case, monkeypatch=monkeypatch
    )
    assert outcome.ledger.is_consumed(attempt_identity) is True
    assert counter.count == 1
    assert analysis["evidence_conclusion"] == "target_met"
    assert action["action"] == "stop_goal_met"
