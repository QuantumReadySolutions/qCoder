"""Bounded retention for immutable evidence inside one active Explorer loop."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from qcoder.current_loop_registration import (
    ROLE_REVISION_LIMIT,
    RUN_SUMMARY_LIMIT,
    SNAPSHOT_LIMIT,
)

RETENTION_SCHEMA_ID = "qcoder.current_loop.evidence_retention.v1"
RETENTION_SCHEMA_VERSION = 1
MINIMUM_COMPLETE_ITERATIONS = 2


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def apply_bounded_retention(
    state: dict[str, Any],
    *,
    deletion_paths: set[Path],
) -> dict[str, int]:
    """Evict only old unreferenced entries; callers delete exact returned paths."""

    registry = state["evidence_registry"]
    snapshots: dict[str, Any] = registry["snapshots"]
    current = registry.get("current_presentation_snapshot_id")
    pending = registry.get("pending_snapshot_id")

    def ordered_ids() -> list[str]:
        return sorted(
            snapshots,
            key=lambda reference: (
                int(snapshots[reference].get("creation_state_revision", 0)),
                reference,
            ),
        )

    evicted_snapshots: list[str] = []

    def evict_snapshot(snapshot_id: str) -> None:
        snapshot = snapshots.pop(snapshot_id)
        evicted_snapshots.append(snapshot_id)
        registry["snapshot_tombstones"].append(
            {
                "snapshot_id": snapshot_id,
                "status": "evicted",
                "content_retained": False,
            }
        )
        for descriptor in snapshot.get("manifestation_revision_set", {}).values():
            if isinstance(descriptor, Mapping) and isinstance(descriptor.get("local_path"), str):
                deletion_paths.add(Path(descriptor["local_path"]))
        summary_ref = snapshot.get("run_summary_reference")
        descriptor = state.get("run_summary_index", {}).pop(summary_ref, None)
        if isinstance(descriptor, Mapping) and isinstance(descriptor.get("local_path"), str):
            deletion_paths.add(Path(descriptor["local_path"]))

    while len(snapshots) > SNAPSHOT_LIMIT:
        candidate = next(
            (reference for reference in ordered_ids() if reference not in {current, pending}),
            None,
        )
        if candidate is None:
            break
        evict_snapshot(candidate)

    while True:
        role_revisions: dict[str, set[str]] = defaultdict(set)
        for snapshot in snapshots.values():
            for role, revision_id in snapshot.get("role_revision_set", {}).items():
                role_revisions[str(role)].add(str(revision_id))
        if all(len(revisions) <= ROLE_REVISION_LIMIT for revisions in role_revisions.values()):
            break
        if len(snapshots) <= MINIMUM_COMPLETE_ITERATIONS:
            break
        candidate = next(
            (reference for reference in ordered_ids() if reference not in {current, pending}),
            None,
        )
        if candidate is None:
            break
        evict_snapshot(candidate)

    summaries = state.get("run_summary_index", {})
    if len(summaries) > RUN_SUMMARY_LIMIT:
        ordered = sorted(
            summaries,
            key=lambda reference: (
                int(summaries[reference].get("creation_revision", 0)),
                reference,
            ),
        )
        retained_summary_refs = {
            snapshot.get("run_summary_reference") for snapshot in snapshots.values()
        }
        for reference in ordered:
            if len(summaries) <= RUN_SUMMARY_LIMIT:
                break
            if reference == state.get("latest_run_summary_reference"):
                continue
            if reference in retained_summary_refs:
                continue
            descriptor = summaries.pop(reference)
            if isinstance(descriptor, Mapping) and isinstance(descriptor.get("local_path"), str):
                deletion_paths.add(Path(descriptor["local_path"]))

    referenced = set(registry.get("role_heads", {}).values())
    for snapshot in snapshots.values():
        referenced.update(snapshot.get("role_revision_set", {}).values())
    removed_revisions = 0
    for revision_id, revision in list(registry["artifact_revisions"].items()):
        if revision_id in referenced:
            continue
        registry["artifact_revisions"].pop(revision_id)
        registry["revision_tombstones"].append(
            {
                "artifact_revision_id": revision_id,
                "logical_role": revision.get("logical_role"),
                "status": "evicted",
                "content_retained": False,
            }
        )
        removed_revisions += 1
    retained_revision_ids = set(registry["artifact_revisions"])
    registry["registration_events"] = [
        event
        for event in registry.get("registration_events", [])
        if event.get("artifact_revision_id") in retained_revision_ids
    ][-64:]
    registry["revision_tombstones"] = registry["revision_tombstones"][-64:]
    registry["snapshot_tombstones"] = registry["snapshot_tombstones"][-32:]
    retained_side_paths = {
        Path(descriptor["local_path"])
        for snapshot in snapshots.values()
        for descriptor in snapshot.get("manifestation_revision_set", {}).values()
        if isinstance(descriptor, Mapping) and isinstance(descriptor.get("local_path"), str)
    }
    retained_side_paths.update(
        Path(descriptor["local_path"])
        for descriptor in state.get("run_summary_index", {}).values()
        if isinstance(descriptor, Mapping) and isinstance(descriptor.get("local_path"), str)
    )
    deletion_paths.difference_update(retained_side_paths)
    return {
        "evicted_snapshots": len(evicted_snapshots),
        "evicted_artifact_revisions": removed_revisions,
        "retained_snapshots": len(snapshots),
        "retained_run_summaries": len(state.get("run_summary_index", {})),
    }


def retention_contract_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": RETENTION_SCHEMA_ID,
        "schema_version": RETENTION_SCHEMA_VERSION,
        "artifact_revisions_per_role_cap": ROLE_REVISION_LIMIT,
        "evidence_snapshot_cap": SNAPSHOT_LIMIT,
        "run_summary_cap": RUN_SUMMARY_LIMIT,
        "minimum_complete_iterations": MINIMUM_COMPLETE_ITERATIONS,
        "current_or_pending_eviction_permitted": False,
        "content_free_tombstones": True,
        "project_artifact_deletion_permitted": False,
    }
    payload["contract_digest"] = _digest(payload)
    return payload
