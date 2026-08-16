"""Client-visible bounded input contracts for local Current Loop controls.

The connected assistant receives these contracts and supplies only exact
customer selections.  Parser choices, policy validation, coordinator
transitions, evidence references, and recovery all consume the same canonical
domain constants; no second assistant-only policy language exists.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from qcoder.current_loop_contract import (
    ADJUSTMENT_DIMENSIONS,
    ADJUSTMENT_VALUES_BY_DIMENSION,
    EVIDENCE_CATEGORIES,
    EVIDENCE_EXCLUSION_REASONS,
    GENERATION_GOVERNANCE_VALUES,
    NAMED_PRESETS,
    CurrentLoopContractError,
    adjust,
    set_preset,
    validate_contract,
)
from qcoder.current_loop_event_receipts import (
    SUPPORTED_OPERATION_CATEGORIES,
    SUPPORTED_OUTPUT_ROLES,
)


BOUNDED_CONTROL_INPUT_SCHEMA_ID = "qcoder.current_loop.bounded_control_input.v1"
BOUNDED_CONTROL_INPUT_SCHEMA_VERSION = 1

CUSTOMER_SELECTS = "explicit_customer_bounded_selection"
QCODER_PREBINDS = "qcoder_owned_prebound_value"
EXACT_PATH_CHANNEL = "exact_literal_path_from_ide_operation_or_customer_selection"

PRESET_MEANINGS = {
    "evidence_only": (
        "Collect and organize explicitly authorized evidence locally. Share-safe derived "
        "context is available only on request; standing recommendations and preparation are off."
    ),
    "assist": (
        "Collect authorized evidence, derive local views, share selected share-safe derived "
        "context, recommend bounded checks, and prepare non-material summaries."
    ),
}
CATEGORY_MEANINGS = {
    "request_baseline": "The exact original customer request for this active loop.",
    "working_blueprint": "The governed goal, constraints, and material design choices.",
    "generation_context": "The confirmed context used for the current generation step.",
    "python_manifestation": "Exact registered Python source evidence.",
    "circuit_manifestation": "Exact registered circuit or QASM evidence.",
    "result_manifestation": "Exact registered execution-result evidence.",
    "lineage": "Attributable relationships among current-loop evidence.",
    "derived_metrics": "Share-safe measurements derived from authorized evidence.",
}
DIMENSION_MEANINGS = {
    "collect": "Allow qCoder to enroll exact authorized evidence in this loop.",
    "derive": "Allow qCoder to compute bounded local integrity or share-safe derived context.",
    "recommend": "Allow bounded recommendations from the current authorized context.",
    "prepare": "Allow bounded non-material summaries or next-check preparation.",
    "request_application_or_execution": (
        "Allow qCoder to ask for a separate application or execution approval; this grants none."
    ),
    "assistant_derived_exposure": (
        "Control share-safe derived context supplied to the connected assistant."
    ),
    "assistant_raw_exposure": (
        "Control raw evidence supplied to the connected assistant; contract.v1 keeps this off."
    ),
}
VALUE_MEANINGS = {
    "disabled": "Not permitted.",
    "enabled": "Permitted within the active contract and all separate authority ceilings.",
    "bounded_non_material": "Only reversible, non-governing summaries or next-check preparation.",
    "on_request": "Available only after an explicit current-loop request.",
    "standing": "Available as selected standing context for this active loop.",
}
EXCLUSION_REASON_MEANINGS = {
    "customer_excluded": "The customer does not want this evidence used going forward.",
    "privacy_narrowing": "Future use is narrowed for privacy.",
    "not_relevant": "The evidence is not relevant to the remaining current-loop work.",
}
PROVENANCE_VALUES = ("assistant_created", "assistant_modified", "user_selected")
GENERATION_GOVERNANCE_MEANINGS = {
    "adaptive": (
        "Adaptive — proceed quietly from exact customer intent and bounded reversible "
        "assumptions; interrupt only for a material decision or genuine blocker."
    ),
    "blueprint_required": (
        "Blueprint required — resolve and confirm governing material choices before generation."
    ),
}
_ADJUSTMENT_GRAPH_CACHE: dict[str, dict[str, Any]] = {}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _option(value: str, meaning: str, **extra: Any) -> dict[str, Any]:
    return {"value": value, "customer_meaning": meaning, **extra}


def current_adjustment_value(
    contract: Mapping[str, Any],
    *,
    category: str,
    dimension: str,
    _contract_is_validated: bool = False,
) -> str:
    """Return the exact CLI value representing the compiled current policy."""

    if not _contract_is_validated:
        validate_contract(contract)
    row = contract["effective_policy"]["categories"][category]
    if dimension in {"collect", "derive", "recommend", "request_application_or_execution"}:
        return "enabled" if row[dimension] is True else "disabled"
    if dimension == "prepare":
        return str(row["prepare"])
    if dimension == "assistant_derived_exposure":
        return str(row["expose"]["connected_assistant"]["derived"])
    if dimension == "assistant_raw_exposure":
        return str(row["expose"]["connected_assistant"]["raw"])
    raise CurrentLoopContractError("contract_dimension_invalid")


def _change_disposition_for_preset(contract: Mapping[str, Any], preset: str) -> str:
    outcome = set_preset(
        contract,
        preset=preset,
        expected_contract_revision=int(contract["contract_revision"]),
        provenance=(
            "customer_requested_narrowing"
            if preset == "evidence_only"
            else "explicit_customer_selection"
        ),
        _contract_is_validated=True,
    )
    return str(outcome["disposition"])


def _change_disposition_for_adjustment(
    contract: Mapping[str, Any],
    *,
    category: str,
    dimension: str,
    value: str,
) -> str:
    outcome = adjust(
        contract,
        category=category,
        dimension=dimension,
        value=value,
        expected_contract_revision=int(contract["contract_revision"]),
        provenance="explicit_customer_selection",
        _contract_is_validated=True,
    )
    return str(outcome["disposition"])


def preset_selection_contract(
    contract: Mapping[str, Any], *, _contract_is_validated: bool = False
) -> dict[str, Any]:
    if not _contract_is_validated:
        validate_contract(contract)
    options = []
    for preset in NAMED_PRESETS:
        disposition = _change_disposition_for_preset(contract, preset)
        options.append(
            _option(
                preset,
                PRESET_MEANINGS[preset],
                change_disposition=disposition,
                confirmation_required=disposition == "broadening",
            )
        )
    return {
        "operation": "contract_set_preset",
        "subcommand": "contract-set-preset",
        "current_preset": contract["effective_preset"],
        "fields": [
            {
                "name": "preset",
                "flag": "--preset",
                "ownership": CUSTOMER_SELECTS,
                "required": True,
                "json_type": "string",
                "accepted_values": options,
                "parser_mapping": "one_exact_cli_value",
                "arbitrary_text_prohibited": True,
            },
            {
                "name": "expected_contract_revision",
                "flag": "--expected-contract-revision",
                "ownership": QCODER_PREBINDS,
                "required": True,
                "json_type": "integer",
                "fixed_value": int(contract["contract_revision"]),
                "parser_mapping": "one_exact_cli_integer",
            },
        ],
        "off_disposition": {
            "advertised_as_preset_selection": False,
            "meaning": "Off means no active loop, not an all-false active contract.",
            "qcoder_operation": "abandon",
            "distinct_authority_only_control": "stop_loop",
        },
        "raw_policy_serialization_required": False,
    }


def adjustment_selection_contract(
    contract: Mapping[str, Any], *, _contract_is_validated: bool = False
) -> dict[str, Any]:
    if not _contract_is_validated:
        validate_contract(contract)
    cache_key = str(contract["effective_policy_digest"])
    cached = _ADJUSTMENT_GRAPH_CACHE.get(cache_key)
    if cached is not None:
        result = deepcopy(cached)
        for field in result["fields"]:
            if field["name"] == "expected_contract_revision":
                field["fixed_value"] = int(contract["contract_revision"])
        return result
    categories: list[dict[str, Any]] = []
    for category in EVIDENCE_CATEGORIES:
        dimensions: list[dict[str, Any]] = []
        for dimension in ADJUSTMENT_DIMENSIONS:
            values = []
            for value in ADJUSTMENT_VALUES_BY_DIMENSION[dimension]:
                disposition = _change_disposition_for_adjustment(
                    contract,
                    category=category,
                    dimension=dimension,
                    value=value,
                )
                values.append(
                    _option(
                        value,
                        VALUE_MEANINGS[value],
                        change_disposition=disposition,
                        confirmation_required=disposition == "broadening",
                    )
                )
            dimensions.append(
                {
                    "value": dimension,
                    "customer_meaning": DIMENSION_MEANINGS[dimension],
                    "current_value": current_adjustment_value(
                        contract,
                        category=category,
                        dimension=dimension,
                        _contract_is_validated=True,
                    ),
                    "accepted_values": values,
                }
            )
        categories.append(
            {
                "value": category,
                "customer_meaning": CATEGORY_MEANINGS[category],
                "dimensions": dimensions,
            }
        )
    result = {
        "operation": "contract_adjust",
        "subcommand": "contract-adjust",
        "fields": [
            {
                "name": "category",
                "flag": "--category",
                "ownership": CUSTOMER_SELECTS,
                "required": True,
                "json_type": "string",
                "accepted_values": [
                    _option(value, CATEGORY_MEANINGS[value]) for value in EVIDENCE_CATEGORIES
                ],
                "parser_mapping": "one_exact_cli_value",
                "arbitrary_text_prohibited": True,
            },
            {
                "name": "dimension",
                "flag": "--dimension",
                "ownership": CUSTOMER_SELECTS,
                "required": True,
                "json_type": "string",
                "accepted_values": [
                    _option(value, DIMENSION_MEANINGS[value]) for value in ADJUSTMENT_DIMENSIONS
                ],
                "selection_is_conditioned_by": "category",
                "parser_mapping": "one_exact_cli_value",
                "arbitrary_text_prohibited": True,
            },
            {
                "name": "value",
                "flag": "--value",
                "ownership": CUSTOMER_SELECTS,
                "required": True,
                "json_type": "string",
                "accepted_values": [
                    _option(value, VALUE_MEANINGS[value])
                    for value in sorted(
                        {
                            item
                            for values in ADJUSTMENT_VALUES_BY_DIMENSION.values()
                            for item in values
                        }
                    )
                ],
                "selection_is_conditioned_by": "category_and_dimension",
                "parser_mapping": "one_exact_cli_value",
                "arbitrary_text_prohibited": True,
            },
            {
                "name": "expected_contract_revision",
                "flag": "--expected-contract-revision",
                "ownership": QCODER_PREBINDS,
                "required": True,
                "json_type": "integer",
                "fixed_value": int(contract["contract_revision"]),
                "parser_mapping": "one_exact_cli_integer",
            },
        ],
        "valid_selection_graph": {"categories": categories},
        "independent_enum_cross_product_valid": False,
        "qcoder_classifies_broadening_or_narrowing": True,
        "raw_policy_serialization_required": False,
    }
    if len(_ADJUSTMENT_GRAPH_CACHE) >= 32:
        _ADJUSTMENT_GRAPH_CACHE.pop(next(iter(_ADJUSTMENT_GRAPH_CACHE)))
    _ADJUSTMENT_GRAPH_CACHE[cache_key] = deepcopy(result)
    return result


def generation_governance_selection_contract(
    contract: Mapping[str, Any], *, _contract_is_validated: bool = False
) -> dict[str, Any]:
    """Describe one compact, revision-bound generation-governance selection."""

    if not _contract_is_validated:
        validate_contract(contract)
    current = str(contract["generation_governance"])
    options = []
    for value in GENERATION_GOVERNANCE_VALUES:
        disposition = (
            "no_op"
            if value == current
            else (
                "broadening"
                if current == "blueprint_required" and value == "adaptive"
                else "narrowing"
            )
        )
        options.append(
            _option(
                value,
                GENERATION_GOVERNANCE_MEANINGS[value],
                change_disposition=disposition,
                confirmation_required=disposition == "broadening",
            )
        )
    return {
        "operation": "contract_set_generation_governance",
        "subcommand": "contract-set-generation-governance",
        "current_generation_governance": current,
        "fields": [
            {
                "name": "generation_governance",
                "flag": "--governance",
                "ownership": CUSTOMER_SELECTS,
                "required": True,
                "json_type": "string",
                "accepted_values": options,
                "parser_mapping": "one_exact_cli_value",
                "arbitrary_text_prohibited": True,
            },
            {
                "name": "expected_contract_revision",
                "flag": "--expected-contract-revision",
                "ownership": QCODER_PREBINDS,
                "required": True,
                "json_type": "integer",
                "fixed_value": int(contract["contract_revision"]),
                "parser_mapping": "one_exact_cli_integer",
            },
        ],
        "one_field_compact_operation": True,
        "narrowing_applies_immediately": True,
        "broadening_creates_pending_proposal": True,
        "broadening_confirmation_is_separate": True,
        "no_op_creates_revision_or_proposal": False,
        "raw_policy_replacement_prohibited": True,
        "editable_document_round_trip_required": False,
        "contract_status_preflight_required": False,
    }


def completion_control_contract(state: Mapping[str, Any]) -> dict[str, Any]:
    """Describe one exact-message ordinary loop-close route."""

    contract = state["current_loop_contract"]
    return {
        "operation": "complete_instruction",
        "subcommand": "complete-instruction",
        "fields": [
            {
                "name": "exact_current_customer_instruction",
                "flag": None,
                "transport": "stdin",
                "ownership": "exact_current_customer_message",
                "required": True,
                "json_type": "string",
                "minimum_utf8_bytes": 1,
                "maximum_utf8_bytes": 65_536,
                "assistant_reconstructs_or_paraphrases": False,
            },
            {
                "name": "instruction_stdin",
                "flag": "--instruction-stdin",
                "ownership": QCODER_PREBINDS,
                "required": True,
                "json_type": "boolean",
                "fixed_value": True,
            },
            {
                "name": "stop",
                "flag": "--stop",
                "ownership": QCODER_PREBINDS,
                "required": True,
                "json_type": "boolean",
                "fixed_value": True,
            },
            {
                "name": "expected_contract_revision",
                "flag": None,
                "ownership": QCODER_PREBINDS,
                "required": True,
                "json_type": "integer",
                "fixed_value": int(contract["contract_revision"]),
            },
        ],
        "ordinary_finish_route": True,
        "separate_build_review_decline_required": False,
        "continue_unchanged_used": False,
        "next_loop_started": False,
        "cross_loop_carryover": False,
        "pending_unconfirmed_broadening_cancelled_on_close": True,
        "customer_project_files_preserved": True,
        "raw_policy_replacement_prohibited": True,
        "hosted_operation_permitted": False,
    }


def _saved_reference_options(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for role, descriptor in sorted(state.get("saved_artifacts", {}).items()):
        if not isinstance(descriptor, Mapping):
            continue
        reference = descriptor.get("artifact_reference")
        if not isinstance(reference, str):
            continue
        options.append(
            {
                "value": reference,
                "customer_meaning": f"Saved qCoder evidence: {str(role).replace('_', ' ')}.",
                "artifact_role": str(role),
                "qcoder_owned_reference": True,
            }
        )
    for reference, descriptor in sorted(state.get("run_summary_index", {}).items()):
        if not isinstance(descriptor, Mapping) or not isinstance(reference, str):
            continue
        options.append(
            {
                "value": reference,
                "customer_meaning": f"Run Summary {reference[-8:]}.",
                "artifact_role": "run_summary",
                "qcoder_owned_reference": True,
            }
        )
    return options


def _excluded_reference_options(
    state: Mapping[str, Any], contract: Mapping[str, Any]
) -> list[dict[str, Any]]:
    saved = {item["value"]: item for item in _saved_reference_options(state)}
    return [
        deepcopy(saved[reference])
        for reference in sorted(contract["evidence_exclusions"])
        if reference in saved
    ]


def _locally_controlled_reference_options(
    state: Mapping[str, Any], *, artifact_directory: Path
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    root = artifact_directory.absolute()
    for item in _saved_reference_options(state):
        descriptor = next(
            (
                value
                for value in state.get("saved_artifacts", {}).values()
                if isinstance(value, Mapping) and value.get("artifact_reference") == item["value"]
            ),
            None,
        )
        if descriptor is None:
            candidate = state.get("run_summary_index", {}).get(item["value"])
            descriptor = candidate if isinstance(candidate, Mapping) else None
        if not isinstance(descriptor, Mapping):
            continue
        path = Path(str(descriptor.get("local_path", ""))).absolute()
        if path.is_file() and path.is_relative_to(root):
            options.append(item)
    return options


def _reference_field(
    *,
    options: Sequence[Mapping[str, Any]],
    meaning: str,
) -> dict[str, Any]:
    return {
        "name": "artifact_reference",
        "flag": "--artifact-reference",
        "ownership": "customer_selects_from_qcoder_owned_references",
        "required": True,
        "json_type": "string",
        "accepted_values": [deepcopy(dict(item)) for item in options],
        "customer_meaning": meaning,
        "parser_mapping": "one_exact_qcoder_owned_reference",
        "arbitrary_text_prohibited": True,
    }


def evidence_control_contracts(
    state: Mapping[str, Any],
    *,
    artifact_directory: Path,
    _contract_is_validated: bool = False,
) -> dict[str, dict[str, Any]]:
    contract = state["current_loop_contract"]
    if not _contract_is_validated:
        validate_contract(contract)
    revision = int(contract["contract_revision"])
    saved = _saved_reference_options(state)
    excluded = {item["value"] for item in _excluded_reference_options(state, contract)}
    return {
        "evidence_exclude": {
            "operation": "evidence_exclude",
            "subcommand": "evidence-exclude",
            "fields": [
                _reference_field(
                    options=[item for item in saved if item["value"] not in excluded],
                    meaning="Select one exact saved qCoder evidence reference to exclude.",
                ),
                {
                    "name": "reason",
                    "flag": "--reason",
                    "ownership": CUSTOMER_SELECTS,
                    "required": True,
                    "json_type": "string",
                    "accepted_values": [
                        _option(value, EXCLUSION_REASON_MEANINGS[value])
                        for value in EVIDENCE_EXCLUSION_REASONS
                    ],
                    "parser_mapping": "one_exact_cli_value",
                    "arbitrary_text_prohibited": True,
                },
                {
                    "name": "expected_contract_revision",
                    "flag": "--expected-contract-revision",
                    "ownership": QCODER_PREBINDS,
                    "required": True,
                    "json_type": "integer",
                    "fixed_value": revision,
                },
            ],
            "raw_evidence_in_control": False,
        },
        "evidence_restore": {
            "operation": "evidence_restore",
            "subcommand": "evidence-restore",
            "fields": [
                _reference_field(
                    options=_excluded_reference_options(state, contract),
                    meaning="Select one exact still-valid excluded qCoder evidence reference.",
                ),
                {
                    "name": "expected_contract_revision",
                    "flag": "--expected-contract-revision",
                    "ownership": QCODER_PREBINDS,
                    "required": True,
                    "json_type": "integer",
                    "fixed_value": revision,
                },
            ],
            "raw_evidence_in_control": False,
        },
        "evidence_delete": {
            "operation": "evidence_delete",
            "subcommand": "evidence-delete",
            "fields": [
                _reference_field(
                    options=_locally_controlled_reference_options(
                        state, artifact_directory=artifact_directory
                    ),
                    meaning="Select one exact qCoder-controlled local evidence reference.",
                ),
                {
                    "name": "expected_contract_revision",
                    "flag": "--expected-contract-revision",
                    "ownership": QCODER_PREBINDS,
                    "required": True,
                    "json_type": "integer",
                    "fixed_value": revision,
                },
                {
                    "name": "approve",
                    "flag": "--approve",
                    "ownership": "explicit_customer_authority",
                    "required": True,
                    "json_type": "boolean",
                    "fixed_true_flag_after_explicit_authority": True,
                },
            ],
            "deletes_project_files": False,
            "raw_evidence_in_control": False,
        },
    }


def operation_receipt_contract(state: Mapping[str, Any]) -> dict[str, Any]:
    coordinator = state.get("coordinator")
    semantics = (
        coordinator.get("current_request_semantics") if isinstance(coordinator, Mapping) else None
    )
    requested_operation = (
        str(semantics.get("requested_operation")) if isinstance(semantics, Mapping) else None
    )
    current_substage = (
        coordinator.get("current_step_substage") if isinstance(coordinator, Mapping) else None
    )
    d080_operation_category = (
        "ide_execute"
        if current_substage == "execution" or requested_operation == "local_execution"
        else "ide_write"
    )
    d080_output_role = (
        "results"
        if current_substage == "execution" or requested_operation == "local_execution"
        else "circuit_qasm"
        if current_substage == "qasm" or requested_operation == "qasm_export"
        else "source"
    )
    d080_path_flag = {
        "source": "--source",
        "circuit_qasm": "--qasm",
        "results": "--results",
    }[d080_output_role]
    current_receipt_id = (
        coordinator.get("current_step_operation_receipt_id")
        if isinstance(coordinator, Mapping)
        else None
    )
    receipts = [
        {
            "value": receipt_id,
            "customer_meaning": (
                f"Single-use {receipt.get('operation_category', 'IDE')} output receipt."
            ),
            "authorized_output_roles": list(receipt.get("authorized_output_role_ceiling", [])),
            "qcoder_owned_reference": True,
        }
        for receipt_id, receipt in sorted(state.get("operation_receipts", {}).items())
        if isinstance(receipt, Mapping) and receipt.get("status") == "issued"
    ]
    return {
        "issue_operation_receipt": {
            "operation": "record_ide_authority",
            "fields": [
                {
                    "name": "operation_category",
                    "flag": "--operation-category",
                    "ownership": QCODER_PREBINDS if semantics is not None else CUSTOMER_SELECTS,
                    "required": semantics is not None,
                    "qcoder_default": d080_operation_category,
                    "fixed_value": d080_operation_category if semantics is not None else None,
                    "json_type": "string",
                    "accepted_values": [
                        _option(value, value.replace("_", " "))
                        for value in SUPPORTED_OPERATION_CATEGORIES
                    ],
                },
                {
                    "name": "output_role",
                    "flag": "--output-role",
                    "ownership": QCODER_PREBINDS if semantics is not None else CUSTOMER_SELECTS,
                    "required": semantics is not None,
                    "qcoder_default": (
                        [d080_output_role]
                        if semantics is not None
                        else list(SUPPORTED_OUTPUT_ROLES)
                    ),
                    "fixed_value": d080_output_role if semantics is not None else None,
                    "json_type": "array",
                    "item_type": "string",
                    "accepted_values": [
                        _option(value, value.replace("_", " ")) for value in SUPPORTED_OUTPUT_ROLES
                    ],
                    "unique_items": True,
                },
                {
                    "name": "allow_and_explicit",
                    "flags": ["--allow", "--explicit"],
                    "ownership": "explicit_customer_authority",
                    "required": True,
                    "json_type": "boolean",
                    "authority_only": True,
                },
                {
                    "name": "exact_iteration_instruction",
                    "flag": "--instruction-stdin",
                    "ownership": "exact_current_customer_message_transport",
                    "required": state.get("quiet_iteration_status") == "assist_iteration_ready",
                    "json_type": "string",
                    "maximum_utf8_bytes": 65_536,
                    "input_channel": "stdin",
                    "provenance": "user_stated",
                    "stored_as_digest_only": True,
                    "arbitrary_text_in_argv": False,
                },
            ],
            "ordinary_iteration_route": (
                "record_ide_authority"
                if state.get("quiet_iteration_status") == "assist_iteration_ready"
                else None
            ),
        },
        "consume_operation_receipt": {
            "operation": "register_artifacts",
            "fields": [
                {
                    "name": "operation_receipt_id",
                    "flag": "--operation-receipt-id",
                    "ownership": (
                        QCODER_PREBINDS
                        if semantics is not None
                        else "customer_selects_from_qcoder_owned_references"
                    ),
                    "required": semantics is not None,
                    "fixed_value": current_receipt_id if semantics is not None else None,
                    "json_type": "string",
                    "accepted_values": receipts,
                    "arbitrary_text_prohibited": True,
                },
                {
                    "name": "artifact_role",
                    "ownership": QCODER_PREBINDS if semantics is not None else CUSTOMER_SELECTS,
                    "required": True,
                    "json_type": "string",
                    "fixed_value": d080_output_role if semantics is not None else None,
                    "accepted_values": [
                        _option(value, value.replace("_", " ")) for value in SUPPORTED_OUTPUT_ROLES
                    ],
                },
                {
                    "name": "artifact_path",
                    "flag": d080_path_flag if semantics is not None else None,
                    "ownership": EXACT_PATH_CHANNEL,
                    "required": True,
                    "json_type": "string",
                    "accepted_domain": (
                        "exact_path_returned_by_the_ide_operation_or_exact_customer_selection"
                    ),
                    "directory_discovery_permitted": False,
                },
                {
                    "name": "provenance",
                    "flag": "--provenance",
                    "ownership": QCODER_PREBINDS if semantics is not None else CUSTOMER_SELECTS,
                    "required": True,
                    "json_type": "string",
                    "fixed_value": "assistant_created" if semantics is not None else None,
                    "accepted_values": [
                        _option(value, value.replace("_", " ")) for value in PROVENANCE_VALUES
                    ],
                },
            ],
        },
    }


def recovery_control_contract(state: Mapping[str, Any]) -> dict[str, Any]:
    coordinator = state.get("coordinator")
    active = coordinator.get("active_recovery") if isinstance(coordinator, Mapping) else None
    return {
        "schema_id": "qcoder.current_loop.bounded_recovery_input.v1",
        "active": isinstance(active, Mapping),
        "qcoder_owned_fields_prebound": True,
        "assistant_constructs_recovery_identifiers": False,
        "refresh_operation": "status",
        "refresh_has_customer_value_fields": False,
        "active_recovery": deepcopy(dict(active)) if isinstance(active, Mapping) else None,
        "alternatives": [
            {
                "value": "skip",
                "customer_meaning": "Skip only the current optional step when qCoder permits it.",
            },
            {
                "value": "abandon_step",
                "customer_meaning": "Abandon only the recoverable step while preserving prior state.",
            },
            {
                "value": "stop_loop",
                "customer_meaning": "Explicitly abandon the active loop.",
            },
        ],
    }


def bounded_control_contracts(
    state: Mapping[str, Any], *, artifact_directory: Path
) -> dict[str, dict[str, Any]]:
    contract = state["current_loop_contract"]
    validate_contract(contract)
    proposal = contract.get("pending_broadening_proposal")
    controls: dict[str, dict[str, Any]] = {
        "contract_status": {
            "operation": "contract_status",
            "subcommand": "contract-status",
            "fields": [],
            "qcoder_owned_current_contract": True,
            "raw_policy_editing_permitted": False,
        },
        "contract_set_preset": preset_selection_contract(contract, _contract_is_validated=True),
        "contract_adjust": adjustment_selection_contract(contract, _contract_is_validated=True),
        "contract_set_generation_governance": generation_governance_selection_contract(
            contract,
            _contract_is_validated=True,
        ),
        "contract_confirm_broadening": {
            "operation": "contract_confirm_broadening",
            "subcommand": "contract-confirm-broadening",
            "fields": [
                {
                    "name": "expected_contract_revision",
                    "flag": "--expected-contract-revision",
                    "ownership": QCODER_PREBINDS,
                    "required": True,
                    "json_type": "integer",
                    "fixed_value": int(contract["contract_revision"]),
                },
                {
                    "name": "approve",
                    "flag": "--approve",
                    "ownership": "explicit_customer_authority",
                    "required": True,
                    "json_type": "boolean",
                    "authority_only": True,
                },
            ],
            "proposal_reference": (
                {
                    "proposal_digest": proposal.get("proposal_digest"),
                    "ownership": QCODER_PREBINDS,
                    "raw_policy_retransmission_required": False,
                }
                if isinstance(proposal, Mapping)
                else None
            ),
        },
        "stop_loop": {
            "operation": "abandon",
            "subcommand": "abandon",
            "fields": [
                {
                    "name": "approve",
                    "flag": "--approve",
                    "ownership": "explicit_customer_authority",
                    "required": True,
                    "json_type": "boolean",
                    "authority_only": True,
                }
            ],
            "off_is_absence_of_active_loop": True,
        },
        "complete_instruction": completion_control_contract(state),
    }
    controls.update(
        evidence_control_contracts(
            state,
            artifact_directory=artifact_directory,
            _contract_is_validated=True,
        )
    )
    for value in controls.values():
        value["schema_id"] = BOUNDED_CONTROL_INPUT_SCHEMA_ID
        value["schema_version"] = BOUNDED_CONTROL_INPUT_SCHEMA_VERSION
        value["contract_revision"] = int(contract["contract_revision"])
        value["state_revision"] = int(state["state_revision"])
        value["loop_ref"] = str(state["loop_ref"])
        value["workspace_binding"] = str(state["workspace_root"])
        value["customer_types_cli_or_internal_identifiers"] = False
        value["assistant_uses_parser_help_or_source"] = False
        value["hosted_operation_permitted"] = False
        value["contract_digest"] = _digest(value)
    return controls


def bounded_control_contract_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": BOUNDED_CONTROL_INPUT_SCHEMA_ID,
        "schema_version": BOUNDED_CONTROL_INPUT_SCHEMA_VERSION,
        "operations": [
            "contract_status",
            "contract_set_preset",
            "contract_adjust",
            "contract_set_generation_governance",
            "contract_confirm_broadening",
            "evidence_exclude",
            "evidence_restore",
            "evidence_delete",
            "stop_loop",
            "complete_instruction",
            "record_ide_authority",
            "register_artifacts",
            "refresh_bounded_recovery",
        ],
        "named_presets": list(NAMED_PRESETS),
        "preset_options": [_option(value, PRESET_MEANINGS[value]) for value in NAMED_PRESETS],
        "off_is_distinct_stop_loop": True,
        "categories": list(EVIDENCE_CATEGORIES),
        "category_options": [
            _option(value, CATEGORY_MEANINGS[value]) for value in EVIDENCE_CATEGORIES
        ],
        "dimensions": list(ADJUSTMENT_DIMENSIONS),
        "dimension_options": [
            _option(value, DIMENSION_MEANINGS[value]) for value in ADJUSTMENT_DIMENSIONS
        ],
        "values_by_dimension": {
            key: list(values) for key, values in ADJUSTMENT_VALUES_BY_DIMENSION.items()
        },
        "value_options": [
            _option(value, VALUE_MEANINGS[value])
            for value in sorted(
                {item for values in ADJUSTMENT_VALUES_BY_DIMENSION.values() for item in values}
            )
        ],
        "exclusion_reasons": list(EVIDENCE_EXCLUSION_REASONS),
        "exclusion_reason_options": [
            _option(value, EXCLUSION_REASON_MEANINGS[value]) for value in EVIDENCE_EXCLUSION_REASONS
        ],
        "operation_categories": list(SUPPORTED_OPERATION_CATEGORIES),
        "operation_output_roles": list(SUPPORTED_OUTPUT_ROLES),
        "provenance_values": list(PROVENANCE_VALUES),
        "raw_policy_serialization_required": False,
        "qcoder_owned_references_prebound": True,
        "assistant_infers_valid_combinations": False,
        "parser_help_or_source_required": False,
    }
    payload["contract_digest"] = _digest(payload)
    return payload


def contract_for_operation(
    state: Mapping[str, Any],
    *,
    operation: str | None,
    artifact_directory: Path,
) -> dict[str, Any] | None:
    if operation is None:
        return None
    if not isinstance(state.get("current_loop_contract"), Mapping):
        return None
    local_control_operations = {
        "contract_status",
        "contract_set_preset",
        "contract_adjust",
        "contract_set_generation_governance",
        "contract_confirm_broadening",
        "complete_instruction",
        "evidence_exclude",
        "evidence_restore",
        "evidence_delete",
    }
    if operation in local_control_operations:
        controls = bounded_control_contracts(state, artifact_directory=artifact_directory)
        return controls[operation]
    receipts = operation_receipt_contract(state)
    if operation == "record_ide_authority":
        payload = {
            "schema_id": BOUNDED_CONTROL_INPUT_SCHEMA_ID,
            "schema_version": BOUNDED_CONTROL_INPUT_SCHEMA_VERSION,
            **receipts["issue_operation_receipt"],
        }
        payload["contract_digest"] = _digest(payload)
        return payload
    if operation == "register_artifacts":
        payload = {
            "schema_id": BOUNDED_CONTROL_INPUT_SCHEMA_ID,
            "schema_version": BOUNDED_CONTROL_INPUT_SCHEMA_VERSION,
            **receipts["consume_operation_receipt"],
        }
        payload["contract_digest"] = _digest(payload)
        return payload
    if operation == "status":
        recovery = recovery_control_contract(state)
        if recovery["active"]:
            payload = {
                "schema_id": BOUNDED_CONTROL_INPUT_SCHEMA_ID,
                "schema_version": BOUNDED_CONTROL_INPUT_SCHEMA_VERSION,
                "operation": "status",
                "fields": [],
                "recovery": recovery,
            }
            payload["contract_digest"] = _digest(payload)
            return payload
    return None


def dynamic_argument_contracts(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project assistant-supplied fields into invocation value-slot contracts."""

    result: list[dict[str, Any]] = []
    for field in value.get("fields", []):
        if not isinstance(field, Mapping):
            continue
        flag = field.get("flag")
        if (
            isinstance(flag, str)
            and field.get("ownership") != QCODER_PREBINDS
            and not field.get("fixed_true_flag_after_explicit_authority")
        ):
            result.append(
                {
                    "flag": flag,
                    "value_source": field.get("ownership"),
                    "allowed_values": [
                        item.get("value")
                        for item in field.get("accepted_values", [])
                        if isinstance(item, Mapping)
                    ],
                    "field_contract": deepcopy(dict(field)),
                }
            )
    return result
