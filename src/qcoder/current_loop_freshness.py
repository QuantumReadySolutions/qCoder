"""Computed integrity and currency for active-loop evidence snapshots."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from typing import Any

FRESHNESS_SCHEMA_ID = "qcoder.current_loop.freshness.v2"
FRESHNESS_SCHEMA_VERSION = 2


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def snapshot_status(
    state: Mapping[str, Any],
    *,
    snapshot_id: str,
) -> dict[str, Any]:
    registry = state["evidence_registry"]
    snapshot = registry["snapshots"].get(snapshot_id)
    if not isinstance(snapshot, Mapping):
        raise KeyError("evidence_snapshot_unknown")
    current_id = registry.get("current_presentation_snapshot_id")
    pending_id = registry.get("pending_snapshot_id")
    integrity = (
        "pending"
        if snapshot.get("snapshot_status") == "pending_derivation"
        else "failed"
        if snapshot.get("snapshot_status") == "failed"
        else "incomplete"
        if snapshot.get("snapshot_status") == "partial"
        else "fresh"
    )
    if pending_id is not None and current_id == snapshot_id:
        currency = "prior_newer_pending"
    elif current_id == snapshot_id and any(
        item.get("snapshot_status") == "failed"
        and item.get("creation_state_revision", 0) > snapshot.get("creation_state_revision", 0)
        for item in registry["snapshots"].values()
        if isinstance(item, Mapping)
    ):
        currency = "prior_newer_failed"
    elif snapshot_id == current_id:
        currency = "current"
    else:
        currency = "superseded"
    result = {
        "schema_id": FRESHNESS_SCHEMA_ID,
        "schema_version": FRESHNESS_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "integrity": integrity,
        "currency": currency,
        "registered_role_heads_match": snapshot.get("role_revision_set")
        == registry.get("role_heads"),
        "current_presentation_snapshot_id": current_id,
        "pending_snapshot_id": pending_id,
    }
    result["status_digest"] = _digest(result)
    return result


def run_summary_status(
    state: Mapping[str, Any],
    *,
    summary_reference: str,
) -> dict[str, Any]:
    descriptor = state.get("run_summary_index", {}).get(summary_reference)
    if not isinstance(descriptor, Mapping):
        raise KeyError("run_summary_reference_unknown")
    snapshot_id = descriptor.get("evidence_snapshot_id")
    if not isinstance(snapshot_id, str):
        raise KeyError("run_summary_snapshot_binding_missing")
    computed = snapshot_status(state, snapshot_id=snapshot_id)
    current_summary = state.get("latest_run_summary_reference")
    if summary_reference != current_summary and computed["currency"] == "current":
        computed["currency"] = "superseded"
    computed["summary_reference"] = summary_reference
    computed["is_current_run_summary"] = (
        summary_reference == current_summary
        and computed["currency"] == "current"
        and computed["integrity"] in {"fresh", "incomplete"}
    )
    computed["status_digest"] = _digest(
        {key: deepcopy(value) for key, value in computed.items() if key != "status_digest"}
    )
    return computed


def freshness_contract_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": FRESHNESS_SCHEMA_ID,
        "schema_version": FRESHNESS_SCHEMA_VERSION,
        "stored_freshness_authoritative": False,
        "integrity_and_currency_separate": True,
        "current_summary_requires_current_presentation_snapshot": True,
        "prior_summary_never_presented_as_latest": True,
        "failed_newer_iteration_disclosed": True,
    }
    payload["contract_digest"] = _digest(payload)
    return payload
