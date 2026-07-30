"""Single-use operation receipts for exact IDE output registration."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import secrets
from typing import Any, Mapping, Sequence

from qcoder.current_loop_evidence_processing import artifact_format_contract_snapshot

EVENT_RECEIPT_SCHEMA_ID = "qcoder.current_loop.operation_receipt.v3"
EVENT_RECEIPT_SCHEMA_VERSION = 3
LEGACY_EVENT_RECEIPT_SCHEMA_ID = "qcoder.current_loop.operation_receipt.v2"
ACTIVITY_RECEIPT_SCHEMA_ID = "qcoder.current_loop.activity_receipt.v3"
ACTIVITY_RECEIPT_SCHEMA_VERSION = 3
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
) -> dict[str, Any]:
    if operation_category not in SUPPORTED_OPERATION_CATEGORIES:
        raise EventReceiptError("operation_receipt_category_invalid")
    roles = sorted(set(output_role_ceiling))
    if not roles or any(role not in SUPPORTED_OUTPUT_ROLES for role in roles):
        raise EventReceiptError("operation_receipt_role_ceiling_invalid")
    receipt = {
        "schema_id": EVENT_RECEIPT_SCHEMA_ID,
        "schema_version": EVENT_RECEIPT_SCHEMA_VERSION,
        "receipt_id": f"operation-receipt-{secrets.token_hex(16)}",
        "loop_ref": loop_ref,
        "workspace_binding": workspace_binding,
        "issued_state_revision": state_revision,
        "issued_contract_revision": contract_revision,
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
        "authority_effect": {
            "ide_operation_recorded": True,
            "artifact_review_authorized": False,
            "raw_exposure_authorized": False,
        },
    }
    receipt["receipt_digest"] = _digest(receipt)
    return receipt


def validate_operation_receipt(
    receipt: Mapping[str, Any],
    *,
    loop_ref: str,
    workspace_binding: str,
    current_state_revision: int,
    current_contract_revision: int | None = None,
    role: str,
    detected_format: str | None = None,
) -> None:
    if (
        receipt.get("schema_id"),
        receipt.get("schema_version"),
    ) not in {
        (EVENT_RECEIPT_SCHEMA_ID, EVENT_RECEIPT_SCHEMA_VERSION),
        (LEGACY_EVENT_RECEIPT_SCHEMA_ID, 2),
    }:
        raise EventReceiptError("operation_receipt_invalid")
    check = deepcopy(dict(receipt))
    supplied = check.pop("receipt_digest", None)
    if supplied != _digest(check):
        raise EventReceiptError("operation_receipt_digest_mismatch")
    if receipt.get("status") != "issued":
        raise EventReceiptError("operation_receipt_replay_rejected")
    if receipt.get("loop_ref") != loop_ref:
        raise EventReceiptError("operation_receipt_loop_mismatch")
    if receipt.get("workspace_binding") != workspace_binding:
        raise EventReceiptError("operation_receipt_workspace_mismatch")
    issued_revision = receipt.get("issued_state_revision")
    if not isinstance(issued_revision, int) or current_state_revision < issued_revision:
        raise EventReceiptError("operation_receipt_revision_invalid")
    if current_state_revision > issued_revision + 3:
        raise EventReceiptError("operation_receipt_stale")
    issued_contract_revision = receipt.get("issued_contract_revision")
    if (
        issued_contract_revision is not None
        and current_contract_revision is not None
        and issued_contract_revision != current_contract_revision
    ):
        raise EventReceiptError("operation_receipt_contract_stale")
    if role not in receipt.get("authorized_output_role_ceiling", []):
        raise EventReceiptError("operation_receipt_role_not_authorized")
    allowed_formats = receipt.get("authorized_output_format_ceiling", {}).get(role, [])
    if detected_format is not None and detected_format not in allowed_formats:
        raise EventReceiptError("operation_receipt_format_not_authorized")


def consume_operation_receipt(
    receipt: Mapping[str, Any],
    *,
    registered_artifacts: Sequence[Mapping[str, Any]],
    consumed_state_revision: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    updated = deepcopy(dict(receipt))
    if updated.get("status") != "issued":
        raise EventReceiptError("operation_receipt_replay_rejected")
    updated["status"] = "consumed"
    updated["schema_id"] = EVENT_RECEIPT_SCHEMA_ID
    updated["schema_version"] = EVENT_RECEIPT_SCHEMA_VERSION
    updated["consumed_state_revision"] = consumed_state_revision
    updated["registered_artifact_count"] = len(registered_artifacts)
    updated["receipt_digest"] = _digest(
        {key: value for key, value in updated.items() if key != "receipt_digest"}
    )
    activity = {
        "schema_id": ACTIVITY_RECEIPT_SCHEMA_ID,
        "schema_version": ACTIVITY_RECEIPT_SCHEMA_VERSION,
        "activity_status": "successful_canonical_registration",
        "operation_receipt_id": updated["receipt_id"],
        "operation_category": updated["operation_category"],
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
