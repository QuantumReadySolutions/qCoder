"""Inert plan, separate user TTY authority, durable single-use analytic research job."""
from pathlib import Path
import os
import signal
import stat
import time
import uuid

from qcoder.focused_loop.canonical import canonical_digest
from . import FAMILY
from .contracts import checked, file_digest, locked, metric, now, read, reference_metric, require, seal, write_new, conclusion
from .fixture import manifest, partition, selection_data, standardized
from .models import ARCHITECTURES, reconstruct, validate_checkpoint
from .runtime import approval_identity, code_identity, runtime, scientific_identity, scientific_runtime
from . import tracker

INPUT_FILES = ("fixture.json", "train.json", "validation.json", "test.json", "recipes.json", "candidate-checkpoint.json", "baseline-checkpoint.json", "candidate-run.json", "baseline-run.json")
PROTOCOL = {"id": "d148.result.v1", "metric": "accuracy@logit>=0", "heldout_count": 40, "candidate_min_correct": 26, "maximum_baseline_advantage_correct": 4, "shots": None}


def identities(root):
    fixture, train, valid = selection_data(root)
    for role in ("candidate", "baseline"):
        validate_checkpoint(read(Path(root) / f"{role}-checkpoint.json"), role, fixture)
    # Digesting sealed test bytes for identity is not model evaluation or selection.
    test = partition(root, "test", fixture)
    ids = train["ids"] + valid["ids"] + test["ids"]
    require(len(set(ids)) == 200, "split_overlap")
    require(canonical_digest({"train": train["ids"], "validation": valid["ids"], "test": test["ids"]}) == fixture["split_digest"], "split_digest")
    features, labels = [None] * 200, [None] * 200
    for record in (train, valid, test):
        for index, row, label in zip(record["ids"], record["features"], record["labels"], strict=True):
            features[index], labels[index] = row, label
    require(canonical_digest(features) == fixture["data_digest"] and canonical_digest(labels) == fixture["labels_digest"], "dataset_digest")
    return {"fixture_digest": fixture["digest"], "data_digest": fixture["data_digest"], "labels_digest": fixture["labels_digest"], "split_digest": fixture["split_digest"], "preprocessing_digest": fixture["preprocessing"]["digest"], "file_sha256": {name: file_digest(Path(root) / name) for name in INPUT_FILES}, "execution_code": code_identity(), "runtime": runtime(), "scientific_code": scientific_identity(), "scientific_runtime": scientific_runtime(), "approval_surface": approval_identity()}


def prepare(root, candidate_id, baseline_id):
    root = Path(root)
    with locked(root):
        selected = tracker.selected(root, candidate_id, baseline_id)
        inputs = identities(root)
        output = tracker.reserve_assessment(root)
        plan = seal({"schema": "d148.plan.v2", "family": FAMILY, "job_id": uuid.uuid4().hex, "attempt_id": uuid.uuid4().hex, "challenge": uuid.uuid4().hex, "created_at": now(), "selected": selected, "identities": inputs, "architecture": ARCHITECTURES, "evaluator": "qcoder.ml_research.job.evaluate/v1", "protocol": PROTOCOL, "device": "default.qubit", "method": "analytic-statevector", "shots": None, "budget": {"timeout_seconds": 60, "research_jobs": 1, "candidate_model_invocations": 40, "baseline_model_invocations": 40, "qnode_invocations": 40}, "tracker": tracker.configuration(root), "assessment_run_id": output})
        write_new(root / "plan.json", plan)
        return plan


def current(root):
    root = Path(root)
    plan = read(root / "plan.json")
    checked(plan, "d148.plan.v2", ["family", "job_id", "attempt_id", "challenge", "created_at", "selected", "identities", "architecture", "evaluator", "protocol", "device", "method", "shots", "budget", "tracker", "assessment_run_id"])
    require(plan["family"] == FAMILY and plan["architecture"] == ARCHITECTURES and plan["protocol"] == PROTOCOL, "plan_science")
    require(plan["shots"] is None and plan["device"] == "default.qubit" and plan["method"] == "analytic-statevector" and plan["evaluator"] == "qcoder.ml_research.job.evaluate/v1", "plan_evaluator")
    require(plan["budget"] == {"timeout_seconds": 60, "research_jobs": 1, "candidate_model_invocations": 40, "baseline_model_invocations": 40, "qnode_invocations": 40}, "plan_budget")
    require(plan["identities"] == identities(root), "inputs_or_runtime_stale")
    selected = tracker.selected(root, plan["selected"]["candidate"]["run_id"], plan["selected"]["baseline"]["run_id"])
    require(plan["selected"] == selected and plan["tracker"] == tracker.configuration(root), "selected_or_destination_stale")
    require(plan["assessment_run_id"] == read(root / "assessment-run.json")["run_id"], "assessment_id_changed")
    tracker.exact_run(root, plan["assessment_run_id"])
    return plan


def _approval_summary(plan):
    """Consequences come only from a fully validated, exact current plan."""
    return (
        "D-148 frozen-model research evaluation\n"
        "Candidate: frozen two-qubit PennyLane hybrid classifier (two entangling layers).\n"
        "Baseline: frozen classical 2-4-1 ReLU classifier.\n"
        "Candidate MLflow source: " + plan["selected"]["candidate"]["run_id"] + "\n"
        "Baseline MLflow source: " + plan["selected"]["baseline"]["run_id"] + "\n"
        "Evaluate both on the same 40 held-out examples.\n"
        "Local analytic default.qubit; shots not applicable. No training or retraining.\n"
        "Authorize exactly one research-job attempt; no automatic retry.\n"
        "After successful science: local MLflow assessment delivery/read-back.\n"
        "Plan audit digest: " + plan["digest"] + "\n"
        "Approve this exact displayed research job? [y/N] "
    )


def approve(root):
    """No digest/token argument. Never called by run; only the human CLI ceremony.

    Local OS/TTY ownership is the trust boundary, not protection against malicious
    same-UID code that can forge files or synthesize terminal input.
    """
    root = Path(root)
    with locked(root):
        plan = current(root)
        require(not (root / "entered.json").exists(), "attempt_consumed")
        require(not (root / "approval.json").exists(), "approval_already_exists")
        require(os.isatty(0) and os.isatty(1), "interactive_human_tty_required")
        # Buffered text update mode requires seeking and fails on POSIX terminals.
        # Open the existing controlling terminal without acquiring a new one.
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY | os.O_CLOEXEC)
        try:
            require(stat.S_ISCHR(os.fstat(fd).st_mode) and os.isatty(fd), "character_tty_required")
            require(os.tcgetpgrp(fd) == os.getpgrp(), "foreground_tty_required")
            message = _approval_summary(plan).encode("ascii")
            require(len(message) <= 2048, "approval_prompt_too_large")
            offset = 0
            while offset < len(message):
                written = os.write(fd, message[offset:])
                require(written > 0, "approval_prompt_write_failed")
                offset += written
            response = bytearray()
            for _ in range(256):
                part = os.read(fd, 1)
                require(part, "approval_input_eof")
                if part == b"\n":
                    break
                response.extend(part)
            else:
                require(False, "approval_input_too_large")
            require(bytes(response) in (b"y", b"Y"), "deliberate_tty_affirmative_required")
            require(os.tcgetpgrp(fd) == os.getpgrp(), "foreground_tty_required")
            require(current(root) == plan, "plan_changed_during_approval")
            record = seal({"schema": "d148.approval.v2", "origin": "local_foreground_tty_user", "plan_digest": plan["digest"], "job_id": plan["job_id"], "attempt_id": plan["attempt_id"], "event_nonce": uuid.uuid4().hex, "approval_surface_digest": plan["identities"]["approval_surface"]["digest"], "displayed_summary_digest": canonical_digest(_approval_summary(plan)), "decision": "approve", "approved_at": now(), "uid": os.getuid(), "tty": os.ttyname(fd), "confirmation_digest": canonical_digest(response.decode("ascii"))})
            write_new(root / "approval.json", record)
            return record
        finally:
            os.close(fd)


def valid_approval(root, plan, *, completed=False):
    approval = read(Path(root) / "approval.json")
    checked(approval, "d148.approval.v2", ["origin", "plan_digest", "job_id", "attempt_id", "event_nonce", "approval_surface_digest", "displayed_summary_digest", "decision", "approved_at", "uid", "tty", "confirmation_digest"])
    require(approval["origin"] == "local_foreground_tty_user" and approval["uid"] == os.getuid(), "user_origin_required")
    require(approval["plan_digest"] == plan["digest"] and approval["attempt_id"] == plan["attempt_id"] and approval["job_id"] == plan["job_id"], "approval_stale")
    require(isinstance(approval["tty"], str) and approval["tty"].startswith("/dev/"), "approval_tty")
    require(type(approval["approved_at"]) in (float, int) and plan["created_at"] <= approval["approved_at"] <= now(), "approval_time")
    if not completed:
        require(now() - approval["approved_at"] < 86400, "approval_expired")
    require(approval["approval_surface_digest"] == approval_identity()["digest"] == plan["identities"]["approval_surface"]["digest"], "approval_implementation_stale")
    require(approval["displayed_summary_digest"] == canonical_digest(_approval_summary(plan)), "displayed_summary_stale")
    require(approval["decision"] == "approve" and approval["confirmation_digest"] in (canonical_digest("y"), canonical_digest("Y")), "confirmation_mismatch")
    require(isinstance(approval["event_nonce"], str) and len(approval["event_nonce"]) == 32 and all(c in "0123456789abcdef" for c in approval["event_nonce"]), "approval_event_nonce")
    return approval


def evaluate(root, plan):
    import torch
    import pennylane as qml
    fixture = manifest(root)
    test = partition(root, "test", fixture)
    models = {role: reconstruct(read(Path(root) / f"{role}-checkpoint.json"), role, fixture) for role in ("candidate", "baseline")}
    predictions = {"candidate": [], "baseline": []}
    candidate = models["candidate"]
    counts = {"research_job_attempts": 1, "candidate_model_invocations": 0, "baseline_model_invocations": 0, "qnode_invocations": 0, "heldout_examples_per_model": 40, "heldout_examples_unique": 40, "heldout_model_example_pairs": 80, "shots": None, "shots_semantics": "not_applicable"}
    with qml.Tracker(candidate.device) as instrument, torch.no_grad():
        for row in standardized(test, fixture["preprocessing"]):
            for role in ("candidate", "baseline"):
                counts[role + "_model_invocations"] += 1
                logit = models[role](torch.tensor(row, dtype=torch.float64)).item()
                require(torch.isfinite(torch.tensor(logit)).item(), "nonfinite_logit")
                predictions[role].append(int(logit >= 0.0))
    counts["qnode_invocations"] = candidate.qnode_invocations
    # These are real Tracker observations, with PennyLane's own key semantics.
    counts["pennylane_tracker"] = {key: instrument.totals.get(key) for key in ("executions", "simulations", "batches")}
    counts["device_count_provenance"] = "pennylane.Tracker; executions=circuits, simulations=statevector simulations"
    return {"predictions": predictions, "test_ids": test["ids"], "accounting": counts}


def result_from(root, plan, outcome, receipt):
    fixture = manifest(root)
    test = partition(root, "test", fixture)
    require(outcome["test_ids"] == test["ids"], "evaluation_order")
    scores = {role: metric(test["labels"], outcome["predictions"][role]) for role in ("candidate", "baseline")}
    require(all(scores[role]["accuracy"] == reference_metric(test["labels"], outcome["predictions"][role]) for role in scores), "metric_oracle_mismatch")
    scores["delta"] = (scores["candidate"]["correct"] - scores["baseline"]["correct"]) / 40
    require(outcome["accounting"]["research_job_attempts"] == 1 and outcome["accounting"]["candidate_model_invocations"] == 40 and outcome["accounting"]["baseline_model_invocations"] == 40 and outcome["accounting"]["qnode_invocations"] == 40 and outcome["accounting"]["shots"] is None, "evaluation_budget_mismatch")
    return seal({"schema": "d148.result.v1", "plan_digest": plan["digest"], "job_id": plan["job_id"], "attempt_id": plan["attempt_id"], "receipt_digest": receipt["digest"], "metrics": scores, **outcome, **conclusion(scores["candidate"], scores["baseline"]), "compatible": True, "currentness": "exact_inputs_verified", "evaluation_time": receipt["ended_at"]})


def verify_completed(root):
    root = Path(root)
    plan = current(root)
    approval = valid_approval(root, plan, completed=True)
    entry = read(root / "entered.json")
    require(entry["plan_digest"] == plan["digest"] and entry["approval_digest"] == approval["digest"] and entry["attempt_id"] == plan["attempt_id"], "entry_join")
    receipt = read(root / "receipt.json")
    require(receipt["entry_digest"] == entry["digest"] and receipt["status"] == "completed" and receipt["plan_digest"] == plan["digest"], "receipt_join")
    result = read(root / "result.json")
    outcome = {key: result[key] for key in ("predictions", "test_ids", "accounting")}
    require(receipt["outcome_digest"] == canonical_digest(outcome), "outcome_join")
    require(result == result_from(root, plan, outcome, receipt), "result_recomputation")
    return plan, result


def run(root):
    root = Path(root)
    with locked(root):
        if (root / "result.json").exists():
            _, result = verify_completed(root)
            return {"reused": True, "new_research_jobs": 0, "result": result}
        plan = current(root)
        require(not (root / "entered.json").exists(), "attempt_entered_no_retry")
        approval = valid_approval(root, plan)
        entry = seal({"schema": "d148.entry.v1", "attempt_id": plan["attempt_id"], "plan_digest": plan["digest"], "approval_digest": approval["digest"], "entered_at": now(), "research_job_attempts": 1, "outcome": "unknown_until_durable_completion"})
        write_new(root / "entered.json", entry)
        started = time.monotonic()
        old_handler = signal.getsignal(signal.SIGALRM)
        def timeout(signum, frame):
            raise TimeoutError("research_timeout")
        try:
            signal.signal(signal.SIGALRM, timeout)
            signal.setitimer(signal.ITIMER_REAL, plan["budget"]["timeout_seconds"])
            outcome = evaluate(root, plan)
            require(current(root) == plan, "post_evaluation_currentness")
            receipt = seal({"schema": "d148.receipt.v1", "entry_digest": entry["digest"], "plan_digest": plan["digest"], "status": "completed", "outcome_digest": canonical_digest(outcome), "ended_at": now(), "elapsed_seconds": time.monotonic() - started})
            result = result_from(root, plan, outcome, receipt)
            write_new(root / "receipt.json", receipt)
            write_new(root / "result.json", result)
        except BaseException as exc:
            if not (root / "receipt.json").exists():
                write_new(root / "receipt.json", seal({"schema": "d148.receipt.v1", "entry_digest": entry["digest"], "plan_digest": plan["digest"], "status": "timeout" if isinstance(exc, TimeoutError) else "failed_or_interrupted", "error_type": type(exc).__name__, "ended_at": now(), "research_job_attempts": 1, "partial_evaluation_counts": None, "partial_counts_status": "not_established", "retry_permitted": False}))
            raise
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)
        return {"reused": False, "new_research_jobs": 1, "result": result}
