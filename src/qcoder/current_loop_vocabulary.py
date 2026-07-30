"""Canonical bounded vocabulary for one active Explorer Current Loop."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from typing import Any

VOCABULARY_SCHEMA_ID = "qcoder.current_loop.vocabulary.v1"
VOCABULARY_SCHEMA_VERSION = 1

OWNERSHIP = ("qcoder_owned", "assistant_supplied", "customer_authorized")
AUTHORIZATION_SOURCES = (
    "operation_receipt",
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
RECOVERY_ACTIONS = (
    "retry_registration",
    "correct_exact_candidate",
    "retry_local_derivation",
    "resume_pending_derivation",
    "continue_with_partial_snapshot",
    "exclude_revision",
    "restore_revision",
    "start_fresh_loop",
    "preserve_old_loop",
    "stop_loop",
)

ERROR_RECOVERY_ACTIONS: Mapping[str, tuple[str, ...]] = {
    "artifact_candidate_file_required": ("correct_exact_candidate", "stop_loop"),
    "artifact_candidate_path_invalid": ("correct_exact_candidate", "stop_loop"),
    "artifact_format_unsupported": ("correct_exact_candidate", "stop_loop"),
    "operation_receipt_invalid": ("retry_registration", "stop_loop"),
    "operation_receipt_stale": ("retry_registration", "stop_loop"),
    "operation_receipt_role_not_authorized": (
        "correct_exact_candidate",
        "stop_loop",
    ),
    "registered_pending_derivation": ("resume_pending_derivation", "stop_loop"),
    "local_derivation_failed": (
        "retry_local_derivation",
        "continue_with_partial_snapshot",
        "stop_loop",
    ),
    "run_summary_build_failed": (
        "retry_local_derivation",
        "continue_with_partial_snapshot",
        "stop_loop",
    ),
    "evidence_snapshot_stale": ("retry_local_derivation", "stop_loop"),
    "evidence_revision_excluded": ("restore_revision", "stop_loop"),
    "evidence_revision_deleted": ("stop_loop",),
    "evidence_side_artifact_corrupt": ("retry_local_derivation", "stop_loop"),
    "current_loop_state_migration_requires_fresh_loop": (
        "preserve_old_loop",
        "start_fresh_loop",
        "stop_loop",
    ),
}


def recovery_actions_for(category: str) -> tuple[str, ...]:
    """Return only explicitly registered recovery actions."""

    return ERROR_RECOVERY_ACTIONS.get(category, ("stop_loop",))


def vocabulary_snapshot() -> dict[str, Any]:
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
        "recovery_actions": list(RECOVERY_ACTIONS),
        "error_recovery_actions": {
            category: list(actions) for category, actions in sorted(ERROR_RECOVERY_ACTIONS.items())
        },
        "persisted_bare_provenance_field_permitted": False,
    }
    payload["registry_digest"] = sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return deepcopy(payload)
