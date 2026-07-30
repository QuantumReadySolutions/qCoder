"""Versioned quiet-interaction contracts for one active Explorer loop.

The builders in this module are pure and bounded. They accept canonical,
already-derived qCoder values and never inspect a workspace, transcript, or
private state file.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


CUSTOMER_INTERACTION_SCHEMA_ID = "qcoder.current_loop.customer_interaction.v1"
CUSTOMER_INTERACTION_SCHEMA_VERSION = 1
ASSISTANT_CONTEXT_UPDATE_SCHEMA_ID = "qcoder.current_loop.assistant_context_update.v1"
ASSISTANT_CONTEXT_UPDATE_SCHEMA_VERSION = 1
COMPLETION_RECEIPT_SCHEMA_ID = "qcoder.current_loop.completion_receipt.v1"
COMPLETION_RECEIPT_SCHEMA_VERSION = 1
HELP_SCHEMA_ID = "qcoder.current_loop.help.v1"
HELP_SCHEMA_VERSION = 1
INTENT_RECEIPT_SCHEMA_ID = "qcoder.current_loop.intent_receipt.v1"
INTENT_RECEIPT_SCHEMA_VERSION = 1

INTERACTION_KINDS = (
    "activation_receipt",
    "activity_receipt",
    "material_decision_request",
    "authority_request",
    "blocker_or_recovery",
    "user_requested_help",
    "no_customer_interaction_required",
)
INTENT_PROVENANCE = (
    "user_stated",
    "observed",
    "qcoder_classified",
    "derived",
    "assistant_proposed",
    "assumed",
    "unresolved",
)
HELP_TOPICS = (
    "overview",
    "current_status",
    "contract",
    "evidence",
    "blocker",
    "next_actions",
    "product_surfaces",
)


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def customer_interaction(
    *,
    kind: str,
    concise_message: str,
    safe_choices: Sequence[Mapping[str, Any]] = (),
    next_invocation: Mapping[str, Any] | None = None,
    activity_receipts: Sequence[Mapping[str, Any]] = (),
    summary_reference: str | None = None,
) -> dict[str, Any]:
    if kind not in INTERACTION_KINDS:
        raise ValueError("customer_interaction_kind_invalid")
    if not isinstance(concise_message, str) or not concise_message or len(concise_message) > 2_000:
        raise ValueError("customer_interaction_message_invalid")
    requires = kind in {
        "material_decision_request",
        "authority_request",
        "blocker_or_recovery",
    }
    result = {
        "schema_id": CUSTOMER_INTERACTION_SCHEMA_ID,
        "schema_version": CUSTOMER_INTERACTION_SCHEMA_VERSION,
        "primary_interaction_kind": kind,
        "requires_customer_response": requires,
        "concise_customer_message": concise_message,
        "safe_choices": [deepcopy(dict(item)) for item in safe_choices],
        "next_invocation": deepcopy(dict(next_invocation)) if next_invocation else None,
        "activity_receipts": [deepcopy(dict(item)) for item in activity_receipts],
        "help_available": True,
        "current_summary_reference": summary_reference,
        "stable_domain_contracts_repeated": False,
        "raw_policy_included": False,
        "raw_evidence_included": False,
    }
    result["interaction_digest"] = _digest(result)
    return result


def intent_receipt(
    *,
    request_baseline_digest: str,
    fields: Mapping[str, Mapping[str, Any]],
    generation_governance: str,
    state_revision: int,
    contract_revision: int,
) -> dict[str, Any]:
    normalized: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    for name, supplied in sorted(fields.items()):
        value = deepcopy(dict(supplied))
        provenance = value.get("provenance")
        if provenance not in INTENT_PROVENANCE:
            raise ValueError("intent_receipt_provenance_invalid")
        if provenance == "unresolved" and value.get("material") is True:
            blockers.append(name)
        normalized[name] = value
    result = {
        "schema_id": INTENT_RECEIPT_SCHEMA_ID,
        "schema_version": INTENT_RECEIPT_SCHEMA_VERSION,
        "request_baseline_digest": request_baseline_digest,
        "generation_governance": generation_governance,
        "fields": normalized,
        "material_decision_fields": blockers,
        "material_decision_required": bool(blockers)
        or generation_governance == "blueprint_required",
        "routine_interpretation_approval_required": False,
        "routine_clarification_approval_required": False,
        "state_revision": state_revision,
        "contract_revision": contract_revision,
        "user_confirmation_manufactured": False,
    }
    result["receipt_digest"] = _digest(result)
    return result


def assistant_context_update(
    *,
    run_reference: str,
    evidence_references: Sequence[Mapping[str, str]],
    backend: str | None,
    shots: int | None,
    top_outcomes: Sequence[Mapping[str, Any]],
    warnings: Sequence[str],
    limitations: Sequence[str],
    circuit_metrics: Mapping[str, Any] | None,
    freshness: str,
    contract_revision: int,
) -> dict[str, Any]:
    if freshness not in {"fresh", "stale", "incomplete"}:
        raise ValueError("assistant_context_update_freshness_invalid")
    bounded_outcomes = [deepcopy(dict(item)) for item in top_outcomes[:16]]
    result = {
        "schema_id": ASSISTANT_CONTEXT_UPDATE_SCHEMA_ID,
        "schema_version": ASSISTANT_CONTEXT_UPDATE_SCHEMA_VERSION,
        "run_reference": run_reference,
        "backend_or_simulator": backend,
        "shot_count": shots,
        "top_outcomes": bounded_outcomes,
        "warnings": [str(item)[:500] for item in warnings[:32]],
        "limitations": [str(item)[:500] for item in limitations[:32]],
        "circuit_metrics": deepcopy(dict(circuit_metrics)) if circuit_metrics else None,
        "freshness": freshness,
        "evidence_references": [deepcopy(dict(item)) for item in evidence_references[:32]],
        "contract_revision": contract_revision,
        "raw_artifacts_remain_local": True,
        "complete_raw_source_included": False,
        "complete_raw_qasm_included": False,
        "unbounded_raw_counts_included": False,
        "cross_loop_carryover": False,
    }
    result["context_digest"] = _digest(result)
    return result


def completion_receipt(
    *,
    instruction_utf8_sha256: str,
    disposition: str,
    hosted_enrichment_disposition: str,
    build_review_disposition: str,
    state_revision: int,
    contract_revision: int,
    provenance: str = "exact_current_customer_message",
) -> dict[str, Any]:
    if disposition not in {"continue_unchanged", "stop_loop"}:
        raise ValueError("completion_receipt_disposition_invalid")
    result = {
        "schema_id": COMPLETION_RECEIPT_SCHEMA_ID,
        "schema_version": COMPLETION_RECEIPT_SCHEMA_VERSION,
        "exact_instruction_utf8_sha256": instruction_utf8_sha256,
        "resulting_disposition": disposition,
        "blueprint_unchanged": True,
        "hosted_enrichment_disposition": hosted_enrichment_disposition,
        "build_review_disposition": build_review_disposition,
        "next_loop_disposition": "do_not_start",
        "cross_loop_carryover": False,
        "state_revision": state_revision,
        "contract_revision": contract_revision,
        "provenance": provenance,
        "restaging_required": False,
        "raw_policy_retransmitted": False,
        "blueprint_retransmitted": False,
    }
    result["receipt_digest"] = _digest(result)
    return result


def help_response(
    *,
    topic: str,
    loop_active: bool,
    effective_preset: str | None,
    contract_summary: str | None,
    generation_governance: str | None,
    evidence: Sequence[Mapping[str, Any]],
    limitations: Sequence[str],
    latest_activity: Mapping[str, Any] | None,
    blocker: Mapping[str, Any] | None,
    supported_actions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if topic not in HELP_TOPICS:
        raise ValueError("current_loop_help_topic_invalid")
    result = {
        "schema_id": HELP_SCHEMA_ID,
        "schema_version": HELP_SCHEMA_VERSION,
        "topic": topic,
        "loop_active": loop_active,
        "effective_preset": effective_preset,
        "contract_summary": contract_summary,
        "generation_governance": generation_governance,
        "available_evidence": [deepcopy(dict(item)) for item in evidence],
        "limitations": [str(item)[:500] for item in limitations],
        "most_recent_activity_receipt": (
            deepcopy(dict(latest_activity)) if latest_activity is not None else None
        ),
        "current_material_blocker": deepcopy(dict(blocker)) if blocker is not None else None,
        "supported_customer_actions": [deepcopy(dict(item)) for item in supported_actions],
        "product_surfaces": [
            "current_loop_contract",
            "working_blueprint",
            "circuit_workbench",
            "run_summary",
            "build_review",
        ],
        "separate_authority_still_required": [
            "IDE write or run",
            "raw evidence exposure",
            "material Blueprint change",
            "external service, paid activity, or hardware",
        ],
        "commands_exposed": False,
        "json_choreography_exposed": False,
        "state_reconstructed_from_transcript": False,
    }
    result["help_digest"] = _digest(result)
    return result


def quiet_workflow_contract_snapshot() -> dict[str, Any]:
    payload = {
        "customer_interaction_schema_id": CUSTOMER_INTERACTION_SCHEMA_ID,
        "assistant_context_update_schema_id": ASSISTANT_CONTEXT_UPDATE_SCHEMA_ID,
        "completion_receipt_schema_id": COMPLETION_RECEIPT_SCHEMA_ID,
        "help_schema_id": HELP_SCHEMA_ID,
        "intent_receipt_schema_id": INTENT_RECEIPT_SCHEMA_ID,
        "interaction_kinds": list(INTERACTION_KINDS),
        "intent_provenance": list(INTENT_PROVENANCE),
        "help_topics": list(HELP_TOPICS),
        "assist_default": "quiet_everyday",
        "generation_governance": ["adaptive", "blueprint_required"],
        "hosted_enrichment": "on_request",
        "build_review": "on_request",
        "raw_exposure_default": False,
        "cross_loop_carryover": False,
    }
    payload["contract_digest"] = _digest(payload)
    return payload
