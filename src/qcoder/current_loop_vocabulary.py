"""Canonical bounded vocabulary for one active Explorer Current Loop."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from typing import Any

VOCABULARY_SCHEMA_ID = "qcoder.current_loop.vocabulary.v3"
VOCABULARY_SCHEMA_VERSION = 3

OWNERSHIP = ("qcoder_owned", "assistant_supplied", "customer_authorized")
AUTHORIZATION_SOURCES = (
    "operation_receipt",
    "qcoder_bounded_action_and_client_completion_evidence",
    "direct_customer_selection",
    "current_loop_contract_assist",
)
EVENT_DISPOSITIONS = ("created", "modified", "selected", "restored")
ARTIFACT_REVISION_STATUSES = (
    "registered",
    "derived",
    "excluded",
    "deleted",
    "evicted",
    "unavailable",
)
PROCESSING_OUTCOMES = (
    "pending",
    "completed",
    "failed_local",
    "unsupported_format",
    "excluded",
    "deleted",
)
SNAPSHOT_STATUSES = ("pending_derivation", "complete", "partial", "failed")
FRESHNESS_STATUSES = ("fresh", "stale", "incomplete", "failed", "pending")
CURRENCY_STATUSES = (
    "current",
    "prior",
    "prior_newer_pending",
    "prior_newer_failed",
    "superseded",
)
ERROR_ORIGINS = (
    "local_artifact_validation",
    "local_source_derivation",
    "local_circuit_derivation",
    "local_result_derivation",
    "local_run_summary",
    "hosted_transport",
    "hosted_operation",
    "contract_or_authority",
    "client_environment",
    "unknown_local_internal",
)
def vocabulary_snapshot() -> dict[str, Any]:
    from qcoder.current_loop_recovery import runtime_recovery_action_inventory

    recovery_actions = runtime_recovery_action_inventory()
    payload: dict[str, Any] = {
        "schema_id": VOCABULARY_SCHEMA_ID,
        "schema_version": VOCABULARY_SCHEMA_VERSION,
        "ownership": list(OWNERSHIP),
        "authorization_sources": list(AUTHORIZATION_SOURCES),
        "event_dispositions": list(EVENT_DISPOSITIONS),
        "artifact_revision_statuses": list(ARTIFACT_REVISION_STATUSES),
        "processing_outcomes": list(PROCESSING_OUTCOMES),
        "snapshot_statuses": list(SNAPSHOT_STATUSES),
        "freshness_statuses": list(FRESHNESS_STATUSES),
        "currency_statuses": list(CURRENCY_STATUSES),
        "error_origins": list(ERROR_ORIGINS),
        "recovery_actions": sorted(recovery_actions),
        "recovery_action_inventory_source": (
            "qcoder.current_loop_recovery.runtime_recovery_action_inventory"
        ),
        "category_recovery_policy_source": (
            "qcoder.current_loop_recovery.resolve_live_recovery_policy"
        ),
        "disconnected_category_action_table_present": False,
        "persisted_bare_provenance_field_permitted": False,
    }
    payload["registry_digest"] = sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return deepcopy(payload)
