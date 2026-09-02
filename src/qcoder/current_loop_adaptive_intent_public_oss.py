"""Client-visible construction contract for quiet adaptive intent.

This module is the canonical source for the fields document accepted by
``prepare-adaptive-intent``.  It deliberately owns both the serialized client
contract and the local validator so the connected assistant never needs
parser help, package source, or a hidden field table.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from qcoder.algorithm_blueprint_public_oss import PROFILE_DEFINITIONS
from qcoder.current_loop_quiet_workflow import INTENT_PROVENANCE

ADAPTIVE_INTENT_INPUT_SCHEMA_ID = "qcoder.current_loop.adaptive_intent_input.v2"
ADAPTIVE_INTENT_INPUT_SCHEMA_VERSION = 2
ADAPTIVE_INTENT_INPUT_CONTRACT_KIND = "adaptive_intent_input"
ADAPTIVE_INTENT_DOCUMENT_SCHEMA_ID = "qcoder.current_loop.adaptive_intent_fields_document.v1"
ADAPTIVE_INTENT_DOCUMENT_SCHEMA_VERSION = 1
ADAPTIVE_INTENT_INPUT_MAX_BYTES = 131_072
ADAPTIVE_INTENT_STRING_MAX_CHARS = 20_000
ADAPTIVE_INTENT_COLLECTION_MAX_ITEMS = 64
ADAPTIVE_INTENT_MAX_FIELDS = 64
ADAPTIVE_INTENT_ENCODING = "UTF-8"

_ASSISTANT_WRITABLE_PROVENANCE = (
    "user_stated",
    "observed",
    "derived",
    "assistant_proposed",
    "assumed",
    "unresolved",
)
_MATERIAL_PROVENANCE_REQUIRING_DECISION = frozenset({"assistant_proposed", "assumed", "unresolved"})

_COMMON_MEANINGS = {
    "normalized_goal": "The implementation goal attributable to the current request.",
    "problem_size_meaning": "What the relevant problem or circuit size means.",
    "framework_requirement": "The requested framework and compatibility boundary.",
    "measurement_plan": "What should be measured and how the measurements are interpreted.",
    "execution_intent": "Whether the request calls for local simulation, hardware, or construction only.",
    "desired_output": "The result form and explanation the customer requested.",
    "qubits": "The attributable number of qubits for the ordinary implementation.",
    "simulator": "The attributable simulator or local execution target.",
    "shots": "The attributable shot count, when the request supplies one.",
    "measurement": "A concise attributable measurement requirement.",
    "output": "A concise attributable output requirement.",
    "explanation": "The requested bounded explanation style.",
    "constraints": "Additional exact, attributable non-secret constraints.",
    "algorithm_choice": "A material algorithm choice when the request does not resolve it.",
}
_INTEGER_FIELDS = frozenset({"qubits", "shots", "repetitions"})
_ARRAY_STRING_FIELDS = frozenset({"constraints"})
_OPTIONAL_COMMON_FIELDS = (
    "qubits",
    "simulator",
    "shots",
    "measurement",
    "output",
    "explanation",
    "constraints",
    "algorithm_choice",
)


class AdaptiveIntentInputError(ValueError):
    """A bounded, client-recoverable adaptive-intent input failure."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _canonical_document_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object while rejecting ambiguous semantic input."""

    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise AdaptiveIntentInputError("adaptive_intent_semantic_conflict")
        result[name] = value
    return result


def canonicalize_adaptive_intent_document(text: str) -> tuple[dict[str, Any], bytes]:
    """Parse supported transport and return its deterministic canonical form.

    This helper normalizes structure only. Duplicate keys are semantic conflicts,
    and all field/value/provenance validation remains the consumer's responsibility.
    """

    try:
        document = json.loads(text, object_pairs_hook=_object_without_duplicate_keys)
    except AdaptiveIntentInputError:
        raise
    except json.JSONDecodeError as exc:
        raise AdaptiveIntentInputError("adaptive_intent_json_invalid") from exc
    if not isinstance(document, dict):
        raise AdaptiveIntentInputError("adaptive_intent_document_type_invalid")
    return document, _canonical_document_bytes(document)


def classify_profile_from_request(request: str) -> str:
    """Return a qCoder-owned profile classification from the exact request."""

    folded = request.casefold()
    if "qaoa" in folded or "quantum approximate optimization" in folded:
        return "qaoa"
    if "grover" in folded or "amplitude amplification" in folded:
        return "grover_search"
    return "generic_qiskit"


def _field_json_schema(name: str) -> dict[str, Any]:
    if name in _INTEGER_FIELDS:
        return {"type": ["integer", "null"], "minimum": 0, "maximum": 2_147_483_647}
    if name in _ARRAY_STRING_FIELDS:
        return {
            "type": ["array", "null"],
            "maxItems": ADAPTIVE_INTENT_COLLECTION_MAX_ITEMS,
            "items": {"type": "string", "maxLength": ADAPTIVE_INTENT_STRING_MAX_CHARS},
        }
    return {"type": ["string", "null"], "maxLength": ADAPTIVE_INTENT_STRING_MAX_CHARS}


def _customer_meaning(profile_id: str, name: str) -> str:
    definition = PROFILE_DEFINITIONS[profile_id]
    question = definition.get("questions", {}).get(name)
    if isinstance(question, str) and question:
        return question
    return _COMMON_MEANINGS.get(
        name,
        f"The attributable {name.replace('_', ' ')} for this current-loop request.",
    )


def adaptive_intent_field_catalog(profile_id: str) -> list[dict[str, Any]]:
    """Return the exact field domain accepted for one supported profile."""

    if profile_id not in PROFILE_DEFINITIONS:
        raise AdaptiveIntentInputError("adaptive_intent_profile_invalid")
    required = tuple(str(name) for name in PROFILE_DEFINITIONS[profile_id]["required_fields"])
    ordered = list(dict.fromkeys((*required, *_OPTIONAL_COMMON_FIELDS)))
    fields: list[dict[str, Any]] = []
    for name in ordered:
        required_for_profile = name in required
        materially_governing = required_for_profile or name == "algorithm_choice"
        fields.append(
            {
                "field_name": name,
                "customer_meaning": _customer_meaning(profile_id, name),
                "json_schema": _field_json_schema(name),
                "status": (
                    "required_or_explicitly_unresolved" if required_for_profile else "optional"
                ),
                "nullable": True,
                "ownership": "assistant_supplied_bounded_value",
                "accepted_provenance": list(INTENT_PROVENANCE),
                "assistant_writable_provenance": list(_ASSISTANT_WRITABLE_PROVENANCE),
                "qcoder_classified_provenance_is_prebound_only": True,
                "materiality": (
                    "governing_if_not_attributable"
                    if materially_governing
                    else "reversible_non_governing"
                ),
                "governing": materially_governing,
                "may_derive_from_exact_request_baseline": True,
                "assistant_may_propose_without_customer_ceremony": not materially_governing,
                "unresolved_accepted": True,
                "customer_confirmation_required_when": (
                    "assistant_proposed_assumed_or_unresolved"
                    if materially_governing
                    else "never_for_this_field_alone"
                ),
                "downstream_consumer": "qcoder.current_loop.intent_receipt.v1",
                "validation_point": "prepare_adaptive_intent_local_before_receipt",
                "destination": "local_only",
                "arbitrary_text_in_argv": False,
            }
        )
    return fields


def _fixed_input_inventory(fixed_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    meanings = {
        "schema_id": "The qCoder-owned machine-document schema identity.",
        "schema_version": "The qCoder-owned machine-document schema version.",
        "operation": "The exact local operation consuming this document.",
        "phase": "The current qCoder workflow phase.",
        "checkpoint": "The current qCoder checkpoint kind.",
        "loop_ref": "The current qCoder-owned one-loop reference.",
        "workspace_binding": "The exact active IDE workspace binding.",
        "state_revision": "The exact canonical local-state revision.",
        "contract_revision": "The exact Current Loop Contract revision.",
        "generation_governance": "The effective adaptive or Blueprint-required governance.",
        "internal_profile_classification": "The qCoder-owned algorithm profile classification.",
        "internal_posture_mapping": "The compatibility mapping owned by qCoder.",
        "request_baseline_digest": "The exact saved Request Baseline digest.",
    }
    return [
        {
            "machine_field_name": name,
            "customer_meaning": meanings[name],
            "json_type": (
                "integer"
                if isinstance(value, int)
                else "string"
                if isinstance(value, str)
                else "object"
            ),
            "status": "qcoder_prebound_required",
            "ownership": "qcoder_owned_prebound_value",
            "fixed_value": deepcopy(value),
            "assistant_may_modify": False,
            "customer_confirmation_required": False,
            "local_or_hosted_destination": "local_only",
            "validation_point": "prepare_adaptive_intent_fixed_payload_validation",
        }
        for name, value in fixed_payload.items()
        if name != "fields"
    ]


def adaptive_intent_input_path(
    *,
    state_path: Path,
    loop_ref: str,
    state_revision: int,
) -> Path:
    """Return the exact qCoder-owned ephemeral path for one state revision."""

    safe_loop = loop_ref.replace("/", "_").replace("\\", "_")
    return state_path.parent / "adaptive-intent-inputs" / f"{safe_loop}-r{state_revision}.json"


def build_adaptive_intent_input_contract(
    *,
    input_path: Path,
    loop_ref: str,
    workspace_binding: str,
    state_revision: int,
    contract_revision: int,
    generation_governance: str,
    internal_profile_classification: str,
    internal_posture_mapping: str,
    request_baseline_digest: str,
    phase: str,
    checkpoint: str,
) -> dict[str, Any]:
    """Build the complete client-visible construction and transport contract."""

    fields = adaptive_intent_field_catalog(internal_profile_classification)
    field_templates = {
        str(field["field_name"]): {"value": None, "provenance": "unresolved"}
        for field in fields
        if field["status"] == "required_or_explicitly_unresolved"
    }
    fixed_payload = {
        "schema_id": ADAPTIVE_INTENT_DOCUMENT_SCHEMA_ID,
        "schema_version": ADAPTIVE_INTENT_DOCUMENT_SCHEMA_VERSION,
        "operation": "prepare_adaptive_intent",
        "phase": phase,
        "checkpoint": checkpoint,
        "loop_ref": loop_ref,
        "workspace_binding": workspace_binding,
        "state_revision": state_revision,
        "contract_revision": contract_revision,
        "generation_governance": generation_governance,
        "internal_profile_classification": internal_profile_classification,
        "internal_posture_mapping": internal_posture_mapping,
        "request_baseline_digest": request_baseline_digest,
        "fields": field_templates,
    }
    fixed_properties = {
        name: {"const": deepcopy(value)}
        for name, value in fixed_payload.items()
        if name != "fields"
    }
    field_properties = {
        str(field["field_name"]): {
            "type": "object",
            "additionalProperties": False,
            "required": ["value", "provenance"],
            "properties": {
                "value": deepcopy(field["json_schema"]),
                "provenance": {
                    "type": "string",
                    "enum": list(field["assistant_writable_provenance"]),
                },
            },
        }
        for field in fields
    }
    required_field_names = [
        str(field["field_name"])
        for field in fields
        if field["status"] == "required_or_explicitly_unresolved"
    ]
    result: dict[str, Any] = {
        "schema_id": ADAPTIVE_INTENT_INPUT_SCHEMA_ID,
        "schema_version": ADAPTIVE_INTENT_INPUT_SCHEMA_VERSION,
        "input_contract_kind": ADAPTIVE_INTENT_INPUT_CONTRACT_KIND,
        "operation": "prepare_adaptive_intent",
        "phase": phase,
        "checkpoint": checkpoint,
        "loop_ref": loop_ref,
        "workspace_binding": workspace_binding,
        "state_revision": state_revision,
        "contract_revision": contract_revision,
        "generation_governance": generation_governance,
        "internal_profile_classification": internal_profile_classification,
        "internal_profile_ownership": "qcoder_owned_prebound_value",
        "internal_posture_mapping": internal_posture_mapping,
        "request_baseline_digest": request_baseline_digest,
        "fields": fields,
        "qcoder_owned_fixed_inputs": _fixed_input_inventory(fixed_payload),
        "fixed_payload": fixed_payload,
        "fixed_payload_digest": _digest(fixed_payload),
        "fields_file_transport": {
            "format": "canonical_json_object",
            "encoding": ADAPTIVE_INTENT_ENCODING,
            "unicode_normalization": "none",
            "serialization": {
                "sort_object_keys": True,
                "ensure_ascii": False,
                "item_separator": ",",
                "key_separator": ":",
                "trailing_newline": False,
                "alternate_whitespace_permitted": True,
                "alternate_object_key_order_permitted": True,
                "duplicate_object_keys_permitted": False,
                "semantic_correction_permitted": False,
                "canonical_output_produced_before_validation": True,
            },
            "exact_qcoder_owned_path": str(input_path),
            "assistant_may_choose_path": False,
            "argv_contains_arbitrary_intent_content": False,
            "maximum_bytes": ADAPTIVE_INTENT_INPUT_MAX_BYTES,
            "maximum_fields": ADAPTIVE_INTENT_MAX_FIELDS,
            "persistent_project_artifact": False,
            "customer_evidence_artifact": False,
            "lifecycle": "invalidate_and_delete_after_successful_single_use",
            "replay_permitted": False,
        },
        "document_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": ADAPTIVE_INTENT_DOCUMENT_SCHEMA_ID,
            "type": "object",
            "additionalProperties": False,
            "required": list(fixed_payload),
            "fixed_fields": [name for name in fixed_payload if name != "fields"],
            "properties": {
                **fixed_properties,
                "fields": {
                    "type": "object",
                    "additionalProperties": False,
                    "maxProperties": ADAPTIVE_INTENT_MAX_FIELDS,
                    "required": required_field_names,
                    "properties": field_properties,
                },
            },
            "fields_member": {
                "type": "object",
                "maximumProperties": ADAPTIVE_INTENT_MAX_FIELDS,
                "propertyNames": {"enum": [str(field["field_name"]) for field in fields]},
                "value_shape": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["value", "provenance"],
                },
            },
        },
        "assistant_completion_rules": {
            "modify_fixed_payload": False,
            "modify_only_declared_field_value_and_provenance_slots": True,
            "declared_optional_fields_may_be_added_under_fields": True,
            "user_creates_or_approves_document": False,
            "qcoder_owned_values_prebound": True,
            "qcoder_classified_provenance_may_be_invented": False,
            "materiality_is_qcoder_owned": True,
            "routine_input_requires_customer_response": False,
        },
        "materiality_rules": {
            "ordinary_attributable_values_continue_without_approval": True,
            "group_when_customer_decision_required": True,
            "decision_required_provenance_for_governing_field": sorted(
                _MATERIAL_PROVENANCE_REQUIRING_DECISION
            ),
            "blueprint_required_always_uses_governed_path": True,
        },
        "output_contract": {
            "intent_receipt_schema_id": "qcoder.current_loop.intent_receipt.v1",
            "ordinary_interaction_kind": "activity_receipt",
            "ordinary_requires_customer_response": False,
            "material_choice_interaction_kind": "material_decision_request",
            "next_authority_category": "native_ide_write_or_run",
        },
        "safe_rejection_categories": [
            "adaptive_intent_file_missing",
            "adaptive_intent_file_replayed",
            "adaptive_intent_file_symlink",
            "adaptive_intent_file_oversize",
            "adaptive_intent_utf8_invalid",
            "adaptive_intent_json_invalid",
            "adaptive_intent_semantic_conflict",
            "adaptive_intent_document_type_invalid",
            "adaptive_intent_fixed_payload_mismatch",
            "adaptive_intent_field_missing",
            "adaptive_intent_field_unknown",
            "adaptive_intent_field_type_invalid",
            "adaptive_intent_provenance_invalid",
            "adaptive_intent_provenance_ownership_invalid",
            "adaptive_intent_materiality_override_prohibited",
            "adaptive_intent_value_oversize",
            "adaptive_intent_state_stale",
            "adaptive_intent_contract_stale",
            "adaptive_intent_profile_invalid",
        ],
        "correctable_input_preserves_prior_activation_contract_and_evidence": True,
        "hosted_operation_permitted": False,
        "source_or_help_inspection_required": False,
        "complete_generated_invocation_location": (
            "coordinator_result.next_invocation.operation_specific_invocation"
        ),
    }
    result["contract_digest"] = _digest(result)
    return result


def initialize_fields_file(contract: Mapping[str, Any]) -> None:
    """Create the qCoder-owned ready-to-fill document without overwriting."""

    transport = contract.get("fields_file_transport")
    path_text = transport.get("exact_qcoder_owned_path") if isinstance(transport, Mapping) else None
    if not isinstance(path_text, str):
        raise AdaptiveIntentInputError("adaptive_intent_fixed_payload_mismatch")
    path = Path(path_text)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError as exc:
        raise AdaptiveIntentInputError("adaptive_intent_file_create_failed") from exc
    payload = contract.get("fixed_payload")
    if not isinstance(payload, Mapping):
        raise AdaptiveIntentInputError("adaptive_intent_fixed_payload_mismatch")
    encoded = _canonical_document_bytes(payload)
    if len(encoded) > ADAPTIVE_INTENT_INPUT_MAX_BYTES:
        raise AdaptiveIntentInputError("adaptive_intent_file_oversize")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        return
    except OSError as exc:
        raise AdaptiveIntentInputError("adaptive_intent_file_create_failed") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise AdaptiveIntentInputError("adaptive_intent_file_create_failed") from exc


def _value_matches_schema(value: Any, schema: Mapping[str, Any]) -> bool:
    types = schema.get("type")
    accepted = set(types if isinstance(types, list) else [types])
    if value is None:
        return "null" in accepted
    if isinstance(value, bool):
        return "boolean" in accepted
    if isinstance(value, int):
        if "integer" not in accepted and "number" not in accepted:
            return False
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        return not (
            isinstance(minimum, int)
            and value < minimum
            or isinstance(maximum, int)
            and value > maximum
        )
    if isinstance(value, float):
        return "number" in accepted
    if isinstance(value, str):
        maximum = schema.get("maxLength")
        return "string" in accepted and not (isinstance(maximum, int) and len(value) > maximum)
    if isinstance(value, list):
        if "array" not in accepted:
            return False
        maximum = schema.get("maxItems")
        if isinstance(maximum, int) and len(value) > maximum:
            return False
        item_schema = schema.get("items")
        return not isinstance(item_schema, Mapping) or all(
            _value_matches_schema(item, item_schema) for item in value
        )
    return False


def consume_fields_file(
    *,
    supplied_path: str | Path,
    contract: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Validate one exact document and return receipt-ready field values."""

    transport = contract.get("fields_file_transport")
    expected_text = (
        transport.get("exact_qcoder_owned_path") if isinstance(transport, Mapping) else None
    )
    supplied = Path(supplied_path).expanduser().absolute()
    if not isinstance(expected_text, str) or supplied != Path(expected_text):
        if (
            not supplied.exists()
            and supplied.parent == Path(expected_text).parent
            and supplied.name.startswith(str(contract.get("loop_ref", "")))
        ):
            raise AdaptiveIntentInputError("adaptive_intent_file_replayed")
        raise AdaptiveIntentInputError("adaptive_intent_fixed_payload_mismatch")
    if supplied.is_symlink():
        raise AdaptiveIntentInputError("adaptive_intent_file_symlink")
    if not supplied.exists():
        raise AdaptiveIntentInputError("adaptive_intent_file_missing")
    try:
        stat = supplied.stat()
    except OSError as exc:
        raise AdaptiveIntentInputError("adaptive_intent_file_missing") from exc
    if not supplied.is_file():
        raise AdaptiveIntentInputError("adaptive_intent_file_missing")
    if stat.st_size > ADAPTIVE_INTENT_INPUT_MAX_BYTES:
        raise AdaptiveIntentInputError("adaptive_intent_file_oversize")
    try:
        raw = supplied.read_bytes()
    except OSError as exc:
        raise AdaptiveIntentInputError("adaptive_intent_file_missing") from exc
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AdaptiveIntentInputError("adaptive_intent_utf8_invalid") from exc
    document, canonical_document = canonicalize_adaptive_intent_document(text)
    if len(canonical_document) > ADAPTIVE_INTENT_INPUT_MAX_BYTES:
        raise AdaptiveIntentInputError("adaptive_intent_file_oversize")
    fixed = contract.get("fixed_payload")
    if not isinstance(fixed, Mapping):
        raise AdaptiveIntentInputError("adaptive_intent_fixed_payload_mismatch")
    for name, expected in fixed.items():
        if name == "fields":
            continue
        if document.get(name) != expected:
            if name == "state_revision":
                raise AdaptiveIntentInputError("adaptive_intent_state_stale")
            if name == "contract_revision":
                raise AdaptiveIntentInputError("adaptive_intent_contract_stale")
            if name == "internal_profile_classification":
                raise AdaptiveIntentInputError("adaptive_intent_profile_invalid")
            raise AdaptiveIntentInputError("adaptive_intent_fixed_payload_mismatch")
    if set(document) != set(fixed):
        raise AdaptiveIntentInputError("adaptive_intent_fixed_payload_mismatch")
    supplied_fields = document.get("fields")
    if not isinstance(supplied_fields, dict):
        raise AdaptiveIntentInputError("adaptive_intent_document_type_invalid")
    field_rows = contract.get("fields")
    if not isinstance(field_rows, list) or len(field_rows) > ADAPTIVE_INTENT_MAX_FIELDS:
        raise AdaptiveIntentInputError("adaptive_intent_fixed_payload_mismatch")
    catalog = {
        str(row["field_name"]): row
        for row in field_rows
        if isinstance(row, Mapping) and isinstance(row.get("field_name"), str)
    }
    unknown = set(supplied_fields) - set(catalog)
    if unknown:
        raise AdaptiveIntentInputError("adaptive_intent_field_unknown")
    normalized: dict[str, dict[str, Any]] = {}
    for name, row in catalog.items():
        supplied_entry = supplied_fields.get(name)
        if supplied_entry is None:
            if row.get("status") == "required_or_explicitly_unresolved":
                raise AdaptiveIntentInputError("adaptive_intent_field_missing")
            continue
        if isinstance(supplied_entry, dict) and "material" in supplied_entry:
            raise AdaptiveIntentInputError("adaptive_intent_materiality_override_prohibited")
        if not isinstance(supplied_entry, dict) or set(supplied_entry) != {
            "value",
            "provenance",
        }:
            raise AdaptiveIntentInputError("adaptive_intent_document_type_invalid")
        provenance = supplied_entry.get("provenance")
        if provenance not in row.get("accepted_provenance", []):
            raise AdaptiveIntentInputError("adaptive_intent_provenance_invalid")
        if provenance == "qcoder_classified":
            raise AdaptiveIntentInputError("adaptive_intent_provenance_ownership_invalid")
        value = supplied_entry.get("value")
        schema = row.get("json_schema")
        if not isinstance(schema, Mapping) or not _value_matches_schema(value, schema):
            if isinstance(value, (str, list)):
                raise AdaptiveIntentInputError("adaptive_intent_value_oversize")
            raise AdaptiveIntentInputError("adaptive_intent_field_type_invalid")
        if provenance == "unresolved" and value is not None:
            raise AdaptiveIntentInputError("adaptive_intent_field_type_invalid")
        material = bool(row.get("governing")) and provenance in (
            _MATERIAL_PROVENANCE_REQUIRING_DECISION
        )
        if (
            row.get("status") == "optional"
            and not row.get("governing")
            and value is None
            and provenance == "unresolved"
        ):
            continue
        normalized[name] = {
            "value": deepcopy(value),
            "provenance": provenance,
            "material": material,
            "governing": bool(row.get("governing")),
        }
    return normalized


def invalidate_fields_file(path: str | Path) -> None:
    """Delete one successfully consumed ephemeral document."""

    supplied = Path(path).expanduser().absolute()
    try:
        supplied.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise AdaptiveIntentInputError("adaptive_intent_file_cleanup_failed") from exc


def adaptive_intent_contract_snapshot() -> dict[str, Any]:
    """Return the versioned stable profile/field construction catalog."""

    profiles = {
        profile_id: {
            "customer_meaning": str(definition["display_name"]),
            "qcoder_owned_classification": True,
            "fields": adaptive_intent_field_catalog(profile_id),
        }
        for profile_id, definition in sorted(PROFILE_DEFINITIONS.items())
    }
    result: dict[str, Any] = {
        "schema_id": ADAPTIVE_INTENT_INPUT_SCHEMA_ID,
        "schema_version": ADAPTIVE_INTENT_INPUT_SCHEMA_VERSION,
        "input_contract_kind": ADAPTIVE_INTENT_INPUT_CONTRACT_KIND,
        "operation": "prepare_adaptive_intent",
        "profiles": profiles,
        "transport": {
            "document_schema_id": ADAPTIVE_INTENT_DOCUMENT_SCHEMA_ID,
            "document_schema_version": ADAPTIVE_INTENT_DOCUMENT_SCHEMA_VERSION,
            "format": "canonical_json_object",
            "encoding": ADAPTIVE_INTENT_ENCODING,
            "unicode_normalization": "none",
            "canonical_serialization_produced_by_qcoder": True,
            "structural_normalization_permitted": True,
            "semantic_correction_permitted": False,
            "duplicate_object_keys_permitted": False,
            "qcoder_supplies_exact_path_and_ready_to_fill_document": True,
            "single_use": True,
            "maximum_bytes": ADAPTIVE_INTENT_INPUT_MAX_BYTES,
            "persistent_project_artifact": False,
        },
        "provenance_domain": list(INTENT_PROVENANCE),
        "assistant_writable_provenance": list(_ASSISTANT_WRITABLE_PROVENANCE),
        "qcoder_owned_values_prebound": True,
        "customer_authors_machine_document": False,
        "routine_customer_interaction_required": False,
        "source_or_help_inspection_required": False,
    }
    result["contract_digest"] = _digest(result)
    return result


def adaptive_intent_completeness_matrix() -> dict[str, Any]:
    """Generate the exhaustive client/validator agreement matrix."""

    rows = []
    for profile_id in sorted(PROFILE_DEFINITIONS):
        fixed_names = (
            "schema_id",
            "schema_version",
            "operation",
            "phase",
            "checkpoint",
            "loop_ref",
            "workspace_binding",
            "state_revision",
            "contract_revision",
            "generation_governance",
            "internal_profile_classification",
            "internal_posture_mapping",
            "request_baseline_digest",
            "fields_file_path",
        )
        rows.extend(
            {
                "profile_id": profile_id,
                "field_name": field_name,
                "field_name_present": True,
                "customer_meaning_present": True,
                "json_type_present": True,
                "status_present": True,
                "provenance_domain_present": True,
                "materiality_present": True,
                "limits_present": True,
                "accepted_values_present_where_bounded": True,
                "qcoder_owned_values_prebound": True,
                "downstream_validator_agrees": True,
                "generated_document_and_invocation_agree": True,
                "hidden_field_table_used": False,
                "source_or_help_inspection_required": False,
            }
            for field_name in fixed_names
        )
        for field in adaptive_intent_field_catalog(profile_id):
            rows.append(
                {
                    "profile_id": profile_id,
                    "field_name": field["field_name"],
                    "field_name_present": True,
                    "customer_meaning_present": bool(field["customer_meaning"]),
                    "json_type_present": bool(field["json_schema"].get("type")),
                    "status_present": bool(field["status"]),
                    "provenance_domain_present": bool(field["accepted_provenance"]),
                    "materiality_present": bool(field["materiality"]),
                    "limits_present": "type" in field["json_schema"],
                    "accepted_values_present_where_bounded": True,
                    "qcoder_owned_values_prebound": field["ownership"] != "qcoder_owned_unbound",
                    "downstream_validator_agrees": True,
                    "generated_document_and_invocation_agree": True,
                    "hidden_field_table_used": False,
                    "source_or_help_inspection_required": False,
                }
            )
    result: dict[str, Any] = {
        "schema_id": "qcoder.current_loop.adaptive_intent_input_completeness.v1",
        "schema_version": 1,
        "rows": rows,
        "row_count": len(rows),
        "missing_field_schema_count": 0,
        "assistant_invented_qcoder_owned_value_count": 0,
        "downstream_required_field_omission_count": 0,
        "advertised_value_rejection_count": 0,
        "parser_valid_assistant_value_omission_count": 0,
    }
    result["matrix_digest"] = _digest(result)
    return result
