from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    EXPECTED_TOOLS,
    build_client_activation_instructions,
    handle_jsonrpc_message,
    tool_descriptors,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator


REQUEST = (
    "Use qCoder to write a Qiskit program that prepares a Φ+ Bell state. "
    "Stop after generating the code."
)


def _wire_bytes(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _activate(tmp_path: Path) -> tuple[CurrentLoopCoordinator, dict[str, object]]:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    result = coordinator.activate(
        original_request=REQUEST,
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    return coordinator, result


def test_inline_binding_is_compact_tiered_digest_verified_and_keeps_twelve_tools(
    tmp_path: Path,
) -> None:
    instructions = build_client_activation_instructions(
        base_url="https://example.invalid",
        token_file=tmp_path / "token.txt",
    )
    assert len(instructions.encode("utf-8")) <= 50_000
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v26"
    assert len(tool_descriptors()) == len(EXPECTED_TOOLS) == 12
    listed = handle_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 1, "method": "resources/list"},
        base_url="https://example.invalid",
        token_file=tmp_path / "token.txt",
    )
    assert listed is not None
    resources = listed["result"]["resources"]
    catalog = next(item for item in resources if item["name"] == "reference_catalog")
    read = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": catalog["uri"]},
        },
        base_url="https://example.invalid",
        token_file=tmp_path / "token.txt",
    )
    assert read is not None
    text = read["result"]["contents"][0]["text"]
    expected = catalog["uri"].rsplit("sha256=", 1)[-1]
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == expected
    missing = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "resources/read",
            "params": {"uri": "qcoder://connected-assistant-contract/unknown?sha256=00"},
        },
        base_url="https://example.invalid",
        token_file=tmp_path / "token.txt",
    )
    assert missing == {
        "jsonrpc": "2.0",
        "id": 3,
        "error": {"code": -32602, "message": "unknown_digest_addressed_contract"},
    }


def test_normal_source_only_results_are_compact_single_source_of_truth(tmp_path: Path) -> None:
    coordinator, activated = _activate(tmp_path)
    assert _wire_bytes(activated) <= 15_000
    assert activated["schema_id"] == "qcoder.current_loop.coordinator_result.v18"
    assert activated["projection_schema_id"] == (
        "qcoder.current_loop.normal_success_projection.v1"
    )
    for duplicate in (
        "next_invocation",
        "request_semantics_contract",
        "customer_interaction",
        "customer_envelope",
        "bounded_contract_controls",
        "bounded_control_catalog",
        "authority_layers",
    ):
        assert duplicate not in activated
    action = activated["compact_next_action"]
    assert action["operation_specific_invocation"]["operation"] == "complete_native_action"
    assert action["native_action_sequence"] == [
        "obtain_action_specific_native_permission",
        "perform_exact_native_action",
        "execute_single_bound_post_action_invocation",
    ]
    source = tmp_path / "bell.py"
    source.write_text("from qiskit import QuantumCircuit\n", encoding="utf-8")
    completed = coordinator.complete_native_action(
        allowed=True,
        explicit_user_action=True,
        candidates=(
            {
                "role": "source",
                "path": str(source),
                "provenance": "assistant_created",
                "explicit_external": False,
            },
        ),
    )
    assert _wire_bytes(completed) <= 15_000
    assert completed["details"]["authority_receipt_consumed"] is True
    assert completed["details"]["exact_output_registered"] is True
    assert "operation_specific_invocation" not in completed["compact_next_action"]
    assert completed["compact_next_action"]["continuation_reference"]["operation"] == (
        "interpret_current_request"
    )
    assert completed["normal_success_projection"] == {
        "specialized_controls_inline": False,
        "duplicate_semantics_contract_omitted": True,
        "duplicate_next_invocation_omitted": True,
        "duplicate_customer_envelopes_omitted": True,
        "full_continuation_invocation_omitted_after_step_completion": True,
        "checkpoint_failure_ambiguity_and_recovery_remain_full": True,
    }


def test_native_write_and_registration_failures_remain_fail_closed_and_recoverable(
    tmp_path: Path, monkeypatch
) -> None:
    coordinator, _ = _activate(tmp_path)
    before = deepcopy(coordinator.store.read())
    missing = coordinator.complete_native_action(
        allowed=True,
        explicit_user_action=True,
        candidates=(
            {
                "role": "source",
                "path": str(tmp_path / "not-written.py"),
                "provenance": "assistant_created",
                "explicit_external": False,
            },
        ),
    )
    assert missing["ok"] is False
    assert missing["category"] == "artifact_candidate_file_required"
    assert coordinator.store.read()["operation_receipts"] == {}
    assert coordinator.store.read()["saved_artifacts"] == before["saved_artifacts"]
    assert coordinator.store.read()["selected_artifacts"] == before["selected_artifacts"]

    race_root = tmp_path / "registration-race"
    race_root.mkdir()
    coordinator, _ = _activate(race_root)
    source = race_root / "bell.py"
    source.write_text("from qiskit import QuantumCircuit\n", encoding="utf-8")
    real_record = coordinator.record_ide_authority

    def record_then_remove(**kwargs):
        result = real_record(**kwargs)
        source.unlink()
        return result

    monkeypatch.setattr(coordinator, "record_ide_authority", record_then_remove)
    failed_registration = coordinator.complete_native_action(
        allowed=True,
        explicit_user_action=True,
        candidates=(
            {
                "role": "source",
                "path": str(source),
                "provenance": "assistant_created",
                "explicit_external": False,
            },
        ),
    )
    assert failed_registration["ok"] is False
    assert failed_registration["details"]["exact_output_registered"] is False
    assert failed_registration["details"]["issued_authority_retained_for_exact_recovery"] is True
    receipts = coordinator.store.read()["operation_receipts"]
    assert len(receipts) == 1
    assert next(iter(receipts.values()))["status"] == "issued"


def test_binding_explicitly_requires_same_turn_completion_without_narration(tmp_path: Path) -> None:
    instructions = build_client_activation_instructions(
        base_url="https://example.invalid",
        token_file=tmp_path / "token.txt",
    )
    assert "without an intermediate customer message or model re-entry" in instructions
    normalized = " ".join(instructions.split())
    assert "immediately execute the bound complete_native_action invocation" in normalized
    assert '"expected_model_turns": 3' in instructions
    assert '"qcoder_control_cycles": 2' in instructions


def test_blueprint_tools_advertise_minimal_shape_and_reject_fields_actionably(
    tmp_path: Path,
) -> None:
    descriptors = {item["name"]: item for item in tool_descriptors()}
    intent = descriptors["create_algorithm_intent_card"]
    assert intent["x-qcoder-minimal-happy-path"] == {
        "original_user_intent": "<exact customer algorithm request>",
        "profile_id": "generic_qiskit",
    }
    assert "MINIMAL HAPPY PATH" in intent["description"]
    malformed = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "create_algorithm_intent_card",
                "arguments": {"invented_shape": "not echoed"},
            },
        },
        base_url="https://example.invalid",
        token_file=tmp_path / "token.txt",
    )
    assert malformed is not None
    payload = malformed["result"]["structuredContent"]
    assert payload["error_category"] == "unsupported_tool_argument"
    assert payload["offending_fields"] == ["invented_shape"]
    assert payload["recovery_category"] == "correct_bounded_argument_shape_and_retry"
    assert "not echoed" not in json.dumps(payload)
    missing = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "create_algorithm_intent_card",
                "arguments": {"original_user_intent": "Prepare a GHZ program."},
            },
        },
        base_url="https://example.invalid",
        token_file=tmp_path / "token.txt",
    )
    assert missing is not None
    missing_payload = missing["result"]["structuredContent"]
    assert missing_payload["error_category"] == "missing_profile_id"
    assert missing_payload["field"] == "profile_id"
    assert missing_payload["expected_shape"]["type"] == "string"
    assert "Prepare a GHZ program." not in json.dumps(missing_payload)
