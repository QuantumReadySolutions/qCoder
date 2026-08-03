"""Client-neutral source contract for qCoder's existing connected workflow.

This module is inert contract and test architecture. It does not select a
client, launch a client, implement another workflow engine, or make a public
compatibility claim.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from hashlib import sha256
from typing import Any

CLIENT_CONFORMANCE_CONTRACT_SCHEMA_ID = (
    "qcoder.connected_assistant.client_neutral_conformance.v1"
)
CLIENT_CONFORMANCE_CONTRACT_SCHEMA_VERSION = 1
CLIENT_CONFORMANCE_PROFILE_SCHEMA_ID = "qcoder.connected_assistant.conformance_profile.v1"
CLIENT_CONFORMANCE_PROFILE_SCHEMA_VERSION = 1

_SHARED_ASSERTIONS = (
    "mcp_initialization",
    "exact_twelve_tool_discovery",
    "fresh_loop_activation",
    "canonical_structured_intent_first_submission",
    "original_request_and_provenance_preserved",
    "native_permission_separation",
    "bounded_write_and_run_authority",
    "pure_status_while_receipt_outstanding",
    "direct_registration_after_status",
    "current_evidence_snapshot",
    "current_run_summary",
    "same_loop_iteration",
    "distinct_retained_prior_evidence",
    "one_call_help",
    "truthful_authority_and_next_actions",
    "direct_completion",
    "project_files_preserved",
    "no_cross_loop_carryover",
)


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def client_neutral_conformance_contract(tool_inventory: Sequence[str]) -> dict[str, Any]:
    """Return the shared contract bound to the existing twelve tools."""

    tools = tuple(str(name) for name in tool_inventory)
    if len(tools) != 12 or len(set(tools)) != 12:
        raise ValueError("client_conformance_tool_inventory_invalid")
    payload: dict[str, Any] = {
        "schema_id": CLIENT_CONFORMANCE_CONTRACT_SCHEMA_ID,
        "schema_version": CLIENT_CONFORMANCE_CONTRACT_SCHEMA_VERSION,
        "contract_kind": "internal_client_neutral_test_contract",
        "product_workflow_engine": "current_loop_coordinator",
        "second_workflow_engine_present": False,
        "public_client_selector_present": False,
        "generic_mcp_compatibility_claimed": False,
        "future_profile_template_enabled": False,
        "tool_inventory": list(tools),
        "tool_count": len(tools),
        "shared_assertions": list(_SHARED_ASSERTIONS),
        "client_specific_seams": [
            "installation_and_launch_setup",
            "native_permission_ui",
            "instruction_binding",
            "evidence_capture_fields",
            "configuration_restoration",
        ],
        "native_permission_auto_approval": False,
        "source_conformance_is_live_client_qualification": False,
    }
    payload["contract_digest"] = _digest(payload)
    return deepcopy(payload)


def cursor_desktop_reference_profile() -> dict[str, Any]:
    """Return the source-only reference profile for shared conformance tests."""

    payload: dict[str, Any] = {
        "schema_id": CLIENT_CONFORMANCE_PROFILE_SCHEMA_ID,
        "schema_version": CLIENT_CONFORMANCE_PROFILE_SCHEMA_VERSION,
        "profile_id": "cursor_desktop_reference",
        "reference_implementation": True,
        "source_conformance_enabled": True,
        "live_client_qualification": False,
        "native_permission_ui_separate": True,
        "automatic_native_permission_approval": False,
        "private_setup_contract": "native_cursor_absent_or_existing_exact_restore",
        "shared_assertions": list(_SHARED_ASSERTIONS),
    }
    payload["profile_digest"] = _digest(payload)
    return deepcopy(payload)


def validate_conformance_profile(profile: dict[str, Any]) -> None:
    """Fail closed when a profile attempts to weaken shared source assertions."""

    if profile.get("schema_id") != CLIENT_CONFORMANCE_PROFILE_SCHEMA_ID:
        raise ValueError("client_conformance_profile_schema_invalid")
    if profile.get("schema_version") != CLIENT_CONFORMANCE_PROFILE_SCHEMA_VERSION:
        raise ValueError("client_conformance_profile_version_invalid")
    if profile.get("source_conformance_enabled") is not True:
        raise ValueError("client_conformance_profile_inert")
    if tuple(profile.get("shared_assertions", ())) != _SHARED_ASSERTIONS:
        raise ValueError("client_conformance_shared_assertion_mismatch")
    if profile.get("automatic_native_permission_approval") is not False:
        raise ValueError("client_conformance_native_permission_boundary_invalid")


def evaluate_conformance_observations(
    *,
    profile: dict[str, Any],
    observations: dict[str, bool],
) -> dict[str, Any]:
    """Evaluate one client-specific observation set against shared assertions."""

    validate_conformance_profile(profile)
    required = tuple(str(value) for value in profile["shared_assertions"])
    unknown = sorted(set(observations) - set(required))
    missing = sorted(set(required) - set(observations))
    failed = sorted(name for name in required if observations.get(name) is not True)
    result: dict[str, Any] = {
        "schema_id": "qcoder.connected_assistant.conformance_result.v1",
        "schema_version": 1,
        "profile_id": profile["profile_id"],
        "required_assertion_count": len(required),
        "unknown_assertions": unknown,
        "missing_assertions": missing,
        "failed_assertions": failed,
        "passed": not unknown and not missing and not failed,
        "live_client_qualification_created": False,
    }
    result["result_digest"] = _digest(result)
    return result
