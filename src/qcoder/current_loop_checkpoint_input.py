"""Lossless, bounded input for Current Loop authority checkpoints.

The connected assistant creates this machine payload.  The customer reviews
the complete values rendered by qCoder and supplies authority separately.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from qcoder.algorithm_blueprint import PROFILE_DEFINITIONS, PROFILE_IDS
from qcoder.blueprint_decisions import ACTION_IDS, CONTROL_TREATMENTS, catalog_entries
from qcoder.current_loop import CurrentLoopError, canonical_bytes

CHECKPOINT_INPUT_SCHEMA_ID = "qcoder.current_loop.checkpoint_input.v3"
CHECKPOINT_INPUT_SCHEMA_VERSION = 3
PREVIOUS_CHECKPOINT_INPUT_SCHEMA_ID = "qcoder.current_loop.checkpoint_input.v1"
PREVIOUS_CHECKPOINT_INPUT_SCHEMA_VERSION = 1
PREVIOUS_CHECKPOINT_INPUT_SCHEMA_IDS = frozenset(
    {
        "qcoder.current_loop.checkpoint_input.v1",
        "qcoder.current_loop.checkpoint_input.v2",
    }
)
CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_ID = "qcoder.current_loop.checkpoint_input_construction.v2"
CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_VERSION = 2
CHECKPOINT_INPUT_SEMANTIC_SCHEMA_ID = (
    "qcoder.current_loop.checkpoint_input_semantic_field_contract.v1"
)
CHECKPOINT_INPUT_SEMANTIC_SCHEMA_VERSION = 1
CHECKPOINT_INPUT_MAX_BYTES = 131_072
CHECKPOINT_INPUT_MAX_FIELDS = 64
CHECKPOINT_INPUT_MAX_FIELD_BYTES = 20_000
CHECKPOINT_INPUT_MAX_DEPTH = 8

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

DECISION_AUTHORITY_PROVENANCE = (
    "user_provided",
    "user_confirmed_assistant_interpretation",
    "inherited_confirmed_lineage",
    "assistant_recommendation_pending_confirmation",
)

POSTURE_AUTHORITY_PROVENANCE = (
    "user_provided",
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


class CheckpointInputSemanticError(CheckpointInputStructuralError):
    """A safe stage-time rejection for a client-visible field contract."""

    def __init__(
        self,
        category: str,
        *,
        field_name: str,
        expected_contract: Mapping[str, Any],
        received_value: object,
        semantic_contract: Mapping[str, Any],
        outside_enum: bool = False,
        fresh_customer_input_required: bool = True,
    ) -> None:
        expected_type = expected_contract.get("type")
        received_type = _json_type(received_value)
        super().__init__(
            category,
            field_name=field_name,
            expected_json_type=expected_type,
            received_json_type=received_type,
            outside_bounded_domain=outside_enum,
            expected_enum=(
                deepcopy(expected_contract.get("enum"))
                if isinstance(expected_contract.get("enum"), list)
                else None
            ),
            semantic_contract_schema_id=semantic_contract.get("schema_id"),
            semantic_contract_schema_version=semantic_contract.get("schema_version"),
            semantic_contract_digest=semantic_contract.get("contract_digest"),
            fresh_customer_input_required=fresh_customer_input_required,
        )
        self.safe_details["semantic_error"] = self.safe_details.pop("structural_error")


def _open_text_schema(
    *, meaning: str, maximum_bytes: int = CHECKPOINT_INPUT_MAX_FIELD_BYTES
) -> dict[str, Any]:
    return {
        "type": "string",
        "minLength": 1,
        "maxUtf8Bytes": maximum_bytes,
        "normalization": "none",
        "controlCharacterPolicy": "tab_cr_lf_only",
        "customer_meaning": meaning,
    }


def _bounded_json_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            {"type": "string", "maxUtf8Bytes": CHECKPOINT_INPUT_MAX_FIELD_BYTES},
            {"type": "number"},
            {"type": "integer"},
            {"type": "boolean"},
            {"type": "null"},
            {
                "type": "array",
                "maxItems": CHECKPOINT_INPUT_MAX_FIELDS,
                "items": {"$ref": "#/$defs/bounded_json"},
            },
            {
                "type": "object",
                "maxProperties": CHECKPOINT_INPUT_MAX_FIELDS,
                "additionalProperties": {"$ref": "#/$defs/bounded_json"},
            },
        ]
    }


def _string_list_schema(*, meaning: str) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": 0,
        "maxItems": CHECKPOINT_INPUT_MAX_FIELDS,
        "uniqueItems": False,
        "ordering": "customer_supplied",
        "items": _open_text_schema(meaning=meaning),
        "customer_meaning": meaning,
    }


def _object_list_schema(*, meaning: str) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": 0,
        "maxItems": CHECKPOINT_INPUT_MAX_FIELDS,
        "uniqueItems": False,
        "ordering": "customer_supplied",
        "items": {
            "type": "object",
            "maxProperties": CHECKPOINT_INPUT_MAX_FIELDS,
            "additionalProperties": {"$ref": "#/$defs/bounded_json"},
        },
        "customer_meaning": meaning,
    }


def _decision_disposition_schema() -> dict[str, Any]:
    profiles: dict[str, Any] = {}
    for profile_id in PROFILE_IDS:
        definitions = catalog_entries(profile_id)
        profiles[profile_id] = {
            "decision_ids": [item["profile_decision_id"] for item in definitions],
            "supported_values_by_decision": {
                item["profile_decision_id"]: list(item.get("supported_alternatives") or [])
                for item in definitions
            },
        }
    return {
        "type": "array",
        "minItems": 0,
        "maxItems": CHECKPOINT_INPUT_MAX_FIELDS,
        "uniqueBy": "profile_decision_id",
        "profileSelectorField": "profile_id",
        "profileVariants": profiles,
        "items": {
            "type": "object",
            "required": [
                "profile_decision_id",
                "user_disposition",
                "authority_provenance",
            ],
            "properties": {
                "profile_decision_id": {"type": "string", "domainSource": "selected_profile"},
                "user_disposition": {
                    "type": "string",
                    "enum": ["selected_choice", "left_unresolved"],
                },
                "selected_value": {
                    "type": ["string", "null"],
                    "maxUtf8Bytes": 500,
                    "domainSource": "selected_profile_decision",
                },
                "authority_provenance": {
                    "type": "string",
                    "enum": list(DECISION_AUTHORITY_PROVENANCE[:3]),
                },
            },
            "additionalProperties": False,
            "conditionalRules": [
                {
                    "if": {"user_disposition": "selected_choice"},
                    "thenRequired": ["selected_value"],
                    "thenDomain": "selected_profile_decision",
                },
                {
                    "if": {"user_disposition": "left_unresolved"},
                    "thenAllowedSelectedValues": [None, "", "-"],
                },
            ],
        },
        "customer_meaning": "Explicit dispositions for the selected profile's exact decisions.",
    }


def checkpoint_input_semantic_contract(
    *,
    operation: str,
    checkpoint_kind: str,
    phase: str,
    bounded_domains: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the canonical promotion-compatible contract for one checkpoint."""

    if (
        operation not in CHECKPOINT_INPUT_OPERATIONS
        or checkpoint_kind not in _CHECKPOINT_KINDS_BY_OPERATION[operation]
        or not phase
    ):
        raise CurrentLoopError("checkpoint_input_semantic_binding_invalid")
    domains = bounded_domains or {}
    field_schemas: dict[str, dict[str, Any]] = {
        "profile_id": {
            "type": "string",
            "enum": list(PROFILE_IDS),
            "enumMeanings": {
                profile_id: str(PROFILE_DEFINITIONS[profile_id]["display_name"])
                for profile_id in PROFILE_IDS
            },
            "customer_meaning": "Selected supported Algorithm Blueprint profile.",
            "assistant_may_propose_supported_value": True,
            "direct_customer_selection_or_approval_required": True,
        },
        "proposed_interpretation": {
            "type": "object",
            "minProperties": 0,
            "maxProperties": CHECKPOINT_INPUT_MAX_FIELDS,
            "propertyNames": {
                "type": "string",
                "minLength": 1,
                "maxUtf8Bytes": CHECKPOINT_INPUT_MAX_FIELD_BYTES,
            },
            "additionalProperties": {"$ref": "#/$defs/bounded_json"},
            "customer_meaning": "Structured assistant-proposed interpretation reviewed by the customer.",
            "assistant_may_propose_supported_value": True,
            "direct_customer_selection_or_approval_required": True,
        },
        "requirements": _object_list_schema(
            meaning="Structured requirements explicitly supplied or approved for this build."
        ),
        "constraints": _string_list_schema(
            meaning="Exact customer constraints retained in supplied order."
        ),
        "non_goals": _string_list_schema(
            meaning="Exact customer non-goals retained in supplied order."
        ),
        "decision_dispositions": _decision_disposition_schema(),
        "reviewed_profile_answers": {
            "type": "object",
            "minProperties": 0,
            "maxProperties": CHECKPOINT_INPUT_MAX_FIELDS,
            "propertyNames": {
                "type": "string",
                "minLength": 1,
                "maxUtf8Bytes": CHECKPOINT_INPUT_MAX_FIELD_BYTES,
            },
            "additionalProperties": {"$ref": "#/$defs/bounded_json"},
            "customer_meaning": "Exact reviewed answers to profile clarification fields.",
        },
        "accepted_unresolved_choices": _string_list_schema(
            meaning="Exact names of unresolved choices the customer accepts retaining."
        ),
        "requested_generation_posture": {
            "type": "string",
            "enum": ["blueprint_guided", "exploratory_first_pass"],
            **(
                {"currentBoundValue": str(domains["current_generation_posture"])}
                if domains.get("current_generation_posture")
                in {"blueprint_guided", "exploratory_first_pass"}
                else {}
            ),
            "customer_meaning": "Separate bounded generation posture selection.",
            "assistant_may_propose_supported_value": True,
            "direct_customer_selection_or_approval_required": True,
        },
        "posture_change_reason": _open_text_schema(
            meaning="Exact attributed customer reason for a posture transition."
        ),
        "posture_authority_provenance": {
            "type": "string",
            "enum": list(POSTURE_AUTHORITY_PROVENANCE),
            "customer_meaning": "Attributable source of the explicit posture authority.",
        },
        "confirmation_assertion": _open_text_schema(
            meaning="Exact customer statement confirming the displayed intent."
        ),
        "user_statement": _open_text_schema(
            meaning="Exact customer statement choosing unchanged continuation."
        ),
        "decline_unconfirmed_proposal": {
            "type": "boolean",
            "customer_meaning": "Explicit decline of the currently displayed unconfirmed proposal.",
            **({"const": True} if phase == "change_confirmation" else {}),
        },
        "decision_ref": _open_text_schema(
            meaning="Exact qCoder-presented decision reference selected by the customer.",
            maximum_bytes=500,
        )
        | (
            {"enum": deepcopy(domains["decision_ref"])}
            if isinstance(domains.get("decision_ref"), list)
            else {}
        ),
        "selected_action": {
            "type": "string",
            "enum": (
                deepcopy(domains["selected_action"])
                if isinstance(domains.get("selected_action"), list)
                else list(ACTION_IDS)
            ),
            "customer_meaning": "Exact supported Carry-Forward action selected by the customer.",
        },
        "proposed_value": {
            "$ref": "#/$defs/bounded_json",
            "customer_meaning": "Exact proposed value for the selected governing decision.",
            **(
                {"domainByDecisionRef": deepcopy(domains["proposed_value_by_decision"])}
                if isinstance(domains.get("proposed_value_by_decision"), Mapping)
                else {}
            ),
        },
        "control_treatment": {
            "type": "string",
            "enum": (
                deepcopy(domains["control_treatment"])
                if isinstance(domains.get("control_treatment"), list)
                else list(CONTROL_TREATMENTS)
            ),
            "customer_meaning": "Exact supported control treatment for the proposal.",
        },
        "semantic_confirmation": _open_text_schema(
            meaning="Exact proposal-specific customer confirmation statement."
        )
        | (
            {"containsUtf8": str(domains["proposal_ref"])}
            if isinstance(domains.get("proposal_ref"), str)
            else {}
        ),
    }
    fields: list[dict[str, Any]] = []
    for name in sorted(_OPERATION_FIELDS[operation]):
        schema = deepcopy(field_schemas[name])
        fields.append(
            {
                "name": name,
                "required": name in _REQUIRED_OPERATION_FIELDS[operation],
                "conditionally_required": (
                    name == "decline_unconfirmed_proposal" and phase == "change_confirmation"
                ),
                "nullable": _schema_allows_null(schema),
                "allowed_provenance": list(CHECKPOINT_INPUT_PROVENANCE),
                "schema": schema,
                "normalization": "none",
                "maximum_field_bytes": CHECKPOINT_INPUT_MAX_FIELD_BYTES,
                "operation": operation,
                "checkpoint_kind": checkpoint_kind,
                "qcoder_may_prebind": True,
            }
        )
    contract: dict[str, Any] = {
        "schema_id": CHECKPOINT_INPUT_SEMANTIC_SCHEMA_ID,
        "schema_version": CHECKPOINT_INPUT_SEMANTIC_SCHEMA_VERSION,
        "operation": operation,
        "checkpoint_kind": checkpoint_kind,
        "phase": phase,
        "fields": fields,
        "$defs": {"bounded_json": _bounded_json_schema()},
        "maximum_depth": CHECKPOINT_INPUT_MAX_DEPTH,
        "stage_validation_equals_promotion_validation": True,
        "staging_grants_authority": False,
        "approval_retransmits_content": False,
    }
    contract["contract_digest"] = sha256(canonical_bytes(contract)).hexdigest()
    return contract


def _schema_allows_null(schema: Mapping[str, Any]) -> bool:
    value = schema.get("type")
    return value == "null" or (isinstance(value, list) and "null" in value)


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "array"
    return "unsupported"


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
    bounded_domains: Mapping[str, Any] | None = None,
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
    semantic_contract = checkpoint_input_semantic_contract(
        operation=operation,
        checkpoint_kind=checkpoint_kind,
        phase=phase,
        bounded_domains=bounded_domains,
    )
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
            "semantic_contract_schema_id": semantic_contract["schema_id"],
            "semantic_contract_schema_version": semantic_contract["schema_version"],
            "semantic_contract_digest": semantic_contract["contract_digest"],
        },
    }
    construction: dict[str, Any] = {
        "schema_id": CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_ID,
        "schema_version": CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_VERSION,
        "construction_mode": "checkpoint_input_transport",
        "fixed_payload": fixed_payload,
        "assistant_supplied_property": "fields",
        "semantic_field_contract": semantic_contract,
        "accepted_value_fields": deepcopy(semantic_contract["fields"]),
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


def _resolve_semantic_schema(
    schema: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
) -> Mapping[str, Any]:
    reference = schema.get("$ref")
    if reference is None:
        return schema
    if reference != "#/$defs/bounded_json":
        raise CurrentLoopError("checkpoint_input_semantic_reference_invalid")
    definitions = contract.get("$defs")
    resolved = definitions.get("bounded_json") if isinstance(definitions, Mapping) else None
    if not isinstance(resolved, Mapping):
        raise CurrentLoopError("checkpoint_input_semantic_reference_invalid")
    return resolved


def _semantic_failure(
    *,
    category: str,
    field_name: str,
    schema: Mapping[str, Any],
    value: object,
    contract: Mapping[str, Any],
    outside_enum: bool = False,
) -> None:
    raise CheckpointInputSemanticError(
        category,
        field_name=field_name,
        expected_contract=schema,
        received_value=value,
        semantic_contract=contract,
        outside_enum=outside_enum,
    )


def _validate_semantic_value(
    value: object,
    schema: Mapping[str, Any],
    *,
    field_name: str,
    contract: Mapping[str, Any],
    depth: int = 0,
) -> None:
    if depth > int(contract.get("maximum_depth") or CHECKPOINT_INPUT_MAX_DEPTH):
        _semantic_failure(
            category="checkpoint_input_semantic_depth_invalid",
            field_name=field_name,
            schema=schema,
            value=value,
            contract=contract,
        )
    schema = _resolve_semantic_schema(schema, contract=contract)
    variants = schema.get("oneOf")
    if isinstance(variants, list):
        for variant in variants:
            if not isinstance(variant, Mapping):
                continue
            try:
                _validate_semantic_value(
                    value,
                    variant,
                    field_name=field_name,
                    contract=contract,
                    depth=depth + 1,
                )
            except CheckpointInputSemanticError:
                continue
            return
        _semantic_failure(
            category="checkpoint_input_field_type_invalid",
            field_name=field_name,
            schema=schema,
            value=value,
            contract=contract,
        )
    expected = schema.get("type")
    allowed_types = [expected] if isinstance(expected, str) else expected
    actual = _json_type(value)
    if isinstance(allowed_types, list):
        compatible = actual in allowed_types or (actual == "integer" and "number" in allowed_types)
        if not compatible:
            _semantic_failure(
                category="checkpoint_input_field_type_invalid",
                field_name=field_name,
                schema=schema,
                value=value,
                contract=contract,
            )
    if "const" in schema and value != schema["const"]:
        _semantic_failure(
            category="checkpoint_input_field_domain_invalid",
            field_name=field_name,
            schema=schema,
            value=value,
            contract=contract,
            outside_enum=True,
        )
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        _semantic_failure(
            category="checkpoint_input_field_domain_invalid",
            field_name=field_name,
            schema=schema,
            value=value,
            contract=contract,
            outside_enum=True,
        )
    if isinstance(value, str):
        size = len(value.encode("utf-8"))
        if (
            size > int(schema.get("maxUtf8Bytes") or CHECKPOINT_INPUT_MAX_FIELD_BYTES)
            or (schema.get("minLength") and len(value) < int(schema["minLength"]))
            or "\x00" in value
            or _unsafe_text_control(value)
        ):
            _semantic_failure(
                category="checkpoint_input_field_size_or_control_invalid",
                field_name=field_name,
                schema=schema,
                value=value,
                contract=contract,
            )
        required_fragment = schema.get("containsUtf8")
        if isinstance(required_fragment, str) and required_fragment not in value:
            _semantic_failure(
                category="checkpoint_input_field_domain_invalid",
                field_name=field_name,
                schema=schema,
                value=value,
                contract=contract,
                outside_enum=True,
            )
    if isinstance(value, Mapping):
        minimum = int(schema.get("minProperties") or 0)
        maximum = int(schema.get("maxProperties") or CHECKPOINT_INPUT_MAX_FIELDS)
        if not minimum <= len(value) <= maximum:
            _semantic_failure(
                category="checkpoint_input_field_collection_invalid",
                field_name=field_name,
                schema=schema,
                value=value,
                contract=contract,
            )
        properties = schema.get("properties")
        required = schema.get("required", [])
        if isinstance(required, list) and any(name not in value for name in required):
            _semantic_failure(
                category="checkpoint_input_field_required_key_missing",
                field_name=field_name,
                schema=schema,
                value=value,
                contract=contract,
            )
        property_map = properties if isinstance(properties, Mapping) else {}
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            if not isinstance(key, str) or not key or _unsafe_text_control(key):
                _semantic_failure(
                    category="checkpoint_input_field_key_invalid",
                    field_name=field_name,
                    schema=schema,
                    value=value,
                    contract=contract,
                )
            item_schema = property_map.get(key)
            if item_schema is None:
                if additional is False:
                    _semantic_failure(
                        category="checkpoint_input_field_extra_key_invalid",
                        field_name=field_name,
                        schema=schema,
                        value=value,
                        contract=contract,
                    )
                item_schema = additional if isinstance(additional, Mapping) else None
            if isinstance(item_schema, Mapping):
                _validate_semantic_value(
                    item,
                    item_schema,
                    field_name=f"{field_name}.{key}",
                    contract=contract,
                    depth=depth + 1,
                )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        minimum = int(schema.get("minItems") or 0)
        maximum = int(schema.get("maxItems") or CHECKPOINT_INPUT_MAX_FIELDS)
        if not minimum <= len(value) <= maximum:
            _semantic_failure(
                category="checkpoint_input_field_collection_invalid",
                field_name=field_name,
                schema=schema,
                value=value,
                contract=contract,
            )
        if schema.get("uniqueItems") is True:
            rendered = [canonical_bytes(item) for item in value]
            if len(rendered) != len(set(rendered)):
                _semantic_failure(
                    category="checkpoint_input_field_duplicate_item",
                    field_name=field_name,
                    schema=schema,
                    value=value,
                    contract=contract,
                )
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                _validate_semantic_value(
                    item,
                    item_schema,
                    field_name=f"{field_name}[{index}]",
                    contract=contract,
                    depth=depth + 1,
                )


def _validate_decision_dispositions(
    value: object,
    *,
    profile_id: object,
    field_contract: Mapping[str, Any],
    semantic_contract: Mapping[str, Any],
) -> None:
    if not isinstance(value, list) or not isinstance(profile_id, str):
        return
    schema = field_contract["schema"]
    variants = schema.get("profileVariants")
    selected = variants.get(profile_id) if isinstance(variants, Mapping) else None
    if not isinstance(selected, Mapping):
        _semantic_failure(
            category="checkpoint_input_field_domain_invalid",
            field_name="profile_id",
            schema={"type": "string", "enum": list(PROFILE_IDS)},
            value=profile_id,
            contract=semantic_contract,
            outside_enum=True,
        )
    decision_ids = selected.get("decision_ids")
    values_by_decision = selected.get("supported_values_by_decision")
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            continue
        decision_id = item.get("profile_decision_id")
        if not isinstance(decision_ids, list) or decision_id not in decision_ids:
            _semantic_failure(
                category="checkpoint_input_field_domain_invalid",
                field_name=f"decision_dispositions[{index}].profile_decision_id",
                schema={"type": "string", "enum": decision_ids or []},
                value=decision_id,
                contract=semantic_contract,
                outside_enum=True,
            )
        if decision_id in seen:
            _semantic_failure(
                category="checkpoint_input_field_duplicate_item",
                field_name=f"decision_dispositions[{index}].profile_decision_id",
                schema={"type": "string", "enum": decision_ids},
                value=decision_id,
                contract=semantic_contract,
            )
        seen.add(str(decision_id))
        disposition = item.get("user_disposition")
        selected_value = item.get("selected_value")
        if disposition == "selected_choice":
            domain = (
                values_by_decision.get(decision_id)
                if isinstance(values_by_decision, Mapping)
                else []
            )
            if not isinstance(selected_value, str) or (
                isinstance(domain, list) and domain and selected_value not in domain
            ):
                _semantic_failure(
                    category="checkpoint_input_field_domain_invalid",
                    field_name=f"decision_dispositions[{index}].selected_value",
                    schema={"type": "string", "enum": domain or None},
                    value=selected_value,
                    contract=semantic_contract,
                    outside_enum=True,
                )
        elif selected_value not in {None, "", "-"}:
            _semantic_failure(
                category="checkpoint_input_field_domain_invalid",
                field_name=f"decision_dispositions[{index}].selected_value",
                schema={"type": ["string", "null"], "enum": [None, "", "-"]},
                value=selected_value,
                contract=semantic_contract,
                outside_enum=True,
            )


def validate_checkpoint_semantic_fields(
    *,
    fields_by_name: Mapping[str, Mapping[str, Any]],
    semantic_contract: Mapping[str, Any],
) -> None:
    """Validate exact supplied values against the advertised promotion contract."""

    contracts = semantic_contract.get("fields")
    if not isinstance(contracts, list):
        raise CurrentLoopError("checkpoint_input_semantic_contract_invalid")
    by_name = {item.get("name"): item for item in contracts if isinstance(item, Mapping)}
    missing = {
        str(item["name"])
        for item in contracts
        if isinstance(item, Mapping)
        and (item.get("required") is True or item.get("conditionally_required") is True)
        and item.get("name") not in fields_by_name
    }
    if missing:
        first = sorted(missing)[0]
        contract = by_name[first]
        raise CheckpointInputSemanticError(
            "checkpoint_input_required_field_missing",
            field_name=first,
            expected_contract=contract["schema"],
            received_value=None,
            semantic_contract=semantic_contract,
        )
    for name, supplied in fields_by_name.items():
        field_contract = by_name.get(name)
        if not isinstance(field_contract, Mapping):
            raise CurrentLoopError("checkpoint_input_field_unsupported")
        schema = field_contract.get("schema")
        if not isinstance(schema, Mapping):
            raise CurrentLoopError("checkpoint_input_semantic_contract_invalid")
        _validate_semantic_value(
            supplied.get("value"),
            schema,
            field_name=name,
            contract=semantic_contract,
        )
    decision = fields_by_name.get("decision_dispositions")
    if isinstance(decision, Mapping):
        profile = fields_by_name.get("profile_id")
        _validate_decision_dispositions(
            decision.get("value"),
            profile_id=(profile.get("value") if isinstance(profile, Mapping) else None),
            field_contract=by_name["decision_dispositions"],
            semantic_contract=semantic_contract,
        )
    requested_posture = fields_by_name.get("requested_generation_posture")
    posture_contract = by_name.get("requested_generation_posture")
    posture_schema = (
        posture_contract.get("schema") if isinstance(posture_contract, Mapping) else None
    )
    if (
        isinstance(requested_posture, Mapping)
        and isinstance(posture_schema, Mapping)
        and requested_posture.get("value") != posture_schema.get("currentBoundValue")
    ):
        for required_name in (
            "posture_change_reason",
            "posture_authority_provenance",
        ):
            if required_name not in fields_by_name:
                field_contract = by_name[required_name]
                raise CheckpointInputSemanticError(
                    "checkpoint_input_required_field_missing",
                    field_name=required_name,
                    expected_contract=field_contract["schema"],
                    received_value=None,
                    semantic_contract=semantic_contract,
                )
    if semantic_contract.get("operation") == "propose_change":
        decision_ref = fields_by_name.get("decision_ref", {}).get("value")
        proposed_value = fields_by_name.get("proposed_value", {}).get("value")
        proposed_contract = by_name.get("proposed_value")
        proposed_schema = (
            proposed_contract.get("schema") if isinstance(proposed_contract, Mapping) else None
        )
        domains = (
            proposed_schema.get("domainByDecisionRef")
            if isinstance(proposed_schema, Mapping)
            else None
        )
        domain = domains.get(decision_ref) if isinstance(domains, Mapping) else None
        if isinstance(domain, list) and domain and proposed_value not in domain:
            _semantic_failure(
                category="checkpoint_input_field_domain_invalid",
                field_name="proposed_value",
                schema={"enum": domain},
                value=proposed_value,
                contract=semantic_contract,
                outside_enum=True,
            )


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
    semantic_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate assistant-created input and bind it to one exact local checkpoint."""

    schema_id = payload.get("schema_id")
    schema_version = payload.get("schema_version")
    legacy_versions = {
        "qcoder.current_loop.checkpoint_input.v1": 1,
        "qcoder.current_loop.checkpoint_input.v2": 2,
    }
    legacy = (
        schema_id in PREVIOUS_CHECKPOINT_INPUT_SCHEMA_IDS
        and legacy_versions.get(str(schema_id)) == schema_version
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
        semantic_contract = (
            deepcopy(dict(semantic_contract))
            if isinstance(semantic_contract, Mapping)
            else checkpoint_input_semantic_contract(
                operation=operation,
                checkpoint_kind=checkpoint_kind,
                phase=phase,
            )
        )
        binding = payload.get("binding")
        expected_binding = {
            "operation": operation,
            "checkpoint_kind": checkpoint_kind,
            "phase": phase,
            "loop_ref": loop_ref,
            "workspace_binding": _workspace_binding_digest(workspace_binding),
            "expected_state_revision": source_state_revision,
            "semantic_contract_schema_id": semantic_contract["schema_id"],
            "semantic_contract_schema_version": semantic_contract["schema_version"],
            "semantic_contract_digest": semantic_contract["contract_digest"],
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
    else:
        semantic_contract = (
            deepcopy(dict(semantic_contract))
            if isinstance(semantic_contract, Mapping)
            else checkpoint_input_semantic_contract(
                operation=operation,
                checkpoint_kind=checkpoint_kind,
                phase=phase,
            )
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

    validate_checkpoint_semantic_fields(
        fields_by_name=by_name,
        semantic_contract=semantic_contract,
    )
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
            "semantic_contract_schema_id": semantic_contract["schema_id"],
            "semantic_contract_schema_version": semantic_contract["schema_version"],
            "semantic_contract_digest": semantic_contract["contract_digest"],
        },
        "operation": operation,
        "checkpoint_kind": checkpoint_kind,
        "fields": canonical_fields,
        "semantic_contract": {
            "schema_id": semantic_contract["schema_id"],
            "schema_version": semantic_contract["schema_version"],
            "contract_digest": semantic_contract["contract_digest"],
        },
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
        "semantic_contract_schema_id": semantic_contract["schema_id"],
        "semantic_contract_schema_version": semantic_contract["schema_version"],
        "semantic_contract_digest": semantic_contract["contract_digest"],
        "semantic_contract_snapshot": deepcopy(dict(semantic_contract)),
        "status": "pending",
        "review_state": "pending_exact_input_review",
    }


def checkpoint_input_values(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return exact staged values after validating the record digest."""

    current = (
        record.get("schema_id") == CHECKPOINT_INPUT_SCHEMA_ID
        and record.get("schema_version") == CHECKPOINT_INPUT_SCHEMA_VERSION
    )
    legacy_versions = {
        "qcoder.current_loop.checkpoint_input.v1": 1,
        "qcoder.current_loop.checkpoint_input.v2": 2,
    }
    legacy = record.get(
        "schema_id"
    ) in PREVIOUS_CHECKPOINT_INPUT_SCHEMA_IDS and legacy_versions.get(
        str(record.get("schema_id"))
    ) == record.get("schema_version")
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
        projection["semantic_contract"] = record.get("semantic_contract")
    if sha256(canonical_bytes(projection)).hexdigest() != record.get("content_digest"):
        raise CurrentLoopError("checkpoint_input_digest_mismatch")
    values: dict[str, Any] = {}
    for field in fields:
        if not isinstance(field, Mapping) or not isinstance(field.get("name"), str):
            raise CurrentLoopError("checkpoint_input_record_invalid")
        values[str(field["name"])] = deepcopy(field.get("value"))
    if current:
        snapshot = record.get("semantic_contract_snapshot")
        if not isinstance(snapshot, Mapping):
            raise CurrentLoopError("checkpoint_input_semantic_contract_stale")
        semantic_contract = deepcopy(dict(snapshot))
        digest_projection = deepcopy(dict(semantic_contract))
        supplied_digest = digest_projection.pop("contract_digest", None)
        if sha256(canonical_bytes(digest_projection)).hexdigest() != supplied_digest:
            raise CurrentLoopError("checkpoint_input_semantic_contract_mismatch")
        if (
            record.get("semantic_contract_schema_id") != semantic_contract["schema_id"]
            or record.get("semantic_contract_schema_version") != semantic_contract["schema_version"]
            or record.get("semantic_contract_digest") != supplied_digest
        ):
            raise CurrentLoopError("checkpoint_input_semantic_contract_stale")
        validate_checkpoint_semantic_fields(
            fields_by_name={
                str(field["name"]): field
                for field in fields
                if isinstance(field, Mapping) and isinstance(field.get("name"), str)
            },
            semantic_contract=semantic_contract,
        )
    return values


def checkpoint_input_contract_snapshot() -> dict[str, Any]:
    semantic_rows = (
        ("prepare_generation", "intent_review", "intent_review"),
        ("prepare_generation", "decision_resolution", "intent_review"),
        ("prepare_generation", "posture", "intent_review"),
        (
            "continue_unchanged",
            "governing_change_confirmation",
            "continuation_choice",
        ),
        ("propose_change", "governing_change_confirmation", "continuation_choice"),
        ("confirm_change", "governing_change_confirmation", "change_confirmation"),
    )
    return {
        "schema_id": CHECKPOINT_INPUT_SCHEMA_ID,
        "schema_version": CHECKPOINT_INPUT_SCHEMA_VERSION,
        "construction_schema_id": CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_ID,
        "construction_schema_version": CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_VERSION,
        "previous_compatibility_schema_ids": sorted(PREVIOUS_CHECKPOINT_INPUT_SCHEMA_IDS),
        "semantic_contract_schema_id": CHECKPOINT_INPUT_SEMANTIC_SCHEMA_ID,
        "semantic_contract_schema_version": CHECKPOINT_INPUT_SEMANTIC_SCHEMA_VERSION,
        "operations": list(CHECKPOINT_INPUT_OPERATIONS),
        "operation_fields": {
            operation: {
                "accepted": sorted(_OPERATION_FIELDS[operation]),
                "required": sorted(_REQUIRED_OPERATION_FIELDS[operation]),
                "checkpoint_kinds": sorted(_CHECKPOINT_KINDS_BY_OPERATION[operation]),
            }
            for operation in CHECKPOINT_INPUT_OPERATIONS
        },
        "semantic_field_inventory": {
            f"{operation}/{checkpoint_kind}": checkpoint_input_semantic_contract(
                operation=operation,
                checkpoint_kind=checkpoint_kind,
                phase=phase,
            )
            for operation, checkpoint_kind, phase in semantic_rows
        },
        "transports": ["stdin", "file"],
        "maximum_transport_bytes": CHECKPOINT_INPUT_MAX_BYTES,
        "maximum_fields": CHECKPOINT_INPUT_MAX_FIELDS,
        "maximum_field_bytes": CHECKPOINT_INPUT_MAX_FIELD_BYTES,
        "approval_only_promotion": True,
        "content_and_approval_same_invocation": False,
        "shell_literal_free_text_required": False,
    }
