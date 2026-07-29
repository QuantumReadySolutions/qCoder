"""Canonical one-loop participation policy for Explorer Current Loop.

The contract is embedded in the canonical local Current Loop state.  This
module owns compilation, validation, comparison, bounded changes, evidence
controls, and policy enforcement; it never reads a workspace or persists data.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Mapping


CONTRACT_SCHEMA_ID = "qcoder.current_loop.contract.v1"
CONTRACT_SCHEMA_VERSION = 1
CONTRACT_MAX_HISTORY = 64
CONTRACT_MAX_EXCLUSIONS = 128
CONTRACT_MAX_TOMBSTONES = 128

PRESETS = ("evidence_only", "assist", "custom")
PRESET_PROVENANCE = (
    "activation_default",
    "explicit_customer_selection",
    "customer_confirmed_broadening",
    "customer_requested_narrowing",
    "migrated_local_state_v2",
)
EVIDENCE_CATEGORIES = (
    "request_baseline",
    "working_blueprint",
    "generation_context",
    "python_manifestation",
    "circuit_manifestation",
    "result_manifestation",
    "lineage",
    "derived_metrics",
)
DIMENSIONS = (
    "collect",
    "derive",
    "expose",
    "recommend",
    "prepare",
    "request_application_or_execution",
)
EXPOSURE_DESTINATIONS = ("local_qcoder", "local_presentation", "connected_assistant")
EXPOSURE_FORMS = ("raw", "derived")
EXPOSURE_MODES = ("standing", "on_request")


class CurrentLoopContractError(ValueError):
    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _exposure(*, local: bool, assistant_derived: str, assistant_raw: str) -> dict[str, Any]:
    return {
        "local_qcoder": {"raw": "standing" if local else "disabled", "derived": "standing"},
        "local_presentation": {"raw": "on_request" if local else "disabled", "derived": "standing"},
        "connected_assistant": {
            "raw": assistant_raw,
            "derived": assistant_derived,
        },
    }


def _category_policy(*, preset: str) -> dict[str, Any]:
    if preset == "evidence_only":
        return {
            "collect": True,
            "derive": True,
            "expose": _exposure(
                local=True,
                assistant_derived="on_request",
                assistant_raw="disabled",
            ),
            "recommend": False,
            "prepare": "disabled",
            "request_application_or_execution": False,
        }
    if preset == "assist":
        return {
            "collect": True,
            "derive": True,
            "expose": _exposure(
                local=True,
                assistant_derived="standing",
                assistant_raw="disabled",
            ),
            "recommend": True,
            "prepare": "bounded_non_material",
            "request_application_or_execution": True,
        }
    raise CurrentLoopContractError("contract_preset_invalid")


def compile_preset(preset: str) -> dict[str, Any]:
    """Compile a named preset into the complete category policy."""

    if preset not in {"evidence_only", "assist"}:
        raise CurrentLoopContractError("contract_named_preset_invalid")
    return {
        "categories": {
            category: _category_policy(preset=preset) for category in EVIDENCE_CATEGORIES
        },
        "policy_ceiling": {
            "application_or_execution_authority_granted": False,
            "blueprint_evolution_permitted": False,
            "raw_assistant_exposure_permitted": False,
            "paid_or_external_activity_permitted": False,
            "automatic_editing_permitted": False,
            "automatic_execution_permitted": False,
        },
    }


def policy_digest(policy: Mapping[str, Any]) -> str:
    return digest(policy)


def policy_summary(preset: str) -> str:
    if preset == "evidence_only":
        return (
            "qCoder may collect and organize explicitly authorized evidence locally. "
            "Share-safe derived context is available only on request; standing "
            "recommendation, preparation, raw exposure, and execution requests are off."
        )
    if preset == "assist":
        return (
            "qCoder may collect authorized evidence, derive local views, share selected "
            "share-safe derived context, recommend bounded next checks, and prepare "
            "non-material summaries. Raw exposure, application, and execution remain separate."
        )
    return "The active bounded Custom policy applies; all execution authority remains separate."


def new_contract(
    *,
    baseline_digest: str,
    capture_provenance: str,
    activation_revision: int,
) -> dict[str, Any]:
    policy = compile_preset("assist")
    receipt = {
        "schema_id": "qcoder.current_loop.activation_receipt.v1",
        "schema_version": 1,
        "baseline_utf8_sha256": baseline_digest,
        "capture_provenance": capture_provenance,
        "contract_schema_id": CONTRACT_SCHEMA_ID,
        "contract_schema_version": CONTRACT_SCHEMA_VERSION,
        "contract_revision": 1,
        "preset": "assist",
        "effective_policy_digest": policy_digest(policy),
        "activation_revision": activation_revision,
        "effective_policy_summary": policy_summary("assist"),
        "authority_scope": [
            "activate_current_loop",
            "preserve_exact_request_baseline",
            "apply_assist",
        ],
        "authority_exclusions": [
            "generation_posture",
            "material_blueprint_decision",
            "ide_write_or_run",
            "raw_exposure",
            "contract_broadening",
            "artifact_review",
            "governing_change",
            "external_service_or_hardware",
        ],
    }
    receipt["receipt_digest"] = digest(receipt)
    contract = {
        "schema_id": CONTRACT_SCHEMA_ID,
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "contract_revision": 1,
        "effective_preset": "assist",
        "preset_provenance": "activation_default",
        "effective_policy": policy,
        "effective_policy_digest": policy_digest(policy),
        "activation_receipt": receipt,
        "pending_broadening_proposal": None,
        "evidence_exclusions": {},
        "evidence_deletion_tombstones": [],
        "change_history": [],
        "dependent_views_stale": False,
        "inactive_after_loop_close": True,
        "cross_loop_inheritance": False,
        "account_synchronization": False,
        "automatic_reopen": False,
        "project_history": False,
    }
    error = contract_error(contract)
    if error:
        raise CurrentLoopContractError(error)
    return contract


def _policy_rank(value: Any) -> int:
    if value in {False, "disabled", None}:
        return 0
    if value == "on_request":
        return 1
    if value in {True, "bounded_non_material", "standing"}:
        return 2
    raise CurrentLoopContractError("contract_policy_value_invalid")


def classify_change(old: Mapping[str, Any], new: Mapping[str, Any]) -> str:
    old_flat: list[int] = []
    new_flat: list[int] = []

    def walk(left: Any, right: Any) -> None:
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            if set(left) != set(right):
                raise CurrentLoopContractError("contract_policy_shape_invalid")
            for key in sorted(left):
                walk(left[key], right[key])
            return
        old_flat.append(_policy_rank(left))
        new_flat.append(_policy_rank(right))

    walk(old, new)
    greater = any(after > before for before, after in zip(old_flat, new_flat, strict=True))
    lesser = any(after < before for before, after in zip(old_flat, new_flat, strict=True))
    if greater:
        return "broadening"
    if lesser:
        return "narrowing"
    return "unchanged"


def _bounded_history(
    history: list[dict[str, Any]], item: Mapping[str, Any]
) -> list[dict[str, Any]]:
    return [*history, deepcopy(dict(item))][-CONTRACT_MAX_HISTORY:]


def _apply_policy(
    contract: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    preset: str,
    provenance: str,
    change_kind: str,
) -> dict[str, Any]:
    result = deepcopy(dict(contract))
    result["contract_revision"] = int(result["contract_revision"]) + 1
    result["effective_policy"] = deepcopy(dict(policy))
    result["effective_policy_digest"] = policy_digest(policy)
    result["effective_preset"] = preset
    result["preset_provenance"] = provenance
    result["pending_broadening_proposal"] = None
    if change_kind == "narrowing":
        result["dependent_views_stale"] = True
    result["change_history"] = _bounded_history(
        list(result["change_history"]),
        {
            "contract_revision": result["contract_revision"],
            "change_kind": change_kind,
            "preset": preset,
            "provenance": provenance,
            "effective_policy_digest": result["effective_policy_digest"],
        },
    )
    return result


def set_preset(
    contract: Mapping[str, Any],
    *,
    preset: str,
    expected_contract_revision: int,
    provenance: str,
) -> dict[str, Any]:
    validate_contract(contract)
    if expected_contract_revision != contract["contract_revision"]:
        raise CurrentLoopContractError("contract_revision_stale")
    if preset not in {"evidence_only", "assist"}:
        raise CurrentLoopContractError("contract_preset_invalid")
    if provenance not in PRESET_PROVENANCE:
        raise CurrentLoopContractError("contract_provenance_invalid")
    policy = compile_preset(preset)
    kind = classify_change(contract["effective_policy"], policy)
    if kind != "broadening":
        return {
            "disposition": kind,
            "contract": _apply_policy(
                contract,
                policy=policy,
                preset=preset,
                provenance=provenance,
                change_kind=kind,
            ),
            "proposal": None,
        }
    proposal = {
        "schema_id": "qcoder.current_loop.contract_broadening.v1",
        "schema_version": 1,
        "proposal_revision": int(contract["contract_revision"]) + 1,
        "expected_contract_revision": contract["contract_revision"],
        "proposed_preset": preset,
        "proposed_policy": policy,
        "proposed_policy_digest": policy_digest(policy),
        "change_kind": "broadening",
        "approval_required": True,
        "raw_policy_retransmission_required": False,
    }
    proposal["proposal_digest"] = digest(proposal)
    result = deepcopy(dict(contract))
    result["pending_broadening_proposal"] = proposal
    return {"disposition": "broadening", "contract": result, "proposal": proposal}


def adjust(
    contract: Mapping[str, Any],
    *,
    category: str,
    dimension: str,
    value: str,
    expected_contract_revision: int,
    provenance: str,
) -> dict[str, Any]:
    validate_contract(contract)
    if expected_contract_revision != contract["contract_revision"]:
        raise CurrentLoopContractError("contract_revision_stale")
    if category not in EVIDENCE_CATEGORIES:
        raise CurrentLoopContractError("contract_category_invalid")
    if dimension not in {
        "collect",
        "derive",
        "recommend",
        "prepare",
        "request_application_or_execution",
        "assistant_derived_exposure",
        "assistant_raw_exposure",
    }:
        raise CurrentLoopContractError("contract_dimension_invalid")
    if provenance not in PRESET_PROVENANCE:
        raise CurrentLoopContractError("contract_provenance_invalid")
    policy = deepcopy(dict(contract["effective_policy"]))
    row = policy["categories"][category]
    if dimension in {"collect", "derive", "recommend", "request_application_or_execution"}:
        if value not in {"enabled", "disabled"}:
            raise CurrentLoopContractError("contract_adjustment_value_invalid")
        row[dimension] = value == "enabled"
    elif dimension == "prepare":
        if value not in {"disabled", "bounded_non_material"}:
            raise CurrentLoopContractError("contract_adjustment_value_invalid")
        row["prepare"] = value
    else:
        if value not in {"disabled", "on_request", "standing"}:
            raise CurrentLoopContractError("contract_adjustment_value_invalid")
        form = "derived" if dimension == "assistant_derived_exposure" else "raw"
        if form == "raw" and value != "disabled":
            raise CurrentLoopContractError("contract_raw_exposure_ceiling")
        row["expose"]["connected_assistant"][form] = value
    kind = classify_change(contract["effective_policy"], policy)
    if kind == "broadening":
        proposal = {
            "schema_id": "qcoder.current_loop.contract_broadening.v1",
            "schema_version": 1,
            "proposal_revision": int(contract["contract_revision"]) + 1,
            "expected_contract_revision": contract["contract_revision"],
            "proposed_preset": "custom",
            "proposed_policy": policy,
            "proposed_policy_digest": policy_digest(policy),
            "change_kind": "broadening",
            "approval_required": True,
            "raw_policy_retransmission_required": False,
            "bounded_change": {"category": category, "dimension": dimension, "value": value},
        }
        proposal["proposal_digest"] = digest(proposal)
        result = deepcopy(dict(contract))
        result["pending_broadening_proposal"] = proposal
        return {"disposition": kind, "contract": result, "proposal": proposal}
    return {
        "disposition": kind,
        "contract": _apply_policy(
            contract,
            policy=policy,
            preset="custom",
            provenance=provenance,
            change_kind=kind,
        ),
        "proposal": None,
    }


def confirm_broadening(
    contract: Mapping[str, Any],
    *,
    expected_contract_revision: int,
    explicit_authority: bool,
) -> dict[str, Any]:
    validate_contract(contract)
    if explicit_authority is not True:
        raise CurrentLoopContractError("contract_broadening_authority_required")
    if expected_contract_revision != contract["contract_revision"]:
        raise CurrentLoopContractError("contract_revision_stale")
    proposal = contract.get("pending_broadening_proposal")
    if not isinstance(proposal, Mapping):
        raise CurrentLoopContractError("contract_broadening_proposal_missing")
    if proposal.get("expected_contract_revision") != expected_contract_revision:
        raise CurrentLoopContractError("contract_broadening_proposal_stale")
    check = deepcopy(dict(proposal))
    supplied_digest = check.pop("proposal_digest", None)
    if supplied_digest != digest(check):
        raise CurrentLoopContractError("contract_broadening_proposal_digest_mismatch")
    return _apply_policy(
        contract,
        policy=proposal["proposed_policy"],
        preset=str(proposal["proposed_preset"]),
        provenance="customer_confirmed_broadening",
        change_kind="broadening",
    )


def exclude_evidence(
    contract: Mapping[str, Any],
    *,
    artifact_reference: str,
    artifact_digest: str,
    reason: str,
    expected_contract_revision: int,
) -> dict[str, Any]:
    validate_contract(contract)
    if expected_contract_revision != contract["contract_revision"]:
        raise CurrentLoopContractError("contract_revision_stale")
    exclusions = deepcopy(dict(contract["evidence_exclusions"]))
    if len(exclusions) >= CONTRACT_MAX_EXCLUSIONS and artifact_reference not in exclusions:
        raise CurrentLoopContractError("contract_evidence_exclusions_full")
    exclusions[artifact_reference] = {
        "artifact_reference": artifact_reference,
        "artifact_digest": artifact_digest,
        "reason": reason,
        "excluded_at_contract_revision": int(contract["contract_revision"]) + 1,
    }
    result = deepcopy(dict(contract))
    result["contract_revision"] += 1
    result["evidence_exclusions"] = exclusions
    result["dependent_views_stale"] = True
    result["change_history"] = _bounded_history(
        result["change_history"],
        {
            "contract_revision": result["contract_revision"],
            "change_kind": "evidence_excluded",
            "artifact_reference": artifact_reference,
        },
    )
    return result


def restore_evidence(
    contract: Mapping[str, Any],
    *,
    artifact_reference: str,
    artifact_digest: str,
    expected_contract_revision: int,
) -> dict[str, Any]:
    validate_contract(contract)
    if expected_contract_revision != contract["contract_revision"]:
        raise CurrentLoopContractError("contract_revision_stale")
    exclusions = deepcopy(dict(contract["evidence_exclusions"]))
    record = exclusions.get(artifact_reference)
    if not isinstance(record, Mapping):
        raise CurrentLoopContractError("contract_evidence_exclusion_missing")
    if record.get("artifact_digest") != artifact_digest:
        raise CurrentLoopContractError("contract_evidence_restore_digest_mismatch")
    del exclusions[artifact_reference]
    result = deepcopy(dict(contract))
    result["contract_revision"] += 1
    result["evidence_exclusions"] = exclusions
    result["dependent_views_stale"] = True
    result["change_history"] = _bounded_history(
        result["change_history"],
        {
            "contract_revision": result["contract_revision"],
            "change_kind": "evidence_restored",
            "artifact_reference": artifact_reference,
        },
    )
    return result


def record_deletion(
    contract: Mapping[str, Any],
    *,
    artifact_reference: str,
    artifact_digest: str,
    artifact_role: str,
    expected_contract_revision: int,
) -> dict[str, Any]:
    validate_contract(contract)
    if expected_contract_revision != contract["contract_revision"]:
        raise CurrentLoopContractError("contract_revision_stale")
    tombstones = deepcopy(list(contract["evidence_deletion_tombstones"]))
    if len(tombstones) >= CONTRACT_MAX_TOMBSTONES:
        raise CurrentLoopContractError("contract_evidence_deletions_full")
    tombstones.append(
        {
            "artifact_reference": artifact_reference,
            "artifact_digest": artifact_digest,
            "artifact_role": artifact_role,
            "deleted_at_contract_revision": int(contract["contract_revision"]) + 1,
            "raw_content_retained": False,
        }
    )
    result = deepcopy(dict(contract))
    result["contract_revision"] += 1
    result["evidence_deletion_tombstones"] = tombstones
    result["evidence_exclusions"].pop(artifact_reference, None)
    result["dependent_views_stale"] = True
    result["change_history"] = _bounded_history(
        result["change_history"],
        {
            "contract_revision": result["contract_revision"],
            "change_kind": "local_evidence_deleted",
            "artifact_reference": artifact_reference,
        },
    )
    return result


def permits(
    contract: Mapping[str, Any],
    *,
    category: str,
    dimension: str,
    artifact_reference: str | None = None,
) -> bool:
    validate_contract(contract)
    if category not in EVIDENCE_CATEGORIES:
        raise CurrentLoopContractError("contract_category_invalid")
    if artifact_reference in contract["evidence_exclusions"]:
        return False
    row = contract["effective_policy"]["categories"][category]
    if dimension == "prepare":
        return row[dimension] != "disabled"
    if dimension in {"collect", "derive", "recommend", "request_application_or_execution"}:
        return bool(row[dimension])
    if dimension == "assistant_derived_exposure":
        return row["expose"]["connected_assistant"]["derived"] != "disabled"
    if dimension == "assistant_raw_exposure":
        return row["expose"]["connected_assistant"]["raw"] != "disabled"
    raise CurrentLoopContractError("contract_dimension_invalid")


def contract_error(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return "current_loop_contract_invalid"
    if (
        value.get("schema_id") != CONTRACT_SCHEMA_ID
        or value.get("schema_version") != CONTRACT_SCHEMA_VERSION
    ):
        return "current_loop_contract_version_invalid"
    if not isinstance(value.get("contract_revision"), int) or value["contract_revision"] < 1:
        return "current_loop_contract_revision_invalid"
    if value.get("effective_preset") not in PRESETS:
        return "current_loop_contract_preset_invalid"
    if value.get("preset_provenance") not in PRESET_PROVENANCE:
        return "current_loop_contract_provenance_invalid"
    policy = value.get("effective_policy")
    if not isinstance(policy, Mapping):
        return "current_loop_contract_policy_invalid"
    categories = policy.get("categories")
    if not isinstance(categories, Mapping) or tuple(sorted(categories)) != tuple(
        sorted(EVIDENCE_CATEGORIES)
    ):
        return "current_loop_contract_categories_invalid"
    if value.get("effective_policy_digest") != policy_digest(policy):
        return "current_loop_contract_policy_digest_mismatch"
    if not isinstance(value.get("activation_receipt"), Mapping):
        return "current_loop_contract_activation_receipt_invalid"
    if not isinstance(value.get("evidence_exclusions"), Mapping):
        return "current_loop_contract_exclusions_invalid"
    if not isinstance(value.get("evidence_deletion_tombstones"), list):
        return "current_loop_contract_deletions_invalid"
    if not isinstance(value.get("change_history"), list):
        return "current_loop_contract_history_invalid"
    if len(value["change_history"]) > CONTRACT_MAX_HISTORY:
        return "current_loop_contract_history_too_large"
    if value.get("cross_loop_inheritance") is not False:
        return "current_loop_contract_persistence_invalid"
    if value.get("account_synchronization") is not False:
        return "current_loop_contract_persistence_invalid"
    if value.get("automatic_reopen") is not False or value.get("project_history") is not False:
        return "current_loop_contract_persistence_invalid"
    return None


def validate_contract(value: object) -> None:
    error = contract_error(value)
    if error:
        raise CurrentLoopContractError(error)


def contract_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": CONTRACT_SCHEMA_ID,
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "presets": ["off", *PRESETS],
        "off_is_absence_of_active_loop": True,
        "dimensions": list(DIMENSIONS),
        "evidence_categories": list(EVIDENCE_CATEGORIES),
        "raw_and_derived_exposure_distinct": True,
        "local_and_assistant_destinations_distinct": True,
        "standing_and_on_request_distinct": True,
        "canonical_serialization": "json",
        "yaml_authoritative": False,
        "cross_loop_inheritance": False,
    }
    payload["contract_digest"] = digest(payload)
    return payload
