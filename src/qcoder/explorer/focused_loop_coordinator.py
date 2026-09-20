"""Conference-only local Explorer composition of the frozen D-143 vertical.

This is not the final production placement. The scientific core and executor remain
independent. Only the accepted result-manifest validator is composed here; no other
workflow state is used. Session digests detect corruption, not a hostile workspace
owner rewriting history. An entered execution boundary is never automatically retried.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path, PurePosixPath
import stat
import time
from uuid import uuid4

from qcoder.current_loop_result_manifest import (
    STRICT_RESULT_MANIFEST_SCHEMA_ID,
    STRICT_RESULT_MANIFEST_SCHEMA_VERSION,
    normalize_strict_result_manifest,
)
from qcoder.executors.aer_stabilizer_v1 import (
    InvocationCounter,
    execute_focused_plan,
    resolve_workspace_qasm_path,
)
from qcoder.focused_loop import applicability, fixtures, identities, result_protocol, reuse
from qcoder.focused_loop.attempt_join import (
    join_attempt_records,
    rebind_receipt_result_manifest_digest,
)
from qcoder.focused_loop.authority import build_execution_authority, validate_execution_authority
from qcoder.focused_loop.canonical import (
    FocusedLoopError,
    canonical_bytes,
    digest_excluding,
    strict_mapping,
    strict_typed_object,
)
from qcoder.focused_loop.contracts import build_execution_profile, build_synthetic_resource_receipt
from qcoder.focused_loop.plan import build_execution_plan

SCHEMA = "qcoder.explorer.focused_session.v1"
STATE_FILE = "session.json"
TOPICS = ("mps", "stabilizer", "shots", "plan", "result", "limits")
UNKNOWN = "execution_in_progress_or_outcome_unknown"
VERSIONS = {"qiskit": "2.5.2", "qiskit_aer": "0.17.2"}
FIELDS = (
    "schema_id",
    "status",
    "prepared",
    "authority",
    "outcome",
    "dispatch_count",
    "dispatch_count_is_exact",
    "session_digest",
)
NON_CLAIMS = (
    "Task-specific parity evidence only: not state or process fidelity, "
    "global-state proof, universal Clifford correctness, general simulator "
    "validation or QPU reliability."
)


def runtime_versions():
    try:
        actual = {"qiskit": version("qiskit"), "qiskit_aer": version("qiskit-aer")}
    except PackageNotFoundError as exc:
        raise FocusedLoopError("focused_runtime_unavailable") from exc
    if actual != VERSIONS:
        raise FocusedLoopError("focused_runtime_unqualified")
    return actual


def _prepared(fixture_id, circuit_path):
    parameters = next(
        (
            p
            for p in (fixtures.PRIMARY_FAMILY_PARAMETERS, fixtures.HELDOUT_FAMILY_PARAMETERS)
            if p.fixture_id == fixture_id
        ),
        None,
    )
    if parameters is None:
        raise FocusedLoopError("focused_fixture_unsupported")
    material = fixtures.materialize_fixture(parameters)
    resource = build_synthetic_resource_receipt(receipt_id="conference-declared-envelope")
    evaluations = applicability.evaluate_regime_methods(
        applicability_prefix=fixture_id,
        coefficient_floor=material["coefficient_floor"],
        safe_envelope_bytes=resource["safe_envelope_bytes"],
    )
    if applicability.selected_method(evaluations) != identities.METHOD_STABILIZER:
        raise FocusedLoopError("focused_method_unsupported")
    profile = build_execution_profile(
        profile_id="local-aer-stabilizer-v1",
        method=identities.METHOD_STABILIZER,
        circuit_family_class="clifford_only",
    )
    plan = build_execution_plan(
        objective_digest=material["objective_digest"],
        circuit_digest=material["qasm_digest"],
        circuit_path=circuit_path,
        profile_digest=profile["record_digest"],
        seed=7,
        max_wall_seconds=60.0,
        max_memory_bytes=2 * 1024**3,
    )
    return dict(
        material=material,
        resource=resource,
        evaluations=evaluations,
        profile=profile,
        plan=plan,
        runtime_versions=dict(VERSIONS),
    )


def _check_circuit(root, prepared):
    path = prepared["plan"]["circuit_path"]
    if ".qcoder" in PurePosixPath(path.replace("\\", "/")).parts:
        raise FocusedLoopError("focused_state_input_forbidden")
    target = resolve_workspace_qasm_path(root, path)
    if ".qcoder" in target.relative_to(root).parts:
        raise FocusedLoopError("focused_state_input_forbidden")
    expected = prepared["material"]["qasm"].encode("utf-8")
    # Exact bytes, including line endings; no filename or digest-only fixture shortcut.
    with target.open("rb") as stream:
        actual = stream.read(len(expected) + 1)
    if actual != expected or sha256(actual).hexdigest() != prepared["plan"]["circuit_digest"]:
        raise FocusedLoopError("focused_circuit_binding_stale")


@contextmanager
def _store(workspace, *, create=False, exclusive=False):
    """Pinned directory descriptors, no symlinks, flock across processes on local POSIX FS.

    The lock file is permanent. Read-only operations never create or rewrite files.
    Workspace owners must not delete/replace this state to recover an unknown attempt.
    """
    root = Path(workspace).resolve(strict=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fds = [os.open(root, flags)]
    lock = None
    try:
        for name in (".qcoder", "focused-loop-v1"):
            if create:
                try:
                    os.mkdir(name, mode=0o700, dir_fd=fds[-1])
                    os.fsync(fds[-1])
                except FileExistsError:
                    pass
            fds.append(os.open(name, flags, dir_fd=fds[-1]))
        lock = os.open(
            "session.lock",
            os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_RDWR | os.O_CREAT if create else os.O_RDONLY),
            0o600,
            dir_fd=fds[-1],
        )
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise FocusedLoopError("focused_state_unsafe")
        fcntl.flock(lock, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        yield root, fds[-1]
    except BlockingIOError as exc:
        raise FocusedLoopError("focused_session_busy") from exc
    finally:
        if lock is not None:
            os.close(lock)
        for fd in reversed(fds):
            os.close(fd)


def _write(fd, session):
    session["session_digest"] = digest_excluding(session, field="session_digest")
    data = canonical_bytes(session) + b"\n"
    name = ".pending-" + uuid4().hex
    out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(out, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, STATE_FILE, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(name, dir_fd=fd)
        except FileNotFoundError:
            pass


def _read(fd):
    file = os.open(STATE_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(file, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise FocusedLoopError("focused_state_unsafe")
        session = strict_typed_object(
            stream.read(256 * 1024 + 1).decode("utf-8"), category="focused_state_invalid"
        )
    strict_mapping(session, required=FIELDS, category="focused_state_invalid")
    if session["schema_id"] != SCHEMA or session["session_digest"] != digest_excluding(
        session, field="session_digest"
    ):
        raise FocusedLoopError("focused_state_digest_mismatch")
    p = session["prepared"]
    expected = _prepared(p["material"]["declared_inputs"]["fixture_id"], p["plan"]["circuit_path"])
    if canonical_bytes(p) != canonical_bytes(expected):
        raise FocusedLoopError("focused_state_preparation_mismatch")
    state = session["status"]
    if state not in ("awaiting_authority", UNKNOWN, "completed", "failed", "unsupported"):
        raise FocusedLoopError("focused_state_invalid")
    if type(session["dispatch_count_is_exact"]) is not bool:
        raise FocusedLoopError("focused_state_invalid")
    count = session["dispatch_count"]
    if count is not None and (type(count) is not int or count not in (0, 1)):
        raise FocusedLoopError("focused_state_invalid")
    if state == "awaiting_authority":
        if session["authority"] is not None or session["outcome"] is not None or count != 0:
            raise FocusedLoopError("focused_state_invalid")
    else:
        # Historical authority validation is at its creation time, not at readback time.
        a = session["authority"]
        validate_execution_authority(
            a, plan_digest=p["plan"]["plan_digest"], now=a["expires_at"] - 600.0
        )
        if state == "completed":
            o = session["outcome"]
            if (
                count != 1
                or not session["dispatch_count_is_exact"]
                or canonical_bytes(o)
                != canonical_bytes(
                    _completed(
                        p, a, o["raw_receipt"], o["counts"], o["backend_or_sampler"], o["interface"]
                    )
                )
            ):
                raise FocusedLoopError("focused_state_result_mismatch")
        elif state == UNKNOWN and session["outcome"] is not None:
            raise FocusedLoopError("focused_state_invalid")
    return session


def _completed(p, authority, raw_receipt, counts, backend, interface):
    """Mechanical v3 projection; validator and generic receipt joins remain unmodified."""
    plan = p["plan"]
    settings = raw_receipt["actual_settings"]
    revision = "focused-exact-circuit-v1"
    payload = {
        "schema_id": STRICT_RESULT_MANIFEST_SCHEMA_ID,
        "schema_version": STRICT_RESULT_MANIFEST_SCHEMA_VERSION,
        "manifestation": "exact_result",
        "counts": counts,
        "requested_shots": plan["settings"]["shots"],
        "observed_shots": sum(counts.values()),
        "circuit_lineage": {
            "status": "exact",
            "artifact_revision_id": revision,
            "content_digest": plan["circuit_digest"],
        },
        "source_lineage": {"status": "not_supplied"},
        "execution_configuration": {
            "status": "exact",
            "reference": p["profile"]["profile_id"],
            "settings": {"backend": backend, "method": raw_receipt["actual_method"], **settings},
        },
        "execution_method": {
            "kind": "sampled_shots",
            "interface": interface,
            "backend_or_sampler": backend,
        },
        "execution_observation": {
            "status": "client_reported_completed",
            "external_execution_attempt_count": 1,
            "dependency_installation_performed": False,
            "environment_mutated": False,
            "qcoder_independently_verified_execution": False,
        },
        "execution_attempt_id": authority["attempt_identity"],
        "producer_provenance": {
            "kind": "native_local_executor",
            "method": interface,
            "identity": plan["plan_digest"],
        },
        "capture_provenance": {
            "kind": "executor_result_object",
            "method": interface,
            "identity": authority["attempt_identity"],
        },
        "bit_register_ordering": {
            "status": "known",
            "convention": "qiskit_little_endian",
            "endianness": "little",
            "bit_order": [f"c[{i}]" for i in range(12)],
            "register_order": ["c"],
        },
        "warnings": [],
        "explicit_missingness": [],
        "limitations": [
            "v3 client-reported observation is separate from the sibling "
            "receipt plan_match_verified_in_process=true."
        ],
        "non_claims": [
            "This manifest does not assert independent qCoder verification of execution."
        ],
        "raw_terminal_or_chat_evidence_used": False,
        "workspace_or_filename_lineage_inferred": False,
    }
    manifest = normalize_strict_result_manifest(
        payload,
        artifact_revisions={
            revision: {"logical_role": "circuit_qasm", "content_digest": plan["circuit_digest"]}
        },
    )
    receipt = rebind_receipt_result_manifest_digest(
        receipt=raw_receipt, result_manifest_digest=manifest["manifest_digest"]
    )
    joined = join_attempt_records(
        plan=plan,
        authority=authority,
        receipt=receipt,
        planned_runtime_versions=p["runtime_versions"],
    )
    config = manifest["execution_configuration"]["settings"]
    if (
        joined["deviation"]["detected"]
        or manifest["execution_attempt_id"] != receipt["attempt_identity"]
        or manifest["circuit_lineage"]["content_digest"] != plan["circuit_digest"]
        or manifest["observed_shots"] != plan["settings"]["shots"]
        or any(config[k] != plan["settings"][k] for k in ("shots", "noise", "seed"))
        or config["method"] != plan["method_id"]
        or manifest["manifest_digest"] != receipt["result_manifest_digest"]
    ):
        raise FocusedLoopError("focused_manifest_join_mismatch")
    joined["joins_verified"] = list(joined["joins_verified"]) + [
        "execution_attempt_id",
        "circuit_digest",
        "observed_shots",
        "execution_configuration_settings",
        "result_manifest_digest",
    ]
    analysis = result_protocol.build_analysis_result(
        analysis_id="focused-analysis", counts=counts, answer_key=p["material"]["answer_key"]
    )
    action = result_protocol.build_next_action(
        action_id="focused-next-action", analysis_result=analysis
    )
    identity = _reuse_identity(p, p["runtime_versions"])
    accepted = dict(
        identity=identity,
        currentness="current",
        result_manifest_digest=manifest["manifest_digest"],
        receipt_digest=receipt["receipt_digest"],
        attempt_identity=authority["attempt_identity"],
    )
    return dict(
        status="completed",
        raw_receipt=raw_receipt,
        counts=counts,
        backend_or_sampler=backend,
        interface=interface,
        receipt=receipt,
        manifest=manifest,
        joined_attempt=joined,
        analysis=analysis,
        next_action=action,
        accepted_result=accepted,
        reuse_identity_digest=reuse.reuse_identity_digest(identity),
    )


def _reuse_identity(p, versions):
    return reuse.build_reuse_identity(
        objective_digest=p["material"]["objective_digest"],
        circuit_digest=p["material"]["qasm_digest"],
        plan_digest=p["plan"]["plan_digest"],
        profile_digest=p["profile"]["record_digest"],
        runtime_versions=versions,
    )


def prepare(workspace, fixture_id, circuit_path):
    p = _prepared(fixture_id, circuit_path)
    runtime_versions()  # pinned availability/qualification before proposing the plan
    root = Path(workspace).resolve(strict=True)
    _check_circuit(root, p)
    with _store(root, create=True, exclusive=True) as (_, fd):
        try:
            os.stat(STATE_FILE, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FocusedLoopError("focused_session_already_exists")
        session = dict(
            schema_id=SCHEMA,
            status="awaiting_authority",
            prepared=p,
            authority=None,
            outcome=None,
            dispatch_count=0,
            dispatch_count_is_exact=True,
        )
        _write(fd, session)
        return session


def run(workspace, confirm_plan_digest, *, _executor_options=None):
    """CLI has no injection controls. Keyword seam supports bounded failure tests only."""
    with _store(workspace, exclusive=True) as (root, fd):
        s = _read(fd)
        p = s["prepared"]
        if not confirm_plan_digest or confirm_plan_digest != p["plan"]["plan_digest"]:
            raise FocusedLoopError("focused_exact_plan_confirmation_required")
        if s["status"] != "awaiting_authority":
            raise FocusedLoopError("focused_attempt_already_entered_no_retry")
        _check_circuit(root, p)
        runtime_versions()
        now = time.time()
        s["authority"] = build_execution_authority(
            plan_digest=confirm_plan_digest,
            attempt_identity="focused-" + uuid4().hex,
            expires_at=now + 600.0,
        )
        s.update(status=UNKNOWN, dispatch_count=None, dispatch_count_is_exact=False)
        _write(fd, s)  # fsync before *any* executor invocation; crash => no retry
        counter = InvocationCounter()
        try:
            outcome = execute_focused_plan(
                plan=p["plan"],
                authority=s["authority"],
                workspace_root=root,
                accepted_circuit_digest=p["material"]["qasm_digest"],
                expected_objective_digest=p["material"]["objective_digest"],
                expected_profile_digest=p["profile"]["record_digest"],
                planned_runtime_versions=p["runtime_versions"],
                now=now,
                invocation_counter=counter,
                **(_executor_options or {}),
            )
            s["dispatch_count"] = counter.count
            s["dispatch_count_is_exact"] = True
            if outcome.completed:
                s["outcome"] = _completed(
                    p,
                    s["authority"],
                    outcome.receipt,
                    outcome.counts,
                    outcome.backend_or_sampler,
                    outcome.interface,
                )
                s["status"] = "completed"
            else:
                s["status"] = "unsupported" if outcome.status == "unsupported" else "failed"
                s["outcome"] = dict(
                    status=outcome.status, category=outcome.category, receipt=outcome.receipt
                )
        except Exception as exc:
            # Never retry, including a conformance/manifest rejection after dispatch.
            s.update(
                status="failed",
                dispatch_count=counter.count,
                dispatch_count_is_exact=True,
                outcome=dict(
                    status="failed", category=getattr(exc, "category", "focused_execution_failed")
                ),
            )
        _write(fd, s)
        return s


def status(workspace):
    with _store(workspace) as (_, fd):
        return _read(fd)


def repeat(workspace):
    with _store(workspace) as (root, fd):
        s = _read(fd)
        if s["status"] != "completed":
            raise FocusedLoopError("focused_completed_result_required")
        _check_circuit(root, s["prepared"])
        decision = reuse.decide_result_reuse(
            request_identity=_reuse_identity(s["prepared"], runtime_versions()),
            accepted_result=s["outcome"]["accepted_result"],
        )
        return dict(
            status=s["status"],
            session_digest=s["session_digest"],
            dispatch_count=s["dispatch_count"],
            **decision,
        )


def explain_session(s, topic):
    p = s["prepared"]
    material = p["material"]
    if topic == "mps":
        return (
            f"Declared natural-order nested-Bell construction: chi_required="
            f"{material['chi_required_claim']['chi_required']}. The coefficient-only exact MPS "
            f"floor is {material['coefficient_floor']['payload_floor_bytes']} bytes, exceeding "
            "the declared synthetic 36 GiB safe envelope, not a measurement of your machine. "
            "This is not a complete Aer peak-memory estimate. Approximate MPS violates exact_required."
        )
    if topic == "stabilizer":
        gates = p["evaluations"][identities.METHOD_STABILIZER]["gates"]
        return (
            "Local Aer stabilizer selected only after availability, qualification, Clifford-family "
            f"applicability, exactness compatibility and result-protocol capability passed: {gates}."
        )
    if topic == "shots":
        below = result_protocol.clopper_pearson_lower_bound(successes=597, trials=597)
        at = result_protocol.clopper_pearson_lower_bound(successes=598, trials=598)
        return (
            f"Fixed 598 noiseless shots. At 597 all-success the lower bound is {below} < 0.995; "
            f"at 598 it is {at}, meeting the target. No adaptive allocation."
        )
    if topic == "plan":
        plan = p["plan"]
        return (
            f"Plan {plan['plan_digest']}: {plan['method_id']}, {plan['settings']}, "
            f"profile {p['profile']['profile_id']}. Inert until explicit exact-digest confirmation. "
            "Nothing executes merely because the plan exists."
        )
    if topic == "result":
        if s["status"] != "completed":
            return "No completed result is available. " + NON_CLAIMS
        a = s["outcome"]["analysis"]
        return (
            f"Executed once locally with Aer stabilizer. {a['satisfying_shots']}/{a['shots_evaluated']} "
            f"shots satisfied the six declared Bell-pair predicates. The one-sided 95% lower bound "
            f"is {a['interval']['lower']:.10f} (exact value {a['interval']['lower']}); target 0.995. "
            f"Conclusion: {a['evidence_conclusion'].replace('_', ' ')}. "
            + (
                "The sampling goal is satisfied; stop. "
                if s["outcome"]["next_action"]["action"] == "stop_goal_met"
                else "No automatic additional shots. "
            )
            + NON_CLAIMS
        )
    if topic == "limits":
        return (
            "One frozen D-143 local ideal-Clifford regime. No remote/QPU/paid execution, "
            "general simulator ranking, general fidelity/runtime claim, adaptive shots or Pro history. "
            "Unknown execution outcomes require recovery or a fresh explicitly authorized attempt "
            "in a separate workspace; never delete state to retry a consumed authority. "
            + NON_CLAIMS
        )
    raise FocusedLoopError("focused_explanation_topic_unsupported")


def explain(workspace, topic):
    s = status(workspace)
    return dict(
        topic=topic,
        text=explain_session(s, topic),
        session_digest=s["session_digest"],
        dispatch_count=s["dispatch_count"],
    )


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise FocusedLoopError("focused_arguments_invalid")


def main(argv=None):
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _Parser(
        prog="qcoder explorer focused", description="Local frozen D-143 focused session."
    )
    sub = parser.add_subparsers(dest="operation", required=True)
    for name in ("prepare", "run", "repeat", "status", "explain"):
        part = sub.add_parser(name)
        part.add_argument("--workspace", required=True)
        part.add_argument("--json", action="store_true")
        if name == "prepare":
            part.add_argument("--fixture", required=True)
            part.add_argument("--qasm", required=True, help="Exact workspace-relative fixture QASM")
        if name == "run":
            part.add_argument("--confirm-plan-digest")
        if name == "explain":
            part.add_argument("topic", choices=TOPICS)
    try:
        args = parser.parse_args(argv)
        if args.operation == "prepare":
            result = prepare(args.workspace, args.fixture, args.qasm)
        elif args.operation == "run":
            result = run(args.workspace, args.confirm_plan_digest)
        elif args.operation == "repeat":
            result = repeat(args.workspace)
        elif args.operation == "explain":
            result = explain(args.workspace, args.topic)
        else:
            result = status(args.workspace)
        if args.json:
            print(json.dumps(result, sort_keys=True, allow_nan=False))
        elif args.operation == "prepare":
            print("Exact result required. " + explain_session(result, "mps"))
            print(
                "Local Aer stabilizer is applicable. Proposed: 598 fixed noiseless shots. Nothing has run yet."
            )
            print(
                "Confirm this exact plan with run --confirm-plan-digest "
                + result["prepared"]["plan"]["plan_digest"]
            )
        elif args.operation == "explain":
            print(result["text"])
        elif args.operation == "repeat":
            print("Reusing the existing result: reuse_existing_result; zero new executions.")
        elif result["status"] == "completed":
            print(explain_session(result, "result"))
            if args.operation == "status":
                print("Result " + result["outcome"]["manifest"]["manifest_digest"])
        elif result["status"] == UNKNOWN:
            print(
                "Execution outcome unknown. No automatic retry; recovery or a fresh explicit attempt is required."
            )
        else:
            print(result["status"])
        return 0 if result.get("status") not in ("failed", "unsupported") else 2
    except (FocusedLoopError, OSError, ValueError, KeyError, TypeError) as exc:
        category = getattr(exc, "category", "focused_state_or_input_invalid")
        error = dict(status="unsupported", category=category, new_execution_attempts_required=0)
        print(json.dumps(error) if "--json" in argv else "Refused: " + category)
        return 2
