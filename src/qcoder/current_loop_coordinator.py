"""Natural IDE orchestration over deterministic current-loop state.

Conversation may choose an operation and present its result. This module owns
the canonical local state, exact artifacts, protected request construction, and
human checkpoints. It never reconstructs required state from conversation.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

from qcoder.algorithm_blueprint import (
    artifact_digest_matches,
    extract_selected_python_file_evidence,
    with_artifact_digest,
)
from qcoder.context_loop import (
    build_circuit_manifestation,
    build_decision_evidence_lineage,
    build_request_baseline,
    build_result_manifestation,
    build_stage_availability,
    share_safe_request_baseline,
)
from qcoder.blueprint_decisions import (
    catalog_entries,
    consistency_digest,
    unpack_decision_record_set,
)
from qcoder.current_loop import (
    AUTHORIZED_ARTIFACT_ROLES,
    GENERATION_POSTURES,
    CurrentLoopConflict,
    CurrentLoopError,
    CurrentLoopStore,
    activate_current_loop,
    activate_next_loop_from_seed,
    build_changed_next_loop_seed,
    build_unchanged_continuation,
    canonical_bytes,
    check_current_loop_freshness,
    complete_current_loop,
    decision_inventory_binding,
    migrate_current_loop_state,
    propose_selected_artifact_authorization,
    read_run_summaries,
    replace_run_summary,
    save_exact_canonical_artifact,
    save_run_summary,
    select_current_loop_generation_posture,
    set_artifact_authorization,
    share_safe_artifact_authorization_projection,
    stage_pending_activation_capture,
    update_selected_artifact_authorization,
)
from qcoder.current_loop_checkpoint_input import (
    CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_ID,
    CHECKPOINT_INPUT_SEMANTIC_SCHEMA_ID,
    CHECKPOINT_INPUT_SCHEMA_ID,
    CHECKPOINT_INPUT_SCHEMA_VERSION,
    DECISION_AUTHORITY_PROVENANCE,
    POSTURE_AUTHORITY_PROVENANCE,
    CheckpointInputStructuralError,
    checkpoint_input_binding_values,
    checkpoint_input_construction,
    checkpoint_input_contract_snapshot,
    checkpoint_input_safe_structure,
    checkpoint_input_values,
    normalize_checkpoint_input,
)
from qcoder.current_loop_invocation import (
    HOSTED_CAPABLE,
    INVOCATION_CONTRACT_SCHEMA_ID,
    LOCAL_ONLY,
    build_operation_invocation,
    invocation_contract_snapshot,
    operation_for_subcommand,
    operation_transport_inventory,
)
from qcoder.current_loop_bootstrap import (
    BOOTSTRAP_INVOCATION_SCHEMA_ID,
    INVOCATION_LIFECYCLE_SCHEMA_ID,
    PRE_RESULT_ENTRY_INVENTORY_SCHEMA_ID,
)
from qcoder.current_loop_contract import (
    CurrentLoopContractError,
    adjust as adjust_contract,
    confirm_broadening,
    contract_snapshot,
    exclude_evidence as contract_exclude_evidence,
    permits as contract_permits,
    record_deletion as contract_record_deletion,
    restore_evidence as contract_restore_evidence,
    set_preset as set_contract_preset,
    validate_contract,
)
from qcoder.current_loop_bounded_control import (
    BOUNDED_CONTROL_INPUT_SCHEMA_ID,
    bounded_control_contract_snapshot,
    bounded_control_contracts,
    contract_for_operation as bounded_contract_for_operation,
    dynamic_argument_contracts,
)
from qcoder.current_loop_event_receipts import (
    EventReceiptError,
    consume_operation_receipt,
    event_receipt_snapshot,
    issue_operation_receipt,
    validate_operation_receipt,
)
from qcoder.current_loop_evidence_processing import (
    ARTIFACT_FORMAT_CONTRACT_SCHEMA_ID,
    FAILURE_PROVENANCE_SCHEMA_ID,
    HOSTED_ENRICHMENT_SCHEMA_ID,
    PROCESSING_OUTCOME_SCHEMA_ID,
    RECOVERY_ACTION_SCHEMA_ID,
    EvidenceProcessingError,
    artifact_format_contract_snapshot,
    detect_exact_artifact_format,
    evidence_processing_contract_snapshot,
    failure_provenance,
    hosted_enrichment_status,
    processing_outcome,
    recovery_action_contract_snapshot,
    recovery_fingerprint,
    registration_format_outcome,
)
from qcoder.current_loop_run_summary import (
    EVIDENCE_VIEW_IDS,
    RunSummaryError,
    build_evidence_view,
    build_run_summary,
    evidence_view_contract_snapshot,
    mark_run_summary_stale,
    mark_run_summary_fresh,
    run_summary_contract_snapshot,
    share_safe_run_summary_projection,
)
from qcoder.context_loop import CONTEXT_LOOP_GATE

COORDINATOR_RESULT_SCHEMA_ID = "qcoder.current_loop.coordinator_result.v11"
COORDINATOR_RESULT_SCHEMA_VERSION = 11
COORDINATOR_STATE_SCHEMA_ID = "qcoder.current_loop.coordinator_state.v9"
PREVIOUS_COORDINATOR_STATE_SCHEMA_ID = "qcoder.current_loop.coordinator_state.v8"
OLDER_COORDINATOR_STATE_SCHEMA_IDS = frozenset(
    {
        "qcoder.current_loop.coordinator_state.v6",
        "qcoder.current_loop.coordinator_state.v7",
        "qcoder.current_loop.coordinator_state.v5",
        "qcoder.current_loop.coordinator_state.v4",
        "qcoder.current_loop.coordinator_state.v1",
        "qcoder.current_loop.coordinator_state.v2",
        "qcoder.current_loop.coordinator_state.v3",
    }
)
COORDINATOR_STATE_SCHEMA_VERSION = 8
RECOVERY_SCHEMA_ID = "qcoder.current_loop.recovery.v2"
RECOVERY_SCHEMA_VERSION = 2
CONSEQUENCE_PROJECTION_SCHEMA_ID = "qcoder.current_loop.consequence_projection.v1"
PERFORMANCE_SCHEMA_ID = "qcoder.current_loop.private_performance.v1"
INPUT_SOURCE_DISPOSITION_SCHEMA_ID = "qcoder.current_loop.permitted_input_source_disposition.v1"
INPUT_SOURCE_DISPOSITION_SCHEMA_VERSION = 1
PERMITTED_INPUT_SOURCE_CATEGORIES = (
    "bounded_enumerated_customer_choice",
    "checkpoint_input_transport",
    "qcoder_held_staged_value",
    "exact_artifact_lineage",
    "authority_only_approval",
    "qcoder_managed_canonical_reference",
    "exact_customer_selected_workspace",
    "exact_request_capture_transport",
    "no_input_permitted_or_required",
)

PHASES = (
    "activated",
    "intent_review",
    "generation_ready",
    "awaiting_local_artifacts",
    "artifact_authorization",
    "evidence_processing",
    "current_build_review",
    "continuation_choice",
    "change_confirmation",
    "next_loop_ready",
    "completed",
    "abandoned",
)
STATE_STATUSES = (
    "ready",
    "checkpoint_required",
    "stale",
    "blocked",
    "conflict",
    "corrupt",
)
CHECKPOINT_KINDS = (
    "activation_request_baseline_review",
    "activation",
    "posture",
    "intent_review",
    "decision_resolution",
    "ide_write_or_run",
    "artifact_review",
    "checkpoint_input_review",
    "governing_change_confirmation",
    "privacy_or_trust",
    "none",
)
CONFIRMATION_TRANSMISSION_STATES = (
    "not_applicable",
    "not_supplied",
    "supplied",
    "clarification_required",
    "confirmed",
    "declined",
)
CLIENT_NAMES = ("cursor", "claude_code", "codex")
SAFE_LOCAL_FAILURE_CATEGORIES = frozenset(
    {
        "bounded_local_run_failure",
        "invalid_local_result",
        "local_dependency_unavailable",
        "local_execution_denied",
        "local_run_failed",
        "simulator_run_failed",
    }
)

_PHASE_TRANSITIONS = {
    "activated": (
        "intent_review",
        "awaiting_local_artifacts",
        "artifact_authorization",
        "abandoned",
    ),
    "intent_review": ("generation_ready", "abandoned"),
    "generation_ready": (
        "intent_review",
        "awaiting_local_artifacts",
        "artifact_authorization",
        "abandoned",
    ),
    "awaiting_local_artifacts": ("artifact_authorization", "abandoned"),
    "artifact_authorization": (
        "awaiting_local_artifacts",
        "evidence_processing",
        "abandoned",
    ),
    "evidence_processing": (
        "generation_ready",
        "artifact_authorization",
        "current_build_review",
        "continuation_choice",
        "abandoned",
    ),
    "current_build_review": ("continuation_choice", "abandoned"),
    "continuation_choice": (
        "current_build_review",
        "change_confirmation",
        "next_loop_ready",
        "completed",
        "abandoned",
    ),
    "change_confirmation": (
        "continuation_choice",
        "next_loop_ready",
        "completed",
        "abandoned",
    ),
    "next_loop_ready": ("completed", "abandoned"),
    "completed": (),
    "abandoned": (),
}

_READY_PHASE_PROTOCOL_DISPOSITIONS = {
    "activated": "select_generation_posture_or_stop",
    "intent_review": "stage_exact_intent_checkpoint_input",
    "generation_ready": "obtain_separate_ide_write_or_run_authority",
    "awaiting_local_artifacts": "perform_authorized_ide_work_and_register_exact_paths",
    "artifact_authorization": "obtain_exact_artifact_set_authorization",
    "evidence_processing": "process_or_review_exact_authorized_evidence",
    "current_build_review": "review_current_build",
    "continuation_choice": "stage_exact_continuation_choice",
    "change_confirmation": "stage_exact_proposal_confirmation_or_decline",
    "next_loop_ready": "start_next_or_stop",
    "completed": "terminal",
    "abandoned": "terminal",
}

_CHECKPOINT_AUTHORITY = {
    "activation_request_baseline_review": (
        "Explicitly activate qCoder and approve preservation of the complete displayed "
        "customer message as the exact Request Baseline."
    ),
    "activation": "Explicitly activate qCoder for this current build.",
    "posture": "Choose exploratory first pass or Blueprint-guided generation.",
    "intent_review": "Review and explicitly approve or correct the proposed interpretation.",
    "decision_resolution": (
        "Approve only the exact generation-relevant decision dispositions, defer them, "
        "or explicitly switch this attempt to exploratory first pass."
    ),
    "ide_write_or_run": "Authorize the IDE host separately before writing or executing code.",
    "artifact_review": "Approve the exact visible artifact set qCoder may inspect locally.",
    "checkpoint_input_review": (
        "Approve, correct, or decline the complete exact staged checkpoint values."
    ),
    "governing_change_confirmation": (
        "Explicitly confirm the exact Carry-Forward Proposal before governing intent changes."
    ),
    "privacy_or_trust": "Review the material privacy, trust, or evidence limitation.",
    "none": "No human authority is required for the next deterministic local transition.",
}
REQUEST_TRANSPORTS = ("inline", "file", "stdin")
REQUEST_LABEL_PROVENANCE = (
    "system_generated",
    "user_provided",
    "user_confirmed_assistant_interpretation",
)

AUTHORIZED_DECISION_PROVENANCE = frozenset(DECISION_AUTHORITY_PROVENANCE[:3])
ARTIFACT_CANDIDATE_PROVENANCE = (
    "assistant_created",
    "assistant_modified",
    "user_selected",
)
LEGACY_ARTIFACT_CANDIDATE_PROVENANCE = "user_supplied"
EXPLORATORY_FIXED_CONSTRAINTS = (
    "Keep this attempt bounded to the explicitly authorized active workspace and current build.",
)
EXPLORATORY_FIXED_PROHIBITIONS = (
    "Do not scan outside the authorized workspace.",
    "Do not treat implementation defaults as governing decisions.",
    "Do not claim correctness or hardware fidelity without evidence.",
    "Do not evolve the Working Blueprint without explicit confirmation.",
)

_RECOVERY = {
    "circuit_format_unsupported": (
        "The exact circuit artifact is not a locally supported structural-analysis format.",
        "Continue with the available evidence, provide an exact OpenQASM 2 artifact under "
        "separate IDE authority, skip this artifact derivation, or stop the loop.",
        True,
        False,
        True,
        False,
    ),
    "artifact_format_unsupported": (
        "The exact artifact format is outside this role's automatic processing contract.",
        "Use the advertised exact-artifact fallback, provide a supported artifact, skip "
        "this derivation, or stop the loop.",
        True,
        False,
        True,
        False,
    ),
    "unknown_local_internal": (
        "A bounded local qCoder operation failed without a safely publishable detail.",
        "Keep prior evidence intact, refresh the result, then choose an advertised bounded "
        "alternative or stop the loop.",
        True,
        False,
        True,
        False,
    ),
    "activation_capture_required": (
        "No reviewed exact Request Baseline capture exists in this workspace.",
        "Stage the complete customer message through activate without approval, review the "
        "returned exact capture, then approve it.",
        True,
        False,
        True,
        False,
    ),
    "request_baseline_constraint_not_verbatim": (
        "A proposed user-stated constraint was not an exact span of the captured request.",
        "Preserve the full request and omit the extraction, or supply only its exact wording.",
        True,
        False,
        True,
        False,
    ),
    "request_baseline_choice_not_verbatim": (
        "A proposed user-stated choice was not an exact span of the captured request.",
        "Preserve the full request and omit the extraction, or supply only its exact wording.",
        True,
        False,
        True,
        False,
    ),
    "request_baseline_label_provenance_required": (
        "A supplied display label lacked attributable user authority.",
        "Omit the label for a system-generated display label, or supply attributable provenance.",
        True,
        False,
        True,
        False,
    ),
    "request_baseline_label_not_verbatim": (
        "A user-provided label was not an exact span of the captured request.",
        "Omit the label or use only the exact user-provided wording.",
        True,
        False,
        True,
        False,
    ),
    "request_baseline_label_without_value": (
        "Label provenance was supplied without a label value.",
        "Omit label provenance or supply the exact attributable label.",
        True,
        False,
        True,
        False,
    ),
    "current_loop_contract_policy_prohibited": (
        "The effective Current Loop Contract does not permit this participation step.",
        "Keep the existing evidence and authority intact. Skip this step, or ask qCoder "
        "for a bounded contract change; any broadening still requires separate approval.",
        True,
        True,
        True,
        False,
    ),
    "contract_revision_stale": (
        "The contract revision changed before this bounded control was applied.",
        "Refresh the current qCoder result and use its newly bound local invocation.",
        True,
        False,
        True,
        False,
    ),
    "contract_broadening_proposal_stale": (
        "The pending contract broadening no longer matches the current contract revision.",
        "Refresh the current contract, then request a new bounded proposal if still wanted.",
        True,
        True,
        True,
        False,
    ),
    "contract_preset_invalid": (
        "The supplied preset is outside the current bounded preset domain.",
        "Use one preset from the refreshed qCoder bounded-control contract.",
        True,
        False,
        True,
        False,
    ),
    "contract_category_invalid": (
        "The supplied evidence category is outside the current bounded domain.",
        "Use one category from the refreshed qCoder bounded-control contract.",
        True,
        False,
        True,
        False,
    ),
    "contract_dimension_invalid": (
        "The supplied participation dimension is outside the current bounded domain.",
        "Use one dimension valid for the selected category in the refreshed contract.",
        True,
        False,
        True,
        False,
    ),
    "contract_adjustment_value_invalid": (
        "The supplied value is not valid for the selected category and dimension.",
        "Use one value from the refreshed valid-selection graph.",
        True,
        False,
        True,
        False,
    ),
    "contract_raw_exposure_ceiling": (
        "The requested raw assistant exposure exceeds the contract.v1 policy ceiling.",
        "Keep raw exposure disabled or choose another advertised bounded adjustment.",
        True,
        False,
        True,
        False,
    ),
    "contract_evidence_exclusion_reason_invalid": (
        "The supplied evidence-exclusion reason is outside the bounded domain.",
        "Use one reason from the refreshed qCoder evidence-control contract.",
        True,
        False,
        True,
        False,
    ),
    "contract_evidence_reference_unknown": (
        "The supplied evidence reference is not an eligible qCoder-owned reference.",
        "Select one exact reference from the refreshed eligible-reference list.",
        True,
        False,
        True,
        False,
    ),
    "contract_evidence_exclusion_missing": (
        "The supplied evidence reference is not currently excluded.",
        "Select one exact reference from the refreshed restore-eligible list.",
        True,
        False,
        True,
        False,
    ),
    "contract_evidence_not_locally_controlled": (
        "The supplied evidence reference is not locally controlled by qCoder.",
        "Select one exact reference from the refreshed deletion-eligible list.",
        True,
        True,
        True,
        False,
    ),
    "operation_receipt_missing": (
        "The exact qCoder operation receipt is not available for this registration.",
        "Keep the literal output paths unchanged and obtain a fresh bounded IDE event receipt, "
        "or use the existing exact-artifact selection fallback.",
        True,
        True,
        True,
        False,
    ),
    "operation_receipt_stale": (
        "The operation receipt is stale for the current local state revision.",
        "Keep the literal output paths unchanged and obtain a fresh bounded IDE event receipt, "
        "or use the existing exact-artifact selection fallback.",
        True,
        True,
        True,
        False,
    ),
    "qcoder_local_state_artifact_prohibited": (
        "qCoder local state cannot be selected as a review artifact.",
        "Use only an exact non-qCoder path retained from an authorized IDE operation "
        "or explicitly selected by the user. Do not inspect qCoder local state.",
        True,
        False,
        True,
        False,
    ),
    "artifact_candidate_discovery_expression_invalid": (
        "A discovery expression cannot be registered as an exact review artifact.",
        "Use the exact file path returned by an authorized IDE operation or explicitly "
        "selected by the user. Do not glob, list, find, or search for candidates.",
        True,
        False,
        True,
        False,
    ),
    "artifact_candidate_file_required": (
        "The exact registered artifact must exist and be a regular file.",
        "Use the exact file path returned by the authorized IDE operation or explicit "
        "user selection. Do not search for a replacement.",
        True,
        False,
        True,
        False,
    ),
    "artifact_candidate_provenance_conflict": (
        "The same exact artifact path was supplied with conflicting provenance.",
        "Correct the provenance from the known IDE operation or explicit user selection; "
        "do not guess or rediscover the path.",
        True,
        False,
        True,
        False,
    ),
    "loop_not_activated": (
        "No qCoder current loop is active in this workspace.",
        "Explicitly activate qCoder and choose a generation posture.",
        True,
        False,
        True,
        False,
    ),
    "loop_already_active": (
        "A qCoder current loop is already active in this workspace.",
        "Continue the active loop or explicitly abandon it before replacing it.",
        True,
        False,
        True,
        True,
    ),
    "posture_required": (
        "qCoder needs one generation-posture choice.",
        "Choose a quick exploratory first pass or Blueprint-guided control.",
        True,
        False,
        True,
        False,
    ),
    "selected_file_stale": (
        "An approved file changed after authorization.",
        "Review and approve the exact current file set, then recreate dependent evidence.",
        True,
        True,
        True,
        True,
    ),
    "selected_file_missing": (
        "An approved file is missing or no longer a regular file.",
        "Restore it or explicitly select and approve a replacement.",
        True,
        True,
        True,
        True,
    ),
    "authorization_declined": (
        "Artifact review was declined; qCoder did not inspect the proposed files.",
        "Continue without review or explicitly propose another exact set later.",
        True,
        False,
        True,
        False,
    ),
    "authorization_partial": (
        "The proposed artifact set changed and still needs explicit approval.",
        "Review the remaining exact set and approve it or decline.",
        True,
        True,
        True,
        False,
    ),
    "ide_write_or_run_denied": (
        "The IDE was not authorized to write or execute code.",
        "Revise the plan, continue read-only, or explicitly authorize the IDE host.",
        True,
        False,
        True,
        False,
    ),
    "canonical_artifact_modified": (
        "A saved canonical qCoder artifact no longer matches its recorded bytes.",
        "Restore the exact artifact or recreate it through the supported operation.",
        False,
        False,
        True,
        True,
    ),
    "parent_digest_mismatch": (
        "An explicitly supplied parent does not match the required digest.",
        "Supply the exact saved parent file. Do not repair it from conversation.",
        False,
        False,
        True,
        True,
    ),
    "client_state_conflict": (
        "Another local client updated current-loop state first.",
        "Reload and revalidate local state before retrying the explicit action.",
        True,
        False,
        True,
        True,
    ),
    "local_state_corrupt": (
        "The local current-loop state is corrupt or unsupported.",
        "Restore the exact state backup or explicitly start a new loop.",
        False,
        False,
        False,
        True,
    ),
    "seed_incomplete": (
        "The next-loop seed or its explicitly supplied parent set is incomplete.",
        "Supply the exact seed and every parent named by it.",
        False,
        False,
        True,
        True,
    ),
    "unsupported_schema": (
        "A supplied artifact uses an unsupported schema version.",
        "Use the exact supported artifact or recreate it with this qCoder build.",
        False,
        False,
        True,
        True,
    ),
    "protected_service_unavailable": (
        "The protected Context Bridge operation is currently unavailable.",
        "Keep local state intact and retry the same supported operation later.",
        True,
        False,
        True,
        True,
    ),
    "protected_operation_rejected": (
        "The protected operation rejected the supplied canonical request.",
        "Use the returned bounded category; do not change payload shape in chat.",
        True,
        False,
        True,
        True,
    ),
    "protected_truth_insufficient": (
        "Supplied product truth is insufficient for an honest concise projection.",
        "Use expanded certification detail or obtain the missing supported evidence.",
        True,
        False,
        True,
        True,
    ),
    "reconstruction_attempt_refused": (
        "qCoder refused to reconstruct canonical state from conversation.",
        "Use the exact saved artifact or rerun its supported creation operation.",
        False,
        False,
        True,
        True,
    ),
}

_ERROR_ALIASES = {
    "current_loop_not_active": "loop_not_activated",
    "current_loop_already_active": "loop_already_active",
    "current_loop_state_corrupt": "local_state_corrupt",
    "current_loop_state_version_invalid": "unsupported_schema",
    "current_loop_state_digest_mismatch": "local_state_corrupt",
    "concurrent_state_update": "client_state_conflict",
    "current_loop_lock_timeout": "client_state_conflict",
    "source_changed": "selected_file_stale",
    "circuit_changed": "selected_file_stale",
    "result_changed": "selected_file_stale",
    "selected_file_changed": "selected_file_stale",
    "next_loop_seed_parent_set_incomplete": "seed_incomplete",
    "next_loop_seed_missing": "seed_incomplete",
    "next_loop_seed_invalid": "seed_incomplete",
    "next_loop_seed_mismatch": "seed_incomplete",
    "context_bridge_unreachable": "protected_service_unavailable",
}

_POSTURE_CUES = {
    "exploratory_first_pass": (
        "first pass",
        "quick attempt",
        "quick first",
        "fastest first",
        "minimal interruption",
        "interrupt only when decisions matter",
        "exploratory",
    ),
    "blueprint_guided": (
        "blueprint-guided",
        "blueprint guided",
        "blueprint review",
        "deliberate control",
        "deliberate blueprint",
        "review choices before",
        "fixed choices before",
        "bounded choices before",
    ),
}

_CONSEQUENCE_GROUPS = (
    "Represented and no action needed",
    "New or changed",
    "Needs your decision",
    "Missing or later evidence",
    "Unproven",
)

_CONSEQUENCE_MAPPING_TABLE = {
    "generation_effect:blocking": "Needs your decision",
    "generation_effect:non_blocking": "Represented and no action needed",
    "aggregate_readiness_result:blocked_pending_decisions": "Needs your decision",
    "aggregate_readiness_result:ready_to_generate": "Represented and no action needed",
    "aggregate_readiness_result:ready_with_bounded_discretion": (
        "Represented and no action needed"
    ),
    "generation_context_eligibility:False": "Needs your decision",
    "generation_context_eligibility:True": "Represented and no action needed",
    "resolution_state:unresolved": "Needs your decision",
    "resolution_state:evidence_deferred": "Missing or later evidence",
    "user_disposition:left_unresolved": "Needs your decision",
    "user_disposition:deferred_to_source_evidence": "Missing or later evidence",
    "user_disposition:deferred_to_later_evidence": "Missing or later evidence",
    "stage_availability:not_supplied": "Missing or later evidence",
    "stage_availability:not_constructed": "Missing or later evidence",
    "stage_availability:not_run": "Missing or later evidence",
    "stage_availability:evidence_requested": "Missing or later evidence",
    "alignment_status:not_represented": "New or changed",
    "alignment_status:mismatch": "New or changed",
    "proposal_state:unconfirmed": "Needs your decision",
}


class ProtectedTransport(Protocol):
    def call(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Execute one existing Context Bridge operation."""

    def confirm_selected_bundle(
        self,
        *,
        selected_bundle_file: str | Path,
        semantic_confirmation: str,
    ) -> dict[str, Any]:
        """Confirm one exact selected portable bundle through the existing operation."""


class ContextBridgeTransport:
    """Existing Context Bridge transport, without adding an MCP operation."""

    def __init__(
        self,
        *,
        base_url: str,
        token_file: str | Path,
        opener: Callable[..., Any] | None = None,
    ):
        self.base_url = base_url
        self.token_file = Path(token_file)
        self.opener = opener

    def call(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        from qcoder.context_bridge_mcp import post_context_bridge

        supplied = deepcopy(dict(arguments))
        artifact_text = supplied.pop("artifact_text", None)
        artifact_kind = str(supplied.pop("artifact_kind", "share_safe_evidence_summary"))
        client_context = supplied.pop("client_context", None)
        return post_context_bridge(
            base_url=self.base_url,
            token_file=self.token_file,
            tool_name=tool_name,
            artifact_text=artifact_text,
            artifact_kind=artifact_kind,
            client_context=(client_context if isinstance(client_context, dict) else None),
            tool_arguments=supplied,
            opener=self.opener,
        )

    def confirm_selected_bundle(
        self,
        *,
        selected_bundle_file: str | Path,
        semantic_confirmation: str,
    ) -> dict[str, Any]:
        from qcoder.context_bridge_mcp import handle_jsonrpc_message

        response = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "create_implementation_blueprint",
                    "arguments": {
                        "use_selected_portable_bundle": True,
                        "resolution_confirmation": {
                            "confirmed": True,
                            "confirmation_assertion": semantic_confirmation,
                            "provenance": "explicit_user_confirmation",
                        },
                    },
                },
            },
            base_url=self.base_url,
            token_file=self.token_file,
            selected_portable_bundle_file=selected_bundle_file,
            opener=self.opener,
        )
        if not isinstance(response, dict):
            return {
                "ok": False,
                "error_category": "context_bridge_unreachable",
            }
        result = response.get("result")
        if not isinstance(result, dict):
            return {
                "ok": False,
                "error_category": "protected_operation_rejected",
            }
        structured = result.get("structuredContent")
        return (
            deepcopy(structured)
            if isinstance(structured, dict)
            else {
                "ok": False,
                "error_category": "protected_operation_rejected",
            }
        )


def infer_requested_posture(original_request: str) -> str | None:
    """Classify only explicit posture wording; never infer a silent default."""

    if not isinstance(original_request, str) or not original_request.strip():
        return None
    normalized = " ".join(original_request.casefold().split())
    matches = [
        posture for posture, cues in _POSTURE_CUES.items() if any(cue in normalized for cue in cues)
    ]
    return matches[0] if len(matches) == 1 else None


def _exact_request_value(original_request: object) -> str:
    if not isinstance(original_request, str) or original_request == "":
        raise CurrentLoopError("request_baseline_original_request_required")
    if len(original_request) > 20_000:
        raise CurrentLoopError("request_baseline_original_request_too_large")
    return original_request


def _attributed_request_spans(
    original_request: str,
    values: Sequence[str],
    *,
    field: str,
) -> list[dict[str, str]]:
    if len(values) > 64:
        raise CurrentLoopError(f"request_baseline_{field}_too_many")
    result: list[dict[str, str]] = []
    for value in values:
        if not isinstance(value, str) or value == "" or len(value) > 1_000:
            raise CurrentLoopError(f"request_baseline_{field}_invalid")
        if value not in original_request:
            raise CurrentLoopError(f"request_baseline_{field}_not_verbatim")
        result.append(
            {
                "value": value,
                "provenance": "user_stated",
                "source": "verbatim_original_request",
            }
        )
    return result


def build_pending_activation_capture(
    *,
    original_request: str,
    workspace_root: Path,
    request_transport: str,
    explicit_constraints: Sequence[str] = (),
    explicit_choices: Sequence[str] = (),
    assistant_interpretation: Mapping[str, Any] | None = None,
    label: str | None = None,
    label_provenance: str | None = None,
    captured_at: float,
) -> dict[str, Any]:
    """Build bounded local pending state without canonical activation."""

    request = _exact_request_value(original_request)
    if request_transport not in REQUEST_TRANSPORTS:
        raise CurrentLoopError("request_transport_invalid")
    constraints = _attributed_request_spans(
        request,
        explicit_constraints,
        field="constraint",
    )
    choices = _attributed_request_spans(
        request,
        explicit_choices,
        field="choice",
    )
    assistant = deepcopy(dict(assistant_interpretation or {}))
    if (
        len(
            json.dumps(
                assistant,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        > 12_000
    ):
        raise CurrentLoopError("assistant_interpretation_too_large")
    if assistant:
        assistant["provenance_role"] = "assistant_proposed"
        assistant["confirmation_state"] = "pending_intent_review"
    if label is None:
        label_record = {
            "value": "qCoder current build",
            "provenance": "system_generated",
        }
    else:
        if (
            not isinstance(label, str)
            or not label
            or len(label) > 160
            or label_provenance not in REQUEST_LABEL_PROVENANCE[1:]
        ):
            raise CurrentLoopError("request_baseline_label_provenance_required")
        if label_provenance == "user_provided" and label not in request:
            raise CurrentLoopError("request_baseline_label_not_verbatim")
        label_record = {
            "value": label,
            "provenance": label_provenance,
        }
    if label is None and label_provenance is not None:
        raise CurrentLoopError("request_baseline_label_without_value")
    request_digest = sha256(request.encode("utf-8")).hexdigest()
    return {
        "schema_id": "qcoder.current_loop.pending_activation_capture.v1",
        "schema_version": 1,
        "original_request": request,
        "original_request_codepoint_length": len(request),
        "original_request_utf8_sha256": request_digest,
        "request_transport": request_transport,
        "explicit_constraints": constraints,
        "explicit_choices": choices,
        "assistant_interpretation": assistant,
        "label": label_record,
        "captured_at": float(captured_at),
        "workspace_binding": str(workspace_root),
        "review_state": "pending_exact_baseline_review",
        "canonical_request_baseline_created": False,
        "activation_performed": False,
        "protected_call_performed": False,
    }


def normalize_decision_dispositions(
    profile_id: str,
    dispositions: Sequence[Mapping[str, Any]],
    *,
    existing_records: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Validate the bounded CLI authority channel against the selected catalog."""

    definitions = {item["profile_decision_id"]: item for item in catalog_entries(profile_id)}
    existing_by_id = {
        str(item.get("profile_decision_id")): item
        for item in existing_records
        if isinstance(item, Mapping)
    }
    normalized: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for supplied in dispositions:
        decision_id = str(supplied.get("profile_decision_id") or "")
        definition = definitions.get(decision_id)
        if definition is None:
            raise CurrentLoopError("decision_disposition_unknown_decision")
        action = str(supplied.get("user_disposition") or "")
        if action not in {"selected_choice", "left_unresolved"}:
            raise CurrentLoopError("decision_disposition_action_invalid")
        provenance = str(supplied.get("authority_provenance") or "")
        if provenance not in AUTHORIZED_DECISION_PROVENANCE:
            if provenance == "assistant_recommendation_pending_confirmation":
                raise CurrentLoopError("decision_recommendation_not_confirmed")
            raise CurrentLoopError("decision_disposition_provenance_invalid")
        value = supplied.get("selected_value")
        if action == "selected_choice":
            if not isinstance(value, str) or not value.strip() or len(value) > 500:
                raise CurrentLoopError("decision_disposition_value_invalid")
            value = value.strip()
            alternatives = list(definition.get("supported_alternatives") or [])
            if alternatives and value not in alternatives:
                raise CurrentLoopError("decision_disposition_value_outside_catalog")
        elif value is not None and value not in ("", "-"):
            raise CurrentLoopError("unresolved_decision_value_prohibited")
        choice_origin = (
            "human_specified" if provenance == "user_provided" else "blueprint_confirmed"
        )
        result: dict[str, Any] = {
            "profile_decision_id": decision_id,
            "resolution_state": "resolved" if action == "selected_choice" else "unresolved",
            "user_disposition": action,
            "generation_effect": (
                "non_blocking"
                if action == "selected_choice"
                else str(definition["default_generation_effect"])
            ),
            "blueprint_representation_state": (
                "represented" if action == "selected_choice" else "not_represented"
            ),
            "choice_origin": choice_origin,
            "evidence_confidence": "User-provided",
            "alignment_status": (
                "appears_aligned" if action == "selected_choice" else "not_applicable"
            ),
            "provenance_entries": [
                {
                    "role": provenance,
                    "explicit_user_authority": True,
                    "assistant_inference": False,
                }
            ],
            "authority_provenance": provenance,
        }
        existing = existing_by_id.get(decision_id)
        if isinstance(existing, Mapping) and isinstance(existing.get("decision_ref"), str):
            result["decision_ref"] = existing["decision_ref"]
        if action == "selected_choice":
            result["selected_value"] = value
        previous = seen.get(decision_id)
        if previous is not None:
            if previous != result:
                raise CurrentLoopError("decision_disposition_contradictory_duplicate")
            raise CurrentLoopError("decision_disposition_duplicate")
        seen[decision_id] = result
        normalized.append(result)
    return normalized


def coordinator_contract_snapshot() -> dict[str, Any]:
    from qcoder.current_loop_contract_sidecar import sidecar_contract_snapshot

    return {
        "schemas": {
            "result": COORDINATOR_RESULT_SCHEMA_ID,
            "state": COORDINATOR_STATE_SCHEMA_ID,
            "consequence_projection": CONSEQUENCE_PROJECTION_SCHEMA_ID,
            "performance": PERFORMANCE_SCHEMA_ID,
            "checkpoint_input": CHECKPOINT_INPUT_SCHEMA_ID,
            "checkpoint_input_semantic_contract": CHECKPOINT_INPUT_SEMANTIC_SCHEMA_ID,
            "bootstrap_invocation": BOOTSTRAP_INVOCATION_SCHEMA_ID,
            "pre_result_entry_inventory": PRE_RESULT_ENTRY_INVENTORY_SCHEMA_ID,
            "operation_invocation": INVOCATION_CONTRACT_SCHEMA_ID,
            "bounded_control_input": BOUNDED_CONTROL_INPUT_SCHEMA_ID,
            "invocation_lifecycle": INVOCATION_LIFECYCLE_SCHEMA_ID,
            "current_loop_contract": contract_snapshot()["schema_id"],
            "operation_receipt": event_receipt_snapshot()["schema_id"],
            "recovery": RECOVERY_SCHEMA_ID,
            "artifact_format_contract": ARTIFACT_FORMAT_CONTRACT_SCHEMA_ID,
            "artifact_processing_outcome": PROCESSING_OUTCOME_SCHEMA_ID,
            "hosted_enrichment": HOSTED_ENRICHMENT_SCHEMA_ID,
            "recovery_action": RECOVERY_ACTION_SCHEMA_ID,
            "failure_provenance": FAILURE_PROVENANCE_SCHEMA_ID,
            "contract_sidecar": sidecar_contract_snapshot()["schema_id"],
            "run_summary": run_summary_contract_snapshot()["schema_id"],
            "evidence_view": evidence_view_contract_snapshot()["schema_id"],
        },
        "operation_invocation": invocation_contract_snapshot(),
        "bounded_control_input": bounded_control_contract_snapshot(),
        "operation_transport_inventory": operation_transport_inventory(),
        "current_loop_contract": contract_snapshot(),
        "operation_receipt": event_receipt_snapshot(),
        "recovery_contract": {
            "schema_id": RECOVERY_SCHEMA_ID,
            "schema_version": RECOVERY_SCHEMA_VERSION,
            "strategies": [
                "qcoder_corrects",
                "restage_with_construction",
                "refresh_revision",
                "bounded_alternative",
                "rebind_event_receipt",
                "skip",
                "abandon_step",
                "stop_loop",
            ],
            "recoverable_next_invocation_required": True,
            "refresh_executes_selected_action": False,
        },
        "artifact_format_contract": artifact_format_contract_snapshot(),
        "evidence_processing_contract": evidence_processing_contract_snapshot(),
        "recovery_action_contract": recovery_action_contract_snapshot(),
        "contract_sidecar": sidecar_contract_snapshot(),
        "run_summary": run_summary_contract_snapshot(),
        "evidence_view": evidence_view_contract_snapshot(),
        "phases": list(PHASES),
        "ready_phase_protocol_dispositions": deepcopy(_READY_PHASE_PROTOCOL_DISPOSITIONS),
        "state_statuses": list(STATE_STATUSES),
        "checkpoint_kinds": list(CHECKPOINT_KINDS),
        "confirmation_transmission_states": list(CONFIRMATION_TRANSMISSION_STATES),
        "checkpoint_result_protocol": {
            "schema_version": COORDINATOR_RESULT_SCHEMA_VERSION,
            "supported_next_action": True,
            "next_invocation": True,
            "required_authority_input": True,
            "required_authority_disposition": True,
            "awaiting_confirmation_fields": True,
            "confirmation_transmission_state": True,
            "identical_repeat_prohibited": True,
            "permitted_input_source": True,
            "input_source_disposition": True,
            "bounded_input_semantics": True,
            "protocol_binding": True,
            "checkpoint_input_construction": True,
            "checkpoint_input_construction_alternatives": True,
            "prohibited_derivations": True,
            "no_action_reason": True,
            "no_action_disposition": True,
            "terminal": True,
        },
        "permitted_input_source_taxonomy": {
            "schema_id": INPUT_SOURCE_DISPOSITION_SCHEMA_ID,
            "schema_version": INPUT_SOURCE_DISPOSITION_SCHEMA_VERSION,
            "categories": list(PERMITTED_INPUT_SOURCE_CATEGORIES),
            "actionable_source_never_null": True,
            "arbitrary_free_text_in_argv": False,
            "customer_types_coordinator_command": False,
            "assistant_infers_authority": False,
        },
        "checkpoint_input": checkpoint_input_contract_snapshot(),
        "request_baseline_transfer": {
            "complete_governing_message_preserved_verbatim": True,
            "transports": list(REQUEST_TRANSPORTS),
            "nonactivating_capture_required": "review_required_mode_only",
            "approval_reuses_pending_capture": True,
            "new_request_with_approval_activates": ("exact_current_customer_message_mode_only"),
            "protected_call_before_activation": False,
            "posture_authority_separate": True,
        },
        "generation_context_response_modes": [
            "exploratory_generation_context_ready",
            "generation_context_blocked_pending_decisions",
            "generation_context_pack_ready",
        ],
        "decision_authority_provenance": list(DECISION_AUTHORITY_PROVENANCE),
        "posture_authority_provenance": list(POSTURE_AUTHORITY_PROVENANCE),
        "artifact_candidate_provenance": list(ARTIFACT_CANDIDATE_PROVENANCE),
        "artifact_handoff": {
            "awaiting_local_artifacts_actionable": True,
            "exact_ide_operation_paths_only": True,
            "explicit_user_selected_paths_only": True,
            "incremental_registration_additive": True,
            "incremental_registration_idempotent": True,
            "qcoder_local_state_access_by_assistant": False,
            "discovery_derived_candidates": False,
            "registration_authorizes_review": False,
            "operation_receipt_supported": True,
            "operation_receipt_single_use": True,
        },
        "workspace_state_is_intent": False,
        "recovery_categories": sorted(_RECOVERY),
        "high_level_operations": [
            "status",
            "activate",
            "prepare_generation",
            "stage_checkpoint_input",
            "approve_staged_checkpoint_input",
            "decline_staged_checkpoint_input",
            "register_artifacts",
            "authorize_artifacts",
            "process_authorized_artifacts",
            "review_build",
            "continue_unchanged",
            "propose_change",
            "confirm_change",
            "start_next",
            "standalone_review",
            "attach_to_loop",
            "abandon",
            "contract_status",
            "contract_set_preset",
            "contract_adjust",
            "contract_confirm_broadening",
            "evidence_exclude",
            "evidence_restore",
            "evidence_delete",
            "open_contract_editor",
            "evidence_view",
            "decline_build_review",
        ],
        "connected_clients": list(CLIENT_NAMES),
        "safe_local_failure_categories": sorted(SAFE_LOCAL_FAILURE_CATEGORIES),
        "protected_operation_added": False,
        "mcp_tool_added": False,
        "customer_serialization_required": False,
        "assistant_reconstruction_allowed": False,
        "directory_scan": False,
        "watcher": False,
        "server_lookup": False,
        "persistence": False,
        "consequence_mapping_version": 1,
        "consequence_mapping_table": deepcopy(_CONSEQUENCE_MAPPING_TABLE),
    }


def consequence_projection(product_truth: Mapping[str, Any]) -> dict[str, Any]:
    """Project only explicit supplied fields into customer-facing groups."""

    groups: dict[str, list[dict[str, Any]]] = {group: [] for group in _CONSEQUENCE_GROUPS}
    mapped_paths: set[str] = set()
    unmapped_count = 0

    def add(group: str, path: str, value: object) -> None:
        summary = _bounded_summary(value)
        if summary is None:
            return
        groups[group].append(
            {
                "source_field": path,
                "summary": summary,
                "mapping_version": 1,
            }
        )
        mapped_paths.add(path)

    def walk(value: object, path: str = "$") -> None:
        nonlocal unmapped_count
        if isinstance(value, Mapping):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if (
                    key in {"non_proofs", "remaining_non_proofs"}
                    and isinstance(child, Sequence)
                    and not isinstance(child, (str, bytes))
                ):
                    for index, item in enumerate(child):
                        add("Unproven", f"{child_path}[{index}]", item)
                    continue
                if key in {"uncertainty", "remaining_uncertainty"}:
                    values = (
                        child
                        if isinstance(child, Sequence) and not isinstance(child, (str, bytes))
                        else [child]
                    )
                    for index, item in enumerate(values):
                        add("Unproven", f"{child_path}[{index}]", item)
                    continue
                if key == "applicable_actions":
                    unmapped_count += max(
                        1,
                        len(child)
                        if isinstance(child, Sequence) and not isinstance(child, (str, bytes))
                        else 1,
                    )
                    continue
                if key in {
                    "before",
                    "proposed_after",
                    "current_value",
                    "proposed_value",
                }:
                    add("New or changed", child_path, child)
                    continue
                mapping_key = f"{key}:{child}"
                group = _CONSEQUENCE_MAPPING_TABLE.get(mapping_key)
                if group is not None:
                    add(group, child_path, child)
                    continue
                if isinstance(child, (Mapping, list, tuple)):
                    walk(child, child_path)
                elif key in {
                    "readiness",
                    "readiness_summary",
                    "aggregate_readiness_result",
                    "applicable_actions",
                }:
                    unmapped_count += 1
                else:
                    unmapped_count += 1
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(product_truth)
    return {
        "schema_id": CONSEQUENCE_PROJECTION_SCHEMA_ID,
        "schema_version": 1,
        "groups": groups,
        "mapped_item_count": len(mapped_paths),
        "additional_evidence_available_count": unmapped_count,
        "unknown_values_guessed": False,
        "readiness_calculated_locally": False,
        "action_eligibility_calculated_locally": False,
        "recommendation_calculated_locally": False,
        "lineage_calculated_locally": False,
        "expanded_truth_preserved": True,
    }


def _bounded_summary(value: object) -> str | None:
    if isinstance(value, str):
        text = " ".join(value.split())
        return text[:500] if text else None
    if isinstance(value, (bool, int, float)) or value is None:
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, Mapping):
        selected = {
            key: deepcopy(value[key])
            for key in (
                "decision_ref",
                "profile_decision_id",
                "selected_value",
                "control_treatment",
                "resolution_state",
                "user_disposition",
                "generation_effect",
            )
            if key in value
        }
        if selected:
            return json.dumps(selected, ensure_ascii=True, sort_keys=True)[:500]
        return "Structured supplied product truth is available in expanded detail."
    return None


def _recovery_checkpoint_kind(
    category: str,
    *,
    reauthorization_required: bool,
) -> str:
    if category == "posture_required":
        return "posture"
    if category in {"loop_not_activated", "loop_already_active"}:
        return "activation"
    if category == "ide_write_or_run_denied":
        return "ide_write_or_run"
    if reauthorization_required and category != "seed_incomplete":
        return "artifact_review"
    return "privacy_or_trust"


def _session_ref() -> str:
    return f"session-artifact-{secrets.token_hex(16)}"


def _artifact_reference(artifact: Mapping[str, Any]) -> str:
    for key in (
        "artifact_ref",
        "derived_artifact_reference",
        "proposal_ref",
        "continuation_ref",
        "seed_ref",
    ):
        value = artifact.get(key)
        if isinstance(value, str) and value:
            return value
    return f"session-artifact-{_artifact_digest(artifact)[:32]}"


def _artifact_digest(artifact: Mapping[str, Any]) -> str:
    artifact_value = dict(artifact)
    value = artifact_value.get("artifact_digest")
    if isinstance(value, str):
        if not artifact_digest_matches(artifact_value):
            raise CurrentLoopError("canonical_artifact_digest_mismatch")
        return value
    value = artifact_value.get("consistency_digest")
    if isinstance(value, str):
        if value != consistency_digest(artifact_value):
            raise CurrentLoopError("canonical_artifact_digest_mismatch")
        return value
    raise CurrentLoopError("canonical_artifact_digest_missing")


def _load_json_file(path: Path, *, maximum_bytes: int = 8 * 1024 * 1024) -> dict[str, Any]:
    if not path.is_absolute() or path.is_symlink():
        raise CurrentLoopError("selected_artifact_path_invalid")
    try:
        stat_result = path.stat()
        if not path.is_file() or stat_result.st_size > maximum_bytes:
            raise CurrentLoopError("selected_artifact_invalid")
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CurrentLoopError("selected_file_missing") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurrentLoopError("selected_artifact_invalid") from exc
    if not isinstance(value, dict):
        raise CurrentLoopError("selected_artifact_invalid")
    return value


def _atomic_exact_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_bytes(value)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            path.chmod(0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _invocation_template(
    subcommand: str | None,
    *,
    required_flags: Sequence[str] = (),
    reused_inputs: Sequence[str] = (),
    new_inputs: Sequence[str] = (),
    argument_values: Sequence[Mapping[str, Any]] = (),
    fixed_argument_values: Mapping[str, Any] | None = None,
    alternatives: Sequence[str] = (),
    uses_transport: bool | None = None,
) -> dict[str, Any]:
    result = {
        "coordinator_prefix_source": "configured_qcoder_runtime.coordinator_prefix",
        "workspace_argument": {
            "flag": "--workspace",
            "value_source": "active_workspace_root",
        },
        "subcommand": subcommand,
        "required_flags": list(required_flags),
        "reused_canonical_inputs": list(reused_inputs),
        "new_input_roles": list(new_inputs),
        "argument_values": [deepcopy(dict(item)) for item in argument_values],
        "fixed_argument_values": deepcopy(dict(fixed_argument_values or {})),
        "allowed_subcommand_alternatives": list(alternatives),
        "private_workspace_path_embedded": False,
        "token_contents_embedded": False,
        "account_identifier_embedded": False,
        "canonical_artifact_reconstruction_required": False,
    }
    if uses_transport is not None:
        result["_qcoder_hosted_transport"] = uses_transport
    return result


def _artifact_handoff_invocation_template() -> dict[str, Any]:
    invocation = _invocation_template(
        "register-artifacts",
        required_flags=("--provenance",),
        new_inputs=(
            "exact_artifact_path_from_ide_operation_or_user_selection",
            "exact_artifact_role",
            "truthful_artifact_provenance",
        ),
    )
    invocation.update(
        {
            "artifact_path_flags": {
                "source": "--source",
                "circuit_qasm": "--qasm",
                "results": "--results",
            },
            "path_source": ("exact_ide_create_or_modify_operation_result_or_exact_user_selection"),
            "accepted_provenance": list(ARTIFACT_CANDIDATE_PROVENANCE),
            "separate_invocations_for_mixed_provenance": True,
            "incremental_registration": "additive_and_idempotent",
            "discovery_permitted": False,
            "qcoder_local_state_access_permitted": False,
            "guessed_artifact_path_embedded": False,
        }
    )
    return invocation


def _checkpoint_input_stage_invocation(
    operation: str,
    checkpoint_kind: str,
) -> dict[str, Any]:
    invocation = _invocation_template(
        "stage-checkpoint-input",
        required_flags=("--checkpoint-input-stdin or --checkpoint-input-file",),
        new_inputs=("assistant_created_versioned_checkpoint_input",),
    )
    invocation.update(
        {
            "qcoder_owned_construction_source": "checkpoint_input_construction",
            "operation": operation,
            "checkpoint_kind": checkpoint_kind,
            "operation_or_checkpoint_flags_required": False,
            "input_transports": ["stdin", "file"],
            "literal_free_text_in_argv": False,
            "customer_creates_input": False,
            "stages_without_authority": True,
            "protected_call_performed": False,
        }
    )
    return invocation


def _checkpoint_input_approval_invocation() -> dict[str, Any]:
    invocation = _invocation_template(
        "approve-checkpoint-input",
        required_flags=("--approve",),
        reused_inputs=("exact_current_staged_checkpoint_input",),
        new_inputs=("explicit_checkpoint_specific_authority",),
    )
    invocation.update(
        {
            "literal_free_text_in_argv": False,
            "staged_values_retransmitted": False,
            "authority_only": True,
        }
    )
    return invocation


def _authority_input(
    flag: str | None,
    authority: str,
    *,
    additional_flags: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "flag": flag,
        "additional_flags": list(additional_flags),
        "authority": authority,
        "omission_is_approval": False,
        "supply_only_after_explicit_user_action": True,
        "assistant_may_infer_or_manufacture": False,
    }


_ACTION_INPUT_SOURCE_CATEGORIES = {
    "select_generation_posture_or_stop": (
        "bounded_enumerated_customer_choice",
        "authority_only_approval",
    ),
    "obtain_separate_generation_posture_authority": (
        "bounded_enumerated_customer_choice",
        "authority_only_approval",
    ),
    "stage_exact_request_before_activation": ("exact_request_capture_transport",),
    "stage_exact_intent_checkpoint_input": ("checkpoint_input_transport",),
    "stage_exact_intent_correction_for_review": ("checkpoint_input_transport",),
    "stage_exact_intent_interpretation_for_review": ("checkpoint_input_transport",),
    "stage_exact_decision_resolution_or_switch_posture": ("checkpoint_input_transport",),
    "stage_exact_continuation_choice": ("checkpoint_input_transport",),
    "stage_exact_proposal_confirmation_or_decline": ("checkpoint_input_transport",),
    "stage_exact_unchanged_continuation_for_review": ("checkpoint_input_transport",),
    "review_staged_checkpoint_input": (
        "qcoder_held_staged_value",
        "authority_only_approval",
    ),
    "present_exact_request_baseline_and_obtain_activation_approval": (
        "qcoder_held_staged_value",
        "authority_only_approval",
    ),
    "obtain_explicit_qcoder_activation": (
        "qcoder_held_staged_value",
        "authority_only_approval",
    ),
    "obtain_separate_ide_write_or_run_authority": ("authority_only_approval",),
    "perform_authorized_ide_work_and_register_exact_paths": ("exact_artifact_lineage",),
    "obtain_exact_artifact_set_authorization": (
        "qcoder_held_staged_value",
        "bounded_enumerated_customer_choice",
        "authority_only_approval",
    ),
    "process_exact_authorized_artifacts": ("qcoder_managed_canonical_reference",),
    "review_current_build": ("qcoder_managed_canonical_reference",),
    "start_next_or_stop": (
        "qcoder_managed_canonical_reference",
        "exact_customer_selected_workspace",
        "bounded_enumerated_customer_choice",
        "authority_only_approval",
    ),
    "stop_and_present_checkpoint": ("authority_only_approval",),
    "refresh_bounded_recovery": ("qcoder_managed_canonical_reference",),
}


def _default_permitted_input_source(action: str) -> str:
    defaults = {
        "select_generation_posture_or_stop": (
            "explicit_customer_bounded_posture_choice_or_explicitly_accepted_"
            "supported_recommendation"
        ),
        "obtain_separate_generation_posture_authority": (
            "explicit_customer_bounded_posture_choice_or_explicitly_accepted_"
            "supported_recommendation"
        ),
        "stage_exact_request_before_activation": (
            "complete_customer_message_via_exact_request_capture_transport"
        ),
        "obtain_explicit_qcoder_activation": (
            "explicit_user_authority_only_for_qcoder_held_activation_request"
        ),
        "obtain_separate_ide_write_or_run_authority": ("explicit_user_authority_only"),
        "obtain_exact_artifact_set_authorization": (
            "explicit_user_bounded_exact_set_action_on_qcoder_displayed_candidates"
        ),
        "stop_and_present_checkpoint": "explicit_user_checkpoint_authority",
        "refresh_bounded_recovery": "fresh_qcoder_coordinator_result",
    }
    source = defaults.get(action)
    if source is None:
        raise CurrentLoopError(f"coordinator_protocol_input_source_undefined_{action}")
    return source


def _bounded_values_for_action(action: str) -> dict[str, list[str]]:
    if action in {
        "select_generation_posture_or_stop",
        "obtain_separate_generation_posture_authority",
        "stage_exact_posture_transition_for_review",
    }:
        return {
            "generation_posture": list(GENERATION_POSTURES),
            "posture_authority_provenance": list(POSTURE_AUTHORITY_PROVENANCE),
        }
    if action == "obtain_exact_artifact_set_authorization":
        return {
            "artifact_review_action": [
                "approve_all",
                "remove_one",
                "add_one_explicitly",
                "decline",
            ]
        }
    if action == "start_next_or_stop":
        return {
            "generation_posture": list(GENERATION_POSTURES),
            "next_loop_action": ["start_next", "stop"],
        }
    return {}


class CurrentLoopCoordinator:
    """One-current-loop deterministic coordinator."""

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        state_path: str | Path | None = None,
        transport: ProtectedTransport | None = None,
        runtime_executable: str | Path | None = None,
        hosted_base_url: str = "https://preview-api.qcoder.ai",
        hosted_token_file: str | Path | None = None,
        local_only_surface: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.workspace_root = Path(workspace_root).expanduser().absolute()
        self.state_path = (
            Path(state_path).expanduser().absolute()
            if state_path is not None
            else self.workspace_root / ".qcoder" / "current-loop" / "state.json"
        )
        self.store = CurrentLoopStore(
            state_path=self.state_path,
            workspace_root=self.workspace_root,
            explicit_external=state_path is not None,
        )
        self.local_only_surface = local_only_surface
        self.transport = None if local_only_surface else transport
        self.runtime_executable = str(
            Path(runtime_executable or sys.executable).expanduser().absolute()
        )
        self.hosted_base_url = (
            ""
            if local_only_surface
            else (
                str(getattr(transport, "base_url"))
                if transport is not None and hasattr(transport, "base_url")
                else hosted_base_url
            )
        )
        self.hosted_token_file = (
            ""
            if local_only_surface
            else str(
                Path(
                    getattr(transport, "token_file")
                    if transport is not None and hasattr(transport, "token_file")
                    else (
                        hosted_token_file
                        or Path.home() / ".qcoder" / "context-bridge" / "token.txt"
                    )
                )
                .expanduser()
                .absolute()
            )
        )
        self.clock = clock
        try:
            existing = self.store.read()
        except CurrentLoopError as exc:
            if exc.category != "current_loop_not_active":
                raise
        else:
            if existing.get("schema_id") in {
                "qcoder.current_loop.local_state.v2",
                "qcoder.current_loop.local_state.v3",
                "qcoder.current_loop.local_state.v4",
            }:
                migrate_current_loop_state(self.store)

    @property
    def artifact_directory(self) -> Path:
        return self.workspace_root / ".qcoder" / "current-loop" / "artifacts"

    def validate_invocation_binding(
        self,
        *,
        expected_revision: int | None,
        expected_loop_ref: str | None,
        expected_checkpoint: str | None,
    ) -> None:
        """Reject stale or cross-loop generated invocations before dispatch."""

        if expected_revision is None and expected_loop_ref is None and expected_checkpoint is None:
            return
        if expected_revision is None or expected_loop_ref is None or expected_checkpoint is None:
            raise CurrentLoopError("operation_invocation_binding_incomplete")
        state = self.store.read()
        if int(state["state_revision"]) != expected_revision:
            raise CurrentLoopError("operation_invocation_revision_mismatch")
        state_loop_ref = str(state.get("loop_ref") or "pending-activation")
        if state_loop_ref != expected_loop_ref:
            raise CurrentLoopError("operation_invocation_loop_mismatch")
        if state.get("state_kind") == "pending_activation":
            checkpoint = "activation_request_baseline_review"
        else:
            checkpoint = str(self._coordinator_state(state)["checkpoint_kind"])
        if checkpoint != expected_checkpoint:
            raise CurrentLoopError("operation_invocation_checkpoint_mismatch")

    def _pending_activation_result(
        self,
        *,
        operation: str,
        state: Mapping[str, Any],
        category: str = "activation_request_baseline_review_required",
    ) -> dict[str, Any]:
        capture = state.get("pending_activation_capture")
        if not isinstance(capture, Mapping):
            raise CurrentLoopError("pending_activation_capture_invalid")
        constraints = [
            deepcopy(dict(item))
            for item in capture.get("explicit_constraints", [])
            if isinstance(item, Mapping)
        ]
        choices = [
            deepcopy(dict(item))
            for item in capture.get("explicit_choices", [])
            if isinstance(item, Mapping)
        ]
        request = str(capture["original_request"])
        digest = str(capture["original_request_utf8_sha256"])
        return self._result_without_state(
            operation=operation,
            ok=True,
            phase="activated",
            state_status="checkpoint_required",
            checkpoint_kind="activation_request_baseline_review",
            category=category,
            invocation_binding_state=state,
            summary=(
                "Review the complete displayed customer message. Approval will activate "
                "qCoder for this build and preserve these exact bytes as the canonical "
                "Request Baseline; posture and all later authorities remain separate."
            ),
            details={
                "pending_capture_reference": f"pending-request-{digest[:16]}",
                "original_request": request,
                "original_request_codepoint_length": len(request),
                "original_request_utf8_sha256": digest,
                "request_transport": capture.get("request_transport"),
                "explicit_constraints": constraints,
                "explicit_choices": choices,
                "assistant_interpretation": deepcopy(capture.get("assistant_interpretation") or {}),
                "label": deepcopy(capture.get("label")),
                "complete_request_displayed": True,
                "request_will_be_preserved_verbatim": True,
                "activation_and_baseline_confirmation_combined": True,
                "posture_authority_separate": True,
                "ide_write_or_run_authority_separate": True,
                "artifact_review_authority_separate": True,
                "governing_change_authority_separate": True,
                "activation_performed": False,
                "canonical_request_baseline_created": False,
                "protected_call_performed": False,
            },
        )

    def activation_offer(self, original_request: str) -> dict[str, Any]:
        posture = infer_requested_posture(original_request)
        if posture is None:
            return self._result_without_state(
                operation="activation_offer",
                ok=True,
                phase="activated",
                state_status="checkpoint_required",
                checkpoint_kind="posture",
                summary=(
                    "qCoder can help with this build. Choose a quick exploratory first "
                    "pass or Blueprint-guided control."
                ),
                category="posture_required",
                details={
                    "original_request_preserved": True,
                    "activation_performed": False,
                    "posture_selected": False,
                },
            )
        return self._result_without_state(
            operation="activation_offer",
            ok=True,
            phase="activated",
            state_status="checkpoint_required",
            checkpoint_kind="activation",
            summary=(
                f"qCoder can activate this build using {posture.replace('_', ' ')} "
                "after explicit approval."
            ),
            details={
                "original_request_preserved": True,
                "activation_performed": False,
                "proposed_posture": posture,
            },
        )

    def status(self) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self.store.read()
        except CurrentLoopError as exc:
            category = _ERROR_ALIASES.get(exc.category, exc.category)
            if category == "loop_not_activated":
                return self._recovery_result(
                    operation="status",
                    category=category,
                    phase="activated",
                    elapsed=self.clock() - started,
                )
            return self._recovery_result(
                operation="status",
                category=category,
                phase="activated",
                elapsed=self.clock() - started,
            )
        if state.get("state_kind") == "pending_activation":
            return self._pending_activation_result(operation="status", state=state)
        coordinator = self._coordinator_state(state)
        active_recovery = coordinator.get("active_recovery")
        status_details: dict[str, Any] = {
            "generation_context_outcome": deepcopy(coordinator.get("generation_context_outcome"))
        }
        if isinstance(active_recovery, Mapping):
            status_details["recovery_refresh"] = {
                "previous_error_category": active_recovery.get("category"),
                "strategy": active_recovery.get("strategy"),
                "prior_valid_authority_preserved": True,
                "prior_valid_evidence_preserved": True,
                "executes_selected_action": False,
                "active_recovery_preserved": True,
            }
            status_details["recovery_contract"] = {
                "schema_id": RECOVERY_SCHEMA_ID,
                "schema_version": RECOVERY_SCHEMA_VERSION,
                "safe_error_category": active_recovery.get("category"),
                "strategy": active_recovery.get("strategy"),
                "prior_valid_authority_preserved": True,
                "prior_valid_evidence_preserved": True,
                "hosted_operation_permitted": False,
                "alternatives": deepcopy(active_recovery.get("alternatives") or []),
                "complete_next_invocation_required": True,
                "refresh_executes_selected_action": False,
                "convergence_fingerprint": active_recovery.get("fingerprint"),
            }
        pending_resolution = coordinator.get("pending_decision_resolution")
        if isinstance(pending_resolution, Mapping):
            status_details.update(
                {
                    "decision_resolution": deepcopy(
                        pending_resolution.get("blocking_decisions") or []
                    ),
                    "blueprint_readiness_summary": deepcopy(
                        pending_resolution.get("blueprint_readiness_summary")
                    ),
                }
            )
        pending_input = coordinator.get("pending_checkpoint_input")
        if isinstance(pending_input, Mapping):
            status_details.update(self._checkpoint_input_display(pending_input))
        return self._result(
            operation="status",
            ok=coordinator["state_status"] not in {"blocked", "conflict", "corrupt"},
            state=state,
            summary=coordinator["customer_summary"],
            elapsed=self.clock() - started,
            details=status_details,
            checkpoint_protocol=(
                {
                    "supported_next_action": "refresh_bounded_recovery",
                    "next_invocation": _invocation_template(
                        "status",
                        reused_inputs=("current_qcoder_owned_local_state",),
                    ),
                    "required_authority_input": None,
                    "awaiting_confirmation_fields": [],
                    "confirmation_transmission_state": "not_applicable",
                    "identical_repeat_prohibited": False,
                    "permitted_input_source": "fresh_qcoder_coordinator_result",
                    "no_action_reason": None,
                }
                if isinstance(active_recovery, Mapping)
                else None
            ),
        )

    def stage_checkpoint_input(
        self,
        *,
        operation: str | None,
        checkpoint_kind: str | None,
        payload: Mapping[str, Any],
        transport: str,
    ) -> dict[str, Any]:
        """Stage exact assistant-created values without granting authority."""

        started = self.clock()
        try:
            supplied_operation, supplied_kind = checkpoint_input_binding_values(payload)
            if operation is None:
                operation = supplied_operation
            if checkpoint_kind is None:
                checkpoint_kind = supplied_kind
            if operation != supplied_operation:
                raise CheckpointInputStructuralError(
                    "checkpoint_input_operation_mismatch",
                    expected_operation=operation,
                    expected_checkpoint_kind=checkpoint_kind,
                    **checkpoint_input_safe_structure(payload),
                )
            if checkpoint_kind != supplied_kind:
                raise CheckpointInputStructuralError(
                    "checkpoint_input_checkpoint_mismatch",
                    expected_operation=operation,
                    expected_checkpoint_kind=checkpoint_kind,
                    **checkpoint_input_safe_structure(payload),
                )
            allowed_phases = {
                "prepare_generation": {"intent_review", "generation_ready"},
                "continue_unchanged": {"continuation_choice", "change_confirmation"},
                "propose_change": {"continuation_choice"},
                "confirm_change": {"change_confirmation"},
            }[operation]
            state = self._require_phase("stage_checkpoint_input", allowed_phases)
            coordinator = self._coordinator_state(state)
            expected_kinds = {
                "prepare_generation": {"intent_review", "decision_resolution", "posture"},
                "continue_unchanged": {"governing_change_confirmation"},
                "propose_change": {"governing_change_confirmation"},
                "confirm_change": {"governing_change_confirmation"},
            }[operation]
            if checkpoint_kind not in expected_kinds:
                raise CurrentLoopError("checkpoint_input_checkpoint_mismatch")
            prior = coordinator.get("pending_checkpoint_input")
            history = list(coordinator.get("checkpoint_input_history") or [])
            if isinstance(prior, Mapping):
                if prior.get("status") == "pending" and prior.get(
                    "transport_utf8_sha256"
                ) == payload.get("_transport_utf8_sha256"):
                    raise CurrentLoopError("checkpoint_input_identical_repeat")
                history.append(
                    {
                        "content_digest": prior.get("content_digest"),
                        "transport_utf8_sha256": prior.get("transport_utf8_sha256"),
                        "operation": prior.get("operation"),
                        "status": "invalidated",
                    }
                )
            record = normalize_checkpoint_input(
                payload,
                operation=operation,
                checkpoint_kind=checkpoint_kind,
                workspace_binding=str(state["workspace_root"]),
                loop_ref=str(state["loop_ref"]),
                phase=str(coordinator["phase"]),
                expected_state_revision=int(state["state_revision"]) + 2,
                source_state_revision=int(state["state_revision"]),
                captured_at=self.clock(),
                transport=transport,
                semantic_contract=checkpoint_input_construction(
                    operation=operation,
                    checkpoint_kind=checkpoint_kind,
                    workspace_binding=str(state["workspace_root"]),
                    loop_ref=str(state["loop_ref"]),
                    phase=str(coordinator["phase"]),
                    expected_state_revision=int(state["state_revision"]),
                    bounded_domains=self._checkpoint_input_bounded_domains(
                        operation=operation,
                        state=state,
                    ),
                )["semantic_field_contract"],
            )
            if any(
                isinstance(item, Mapping)
                and (
                    item.get("content_digest") == record["content_digest"]
                    or (
                        record.get("transport_utf8_sha256") is not None
                        and item.get("transport_utf8_sha256") == record.get("transport_utf8_sha256")
                    )
                )
                and item.get("status") == "promoted"
                for item in history
            ):
                raise CurrentLoopError("checkpoint_input_replay")
            prior_protocol = (
                prior.get("prior_protocol")
                if isinstance(prior, Mapping) and isinstance(prior.get("prior_protocol"), Mapping)
                else {
                    "state_status": coordinator["state_status"],
                    "checkpoint_kind": coordinator["checkpoint_kind"],
                    "customer_summary": coordinator["customer_summary"],
                }
            )
            record["prior_protocol"] = deepcopy(dict(prior_protocol))
            coordinator.update(
                {
                    "state_status": "checkpoint_required",
                    "checkpoint_kind": "checkpoint_input_review",
                    "customer_summary": (
                        "Review every complete staged value. Approval promotes these exact "
                        "bytes; correction replaces the pending set and requires new review."
                    ),
                    "pending_checkpoint_input": record,
                    "checkpoint_input_history": history[-16:],
                }
            )
            self._replace_coordinator(coordinator)
            return self._result(
                operation="stage_checkpoint_input",
                ok=True,
                state=self.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                category="checkpoint_input_review_required",
                details=self._checkpoint_input_display(record),
            )
        except (CurrentLoopError, CurrentLoopConflict, EvidenceProcessingError, ValueError) as exc:
            return self._exception_result("stage_checkpoint_input", exc, started)

    def approve_staged_checkpoint_input(
        self,
        *,
        explicit_authority: bool,
    ) -> dict[str, Any]:
        """Promote one exact pending set, then execute its bound operation."""

        started = self.clock()
        try:
            state = self.store.read()
            coordinator = self._coordinator_state(state)
            pending = coordinator.get("pending_checkpoint_input")
            if explicit_authority is not True:
                return self._result_without_state(
                    operation="approve_staged_checkpoint_input",
                    phase=coordinator["phase"],
                    state_status="checkpoint_required",
                    checkpoint_kind="checkpoint_input_review",
                    ok=True,
                    summary="The exact staged values remain pending; omission is not approval.",
                    category="checkpoint_input_approval_not_transmitted",
                    details=(
                        self._checkpoint_input_display(pending)
                        if isinstance(pending, Mapping)
                        else {}
                    ),
                )
            if not isinstance(pending, Mapping):
                raise CurrentLoopError("checkpoint_input_pending_required")
            if pending.get("expected_state_revision") != state["state_revision"]:
                raise CurrentLoopError("checkpoint_input_state_revision_stale")
            if (
                pending.get("workspace_binding") != str(state["workspace_root"])
                or pending.get("loop_ref") != state["loop_ref"]
                or pending.get("phase") != coordinator["phase"]
            ):
                raise CurrentLoopError("checkpoint_input_binding_mismatch")
            values = checkpoint_input_values(pending)
            operation = str(pending["operation"])
            digest = str(pending["content_digest"])
            history = list(coordinator.get("checkpoint_input_history") or [])
            history.append(
                {
                    "content_digest": digest,
                    "transport_utf8_sha256": pending.get("transport_utf8_sha256"),
                    "operation": operation,
                    "status": "promoted",
                    "promoted_at": self.clock(),
                }
            )
            prior_protocol = pending.get("prior_protocol")
            if not isinstance(prior_protocol, Mapping):
                raise CurrentLoopError("checkpoint_input_record_invalid")
            coordinator.update(
                {
                    "state_status": prior_protocol.get("state_status"),
                    "checkpoint_kind": prior_protocol.get("checkpoint_kind"),
                    "customer_summary": prior_protocol.get("customer_summary"),
                    "pending_checkpoint_input": None,
                    "checkpoint_input_history": history[-16:],
                }
            )
            self._replace_coordinator(coordinator)
            result = self._execute_promoted_checkpoint_input(operation, values)
            details = result.setdefault("details", {})
            if isinstance(details, dict):
                details.update(
                    {
                        "checkpoint_input_schema_id": CHECKPOINT_INPUT_SCHEMA_ID,
                        "checkpoint_input_schema_version": CHECKPOINT_INPUT_SCHEMA_VERSION,
                        "semantic_contract_schema_id": pending.get("semantic_contract_schema_id"),
                        "semantic_contract_schema_version": pending.get(
                            "semantic_contract_schema_version"
                        ),
                        "semantic_contract_digest": pending.get("semantic_contract_digest"),
                        "staged_content_digest": digest,
                        "promoted_content_digest": digest,
                        "stage_to_promotion_semantic_compatibility_verified": True,
                        "authority_only_promotion": True,
                        "literal_free_text_in_argv": False,
                        "replay_permitted": False,
                    }
                )
            return result
        except (CurrentLoopError, CurrentLoopConflict, ValueError) as exc:
            return self._exception_result("approve_staged_checkpoint_input", exc, started)

    def decline_staged_checkpoint_input(
        self,
        *,
        explicit_authority: bool,
    ) -> dict[str, Any]:
        """Decline one pending exact set without promoting it."""

        started = self.clock()
        try:
            state = self.store.read()
            coordinator = self._coordinator_state(state)
            pending = coordinator.get("pending_checkpoint_input")
            if not isinstance(pending, Mapping):
                raise CurrentLoopError("checkpoint_input_pending_required")
            if explicit_authority is not True:
                return self._result_without_state(
                    operation="decline_staged_checkpoint_input",
                    phase=coordinator["phase"],
                    state_status="checkpoint_required",
                    checkpoint_kind="checkpoint_input_review",
                    ok=True,
                    summary="The exact staged values remain pending; omission is not a decline.",
                    category="checkpoint_input_decline_not_transmitted",
                    details=self._checkpoint_input_display(pending),
                )
            if pending.get("expected_state_revision") != state["state_revision"]:
                raise CurrentLoopError("checkpoint_input_state_revision_stale")
            history = list(coordinator.get("checkpoint_input_history") or [])
            history.append(
                {
                    "content_digest": pending.get("content_digest"),
                    "operation": pending.get("operation"),
                    "status": "invalidated",
                    "declined_at": self.clock(),
                }
            )
            prior = pending.get("prior_protocol")
            if not isinstance(prior, Mapping):
                raise CurrentLoopError("checkpoint_input_record_invalid")
            coordinator.update(
                {
                    "state_status": prior.get("state_status"),
                    "checkpoint_kind": prior.get("checkpoint_kind"),
                    "customer_summary": (
                        "The staged values were declined and not promoted. "
                        + str(prior.get("customer_summary") or "")
                    ).strip(),
                    "pending_checkpoint_input": None,
                    "checkpoint_input_history": history[-16:],
                }
            )
            self._replace_coordinator(coordinator)
            return self._result(
                operation="decline_staged_checkpoint_input",
                ok=True,
                state=self.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                category="checkpoint_input_declined",
                details={
                    "staged_content_promoted": False,
                    "protected_call_performed": False,
                    "pending_input_invalidated": True,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict, ValueError) as exc:
            return self._exception_result("decline_staged_checkpoint_input", exc, started)

    def _execute_promoted_checkpoint_input(
        self,
        operation: str,
        values: Mapping[str, Any],
    ) -> dict[str, Any]:
        if operation == "prepare_generation":
            requested_posture = values.get("requested_generation_posture")
            return self.prepare_generation(
                profile_id=str(values["profile_id"]),
                proposed_interpretation=self._mapping_value(values, "proposed_interpretation"),
                requirements=self._mapping_sequence(values, "requirements"),
                constraints=self._string_sequence(values, "constraints"),
                non_goals=self._string_sequence(values, "non_goals"),
                decision_dispositions=self._mapping_sequence(values, "decision_dispositions"),
                reviewed_profile_answers=self._optional_mapping_value(
                    values, "reviewed_profile_answers"
                ),
                explicit_intent_approval=True,
                confirmation_assertion=self._optional_string_value(
                    values, "confirmation_assertion"
                ),
                accepted_unresolved_choices=self._string_sequence(
                    values, "accepted_unresolved_choices"
                ),
                explicit_decision_authority=bool(values.get("decision_dispositions")),
                requested_generation_posture=(
                    str(requested_posture) if requested_posture is not None else None
                ),
                explicit_posture_authority=(
                    requested_posture is not None
                    and values.get("posture_change_reason") is not None
                ),
                posture_change_reason=self._optional_string_value(values, "posture_change_reason"),
                posture_authority_provenance=self._optional_string_value(
                    values, "posture_authority_provenance"
                ),
            )
        if operation == "continue_unchanged":
            return self.continue_unchanged(
                explicit_user_action=True,
                user_statement=self._string_value(values, "user_statement"),
                decline_unconfirmed_proposal=(values.get("decline_unconfirmed_proposal") is True),
            )
        if operation == "propose_change":
            return self.propose_change(
                decision_ref=self._string_value(values, "decision_ref"),
                selected_action=self._string_value(values, "selected_action"),
                proposed_value=deepcopy(values["proposed_value"]),
                control_treatment=self._string_value(values, "control_treatment"),
                explicit_user_selection=True,
            )
        if operation == "confirm_change":
            return self.confirm_change(
                semantic_confirmation=self._string_value(values, "semantic_confirmation"),
                explicit_user_confirmation=True,
            )
        raise CurrentLoopError("checkpoint_input_operation_invalid")

    def _checkpoint_input_display(self, record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "pending_capture_reference": (
                f"pending-checkpoint-input-{str(record['content_digest'])[:16]}"
            ),
            "checkpoint_input_schema_id": record.get("schema_id"),
            "checkpoint_input_schema_version": record.get("schema_version"),
            "semantic_contract_schema_id": record.get("semantic_contract_schema_id"),
            "semantic_contract_schema_version": record.get("semantic_contract_schema_version"),
            "semantic_contract_digest": record.get("semantic_contract_digest"),
            "operation": record.get("operation"),
            "checkpoint_kind": record.get("checkpoint_kind"),
            "phase": record.get("phase"),
            "expected_state_revision": record.get("expected_state_revision"),
            "complete_staged_values": [
                {
                    "field": field.get("name"),
                    "value": deepcopy(field.get("value")),
                    "provenance": field.get("provenance"),
                    "utf8_sha256": field.get("value_utf8_sha256"),
                    "size_bytes": field.get("size_bytes"),
                }
                for field in record.get("fields", [])
                if isinstance(field, Mapping)
            ],
            "content_digest": record.get("content_digest"),
            "complete_values_displayed": True,
            "protected_call_performed": False,
            "authority_granted": False,
            "canonical_promotion_performed": False,
        }

    @staticmethod
    def _string_value(values: Mapping[str, Any], name: str) -> str:
        value = values.get(name)
        if not isinstance(value, str) or not value:
            raise CurrentLoopError("checkpoint_input_field_type_invalid")
        return value

    @classmethod
    def _optional_string_value(cls, values: Mapping[str, Any], name: str) -> str | None:
        return cls._string_value(values, name) if name in values else None

    @staticmethod
    def _mapping_value(values: Mapping[str, Any], name: str) -> dict[str, Any]:
        value = values.get(name)
        if not isinstance(value, Mapping):
            raise CurrentLoopError("checkpoint_input_field_type_invalid")
        return deepcopy(dict(value))

    @classmethod
    def _optional_mapping_value(cls, values: Mapping[str, Any], name: str) -> dict[str, Any] | None:
        return cls._mapping_value(values, name) if name in values else None

    @staticmethod
    def _mapping_sequence(values: Mapping[str, Any], name: str) -> list[dict[str, Any]]:
        value = values.get(name, [])
        if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
            raise CurrentLoopError("checkpoint_input_field_type_invalid")
        return [deepcopy(dict(item)) for item in value]

    @staticmethod
    def _string_sequence(values: Mapping[str, Any], name: str) -> list[str]:
        value = values.get(name, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise CurrentLoopError("checkpoint_input_field_type_invalid")
        return list(value)

    def activate(
        self,
        *,
        original_request: str | None = None,
        generation_posture: str | None = None,
        explicit_authority: bool = False,
        explicit_posture_authority: bool = False,
        posture_authority_provenance: str | None = None,
        request_transport: str = "inline",
        explicit_constraints: Sequence[str] = (),
        explicit_choices: Sequence[str] = (),
        label: str | None = None,
        label_provenance: str | None = None,
        parent_loop_ref: str | None = None,
        assistant_interpretation: Mapping[str, Any] | None = None,
        capture_mode: str = "review_required",
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            if capture_mode not in {"review_required", "exact_current_customer_message"}:
                raise CurrentLoopError("activation_capture_mode_invalid")
            if original_request is not None and capture_mode == "exact_current_customer_message":
                if (
                    explicit_authority is not True
                    or generation_posture is not None
                    or explicit_posture_authority
                    or explicit_constraints
                    or explicit_choices
                    or assistant_interpretation is not None
                    or "qcoder" not in original_request.casefold()
                ):
                    raise CurrentLoopError("activation_exact_message_mode_ineligible")
                baseline = build_request_baseline(original_request=original_request)
                baseline_digest = sha256(original_request.encode("utf-8")).hexdigest()
                activated = activate_current_loop(
                    workspace_root=self.workspace_root,
                    generation_posture=None,
                    explicit_authority=True,
                    label=label,
                    external_state_path=(
                        self.state_path
                        if self.state_path
                        != self.workspace_root / ".qcoder" / "current-loop" / "state.json"
                        else None
                    ),
                    request_baseline_digest=baseline_digest,
                    activation_capture_provenance="exact_current_customer_message",
                )
                self._save_artifact("request_baseline", baseline, "request-baseline.json")
                state = self.store.read()
                contract = state["current_loop_contract"]
                coordinator = self._initial_coordinator_state(
                    phase="activated",
                    state_status="ready",
                    checkpoint_kind="none",
                    summary=(
                        "qCoder is active under Assist. The exact current customer message "
                        "is preserved as the Request Baseline. Generation posture remains unset "
                        "until generation becomes relevant."
                    ),
                )
                coordinator["activation"] = {
                    "explicit": True,
                    "capture_mode": "exact_current_customer_message",
                    "original_request_preserved": True,
                    "redundant_baseline_approval_required": False,
                    "generation_posture_explicit": False,
                }
                coordinator["assist_ready"] = True
                coordinator["request_baseline_reference"] = _artifact_reference(baseline)
                self._replace_coordinator(coordinator)
                return self._result(
                    operation="activate",
                    ok=True,
                    state=self.store.read(),
                    summary=coordinator["customer_summary"],
                    elapsed=self.clock() - started,
                    details={
                        "loop_ref": activated["state"]["loop_ref"],
                        "request_baseline_saved": True,
                        "original_request": original_request,
                        "original_request_utf8_sha256": baseline_digest,
                        "activation_receipt": deepcopy(contract["activation_receipt"]),
                        "effective_preset": "assist",
                        "assist_ready": True,
                        "posture_deferred": True,
                        "ide_write_or_run_authorized": False,
                        "artifact_review_authorized": False,
                    },
                )
            if original_request is not None:
                capture = build_pending_activation_capture(
                    original_request=original_request,
                    workspace_root=self.workspace_root,
                    request_transport=request_transport,
                    explicit_constraints=explicit_constraints,
                    explicit_choices=explicit_choices,
                    assistant_interpretation=assistant_interpretation,
                    label=label,
                    label_provenance=label_provenance,
                    captured_at=self.clock(),
                )
                state = stage_pending_activation_capture(
                    workspace_root=self.workspace_root,
                    capture=capture,
                    external_state_path=(
                        self.state_path
                        if self.state_path
                        != self.workspace_root / ".qcoder" / "current-loop" / "state.json"
                        else None
                    ),
                )
                return self._pending_activation_result(
                    operation="activate",
                    state=state,
                    category=(
                        "new_request_requires_exact_baseline_review"
                        if explicit_authority
                        else "activation_request_baseline_review_required"
                    ),
                )

            try:
                state = self.store.read()
            except CurrentLoopError:
                if explicit_authority:
                    return self._recovery_result(
                        operation="activate",
                        category="activation_capture_required",
                        phase="activated",
                        elapsed=self.clock() - started,
                    )
                return self._recovery_result(
                    operation="activate",
                    category="loop_not_activated",
                    phase="activated",
                    elapsed=self.clock() - started,
                )

            if state.get("state_kind") == "active_loop":
                if state.get("generation_posture") is None and generation_posture is not None:
                    if (
                        explicit_posture_authority is not True
                        or posture_authority_provenance not in POSTURE_AUTHORITY_PROVENANCE
                    ):
                        return self._checkpoint_result(
                            operation="activate",
                            phase="activated",
                            checkpoint_kind="posture",
                            category="posture_authority_required",
                            summary=(
                                "qCoder is active, but generation posture remains "
                                "unselected. Obtain a separate explicit posture decision."
                            ),
                            elapsed=self.clock() - started,
                        )
                    selected = select_current_loop_generation_posture(
                        store=self.store,
                        generation_posture=generation_posture,
                        explicit_authority=True,
                    )
                    coordinator = self._coordinator_state(selected["state"])
                    coordinator.update(
                        {
                            "phase": "intent_review",
                            "state_status": "checkpoint_required",
                            "checkpoint_kind": "intent_review",
                            "customer_summary": (
                                "Generation posture is separately authorized. Review "
                                "the assistant-proposed interpretation next."
                            ),
                            "effective_generation_posture": generation_posture,
                        }
                    )
                    coordinator["posture_selection"] = {
                        "explicit": True,
                        "provenance": posture_authority_provenance,
                    }
                    self._replace_coordinator(coordinator)
                    return self._result(
                        operation="activate",
                        ok=True,
                        state=self.store.read(),
                        summary=coordinator["customer_summary"],
                        elapsed=self.clock() - started,
                        details={
                            "generation_posture": generation_posture,
                            "posture_authority_transmitted": True,
                            "request_baseline_saved": True,
                        },
                    )
                return self._recovery_result(
                    operation="activate",
                    category="loop_already_active",
                    phase=self._safe_phase(),
                    elapsed=self.clock() - started,
                )

            if explicit_authority is not True:
                return self._pending_activation_result(
                    operation="activate",
                    state=state,
                )
            capture = state.get("pending_activation_capture")
            if not isinstance(capture, Mapping):
                raise CurrentLoopError("pending_activation_capture_invalid")
            if generation_posture is not None:
                if (
                    explicit_posture_authority is not True
                    or posture_authority_provenance not in POSTURE_AUTHORITY_PROVENANCE
                ):
                    generation_posture = None
                elif (
                    posture_authority_provenance == "user_provided"
                    and infer_requested_posture(str(capture["original_request"]))
                    != generation_posture
                ):
                    raise CurrentLoopError("posture_not_attributable_to_request")
            elif explicit_posture_authority:
                raise CurrentLoopError("posture_value_required")
            label_record = capture.get("label")
            if not isinstance(label_record, Mapping):
                raise CurrentLoopError("pending_activation_label_invalid")
            baseline = build_request_baseline(
                original_request=str(capture["original_request"]),
                explicit_constraints=[
                    str(item["value"])
                    for item in capture.get("explicit_constraints", [])
                    if isinstance(item, Mapping)
                ],
                explicit_choices=[
                    str(item["value"])
                    for item in capture.get("explicit_choices", [])
                    if isinstance(item, Mapping)
                ],
                assistant_interpretation=(
                    capture.get("assistant_interpretation")
                    if isinstance(capture.get("assistant_interpretation"), Mapping)
                    else None
                ),
            )
            activated = activate_current_loop(
                workspace_root=self.workspace_root,
                generation_posture=generation_posture,
                explicit_authority=True,
                parent_loop_ref=parent_loop_ref,
                label=str(label_record["value"]),
                request_baseline_digest=sha256(
                    str(capture["original_request"]).encode("utf-8")
                ).hexdigest(),
                activation_capture_provenance="reviewed_exact_request_baseline",
                external_state_path=(
                    self.state_path
                    if self.state_path
                    != self.workspace_root / ".qcoder" / "current-loop" / "state.json"
                    else None
                ),
            )
            self._save_artifact(
                "request_baseline",
                baseline,
                "request-baseline.json",
            )
            state = self.store.read()
            coordinator = self._initial_coordinator_state(
                phase=("intent_review" if generation_posture is not None else "activated"),
                state_status="checkpoint_required",
                checkpoint_kind=("intent_review" if generation_posture is not None else "posture"),
                summary=(
                    (
                        "qCoder is active and the complete Request Baseline is saved "
                        "verbatim. Review the separately attributed assistant "
                        "interpretation before confirming generation intent."
                    )
                    if generation_posture is not None
                    else (
                        "qCoder is active and the complete Request Baseline is saved "
                        "verbatim. Choose the separate generation posture next."
                    )
                ),
            )
            coordinator["activation"] = {
                "explicit": True,
                "original_request_preserved": True,
                "exact_baseline_approved": True,
                "generation_posture_explicit": generation_posture is not None,
            }
            coordinator["effective_generation_posture"] = generation_posture
            coordinator["request_baseline_reference"] = _artifact_reference(baseline)
            self._replace_coordinator(coordinator)
            state = self.store.read()
            return self._result(
                operation="activate",
                ok=True,
                state=state,
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                details={
                    "loop_ref": activated["state"]["loop_ref"],
                    "generation_posture": generation_posture,
                    "request_baseline_saved": True,
                    "original_request": baseline["original_request"],
                    "original_request_utf8_sha256": sha256(
                        baseline["original_request"].encode("utf-8")
                    ).hexdigest(),
                    "activation_authority_transmitted": True,
                    "posture_authority_transmitted": generation_posture is not None,
                    "ide_write_or_run_authorized": False,
                    "artifact_review_authorized": False,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict, ValueError) as exc:
            return self._exception_result("activate", exc, started)

    def prepare_generation(
        self,
        *,
        profile_id: str,
        proposed_interpretation: Mapping[str, Any],
        requirements: Sequence[Mapping[str, Any]] = (),
        constraints: Sequence[str] = (),
        non_goals: Sequence[str] = (),
        decision_dispositions: Sequence[Mapping[str, Any]] = (),
        reviewed_profile_answers: Mapping[str, Any] | None = None,
        explicit_intent_approval: bool,
        confirmation_assertion: str | None = None,
        accepted_unresolved_choices: Sequence[str] = (),
        explicit_decision_authority: bool = False,
        requested_generation_posture: str | None = None,
        explicit_posture_authority: bool = False,
        posture_change_reason: str | None = None,
        posture_authority_provenance: str | None = None,
        posture_only: bool = False,
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            if not profile_id:
                profile_id = "generic_qiskit"
            state = self._require_phase("prepare_generation", {"intent_review", "generation_ready"})
            self._require_contract_permission(
                state,
                category="generation_context",
                dimension="derive",
            )
            self._require_contract_permission(
                state,
                category="generation_context",
                dimension="assistant_derived_exposure",
            )
            if self.transport is None:
                return self._recovery_result(
                    operation="prepare_generation",
                    category="protected_service_unavailable",
                    phase=self._coordinator_state(state)["phase"],
                    elapsed=self.clock() - started,
                )
            coordinator = self._coordinator_state(state)
            current_posture = str(
                coordinator.get("effective_generation_posture") or state["generation_posture"]
            )
            requested_posture = requested_generation_posture or current_posture
            posture_transition_applied = False
            if requested_posture not in {"blueprint_guided", "exploratory_first_pass"}:
                raise CurrentLoopError("generation_posture_invalid")
            pending_resolution = coordinator.get("pending_decision_resolution")
            if requested_posture != current_posture:
                if explicit_posture_authority is not True or not isinstance(
                    posture_authority_provenance, str
                ):
                    return self._checkpoint_result(
                        operation="prepare_generation",
                        phase="intent_review",
                        checkpoint_kind="posture",
                        summary=(
                            "Changing generation posture requires explicit user authority, "
                            "an attributable reason, and provenance. Workspace state is not intent."
                        ),
                        elapsed=self.clock() - started,
                        category="posture_transition_authority_required",
                        details={
                            "source_posture": current_posture,
                            "requested_posture": requested_posture,
                            "working_blueprint_mutated": False,
                            "decision_mutation": False,
                        },
                    )
                if requested_posture == "exploratory_first_pass" and decision_dispositions:
                    raise CurrentLoopError("posture_transition_decision_mutation_prohibited")
                self._record_posture_transition(
                    coordinator,
                    source_posture=current_posture,
                    requested_posture=requested_posture,
                    reason=(
                        posture_change_reason
                        if isinstance(posture_change_reason, str)
                        else "Explicit bounded customer posture choice."
                    ),
                    provenance=posture_authority_provenance,
                )
                coordinator["customer_summary"] = (
                    f"This attempt now uses {requested_posture.replace('_', ' ')} by "
                    "explicit user authority. The Working Blueprint and unresolved "
                    "decision inventory remain unchanged."
                )
                self._replace_coordinator(coordinator)
                state = self.store.read()
                coordinator = self._coordinator_state(state)
                posture_transition_applied = True
                if posture_only:
                    return self._result(
                        operation="prepare_generation",
                        ok=True,
                        state=state,
                        summary=coordinator["customer_summary"],
                        elapsed=self.clock() - started,
                        category="generation_posture_transition_recorded",
                        details={
                            "source_posture": current_posture,
                            "selected_posture": requested_posture,
                            "bounded_enumerated_choice": True,
                            "checkpoint_input_transport_used": False,
                            "protected_call_performed": False,
                        },
                    )
            elif posture_only:
                raise CurrentLoopError("generation_posture_transition_not_requested")

            existing_records: list[Mapping[str, Any]] = []
            prior_dispositions: list[Mapping[str, Any]] = []
            if isinstance(pending_resolution, Mapping):
                existing_records = [
                    item
                    for item in pending_resolution.get("decision_records", [])
                    if isinstance(item, Mapping)
                ]
                prior_dispositions = [
                    item
                    for item in pending_resolution.get("authorized_dispositions", [])
                    if isinstance(item, Mapping)
                ]
            if decision_dispositions and explicit_decision_authority is not True:
                return self._checkpoint_result(
                    operation="prepare_generation",
                    phase="intent_review",
                    checkpoint_kind="decision_resolution",
                    summary=(
                        "Decision values were supplied without the separate explicit "
                        "decision authority. Omission of --approve-decisions is not approval."
                    ),
                    elapsed=self.clock() - started,
                    category="decision_authority_not_transmitted",
                    details={
                        "decision_dispositions_transmitted": False,
                        "assistant_recommendations_adopted": False,
                    },
                )
            merged_dispositions: dict[str, Mapping[str, Any]] = {
                str(item.get("profile_decision_id")): item for item in prior_dispositions
            }
            for item in decision_dispositions:
                decision_id = str(item.get("profile_decision_id") or "")
                merged_dispositions[decision_id] = item
            normalized_dispositions = normalize_decision_dispositions(
                profile_id,
                list(merged_dispositions.values()),
                existing_records=existing_records,
            )
            baseline = self._saved_artifact(state, "request_baseline")
            original_request = baseline.get("original_request")
            if not isinstance(original_request, str):
                raise CurrentLoopError("canonical_artifact_modified")
            review_input = self._intent_review_input(
                profile_id=profile_id,
                proposed_interpretation=proposed_interpretation,
                requirements=requirements,
                constraints=constraints,
                non_goals=non_goals,
                decision_dispositions=normalized_dispositions,
                reviewed_profile_answers=reviewed_profile_answers,
                accepted_unresolved_choices=accepted_unresolved_choices,
                generation_posture=requested_posture,
            )
            review_input_digest = sha256(canonical_bytes(review_input)).hexdigest()
            if posture_transition_applied:
                return self._prepare_generation_after_posture_transition(
                    state=state,
                    coordinator=coordinator,
                    pending_resolution=(
                        pending_resolution if isinstance(pending_resolution, Mapping) else None
                    ),
                    profile_id=profile_id,
                    requested_posture=requested_posture,
                    review_input=review_input,
                    review_input_digest=review_input_digest,
                    normalized_dispositions=normalized_dispositions,
                    constraints=constraints,
                    non_goals=non_goals,
                    accepted_unresolved_choices=accepted_unresolved_choices,
                    started=started,
                )
            if (
                requested_posture == "blueprint_guided"
                and isinstance(pending_resolution, Mapping)
                and pending_resolution.get("input_digest") == review_input_digest
            ):
                summary = (
                    "The Blueprint-guided readiness checkpoint is unchanged and no new "
                    "authorized disposition was transmitted. Review the existing blockers, "
                    "defer, or explicitly switch this attempt to exploratory first pass."
                )
                coordinator["customer_summary"] = summary
                self._replace_coordinator(coordinator)
                return self._result(
                    operation="prepare_generation",
                    ok=True,
                    state=self.store.read(),
                    summary=summary,
                    elapsed=self.clock() - started,
                    category="decision_resolution_unchanged",
                    details={
                        "protected_call_made": False,
                        "identical_pending_review_reused": True,
                        "decision_resolution": deepcopy(
                            pending_resolution.get("blocking_decisions") or []
                        ),
                    },
                    checkpoint_protocol={
                        "confirmation_transmission_state": "not_supplied",
                        "awaiting_confirmation_fields": list(
                            pending_resolution.get("awaiting_confirmation_fields") or []
                        ),
                    },
                )
            pending = coordinator.get("pending_intent_review")
            if (
                explicit_intent_approval is True
                and isinstance(pending, Mapping)
                and pending.get("input_digest") == review_input_digest
                and pending.get("confirmation_transmission_state") == "supplied"
            ):
                awaiting = list(
                    pending.get("awaiting_confirmation_fields") or ["reviewed_interpretation"]
                )
                summary = (
                    "Confirmation was already transmitted for these unchanged inputs. "
                    "Review the returned clarification fields and stop; do not retry "
                    "until corrected input is available."
                )
                coordinator["customer_summary"] = summary
                self._replace_coordinator(coordinator)
                return self._result(
                    operation="prepare_generation",
                    ok=True,
                    state=self.store.read(),
                    summary=summary,
                    elapsed=self.clock() - started,
                    category="intent_clarification_unchanged",
                    details={
                        "intent_confirmation_state": pending.get("intent_confirmation_state"),
                        "confirmation_transmission_state": "supplied",
                        "awaiting_confirmation_fields": awaiting,
                        "working_blueprint_created": False,
                        "generation_context_created": False,
                        "protected_call_made": False,
                        "identical_pending_review_reused": True,
                    },
                    checkpoint_protocol={
                        "confirmation_transmission_state": "supplied",
                        "awaiting_confirmation_fields": awaiting,
                    },
                )
            if (
                explicit_intent_approval is not True
                and isinstance(pending, Mapping)
                and pending.get("input_digest") == review_input_digest
            ):
                summary = (
                    "The reviewed interpretation is unchanged, but explicit intent "
                    "confirmation was not transmitted. Present the existing proposal "
                    "and re-invoke with --confirm-intent only after user approval."
                )
                coordinator["customer_summary"] = summary
                coordinator["state_status"] = "checkpoint_required"
                coordinator["checkpoint_kind"] = "intent_review"
                self._replace_coordinator(coordinator)
                return self._result(
                    operation="prepare_generation",
                    ok=True,
                    state=self.store.read(),
                    summary=summary,
                    elapsed=self.clock() - started,
                    category="confirmation_not_transmitted",
                    details={
                        "intent_confirmation_state": pending.get("intent_confirmation_state"),
                        "confirmation_transmission_state": "not_supplied",
                        "working_blueprint_created": False,
                        "generation_context_created": False,
                        "protected_call_made": False,
                        "identical_pending_review_reused": True,
                    },
                    checkpoint_protocol={
                        "confirmation_transmission_state": "not_supplied",
                        "awaiting_confirmation_fields": ["explicit_intent_confirmation"],
                    },
                )
            interpretation = deepcopy(dict(proposed_interpretation))
            if reviewed_profile_answers:
                interpretation.update(deepcopy(dict(reviewed_profile_answers)))
            intent_arguments: dict[str, Any] = {
                "original_user_intent": original_request,
                "profile_id": profile_id,
                "proposed_interpretation": interpretation,
                "requirements": [deepcopy(dict(item)) for item in requirements],
                "constraints": list(constraints),
                "non_goals": list(non_goals),
                "decision_loop": "readiness_resolution_v1",
                "profile_decision_catalog_version": 1,
                "current_lineage_reference": baseline["artifact_ref"],
                "decision_dispositions": deepcopy(normalized_dispositions),
                "field_provenance": {
                    "original_user_intent": "user",
                    "proposed_interpretation": "connected_assistant",
                    "reviewed_profile_answers": "user",
                },
                "requested_confirmation_state": (
                    "confirmed" if explicit_intent_approval else "proposed"
                ),
                "accepted_unresolved_choices": list(accepted_unresolved_choices),
            }
            if existing_records:
                intent_arguments["decision_references"] = {
                    str(item["profile_decision_id"]): str(item["decision_ref"])
                    for item in existing_records
                    if isinstance(item.get("profile_decision_id"), str)
                    and isinstance(item.get("decision_ref"), str)
                }
            if explicit_intent_approval:
                intent_arguments["confirmation_assertion"] = {"user_reviewed": True}
            intent_payload = self._protected_call("create_algorithm_intent_card", intent_arguments)
            intent = self._response_artifact(intent_payload, "algorithm_intent_card")
            if intent.get("confirmation_state") != "confirmed":
                self._save_intent_review_artifact(intent)
                awaiting = self._intent_clarification_fields(intent)
                transmitted = explicit_intent_approval is True
                hosted_values = self._hosted_clarification_values(intent, awaiting)
                if transmitted and hosted_values is not None:
                    corrected_review = deepcopy(review_input)
                    corrected_answers = dict(corrected_review.get("reviewed_profile_answers") or {})
                    corrected_answers.update(hosted_values)
                    corrected_review["reviewed_profile_answers"] = corrected_answers
                    staged = self._stage_held_prepare_generation_values(
                        corrected_review,
                        provenance="hosted_presented",
                    )
                    details = staged.setdefault("details", {})
                    if isinstance(details, dict):
                        details.update(
                            {
                                "hosted_call_preceded_staging": True,
                                "hosted_presented_fields": sorted(hosted_values),
                                "assistant_retransmission_required": False,
                            }
                        )
                    return staged
                category = (
                    "intent_clarification_required"
                    if transmitted
                    else "intent_confirmation_required"
                )
                summary = (
                    "Intent confirmation was transmitted, but the hosted review "
                    "requires the returned clarification fields before it can confirm."
                    if transmitted
                    else (
                        "Present the assistant-proposed interpretation for explicit "
                        "review. After approval, re-invoke with --confirm-intent; do "
                        "not repeat this invocation unchanged."
                    )
                )
                pending = self._pending_intent_review(
                    review_input,
                    intent=intent,
                    confirmation_transmission_state=("supplied" if transmitted else "not_supplied"),
                    awaiting_confirmation_fields=awaiting,
                )
                self._set_pending_intent_review(pending, summary=summary)
                return self._result(
                    operation="prepare_generation",
                    ok=True,
                    state=self.store.read(),
                    summary=summary,
                    elapsed=self.clock() - started,
                    category=category,
                    details={
                        "intent_confirmation_state": intent.get("confirmation_state"),
                        "confirmation_transmission_state": (
                            "supplied" if transmitted else "not_supplied"
                        ),
                        "awaiting_confirmation_fields": awaiting,
                        "confirmation_statement_supplied": bool(confirmation_assertion),
                        "working_blueprint_created": False,
                        "generation_context_created": False,
                        "protected_call_made": True,
                        "identical_pending_review_reused": False,
                    },
                    checkpoint_protocol={
                        "confirmation_transmission_state": (
                            "supplied" if transmitted else "not_supplied"
                        ),
                        "awaiting_confirmation_fields": awaiting,
                    },
                )
            intent_binding = decision_inventory_binding(intent)
            blueprint_payload = self._protected_call(
                "create_implementation_blueprint",
                {
                    "algorithm_intent_card": intent,
                    "intent_relationship": {
                        "relationship_type": "represented_by",
                        "parent_artifact_digest": _artifact_digest(intent),
                    },
                },
            )
            blueprint = self._response_artifact(blueprint_payload, "implementation_blueprint")
            output_contract = self._response_artifact(blueprint_payload, "output_evidence_contract")
            blueprint_binding = decision_inventory_binding(blueprint)
            if blueprint_binding != intent_binding:
                raise CurrentLoopError("blueprint_decision_inventory_continuity_mismatch")
            generation_arguments: dict[str, Any] = {
                "context_loop": CONTEXT_LOOP_GATE,
                "generation_posture": requested_posture,
                "implementation_blueprint": blueprint,
                "output_evidence_contract": output_contract,
            }
            if requested_posture == "exploratory_first_pass":
                generation_arguments.update(
                    {
                        "exploratory_authorization": True,
                        "exploratory_constraints": list(
                            dict.fromkeys([*constraints, *EXPLORATORY_FIXED_CONSTRAINTS])
                        ),
                        "exploratory_prohibitions": list(
                            dict.fromkeys([*non_goals, *EXPLORATORY_FIXED_PROHIBITIONS])
                        ),
                        "unresolved_assistant_choices": list(accepted_unresolved_choices),
                    }
                )
            generation_payload = self._protected_call(
                "create_generation_context_pack",
                generation_arguments,
            )
            context_status = generation_payload.get("context_status")
            coordinator = self._coordinator_state(self.store.read())
            coordinator.pop("pending_intent_review", None)
            coordinator["effective_generation_posture"] = requested_posture
            coordinator["canonical_decision_inventory"] = intent_binding
            if context_status == "generation_context_blocked_pending_decisions":
                if (
                    generation_payload.get("generation_context_pack") is not None
                    or generation_payload.get("generation_context_pack_produced") is not False
                    or not isinstance(
                        generation_payload.get("blueprint_readiness_summary"), Mapping
                    )
                ):
                    raise CurrentLoopError("protected_truth_insufficient")
                readiness = deepcopy(dict(generation_payload["blueprint_readiness_summary"]))
                if (
                    readiness.get("aggregate_readiness_result") != "blocked_pending_decisions"
                    or readiness.get("generation_context_eligibility") is not False
                ):
                    raise CurrentLoopError("protected_truth_insufficient")
                blockers, records = self._decision_resolution_details(
                    profile_id=profile_id,
                    blueprint=blueprint,
                    readiness=readiness,
                )
                if not blockers:
                    raise CurrentLoopError("protected_truth_insufficient")
                retained = [
                    self._save_pending_generation_artifact("algorithm-intent-card", intent),
                    self._save_pending_generation_artifact("working-blueprint", blueprint),
                    self._save_pending_generation_artifact(
                        "output-evidence-contract", output_contract
                    ),
                ]
                awaiting = [str(item["profile_decision_id"]) for item in blockers]
                pending_resolution = {
                    "input_digest": review_input_digest,
                    "profile_id": profile_id,
                    "interpretation_summary": (
                        proposed_interpretation.get("summary")
                        or proposed_interpretation.get("normalized_goal")
                        or "Reviewed interpretation"
                    ),
                    "profile_answers": deepcopy(dict(reviewed_profile_answers or {})),
                    "constraints": list(constraints),
                    "non_goals": list(non_goals),
                    "accepted_unresolved_choices": list(accepted_unresolved_choices),
                    "authorized_dispositions": deepcopy(normalized_dispositions),
                    "decision_records": deepcopy(records),
                    "blocking_decisions": blockers,
                    "blueprint_readiness_summary": readiness,
                    "awaiting_confirmation_fields": awaiting,
                    "retained_artifacts": retained,
                }
                summary = (
                    "Blueprint-guided generation is waiting only on the returned "
                    "generation-relevant decisions. Approve exact dispositions, defer, "
                    "or explicitly switch this attempt to exploratory first pass."
                )
                coordinator.update(
                    {
                        "phase": "intent_review",
                        "state_status": "checkpoint_required",
                        "checkpoint_kind": "decision_resolution",
                        "customer_summary": summary,
                        "pending_decision_resolution": pending_resolution,
                        "generation_context_outcome": {
                            "context_status": context_status,
                            "generation_context_pack_created": False,
                            "exploratory_generation_context_created": False,
                            "unresolved_decision_references": [
                                item["decision_ref"] for item in blockers
                            ],
                        },
                    }
                )
                self._replace_coordinator(coordinator)
                return self._result(
                    operation="prepare_generation",
                    ok=True,
                    state=self.store.read(),
                    summary=summary,
                    elapsed=self.clock() - started,
                    category=context_status,
                    details={
                        "intent_confirmed": True,
                        "confirmation_transmission_state": "confirmed",
                        "working_blueprint_retained": True,
                        "output_evidence_contract_retained": True,
                        "generation_context_pack_created": False,
                        "exploratory_generation_context_created": False,
                        "blueprint_readiness_summary": readiness,
                        "decision_resolution": blockers,
                        "decision_inventory": intent_binding,
                        "ide_write_or_run_authorized": False,
                    },
                    checkpoint_protocol={
                        "confirmation_transmission_state": "not_supplied",
                        "awaiting_confirmation_fields": awaiting,
                    },
                )

            self._save_generation_parent_artifact(
                "algorithm_intent_card",
                intent,
                "algorithm-intent-card.json",
            )
            self._save_generation_parent_artifact(
                "working_blueprint",
                blueprint,
                "working-blueprint.json",
            )
            self._save_generation_parent_artifact(
                "output_evidence_contract",
                output_contract,
                "output-evidence-contract.json",
            )
            coordinator = self._coordinator_state(self.store.read())
            generation_context_pack_created = False
            exploratory_context_created = False
            unresolved_decision_references: list[str] = []
            if context_status == "exploratory_generation_context_ready":
                if (
                    generation_payload.get("generation_context_pack") is not None
                    or generation_payload.get("generation_context_pack_produced") is not False
                ):
                    raise CurrentLoopError("protected_truth_insufficient")
                generation = self._response_artifact(
                    generation_payload, "exploratory_generation_context"
                )
                if (
                    generation.get("artifact_type") != "exploratory_generation_context"
                    or generation.get("non_governing") is not True
                ):
                    raise CurrentLoopError("protected_truth_insufficient")
                self._save_artifact(
                    "exploratory_generation_context",
                    generation,
                    "exploratory-generation-context.json",
                )
                exploratory_context_created = True
                records = unpack_decision_record_set(blueprint["blueprint_decision_records"])
                unresolved_decision_references = [
                    str(item["decision_ref"])
                    for item in records
                    if item.get("resolution_state") != "resolved"
                ]
                summary = (
                    "Exploratory generation context is ready for this bounded attempt. "
                    "A full Generation Context Pack does not exist, unresolved decisions "
                    "remain, and IDE write/run authority is still separate."
                )
            elif context_status == "generation_context_pack_ready":
                if generation_payload.get("generation_context_pack_produced") is not True:
                    raise CurrentLoopError("protected_truth_insufficient")
                generation = self._response_artifact(generation_payload, "generation_context_pack")
                self._save_artifact(
                    "generation_context_pack",
                    generation,
                    "generation-context-pack.json",
                )
                generation_context_pack_created = True
                summary = (
                    "The full Generation Context Pack is ready. Writing or running code "
                    "in the IDE is a separate user authority."
                )
            else:
                raise CurrentLoopError("protected_truth_insufficient")
            coordinator.pop("pending_decision_resolution", None)
            coordinator.update(
                {
                    "phase": "generation_ready",
                    "state_status": "checkpoint_required",
                    "checkpoint_kind": "ide_write_or_run",
                    "customer_summary": summary,
                    "generation_context_outcome": {
                        "context_status": context_status,
                        "generation_context_pack_created": generation_context_pack_created,
                        "exploratory_generation_context_created": exploratory_context_created,
                        "unresolved_decision_references": unresolved_decision_references,
                    },
                }
            )
            self._replace_coordinator(coordinator)
            return self._result(
                operation="prepare_generation",
                ok=True,
                state=self.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                details={
                    "intent_confirmed": True,
                    "confirmation_transmission_state": "confirmed",
                    "working_blueprint_created": True,
                    "output_evidence_contract_created": True,
                    "generation_context_created": True,
                    "context_status": context_status,
                    "generation_context_pack_created": generation_context_pack_created,
                    "exploratory_generation_context_created": exploratory_context_created,
                    "unresolved_decision_references": unresolved_decision_references,
                    "full_blueprint_readiness_claimed": generation_context_pack_created,
                    "decision_inventory": intent_binding,
                    "ide_write_or_run_authorized": False,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict, ValueError) as exc:
            return self._exception_result("prepare_generation", exc, started)

    def _replace_contract(
        self,
        contract: Mapping[str, Any],
        *,
        cancel_pending_for_narrowing: bool = False,
    ) -> dict[str, Any]:
        validate_contract(contract)
        state = self.store.read()

        def mutator(value: dict[str, Any]) -> Mapping[str, Any]:
            value["current_loop_contract"] = deepcopy(dict(contract))
            if cancel_pending_for_narrowing:
                issued = [
                    receipt_id
                    for receipt_id, receipt in value.get("operation_receipts", {}).items()
                    if isinstance(receipt, Mapping) and receipt.get("status") == "issued"
                ]
                for receipt_id in issued:
                    value["operation_receipts"].pop(receipt_id, None)
                coordinator = value.get("coordinator")
                staged_cancelled = False
                if isinstance(coordinator, dict):
                    pending = coordinator.get("pending_checkpoint_input")
                    staged_cancelled = (
                        isinstance(pending, Mapping) and pending.get("status") == "pending"
                    )
                    if staged_cancelled:
                        coordinator["pending_checkpoint_input"] = None
                        coordinator["state_status"] = "ready"
                        coordinator["checkpoint_kind"] = "none"
                        coordinator["customer_summary"] = (
                            "The narrower Current Loop Contract is effective. Pending work "
                            "was cancelled and must be reissued under the new ceiling."
                        )
                value["contract_narrowing_cancellation"] = {
                    "schema_id": "qcoder.current_loop.contract_narrowing_receipt.v1",
                    "schema_version": 1,
                    "contract_revision": contract["contract_revision"],
                    "pending_checkpoint_input_cancelled": staged_cancelled,
                    "issued_operation_receipts_cancelled": len(issued),
                    "prior_evidence_rewritten": False,
                    "future_use_follows_new_contract": True,
                }
            return value

        return self.store.update(mutator, expected_revision=int(state["state_revision"]))

    def contract_status(self) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self.store.read()
            validate_contract(state["current_loop_contract"])
            return self._result(
                operation="contract_status",
                ok=True,
                state=state,
                summary="The effective one-loop participation contract is shown.",
                elapsed=self.clock() - started,
                details={
                    "current_loop_contract": deepcopy(state["current_loop_contract"]),
                    "raw_policy_editing_permitted": False,
                    "yaml_authoritative": False,
                },
            )
        except (CurrentLoopError, CurrentLoopContractError) as exc:
            return self._exception_result("contract_status", exc, started)

    def open_contract_editor(self) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self.store.read()
            if state.get("activation_state") != "active":
                raise CurrentLoopError("contract_editor_requires_active_loop")
            from qcoder.current_loop_contract_sidecar import (
                launch_sidecar_process,
                sidecar_contract_snapshot,
            )

            launched = launch_sidecar_process(
                workspace=self.workspace_root,
                runtime_executable=self.runtime_executable,
            )
            return self._result(
                operation="open_contract_editor",
                ok=True,
                state=state,
                summary=(
                    "The optional loop-bound local contract editor is ready. "
                    "Ordinary work can continue entirely in the IDE."
                ),
                elapsed=self.clock() - started,
                details={
                    "sidecar_contract": sidecar_contract_snapshot(),
                    "sidecar_session": launched,
                    "current_contract_revision": state["current_loop_contract"][
                        "contract_revision"
                    ],
                    "local_only": True,
                    "hosted_operation_permitted": False,
                    "credential_values_included": False,
                    "browser_optional": True,
                    "automatic_browser_opened": False,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict, RuntimeError, OSError) as exc:
            return self._exception_result("open_contract_editor", exc, started)

    def _prepare_run_summary_on_request(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """Prepare from one exact registered result path; never discover a file."""

        if state.get("run_summary_index"):
            return deepcopy(dict(state))
        if "result_manifestation" not in state.get("saved_artifacts", {}):
            return deepcopy(dict(state))
        if not contract_permits(
            state["current_loop_contract"],
            category="result_manifestation",
            dimension="derive",
        ):
            raise CurrentLoopError("current_loop_contract_derivation_prohibited")
        authorization = state.get("artifact_authorization")
        if not isinstance(authorization, Mapping) or authorization.get("state") != "approved":
            return deepcopy(dict(state))
        result_item = next(
            (
                item
                for item in authorization.get("items", [])
                if isinstance(item, Mapping) and item.get("artifact_role") == "results"
            ),
            None,
        )
        if not isinstance(result_item, Mapping):
            return deepcopy(dict(state))
        path = Path(str(result_item.get("local_path") or "")).absolute()
        if not path.is_file() or path.is_symlink():
            raise CurrentLoopError("selected_file_missing")
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != result_item.get("content_digest"):
            raise CurrentLoopError("selected_file_changed")
        payload = _load_json_file(path)
        payload = payload if "counts" in payload else {"counts": payload}
        summary = build_run_summary(
            loop_ref=str(state["loop_ref"]),
            workspace_binding=str(state["workspace_root"]),
            state_revision=int(state["state_revision"]),
            contract_revision=int(state["current_loop_contract"]["contract_revision"]),
            result_payload=payload,
            result_manifestation=self._saved_artifact(state, "result_manifestation"),
            circuit_manifestation=(
                self._saved_artifact(state, "circuit_manifestation")
                if "circuit_manifestation" in state["saved_artifacts"]
                else None
            ),
            source_manifestation=(
                self._saved_artifact(state, "python_manifestation")
                if "python_manifestation" in state["saved_artifacts"]
                else None
            ),
            operation_lineage={
                "status": (
                    "recorded"
                    if result_item.get("operation_receipt_id") is not None
                    else "exact_artifact_authorization_fallback"
                ),
                "operation_receipt_id": result_item.get("operation_receipt_id"),
                "activity_digest": None,
            },
        )
        save_run_summary(
            store=self.store,
            summary=summary,
            destination=self.artifact_directory / f"{summary['artifact_ref']}.json",
            expected_revision=int(state["state_revision"]),
        )
        return self.store.read()

    def evidence_view(
        self,
        *,
        view_id: str,
        selected_run_reference: str | None = None,
        destination: str = "connected_assistant",
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            if view_id not in EVIDENCE_VIEW_IDS:
                return self._bounded_control_rejection(
                    operation="evidence_view",
                    category="evidence_view_invalid",
                    field_name="view_id",
                    received=view_id,
                    started=started,
                )
            state = self.store.read()
            state = self._prepare_run_summary_on_request(state)
            summaries = read_run_summaries(state)
            exclusions = set(state["current_loop_contract"]["evidence_exclusions"])
            eligible = [
                summary
                for summary in summaries
                if summary["artifact_ref"] not in exclusions
                and summary["result_evidence_reference"] not in exclusions
            ]
            limitations: list[str] = []
            if state["current_loop_contract"].get("dependent_views_stale"):
                limitations.append(
                    "One or more evidence changes make dependent views stale or incomplete."
                )
            if exclusions:
                limitations.append(
                    "Excluded evidence is unavailable to future summaries and views."
                )
            circuit = (
                self._saved_artifact(state, "circuit_manifestation")
                if "circuit_manifestation" in state["saved_artifacts"]
                and state["saved_artifacts"]["circuit_manifestation"]["artifact_reference"]
                not in exclusions
                else None
            )
            baseline_reference = (
                state["saved_artifacts"]["request_baseline"]["artifact_reference"]
                if "request_baseline" in state["saved_artifacts"]
                else None
            )
            view = build_evidence_view(
                view_id=view_id,
                contract=state["current_loop_contract"],
                run_summaries=eligible,
                circuit_manifestation=circuit,
                baseline_reference=baseline_reference,
                evidence_limitations=limitations,
                selected_run_reference=selected_run_reference,
                destination=destination,
            )
            return self._result(
                operation="evidence_view",
                ok=True,
                state=state,
                summary="The bounded current-loop evidence view is ready.",
                elapsed=self.clock() - started,
                details={
                    "evidence_view": view,
                    "view_contract": evidence_view_contract_snapshot(),
                    "run_summary_contract": run_summary_contract_snapshot(),
                    "eligible_run_references": [summary["artifact_ref"] for summary in eligible],
                    "arbitrary_query_text_accepted": False,
                    "project_file_discovery_performed": False,
                },
            )
        except (
            CurrentLoopError,
            CurrentLoopConflict,
            CurrentLoopContractError,
            RunSummaryError,
            OSError,
            ValueError,
        ) as exc:
            return self._exception_result("evidence_view", exc, started)

    def _bounded_control_rejection(
        self,
        *,
        operation: str,
        category: str,
        field_name: str,
        received: object,
        started: float,
    ) -> dict[str, Any]:
        try:
            state = self.store.read()
            contract = bounded_contract_for_operation(
                state,
                operation=operation,
                artifact_directory=self.artifact_directory,
            )
        except CurrentLoopError:
            contract = None
        expected = None
        if isinstance(contract, Mapping):
            expected = next(
                (
                    deepcopy(dict(item))
                    for item in contract.get("fields", [])
                    if isinstance(item, Mapping) and item.get("name") == field_name
                ),
                None,
            )
        safe_value = (
            received
            if isinstance(received, str)
            and len(received) <= 64
            and received.replace("_", "").replace("-", "").isalnum()
            else None
        )
        received_bytes = (
            str(received).encode("utf-8")
            if isinstance(received, (str, int, float, bool))
            else type(received).__name__.encode("utf-8")
        )
        return self._recovery_result(
            operation=operation,
            category=category,
            phase=self._safe_phase(),
            elapsed=self.clock() - started,
            details={
                "bounded_control_rejection": {
                    "schema_id": "qcoder.current_loop.bounded_control_rejection.v1",
                    "error_category": category,
                    "operation": operation,
                    "field_name": field_name,
                    "expected_field_contract": expected,
                    "received_type": type(received).__name__,
                    "received_bounded_value": safe_value,
                    "received_utf8_sha256": sha256(received_bytes).hexdigest(),
                    "current_contract_revision": (
                        contract.get("contract_revision") if isinstance(contract, Mapping) else None
                    ),
                    "assistant_should_stop_or_recover": "recover",
                    "hosted_operation_permitted": False,
                    "raw_policy_or_evidence_echoed": False,
                    "fresh_bounded_control_contract_required": True,
                }
            },
        )

    def contract_set_preset(
        self, *, preset: str, expected_contract_revision: int
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self.store.read()
            outcome = set_contract_preset(
                state["current_loop_contract"],
                preset=preset,
                expected_contract_revision=expected_contract_revision,
                provenance=(
                    "customer_requested_narrowing"
                    if preset == "evidence_only"
                    else "explicit_customer_selection"
                ),
            )
            updated = self._replace_contract(
                outcome["contract"],
                cancel_pending_for_narrowing=outcome["disposition"] == "narrowing",
            )
            broadening = outcome["disposition"] == "broadening"
            return self._result(
                operation="contract_set_preset",
                ok=True,
                state=updated,
                summary=(
                    "The broader contract is proposed and requires explicit approval."
                    if broadening
                    else "The narrower contract is effective immediately."
                ),
                elapsed=self.clock() - started,
                category="contract_broadening_proposed" if broadening else None,
                details={
                    "disposition": outcome["disposition"],
                    "pending_proposal": deepcopy(outcome["proposal"]),
                    "current_loop_contract": deepcopy(outcome["contract"]),
                    "previously_exposed_information_recallable": False,
                },
            )
        except CurrentLoopContractError as exc:
            if exc.category == "contract_preset_invalid":
                return self._bounded_control_rejection(
                    operation="contract_set_preset",
                    category=exc.category,
                    field_name="preset",
                    received=preset,
                    started=started,
                )
            return self._exception_result("contract_set_preset", exc, started)
        except (CurrentLoopError, CurrentLoopConflict) as exc:
            return self._exception_result("contract_set_preset", exc, started)

    def contract_adjust(
        self,
        *,
        category: str,
        dimension: str,
        value: str,
        expected_contract_revision: int,
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self.store.read()
            outcome = adjust_contract(
                state["current_loop_contract"],
                category=category,
                dimension=dimension,
                value=value,
                expected_contract_revision=expected_contract_revision,
                provenance="explicit_customer_selection",
            )
            updated = self._replace_contract(
                outcome["contract"],
                cancel_pending_for_narrowing=outcome["disposition"] == "narrowing",
            )
            broadening = outcome["disposition"] == "broadening"
            return self._result(
                operation="contract_adjust",
                ok=True,
                state=updated,
                summary=(
                    "The broader bounded change awaits explicit approval."
                    if broadening
                    else "The bounded narrowing is effective immediately."
                ),
                elapsed=self.clock() - started,
                category="contract_broadening_proposed" if broadening else None,
                details={
                    "disposition": outcome["disposition"],
                    "pending_proposal": deepcopy(outcome["proposal"]),
                    "current_loop_contract": deepcopy(outcome["contract"]),
                },
            )
        except CurrentLoopContractError as exc:
            field_name = {
                "contract_category_invalid": "category",
                "contract_dimension_invalid": "dimension",
                "contract_adjustment_value_invalid": "value",
                "contract_raw_exposure_ceiling": "value",
            }.get(exc.category)
            if field_name is not None:
                return self._bounded_control_rejection(
                    operation="contract_adjust",
                    category=exc.category,
                    field_name=field_name,
                    received={
                        "category": category,
                        "dimension": dimension,
                        "value": value,
                    }[field_name],
                    started=started,
                )
            return self._exception_result("contract_adjust", exc, started)
        except (CurrentLoopError, CurrentLoopConflict) as exc:
            return self._exception_result("contract_adjust", exc, started)

    def contract_confirm_broadening(
        self, *, expected_contract_revision: int, explicit_authority: bool
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self.store.read()
            contract = confirm_broadening(
                state["current_loop_contract"],
                expected_contract_revision=expected_contract_revision,
                explicit_authority=explicit_authority,
            )
            updated = self._replace_contract(contract)
            return self._result(
                operation="contract_confirm_broadening",
                ok=True,
                state=updated,
                summary="The explicitly approved broader contract is effective.",
                elapsed=self.clock() - started,
                details={
                    "current_loop_contract": deepcopy(contract),
                    "authority_only": True,
                    "raw_policy_retransmitted": False,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict, CurrentLoopContractError) as exc:
            return self._exception_result("contract_confirm_broadening", exc, started)

    def _evidence_descriptor(
        self, state: Mapping[str, Any], reference: str
    ) -> tuple[str, dict[str, Any]]:
        for role, descriptor in state.get("saved_artifacts", {}).items():
            if (
                isinstance(descriptor, Mapping)
                and descriptor.get("artifact_reference") == reference
            ):
                return str(role), deepcopy(dict(descriptor))
        summary = state.get("run_summary_index", {}).get(reference)
        if isinstance(summary, Mapping):
            return "run_summary", deepcopy(dict(summary))
        raise CurrentLoopError("contract_evidence_reference_unknown")

    def _mark_dependent_run_summaries_stale(
        self, *, source_reference: str, reason: str
    ) -> dict[str, Any]:
        state = self.store.read()
        for summary in read_run_summaries(state):
            bindings = summary.get("evidence_bindings", [])
            if source_reference != summary.get("artifact_ref") and not any(
                isinstance(binding, Mapping)
                and binding.get("artifact_reference") == source_reference
                for binding in bindings
            ):
                continue
            stale = mark_run_summary_stale(summary, reasons=[reason])
            replace_run_summary(
                store=self.store,
                summary=stale,
                expected_revision=int(state["state_revision"]),
            )
            state = self.store.read()
        return state

    def _refresh_dependent_run_summaries(self, *, restored_reference: str) -> dict[str, Any]:
        state = self.store.read()
        saved_by_reference = {
            str(descriptor["artifact_reference"]): descriptor
            for descriptor in state.get("saved_artifacts", {}).values()
            if isinstance(descriptor, Mapping)
            and isinstance(descriptor.get("artifact_reference"), str)
        }
        for summary in read_run_summaries(state):
            related = restored_reference == summary.get("artifact_ref") or any(
                isinstance(binding, Mapping)
                and binding.get("artifact_reference") == restored_reference
                for binding in summary.get("evidence_bindings", [])
            )
            if not related:
                continue
            bindings_valid = all(
                isinstance(binding, Mapping)
                and isinstance(
                    saved_by_reference.get(str(binding.get("artifact_reference"))),
                    Mapping,
                )
                and saved_by_reference[str(binding["artifact_reference"])].get("artifact_digest")
                == binding.get("artifact_digest")
                for binding in summary.get("evidence_bindings", [])
            )
            if not bindings_valid:
                continue
            refreshed = mark_run_summary_fresh(summary)
            replace_run_summary(
                store=self.store,
                summary=refreshed,
                expected_revision=int(state["state_revision"]),
            )
            state = self.store.read()
        return state

    def evidence_exclude(
        self,
        *,
        artifact_reference: str,
        reason: str,
        expected_contract_revision: int,
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self.store.read()
            _role, descriptor = self._evidence_descriptor(state, artifact_reference)
            contract = contract_exclude_evidence(
                state["current_loop_contract"],
                artifact_reference=artifact_reference,
                artifact_digest=str(descriptor["artifact_digest"]),
                reason=reason,
                expected_contract_revision=expected_contract_revision,
            )
            updated = self._replace_contract(contract)
            updated = self._mark_dependent_run_summaries_stale(
                source_reference=artifact_reference,
                reason="source_evidence_excluded",
            )
            return self._result(
                operation="evidence_exclude",
                ok=True,
                state=updated,
                summary="The selected qCoder evidence is excluded from future use.",
                elapsed=self.clock() - started,
                details={"artifact_reference": artifact_reference, "dependent_views_stale": True},
            )
        except CurrentLoopContractError as exc:
            if exc.category == "contract_evidence_exclusion_reason_invalid":
                return self._bounded_control_rejection(
                    operation="evidence_exclude",
                    category=exc.category,
                    field_name="reason",
                    received=reason,
                    started=started,
                )
            return self._exception_result("evidence_exclude", exc, started)
        except CurrentLoopError as exc:
            if exc.category == "contract_evidence_reference_unknown":
                return self._bounded_control_rejection(
                    operation="evidence_exclude",
                    category=exc.category,
                    field_name="artifact_reference",
                    received=artifact_reference,
                    started=started,
                )
            return self._exception_result("evidence_exclude", exc, started)
        except CurrentLoopConflict as exc:
            return self._exception_result("evidence_exclude", exc, started)

    def evidence_restore(
        self, *, artifact_reference: str, expected_contract_revision: int
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self.store.read()
            _role, descriptor = self._evidence_descriptor(state, artifact_reference)
            contract = contract_restore_evidence(
                state["current_loop_contract"],
                artifact_reference=artifact_reference,
                artifact_digest=str(descriptor["artifact_digest"]),
                expected_contract_revision=expected_contract_revision,
            )
            updated = self._replace_contract(contract)
            updated = self._refresh_dependent_run_summaries(restored_reference=artifact_reference)
            return self._result(
                operation="evidence_restore",
                ok=True,
                state=updated,
                summary="The exact still-valid qCoder evidence is restored.",
                elapsed=self.clock() - started,
                details={"artifact_reference": artifact_reference, "explicit_restore": True},
            )
        except (CurrentLoopError, CurrentLoopConflict, CurrentLoopContractError) as exc:
            category = getattr(exc, "category", "")
            if category in {
                "contract_evidence_reference_unknown",
                "contract_evidence_exclusion_missing",
            }:
                return self._bounded_control_rejection(
                    operation="evidence_restore",
                    category=str(category),
                    field_name="artifact_reference",
                    received=artifact_reference,
                    started=started,
                )
            return self._exception_result("evidence_restore", exc, started)

    def evidence_delete(
        self,
        *,
        artifact_reference: str,
        expected_contract_revision: int,
        explicit_authority: bool,
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            if explicit_authority is not True:
                raise CurrentLoopError("contract_evidence_delete_authority_required")
            state = self.store.read()
            role, descriptor = self._evidence_descriptor(state, artifact_reference)
            path = Path(str(descriptor.get("local_path", ""))).absolute()
            if not path.is_file() or not path.is_relative_to(self.artifact_directory):
                raise CurrentLoopError("contract_evidence_not_locally_controlled")
            path.unlink()
            contract = contract_record_deletion(
                state["current_loop_contract"],
                artifact_reference=artifact_reference,
                artifact_digest=str(descriptor["artifact_digest"]),
                artifact_role=role,
                expected_contract_revision=expected_contract_revision,
            )
            state = self.store.read()

            def mutator(value: dict[str, Any]) -> Mapping[str, Any]:
                value["current_loop_contract"] = contract
                if role == "run_summary":
                    value["run_summary_index"].pop(artifact_reference, None)
                    if value.get("latest_run_summary_reference") == artifact_reference:
                        value["latest_run_summary_reference"] = None
                else:
                    value["saved_artifacts"].pop(role, None)
                return value

            updated = self.store.update(mutator, expected_revision=state["state_revision"])
            if role != "run_summary":
                updated = self._mark_dependent_run_summaries_stale(
                    source_reference=artifact_reference,
                    reason="source_evidence_deleted",
                )
            return self._result(
                operation="evidence_delete",
                ok=True,
                state=updated,
                summary="The locally controlled qCoder evidence was deleted.",
                elapsed=self.clock() - started,
                details={
                    "artifact_reference": artifact_reference,
                    "project_file_deleted": False,
                    "raw_content_retained_in_tombstone": False,
                },
            )
        except (
            CurrentLoopError,
            CurrentLoopConflict,
            CurrentLoopContractError,
            OSError,
        ) as exc:
            category = getattr(exc, "category", "")
            if category in {
                "contract_evidence_reference_unknown",
                "contract_evidence_not_locally_controlled",
            }:
                return self._bounded_control_rejection(
                    operation="evidence_delete",
                    category=str(category),
                    field_name="artifact_reference",
                    received=artifact_reference,
                    started=started,
                )
            return self._exception_result("evidence_delete", exc, started)

    def record_ide_authority(
        self,
        *,
        allowed: bool,
        explicit_user_action: bool,
        operation_category: str = "ide_write",
        output_role_ceiling: Sequence[str] = ("source", "circuit_qasm", "results"),
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self._require_phase(
                "record_ide_authority",
                {"activated", "generation_ready", "awaiting_local_artifacts"},
            )
            if not explicit_user_action or not allowed:
                return self._recovery_result(
                    operation="record_ide_authority",
                    category="ide_write_or_run_denied",
                    phase=self._coordinator_state(state)["phase"],
                    elapsed=self.clock() - started,
                )
            coordinator = self._coordinator_state(state)
            receipt = issue_operation_receipt(
                loop_ref=str(state["loop_ref"]),
                workspace_binding=str(state["workspace_root"]),
                state_revision=int(state["state_revision"]),
                operation_category=operation_category,
                output_role_ceiling=output_role_ceiling,
            )

            def receipt_mutator(value: dict[str, Any]) -> Mapping[str, Any]:
                value["operation_receipts"][receipt["receipt_id"]] = receipt
                return value

            state = self.store.update(
                receipt_mutator,
                expected_revision=int(state["state_revision"]),
            )
            coordinator = self._coordinator_state(state)
            coordinator.update(
                {
                    "phase": "awaiting_local_artifacts",
                    "state_status": "ready",
                    "checkpoint_kind": "none",
                    "customer_summary": (
                        "The IDE host recorded its separate write or run authority. "
                        "Perform only the authorized IDE work, retain exact paths returned "
                        "by write or modify operations, and register those exact paths. "
                        "qCoder artifact review is still not authorized."
                    ),
                }
            )
            coordinator["authority_separation"]["ide_write_or_run"] = "owned_by_ide_host_not_qcoder"
            self._replace_coordinator(coordinator)
            return self._result(
                operation="record_ide_authority",
                ok=True,
                state=self.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                details={
                    "artifact_review_authorized": False,
                    "ide_authority_recorded": True,
                    "artifact_path_source": (
                        "exact_ide_operation_result_or_explicit_user_selection"
                    ),
                    "directory_orientation_required": False,
                    "candidate_discovery_permitted": False,
                    "qcoder_local_state_access_permitted": False,
                    "operation_receipt": deepcopy(receipt),
                },
            )
        except (CurrentLoopError, CurrentLoopConflict, EventReceiptError) as exc:
            return self._exception_result("record_ide_authority", exc, started)

    def register_artifacts(
        self,
        *,
        candidates: Sequence[Mapping[str, Any]],
        operation_receipt_id: str | None = None,
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self._require_phase(
                "register_artifacts",
                {
                    "activated",
                    "generation_ready",
                    "awaiting_local_artifacts",
                    "artifact_authorization",
                    "evidence_processing",
                },
            )
            coordinator = self._coordinator_state(state)
            normalized = self._normalize_candidates(candidates)
            format_outcomes: list[dict[str, Any]] = []
            eligible_candidates: list[dict[str, Any]] = []
            for item in normalized:
                if operation_receipt_id is not None:
                    name = Path(str(item["path"])).name.casefold()
                    if any(marker in name for marker in (".env", "secret", "credential", "token")):
                        raise CurrentLoopError(
                            "operation_receipt_sensitive_output_requires_selection"
                        )
                provenance = (
                    "customer_selected_exact_artifact"
                    if item["provenance"] == "user_selected"
                    else "assistant_operation_receipt"
                )
                outcome = registration_format_outcome(
                    path=Path(str(item["path"])),
                    role=str(item["role"]),
                    provenance=provenance,
                )
                item["detected_format"] = outcome["detected_format"]
                item["format_contract_schema_id"] = ARTIFACT_FORMAT_CONTRACT_SCHEMA_ID
                format_outcomes.append(outcome)
                if operation_receipt_id is None or outcome["automatic_registration_supported"]:
                    eligible_candidates.append(item)
            normalized = eligible_candidates
            if not normalized:
                raise EvidenceProcessingError(
                    "artifact_format_unsupported",
                    origin="local_artifact_validation",
                    safe_details={
                        "registration_outcomes": format_outcomes,
                        "artifact_format_contract": artifact_format_contract_snapshot(),
                    },
                )
            activity_receipt = None
            category_by_role = {
                "source": "python_manifestation",
                "circuit_qasm": "circuit_manifestation",
                "results": "result_manifestation",
            }
            for item in normalized:
                self._require_contract_permission(
                    state,
                    category=category_by_role[str(item["role"])],
                    dimension="collect",
                )
            if operation_receipt_id is not None:
                receipt = state.get("operation_receipts", {}).get(operation_receipt_id)
                if not isinstance(receipt, Mapping):
                    raise CurrentLoopError("operation_receipt_missing")
                for item in normalized:
                    validate_operation_receipt(
                        receipt,
                        loop_ref=str(state["loop_ref"]),
                        workspace_binding=str(state["workspace_root"]),
                        current_state_revision=int(state["state_revision"]),
                        role=str(item["role"]),
                        detected_format=str(item["detected_format"]),
                    )
                    if not contract_permits(
                        state["current_loop_contract"],
                        category=category_by_role[str(item["role"])],
                        dimension="collect",
                    ):
                        raise CurrentLoopError("current_loop_contract_collection_prohibited")
                    name = Path(str(item["path"])).name.casefold()
                    if any(marker in name for marker in (".env", "secret", "credential", "token")):
                        raise CurrentLoopError(
                            "operation_receipt_sensitive_output_requires_selection"
                        )
                    raw = Path(str(item["path"])).read_bytes()
                    if len(raw) > 8 * 1024 * 1024:
                        raise CurrentLoopError("artifact_candidate_file_too_large")
                    item["content_digest"] = sha256(raw).hexdigest()
                    item["operation_receipt_id"] = operation_receipt_id
                consumed, activity_receipt = consume_operation_receipt(
                    receipt,
                    registered_artifacts=normalized,
                    consumed_state_revision=int(state["state_revision"]) + 1,
                )

                def consume_mutator(value: dict[str, Any]) -> Mapping[str, Any]:
                    value["operation_receipts"][operation_receipt_id] = consumed
                    value["activity_receipts"].append(activity_receipt)
                    return value

                state = self.store.update(
                    consume_mutator,
                    expected_revision=int(state["state_revision"]),
                )
                coordinator = self._coordinator_state(state)
            merged, added_count = self._merge_artifact_candidates(
                coordinator.get("artifact_candidates", []),
                normalized,
            )
            current_authorization = state.get("artifact_authorization")
            if (
                added_count == 0
                and coordinator["phase"] == "artifact_authorization"
                and isinstance(current_authorization, Mapping)
                and current_authorization.get("state") == "proposed"
            ):
                visible = self._visible_candidate_set(merged)
                return self._result(
                    operation="register_artifacts",
                    ok=True,
                    state=state,
                    summary=coordinator["customer_summary"],
                    elapsed=self.clock() - started,
                    details={
                        "proposed_set": visible,
                        "visible_candidate_set": visible,
                        "candidate_actions": [
                            "approve_all",
                            "remove_one",
                            "add_one_explicitly",
                            "decline",
                        ],
                        "registered_candidate_count": len(merged),
                        "new_candidate_count": 0,
                        "idempotent_registration": True,
                        "review_authorized": False,
                        "registration_authorizes_review": False,
                        "directory_scanned": False,
                        "candidate_discovery_performed": False,
                        "qcoder_local_state_accessed": False,
                        "raw_file_contents_included": False,
                    },
                )
            authorization = propose_selected_artifact_authorization(
                loop_ref=state["loop_ref"],
                proposed_artifacts=[
                    {
                        "artifact_role": item["role"],
                        "artifact_type": item["artifact_type"],
                        "local_path": item["path"],
                    }
                    for item in merged
                ],
            )
            state = set_artifact_authorization(
                store=self.store,
                authorization=authorization,
                expected_revision=state["state_revision"],
            )
            coordinator = self._coordinator_state(state)
            coordinator.update(
                {
                    "phase": "artifact_authorization",
                    "state_status": "checkpoint_required",
                    "checkpoint_kind": "artifact_review",
                    "customer_summary": (
                        "Review these current-build artifacts locally? Writing or "
                        "running code is separate from letting qCoder inspect them."
                    ),
                    "artifact_candidates": merged,
                    "evidence_processing_complete": False,
                }
            )
            self._replace_coordinator(coordinator)
            return self._result(
                operation="register_artifacts",
                ok=True,
                state=self.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                details={
                    "proposed_set": self._visible_candidate_set(merged),
                    "visible_candidate_set": self._visible_candidate_set(merged),
                    "candidate_actions": [
                        "approve_all",
                        "remove_one",
                        "add_one_explicitly",
                        "decline",
                    ],
                    "registered_candidate_count": len(merged),
                    "new_candidate_count": added_count,
                    "idempotent_registration": added_count == 0,
                    "review_authorized": False,
                    "registration_authorizes_review": False,
                    "directory_scanned": False,
                    "candidate_discovery_performed": False,
                    "qcoder_local_state_accessed": False,
                    "raw_file_contents_included": False,
                    "operation_receipt_consumed": operation_receipt_id is not None,
                    "activity_receipt": deepcopy(activity_receipt),
                    "registration_outcomes": format_outcomes,
                    "artifact_format_contract": artifact_format_contract_snapshot(),
                },
            )
        except (
            CurrentLoopError,
            CurrentLoopConflict,
            CurrentLoopContractError,
            EventReceiptError,
            EvidenceProcessingError,
            ValueError,
        ) as exc:
            return self._exception_result("register_artifacts", exc, started)

    def authorize_artifacts(
        self,
        *,
        action: str,
        explicit_action_provenance: str,
        selected_path: str | Path | None = None,
        artifact_role: str | None = None,
        artifact_type: str | None = None,
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self._require_phase("authorize_artifacts", {"artifact_authorization"})
            authorization = state.get("artifact_authorization")
            if not isinstance(authorization, Mapping):
                raise CurrentLoopError("selected_artifact_authorization_missing")
            coordinator = self._coordinator_state(state)
            candidates = [
                deepcopy(dict(item))
                for item in coordinator.get("artifact_candidates", [])
                if isinstance(item, Mapping)
            ]
            normalized_added: dict[str, Any] | None = None
            if action == "add_one_explicitly":
                if selected_path is None or artifact_role is None:
                    raise CurrentLoopError("selected_artifact_add_invalid")
                normalized_added = self._normalize_candidates(
                    [
                        {
                            "path": selected_path,
                            "role": artifact_role,
                            "artifact_type": artifact_type or artifact_role,
                            "provenance": "user_selected",
                            "explicit_external": False,
                        }
                    ]
                )[0]
                selected_path = normalized_added["path"]
            updated_authorization = update_selected_artifact_authorization(
                authorization,
                action=action,
                explicit_action_provenance=explicit_action_provenance,
                selected_path=selected_path,
                artifact_role=artifact_role,
                artifact_type=artifact_type,
            )
            state = set_artifact_authorization(
                store=self.store,
                authorization=updated_authorization,
                expected_revision=state["state_revision"],
            )
            coordinator = self._coordinator_state(state)
            authorized_paths = {
                str(item["local_path"])
                for item in updated_authorization["items"]
                if isinstance(item, Mapping)
            }
            if normalized_added is not None:
                candidates, _ = self._merge_artifact_candidates(
                    candidates,
                    [normalized_added],
                )
            candidates = [item for item in candidates if str(item.get("path")) in authorized_paths]
            coordinator["artifact_candidates"] = candidates
            if updated_authorization["state"] == "approved":
                coordinator.update(
                    {
                        "phase": "evidence_processing",
                        "state_status": "ready",
                        "checkpoint_kind": "none",
                        "customer_summary": (
                            "The exact visible artifact set is approved for local "
                            "qCoder inspection."
                        ),
                        "evidence_processing_complete": False,
                    }
                )
                category = None
            elif updated_authorization["state"] == "declined":
                coordinator.update(
                    {
                        "phase": "awaiting_local_artifacts",
                        "state_status": "ready",
                        "checkpoint_kind": "none",
                        "customer_summary": (
                            "Artifact review was declined. qCoder did not inspect the files."
                        ),
                        "evidence_processing_complete": False,
                    }
                )
                coordinator["artifact_candidates"] = []
                category = "authorization_declined"
            else:
                coordinator.update(
                    {
                        "phase": "artifact_authorization",
                        "state_status": "checkpoint_required",
                        "checkpoint_kind": "artifact_review",
                        "customer_summary": (
                            "The changed artifact set still needs explicit approval."
                        ),
                        "evidence_processing_complete": False,
                    }
                )
                category = "authorization_partial"
            self._replace_coordinator(coordinator)
            projection = share_safe_artifact_authorization_projection(updated_authorization)
            return self._result(
                operation="authorize_artifacts",
                ok=True,
                state=self.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                category=category,
                details={
                    "authorization_state": updated_authorization["state"],
                    "share_safe_projection": projection,
                    "visible_candidate_set": self._visible_candidate_set(
                        coordinator["artifact_candidates"]
                    ),
                    "registration_authorizes_review": False,
                    "paths_transmitted": False,
                    "ide_write_or_run_implied": False,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict) as exc:
            return self._exception_result("authorize_artifacts", exc, started)

    def process_authorized_artifacts(self) -> dict[str, Any]:
        """Derive each authorized artifact locally and independently.

        This operation is deliberately incapable of calling Protected. Optional
        hosted enrichment is a later, separately generated invocation.
        """

        started = self.clock()
        extraction_started = self.clock()
        try:
            state = self._require_phase("process_authorized_artifacts", {"evidence_processing"})
            authorization = state.get("artifact_authorization")
            if not isinstance(authorization, Mapping) or authorization.get("state") != "approved":
                raise CurrentLoopError("selected_artifact_authorization_required")
            freshness = check_current_loop_freshness(
                store=self.store, expected_revision=state["state_revision"]
            )
            if not freshness["fresh"]:
                first = freshness["events"][0]["category"]
                category = _ERROR_ALIASES.get(first, "selected_file_stale")
                return self._recovery_result(
                    operation="process_authorized_artifacts",
                    category=category,
                    phase="evidence_processing",
                    elapsed=self.clock() - started,
                    origin="local_artifact_validation",
                )
            extracted_roles: list[str] = []
            outcomes: list[dict[str, Any]] = []
            run_summary_payload: dict[str, Any] | None = None
            run_summary_lineage: dict[str, Any] | None = None
            for item in authorization["items"]:
                path = Path(item["local_path"])
                role = str(item["artifact_role"])
                content_digest = str(item["content_digest"])
                detected_format = "unknown"
                category_by_role = {
                    "source": "python_manifestation",
                    "circuit_qasm": "circuit_manifestation",
                    "results": "result_manifestation",
                }
                category = category_by_role.get(role)
                if category is None:
                    outcomes.append(
                        processing_outcome(
                            role=role,
                            content_digest=content_digest,
                            detected_format="unsupported",
                            status="failed_local",
                            safe_error_category="unsupported_authorized_artifact_type",
                        )
                    )
                    continue
                try:
                    self._require_contract_permission(
                        self.store.read(),
                        category=category,
                        dimension="derive",
                    )
                    detected_format = detect_exact_artifact_format(path, role)
                    if role == "source":
                        if detected_format != "python_source":
                            raise EvidenceProcessingError(
                                "artifact_format_unsupported",
                                origin="local_source_derivation",
                            )
                        source = extract_selected_python_file_evidence(
                            path,
                            logical_source_label=path.name,
                        )
                        self._save_artifact("source_evidence", source, "source-evidence.json")
                        manifestation = self._python_manifestation(source)
                        self._save_artifact(
                            "python_manifestation",
                            manifestation,
                            "python-manifestation.json",
                        )
                        roles = ["source_evidence", "python_manifestation"]
                    elif role == "circuit_qasm":
                        if detected_format != "openqasm_2":
                            raise EvidenceProcessingError(
                                "circuit_format_unsupported",
                                origin="local_circuit_derivation",
                                safe_details={
                                    "detected_format": detected_format,
                                    "supported_formats": ["openqasm_2"],
                                },
                            )
                        circuit = build_circuit_manifestation(
                            qasm_text=path.read_text(encoding="utf-8"),
                            stage="logical_circuit",
                        )
                        self._save_artifact(
                            "circuit_manifestation",
                            circuit,
                            "circuit-manifestation.json",
                        )
                        roles = ["circuit_manifestation"]
                    else:
                        if detected_format != "qcoder_result_json":
                            raise EvidenceProcessingError(
                                "artifact_format_unsupported",
                                origin="local_result_derivation",
                            )
                        result_input = _load_json_file(path)
                        current_state = self.store.read()
                        try:
                            related_ref = self._related_circuit_reference(current_state, path)
                            circuit_available = True
                        except CurrentLoopError:
                            related_ref = (
                                "session-artifact-"
                                + sha256(f"unavailable:{content_digest}".encode()).hexdigest()[:16]
                            )
                            circuit_available = False
                        if (
                            result_input.get("status") == "failed"
                            or result_input.get("run_status") == "failed"
                        ):
                            result = self._failed_result_manifestation(
                                related_circuit_ref=related_ref,
                                safe_category=str(
                                    result_input.get("error_category") or "local_run_failed"
                                ),
                            )
                        else:
                            counts_value = result_input.get("counts", result_input)
                            if not isinstance(counts_value, Mapping):
                                raise EvidenceProcessingError(
                                    "result_artifact_invalid",
                                    origin="local_result_derivation",
                                )
                            counts = {str(key): int(value) for key, value in counts_value.items()}
                            result = build_result_manifestation(
                                counts=counts,
                                related_circuit_ref=related_ref,
                                user_provided_shots=(
                                    int(result_input["shots"])
                                    if isinstance(result_input.get("shots"), int)
                                    else None
                                ),
                            )
                            if not circuit_available:
                                result = with_artifact_digest(
                                    {
                                        **{
                                            key: deepcopy(value)
                                            for key, value in result.items()
                                            if key != "artifact_digest"
                                        },
                                        "related_circuit_availability": "unavailable",
                                    }
                                )
                            run_summary_payload = (
                                deepcopy(result_input)
                                if "counts" in result_input
                                else {"counts": deepcopy(result_input)}
                            )
                            activity = next(
                                (
                                    receipt
                                    for receipt in current_state.get("activity_receipts", [])
                                    if isinstance(receipt, Mapping)
                                    and any(
                                        isinstance(registered, Mapping)
                                        and registered.get("role") == "results"
                                        and registered.get("content_digest") == content_digest
                                        for registered in receipt.get("registered_artifacts", [])
                                    )
                                ),
                                None,
                            )
                            if isinstance(activity, Mapping):
                                run_summary_lineage = {
                                    "status": "recorded",
                                    "operation_receipt_id": activity.get("operation_receipt_id"),
                                    "activity_digest": activity.get("activity_digest"),
                                }
                        self._save_artifact(
                            "result_manifestation",
                            result,
                            "result-manifestation.json",
                        )
                        roles = ["result_manifestation"]
                    extracted_roles.extend(roles)
                    outcomes.append(
                        processing_outcome(
                            role=role,
                            content_digest=content_digest,
                            detected_format=detected_format,
                            status="completed",
                            manifestation_roles=roles,
                        )
                    )
                except (EvidenceProcessingError, CurrentLoopContractError) as exc:
                    error_category = str(getattr(exc, "category", "unknown_local_internal"))
                    outcomes.append(
                        processing_outcome(
                            role=role,
                            content_digest=content_digest,
                            detected_format=detected_format,
                            status=(
                                "unsupported_format"
                                if error_category
                                in {"artifact_format_unsupported", "circuit_format_unsupported"}
                                else "excluded"
                                if error_category == "current_loop_contract_policy_prohibited"
                                else "failed_local"
                            ),
                            limitation=(
                                "Circuit structural derivation is unavailable because the "
                                "exact artifact is not OpenQASM 2."
                                if error_category == "circuit_format_unsupported"
                                else "Local derivation was unavailable for this exact artifact."
                            ),
                            safe_error_category=error_category,
                        )
                    )
                except (ValueError, OSError):
                    outcomes.append(
                        processing_outcome(
                            role=role,
                            content_digest=content_digest,
                            detected_format=detected_format,
                            status="failed_local",
                            limitation="A bounded local derivation failed for this exact artifact.",
                            safe_error_category=f"local_{role}_derivation_failed",
                        )
                    )
            state = self.store.read()
            if (
                run_summary_payload is not None
                and "result_manifestation" in state["saved_artifacts"]
                and contract_permits(
                    state["current_loop_contract"],
                    category="result_manifestation",
                    dimension="prepare",
                )
            ):
                try:
                    summary = build_run_summary(
                        loop_ref=str(state["loop_ref"]),
                        workspace_binding=str(state["workspace_root"]),
                        state_revision=int(state["state_revision"]),
                        contract_revision=int(state["current_loop_contract"]["contract_revision"]),
                        result_payload=run_summary_payload,
                        result_manifestation=self._saved_artifact(state, "result_manifestation"),
                        circuit_manifestation=(
                            self._saved_artifact(state, "circuit_manifestation")
                            if "circuit_manifestation" in state["saved_artifacts"]
                            else None
                        ),
                        source_manifestation=(
                            self._saved_artifact(state, "python_manifestation")
                            if "python_manifestation" in state["saved_artifacts"]
                            else None
                        ),
                        operation_lineage=run_summary_lineage,
                    )
                    summary_reference = str(summary["artifact_ref"])
                    save_run_summary(
                        store=self.store,
                        summary=summary,
                        destination=(self.artifact_directory / f"{summary_reference}.json"),
                        expected_revision=int(state["state_revision"]),
                    )
                    extracted_roles.append("run_summary")
                    state = self.store.read()
                except (RunSummaryError, CurrentLoopError, OSError, ValueError):
                    outcomes.append(
                        processing_outcome(
                            role="results",
                            content_digest=sha256(
                                json.dumps(
                                    run_summary_payload,
                                    ensure_ascii=True,
                                    sort_keys=True,
                                ).encode()
                            ).hexdigest(),
                            detected_format="qcoder_result_json",
                            status="failed_local",
                            limitation="Local Run Summary construction was unavailable.",
                            safe_error_category="local_run_summary_failed",
                        )
                    )
            hosted_available = "result_manifestation" in state["saved_artifacts"] or (
                "source_evidence" in state["saved_artifacts"]
                and "working_blueprint" in state["saved_artifacts"]
                and "output_evidence_contract" in state["saved_artifacts"]
            )
            hosted = hosted_enrichment_status("available" if hosted_available else "not_offered")

            def processing_mutator(value: dict[str, Any]) -> Mapping[str, Any]:
                for outcome in outcomes:
                    key = f"{outcome['role']}:{outcome['content_digest']}"
                    value["artifact_processing_outcomes"][key] = deepcopy(outcome)
                value["hosted_enrichment"] = deepcopy(hosted)
                return value

            state = self.store.update(
                processing_mutator,
                expected_revision=int(state["state_revision"]),
            )
            coordinator = self._coordinator_state(state)
            limitation_count = sum(1 for outcome in outcomes if outcome["status"] != "completed")
            circuit_limitation = next(
                (
                    outcome
                    for outcome in outcomes
                    if outcome.get("safe_error_category") == "circuit_format_unsupported"
                ),
                None,
            )
            bounded_recovery: dict[str, Any] | None = None
            if isinstance(circuit_limitation, Mapping):
                fingerprint = recovery_fingerprint(
                    category="circuit_format_unsupported",
                    operation="process_authorized_artifacts",
                    input_digests=[str(circuit_limitation["content_digest"])],
                )
                actions = [
                    "continue_with_limitations",
                    "provide_supported_circuit_artifact",
                    "skip_current_artifact_derivation",
                    "stop_loop",
                ]
                coordinator["active_recovery"] = {
                    "schema_id": RECOVERY_SCHEMA_ID,
                    "schema_version": RECOVERY_SCHEMA_VERSION,
                    "category": "circuit_format_unsupported",
                    "strategy": "bounded_alternative",
                    "reference": f"recovery-{fingerprint[:24]}",
                    "fingerprint": fingerprint,
                    "occurrence_count": 1,
                    "deterministic": True,
                    "alternatives": actions,
                    "origin": "local_circuit_derivation",
                    "nonblocking": True,
                }
                bounded_recovery = {
                    "schema_id": RECOVERY_SCHEMA_ID,
                    "schema_version": RECOVERY_SCHEMA_VERSION,
                    "strategy": "bounded_alternative",
                    "safe_error_category": "circuit_format_unsupported",
                    "prior_valid_authority_preserved": True,
                    "prior_valid_evidence_preserved": True,
                    "hosted_operation_permitted": False,
                    "alternatives": actions,
                    "complete_next_invocation_required": True,
                    "convergence_fingerprint": fingerprint,
                    "deterministic_failure": True,
                }
            coordinator.update(
                {
                    "phase": "evidence_processing",
                    "state_status": "ready",
                    "checkpoint_kind": "none",
                    "customer_summary": (
                        "Authorized local artifacts were processed and exact bounded "
                        "evidence was saved. Raw artifacts remained local."
                    ),
                    "evidence_processing_complete": True,
                    "hosted_enrichment_status": hosted["status"],
                }
            )
            coordinator["performance"]["local_extraction_seconds"] += max(
                0.0, self.clock() - extraction_started
            )
            self._replace_coordinator(coordinator)
            return self._result(
                operation="process_authorized_artifacts",
                ok=True,
                state=self.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                details={
                    "extracted_roles": extracted_roles,
                    "per_item_outcomes": outcomes,
                    "processing_partial": limitation_count > 0,
                    "evidence_limitations": [
                        outcome["limitation"]
                        for outcome in outcomes
                        if isinstance(outcome.get("limitation"), str)
                    ],
                    "local_processing": {
                        "transport": LOCAL_ONLY,
                        "protected_calls_attempted": 0,
                        "per_item_isolation": True,
                        "successful_outcomes_persisted": True,
                    },
                    "hosted_enrichment": hosted,
                    "recovery_contract": bounded_recovery,
                    "run_summary": {
                        "schema": run_summary_contract_snapshot(),
                        "automatic_preparation": "run_summary" in extracted_roles,
                        "latest_reference": self.store.read().get("latest_run_summary_reference"),
                    },
                    "build_review": {
                        "optional": True,
                        "decline_blocks_completion": False,
                        "may_request_later": True,
                    },
                    "raw_source_sent": False,
                    "raw_qasm_sent": False,
                    "raw_results_sent": False,
                    "source_executed": False,
                    "manual_extractor_commands": 0,
                },
            )
        except (
            CurrentLoopError,
            CurrentLoopConflict,
            CurrentLoopContractError,
            EvidenceProcessingError,
            ValueError,
            OSError,
        ) as exc:
            return self._exception_result("process_authorized_artifacts", exc, started)

    def enrich_authorized_evidence(self) -> dict[str, Any]:
        """Optionally enrich already-persisted evidence without endangering local results."""

        started = self.clock()
        try:
            state = self._require_phase(
                "enrich_authorized_evidence",
                {"evidence_processing", "current_build_review"},
            )
            coordinator = self._coordinator_state(state)
            if coordinator.get("evidence_processing_complete") is not True:
                raise EvidenceProcessingError(
                    "local_evidence_processing_required",
                    origin="contract_or_authority",
                )
            hosted = state.get("hosted_enrichment")
            if not isinstance(hosted, Mapping) or hosted.get("status") not in {
                "available",
                "rejected",
                "unavailable",
                "skipped",
            }:
                raise EvidenceProcessingError(
                    "hosted_enrichment_not_available",
                    origin="contract_or_authority",
                )
            if self.transport is None:
                return self._recovery_result(
                    operation="enrich_authorized_evidence",
                    category="protected_service_unavailable",
                    phase=coordinator["phase"],
                    elapsed=self.clock() - started,
                    origin="hosted_transport",
                    deterministic=False,
                    alternatives=("retry_hosted_enrichment", "skip_hosted_enrichment", "stop_loop"),
                )
            attempt_count = int(hosted.get("attempts", 0)) + 1

            def in_progress(value: dict[str, Any]) -> Mapping[str, Any]:
                value["hosted_enrichment"] = hosted_enrichment_status(
                    "in_progress", attempts=attempt_count
                )
                return value

            state = self.store.update(in_progress, expected_revision=int(state["state_revision"]))
            enriched_roles: list[str] = []
            try:
                if "result_manifestation" in state["saved_artifacts"]:
                    result_review_payload = self._protected_call(
                        "create_result_review_context_card",
                        {
                            "context_loop": "current_build_context_v1",
                            "result_manifestation": self._saved_artifact(
                                state, "result_manifestation"
                            ),
                            "evidence_parent_artifacts": [
                                self._saved_artifact(state, role)
                                for role in ("circuit_manifestation", "result_manifestation")
                                if role in state["saved_artifacts"]
                            ],
                        },
                    )
                    try:
                        result_review = self._response_artifact(
                            result_review_payload, "result_review_context_card"
                        )
                    except CurrentLoopError as exc:
                        raise EvidenceProcessingError(
                            exc.category,
                            origin="hosted_operation",
                            deterministic=False,
                            protected_call_attempted=True,
                        ) from exc
                    self._save_artifact(
                        "result_review_context_card",
                        result_review,
                        "result-review-context-card.json",
                    )
                    enriched_roles.append("result_review_context_card")
                    state = self.store.read()
                if all(
                    role in state["saved_artifacts"]
                    for role in (
                        "source_evidence",
                        "working_blueprint",
                        "output_evidence_contract",
                    )
                ):
                    alignment_payload = self._protected_call(
                        "create_source_blueprint_alignment_review",
                        {
                            "implementation_blueprint": self._saved_artifact(
                                state, "working_blueprint"
                            ),
                            "output_evidence_contract": self._saved_artifact(
                                state, "output_evidence_contract"
                            ),
                            "selected_python_source_evidence": self._saved_artifact(
                                state, "source_evidence"
                            ),
                        },
                    )
                    try:
                        alignment = self._response_artifact(
                            alignment_payload, "source_blueprint_alignment_review"
                        )
                    except CurrentLoopError as exc:
                        raise EvidenceProcessingError(
                            exc.category,
                            origin="hosted_operation",
                            deterministic=False,
                            protected_call_attempted=True,
                        ) from exc
                    self._save_artifact(
                        "source_blueprint_alignment",
                        alignment,
                        "source-blueprint-alignment.json",
                    )
                    enriched_roles.append("source_blueprint_alignment")
            except (CurrentLoopError, EvidenceProcessingError) as exc:
                current = self.store.read()
                safe_category = str(getattr(exc, "category", "protected_operation_rejected"))

                def rejected(value: dict[str, Any]) -> Mapping[str, Any]:
                    value["hosted_enrichment"] = hosted_enrichment_status(
                        "rejected",
                        provenance="hosted_rejection",
                        attempts=attempt_count,
                        last_safe_category=safe_category,
                    )
                    return value

                self.store.update(rejected, expected_revision=int(current["state_revision"]))
                return self._exception_result("enrich_authorized_evidence", exc, started)
            current = self.store.read()

            def completed(value: dict[str, Any]) -> Mapping[str, Any]:
                value["hosted_enrichment"] = hosted_enrichment_status(
                    "completed", attempts=attempt_count
                )
                return value

            state = self.store.update(completed, expected_revision=int(current["state_revision"]))
            coordinator = self._coordinator_state(state)
            coordinator["hosted_enrichment_status"] = "completed"
            coordinator["state_status"] = "ready"
            coordinator["checkpoint_kind"] = "none"
            coordinator["customer_summary"] = (
                "Optional hosted enrichment completed. Local evidence and the Run Summary "
                "remain independently available."
            )
            coordinator.pop("active_recovery", None)
            self._replace_coordinator(coordinator)
            return self._result(
                operation="enrich_authorized_evidence",
                ok=True,
                state=self.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                details={
                    "enriched_roles": enriched_roles,
                    "local_evidence_preserved": True,
                    "run_summary_preserved": True,
                    "hosted_enrichment": self.store.read()["hosted_enrichment"],
                },
            )
        except (CurrentLoopError, CurrentLoopConflict, EvidenceProcessingError) as exc:
            return self._exception_result("enrich_authorized_evidence", exc, started)

    def execute_recovery_action(
        self,
        *,
        recovery_reference: str,
        action: str,
        expected_contract_revision: int,
    ) -> dict[str, Any]:
        """Execute one selected bounded action; refreshing never executes it."""

        started = self.clock()
        try:
            state = self.store.read()
            contract = state.get("current_loop_contract")
            if (
                not isinstance(contract, Mapping)
                or int(contract["contract_revision"]) != expected_contract_revision
            ):
                raise CurrentLoopError("contract_revision_stale")
            coordinator = self._coordinator_state(state)
            active = coordinator.get("active_recovery")
            if not isinstance(active, Mapping) or active.get("reference") != recovery_reference:
                raise EvidenceProcessingError(
                    "recovery_reference_stale",
                    origin="contract_or_authority",
                )
            alternatives = active.get("alternatives")
            if not isinstance(alternatives, list) or action not in alternatives:
                raise EvidenceProcessingError(
                    "recovery_action_not_permitted",
                    origin="contract_or_authority",
                    safe_details={"advertised_actions": list(alternatives or [])},
                )
            if action == "stop_loop":
                raise EvidenceProcessingError(
                    "recovery_stop_requires_abandon_invocation",
                    origin="contract_or_authority",
                )
            if action == "retry_hosted_enrichment":
                raise EvidenceProcessingError(
                    "recovery_hosted_retry_requires_hosted_invocation",
                    origin="contract_or_authority",
                )
            if action == "skip_hosted_enrichment":
                current = self.store.read()

                def skip_hosted(value: dict[str, Any]) -> Mapping[str, Any]:
                    existing = value.get("hosted_enrichment", {})
                    value["hosted_enrichment"] = hosted_enrichment_status(
                        "skipped",
                        provenance=(
                            "hosted_rejection"
                            if isinstance(existing, Mapping)
                            and existing.get("status") in {"rejected", "unavailable"}
                            else "explicit_customer_choice"
                        ),
                        attempts=(
                            int(existing.get("attempts", 0)) if isinstance(existing, Mapping) else 0
                        ),
                    )
                    return value

                state = self.store.update(
                    skip_hosted, expected_revision=int(current["state_revision"])
                )
                summary = (
                    "Optional hosted enrichment was skipped. Local manifestations, the "
                    "Run Summary, and local evidence views remain available."
                )
            elif action == "provide_supported_circuit_artifact":
                summary = (
                    "A fresh, separately authorized IDE operation may now create or select "
                    "one exact OpenQASM 2 circuit artifact."
                )
                coordinator["phase"] = "generation_ready"
                coordinator["evidence_processing_complete"] = True
            elif action in {
                "continue_with_limitations",
                "skip_current_artifact_derivation",
                "abandon_step",
            }:
                summary = (
                    "The optional failed derivation step was closed with its limitation. "
                    "Prior trustworthy evidence and authority remain intact."
                )
            elif action == "retry_local_derivation":
                if (
                    active.get("deterministic") is True
                    and int(active.get("occurrence_count", 0)) > 0
                ):
                    raise EvidenceProcessingError(
                        "deterministic_retry_requires_changed_input",
                        origin="local_artifact_validation",
                    )
                coordinator["evidence_processing_complete"] = False
                summary = "Local derivation may be retried using the current exact authorized set."
            elif action == "decline_build_review":
                summary = "The optional Build Review was declined; the Blueprint is unchanged."
                coordinator["phase"] = "continuation_choice"
            else:
                raise EvidenceProcessingError(
                    "recovery_action_not_permitted",
                    origin="contract_or_authority",
                )
            history = coordinator.setdefault("recovery_history", [])
            history.append(
                {
                    "reference": recovery_reference,
                    "action": action,
                    "fingerprint": active.get("fingerprint"),
                    "prior_authority_preserved": True,
                    "prior_evidence_preserved": True,
                }
            )
            coordinator["active_recovery"] = None
            coordinator["state_status"] = "ready"
            coordinator["checkpoint_kind"] = "none"
            coordinator["customer_summary"] = summary
            if action == "skip_hosted_enrichment":
                coordinator["hosted_enrichment_status"] = "skipped"
            self._replace_coordinator(coordinator)
            return self._result(
                operation="execute_recovery_action",
                ok=True,
                state=self.store.read(),
                summary=summary,
                elapsed=self.clock() - started,
                details={
                    "executed_action": action,
                    "recovery_reference": recovery_reference,
                    "refresh_operation_executed_action": False,
                    "prior_valid_authority_preserved": True,
                    "prior_valid_evidence_preserved": True,
                    "hosted_operation_permitted": False,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict, EvidenceProcessingError) as exc:
            return self._exception_result("execute_recovery_action", exc, started)

    def decline_build_review(self, *, explicit_authority: bool) -> dict[str, Any]:
        """Decline the optional passive review without changing the Blueprint."""

        started = self.clock()
        try:
            state = self._require_phase(
                "decline_build_review", {"evidence_processing", "current_build_review"}
            )
            if explicit_authority is not True:
                return self._checkpoint_result(
                    operation="decline_build_review",
                    phase=self._coordinator_state(state)["phase"],
                    checkpoint_kind="none",
                    summary="Declining the optional Build Review requires an explicit choice.",
                    elapsed=self.clock() - started,
                )
            coordinator = self._coordinator_state(state)
            coordinator.update(
                {
                    "phase": "continuation_choice",
                    "state_status": "checkpoint_required",
                    "checkpoint_kind": "none",
                    "customer_summary": (
                        "Build Review was declined. The governing Blueprint is unchanged; "
                        "continue or request the review later."
                    ),
                    "build_review": {
                        "status": "declined",
                        "optional": True,
                        "may_request_later": True,
                        "blueprint_mutated": False,
                        "evolved_blueprint_created": False,
                    },
                }
            )
            self._replace_coordinator(coordinator)
            return self._result(
                operation="decline_build_review",
                ok=True,
                state=self.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                details={
                    "build_review_declined": True,
                    "continuation_unblocked": True,
                    "working_blueprint_unchanged": True,
                    "evolved_blueprint_created": False,
                    "hosted_operation_invoked": False,
                    "may_request_later": True,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict) as exc:
            return self._exception_result("decline_build_review", exc, started)

    def review_build(self) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self._require_phase(
                "review_build",
                {"evidence_processing", "current_build_review", "continuation_choice"},
            )
            self._require_contract_permission(
                state,
                category="derived_metrics",
                dimension="derive",
            )
            self._require_contract_permission(
                state,
                category="derived_metrics",
                dimension="assistant_derived_exposure",
            )
            freshness = check_current_loop_freshness(
                store=self.store, expected_revision=state["state_revision"]
            )
            if not freshness["fresh"]:
                return self._recovery_result(
                    operation="review_build",
                    category=_ERROR_ALIASES.get(
                        freshness["events"][0]["category"],
                        "canonical_artifact_modified",
                    ),
                    phase="evidence_processing",
                    elapsed=self.clock() - started,
                )
            if self.transport is None:
                return self._recovery_result(
                    operation="review_build",
                    category="protected_service_unavailable",
                    phase="evidence_processing",
                    elapsed=self.clock() - started,
                )
            state = self.store.read()
            saved = {role: self._saved_artifact(state, role) for role in state["saved_artifacts"]}
            if "working_blueprint" in state["saved_artifacts"]:
                saved["working_blueprint"] = self._saved_artifact(state, "working_blueprint")
            if "output_evidence_contract" in state["saved_artifacts"]:
                saved["output_evidence_contract"] = self._saved_artifact(
                    state, "output_evidence_contract"
                )
            blueprint = saved.get("working_blueprint")
            baseline = saved.get("request_baseline")
            if not isinstance(blueprint, Mapping) or not isinstance(baseline, Mapping):
                raise CurrentLoopError("canonical_parent_set_incomplete")
            share_safe_baseline = share_safe_request_baseline(
                baseline,
                structural_summary=(
                    "The exact original request remains local; supplied constraints "
                    "and decisions govern this current build."
                ),
            )
            self._save_artifact(
                "request_baseline_handoff",
                share_safe_baseline,
                "request-baseline.handoff.json",
            )
            stage_availability = build_stage_availability(
                {
                    "human_intent": {
                        "artifact_supplied": True,
                        "artifact_validated": True,
                    },
                    "python_source": {
                        "artifact_supplied": "python_manifestation" in saved,
                        "artifact_validated": "python_manifestation" in saved,
                    },
                    "logical_circuit": {
                        "artifact_supplied": "circuit_manifestation" in saved,
                        "artifact_validated": "circuit_manifestation" in saved,
                        "explicit_state": (
                            None if "circuit_manifestation" in saved else "not_constructed"
                        ),
                    },
                    "run_results": {
                        "artifact_supplied": "result_manifestation" in saved,
                        "artifact_validated": "result_manifestation" in saved,
                        "explicit_state": (None if "result_manifestation" in saved else "not_run"),
                    },
                    "next_human_intent": {"artifact_supplied": False},
                }
            )
            self._save_artifact(
                "stage_availability",
                stage_availability,
                "stage-availability.json",
            )
            lineage = build_decision_evidence_lineage(links=[])
            self._save_artifact(
                "decision_evidence_lineage",
                lineage,
                "decision-evidence-lineage.json",
            )
            arguments: dict[str, Any] = {
                "context_loop": "current_build_context_v1",
                "request_baseline": share_safe_baseline,
                "request_share_safe_summary": share_safe_baseline["request_summary"],
                "request_text_share_safe": False,
                "working_blueprint": blueprint,
                "stage_availability": stage_availability,
                "decision_evidence_lineage": lineage,
                "artifact_references": [],
                "evidence_parent_artifacts": [],
            }
            summaries = read_run_summaries(state)
            fresh_summaries = [
                summary
                for summary in summaries
                if summary.get("freshness", {}).get("status") == "fresh"
            ]
            if fresh_summaries:
                arguments["selected_share_safe_summaries"] = {
                    "run_summary": share_safe_run_summary_projection(
                        fresh_summaries[-1], full=False
                    )
                }
            role_to_argument = {
                "generation_context_pack": "generation_context",
                "exploratory_generation_context": "generation_context",
                "python_manifestation": "python_manifestation",
                "circuit_manifestation": "circuit_manifestation",
                "result_manifestation": "result_manifestation",
            }
            for role, argument in role_to_argument.items():
                if role in saved:
                    arguments[argument] = saved[role]
                    arguments["evidence_parent_artifacts"].append(saved[role])
            payload = self._protected_call("create_context_session_card", arguments)
            current = self._response_artifact(payload, "current_build_context")
            self._save_artifact(
                "current_build_context",
                current,
                "current-build-context.json",
            )
            portable = payload.get("portable_current_build_context")
            if not isinstance(portable, Mapping):
                raise CurrentLoopError("protected_truth_insufficient")
            self._save_artifact(
                "pre_proposal_portable_current_build_context",
                portable,
                "current-build-context.pre-proposal.portable.json",
            )
            projection = consequence_projection(current)
            coordinator = self._coordinator_state(self.store.read())
            coordinator.update(
                {
                    "phase": "current_build_review",
                    "state_status": "ready",
                    "checkpoint_kind": "none",
                    "customer_summary": (
                        "Current-build evidence is ready for deterministic review."
                    ),
                    "consequence_projection": projection,
                }
            )
            self._replace_coordinator(coordinator)
            coordinator = self._coordinator_state(self.store.read())
            coordinator.update(
                {
                    "phase": "continuation_choice",
                    "state_status": "checkpoint_required",
                    "checkpoint_kind": "none",
                    "customer_summary": (
                        "Current-build review is ready. Continue with the current "
                        "Blueprint or review a supplied Carry-Forward option."
                    ),
                    "consequence_projection": projection,
                }
            )
            self._replace_coordinator(coordinator)
            return self._result(
                operation="review_build",
                ok=True,
                state=self.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                details={
                    "consequence_groups": projection["groups"],
                    "additional_evidence_available_count": projection[
                        "additional_evidence_available_count"
                    ],
                    "expanded_truth_preserved": True,
                    "readiness_calculated_locally": False,
                    "run_summary_reference": (
                        fresh_summaries[-1]["artifact_ref"] if fresh_summaries else None
                    ),
                    "run_summary_missing_limitation": not bool(fresh_summaries),
                    "blueprint_mutated": False,
                    "evolved_blueprint_created": False,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict, ValueError) as exc:
            return self._exception_result("review_build", exc, started)

    def continue_unchanged(
        self,
        *,
        explicit_user_action: bool,
        user_statement: str,
        decline_unconfirmed_proposal: bool = False,
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self._require_phase(
                "continue_unchanged",
                {"continuation_choice", "change_confirmation"},
            )
            if not explicit_user_action:
                return self._checkpoint_result(
                    operation="continue_unchanged",
                    phase=self._coordinator_state(state)["phase"],
                    checkpoint_kind="governing_change_confirmation",
                    summary=(
                        "Continuing with the current Blueprint requires an explicit "
                        "user act; silence is not a decision."
                    ),
                    elapsed=self.clock() - started,
                )
            freshness = check_current_loop_freshness(
                store=self.store, expected_revision=state["state_revision"]
            )
            if not freshness["fresh"]:
                return self._recovery_result(
                    operation="continue_unchanged",
                    category=_ERROR_ALIASES.get(
                        freshness["events"][0]["category"],
                        "canonical_artifact_modified",
                    ),
                    phase=self._coordinator_state(self.store.read())["phase"],
                    elapsed=self.clock() - started,
                )
            state = self.store.read()
            blueprint = self._saved_artifact(state, "working_blueprint")
            retained = {
                role: self._saved_artifact(state, role)
                for role in (
                    "source_evidence",
                    "python_manifestation",
                    "circuit_manifestation",
                    "result_manifestation",
                    "current_build_context",
                )
                if role in state["saved_artifacts"]
            }
            required = {
                "governing_blueprint": (
                    "implementation_blueprint",
                    blueprint,
                )
            }
            if "output_evidence_contract" in state["saved_artifacts"]:
                required["output_evidence_contract"] = self._saved_artifact(
                    state, "output_evidence_contract"
                )
            proposal = (
                self._saved_artifact(state, "carry_forward_proposal")
                if "carry_forward_proposal" in state["saved_artifacts"]
                else None
            )
            if proposal is not None and proposal.get("proposal_state") not in {
                "unconfirmed",
                "declined",
            }:
                raise CurrentLoopError("unchanged_continuation_proposal_state_invalid")
            if proposal is not None and decline_unconfirmed_proposal:
                proposal = deepcopy(proposal)
                proposal.pop("artifact_digest", None)
                proposal["proposal_state"] = "declined"
                proposal = with_artifact_digest(proposal)
            outcome = build_unchanged_continuation(
                loop_instance_record=self._load_loop_instance_record(state),
                governing_working_blueprint=blueprint,
                retained_evidence=retained,
                explicit_user_action={
                    "confirmed": True,
                    "provenance": "direct_user_action",
                    "statement": user_statement,
                },
                required_parent_artifacts=required,
                next_permitted_operation_family="create_generation_context_pack",
                unadopted_proposal=proposal,
            )
            continuation = outcome["unchanged_continuation"]
            seed = outcome["next_loop_seed"]
            self._save_artifact(
                "unchanged_continuation",
                continuation,
                "unchanged-continuation.json",
            )
            self._save_artifact("next_loop_seed", seed, "next-loop-seed.json")
            state = self.store.read()
            complete_current_loop(
                store=self.store,
                completion_state="completed_unchanged",
                continuation_artifact=continuation,
                next_loop_seed=seed,
                expected_revision=state["state_revision"],
            )
            coordinator = self._coordinator_state(self.store.read())
            coordinator.update(
                {
                    "phase": "next_loop_ready",
                    "state_status": "ready",
                    "checkpoint_kind": "none",
                    "customer_summary": (
                        "The governing Blueprint is unchanged; no governing decision "
                        "changed, and the next-loop seed is ready."
                    ),
                    "next_loop_branch": {
                        "completed_build_governing_change_branch_closed": True,
                        "governing_blueprint_unchanged": True,
                        "evolved_blueprint_created": False,
                        "proposal_adopted": False,
                        "continuation_reference": _artifact_reference(continuation),
                        "next_loop_seed_reference": _artifact_reference(seed),
                    },
                }
            )
            self._replace_coordinator(coordinator)
            return self._result(
                operation="continue_unchanged",
                ok=True,
                state=self.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                details={
                    "governing_blueprint_unchanged": True,
                    "governing_decisions_changed": False,
                    "evolved_blueprint_created": False,
                    "proposal_adopted": False,
                    "next_loop_seed_ready": True,
                    "completed_build_governing_change_branch_closed": True,
                    "start_next_uses_qcoder_managed_references": True,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict, ValueError) as exc:
            return self._exception_result("continue_unchanged", exc, started)

    def propose_change(
        self,
        *,
        decision_ref: str,
        selected_action: str,
        proposed_value: object,
        control_treatment: str,
        explicit_user_selection: bool,
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self._require_phase("propose_change", {"continuation_choice"})
            self._require_contract_permission(
                state,
                category="working_blueprint",
                dimension="recommend",
            )
            if not explicit_user_selection:
                return self._checkpoint_result(
                    operation="propose_change",
                    phase="continuation_choice",
                    checkpoint_kind="governing_change_confirmation",
                    summary="qCoder will not choose a Carry-Forward treatment for the user.",
                    elapsed=self.clock() - started,
                )
            if self.transport is None:
                return self._recovery_result(
                    operation="propose_change",
                    category="protected_service_unavailable",
                    phase="continuation_choice",
                    elapsed=self.clock() - started,
                )
            freshness = check_current_loop_freshness(
                store=self.store, expected_revision=state["state_revision"]
            )
            if not freshness["fresh"]:
                return self._recovery_result(
                    operation="propose_change",
                    category=_ERROR_ALIASES.get(
                        freshness["events"][0]["category"],
                        "canonical_artifact_modified",
                    ),
                    phase="continuation_choice",
                    elapsed=self.clock() - started,
                )
            state = self.store.read()
            blueprint = self._saved_artifact(state, "working_blueprint")
            binding = decision_inventory_binding(blueprint)
            records = self._decision_records(blueprint)
            selected = next(
                (item for item in records if item.get("decision_ref") == decision_ref),
                None,
            )
            if selected is None:
                raise CurrentLoopError("selected_decision_not_found")
            current = self._saved_artifact(state, "current_build_context")
            applicable = current.get("applicable_actions")
            if isinstance(applicable, list) and selected_action not in applicable:
                raise CurrentLoopError("selected_action_not_applicable")
            proposed_update = self._proposed_update(
                selected,
                proposed_value=proposed_value,
                control_treatment=control_treatment,
            )
            parent_artifacts = [
                self._saved_artifact(state, role) for role in self._current_parent_roles(current)
            ] + [current]
            arguments = {
                "context_loop": "current_build_context_v1",
                "decision_loop": "readiness_resolution_v1",
                "resolution_context": "current_build_context",
                "resolution_phase": "propose",
                "selected_action": selected_action,
                "current_lineage_reference": records[0]["current_lineage_reference"],
                "working_blueprint": blueprint,
                "current_build_context": current,
                "evidence_parent_artifacts": parent_artifacts,
                "decision_records": records,
                "selected_decision_references": [decision_ref],
                "proposed_updates": [proposed_update],
                "profile_id": binding["profile_id"],
                "remaining_uncertainty": list(current.get("remaining_uncertainty", [])),
                "generation_context_effect": (
                    "Apply only after exact proposal-specific confirmation."
                ),
            }
            payload = self._protected_call("create_implementation_blueprint", arguments)
            proposal = self._response_artifact(payload, "carry_forward_proposal")
            proposed_outcome = proposal.get("proposed_outcome")
            decision_updates = (
                proposed_outcome.get("decision_updates")
                if isinstance(proposed_outcome, Mapping)
                else None
            )
            if (
                proposal.get("proposal_state") != "unconfirmed"
                or proposal.get("derived_artifact_materialized") is not False
                or not isinstance(decision_updates, list)
                or len(decision_updates) != 1
                or not isinstance(decision_updates[0], Mapping)
                or decision_updates[0].get("decision_ref") != decision_ref
            ):
                raise CurrentLoopError("proposal_confirmation_boundary_invalid")
            portable = payload.get("portable_current_build_context")
            if not isinstance(portable, Mapping):
                raise CurrentLoopError("protected_truth_insufficient")
            self._save_artifact(
                "carry_forward_proposal",
                proposal,
                "carry-forward-proposal.json",
            )
            self._save_artifact(
                "proposal_bearing_portable_current_build_context",
                portable,
                "current-build-context.proposal-bearing.portable.json",
            )
            coordinator = self._coordinator_state(self.store.read())
            coordinator.update(
                {
                    "phase": "change_confirmation",
                    "state_status": "checkpoint_required",
                    "checkpoint_kind": "governing_change_confirmation",
                    "customer_summary": (
                        "One unconfirmed Carry-Forward Proposal is ready. Review the "
                        "exact before and proposed-after values before deciding."
                    ),
                    "consequence_projection": consequence_projection(proposal),
                }
            )
            self._replace_coordinator(coordinator)
            return self._result(
                operation="propose_change",
                ok=True,
                state=self.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                details={
                    "proposal_state": "unconfirmed",
                    "decision_update_count": len(decision_updates),
                    "derived_artifact_materialized": False,
                    "confirmation_transport_attached": False,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict, ValueError) as exc:
            return self._exception_result("propose_change", exc, started)

    def confirm_change(
        self,
        *,
        semantic_confirmation: str,
        explicit_user_confirmation: bool,
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self._require_phase("confirm_change", {"change_confirmation"})
            if not explicit_user_confirmation:
                return self._checkpoint_result(
                    operation="confirm_change",
                    phase="change_confirmation",
                    checkpoint_kind="governing_change_confirmation",
                    summary=(
                        "The proposal remains unconfirmed. qCoder will not decide for the user."
                    ),
                    elapsed=self.clock() - started,
                )
            if self.transport is None:
                return self._recovery_result(
                    operation="confirm_change",
                    category="protected_service_unavailable",
                    phase="change_confirmation",
                    elapsed=self.clock() - started,
                )
            proposal = self._saved_artifact(state, "carry_forward_proposal")
            proposal_ref = proposal.get("proposal_ref")
            if not isinstance(proposal_ref, str) or proposal_ref not in semantic_confirmation:
                return self._checkpoint_result(
                    operation="confirm_change",
                    phase="change_confirmation",
                    checkpoint_kind="governing_change_confirmation",
                    summary=("Confirmation must identify the exact proposal being adopted."),
                    elapsed=self.clock() - started,
                )
            portable_descriptor = state["saved_artifacts"].get(
                "proposal_bearing_portable_current_build_context"
            )
            if not isinstance(portable_descriptor, Mapping):
                raise CurrentLoopError("selected_portable_bundle_missing")
            confirmation_started = self.clock()
            try:
                payload = self.transport.confirm_selected_bundle(
                    selected_bundle_file=portable_descriptor["local_path"],
                    semantic_confirmation=semantic_confirmation,
                )
            except Exception as exc:
                raise EvidenceProcessingError(
                    "protected_service_unavailable",
                    origin="hosted_transport",
                    deterministic=False,
                    protected_call_attempted=True,
                ) from exc
            self._record_protected_call(max(0.0, self.clock() - confirmation_started))
            if payload.get("ok") is False:
                raise EvidenceProcessingError(
                    str(payload.get("error_category") or "protected_operation_rejected"),
                    origin="hosted_operation",
                    deterministic=False,
                    protected_call_attempted=True,
                    protected_non_success=True,
                )
            evolved = self._response_artifact(payload, "evolved_blueprint")
            working = self._saved_artifact(state, "working_blueprint")
            if evolved.get("working_blueprint_parent", {}).get("digest") not in {
                None,
                _artifact_digest(working),
            }:
                raise CurrentLoopError("parent_digest_mismatch")
            self._save_artifact("evolved_blueprint", evolved, "evolved-blueprint.json")
            required = {"governing_blueprint": ("implementation_blueprint", evolved)}
            if "output_evidence_contract" in state["saved_artifacts"]:
                required["output_evidence_contract"] = self._saved_artifact(
                    self.store.read(), "output_evidence_contract"
                )
            seed = build_changed_next_loop_seed(
                source_loop_ref=state["loop_ref"],
                evolved_blueprint=evolved,
                required_parent_artifacts=required,
                next_permitted_operation_family="create_generation_context_pack",
            )
            self._save_artifact("next_loop_seed", seed, "next-loop-seed.json")
            state = self.store.read()
            complete_current_loop(
                store=self.store,
                completion_state="completed_changed",
                continuation_artifact=None,
                next_loop_seed=seed,
                expected_revision=state["state_revision"],
            )
            coordinator = self._coordinator_state(self.store.read())
            coordinator.update(
                {
                    "phase": "next_loop_ready",
                    "state_status": "ready",
                    "checkpoint_kind": "none",
                    "customer_summary": (
                        "The exact proposal was confirmed. The Evolved Blueprint and "
                        "next-loop seed are ready; the Working Blueprint is unchanged."
                    ),
                    "next_loop_branch": {
                        "completed_build_governing_change_branch_closed": True,
                        "governing_blueprint_unchanged": False,
                        "evolved_blueprint_created": True,
                        "proposal_adopted": True,
                        "continuation_reference": _artifact_reference(evolved),
                        "next_loop_seed_reference": _artifact_reference(seed),
                    },
                }
            )
            self._replace_coordinator(coordinator)
            return self._result(
                operation="confirm_change",
                ok=True,
                state=self.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                details={
                    "proposal_ref": proposal_ref,
                    "evolved_blueprint_created": True,
                    "working_blueprint_mutated": False,
                    "selected_bundle_used": True,
                    "parent_reconstructed": False,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict, ValueError) as exc:
            return self._exception_result("confirm_change", exc, started)

    def start_next(
        self,
        *,
        next_workspace_root: str | Path,
        generation_posture: str,
        seed_file: str | Path | None,
        parent_files: Mapping[str, str | Path] | None,
        explicit_authority: bool,
        use_current_seed: bool = False,
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self._require_phase("start_next", {"next_loop_ready"})
            if not explicit_authority:
                return self._checkpoint_result(
                    operation="start_next",
                    phase=self._coordinator_state(state)["phase"],
                    checkpoint_kind="activation",
                    summary="Starting the next loop requires explicit activation.",
                    elapsed=self.clock() - started,
                )
            supplied_parents = dict(parent_files or {})
            if use_current_seed:
                if seed_file is not None or supplied_parents:
                    raise CurrentLoopError("next_loop_seed_transport_conflict")
                seed_file, supplied_parents = self._current_seed_inputs(state)
            elif seed_file is None:
                raise CurrentLoopError("next_loop_seed_missing")
            activated = activate_next_loop_from_seed(
                workspace_root=next_workspace_root,
                generation_posture=generation_posture,
                explicit_authority=True,
                seed_file=seed_file,
                parent_files=supplied_parents,
                tool_name="create_generation_context_pack",
            )
            next_coordinator = CurrentLoopCoordinator(
                workspace_root=next_workspace_root,
                transport=self.transport,
                clock=self.clock,
            )
            coordinator = next_coordinator._initial_coordinator_state(
                phase="generation_ready",
                state_status="checkpoint_required",
                checkpoint_kind="ide_write_or_run",
                summary=(
                    "A new loop is active from the explicitly supplied seed and exact "
                    "parents. The next generation checkpoint is ready."
                ),
            )
            next_coordinator._replace_coordinator(coordinator)
            return next_coordinator._result(
                operation="start_next",
                ok=True,
                state=next_coordinator.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                details={
                    "new_loop_active": True,
                    "generation_posture": generation_posture,
                    "parent_loop_ref": activated["state"]["parent_loop_ref"],
                    "server_lookup_performed": False,
                    "parent_traversed": False,
                    "parent_traversal_performed": False,
                    "project_reopened": False,
                    "canonical_request_expanded_locally": True,
                    "qcoder_managed_seed_used": use_current_seed,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict, ValueError) as exc:
            return self._exception_result("start_next", exc, started)

    def standalone_review(
        self,
        *,
        role: str,
        path: str | Path,
        destination: str | Path,
        related_circuit_ref: str | None = None,
    ) -> dict[str, Any]:
        started = self.clock()
        selected = Path(path).expanduser().absolute()
        output = Path(destination).expanduser().absolute()
        try:
            if role == "source":
                artifact = extract_selected_python_file_evidence(
                    selected, logical_source_label=selected.name
                )
            elif role == "circuit_qasm":
                artifact = build_circuit_manifestation(
                    qasm_text=selected.read_text(encoding="utf-8"),
                    stage="logical_circuit",
                )
            elif role == "results":
                if not related_circuit_ref:
                    raise CurrentLoopError("result_related_circuit_ref_required")
                supplied = _load_json_file(selected)
                counts_value = supplied.get("counts", supplied)
                if not isinstance(counts_value, Mapping):
                    raise CurrentLoopError("result_artifact_invalid")
                artifact = build_result_manifestation(
                    counts={str(key): int(value) for key, value in counts_value.items()},
                    related_circuit_ref=related_circuit_ref,
                )
            else:
                raise CurrentLoopError("unsupported_authorized_artifact_type")
            _atomic_exact_write(output, artifact)
            return self._result_without_state(
                operation="standalone_review",
                ok=True,
                phase="activated",
                state_status="ready",
                checkpoint_kind="none",
                summary=(
                    "Standalone bounded evidence was created without activating or "
                    "silently composing a current loop."
                ),
                details={
                    "artifact_reference": _artifact_reference(artifact),
                    "artifact_digest": _artifact_digest(artifact),
                    "loop_activated": False,
                    "missing_stages_preserved": True,
                    "raw_artifact_sent": False,
                },
            )
        except (CurrentLoopError, ValueError, OSError) as exc:
            return self._exception_result("standalone_review", exc, started)

    def attach_to_loop(
        self,
        *,
        role: str,
        path: str | Path,
        provenance: str = "user_selected",
    ) -> dict[str, Any]:
        return self.register_artifacts(
            candidates=[
                {
                    "role": role,
                    "path": str(Path(path).expanduser().absolute()),
                    "provenance": provenance,
                    "explicit_external": not self._is_within_workspace(
                        Path(path).expanduser().absolute()
                    ),
                }
            ]
        )

    def abandon(self, *, explicit_authority: bool) -> dict[str, Any]:
        started = self.clock()
        try:
            current_state = self.store.read()
        except CurrentLoopError:
            current_state = None
        if (
            isinstance(current_state, Mapping)
            and current_state.get("state_kind") == "pending_activation"
        ):
            if not explicit_authority:
                return self._pending_activation_result(
                    operation="abandon",
                    state=current_state,
                    category="pending_activation_abandon_authority_required",
                )
            try:
                self.store.delete_state(explicit_authority=True)
                return self._result_without_state(
                    operation="abandon",
                    ok=True,
                    phase="abandoned",
                    state_status="ready",
                    checkpoint_kind="none",
                    summary=(
                        "The pending noncanonical activation capture was cleared locally. "
                        "qCoder was not activated and no Request Baseline was created."
                    ),
                    details={
                        "pending_capture_invalidated": True,
                        "activation_performed": False,
                        "canonical_request_baseline_created": False,
                    },
                )
            except (CurrentLoopError, CurrentLoopConflict) as exc:
                return self._exception_result("abandon", exc, started)
        if not explicit_authority:
            return self._checkpoint_result(
                operation="abandon",
                phase=self._safe_phase(),
                checkpoint_kind="activation",
                summary="Abandoning the active loop requires an explicit user act.",
                elapsed=self.clock() - started,
            )
        try:
            state = self.store.read()
            complete_current_loop(
                store=self.store,
                completion_state="abandoned",
                continuation_artifact=None,
                next_loop_seed=None,
                expected_revision=state["state_revision"],
            )
            coordinator = self._coordinator_state(self.store.read())
            coordinator.update(
                {
                    "phase": "abandoned",
                    "state_status": "ready",
                    "checkpoint_kind": "none",
                    "customer_summary": (
                        "The current loop is abandoned locally. Customer artifacts "
                        "and saved qCoder artifacts were not deleted."
                    ),
                }
            )
            self._replace_coordinator(coordinator)
            return self._result(
                operation="abandon",
                ok=True,
                state=self.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
            )
        except (CurrentLoopError, CurrentLoopConflict) as exc:
            return self._exception_result("abandon", exc, started)

    def record_external_time(
        self,
        *,
        category: str,
        seconds: float,
    ) -> dict[str, Any]:
        if category not in {
            "assistant_orchestration_seconds",
            "ide_write_or_run_seconds",
            "human_review_seconds",
        }:
            return self._recovery_result(
                operation="record_external_time",
                category="unsupported_schema",
                phase="activated",
                elapsed=0.0,
            )
        if not isinstance(seconds, (int, float)) or seconds < 0:
            return self._recovery_result(
                operation="record_external_time",
                category="unsupported_schema",
                phase="activated",
                elapsed=0.0,
            )
        try:
            state = self.store.read()
            coordinator = self._coordinator_state(state)
            coordinator["performance"][category] += float(seconds)
            self._replace_coordinator(coordinator)
            return self._result(
                operation="record_external_time",
                ok=True,
                state=self.store.read(),
                summary="Private local timing was recorded without telemetry.",
                elapsed=0.0,
            )
        except (CurrentLoopError, CurrentLoopConflict) as exc:
            return self._exception_result("record_external_time", exc, self.clock())

    def private_performance_snapshot(self) -> dict[str, Any]:
        state = self.store.read()
        coordinator = self._coordinator_state(state)
        return deepcopy(coordinator["performance"])

    def refuse_reconstruction(self, artifact_role: str) -> dict[str, Any]:
        return self._recovery_result(
            operation="refuse_reconstruction",
            category="reconstruction_attempt_refused",
            phase=self._safe_phase(),
            elapsed=0.0,
            details={
                "artifact_role": artifact_role,
                "artifact_reconstructed": False,
                "schema_repair_attempted": False,
            },
        )

    def _transition_parent_artifacts(
        self,
        state: Mapping[str, Any],
        pending_resolution: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        names = (
            "algorithm-intent-card",
            "working-blueprint",
            "output-evidence-contract",
        )
        if pending_resolution is not None:
            retained = {
                str(item.get("role")): item
                for item in pending_resolution.get("retained_artifacts", [])
                if isinstance(item, Mapping)
            }
            loaded: list[dict[str, Any]] = []
            for name in names:
                descriptor = retained.get(name)
                filename = (
                    descriptor.get("local_record") if isinstance(descriptor, Mapping) else None
                )
                if not isinstance(filename, str) or Path(filename).name != filename:
                    raise CurrentLoopError("canonical_parent_set_incomplete")
                loaded.append(_load_json_file(self.artifact_directory / filename))
            return loaded[0], loaded[1], loaded[2]
        return (
            self._saved_artifact(state, "algorithm_intent_card"),
            self._saved_artifact(state, "working_blueprint"),
            self._saved_artifact(state, "output_evidence_contract"),
        )

    def _ensure_transition_parent_saved(
        self,
        role: str,
        artifact: Mapping[str, Any],
        filename: str,
    ) -> None:
        state = self.store.read()
        if role in state.get("saved_artifacts", {}):
            if self._saved_artifact(state, role) != dict(artifact):
                raise CurrentLoopError("posture_transition_working_blueprint_mutation")
            return
        self._save_artifact(role, artifact, filename)

    def _prepare_generation_after_posture_transition(
        self,
        *,
        state: Mapping[str, Any],
        coordinator: dict[str, Any],
        pending_resolution: Mapping[str, Any] | None,
        profile_id: str,
        requested_posture: str,
        review_input: Mapping[str, Any],
        review_input_digest: str,
        normalized_dispositions: Sequence[Mapping[str, Any]],
        constraints: Sequence[str],
        non_goals: Sequence[str],
        accepted_unresolved_choices: Sequence[str],
        started: float,
    ) -> dict[str, Any]:
        intent, blueprint, output_contract = self._transition_parent_artifacts(
            state, pending_resolution
        )
        generation_arguments: dict[str, Any] = {
            "context_loop": CONTEXT_LOOP_GATE,
            "generation_posture": requested_posture,
            "implementation_blueprint": blueprint,
            "output_evidence_contract": output_contract,
        }
        if requested_posture == "exploratory_first_pass":
            generation_arguments.update(
                {
                    "exploratory_authorization": True,
                    "exploratory_constraints": list(
                        dict.fromkeys([*constraints, *EXPLORATORY_FIXED_CONSTRAINTS])
                    ),
                    "exploratory_prohibitions": list(
                        dict.fromkeys([*non_goals, *EXPLORATORY_FIXED_PROHIBITIONS])
                    ),
                    "unresolved_assistant_choices": list(accepted_unresolved_choices),
                }
            )
        payload = self._protected_call("create_generation_context_pack", generation_arguments)
        context_status = payload.get("context_status")
        intent_binding = decision_inventory_binding(intent)
        if context_status == "generation_context_blocked_pending_decisions":
            if (
                requested_posture != "blueprint_guided"
                or payload.get("generation_context_pack") is not None
                or payload.get("generation_context_pack_produced") is not False
                or not isinstance(payload.get("blueprint_readiness_summary"), Mapping)
            ):
                raise CurrentLoopError("protected_truth_insufficient")
            readiness = deepcopy(dict(payload["blueprint_readiness_summary"]))
            blockers, records = self._decision_resolution_details(
                profile_id=profile_id,
                blueprint=blueprint,
                readiness=readiness,
            )
            if not blockers:
                raise CurrentLoopError("protected_truth_insufficient")
            retained = (
                deepcopy(list(pending_resolution.get("retained_artifacts") or []))
                if pending_resolution is not None
                else [
                    self._save_pending_generation_artifact("algorithm-intent-card", intent),
                    self._save_pending_generation_artifact("working-blueprint", blueprint),
                    self._save_pending_generation_artifact(
                        "output-evidence-contract", output_contract
                    ),
                ]
            )
            awaiting = [str(item["profile_decision_id"]) for item in blockers]
            coordinator.update(
                {
                    "phase": "intent_review",
                    "state_status": "checkpoint_required",
                    "checkpoint_kind": "decision_resolution",
                    "customer_summary": (
                        "Blueprint-guided generation is waiting only on the returned "
                        "generation-relevant decisions. The posture transition did not "
                        "rewrite the Working Blueprint."
                    ),
                    "canonical_decision_inventory": intent_binding,
                    "pending_decision_resolution": {
                        "input_digest": review_input_digest,
                        "profile_id": profile_id,
                        "interpretation_summary": (
                            dict(review_input.get("proposed_interpretation") or {}).get("summary")
                            or dict(review_input.get("proposed_interpretation") or {}).get(
                                "normalized_goal"
                            )
                            or "Reviewed interpretation"
                        ),
                        "profile_answers": deepcopy(
                            dict(review_input.get("reviewed_profile_answers") or {})
                        ),
                        "constraints": list(constraints),
                        "non_goals": list(non_goals),
                        "accepted_unresolved_choices": list(accepted_unresolved_choices),
                        "authorized_dispositions": [
                            deepcopy(dict(item)) for item in normalized_dispositions
                        ],
                        "decision_records": deepcopy(records),
                        "blocking_decisions": blockers,
                        "blueprint_readiness_summary": readiness,
                        "awaiting_confirmation_fields": awaiting,
                        "retained_artifacts": retained,
                    },
                    "generation_context_outcome": {
                        "context_status": context_status,
                        "generation_context_pack_created": False,
                        "exploratory_generation_context_created": False,
                        "unresolved_decision_references": [
                            item["decision_ref"] for item in blockers
                        ],
                    },
                }
            )
            self._replace_coordinator(coordinator)
            return self._result(
                operation="prepare_generation",
                ok=True,
                state=self.store.read(),
                summary=coordinator["customer_summary"],
                elapsed=self.clock() - started,
                category=context_status,
                details={
                    "posture_transition_applied": True,
                    "working_blueprint_mutated": False,
                    "evolved_blueprint_created": False,
                    "generation_context_pack_created": False,
                    "decision_resolution": blockers,
                    "blueprint_readiness_summary": readiness,
                    "ide_write_or_run_authorized": False,
                },
                checkpoint_protocol={
                    "confirmation_transmission_state": "not_supplied",
                    "awaiting_confirmation_fields": awaiting,
                },
            )

        self._ensure_transition_parent_saved(
            "algorithm_intent_card", intent, "algorithm-intent-card.json"
        )
        self._ensure_transition_parent_saved(
            "working_blueprint", blueprint, "working-blueprint.json"
        )
        self._ensure_transition_parent_saved(
            "output_evidence_contract",
            output_contract,
            "output-evidence-contract.json",
        )
        unresolved_refs: list[str] = []
        pack_created = False
        exploratory_created = False
        if context_status == "exploratory_generation_context_ready":
            if (
                requested_posture != "exploratory_first_pass"
                or payload.get("generation_context_pack") is not None
                or payload.get("generation_context_pack_produced") is not False
            ):
                raise CurrentLoopError("protected_truth_insufficient")
            generation = self._response_artifact(payload, "exploratory_generation_context")
            self._save_artifact(
                "exploratory_generation_context",
                generation,
                "exploratory-generation-context.json",
            )
            exploratory_created = True
            unresolved_refs = [
                str(item["decision_ref"])
                for item in unpack_decision_record_set(blueprint["blueprint_decision_records"])
                if item.get("resolution_state") != "resolved"
            ]
            summary = (
                "Exploratory generation context is ready for this attempt without a "
                "full Generation Context Pack or Blueprint-readiness claim."
            )
        elif context_status == "generation_context_pack_ready":
            if (
                requested_posture != "blueprint_guided"
                or payload.get("generation_context_pack_produced") is not True
            ):
                raise CurrentLoopError("protected_truth_insufficient")
            generation = self._response_artifact(payload, "generation_context_pack")
            self._save_artifact(
                "generation_context_pack",
                generation,
                "generation-context-pack.json",
            )
            pack_created = True
            summary = "The full Generation Context Pack is ready."
        else:
            raise CurrentLoopError("protected_truth_insufficient")
        coordinator.update(
            {
                "phase": "generation_ready",
                "state_status": "checkpoint_required",
                "checkpoint_kind": "ide_write_or_run",
                "customer_summary": (f"{summary} IDE write/run authority remains separate."),
                "canonical_decision_inventory": intent_binding,
                "pending_decision_resolution": None,
                "generation_context_outcome": {
                    "context_status": context_status,
                    "generation_context_pack_created": pack_created,
                    "exploratory_generation_context_created": exploratory_created,
                    "unresolved_decision_references": unresolved_refs,
                },
            }
        )
        self._replace_coordinator(coordinator)
        return self._result(
            operation="prepare_generation",
            ok=True,
            state=self.store.read(),
            summary=coordinator["customer_summary"],
            elapsed=self.clock() - started,
            details={
                "posture_transition_applied": True,
                "working_blueprint_mutated": False,
                "evolved_blueprint_created": False,
                "context_status": context_status,
                "generation_context_pack_created": pack_created,
                "exploratory_generation_context_created": exploratory_created,
                "unresolved_decision_references": unresolved_refs,
                "ide_write_or_run_authorized": False,
            },
        )

    def _protected_call(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if self.local_only_surface:
            raise EvidenceProcessingError(
                "local_sidecar_hosted_operation_prohibited",
                origin="contract_or_authority",
            )
        if self.transport is None:
            raise EvidenceProcessingError(
                "protected_service_unavailable",
                origin="hosted_transport",
                deterministic=False,
            )
        started = self.clock()
        try:
            payload = self.transport.call(tool_name, arguments)
        except Exception as exc:
            raise EvidenceProcessingError(
                "protected_service_unavailable",
                origin="hosted_transport",
                deterministic=False,
                protected_call_attempted=True,
            ) from exc
        elapsed = max(0.0, self.clock() - started)
        self._record_protected_call(elapsed)
        if payload.get("ok") is False:
            category = str(payload.get("error_category") or "protected_operation_rejected")
            raise EvidenceProcessingError(
                category,
                origin="hosted_operation",
                deterministic=False,
                protected_call_attempted=True,
                protected_non_success=True,
            )
        return payload

    def _record_protected_call(self, elapsed: float) -> None:
        try:
            state = self.store.read()
        except CurrentLoopError:
            return
        coordinator = self._coordinator_state(state)
        coordinator["performance"]["protected_service_seconds"] += elapsed
        coordinator["performance"]["protected_tool_calls"] += 1
        self._replace_coordinator(coordinator)

    def _response_artifact(self, payload: Mapping[str, Any], field: str) -> dict[str, Any]:
        value = payload.get(field)
        if not isinstance(value, Mapping):
            raise CurrentLoopError("protected_truth_insufficient")
        result = deepcopy(dict(value))
        artifact_valid = artifact_digest_matches(result)
        supplied_consistency = result.get("consistency_digest")
        consistency_valid = isinstance(
            supplied_consistency, str
        ) and supplied_consistency == consistency_digest(result)
        if not artifact_valid and not consistency_valid:
            raise CurrentLoopError("protected_truth_insufficient")
        return result

    def _save_intent_review_artifact(self, artifact: Mapping[str, Any]) -> dict[str, Any]:
        digest = _artifact_digest(artifact)
        path = self.artifact_directory / f"algorithm-intent-review-{digest[:16]}.json"
        _atomic_exact_write(path, artifact)
        reloaded = _load_json_file(path)
        if reloaded != dict(artifact) or _artifact_digest(reloaded) != digest:
            raise CurrentLoopError("canonical_artifact_save_verification_failed")
        state = self.store.read()
        coordinator = self._coordinator_state(state)
        history = coordinator.setdefault("intent_review_artifacts", [])
        descriptor = {
            "artifact_reference": _artifact_reference(artifact),
            "artifact_digest": digest,
            "local_path": str(path),
            "confirmation_state": artifact.get("confirmation_state"),
        }
        if descriptor not in history:
            if len(history) >= 8:
                raise CurrentLoopError("intent_review_history_limit_exceeded")
            history.append(descriptor)
        self._replace_coordinator(coordinator)
        return {
            "saved": True,
            "artifact_digest": digest,
            "wrapper_added": False,
            "notes_added": False,
        }

    def _intent_review_input(
        self,
        *,
        profile_id: str,
        proposed_interpretation: Mapping[str, Any],
        requirements: Sequence[Mapping[str, Any]],
        constraints: Sequence[str],
        non_goals: Sequence[str],
        decision_dispositions: Sequence[Mapping[str, Any]],
        reviewed_profile_answers: Mapping[str, Any] | None,
        accepted_unresolved_choices: Sequence[str],
        generation_posture: str,
    ) -> dict[str, Any]:
        return {
            "profile_id": profile_id,
            "proposed_interpretation": deepcopy(dict(proposed_interpretation)),
            "requirements": [deepcopy(dict(item)) for item in requirements],
            "constraints": list(constraints),
            "non_goals": list(non_goals),
            "decision_dispositions": [deepcopy(dict(item)) for item in decision_dispositions],
            "reviewed_profile_answers": deepcopy(dict(reviewed_profile_answers or {})),
            "accepted_unresolved_choices": list(accepted_unresolved_choices),
            "generation_posture": generation_posture,
        }

    def _pending_intent_review(
        self,
        review_input: Mapping[str, Any],
        *,
        intent: Mapping[str, Any],
        confirmation_transmission_state: str,
        awaiting_confirmation_fields: Sequence[str],
    ) -> dict[str, Any]:
        interpretation = dict(review_input.get("proposed_interpretation") or {})
        answers = dict(review_input.get("reviewed_profile_answers") or {})
        for key, value in interpretation.items():
            if key not in {"summary", "provenance_role"}:
                answers.setdefault(key, value)
        profile_answers = [
            f"{key}={value if isinstance(value, str) else json.dumps(value, sort_keys=True)}"
            for key, value in sorted(answers.items())
        ]
        summary = interpretation.get("summary") or interpretation.get("normalized_goal")
        return {
            "input_digest": sha256(canonical_bytes(review_input)).hexdigest(),
            "profile_id": review_input.get("profile_id"),
            "interpretation_summary": (
                str(summary) if summary is not None else "Reviewed interpretation"
            ),
            "profile_answers": profile_answers,
            "constraints": list(review_input.get("constraints") or []),
            "non_goals": list(review_input.get("non_goals") or []),
            "intent_artifact_reference": _artifact_reference(intent),
            "intent_artifact_digest": _artifact_digest(intent),
            "intent_confirmation_state": intent.get("confirmation_state"),
            "confirmation_transmission_state": confirmation_transmission_state,
            "awaiting_confirmation_fields": list(awaiting_confirmation_fields),
        }

    def _intent_clarification_fields(
        self,
        intent: Mapping[str, Any],
    ) -> list[str]:
        result: list[str] = []
        for value in intent.get("unresolved_questions", []):
            if isinstance(value, str) and value and value not in result:
                result.append(value)
        for question in intent.get("profile_questions", []):
            if not isinstance(question, Mapping):
                continue
            value = question.get("field") or question.get("id") or question.get("question_id")
            if isinstance(value, str) and value and value not in result:
                result.append(value)
        return result or ["reviewed_interpretation"]

    def _hosted_clarification_values(
        self,
        intent: Mapping[str, Any],
        fields: Sequence[str],
    ) -> dict[str, Any] | None:
        containers = [
            intent,
            intent.get("proposed_interpretation"),
            intent.get("reviewed_profile_answers"),
            intent.get("profile_fields"),
            intent.get("clarification_values"),
        ]
        result: dict[str, Any] = {}
        for field in fields:
            found = False
            for container in containers:
                if isinstance(container, Mapping) and field in container:
                    result[field] = deepcopy(container[field])
                    found = True
                    break
            if not found:
                for question in intent.get("profile_questions", []):
                    if not isinstance(question, Mapping):
                        continue
                    identity = (
                        question.get("field") or question.get("id") or question.get("question_id")
                    )
                    if identity != field:
                        continue
                    for value_key in (
                        "value",
                        "proposed_value",
                        "presented_value",
                        "recommended_value",
                        "answer",
                    ):
                        if value_key in question:
                            result[field] = deepcopy(question[value_key])
                            found = True
                            break
                    if found:
                        break
            if not found:
                return None
        return result

    def _stage_held_prepare_generation_values(
        self,
        review_input: Mapping[str, Any],
        *,
        provenance: str,
    ) -> dict[str, Any]:
        fields = [
            {
                "name": name,
                "value": deepcopy(value),
                "provenance": provenance,
            }
            for name, value in sorted(review_input.items())
            if name
            in {
                "profile_id",
                "proposed_interpretation",
                "requirements",
                "constraints",
                "non_goals",
                "decision_dispositions",
                "reviewed_profile_answers",
                "accepted_unresolved_choices",
                "generation_posture",
            }
        ]
        for field in fields:
            if field["name"] == "generation_posture":
                field["name"] = "requested_generation_posture"
        state = self.store.read()
        coordinator = self._coordinator_state(state)
        construction = checkpoint_input_construction(
            operation="prepare_generation",
            checkpoint_kind="intent_review",
            workspace_binding=str(state["workspace_root"]),
            loop_ref=str(state["loop_ref"]),
            phase=str(coordinator["phase"]),
            expected_state_revision=int(state["state_revision"]),
            bounded_domains=self._checkpoint_input_bounded_domains(
                operation="prepare_generation",
                state=state,
            ),
        )
        payload: dict[str, Any] = {
            **deepcopy(construction["fixed_payload"]),
            "fields": fields,
        }
        raw = canonical_bytes(payload)
        payload["_transport_utf8_sha256"] = sha256(raw).hexdigest()
        payload["_transport_size_bytes"] = len(raw)
        return self.stage_checkpoint_input(
            operation=None,
            checkpoint_kind=None,
            payload=payload,
            transport="qcoder_held",
        )

    def _set_pending_intent_review(
        self,
        pending: Mapping[str, Any],
        *,
        summary: str,
    ) -> None:
        coordinator = self._coordinator_state(self.store.read())
        coordinator.update(
            {
                "phase": "intent_review",
                "state_status": "checkpoint_required",
                "checkpoint_kind": "intent_review",
                "customer_summary": summary,
                "pending_intent_review": deepcopy(dict(pending)),
            }
        )
        self._replace_coordinator(coordinator)

    def _save_pending_generation_artifact(
        self,
        role: str,
        artifact: Mapping[str, Any],
    ) -> dict[str, Any]:
        digest = _artifact_digest(artifact)
        path = self.artifact_directory / f"pending-{role}-{digest[:16]}.json"
        _atomic_exact_write(path, artifact)
        reloaded = _load_json_file(path)
        if reloaded != dict(artifact) or _artifact_digest(reloaded) != digest:
            raise CurrentLoopError("canonical_artifact_save_verification_failed")
        return {
            "role": role,
            "artifact_reference": _artifact_reference(artifact),
            "artifact_digest": digest,
            "local_record": path.name,
            "exact_protected_artifact_preserved": True,
        }

    def _decision_resolution_details(
        self,
        *,
        profile_id: str,
        blueprint: Mapping[str, Any],
        readiness: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        records = unpack_decision_record_set(blueprint["blueprint_decision_records"])
        by_ref = {str(item["decision_ref"]): item for item in records}
        definitions = {item["profile_decision_id"]: item for item in catalog_entries(profile_id)}
        blockers: list[dict[str, Any]] = []
        for decision_ref in readiness.get("blocking_decision_references") or []:
            record = by_ref.get(str(decision_ref))
            if record is None:
                raise CurrentLoopError("protected_truth_insufficient")
            definition = definitions.get(str(record.get("profile_decision_id")))
            if definition is None or definition.get("generation_relevant") is not True:
                raise CurrentLoopError("protected_truth_insufficient")
            current_value = (
                {
                    "selected_value": deepcopy(record.get("selected_value")),
                    "provenance_entries": deepcopy(record.get("provenance_entries") or []),
                }
                if record.get("selected_value") is not None
                else None
            )
            blockers.append(
                {
                    "decision_ref": decision_ref,
                    "profile_decision_id": record["profile_decision_id"],
                    "customer_meaning": definition["display_label"],
                    "question": definition["question"],
                    "current_attributable_value": current_value,
                    "profile_supported_alternatives": deepcopy(
                        definition.get("supported_alternatives") or []
                    ),
                    "applicable_actions": deepcopy(
                        readiness.get("applicable_user_controlled_actions") or []
                    ),
                    "may_defer": True,
                    "may_switch_attempt_to_exploratory_first_pass": True,
                }
            )
        return blockers, records

    def _record_posture_transition(
        self,
        coordinator: dict[str, Any],
        *,
        source_posture: str,
        requested_posture: str,
        reason: str,
        provenance: str,
    ) -> None:
        if requested_posture not in {"blueprint_guided", "exploratory_first_pass"}:
            raise CurrentLoopError("generation_posture_invalid")
        if provenance not in POSTURE_AUTHORITY_PROVENANCE:
            raise CurrentLoopError("posture_transition_provenance_invalid")
        clean_reason = " ".join(reason.split())
        if not clean_reason or len(clean_reason) > 500:
            raise CurrentLoopError("posture_transition_reason_invalid")
        history = coordinator.setdefault("posture_transition_history", [])
        if len(history) >= 16:
            raise CurrentLoopError("posture_transition_history_limit_exceeded")
        history.append(
            {
                "source_posture": source_posture,
                "requested_posture": requested_posture,
                "explicit_authority": True,
                "reason": clean_reason,
                "provenance": provenance,
                "timestamp_unix_seconds": int(time.time()),
                "working_blueprint_mutated": False,
                "evolved_blueprint_created": False,
                "decision_mutation": False,
            }
        )
        coordinator["effective_generation_posture"] = requested_posture

    def _save_artifact(
        self, role: str, artifact: Mapping[str, Any], filename: str
    ) -> dict[str, Any]:
        state = self.store.read()
        return save_exact_canonical_artifact(
            store=self.store,
            role=role,
            artifact=artifact,
            destination=self.artifact_directory / filename,
            expected_revision=state["state_revision"],
        )

    def _save_generation_parent_artifact(
        self,
        role: str,
        artifact: Mapping[str, Any],
        filename: str,
    ) -> dict[str, Any]:
        state = self.store.read()
        coordinator = self._coordinator_state(state)
        active = coordinator.get("active_generation_artifacts")
        if isinstance(active, Mapping) and isinstance(active.get(role), Mapping):
            current = self._saved_artifact(state, role)
            if current == dict(artifact):
                return deepcopy(dict(active[role]))
        if role not in state.get("saved_artifacts", {}):
            return self._save_artifact(role, artifact, filename)
        current = self._saved_artifact(state, role)
        if current == dict(artifact):
            return deepcopy(dict(state["saved_artifacts"][role]))
        digest = _artifact_digest(artifact)
        path = self.artifact_directory / f"{Path(filename).stem}-{digest[:16]}.json"
        _atomic_exact_write(path, artifact)
        reloaded = _load_json_file(path)
        if reloaded != dict(artifact) or _artifact_digest(reloaded) != digest:
            raise CurrentLoopError("canonical_artifact_save_verification_failed")
        descriptor = {
            "role": role,
            "artifact_reference": _artifact_reference(artifact),
            "artifact_digest": digest,
            "local_path": str(path),
            "status": "fresh",
            "generation_stage_revision": True,
            "prior_artifact_preserved": True,
        }
        active_artifacts = coordinator.setdefault("active_generation_artifacts", {})
        history = coordinator.setdefault("generation_parent_history", [])
        if len(history) >= 32:
            raise CurrentLoopError("generation_parent_history_limit_exceeded")
        history.append(
            {
                "role": role,
                "prior_artifact_digest": _artifact_digest(current),
                "next_artifact_digest": digest,
                "explicit_decision_authority_required": True,
                "posture_transition_only": False,
            }
        )
        active_artifacts[role] = descriptor
        self._replace_coordinator(coordinator)
        return deepcopy(descriptor)

    def _saved_artifact(self, state: Mapping[str, Any], role: str) -> dict[str, Any]:
        coordinator = self._coordinator_state(state)
        active = coordinator.get("active_generation_artifacts")
        descriptor = (
            active.get(role)
            if isinstance(active, Mapping) and isinstance(active.get(role), Mapping)
            else state.get("saved_artifacts", {}).get(role)
        )
        if not isinstance(descriptor, Mapping):
            raise CurrentLoopError("canonical_parent_set_incomplete")
        path = Path(str(descriptor.get("local_path") or ""))
        value = _load_json_file(path)
        if _artifact_digest(value) != descriptor.get("artifact_digest") or not path.exists():
            raise CurrentLoopError("canonical_artifact_modified")
        return value

    def _load_loop_instance_record(self, state: Mapping[str, Any]) -> dict[str, Any]:
        return _load_json_file(Path(state["loop_instance_record_path"]))

    def _python_manifestation(self, source_evidence: Mapping[str, Any]) -> dict[str, Any]:
        return with_artifact_digest(
            {
                "schema_id": "qcoder.python_manifestation.v1",
                "schema_version": 1,
                "artifact_type": "python_manifestation",
                "artifact_ref": _session_ref(),
                "selected_source_evidence_reference": {
                    "artifact_ref": _artifact_reference(source_evidence),
                    "digest": _artifact_digest(source_evidence),
                    "retrievable": False,
                },
                "framework_observation": source_evidence.get("framework_observation"),
                "parse_status": source_evidence.get("parse_status"),
                "evidence_coverage": source_evidence.get("evidence_coverage"),
                "represented_in_selected_source_evidence": True,
                "raw_source_included": False,
                "source_executed": False,
                "repository_scanned": False,
                "retention": "process_and_discard",
                "non_proofs": [
                    "Selected source evidence does not prove runtime behavior.",
                    "This manifestation does not prove source-to-circuit equivalence.",
                ],
            }
        )

    def _failed_result_manifestation(
        self,
        *,
        related_circuit_ref: str,
        safe_category: str,
    ) -> dict[str, Any]:
        bounded_category = (
            safe_category if safe_category in SAFE_LOCAL_FAILURE_CATEGORIES else "local_run_failed"
        )
        return with_artifact_digest(
            {
                "schema_id": "qcoder.result_manifestation.v1",
                "schema_version": 1,
                "artifact_type": "result_manifestation",
                "artifact_ref": _session_ref(),
                "related_circuit_ref": related_circuit_ref,
                "development_stage": "run_results",
                "stage_availability": "not_run",
                "representation_category": "failed_local_run",
                "safe_failure_category": bounded_category,
                "observed_outcome_count": 0,
                "observed_shot_count": 0,
                "raw_counts_included": False,
                "raw_error_included": False,
                "result_executed_by_qcoder": False,
                "design_selection_effect": "none",
                "retention": "process_and_discard",
                "non_proofs": [
                    "A failed local run does not supply Run Evidence.",
                    "Failure does not prove a circuit, source, backend, or environment defect.",
                ],
            }
        )

    def _related_circuit_reference(self, state: Mapping[str, Any], result_path: Path) -> str:
        if "circuit_manifestation" in state.get("saved_artifacts", {}):
            circuit = self._saved_artifact(state, "circuit_manifestation")
            return _artifact_reference(circuit)
        candidates = self._coordinator_state(state).get("artifact_candidates", [])
        for item in candidates:
            if item.get("path") == str(result_path) and isinstance(
                item.get("related_circuit_ref"), str
            ):
                return item["related_circuit_ref"]
        raise CurrentLoopError("result_related_circuit_ref_required")

    def _normalize_candidates(
        self, candidates: Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        if not candidates:
            raise CurrentLoopError("selected_artifact_set_invalid")
        normalized = []
        seen: set[str] = set()
        for candidate in candidates:
            role = candidate.get("role")
            if role not in AUTHORIZED_ARTIFACT_ROLES:
                raise CurrentLoopError("selected_artifact_role_invalid")
            path_value = candidate.get("path")
            if not isinstance(path_value, (str, Path)):
                raise CurrentLoopError("selected_artifact_path_invalid")
            path_text = str(path_value)
            if self._is_discovery_expression(path_text):
                raise CurrentLoopError("artifact_candidate_discovery_expression_invalid")
            if self._contains_qcoder_component(path_text):
                raise CurrentLoopError("qcoder_local_state_artifact_prohibited")
            path = Path(path_value).expanduser()
            if not path.is_absolute() or ".." in path.parts:
                raise CurrentLoopError("selected_artifact_path_invalid")
            path = path.absolute()
            try:
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise CurrentLoopError("artifact_candidate_file_required") from exc
            if self._contains_qcoder_component(str(resolved)):
                raise CurrentLoopError("qcoder_local_state_artifact_prohibited")
            if path.is_symlink():
                raise CurrentLoopError("selected_artifact_symlink_prohibited")
            if not path.is_file():
                raise CurrentLoopError("artifact_candidate_file_required")
            exact = str(path)
            if exact in seen:
                raise CurrentLoopError("selected_artifact_duplicate_path")
            seen.add(exact)
            provenance = candidate.get("provenance")
            if provenance == LEGACY_ARTIFACT_CANDIDATE_PROVENANCE:
                provenance = "user_selected"
            if provenance not in ARTIFACT_CANDIDATE_PROVENANCE:
                raise CurrentLoopError("artifact_candidate_provenance_invalid")
            external = not self._is_within_workspace(resolved)
            if external and candidate.get("explicit_external") is not True:
                raise CurrentLoopError("external_artifact_selection_required")
            display = (
                str(path.relative_to(self.workspace_root))
                if not external
                else f"external:{path.name}"
            )
            normalized.append(
                {
                    "role": role,
                    "artifact_type": str(candidate.get("artifact_type") or role)[:100],
                    "path": exact,
                    "display_path": display,
                    "external": external,
                    "provenance": provenance,
                    "related_circuit_ref": candidate.get("related_circuit_ref"),
                }
            )
        return normalized

    def _merge_artifact_candidates(
        self,
        existing: object,
        supplied: Sequence[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        merged: list[dict[str, Any]] = []
        by_path: dict[str, dict[str, Any]] = {}
        if isinstance(existing, Sequence) and not isinstance(existing, (str, bytes)):
            for item in existing:
                if not isinstance(item, Mapping):
                    raise CurrentLoopError("selected_artifact_set_invalid")
                value = deepcopy(dict(item))
                if value.get("provenance") == LEGACY_ARTIFACT_CANDIDATE_PROVENANCE:
                    value["provenance"] = "user_selected"
                path = str(value.get("path") or "")
                if not path:
                    raise CurrentLoopError("selected_artifact_path_invalid")
                by_path[path] = value
                merged.append(value)
        added_count = 0
        for item in supplied:
            value = deepcopy(dict(item))
            path = str(value["path"])
            previous = by_path.get(path)
            if previous is None:
                by_path[path] = value
                merged.append(value)
                added_count += 1
                continue
            if previous.get("provenance") != value.get("provenance"):
                raise CurrentLoopError("artifact_candidate_provenance_conflict")
            comparable_keys = (
                "role",
                "artifact_type",
                "external",
                "related_circuit_ref",
            )
            if any(previous.get(key) != value.get(key) for key in comparable_keys):
                raise CurrentLoopError("selected_artifact_duplicate_path")
        return merged, added_count

    @staticmethod
    def _visible_candidate_set(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "role": item["role"],
                "display_path": item["display_path"],
                "external": item["external"],
                "provenance": item["provenance"],
            }
            for item in candidates
        ]

    @staticmethod
    def _contains_qcoder_component(path_value: str) -> bool:
        normalized = path_value.replace("\\", "/")
        return any(part.casefold() == ".qcoder" for part in normalized.split("/"))

    @staticmethod
    def _is_discovery_expression(path_value: str) -> bool:
        return any(marker in path_value for marker in ("*", "?", "[", "]"))

    def _is_within_workspace(self, path: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(self.workspace_root.resolve(strict=False))
        except ValueError:
            return False
        return True

    def _decision_records(self, blueprint: Mapping[str, Any]) -> list[dict[str, Any]]:
        from qcoder.blueprint_decisions import unpack_decision_record_set

        if isinstance(blueprint.get("blueprint_decision_records"), Mapping):
            return unpack_decision_record_set(blueprint["blueprint_decision_records"])
        records = blueprint.get("decision_records")
        if isinstance(records, list):
            return [deepcopy(dict(item)) for item in records]
        raise CurrentLoopError("blueprint_decision_inventory_incomplete")

    def _proposed_update(
        self,
        selected: Mapping[str, Any],
        *,
        proposed_value: object,
        control_treatment: str,
    ) -> dict[str, Any]:
        result = deepcopy(dict(selected))
        result.update(
            {
                "control_treatment": control_treatment,
                "selected_value": deepcopy(proposed_value),
                "resolution_state": "resolved",
                "user_disposition": "selected_choice",
                "generation_effect": "non_blocking",
                "blueprint_representation_state": ("represented_in_derived_blueprint"),
                "unresolved_questions": [],
            }
        )
        result["provenance_entries"] = list(selected.get("provenance_entries", [])) + [
            {
                "role": "user_selected_carry_forward_treatment",
                "source_decision_ref": selected.get("decision_ref"),
            }
        ]
        return result

    def _current_parent_roles(self, current: Mapping[str, Any]) -> list[str]:
        references = current.get("artifact_references")
        if not isinstance(references, Mapping):
            raise CurrentLoopError("canonical_parent_set_incomplete")
        outcome = self._coordinator_state(self.store.read()).get("generation_context_outcome")
        generation_role = (
            "exploratory_generation_context"
            if isinstance(outcome, Mapping)
            and outcome.get("exploratory_generation_context_created") is True
            else "generation_context_pack"
        )
        mapping = {
            "request_baseline": "request_baseline_handoff",
            "working_blueprint": "working_blueprint",
            "generation_context": generation_role,
            "python_manifestation": "python_manifestation",
            "circuit_manifestation": "circuit_manifestation",
            "result_manifestation": "result_manifestation",
            "lineage": "decision_evidence_lineage",
        }
        return [mapping[name] for name in references if name in mapping]

    def _require_phase(self, operation: str, allowed: set[str]) -> dict[str, Any]:
        try:
            state = self.store.read()
        except CurrentLoopError as exc:
            raise CurrentLoopError(_ERROR_ALIASES.get(exc.category, exc.category)) from exc
        coordinator = self._coordinator_state(state)
        if coordinator["phase"] not in allowed:
            raise CurrentLoopError(f"{operation}_phase_invalid")
        return state

    @staticmethod
    def _require_contract_permission(
        state: Mapping[str, Any],
        *,
        category: str,
        dimension: str,
        artifact_reference: str | None = None,
    ) -> None:
        contract = state.get("current_loop_contract")
        if not isinstance(contract, Mapping) or not contract_permits(
            contract,
            category=category,
            dimension=dimension,
            artifact_reference=artifact_reference,
        ):
            raise CurrentLoopContractError("current_loop_contract_policy_prohibited")

    def _initial_coordinator_state(
        self,
        *,
        phase: str,
        state_status: str,
        checkpoint_kind: str,
        summary: str,
    ) -> dict[str, Any]:
        return {
            "schema_id": COORDINATOR_STATE_SCHEMA_ID,
            "schema_version": COORDINATOR_STATE_SCHEMA_VERSION,
            "phase": phase,
            "state_status": state_status,
            "checkpoint_kind": checkpoint_kind,
            "customer_summary": summary,
            "artifact_candidates": [],
            "evidence_processing_complete": False,
            "hosted_enrichment_status": "not_offered",
            "active_recovery": None,
            "recovery_history": [],
            "consequence_projection": None,
            "authority_separation": {
                "qcoder_activation": "explicit_user_authority",
                "ide_write_or_run": "owned_by_ide_host_not_qcoder",
                "artifact_review": "separate_exact_set_authorization",
            },
            "performance": {
                "schema_id": PERFORMANCE_SCHEMA_ID,
                "schema_version": 1,
                "assistant_orchestration_seconds": 0.0,
                "coordinator_seconds": 0.0,
                "local_extraction_seconds": 0.0,
                "protected_service_seconds": 0.0,
                "ide_write_or_run_seconds": 0.0,
                "human_review_seconds": 0.0,
                "retries": 0,
                "duplicate_calls": 0,
                "user_visible_checkpoints": 1 if checkpoint_kind != "none" else 0,
                "protected_tool_calls": 0,
                "coordinator_calls": 0,
                "manual_serialization_actions": 0,
                "customer_telemetry_emitted": False,
            },
            "assistant_reconstruction_allowed": False,
            "customer_serialization_required": False,
            "protected_payload_retained": False,
            "effective_generation_posture": None,
            "posture_transition_history": [],
            "pending_decision_resolution": None,
            "generation_context_outcome": None,
            "active_generation_artifacts": {},
            "generation_parent_history": [],
            "pending_checkpoint_input": None,
            "checkpoint_input_history": [],
            "next_loop_branch": None,
        }

    def _coordinator_state(self, state: Mapping[str, Any]) -> dict[str, Any]:
        coordinator = state.get("coordinator")
        if not isinstance(coordinator, Mapping):
            return self._initial_coordinator_state(
                phase="activated",
                state_status="ready",
                checkpoint_kind="none",
                summary="A current loop is active.",
            )
        result = deepcopy(dict(coordinator))
        if result.get("schema_id") in {
            PREVIOUS_COORDINATOR_STATE_SCHEMA_ID,
            *OLDER_COORDINATOR_STATE_SCHEMA_IDS,
        } and result.get("schema_version") in {1, 2, 3, 4, 5, 6, 7, 8}:
            result["schema_id"] = COORDINATOR_STATE_SCHEMA_ID
            result["schema_version"] = COORDINATOR_STATE_SCHEMA_VERSION
            result.setdefault("effective_generation_posture", state.get("generation_posture"))
            result.setdefault("posture_transition_history", [])
            result.setdefault("pending_decision_resolution", None)
            result.setdefault("generation_context_outcome", None)
            result.setdefault("active_generation_artifacts", {})
            result.setdefault("generation_parent_history", [])
            result.setdefault("evidence_processing_complete", False)
            result.setdefault("hosted_enrichment_status", "not_offered")
            result.setdefault("active_recovery", None)
            result.setdefault("recovery_history", [])
            result.setdefault("pending_checkpoint_input", None)
            result.setdefault("checkpoint_input_history", [])
            result.setdefault("next_loop_branch", None)
            for candidate in result.get("artifact_candidates", []):
                if (
                    isinstance(candidate, dict)
                    and candidate.get("provenance") == LEGACY_ARTIFACT_CANDIDATE_PROVENANCE
                ):
                    candidate["provenance"] = "user_selected"
        result.setdefault("effective_generation_posture", state.get("generation_posture"))
        result.setdefault("posture_transition_history", [])
        result.setdefault("pending_decision_resolution", None)
        result.setdefault("generation_context_outcome", None)
        result.setdefault("active_generation_artifacts", {})
        result.setdefault("generation_parent_history", [])
        result.setdefault("evidence_processing_complete", False)
        result.setdefault("hosted_enrichment_status", "not_offered")
        result.setdefault("active_recovery", None)
        result.setdefault("recovery_history", [])
        result.setdefault("pending_checkpoint_input", None)
        result.setdefault("checkpoint_input_history", [])
        result.setdefault("next_loop_branch", None)
        if (
            result.get("schema_id") != COORDINATOR_STATE_SCHEMA_ID
            or result.get("schema_version") != COORDINATOR_STATE_SCHEMA_VERSION
            or result.get("phase") not in PHASES
            or result.get("state_status") not in STATE_STATUSES
            or result.get("checkpoint_kind") not in CHECKPOINT_KINDS
        ):
            raise CurrentLoopError("current_loop_state_corrupt")
        if result.get("effective_generation_posture") not in {
            None,
            "blueprint_guided",
            "exploratory_first_pass",
        }:
            raise CurrentLoopError("current_loop_state_corrupt")
        if not isinstance(result.get("posture_transition_history"), list):
            raise CurrentLoopError("current_loop_state_corrupt")
        if not isinstance(result.get("evidence_processing_complete"), bool):
            raise CurrentLoopError("current_loop_state_corrupt")
        if result.get("hosted_enrichment_status") not in {
            "not_offered",
            "available",
            "in_progress",
            "completed",
            "rejected",
            "unavailable",
            "skipped",
            "declined",
        }:
            raise CurrentLoopError("current_loop_state_corrupt")
        if result.get("active_recovery") is not None and not isinstance(
            result.get("active_recovery"), Mapping
        ):
            raise CurrentLoopError("current_loop_state_corrupt")
        if not isinstance(result.get("recovery_history"), list):
            raise CurrentLoopError("current_loop_state_corrupt")
        if result.get("pending_checkpoint_input") is not None and not isinstance(
            result.get("pending_checkpoint_input"), Mapping
        ):
            raise CurrentLoopError("current_loop_state_corrupt")
        if not isinstance(result.get("checkpoint_input_history"), list):
            raise CurrentLoopError("current_loop_state_corrupt")
        return result

    def _replace_coordinator(self, coordinator: Mapping[str, Any]) -> None:
        phase = coordinator.get("phase")
        if phase not in PHASES:
            raise CurrentLoopError("coordinator_phase_invalid")
        state = self.store.read()
        current = self._coordinator_state(state)
        previous_phase = current["phase"]
        if (
            previous_phase != phase
            and phase not in _PHASE_TRANSITIONS.get(previous_phase, ())
            and not (previous_phase == "activated" and phase == "generation_ready")
        ):
            raise CurrentLoopError("coordinator_transition_invalid")
        updated = deepcopy(dict(coordinator))
        performance = updated["performance"]
        if updated["checkpoint_kind"] != "none" and (
            current.get("checkpoint_kind") != updated["checkpoint_kind"]
            or current.get("phase") != updated["phase"]
        ):
            performance["user_visible_checkpoints"] += 1

        def mutator(value: dict[str, Any]) -> Mapping[str, Any]:
            value["coordinator"] = updated
            value["next_operation"] = (
                _PHASE_TRANSITIONS[updated["phase"]][0]
                if _PHASE_TRANSITIONS[updated["phase"]]
                else None
            )
            return value

        self.store.update(mutator, expected_revision=state["state_revision"])

    def _saved_references(self, state: Mapping[str, Any]) -> list[dict[str, Any]]:
        result = []
        for role, descriptor in sorted(state.get("saved_artifacts", {}).items()):
            if not isinstance(descriptor, Mapping):
                continue
            result.append(
                {
                    "role": role,
                    "artifact_reference": descriptor.get("artifact_reference"),
                    "artifact_digest": descriptor.get("artifact_digest"),
                    "status": descriptor.get("status"),
                }
            )
        active = self._coordinator_state(state).get("active_generation_artifacts")
        if isinstance(active, Mapping):
            for role, descriptor in sorted(active.items()):
                if not isinstance(descriptor, Mapping):
                    continue
                result = [item for item in result if item.get("role") != role]
                result.append(
                    {
                        "role": role,
                        "artifact_reference": descriptor.get("artifact_reference"),
                        "artifact_digest": descriptor.get("artifact_digest"),
                        "status": descriptor.get("status"),
                        "generation_stage_revision": True,
                    }
                )
        return result

    def _current_seed_inputs(
        self,
        state: Mapping[str, Any],
    ) -> tuple[str, dict[str, str]]:
        seed_descriptor = state.get("saved_artifacts", {}).get("next_loop_seed")
        if not isinstance(seed_descriptor, Mapping):
            raise CurrentLoopError("next_loop_seed_missing")
        seed_path = seed_descriptor.get("local_path")
        if not isinstance(seed_path, str):
            raise CurrentLoopError("next_loop_seed_missing")
        seed = _load_json_file(Path(seed_path))
        inventory = seed.get("required_parent_artifact_inventory")
        if not isinstance(inventory, list):
            raise CurrentLoopError("next_loop_seed_invalid")
        saved = [
            descriptor
            for descriptor in state.get("saved_artifacts", {}).values()
            if isinstance(descriptor, Mapping)
        ]
        parents: dict[str, str] = {}
        for required in inventory:
            if not isinstance(required, Mapping):
                raise CurrentLoopError("next_loop_seed_invalid")
            artifact_role = required.get("artifact_role")
            reference = required.get("artifact_reference")
            digest = required.get("artifact_digest")
            matched = next(
                (
                    descriptor
                    for descriptor in saved
                    if descriptor.get("artifact_reference") == reference
                    and descriptor.get("artifact_digest") == digest
                    and isinstance(descriptor.get("local_path"), str)
                ),
                None,
            )
            if not isinstance(artifact_role, str) or matched is None:
                raise CurrentLoopError("next_loop_seed_parent_set_incomplete")
            parents[artifact_role] = str(matched["local_path"])
        return seed_path, parents

    def _checkpoint_protocol(
        self,
        *,
        operation: str,
        phase: str,
        state_status: str,
        checkpoint_kind: str,
        category: str | None,
        coordinator: Mapping[str, Any] | None,
        override: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        protocol: dict[str, Any] = {
            "supported_next_action": None,
            "next_invocation": None,
            "required_authority_input": None,
            "awaiting_confirmation_fields": [],
            "confirmation_transmission_state": "not_applicable",
            "identical_repeat_prohibited": False,
            "permitted_input_source": None,
            "input_source_disposition": None,
            "bounded_input_semantics": None,
            "required_authority_disposition": None,
            "protocol_binding": None,
            "prohibited_derivations": [
                "conversation_reconstruction",
                "transcript_search",
                "source_or_package_inspection",
                "qcoder_local_state_inspection",
            ],
            "no_action_reason": None,
            "no_action_disposition": None,
            "terminal": phase in {"completed", "abandoned"},
        }
        if operation == "standalone_review" and state_status == "ready":
            protocol["no_action_reason"] = "bounded_single_capability_complete"
            protocol["terminal"] = True
            return protocol
        if phase in {"completed", "abandoned"}:
            protocol["no_action_reason"] = f"current_loop_{phase}_terminal"
            return protocol
        if phase == "activated" and state_status == "ready":
            protocol.update(
                {
                    "supported_next_action": "select_generation_posture_or_stop",
                    "next_invocation": _invocation_template(
                        "activate",
                        required_flags=(
                            "--posture",
                            "--approve-posture",
                            "--posture-provenance",
                        ),
                        reused_inputs=("canonical_request_baseline",),
                        new_inputs=("explicit_generation_posture_authority",),
                        argument_values=(
                            {
                                "flag": "--posture",
                                "value_source": "explicit_bounded_customer_choice",
                                "allowed_values": list(GENERATION_POSTURES),
                            },
                        ),
                    ),
                    "required_authority_input": _authority_input(
                        "--approve-posture",
                        "Transmit only an explicit attributed generation-posture decision.",
                    ),
                    "permitted_input_source": (
                        "explicit_customer_bounded_posture_choice_or_explicitly_accepted_"
                        "supported_recommendation"
                    ),
                }
            )
            return protocol
        if phase == "intent_review" and state_status == "ready":
            protocol.update(
                {
                    "supported_next_action": "stage_exact_intent_checkpoint_input",
                    "next_invocation": _checkpoint_input_stage_invocation(
                        "prepare_generation", "intent_review"
                    ),
                    "permitted_input_source": (
                        "explicit_user_text_or_attributed_assistant_proposal"
                    ),
                }
            )
            return protocol
        if phase == "generation_ready" and state_status == "ready":
            protocol.update(
                {
                    "supported_next_action": "obtain_separate_ide_write_or_run_authority",
                    "next_invocation": _invocation_template(
                        "record-ide-authority",
                        required_flags=("--allow", "--explicit"),
                        new_inputs=("explicit_ide_write_or_run_authority",),
                    ),
                    "required_authority_input": _authority_input(
                        "--allow",
                        "Authorize only the IDE host's requested write or run operation.",
                        additional_flags=("--explicit",),
                    ),
                    "permitted_input_source": "explicit_user_authority",
                }
            )
            return protocol
        if phase == "awaiting_local_artifacts" and state_status == "ready":
            protocol.update(
                {
                    "supported_next_action": (
                        "perform_authorized_ide_work_and_register_exact_paths"
                    ),
                    "next_invocation": _artifact_handoff_invocation_template(),
                    "required_authority_input": None,
                    "awaiting_confirmation_fields": [],
                    "confirmation_transmission_state": "confirmed",
                    "identical_repeat_prohibited": False,
                    "permitted_input_source": (
                        "exact_ide_create_or_modify_result_or_exact_user_selection"
                    ),
                }
            )
            return protocol
        if phase == "evidence_processing" and state_status == "ready":
            processing_complete = (
                isinstance(coordinator, Mapping)
                and coordinator.get("evidence_processing_complete") is True
            )
            protocol.update(
                {
                    "supported_next_action": (
                        "review_current_build"
                        if processing_complete
                        else "process_exact_authorized_artifacts"
                    ),
                    "next_invocation": _invocation_template(
                        ("review-build" if processing_complete else "process-authorized-artifacts"),
                        alternatives=(
                            (
                                "enrich-authorized-evidence",
                                "decline-build-review",
                                "evidence-view",
                            )
                            if processing_complete
                            else ()
                        ),
                        reused_inputs=(
                            (
                                "exact_saved_current_build_evidence"
                                if processing_complete
                                else "exact_approved_artifact_set"
                            ),
                        ),
                        uses_transport=processing_complete,
                    ),
                }
            )
            protocol["permitted_input_source"] = "exact_authorized_local_artifact_set"
            if processing_complete:
                protocol["build_review_optional"] = True
                protocol["decline_blocks_loop_completion"] = False
            return protocol
        if phase == "current_build_review" and state_status == "ready":
            protocol.update(
                {
                    "supported_next_action": "review_current_build",
                    "next_invocation": _invocation_template(
                        "review-build",
                        reused_inputs=("exact_saved_current_build_evidence",),
                        uses_transport=True,
                    ),
                }
            )
            protocol["permitted_input_source"] = "exact_saved_current_build_evidence"
            return protocol
        if phase == "next_loop_ready" and state_status == "ready":
            branch = (
                coordinator.get("next_loop_branch") if isinstance(coordinator, Mapping) else None
            )
            protocol.update(
                {
                    "supported_next_action": "start_next_or_stop",
                    "next_invocation": _invocation_template(
                        "start-next",
                        required_flags=(
                            "--next-workspace",
                            "--posture",
                            "--use-current-seed",
                            "--approve",
                        ),
                        reused_inputs=("exact_next_loop_seed", "exact_named_parent_artifacts"),
                        new_inputs=(
                            "next_workspace",
                            "generation_posture",
                            "explicit_next_loop_activation",
                        ),
                    ),
                    "required_authority_input": _authority_input(
                        "--approve",
                        "Explicitly activate only the selected next loop.",
                    ),
                    "awaiting_confirmation_fields": ["next_loop_activation"],
                    "confirmation_transmission_state": "not_supplied",
                    "permitted_input_source": (
                        "qcoder_supplied_canonical_references_plus_explicit_next_"
                        "workspace_bounded_posture_and_authority"
                    ),
                    "stop_option": {
                        "supported": True,
                        "requires_invocation": False,
                        "no_further_action_required": True,
                    },
                    "completed_build_branch": deepcopy(
                        dict(branch) if isinstance(branch, Mapping) else {}
                    ),
                    "propose_change_available_for_completed_build": False,
                    "source_or_state_discovery_required": False,
                }
            )
            return protocol
        if phase == "artifact_authorization" and state_status == "ready":
            protocol.update(
                {
                    "supported_next_action": "obtain_exact_artifact_set_authorization",
                    "next_invocation": _invocation_template(
                        "authorize-artifacts",
                        required_flags=("--action", "--provenance"),
                        reused_inputs=("exact_visible_artifact_candidates",),
                        new_inputs=("explicit_exact_set_action",),
                    ),
                    "required_authority_input": _authority_input(
                        "--action", "Authorize only the complete visible exact set."
                    ),
                    "permitted_input_source": "explicit_user_exact_set_action",
                }
            )
            return protocol
        if phase == "continuation_choice" and state_status == "ready":
            protocol.update(
                {
                    "supported_next_action": "stage_exact_continuation_choice",
                    "next_invocation": _invocation_template(
                        None,
                        alternatives=(
                            "stage-checkpoint-input for continue_unchanged",
                            "stage-checkpoint-input for propose_change",
                        ),
                    ),
                    "required_authority_input": _authority_input(
                        None, "Choose one exact continuation branch."
                    ),
                    "permitted_input_source": "explicit_user_continuation_choice",
                }
            )
            return protocol
        if phase == "change_confirmation" and state_status == "ready":
            protocol.update(
                {
                    "supported_next_action": "stage_exact_proposal_confirmation_or_decline",
                    "next_invocation": _invocation_template(
                        None,
                        alternatives=(
                            "stage-checkpoint-input for confirm_change",
                            "stage-checkpoint-input for continue_unchanged with explicit decline",
                        ),
                    ),
                    "required_authority_input": _authority_input(
                        None, "Confirm or decline only the exact displayed proposal."
                    ),
                    "permitted_input_source": "explicit_user_proposal_decision",
                }
            )
            return protocol
        if state_status != "checkpoint_required":
            protocol["no_action_reason"] = f"state_status_{state_status}_requires_bounded_recovery"
            return protocol

        protocol["identical_repeat_prohibited"] = True
        if checkpoint_kind == "checkpoint_input_review":
            pending = (
                coordinator.get("pending_checkpoint_input")
                if isinstance(coordinator, Mapping)
                else None
            )
            fields = [
                str(item.get("name"))
                for item in (pending.get("fields", []) if isinstance(pending, Mapping) else [])
                if isinstance(item, Mapping)
            ]
            protocol.update(
                {
                    "supported_next_action": "review_staged_checkpoint_input",
                    "next_invocation": _checkpoint_input_approval_invocation(),
                    "required_authority_input": _authority_input(
                        "--approve",
                        (
                            "Approve only the complete exact qCoder-displayed staged "
                            "values; correction requires a new staged input."
                        ),
                    ),
                    "awaiting_confirmation_fields": fields,
                    "confirmation_transmission_state": "not_supplied",
                    "permitted_input_source": (
                        "authority_only_for_approval_or_new_stdin_or_file_for_correction"
                    ),
                    "identical_repeat_prohibited": True,
                }
            )
        elif checkpoint_kind == "activation_request_baseline_review":
            protocol.update(
                {
                    "supported_next_action": (
                        "present_exact_request_baseline_and_obtain_activation_approval"
                    ),
                    "next_invocation": _invocation_template(
                        "activate",
                        required_flags=("--approve",),
                        reused_inputs=("pending_exact_request_capture",),
                        new_inputs=(
                            "explicit_qcoder_activation",
                            "exact_request_baseline_approval",
                        ),
                    ),
                    "required_authority_input": _authority_input(
                        "--approve",
                        (
                            "Approve qCoder activation and canonical preservation of the "
                            "complete displayed customer message exactly as captured."
                        ),
                    ),
                    "awaiting_confirmation_fields": [
                        "qcoder_activation",
                        "exact_request_baseline_preservation",
                    ],
                    "confirmation_transmission_state": "not_supplied",
                    "permitted_input_source": "explicit_user_activation_and_exact_baseline_approval",
                }
            )
        elif checkpoint_kind == "posture":
            if category == "posture_transition_authority_required":
                protocol.update(
                    {
                        "supported_next_action": ("obtain_separate_generation_posture_authority"),
                        "next_invocation": _invocation_template(
                            "prepare-generation",
                            required_flags=(
                                "--use-current-intent",
                                "--posture",
                                "--approve-posture-change",
                                "--posture-provenance",
                            ),
                            reused_inputs=("qcoder_held_current_intent",),
                            new_inputs=("explicit_bounded_generation_posture_choice",),
                            argument_values=(
                                {
                                    "flag": "--posture",
                                    "value_source": "explicit_bounded_customer_choice",
                                    "allowed_values": list(GENERATION_POSTURES),
                                },
                            ),
                        ),
                        "required_authority_input": _authority_input(
                            "--approve-posture-change",
                            "Transmit only the explicit bounded posture choice.",
                            additional_flags=("--posture", "--posture-provenance"),
                        ),
                        "awaiting_confirmation_fields": ["generation_posture_transition"],
                        "confirmation_transmission_state": "not_supplied",
                        "permitted_input_source": (
                            "explicit_user_transition_or_explicitly_accepted_recommendation"
                        ),
                    }
                )
                if override:
                    for key in protocol:
                        if key in override:
                            protocol[key] = deepcopy(override[key])
                return protocol
            already_activated = (
                isinstance(coordinator, Mapping)
                and isinstance(coordinator.get("activation"), Mapping)
                and coordinator["activation"].get("explicit") is True
            )
            protocol.update(
                {
                    "supported_next_action": (
                        "obtain_separate_generation_posture_authority"
                        if already_activated
                        else "stage_exact_request_before_activation"
                    ),
                    "next_invocation": (
                        _invocation_template(
                            "activate",
                            required_flags=(
                                "--posture",
                                "--approve-posture",
                                "--posture-provenance",
                            ),
                            reused_inputs=("canonical_request_baseline",),
                            new_inputs=(
                                "generation_posture_selection",
                                "explicit_posture_authority",
                                "posture_authority_provenance",
                            ),
                            argument_values=(
                                {
                                    "flag": "--posture",
                                    "value_source": "explicit_bounded_customer_choice",
                                    "allowed_values": list(GENERATION_POSTURES),
                                },
                            ),
                        )
                        if already_activated
                        else _invocation_template(
                            "activate",
                            required_flags=("--request-stdin",),
                            new_inputs=("complete_governing_customer_message",),
                        )
                    ),
                    "required_authority_input": (
                        _authority_input(
                            "--approve-posture",
                            ("Transmit the user's separate explicit generation-posture decision."),
                            additional_flags=("--posture", "--posture-provenance"),
                        )
                        if already_activated
                        else _authority_input(
                            None,
                            (
                                "First stage and display the exact Request Baseline; "
                                "posture authority remains separate."
                            ),
                        )
                    ),
                    "awaiting_confirmation_fields": (
                        ["generation_posture"]
                        if already_activated
                        else ["exact_request_baseline_capture"]
                    ),
                    "confirmation_transmission_state": "not_supplied",
                    "permitted_input_source": (
                        "explicit_customer_bounded_posture_choice_or_explicitly_accepted_"
                        "supported_recommendation"
                        if already_activated
                        else "complete_customer_message_via_exact_request_capture_transport"
                    ),
                }
            )
        elif checkpoint_kind == "decision_resolution":
            pending_resolution = (
                coordinator.get("pending_decision_resolution")
                if isinstance(coordinator, Mapping)
                else None
            )
            protocol.update(
                {
                    "supported_next_action": "stage_exact_decision_resolution_or_switch_posture",
                    "next_invocation": _checkpoint_input_stage_invocation(
                        "prepare_generation", "decision_resolution"
                    ),
                    "required_authority_input": _authority_input(
                        None,
                        (
                            "Stage the exact proposed dispositions for display first; "
                            "authority is transmitted only after that review."
                        ),
                    ),
                    "awaiting_confirmation_fields": list(
                        (override or {}).get(
                            "awaiting_confirmation_fields",
                            (
                                pending_resolution.get("awaiting_confirmation_fields", [])
                                if isinstance(pending_resolution, Mapping)
                                else []
                            ),
                        )
                    ),
                    "confirmation_transmission_state": "not_supplied",
                    "permitted_input_source": (
                        "explicit_user_disposition_or_explicitly_accepted_assistant_recommendation"
                    ),
                }
            )
        elif checkpoint_kind == "activation":
            subcommand = "start-next" if operation == "start_next" else "activate"
            protocol.update(
                {
                    "supported_next_action": "obtain_explicit_qcoder_activation",
                    "next_invocation": _invocation_template(
                        subcommand,
                        required_flags=("--approve",),
                        reused_inputs=("current_activation_request",),
                        new_inputs=("explicit_qcoder_activation",),
                    ),
                    "required_authority_input": _authority_input(
                        "--approve",
                        "Explicitly activate qCoder for this current build.",
                    ),
                    "awaiting_confirmation_fields": ["qcoder_activation"],
                    "confirmation_transmission_state": "not_supplied",
                    "permitted_input_source": (
                        "explicit_user_authority_only_for_qcoder_held_activation_request"
                    ),
                }
            )
        elif checkpoint_kind == "intent_review":
            pending = (
                coordinator.get("pending_intent_review")
                if isinstance(coordinator, Mapping)
                else None
            )
            clarification = category in {
                "intent_clarification_required",
                "intent_clarification_unchanged",
            }
            protocol.update(
                {
                    "supported_next_action": (
                        "stage_exact_intent_correction_for_review"
                        if clarification
                        else "stage_exact_intent_interpretation_for_review"
                    ),
                    "next_invocation": _checkpoint_input_stage_invocation(
                        "prepare_generation", "intent_review"
                    ),
                    "required_authority_input": _authority_input(
                        None,
                        (
                            "Stage and display the complete exact interpretation first. "
                            "Conversational approval alone is not canonical authority."
                        ),
                    ),
                    "awaiting_confirmation_fields": list(
                        (override or {}).get(
                            "awaiting_confirmation_fields",
                            ["reviewed_interpretation", "explicit_intent_confirmation"],
                        )
                    ),
                    "confirmation_transmission_state": (
                        "supplied"
                        if clarification
                        else (
                            "not_supplied"
                            if category == "confirmation_not_transmitted"
                            else "not_supplied"
                        )
                    ),
                    "permitted_input_source": (
                        "qcoder_hosted_presented_values_or_explicit_user_correction"
                        if clarification
                        else "attributed_assistant_proposal_and_explicit_user_text"
                    ),
                }
            )
        elif checkpoint_kind == "ide_write_or_run":
            protocol.update(
                {
                    "supported_next_action": "obtain_separate_ide_write_or_run_authority",
                    "next_invocation": _invocation_template(
                        "record-ide-authority",
                        required_flags=("--allow", "--explicit"),
                        new_inputs=("explicit_ide_write_or_run_authority",),
                    ),
                    "required_authority_input": _authority_input(
                        "--allow",
                        "Authorize the IDE host to write or run for this build.",
                        additional_flags=("--explicit",),
                    ),
                    "awaiting_confirmation_fields": ["ide_write_or_run_authority"],
                    "confirmation_transmission_state": "not_supplied",
                    "permitted_input_source": "explicit_user_authority_only",
                }
            )
        elif checkpoint_kind == "artifact_review":
            candidates = (
                [
                    deepcopy(dict(item))
                    for item in coordinator.get("artifact_candidates", [])
                    if isinstance(item, Mapping)
                ]
                if isinstance(coordinator, Mapping)
                else []
            )
            next_invocation = _invocation_template(
                "authorize-artifacts",
                required_flags=("--action", "--provenance"),
                reused_inputs=("exact_visible_artifact_candidates",),
                new_inputs=("exact_artifact_review_action",),
                alternatives=(
                    "approve_all",
                    "remove_one",
                    "add_one_explicitly",
                    "decline",
                ),
            )
            next_invocation["visible_candidate_set"] = self._visible_candidate_set(candidates)
            next_invocation["hidden_candidates_permitted"] = False
            protocol.update(
                {
                    "supported_next_action": "obtain_exact_artifact_set_authorization",
                    "next_invocation": next_invocation,
                    "required_authority_input": _authority_input(
                        "--action",
                        "Approve, adjust, or decline the exact visible artifact set.",
                    ),
                    "awaiting_confirmation_fields": ["exact_artifact_review_action"],
                    "confirmation_transmission_state": "not_supplied",
                    "permitted_input_source": (
                        "explicit_user_bounded_exact_set_action_on_qcoder_displayed_candidates"
                    ),
                }
            )
        elif checkpoint_kind == "governing_change_confirmation":
            if operation == "continue_unchanged":
                next_invocation = _checkpoint_input_stage_invocation(
                    "continue_unchanged", "governing_change_confirmation"
                )
                supported_action = "stage_exact_unchanged_continuation_for_review"
            else:
                next_invocation = _invocation_template(
                    None,
                    alternatives=(
                        "stage-checkpoint-input for confirm_change",
                        "stage-checkpoint-input for continue_unchanged with explicit decline",
                    ),
                    reused_inputs=("exact_carry_forward_proposal",),
                )
                supported_action = "stage_exact_proposal_confirmation_or_decline"
            protocol.update(
                {
                    "supported_next_action": supported_action,
                    "next_invocation": next_invocation,
                    "required_authority_input": _authority_input(
                        None,
                        (
                            "Stage the exact governing choice first; promotion authority "
                            "is separate and contains no repeated free text."
                        ),
                    ),
                    "awaiting_confirmation_fields": ["governing_change_or_unchanged_continuation"],
                    "confirmation_transmission_state": "not_supplied",
                    "permitted_input_source": "explicit_user_governing_choice",
                }
            )
        elif phase == "continuation_choice":
            protocol.update(
                {
                    "supported_next_action": "stage_exact_continuation_choice",
                    "next_invocation": _invocation_template(
                        None,
                        alternatives=(
                            "stage-checkpoint-input for continue_unchanged",
                            "stage-checkpoint-input for propose_change",
                        ),
                        reused_inputs=("current_build_review", "working_blueprint"),
                        new_inputs=("exact_proposed_continuation_values",),
                    ),
                    "required_authority_input": _authority_input(
                        None,
                        (
                            "Stage and review unchanged continuation or one bounded "
                            "proposal selection before authority is transmitted."
                        ),
                    ),
                    "awaiting_confirmation_fields": ["continuation_choice"],
                    "confirmation_transmission_state": "not_supplied",
                    "permitted_input_source": "explicit_user_continuation_choice",
                }
            )
        else:
            protocol.update(
                {
                    "supported_next_action": "stop_and_present_checkpoint",
                    "next_invocation": _invocation_template(None),
                    "required_authority_input": _authority_input(
                        None,
                        _CHECKPOINT_AUTHORITY[checkpoint_kind],
                    ),
                    "awaiting_confirmation_fields": [checkpoint_kind],
                    "confirmation_transmission_state": "not_supplied",
                    "permitted_input_source": "explicit_user_checkpoint_authority",
                }
            )
        if override:
            for key in protocol:
                if key in override:
                    protocol[key] = deepcopy(override[key])
        if protocol["confirmation_transmission_state"] not in (CONFIRMATION_TRANSMISSION_STATES):
            raise CurrentLoopError("confirmation_transmission_state_invalid")
        return protocol

    def _attach_checkpoint_input_constructions(
        self,
        *,
        state: Mapping[str, Any],
        phase: str,
        protocol: Mapping[str, Any],
    ) -> dict[str, Any]:
        completed = deepcopy(dict(protocol))
        disposition = completed.get("input_source_disposition")
        categories = disposition.get("categories", []) if isinstance(disposition, Mapping) else []
        if "checkpoint_input_transport" not in categories:
            completed["checkpoint_input_construction"] = None
            completed["checkpoint_input_construction_alternatives"] = []
            return completed
        action = completed.get("supported_next_action")
        pairs: tuple[tuple[str, str], ...]
        if action in {
            "stage_exact_intent_checkpoint_input",
            "stage_exact_intent_correction_for_review",
            "stage_exact_intent_interpretation_for_review",
        }:
            pairs = (("prepare_generation", "intent_review"),)
        elif action == "stage_exact_decision_resolution_or_switch_posture":
            pairs = (("prepare_generation", "decision_resolution"),)
        elif action == "stage_exact_unchanged_continuation_for_review":
            pairs = (("continue_unchanged", "governing_change_confirmation"),)
        elif action == "stage_exact_continuation_choice":
            pairs = (
                ("continue_unchanged", "governing_change_confirmation"),
                ("propose_change", "governing_change_confirmation"),
            )
        elif action == "stage_exact_proposal_confirmation_or_decline":
            pairs = (
                ("confirm_change", "governing_change_confirmation"),
                ("continue_unchanged", "governing_change_confirmation"),
            )
        else:
            raise CurrentLoopError(f"checkpoint_input_construction_undefined_{action}")
        constructions = [
            checkpoint_input_construction(
                operation=operation,
                checkpoint_kind=checkpoint_kind,
                workspace_binding=str(state["workspace_root"]),
                loop_ref=str(state["loop_ref"]),
                phase=phase,
                expected_state_revision=int(state["state_revision"]),
                bounded_domains=self._checkpoint_input_bounded_domains(
                    operation=operation,
                    state=state,
                ),
            )
            for operation, checkpoint_kind in pairs
        ]
        completed["checkpoint_input_construction"] = (
            deepcopy(constructions[0]) if len(constructions) == 1 else None
        )
        completed["checkpoint_input_construction_alternatives"] = deepcopy(
            constructions if len(constructions) > 1 else []
        )
        return completed

    def _checkpoint_input_bounded_domains(
        self,
        *,
        operation: str,
        state: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return exact qCoder-owned domains visible at this state revision."""

        if operation == "prepare_generation":
            coordinator = self._coordinator_state(state)
            posture = coordinator.get("effective_generation_posture") or state.get(
                "generation_posture"
            )
            return (
                {"current_generation_posture": str(posture)}
                if posture in GENERATION_POSTURES
                else {}
            )
        if operation == "propose_change":
            try:
                blueprint = self._saved_artifact(state, "working_blueprint")
                records = self._decision_records(blueprint)
                current = self._saved_artifact(state, "current_build_context")
            except CurrentLoopError:
                return {}
            actions = current.get("applicable_actions")
            treatments: list[str] = []
            values: dict[str, list[Any]] = {}
            for record in records:
                decision_ref = record.get("decision_ref")
                if not isinstance(decision_ref, str):
                    continue
                alternatives = record.get("allowed_profile_alternatives")
                values[decision_ref] = (
                    deepcopy(alternatives) if isinstance(alternatives, list) else []
                )
                available = record.get("available_control_treatments")
                if isinstance(available, list):
                    for treatment in available:
                        if isinstance(treatment, str) and treatment not in treatments:
                            treatments.append(treatment)
            return {
                "decision_ref": [
                    str(record["decision_ref"])
                    for record in records
                    if isinstance(record.get("decision_ref"), str)
                ],
                "selected_action": (
                    [str(item) for item in actions if isinstance(item, str)]
                    if isinstance(actions, list)
                    else []
                ),
                "control_treatment": treatments,
                "proposed_value_by_decision": values,
            }
        if operation == "confirm_change":
            try:
                proposal = self._saved_artifact(state, "carry_forward_proposal")
            except CurrentLoopError:
                return {}
            proposal_ref = proposal.get("proposal_ref")
            return {"proposal_ref": proposal_ref} if isinstance(proposal_ref, str) else {}
        return {}

    def _result(
        self,
        *,
        operation: str,
        ok: bool,
        state: Mapping[str, Any],
        summary: str,
        elapsed: float,
        category: str | None = None,
        details: Mapping[str, Any] | None = None,
        checkpoint_protocol: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        coordinator = self._coordinator_state(state)
        coordinator["performance"]["coordinator_calls"] += 1
        coordinator["performance"]["coordinator_seconds"] += max(0.0, elapsed)
        pending = coordinator.get("pending_checkpoint_input")
        if isinstance(pending, dict) and pending.get("status") == "pending":
            pending["expected_state_revision"] = int(state["state_revision"]) + 1
        self._replace_coordinator(coordinator)
        state = self.store.read()
        coordinator = self._coordinator_state(state)
        protocol = self._checkpoint_protocol(
            operation=operation,
            phase=coordinator["phase"],
            state_status=coordinator["state_status"],
            checkpoint_kind=coordinator["checkpoint_kind"],
            category=category,
            coordinator=coordinator,
            override=checkpoint_protocol,
        )
        protocol = self._complete_protocol_disposition(
            phase=coordinator["phase"],
            state_status=coordinator["state_status"],
            checkpoint_kind=coordinator["checkpoint_kind"],
            coordinator=coordinator,
            protocol=protocol,
        )
        protocol.setdefault("checkpoint_input_construction", None)
        protocol.setdefault("checkpoint_input_construction_alternatives", [])
        protocol = self._attach_checkpoint_input_constructions(
            state=state,
            phase=str(coordinator["phase"]),
            protocol=protocol,
        )
        protocol = self._attach_operation_specific_invocations(
            state=state,
            checkpoint_kind=str(coordinator["checkpoint_kind"]),
            coordinator=coordinator,
            protocol=protocol,
        )
        self._validate_protocol_disposition(
            phase=coordinator["phase"],
            state_status=coordinator["state_status"],
            checkpoint_kind=coordinator["checkpoint_kind"],
            protocol=protocol,
        )
        result_details = deepcopy(dict(details or {}))
        result_details = self._attach_executable_recovery_alternatives(
            state=state,
            checkpoint_kind=str(coordinator["checkpoint_kind"]),
            details=result_details,
        )
        pending = coordinator.get("pending_checkpoint_input")
        if isinstance(pending, Mapping):
            result_details.update(self._checkpoint_input_display(pending))
        return {
            "schema_id": COORDINATOR_RESULT_SCHEMA_ID,
            "schema_version": COORDINATOR_RESULT_SCHEMA_VERSION,
            "operation": operation,
            "ok": ok,
            "category": category,
            "phase": coordinator["phase"],
            "state_status": coordinator["state_status"],
            "checkpoint_kind": coordinator["checkpoint_kind"],
            "required_authority": _CHECKPOINT_AUTHORITY[coordinator["checkpoint_kind"]],
            "next_permitted_transitions": list(_PHASE_TRANSITIONS[coordinator["phase"]]),
            "customer_summary": summary,
            "saved_artifact_references": self._saved_references(state),
            "details": result_details,
            "raw_protected_payload_included": False,
            "token_contents_included": False,
            "local_paths_transmitted": False,
            "assistant_reconstruction_performed": False,
            "bounded_contract_controls": self._contract_control_invocations(
                state=state,
                checkpoint_kind=str(coordinator["checkpoint_kind"]),
            ),
            **protocol,
        }

    def _attach_executable_recovery_alternatives(
        self,
        *,
        state: Mapping[str, Any],
        checkpoint_kind: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        recovery = details.get("recovery_contract")
        if not isinstance(recovery, dict):
            return details
        alternatives = recovery.get("alternatives")
        if not isinstance(alternatives, list):
            return details
        coordinator = self._coordinator_state(state)
        active = coordinator.get("active_recovery")
        reference = (
            str(active.get("reference"))
            if isinstance(active, Mapping) and isinstance(active.get("reference"), str)
            else f"recovery-{str(recovery.get('convergence_fingerprint', 'unbound'))[:24]}"
        )
        contract_revision = int(state["current_loop_contract"]["contract_revision"])
        completed: list[dict[str, Any]] = []
        for value in alternatives:
            action = str(value.get("action")) if isinstance(value, Mapping) else str(value)
            if action == "retry_hosted_enrichment":
                template = _invocation_template("enrich-authorized-evidence", uses_transport=True)
            elif action == "stop_loop":
                template = _invocation_template(
                    "abandon",
                    required_flags=("--approve",),
                    fixed_argument_values={"--approve": True},
                )
            elif action == "decline_build_review":
                template = _invocation_template(
                    "decline-build-review",
                    required_flags=("--approve",),
                    fixed_argument_values={"--approve": True},
                )
            else:
                template = _invocation_template(
                    "execute-recovery-action",
                    required_flags=(
                        "--recovery-reference",
                        "--action",
                        "--expected-contract-revision",
                    ),
                    fixed_argument_values={
                        "--recovery-reference": reference,
                        "--action": action,
                        "--expected-contract-revision": contract_revision,
                    },
                )
            bound = build_operation_invocation(
                template,
                executable=self.runtime_executable,
                workspace=str(state["workspace_root"]),
                base_url=self.hosted_base_url,
                token_file=self.hosted_token_file,
                state_revision=int(state["state_revision"]),
                loop_ref=str(state["loop_ref"]),
                checkpoint=checkpoint_kind,
            )
            completed.append(
                {
                    "action": action,
                    "customer_meaning": next(
                        (
                            row["customer_meaning"]
                            for row in recovery_action_contract_snapshot()["actions"]
                            if row["action"] == action
                        ),
                        action.replace("_", " "),
                    ),
                    "recovery_reference": reference,
                    "invocation": bound["operation_specific_invocation"],
                }
            )
        recovery["alternatives"] = completed
        recovery["zero_non_executable_alternatives"] = all(
            isinstance(item.get("invocation"), Mapping) for item in completed
        )
        return details

    def _contract_control_invocations(
        self, *, state: Mapping[str, Any], checkpoint_kind: str
    ) -> dict[str, Any]:
        contract = state.get("current_loop_contract")
        if not isinstance(contract, Mapping):
            return {}
        contract_revision = int(contract["contract_revision"])
        contracts = bounded_control_contracts(
            state,
            artifact_directory=self.artifact_directory,
        )
        rows = {
            "inspect": _invocation_template("contract-status"),
            "set_preset": _invocation_template(
                "contract-set-preset",
                required_flags=("--preset", "--expected-contract-revision"),
                new_inputs=("bounded_preset",),
            ),
            "adjust": _invocation_template(
                "contract-adjust",
                required_flags=(
                    "--category",
                    "--dimension",
                    "--value",
                    "--expected-contract-revision",
                ),
                new_inputs=("bounded_category_dimension_value",),
            ),
            "confirm_broadening": _invocation_template(
                "contract-confirm-broadening",
                required_flags=("--expected-contract-revision", "--approve"),
                reused_inputs=("current_qcoder_owned_pending_broadening",),
            ),
            "exclude": _invocation_template(
                "evidence-exclude",
                required_flags=(
                    "--artifact-reference",
                    "--reason",
                    "--expected-contract-revision",
                ),
                reused_inputs=("qcoder_displayed_artifact_reference",),
            ),
            "restore": _invocation_template(
                "evidence-restore",
                required_flags=(
                    "--artifact-reference",
                    "--expected-contract-revision",
                ),
                reused_inputs=("qcoder_displayed_artifact_reference",),
            ),
            "delete": _invocation_template(
                "evidence-delete",
                required_flags=(
                    "--artifact-reference",
                    "--expected-contract-revision",
                    "--approve",
                ),
                reused_inputs=("qcoder_displayed_locally_controlled_artifact_reference",),
            ),
            "stop_loop": _invocation_template(
                "abandon",
                required_flags=("--approve",),
                new_inputs=("explicit_stop_loop_authority",),
            ),
            "open_editor": _invocation_template("open-contract-editor"),
            "evidence_view": _invocation_template(
                "evidence-view",
                required_flags=("--view",),
                new_inputs=("bounded_evidence_view",),
            ),
            "decline_build_review": _invocation_template(
                "decline-build-review",
                required_flags=("--approve",),
                new_inputs=("explicit_build_review_decline",),
            ),
        }
        contract_operations = {
            "inspect": "contract_status",
            "set_preset": "contract_set_preset",
            "adjust": "contract_adjust",
            "confirm_broadening": "contract_confirm_broadening",
            "exclude": "evidence_exclude",
            "restore": "evidence_restore",
            "delete": "evidence_delete",
            "stop_loop": "stop_loop",
            "open_editor": "open_contract_editor",
            "evidence_view": "evidence_view",
            "decline_build_review": "decline_build_review",
        }
        result: dict[str, Any] = {}
        for name, template in rows.items():
            if name == "open_editor":
                bounded_contract = {
                    "schema_id": "qcoder.current_loop.contract_sidecar.v1",
                    "schema_version": 1,
                    "operation": "open_contract_editor",
                    "fields": [],
                    "browser_optional": True,
                    "hosted_operation_permitted": False,
                }
            elif name == "evidence_view":
                view_contract = evidence_view_contract_snapshot()
                bounded_contract = {
                    "schema_id": view_contract["schema_id"],
                    "schema_version": view_contract["schema_version"],
                    "operation": "evidence_view",
                    "fields": [
                        {
                            "name": "view_id",
                            "flag": "--view",
                            "ownership": "customer_selected_from_qcoder_domain",
                            "required": True,
                            "json_type": "string",
                            "accepted_values": deepcopy(view_contract["views"]),
                        },
                        {
                            "name": "selected_run_reference",
                            "flag": "--run-reference",
                            "ownership": "qcoder_owned_reference_selection",
                            "required": False,
                            "json_type": ["string", "null"],
                            "accepted_values": [
                                {
                                    "value": reference,
                                    "customer_meaning": f"Recorded run {reference[-8:]}",
                                }
                                for reference in sorted(state.get("run_summary_index", {}))
                            ],
                        },
                    ],
                    "arbitrary_query_text": False,
                }
            elif name == "decline_build_review":
                bounded_contract = {
                    "schema_id": "qcoder.current_loop.build_review_choice.v1",
                    "schema_version": 1,
                    "operation": "decline_build_review",
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
                    "blueprint_mutated": False,
                    "may_request_later": True,
                }
            else:
                bounded_contract = contracts[contract_operations[name]]
            template["bounded_control_input_contract"] = bounded_contract
            template["argument_values"] = dynamic_argument_contracts(bounded_contract)
            if "--expected-contract-revision" in template.get("required_flags", []):
                template["fixed_argument_values"] = {
                    "--expected-contract-revision": contract_revision
                }
            result[name] = build_operation_invocation(
                template,
                executable=self.runtime_executable,
                workspace=str(state["workspace_root"]),
                base_url=self.hosted_base_url,
                token_file=self.hosted_token_file,
                state_revision=int(state["state_revision"]),
                loop_ref=str(state["loop_ref"]),
                checkpoint=checkpoint_kind,
            )["operation_specific_invocation"]
        return result

    def _result_without_state(
        self,
        *,
        operation: str,
        ok: bool,
        phase: str,
        state_status: str,
        checkpoint_kind: str,
        summary: str,
        category: str | None = None,
        details: Mapping[str, Any] | None = None,
        checkpoint_protocol: Mapping[str, Any] | None = None,
        invocation_binding_state: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        protocol = self._checkpoint_protocol(
            operation=operation,
            phase=phase,
            state_status=state_status,
            checkpoint_kind=checkpoint_kind,
            category=category,
            coordinator=None,
            override=checkpoint_protocol,
        )
        protocol = self._complete_protocol_disposition(
            phase=phase,
            state_status=state_status,
            checkpoint_kind=checkpoint_kind,
            coordinator=None,
            protocol=protocol,
        )
        protocol.setdefault("checkpoint_input_construction", None)
        protocol.setdefault("checkpoint_input_construction_alternatives", [])
        protocol = self._attach_checkpoint_input_constructions(
            state={
                "workspace_root": str(self.workspace_root),
                "loop_ref": "synthetic-protocol-matrix-loop",
                "state_revision": 1,
            },
            phase=phase,
            protocol=protocol,
        )
        protocol = self._attach_operation_specific_invocations(
            state=(
                invocation_binding_state
                or {
                    "workspace_root": str(self.workspace_root),
                    "loop_ref": "synthetic-protocol-matrix-loop",
                    "state_revision": 1,
                }
            ),
            checkpoint_kind=checkpoint_kind,
            coordinator=None,
            protocol=protocol,
        )
        self._validate_protocol_disposition(
            phase=phase,
            state_status=state_status,
            checkpoint_kind=checkpoint_kind,
            protocol=protocol,
        )
        return {
            "schema_id": COORDINATOR_RESULT_SCHEMA_ID,
            "schema_version": COORDINATOR_RESULT_SCHEMA_VERSION,
            "operation": operation,
            "ok": ok,
            "category": category,
            "phase": phase,
            "state_status": state_status,
            "checkpoint_kind": checkpoint_kind,
            "required_authority": _CHECKPOINT_AUTHORITY[checkpoint_kind],
            "next_permitted_transitions": list(_PHASE_TRANSITIONS[phase]),
            "customer_summary": summary,
            "saved_artifact_references": [],
            "details": deepcopy(dict(details or {})),
            "raw_protected_payload_included": False,
            "token_contents_included": False,
            "local_paths_transmitted": False,
            "assistant_reconstruction_performed": False,
            **protocol,
        }

    def _attach_operation_specific_invocations(
        self,
        *,
        state: Mapping[str, Any],
        checkpoint_kind: str,
        coordinator: Mapping[str, Any] | None,
        protocol: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Bind every actionable template to qCoder-owned runtime routing."""

        completed = deepcopy(dict(protocol))
        invocation = completed.get("next_invocation")
        if not isinstance(invocation, Mapping):
            return completed
        pending = (
            coordinator.get("pending_checkpoint_input")
            if isinstance(coordinator, Mapping)
            else None
        )
        staged_operation = (
            str(pending.get("operation"))
            if isinstance(pending, Mapping) and isinstance(pending.get("operation"), str)
            else None
        )
        invocation = deepcopy(dict(invocation))
        try:
            operation = operation_for_subcommand(
                (
                    str(invocation["subcommand"])
                    if isinstance(invocation.get("subcommand"), str)
                    else None
                )
            )
            bounded_contract = bounded_contract_for_operation(
                state,
                operation=operation,
                artifact_directory=self.artifact_directory,
            )
            if isinstance(bounded_contract, Mapping):
                invocation["bounded_control_input_contract"] = bounded_contract
                existing_arguments = invocation.get("argument_values")
                arguments = (
                    [deepcopy(dict(item)) for item in existing_arguments]
                    if isinstance(existing_arguments, list)
                    else []
                )
                existing_flags = {
                    item.get("flag") for item in arguments if isinstance(item, Mapping)
                }
                arguments.extend(
                    item
                    for item in dynamic_argument_contracts(bounded_contract)
                    if item.get("flag") not in existing_flags
                )
                invocation["argument_values"] = arguments
                fixed = (
                    deepcopy(dict(invocation["fixed_argument_values"]))
                    if isinstance(invocation.get("fixed_argument_values"), Mapping)
                    else {}
                )
                for field in bounded_contract.get("fields", []):
                    if (
                        isinstance(field, Mapping)
                        and isinstance(field.get("flag"), str)
                        and field.get("ownership") == "qcoder_owned_prebound_value"
                        and "fixed_value" in field
                    ):
                        fixed[str(field["flag"])] = field["fixed_value"]
                invocation["fixed_argument_values"] = fixed
            completed["next_invocation"] = build_operation_invocation(
                invocation,
                executable=self.runtime_executable,
                workspace=str(state["workspace_root"]),
                base_url=self.hosted_base_url,
                token_file=self.hosted_token_file,
                state_revision=int(state["state_revision"]),
                loop_ref=str(state.get("loop_ref") or "pending-activation"),
                checkpoint=checkpoint_kind,
                staged_operation=staged_operation,
            )
        except ValueError as exc:
            raise CurrentLoopError(str(exc)) from exc
        return completed

    @staticmethod
    def _complete_protocol_disposition(
        *,
        phase: str,
        state_status: str,
        checkpoint_kind: str,
        coordinator: Mapping[str, Any] | None,
        protocol: Mapping[str, Any],
    ) -> dict[str, Any]:
        completed = deepcopy(dict(protocol))
        action = completed.get("supported_next_action")
        reason = completed.get("no_action_reason")
        if action is None:
            completed["permitted_input_source"] = "no_input_permitted_or_required"
            completed["input_source_disposition"] = {
                "schema_id": INPUT_SOURCE_DISPOSITION_SCHEMA_ID,
                "schema_version": INPUT_SOURCE_DISPOSITION_SCHEMA_VERSION,
                "categories": ["no_input_permitted_or_required"],
                "permitted_source": "no_input_permitted_or_required",
            }
            completed["bounded_input_semantics"] = {
                "input_required": False,
                "content_transport": "none",
                "accepted_values": {},
                "arbitrary_free_text_in_argv_permitted": False,
                "customer_types_coordinator_command": False,
                "assistant_may_infer_input_or_authority": False,
                "qcoder_held_values_retransmitted": False,
            }
            completed["required_authority_disposition"] = {
                "required_for_next_invocation": False,
                "authority_only": False,
                "content_submission_grants_authority": False,
            }
            completed["protocol_binding"] = {
                "phase": phase,
                "checkpoint_kind": checkpoint_kind,
                "current_local_state_is_canonical": True,
                "resolved_from_current_state_revision": True,
            }
            completed["no_action_disposition"] = {
                "reason": reason,
                "assistant_should_stop": True,
                "current_build_complete": phase == "completed",
                "new_loop_may_be_started": False,
                "prior_branch_closed": phase in {"completed", "abandoned"},
            }
            return completed

        if not isinstance(action, str):
            raise CurrentLoopError("coordinator_protocol_action_invalid")
        categories = _ACTION_INPUT_SOURCE_CATEGORIES.get(action)
        if categories is None:
            raise CurrentLoopError(f"coordinator_protocol_source_category_undefined_{action}")
        source = completed.get("permitted_input_source")
        if not isinstance(source, str) or not source:
            source = _default_permitted_input_source(action)
            completed["permitted_input_source"] = source
        invocation = completed.get("next_invocation")
        subcommand = invocation.get("subcommand") if isinstance(invocation, Mapping) else None
        checkpoint_transport = "checkpoint_input_transport" in categories
        request_transport = "exact_request_capture_transport" in categories
        authority_only = (
            "authority_only_approval" in categories
            and not checkpoint_transport
            and not request_transport
        )
        completed["input_source_disposition"] = {
            "schema_id": INPUT_SOURCE_DISPOSITION_SCHEMA_ID,
            "schema_version": INPUT_SOURCE_DISPOSITION_SCHEMA_VERSION,
            "categories": list(categories),
            "permitted_source": source,
        }
        completed["bounded_input_semantics"] = {
            "input_required": True,
            "content_transport": (
                "checkpoint_input_stdin_or_file"
                if checkpoint_transport
                else ("request_inline_or_explicit_stdin_or_file" if request_transport else "none")
            ),
            "accepted_values": _bounded_values_for_action(action),
            "arbitrary_free_text_in_argv_permitted": False,
            "customer_types_coordinator_command": False,
            "assistant_may_infer_input_or_authority": False,
            "qcoder_held_values_retransmitted": False,
        }
        stage_only = subcommand == "stage-checkpoint-input"
        completed["required_authority_disposition"] = {
            "required_for_next_invocation": (
                isinstance(completed.get("required_authority_input"), Mapping) and not stage_only
            ),
            "authority_only": authority_only,
            "content_submission_grants_authority": False,
        }
        pending = (
            coordinator.get("pending_checkpoint_input")
            if isinstance(coordinator, Mapping)
            else None
        )
        completed["protocol_binding"] = {
            "phase": phase,
            "checkpoint_kind": checkpoint_kind,
            "current_local_state_is_canonical": True,
            "resolved_from_current_state_revision": True,
            "pending_checkpoint_reference_source": (
                "qcoder_current_local_state" if isinstance(pending, Mapping) else None
            ),
            "expected_state_revision": (
                pending.get("expected_state_revision") if isinstance(pending, Mapping) else None
            ),
        }
        completed["no_action_disposition"] = None
        return completed

    @staticmethod
    def _validate_protocol_disposition(
        *,
        phase: str,
        state_status: str,
        checkpoint_kind: str,
        protocol: Mapping[str, Any],
    ) -> None:
        action = protocol.get("supported_next_action")
        invocation = protocol.get("next_invocation")
        reason = protocol.get("no_action_reason")
        if action is not None:
            if not isinstance(action, str) or not action or not isinstance(invocation, Mapping):
                raise CurrentLoopError("coordinator_protocol_incomplete")
            if reason is not None:
                raise CurrentLoopError("coordinator_protocol_contradictory")
            operation_invocation = invocation.get("operation_specific_invocation")
            if (
                not isinstance(operation_invocation, Mapping)
                or operation_invocation.get("schema_id") != INVOCATION_CONTRACT_SCHEMA_ID
                or not isinstance(operation_invocation.get("contract_digest"), str)
            ):
                raise CurrentLoopError("coordinator_operation_invocation_contract_missing")
            classification = operation_invocation.get("transport_classification")
            argv = operation_invocation.get("qcoder_owned_argv_prefix")
            structured_argv = operation_invocation.get("structured_argv")
            if not isinstance(argv, list) or not isinstance(structured_argv, list):
                raise CurrentLoopError("coordinator_operation_invocation_argv_missing")
            hosted_names = {"--base-url", "--token-file"}
            present_hosted_names = hosted_names.intersection(
                str(item) for item in [*argv, *structured_argv]
            )
            if classification == LOCAL_ONLY and present_hosted_names:
                raise CurrentLoopError("coordinator_local_invocation_transport_leak")
            if classification == HOSTED_CAPABLE and present_hosted_names != hosted_names:
                raise CurrentLoopError("coordinator_hosted_invocation_transport_incomplete")
            if invocation.get("assistant_constructs_transport_routing") is not False:
                raise CurrentLoopError("coordinator_assistant_transport_routing_prohibited")
            source = protocol.get("permitted_input_source")
            disposition = protocol.get("input_source_disposition")
            semantics = protocol.get("bounded_input_semantics")
            binding = protocol.get("protocol_binding")
            authority = protocol.get("required_authority_disposition")
            if not isinstance(source, str) or not source:
                raise CurrentLoopError("coordinator_protocol_permitted_input_source_missing")
            if (
                not isinstance(disposition, Mapping)
                or disposition.get("permitted_source") != source
            ):
                raise CurrentLoopError("coordinator_protocol_input_source_disposition_invalid")
            categories = disposition.get("categories")
            if (
                not isinstance(categories, list)
                or not categories
                or any(item not in PERMITTED_INPUT_SOURCE_CATEGORIES for item in categories)
                or "no_input_permitted_or_required" in categories
            ):
                raise CurrentLoopError("coordinator_protocol_input_source_category_invalid")
            if not isinstance(semantics, Mapping) or not isinstance(binding, Mapping):
                raise CurrentLoopError("coordinator_protocol_bounded_input_semantics_missing")
            if semantics.get("arbitrary_free_text_in_argv_permitted") is not False:
                raise CurrentLoopError("coordinator_protocol_literal_free_text_prohibited")
            if semantics.get("assistant_may_infer_input_or_authority") is not False:
                raise CurrentLoopError("coordinator_protocol_inference_prohibited")
            if (
                not isinstance(authority, Mapping)
                or authority.get("content_submission_grants_authority") is not False
            ):
                raise CurrentLoopError("coordinator_protocol_authority_disposition_invalid")
            authority_input_supplied = isinstance(protocol.get("required_authority_input"), Mapping)
            authority_required_now = authority.get("required_for_next_invocation")
            if authority_required_now is True and not authority_input_supplied:
                raise CurrentLoopError("coordinator_protocol_required_authority_missing")
            if (
                authority_required_now is False
                and authority_input_supplied
                and invocation.get("subcommand") != "stage-checkpoint-input"
                and not invocation.get("allowed_subcommand_alternatives")
            ):
                raise CurrentLoopError("coordinator_protocol_required_authority_contradictory")
            if "authority_only_approval" in categories and authority_required_now is not True:
                raise CurrentLoopError("coordinator_protocol_authority_source_mismatch")
            required_flags = invocation.get("required_flags", [])
            checkpoint_input_required = any(
                "checkpoint-input" in str(flag) for flag in required_flags
            )
            if (
                checkpoint_kind == "posture"
                and action
                in {
                    "obtain_separate_generation_posture_authority",
                    "select_generation_posture_or_stop",
                }
                and "checkpoint_input_transport" in categories
            ):
                raise CurrentLoopError("coordinator_protocol_posture_transport_invalid")
            if checkpoint_input_required and "checkpoint_input_transport" not in categories:
                raise CurrentLoopError("coordinator_protocol_checkpoint_input_source_mismatch")
            if "checkpoint_input_transport" in categories:
                construction = protocol.get("checkpoint_input_construction")
                alternatives = protocol.get("checkpoint_input_construction_alternatives")
                constructions = (
                    [construction]
                    if isinstance(construction, Mapping)
                    else (alternatives if isinstance(alternatives, list) else [])
                )
                if not constructions or any(
                    not isinstance(item, Mapping)
                    or item.get("schema_id") != CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_ID
                    or not isinstance(item.get("fixed_payload"), Mapping)
                    or not isinstance(item.get("accepted_value_fields"), list)
                    or not isinstance(item.get("semantic_field_contract"), Mapping)
                    or item["semantic_field_contract"].get("schema_id")
                    != CHECKPOINT_INPUT_SEMANTIC_SCHEMA_ID
                    or not isinstance(item["semantic_field_contract"].get("contract_digest"), str)
                    or not isinstance(item.get("construction_digest"), str)
                    for item in constructions
                ):
                    raise CurrentLoopError(
                        "coordinator_protocol_checkpoint_input_construction_missing"
                    )
                if any(
                    "--operation" in item["stage_invocation"].get("required_flags", [])
                    or "--checkpoint-kind" in item["stage_invocation"].get("required_flags", [])
                    for item in constructions
                ):
                    raise CurrentLoopError(
                        "coordinator_protocol_checkpoint_input_duplication_invalid"
                    )
            if invocation.get("authority_only") is True:
                if not {
                    "qcoder_held_staged_value",
                    "authority_only_approval",
                }.issubset(categories):
                    raise CurrentLoopError("coordinator_protocol_approval_source_mismatch")
                if invocation.get("staged_values_retransmitted") is not False:
                    raise CurrentLoopError("coordinator_protocol_content_retransmission_invalid")
            if (
                "bounded_enumerated_customer_choice" in categories
                and "checkpoint_input_transport" not in categories
                and not semantics.get("accepted_values")
            ):
                raise CurrentLoopError("coordinator_protocol_bounded_values_missing")
            if phase == "next_loop_ready":
                if action != "start_next_or_stop":
                    raise CurrentLoopError("coordinator_protocol_closed_branch_action_invalid")
                alternatives = invocation.get("allowed_subcommand_alternatives", [])
                serialized = json.dumps(
                    [invocation, alternatives],
                    ensure_ascii=True,
                    sort_keys=True,
                )
                if "propose_change" in serialized:
                    raise CurrentLoopError("coordinator_protocol_closed_branch_reopened")
            if checkpoint_kind == "posture" and action in {
                "obtain_separate_generation_posture_authority",
                "select_generation_posture_or_stop",
            }:
                accepted = semantics.get("accepted_values", {})
                if accepted.get("generation_posture") != list(GENERATION_POSTURES):
                    raise CurrentLoopError("coordinator_protocol_posture_values_invalid")
                if "checkpoint_input_transport" in categories:
                    raise CurrentLoopError("coordinator_protocol_posture_transport_invalid")
            return
        if not isinstance(reason, str) or not reason:
            raise CurrentLoopError(f"coordinator_protocol_incomplete_{phase}_{state_status}")
        if invocation is not None:
            raise CurrentLoopError("coordinator_protocol_no_action_invocation_invalid")
        disposition = protocol.get("input_source_disposition")
        no_action = protocol.get("no_action_disposition")
        if (
            protocol.get("permitted_input_source") != "no_input_permitted_or_required"
            or not isinstance(disposition, Mapping)
            or disposition.get("categories") != ["no_input_permitted_or_required"]
            or not isinstance(no_action, Mapping)
            or no_action.get("reason") != reason
        ):
            raise CurrentLoopError("coordinator_protocol_no_action_disposition_invalid")

    def _checkpoint_result(
        self,
        *,
        operation: str,
        phase: str,
        checkpoint_kind: str,
        summary: str,
        elapsed: float,
        category: str | None = None,
        details: Mapping[str, Any] | None = None,
        checkpoint_protocol: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            state = self.store.read()
        except CurrentLoopError:
            return self._result_without_state(
                operation=operation,
                ok=True,
                phase=phase,
                state_status="checkpoint_required",
                checkpoint_kind=checkpoint_kind,
                summary=summary,
                category=category,
                details=details,
                checkpoint_protocol=checkpoint_protocol,
            )
        coordinator = self._coordinator_state(state)
        coordinator.update(
            {
                "phase": phase,
                "state_status": "checkpoint_required",
                "checkpoint_kind": checkpoint_kind,
                "customer_summary": summary,
            }
        )
        self._replace_coordinator(coordinator)
        return self._result(
            operation=operation,
            ok=True,
            state=self.store.read(),
            summary=summary,
            elapsed=elapsed,
            category=category,
            details=details,
            checkpoint_protocol=checkpoint_protocol,
        )

    def _recovery_result(
        self,
        *,
        operation: str,
        category: str,
        phase: str,
        elapsed: float,
        details: Mapping[str, Any] | None = None,
        origin: str = "contract_or_authority",
        deterministic: bool = True,
        alternatives: Sequence[str] | None = None,
        protected_call_attempted: bool = False,
        protected_non_success: bool = False,
    ) -> dict[str, Any]:
        normalized = _ERROR_ALIASES.get(category, category)
        recovery = _RECOVERY.get(
            normalized,
            _RECOVERY["unknown_local_internal"],
        )
        status = (
            "conflict"
            if normalized == "client_state_conflict"
            else "corrupt"
            if normalized == "local_state_corrupt"
            else "stale"
            if normalized
            in {
                "selected_file_stale",
                "selected_file_missing",
                "canonical_artifact_modified",
                "parent_digest_mismatch",
                "seed_incomplete",
            }
            else "blocked"
        )
        recoverable = recovery[2] is True and normalized not in {
            "loop_not_activated",
            "local_state_corrupt",
            "reconstruction_attempt_refused",
        }
        if recoverable:
            status = "checkpoint_required"
        payload = {
            "message": recovery[0],
            "supported_next_action": recovery[1],
            "conversation_may_continue": recovery[2],
            "reauthorization_required": recovery[3],
            "local_state_intact": recovery[4],
            "certification_fallback_available": recovery[5],
            **deepcopy(dict(details or {})),
        }
        payload["failure_provenance"] = failure_provenance(
            origin=origin,
            category=normalized,
            protected_call_attempted=protected_call_attempted,
            protected_non_success=protected_non_success,
        )
        strategy = (
            "qcoder_corrects"
            if normalized
            in {
                "checkpoint_input_required_field_missing",
                "profile_id_missing",
                "classification_missing",
            }
            else "refresh_revision"
            if normalized == "client_state_conflict"
            else "rebind_event_receipt"
            if "operation_receipt" in normalized
            else "bounded_alternative"
            if (
                "unsupported" in normalized
                or "invalid" in normalized
                or normalized == "current_loop_contract_policy_prohibited"
            )
            else "restage_with_construction"
        )
        selected_alternatives = list(
            alternatives
            or (
                ("continue_with_limitations", "provide_supported_circuit_artifact", "stop_loop")
                if normalized in {"artifact_format_unsupported", "circuit_format_unsupported"}
                else ("retry_hosted_enrichment", "skip_hosted_enrichment", "stop_loop")
                if origin in {"hosted_transport", "hosted_operation"}
                else ("abandon_step", "stop_loop")
            )
        )
        input_digests = [
            str(value)
            for value in (details or {}).get("input_digests", [])
            if isinstance(value, str)
        ]
        fingerprint = recovery_fingerprint(
            category=normalized,
            operation=operation,
            input_digests=input_digests,
        )
        payload["recovery_contract"] = {
            "schema_id": RECOVERY_SCHEMA_ID,
            "schema_version": RECOVERY_SCHEMA_VERSION,
            "strategy": strategy,
            "safe_error_category": normalized,
            "prior_valid_authority_preserved": recovery[4],
            "prior_valid_evidence_preserved": recovery[4],
            "permitted_input_source": (
                "qcoder_owned_prebound_value"
                if strategy == "qcoder_corrects"
                else "fresh_coordinator_result"
            ),
            "customer_review_required": recovery[3],
            "hosted_operation_permitted": False,
            "alternatives": selected_alternatives,
            "state_and_contract_binding_required": True,
            "complete_next_invocation_required": True,
            "refresh_executes_selected_action": False,
            "deterministic_failure": deterministic,
            "convergence_fingerprint": fingerprint,
        }
        recovery_protocol = (
            {
                "supported_next_action": "refresh_bounded_recovery",
                "next_invocation": _invocation_template(
                    "status",
                    reused_inputs=("current_qcoder_owned_local_state",),
                ),
                "required_authority_input": None,
                "awaiting_confirmation_fields": [],
                "confirmation_transmission_state": "not_applicable",
                "identical_repeat_prohibited": False,
                "permitted_input_source": "fresh_qcoder_coordinator_result",
                "no_action_reason": None,
            }
            if recoverable
            else None
        )
        try:
            state = self.store.read()
        except CurrentLoopError:
            return self._result_without_state(
                operation=operation,
                ok=False,
                category=normalized,
                phase=phase,
                state_status=status,
                checkpoint_kind=_recovery_checkpoint_kind(
                    normalized,
                    reauthorization_required=recovery[3],
                ),
                summary=recovery[0],
                details=payload,
                checkpoint_protocol=recovery_protocol,
            )
        coordinator = self._coordinator_state(state)
        previous = coordinator.get("active_recovery")
        occurrence_count = (
            int(previous.get("occurrence_count", 0)) + 1
            if isinstance(previous, Mapping) and previous.get("fingerprint") == fingerprint
            else 1
        )
        if deterministic and occurrence_count > 1:
            selected_alternatives = [
                action for action in selected_alternatives if action != "retry_local_derivation"
            ]
            payload["recovery_contract"]["alternatives"] = selected_alternatives
            payload["recovery_contract"]["futile_identical_retry_removed"] = True
        coordinator.update(
            {
                "state_status": status,
                "checkpoint_kind": _recovery_checkpoint_kind(
                    normalized,
                    reauthorization_required=recovery[3],
                ),
                "customer_summary": recovery[0],
            }
        )
        if recoverable:
            coordinator["active_recovery"] = {
                "schema_id": RECOVERY_SCHEMA_ID,
                "schema_version": RECOVERY_SCHEMA_VERSION,
                "category": normalized,
                "strategy": strategy,
                "reference": f"recovery-{fingerprint[:24]}",
                "fingerprint": fingerprint,
                "occurrence_count": occurrence_count,
                "deterministic": deterministic,
                "alternatives": selected_alternatives,
                "origin": origin,
            }
        self._replace_coordinator(coordinator)
        return self._result(
            operation=operation,
            ok=False,
            category=normalized,
            state=self.store.read(),
            summary=recovery[0],
            elapsed=elapsed,
            details=payload,
            checkpoint_protocol=recovery_protocol,
        )

    def _exception_result(self, operation: str, exc: Exception, started: float) -> dict[str, Any]:
        category = (
            str(getattr(exc, "category"))
            if isinstance(getattr(exc, "category", None), str)
            else "unknown_local_internal"
        )
        category = _ERROR_ALIASES.get(category, category)
        if category == "protected_operation_rejected" and not (
            isinstance(exc, EvidenceProcessingError)
            and exc.protected_call_attempted
            and exc.protected_non_success
        ):
            category = "unknown_local_internal"
        if category not in _RECOVERY:
            if category.startswith("checkpoint_input_") or category.startswith(
                "coordinator_protocol_"
            ):
                pass
            elif "reconstruct" in category:
                category = "reconstruction_attempt_refused"
            elif "schema" in category or "version" in category:
                category = "unsupported_schema"
            elif "parent" in category or "digest" in category:
                category = "parent_digest_mismatch"
            elif isinstance(exc, EvidenceProcessingError):
                pass
            elif category.startswith(
                ("selected_", "artifact_", "current_loop_", "contract_", "operation_receipt_")
            ):
                pass
            elif category.startswith(("protected_", "preview_")):
                pass
            else:
                category = "unknown_local_internal"
        origin = (
            exc.origin
            if isinstance(exc, EvidenceProcessingError)
            else "hosted_operation"
            if category.startswith(("protected_", "preview_"))
            else "contract_or_authority"
            if isinstance(exc, (CurrentLoopError, CurrentLoopConflict))
            else "unknown_local_internal"
        )
        return self._recovery_result(
            operation=operation,
            category=category,
            phase=self._safe_phase(),
            elapsed=max(0.0, self.clock() - started),
            details=(
                exc.safe_details
                if isinstance(exc, (CheckpointInputStructuralError, EvidenceProcessingError))
                else None
            ),
            origin=origin,
            deterministic=(exc.deterministic if isinstance(exc, EvidenceProcessingError) else True),
            protected_call_attempted=(
                exc.protected_call_attempted if isinstance(exc, EvidenceProcessingError) else False
            ),
            protected_non_success=(
                exc.protected_non_success if isinstance(exc, EvidenceProcessingError) else False
            ),
        )

    def _safe_phase(self) -> str:
        try:
            return self._coordinator_state(self.store.read())["phase"]
        except CurrentLoopError:
            return "activated"
