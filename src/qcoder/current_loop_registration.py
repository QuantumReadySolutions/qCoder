"""Atomic exact-path registration for the active-loop evidence spine."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from qcoder.current_loop import (
    MAX_LOCAL_FILE_BYTES,
    CurrentLoopError,
    CurrentLoopStore,
)
from qcoder.current_loop_event_receipts import (
    ACTIVITY_RECEIPT_SCHEMA_ID,
    ACTIVITY_RECEIPT_SCHEMA_VERSION,
    consume_operation_receipt,
    validate_operation_receipt,
    validate_operation_receipt_lifecycle,
)
from qcoder.current_loop_evidence_processing import (
    ARTIFACT_FORMAT_CONTRACT_SCHEMA_ID,
    detect_exact_artifact_format,
    registration_format_outcome,
)
from qcoder.current_loop_quiet_workflow import assistant_context_update
from qcoder.current_loop_vocabulary import (
    AUTHORIZATION_SOURCES,
    EVENT_DISPOSITIONS,
)

ARTIFACT_REVISION_SCHEMA_ID = "qcoder.current_loop.artifact_revision.v1"
ARTIFACT_REVISION_SCHEMA_VERSION = 1
EVIDENCE_REGISTRY_SCHEMA_ID = "qcoder.current_loop.evidence_registry.v1"
EVIDENCE_REGISTRY_SCHEMA_VERSION = 1
EVIDENCE_SNAPSHOT_SCHEMA_ID = "qcoder.current_loop.evidence_snapshot.v1"
EVIDENCE_SNAPSHOT_SCHEMA_VERSION = 1
REGISTRATION_TRANSACTION_SCHEMA_ID = "qcoder.current_loop.registration_transaction.v1"
REGISTRATION_TRANSACTION_SCHEMA_VERSION = 1
LOGICAL_ROLES = ("source", "circuit_qasm", "results")
ROLE_REVISION_LIMIT = 5
SNAPSHOT_LIMIT = 5
RUN_SUMMARY_LIMIT = 5

_LEGACY_EVENT_DISPOSITIONS = {
    "assistant_created": "created",
    "assistant_modified": "modified",
    "user_selected": "selected",
    "user_supplied": "selected",
}


def _canonical_digest(value: Any) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def new_evidence_registry() -> dict[str, Any]:
    return {
        "schema_id": EVIDENCE_REGISTRY_SCHEMA_ID,
        "schema_version": EVIDENCE_REGISTRY_SCHEMA_VERSION,
        "artifact_revisions": {},
        "registration_events": [],
        "role_heads": {},
        "snapshots": {},
        "current_presentation_snapshot_id": None,
        "pending_snapshot_id": None,
        "revision_tombstones": [],
        "snapshot_tombstones": [],
        "migration_aliases": {},
        "retention_limits": {
            "artifact_revisions_per_role": ROLE_REVISION_LIMIT,
            "evidence_snapshots": SNAPSHOT_LIMIT,
            "run_summaries": RUN_SUMMARY_LIMIT,
        },
    }


def _event_disposition(candidate: Mapping[str, Any]) -> str:
    explicit = candidate.get("event_disposition")
    if explicit in EVENT_DISPOSITIONS:
        return str(explicit)
    legacy = candidate.get("provenance")
    if legacy in _LEGACY_EVENT_DISPOSITIONS:
        return _LEGACY_EVENT_DISPOSITIONS[str(legacy)]
    raise CurrentLoopError("artifact_event_disposition_invalid")


def _exact_path(
    candidate: Mapping[str, Any],
    *,
    workspace_root: Path,
) -> tuple[Path, bool]:
    path_value = candidate.get("path")
    if not isinstance(path_value, (str, Path)):
        raise CurrentLoopError("artifact_candidate_path_invalid")
    text = str(path_value)
    if any(marker in text for marker in ("*", "?", "[", "]")):
        raise CurrentLoopError("artifact_candidate_discovery_expression_invalid")
    path = Path(path_value).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise CurrentLoopError("artifact_candidate_path_invalid")
    path = path.absolute()
    if ".qcoder" in path.parts:
        raise CurrentLoopError("qcoder_local_state_artifact_prohibited")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CurrentLoopError("artifact_candidate_file_required") from exc
    if path.is_symlink() or not path.is_file():
        raise CurrentLoopError("artifact_candidate_file_required")
    try:
        resolved.relative_to(workspace_root.absolute())
        external = False
    except ValueError:
        external = True
    if external and candidate.get("explicit_external") is not True:
        raise CurrentLoopError("external_artifact_selection_required")
    return path, external


def registration_continuation_binding(
    *,
    candidates: Sequence[Mapping[str, Any]],
    workspace_root: Path,
) -> dict[str, Any]:
    """Seal exact same-action inputs without creating a registration effect."""

    if not candidates:
        raise CurrentLoopError("selected_artifact_set_invalid")
    roles_seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for candidate in candidates:
        role = candidate.get("role")
        if role not in LOGICAL_ROLES or role in roles_seen:
            raise CurrentLoopError("artifact_candidate_role_invalid")
        roles_seen.add(str(role))
        path, external = _exact_path(candidate, workspace_root=workspace_root)
        raw = path.read_bytes()
        if len(raw) > MAX_LOCAL_FILE_BYTES:
            raise CurrentLoopError("artifact_candidate_file_too_large")
        items.append(
            {
                "role": str(role),
                "exact_path": str(path),
                "path_digest": sha256(str(path).encode()).hexdigest(),
                "content_digest": sha256(raw).hexdigest(),
                "size_bytes": len(raw),
                "detected_format": detect_exact_artifact_format(path, str(role)),
                "event_disposition": _event_disposition(candidate),
                "external": external,
                "destination": "active_loop_canonical_evidence_registry",
            }
        )
    items.sort(key=lambda item: item["role"])
    result = {
        "artifact_set": items,
        "artifact_count": len(items),
        "requested_destination": "active_loop_canonical_evidence_registry",
        "directory_scan_performed": False,
        "git_discovery_performed": False,
        "glob_performed": False,
        "watcher_active": False,
    }
    result["binding_digest"] = _canonical_digest(result)
    return result


def prepare_registration_transaction(
    *,
    state: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    workspace_root: Path,
    operation_receipt_id: str | None,
    authorization_source: str,
    enrollment_authority: str,
    collect_permitted_roles: Sequence[str],
    native_action_completion_evidence: Mapping[str, Any] | None = None,
    current_time: float | None = None,
) -> dict[str, Any]:
    """Validate every exact candidate with no durable success effects."""

    if authorization_source not in AUTHORIZATION_SOURCES:
        raise CurrentLoopError("artifact_authorization_source_invalid")
    if not candidates:
        raise CurrentLoopError("selected_artifact_set_invalid")
    if operation_receipt_id is None and authorization_source == "operation_receipt":
        raise CurrentLoopError("operation_receipt_missing")
    receipt = (
        state.get("operation_receipts", {}).get(operation_receipt_id)
        if operation_receipt_id is not None
        else None
    )
    if operation_receipt_id is not None and not isinstance(receipt, Mapping):
        raise CurrentLoopError("operation_receipt_missing")
    safe_completion_evidence: dict[str, Any] | None = None
    if native_action_completion_evidence is not None:
        if not isinstance(native_action_completion_evidence, Mapping):
            raise CurrentLoopError("native_action_completion_evidence_invalid")
        safe_completion_evidence = deepcopy(dict(native_action_completion_evidence))
        if (
            safe_completion_evidence.get("schema_id")
            != "qcoder.current_loop.native_action_completion_evidence.v1"
            or safe_completion_evidence.get("native_client_permission_owned_by_client") is not True
            or safe_completion_evidence.get("native_client_permission_granted_by_qcoder") is not False
            or safe_completion_evidence.get("user_approval_click_inferred") is not False
            or safe_completion_evidence.get("raw_path_retained") is not False
            or safe_completion_evidence.get("raw_source_retained") is not False
            or safe_completion_evidence.get("bounded_action_expectation_id")
            != operation_receipt_id
        ):
            raise CurrentLoopError("native_action_completion_evidence_invalid")
        if (
            not isinstance(receipt, Mapping)
            or receipt.get("receipt_kind") != "qcoder_bounded_action_expectation"
        ):
            raise CurrentLoopError("native_action_completion_evidence_expectation_required")
    registry = state.get("evidence_registry")
    if not isinstance(registry, Mapping):
        raise CurrentLoopError("evidence_registry_missing")
    role_heads = registry.get("role_heads")
    revisions = registry.get("artifact_revisions")
    if not isinstance(role_heads, Mapping) or not isinstance(revisions, Mapping):
        raise CurrentLoopError("evidence_registry_invalid")
    roles_seen: set[str] = set()
    prepared: list[dict[str, Any]] = []
    format_outcomes: list[dict[str, Any]] = []
    validation_time = time.monotonic() if current_time is None else current_time
    for candidate in candidates:
        role = candidate.get("role")
        if role not in LOGICAL_ROLES or role in roles_seen:
            raise CurrentLoopError("artifact_candidate_role_invalid")
        roles_seen.add(str(role))
        if role not in collect_permitted_roles:
            raise CurrentLoopError("current_loop_contract_collection_prohibited")
        path, _external = _exact_path(candidate, workspace_root=workspace_root)
        name = path.name.casefold()
        if operation_receipt_id is not None and any(
            marker in name for marker in (".env", "secret", "credential", "token")
        ):
            raise CurrentLoopError("operation_receipt_sensitive_output_requires_selection")
        raw = path.read_bytes()
        if safe_completion_evidence is not None and (
            safe_completion_evidence.get("artifact_role") != role
            or safe_completion_evidence.get("artifact_cardinality") != "exactly_one"
            or safe_completion_evidence.get("exact_path_sha256")
            != sha256(str(path).encode("utf-8")).hexdigest()
            or safe_completion_evidence.get("artifact_sha256") != sha256(raw).hexdigest()
            or safe_completion_evidence.get("artifact_bytes") != len(raw)
        ):
            raise CurrentLoopError("native_action_completion_evidence_artifact_mismatch")
        if len(raw) > MAX_LOCAL_FILE_BYTES:
            raise CurrentLoopError("artifact_candidate_file_too_large")
        content_digest = sha256(raw).hexdigest()
        expected_content_digest = candidate.get("content_digest")
        if isinstance(expected_content_digest, str) and expected_content_digest != content_digest:
            raise CurrentLoopError("selected_file_stale")
        detected_format = detect_exact_artifact_format(path, str(role))
        format_outcome = registration_format_outcome(
            path=path,
            role=str(role),
            provenance=(
                "assistant_operation_receipt"
                if operation_receipt_id is not None
                else "customer_selected_exact_artifact"
            ),
        )
        format_outcomes.append(format_outcome)
        if (
            operation_receipt_id is not None
            and not format_outcome["automatic_registration_supported"]
        ):
            raise CurrentLoopError(
                "artifact_format_unsupported",
                safe_details={
                    "registration_outcomes": format_outcomes,
                    "operation_receipt_id": operation_receipt_id,
                },
            )
        if isinstance(receipt, Mapping):
            validate_operation_receipt(
                receipt,
                loop_ref=str(state["loop_ref"]),
                workspace_binding=str(state["workspace_root"]),
                current_state_revision=int(state["state_revision"]),
                current_contract_revision=int(state["current_loop_contract"]["contract_revision"]),
                role=str(role),
                detected_format=detected_format,
                current_time=validation_time,
            )
        path_digest = sha256(str(path).encode()).hexdigest()
        revision_id = (
            "artifact-revision-"
            + _canonical_digest(
                {
                    "loop_ref": state["loop_ref"],
                    "role": role,
                    "path_digest": path_digest,
                    "content_digest": content_digest,
                }
            )[:32]
        )
        supplied_event_disposition = _event_disposition(candidate)
        current_id = role_heads.get(role)
        current = revisions.get(current_id) if isinstance(current_id, str) else None
        idempotent = (
            isinstance(current, Mapping)
            and current.get("artifact_revision_id") == revision_id
            and current.get("content_digest") == content_digest
        )
        revision_already_exists = revision_id in revisions
        event_disposition = (
            supplied_event_disposition
            if idempotent
            else "modified"
            if isinstance(current, Mapping) and current.get("exact_path") == str(path)
            else "selected"
            if authorization_source == "direct_customer_selection"
            else "created"
        )
        revision = {
            "schema_id": ARTIFACT_REVISION_SCHEMA_ID,
            "schema_version": ARTIFACT_REVISION_SCHEMA_VERSION,
            "artifact_revision_id": revision_id,
            "logical_role": role,
            "exact_path": str(path),
            "path_digest": path_digest,
            "content_digest": content_digest,
            "size_bytes": len(raw),
            "detected_format": detected_format,
            "format_contract_schema_id": ARTIFACT_FORMAT_CONTRACT_SCHEMA_ID,
            "event_disposition": event_disposition,
            "authorization_source": authorization_source,
            "enrollment_authority": enrollment_authority,
            "operation_receipt_reference": operation_receipt_id,
            "ide_authority_reference": (
                str(receipt.get("receipt_id"))
                if isinstance(receipt, Mapping)
                and receipt.get("receipt_kind") == "explicit_client_authority_record"
                else None
            ),
            "bounded_action_expectation_reference": (
                str(receipt.get("receipt_id"))
                if isinstance(receipt, Mapping)
                and receipt.get("receipt_kind") == "qcoder_bounded_action_expectation"
                else None
            ),
            "native_action_completion_evidence_digest": (
                _canonical_digest(safe_completion_evidence)
                if safe_completion_evidence is not None
                else None
            ),
            "registered_state_revision": int(state["state_revision"]) + 1,
            "loop_ref": state["loop_ref"],
            "workspace_binding": state["workspace_root"],
            "availability": "available",
            "revision_status": "registered",
        }
        if revision["ide_authority_reference"] is None:
            revision.pop("ide_authority_reference")
        if revision["bounded_action_expectation_reference"] is None:
            revision.pop("bounded_action_expectation_reference")
        if revision["native_action_completion_evidence_digest"] is None:
            revision.pop("native_action_completion_evidence_digest")
        prepared.append(
            {
                "revision": revision,
                "idempotent": idempotent,
                "revision_already_exists": revision_already_exists,
                "previous_head": current_id,
            }
        )
    next_heads = deepcopy(dict(role_heads))
    for item in prepared:
        next_heads[item["revision"]["logical_role"]] = item["revision"]["artifact_revision_id"]
    snapshot_id = (
        "evidence-snapshot-"
        + _canonical_digest(
            {
                "loop_ref": state["loop_ref"],
                "role_revision_set": next_heads,
                "contract_revision": state["current_loop_contract"]["contract_revision"],
                "registration_event_binding": (
                    operation_receipt_id
                    if operation_receipt_id is not None
                    else f"direct-selection-state-{state['state_revision']}"
                ),
            }
        )[:32]
    )
    return {
        "schema_id": REGISTRATION_TRANSACTION_SCHEMA_ID,
        "schema_version": REGISTRATION_TRANSACTION_SCHEMA_VERSION,
        "expected_state_revision": state["state_revision"],
        "loop_ref": state["loop_ref"],
        "workspace_binding": state["workspace_root"],
        "operation_receipt_id": operation_receipt_id,
        "authorization_source": authorization_source,
        "enrollment_authority": enrollment_authority,
        "prepared_revisions": prepared,
        "next_role_heads": next_heads,
        "pending_snapshot_id": snapshot_id,
        "format_outcomes": format_outcomes,
        "native_action_completion_evidence": safe_completion_evidence,
        "all_validation_complete": True,
        "durable_success_effects_before_commit": False,
    }


def commit_registration_transaction(
    *,
    store: CurrentLoopStore,
    transaction: Mapping[str, Any],
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Commit revisions, heads, activity, receipt, and pending marker in one CAS."""

    if transaction.get("all_validation_complete") is not True:
        raise CurrentLoopError("registration_transaction_incomplete")
    state = store.read()
    expected = int(transaction["expected_state_revision"])
    if state["state_revision"] != expected:
        raise CurrentLoopError("client_state_conflict")
    receipt_id = transaction.get("operation_receipt_id")
    receipt = (
        state.get("operation_receipts", {}).get(receipt_id) if isinstance(receipt_id, str) else None
    )
    causal_rebind = transaction.get("causal_receipt_rebind")
    receipt_for_consumption = receipt
    if isinstance(causal_rebind, Mapping):
        rebound = causal_rebind.get("rebound_receipt")
        if (
            not isinstance(receipt, Mapping)
            or not isinstance(rebound, Mapping)
            or receipt.get("status") != "issued"
            or receipt.get("receipt_digest")
            != causal_rebind.get("original_receipt_digest")
            or rebound.get("receipt_id") != receipt_id
        ):
            raise CurrentLoopError("operation_receipt_replay_rejected")
        receipt_for_consumption = rebound
    registered = [
        item["revision"]
        for item in transaction["prepared_revisions"]
        if not item["revision_already_exists"]
    ]
    activity_items = [
        {
            "role": item["revision"]["logical_role"],
            "path": item["revision"]["exact_path"],
            "content_digest": item["revision"]["content_digest"],
            "detected_format": item["revision"]["detected_format"],
            "event_disposition": (
                None if item["idempotent"] else item["revision"]["event_disposition"]
            ),
            "authorization_source": item["revision"]["authorization_source"],
            "enrollment_authority": item["revision"]["enrollment_authority"],
            "artifact_revision_id": item["revision"]["artifact_revision_id"],
        }
        for item in transaction["prepared_revisions"]
    ]
    activity: dict[str, Any] | None = None
    if not isinstance(receipt_for_consumption, Mapping):
        activity = {
            "schema_id": ACTIVITY_RECEIPT_SCHEMA_ID,
            "schema_version": ACTIVITY_RECEIPT_SCHEMA_VERSION,
            "activity_status": "successful_canonical_registration",
            "operation_receipt_id": None,
            "operation_category": "direct_customer_selection",
            "registered_artifacts": [
                {
                    "role": item["role"],
                    "path_digest": sha256(item["path"].encode()).hexdigest(),
                    "content_digest": item["content_digest"],
                    "event_disposition": item["event_disposition"],
                    "authorization_source": item["authorization_source"],
                    "enrollment_authority": item["enrollment_authority"],
                    "artifact_revision_id": item["artifact_revision_id"],
                    "detected_format": item["detected_format"],
                }
                for item in activity_items
            ],
            "directory_scan_performed": False,
            "git_discovery_performed": False,
            "glob_performed": False,
            "watcher_active": False,
            "artifact_review_authorized": True,
        }
        activity["activity_digest"] = _canonical_digest(activity)
    existing_current_id = state["evidence_registry"].get("current_presentation_snapshot_id")
    existing_current = state["evidence_registry"].get("snapshots", {}).get(existing_current_id)
    idempotent_current = (
        not registered
        and isinstance(existing_current, Mapping)
        and existing_current.get("role_revision_set") == transaction.get("next_role_heads")
        and existing_current.get("snapshot_status") in {"complete", "partial"}
    )
    snapshot_id = (
        str(existing_current_id) if idempotent_current else str(transaction["pending_snapshot_id"])
    )
    snapshot = {
        "schema_id": EVIDENCE_SNAPSHOT_SCHEMA_ID,
        "schema_version": EVIDENCE_SNAPSHOT_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "role_revision_set": deepcopy(dict(transaction["next_role_heads"])),
        "artifact_revision_digest_bindings": {
            role: state["evidence_registry"]["artifact_revisions"][revision_id]["content_digest"]
            if revision_id in state["evidence_registry"]["artifact_revisions"]
            else next(
                item["revision"]["content_digest"]
                for item in transaction["prepared_revisions"]
                if item["revision"]["artifact_revision_id"] == revision_id
            )
            for role, revision_id in transaction["next_role_heads"].items()
        },
        "manifestation_revision_set": {},
        "run_summary_reference": None,
        "current_build_context": None,
        "assistant_context_update_reference": None,
        "processing_outcomes": {},
        "snapshot_status": "pending_derivation",
        "contract_revision": state["current_loop_contract"]["contract_revision"],
        "derivation_version": "qcoder.current_loop.derivation.v1",
        "creation_state_revision": expected + 1,
    }
    pending_context_update = None
    if not idempotent_current:
        prior_summary_reference = state.get("latest_run_summary_reference")
        pending_context_update = assistant_context_update(
            run_reference=str(prior_summary_reference or "run-summary-unavailable"),
            evidence_references=[],
            backend=None,
            shots=None,
            top_outcomes=[],
            warnings=["Newer exact evidence is registered and pending local derivation."],
            limitations=[
                (
                    "Any prior context remains attributable to its prior snapshot and is "
                    "not the newest iteration's result."
                )
            ],
            circuit_metrics=None,
            freshness="pending",
            contract_revision=int(state["current_loop_contract"]["contract_revision"]),
            evidence_snapshot_id=snapshot_id,
            artifact_revision_references=transaction["next_role_heads"],
            currency="prior_newer_pending",
            newer_iteration_status="pending",
            prior_context_available=prior_summary_reference is not None,
        )

    def mutator(value: dict[str, Any]) -> Mapping[str, Any]:
        nonlocal activity
        consumed: dict[str, Any] | None = None
        if isinstance(receipt_id, str):
            current = value["operation_receipts"].get(receipt_id)
            if not isinstance(current, Mapping):
                raise CurrentLoopError("operation_receipt_replay_rejected")
            commit_time = clock()
            # This lifecycle check executes under CurrentLoopStore.update's CAS
            # lock. It therefore governs the canonical registration
            # linearization point, rather than only transaction preparation.
            validate_operation_receipt_lifecycle(current, current_time=commit_time)
            current_for_consumption: Mapping[str, Any] = current
            if isinstance(causal_rebind, Mapping):
                rebound = causal_rebind.get("rebound_receipt")
                if (
                    not isinstance(rebound, Mapping)
                    or current.get("receipt_digest")
                    != causal_rebind.get("original_receipt_digest")
                    or rebound.get("receipt_id") != receipt_id
                ):
                    raise CurrentLoopError("operation_receipt_replay_rejected")
                validate_operation_receipt_lifecycle(rebound, current_time=commit_time)
                current_for_consumption = rebound
            consumed, activity = consume_operation_receipt(
                current_for_consumption,
                registered_artifacts=activity_items,
                consumed_state_revision=expected + 1,
                native_action_completion_evidence=transaction.get(
                    "native_action_completion_evidence"
                ),
            )
        if not isinstance(activity, Mapping):
            raise CurrentLoopError("registration_activity_receipt_missing")
        registry = value["evidence_registry"]
        if registry.get("role_heads") != state["evidence_registry"].get("role_heads"):
            raise CurrentLoopError("client_state_conflict")
        for revision in registered:
            registry["artifact_revisions"][revision["artifact_revision_id"]] = deepcopy(revision)
        registration_event_ids: dict[str, str] = {}
        for item in transaction["prepared_revisions"]:
            if item["idempotent"]:
                continue
            revision = item["revision"]
            event_id = (
                "artifact-registration-event-"
                + _canonical_digest(
                    {
                        "artifact_revision_id": revision["artifact_revision_id"],
                        "previous_head": item["previous_head"],
                        "event_disposition": revision["event_disposition"],
                        "operation_receipt_id": receipt_id,
                        "state_revision": expected + 1,
                    }
                )[:32]
            )
            registration_event = {
                    "event_id": event_id,
                    "artifact_revision_id": revision["artifact_revision_id"],
                    "logical_role": revision["logical_role"],
                    "previous_head": item["previous_head"],
                    "event_disposition": revision["event_disposition"],
                    "authorization_source": revision["authorization_source"],
                    "operation_receipt_reference": receipt_id,
                    "state_revision": expected + 1,
                }
            if "native_action_completion_evidence_digest" in revision:
                registration_event["native_action_completion_evidence_digest"] = revision[
                    "native_action_completion_evidence_digest"
                ]
            registry["registration_events"].append(registration_event)
            registration_event_ids[str(revision["logical_role"])] = event_id
        registry["registration_events"] = registry["registration_events"][-64:]
        registry["role_heads"] = deepcopy(dict(transaction["next_role_heads"]))
        if not idempotent_current and snapshot_id not in registry["snapshots"]:
            snapshot["role_head_event_references"] = registration_event_ids
            registry["snapshots"][snapshot_id] = deepcopy(snapshot)
        if not idempotent_current:
            registry["pending_snapshot_id"] = snapshot_id
            value["registered_pending_derivation"] = {
                "snapshot_id": snapshot_id,
                "artifact_revision_ids": sorted(transaction["next_role_heads"].values()),
                "registered_state_revision": expected + 1,
            }
            prior_reference = value.get("latest_run_summary_reference")
            if isinstance(prior_reference, str):
                prior_descriptor = value["run_summary_index"].get(prior_reference)
                if isinstance(prior_descriptor, dict):
                    prior_descriptor["currency"] = "prior_newer_pending"
            value["latest_run_summary_reference"] = None
            value["current_evidence_status"] = "pending"
            if isinstance(pending_context_update, Mapping):
                value["assistant_context_updates"].append(deepcopy(pending_context_update))
                value["assistant_context_updates"] = value["assistant_context_updates"][-32:]
                value["latest_assistant_context_update"] = deepcopy(pending_context_update)
        if isinstance(receipt_id, str):
            current = value["operation_receipts"].get(receipt_id)
            if (
                not isinstance(current, Mapping)
                or current.get("status") != "issued"
                or (
                    isinstance(causal_rebind, Mapping)
                    and current.get("receipt_digest")
                    != causal_rebind.get("original_receipt_digest")
                )
            ):
                raise CurrentLoopError("operation_receipt_replay_rejected")
            if not isinstance(consumed, Mapping):
                raise CurrentLoopError("operation_receipt_consumption_missing")
            value["operation_receipts"][receipt_id] = deepcopy(consumed)
        value["activity_receipts"].append(deepcopy(activity))
        return value

    updated = store.update(mutator, expected_revision=expected)
    return {
        "committed": True,
        "state_revision": updated["state_revision"],
        "pending_snapshot_id": None if idempotent_current else snapshot_id,
        "current_snapshot_id": snapshot_id if idempotent_current else None,
        "derivation_required": not idempotent_current,
        "registered_revision_ids": [
            item["revision"]["artifact_revision_id"] for item in transaction["prepared_revisions"]
        ],
        "new_revision_count": len(registered),
        "reused_revision_count": sum(
            1
            for item in transaction["prepared_revisions"]
            if item["revision_already_exists"] and not item["idempotent"]
        ),
        "idempotent_revision_count": len(transaction["prepared_revisions"]) - len(registered),
        "operation_receipt_consumed": isinstance(receipt_id, str),
        "activity_receipt": activity,
        "format_outcomes": deepcopy(list(transaction["format_outcomes"])),
    }


def registration_contract_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": REGISTRATION_TRANSACTION_SCHEMA_ID,
        "schema_version": REGISTRATION_TRANSACTION_SCHEMA_VERSION,
        "artifact_revision_schema_id": ARTIFACT_REVISION_SCHEMA_ID,
        "evidence_registry_schema_id": EVIDENCE_REGISTRY_SCHEMA_ID,
        "evidence_snapshot_schema_id": EVIDENCE_SNAPSHOT_SCHEMA_ID,
        "logical_roles": list(LOGICAL_ROLES),
        "legacy_provenance_is_boundary_only": True,
        "persisted_bare_provenance_field": False,
        "receipt_consumed_only_in_atomic_commit": True,
        "causal_rebind_issued_state_persisted_before_commit": False,
        "causal_rebind_consumed_with_registration_in_same_commit": True,
        "successful_activity_only_in_atomic_commit": True,
        "directory_discovery_permitted": False,
        "git_discovery_permitted": False,
        "glob_permitted": False,
        "watcher_permitted": False,
    }
    payload["contract_digest"] = _canonical_digest(payload)
    return payload


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def artifact_revision_error(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return "current_loop_artifact_revision_invalid"
    if (
        value.get("schema_id") != ARTIFACT_REVISION_SCHEMA_ID
        or value.get("schema_version") != ARTIFACT_REVISION_SCHEMA_VERSION
    ):
        return "current_loop_artifact_revision_schema_invalid"
    if "provenance" in value:
        return "current_loop_artifact_revision_qualified_vocabulary_required"
    revision_id = value.get("artifact_revision_id")
    if not isinstance(revision_id, str) or not revision_id.startswith("artifact-revision-"):
        return "current_loop_artifact_revision_id_invalid"
    if value.get("logical_role") not in LOGICAL_ROLES:
        return "current_loop_artifact_revision_role_invalid"
    if not _digest(value.get("path_digest")) or not _digest(value.get("content_digest")):
        return "current_loop_artifact_revision_digest_invalid"
    if value.get("event_disposition") not in EVENT_DISPOSITIONS:
        return "current_loop_artifact_revision_event_invalid"
    if value.get("authorization_source") not in AUTHORIZATION_SOURCES:
        return "current_loop_artifact_revision_authorization_invalid"
    if value.get("revision_status") not in {
        "registered",
        "derived",
        "excluded",
        "deleted",
        "evicted",
        "unavailable",
    }:
        return "current_loop_artifact_revision_status_invalid"
    if value.get("availability") not in {"available", "excluded", "deleted", "evicted"}:
        return "current_loop_artifact_revision_availability_invalid"
    if not isinstance(value.get("registered_state_revision"), int):
        return "current_loop_artifact_revision_state_binding_invalid"
    return None


def evidence_snapshot_error(value: object, revisions: Mapping[str, Any]) -> str | None:
    if not isinstance(value, Mapping):
        return "current_loop_evidence_snapshot_invalid"
    if (
        value.get("schema_id") != EVIDENCE_SNAPSHOT_SCHEMA_ID
        or value.get("schema_version") != EVIDENCE_SNAPSHOT_SCHEMA_VERSION
    ):
        return "current_loop_evidence_snapshot_schema_invalid"
    snapshot_id = value.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id.startswith("evidence-snapshot-"):
        return "current_loop_evidence_snapshot_id_invalid"
    role_set = value.get("role_revision_set")
    if not isinstance(role_set, Mapping):
        return "current_loop_evidence_snapshot_role_set_invalid"
    for role, revision_id in role_set.items():
        if role not in LOGICAL_ROLES or revision_id not in revisions:
            return "current_loop_evidence_snapshot_revision_invalid"
    digest_bindings = value.get("artifact_revision_digest_bindings")
    if not isinstance(digest_bindings, Mapping):
        return "current_loop_evidence_snapshot_digest_bindings_invalid"
    if set(digest_bindings) != set(role_set):
        return "current_loop_evidence_snapshot_digest_bindings_invalid"
    for role, digest in digest_bindings.items():
        revision = revisions[role_set[role]]
        if digest != revision.get("content_digest"):
            return "current_loop_evidence_snapshot_digest_binding_mismatch"
    if value.get("snapshot_status") not in {
        "pending_derivation",
        "complete",
        "partial",
        "failed",
    }:
        return "current_loop_evidence_snapshot_status_invalid"
    if not isinstance(value.get("manifestation_revision_set"), Mapping):
        return "current_loop_evidence_snapshot_manifestations_invalid"
    if not isinstance(value.get("processing_outcomes"), Mapping):
        return "current_loop_evidence_snapshot_outcomes_invalid"
    return None


def evidence_registry_error(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return "current_loop_evidence_registry_invalid"
    if (
        value.get("schema_id") != EVIDENCE_REGISTRY_SCHEMA_ID
        or value.get("schema_version") != EVIDENCE_REGISTRY_SCHEMA_VERSION
    ):
        return "current_loop_evidence_registry_schema_invalid"
    revisions = value.get("artifact_revisions")
    heads = value.get("role_heads")
    snapshots = value.get("snapshots")
    if not isinstance(revisions, Mapping) or not isinstance(heads, Mapping):
        return "current_loop_evidence_registry_revisions_invalid"
    if not isinstance(snapshots, Mapping):
        return "current_loop_evidence_registry_snapshots_invalid"
    events = value.get("registration_events")
    if not isinstance(events, list):
        return "current_loop_evidence_registration_events_invalid"
    for event in events:
        if not isinstance(event, Mapping):
            return "current_loop_evidence_registration_event_invalid"
        if event.get("artifact_revision_id") not in revisions:
            return "current_loop_evidence_registration_event_revision_invalid"
        if event.get("event_disposition") not in EVENT_DISPOSITIONS:
            return "current_loop_evidence_registration_event_disposition_invalid"
        if event.get("authorization_source") not in AUTHORIZATION_SOURCES:
            return "current_loop_evidence_registration_event_authorization_invalid"
    for revision_id, revision in revisions.items():
        if revision_id != (
            revision.get("artifact_revision_id") if isinstance(revision, Mapping) else None
        ):
            return "current_loop_artifact_revision_key_invalid"
        error = artifact_revision_error(revision)
        if error:
            return error
    for role, revision_id in heads.items():
        if role not in LOGICAL_ROLES or revision_id not in revisions:
            return "current_loop_evidence_role_head_invalid"
    for snapshot_id, snapshot in snapshots.items():
        if snapshot_id != (snapshot.get("snapshot_id") if isinstance(snapshot, Mapping) else None):
            return "current_loop_evidence_snapshot_key_invalid"
        error = evidence_snapshot_error(snapshot, revisions)
        if error:
            return error
    for pointer in ("current_presentation_snapshot_id", "pending_snapshot_id"):
        reference = value.get(pointer)
        if reference is not None and reference not in snapshots:
            return "current_loop_evidence_snapshot_pointer_invalid"
    limits = value.get("retention_limits")
    if not isinstance(limits, Mapping):
        return "current_loop_evidence_retention_limits_invalid"
    if limits.get("artifact_revisions_per_role") != ROLE_REVISION_LIMIT:
        return "current_loop_evidence_retention_limits_invalid"
    if limits.get("evidence_snapshots") != SNAPSHOT_LIMIT:
        return "current_loop_evidence_retention_limits_invalid"
    if limits.get("run_summaries") != RUN_SUMMARY_LIMIT:
        return "current_loop_evidence_retention_limits_invalid"
    for key in ("revision_tombstones", "snapshot_tombstones"):
        if not isinstance(value.get(key), list):
            return "current_loop_evidence_tombstones_invalid"
    if not isinstance(value.get("migration_aliases"), Mapping):
        return "current_loop_evidence_migration_aliases_invalid"
    return None


def migrate_v8_evidence_registry(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build a v9 registry from exact v8 candidates without file discovery."""

    registry = new_evidence_registry()
    coordinator = state.get("coordinator")
    candidates = (
        coordinator.get("artifact_candidates", []) if isinstance(coordinator, Mapping) else []
    )
    saved = state.get("saved_artifacts")
    manifestation_roles = {
        "python_manifestation",
        "source_evidence",
        "circuit_manifestation",
        "result_manifestation",
    }
    has_manifestations = isinstance(saved, Mapping) and any(
        role in saved for role in manifestation_roles
    )
    if has_manifestations and not candidates:
        raise CurrentLoopError("v8_manifestation_without_registered_candidate")
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise CurrentLoopError("v8_artifact_candidate_invalid")
        role = candidate.get("role")
        if role not in LOGICAL_ROLES:
            continue
        path, _external = _exact_path(candidate, workspace_root=Path(str(state["workspace_root"])))
        raw = path.read_bytes()
        content_digest = sha256(raw).hexdigest()
        old_digest = candidate.get("content_digest")
        if old_digest is not None and old_digest != content_digest:
            raise CurrentLoopError("v8_artifact_candidate_digest_mismatch")
        path_digest = sha256(str(path).encode()).hexdigest()
        revision_id = (
            "artifact-revision-"
            + _canonical_digest(
                {
                    "loop_ref": state["loop_ref"],
                    "role": role,
                    "path_digest": path_digest,
                    "content_digest": content_digest,
                }
            )[:32]
        )
        receipt = candidate.get("operation_receipt_id")
        revision = {
            "schema_id": ARTIFACT_REVISION_SCHEMA_ID,
            "schema_version": ARTIFACT_REVISION_SCHEMA_VERSION,
            "artifact_revision_id": revision_id,
            "logical_role": role,
            "exact_path": str(path),
            "path_digest": path_digest,
            "content_digest": content_digest,
            "size_bytes": len(raw),
            "detected_format": detect_exact_artifact_format(path, str(role)),
            "format_contract_schema_id": ARTIFACT_FORMAT_CONTRACT_SCHEMA_ID,
            "event_disposition": _event_disposition(candidate),
            "authorization_source": (
                "operation_receipt" if isinstance(receipt, str) else "direct_customer_selection"
            ),
            "enrollment_authority": (
                "current_loop_contract_assist"
                if isinstance(receipt, str)
                else "direct_customer_selection"
            ),
            "operation_receipt_reference": receipt,
            "ide_authority_reference": receipt,
            "registered_state_revision": int(state["state_revision"]),
            "loop_ref": state["loop_ref"],
            "workspace_binding": state["workspace_root"],
            "availability": "available",
            "revision_status": "derived" if has_manifestations else "registered",
        }
        registry["artifact_revisions"][revision_id] = revision
        registry["role_heads"][str(role)] = revision_id
        registry["migration_aliases"][path_digest] = revision_id
    current_snapshot_id = None
    if registry["role_heads"]:
        current_snapshot_id = (
            "evidence-snapshot-"
            + _canonical_digest(
                {
                    "loop_ref": state["loop_ref"],
                    "role_revision_set": registry["role_heads"],
                    "migration": "v8_to_v9",
                }
            )[:32]
        )
        manifestations = {}
        if isinstance(saved, Mapping):
            for role in sorted(manifestation_roles):
                descriptor = saved.get(role)
                if isinstance(descriptor, Mapping):
                    manifestations[role] = deepcopy(dict(descriptor))
        summary_ref = state.get("latest_run_summary_reference")
        snapshot = {
            "schema_id": EVIDENCE_SNAPSHOT_SCHEMA_ID,
            "schema_version": EVIDENCE_SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": current_snapshot_id,
            "role_revision_set": deepcopy(registry["role_heads"]),
            "artifact_revision_digest_bindings": {
                role: registry["artifact_revisions"][revision_id]["content_digest"]
                for role, revision_id in registry["role_heads"].items()
            },
            "manifestation_revision_set": manifestations,
            "run_summary_reference": summary_ref,
            "current_build_context": (
                deepcopy(saved.get("current_build_context"))
                if isinstance(saved, Mapping)
                and isinstance(saved.get("current_build_context"), Mapping)
                else None
            ),
            "assistant_context_update_reference": None,
            "processing_outcomes": deepcopy(dict(state.get("artifact_processing_outcomes", {}))),
            "snapshot_status": "pending_derivation",
            "contract_revision": state["current_loop_contract"]["contract_revision"],
            "derivation_version": "qcoder.current_loop.derivation.legacy_v8",
            "creation_state_revision": int(state["state_revision"]),
        }
        registry["snapshots"][current_snapshot_id] = snapshot
        registry["pending_snapshot_id"] = current_snapshot_id
    return {
        "evidence_registry": registry,
        "registered_pending_derivation": (
            {
                "snapshot_id": current_snapshot_id,
                "artifact_revision_ids": sorted(registry["role_heads"].values()),
                "registered_state_revision": int(state["state_revision"]),
            }
            if current_snapshot_id is not None
            else None
        ),
        "current_evidence_status": ("pending"),
    }
