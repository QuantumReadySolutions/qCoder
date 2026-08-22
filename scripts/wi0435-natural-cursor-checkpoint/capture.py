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
    return {
        reference: {"currency": value.get("currency"), "status": value.get("status")}
        for reference, value in sorted(state.get("run_summary_index", {}).items())
    }


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


def wall_time(value: str) -> float | str:
    if value in {"unknown", "aborted", "timeout"}:
        return value
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("wall time must be nonnegative")
    return parsed


def _read_json_lines(path: Path, *, offset: int) -> tuple[list[dict], int]:
    if not path.exists():
        return [], 0
    if not path.is_file() or path.is_symlink():
        raise SystemExit("Bounded instrumentation log is unsafe.")
    raw = path.read_bytes()
    if offset < 0 or offset > len(raw):
        raise SystemExit("Bounded instrumentation watermark is invalid.")
    values: list[dict] = []
    for line in raw[offset:].splitlines():
        value = json.loads(line.decode("utf-8"))
        if not isinstance(value, dict):
            raise SystemExit("Bounded instrumentation event is invalid.")
        values.append(value)
    return values, len(raw)


def instrumentation_projection(operator_run_dir: Path, state: dict) -> tuple[dict, dict]:
    watermark_path = operator_run_dir / ".capture-watermark.json"
    watermark = (
        json.loads(watermark_path.read_text(encoding="utf-8"))
        if watermark_path.is_file() and not watermark_path.is_symlink()
        else {}
    )
    offsets = watermark.get("offsets", {}) if isinstance(watermark, dict) else {}
    mcp_events, mcp_offset = _read_json_lines(
        operator_run_dir / "mcp-events.jsonl", offset=int(offsets.get("mcp", 0))
    )
    execution_events, execution_offset = _read_json_lines(
        operator_run_dir / "execution-events.jsonl", offset=int(offsets.get("execution", 0))
    )
    prior_ids = set(watermark.get("registration_event_ids", []))
    registry = state.get("evidence_registry", {})
    registrations = registry.get("registration_events", []) if isinstance(registry, dict) else []
    new_registrations = [
        item
        for item in registrations
        if isinstance(item, dict) and item.get("event_id") not in prior_ids
    ]
    private = [item for item in mcp_events if item.get("surface") == "private_current_loop"]
    public = [item for item in mcp_events if item.get("surface") == "public_context_bridge"]
    completions = [item for item in private if item.get("tool") == "complete_current_step"]
    control_evaluations = [
        item
        for item in private
        if item.get("result", {}).get("operation") == "evaluate_selected_result_evidence_controls"
    ]
    starts = [item for item in execution_events if item.get("event") == "execution_started"]
    sampled = [
        item for item in execution_events if item.get("event") == "sampled_execution_completed"
    ]
    projection = {
        "mcp_tool_calls": len(mcp_events),
        "public_context_bridge_calls": len(public),
        "private_current_loop_calls": len(private),
        "qcoder_begin_calls": sum(item.get("tool") == "begin_current_loop" for item in private),
        "qcoder_completion_calls": len(completions),
        "qcoder_completion_rejections": sum(
            item.get("result", {}).get("ok") is not True for item in completions
        ),
        "selected_result_control_evaluations": len(control_evaluations),
        "selected_result_control_paths": sum(
            int(item.get("result", {}).get("selected_artifact_count") or 0)
            for item in control_evaluations
        ),
        "selected_result_control_dispositions": [
            value
            for item in control_evaluations
            for value in item.get("result", {}).get("selected_control_dispositions", [])
        ],
        "selected_result_control_current_result_unchanged": (
            all(
                item.get("result", {}).get("current_result_unchanged") is True
                for item in control_evaluations
            )
            if control_evaluations
            else "not_observed"
        ),
        "canonical_registrations": len(new_registrations),
        "registered_roles": sorted(
            str(item.get("logical_role"))
            for item in new_registrations
            if isinstance(item.get("logical_role"), str)
        ),
        "prepared_execution_process_attempts": len(starts),
        "prepared_sampler_executions": len(sampled),
        "prepared_execution_reruns": max(
            0,
            len(starts) - len({item.get("attempt_identity_sha256") for item in starts}),
        ),
        "dependency_installations": (
            0
            if sampled
            and all(item.get("dependency_installation_performed") is False for item in sampled)
            else "not_observed"
        ),
        "environment_mutations": (
            0
            if sampled and all(item.get("environment_mutated") is False for item in sampled)
            else "not_observed"
        ),
        "other_native_process_attempts": "not_observed",
        "qcoder_cli_or_help_invocations": "not_observed",
        "workspace_target_selection_discovery": "not_observed",
        "harness_file_reads": "not_observed",
    }
    next_watermark = {
        "offsets": {"mcp": mcp_offset, "execution": execution_offset},
        "registration_event_ids": [
            item.get("event_id")
            for item in registrations
            if isinstance(item, dict) and isinstance(item.get("event_id"), str)
        ],
    }
    return projection, next_watermark


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--operator-run-dir", type=Path, required=True)
    parser.add_argument("--wall-seconds", type=wall_time, required=True)
    parser.add_argument("--stage-status", choices=["complete", "aborted", "timeout"], required=True)
    parser.add_argument(
        "--procedure-narration", choices=["yes", "no", "not_observed"], default="not_observed"
    )
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
    instrumentation, next_watermark = instrumentation_projection(operator_run_dir, state)
    output = {
        "schema_id": "qcoder.wi0435.natural_cursor_checkpoint.v7",
        "checkpoint": args.label,
        "stage_status": args.stage_status,
        "customer_visible_wall_seconds": args.wall_seconds,
        "operator_observations": {
            "procedure_narration": (
                args.procedure_narration == "yes"
                if args.procedure_narration in {"yes", "no"}
                else "not_observed"
            ),
            "all_internal_counts_operator_entered": False,
        },
        "bounded_instrumentation": instrumentation,
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
    watermark_path = operator_run_dir / ".capture-watermark.json"
    watermark_path.write_bytes(canonical_bytes(next_watermark) + b"\n")
    os.chmod(watermark_path, stat.S_IRUSR | stat.S_IWUSR)
    print(destination)


if __name__ == "__main__":
    main()
