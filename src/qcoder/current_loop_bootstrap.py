"""Pre-result Current Loop invocation contracts for connected assistants.

The bootstrap contract closes the boundary before a coordinator result exists.
qCoder owns the executable, operation, subcommand, fixed argv, input channel,
transport classification, and platform serialization.  The connected
assistant supplies only an exact active-workspace execution context and, for a
fresh active build, the customer's exact request bytes through stdin.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import shlex
import subprocess
from typing import Any, Mapping, Sequence


BOOTSTRAP_INVOCATION_SCHEMA_ID = "qcoder.current_loop.bootstrap_invocation.v2"
BOOTSTRAP_INVOCATION_SCHEMA_VERSION = 2
PRE_RESULT_ENTRY_INVENTORY_SCHEMA_ID = "qcoder.current_loop.pre_result_entry_inventory.v1"
PRE_RESULT_ENTRY_INVENTORY_SCHEMA_VERSION = 1
INVOCATION_LIFECYCLE_SCHEMA_ID = "qcoder.current_loop.invocation_lifecycle.v1"
INVOCATION_LIFECYCLE_SCHEMA_VERSION = 1

REQUEST_BASELINE_MAX_CODEPOINTS = 20_000
REQUEST_BASELINE_MAX_UTF8_BYTES = REQUEST_BASELINE_MAX_CODEPOINTS * 4

FRESH_ACTIVE_BUILD_ENTRYPOINT = "fresh_active_build_request_baseline_staging"
CURRENT_LOOP_STATUS_ENTRYPOINT = "existing_current_loop_status"


def _digest(value: Mapping[str, Any] | Sequence[Any]) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _workspace_contract() -> dict[str, Any]:
    return {
        "source": "exact_active_ide_or_explicit_customer_selected_workspace",
        "transport": "client_execution_working_directory",
        "argv_contains_workspace": False,
        "assistant_discovers_workspace": False,
        "assistant_manufactures_workspace_binding": False,
        "qcoder_canonicalization": "expanduser_then_absolute_without_hidden_lookup",
        "state_binding_created_from_execution_workspace": True,
        "later_invocations_bound_to_exact_recorded_workspace": True,
        "symlink_policy": (
            "state-path symlink components fail closed; platform cwd resolution may "
            "produce the operating system physical-path identity"
        ),
        "case_policy": "platform_filesystem_semantics_without_qcoder_case_rewriting",
        "inaccessible_workspace_result": "client_execution_failure_before_qcoder_state",
        "mismatched_workspace_result": "later_operation_invocation_workspace_mismatch",
    }


def _bootstrap_invocation(
    *,
    executable: str,
    entrypoint_id: str,
    operation: str,
    subcommand: str,
    fixed_arguments: Sequence[str] = (),
    input_channel: Mapping[str, Any],
    authority_effect: Mapping[str, Any],
    next_expected_result: Mapping[str, Any],
    failure_semantics: Mapping[str, Any],
) -> dict[str, Any]:
    argv = [
        executable,
        "-m",
        "qcoder",
        "current-loop",
        subcommand,
        *fixed_arguments,
    ]
    contract: dict[str, Any] = {
        "schema_id": BOOTSTRAP_INVOCATION_SCHEMA_ID,
        "schema_version": BOOTSTRAP_INVOCATION_SCHEMA_VERSION,
        "entrypoint_id": entrypoint_id,
        "workstyle": "active_build",
        "explicit_activation_requirement": (
            "explicit_use_qcoder_for_this_build_or_accepted_activation_offer"
        ),
        "operation": operation,
        "subcommand": subcommand,
        "executable": executable,
        "qcoder_owned_structured_argv": argv,
        "assistant_modifies_argv": False,
        "working_directory": _workspace_contract(),
        "input_channel": deepcopy(dict(input_channel)),
        "transport_classification": "local_only",
        "hosted_operation_permitted": False,
        "hosted_transport_argument_names": [],
        "client_environment_permission_may_be_encountered": False,
        "authority_effect": deepcopy(dict(authority_effect)),
        "state_binding": {
            "loop_ref": None,
            "revision": None,
            "checkpoint": None,
            "absence_reason": "no_coordinator_result_or_current_entry_binding_exists_yet",
            "created_or_resolved_by_first_result": True,
        },
        "next_expected_coordinator_result": deepcopy(dict(next_expected_result)),
        "failure_semantics": deepcopy(dict(failure_semantics)),
        "platform_serialization": {
            "posix": shlex.join(argv),
            "windows": subprocess.list2cmdline(argv),
            "assistant_reserializes": False,
            "working_directory_is_client_execution_metadata": True,
        },
        "prohibitions": [
            "do_not_run_help_to_discover_command_construction",
            "do_not_construct_from_coordinator_prefix",
            "do_not_construct_from_operation_inventory",
            "do_not_append_remove_reorder_or_reinterpret_arguments",
            "do_not_append_hosted_transport",
            "do_not_inspect_source_package_proof_transcript_or_qcoder_state",
            "do_not_scan_or_infer_workspace",
        ],
        "token_contents_embedded": False,
        "credential_bearing_metadata_embedded": False,
        "customer_types_command": False,
    }
    contract["canonical_structured_argv_digest"] = _digest({"argv": argv})
    contract["contract_digest"] = _digest(contract)
    return contract


def build_fresh_active_build_bootstrap(*, executable: str) -> dict[str, Any]:
    """Return exact-message Assist activation; strict review is a separate capture mode."""

    return _bootstrap_invocation(
        executable=executable,
        entrypoint_id=FRESH_ACTIVE_BUILD_ENTRYPOINT,
        operation="activate",
        subcommand="activate",
        fixed_arguments=(
            "--request-stdin",
            "--capture-mode",
            "exact_current_customer_message",
            "--approve",
        ),
        input_channel={
            "type": "exact_utf8_stdin",
            "customer_value_source": "complete_explicit_active_build_customer_message",
            "assistant_supplies_only": ["exact_original_request_utf8_bytes"],
            "encoding": "utf-8",
            "normalization": "none",
            "maximum_codepoints": REQUEST_BASELINE_MAX_CODEPOINTS,
            "maximum_utf8_bytes": REQUEST_BASELINE_MAX_UTF8_BYTES,
            "empty_input_permitted": False,
            "interactive_tty_permitted": False,
            "bounded_file_alternative": False,
            "arbitrary_request_text_in_argv": False,
        },
        authority_effect={
            "stages_content": True,
            "grants_qcoder_activation": True,
            "grants_request_baseline_approval": True,
            "activation_scope": "exact_current_customer_message_and_assist_only",
            "grants_posture_authority": False,
            "grants_ide_authority": False,
            "grants_artifact_review_authority": False,
            "grants_governing_change_authority": False,
            "protected_call_permitted": False,
        },
        next_expected_result={
            "schema_id": "qcoder.current_loop.coordinator_result.v10",
            "category": None,
            "checkpoint_kind": "none",
            "complete_exact_request_displayed": True,
            "next_invocation": "assist_ready_or_generation_posture_when_relevant",
            "request_content_retransmitted_on_approval": False,
            "activation_receipt_returned": True,
            "generation_posture_deferred": True,
        },
        failure_semantics={
            "assistant_should_stop": True,
            "hosted_operation_permitted": False,
            "state_created_only_after_valid_exact_input": True,
            "fresh_customer_input_required_for_invalid_or_empty_input": True,
            "fresh_bootstrap_contract_required": False,
            "retry_permitted_only_when_no_active_loop_was_created": True,
        },
    )


def build_current_loop_status_bootstrap(*, executable: str) -> dict[str, Any]:
    """Return the explicit, local-only existing-loop status invocation."""

    return _bootstrap_invocation(
        executable=executable,
        entrypoint_id=CURRENT_LOOP_STATUS_ENTRYPOINT,
        operation="status",
        subcommand="status",
        input_channel={
            "type": "none",
            "customer_value_source": "none",
            "assistant_supplies_only": [],
            "arbitrary_content_in_argv": False,
        },
        authority_effect={
            "stages_content": False,
            "grants_qcoder_activation": False,
            "grants_any_workflow_authority": False,
            "protected_call_permitted": False,
        },
        next_expected_result={
            "schema_id": "qcoder.current_loop.coordinator_result.v10",
            "category": "current_status_or_machine_readable_recovery",
            "missing_state_disposition": "explicit_machine_readable_no_action",
            "complete_operation_specific_next_invocation_when_actionable": True,
        },
        failure_semantics={
            "assistant_should_stop": True,
            "hosted_operation_permitted": False,
            "fresh_customer_input_required": False,
            "unsupported_or_missing_state_returns_machine_readable_recovery": True,
        },
    )


def pre_result_entry_inventory(*, executable: str) -> dict[str, Any]:
    """Return every connected-assistant workstyle disposition before a result."""

    active = build_fresh_active_build_bootstrap(executable=executable)
    status = build_current_loop_status_bootstrap(executable=executable)
    entries: list[dict[str, Any]] = [
        {
            "entrypoint_id": "available_inactive",
            "workstyle": "available_inactive",
            "customer_trigger": "no_explicit_qcoder_request",
            "supported": True,
            "current_loop_invocation": None,
            "action": "none",
            "state_created": False,
            "protected_access_possible": False,
        },
        {
            "entrypoint_id": "bounded_single_capability",
            "workstyle": "single_capability",
            "customer_trigger": "explicit_bounded_qcoder_capability_request",
            "supported": True,
            "current_loop_invocation": None,
            "action": "use_applicable_existing_context_bridge_mcp_tool",
            "state_created": False,
            "protected_access_possible": True,
            "activates_context_loop": False,
        },
        {
            "entrypoint_id": FRESH_ACTIVE_BUILD_ENTRYPOINT,
            "workstyle": "active_build",
            "customer_trigger": "explicit_use_qcoder_for_this_build_or_accepted_offer",
            "supported": True,
            "current_loop_invocation": active,
            "action": "stage_exact_request_baseline_without_authority",
            "state_created": "pending_activation_only_after_valid_input",
            "protected_access_possible": False,
        },
        {
            "entrypoint_id": CURRENT_LOOP_STATUS_ENTRYPOINT,
            "workstyle": "active_build",
            "customer_trigger": "explicit_status_or_continuation_of_an_existing_current_loop",
            "supported": True,
            "current_loop_invocation": status,
            "action": "read_coordinator_status_without_granting_authority",
            "state_created": False,
            "protected_access_possible": False,
        },
    ]
    unsupported = [
        {
            "entrypoint_id": "standalone_review_cli",
            "reason": "connected_single_capability_route_uses_existing_mcp_tool",
        },
        {
            "entrypoint_id": "attach_to_loop",
            "reason": "requires_existing_loop_and_coordinator_directed_authority_path",
        },
        {
            "entrypoint_id": "start_next",
            "reason": "requires_qcoder_supplied_completed_loop_seed_and_parent_references",
        },
        {
            "entrypoint_id": "abandon",
            "reason": "requires_existing_loop_result_and_explicit_authority",
        },
        {
            "entrypoint_id": "direct_post_result_operation",
            "reason": "requires_current_coordinator_result_and_operation_specific_invocation",
        },
    ]
    payload: dict[str, Any] = {
        "schema_id": PRE_RESULT_ENTRY_INVENTORY_SCHEMA_ID,
        "schema_version": PRE_RESULT_ENTRY_INVENTORY_SCHEMA_VERSION,
        "entries": entries,
        "unsupported_entries": unsupported,
        "assistant_constructs_commands_from_inventory": False,
        "new_customer_facing_operation_created": False,
    }
    payload["inventory_digest"] = _digest(payload)
    return payload


def bootstrap_contract_snapshot(*, executable: str) -> dict[str, Any]:
    inventory = pre_result_entry_inventory(executable=executable)
    active = build_fresh_active_build_bootstrap(executable=executable)
    status = build_current_loop_status_bootstrap(executable=executable)
    snapshot: dict[str, Any] = {
        "schema_id": BOOTSTRAP_INVOCATION_SCHEMA_ID,
        "schema_version": BOOTSTRAP_INVOCATION_SCHEMA_VERSION,
        "entry_inventory_schema_id": PRE_RESULT_ENTRY_INVENTORY_SCHEMA_ID,
        "entry_inventory_schema_version": PRE_RESULT_ENTRY_INVENTORY_SCHEMA_VERSION,
        "entry_inventory_digest": inventory["inventory_digest"],
        "supported_entrypoints": {
            FRESH_ACTIVE_BUILD_ENTRYPOINT: active,
            CURRENT_LOOP_STATUS_ENTRYPOINT: status,
        },
        "assistant_runs_help_for_construction": False,
        "coordinator_prefix_is_command_construction_primitive": False,
        "local_entry_excludes_hosted_transport": True,
        "request_baseline_staging_is_authority": "review_required_mode_false",
        "activation_capture_modes": {
            "exact_current_customer_message": {
                "single_exact_message_required": True,
                "assist_activation_in_same_invocation": True,
                "redundant_baseline_review_required": False,
            },
            "review_required": {
                "combined_or_changed_or_ambiguous_or_blueprint_guided": True,
                "staging_is_authority": False,
                "separate_approval_required": True,
            },
        },
    }
    snapshot["contract_digest"] = _digest(snapshot)
    return snapshot


def invocation_lifecycle_snapshot(
    *,
    executable: str,
    post_result_invocation_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind pre-result and post-result invocation ownership into one lifecycle."""

    bootstrap = bootstrap_contract_snapshot(executable=executable)
    lifecycle: dict[str, Any] = {
        "schema_id": INVOCATION_LIFECYCLE_SCHEMA_ID,
        "schema_version": INVOCATION_LIFECYCLE_SCHEMA_VERSION,
        "bootstrap_contract": bootstrap,
        "post_result_invocation_contract": deepcopy(dict(post_result_invocation_contract)),
        "gap_between_bootstrap_and_post_result": False,
        "qcoder_owns_complete_invocation_lifecycle": True,
    }
    lifecycle["contract_digest"] = _digest(lifecycle)
    return lifecycle
