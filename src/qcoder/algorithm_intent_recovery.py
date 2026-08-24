"""Stateless clarification recovery for Algorithm Intent Cards."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping

from qcoder.algorithm_blueprint import (
    PROFILE_DEFINITIONS,
    artifact_digest_matches,
)


RECOVERY_SCHEMA_ID = "qcoder.algorithm_intent.clarification_recovery.v1"
RECOVERY_SCHEMA_VERSION = 1
RECOVERY_CONTRACT_ID = "qcoder.algorithm_intent.clarification_recovery.v1"
RECOVERY_INPUT_FIELD = "clarification_recovery"
EXPLICIT_CONFIRMATION_FIELD = "explicit_confirmation_assertion"


class ClarificationRecoveryError(ValueError):
    """Bounded recovery error that is safe to project to a connected client."""

    def __init__(
        self,
        category: str,
        *,
        field: str | None = None,
        trigger_class: str | None = None,
        expected: Mapping[str, Any] | None = None,
        safe_next_action: str = "resupply_the_exact_returned_contract_and_a_bounded_correction",
    ) -> None:
        super().__init__(category)
        self.category = category
        self.field = field
        self.trigger_class = trigger_class
        self.expected = deepcopy(dict(expected)) if expected is not None else None
        self.safe_next_action = safe_next_action


def _canonical_digest(value: Mapping[str, Any], *, omitted: frozenset[str]) -> str:
    projected = {str(key): deepcopy(item) for key, item in value.items() if str(key) not in omitted}
    encoded = json.dumps(
        projected,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _card_binding(card: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_type": "algorithm_intent_card",
        "schema_version": card.get("schema_version"),
        "artifact_digest": card.get("artifact_digest"),
        "revision_digest": card.get("artifact_digest"),
    }


def _profile_id(card: Mapping[str, Any]) -> str:
    profile = card.get("profile")
    if isinstance(profile, Mapping) and isinstance(profile.get("id"), str):
        return str(profile["id"])
    selected = card.get("selected_profile")
    return str(selected) if isinstance(selected, str) else ""


def _unresolved_fields(card: Mapping[str, Any]) -> list[str]:
    value = card.get("unresolved_questions")
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        field = str(item).strip()
        if field and field not in result:
            result.append(field)
    return result


def _field_contract(profile_id: str, field: str) -> dict[str, Any]:
    if field == EXPLICIT_CONFIRMATION_FIELD:
        return {
            "field_id": field,
            "expected_type": "boolean",
            "machine_domain": [True],
            "customer_facing_meaning": (
                "The customer explicitly reviewed the bounded interpretation supplied for this revision."
            ),
            "explicit_confirmation_required": True,
        }
    definition = PROFILE_DEFINITIONS[profile_id]
    if field not in definition["required_fields"]:
        raise ClarificationRecoveryError(
            "clarification_recovery_unknown_unresolved_field",
            field=field,
            trigger_class="unsupported_correction_shape",
            safe_next_action="request_a_fresh_intent_card_without_inferring_a_field",
        )
    return {
        "field_id": field,
        "expected_type": "non_empty_string",
        "customer_facing_meaning": definition["questions"].get(
            field,
            f"Supply the customer-reviewed meaning for {field.replace('_', ' ')}.",
        ),
        "explicit_confirmation_required": True,
    }


def build_clarification_recovery_contract(card: Mapping[str, Any]) -> dict[str, Any]:
    """Build the exact bounded continuation contract for one returned card revision."""

    supplied = deepcopy(dict(card))
    if (
        supplied.get("artifact_type") != "algorithm_intent_card"
        or supplied.get("confirmation_state") != "needs_clarification"
        or not artifact_digest_matches(supplied)
    ):
        raise ClarificationRecoveryError(
            "clarification_recovery_card_invalid",
            trigger_class="stale_or_cross_card",
            safe_next_action="use_the_exact_current_needs_clarification_card",
        )
    profile_id = _profile_id(supplied)
    if profile_id not in PROFILE_DEFINITIONS:
        raise ClarificationRecoveryError(
            "clarification_recovery_profile_invalid",
            field="profile_id",
            trigger_class="unsupported_correction_shape",
            safe_next_action="request_a_fresh_supported_profile_card",
        )
    unresolved = _unresolved_fields(supplied)
    if not unresolved:
        raise ClarificationRecoveryError(
            "clarification_recovery_unresolved_fields_missing",
            trigger_class="unsupported_correction_shape",
            safe_next_action="request_a_fresh_intent_card_without_inferring_fields",
        )
    field_contracts = [_field_contract(profile_id, field) for field in unresolved]
    correction_fields = [
        item["field_id"]
        for item in field_contracts
        if item["field_id"] != EXPLICIT_CONFIRMATION_FIELD
    ]
    binding = _card_binding(supplied)
    contract: dict[str, Any] = {
        "schema_id": RECOVERY_SCHEMA_ID,
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "contract_id": RECOVERY_CONTRACT_ID,
        "card_binding": binding,
        "unresolved_fields": field_contracts,
        "explicit_confirmation_required": True,
        "safe_correction_shape": {
            "type": "object",
            "required": [
                "card_binding",
                "field_values",
                "confirmation_assertion",
            ],
            "properties": {
                "card_binding": deepcopy(binding),
                "field_values": {
                    "type": "object",
                    "allowed_fields": correction_fields,
                    "additional_properties": False,
                },
                "confirmation_assertion": {
                    "type": "object",
                    "required": ["user_reviewed"],
                    "properties": {"user_reviewed": {"const": True}},
                    "additional_properties": False,
                },
            },
            "additional_properties": False,
        },
        "supported_next_invocation": {
            "tool_name": "create_algorithm_intent_card",
            "argument_field": RECOVERY_INPUT_FIELD,
            "required_envelope_fields": [
                "contract",
                "prior_algorithm_intent_card",
                "correction",
            ],
            "additional_properties": False,
        },
        "binding_guards": {
            "stale_card_refused": True,
            "cross_card_refused": True,
            "cross_revision_refused": True,
            "hidden_lookup": False,
        },
        "retention": "process_and_discard",
        "raw_rejected_value_returned": False,
    }
    contract["contract_digest"] = _canonical_digest(
        contract,
        omitted=frozenset({"contract_digest"}),
    )
    return contract


def clarification_recovery_contract_snapshot() -> dict[str, Any]:
    """Return the client-neutral recovery semantics without card-specific values."""

    return {
        "schema_id": RECOVERY_SCHEMA_ID,
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "contract_id": RECOVERY_CONTRACT_ID,
        "input_field": RECOVERY_INPUT_FIELD,
        "card_and_revision_bound": True,
        "field_local_diagnostics": True,
        "explicit_confirmation_required": True,
        "stale_cross_card_cross_revision_refused": True,
        "raw_rejected_value_returned": False,
        "retention": "process_and_discard",
        "hidden_lookup": False,
        "public_tool_added": False,
    }


def prepare_clarification_recovery(
    envelope: object,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate one exact recovery envelope and expand it to the existing operation."""

    if not isinstance(envelope, Mapping) or set(envelope) != {
        "contract",
        "prior_algorithm_intent_card",
        "correction",
    }:
        raise ClarificationRecoveryError(
            "clarification_recovery_envelope_invalid",
            trigger_class="unsupported_correction_shape",
        )
    prior = envelope.get("prior_algorithm_intent_card")
    contract = envelope.get("contract")
    correction = envelope.get("correction")
    if not isinstance(prior, Mapping) or not isinstance(contract, Mapping):
        raise ClarificationRecoveryError(
            "clarification_recovery_binding_invalid",
            trigger_class="stale_or_cross_card",
            safe_next_action="resupply_the_exact_returned_card_and_contract",
        )
    expected_contract = build_clarification_recovery_contract(prior)
    if dict(contract) != expected_contract:
        raise ClarificationRecoveryError(
            "clarification_recovery_contract_mismatch",
            trigger_class="stale_or_cross_revision",
            safe_next_action="use_the_contract_returned_with_this_exact_card_revision",
        )
    if not isinstance(correction, Mapping) or set(correction) != {
        "card_binding",
        "field_values",
        "confirmation_assertion",
    }:
        raise ClarificationRecoveryError(
            "clarification_recovery_correction_shape_invalid",
            trigger_class="unsupported_correction_shape",
        )
    if correction.get("card_binding") != expected_contract["card_binding"]:
        raise ClarificationRecoveryError(
            "clarification_recovery_card_binding_mismatch",
            trigger_class="stale_or_cross_revision",
            safe_next_action="bind_the_correction_to_the_exact_returned_card_revision",
        )
    assertion = correction.get("confirmation_assertion")
    if not isinstance(assertion, Mapping) or dict(assertion) != {"user_reviewed": True}:
        raise ClarificationRecoveryError(
            "clarification_recovery_explicit_confirmation_required",
            field=EXPLICIT_CONFIRMATION_FIELD,
            trigger_class="type_or_domain_mismatch",
            expected={"type": "boolean", "machine_domain": [True]},
            safe_next_action="obtain_customer_review_before_resubmitting",
        )
    field_values = correction.get("field_values")
    if not isinstance(field_values, Mapping):
        raise ClarificationRecoveryError(
            "clarification_recovery_field_values_required",
            trigger_class="unsupported_correction_shape",
        )
    allowed = {
        str(item["field_id"]): item
        for item in expected_contract["unresolved_fields"]
        if item["field_id"] != EXPLICIT_CONFIRMATION_FIELD
    }
    unknown = sorted(str(field) for field in field_values if str(field) not in allowed)
    if unknown:
        raise ClarificationRecoveryError(
            "clarification_recovery_field_not_unresolved",
            field=unknown[0],
            trigger_class="unsupported_correction_shape",
            expected={"allowed_fields": sorted(allowed)},
            safe_next_action="submit_only_a_field_listed_as_unresolved",
        )
    normalized: dict[str, str] = {}
    for field, value in field_values.items():
        field_name = str(field)
        if not isinstance(value, str) or not value.strip():
            raise ClarificationRecoveryError(
                "clarification_recovery_value_type_invalid",
                field=field_name,
                trigger_class="type_or_domain_mismatch",
                expected={"type": "non_empty_string"},
                safe_next_action="supply_one_non_empty_customer_reviewed_string",
            )
        normalized[field_name] = value

    prior_card = deepcopy(dict(prior))
    interpretation = prior_card.get("interpretation")
    if not isinstance(interpretation, Mapping):
        interpretation = {}
    merged_interpretation = deepcopy(dict(interpretation))
    merged_interpretation.update(normalized)
    provenance = prior_card.get("field_provenance")
    merged_provenance = deepcopy(dict(provenance)) if isinstance(provenance, Mapping) else {}
    merged_provenance.update({field: "user" for field in normalized})
    profile_id = _profile_id(prior_card)
    expanded = {
        "original_user_intent": prior_card["original_user_intent"],
        "profile_id": profile_id,
        "proposed_interpretation": merged_interpretation,
        "requirements": deepcopy(prior_card.get("requirements") or []),
        "constraints": deepcopy(prior_card.get("implementation_constraints") or []),
        "non_goals": deepcopy(prior_card.get("explicit_non_goals") or []),
        "field_provenance": merged_provenance,
        "requested_confirmation_state": "confirmed",
        "confirmation_assertion": {"user_reviewed": True},
        "accepted_unresolved_choices": deepcopy(
            prior_card.get("user_accepted_unresolved_choices") or []
        ),
    }
    return expanded, {
        "recovered_from_card_digest": prior_card["artifact_digest"],
        "corrected_fields": sorted(normalized),
    }


__all__ = [
    "ClarificationRecoveryError",
    "EXPLICIT_CONFIRMATION_FIELD",
    "RECOVERY_CONTRACT_ID",
    "RECOVERY_INPUT_FIELD",
    "RECOVERY_SCHEMA_ID",
    "RECOVERY_SCHEMA_VERSION",
    "build_clarification_recovery_contract",
    "clarification_recovery_contract_snapshot",
    "prepare_clarification_recovery",
]
