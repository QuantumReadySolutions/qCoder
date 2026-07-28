"""Operation-specific Current Loop invocation construction.

This module is the single source of truth for whether a Current Loop operation
is local-only, hosted-capable, or dynamically scoped by staged checkpoint
input.  Connected assistants execute the invocation qCoder supplies; they do
not compose hosted transport arguments.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import shlex
import subprocess
from typing import Any, Mapping, Sequence


INVOCATION_CONTRACT_SCHEMA_ID = "qcoder.current_loop.operation_invocation.v1"
INVOCATION_CONTRACT_SCHEMA_VERSION = 1
OPERATION_INVENTORY_SCHEMA_ID = "qcoder.current_loop.operation_transport_inventory.v1"
OPERATION_INVENTORY_SCHEMA_VERSION = 1

LOCAL_ONLY = "local_only"
HOSTED_CAPABLE = "hosted_capable"
DYNAMIC_STAGED_OPERATION = "staged_operation_scoped"


_OPERATION_ROWS: tuple[dict[str, Any], ...] = (
    {"operation": "status", "subcommand": "status", "transport": LOCAL_ONLY},
    {"operation": "activate", "subcommand": "activate", "transport": LOCAL_ONLY},
    {
        "operation": "prepare_generation",
        "subcommand": "prepare-generation",
        "transport": HOSTED_CAPABLE,
    },
    {
        "operation": "record_ide_authority",
        "subcommand": "record-ide-authority",
        "transport": LOCAL_ONLY,
    },
    {
        "operation": "register_artifacts",
        "subcommand": "register-artifacts",
        "transport": LOCAL_ONLY,
    },
    {
        "operation": "authorize_artifacts",
        "subcommand": "authorize-artifacts",
        "transport": LOCAL_ONLY,
    },
    {
        "operation": "process_authorized_artifacts",
        "subcommand": "process-authorized-artifacts",
        "transport": HOSTED_CAPABLE,
        "hosted_condition": "authorized_evidence_requires_existing_hosted_review",
    },
    {
        "operation": "review_build",
        "subcommand": "review-build",
        "transport": HOSTED_CAPABLE,
    },
    {
        "operation": "continue_unchanged",
        "subcommand": "continue-unchanged",
        "transport": LOCAL_ONLY,
    },
    {
        "operation": "propose_change",
        "subcommand": "propose-change",
        "transport": HOSTED_CAPABLE,
    },
    {
        "operation": "confirm_change",
        "subcommand": "confirm-change",
        "transport": HOSTED_CAPABLE,
    },
    {
        "operation": "start_next",
        "subcommand": "start-next",
        "transport": LOCAL_ONLY,
    },
    {
        "operation": "stage_checkpoint_input",
        "subcommand": "stage-checkpoint-input",
        "transport": LOCAL_ONLY,
    },
    {
        "operation": "approve_staged_checkpoint_input",
        "subcommand": "approve-checkpoint-input",
        "transport": DYNAMIC_STAGED_OPERATION,
        "hosted_staged_operations": [
            "prepare_generation",
            "propose_change",
            "confirm_change",
        ],
        "local_staged_operations": ["continue_unchanged"],
    },
    {
        "operation": "decline_staged_checkpoint_input",
        "subcommand": "decline-checkpoint-input",
        "transport": LOCAL_ONLY,
    },
    {
        "operation": "standalone_review",
        "subcommand": "standalone-review",
        "transport": LOCAL_ONLY,
    },
    {
        "operation": "attach_to_loop",
        "subcommand": "attach-to-loop",
        "transport": LOCAL_ONLY,
    },
    {"operation": "abandon", "subcommand": "abandon", "transport": LOCAL_ONLY},
)

_BY_SUBCOMMAND = {str(row["subcommand"]): row for row in _OPERATION_ROWS}
_BY_OPERATION = {str(row["operation"]): row for row in _OPERATION_ROWS}
_BOOLEAN_FLAGS = frozenset(
    {
        "--allow",
        "--allow-external",
        "--approve",
        "--approve-decisions",
        "--approve-posture",
        "--approve-posture-change",
        "--approve-selection",
        "--decline",
        "--decline-proposal",
        "--explicit",
        "--request-stdin",
        "--use-current-intent",
        "--use-current-seed",
    }
)


def _digest(value: Mapping[str, Any] | Sequence[Any]) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def operation_transport_inventory() -> dict[str, Any]:
    """Return the diagnostics-only canonical operation inventory."""

    rows = [deepcopy(row) for row in _OPERATION_ROWS]
    payload: dict[str, Any] = {
        "schema_id": OPERATION_INVENTORY_SCHEMA_ID,
        "schema_version": OPERATION_INVENTORY_SCHEMA_VERSION,
        "diagnostics_only": True,
        "assistant_constructs_commands_from_inventory": False,
        "operations": rows,
    }
    payload["inventory_digest"] = _digest(payload)
    return payload


def transport_classification(
    *,
    subcommand: str | None,
    staged_operation: str | None = None,
    explicit_hosted: bool | None = None,
) -> str:
    """Resolve transport scope from qCoder-owned operation state."""

    if explicit_hosted is not None:
        return HOSTED_CAPABLE if explicit_hosted else LOCAL_ONLY
    if subcommand is None:
        return LOCAL_ONLY
    row = _BY_SUBCOMMAND.get(subcommand)
    if row is None:
        raise ValueError(f"current_loop_operation_inventory_missing:{subcommand}")
    classification = str(row["transport"])
    if classification != DYNAMIC_STAGED_OPERATION:
        return classification
    if staged_operation in row.get("hosted_staged_operations", []):
        return HOSTED_CAPABLE
    if staged_operation in row.get("local_staged_operations", []):
        return LOCAL_ONLY
    # Contract-matrix projections may not carry a live pending record.  The
    # unresolved dynamic class is descriptive only and never authorizes hosted
    # access or emits hosted arguments.
    return DYNAMIC_STAGED_OPERATION


def operation_for_subcommand(subcommand: str | None) -> str | None:
    if subcommand is None:
        return None
    row = _BY_SUBCOMMAND.get(subcommand)
    if row is None:
        raise ValueError(f"current_loop_operation_inventory_missing:{subcommand}")
    return str(row["operation"])


def build_operation_invocation(
    legacy: Mapping[str, Any],
    *,
    executable: str,
    workspace: str,
    base_url: str,
    token_file: str,
    state_revision: int,
    loop_ref: str,
    checkpoint: str,
    staged_operation: str | None = None,
) -> dict[str, Any]:
    """Bind one legacy protocol template into a complete operation invocation."""

    result = deepcopy(dict(legacy))
    subcommand_value = result.get("subcommand")
    subcommand = str(subcommand_value) if isinstance(subcommand_value, str) else None
    explicit = result.pop("_qcoder_hosted_transport", None)
    classification = transport_classification(
        subcommand=subcommand,
        staged_operation=staged_operation,
        explicit_hosted=explicit if isinstance(explicit, bool) else None,
    )
    hosted = classification == HOSTED_CAPABLE
    prefix = [executable, "-m", "qcoder", "current-loop", "--workspace", workspace]
    prefix.extend(
        [
            "--expected-revision",
            str(state_revision),
            "--expected-loop-ref",
            loop_ref,
            "--expected-checkpoint",
            checkpoint,
        ]
    )
    if subcommand is not None:
        prefix.append(subcommand)
    if hosted:
        prefix.extend(["--base-url", base_url, "--token-file", token_file])
    argument_values = result.get("argument_values")
    dynamic_arguments = deepcopy(argument_values) if isinstance(argument_values, list) else []
    required_flags = result.get("required_flags")
    if not isinstance(required_flags, list):
        required_flags = []
    structured_argv: list[Any] = list(prefix)
    for required in required_flags:
        flag = str(required)
        if " or " in flag or " " in flag or not flag.startswith("--"):
            continue
        if flag in _BOOLEAN_FLAGS:
            structured_argv.append(flag)
            continue
        value_contract = next(
            (
                deepcopy(dict(item))
                for item in dynamic_arguments
                if isinstance(item, Mapping) and item.get("flag") == flag
            ),
            {
                "flag": flag,
                "value_source": "coordinator_declared_bounded_input_role",
            },
        )
        structured_argv.extend(
            [
                flag,
                {
                    "value_slot": flag.removeprefix("--").replace("-", "_"),
                    "contract": value_contract,
                },
            ]
        )
    fixed_redacted = [
        "<token-file-path>" if index and prefix[index - 1] == "--token-file" else token
        for index, token in enumerate(prefix)
    ]
    serialized_template = [
        (
            f"<{item['value_slot']}>"
            if isinstance(item, Mapping) and isinstance(item.get("value_slot"), str)
            else str(item)
        )
        for item in structured_argv
    ]
    input_channel = "none"
    if subcommand == "stage-checkpoint-input":
        input_channel = "checkpoint_input_stdin_or_bounded_file"
    elif any("request-stdin" in str(item) for item in required_flags):
        input_channel = "exact_request_stdin"
    elif dynamic_arguments or required_flags:
        input_channel = "bounded_declared_arguments"
    contract: dict[str, Any] = {
        "schema_id": INVOCATION_CONTRACT_SCHEMA_ID,
        "schema_version": INVOCATION_CONTRACT_SCHEMA_VERSION,
        "operation": operation_for_subcommand(subcommand),
        "subcommand": subcommand,
        "executable": executable,
        "qcoder_owned_argv_prefix": prefix,
        "structured_argv": structured_argv,
        "assistant_appends_qcoder_owned_flags": False,
        "sanitized_argv_structure": fixed_redacted,
        "dynamic_argument_contract": dynamic_arguments,
        "required_flag_contract": deepcopy(required_flags),
        "input_channel": input_channel,
        "authority_requirements": {
            "supplied_by_coordinator_protocol": True,
            "content_submission_grants_authority": False,
        },
        "state_binding": {
            "revision": state_revision,
            "checkpoint": checkpoint,
            "loop_ref": loop_ref,
            "workspace": workspace,
        },
        "transport_classification": classification,
        "hosted_access_permitted": hosted,
        "client_environment_permission_may_be_encountered": hosted,
        "hosted_transport_argument_names": (["--base-url", "--token-file"] if hosted else []),
        "platform_serialization": {
            "posix": shlex.join(serialized_template),
            "windows": subprocess.list2cmdline(serialized_template),
            "assistant_reserializes": False,
            "value_slots_are_qcoder_declared": True,
        },
        "prohibitions": [
            "do_not_append_remove_move_or_reinterpret_arguments",
            "do_not_infer_transport_applicability",
            "do_not_inspect_package_source_or_qcoder_local_state",
            "do_not_reuse_against_another_revision_loop_workspace_checkpoint_or_operation",
        ],
        "token_contents_embedded": False,
        "credential_values_retained_in_proof": False,
    }
    contract["canonical_full_argv_digest"] = _digest({"argv": structured_argv})
    contract["sanitized_argv_structure_digest"] = _digest({"argv": fixed_redacted})
    contract["contract_digest"] = _digest(contract)
    result.pop("coordinator_prefix_source", None)
    result.pop("workspace_argument", None)
    result.pop("transport_argument_source", None)
    result["operation_specific_invocation"] = contract
    result["transport_classification"] = classification
    result["hosted_access_permitted"] = hosted
    result["assistant_constructs_transport_routing"] = False
    return result


def invocation_contract_snapshot() -> dict[str, Any]:
    inventory = operation_transport_inventory()
    return {
        "schema_id": INVOCATION_CONTRACT_SCHEMA_ID,
        "schema_version": INVOCATION_CONTRACT_SCHEMA_VERSION,
        "inventory_schema_id": OPERATION_INVENTORY_SCHEMA_ID,
        "inventory_schema_version": OPERATION_INVENTORY_SCHEMA_VERSION,
        "inventory_digest": inventory["inventory_digest"],
        "structured_argv_canonical": True,
        "platform_serialization_qcoder_owned": True,
        "global_transport_argument_array": False,
        "assistant_routes_transport": False,
        "local_only_excludes_hosted_transport": True,
    }
