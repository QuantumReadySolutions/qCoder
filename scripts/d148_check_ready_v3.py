"""Read-only pending-plan proof; never calls approve, run, training or evaluation."""
import argparse
import hashlib
import json
from pathlib import Path

from qcoder.ml_research import job
from qcoder.ml_research.contracts import read, seal, write_new

ABSENT = ("approval.json", "entered.json", "receipt.json", "result.json", "assessment.json", "readback.json")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--proof", type=Path, required=True)
    args = p.parse_args()
    root = args.workspace
    plan = job.current(root)
    assert all(not (root / name).exists() for name in ABSENT)
    proof = {
        "schema": "d148.pending_human_readable_approval.v3",
        "plan_digest": plan["digest"], "job_id": plan["job_id"], "attempt_id": plan["attempt_id"],
        "internal_challenge": plan["challenge"],
        "source_run_ids": {role: plan["selected"][role]["run_id"] for role in ("candidate", "baseline")},
        "assessment_run_id": plan["assessment_run_id"],
        "experiment_id": plan["tracker"]["experiment_id"], "tracker_digest": plan["tracker"]["digest"],
        "identities": plan["identities"],
        "checkpoint_digests": {role: read(root / (role + "-checkpoint.json"))["digest"] for role in ("candidate", "baseline")},
        "plan_file_sha256": hashlib.sha256((root / "plan.json").read_bytes()).hexdigest(),
        "absent_records": list(ABSENT),
        "accounting": {"research_jobs": 0, "candidate_model_invocations": 0, "baseline_model_invocations": 0,
                       "qnode_invocations": 0, "heldout_examples_processed": 0, "shots": None},
        "accounting_basis": "No approval, entry, receipt or result; durable entered-before-science invariant tested separately on synthetic fixtures. No canonical approval/run/evaluation invoked.",
        "human_prompt": job._approval_summary(plan),
        "disposition": "D148_HUMAN_READABLE_APPROVAL_AND_PROVENANCE_SPLIT_READY__CANONICAL_SCIENCE_ZERO__AWAIT_ROB_APPROVAL",
    }
    write_new(args.proof, seal(proof))


if __name__ == "__main__":
    main()
