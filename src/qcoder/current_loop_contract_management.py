"""Customer-facing management for one canonical Explorer Current Loop Contract.

This module is the single policy-management boundary used by the coordinator,
the optional loopback editor, and black-box certification.  It projects only
customer-relevant contract state, validates one bounded editable JSON document,
classifies changes against the canonical compiler, and creates revisioned
narrowing receipts or authority-only broadening proposals.

It does not persist state, inspect a workspace, expose evidence, or grant IDE,
execution, raw-exposure, external-service, cost, or Blueprint authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from qcoder.current_loop_contract import (
    ADJUSTMENT_VALUES_BY_DIMENSION,
    CONTRACT_SCHEMA_ID,
    EVIDENCE_CATEGORIES,
    GENERATION_GOVERNANCE_VALUES,
    NAMED_PRESETS,
    PRESET_PROVENANCE,
    CurrentLoopContractError,
    compile_preset,
    digest,
    iteration_context_policy,
    policy_digest,
    policy_summary,
    quiet_communication_policy,
    validate_contract,
)

EFFECTIVE_CONTRACT_DOCUMENT_SCHEMA_ID = "qcoder.current_loop.effective_contract_document.v1"
CUSTOMER_CONTRACT_DOCUMENT_SCHEMA_ID = "qcoder.current_loop.customer_contract_document.v1"
CONTRACT_CHANGE_SET_SCHEMA_ID = "qcoder.current_loop.contract_change_set.v1"
CONTRACT_DIFF_SCHEMA_ID = "qcoder.current_loop.contract_diff.v1"
CONTRACT_VALIDATION_SCHEMA_ID = "qcoder.current_loop.contract_validation_result.v1"
CONTRACT_CHANGE_RECEIPT_SCHEMA_ID = "qcoder.current_loop.contract_change_receipt.v1"
CONTRACT_MANAGEMENT_SCHEMA_ID = "qcoder.current_loop.contract_management.v1"
CONTRACT_MANAGEMENT_SCHEMA_VERSION = 1

CUSTOMER_DOCUMENT_MAX_BYTES = 65_536
CUSTOMER_DOCUMENT_MAX_DEPTH = 12
CUSTOMER_DOCUMENT_MAX_STRING_BYTES = 8_192
CUSTOMER_DOCUMENT_MAX_CHANGES = 64

CUSTOMER_PRESETS = ("assist", "evidence_only", "custom")
CUSTOMER_PRESET_MEANINGS = {
    "assist": "Assist — quiet everyday help within the current contract.",
    "evidence_only": "Evidence only — retain bounded local evidence without standing help.",
    "custom": "Custom — use the validated granular settings shown below.",
}
GENERATION_GOVERNANCE_MEANINGS = {
    "adaptive": "Adaptive — proceed quietly unless a material governing decision is unresolved.",
    "blueprint_required": (
        "Blueprint required — confirm material governing choices before generation."
    ),
}
CATEGORY_MEANINGS = {
    "request_baseline": "Request Baseline",
    "working_blueprint": "Working Blueprint",
    "generation_context": "Generation Context",
    "python_manifestation": "Python/source evidence",
    "circuit_manifestation": "Circuit/QASM evidence",
    "result_manifestation": "Result evidence",
    "lineage": "Lineage",
    "derived_metrics": "Derived metrics",
}
CUSTOMER_DIMENSIONS = (
    "collect",
    "local_derivation",
    "derived_assistant_exposure",
    "raw_assistant_exposure",
    "recommendations",
    "bounded_non_material_preparation",
    "request_application_or_execution_ceiling",
)
CUSTOMER_DIMENSION_MEANINGS = {
    "collect": "Collect exact authorized evidence",
    "local_derivation": "Derive bounded local evidence",
    "derived_assistant_exposure": "Share derived context with the connected assistant",
    "raw_assistant_exposure": "Share raw evidence with the connected assistant",
    "recommendations": "Recommend bounded next checks",
    "bounded_non_material_preparation": "Prepare bounded non-material context",
    "request_application_or_execution_ceiling": (
        "Permit qCoder to request separately authorized IDE application or execution"
    ),
}
CUSTOMER_VALUES = {
    "collect": ("disabled", "enabled"),
    "local_derivation": ("disabled", "enabled"),
    "derived_assistant_exposure": ("disabled", "on_request", "standing"),
    "raw_assistant_exposure": ("disabled",),
    "recommendations": ("disabled", "enabled"),
    "bounded_non_material_preparation": ("disabled", "bounded_non_material"),
    "request_application_or_execution_ceiling": ("disabled", "enabled"),
}
PROTOTYPE_POLLUTION_KEYS = frozenset({"__proto__", "constructor", "prototype"})


class ContractManagementError(ValueError):
    """One bounded contract-management validation failure."""

    def __init__(
        self,
        category: str,
        *,
        field_path: str | None = None,
        line: int | None = None,
        column: int | None = None,
    ):
        super().__init__(category)
        self.category = category
        self.field_path = field_path
        self.line = line
        self.column = column
        self.safe_details = {
            "contract_validation_error_location": {
                "field_path": field_path,
                "line": line,
                "column": column,
            },
            "raw_contract_document_echoed": False,
        }


def _pairs_without_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractManagementError(
                "customer_contract_json_duplicate_key",
                field_path=key,
            )
        if key in PROTOTYPE_POLLUTION_KEYS:
            raise ContractManagementError(
                "customer_contract_json_unsafe_key",
                field_path=key,
            )
        result[key] = value
    return result


def _validate_json_value(value: Any, *, path: str = "$", depth: int = 0) -> None:
    if depth > CUSTOMER_DOCUMENT_MAX_DEPTH:
        raise ContractManagementError(
            "customer_contract_json_depth_exceeded",
            field_path=path,
        )
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractManagementError(
                    "customer_contract_json_key_invalid",
                    field_path=path,
                )
            if key in PROTOTYPE_POLLUTION_KEYS:
                raise ContractManagementError(
                    "customer_contract_json_unsafe_key",
                    field_path=f"{path}.{key}",
                )
            _validate_json_value(item, path=f"{path}.{key}", depth=depth + 1)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]", depth=depth + 1)
        return
    if isinstance(value, str):
        if len(value.encode("utf-8")) > CUSTOMER_DOCUMENT_MAX_STRING_BYTES:
            raise ContractManagementError(
                "customer_contract_json_string_too_large",
                field_path=path,
            )
        if any(ord(character) < 32 for character in value):
            raise ContractManagementError(
                "customer_contract_json_unsafe_control",
                field_path=path,
            )
        return
    if value is not None and not isinstance(value, (bool, int, float)):
        raise ContractManagementError(
            "customer_contract_json_value_invalid",
            field_path=path,
        )


def parse_customer_contract_json(raw: bytes | str) -> dict[str, Any]:
    """Parse one bounded UTF-8 JSON document without duplicate or unsafe keys."""

    if isinstance(raw, bytes):
        if len(raw) > CUSTOMER_DOCUMENT_MAX_BYTES:
            raise ContractManagementError("customer_contract_json_too_large")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractManagementError("customer_contract_json_utf8_invalid") from exc
    elif isinstance(raw, str):
        text = raw
        if len(text.encode("utf-8")) > CUSTOMER_DOCUMENT_MAX_BYTES:
            raise ContractManagementError("customer_contract_json_too_large")
    else:
        raise ContractManagementError("customer_contract_json_type_invalid")
    try:
        value = json.loads(text, object_pairs_hook=_pairs_without_duplicates)
    except ContractManagementError:
        raise
    except json.JSONDecodeError as exc:
        raise ContractManagementError(
            "customer_contract_json_syntax_invalid",
            line=exc.lineno,
            column=exc.colno,
        ) from exc
    if not isinstance(value, Mapping):
        raise ContractManagementError("customer_contract_document_object_required")
    _validate_json_value(value)
    return deepcopy(dict(value))


def _enabled(value: Any) -> str:
    return "enabled" if value is True else "disabled"


def _customer_category_row(row: Mapping[str, Any]) -> dict[str, str]:
    return {
        "collect": _enabled(row["collect"]),
        "local_derivation": _enabled(row["derive"]),
        "derived_assistant_exposure": str(row["expose"]["connected_assistant"]["derived"]),
        "raw_assistant_exposure": str(row["expose"]["connected_assistant"]["raw"]),
        "recommendations": _enabled(row["recommend"]),
        "bounded_non_material_preparation": str(row["prepare"]),
        "request_application_or_execution_ceiling": _enabled(
            row["request_application_or_execution"]
        ),
    }


def _internal_category_row(row: Mapping[str, Any], *, category: str) -> dict[str, Any]:
    if set(row) != set(CUSTOMER_DIMENSIONS):
        raise ContractManagementError(
            "customer_contract_category_shape_invalid",
            field_path=f"customer_settings.evidence_categories.{category}",
        )
    for dimension in CUSTOMER_DIMENSIONS:
        value = row[dimension]
        if not isinstance(value, str) or value not in CUSTOMER_VALUES[dimension]:
            raise ContractManagementError(
                "customer_contract_value_invalid",
                field_path=f"customer_settings.evidence_categories.{category}.{dimension}",
            )
    local = row["collect"] == "enabled"
    return {
        "collect": local,
        "derive": row["local_derivation"] == "enabled",
        "expose": {
            "local_qcoder": {
                "raw": "standing" if local else "disabled",
                "derived": "standing",
            },
            "local_presentation": {
                "raw": "on_request" if local else "disabled",
                "derived": "standing",
            },
            "connected_assistant": {
                "raw": row["raw_assistant_exposure"],
                "derived": row["derived_assistant_exposure"],
            },
        },
        "recommend": row["recommendations"] == "enabled",
        "prepare": row["bounded_non_material_preparation"],
        "request_application_or_execution": (
            row["request_application_or_execution_ceiling"] == "enabled"
        ),
    }


def _customer_settings(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "preset": str(contract["effective_preset"]),
        "generation_governance": str(contract["generation_governance"]),
        "evidence_categories": {
            category: _customer_category_row(contract["effective_policy"]["categories"][category])
            for category in EVIDENCE_CATEGORIES
        },
        "hosted_enrichment": "on_request",
        "build_review": "on_request",
    }


def customer_contract_document(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Return the complete qCoder-bound customer-editable JSON document."""

    validate_contract(contract)
    return {
        "schema_id": CUSTOMER_CONTRACT_DOCUMENT_SCHEMA_ID,
        "schema_version": 1,
        "expected_contract_revision": int(contract["contract_revision"]),
        "customer_settings": _customer_settings(contract),
    }


def _last_change_receipt(contract: Mapping[str, Any]) -> dict[str, Any] | None:
    receipt = contract.get("last_contract_management_receipt")
    return deepcopy(dict(receipt)) if isinstance(receipt, Mapping) else None


def effective_contract_document(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Return canonical customer-relevant effective JSON, never raw loop state."""

    validate_contract(contract)
    pending = contract.get("pending_broadening_proposal")
    pending_summary = None
    if isinstance(pending, Mapping):
        pending_summary = {
            "proposal_reference": pending.get("proposal_reference")
            or pending.get("proposal_digest"),
            "expected_contract_revision": pending.get("expected_contract_revision"),
            "change_kind": pending.get("change_kind", "broadening"),
            "customer_summary": pending.get(
                "customer_summary",
                "A broader contract change awaits explicit confirmation.",
            ),
            "raw_json_retransmission_required": False,
        }
    return {
        "schema_id": EFFECTIVE_CONTRACT_DOCUMENT_SCHEMA_ID,
        "schema_version": 1,
        "canonical_contract_schema_id": CONTRACT_SCHEMA_ID,
        "contract_revision": int(contract["contract_revision"]),
        "effective_preset": str(contract["effective_preset"]),
        "generation_governance": str(contract["generation_governance"]),
        "effective_customer_policy": _customer_settings(contract),
        "contract_provenance": {
            "preset": contract["preset_provenance"],
            "generation_governance": contract["generation_governance_provenance"],
        },
        "pending_broadening": pending_summary,
        "effective_policy_digest": str(contract["effective_policy_digest"]),
        "customer_language_summary": policy_summary(str(contract["effective_preset"])),
        "last_contract_change_receipt": _last_change_receipt(contract),
        "separate_authority_still_required": [
            "IDE editing or execution",
            "raw evidence exposure",
            "external service, hardware, or paid activity",
            "material Blueprint change",
        ],
        "raw_internal_state_included": False,
    }


def _document_error_result(exc: ContractManagementError) -> dict[str, Any]:
    return {
        "schema_id": CONTRACT_VALIDATION_SCHEMA_ID,
        "schema_version": 1,
        "valid": False,
        "error_category": exc.category,
        "error_location": {
            "field_path": exc.field_path,
            "line": exc.line,
            "column": exc.column,
        },
        "customer_message": _error_message(exc.category),
        "raw_document_echoed": False,
        "state_replacement_accepted": False,
    }


def _error_message(category: str) -> str:
    messages = {
        "customer_contract_json_duplicate_key": "The JSON repeats one field name.",
        "customer_contract_json_unsafe_key": "The JSON contains an unsafe field name.",
        "customer_contract_json_unsafe_control": "The JSON contains an unsafe control character.",
        "customer_contract_json_syntax_invalid": "The JSON is not valid.",
        "customer_contract_json_too_large": "The editable contract is too large.",
        "customer_contract_json_depth_exceeded": "The editable contract is nested too deeply.",
        "customer_contract_document_schema_invalid": (
            "This is not the current customer-editable contract document."
        ),
        "customer_contract_document_revision_stale": (
            "The contract changed after this draft was opened. Refresh before applying it."
        ),
        "customer_contract_document_unknown_field": (
            "The editable contract contains a field qCoder does not support."
        ),
        "customer_contract_value_invalid": "One setting is outside qCoder's supported domain.",
        "customer_contract_qcoder_owned_field_changed": (
            "A qCoder-owned schema or revision field was changed."
        ),
    }
    return messages.get(category, "qCoder could not validate this contract draft safely.")


def _expect_exact_keys(value: Mapping[str, Any], expected: set[str], *, path: str) -> None:
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown:
        raise ContractManagementError(
            "customer_contract_document_unknown_field",
            field_path=f"{path}.{min(unknown)}",
        )
    if missing:
        raise ContractManagementError(
            "customer_contract_document_field_missing",
            field_path=f"{path}.{min(missing)}",
        )


def validate_customer_contract_document(
    contract: Mapping[str, Any],
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the complete editable projection against one exact revision."""

    try:
        validate_contract(contract)
        _expect_exact_keys(
            document,
            {
                "schema_id",
                "schema_version",
                "expected_contract_revision",
                "customer_settings",
            },
            path="$",
        )
        if (
            document.get("schema_id") != CUSTOMER_CONTRACT_DOCUMENT_SCHEMA_ID
            or document.get("schema_version") != 1
        ):
            raise ContractManagementError(
                "customer_contract_document_schema_invalid",
                field_path="$.schema_id",
            )
        revision = document.get("expected_contract_revision")
        if not isinstance(revision, int):
            raise ContractManagementError(
                "customer_contract_qcoder_owned_field_changed",
                field_path="$.expected_contract_revision",
            )
        if revision != contract["contract_revision"]:
            raise ContractManagementError(
                "customer_contract_document_revision_stale",
                field_path="$.expected_contract_revision",
            )
        settings = document.get("customer_settings")
        if not isinstance(settings, Mapping):
            raise ContractManagementError(
                "customer_contract_document_settings_invalid",
                field_path="$.customer_settings",
            )
        _expect_exact_keys(
            settings,
            {
                "preset",
                "generation_governance",
                "evidence_categories",
                "hosted_enrichment",
                "build_review",
            },
            path="$.customer_settings",
        )
        if settings["preset"] not in CUSTOMER_PRESETS:
            raise ContractManagementError(
                "customer_contract_value_invalid",
                field_path="$.customer_settings.preset",
            )
        if settings["generation_governance"] not in GENERATION_GOVERNANCE_VALUES:
            raise ContractManagementError(
                "customer_contract_value_invalid",
                field_path="$.customer_settings.generation_governance",
            )
        if settings["hosted_enrichment"] != "on_request":
            raise ContractManagementError(
                "customer_contract_value_invalid",
                field_path="$.customer_settings.hosted_enrichment",
            )
        if settings["build_review"] != "on_request":
            raise ContractManagementError(
                "customer_contract_value_invalid",
                field_path="$.customer_settings.build_review",
            )
        categories = settings["evidence_categories"]
        if not isinstance(categories, Mapping) or set(categories) != set(EVIDENCE_CATEGORIES):
            raise ContractManagementError(
                "customer_contract_category_inventory_invalid",
                field_path="$.customer_settings.evidence_categories",
            )
        internal_categories = {
            category: _internal_category_row(categories[category], category=category)
            for category in EVIDENCE_CATEGORIES
            if isinstance(categories[category], Mapping)
        }
        if len(internal_categories) != len(EVIDENCE_CATEGORIES):
            raise ContractManagementError(
                "customer_contract_category_shape_invalid",
                field_path="$.customer_settings.evidence_categories",
            )
        target_policy = {
            "categories": internal_categories,
            "policy_ceiling": deepcopy(contract["effective_policy"]["policy_ceiling"]),
        }
        target_preset = str(settings["preset"])
        if target_preset in NAMED_PRESETS and target_policy != compile_preset(target_preset):
            target_preset = "custom"
        normalized = deepcopy(dict(document))
        normalized["customer_settings"]["preset"] = target_preset
        return {
            "schema_id": CONTRACT_VALIDATION_SCHEMA_ID,
            "schema_version": 1,
            "valid": True,
            "error_category": None,
            "normalized_document": normalized,
            "target_policy": target_policy,
            "target_policy_digest": policy_digest(target_policy),
            "normalization": (
                "custom_due_to_granular_deviation"
                if target_preset != settings["preset"]
                else "none"
            ),
            "raw_document_echoed": False,
            "state_replacement_accepted": False,
        }
    except CurrentLoopContractError as exc:
        return _document_error_result(ContractManagementError(exc.category))
    except ContractManagementError as exc:
        return _document_error_result(exc)


def _rank(path: str, value: str) -> int:
    if path == "generation_governance":
        return {"blueprint_required": 0, "adaptive": 1}[value]
    if value == "disabled":
        return 0
    if value == "on_request":
        return 1
    if value in {"enabled", "bounded_non_material", "standing"}:
        return 2
    raise ContractManagementError("customer_contract_value_invalid", field_path=path)


def _change_rows(
    current: Mapping[str, Any],
    target: Mapping[str, Any],
) -> list[dict[str, Any]]:
    before = _customer_settings(current)
    after = target["customer_settings"]
    rows: list[dict[str, Any]] = []

    def add(path: str, old: str, new: str, customer_meaning: str) -> None:
        if old == new:
            return
        old_rank = _rank(path, old)
        new_rank = _rank(path, new)
        rows.append(
            {
                "path": path,
                "before": old,
                "after": new,
                "classification": "broadening" if new_rank > old_rank else "narrowing",
                "customer_meaning": customer_meaning,
            }
        )

    add(
        "generation_governance",
        str(before["generation_governance"]),
        str(after["generation_governance"]),
        "Generation governance",
    )
    for category in EVIDENCE_CATEGORIES:
        for dimension in CUSTOMER_DIMENSIONS:
            add(
                f"evidence_categories.{category}.{dimension}",
                str(before["evidence_categories"][category][dimension]),
                str(after["evidence_categories"][category][dimension]),
                f"{CATEGORY_MEANINGS[category]} — {CUSTOMER_DIMENSION_MEANINGS[dimension]}",
            )
    if len(rows) > CUSTOMER_DOCUMENT_MAX_CHANGES:
        raise ContractManagementError("customer_contract_change_set_too_large")
    return rows


def review_customer_contract_document(
    contract: Mapping[str, Any],
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and construct one qCoder-owned before/after diff."""

    validation = validate_customer_contract_document(contract, document)
    if not validation["valid"]:
        return {
            "schema_id": CONTRACT_DIFF_SCHEMA_ID,
            "schema_version": 1,
            "valid": False,
            "validation": validation,
            "classification": "invalid",
            "changes": [],
            "choices": [],
        }
    normalized = validation["normalized_document"]
    changes = _change_rows(contract, normalized)
    kinds = {item["classification"] for item in changes}
    if kinds == {"narrowing", "broadening"}:
        classification = "mixed"
    elif "broadening" in kinds:
        classification = "broadening"
    elif "narrowing" in kinds:
        classification = "narrowing"
    else:
        classification = "neutral"
    choices = {
        "mixed": [
            {
                "value": "apply_narrowing_subset",
                "customer_meaning": (
                    "Apply only the narrower settings now and keep the broader settings "
                    "as one separate proposal."
                ),
            },
            {
                "value": "confirm_complete_change_set",
                "customer_meaning": "Confirm and apply the complete displayed change set.",
            },
            {"value": "cancel", "customer_meaning": "Cancel without changing the contract."},
        ],
        "broadening": [
            {
                "value": "create_broadening_proposal",
                "customer_meaning": "Create the displayed proposal for explicit confirmation.",
            },
            {"value": "cancel", "customer_meaning": "Cancel without changing the contract."},
        ],
        "narrowing": [
            {
                "value": "apply_narrowing",
                "customer_meaning": "Apply the displayed narrowing immediately.",
            },
            {"value": "cancel", "customer_meaning": "Cancel without changing the contract."},
        ],
        "neutral": [{"value": "cancel", "customer_meaning": "No effective change is needed."}],
    }[classification]
    summary = {
        "narrowing": "This draft only reduces qCoder participation and can apply immediately.",
        "broadening": "This draft increases qCoder participation and requires confirmation.",
        "mixed": (
            "This draft both reduces and increases qCoder participation. qCoder will not "
            "silently apply only part of it."
        ),
        "neutral": "This draft makes no effective policy change.",
    }[classification]
    return {
        "schema_id": CONTRACT_DIFF_SCHEMA_ID,
        "schema_version": 1,
        "valid": True,
        "validation": validation,
        "classification": classification,
        "expected_contract_revision": contract["contract_revision"],
        "before_customer_json": customer_contract_document(contract),
        "after_customer_json": normalized,
        "changes": changes,
        "customer_summary": summary,
        "affected_behavior": [item["customer_meaning"] for item in changes],
        "previously_delivered_context_recallable": False,
        "choices": choices,
        "raw_state_included": False,
    }


def _apply_change_rows(settings: dict[str, Any], changes: Sequence[Mapping[str, Any]]) -> None:
    for item in changes:
        path = str(item["path"])
        if path == "generation_governance":
            settings["generation_governance"] = item["after"]
            continue
        parts = path.split(".")
        if len(parts) != 3 or parts[0] != "evidence_categories":
            raise ContractManagementError("customer_contract_change_path_invalid")
        settings["evidence_categories"][parts[1]][parts[2]] = item["after"]


def _policy_from_settings(
    contract: Mapping[str, Any],
    settings: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    categories = {
        category: _internal_category_row(
            settings["evidence_categories"][category],
            category=category,
        )
        for category in EVIDENCE_CATEGORIES
    }
    policy = {
        "categories": categories,
        "policy_ceiling": deepcopy(contract["effective_policy"]["policy_ceiling"]),
    }
    requested = str(settings.get("preset", "custom"))
    preset = (
        requested
        if requested in NAMED_PRESETS and policy == compile_preset(requested)
        else "custom"
    )
    return policy, preset


def _change_receipt(
    *,
    revision: int,
    classification: str,
    surface: str,
    changes: Sequence[Mapping[str, Any]],
    effective_policy_digest: str,
) -> dict[str, Any]:
    receipt = {
        "schema_id": CONTRACT_CHANGE_RECEIPT_SCHEMA_ID,
        "schema_version": 1,
        "contract_revision": revision,
        "change_classification": classification,
        "change_surface": surface,
        "change_authority_provenance": "explicit_customer_contract_action",
        "changed_paths": [str(item["path"]) for item in changes],
        "effective_policy_digest": effective_policy_digest,
        "previously_delivered_context_recallable": False,
        "raw_json_retransmitted": False,
    }
    receipt["receipt_digest"] = digest(receipt)
    return receipt


def _apply_settings(
    contract: Mapping[str, Any],
    *,
    settings: Mapping[str, Any],
    classification: str,
    surface: str,
    changes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    policy, preset = _policy_from_settings(contract, settings)
    result = deepcopy(dict(contract))
    result["contract_revision"] = int(contract["contract_revision"]) + 1
    result["effective_policy"] = policy
    result["effective_policy_digest"] = policy_digest(policy)
    result["effective_preset"] = preset
    result["preset_provenance"] = (
        "customer_requested_narrowing"
        if classification == "narrowing"
        else "customer_confirmed_broadening"
    )
    governance = str(settings["generation_governance"])
    result["generation_governance"] = governance
    result["generation_governance_provenance"] = (
        "customer_selected_contract_setting"
        if classification == "narrowing"
        else "customer_confirmed_broadening"
    )
    result["effective_internal_generation_posture"] = (
        "exploratory_first_pass" if governance == "adaptive" else "blueprint_guided"
    )
    result["quiet_communication_policy"] = quiet_communication_policy(
        preset=preset,
        policy=policy["categories"],
    )
    result["iteration_context_policy"] = iteration_context_policy(
        preset=preset,
        policy=policy["categories"],
    )
    result["pending_broadening_proposal"] = None
    if classification in {"narrowing", "mixed"}:
        result["dependent_views_stale"] = True
    history = list(result["change_history"])
    history.append(
        {
            "contract_revision": result["contract_revision"],
            "change_kind": classification,
            "preset": preset,
            "change_authority_provenance": "explicit_customer_contract_action",
            "effective_policy_digest": result["effective_policy_digest"],
        }
    )
    result["change_history"] = history[-64:]
    result["last_contract_management_receipt"] = _change_receipt(
        revision=int(result["contract_revision"]),
        classification=classification,
        surface=surface,
        changes=changes,
        effective_policy_digest=str(result["effective_policy_digest"]),
    )
    validate_contract(result)
    return result


def _proposal(
    *,
    contract: Mapping[str, Any],
    changes: Sequence[Mapping[str, Any]],
    customer_summary: str,
    scope: str,
    application_classification: str,
    target_preset: str,
) -> dict[str, Any]:
    proposal = {
        "schema_id": "qcoder.current_loop.contract_management_broadening.v1",
        "schema_version": 1,
        "expected_contract_revision": int(contract["contract_revision"]),
        "change_kind": "broadening",
        "application_classification": application_classification,
        "confirmation_scope": scope,
        "target_preset": target_preset,
        "changes": [
            {
                "path": str(item["path"]),
                "after": item["after"],
            }
            for item in changes
        ],
        "customer_summary": customer_summary,
        "approval_required": True,
        "authority_only_confirmation": True,
        "raw_json_retransmission_required": False,
    }
    proposal["proposal_reference"] = f"contract-proposal-{digest(proposal)[:24]}"
    proposal["proposal_digest"] = digest(proposal)
    return proposal


def apply_customer_contract_review(
    contract: Mapping[str, Any],
    review: Mapping[str, Any],
    *,
    choice: str,
    surface: str,
    explicit_authority: bool = False,
) -> dict[str, Any]:
    """Apply, propose, split, confirm, or cancel one already validated review."""

    validate_contract(contract)
    if review.get("schema_id") != CONTRACT_DIFF_SCHEMA_ID or review.get("valid") is not True:
        raise ContractManagementError("customer_contract_review_invalid")
    if review.get("expected_contract_revision") != contract["contract_revision"]:
        raise ContractManagementError("customer_contract_document_revision_stale")
    classification = str(review["classification"])
    changes = [deepcopy(dict(item)) for item in review["changes"]]
    current_settings = _customer_settings(contract)
    target_settings = deepcopy(review["after_customer_json"]["customer_settings"])
    if choice == "cancel":
        return {
            "disposition": "cancelled",
            "contract": deepcopy(dict(contract)),
            "proposal": None,
            "receipt": None,
        }
    if classification == "narrowing" and choice == "apply_narrowing":
        updated = _apply_settings(
            contract,
            settings=target_settings,
            classification="narrowing",
            surface=surface,
            changes=changes,
        )
        return {
            "disposition": "narrowing_applied",
            "contract": updated,
            "proposal": None,
            "receipt": deepcopy(updated["last_contract_management_receipt"]),
        }
    if classification == "broadening" and choice == "create_broadening_proposal":
        proposal = _proposal(
            contract=contract,
            changes=changes,
            customer_summary=str(review["customer_summary"]),
            scope="complete_change_set",
            application_classification="broadening",
            target_preset=str(target_settings["preset"]),
        )
        updated = deepcopy(dict(contract))
        updated["pending_broadening_proposal"] = proposal
        return {
            "disposition": "broadening_proposed",
            "contract": updated,
            "proposal": proposal,
            "receipt": None,
        }
    if classification == "mixed" and choice == "apply_narrowing_subset":
        narrowing = [item for item in changes if item["classification"] == "narrowing"]
        broadening = [item for item in changes if item["classification"] == "broadening"]
        narrowed_settings = deepcopy(current_settings)
        _apply_change_rows(narrowed_settings, narrowing)
        updated = _apply_settings(
            contract,
            settings=narrowed_settings,
            classification="narrowing",
            surface=surface,
            changes=narrowing,
        )
        rebased_broadening = deepcopy(broadening)
        for item in rebased_broadening:
            item["before"] = _value_at_settings(narrowed_settings, str(item["path"]))
        proposal = _proposal(
            contract=updated,
            changes=rebased_broadening,
            customer_summary="The broader subset awaits explicit confirmation.",
            scope="broadening_subset_after_narrowing",
            application_classification="broadening",
            target_preset=str(target_settings["preset"]),
        )
        updated["pending_broadening_proposal"] = proposal
        return {
            "disposition": "narrowing_applied_broadening_proposed",
            "contract": updated,
            "proposal": proposal,
            "receipt": deepcopy(updated["last_contract_management_receipt"]),
        }
    if classification == "mixed" and choice == "confirm_complete_change_set":
        proposal = _proposal(
            contract=contract,
            changes=changes,
            customer_summary=(
                "The complete mixed change set awaits one authority-only confirmation."
            ),
            scope="complete_mixed_change_set",
            application_classification="mixed",
            target_preset=str(target_settings["preset"]),
        )
        updated = deepcopy(dict(contract))
        updated["pending_broadening_proposal"] = proposal
        return {
            "disposition": "mixed_change_proposed",
            "contract": updated,
            "proposal": proposal,
            "receipt": None,
        }
    raise ContractManagementError("customer_contract_change_choice_invalid")


def _value_at_settings(settings: Mapping[str, Any], path: str) -> str:
    if path == "generation_governance":
        return str(settings["generation_governance"])
    _, category, dimension = path.split(".")
    return str(settings["evidence_categories"][category][dimension])


def confirm_customer_contract_broadening(
    contract: Mapping[str, Any],
    *,
    expected_contract_revision: int,
    explicit_authority: bool,
    surface: str,
) -> dict[str, Any]:
    """Apply only the exact qCoder-owned pending proposal by authority reference."""

    validate_contract(contract)
    if explicit_authority is not True:
        raise ContractManagementError("customer_contract_broadening_authority_required")
    if expected_contract_revision != contract["contract_revision"]:
        raise ContractManagementError("customer_contract_document_revision_stale")
    proposal = contract.get("pending_broadening_proposal")
    if not isinstance(proposal, Mapping):
        raise ContractManagementError("customer_contract_broadening_proposal_missing")
    if proposal.get("schema_id") != "qcoder.current_loop.contract_management_broadening.v1":
        raise ContractManagementError("customer_contract_broadening_proposal_kind_invalid")
    if proposal.get("expected_contract_revision") != expected_contract_revision:
        raise ContractManagementError("customer_contract_broadening_proposal_stale")
    checked = deepcopy(dict(proposal))
    supplied_digest = checked.pop("proposal_digest", None)
    if supplied_digest != digest(checked):
        raise ContractManagementError("customer_contract_broadening_proposal_digest_mismatch")
    changes = [deepcopy(dict(item)) for item in proposal["changes"]]
    settings = _customer_settings(contract)
    _apply_change_rows(settings, changes)
    target_preset = proposal.get("target_preset")
    if target_preset not in CUSTOMER_PRESETS:
        raise ContractManagementError("customer_contract_broadening_proposal_kind_invalid")
    settings["preset"] = target_preset
    classification = str(proposal.get("application_classification") or "broadening")
    if classification not in {"broadening", "mixed"}:
        raise ContractManagementError("customer_contract_broadening_proposal_kind_invalid")
    updated = _apply_settings(
        contract,
        settings=settings,
        classification=classification,
        surface=surface,
        changes=changes,
    )
    return {
        "disposition": "broadening_confirmed",
        "contract": updated,
        "proposal": None,
        "receipt": deepcopy(updated["last_contract_management_receipt"]),
    }


def reset_customer_contract_document(
    contract: Mapping[str, Any],
    *,
    preset: str,
) -> dict[str, Any]:
    """Create a complete editable draft compiled from one named preset."""

    if preset not in NAMED_PRESETS:
        raise ContractManagementError("customer_contract_reset_preset_invalid")
    document = customer_contract_document(contract)
    document["customer_settings"]["preset"] = preset
    compiled = compile_preset(preset)
    document["customer_settings"]["evidence_categories"] = {
        category: _customer_category_row(compiled["categories"][category])
        for category in EVIDENCE_CATEGORIES
    }
    if preset == "assist":
        document["customer_settings"]["generation_governance"] = "adaptive"
    return document


def contract_management_snapshot() -> dict[str, Any]:
    """Return the complete client-visible contract-management domain."""

    payload = {
        "schema_id": CONTRACT_MANAGEMENT_SCHEMA_ID,
        "schema_version": CONTRACT_MANAGEMENT_SCHEMA_VERSION,
        "title": "How qCoder should help with this build",
        "canonical_internal_name": "Current Loop Contract",
        "effective_document_schema": {
            "schema_id": EFFECTIVE_CONTRACT_DOCUMENT_SCHEMA_ID,
            "schema_version": 1,
            "read_only": True,
            "raw_state_excluded": True,
        },
        "customer_document_schema": {
            "schema_id": CUSTOMER_CONTRACT_DOCUMENT_SCHEMA_ID,
            "schema_version": 1,
            "canonical_encoding": "UTF-8 JSON",
            "maximum_bytes": CUSTOMER_DOCUMENT_MAX_BYTES,
            "maximum_depth": CUSTOMER_DOCUMENT_MAX_DEPTH,
            "unknown_keys": "rejected",
            "duplicate_keys": "rejected",
            "prototype_pollution_keys": "rejected",
            "yaml_supported": False,
            "qcoder_owned_fields": [
                "schema_id",
                "schema_version",
                "expected_contract_revision",
            ],
            "customer_settings": {
                "preset": list(CUSTOMER_PRESETS),
                "generation_governance": list(GENERATION_GOVERNANCE_VALUES),
                "evidence_categories": {
                    "categories": [
                        {"value": value, "customer_meaning": CATEGORY_MEANINGS[value]}
                        for value in EVIDENCE_CATEGORIES
                    ],
                    "dimensions": [
                        {
                            "value": value,
                            "customer_meaning": CUSTOMER_DIMENSION_MEANINGS[value],
                            "accepted_values": list(CUSTOMER_VALUES[value]),
                        }
                        for value in CUSTOMER_DIMENSIONS
                    ],
                },
                "hosted_enrichment": ["on_request"],
                "build_review": ["on_request"],
            },
        },
        "change_set_schema_id": CONTRACT_CHANGE_SET_SCHEMA_ID,
        "diff_schema_id": CONTRACT_DIFF_SCHEMA_ID,
        "validation_schema_id": CONTRACT_VALIDATION_SCHEMA_ID,
        "receipt_schema_id": CONTRACT_CHANGE_RECEIPT_SCHEMA_ID,
        "classification": ["narrowing", "broadening", "mixed", "neutral", "invalid"],
        "narrowing": "immediate_revisioned_receipt",
        "broadening": "explicit_authority_only_confirmation",
        "mixed": "no_silent_partial_application",
        "canonical_service_shared_by": ["coordinator_ide", "local_browser", "tests"],
        "browser_optional": True,
        "customer_cli_required": False,
        "raw_state_replacement_accepted": False,
        "assistant_reconstruction_permitted": False,
        "cross_loop_persistence": False,
    }
    payload["contract_digest"] = digest(payload)
    return payload


def semantic_contract_equivalence() -> dict[str, Any]:
    """Machine proof that customer domains derive from the canonical compiler."""

    preset_domains = {
        preset: {
            category: _customer_category_row(compile_preset(preset)["categories"][category])
            for category in EVIDENCE_CATEGORIES
        }
        for preset in NAMED_PRESETS
    }
    return {
        "schema_id": "qcoder.current_loop.contract_management_domain_equivalence.v1",
        "preset_domains": preset_domains,
        "generation_governance": list(GENERATION_GOVERNANCE_VALUES),
        "canonical_evidence_categories": list(EVIDENCE_CATEGORIES),
        "legacy_adjustment_domains": {
            key: list(values) for key, values in ADJUSTMENT_VALUES_BY_DIMENSION.items()
        },
        "preset_provenance_domain": list(PRESET_PROVENANCE),
        "duplicate_policy_tables": False,
    }
