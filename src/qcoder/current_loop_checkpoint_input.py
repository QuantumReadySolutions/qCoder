"""Lossless, bounded input for Current Loop authority checkpoints.

The connected assistant creates this machine payload.  The customer reviews
the complete values rendered by qCoder and supplies authority separately.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from qcoder.current_loop import CurrentLoopError, canonical_bytes

CHECKPOINT_INPUT_SCHEMA_ID = "qcoder.current_loop.checkpoint_input.v1"
CHECKPOINT_INPUT_SCHEMA_VERSION = 1
CHECKPOINT_INPUT_MAX_BYTES = 131_072
CHECKPOINT_INPUT_MAX_FIELDS = 64
CHECKPOINT_INPUT_MAX_FIELD_BYTES = 20_000

CHECKPOINT_INPUT_OPERATIONS = (
    "prepare_generation",
    "continue_unchanged",
    "propose_change",
    "confirm_change",
)

CHECKPOINT_INPUT_PROVENANCE = (
    "assistant_proposed",
    "hosted_presented",
    "user_provided",
    "user_confirmed_assistant_interpretation",
    "user_confirmed_assistant_recommendation",
    "inherited_confirmed_lineage",
)

_OPERATION_FIELDS = {
    "prepare_generation": frozenset(
        {
            "profile_id",
            "proposed_interpretation",
            "requirements",
            "constraints",
            "non_goals",
            "decision_dispositions",
            "reviewed_profile_answers",
            "accepted_unresolved_choices",
            "requested_generation_posture",
            "posture_change_reason",
            "posture_authority_provenance",
            "confirmation_assertion",
        }
    ),
    "continue_unchanged": frozenset(
        {
            "user_statement",
            "decline_unconfirmed_proposal",
        }
    ),
    "propose_change": frozenset(
        {
            "decision_ref",
            "selected_action",
            "proposed_value",
            "control_treatment",
        }
    ),
    "confirm_change": frozenset({"semantic_confirmation"}),
}

_REQUIRED_OPERATION_FIELDS = {
    "prepare_generation": frozenset({"profile_id", "proposed_interpretation"}),
    "continue_unchanged": frozenset({"user_statement"}),
    "propose_change": frozenset(
        {"decision_ref", "selected_action", "proposed_value", "control_treatment"}
    ),
    "confirm_change": frozenset({"semantic_confirmation"}),
}


def _unsafe_text_control(value: str) -> bool:
    return any(
        (ord(character) < 32 and character not in "\t\n\r") or ord(character) == 127
        for character in value
    )


def _validate_text_tree(value: object) -> None:
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        if not value or len(encoded) > CHECKPOINT_INPUT_MAX_FIELD_BYTES:
            raise CurrentLoopError("checkpoint_input_field_size_invalid")
        if "\x00" in value or _unsafe_text_control(value):
            raise CurrentLoopError("checkpoint_input_text_control_invalid")
        return
    if isinstance(value, Mapping):
        if len(value) > CHECKPOINT_INPUT_MAX_FIELDS:
            raise CurrentLoopError("checkpoint_input_field_count_invalid")
        for key, item in value.items():
            if not isinstance(key, str) or not key or _unsafe_text_control(key):
                raise CurrentLoopError("checkpoint_input_field_name_invalid")
            _validate_text_tree(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > CHECKPOINT_INPUT_MAX_FIELDS:
            raise CurrentLoopError("checkpoint_input_field_count_invalid")
        for item in value:
            _validate_text_tree(item)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise CurrentLoopError("checkpoint_input_value_invalid")


def decode_checkpoint_input(raw: bytes) -> dict[str, Any]:
    """Decode one exact UTF-8 payload without newline or whitespace normalization."""

    if not raw:
        raise CurrentLoopError("checkpoint_input_empty")
    if len(raw) > CHECKPOINT_INPUT_MAX_BYTES:
        raise CurrentLoopError("checkpoint_input_too_large")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CurrentLoopError("checkpoint_input_utf8_invalid") from exc
    if "\x00" in text or _unsafe_text_control(text):
        raise CurrentLoopError("checkpoint_input_text_control_invalid")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CurrentLoopError("checkpoint_input_json_invalid") from exc
    if not isinstance(value, dict):
        raise CurrentLoopError("checkpoint_input_schema_invalid")
    value["_transport_utf8_sha256"] = sha256(raw).hexdigest()
    value["_transport_size_bytes"] = len(raw)
    return value


def normalize_checkpoint_input(
    payload: Mapping[str, Any],
    *,
    operation: str,
    checkpoint_kind: str,
    workspace_binding: str,
    loop_ref: str,
    phase: str,
    expected_state_revision: int,
    captured_at: float,
    transport: str,
) -> dict[str, Any]:
    """Validate assistant-created input and bind it to one exact local checkpoint."""

    if set(payload) - {
        "schema_id",
        "schema_version",
        "operation",
        "checkpoint_kind",
        "fields",
        "_transport_utf8_sha256",
        "_transport_size_bytes",
    }:
        raise CurrentLoopError("checkpoint_input_schema_invalid")
    if (
        payload.get("schema_id") != CHECKPOINT_INPUT_SCHEMA_ID
        or payload.get("schema_version") != CHECKPOINT_INPUT_SCHEMA_VERSION
    ):
        raise CurrentLoopError("checkpoint_input_schema_invalid")
    if operation not in CHECKPOINT_INPUT_OPERATIONS or payload.get("operation") != operation:
        raise CurrentLoopError("checkpoint_input_operation_mismatch")
    if (
        transport not in {"stdin", "file", "qcoder_held"}
        or not workspace_binding
        or not loop_ref
        or not phase
        or expected_state_revision < 1
    ):
        raise CurrentLoopError("checkpoint_input_binding_invalid")
    supplied_kind = payload.get("checkpoint_kind")
    if supplied_kind != checkpoint_kind:
        raise CurrentLoopError("checkpoint_input_checkpoint_mismatch")
    supplied_fields = payload.get("fields")
    if not isinstance(supplied_fields, list) or not supplied_fields:
        raise CurrentLoopError("checkpoint_input_fields_invalid")
    if len(supplied_fields) > CHECKPOINT_INPUT_MAX_FIELDS:
        raise CurrentLoopError("checkpoint_input_field_count_invalid")

    permitted = _OPERATION_FIELDS[operation]
    by_name: dict[str, dict[str, Any]] = {}
    for supplied in supplied_fields:
        if not isinstance(supplied, Mapping):
            raise CurrentLoopError("checkpoint_input_field_invalid")
        name = supplied.get("name")
        provenance = supplied.get("provenance")
        if not isinstance(name, str) or name not in permitted:
            raise CurrentLoopError("checkpoint_input_field_unsupported")
        if provenance not in CHECKPOINT_INPUT_PROVENANCE:
            raise CurrentLoopError("checkpoint_input_provenance_invalid")
        if "value" not in supplied:
            raise CurrentLoopError("checkpoint_input_field_invalid")
        value = deepcopy(supplied["value"])
        _validate_text_tree(value)
        field_bytes = canonical_bytes({"value": value})
        if len(field_bytes) > CHECKPOINT_INPUT_MAX_FIELD_BYTES:
            raise CurrentLoopError("checkpoint_input_field_size_invalid")
        normalized = {
            "name": name,
            "value": value,
            "provenance": provenance,
            "value_utf8_sha256": sha256(
                value.encode("utf-8") if isinstance(value, str) else canonical_bytes(value)
            ).hexdigest(),
            "size_bytes": (
                len(value.encode("utf-8"))
                if isinstance(value, str)
                else len(canonical_bytes(value))
            ),
        }
        previous = by_name.get(name)
        if previous is not None:
            if previous != normalized:
                raise CurrentLoopError("checkpoint_input_contradictory_duplicate")
            raise CurrentLoopError("checkpoint_input_duplicate")
        by_name[name] = normalized

    missing = _REQUIRED_OPERATION_FIELDS[operation] - set(by_name)
    if missing:
        raise CurrentLoopError("checkpoint_input_required_field_missing")
    canonical_fields = [by_name[name] for name in sorted(by_name)]
    content_projection = {
        "schema_id": CHECKPOINT_INPUT_SCHEMA_ID,
        "schema_version": CHECKPOINT_INPUT_SCHEMA_VERSION,
        "operation": operation,
        "checkpoint_kind": checkpoint_kind,
        "fields": canonical_fields,
    }
    total_size = len(canonical_bytes(content_projection))
    if total_size > CHECKPOINT_INPUT_MAX_BYTES:
        raise CurrentLoopError("checkpoint_input_too_large")
    content_digest = sha256(canonical_bytes(content_projection)).hexdigest()
    return {
        **content_projection,
        "workspace_binding": workspace_binding,
        "loop_ref": loop_ref,
        "phase": phase,
        "expected_state_revision": expected_state_revision,
        "captured_at": captured_at,
        "transport": transport,
        "transport_utf8_sha256": payload.get("_transport_utf8_sha256"),
        "transport_size_bytes": payload.get("_transport_size_bytes"),
        "total_size_bytes": total_size,
        "content_digest": content_digest,
        "status": "pending",
        "review_state": "pending_exact_input_review",
    }


def checkpoint_input_values(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return exact staged values after validating the record digest."""

    if (
        record.get("schema_id") != CHECKPOINT_INPUT_SCHEMA_ID
        or record.get("schema_version") != CHECKPOINT_INPUT_SCHEMA_VERSION
        or record.get("status") != "pending"
    ):
        raise CurrentLoopError("checkpoint_input_pending_required")
    fields = record.get("fields")
    if not isinstance(fields, list):
        raise CurrentLoopError("checkpoint_input_record_invalid")
    projection = {
        "schema_id": record["schema_id"],
        "schema_version": record["schema_version"],
        "operation": record.get("operation"),
        "checkpoint_kind": record.get("checkpoint_kind"),
        "fields": fields,
    }
    if sha256(canonical_bytes(projection)).hexdigest() != record.get("content_digest"):
        raise CurrentLoopError("checkpoint_input_digest_mismatch")
    values: dict[str, Any] = {}
    for field in fields:
        if not isinstance(field, Mapping) or not isinstance(field.get("name"), str):
            raise CurrentLoopError("checkpoint_input_record_invalid")
        values[str(field["name"])] = deepcopy(field.get("value"))
    return values


def checkpoint_input_contract_snapshot() -> dict[str, Any]:
    return {
        "schema_id": CHECKPOINT_INPUT_SCHEMA_ID,
        "schema_version": CHECKPOINT_INPUT_SCHEMA_VERSION,
        "operations": list(CHECKPOINT_INPUT_OPERATIONS),
        "transports": ["stdin", "file"],
        "maximum_transport_bytes": CHECKPOINT_INPUT_MAX_BYTES,
        "maximum_fields": CHECKPOINT_INPUT_MAX_FIELDS,
        "maximum_field_bytes": CHECKPOINT_INPUT_MAX_FIELD_BYTES,
        "approval_only_promotion": True,
        "content_and_approval_same_invocation": False,
        "shell_literal_free_text_required": False,
    }
