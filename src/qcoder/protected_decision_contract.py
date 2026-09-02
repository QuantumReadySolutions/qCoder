"""Public fixed contract for one future inert protected decision proposal."""

from __future__ import annotations

import hashlib
import json
import math
from importlib.resources import files
from typing import Any, Mapping

from qcoder.protected_capability import ProtectedCapabilityCategory

REQUEST_CONTRACT_ID = "qcoder.protected_decision.request.v1"
RESPONSE_CONTRACT_ID = "qcoder.protected_decision.response.v1"
PROPOSAL_CONTRACT_ID = "qcoder.protected_decision.proposal.v1"
MAX_CANONICAL_BYTES = 16_384
MAX_DEPTH = 8
MAX_LIST_ITEMS = 32
MAX_MAP_ITEMS = 32
MAX_STRING_BYTES = 512

REQUEST_KEYS = frozenset(
    {
        "contract_id",
        "contract_version",
        "expires_at",
        "intent",
        "nonce",
        "privacy_assertions",
        "request_digest",
        "semantic_revision_digest",
    }
)
INTENT_KEYS = frozenset(
    {
        "artifact_kind",
        "customer_visible_constraint_categories",
        "framework_category",
        "objective_category",
        "operation_intent_categories",
        "unresolved_choice_ids",
    }
)
RESPONSE_REQUIRED_KEYS = frozenset(
    {
        "contract_id",
        "contract_version",
        "expires_at",
        "outcome",
        "request_digest",
        "response_digest",
    }
)
PROPOSAL_KEYS = frozenset(
    {
        "authority",
        "groups",
        "limitations",
        "proposal_digest",
        "schema_id",
        "unresolved_choice_ids",
    }
)


def _bounded(value: Any, *, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise ValueError("protected_contract_depth_exceeded")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("protected_contract_nonfinite_number")
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_STRING_BYTES:
            raise ValueError("protected_contract_string_too_large")
        return
    if isinstance(value, Mapping):
        if len(value) > MAX_MAP_ITEMS:
            raise ValueError("protected_contract_map_too_large")
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("protected_contract_non_string_key")
            _bounded(item, depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > MAX_LIST_ITEMS:
            raise ValueError("protected_contract_list_too_large")
        for item in value:
            _bounded(item, depth=depth + 1)


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    _bounded(value)
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > MAX_CANONICAL_BYTES:
        raise ValueError("protected_contract_too_large")
    return encoded


def canonical_digest(value: Mapping[str, Any], *, omit: str | None = None) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def boundary_contract_manifest() -> dict[str, Any]:
    resource = files("qcoder.contracts").joinpath("protected_decision_contract_v1.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def protected_contract_snapshot() -> dict[str, Any]:
    snapshot = {
        "request_contract_id": REQUEST_CONTRACT_ID,
        "response_contract_id": RESPONSE_CONTRACT_ID,
        "proposal_contract_id": PROPOSAL_CONTRACT_ID,
        "request_keys": sorted(REQUEST_KEYS),
        "intent_keys": sorted(INTENT_KEYS),
        "response_required_keys": sorted(RESPONSE_REQUIRED_KEYS),
        "outcomes": [item.value for item in ProtectedCapabilityCategory],
        "local_authority_from_service": False,
        "historical_policy_fallback": False,
    }
    manifest = boundary_contract_manifest()
    if snapshot != {
        "request_contract_id": manifest["request_contract_id"],
        "response_contract_id": manifest["response_contract_id"],
        "proposal_contract_id": manifest["proposal_contract_id"],
        "request_keys": manifest["request_keys"],
        "intent_keys": manifest["intent_keys"],
        "response_required_keys": manifest["response_required_keys"],
        "outcomes": manifest["outcomes"],
        "local_authority_from_service": manifest["local_authority_from_service"],
        "historical_policy_fallback": manifest["historical_policy_fallback"],
    }:
        raise ValueError("protected_boundary_manifest_mismatch")
    return snapshot
