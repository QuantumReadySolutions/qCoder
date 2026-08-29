"""Project-local typed MCP transport for Current Step transactions.

This adapter is deliberately separate from the twelve-tool public Context
Bridge surface.  It exposes two binding-owned internal operations so a connected
assistant can begin and complete one exact Current Step without reconstructing
a local command, stdin pipeline, receipt, digest, or stage ceiling.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

from qcoder import __version__
from qcoder.context_bridge_connection import record_server_exchange
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_artifact_targets import (
    ArtifactTargetError,
    MAX_TARGET_PATH_BYTES,
    current_registered_role_target,
    normalize_completion_artifact_path,
    normalize_intended_artifact_targets,
    normalize_selected_artifact_paths,
    target_contract_snapshot,
)
from qcoder.current_loop_request_semantics import classify_current_request
from qcoder.current_loop_pending_completion import (
    PendingCompletionError,
    validate_pending_completion_checkpoint,
)
from qcoder.current_loop_result_controls import ResultControlError
from qcoder.current_step_contract import (
    derive_current_step_contract,
    quiet_customer_visibility_contract,
)

BINDING_MCP_SCHEMA_ID = "qcoder.current_loop.binding_mcp.v12"
BINDING_MCP_SCHEMA_VERSION = 12
BINDING_MCP_SERVER_NAME = "qcoder-current-loop"
BEGIN_CURRENT_LOOP_TOOL_NAME = "begin_current_loop"
COMPLETE_CURRENT_STEP_TOOL_NAME = "complete_current_step"
MAX_REQUEST_BYTES = 65_536
MAX_PATH_BYTES = 16_384


def _request_explicitly_selects_target(request_text: str, target: str) -> bool:
    normalized_request = request_text.replace("\\", "/").casefold()
    normalized_target = target.replace("\\", "/").casefold()
    return bool(
        normalized_target
        and re.search(
            rf"(?<![\w./-]){re.escape(normalized_target)}(?![\w./-])",
            normalized_request,
        )
    )


def binding_tool_descriptors() -> list[dict[str, Any]]:
    """Return the two private operations in the client-neutral transaction."""

    return [
        {
            "name": BEGIN_CURRENT_LOOP_TOOL_NAME,
            "description": (
                "INTERNAL NORMAL-PATH OPERATION: call as the first response action without a "
                "customer-facing preface. Begin qCoder's bounded Current Loop, or interpret the "
                "exact next instruction against an already complete-resumable loop. "
                "Supply request_text exactly once as the complete unmodified customer message. "
                "For an artifact-producing request, also supply one exact workspace-relative "
                "intended_artifact_paths entry for every requested role on a fresh loop. For an "
                "active-loop replacement, omit the path: qCoder binds the current registered "
                "role-head target automatically. A different target is accepted only when the "
                "exact customer message names that workspace-relative path. Never read, list, "
                "glob, or search the workspace to choose a target. qCoder binds it before any "
                "native action. "
                "For an exact selected result-evidence control request, copy the customer-named "
                "workspace-relative paths in order into selected_artifact_paths; never read or "
                "search for them. qCoder returns the terminal bounded control disposition with "
                "no native action. For an exact pre-existing source satisfaction request, copy "
                "its one customer-named path into selected_artifact_paths; qCoder binds it as the "
                "source target without a write. "
                "This operation preserves the Request Baseline, classifies authority fail-closed, "
                "and grants no native write, execution, review, or governing authority. On an "
                "active loop, call it directly without narrating or reconstructing continuation "
                "procedure; the returned replacement Current Step Contract is the only action "
                "source."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_text": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_REQUEST_BYTES,
                        "description": "Exact complete current customer message, unchanged.",
                    },
                    "intended_artifact_paths": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string", "maxLength": MAX_TARGET_PATH_BYTES},
                            "circuit_qasm": {
                                "type": "string",
                                "maxLength": MAX_TARGET_PATH_BYTES,
                            },
                            "results": {"type": "string", "maxLength": MAX_TARGET_PATH_BYTES},
                        },
                        "additionalProperties": False,
                        "description": (
                            "Fresh-loop exact workspace-relative targets. Omit for an active-loop "
                            "replacement so qCoder reuses the registered current role-head target."
                        ),
                    },
                    "selected_artifact_paths": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 2,
                        "uniqueItems": True,
                        "items": {"type": "string", "maxLength": MAX_TARGET_PATH_BYTES},
                        "description": (
                            "Copy only exact workspace-relative paths explicitly named by the "
                            "customer. Use two for bounded result-evidence controls or one for "
                            "pre-existing exact source satisfaction. Never discover paths."
                        ),
                    },
                },
                "required": ["request_text"],
                "additionalProperties": False,
            },
            "x-qcoder-binding-owned-internal-operation": True,
            "x-qcoder-public-context-bridge-tool": False,
            "x-qcoder-normal-happy-path": {
                "request_text": "<exact current customer message>",
                "intended_artifact_paths": {"source": "<exact workspace-relative filename>"},
            },
            "x-qcoder-artifact-target-contract": target_contract_snapshot(),
            "x-qcoder-selected-result-control-happy-path": {
                "request_text": "<exact complete customer message>",
                "selected_artifact_paths": [
                    "<first exact customer-named relative path>",
                    "<second exact customer-named relative path>",
                ],
                "terminal_read_only_projection": True,
                "native_action_required": False,
            },
            "x-qcoder-preexisting-source-happy-path": {
                "request_text": "<exact complete customer message>",
                "selected_artifact_paths": ["<exact customer-named relative source path>"],
                "native_write_required": False,
                "completion_arguments": {},
                "artifact_disposition_derived_by_qcoder": "pre_existing_exact_artifact",
            },
            "x-qcoder-active-loop-continuation": {
                "request_text": "<exact next customer message>",
                "reuse_active_loop": True,
                "rebootstrap": False,
                "request_baseline_recreated": False,
                "pre_contract_procedure_reasoning": False,
                "customer_visible_transition_narration": False,
                "action_source": "replacement_current_step_contract",
                "replacement_target_source": "registered_current_role_head",
                "replacement_target_model_selection_required": False,
                "different_target_requires_exact_customer_path_selection": True,
            },
            "x-qcoder-customer-visibility": quiet_customer_visibility_contract(),
            "x-qcoder-normal-success-presentation": {
                "customer_message_before_tool_call": "none",
                "customer_message_after_tool_call": "none_or_task_level_progress_only",
                "internal_mechanics_explanation": False,
            },
        },
        {
            "name": COMPLETE_CURRENT_STEP_TOOL_NAME,
            "description": (
                "BOUNDED COMPLETION AND RECOVERY OPERATION: call this operation after the native "
                "action only when current_step_contract.completion.mode is "
                "binding_owned_typed_completion, or when qCoder reports pending recovery. "
                "When the contract selects synchronous_native_edit_event terminal closure, do not "
                "make a duplicate completion call. For an applicable pending completion, call "
                "this operation directly with an empty object, including "
                "on a later turn or same-host MCP restart. Do not call begin_current_loop, inspect "
                "state/help, refresh the result, or rerun execution. Call without a customer-facing "
                "transition message. "
                "a customer-facing transition message. Complete the exact active qCoder Current "
                "Step after the native client has "
                "performed its action under its own controls. qCoder resolves its durable opaque "
                "action handle and exact bound workspace-relative target. Optional explicit "
                "handle/path compatibility fields must match that same checkpoint exactly. "
                "qCoder reads and validates the actual bytes; do not supply permission state, "
                "digests, loop revisions, receipt identities, roles, or stage ceilings."
                " For a result step, artifact_path transports the exact strict-result-manifest "
                "file required by the returned Current Step Contract; bare counts are not "
                "current result evidence. Use only an already prepared and prevalidated "
                "native-client runtime. Dependency installation, environment mutation, analytic "
                "substitution for sampled shots, and additional execution attempts are outside "
                "the step; surface a blocker instead. On result success, use the returned "
                "canonical current_run_summary for the requested final outcome."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "current_action_handle": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 256,
                        "description": "Opaque current-action handle from Current Step Contract.",
                    },
                    "artifact_path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_PATH_BYTES,
                        "description": (
                            "Copy the exact workspace-relative artifact_path value from the "
                            "Current Step Contract; absolute paths are not accepted."
                        ),
                        "x-qcoder-path-form": "workspace_relative_bound_target",
                    },
                    "artifact_disposition": {
                        "type": "string",
                        "enum": [
                            "assistant_created",
                            "assistant_modified",
                            "pre_existing_exact_artifact",
                            "explicitly_user_selected_or_supplied",
                        ],
                        "default": "assistant_created",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            "x-qcoder-binding-owned-internal-operation": True,
            "x-qcoder-public-context-bridge-tool": False,
            "x-qcoder-normal-happy-path": {},
            "x-qcoder-pending-completion": {
                "sole_next_qcoder_operation": True,
                "direct_later_turn_completion": True,
                "begin_current_loop_required": False,
                "external_execution_rerun_permitted": False,
            },
            "x-qcoder-native-permission-owner": "native_client",
            "x-qcoder-hooks-required-for-correctness": False,
            "x-qcoder-strict-result-manifest-transport": "exact_artifact_path",
            "x-qcoder-customer-visibility": quiet_customer_visibility_contract(),
            "x-qcoder-normal-success-presentation": {
                "customer_message_before_tool_call": "none",
                "customer_message_after_tool_call": "one_concise_task_outcome",
                "internal_mechanics_explanation": False,
            },
        },
    ]


def _result(message_id: object, value: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": dict(value)}


def _error(message_id: object, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _tool_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(payload)
    return {
        "content": [{"type": "text", "text": json.dumps(value, sort_keys=True)}],
        "structuredContent": value,
        "isError": value.get("ok") is not True,
    }


def handle_binding_jsonrpc_message(
    message: Mapping[str, Any], *, workspace_root: str | Path
) -> dict[str, Any] | None:
    """Handle one MCP request without accepting workspace or authority from the model."""

    method = message.get("method")
    message_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return _result(
            message_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": BINDING_MCP_SERVER_NAME, "version": __version__},
                "instructions": (
                    "NORMAL SUCCESS EVENT ORDER: the first response event is begin_current_loop, "
                    "not customer-facing text. Do not send a customer-visible message before "
                    "begin_current_loop, between the native task and "
                    "complete_current_step, or to explain the transaction. Optional progress is "
                    "task-level only; after successful completion give one concise task outcome. "
                    "Never describe activation or loop/step transitions, contracts or bounded "
                    "authority, typed completion or registration, receipts, revisions, hooks, or "
                    "evidence bookkeeping during normal success. "
                    "Surface qCoder mechanics only for a real blocker, ambiguity, bounded "
                    "recovery, meaningful authority broadening, or requested qCoder help. "
                    "This project-local qCoder binding exposes two typed operations for one "
                    "Current Step transaction. Begin once. Then follow only "
                    "current_step_contract.completion: an exact native-edit event performs "
                    "synchronous deterministic terminal closure when selected; otherwise call "
                    "complete_current_step after the native action. Never duplicate completion. "
                    "Native permission remains client-owned. "
                    "For an active-loop continuation, call begin_current_loop immediately with "
                    "the exact next customer message; silently use its compact replacement "
                    "contract without re-bootstrap, baseline recreation, or procedure narration. "
                    "Do not construct Shell commands, stdin pipelines, receipts, digests, loop "
                    "revisions, roles, or stage ceilings. The returned current_step_contract is "
                    "the only current-stage action source. Hooks may accelerate completion but "
                    "are never required for correctness. For a fresh artifact-producing request, "
                    "supply intended_artifact_paths in the first begin call. For an active-loop "
                    "replacement, omit the path and let qCoder bind the registered current "
                    "role-head target; never rediscover or reselect it. A different target is "
                    "valid only when the exact customer message explicitly names it. Do not "
                    "Read, Glob, Grep, list, scan, or search the workspace to select a target. "
                    "Use only the exact target returned in the Current Step Contract."
                    " For exact selected result-evidence controls, copy the customer-named "
                    "relative paths directly into selected_artifact_paths and use the returned "
                    "terminal control projection. Do not use CLI/help, inspect state or package "
                    "files, read the controls yourself, or search any workspace. This operation "
                    "never executes or changes the current registered result. For an explicitly "
                    "selected pre-existing source, pass its one exact named path in the same "
                    "field; no native write is required and qCoder derives selected provenance."
                    " If a pending completion exists, complete_current_step is the sole next "
                    "qCoder operation: call it directly with an empty object even on a later turn "
                    "or same-host MCP restart. Do not call begin_current_loop, inspect state/help, "
                    "refresh/restage the artifact, or rerun external execution."
                    " For an external execution step, use only an already prepared and "
                    "prevalidated native-client runtime. The step does not authorize dependency "
                    "installation, environment mutation, analytic substitution for sampled "
                    "shots, or an additional execution attempt; return a blocker instead."
                ),
            },
        )
    if method == "tools/list":
        return _result(message_id, {"tools": binding_tool_descriptors()})
    if method != "tools/call":
        return _error(message_id, -32601, "method_not_supported")

    params = message.get("params")
    if not isinstance(params, Mapping) or params.get("name") not in {
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
    }:
        return _error(message_id, -32602, "unknown_binding_operation")
    operation_name = str(params.get("name"))
    arguments = params.get("arguments")
    if operation_name == COMPLETE_CURRENT_STEP_TOOL_NAME:
        allowed = {"current_action_handle", "artifact_path", "artifact_disposition"}
        explicit_identity = isinstance(arguments, Mapping) and (
            "current_action_handle" in arguments or "artifact_path" in arguments
        )
        if (
            not isinstance(arguments, Mapping)
            or set(arguments).difference(allowed)
            or (
                explicit_identity
                and not {"current_action_handle", "artifact_path"}.issubset(arguments)
            )
            or (
                explicit_identity
                and (
                    not isinstance(arguments.get("current_action_handle"), str)
                    or not arguments["current_action_handle"]
                    or len(arguments["current_action_handle"].encode("utf-8")) > 256
                    or not isinstance(arguments.get("artifact_path"), str)
                    or not arguments["artifact_path"]
                    or len(arguments["artifact_path"].encode("utf-8")) > MAX_PATH_BYTES
                )
            )
            or arguments.get("artifact_disposition", "assistant_created")
            not in {
                "assistant_created",
                "assistant_modified",
                "pre_existing_exact_artifact",
                "explicitly_user_selected_or_supplied",
            }
        ):
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.typed_completion_rejection.v1",
                        "ok": False,
                        "category": "typed_completion_shape_invalid",
                        "expected_shape": {
                            "canonical": {},
                            "compatibility": "both exact handle and bound relative path",
                            "artifact_disposition": (
                                "optional created, modified, pre-existing, or explicit-selection enum"
                            ),
                        },
                        "state_mutated": False,
                        "raw_path_echoed": False,
                    }
                ),
            )
        binding_workspace = Path(workspace_root).expanduser().absolute()
        try:
            normalized_completion_path = (
                normalize_completion_artifact_path(
                    arguments["artifact_path"], workspace_root=binding_workspace
                )
                if explicit_identity
                else None
            )
        except ArtifactTargetError as exc:
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.typed_completion_rejection.v2",
                        "ok": False,
                        "category": str(exc),
                        "expected_path_form": "workspace_relative_bound_target",
                        "copy_from": "current_step_contract.completion.artifact_path",
                        "absolute_path_accepted": False,
                        "workspace_discovery_permitted": False,
                        "state_mutated": False,
                        "raw_path_echoed": False,
                    }
                ),
            )
        coordinator = CurrentLoopCoordinator(
            workspace_root=binding_workspace,
            runtime_executable=sys.executable,
        )
        completion_disposition = arguments.get("artifact_disposition")
        if completion_disposition is None:
            current = coordinator.store.read()
            current_semantics = current.get("coordinator", {}).get("current_request_semantics")
            completion_disposition = (
                "pre_existing_exact_artifact"
                if isinstance(current_semantics, Mapping)
                and current_semantics.get("preexisting_exact_source_satisfaction_requested") is True
                else "assistant_created"
            )
        payload = coordinator.complete_current_step(
            current_action_handle=(
                str(arguments["current_action_handle"]) if explicit_identity else None
            ),
            artifact_path=(str(normalized_completion_path) if normalized_completion_path else None),
            artifact_disposition=str(completion_disposition),
        )
        return _result(message_id, _tool_result(payload))

    if (
        not isinstance(arguments, Mapping)
        or set(arguments).difference(
            {"request_text", "intended_artifact_paths", "selected_artifact_paths"}
        )
        or "request_text" not in arguments
    ):
        return _result(
            message_id,
            _tool_result(
                {
                    "schema_id": "qcoder.current_loop.structured_activation_rejection.v1",
                    "ok": False,
                    "category": "exact_request_text_argument_required",
                    "expected_shape": {
                        "request_text": "nonempty exact customer message",
                        "intended_artifact_paths": (
                            "exact role-to-workspace-relative-path map for artifact requests"
                        ),
                        "selected_artifact_paths": (
                            "bounded exact customer-named workspace-relative path list"
                        ),
                    },
                    "state_mutated": False,
                    "raw_request_echoed": False,
                }
            ),
        )
    request_text = arguments.get("request_text")
    if (
        not isinstance(request_text, str)
        or not request_text
        or len(request_text.encode("utf-8")) > MAX_REQUEST_BYTES
    ):
        return _result(
            message_id,
            _tool_result(
                {
                    "schema_id": "qcoder.current_loop.structured_activation_rejection.v1",
                    "ok": False,
                    "category": "exact_request_text_invalid",
                    "state_mutated": False,
                    "raw_request_echoed": False,
                }
            ),
        )

    coordinator = CurrentLoopCoordinator(
        workspace_root=Path(workspace_root).expanduser().absolute(),
        runtime_executable=sys.executable,
    )
    state_path = coordinator.workspace_root / ".qcoder" / "current-loop" / "state.json"
    continuation = False
    active_state: Mapping[str, Any] | None = None
    if state_path.is_file() and not state_path.is_symlink():
        current = coordinator.store.read()
        active_state = current
        current_status = current.get("coordinator", {}).get("current_step_status")
        if current_status == "awaiting_external_client_action":
            try:
                checkpoint, _receipt = validate_pending_completion_checkpoint(
                    state=current,
                    coordinator=coordinator._coordinator_state(current),
                    current_time=coordinator.clock(),
                )
                contract = derive_current_step_contract(current)
            except (PendingCompletionError, ValueError) as exc:
                return _result(
                    message_id,
                    _tool_result(
                        {
                            "schema_id": "qcoder.current_loop.pending_completion_blocker.v1",
                            "ok": False,
                            "category": str(getattr(exc, "category", exc)),
                            "state_mutated": False,
                            "external_execution_rerun_permitted": False,
                            "recovery": "honest_blocker_no_refresh_or_restage",
                        }
                    ),
                )
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.pending_completion_resume.v1",
                        "schema_version": 1,
                        "ok": True,
                        "operation": "begin_current_loop",
                        "category": "pending_completion_already_active",
                        "state_revision": current["state_revision"],
                        "state_mutated": False,
                        "bootstrap_count": current["coordinator"].get("bootstrap_count"),
                        "request_baseline_count": current["coordinator"].get(
                            "request_baseline_count"
                        ),
                        "current_step_contract": contract,
                        "pending_completion": {
                            "checkpoint_digest": checkpoint.get("checkpoint_digest"),
                            "sole_next_qcoder_operation": "complete_current_step",
                            "canonical_arguments": {},
                            "external_execution_rerun_permitted": False,
                            "state_or_help_archaeology_required": False,
                        },
                    }
                ),
            )
        continuation = current_status == "complete_resumable"
    selected_paths_value = arguments.get("selected_artifact_paths")
    if selected_paths_value is not None and (
        not isinstance(selected_paths_value, list)
        or any(not isinstance(item, str) for item in selected_paths_value)
    ):
        return _result(
            message_id,
            _tool_result(
                {
                    "schema_id": "qcoder.current_loop.selected_artifact_transport_rejection.v1",
                    "ok": False,
                    "category": "exact_selected_artifact_paths_required",
                    "expected_shape": {
                        "selected_artifact_paths": ["exact customer-named workspace-relative path"]
                    },
                    "workspace_discovery_permitted": False,
                    "cli_or_help_fallback_permitted": False,
                    "state_mutated": False,
                }
            ),
        )
    selected_paths = list(selected_paths_value or [])
    semantics = classify_current_request(
        request_text,
        active_loop=continuation,
        selected_paths=selected_paths,
    )
    if semantics.get("requested_operation") == "selected_result_evidence_controls":
        if arguments.get("intended_artifact_paths") is not None:
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.selected_result_control_rejection.v1",
                        "ok": False,
                        "category": "selected_result_controls_use_selected_artifact_paths_only",
                        "workspace_discovery_permitted": False,
                        "cli_or_help_fallback_permitted": False,
                        "state_mutated": False,
                    }
                ),
            )
        try:
            normalized_selected = normalize_selected_artifact_paths(
                selected_paths,
                workspace_root=coordinator.workspace_root,
                minimum_count=2,
                maximum_count=2,
            )
            if any(
                not _request_explicitly_selects_target(
                    request_text, str(item["workspace_relative_path"])
                )
                for item in normalized_selected
            ):
                raise ArtifactTargetError("selected_result_control_path_not_named_by_customer")
            payload = coordinator.interpret_current_request(
                exact_message=request_text,
                selected_paths=[
                    str(item["workspace_relative_path"]) for item in normalized_selected
                ],
            )
        except (ArtifactTargetError, ResultControlError) as exc:
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.selected_result_control_rejection.v1",
                        "ok": False,
                        "category": str(getattr(exc, "category", exc)),
                        "workspace_discovery_permitted": False,
                        "cli_or_help_fallback_permitted": False,
                        "state_mutated": False,
                    }
                ),
            )
        payload.setdefault("details", {}).update(
            {
                "structured_selected_artifact_transport": "project_local_binding_mcp",
                "selected_artifact_paths_received_once": True,
                "selected_artifact_count": len(normalized_selected),
                "shell_or_cli_transport_used": False,
                "workspace_discovery_performed": False,
                "public_context_bridge_tool": False,
            }
        )
        return _result(message_id, _tool_result(payload))
    actionable_artifact_request = semantics.get(
        "clarification_required"
    ) is False and semantics.get("requested_operation") in {
        "source_generation",
        "source_and_qasm_generation",
        "source_and_local_execution",
        "qasm_export",
        "local_execution",
    }
    required_roles = (
        semantics.get("requested_artifact_roles", ()) if actionable_artifact_request else ()
    )
    intended_paths_value = arguments.get("intended_artifact_paths")
    if intended_paths_value is not None and not isinstance(intended_paths_value, Mapping):
        return _result(
            message_id,
            _tool_result(
                {
                    "schema_id": "qcoder.current_loop.structured_activation_rejection.v2",
                    "ok": False,
                    "category": "exact_intended_artifact_targets_required",
                    "workspace_discovery_permitted": False,
                    "state_mutated": False,
                }
            ),
        )
    intended_paths = dict(intended_paths_value) if isinstance(intended_paths_value, Mapping) else {}
    if semantics.get("preexisting_exact_source_satisfaction_requested") is True:
        if len(selected_paths) != 1 or intended_paths:
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.preexisting_satisfaction_rejection.v1",
                        "ok": False,
                        "category": "exact_one_selected_preexisting_source_required",
                        "workspace_discovery_permitted": False,
                        "state_mutated": False,
                    }
                ),
            )
        try:
            selected_source = normalize_selected_artifact_paths(
                selected_paths,
                workspace_root=coordinator.workspace_root,
                minimum_count=1,
                maximum_count=1,
            )[0]
        except ArtifactTargetError as exc:
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.preexisting_satisfaction_rejection.v1",
                        "ok": False,
                        "category": str(exc),
                        "workspace_discovery_permitted": False,
                        "state_mutated": False,
                    }
                ),
            )
        selected_relative = str(selected_source["workspace_relative_path"])
        if not _request_explicitly_selects_target(request_text, selected_relative):
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.preexisting_satisfaction_rejection.v1",
                        "ok": False,
                        "category": "preexisting_source_path_not_named_by_customer",
                        "workspace_discovery_permitted": False,
                        "state_mutated": False,
                    }
                ),
            )
        intended_paths["source"] = selected_relative
    target_continuity: dict[str, dict[str, Any]] = {}
    if continuation and isinstance(active_state, Mapping) and isinstance(required_roles, list):
        try:
            for role in required_roles:
                if role not in {"source", "circuit_qasm"}:
                    continue
                current_target = current_registered_role_target(
                    active_state,
                    role=str(role),
                    workspace_root=coordinator.workspace_root,
                )
                if current_target is None:
                    continue
                current_relative = str(current_target["workspace_relative_path"])
                supplied = intended_paths.get(str(role))
                if supplied is None:
                    intended_paths[str(role)] = current_relative
                    target_continuity[str(role)] = current_target
                    continue
                normalized_supplied = normalize_intended_artifact_targets(
                    {str(role): supplied},
                    workspace_root=coordinator.workspace_root,
                    required_roles=(str(role),),
                )[str(role)]
                supplied_relative = str(normalized_supplied["workspace_relative_path"])
                if supplied_relative == current_relative:
                    target_continuity[str(role)] = current_target
                    continue
                if not _request_explicitly_selects_target(request_text, supplied_relative):
                    raise ArtifactTargetError(
                        "active_loop_replacement_target_requires_exact_customer_selection"
                    )
        except ArtifactTargetError as exc:
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.replacement_target_rejection.v1",
                        "ok": False,
                        "category": str(exc),
                        "current_registered_target_retained": True,
                        "workspace_discovery_permitted": False,
                        "selected_file_review_inferred": False,
                        "state_mutated": False,
                    }
                ),
            )
    try:
        normalize_intended_artifact_targets(
            intended_paths or None,
            workspace_root=coordinator.workspace_root,
            required_roles=required_roles if isinstance(required_roles, list) else (),
        )
    except ArtifactTargetError as exc:
        return _result(
            message_id,
            _tool_result(
                {
                    "schema_id": "qcoder.current_loop.structured_activation_rejection.v2",
                    "ok": False,
                    "category": str(exc),
                    "expected_shape": {
                        "request_text": "exact customer message",
                        "intended_artifact_paths": {
                            str(role): "exact workspace-relative path" for role in required_roles
                        },
                    },
                    "workspace_discovery_permitted": False,
                    "state_mutated": False,
                    "raw_request_echoed": False,
                    "raw_absolute_path_echoed": False,
                }
            ),
        )
    payload = (
        coordinator.interpret_current_request(
            exact_message=request_text,
            selected_paths=selected_paths,
            intended_artifact_paths=(intended_paths or None),
            intended_artifact_target_binding_modes={
                role: "registered_current_role_head_exact_target" for role in target_continuity
            }
            or None,
        )
        if continuation
        else coordinator.activate(
            original_request=request_text,
            explicit_authority=True,
            capture_mode="exact_current_customer_message",
            request_transport="binding_owned_structured_mcp_argument",
            intended_artifact_paths=(intended_paths or None),
        )
    )
    payload.setdefault("details", {}).update(
        {
            "structured_activation_transport": "project_local_binding_mcp",
            "request_text_argument_received_once": True,
            "shell_or_cli_transport_used": False,
            "stdin_transport_used": False,
            "public_context_bridge_tool": False,
            "active_loop_continuation": continuation,
            "request_baseline_recreated": False if continuation else None,
            "rebootstrap_performed": False if continuation else None,
            "active_loop_target_continuity": {
                role: {
                    "binding_mode": value.get("binding_mode"),
                    "artifact_revision_id": value.get("artifact_revision_id"),
                    "workspace_discovery_performed": False,
                }
                for role, value in sorted(target_continuity.items())
            },
        }
    )
    return _result(message_id, _tool_result(payload))


def _write_content_length_response(response: Mapping[str, Any]) -> None:
    data = json.dumps(dict(response), sort_keys=True, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _record_connection_exchange_best_effort(
    *,
    connection_state_root: str | Path | None,
    connection_generation: str | None,
    connection_session_sha256: str | None,
    message: object,
    response: Mapping[str, Any] | None,
) -> None:
    if (
        connection_state_root is None
        or connection_generation is None
        or connection_session_sha256 is None
        or not isinstance(message, Mapping)
    ):
        return
    try:
        record_server_exchange(
            state_root=connection_state_root,
            setup_generation=connection_generation,
            configured_client_session_sha256=connection_session_sha256,
            server_name=BINDING_MCP_SERVER_NAME,
            request=message,
            response=response,
        )
    except Exception:  # noqa: BLE001 - diagnostic failure must not alter the protocol response
        return


def serve_binding_mcp_stdio(
    *,
    workspace_root: str | Path,
    connection_state_root: str | Path | None = None,
    connection_generation: str | None = None,
    connection_session_sha256: str | None = None,
) -> int:
    """Serve the internal binding MCP over JSON-lines or Content-Length stdio."""

    stdin = sys.stdin.buffer
    while True:
        first = stdin.readline()
        if not first:
            break
        if not first.strip():
            continue
        framed = not first.lstrip().startswith(b"{")
        raw = first
        if framed:
            headers: dict[str, str] = {}
            line = first
            while line:
                stripped = line.strip()
                if not stripped:
                    break
                if b":" in stripped:
                    key, value = stripped.split(b":", 1)
                    headers[key.decode("ascii", "ignore").lower()] = value.decode(
                        "ascii", "ignore"
                    ).strip()
                line = stdin.readline()
            try:
                length = int(headers.get("content-length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > 1_048_576:
                response = _error(None, -32600, "invalid_content_length")
                _write_content_length_response(response)
                continue
            raw = stdin.read(length)
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            response = _error(None, -32700, "parse_error")
        else:
            response = (
                handle_binding_jsonrpc_message(message, workspace_root=workspace_root)
                if isinstance(message, Mapping)
                else _error(None, -32600, "invalid_request")
            )
            _record_connection_exchange_best_effort(
                connection_state_root=connection_state_root,
                connection_generation=connection_generation,
                connection_session_sha256=connection_session_sha256,
                message=message,
                response=response,
            )
        if response is None:
            continue
        if framed:
            _write_content_length_response(response)
        else:
            print(json.dumps(response, sort_keys=True), flush=True)
    return 0


__all__ = [
    "BEGIN_CURRENT_LOOP_TOOL_NAME",
    "COMPLETE_CURRENT_STEP_TOOL_NAME",
    "BINDING_MCP_SCHEMA_ID",
    "BINDING_MCP_SERVER_NAME",
    "binding_tool_descriptors",
    "handle_binding_jsonrpc_message",
    "serve_binding_mcp_stdio",
]
