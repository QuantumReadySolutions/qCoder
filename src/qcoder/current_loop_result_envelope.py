"""Compact customer and tiered deterministic coordinator-result envelopes."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any, Mapping

from qcoder.current_loop import canonical_bytes

CUSTOMER_ENVELOPE_SCHEMA_ID = "qcoder.current_loop.customer_envelope.v1"
CUSTOMER_ENVELOPE_SCHEMA_VERSION = 1
TIERED_RESULT_ENVELOPE_SCHEMA_ID = "qcoder.current_loop.tiered_result_envelope.v1"
TIERED_RESULT_ENVELOPE_SCHEMA_VERSION = 1
BOUNDED_CONTROL_REFERENCE_SCHEMA_ID = "qcoder.current_loop.bounded_control_reference.v1"
BOUNDED_CONTROL_REFERENCE_SCHEMA_VERSION = 1
PERFORMANCE_DIAGNOSTICS_SCHEMA_ID = "qcoder.current_loop.performance_diagnostics.v1"
PERFORMANCE_DIAGNOSTICS_SCHEMA_VERSION = 1

CONTRACT_MANAGEMENT_OPERATIONS = frozenset(
    {
        "contract_status",
        "contract_review_customer_document",
        "contract_apply_customer_document",
        "contract_reset_to_preset",
        "contract_set_preset",
        "contract_adjust",
        "contract_set_generation_governance",
        "contract_confirm_broadening",
    }
)
QUIET_INFORMATIONAL_OPERATIONS = frozenset(
    {
        "help",
        "status",
        "evidence_view",
    }
)


def _digest(value: object) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def compact_invocation_reference(
    invocation: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Retain one executable local route without repeating its input domains."""

    if not isinstance(invocation, Mapping):
        return None
    operation = invocation.get("operation_specific_invocation")
    source = operation if isinstance(operation, Mapping) else invocation
    structured = source.get("structured_argv")
    if not isinstance(structured, list):
        structured = None
    return {
        "operation": source.get("operation"),
        "subcommand": source.get("subcommand") or invocation.get("subcommand"),
        "structured_argv": deepcopy(structured),
        "invocation_contract_digest": source.get("contract_digest"),
        "input_domains_inline": False,
    }


def controls_required_inline(
    *,
    operation: str,
    ok: bool,
    checkpoint_kind: str,
    details: Mapping[str, Any],
) -> tuple[bool, str]:
    """Classify whether deterministic bounded domains must be inline."""

    if operation == "bounded_control_catalog":
        return True, "catalog_fetch"
    if not ok:
        return True, "non_success"
    if checkpoint_kind != "none":
        return True, "actionable_checkpoint"
    if operation in CONTRACT_MANAGEMENT_OPERATIONS:
        return True, "contract_management_domains"
    if isinstance(details.get("bounded_control_rejection"), Mapping):
        return True, "bounded_control_rejection"
    recovery = details.get("recovery_contract")
    if isinstance(recovery, Mapping):
        return True, "recovery_domains"
    return False, "quiet_success_reference"


def control_policy_matrix(operations: list[str]) -> dict[str, Any]:
    rows = []
    for operation in sorted(set(operations)):
        rows.append(
            {
                "operation": operation,
                "successful_checkpoint_none": (
                    "inline"
                    if operation in CONTRACT_MANAGEMENT_OPERATIONS
                    or operation == "bounded_control_catalog"
                    else "reference"
                ),
                "checkpoint": "inline",
                "non_success": "inline",
                "recovery": "inline",
                "quiet_informational": operation in QUIET_INFORMATIONAL_OPERATIONS,
            }
        )
    payload = {
        "schema_id": TIERED_RESULT_ENVELOPE_SCHEMA_ID,
        "schema_version": TIERED_RESULT_ENVELOPE_SCHEMA_VERSION,
        "rows": rows,
        "zero_checkpoint_domains_omitted": True,
        "zero_recovery_domains_omitted": True,
        "zero_contract_management_domains_omitted": True,
        "clients_infer_referenced_domains": False,
    }
    payload["matrix_digest"] = _digest(payload)
    return payload


def bounded_control_envelope(
    *,
    controls: Mapping[str, Any],
    controls_inline: bool,
    fetch_invocation: Mapping[str, Any] | None,
    loop_ref: str,
    workspace_binding: str,
    state_revision: int,
    contract_revision: int,
    reason: str,
) -> dict[str, Any]:
    digest = _digest(controls)
    result = {
        "schema_id": BOUNDED_CONTROL_REFERENCE_SCHEMA_ID,
        "schema_version": BOUNDED_CONTROL_REFERENCE_SCHEMA_VERSION,
        "controls_schema_id": "qcoder.current_loop.bounded_control_catalog.v1",
        "controls_schema_version": 1,
        "controls_digest": digest,
        "controls_inline": controls_inline,
        "inline_reason": reason,
        "fetch_invocation": (
            compact_invocation_reference(fetch_invocation) if not controls_inline else None
        ),
        "loop_ref": loop_ref,
        "workspace_binding": workspace_binding,
        "state_revision": state_revision,
        "contract_revision": contract_revision,
        "client_may_infer_domains": False,
        "fetched_catalog_digest_must_match": True,
    }
    result["reference_digest"] = _digest(result)
    return result


def customer_envelope(
    *,
    operation: str,
    interaction: Mapping[str, Any],
    phase: str,
    state_status: str,
    contract_revision: int | None,
    effective_contract_digest: str | None,
    evidence_summary_reference: str | None,
    primary_next_invocation: Mapping[str, Any] | None,
    help_invocation: Mapping[str, Any] | None,
    help_available: bool,
    controls: Mapping[str, Any],
) -> dict[str, Any]:
    result = {
        "schema_id": CUSTOMER_ENVELOPE_SCHEMA_ID,
        "schema_version": CUSTOMER_ENVELOPE_SCHEMA_VERSION,
        "operation": operation,
        "interaction_kind": interaction.get("primary_interaction_kind"),
        "requires_customer_response": bool(interaction.get("requires_customer_response")),
        "concise_customer_message": interaction.get("concise_customer_message"),
        "current_phase": phase,
        "current_status": state_status,
        "contract_summary_reference": {
            "contract_revision": contract_revision,
            "effective_contract_digest": effective_contract_digest,
        },
        "evidence_summary_reference": evidence_summary_reference,
        "primary_next_invocation": compact_invocation_reference(primary_next_invocation),
        "optional_secondary_action_references": deepcopy(
            list(interaction.get("optional_on_request_actions", []))
        ),
        "help": {
            "available": help_available,
            "default_topic": "overview",
            "invocation": compact_invocation_reference(help_invocation),
        },
        "machine_block": {
            "controls_inline": controls.get("controls_inline"),
            "controls_digest": controls.get("controls_digest"),
            "controls_reference_digest": controls.get("reference_digest"),
        },
        "raw_evidence_included": False,
        "token_paths_included": False,
        "internal_state_dump_included": False,
    }
    result["envelope_digest"] = _digest(result)
    return result


def performance_diagnostics(
    *,
    total_seconds: float,
    state_load_validation_seconds: float,
    help_projection_seconds: float,
    controls_construction_seconds: float,
    result_serialization_seconds: float,
    final_result_bytes: int,
    controls_inline: bool,
) -> dict[str, Any]:
    return {
        "schema_id": PERFORMANCE_DIAGNOSTICS_SCHEMA_ID,
        "schema_version": PERFORMANCE_DIAGNOSTICS_SCHEMA_VERSION,
        "authority_bearing": False,
        "persisted": False,
        "total_operation_elapsed_seconds": max(0.0, total_seconds),
        "state_load_validation_seconds": max(0.0, state_load_validation_seconds),
        "help_projection_seconds": max(0.0, help_projection_seconds),
        "controls_construction_seconds": max(0.0, controls_construction_seconds),
        "result_serialization_seconds": max(0.0, result_serialization_seconds),
        "final_result_bytes": max(0, final_result_bytes),
        "controls_inline": controls_inline,
        "paths_or_secrets_included": False,
        "raw_evidence_included": False,
        "authority_digest_input": False,
    }
