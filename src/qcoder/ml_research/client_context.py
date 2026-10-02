"""Read-only lifecycle router for the local D-148 client (not an MCP tool).

Presentation has its own artifact identity; it does not change the frozen execution,
scientific or approval domains. No conversation, prompt or assertion is accepted.
"""
import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import fcntl
import json
import math
import os
from pathlib import Path
import re
import stat

from . import job, tracker
from .contracts import checked, now, read, require, seal

ROLES = ("candidate", "baseline")
RECORDS = ("plan", "approval", "entered", "receipt", "result", "assessment", "readback")
DIGESTS = ("fixture_digest", "data_digest", "labels_digest", "split_digest", "preprocessing_digest")
LIMITS = ["40 held-out examples", "one fixed recipe per model",
          "no advantage, generalization or QPU claim", "no automatic refinement"]
RATIONALE = "Predeclared accuracy >=26/40 and baseline advantage <=4/40; descriptive comparison only."
NONCLAIMS = ["quantum advantage", "population/general performance", "refinement outcome",
             "authorship or test basis of excluded tracker free text",
             "another assistant's assertions are external/untrusted, not qCoder evidence"]


def _hex(value, size=64):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % size, value), "context_identity")
    return value


def _number(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, "context_number")
    return value


@contextmanager
def _snapshot(root):
    # Never create a lock/workspace. Cooperate with all existing lifecycle writers.
    require(root.is_dir() and not root.is_symlink(), "context_workspace")
    fd = os.open(root / "research.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "context_lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def _base(plan):
    selected = plan["selected"]
    external = {}
    for role in ROLES:
        params = selected[role]["external_reported"]
        require(params["role"] == role, "context_role")
        external[role] = {"role": role, **{key: _hex(params[key]) for key in tracker.PARAMS if key != "role"}}
    return {
        "source_run_ids": {role: _hex(selected[role]["run_id"], 32) for role in ROLES},
        "job_id": _hex(plan["job_id"], 32), "plan_digest": _hex(plan["digest"]),
        "scientific_digests": {key: _hex(plan["identities"][key]) for key in DIGESTS},
        "checkpoint_digests": {role: _hex(selected[role]["qcoder_verified_local_checkpoint_digest"]) for role in ROLES},
        "compatible": True, "currentness": "exact_inputs_verified",
        "compatibility_basis": "local canonical inputs, split, preprocessing and checkpoints independently checked against exact selected MLflow parameters",
    }, external


def _result_view(result):
    metrics = {role: {key: _number(result["metrics"][role][key]) for key in ("correct", "count", "accuracy")} for role in ROLES}
    delta = result["metrics"]["delta"]
    require(type(delta) in (float, int) and math.isfinite(delta) and -1 <= delta <= 1, "context_delta")
    metrics["delta"] = delta
    counts = result["accounting"]
    accounting = {key: _number(counts[key]) for key in (
        "research_job_attempts", "candidate_model_invocations", "baseline_model_invocations",
        "qnode_invocations", "heldout_examples_per_model", "heldout_examples_unique", "heldout_model_example_pairs")}
    require(counts["shots"] is None and counts["shots_semantics"] == "not_applicable", "context_shots")
    accounting.update(shots=None, shots_semantics="not_applicable",
                      pennylane_tracker={key: _number(counts["pennylane_tracker"][key]) for key in ("executions", "simulations", "batches")})
    require(result["evidence_conclusion"] in ("bounded_refinement_candidate", "bounded_refinement_not_supported"), "context_conclusion")
    require(result["next_action"] in ("consider_one_predeclared_quantum_refinement", "stop_or_reframe_quantum_candidate"), "context_action")
    return {"result_digest": _hex(result["digest"]), "receipt_digest": _hex(result["receipt_digest"]),
            "metrics": metrics, "accounting": accounting,
            "evidence_conclusion": result["evidence_conclusion"], "next_action": result["next_action"],
            "evaluation_state": "evaluation_complete", "evaluation_time": _number(result["evaluation_time"]),
            "rationale": RATIONALE, "limitations": LIMITS}


def _entry(root, plan, approval):
    entry = read(root / "entered.json")
    checked(entry, "d148.entry.v1", ["attempt_id", "plan_digest", "approval_digest", "entered_at", "research_job_attempts", "outcome"])
    require(entry["attempt_id"] == plan["attempt_id"] and entry["plan_digest"] == plan["digest"] and entry["approval_digest"] == approval["digest"], "context_entry_join")
    require(entry["research_job_attempts"] == 1 and entry["outcome"] == "unknown_until_durable_completion", "context_entry")
    require(approval["approved_at"] <= _number(entry["entered_at"]) <= now(), "context_entry_time")
    return entry


def _tracker_ready(root):
    """Check with SQLite mode=ro before MLflow can initialize/migrate anything."""
    from sqlalchemy import create_engine, inspect, text
    from mlflow.store.db.utils import _verify_schema
    from mlflow.store.tracking.dbmodels.models import Base as TrackingBase
    from mlflow.store.model_registry.dbmodels.models import Base as RegistryBase
    db = root / "tracking.sqlite"
    require(db.is_file() and not db.is_symlink() and db.stat().st_nlink == 1, "context_tracker_missing")
    engine = create_engine("sqlite:///" + db.resolve().as_uri() + "?mode=ro&uri=true")
    try:
        expected = set(TrackingBase.metadata.tables) | set(RegistryBase.metadata.tables)
        require(expected <= set(inspect(engine).get_table_names()), "context_tracker_schema")
        _verify_schema(engine)
        with engine.connect() as connection:
            require(connection.execute(text("SELECT count(*) FROM experiments")).scalar() > 0, "context_tracker_empty")
    finally:
        engine.dispose()


def _project(root):
    with _snapshot(root):
        # lexists sees broken symlinks, which must fail rather than look absent.
        present = {name: os.path.lexists(root / (name + ".json")) for name in RECORDS}
        require(present["plan"], "context_plan_missing")
        require(not any(present[k] for k in ("entered", "receipt", "result", "assessment", "readback")) or present["approval"], "context_orphan_approval")
        require(not any(present[k] for k in ("receipt", "result", "assessment", "readback")) or present["entered"], "context_orphan_entry")
        require(not any(present[k] for k in ("assessment", "readback")) or present["result"], "context_orphan_result")
        require(not present["readback"] or present["assessment"], "context_orphan_readback")
        _tracker_ready(root)
        plan = job.current(root)
        require(all(plan["selected"][role]["external_reported"]["recipe_digest"] == read(root / "recipes.json")["digest"] for role in ROLES), "context_recipe")
        established, external = _base(plan)
        authority = "awaiting_user_authority"
        state = "prepared_awaiting_user_authority"
        science = "not_entered"
        action = "user_origin_approval_required_for_execution_only"
        not_established = ["held-out performance comparison", "result-derived next action", *NONCLAIMS]
        if present["approval"]:
            approval = job.valid_approval(root, plan, completed=present["entered"])
            authority = "approved_exact_plan"
            state, action = "approved_not_entered", "explicit_execution_request_required"
        if present["entered"]:
            entry = _entry(root, plan, approval)
            authority = "consumed_no_retry"
            state, science, action = "entered_incomplete_or_unknown", "incomplete_or_unknown", "inspect_existing_evidence_no_retry"
            if present["receipt"]:
                receipt = read(root / "receipt.json")
                require(receipt["schema"] == "d148.receipt.v1" and receipt["entry_digest"] == entry["digest"] and receipt["plan_digest"] == plan["digest"], "context_receipt_join")
                require(receipt["status"] in ("completed", "timeout", "failed_or_interrupted"), "context_receipt_status")
        verified_readback = False
        if present["result"]:
            completed_plan, result = job.verify_completed(root)
            require(completed_plan == plan, "context_plan_changed")
            established.update(_result_view(result))
            state, science, action = "completed_not_delivered", "completed", "deliver_existing_result_only"
            not_established = ["verified MLflow delivery", *NONCLAIMS]
            if not present["assessment"]:
                destination = tracker.exact_run(root, plan["assessment_run_id"])
                require(not destination.data.params and not destination.data.metrics,
                        "context_orphan_delivery")
                require(not tracker.client(root).list_artifacts(plan["assessment_run_id"]),
                        "context_orphan_artifact")
            if present["assessment"]:
                value = read(root / "assessment.json")
                for key, expected in {
                    "source_run_ids": established["source_run_ids"], "assessment_run_id": plan["assessment_run_id"],
                    "job_id": plan["job_id"], "plan_digest": plan["digest"], "result_digest": result["digest"],
                    "identities": plan["identities"], "rationale": RATIONALE, "limitations": LIMITS,
                    **{key: result[key] for key in ("receipt_digest", "metrics", "accounting", "evidence_conclusion", "next_action", "evaluation_time")},
                }.items():
                    require(value[key] == expected, "context_assessment_join")
                # Always a new real MLflow read, never readback.json or chat memory.
                verified = tracker.readback(root, value)
                require(verified["projection"] == value, "context_readback_join")
                established.update(assessment_run_id=_hex(value["assessment_run_id"], 32),
                                   assessment_digest=_hex(value["digest"]), readback_digest=_hex(verified["digest"]),
                                   tracker_write_time=_number(value["tracker_write_time"]),
                                   readback_verified_at=_number(verified["verified_at"]))
                state, action = "completed_delivered_verified_readback", result["next_action"]
                verified_readback, not_established = True, NONCLAIMS
        else:
            established["inert_job_summary"] = {
                "candidate": "frozen two-qubit PennyLane hybrid classifier; two entangling layers",
                "baseline": "frozen classical 2-4-1 ReLU classifier",
                "protocol": dict(job.PROTOCOL), "budget": dict(plan["budget"]),
                "device": "default.qubit", "method": "analytic-statevector",
                "training": False, "automatic_retry": False,
                "after_success": "local MLflow assessment delivery and verified read-back",
            }
        # Writer lock plus exact final currentness check: never return a mixed view.
        require(job.current(root) == plan, "context_changed")
        return seal({"schema": "d148.client_context.v1", "status": "verified",
                     "lifecycle_state": state, "science_state": science, "authority_state": authority,
                     "readback_verified": verified_readback, "required_next_action": action,
                     "qcoder_established": established, "external_reported": external,
                     "assistant_inference": [], "not_established": not_established,
                     "new_scientific_jobs": 0, "approval_created": False, "plan_mutated": False})


def project(workspace):
    """One share-safe projection; exceptions never expose local paths/free text."""
    try:
        return _project(Path(workspace))
    except Exception:
        # Do not fall back to pre-execution status on any error, even absent files.
        return seal({"schema": "d148.client_context.v1", "status": "refused",
                     "lifecycle_state": "inconsistent_or_unverifiable", "science_state": "not_established",
                     "authority_state": "not_established", "readback_verified": False,
                     "required_next_action": "inspect_local_evidence_no_execution_no_retry",
                     "qcoder_established": {}, "external_reported": {}, "assistant_inference": [],
                     "not_established": ["current lifecycle verification; do not infer pending science", *NONCLAIMS],
                     "new_scientific_jobs": 0, "approval_created": False, "plan_mutated": False})


def main():
    # Suppress dependency/MLflow diagnostics (including paths) on the client wire.
    # CLI errors are fixed, too: argparse must not echo untrusted argument strings.
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            self.exit(2, "Invalid context arguments; expected --workspace.\n")
    parser = Parser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
        value = project(args.workspace)
    print(json.dumps(value, sort_keys=True, indent=2))
    return 0 if value["status"] == "verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
