"""Single-use operation receipts for exact IDE output registration."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
import secrets
import time
from typing import Any, Mapping, Sequence

from qcoder.current_loop_evidence_processing import artifact_format_contract_snapshot

EVENT_RECEIPT_SCHEMA_ID = "qcoder.current_loop.operation_receipt.v5"
EVENT_RECEIPT_SCHEMA_VERSION = 5
ACTIVITY_RECEIPT_SCHEMA_ID = "qcoder.current_loop.activity_receipt.v3"
ACTIVITY_RECEIPT_SCHEMA_VERSION = 3
OPERATION_RECEIPT_LIFETIME_SECONDS = 15 * 60
SUPPORTED_OPERATION_CATEGORIES = ("ide_write", "ide_modify", "ide_execute")
SUPPORTED_OUTPUT_ROLES = ("source", "circuit_qasm", "results")


class EventReceiptError(ValueError):
    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def issue_operation_receipt(
    *,
    loop_ref: str,
    workspace_binding: str,
    state_revision: int,
    contract_revision: int | None = None,
    operation_category: str,
    output_role_ceiling: Sequence[str],
    authority_binding: Mapping[str, Any] | None = None,
    issued_at: float | None = None,
    lifetime_seconds: float = OPERATION_RECEIPT_LIFETIME_SECONDS,
) -> dict[str, Any]:
    if operation_category not in SUPPORTED_OPERATION_CATEGORIES:
        raise EventReceiptError("operation_receipt_category_invalid")
    roles = sorted(set(output_role_ceiling))
    if not roles or any(role not in SUPPORTED_OUTPUT_ROLES for role in roles):
        raise EventReceiptError("operation_receipt_role_ceiling_invalid")
    timestamp = time.monotonic() if issued_at is None else issued_at
    if (
        not isinstance(timestamp, (int, float))
        or isinstance(timestamp, bool)
        or not math.isfinite(float(timestamp))
        or float(timestamp) < 0
        or not isinstance(lifetime_seconds, (int, float))
        or isinstance(lifetime_seconds, bool)
        or not math.isfinite(float(lifetime_seconds))
        or float(lifetime_seconds) <= 0
    ):
        raise EventReceiptError("operation_receipt_expiry_invalid")
    receipt = {
        "schema_id": EVENT_RECEIPT_SCHEMA_ID,
        "schema_version": EVENT_RECEIPT_SCHEMA_VERSION,
        "receipt_id": f"operation-receipt-{secrets.token_hex(16)}",
        "loop_ref": loop_ref,
        "workspace_binding": workspace_binding,
        "issued_state_revision": state_revision,
        "issued_contract_revision": contract_revision,
        "issued_at": float(timestamp),
        "expires_at": float(timestamp) + float(lifetime_seconds),
        "operation_category": operation_category,
        "authorized_output_role_ceiling": roles,
        "authorized_output_format_ceiling": {
            row["role"]: deepcopy(row["accepted_automatic_registration_formats"])
            for row in artifact_format_contract_snapshot()["roles"]
            if row["role"] in roles
        },
        "status": "issued",
        "single_use": True,
        "replay_permitted": False,
        "stale_after_loop_or_workspace_change": True,
        "stale_after_any_authoritative_revision_change": True,
        "authority_binding": deepcopy(dict(authority_binding or {})),
        "authority_effect": {
            "ide_operation_recorded": True,
            "artifact_review_authorized": False,
            "raw_exposure_authorized": False,
        },
    }
    receipt["receipt_digest"] = _digest(receipt)
    return receipt


def _validate_integrity_and_lifecycle(
    receipt: Mapping[str, Any],
    *,
    current_time: float,
) -> None:
    if (
        receipt.get("schema_id") != EVENT_RECEIPT_SCHEMA_ID
        or receipt.get("schema_version") != EVENT_RECEIPT_SCHEMA_VERSION
    ):
        raise EventReceiptError("operation_receipt_invalid")
    check = deepcopy(dict(receipt))
    supplied = check.pop("receipt_digest", None)
    if supplied != _digest(check):
        raise EventReceiptError("operation_receipt_digest_mismatch")
    if receipt.get("status") != "issued":
        raise EventReceiptError("operation_receipt_replay_rejected")
    issued_at = receipt.get("issued_at")
    expires_at = receipt.get("expires_at")
    if (
        not isinstance(current_time, (int, float))
        or isinstance(current_time, bool)
        or not math.isfinite(float(current_time))
        or not isinstance(issued_at, (int, float))
        or isinstance(issued_at, bool)
        or not math.isfinite(float(issued_at))
        or not isinstance(expires_at, (int, float))
        or isinstance(expires_at, bool)
        or not math.isfinite(float(expires_at))
        or float(expires_at) <= float(issued_at)
    ):
        raise EventReceiptError("operation_receipt_expiry_invalid")
    if float(current_time) < float(issued_at):
        raise EventReceiptError("operation_receipt_clock_invalid")
    if float(current_time) >= float(expires_at):
        raise EventReceiptError("operation_receipt_expired")


def validate_operation_receipt_lifecycle(
    receipt: Mapping[str, Any],
    *,
    current_time: float | None = None,
) -> None:
    """Validate stored receipt integrity, status, and monotonic lifetime."""

    _validate_integrity_and_lifecycle(
        receipt,
        current_time=(time.monotonic() if current_time is None else current_time),
    )


def validate_operation_receipt(
    receipt: Mapping[str, Any],
    *,
    loop_ref: str,
    workspace_binding: str,
    current_state_revision: int,
    current_contract_revision: int | None = None,
    role: str,
    detected_format: str | None = None,
    current_time: float | None = None,
) -> None:
    validate_operation_receipt_lifecycle(
        receipt,
        current_time=(time.monotonic() if current_time is None else current_time),
    )
    if receipt.get("loop_ref") != loop_ref:
        raise EventReceiptError("operation_receipt_loop_mismatch")
    if receipt.get("workspace_binding") != workspace_binding:
        raise EventReceiptError("operation_receipt_workspace_mismatch")
    issued_contract_revision = receipt.get("issued_contract_revision")
    if (
        issued_contract_revision is not None
        and current_contract_revision is not None
        and issued_contract_revision != current_contract_revision
    ):
        raise EventReceiptError("operation_receipt_contract_stale")
    issued_revision = receipt.get("issued_state_revision")
    if not isinstance(issued_revision, int) or current_state_revision < issued_revision:
        raise EventReceiptError("operation_receipt_revision_invalid")
    if current_state_revision != issued_revision:
        raise EventReceiptError("operation_receipt_stale")
    if role not in receipt.get("authorized_output_role_ceiling", []):
        raise EventReceiptError("operation_receipt_role_not_authorized")
    allowed_formats = receipt.get("authorized_output_format_ceiling", {}).get(role, [])
    if detected_format is not None and detected_format not in allowed_formats:
        raise EventReceiptError("operation_receipt_format_not_authorized")


def rebind_operation_receipt_for_causal_continuation(
    receipt: Mapping[str, Any],
    *,
    current_state_revision: int,
    current_time: float,
) -> dict[str, Any]:
    """Create an ephemeral same-ID binding for one already-authorized continuation.

    The rebound form is never persisted as an issued receipt. Registration consumes it
    atomically with the exact artifact commit, so recovery cannot create a live successor
    or extend the original expiry.
    """

    validate_operation_receipt_lifecycle(receipt, current_time=current_time)
    if not isinstance(current_state_revision, int) or current_state_revision < 1:
        raise EventReceiptError("operation_receipt_revision_invalid")
    rebound = deepcopy(dict(receipt))
    original_digest = str(receipt["receipt_digest"])
    rebound["issued_state_revision"] = current_state_revision
    rebound["causal_continuation"] = {
        "attempt": 1,
        "original_receipt_digest": original_digest,
        "expiry_extended": False,
        "authority_broadened": False,
    }
    rebound["receipt_digest"] = _digest(
        {key: value for key, value in rebound.items() if key != "receipt_digest"}
    )
    return rebound


def consume_operation_receipt(
    receipt: Mapping[str, Any],
    *,
    registered_artifacts: Sequence[Mapping[str, Any]],
    consumed_state_revision: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if receipt.get("status") != "issued":
        raise EventReceiptError("operation_receipt_replay_rejected")
    updated = {
        "schema_id": EVENT_RECEIPT_SCHEMA_ID,
        "schema_version": EVENT_RECEIPT_SCHEMA_VERSION,
        "receipt_id": receipt.get("receipt_id"),
        "status": "consumed",
        "single_use": True,
        "replay_permitted": False,
        "issued_receipt_digest": receipt.get("receipt_digest"),
        "consumed_state_revision": consumed_state_revision,
        "registered_artifact_count": len(registered_artifacts),
        "authority_binding_digest": _digest(receipt.get("authority_binding", {})),
        "authority_evidence_source": receipt.get("authority_binding", {}).get(
            "authority_evidence_source"
        ),
        "native_client_event_binding_digest": (
            _digest(receipt.get("authority_binding", {}).get("native_client_event_binding"))
            if isinstance(
                receipt.get("authority_binding", {}).get("native_client_event_binding"),
                Mapping,
            )
            else None
        ),
        "causal_continuation_used": isinstance(
            receipt.get("causal_continuation"), Mapping
        ),
    }
    updated["receipt_digest"] = _digest(updated)
    activity = {
        "schema_id": ACTIVITY_RECEIPT_SCHEMA_ID,
        "schema_version": ACTIVITY_RECEIPT_SCHEMA_VERSION,
        "activity_status": "successful_canonical_registration",
        "operation_receipt_id": updated["receipt_id"],
        "operation_category": receipt["operation_category"],
        "registered_artifacts": [
            {
                "role": item["role"],
                "path_digest": _digest({"path": item["path"]}),
                "content_digest": item.get("content_digest"),
                "event_disposition": item.get("event_disposition"),
                "authorization_source": item.get("authorization_source"),
                "enrollment_authority": item.get("enrollment_authority"),
                "artifact_revision_id": item.get("artifact_revision_id"),
                "detected_format": item.get("detected_format"),
            }
            for item in registered_artifacts
        ],
        "directory_scan_performed": False,
        "git_discovery_performed": False,
        "glob_performed": False,
        "watcher_active": False,
        "artifact_review_authorized": False,
    }
    activity["activity_digest"] = _digest(activity)
    return updated, activity


def supersede_operation_receipt(
    receipt: Mapping[str, Any],
    *,
    successor_receipt_id: str,
    superseded_state_revision: int,
) -> dict[str, Any]:
    """Close one issued receipt in favor of a qCoder-owned bounded successor."""

    updated = deepcopy(dict(receipt))
    if updated.get("status") != "issued":
        raise EventReceiptError("operation_receipt_replay_rejected")
    updated["schema_id"] = EVENT_RECEIPT_SCHEMA_ID
    updated["schema_version"] = EVENT_RECEIPT_SCHEMA_VERSION
    updated["status"] = "superseded"
    updated["successor_receipt_id"] = successor_receipt_id
    updated["superseded_state_revision"] = superseded_state_revision
    updated["receipt_digest"] = _digest(
        {key: value for key, value in updated.items() if key != "receipt_digest"}
    )
    return updated


def event_receipt_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": EVENT_RECEIPT_SCHEMA_ID,
        "schema_version": EVENT_RECEIPT_SCHEMA_VERSION,
        "activity_receipt_schema_id": ACTIVITY_RECEIPT_SCHEMA_ID,
        "activity_receipt_schema_version": ACTIVITY_RECEIPT_SCHEMA_VERSION,
        "operation_categories": list(SUPPORTED_OPERATION_CATEGORIES),
        "output_roles": list(SUPPORTED_OUTPUT_ROLES),
        "output_format_ceiling": {
            row["role"]: deepcopy(row["accepted_automatic_registration_formats"])
            for row in artifact_format_contract_snapshot()["roles"]
        },
        "single_use": True,
        "single_use_meaning": "consumed_only_after_successful_canonical_registration_commit",
        "receipt_lifetime_seconds": OPERATION_RECEIPT_LIFETIME_SECONDS,
        "time_expiry_required": True,
        "revision_binding": "exact_authoritative_revision",
        "issuance_commit": "one_compare_and_swap_with_final_post_commit_revision_binding",
        "causal_continuation": {
            "same_receipt_id": True,
            "one_attempt": True,
            "expiry_extended": False,
            "issued_rebound_persisted_before_registration": False,
        },
        "statuses": ["issued", "consumed", "superseded", "invalid", "unavailable"],
        "transaction_escrow_before_commit": True,
        "exact_literal_paths_only": True,
        "directory_scan_performed": False,
        "git_discovery_performed": False,
        "glob_performed": False,
        "watcher_active": False,
    }
    payload["contract_digest"] = _digest(payload)
    return payload
