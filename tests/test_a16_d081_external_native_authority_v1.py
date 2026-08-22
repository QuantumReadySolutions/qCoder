from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from qcoder.context_bridge_mcp import EXPECTED_TOOLS
from qcoder.current_loop_binding_mcp import (
    BEGIN_CURRENT_LOOP_TOOL_NAME,
    COMPLETE_CURRENT_STEP_TOOL_NAME,
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_request_semantics import (
    classify_current_request,
    migrate_request_semantics,
)
from qcoder.cursor_post_write_hook import (
    _event_binding,
    handle_cursor_after_file_edit_event,
    handle_cursor_post_tool_use_event,
    install_cursor_post_write_hook,
)


REQUEST = (
    "Use qCoder to write a Qiskit program that prepares a Φ+ Bell state. "
    "Stop after generating the code."
)


def _activate(root: Path) -> tuple[CurrentLoopCoordinator, dict]:
    install_cursor_post_write_hook(workspace_root=root)
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": BEGIN_CURRENT_LOOP_TOOL_NAME,
                "arguments": {
                    "request_text": REQUEST,
                    "intended_artifact_paths": {"source": "bell.py"},
                },
            },
        },
        workspace_root=root,
    )
    assert response is not None
    result = response["result"]["structuredContent"]
    assert result["ok"] is True
    return CurrentLoopCoordinator(workspace_root=root), result


def _event(root: Path, source: Path, *, name: str = "afterFileEdit") -> dict:
    base = {
        "hook_event_name": name,
        "conversation_id": "safe-conversation",
        "generation_id": "safe-generation",
        "workspace_roots": [str(root)],
    }
    if name == "afterFileEdit":
        return {
            **base,
            "file_path": str(source),
            "edits": [{"old_string": "", "new_string": "not-retained"}],
        }
    raw = source.read_bytes()
    return {
        **base,
        "tool_name": "UnknownNativeEditToolName",
        "tool_input": {"path": str(source), "content": raw.decode("utf-8")},
        "tool_output": json.dumps(
            {"success": True, "file_path": str(source), "bytes_written": len(raw)}
        ),
    }


def _candidate(source: Path, *, role: str = "source") -> dict:
    return {
        "role": role,
        "path": str(source),
        "provenance": "assistant_created",
        "explicit_external": False,
    }


def test_activation_issues_bounded_expectation_not_native_permission(tmp_path: Path) -> None:
    coordinator, result = _activate(tmp_path)
    state = coordinator.store.read()
    action = result["compact_next_action"]
    contract = action["bounded_action_contract"]
    assert result["current_step_status"] == "awaiting_external_client_action"
    assert action["native_client_permission_owner"] == "native_client"
    assert action["native_client_permission_requirement"] == "client_determined"
    assert action["native_client_permission_granted_by_qcoder"] is False
    assert action["native_client_permission_observed_by_qcoder"] is False
    assert action["user_approval_click_inferred"] is False
    assert contract["permitted_artifact_role"] == "source"
    assert contract["permitted_artifact_cardinality"] == "exactly_one"
    assert contract["prohibited_artifact_roles"] == ["circuit_qasm", "results"]
    assert contract["bound_state_revision"] == state["state_revision"]
    assert contract["request_identity_sha256"] == result["request_identity"][
        "original_message_utf8_sha256"
    ]
    receipt = next(iter(state["operation_receipts"].values()))
    assert receipt["receipt_kind"] == "qcoder_bounded_action_expectation"
    assert receipt["status"] == "issued"
    assert receipt["authority_effect"] == {
        "qcoder_bounded_action_contract": True,
        "native_client_permission_granted_by_qcoder": False,
        "native_client_permission_observed": False,
        "user_approval_click_inferred": False,
        "artifact_review_authorized": False,
        "raw_exposure_authorized": False,
    }


def test_legacy_permission_operation_cannot_bypass_d081_expectation(tmp_path: Path) -> None:
    coordinator, _ = _activate(tmp_path)
    source = tmp_path / "bell.py"
    source.write_text("print('bell')\n", encoding="utf-8")
    before = deepcopy(coordinator.store.read())
    result = coordinator.complete_native_action(
        allowed=True,
        explicit_user_action=True,
        candidates=(_candidate(source),),
    )
    assert result["ok"] is False
    assert result["category"] == "native_client_completion_evidence_required"
    assert result["recovery"]["state_mutated"] is False
    assert coordinator.store.read() == before


@pytest.mark.parametrize("event_name", ["afterFileEdit", "postToolUse"])
def test_each_event_can_register_without_native_permission_receipt(
    tmp_path: Path, event_name: str
) -> None:
    coordinator, _ = _activate(tmp_path)
    source = tmp_path / "bell.py"
    source.write_text("from qiskit import QuantumCircuit\n", encoding="utf-8")
    event = _event(tmp_path, source, name=event_name)
    result = (
        handle_cursor_after_file_edit_event(workspace_root=tmp_path, event=event)
        if event_name == "afterFileEdit"
        else handle_cursor_post_tool_use_event(workspace_root=tmp_path, event=event)
    )
    assert result["registration_completed"] is True
    state = coordinator.store.read()
    assert state["coordinator"]["current_step_status"] == "complete_resumable"
    assert set(state["saved_artifacts"]) == {
        "request_baseline",
        "python_manifestation",
        "source_evidence",
    }
    source_head = state["evidence_registry"]["role_heads"]["source"]
    source_revision = state["evidence_registry"]["artifact_revisions"][source_head]
    assert source_revision["logical_role"] == "source"
    assert source_revision["content_digest"]
    receipt = next(iter(state["operation_receipts"].values()))
    assert receipt["receipt_kind"] == "qcoder_bounded_action_expectation"
    assert receipt["status"] == "consumed"
    assert receipt["native_client_permission_granted_by_qcoder"] is False
    assert receipt["user_approval_click_inferred"] is False
    activity = state["activity_receipts"][-1]
    evidence = activity["native_action_completion_evidence"]
    assert evidence["transport_event"] == event_name
    assert evidence["transport"] == "client_hook_adapter"
    assert evidence["client_approval_telemetry"] is None
    assert evidence["raw_path_retained"] is False
    assert evidence["raw_source_retained"] is False


def test_optional_explicit_client_telemetry_is_provenance_only(tmp_path: Path) -> None:
    coordinator, _ = _activate(tmp_path)
    source = tmp_path / "bell.py"
    source.write_text("print('bell')\n", encoding="utf-8")
    state = coordinator.store.read()
    event = _event(tmp_path, source)
    binding = _event_binding(event, source, state, event_name="afterFileEdit")
    binding["explicit_client_approval_telemetry"] = {
        "observed": True,
        "source": "native_client_supplied",
        "event_identity_sha256": "a" * 64,
    }
    result = coordinator.complete_external_native_action(
        candidates=(_candidate(source),), native_client_event_binding=binding
    )
    assert result["ok"] is True
    receipt = next(iter(coordinator.store.read()["operation_receipts"].values()))
    assert receipt["native_client_permission_granted_by_qcoder"] is False
    assert receipt["user_approval_click_inferred"] is False
    evidence = coordinator.store.read()["activity_receipts"][-1][
        "native_action_completion_evidence"
    ]
    assert evidence["client_approval_telemetry"] == binding[
        "explicit_client_approval_telemetry"
    ]


@pytest.mark.parametrize(
    ("binding_field", "replacement", "expected_category"),
    [
        ("bound_workspace_identity_sha256", "0" * 64, "native_action_completion_state_or_artifact_mismatch"),
        ("bound_loop_identity_sha256", "1" * 64, "native_action_completion_state_or_artifact_mismatch"),
        ("current_request_identity_sha256", "2" * 64, "native_action_completion_state_or_artifact_mismatch"),
        ("bound_state_revision", 999999, "native_action_completion_state_or_artifact_mismatch"),
        ("bounded_action_expectation_digest", "3" * 64, "native_action_completion_evidence_invalid"),
        ("exact_path_sha256", "4" * 64, "native_action_completion_state_or_artifact_mismatch"),
        ("expected_artifact_sha256", "5" * 64, "native_action_completion_state_or_artifact_mismatch"),
    ],
)
def test_tampered_completion_evidence_fails_before_state_mutation(
    tmp_path: Path,
    binding_field: str,
    replacement: object,
    expected_category: str,
) -> None:
    coordinator, _ = _activate(tmp_path)
    source = tmp_path / "bell.py"
    source.write_text("print('bell')\n", encoding="utf-8")
    state = coordinator.store.read()
    binding = _event_binding(_event(tmp_path, source), source, state, event_name="afterFileEdit")
    binding[binding_field] = replacement
    before = deepcopy(state)
    result = coordinator.complete_external_native_action(
        candidates=(_candidate(source),), native_client_event_binding=binding
    )
    assert result["ok"] is False
    assert result["category"] == expected_category
    assert result["recovery"]["state_mutated"] is False
    assert coordinator.store.read() == before


@pytest.mark.parametrize("role", ["circuit_qasm", "results"])
def test_wrong_role_or_later_stage_evidence_fails_closed(tmp_path: Path, role: str) -> None:
    coordinator, _ = _activate(tmp_path)
    source = tmp_path / ("bell.qasm" if role == "circuit_qasm" else "counts.json")
    source.write_text("OPENQASM 3;\n" if role == "circuit_qasm" else "{}\n", encoding="utf-8")
    state = coordinator.store.read()
    binding = _event_binding(_event(tmp_path, source), source, state, event_name="afterFileEdit")
    binding["artifact_role"] = role
    before = deepcopy(state)
    result = coordinator.complete_external_native_action(
        candidates=(_candidate(source, role=role),), native_client_event_binding=binding
    )
    assert result["ok"] is False
    assert result["category"] == "bounded_action_completion_cardinality_or_role_mismatch"
    assert coordinator.store.read() == before


def test_missing_file_excess_cardinality_and_stale_expectation_fail_closed(
    tmp_path: Path,
) -> None:
    coordinator, _ = _activate(tmp_path)
    one = tmp_path / "one.py"
    two = tmp_path / "two.py"
    one.write_text("print(1)\n", encoding="utf-8")
    two.write_text("print(2)\n", encoding="utf-8")
    state = coordinator.store.read()
    binding = _event_binding(_event(tmp_path, one), one, state, event_name="afterFileEdit")
    before = deepcopy(state)
    excess = coordinator.complete_external_native_action(
        candidates=(_candidate(one), _candidate(two)),
        native_client_event_binding=binding,
    )
    assert excess["category"] == "bounded_action_completion_cardinality_or_role_mismatch"
    assert coordinator.store.read() == before

    one.unlink()
    missing = coordinator.complete_external_native_action(
        candidates=(_candidate(one),), native_client_event_binding=binding
    )
    assert missing["ok"] is False
    assert missing["category"] == "artifact_candidate_file_required"
    assert coordinator.store.read() == before

    one.write_text("print(1)\n", encoding="utf-8")
    current = coordinator.store.read()
    coordinator.store.update(lambda value: value, expected_revision=current["state_revision"])
    stale_before = deepcopy(coordinator.store.read())
    stale_binding = _event_binding(
        _event(tmp_path, one), one, stale_before, event_name="afterFileEdit"
    )
    stale = coordinator.complete_external_native_action(
        candidates=(_candidate(one),), native_client_event_binding=stale_binding
    )
    assert stale["category"] == "bounded_action_expectation_state_mismatch"
    assert coordinator.store.read() == stale_before


def test_public_private_tool_inventories_remain_exact() -> None:
    assert len(EXPECTED_TOOLS) == 12
    private = binding_tool_descriptors()
    assert [item["name"] for item in private] == [
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
    ]
    assert all(item["x-qcoder-public-context-bridge-tool"] is False for item in private)


def test_prefreeze_request_semantics_migrate_without_changing_stage_meaning() -> None:
    current = classify_current_request(REQUEST)
    legacy = deepcopy(current)
    legacy["schema_id"] = "qcoder.current_loop.request_semantics.v1"
    legacy["schema_version"] = 1
    legacy["authority_layers"] = {"legacy_projection": True}
    legacy["semantics_digest"] = "legacy-recomputed-by-migration"
    migrated = migrate_request_semantics(legacy)
    assert migrated["schema_id"] == "qcoder.current_loop.request_semantics.v5"
    assert migrated["requested_operation"] == current["requested_operation"]
    assert migrated["requested_artifact_roles"] == current["requested_artifact_roles"]
    assert migrated["current_step_ceiling"] == current["current_step_ceiling"]
    assert migrated["authority_layers"]["native_client_permission"]["owner"] == (
        "native_client"
    )
    assert migrated["authority_layers"]["native_client_permission"][
        "granted_by_qcoder"
    ] is False
