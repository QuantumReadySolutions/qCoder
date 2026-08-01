"""Explicit bounded recovery for the active-loop evidence spine."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from hashlib import sha256
from typing import Any

from qcoder.current_loop_invocation import build_operation_invocation
from qcoder.current_loop_vocabulary import recovery_actions_for

RECOVERY_SCHEMA_ID = "qcoder.current_loop.recovery.v5"
RECOVERY_SCHEMA_VERSION = 5

_ACTION_OPERATIONS = {
    "retry_registration": ("execute_recovery_action", "execute-recovery-action"),
    "correct_candidate": ("execute_recovery_action", "execute-recovery-action"),
    "retry_local_derivation": (
        "process_authorized_artifacts",
        "process-authorized-artifacts",
    ),
    "resume_pending_derivation": (
        "process_authorized_artifacts",
        "process-authorized-artifacts",
    ),
    "restore_evidence": ("execute_recovery_action", "execute-recovery-action"),
    "stop_loop": ("abandon", "abandon"),
}


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def evidence_recovery(
    *,
    category: str,
    state: Mapping[str, Any],
    operation: str,
    safe_arguments: Mapping[str, Any] | None = None,
    allowed_actions: Sequence[str] | None = None,
    runtime_executable: str = sys.executable,
    checkpoint: str = "privacy_or_trust",
) -> dict[str, Any]:
    actions = tuple(allowed_actions or recovery_actions_for(category))
    generated = []
    for action in actions:
        target = _ACTION_OPERATIONS.get(action)
        if target is None:
            continue
        target_operation, subcommand = target
        fixed: dict[str, Any] = {}
        required: list[str] = []
        if subcommand == "abandon":
            required = ["--approve"]
            fixed = {"--approve": True}
        invocation_reference = (
            f"recovery-{_digest({'category': category, 'operation': operation})[:24]}"
        )
        if subcommand == "execute-recovery-action":
            required = [
                "--recovery-reference",
                "--action",
                "--expected-contract-revision",
            ]
            fixed = {
                "--recovery-reference": invocation_reference,
                "--action": action,
                "--expected-contract-revision": int(
                    state["current_loop_contract"]["contract_revision"]
                ),
            }
        invocation = build_operation_invocation(
            {
                "subcommand": subcommand,
                "required_flags": required,
                "fixed_argument_values": fixed,
            },
            executable=runtime_executable,
            workspace=str(state["workspace_root"]),
            base_url="",
            token_file="",
            state_revision=int(state["state_revision"]),
            loop_ref=str(state["loop_ref"]),
            checkpoint=checkpoint,
        )
        generated.append(
            {
                "action": action,
                "operation": target_operation,
                "invocation": invocation,
                "executable": True,
            }
        )
    result = {
        "schema_id": RECOVERY_SCHEMA_ID,
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "category": category,
        "originating_operation": operation,
        "loop_ref": state["loop_ref"],
        "workspace_binding": state["workspace_root"],
        "state_revision": state["state_revision"],
        "contract_revision": state["current_loop_contract"]["contract_revision"],
        "actions": generated,
        "conversation_may_continue": bool(generated),
        "assistant_should_stop": not bool(generated),
        "primary_next_invocation": (deepcopy(generated[0]["invocation"]) if generated else None),
        "canonical_state_reconstructed_by_assistant": False,
        "substring_routing_used": False,
    }
    result["recovery_digest"] = _digest(result)
    return result


def recovery_contract_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": RECOVERY_SCHEMA_ID,
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "category_mapping": "qcoder.current_loop.vocabulary.v1",
        "substring_routing_permitted": False,
        "every_advertised_action_executable": True,
        "assistant_reconstruction_permitted": False,
        "retry_registration_causal_continuation": {
            "same_action_binding_required": True,
            "one_attempt": True,
            "material_change_blocks": True,
            "second_customer_approval_for_stale_only_receipt": False,
            "native_ide_permission_separate": True,
            "internal_choreography_customer_visible": False,
        },
    }
    payload["contract_digest"] = _digest(payload)
    return payload
