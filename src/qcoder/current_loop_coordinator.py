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
    propose_selected_artifact_authorization,
    save_exact_canonical_artifact,
    set_artifact_authorization,
    share_safe_artifact_authorization_projection,
    update_selected_artifact_authorization,
)
from qcoder.context_loop import CONTEXT_LOOP_GATE

COORDINATOR_RESULT_SCHEMA_ID = "qcoder.current_loop.coordinator_result.v3"
COORDINATOR_RESULT_SCHEMA_VERSION = 3
COORDINATOR_STATE_SCHEMA_ID = "qcoder.current_loop.coordinator_state.v2"
LEGACY_COORDINATOR_STATE_SCHEMA_ID = "qcoder.current_loop.coordinator_state.v1"
COORDINATOR_STATE_SCHEMA_VERSION = 2
CONSEQUENCE_PROJECTION_SCHEMA_ID = "qcoder.current_loop.consequence_projection.v1"
PERFORMANCE_SCHEMA_ID = "qcoder.current_loop.private_performance.v1"

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
    "activation",
    "posture",
    "intent_review",
    "decision_resolution",
    "ide_write_or_run",
    "artifact_review",
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
    "activated": ("intent_review", "abandoned"),
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
        "artifact_authorization",
        "current_build_review",
        "abandoned",
    ),
    "current_build_review": ("continuation_choice", "abandoned"),
    "continuation_choice": (
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

_CHECKPOINT_AUTHORITY = {
    "activation": "Explicitly activate qCoder for this current build.",
    "posture": "Choose exploratory first pass or Blueprint-guided generation.",
    "intent_review": "Review and explicitly approve or correct the proposed interpretation.",
    "decision_resolution": (
        "Approve only the exact generation-relevant decision dispositions, defer them, "
        "or explicitly switch this attempt to exploratory first pass."
    ),
    "ide_write_or_run": "Authorize the IDE host separately before writing or executing code.",
    "artifact_review": "Approve the exact visible artifact set qCoder may inspect locally.",
    "governing_change_confirmation": (
        "Explicitly confirm the exact Carry-Forward Proposal before governing intent changes."
    ),
    "privacy_or_trust": "Review the material privacy, trust, or evidence limitation.",
    "none": "No human authority is required for the next deterministic local transition.",
}

DECISION_AUTHORITY_PROVENANCE = (
    "user_provided",
    "user_confirmed_assistant_interpretation",
    "inherited_confirmed_lineage",
    "assistant_recommendation_pending_confirmation",
)
AUTHORIZED_DECISION_PROVENANCE = frozenset(DECISION_AUTHORITY_PROVENANCE[:3])
POSTURE_AUTHORITY_PROVENANCE = (
    "user_provided",
    "user_confirmed_assistant_recommendation",
    "inherited_confirmed_lineage",
)
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
    return {
        "schemas": {
            "result": COORDINATOR_RESULT_SCHEMA_ID,
            "state": COORDINATOR_STATE_SCHEMA_ID,
            "consequence_projection": CONSEQUENCE_PROJECTION_SCHEMA_ID,
            "performance": PERFORMANCE_SCHEMA_ID,
        },
        "phases": list(PHASES),
        "state_statuses": list(STATE_STATUSES),
        "checkpoint_kinds": list(CHECKPOINT_KINDS),
        "confirmation_transmission_states": list(CONFIRMATION_TRANSMISSION_STATES),
        "checkpoint_result_protocol": {
            "schema_version": COORDINATOR_RESULT_SCHEMA_VERSION,
            "supported_next_action": True,
            "next_invocation": True,
            "required_authority_input": True,
            "awaiting_confirmation_fields": True,
            "confirmation_transmission_state": True,
            "identical_repeat_prohibited": True,
        },
        "generation_context_response_modes": [
            "exploratory_generation_context_ready",
            "generation_context_blocked_pending_decisions",
            "generation_context_pack_ready",
        ],
        "decision_authority_provenance": list(DECISION_AUTHORITY_PROVENANCE),
        "posture_authority_provenance": list(POSTURE_AUTHORITY_PROVENANCE),
        "workspace_state_is_intent": False,
        "recovery_categories": sorted(_RECOVERY),
        "high_level_operations": [
            "status",
            "activate",
            "prepare_generation",
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
    alternatives: Sequence[str] = (),
    uses_transport: bool = False,
) -> dict[str, Any]:
    return {
        "coordinator_prefix_source": "configured_qcoder_runtime.coordinator_prefix",
        "workspace_argument": {
            "flag": "--workspace",
            "value_source": "active_workspace_root",
        },
        "transport_argument_source": (
            "configured_qcoder_runtime.transport_arguments" if uses_transport else None
        ),
        "subcommand": subcommand,
        "required_flags": list(required_flags),
        "reused_canonical_inputs": list(reused_inputs),
        "new_input_roles": list(new_inputs),
        "argument_values": [deepcopy(dict(item)) for item in argument_values],
        "allowed_subcommand_alternatives": list(alternatives),
        "private_workspace_path_embedded": False,
        "token_contents_embedded": False,
        "account_identifier_embedded": False,
        "canonical_artifact_reconstruction_required": False,
    }


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


class CurrentLoopCoordinator:
    """One-current-loop deterministic coordinator."""

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        state_path: str | Path | None = None,
        transport: ProtectedTransport | None = None,
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
        self.transport = transport
        self.clock = clock

    @property
    def artifact_directory(self) -> Path:
        return self.workspace_root / ".qcoder" / "current-loop" / "artifacts"

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
        coordinator = self._coordinator_state(state)
        status_details: dict[str, Any] = {
            "generation_context_outcome": deepcopy(coordinator.get("generation_context_outcome"))
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
        return self._result(
            operation="status",
            ok=coordinator["state_status"] not in {"blocked", "conflict", "corrupt"},
            state=state,
            summary=coordinator["customer_summary"],
            elapsed=self.clock() - started,
            details=status_details,
        )

    def activate(
        self,
        *,
        original_request: str,
        generation_posture: str | None,
        explicit_authority: bool,
        label: str | None = None,
        parent_loop_ref: str | None = None,
        assistant_interpretation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = self.clock()
        if generation_posture is None:
            generation_posture = infer_requested_posture(original_request)
        if generation_posture is None:
            return self._recovery_result(
                operation="activate",
                category="posture_required",
                phase="activated",
                elapsed=self.clock() - started,
            )
        if explicit_authority is not True:
            return self._checkpoint_result(
                operation="activate",
                phase="activated",
                checkpoint_kind="activation",
                summary="qCoder has not been activated. Explicit approval is required.",
                elapsed=self.clock() - started,
            )
        try:
            activated = activate_current_loop(
                workspace_root=self.workspace_root,
                generation_posture=generation_posture,
                explicit_authority=True,
                parent_loop_ref=parent_loop_ref,
                label=label,
                external_state_path=(
                    self.state_path
                    if self.state_path
                    != self.workspace_root / ".qcoder" / "current-loop" / "state.json"
                    else None
                ),
            )
            baseline = build_request_baseline(
                original_request=original_request,
                assistant_interpretation=assistant_interpretation,
            )
            self._save_artifact(
                "request_baseline",
                baseline,
                "request-baseline.json",
            )
            state = self.store.read()
            coordinator = self._initial_coordinator_state(
                phase="intent_review",
                state_status="checkpoint_required",
                checkpoint_kind="intent_review",
                summary=(
                    "qCoder is active. Review the separately attributed assistant "
                    "interpretation before confirming generation intent."
                ),
            )
            coordinator["activation"] = {
                "explicit": True,
                "original_request_preserved": True,
                "generation_posture_explicit": True,
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
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self._require_phase("prepare_generation", {"intent_review", "generation_ready"})
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
                if (
                    explicit_posture_authority is not True
                    or not isinstance(posture_change_reason, str)
                    or not isinstance(posture_authority_provenance, str)
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
                    reason=posture_change_reason,
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

    def record_ide_authority(
        self,
        *,
        allowed: bool,
        explicit_user_action: bool,
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self._require_phase(
                "record_ide_authority",
                {"generation_ready", "awaiting_local_artifacts"},
            )
            if not explicit_user_action or not allowed:
                return self._recovery_result(
                    operation="record_ide_authority",
                    category="ide_write_or_run_denied",
                    phase=self._coordinator_state(state)["phase"],
                    elapsed=self.clock() - started,
                )
            coordinator = self._coordinator_state(state)
            coordinator.update(
                {
                    "phase": "awaiting_local_artifacts",
                    "state_status": "ready",
                    "checkpoint_kind": "none",
                    "customer_summary": (
                        "The IDE host recorded its separate write or run authority. "
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
                details={"artifact_review_authorized": False},
            )
        except (CurrentLoopError, CurrentLoopConflict) as exc:
            return self._exception_result("record_ide_authority", exc, started)

    def register_artifacts(
        self,
        *,
        candidates: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self._require_phase(
                "register_artifacts",
                {
                    "generation_ready",
                    "awaiting_local_artifacts",
                    "artifact_authorization",
                    "evidence_processing",
                },
            )
            normalized = self._normalize_candidates(candidates)
            authorization = propose_selected_artifact_authorization(
                loop_ref=state["loop_ref"],
                proposed_artifacts=[
                    {
                        "artifact_role": item["role"],
                        "artifact_type": item["artifact_type"],
                        "local_path": item["path"],
                    }
                    for item in normalized
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
                    "artifact_candidates": normalized,
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
                    "proposed_set": [
                        {
                            "role": item["role"],
                            "display_path": item["display_path"],
                            "external": item["external"],
                            "provenance": item["provenance"],
                        }
                        for item in normalized
                    ],
                    "review_authorized": False,
                    "directory_scanned": False,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict, ValueError) as exc:
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
                    }
                )
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
                    "paths_transmitted": False,
                    "ide_write_or_run_implied": False,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict) as exc:
            return self._exception_result("authorize_artifacts", exc, started)

    def process_authorized_artifacts(self) -> dict[str, Any]:
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
                )
            extracted_roles: list[str] = []
            for item in authorization["items"]:
                path = Path(item["local_path"])
                role = item["artifact_role"]
                if role == "source":
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
                    extracted_roles.extend(["source_evidence", "python_manifestation"])
                elif role == "circuit_qasm":
                    qasm_text = path.read_text(encoding="utf-8")
                    circuit = build_circuit_manifestation(
                        qasm_text=qasm_text,
                        stage="logical_circuit",
                    )
                    self._save_artifact(
                        "circuit_manifestation",
                        circuit,
                        "circuit-manifestation.json",
                    )
                    extracted_roles.append("circuit_manifestation")
                elif role == "results":
                    result_input = _load_json_file(path)
                    related_ref = self._related_circuit_reference(self.store.read(), path)
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
                            raise CurrentLoopError("result_artifact_invalid")
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
                    self._save_artifact(
                        "result_manifestation",
                        result,
                        "result-manifestation.json",
                    )
                    extracted_roles.append("result_manifestation")
                else:
                    raise CurrentLoopError("unsupported_authorized_artifact_type")
            state = self.store.read()
            if "result_manifestation" in state["saved_artifacts"]:
                if self.transport is None:
                    return self._recovery_result(
                        operation="process_authorized_artifacts",
                        category="protected_service_unavailable",
                        phase="evidence_processing",
                        elapsed=self.clock() - started,
                    )
                result_review_payload = self._protected_call(
                    "create_result_review_context_card",
                    {
                        "context_loop": "current_build_context_v1",
                        "result_manifestation": self._saved_artifact(state, "result_manifestation"),
                        "evidence_parent_artifacts": [
                            self._saved_artifact(state, role)
                            for role in (
                                "circuit_manifestation",
                                "result_manifestation",
                            )
                            if role in state["saved_artifacts"]
                        ],
                    },
                )
                result_review = self._response_artifact(
                    result_review_payload, "result_review_context_card"
                )
                self._save_artifact(
                    "result_review_context_card",
                    result_review,
                    "result-review-context-card.json",
                )
                extracted_roles.append("result_review_context_card")
                state = self.store.read()
            if (
                "source_evidence" in state["saved_artifacts"]
                and "working_blueprint" in state["saved_artifacts"]
                and "output_evidence_contract" in state["saved_artifacts"]
            ):
                if self.transport is None:
                    return self._recovery_result(
                        operation="process_authorized_artifacts",
                        category="protected_service_unavailable",
                        phase="evidence_processing",
                        elapsed=self.clock() - started,
                    )
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
                alignment = self._response_artifact(
                    alignment_payload, "source_blueprint_alignment_review"
                )
                self._save_artifact(
                    "source_blueprint_alignment",
                    alignment,
                    "source-blueprint-alignment.json",
                )
                extracted_roles.append("source_blueprint_alignment")
            state = self.store.read()
            coordinator = self._coordinator_state(state)
            coordinator.update(
                {
                    "phase": "evidence_processing",
                    "state_status": "ready",
                    "checkpoint_kind": "none",
                    "customer_summary": (
                        "Authorized local artifacts were processed and exact bounded "
                        "evidence was saved. Raw artifacts remained local."
                    ),
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
                    "raw_source_sent": False,
                    "raw_qasm_sent": False,
                    "raw_results_sent": False,
                    "source_executed": False,
                    "manual_extractor_commands": 0,
                },
            )
        except (CurrentLoopError, CurrentLoopConflict, ValueError, OSError) as exc:
            return self._exception_result("process_authorized_artifacts", exc, started)

    def review_build(self) -> dict[str, Any]:
        started = self.clock()
        try:
            state = self._require_phase(
                "review_build", {"evidence_processing", "current_build_review"}
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
                proposal["proposal_state"] = "declined"
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
            payload = self.transport.confirm_selected_bundle(
                selected_bundle_file=portable_descriptor["local_path"],
                semantic_confirmation=semantic_confirmation,
            )
            self._record_protected_call(max(0.0, self.clock() - confirmation_started))
            if payload.get("ok") is False:
                raise CurrentLoopError(
                    str(payload.get("error_category") or "protected_operation_rejected")
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
        seed_file: str | Path,
        parent_files: Mapping[str, str | Path],
        explicit_authority: bool,
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
            activated = activate_next_loop_from_seed(
                workspace_root=next_workspace_root,
                generation_posture=generation_posture,
                explicit_authority=True,
                seed_file=seed_file,
                parent_files=parent_files,
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
        provenance: str = "user_supplied",
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
        if self.transport is None:
            raise CurrentLoopError("protected_service_unavailable")
        started = self.clock()
        payload = self.transport.call(tool_name, arguments)
        elapsed = max(0.0, self.clock() - started)
        self._record_protected_call(elapsed)
        if payload.get("ok") is False:
            category = str(payload.get("error_category") or "protected_operation_rejected")
            raise CurrentLoopError(category)
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
            path = Path(path_value).expanduser()
            if not path.is_absolute() or ".." in path.parts:
                raise CurrentLoopError("selected_artifact_path_invalid")
            exact = str(path)
            if exact in seen:
                raise CurrentLoopError("selected_artifact_duplicate_path")
            seen.add(exact)
            provenance = candidate.get("provenance")
            if provenance not in {"assistant_created", "user_supplied"}:
                raise CurrentLoopError("artifact_candidate_provenance_invalid")
            external = not self._is_within_workspace(path)
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

    def _is_within_workspace(self, path: Path) -> bool:
        try:
            path.absolute().relative_to(self.workspace_root)
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
        if (
            result.get("schema_id") == LEGACY_COORDINATOR_STATE_SCHEMA_ID
            and result.get("schema_version") == 1
        ):
            result["schema_id"] = COORDINATOR_STATE_SCHEMA_ID
            result["schema_version"] = COORDINATOR_STATE_SCHEMA_VERSION
            result.setdefault("effective_generation_posture", state.get("generation_posture"))
            result.setdefault("posture_transition_history", [])
            result.setdefault("pending_decision_resolution", None)
            result.setdefault("generation_context_outcome", None)
            result.setdefault("active_generation_artifacts", {})
            result.setdefault("generation_parent_history", [])
        result.setdefault("effective_generation_posture", state.get("generation_posture"))
        result.setdefault("posture_transition_history", [])
        result.setdefault("pending_decision_resolution", None)
        result.setdefault("generation_context_outcome", None)
        result.setdefault("active_generation_artifacts", {})
        result.setdefault("generation_parent_history", [])
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
        }
        if state_status != "checkpoint_required":
            return protocol

        protocol["identical_repeat_prohibited"] = True
        if checkpoint_kind == "posture":
            if category == "posture_transition_authority_required":
                protocol.update(
                    {
                        "supported_next_action": "obtain_explicit_posture_transition_authority",
                        "next_invocation": _invocation_template(
                            "prepare-generation",
                            required_flags=(
                                "--posture",
                                "--approve-posture-change",
                                "--posture-reason",
                                "--posture-provenance",
                            ),
                            reused_inputs=(
                                "confirmed_interpretation_inputs",
                                "current_working_blueprint",
                                "unresolved_decision_inventory",
                            ),
                            new_inputs=(
                                "requested_generation_posture",
                                "explicit_posture_transition_authority",
                                "posture_change_reason",
                                "posture_authority_provenance",
                            ),
                            uses_transport=True,
                        ),
                        "required_authority_input": _authority_input(
                            "--approve-posture-change",
                            "Authorize only the explicit posture transition for this attempt.",
                            additional_flags=(
                                "--posture",
                                "--posture-reason",
                                "--posture-provenance",
                            ),
                        ),
                        "awaiting_confirmation_fields": [
                            "generation_posture_transition",
                            "posture_change_reason",
                            "posture_authority_provenance",
                        ],
                        "confirmation_transmission_state": "not_supplied",
                    }
                )
                if override:
                    for key in protocol:
                        if key in override:
                            protocol[key] = deepcopy(override[key])
                return protocol
            protocol.update(
                {
                    "supported_next_action": "obtain_generation_posture_and_activation",
                    "next_invocation": _invocation_template(
                        "activate",
                        required_flags=("--request", "--posture", "--approve"),
                        reused_inputs=("original_request",),
                        new_inputs=(
                            "generation_posture_selection",
                            "explicit_qcoder_activation",
                        ),
                    ),
                    "required_authority_input": _authority_input(
                        "--approve",
                        "Explicitly activate qCoder after selecting the generation posture.",
                    ),
                    "awaiting_confirmation_fields": [
                        "generation_posture",
                        "qcoder_activation",
                    ],
                    "confirmation_transmission_state": "not_supplied",
                }
            )
        elif checkpoint_kind == "decision_resolution":
            pending_resolution = (
                coordinator.get("pending_decision_resolution")
                if isinstance(coordinator, Mapping)
                else None
            )
            argument_values: list[dict[str, Any]] = []
            if isinstance(pending_resolution, Mapping):
                argument_values.extend(
                    [
                        {
                            "flag": "--profile",
                            "value": pending_resolution.get("profile_id"),
                        },
                        {
                            "flag": "--interpretation-summary",
                            "value": pending_resolution.get("interpretation_summary"),
                        },
                    ]
                )
                for field, value in sorted(
                    dict(pending_resolution.get("profile_answers") or {}).items()
                ):
                    argument_values.append(
                        {"flag": "--profile-answer", "value": f"{field}={value}"}
                    )
                for value in pending_resolution.get("constraints", []):
                    argument_values.append({"flag": "--constraint", "value": value})
                for value in pending_resolution.get("non_goals", []):
                    argument_values.append({"flag": "--non-goal", "value": value})
                for disposition in pending_resolution.get("authorized_dispositions", []):
                    if not isinstance(disposition, Mapping):
                        continue
                    argument_values.append(
                        {
                            "flag": "--decision-disposition",
                            "values": [
                                disposition.get("profile_decision_id"),
                                disposition.get("user_disposition"),
                                disposition.get("selected_value", "-"),
                                disposition.get("authority_provenance"),
                            ],
                            "reused_authorized_input": True,
                        }
                    )
            protocol.update(
                {
                    "supported_next_action": "resolve_generation_decisions_or_switch_posture",
                    "next_invocation": _invocation_template(
                        "prepare-generation",
                        required_flags=(
                            "--profile",
                            "--interpretation-summary",
                            "--confirm-intent",
                            "--decision-disposition",
                            "--approve-decisions",
                        ),
                        reused_inputs=(
                            "confirmed_intent_card",
                            "working_blueprint",
                            "output_evidence_contract",
                            "pending_decision_resolution.interpretation_inputs",
                            "pending_decision_resolution.authorized_dispositions",
                        ),
                        new_inputs=("explicitly_approved_decision_dispositions",),
                        argument_values=argument_values,
                        alternatives=(
                            "prepare-generation with explicit exploratory posture transition",
                            "defer and stop",
                        ),
                        uses_transport=True,
                    ),
                    "required_authority_input": _authority_input(
                        "--approve-decisions",
                        "Transmit only the user's exact approved generation-relevant dispositions.",
                        additional_flags=("--decision-disposition",),
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
                }
            )
        elif checkpoint_kind == "intent_review":
            pending = (
                coordinator.get("pending_intent_review")
                if isinstance(coordinator, Mapping)
                else None
            )
            if isinstance(pending, Mapping):
                argument_values: list[dict[str, Any]] = [
                    {"flag": "--profile", "value": pending.get("profile_id")},
                    {
                        "flag": "--interpretation-summary",
                        "value": pending.get("interpretation_summary"),
                    },
                ]
                for value in pending.get("profile_answers", []):
                    argument_values.append({"flag": "--profile-answer", "value": value})
                for value in pending.get("constraints", []):
                    argument_values.append({"flag": "--constraint", "value": value})
                for value in pending.get("non_goals", []):
                    argument_values.append({"flag": "--non-goal", "value": value})
                next_invocation = _invocation_template(
                    "prepare-generation",
                    required_flags=(
                        "--profile",
                        "--interpretation-summary",
                        "--confirm-intent",
                    ),
                    reused_inputs=(
                        "pending_intent_review.profile_id",
                        "pending_intent_review.interpretation_inputs",
                    ),
                    new_inputs=("explicit_intent_confirmation",),
                    argument_values=argument_values,
                    uses_transport=True,
                )
            else:
                next_invocation = _invocation_template(
                    "prepare-generation",
                    required_flags=("--profile", "--interpretation-summary"),
                    reused_inputs=("request_baseline",),
                    new_inputs=(
                        "reviewed_interpretation",
                        "reviewed_profile_answers",
                    ),
                    uses_transport=True,
                )
            clarification = category in {
                "intent_clarification_required",
                "intent_clarification_unchanged",
            }
            protocol.update(
                {
                    "supported_next_action": (
                        "review_intent_clarification_and_retransmit_confirmation"
                        if clarification
                        else "present_intent_and_transmit_explicit_confirmation"
                    ),
                    "next_invocation": next_invocation,
                    "required_authority_input": _authority_input(
                        "--confirm-intent",
                        (
                            "Transmit the user's explicit approval of the reviewed "
                            "interpretation; conversational approval alone is not canonical."
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
                }
            )
        elif checkpoint_kind == "artifact_review":
            protocol.update(
                {
                    "supported_next_action": "obtain_exact_artifact_set_authorization",
                    "next_invocation": _invocation_template(
                        "authorize-artifacts",
                        required_flags=("--action", "--provenance"),
                        reused_inputs=("exact_visible_artifact_candidates",),
                        new_inputs=("exact_artifact_review_action",),
                    ),
                    "required_authority_input": _authority_input(
                        "--action",
                        "Approve, adjust, or decline the exact visible artifact set.",
                    ),
                    "awaiting_confirmation_fields": ["exact_artifact_review_action"],
                    "confirmation_transmission_state": "not_supplied",
                }
            )
        elif checkpoint_kind == "governing_change_confirmation":
            if operation == "continue_unchanged":
                next_invocation = _invocation_template(
                    "continue-unchanged",
                    required_flags=("--statement", "--approve"),
                    reused_inputs=("current_working_blueprint",),
                    new_inputs=("explicit_unchanged_continuation",),
                )
                authority_flag = "--approve"
                supported_action = "obtain_explicit_unchanged_continuation"
            else:
                next_invocation = _invocation_template(
                    "confirm-change",
                    required_flags=("--confirmation", "--approve"),
                    reused_inputs=("exact_carry_forward_proposal",),
                    new_inputs=("proposal_specific_confirmation",),
                    uses_transport=True,
                )
                authority_flag = "--approve"
                supported_action = "obtain_proposal_specific_confirmation"
            protocol.update(
                {
                    "supported_next_action": supported_action,
                    "next_invocation": next_invocation,
                    "required_authority_input": _authority_input(
                        authority_flag,
                        "Confirm only the exact reviewed governing action.",
                    ),
                    "awaiting_confirmation_fields": ["governing_change_or_unchanged_continuation"],
                    "confirmation_transmission_state": "not_supplied",
                }
            )
        elif phase == "continuation_choice":
            protocol.update(
                {
                    "supported_next_action": "obtain_continuation_choice",
                    "next_invocation": _invocation_template(
                        None,
                        alternatives=("continue-unchanged", "propose-change"),
                        reused_inputs=("current_build_review", "working_blueprint"),
                        new_inputs=("explicit_continuation_choice",),
                    ),
                    "required_authority_input": _authority_input(
                        None,
                        "Choose unchanged continuation or one bounded proposal selection.",
                    ),
                    "awaiting_confirmation_fields": ["continuation_choice"],
                    "confirmation_transmission_state": "not_supplied",
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
                }
            )
        if override:
            for key in protocol:
                if key in override:
                    protocol[key] = deepcopy(override[key])
        if protocol["confirmation_transmission_state"] not in (CONFIRMATION_TRANSMISSION_STATES):
            raise CurrentLoopError("confirmation_transmission_state_invalid")
        return protocol

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
            "details": deepcopy(dict(details or {})),
            "raw_protected_payload_included": False,
            "token_contents_included": False,
            "local_paths_transmitted": False,
            "assistant_reconstruction_performed": False,
            **protocol,
        }

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
    ) -> dict[str, Any]:
        normalized = _ERROR_ALIASES.get(category, category)
        recovery = _RECOVERY.get(
            normalized,
            _RECOVERY["protected_operation_rejected"],
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
        payload = {
            "message": recovery[0],
            "supported_next_action": recovery[1],
            "conversation_may_continue": recovery[2],
            "reauthorization_required": recovery[3],
            "local_state_intact": recovery[4],
            "certification_fallback_available": recovery[5],
            **deepcopy(dict(details or {})),
        }
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
            )
        coordinator = self._coordinator_state(state)
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
        self._replace_coordinator(coordinator)
        return self._result(
            operation=operation,
            ok=False,
            category=normalized,
            state=self.store.read(),
            summary=recovery[0],
            elapsed=elapsed,
            details=payload,
        )

    def _exception_result(self, operation: str, exc: Exception, started: float) -> dict[str, Any]:
        category = (
            exc.category if isinstance(exc, CurrentLoopError) else "protected_operation_rejected"
        )
        category = _ERROR_ALIASES.get(category, category)
        if category not in _RECOVERY:
            if "reconstruct" in category:
                category = "reconstruction_attempt_refused"
            elif "schema" in category or "version" in category:
                category = "unsupported_schema"
            elif "parent" in category or "digest" in category:
                category = "parent_digest_mismatch"
            elif "selected" in category or "artifact" in category:
                category = "protected_operation_rejected"
            else:
                category = "protected_operation_rejected"
        return self._recovery_result(
            operation=operation,
            category=category,
            phase=self._safe_phase(),
            elapsed=max(0.0, self.clock() - started),
        )

    def _safe_phase(self) -> str:
        try:
            return self._coordinator_state(self.store.read())["phase"]
        except CurrentLoopError:
            return "activated"
