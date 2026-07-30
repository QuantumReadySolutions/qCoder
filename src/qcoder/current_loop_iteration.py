"""Bounded quiet-iteration receipts and canonical parent-error taxonomy.

This module is deliberately local and pure.  It records only attributable
instruction digests and safe parent-comparison references; it never inspects a
workspace, loads canonical state, or performs a hosted operation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from typing import Any

ITERATION_AUTHORITY_RECEIPT_SCHEMA_ID = "qcoder.current_loop.iteration_authority_receipt.v1"
ITERATION_AUTHORITY_RECEIPT_SCHEMA_VERSION = 1
PARENT_ERROR_TAXONOMY_SCHEMA_ID = "qcoder.current_loop.parent_error_taxonomy.v1"
PARENT_ERROR_TAXONOMY_SCHEMA_VERSION = 1
MAX_ITERATION_INSTRUCTION_BYTES = 65_536

PARENT_ERROR_CATEGORIES = (
    "governing_blueprint_unavailable",
    "canonical_parent_set_incomplete",
    "parent_reference_stale",
    "parent_digest_mismatch",
    "parent_artifact_missing",
    "unsupported_iteration_route",
    "unknown_local_internal",
)


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def iteration_authority_receipt(
    *,
    exact_instruction: str,
    loop_ref: str,
    workspace_binding: str,
    state_revision: int,
    contract_revision: int,
    action_category: str,
    iteration_target: str = "ordinary_current_build_edit_and_run",
) -> dict[str, Any]:
    """Bind one exact ordinary development instruction without retaining it."""

    if not isinstance(exact_instruction, str) or not exact_instruction.strip():
        raise ValueError("ordinary_iteration_instruction_required")
    instruction_bytes = exact_instruction.encode("utf-8")
    if len(instruction_bytes) > MAX_ITERATION_INSTRUCTION_BYTES:
        raise ValueError("ordinary_iteration_instruction_too_large")
    if not isinstance(loop_ref, str) or not loop_ref:
        raise ValueError("ordinary_iteration_loop_reference_invalid")
    if not isinstance(workspace_binding, str) or not workspace_binding:
        raise ValueError("ordinary_iteration_workspace_binding_invalid")
    if not isinstance(action_category, str) or not action_category:
        raise ValueError("ordinary_iteration_action_category_invalid")
    result: dict[str, Any] = {
        "schema_id": ITERATION_AUTHORITY_RECEIPT_SCHEMA_ID,
        "schema_version": ITERATION_AUTHORITY_RECEIPT_SCHEMA_VERSION,
        "exact_instruction_utf8_sha256": sha256(instruction_bytes).hexdigest(),
        "provenance": "user_stated",
        "loop_ref": loop_ref,
        "workspace_binding": workspace_binding,
        "state_revision": state_revision,
        "contract_revision": contract_revision,
        "action_category": action_category,
        "iteration_target": iteration_target,
        "governing_blueprint_unchanged": True,
        "blueprint_promotion_performed": False,
        "evolved_blueprint_created": False,
        "continuation_artifact_created": False,
        "build_review_implicitly_deferred": True,
        "cross_loop_carryover": False,
        "raw_instruction_retained": False,
    }
    result["receipt_digest"] = _digest(result)
    return result


def parent_digest_failure_details(
    *,
    expected_digest_reference: str,
    observed_digest_reference: str,
    parent_role: str,
) -> dict[str, Any]:
    """Return the proof required before using parent_digest_mismatch."""

    if not all(
        isinstance(value, str) and bool(value)
        for value in (expected_digest_reference, observed_digest_reference, parent_role)
    ):
        raise ValueError("parent_digest_comparison_reference_invalid")
    return {
        "digest_comparison_attempted": True,
        "expected_digest_reference": expected_digest_reference,
        "observed_digest_reference": observed_digest_reference,
        "parent_role": parent_role,
        "raw_parent_content_included": False,
        "private_parent_path_included": False,
    }


def parent_digest_failure_provenance_valid(details: object) -> bool:
    if not isinstance(details, Mapping):
        return False
    return (
        details.get("digest_comparison_attempted") is True
        and isinstance(details.get("expected_digest_reference"), str)
        and bool(details["expected_digest_reference"])
        and isinstance(details.get("observed_digest_reference"), str)
        and bool(details["observed_digest_reference"])
        and isinstance(details.get("parent_role"), str)
        and bool(details["parent_role"])
        and details.get("raw_parent_content_included") is False
        and details.get("private_parent_path_included") is False
    )


def parent_error_taxonomy_snapshot() -> dict[str, Any]:
    meanings = {
        "governing_blueprint_unavailable": (
            "This adaptive loop has no governing Working Blueprint for lineage closure."
        ),
        "canonical_parent_set_incomplete": (
            "A parent-dependent operation lacks one or more qCoder-owned canonical parents."
        ),
        "parent_reference_stale": "A qCoder-owned canonical parent reference is stale.",
        "parent_digest_mismatch": (
            "An actual expected-versus-observed parent digest comparison failed."
        ),
        "parent_artifact_missing": "A qCoder-owned canonical parent artifact is unavailable.",
        "unsupported_iteration_route": (
            "A loop-closing or governing route was selected for an ordinary iteration."
        ),
        "unknown_local_internal": "An unclassified local internal failure occurred.",
    }
    result: dict[str, Any] = {
        "schema_id": PARENT_ERROR_TAXONOMY_SCHEMA_ID,
        "schema_version": PARENT_ERROR_TAXONOMY_SCHEMA_VERSION,
        "categories": [
            {
                "category": category,
                "customer_meaning": meanings[category],
                "substring_classification_permitted": False,
                "digest_comparison_proof_required": category == "parent_digest_mismatch",
            }
            for category in PARENT_ERROR_CATEGORIES
        ],
        "assistant_supplies_parent_reference": False,
        "raw_parent_content_exposed": False,
    }
    result["contract_digest"] = _digest(result)
    return result


def iteration_contract_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {
        "iteration_receipt_schema_id": ITERATION_AUTHORITY_RECEIPT_SCHEMA_ID,
        "iteration_receipt_schema_version": ITERATION_AUTHORITY_RECEIPT_SCHEMA_VERSION,
        "parent_error_taxonomy": parent_error_taxonomy_snapshot(),
        "primary_ready_state": "assist_iteration_ready",
        "ordinary_instruction_provenance": "user_stated",
        "ordinary_iteration_operation": "record_ide_authority",
        "ordinary_iteration_input_channel": "exact_current_customer_instruction_stdin",
        "build_review": "available_on_request",
        "hosted_enrichment": "available_on_request",
        "continue_unchanged_scope": "lineage_closure_not_ordinary_iteration",
        "working_blueprint_required_for_ordinary_iteration": False,
        "cross_loop_carryover": False,
    }
    result["contract_digest"] = _digest(result)
    return deepcopy(result)
