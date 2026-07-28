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

CHECKPOINT_INPUT_SCHEMA_ID = "qcoder.current_loop.checkpoint_input.v2"
CHECKPOINT_INPUT_SCHEMA_VERSION = 2
PREVIOUS_CHECKPOINT_INPUT_SCHEMA_ID = "qcoder.current_loop.checkpoint_input.v1"
PREVIOUS_CHECKPOINT_INPUT_SCHEMA_VERSION = 1
CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_ID = "qcoder.current_loop.checkpoint_input_construction.v1"
CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_VERSION = 1
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

_CHECKPOINT_KINDS_BY_OPERATION = {
    "prepare_generation": frozenset({"intent_review", "decision_resolution", "posture"}),
    "continue_unchanged": frozenset({"governing_change_confirmation"}),
    "propose_change": frozenset({"governing_change_confirmation"}),
    "confirm_change": frozenset({"governing_change_confirmation"}),
}


class CheckpointInputStructuralError(CurrentLoopError):
    """A fail-closed structural error with customer-safe diagnostic metadata."""

    def __init__(self, category: str, **safe_details: object) -> None:
        super().__init__(category)
        self.safe_details = {
            "structural_error": {
                "error_code": category,
                "assistant_should_stop": True,
                "hosted_operation_permitted": False,
                "fresh_customer_input_required": bool(
                    safe_details.pop("fresh_customer_input_required", False)
                ),
                **safe_details,
            }
        }


def checkpoint_input_safe_structure(payload: Mapping[str, Any]) -> dict[str, Any]:
    fields = payload.get("fields")
    field_records: list[dict[str, Any]] = []
    if isinstance(fields, list):
        for item in fields:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name")
            value = item.get("value")
            if not isinstance(name, str):
                continue
            try:
                encoded = (
                    value.encode("utf-8") if isinstance(value, str) else canonical_bytes(value)
                )
            except (TypeError, ValueError):
                continue
            field_records.append(
                {
                    "name": name,
                    "size_bytes": len(encoded),
                    "value_sha256": sha256(encoded).hexdigest(),
                }
            )
    binding = payload.get("binding")
    return {
        "received_schema_id": payload.get("schema_id"),
        "received_schema_version": payload.get("schema_version"),
        "received_operation": (
            binding.get("operation") if isinstance(binding, Mapping) else payload.get("operation")
        ),
        "received_checkpoint_kind": (
            binding.get("checkpoint_kind")
            if isinstance(binding, Mapping)
            else payload.get("checkpoint_kind")
        ),
        "received_state_revision": (
            binding.get("expected_state_revision") if isinstance(binding, Mapping) else None
        ),
        "content_fields": field_records,
        "transport_size_bytes": payload.get("_transport_size_bytes"),
        "transport_sha256": payload.get("_transport_utf8_sha256"),
    }


def _workspace_binding_digest(workspace_binding: str) -> str:
    return f"sha256:{sha256(workspace_binding.encode('utf-8')).hexdigest()}"


def checkpoint_input_construction(
    *,
    operation: str,
    checkpoint_kind: str,
    workspace_binding: str,
    loop_ref: str,
    phase: str,
    expected_state_revision: int,
) -> dict[str, Any]:
    """Return the complete client-visible recipe for one exact staging action."""

    if (
        operation not in CHECKPOINT_INPUT_OPERATIONS
        or checkpoint_kind not in _CHECKPOINT_KINDS_BY_OPERATION[operation]
        or not workspace_binding
        or not loop_ref
        or not phase
        or expected_state_revision < 1
    ):
        raise CurrentLoopError("checkpoint_input_construction_binding_invalid")
    fixed_payload = {
        "schema_id": CHECKPOINT_INPUT_SCHEMA_ID,
        "schema_version": CHECKPOINT_INPUT_SCHEMA_VERSION,
        "binding": {
            "operation": operation,
            "checkpoint_kind": checkpoint_kind,
            "phase": phase,
            "loop_ref": loop_ref,
            "workspace_binding": _workspace_binding_digest(workspace_binding),
            "expected_state_revision": expected_state_revision,
        },
    }
    construction: dict[str, Any] = {
        "schema_id": CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_ID,
        "schema_version": CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_VERSION,
        "construction_mode": "checkpoint_input_transport",
        "fixed_payload": fixed_payload,
        "assistant_supplied_property": "fields",
        "accepted_value_fields": [
            {
                "name": name,
                "required": name in _REQUIRED_OPERATION_FIELDS[operation],
                "value_type": "bounded_json_value_with_exact_utf8_text",
                "allowed_provenance": list(CHECKPOINT_INPUT_PROVENANCE),
            }
            for name in sorted(_OPERATION_FIELDS[operation])
        ],
        "field_item_contract": {
            "required_properties": ["name", "value", "provenance"],
            "additional_properties": False,
            "duplicate_names_permitted": False,
        },
        "serialization": {
            "media_type": "application/json",
            "encoding": "UTF-8",
            "newline_normalization": False,
            "terminal_control_policy": "tab_cr_lf_only",
            "maximum_transport_bytes": CHECKPOINT_INPUT_MAX_BYTES,
            "maximum_fields": CHECKPOINT_INPUT_MAX_FIELDS,
            "maximum_field_bytes": CHECKPOINT_INPUT_MAX_FIELD_BYTES,
        },
        "digest_semantics": {
            "assistant_computes_digest": False,
            "transport_digest": "qcoder_sha256_of_exact_received_utf8_bytes",
            "content_digest": ("qcoder_sha256_of_canonical_validated_schema_binding_and_fields"),
            "field_digest": "qcoder_sha256_of_exact_utf8_or_canonical_json_value",
            "canonicalization_or_field_order_must_not_be_inferred": True,
        },
        "stage_invocation": {
            "subcommand": "stage-checkpoint-input",
            "required_flags": ["--checkpoint-input-stdin or --checkpoint-input-file"],
            "operation_or_checkpoint_flags_required": False,
            "input_transports": ["stdin", "file"],
            "literal_free_text_in_argv": False,
            "customer_types_command": False,
        },
        "approval": {
            "separate_invocation_required": True,
            "subcommand": "approve-checkpoint-input",
            "required_flags": ["--approve"],
            "staged_values_retransmitted": False,
            "content_submission_grants_authority": False,
        },
        "prohibitions": [
            "assistant_must_not_modify_fixed_payload",
            "assistant_must_not_duplicate_fixed_values_in_cli_flags",
            "assistant_must_not_compute_or_supply_digests",
            "assistant_must_not_reconstruct_values_from_transcript",
            "assistant_must_not_inspect_source_or_package",
            "assistant_must_not_inspect_qcoder_local_state",
        ],
    }
    construction["construction_digest"] = sha256(canonical_bytes(construction)).hexdigest()
    return construction


def checkpoint_input_binding_values(payload: Mapping[str, Any]) -> tuple[str, str]:
    """Read the qCoder-emitted operation and kind without accepting guesswork."""

    binding = payload.get("binding")
    if not isinstance(binding, Mapping):
        operation = payload.get("operation")
        checkpoint_kind = payload.get("checkpoint_kind")
    else:
        operation = binding.get("operation")
        checkpoint_kind = binding.get("checkpoint_kind")
    if not isinstance(operation, str) or operation not in CHECKPOINT_INPUT_OPERATIONS:
        raise CheckpointInputStructuralError(
            "checkpoint_input_operation_invalid",
            received_operation=operation if isinstance(operation, str) else None,
        )
    if (
        not isinstance(checkpoint_kind, str)
        or checkpoint_kind not in _CHECKPOINT_KINDS_BY_OPERATION[operation]
    ):
        raise CheckpointInputStructuralError(
            "checkpoint_input_checkpoint_mismatch",
            expected_checkpoint_kinds=sorted(_CHECKPOINT_KINDS_BY_OPERATION[operation]),
            received_checkpoint_kind=(
                checkpoint_kind if isinstance(checkpoint_kind, str) else None
            ),
        )
    return operation, checkpoint_kind


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
    source_state_revision: int,
    captured_at: float,
    transport: str,
) -> dict[str, Any]:
    """Validate assistant-created input and bind it to one exact local checkpoint."""

    schema_id = payload.get("schema_id")
    schema_version = payload.get("schema_version")
    legacy = (
        schema_id == PREVIOUS_CHECKPOINT_INPUT_SCHEMA_ID
        and schema_version == PREVIOUS_CHECKPOINT_INPUT_SCHEMA_VERSION
    )
    permitted_payload_keys = {
        "schema_id",
        "schema_version",
        "binding",
        "fields",
        "_transport_utf8_sha256",
        "_transport_size_bytes",
    }
    if legacy:
        permitted_payload_keys.update({"operation", "checkpoint_kind"})
    if set(payload) - permitted_payload_keys:
        raise CurrentLoopError("checkpoint_input_schema_invalid")
    if not legacy and (
        schema_id != CHECKPOINT_INPUT_SCHEMA_ID or schema_version != CHECKPOINT_INPUT_SCHEMA_VERSION
    ):
        raise CheckpointInputStructuralError(
            "checkpoint_input_schema_invalid",
            expected_schema_id=CHECKPOINT_INPUT_SCHEMA_ID,
            expected_schema_version=CHECKPOINT_INPUT_SCHEMA_VERSION,
            **checkpoint_input_safe_structure(payload),
        )
    supplied_operation, supplied_kind = checkpoint_input_binding_values(payload)
    if operation not in CHECKPOINT_INPUT_OPERATIONS or supplied_operation != operation:
        raise CheckpointInputStructuralError(
            "checkpoint_input_operation_mismatch",
            expected_operation=operation,
            received_operation=supplied_operation,
            expected_checkpoint_kind=checkpoint_kind,
            received_checkpoint_kind=supplied_kind,
        )
    if (
        transport not in {"stdin", "file", "qcoder_held"}
        or not workspace_binding
        or not loop_ref
        or not phase
        or expected_state_revision < 1
        or source_state_revision < 1
    ):
        raise CurrentLoopError("checkpoint_input_binding_invalid")
    if supplied_kind != checkpoint_kind:
        raise CheckpointInputStructuralError(
            "checkpoint_input_checkpoint_mismatch",
            expected_operation=operation,
            received_operation=supplied_operation,
            expected_checkpoint_kind=checkpoint_kind,
            received_checkpoint_kind=supplied_kind,
        )
    if not legacy:
        binding = payload.get("binding")
        expected_binding = {
            "operation": operation,
            "checkpoint_kind": checkpoint_kind,
            "phase": phase,
            "loop_ref": loop_ref,
            "workspace_binding": _workspace_binding_digest(workspace_binding),
            "expected_state_revision": source_state_revision,
        }
        if not isinstance(binding, Mapping):
            raise CheckpointInputStructuralError(
                "checkpoint_input_binding_mismatch",
                expected_operation=operation,
                expected_checkpoint_kind=checkpoint_kind,
                expected_state_revision=source_state_revision,
            )
        received_revision = binding.get("expected_state_revision")
        if received_revision != source_state_revision:
            raise CheckpointInputStructuralError(
                "checkpoint_input_state_revision_stale",
                expected_operation=operation,
                received_operation=binding.get("operation"),
                expected_checkpoint_kind=checkpoint_kind,
                received_checkpoint_kind=binding.get("checkpoint_kind"),
                expected_state_revision=source_state_revision,
                received_state_revision=received_revision,
                fresh_customer_input_required=False,
            )
        if dict(binding) != expected_binding:
            raise CheckpointInputStructuralError(
                "checkpoint_input_binding_mismatch",
                expected_operation=operation,
                received_operation=binding.get("operation"),
                expected_checkpoint_kind=checkpoint_kind,
                received_checkpoint_kind=binding.get("checkpoint_kind"),
                expected_state_revision=source_state_revision,
                received_state_revision=received_revision,
            )
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
        "binding": {
            "operation": operation,
            "checkpoint_kind": checkpoint_kind,
            "phase": phase,
            "loop_ref": loop_ref,
            "workspace_binding": _workspace_binding_digest(workspace_binding),
            "expected_state_revision": source_state_revision,
        },
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

    current = (
        record.get("schema_id") == CHECKPOINT_INPUT_SCHEMA_ID
        and record.get("schema_version") == CHECKPOINT_INPUT_SCHEMA_VERSION
    )
    legacy = (
        record.get("schema_id") == PREVIOUS_CHECKPOINT_INPUT_SCHEMA_ID
        and record.get("schema_version") == PREVIOUS_CHECKPOINT_INPUT_SCHEMA_VERSION
    )
    if (not current and not legacy) or record.get("status") != "pending":
        raise CurrentLoopError("checkpoint_input_pending_required")
    fields = record.get("fields")
    if not isinstance(fields, list):
        raise CurrentLoopError("checkpoint_input_record_invalid")
    projection: dict[str, Any] = {
        "schema_id": record["schema_id"],
        "schema_version": record["schema_version"],
        "operation": record.get("operation"),
        "checkpoint_kind": record.get("checkpoint_kind"),
        "fields": fields,
    }
    if current:
        projection["binding"] = record.get("binding")
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
        "construction_schema_id": CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_ID,
        "construction_schema_version": CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_VERSION,
        "previous_compatibility_schema_id": PREVIOUS_CHECKPOINT_INPUT_SCHEMA_ID,
        "operations": list(CHECKPOINT_INPUT_OPERATIONS),
        "operation_fields": {
            operation: {
                "accepted": sorted(_OPERATION_FIELDS[operation]),
                "required": sorted(_REQUIRED_OPERATION_FIELDS[operation]),
                "checkpoint_kinds": sorted(_CHECKPOINT_KINDS_BY_OPERATION[operation]),
            }
            for operation in CHECKPOINT_INPUT_OPERATIONS
        },
        "transports": ["stdin", "file"],
        "maximum_transport_bytes": CHECKPOINT_INPUT_MAX_BYTES,
        "maximum_fields": CHECKPOINT_INPUT_MAX_FIELDS,
        "maximum_field_bytes": CHECKPOINT_INPUT_MAX_FIELD_BYTES,
        "approval_only_promotion": True,
        "content_and_approval_same_invocation": False,
        "shell_literal_free_text_required": False,
    }
