from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from qcoder.current_loop_coordinator import CurrentLoopCoordinator


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def artifact_projection(state: dict) -> dict:
    registry = state.get("evidence_registry", {})
    revisions = registry.get("artifact_revisions", {})
    result = {}
    for role, revision_id in sorted(registry.get("role_heads", {}).items()):
        revision = revisions.get(revision_id, {})
        result[role] = {
            "artifact_revision_id": revision_id,
            "content_digest": revision.get("content_digest"),
            "event_disposition": revision.get("event_disposition"),
            "causal_lineage": revision.get("causal_lineage"),
            "strict_result_manifest_binding": revision.get("strict_result_manifest_binding"),
        }
    return result


def summary_projection(state: dict) -> dict:
    result = {}
    for reference, descriptor in sorted(state.get("run_summary_index", {}).items()):
        result[reference] = {
            "currency": descriptor.get("currency"),
            "status": descriptor.get("status"),
        }
    return result


def runtime_projection(workspace: Path) -> dict:
    path = workspace / ".qcoder-client-runtime" / "runtime-identity.json"
    if not path.is_file() or path.is_symlink():
        return {"available": False}
    value = json.loads(path.read_text(encoding="utf-8"))
    return {
        "available": True,
        "identity_sha256": sha256(path.read_bytes()).hexdigest(),
        "schema_id": value.get("schema_id"),
        "versions": value.get("versions"),
        "backend_or_sampler": value.get("backend_or_sampler"),
        "preflight_status": value.get("preflight", {}).get("status"),
        "natural_campaign_execution_count_at_setup": value.get("natural_campaign_execution_count"),
    }


def fixture_projection(workspace: Path) -> dict:
    identity_path = workspace / "fixtures" / "preexisting-identity.json"
    source = workspace / "fixtures" / "preexisting_bell.py"
    if not identity_path.is_file() or not source.is_file():
        return {"available": False}
    before = json.loads(identity_path.read_text(encoding="utf-8"))
    after = source.stat()
    current = {
        "bytes": after.st_size,
        "sha256": sha256(source.read_bytes()).hexdigest(),
        "mtime_ns": after.st_mtime_ns,
        "mode": stat.S_IMODE(after.st_mode),
    }
    return {
        "available": True,
        "identity_unchanged": all(current.get(key) == before.get(key) for key in current),
        "before": {key: before.get(key) for key in current},
        "after": current,
    }


OBSERVATION_VALUES = {"unknown", "not_observed", "aborted", "timeout"}


def observation_count(value: str) -> int | str:
    if value in OBSERVATION_VALUES:
        return value
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("observation count must be nonnegative")
    return parsed


def wall_time(value: str) -> float | str:
    if value in {"unknown", "aborted", "timeout"}:
        return value
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("wall time must be nonnegative")
    return parsed


def pending_projection(state: dict, workspace: Path) -> dict:
    pending = state.get("coordinator", {}).get("pending_completion_checkpoint")
    if not isinstance(pending, dict):
        return {"available": False}
    artifact = pending.get("artifact", {})
    relative = artifact.get("workspace_relative_target")
    target = workspace / relative if isinstance(relative, str) else None
    exact = target is not None and target.is_file() and not target.is_symlink()
    return {
        "available": True,
        "checkpoint_digest": pending.get("checkpoint_digest"),
        "status": pending.get("status"),
        "role": artifact.get("role"),
        "target_identity_sha256": artifact.get("exact_path_sha256"),
        "execution_attempt_identity": pending.get("execution_attempt_identity"),
        "requested_shots": pending.get("requested_shots"),
        "exact_saved_artifact_available": exact,
        "saved_artifact_bytes": target.stat().st_size if exact else None,
        "saved_artifact_sha256": sha256(target.read_bytes()).hexdigest() if exact else None,
        "external_execution_rerun_permitted": pending.get("external_execution_rerun_permitted"),
        "raw_path_retained": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--operator-run-dir", type=Path, required=True)
    parser.add_argument("--wall-seconds", type=wall_time, required=True)
    parser.add_argument("--stage-status", choices=["complete", "aborted", "timeout"], required=True)
    parser.add_argument("--procedure-narration", choices=["yes", "no"], required=True)
    parser.add_argument("--native-process-attempts", type=observation_count, required=True)
    parser.add_argument("--sampler-executions", type=observation_count, required=True)
    parser.add_argument("--dependency-installations", type=observation_count, required=True)
    parser.add_argument("--environment-mutations", type=observation_count, required=True)
    parser.add_argument("--execution-reruns", type=observation_count, required=True)
    parser.add_argument("--qcoder-begin-calls", type=observation_count, required=True)
    parser.add_argument("--qcoder-completion-calls", type=observation_count, required=True)
    parser.add_argument("--completion-retries", type=observation_count, required=True)
    parser.add_argument("--cli-help-invocations", type=observation_count, required=True)
    parser.add_argument("--workspace-discovery-actions", type=observation_count, required=True)
    parser.add_argument("--harness-file-reads", type=observation_count, required=True)
    parser.add_argument("--requested-outcome", required=True)
    parser.add_argument("--final-outcome-observed", choices=["yes", "no"], required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    operator_run_dir = args.operator_run_dir.resolve()
    if (
        workspace == operator_run_dir
        or workspace in operator_run_dir.parents
        or operator_run_dir in workspace.parents
    ):
        raise SystemExit("Operator run directory must remain outside the Cursor workspace.")
    if not operator_run_dir.is_dir() or operator_run_dir.is_symlink():
        raise SystemExit("Operator run directory is missing or unsafe.")
    state = CurrentLoopCoordinator(workspace_root=workspace).store.read()
    coordinator = state.get("coordinator", {})
    output = {
        "schema_id": "qcoder.wi0435.natural_cursor_checkpoint.v5",
        "checkpoint": args.label,
        "stage_status": args.stage_status,
        "customer_visible_wall_seconds": args.wall_seconds,
        "operator_observations": {
            "procedure_narration": args.procedure_narration == "yes",
            "native_process_attempts": args.native_process_attempts,
            "actual_sampler_executions": args.sampler_executions,
            "dependency_installation_actions": args.dependency_installations,
            "environment_mutations": args.environment_mutations,
            "execution_reruns": args.execution_reruns,
            "qcoder_begin_calls": args.qcoder_begin_calls,
            "qcoder_completion_calls": args.qcoder_completion_calls,
            "qcoder_completion_retries": args.completion_retries,
            "qcoder_cli_or_help_invocations": args.cli_help_invocations,
            "target_selection_discovery_actions": args.workspace_discovery_actions,
            "harness_file_reads": args.harness_file_reads,
            "requested_final_outcome": args.requested_outcome,
            "requested_final_outcome_observed": args.final_outcome_observed == "yes",
        },
        "prepared_external_runtime": runtime_projection(workspace),
        "preexisting_fixture": fixture_projection(workspace),
        "pending_completion": pending_projection(state, workspace),
        "state": {
            "phase": state.get("phase"),
            "current_step_status": coordinator.get("current_step_status"),
            "bootstrap_count": coordinator.get("bootstrap_count"),
            "request_baseline_count": coordinator.get("request_baseline_count"),
            "latest_run_summary_reference": state.get("latest_run_summary_reference"),
            "artifact_role_heads": artifact_projection(state),
            "run_summaries": summary_projection(state),
        },
        "raw_artifact_content_retained": False,
        "raw_qcoder_state_retained": False,
        "credential_retained": False,
    }
    destination = operator_run_dir / f"{args.label}.json"
    destination.write_bytes(canonical_bytes(output) + b"\n")
    os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)
    print(destination)


if __name__ == "__main__":
    main()
