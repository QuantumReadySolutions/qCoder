"""Natural IDE orchestration over deterministic current-loop state.

Conversation may choose an operation and present its result. This module owns
the canonical local state, exact artifacts, protected request construction, and
human checkpoints. It never reconstructs required state from conversation.
"""

from __future__ import annotations

from copy import deepcopy
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
from qcoder.blueprint_decisions import consistency_digest
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

COORDINATOR_RESULT_SCHEMA_ID = "qcoder.current_loop.coordinator_result.v1"
COORDINATOR_STATE_SCHEMA_ID = "qcoder.current_loop.coordinator_state.v1"
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
    "ide_write_or_run",
    "artifact_review",
    "governing_change_confirmation",
    "privacy_or_trust",
    "none",
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
    "ide_write_or_run": "Authorize the IDE host separately before writing or executing code.",
    "artifact_review": "Approve the exact visible artifact set qCoder may inspect locally.",
    "governing_change_confirmation": (
        "Explicitly confirm the exact Carry-Forward Proposal before governing intent changes."
    ),
    "privacy_or_trust": "Review the material privacy, trust, or evidence limitation.",
    "none": "No human authority is required for the next deterministic local transition.",
}

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
        return self._result(
            operation="status",
            ok=coordinator["state_status"] not in {"blocked", "conflict", "corrupt"},
            state=state,
            summary=coordinator["customer_summary"],
            elapsed=self.clock() - started,
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
            baseline = self._saved_artifact(state, "request_baseline")
            original_request = baseline.get("original_request")
            if not isinstance(original_request, str):
                raise CurrentLoopError("canonical_artifact_modified")
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
                "decision_dispositions": [deepcopy(dict(item)) for item in decision_dispositions],
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
            if confirmation_assertion:
                intent_arguments["confirmation_assertion"] = confirmation_assertion
            intent_payload = self._protected_call("create_algorithm_intent_card", intent_arguments)
            intent = self._response_artifact(intent_payload, "algorithm_intent_card")
            if intent.get("confirmation_state") != "confirmed":
                self._save_intent_review_artifact(intent)
                coordinator = self._coordinator_state(self.store.read())
                coordinator.update(
                    {
                        "phase": "intent_review",
                        "state_status": "checkpoint_required",
                        "checkpoint_kind": "intent_review",
                        "customer_summary": (
                            "The assistant-proposed interpretation still needs explicit "
                            "review or clarification."
                        ),
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
                        "intent_confirmation_state": intent.get("confirmation_state"),
                        "working_blueprint_created": False,
                        "generation_context_created": False,
                    },
                )
            self._save_artifact(
                "algorithm_intent_card",
                intent,
                "algorithm-intent-card.json",
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
            self._save_artifact(
                "working_blueprint",
                blueprint,
                "working-blueprint.json",
            )
            self._save_artifact(
                "output_evidence_contract",
                output_contract,
                "output-evidence-contract.json",
            )
            generation_payload = self._protected_call(
                "create_generation_context_pack",
                {
                    "implementation_blueprint": blueprint,
                    "output_evidence_contract": output_contract,
                },
            )
            generation = self._response_artifact(generation_payload, "generation_context_pack")
            self._save_artifact(
                "generation_context_pack",
                generation,
                "generation-context-pack.json",
            )
            coordinator = self._coordinator_state(self.store.read())
            coordinator.update(
                {
                    "phase": "generation_ready",
                    "state_status": "checkpoint_required",
                    "checkpoint_kind": "ide_write_or_run",
                    "customer_summary": (
                        "Generation context is ready. Writing or running code in the "
                        "IDE is a separate user authority."
                    ),
                    "canonical_decision_inventory": intent_binding,
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
                    "working_blueprint_created": True,
                    "output_evidence_contract_created": True,
                    "generation_context_created": True,
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

    def _saved_artifact(self, state: Mapping[str, Any], role: str) -> dict[str, Any]:
        descriptor = state.get("saved_artifacts", {}).get(role)
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
        mapping = {
            "request_baseline": "request_baseline_handoff",
            "working_blueprint": "working_blueprint",
            "generation_context": "generation_context_pack",
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
            "schema_version": 1,
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
            result.get("schema_id") != COORDINATOR_STATE_SCHEMA_ID
            or result.get("schema_version") != 1
            or result.get("phase") not in PHASES
            or result.get("state_status") not in STATE_STATUSES
            or result.get("checkpoint_kind") not in CHECKPOINT_KINDS
        ):
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
        return result

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
    ) -> dict[str, Any]:
        coordinator = self._coordinator_state(state)
        coordinator["performance"]["coordinator_calls"] += 1
        coordinator["performance"]["coordinator_seconds"] += max(0.0, elapsed)
        self._replace_coordinator(coordinator)
        state = self.store.read()
        coordinator = self._coordinator_state(state)
        return {
            "schema_id": COORDINATOR_RESULT_SCHEMA_ID,
            "schema_version": 1,
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
    ) -> dict[str, Any]:
        return {
            "schema_id": COORDINATOR_RESULT_SCHEMA_ID,
            "schema_version": 1,
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
        }

    def _checkpoint_result(
        self,
        *,
        operation: str,
        phase: str,
        checkpoint_kind: str,
        summary: str,
        elapsed: float,
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
