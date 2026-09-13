"""Bounded Aer stabilizer executor: every refusal, every censored failure, no real Aer.

``qiskit_aer`` is not installed in this environment and is never installed by these
tests. Every execution path is exercised through the injected fake backend adapter, and
the real lazy adapter is only ever asked to prove that it reports
``executor_backend_unavailable`` instead of falling back to a substitute simulator.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable
import importlib.util
import os
from pathlib import Path
import sys
from typing import Any

import pytest

from qcoder.executors.aer_stabilizer_v1 import (
    BackendRequest,
    BackendSample,
    CooperativeCancellation,
    ExecutionOutcome,
    ExecutorBackendUnavailable,
    InvocationCounter,
    aer_stabilizer_backend,
    compute_circuit_digest,
    execute_focused_plan,
    load_bound_qasm,
    resolve_workspace_qasm_path,
)
from qcoder.focused_loop.authority import AttemptLedger, build_execution_authority
from qcoder.focused_loop.canonical import FocusedLoopError, digest_excluding
from qcoder.focused_loop.identities import FIXED_SHOTS, METHOD_STABILIZER
from qcoder.focused_loop.plan import PLAN_DIGEST_FIELD, build_execution_plan
from qcoder.focused_loop.receipt import (
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    STATUS_UNSUPPORTED,
    receipt_is_enrollable_as_current_evidence,
    validate_execution_receipt,
)

OBJECTIVE_DIGEST = "1" * 64
PROFILE_DIGEST = "3" * 64
ATTEMPT_IDENTITY = "attempt-exec-0001"
NOW = 1_000.0
EXPIRES_AT = 2_000.0
PLANNED_VERSIONS = {"python": "3.14.3", "qiskit": "2.4.1", "qiskit_aer": "0.17.0"}
COUNTS = {"000000000000": 299, "000000000011": 299}
QASM_TEXT = (
    'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[12];\ncreg c[12];\n'
    "h q[0];\ncx q[0],q[1];\nmeasure q -> c;\n"
)


class FakeBackend:
    """Injected stand-in for the Aer adapter. Records every dispatch it receives."""

    def __init__(
        self,
        *,
        counts: dict[str, int] | None = None,
        runtime_versions: dict[str, str] | None = None,
        cancel_during_run: bool = False,
        raises: BaseException | None = None,
    ) -> None:
        self.counts = COUNTS if counts is None else counts
        self.runtime_versions = (
            dict(PLANNED_VERSIONS) if runtime_versions is None else runtime_versions
        )
        self.cancel_during_run = cancel_during_run
        self.raises = raises
        self.calls: list[BackendRequest] = []

    def __call__(self, request: BackendRequest) -> BackendSample:
        self.calls.append(request)
        if self.raises is not None:
            raise self.raises
        if self.cancel_during_run:
            request.cancellation.request()
        return BackendSample(
            counts=dict(self.counts),
            backend_or_sampler="fake_stabilizer_sampler",
            interface="fake_backend.run",
            runtime_versions=dict(self.runtime_versions),
        )


def forbidden_backend(request: BackendRequest) -> BackendSample:
    raise AssertionError("the backend adapter must never be reached on a refused plan")


def fixed_clock(*values: float) -> Callable[[], float]:
    remaining = list(values)

    def clock() -> float:
        return remaining.pop(0) if remaining else values[-1]

    return clock


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "circuits").mkdir(parents=True)
    (root / "circuits" / "nested_bell.qasm").write_text(QASM_TEXT, encoding="utf-8")
    return root


def make_plan(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "objective_digest": OBJECTIVE_DIGEST,
        "circuit_digest": compute_circuit_digest(QASM_TEXT),
        "circuit_path": "circuits/nested_bell.qasm",
        "profile_digest": PROFILE_DIGEST,
        "seed": 5,
    }
    kwargs.update(overrides)
    return build_execution_plan(**kwargs)


def tamper(plan: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    mutated = {
        key: dict(value) if isinstance(value, dict) else value for key, value in plan.items()
    }
    for key, value in overrides.items():
        if "." in key:
            outer, inner = key.split(".", 1)
            mutated[outer][inner] = value
        else:
            mutated[key] = value
    mutated[PLAN_DIGEST_FIELD] = digest_excluding(mutated, field=PLAN_DIGEST_FIELD)
    return mutated


def make_authority(plan: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "plan_digest": plan[PLAN_DIGEST_FIELD],
        "attempt_identity": ATTEMPT_IDENTITY,
        "expires_at": EXPIRES_AT,
    }
    kwargs.update(overrides)
    return build_execution_authority(**kwargs)


def run(
    plan: dict[str, Any],
    authority: dict[str, Any] | None,
    workspace_root: Path,
    **overrides: Any,
) -> ExecutionOutcome:
    kwargs: dict[str, Any] = {
        "plan": plan,
        "authority": authority,
        "workspace_root": workspace_root,
        "accepted_circuit_digest": plan["circuit_digest"],
        "expected_objective_digest": OBJECTIVE_DIGEST,
        "expected_profile_digest": PROFILE_DIGEST,
        "planned_runtime_versions": PLANNED_VERSIONS,
        "now": NOW,
        "clock": fixed_clock(0.0, 0.25),
    }
    kwargs.update(overrides)
    return execute_focused_plan(**kwargs)


def test_exact_plan_happy_path_through_the_injected_fake_backend(workspace: Path) -> None:
    plan = make_plan()
    authority = make_authority(plan)
    backend = FakeBackend()
    counter = InvocationCounter()
    environment_before = dict(os.environ)
    qasm_before = (workspace / "circuits" / "nested_bell.qasm").read_text(encoding="utf-8")

    outcome = run(
        plan, authority, workspace, backend_factory=backend, invocation_counter=counter
    )

    assert outcome.status == STATUS_COMPLETED
    assert outcome.completed is True
    assert counter.count == 1
    assert len(backend.calls) == 1
    assert backend.calls[0].method_id == METHOD_STABILIZER
    assert backend.calls[0].shots == FIXED_SHOTS
    assert backend.calls[0].noise == "none"
    assert backend.calls[0].seed == 5
    assert backend.calls[0].qasm_text == QASM_TEXT
    assert outcome.counts == dict(sorted(COUNTS.items()))
    assert sum(outcome.counts.values()) == FIXED_SHOTS

    receipt = outcome.receipt
    assert receipt["status"] == STATUS_COMPLETED
    assert receipt["actual_method"] == METHOD_STABILIZER
    assert receipt["actual_settings"] == {"shots": FIXED_SHOTS, "noise": "none", "seed": 5}
    assert receipt["actual_profile_digest"] == PROFILE_DIGEST
    assert receipt["deviation"] == {"detected": False, "fields": []}
    assert receipt["plan_match_verified_in_process"] is True
    assert receipt_is_enrollable_as_current_evidence(receipt) is True
    assert validate_execution_receipt(
        receipt,
        plan=plan,
        expected_attempt_identity=ATTEMPT_IDENTITY,
        expected_runtime_versions=PLANNED_VERSIONS,
    ) == receipt

    assert outcome.ledger.is_consumed(ATTEMPT_IDENTITY) is True
    assert dict(os.environ) == environment_before
    assert "qiskit_aer" not in sys.modules
    assert (workspace / "circuits" / "nested_bell.qasm").read_text(encoding="utf-8") == qasm_before


def test_missing_authority_refuses_with_zero_backend_dispatch(workspace: Path) -> None:
    plan = make_plan()
    counter = InvocationCounter()
    with pytest.raises(FocusedLoopError) as excinfo:
        run(plan, None, workspace, backend_factory=forbidden_backend, invocation_counter=counter)
    assert excinfo.value.category == "executor_authority_missing"
    assert counter.count == 0


def test_authority_for_a_different_plan_is_refused(workspace: Path) -> None:
    plan = make_plan()
    other = make_plan(circuit_digest="9" * 64)
    counter = InvocationCounter()
    with pytest.raises(FocusedLoopError) as excinfo:
        run(
            plan,
            make_authority(other),
            workspace,
            backend_factory=forbidden_backend,
            invocation_counter=counter,
        )
    assert excinfo.value.category == "execution_authority_plan_digest_mismatch"
    assert counter.count == 0


def test_expired_and_stale_displayed_authority_are_refused(workspace: Path) -> None:
    plan = make_plan()
    counter = InvocationCounter()
    with pytest.raises(FocusedLoopError) as expired:
        run(
            plan,
            make_authority(plan, expires_at=NOW - 1.0),
            workspace,
            backend_factory=forbidden_backend,
            invocation_counter=counter,
        )
    assert expired.value.category == "execution_authority_expired"

    stale = build_execution_authority(
        plan_digest=plan[PLAN_DIGEST_FIELD],
        displayed_plan_digest=make_plan(seed=6)[PLAN_DIGEST_FIELD],
        attempt_identity=ATTEMPT_IDENTITY,
        expires_at=EXPIRES_AT,
    )
    with pytest.raises(FocusedLoopError) as displayed:
        run(
            plan,
            stale,
            workspace,
            backend_factory=forbidden_backend,
            invocation_counter=counter,
        )
    assert displayed.value.category == "execution_authority_displayed_plan_stale"
    assert counter.count == 0


@pytest.mark.parametrize(
    ("overrides", "category"),
    [
        ({"method_id": "mps_exact"}, "execution_plan_method_unsupported"),
        ({"settings.shots": 597}, "execution_plan_shots_unsupported"),
        ({"settings.shots": 1_024}, "execution_plan_shots_unsupported"),
        ({"settings.noise": "depolarizing"}, "execution_plan_noise_unsupported"),
        ({"regime_id": "remote_qpu_v1"}, "execution_plan_regime_unsupported"),
        ({"result_protocol_id": "other.v1"}, "execution_plan_result_protocol_unsupported"),
        ({"plan_state": "authorized"}, "execution_plan_state_not_inert"),
    ],
)
def test_out_of_regime_plans_are_refused_before_any_dispatch(
    workspace: Path, overrides: dict[str, Any], category: str
) -> None:
    plan = make_plan()
    forged = tamper(plan, **overrides)
    authority = make_authority(forged)
    counter = InvocationCounter()
    with pytest.raises(FocusedLoopError) as excinfo:
        run(
            forged,
            authority,
            workspace,
            accepted_circuit_digest=forged["circuit_digest"],
            backend_factory=forbidden_backend,
            invocation_counter=counter,
        )
    assert excinfo.value.category == category
    assert counter.count == 0


def test_a_forged_plan_digest_is_refused(workspace: Path) -> None:
    plan = dict(make_plan())
    authority = make_authority(plan)
    plan[PLAN_DIGEST_FIELD] = "0" * 64
    counter = InvocationCounter()
    with pytest.raises(FocusedLoopError) as excinfo:
        run(
            plan,
            authority,
            workspace,
            backend_factory=forbidden_backend,
            invocation_counter=counter,
        )
    assert excinfo.value.category == "execution_plan_digest_mismatch"
    assert counter.count == 0


def test_wrong_objective_or_profile_digest_is_refused(workspace: Path) -> None:
    plan = make_plan()
    authority = make_authority(plan)
    counter = InvocationCounter()
    with pytest.raises(FocusedLoopError) as objective_error:
        run(
            plan,
            authority,
            workspace,
            expected_objective_digest="a" * 64,
            backend_factory=forbidden_backend,
            invocation_counter=counter,
        )
    assert objective_error.value.category == "executor_objective_digest_mismatch"
    with pytest.raises(FocusedLoopError) as profile_error:
        run(
            plan,
            authority,
            workspace,
            expected_profile_digest="b" * 64,
            backend_factory=forbidden_backend,
            invocation_counter=counter,
        )
    assert profile_error.value.category == "executor_profile_digest_mismatch"
    assert counter.count == 0


def test_stale_cross_revision_circuit_binding_is_refused_before_execution(
    workspace: Path,
) -> None:
    plan = make_plan()
    authority = make_authority(plan)
    counter = InvocationCounter()
    with pytest.raises(FocusedLoopError) as excinfo:
        run(
            plan,
            authority,
            workspace,
            accepted_circuit_digest=compute_circuit_digest(QASM_TEXT + "// revised\n"),
            backend_factory=forbidden_backend,
            invocation_counter=counter,
        )
    assert excinfo.value.category == "executor_circuit_binding_stale"
    assert counter.count == 0


def test_loaded_qasm_digest_mismatch_is_refused(workspace: Path) -> None:
    plan = make_plan()
    authority = make_authority(plan)
    (workspace / "circuits" / "nested_bell.qasm").write_text(
        QASM_TEXT + "x q[0];\n", encoding="utf-8"
    )
    counter = InvocationCounter()
    with pytest.raises(FocusedLoopError) as excinfo:
        run(
            plan,
            authority,
            workspace,
            backend_factory=forbidden_backend,
            invocation_counter=counter,
        )
    assert excinfo.value.category == "executor_loaded_circuit_digest_mismatch"
    assert counter.count == 0


@pytest.mark.parametrize(
    ("circuit_path", "category"),
    [
        ("../outside.qasm", "executor_circuit_path_traversal"),
        ("circuits/../../outside.qasm", "executor_circuit_path_traversal"),
        ("/etc/passwd.qasm", "executor_circuit_path_absolute"),
        ("C:/windows/evil.qasm", "executor_circuit_path_absolute"),
        ("circuits/nested_bell.py", "executor_circuit_path_suffix_unsupported"),
        ("circuits/nested_bell.qasm.txt", "executor_circuit_path_suffix_unsupported"),
        ("circuits/absent.qasm", "executor_circuit_path_missing"),
    ],
)
def test_unsafe_circuit_paths_are_refused(
    workspace: Path, circuit_path: str, category: str
) -> None:
    plan = make_plan(circuit_path=circuit_path)
    authority = make_authority(plan)
    counter = InvocationCounter()
    with pytest.raises(FocusedLoopError) as excinfo:
        run(
            plan,
            authority,
            workspace,
            backend_factory=forbidden_backend,
            invocation_counter=counter,
        )
    assert excinfo.value.category == category
    assert counter.count == 0


def test_symlink_escape_is_refused(workspace: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.qasm").write_text(QASM_TEXT, encoding="utf-8")
    link = workspace / "circuits" / "link.qasm"
    link.symlink_to(outside / "secret.qasm")

    plan = make_plan(circuit_path="circuits/link.qasm")
    authority = make_authority(plan)
    counter = InvocationCounter()
    with pytest.raises(FocusedLoopError) as excinfo:
        run(
            plan,
            authority,
            workspace,
            backend_factory=forbidden_backend,
            invocation_counter=counter,
        )
    assert excinfo.value.category == "executor_circuit_path_escape"
    assert counter.count == 0


def test_path_resolution_helpers_are_directly_bounded(workspace: Path) -> None:
    resolved = resolve_workspace_qasm_path(workspace, "circuits/nested_bell.qasm")
    assert resolved.is_file()
    assert load_bound_qasm(workspace, "circuits/nested_bell.qasm") == QASM_TEXT
    with pytest.raises(FocusedLoopError) as excinfo:
        resolve_workspace_qasm_path(workspace / "absent", "circuits/nested_bell.qasm")
    assert excinfo.value.category == "executor_workspace_root_invalid"


def test_timeout_produces_a_censored_typed_failure_with_no_partial_counts(
    workspace: Path,
) -> None:
    plan = make_plan(max_wall_seconds=1.0)
    authority = make_authority(plan)
    backend = FakeBackend()
    outcome = run(
        plan, authority, workspace, backend_factory=backend, clock=fixed_clock(0.0, 5.0)
    )
    assert outcome.status == STATUS_TIMEOUT
    assert outcome.category == "executor_wall_time_exceeded"
    assert outcome.counts is None
    assert outcome.receipt["status"] == STATUS_TIMEOUT
    assert outcome.receipt["timing"]["censored"] is True
    assert outcome.receipt["timing"]["elapsed_seconds"] is None
    assert outcome.receipt["result_manifest_digest"] is None
    assert receipt_is_enrollable_as_current_evidence(outcome.receipt) is False
    assert outcome.ledger.is_consumed(ATTEMPT_IDENTITY) is True


def test_cancel_before_dispatch_never_reaches_the_backend(workspace: Path) -> None:
    plan = make_plan()
    authority = make_authority(plan)
    token = CooperativeCancellation()
    token.request()
    counter = InvocationCounter()
    outcome = run(
        plan,
        authority,
        workspace,
        backend_factory=forbidden_backend,
        cancellation=token,
        invocation_counter=counter,
    )
    assert outcome.status == STATUS_CANCELLED
    assert outcome.category == "executor_cancelled_before_dispatch"
    assert outcome.counts is None
    assert counter.count == 0
    assert outcome.receipt["timing"]["censored"] is True
    assert receipt_is_enrollable_as_current_evidence(outcome.receipt) is False


def test_cancel_during_dispatch_discards_any_counts(workspace: Path) -> None:
    plan = make_plan()
    authority = make_authority(plan)
    backend = FakeBackend(cancel_during_run=True)
    outcome = run(plan, authority, workspace, backend_factory=backend, cancellation=None)
    assert len(backend.calls) == 1
    assert outcome.status == STATUS_CANCELLED
    assert outcome.category == "executor_cancelled_during_dispatch"
    assert outcome.counts is None
    assert outcome.receipt["timing"]["censored"] is True
    assert outcome.receipt["result_manifest_digest"] is None
    assert receipt_is_enrollable_as_current_evidence(outcome.receipt) is False


def test_cancel_during_dispatch_uses_an_explicitly_supplied_token(workspace: Path) -> None:
    plan = make_plan()
    authority = make_authority(plan)
    token = CooperativeCancellation()

    def cancelling_backend(request: BackendRequest) -> BackendSample:
        assert request.cancellation is token
        token.request()
        return BackendSample(
            counts=dict(COUNTS),
            backend_or_sampler="fake_stabilizer_sampler",
            interface="fake_backend.run",
            runtime_versions=dict(PLANNED_VERSIONS),
        )

    outcome = run(
        plan, authority, workspace, backend_factory=cancelling_backend, cancellation=token
    )
    assert outcome.status == STATUS_CANCELLED
    assert outcome.counts is None


def test_a_second_execution_for_the_same_attempt_identity_is_refused(workspace: Path) -> None:
    plan = make_plan()
    authority = make_authority(plan)
    backend = FakeBackend()
    counter = InvocationCounter()
    first = run(plan, authority, workspace, backend_factory=backend, invocation_counter=counter)
    assert first.status == STATUS_COMPLETED
    assert counter.count == 1

    with pytest.raises(FocusedLoopError) as excinfo:
        run(
            plan,
            authority,
            workspace,
            backend_factory=backend,
            ledger=first.ledger,
            invocation_counter=counter,
        )
    assert excinfo.value.category == "execution_attempt_identity_already_consumed"
    assert counter.count == 1
    assert len(backend.calls) == 1


def test_a_deviating_runtime_version_is_reported_and_not_enrollable(workspace: Path) -> None:
    plan = make_plan()
    authority = make_authority(plan)
    backend = FakeBackend(runtime_versions={**PLANNED_VERSIONS, "qiskit": "2.3.0"})
    outcome = run(plan, authority, workspace, backend_factory=backend)
    assert outcome.status == STATUS_COMPLETED
    assert outcome.receipt["deviation"] == {
        "detected": True,
        "fields": ["runtime_versions.qiskit"],
    }
    assert receipt_is_enrollable_as_current_evidence(outcome.receipt) is False
    with pytest.raises(FocusedLoopError) as excinfo:
        validate_execution_receipt(
            outcome.receipt, plan=plan, expected_runtime_versions=PLANNED_VERSIONS
        )
    assert excinfo.value.category == "execution_receipt_runtime_version_mismatch"


def test_a_backend_returning_the_wrong_shot_total_is_refused(workspace: Path) -> None:
    plan = make_plan()
    authority = make_authority(plan)
    backend = FakeBackend(counts={"000000000000": 597})
    with pytest.raises(FocusedLoopError) as excinfo:
        run(plan, authority, workspace, backend_factory=backend)
    assert excinfo.value.category == "executor_counts_shot_total_mismatch"


def test_a_backend_returning_non_bitstring_outcomes_is_refused(workspace: Path) -> None:
    plan = make_plan()
    authority = make_authority(plan)
    backend = FakeBackend(counts={"0x2a": 598})
    with pytest.raises(FocusedLoopError) as excinfo:
        run(plan, authority, workspace, backend_factory=backend)
    assert excinfo.value.category == "executor_counts_invalid"


def test_an_unexpected_backend_exception_becomes_a_typed_failure(workspace: Path) -> None:
    plan = make_plan()
    authority = make_authority(plan)
    backend = FakeBackend(raises=RuntimeError("simulator exploded"))
    outcome = run(plan, authority, workspace, backend_factory=backend)
    assert outcome.status == STATUS_FAILED
    assert outcome.category == "executor_backend_failed"
    assert outcome.detail == "RuntimeError"
    assert outcome.counts is None
    assert outcome.receipt["timing"]["censored"] is True
    assert receipt_is_enrollable_as_current_evidence(outcome.receipt) is False


def test_unavailable_aer_is_reported_not_substituted(workspace: Path) -> None:
    plan = make_plan()
    authority = make_authority(plan)
    backend = FakeBackend(raises=ExecutorBackendUnavailable("qiskit_aer"))
    outcome = run(plan, authority, workspace, backend_factory=backend)
    assert outcome.status == STATUS_UNSUPPORTED
    assert outcome.category == "executor_backend_unavailable"
    assert outcome.detail == "qiskit_aer"
    assert outcome.counts is None
    assert outcome.receipt["timing"]["censored"] is True
    assert outcome.receipt["result_manifest_digest"] is None
    assert receipt_is_enrollable_as_current_evidence(outcome.receipt) is False
    assert "qiskit_aer" not in sys.modules


def backend_request() -> BackendRequest:
    return BackendRequest(
        qasm_text=QASM_TEXT,
        method_id=METHOD_STABILIZER,
        shots=FIXED_SHOTS,
        noise="none",
        seed=5,
        max_wall_seconds=60.0,
        max_memory_bytes=2 * 1024**3,
        cancellation=CooperativeCancellation(),
    )


def test_qiskit_aer_is_absent_in_this_environment() -> None:
    assert importlib.util.find_spec("qiskit_aer") is None


@pytest.mark.skipif(
    importlib.util.find_spec("qiskit_aer") is not None,
    reason="this assertion is about the adapter's behaviour when Aer is genuinely absent",
)
def test_real_lazy_adapter_raises_backend_unavailable_without_aer() -> None:
    with pytest.raises(ExecutorBackendUnavailable) as excinfo:
        aer_stabilizer_backend(backend_request())
    assert excinfo.value.category == "executor_backend_unavailable"
    assert "qiskit_aer" not in sys.modules


def test_simulated_aer_import_failure_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def failing_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "qiskit_aer" or name.startswith("qiskit_aer."):
            raise ImportError("No module named 'qiskit_aer'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    with pytest.raises(ExecutorBackendUnavailable) as excinfo:
        aer_stabilizer_backend(backend_request())
    assert excinfo.value.category == "executor_backend_unavailable"
    assert "qiskit_aer" in str(excinfo.value.detail)


def test_a_simulated_aer_import_failure_flows_through_the_executor(workspace: Path) -> None:
    plan = make_plan()
    authority = make_authority(plan)

    def unavailable_backend(request: BackendRequest) -> BackendSample:
        raise ExecutorBackendUnavailable("No module named 'qiskit_aer'")

    outcome = run(plan, authority, workspace, backend_factory=unavailable_backend)
    assert outcome.status == STATUS_UNSUPPORTED
    assert outcome.category == "executor_backend_unavailable"
    assert outcome.ledger.is_consumed(ATTEMPT_IDENTITY) is True
