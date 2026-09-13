"""Bounded local Aer stabilizer executor for ``local_aer_stabilizer_clifford_memory_binding_v1``.

This is not arbitrary Python execution. The only thing this module can do is load one
exact ``.qasm`` artifact from inside an explicitly supplied workspace root, verify that
its recomputed digest equals the digest frozen into a validated inert plan, verify a
separate single-use authority, and hand the text to an injectable backend adapter that
defaults to a lazy local Qiskit/Aer ``stabilizer`` simulation.

It never executes customer ``.py`` files or shell, never calls ``eval``/``exec``/
``compile``/``subprocess``/``importlib`` on customer input, never installs a dependency,
never mutates the environment or any file, never uses a network provider or a cloud
simulator, never broadens the planned method or settings, and never retries.

When ``qiskit_aer`` is not importable the adapter raises a typed
``executor_backend_unavailable`` condition. It is deliberately not replaced by a
substitute simulator: an unavailable dependency is reported, not worked around.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path, PurePosixPath
import time
from typing import Any

from qcoder.focused_loop.authority import (
    AttemptLedger,
    attempt_identity_text,
    validate_execution_authority,
)
from qcoder.focused_loop.canonical import (
    FocusedLoopError,
    bounded_text,
    canonical_digest,
    digest_text,
    strict_float,
)
from qcoder.focused_loop.identities import (
    FIXED_SHOTS,
    METHOD_STABILIZER,
    REGIME_ID,
    RESULT_PROTOCOL_SCHEMA_ID,
)
from qcoder.focused_loop.plan import validate_execution_plan
from qcoder.focused_loop.receipt import (
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    STATUS_UNSUPPORTED,
    build_execution_receipt,
    censored_timing,
    detect_plan_deviation,
    observed_timing,
    unmeasured_resource_observation,
)

EXECUTOR_ID = "qcoder.executors.aer_stabilizer_v1"
ALLOWED_CIRCUIT_SUFFIX = ".qasm"
MAX_QASM_BYTES = 4 * 1024 * 1024
MAX_DISTINCT_OUTCOMES = 1_024


class ExecutorBackendUnavailable(FocusedLoopError):
    """Typed dependency-unavailable condition. Never a silent fallback."""

    def __init__(self, detail: str = "qiskit_aer"):
        super().__init__("executor_backend_unavailable")
        self.detail = detail


def compute_circuit_digest(qasm_text: str) -> str:
    """Digest of the exact QASM text: SHA-256 over its UTF-8 bytes.

    The executor recomputes this over the bytes it actually loaded and compares it to
    the digest frozen in the plan. Filename, path, and adjacency are never evidence.

    This is deliberately the same convention the fixture manifest publishes as the
    circuit artifact digest, so a plan can bind directly to a materialized fixture
    without a second translation step.
    """
    if not isinstance(qasm_text, str) or not qasm_text:
        raise FocusedLoopError("executor_circuit_text_invalid")
    return sha256(qasm_text.encode("utf-8")).hexdigest()


@dataclass
class CooperativeCancellation:
    """Explicit cancellation input. The executor polls it; it is never implicit."""

    requested: bool = False

    def request(self) -> None:
        self.requested = True

    def is_requested(self) -> bool:
        return bool(self.requested)


@dataclass(frozen=True)
class BackendRequest:
    """Exactly what the backend adapter is permitted to see."""

    qasm_text: str
    method_id: str
    shots: int
    noise: str
    seed: int | None
    max_wall_seconds: float
    max_memory_bytes: int
    cancellation: CooperativeCancellation


@dataclass(frozen=True)
class BackendSample:
    """Bounded result data returned by a backend adapter."""

    counts: Mapping[str, int]
    backend_or_sampler: str
    interface: str
    runtime_versions: Mapping[str, str]
    peak_memory_bytes: int | None = None


@dataclass(frozen=True)
class ExecutionOutcome:
    """Typed executor result. ``counts`` is present only for a completed attempt."""

    status: str
    receipt: dict[str, Any]
    ledger: AttemptLedger
    counts: dict[str, int] | None = None
    backend_or_sampler: str | None = None
    interface: str | None = None
    category: str | None = None
    detail: str | None = None

    @property
    def completed(self) -> bool:
        return self.status == STATUS_COMPLETED


@dataclass
class InvocationCounter:
    """Test-visible counter proving that inert or refused paths never dispatch."""

    count: int = 0
    requests: list[BackendRequest] = field(default_factory=list)

    def record(self, request: BackendRequest) -> None:
        self.count += 1
        self.requests.append(request)


def resolve_workspace_qasm_path(workspace_root: str | Path, circuit_path: str) -> Path:
    """Resolve one workspace-relative ``.qasm`` path, refusing every escape."""
    relative = bounded_text(circuit_path, category="executor_circuit_path_invalid")
    pure = PurePosixPath(relative.replace("\\", "/"))
    if pure.is_absolute() or relative.startswith("/") or ":" in pure.parts[0]:
        raise FocusedLoopError("executor_circuit_path_absolute")
    if any(part == ".." for part in pure.parts):
        raise FocusedLoopError("executor_circuit_path_traversal")
    if pure.suffix != ALLOWED_CIRCUIT_SUFFIX:
        raise FocusedLoopError("executor_circuit_path_suffix_unsupported")
    try:
        root = Path(workspace_root).resolve(strict=True)
    except OSError as exc:
        raise FocusedLoopError("executor_workspace_root_invalid") from exc
    if not root.is_dir():
        raise FocusedLoopError("executor_workspace_root_invalid")
    candidate = (root / pure).resolve()
    if not candidate.is_relative_to(root):
        raise FocusedLoopError("executor_circuit_path_escape")
    if not candidate.is_file():
        raise FocusedLoopError("executor_circuit_path_missing")
    return candidate


def load_bound_qasm(workspace_root: str | Path, circuit_path: str) -> str:
    """Read the exact bound QASM text. Read-only; nothing is written or modified."""
    resolved = resolve_workspace_qasm_path(workspace_root, circuit_path)
    try:
        if resolved.stat().st_size > MAX_QASM_BYTES:
            raise FocusedLoopError("executor_circuit_too_large")
        return resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise FocusedLoopError("executor_circuit_unreadable") from exc
    except UnicodeDecodeError as exc:
        raise FocusedLoopError("executor_circuit_unreadable") from exc


def aer_stabilizer_backend(request: BackendRequest) -> BackendSample:
    """Default adapter: local Qiskit/Aer ``stabilizer`` behind a lazy import.

    The import is deliberately inside the function so that plan, authority, path, and
    digest verification all run -- and can be tested -- without the dependency present.
    """
    try:
        import qiskit_aer  # noqa: PLC0415
        from qiskit import QuantumCircuit, __version__ as qiskit_version  # noqa: PLC0415
        from qiskit.qasm2 import loads as qasm2_loads  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - exercised via the fake adapter
        raise ExecutorBackendUnavailable(str(exc)) from exc

    if request.method_id != METHOD_STABILIZER or request.noise != "none":
        raise FocusedLoopError("executor_backend_request_unsupported")
    circuit: Any = qasm2_loads(request.qasm_text)
    if not isinstance(circuit, QuantumCircuit):  # pragma: no cover - defensive
        raise FocusedLoopError("executor_circuit_unreadable")
    simulator = qiskit_aer.AerSimulator(method=METHOD_STABILIZER, noise_model=None)
    job = simulator.run(circuit, shots=request.shots, seed_simulator=request.seed)
    counts = job.result().get_counts()
    return BackendSample(
        counts={str(key).replace(" ", ""): int(value) for key, value in dict(counts).items()},
        backend_or_sampler="aer_simulator_stabilizer",
        interface="qiskit_aer.AerSimulator.run",
        runtime_versions={
            "qiskit": str(qiskit_version),
            "qiskit_aer": str(getattr(qiskit_aer, "__version__", "unknown")),
        },
    )


def _bounded_counts(value: object, *, shots: int) -> dict[str, int]:
    if not isinstance(value, Mapping) or not value or len(value) > MAX_DISTINCT_OUTCOMES:
        raise FocusedLoopError("executor_counts_invalid")
    counts: dict[str, int] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or any(char not in "01" for char in key):
            raise FocusedLoopError("executor_counts_invalid")
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise FocusedLoopError("executor_counts_invalid")
        counts[key] = counts.get(key, 0) + item
    if sum(counts.values()) != shots:
        raise FocusedLoopError("executor_counts_shot_total_mismatch")
    return dict(sorted(counts.items()))


def _failure_outcome(
    *,
    status: str,
    category: str,
    plan: Mapping[str, Any],
    authority: Mapping[str, Any],
    started_at: float | None,
    ledger: AttemptLedger,
    runtime_versions: Mapping[str, str],
    detail: str | None = None,
) -> ExecutionOutcome:
    receipt = build_execution_receipt(
        plan_digest=plan["plan_digest"],
        authority_digest=authority["authority_digest"],
        attempt_identity=authority["attempt_identity"],
        actual_method=plan["method_id"],
        actual_settings={"shots": 0, "noise": plan["settings"]["noise"], "seed": None},
        actual_profile_digest=plan["profile_digest"],
        runtime_versions=runtime_versions,
        timing=censored_timing(started_at=started_at, censor_reason=category),
        resource_observation=unmeasured_resource_observation(),
        status=status,
        deviation={"detected": True, "fields": ["settings.shots"]},
        plan_match_verified_in_process=True,
        result_manifest_digest=None,
    )
    return ExecutionOutcome(
        status=status,
        receipt=receipt,
        ledger=ledger,
        counts=None,
        category=category,
        detail=detail,
    )


def execute_focused_plan(
    *,
    plan: Mapping[str, Any],
    authority: Mapping[str, Any] | None,
    workspace_root: str | Path,
    accepted_circuit_digest: str,
    expected_objective_digest: str,
    expected_profile_digest: str,
    planned_runtime_versions: Mapping[str, Any],
    now: float,
    ledger: AttemptLedger | Iterable[str] | None = None,
    backend_factory: Callable[[BackendRequest], BackendSample] = aer_stabilizer_backend,
    cancellation: CooperativeCancellation | None = None,
    clock: Callable[[], float] = time.monotonic,
    invocation_counter: InvocationCounter | None = None,
) -> ExecutionOutcome:
    """Execute exactly one validated frozen plan, or refuse with a bounded category.

    Every pre-execution requirement is checked before ``backend_factory`` is reachable:
    a refusal therefore guarantees zero backend dispatch. ``backend_factory`` is the
    injectable boundary; it defaults to the real lazy Aer adapter.
    """
    validated_plan = validate_execution_plan(plan)
    if validated_plan["regime_id"] != REGIME_ID:
        raise FocusedLoopError("executor_regime_unsupported")
    if validated_plan["method_id"] != METHOD_STABILIZER:
        raise FocusedLoopError("executor_method_unsupported")
    if validated_plan["settings"]["shots"] != FIXED_SHOTS:
        raise FocusedLoopError("executor_shots_unsupported")
    if validated_plan["settings"]["noise"] != "none":
        raise FocusedLoopError("executor_noise_unsupported")
    if validated_plan["result_protocol_id"] != RESULT_PROTOCOL_SCHEMA_ID:
        raise FocusedLoopError("executor_result_protocol_unsupported")

    if authority is None:
        raise FocusedLoopError("executor_authority_missing")
    validated_authority = validate_execution_authority(
        authority, plan_digest=validated_plan["plan_digest"], now=now
    )

    if validated_plan["objective_digest"] != digest_text(
        expected_objective_digest, category="executor_objective_digest_invalid"
    ):
        raise FocusedLoopError("executor_objective_digest_mismatch")
    if validated_plan["profile_digest"] != digest_text(
        expected_profile_digest, category="executor_profile_digest_invalid"
    ):
        raise FocusedLoopError("executor_profile_digest_mismatch")
    if validated_plan["circuit_digest"] != digest_text(
        accepted_circuit_digest, category="executor_circuit_digest_invalid"
    ):
        raise FocusedLoopError("executor_circuit_binding_stale")

    current_ledger = ledger if isinstance(ledger, AttemptLedger) else AttemptLedger.of(ledger)
    attempt_identity = attempt_identity_text(validated_authority["attempt_identity"])
    current_ledger.require_unconsumed(attempt_identity)

    qasm_text = load_bound_qasm(workspace_root, validated_plan["circuit_path"])
    if compute_circuit_digest(qasm_text) != validated_plan["circuit_digest"]:
        raise FocusedLoopError("executor_loaded_circuit_digest_mismatch")

    token = CooperativeCancellation() if cancellation is None else cancellation
    expected_versions = {
        str(key): str(item) for key, item in dict(planned_runtime_versions).items()
    }
    limit_seconds = strict_float(
        validated_plan["limits"]["max_wall_seconds"],
        category="executor_wall_limit_invalid",
        minimum=0.0,
    )

    # The attempt identity is spent the moment dispatch becomes possible, so a timeout,
    # a cancel, or an unavailable backend can never be retried under the same authority.
    spent_ledger = current_ledger.consume(attempt_identity)

    if token.is_requested():
        return _failure_outcome(
            status=STATUS_CANCELLED,
            category="executor_cancelled_before_dispatch",
            plan=validated_plan,
            authority=validated_authority,
            started_at=None,
            ledger=spent_ledger,
            runtime_versions=expected_versions,
        )

    request = BackendRequest(
        qasm_text=qasm_text,
        method_id=validated_plan["method_id"],
        shots=validated_plan["settings"]["shots"],
        noise=validated_plan["settings"]["noise"],
        seed=validated_plan["settings"]["seed"],
        max_wall_seconds=limit_seconds,
        max_memory_bytes=validated_plan["limits"]["max_memory_bytes"],
        cancellation=token,
    )
    if invocation_counter is not None:
        invocation_counter.record(request)

    started_at = float(clock())
    try:
        sample = backend_factory(request)
    except ExecutorBackendUnavailable as exc:
        return _failure_outcome(
            status=STATUS_UNSUPPORTED,
            category="executor_backend_unavailable",
            plan=validated_plan,
            authority=validated_authority,
            started_at=started_at,
            ledger=spent_ledger,
            runtime_versions=expected_versions,
            detail=exc.detail,
        )
    except FocusedLoopError:
        raise
    except Exception as exc:  # noqa: BLE001 - bounded, typed failure receipt
        return _failure_outcome(
            status=STATUS_FAILED,
            category="executor_backend_failed",
            plan=validated_plan,
            authority=validated_authority,
            started_at=started_at,
            ledger=spent_ledger,
            runtime_versions=expected_versions,
            detail=type(exc).__name__,
        )
    ended_at = float(clock())

    if token.is_requested():
        return _failure_outcome(
            status=STATUS_CANCELLED,
            category="executor_cancelled_during_dispatch",
            plan=validated_plan,
            authority=validated_authority,
            started_at=started_at,
            ledger=spent_ledger,
            runtime_versions=expected_versions,
        )
    if ended_at - started_at > limit_seconds:
        return _failure_outcome(
            status=STATUS_TIMEOUT,
            category="executor_wall_time_exceeded",
            plan=validated_plan,
            authority=validated_authority,
            started_at=started_at,
            ledger=spent_ledger,
            runtime_versions=expected_versions,
        )

    if not isinstance(sample, BackendSample):
        raise FocusedLoopError("executor_backend_sample_invalid")
    counts = _bounded_counts(sample.counts, shots=validated_plan["settings"]["shots"])
    actual_settings = {
        "shots": sum(counts.values()),
        "noise": validated_plan["settings"]["noise"],
        "seed": validated_plan["settings"]["seed"],
    }
    observed_versions = {
        str(key): str(item) for key, item in dict(sample.runtime_versions).items()
    }
    deviation = detect_plan_deviation(
        plan=validated_plan,
        actual_method=validated_plan["method_id"],
        actual_settings=actual_settings,
        actual_profile_digest=validated_plan["profile_digest"],
        runtime_versions=observed_versions,
        planned_runtime_versions=expected_versions,
    )
    resource_observation = (
        unmeasured_resource_observation()
        if sample.peak_memory_bytes is None
        else {"peak_memory_bytes": int(sample.peak_memory_bytes), "below_resolution": False}
    )
    receipt = build_execution_receipt(
        plan_digest=validated_plan["plan_digest"],
        authority_digest=validated_authority["authority_digest"],
        attempt_identity=attempt_identity,
        actual_method=validated_plan["method_id"],
        actual_settings=actual_settings,
        actual_profile_digest=validated_plan["profile_digest"],
        runtime_versions=observed_versions,
        timing=observed_timing(started_at=started_at, ended_at=ended_at),
        resource_observation=resource_observation,
        status=STATUS_COMPLETED,
        deviation=deviation,
        plan_match_verified_in_process=True,
        result_manifest_digest=canonical_digest(
            {"counts": counts, "observed_shots": sum(counts.values())}
        ),
    )
    return ExecutionOutcome(
        status=STATUS_COMPLETED,
        receipt=receipt,
        ledger=spent_ledger,
        counts=counts,
        backend_or_sampler=bounded_text(
            sample.backend_or_sampler, category="executor_backend_sample_invalid"
        ),
        interface=bounded_text(sample.interface, category="executor_backend_sample_invalid"),
        category=None,
    )


__all__ = [
    "ALLOWED_CIRCUIT_SUFFIX",
    "EXECUTOR_ID",
    "BackendRequest",
    "BackendSample",
    "CooperativeCancellation",
    "ExecutionOutcome",
    "ExecutorBackendUnavailable",
    "InvocationCounter",
    "aer_stabilizer_backend",
    "compute_circuit_digest",
    "execute_focused_plan",
    "load_bound_qasm",
    "resolve_workspace_qasm_path",
]
