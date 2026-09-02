"""Strict public validation for bounded protected requests and inert proposals."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from qcoder.protected_capability import ProtectedCapabilityCategory
from qcoder.protected_decision_contract import (
    INTENT_KEYS,
    PROPOSAL_CONTRACT_ID,
    PROPOSAL_KEYS,
    REQUEST_CONTRACT_ID,
    REQUEST_KEYS,
    RESPONSE_CONTRACT_ID,
    RESPONSE_REQUIRED_KEYS,
    canonical_digest,
    canonical_json_bytes,
)

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_NONCE = re.compile(r"^[A-Za-z0-9_-]{22,128}$")
_FORBIDDEN_ANYWHERE = frozenset(
    {
        "code",
        "comments",
        "counts",
        "credential",
        "customer_data",
        "filename",
        "notebook",
        "path",
        "private_client_state",
        "provider_result",
        "qasm",
        "qir",
        "raw_conversation",
        "raw_prompt",
        "source",
        "token",
    }
)


def decode_json_strict(raw: bytes) -> dict[str, Any]:
    if len(raw) > 16_384:
        raise ValueError("protected_contract_too_large")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("protected_contract_duplicate_key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("protected_contract_nonfinite_number")
            ),
        )
    except UnicodeDecodeError as exc:
        raise ValueError("protected_contract_utf8_invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("protected_contract_not_object")
    return value


def _exact_keys(value: Mapping[str, Any], keys: frozenset[str], category: str) -> None:
    if set(value) != keys:
        raise ValueError(f"protected_{category}_keys_invalid")


def _digest(value: Any, category: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ValueError(f"protected_{category}_invalid")
    return value


def _timestamp(value: Any, *, now: datetime | None = None) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("protected_expiry_invalid")
    try:
        expiry = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("protected_expiry_invalid") from exc
    current = now or datetime.now(timezone.utc)
    if expiry <= current:
        raise ValueError("protected_capability_expired")
    return value


def _reject_forbidden_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key.casefold() in _FORBIDDEN_ANYWHERE:
                raise ValueError("protected_customer_or_raw_field_prohibited")
            _reject_forbidden_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_forbidden_keys(item)


def validate_request(value: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    _exact_keys(value, REQUEST_KEYS, "request")
    if value.get("contract_id") != REQUEST_CONTRACT_ID or value.get("contract_version") != 1:
        raise ValueError("protected_request_contract_unsupported")
    if not isinstance(value.get("nonce"), str) or not _NONCE.fullmatch(value["nonce"]):
        raise ValueError("protected_nonce_invalid")
    _digest(value.get("request_digest"), "request_digest")
    _digest(value.get("semantic_revision_digest"), "semantic_revision_digest")
    _timestamp(value.get("expires_at"), now=now)
    privacy = value.get("privacy_assertions")
    if privacy != {
        "bounded_customer_visible_intent_only": True,
        "contains_customer_payload": False,
        "contains_source_or_evidence": False,
    }:
        raise ValueError("protected_privacy_assertions_invalid")
    intent = value.get("intent")
    if not isinstance(intent, Mapping):
        raise ValueError("protected_intent_invalid")
    _exact_keys(intent, INTENT_KEYS, "intent")
    _reject_forbidden_keys(value)
    normalized = json.loads(canonical_json_bytes(dict(value)))
    expected = canonical_digest(normalized, omit="request_digest")
    if normalized["request_digest"] != expected:
        raise ValueError("protected_request_digest_mismatch")
    return normalized


def validate_proposal(value: Mapping[str, Any]) -> dict[str, Any]:
    _exact_keys(value, PROPOSAL_KEYS, "proposal")
    if value.get("schema_id") != PROPOSAL_CONTRACT_ID:
        raise ValueError("protected_proposal_contract_unsupported")
    if value.get("authority") != "inert_until_exact_local_confirmation":
        raise ValueError("protected_proposal_authority_invalid")
    groups = value.get("groups")
    if not isinstance(groups, list) or not groups or len(groups) > 8:
        raise ValueError("protected_proposal_groups_invalid")
    for group in groups:
        if not isinstance(group, Mapping) or set(group) != {"group_id", "label", "value"}:
            raise ValueError("protected_proposal_group_invalid")
        if not all(isinstance(group[key], str) and group[key] for key in group):
            raise ValueError("protected_proposal_group_invalid")
    for field in ("limitations", "unresolved_choice_ids"):
        if not isinstance(value.get(field), list):
            raise ValueError(f"protected_proposal_{field}_invalid")
    _reject_forbidden_keys(value)
    normalized = json.loads(canonical_json_bytes(dict(value)))
    expected = canonical_digest(normalized, omit="proposal_digest")
    if normalized.get("proposal_digest") != expected:
        raise ValueError("protected_proposal_digest_mismatch")
    return normalized


def validate_response(value: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    keys = set(value)
    if keys not in (set(RESPONSE_REQUIRED_KEYS), set(RESPONSE_REQUIRED_KEYS) | {"proposal"}):
        raise ValueError("protected_response_keys_invalid")
    if value.get("contract_id") != RESPONSE_CONTRACT_ID or value.get("contract_version") != 1:
        raise ValueError("protected_response_contract_unsupported")
    outcome = ProtectedCapabilityCategory(value.get("outcome"))
    _digest(value.get("request_digest"), "response_request_digest")
    _digest(value.get("response_digest"), "response_digest")
    _timestamp(value.get("expires_at"), now=now)
    proposal = value.get("proposal")
    if outcome is ProtectedCapabilityCategory.COMPLETED:
        if not isinstance(proposal, Mapping):
            raise ValueError("protected_completed_proposal_required")
        validate_proposal(proposal)
    elif proposal is not None:
        raise ValueError("protected_noncompleted_proposal_prohibited")
    _reject_forbidden_keys(value)
    normalized = json.loads(canonical_json_bytes(dict(value)))
    expected = canonical_digest(normalized, omit="response_digest")
    if normalized["response_digest"] != expected:
        raise ValueError("protected_response_digest_mismatch")
    return normalized
