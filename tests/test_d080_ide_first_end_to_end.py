from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

from qcoder.context_bridge_mcp import EXPECTED_TOOLS, build_client_binding_descriptor
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_bootstrap import build_fresh_active_build_bootstrap
from qcoder.current_loop_invocation import operation_transport_inventory
from qcoder.current_loop_request_semantics import classify_current_request
from qcoder.cursor_post_write_hook import (
    handle_cursor_after_file_edit_event,
    install_cursor_post_write_hook,
)
from qcoder.d079_workflows import classify_binding_default_route


SOURCE_ONLY_REQUESTS = (
    "Use qCoder to write a Qiskit program that prepares a Φ+ Bell state. "
    "Stop after generating the code.",
    "Have qCoder help me create only the Qiskit source for a Φ+ state.",
    "Let’s use qCoder for this build. Make the Python file, but don’t export QASM or run it.",
    "With qCoder, generate a two-qubit Bell example in Python and stop after the source.",
    "qCoder, help me write the Bell-state code. We’ll do circuit evidence and results later.",
    "Use qcoder to make the Python for a local Bell example—code only for now.",
)


def _essential(value: dict[str, object]) -> dict[str, object]:
    return {
        "qcoder": value["qcoder_explicitly_requested"],
        "operation": value["requested_operation"],
        "roles": value["requested_artifact_roles"],
        "prohibited": value["prohibited_artifact_roles"],
        "qasm": value["qasm_disposition"],
        "execution": value["execution_disposition"],
        "results": value["results_disposition"],
        "review": value["evidence_review_disposition"],
        "ambiguity": value["ambiguity_state"],
        "clarification": value["clarification_required"],
    }


def test_six_source_only_paraphrases_converge_without_phrase_identity() -> None:
    rows = [classify_current_request(message) for message in SOURCE_ONLY_REQUESTS]
    assert all(
        row["exact_original_message"] == message for row, message in zip(rows, SOURCE_ONLY_REQUESTS)
    )
    assert len({row["original_message_utf8_sha256"] for row in rows}) == 6
    expected = _essential(rows[0])
    assert all(_essential(row) == expected for row in rows)
    assert expected == {
        "qcoder": True,
        "operation": "source_generation",
        "roles": ["source"],
        "prohibited": ["circuit_qasm", "results"],
        "qasm": "prohibited_for_current_step",
        "execution": "prohibited_for_current_step",
        "results": "prohibited_for_current_step",
        "review": "prohibited_for_current_step",
        "ambiguity": "none",
        "clarification": False,
    }
    assert all(
        row["classifier_properties"]["exact_sentence_identity_used_for_routing"] is False
        for row in rows
    )


def test_broader_positive_negative_and_ambiguity_semantics() -> None:
    source_qasm = classify_current_request(
        "Use qCoder to write the Qiskit source and export QASM, but do not run it."
    )
    assert source_qasm["requested_operation"] == "source_and_qasm_generation"
    assert source_qasm["requested_artifact_roles"] == ["source", "circuit_qasm"]
    assert source_qasm["execution_disposition"] == "prohibited_for_current_step"
    source_run = classify_current_request(
        "Use qCoder to write the Qiskit source and run it locally with 1,024 shots."
    )
    assert source_run["requested_operation"] == "source_and_local_execution"
    assert source_run["execution_disposition"] == "requires_separate_exact_execution_authority"
    selected = classify_current_request(
        "Review these selected files with qCoder.", selected_paths=("selected.py",)
    )
    assert selected["requested_operation"] == "selected_artifact_review"
    assert selected["evidence_review_disposition"] == "exact_selected_files_only"

    for message in (
        "Can qCoder help with Bell circuits?",
        "What does qCoder do?",
        "Show me the qCoder setup instructions.",
        "Write a Bell circuit.",
    ):
        semantics = classify_current_request(message)
        assert semantics["loop_mutation_permitted"] is False
        assert semantics["bootstrap_required"] is False

    for message in (
        "Use qCoder for this.",
        "Don’t run it yet.",
        "Stop there.",
        "Make the circuit, but don’t execute it.",
    ):
        semantics = classify_current_request(message, active_loop=True)
        assert semantics["clarification_required"] is True
        assert semantics["loop_mutation_permitted"] is False
        assert semantics["recovery"]["authority_broadening_permitted"] is False

    for message in (
        "Please stop there.",
        "Please use qCoder for this.",
        "Do not run this yet.",
    ):
        semantics = classify_current_request(message, active_loop=True)
        assert semantics["clarification_required"] is True
        assert semantics["loop_mutation_permitted"] is False

    source_without_run = classify_current_request(
        "Use qCoder to write the Qiskit source, but do not run it."
    )
    assert source_without_run["requested_operation"] == "source_generation"
    assert source_without_run["requested_artifact_roles"] == ["source"]
    for message in (
        "Use qCoder to write code without running it.",
        "Use qCoder to generate source, but not QASM or results.",
    ):
        narrowed = classify_current_request(message)
        assert narrowed["requested_operation"] == "source_generation"
        assert narrowed["requested_artifact_roles"] == ["source"]
        assert narrowed["prohibited_artifact_roles"] == ["circuit_qasm", "results"]
    no_saved_results = classify_current_request(
        "Run it locally but do not save results.", active_loop=True
    )
    assert no_saved_results["clarification_required"] is True
    assert "results" not in no_saved_results["requested_artifact_roles"]


def test_binding_route_and_inventory_are_deterministic_and_keep_twelve_tools() -> None:
    for message in SOURCE_ONLY_REQUESTS:
        route = classify_binding_default_route(customer_instruction=message)
        assert route["selected_route"] == "active_build"
        assert route["operation"] == "begin_current_loop"
        assert route["raw_mcp_default_entrypoint"] is False
    generic = classify_binding_default_route(
        customer_instruction="Create a prompt context with qCoder."
    )
    assert generic["action"] == "use_applicable_mcp_tool"
    assert generic["raw_mcp_default_entrypoint"] is True
    question = classify_binding_default_route(
        customer_instruction="Can qCoder help with this build?"
    )
    assert question["selected_route"] == "available_inactive"
    assert question["action"] == "none"
    assert len(EXPECTED_TOOLS) == 12
    assert "interpret_current_request" not in EXPECTED_TOOLS
    inventory = operation_transport_inventory()
    continuation = next(
        row for row in inventory["operations"] if row["operation"] == "interpret_current_request"
    )
    assert continuation["transport"] == "hosted_capable"
    assert continuation["public_context_bridge_tool"] is False
    descriptor = build_client_binding_descriptor(
        coordinator_prefix=["python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    assert descriptor["contract_id"] == "qcoder.connected_assistant.client_binding.v38"
    assert (
        descriptor["current_request_semantics_contract"]["temporary_current_step_ceiling"] is True
    )
    handoff = descriptor["workstyle_routes"]["d080_current_request"][
        "normal_path_native_action_handoff"
    ]
    assert handoff["post_action_operation"] == "complete_current_step"
    assert handoff["qcoder_serial_control_cycles"] == 2
    assert handoff["bounded_action_expectation_and_registration_composed"] is True
    assert handoff["native_client_permission_owner"] == "native_client"
    assert handoff["native_client_permission_granted_or_observed_by_qcoder"] is False
    assert handoff["separate_receipt_read_required"] is False
    assert handoff["separate_registration_discovery_required"] is False
    compressed = next(
        row for row in inventory["operations"] if row["operation"] == "complete_native_action"
    )
    assert compressed["transport"] == "local_only"
    assert compressed["public_context_bridge_tool"] is False


def test_source_only_real_coordinator_path_enforces_one_write_and_resumable_stop(
    tmp_path: Path,
) -> None:
    install_cursor_post_write_hook(workspace_root=tmp_path)
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    activated = coordinator.activate(
        original_request=SOURCE_ONLY_REQUESTS[0],
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    assert activated["ok"] is True
    assert activated["phase"] == "generation_ready"
    assert activated["bootstrap_count"] == 1
    assert activated["request_baseline_count"] == 1
    action = activated["compact_next_action"]
    assert action["artifact_role"] == "source"
    assert action["procedural_source_of_truth"] is True
    assert "operation_specific_invocation" not in action
    assert action["post_action_operation"] == "complete_current_step"
    assert action["bounded_action_expectation_preissued_by_qcoder"] is True
    assert action["native_client_permission_owner"] == "native_client"
    assert action["native_client_permission_granted_by_qcoder"] is False
    assert action["normal_path_qcoder_serial_cycles_including_bootstrap"] == 2
    assert "next_invocation" not in activated

    before_broadened = deepcopy(coordinator.store.read())
    broadened = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        operation_category="ide_execute",
        output_role_ceiling=("source", "circuit_qasm", "results"),
    )
    assert broadened["ok"] is False
    assert broadened["category"] == "native_client_permission_not_qcoder_state"
    assert coordinator.store.read() == before_broadened

    source = tmp_path / "bell.py"
    source.write_text(
        "from qiskit import QuantumCircuit\nqc = QuantumCircuit(2)\n",
        encoding="utf-8",
    )
    no_receipt_before_permission = coordinator.register_artifacts(
        candidates=(
            {
                "role": "source",
                "path": str(source),
                "provenance": "assistant_created",
                "explicit_external": False,
            },
        )
    )
    assert no_receipt_before_permission["ok"] is False
    assert no_receipt_before_permission["category"] == "current_step_operation_receipt_required"
    assert coordinator.store.read() == before_broadened

    source.write_text(
        "from qiskit import QuantumCircuit\nqc = QuantumCircuit(2)\nqc.h(0)\nqc.cx(0, 1)\n",
        encoding="utf-8",
    )
    registered = handle_cursor_after_file_edit_event(
        workspace_root=tmp_path,
        event={
            "hook_event_name": "afterFileEdit",
            "conversation_id": "safe-conversation",
            "generation_id": "safe-generation",
            "workspace_roots": [str(tmp_path)],
            "file_path": str(source),
            "edits": [{"old_string": "", "new_string": "not-retained"}],
        },
    )
    assert registered["registration_completed"] is True
    state = coordinator.store.read()
    assert state["coordinator"]["current_step_status"] == "complete_resumable"
    receipt = next(iter(state["operation_receipts"].values()))
    assert receipt["receipt_kind"] == "qcoder_bounded_action_expectation"
    assert receipt["status"] == "consumed"


def test_compressed_native_action_preserves_receipt_and_exact_registration(
    tmp_path: Path,
) -> None:
    install_cursor_post_write_hook(workspace_root=tmp_path)
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    activated = coordinator.activate(
        original_request=SOURCE_ONLY_REQUESTS[0],
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    assert activated["compact_next_action"]["post_action_operation"] == (
        "complete_current_step"
    )
    source = tmp_path / "bell.py"
    source.write_text(
        "from qiskit import QuantumCircuit\nqc = QuantumCircuit(2)\nqc.h(0)\nqc.cx(0, 1)\n",
        encoding="utf-8",
    )
    completed = handle_cursor_after_file_edit_event(
        workspace_root=tmp_path,
        event={
            "hook_event_name": "afterFileEdit",
            "conversation_id": "safe-conversation",
            "generation_id": "safe-generation",
            "workspace_roots": [str(tmp_path)],
            "file_path": str(source),
            "edits": [{"old_string": "", "new_string": "not-retained"}],
        },
    )
    assert completed["ok"] is True
    assert completed["registration_completed"] is True
    assert completed["native_client_permission_owned_by_client"] is True
    assert completed["native_client_permission_granted_by_qcoder"] is False
    assert completed["user_approval_click_inferred"] is False
    receipts = coordinator.store.read()["operation_receipts"]
    assert len(receipts) == 1
    assert next(iter(receipts.values()))["status"] == "consumed"


def test_compressed_native_action_rejects_broader_or_multiple_outputs_before_mutation(
    tmp_path: Path,
) -> None:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    coordinator.activate(
        original_request=SOURCE_ONLY_REQUESTS[0],
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    source = tmp_path / "bell.py"
    source.write_text("print('source')\n", encoding="utf-8")
    qasm = tmp_path / "bell.qasm"
    qasm.write_text("OPENQASM 2.0;\nqreg q[2];\n", encoding="utf-8")
    before = deepcopy(coordinator.store.read())
    wrong_role = coordinator.complete_native_action(
        allowed=True,
        explicit_user_action=True,
        candidates=(
            {
                "role": "circuit_qasm",
                "path": str(qasm),
                "provenance": "assistant_created",
                "explicit_external": False,
            },
        ),
    )
    assert wrong_role["ok"] is False
    assert wrong_role["category"] == "native_client_completion_evidence_required"
    assert coordinator.store.read() == before
    multiple = coordinator.complete_native_action(
        allowed=True,
        explicit_user_action=True,
        candidates=(
            {
                "role": "source",
                "path": str(source),
                "provenance": "assistant_created",
                "explicit_external": False,
            },
            {
                "role": "circuit_qasm",
                "path": str(qasm),
                "provenance": "assistant_created",
                "explicit_external": False,
            },
        ),
    )
    assert multiple["ok"] is False
    assert multiple["category"] == "native_client_completion_evidence_required"
    assert coordinator.store.read() == before


def test_binding_owned_black_box_bootstrap_reaches_d080_compact_action(tmp_path: Path) -> None:
    bootstrap = build_fresh_active_build_bootstrap(executable=sys.executable)
    environment = dict(os.environ)
    source_root = Path(__file__).resolve().parents[1] / "src"
    environment["PYTHONPATH"] = str(source_root)
    completed = subprocess.run(
        [str(value) for value in bootstrap["qcoder_owned_structured_argv"]],
        cwd=tmp_path,
        input=SOURCE_ONLY_REQUESTS[0].encode("utf-8"),
        capture_output=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    result = json.loads(completed.stdout)
    assert result["ok"] is True
    assert result["phase"] == "generation_ready"
    assert result["current_request_semantics"]["requested_operation"] == "source_generation"
    assert result["compact_next_action"]["artifact_role"] == "source"
    assert result["compact_next_action_is_sole_procedural_source"] is True
    assert result["current_step_contract"]["completion"]["operation"] == (
        "complete_current_step"
    )
    assert result["current_step_contract"]["completion"]["required_arguments"] == [
        "current_action_handle",
        "artifact_path",
    ]
    assert "next_invocation" not in result


def test_binding_owned_black_box_compressed_post_write_handoff(tmp_path: Path) -> None:
    install_cursor_post_write_hook(workspace_root=tmp_path)
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    activation = coordinator.activate(
        original_request=SOURCE_ONLY_REQUESTS[0],
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="structured_binding_argument",
    )
    source = tmp_path / "bell.py"
    source.write_text(
        "from qiskit import QuantumCircuit\nqc = QuantumCircuit(2)\nqc.h(0)\nqc.cx(0, 1)\n",
        encoding="utf-8",
    )
    assert "operation_specific_invocation" not in activation["compact_next_action"]
    result = handle_cursor_after_file_edit_event(
        workspace_root=tmp_path,
        event={
            "hook_event_name": "afterFileEdit",
            "conversation_id": "safe-conversation",
            "generation_id": "safe-generation",
            "workspace_roots": [str(tmp_path)],
            "file_path": str(source),
            "edits": [{"old_string": "", "new_string": "not-retained"}],
        },
    )
    assert result["registration_completed"] is True
    state = coordinator.store.read()
    assert state["coordinator"]["current_step_status"] == "complete_resumable"
    assert state["coordinator"]["bootstrap_count"] == 1


def test_active_continuation_does_not_mutate_on_ambiguity_or_rebootstrap(tmp_path: Path) -> None:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    activated = coordinator.activate(
        original_request=SOURCE_ONLY_REQUESTS[0],
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
    )
    assert activated["ok"] is True
    before = deepcopy(coordinator.store.read())
    ambiguous = coordinator.interpret_current_request(exact_message="Don’t run it yet.")
    assert ambiguous["ok"] is False
    assert ambiguous["state_mutated"] is False
    assert coordinator.store.read() == before

    qasm = coordinator.interpret_current_request(exact_message="Now export the circuit as QASM.")
    assert qasm["ok"] is True
    assert qasm["current_request_semantics"]["requested_operation"] == "qasm_export"
    assert qasm["current_step_contract_is_sole_action_source"] is True
    assert qasm["bootstrap_count"] == 1
    assert qasm["request_baseline_count"] == 1
    assert qasm["details"]["rebootstrap_performed"] is False
    assert qasm["details"]["request_baseline_recreated"] is False


def test_source_plus_qasm_uses_two_exact_native_actions_and_never_runs(tmp_path: Path) -> None:
    install_cursor_post_write_hook(workspace_root=tmp_path)
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    activated = coordinator.activate(
        original_request=(
            "Have qCoder write the Qiskit source and export QASM, but do not run it."
        ),
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
    )
    assert activated["current_request_semantics"]["requested_operation"] == (
        "source_and_qasm_generation"
    )
    assert activated["compact_next_action"]["artifact_role"] == "source"
    source = tmp_path / "bell.py"
    source.write_text(
        "from qiskit import QuantumCircuit\nqc = QuantumCircuit(2)\nqc.h(0)\nqc.cx(0, 1)\n",
        encoding="utf-8",
    )
    source_registered = handle_cursor_after_file_edit_event(
        workspace_root=tmp_path,
        event={
            "hook_event_name": "afterFileEdit",
            "conversation_id": "safe-conversation",
            "generation_id": "safe-generation",
            "workspace_roots": [str(tmp_path)],
            "file_path": str(source),
            "edits": [{"old_string": "", "new_string": "not-retained"}],
        },
    )
    assert source_registered["registration_completed"] is True
    intermediate = coordinator.store.read()
    assert intermediate["coordinator"]["current_step_substage"] == "qasm"
    expectation_id = intermediate["coordinator"][
        "current_step_bounded_action_expectation_id"
    ]
    assert intermediate["operation_receipts"][expectation_id]["authority_binding"][
        "authorized_artifact_role"
    ] == "circuit_qasm"
    qasm = tmp_path / "bell.qasm"
    qasm.write_text(
        'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\nh q[0];\ncx q[0],q[1];\n',
        encoding="utf-8",
    )
    qasm_registered = handle_cursor_after_file_edit_event(
        workspace_root=tmp_path,
        event={
            "hook_event_name": "afterFileEdit",
            "conversation_id": "safe-conversation",
            "generation_id": "safe-generation-2",
            "workspace_roots": [str(tmp_path)],
            "file_path": str(qasm),
            "edits": [{"old_string": "", "new_string": "not-retained"}],
        },
    )
    assert qasm_registered["registration_completed"] is True
    final = coordinator.store.read()
    assert final["coordinator"]["current_step_status"] == "complete_resumable"
    assert "results" not in final["evidence_registry"]["role_heads"]


def test_source_plus_run_requires_a_second_exact_execution_permission(tmp_path: Path) -> None:
    install_cursor_post_write_hook(workspace_root=tmp_path)
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    activated = coordinator.activate(
        original_request=(
            "Have qCoder write the Qiskit source and run it locally with 1,024 shots."
        ),
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
    )
    assert activated["compact_next_action"]["artifact_role"] == "source"
    source = tmp_path / "bell.py"
    source.write_text("print('bounded source')\n", encoding="utf-8")
    source_registered = handle_cursor_after_file_edit_event(
        workspace_root=tmp_path,
        event={
            "hook_event_name": "afterFileEdit",
            "conversation_id": "safe-conversation",
            "generation_id": "safe-generation",
            "workspace_roots": [str(tmp_path)],
            "file_path": str(source),
            "edits": [{"old_string": "", "new_string": "not-retained"}],
        },
    )
    assert source_registered["registration_completed"] is True
    state = coordinator.store.read()
    assert state["coordinator"]["current_step_substage"] == "execution"
    expectation_id = state["coordinator"]["current_step_bounded_action_expectation_id"]
    execution_expectation = state["operation_receipts"][expectation_id]
    assert execution_expectation["authority_binding"]["requested_operation"] == "ide_execute"
    assert execution_expectation["authority_binding"]["authorized_artifact_role"] == "results"
    assert execution_expectation["authority_effect"][
        "native_client_permission_granted_by_qcoder"
    ] is False
    assert len(state["operation_receipts"]) == 2
    assert sorted(row["status"] for row in state["operation_receipts"].values()) == [
        "consumed",
        "issued",
    ]


def test_semantic_and_stage_authority_state_stays_bounded_by_decisions() -> None:
    small = classify_current_request(
        "Use qCoder to write Qiskit source for a Bell circuit and stop after code."
    )
    large = classify_current_request(
        "Use qCoder to write Qiskit source for a one-million-gate circuit and stop after code."
    )
    assert small["requested_operation"] == large["requested_operation"]
    assert (
        small["current_step_ceiling"]["allowed_operations"]
        == large["current_step_ceiling"]["allowed_operations"]
    )
    assert small["current_step_ceiling"]["large_artifact_or_gate_enumeration"] is False
    assert large["current_step_ceiling"]["large_artifact_or_gate_enumeration"] is False
    small_projection = deepcopy(small)
    large_projection = deepcopy(large)
    for projection in (small_projection, large_projection):
        projection.pop("exact_original_message")
        projection.pop("original_message_utf8_sha256")
        projection.pop("semantics_digest")
    assert abs(len(json.dumps(small_projection)) - len(json.dumps(large_projection))) < 64


def test_active_selected_review_and_diff_execute_through_declared_hosted_continuation(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class Transport:
        def call(self, name: str, arguments: object) -> dict[str, object]:
            safe = deepcopy(dict(arguments))  # type: ignore[arg-type]
            calls.append((name, safe))
            return {
                "tool_name": name,
                "ok": True,
                "context_status": (
                    "single_loop_evidence_diff_ready"
                    if name == "create_single_loop_evidence_diff"
                    else "assistant_context_ready"
                    if name == "get_guided_evidence_context"
                    else "result_review_context_card_ready"
                ),
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }

    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path, transport=Transport())
    activated = coordinator.activate(
        original_request=SOURCE_ONLY_REQUESTS[0],
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
    )
    assert activated["ok"] is True
    selected = tmp_path / "selected.py"
    selected.write_text("x = 1\n", encoding="utf-8")
    reviewed = coordinator.interpret_current_request(
        exact_message="Review these selected files with qCoder.",
        selected_paths=(str(selected),),
    )
    assert reviewed["ok"] is True
    assert reviewed["result_review"]["status"] == "result_review_ready"
    assert reviewed["protected_received_selected_paths"] is False
    assert reviewed["protected_received_raw_artifacts"] is False
    assert all(str(selected) not in json.dumps(arguments) for _, arguments in calls)
    assert all("x = 1" not in json.dumps(arguments) for _, arguments in calls)

    changed = coordinator.interpret_current_request(exact_message="Show me what changed.")
    assert changed["ok"] is True
    assert changed["comparison_result"]["ok"] is True
    assert changed["supported_path"] == "canonical_current_loop_comparison"
    assert calls[-1][0] == "create_single_loop_evidence_diff"
    assert changed["raw_artifact_transferred"] is False
    assert changed["local_path_transferred"] is False


def test_review_intent_precedes_artifact_nouns_without_creating_authority(
    tmp_path: Path,
) -> None:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    activated = coordinator.activate(
        original_request=SOURCE_ONLY_REQUESTS[0],
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
    )
    assert activated["ok"] is True
    for message in (
        "Review the source, QASM, and counts.",
        "Check the circuit and results with qCoder.",
        "Look at the generated QASM and tell me what the evidence supports.",
        "Review what we ran.",
        "Inspect the result evidence.",
    ):
        before = deepcopy(coordinator.store.read())
        result = coordinator.interpret_current_request(exact_message=message)
        assert result["ok"] is False
        assert result["customer_summary"] == "Which exact files should qCoder review?"
        assert result["current_request_semantics"]["requested_operation"] == (
            "selected_artifact_review"
        )
        assert result["state_mutated"] is False
        assert coordinator.store.read() == before
        assert not list(tmp_path.glob("*.qasm"))
        assert not list(tmp_path.glob("*result*"))


def test_review_intent_with_native_selection_uses_only_wi0433_selected_files(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class Transport:
        def call(self, name: str, arguments: object) -> dict[str, object]:
            calls.append((name, deepcopy(dict(arguments))))  # type: ignore[arg-type]
            return {
                "tool_name": name,
                "ok": True,
                "context_status": (
                    "assistant_context_ready"
                    if name == "get_guided_evidence_context"
                    else "result_review_context_card_ready"
                ),
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }

    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path, transport=Transport())
    coordinator.activate(
        original_request=SOURCE_ONLY_REQUESTS[0],
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
    )
    selected = tmp_path / "only-selected.py"
    selected.write_text("SELECTED_SENTINEL = True\n", encoding="utf-8")
    neighboring = tmp_path / "must-not-be-read.qasm"
    neighboring.write_text("NEIGHBOR_SENTINEL\n", encoding="utf-8")
    result = coordinator.interpret_current_request(
        exact_message="Review the source, QASM, and counts.",
        selected_paths=(str(selected),),
    )
    assert result["ok"] is True
    assert result["workflow"] == "local_first_evidence_review"
    assert result["result_review"]["status"] == "result_review_ready"
    protected = json.dumps(calls)
    assert str(selected) not in protected
    assert str(neighboring) not in protected
    assert "SELECTED_SENTINEL" not in protected
    assert "NEIGHBOR_SENTINEL" not in protected


def test_negated_review_intent_never_reads_selected_files_or_mutates_loop(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, object]] = []

    class Transport:
        def call(self, name: str, arguments: object) -> dict[str, object]:
            calls.append((name, arguments))
            raise AssertionError("negated review intent must not reach protected transport")

    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path, transport=Transport())
    coordinator.activate(
        original_request=SOURCE_ONLY_REQUESTS[0],
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
    )
    selected = tmp_path / "selected.py"
    selected.write_text("SENSITIVE = True\n", encoding="utf-8")
    for message in (
        "Do not review these selected files with qCoder.",
        "Don't check these selected files with qCoder.",
        "Never inspect the selected results with qCoder.",
    ):
        for selected_paths in ((), (str(selected),)):
            before = deepcopy(coordinator.store.read())
            result = coordinator.interpret_current_request(
                exact_message=message,
                selected_paths=selected_paths,
            )
            assert result["ok"] is False
            assert result["category"] == "current_request_inactive"
            assert result["current_request_semantics"]["requested_operation"] == "inactive"
            assert result["state_mutated"] is False
            assert coordinator.store.read() == before
    assert calls == []


def test_orderly_close_and_explicit_abandon_are_distinct_terminal_actions(
    tmp_path: Path,
) -> None:
    close_messages = (
        "Close qCoder for this build.",
        "Finish this qCoder loop.",
        "End the current qCoder session.",
        "We’re done with this loop.",
    )
    for index, message in enumerate(close_messages):
        workspace = tmp_path / f"close-{index}"
        workspace.mkdir()
        coordinator = CurrentLoopCoordinator(workspace_root=workspace)
        coordinator.activate(
            original_request=SOURCE_ONLY_REQUESTS[0],
            explicit_authority=True,
            capture_mode="exact_current_customer_message",
        )
        result = coordinator.interpret_current_request(exact_message=message)
        assert result["ok"] is True
        assert result["phase"] == "completed"
        assert result["ordinary_language_close"] is True
        assert result["ordinary_language_abandonment"] is False
        assert result["details"]["completion_receipt"]["resulting_disposition"] == "stop_loop"
        assert result["details"]["abandonment_selected"] is False
        assert "abandon" not in result["customer_summary"].casefold()

    for index, message in enumerate(
        ("Abandon this loop.", "Discard this qCoder loop.", "Throw away this current loop.")
    ):
        workspace = tmp_path / f"abandon-{index}"
        workspace.mkdir()
        coordinator = CurrentLoopCoordinator(workspace_root=workspace)
        coordinator.activate(
            original_request=SOURCE_ONLY_REQUESTS[0],
            explicit_authority=True,
            capture_mode="exact_current_customer_message",
        )
        result = coordinator.interpret_current_request(exact_message=message)
        assert result["ok"] is True
        assert result["phase"] == "abandoned"
        assert result["ordinary_language_abandonment"] is True
        assert "completion_receipt" not in result["details"]


def test_negated_or_nonterminal_close_words_cannot_end_or_abandon_the_loop(
    tmp_path: Path,
) -> None:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    coordinator.activate(
        original_request=SOURCE_ONLY_REQUESTS[0],
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
    )
    for message in (
        "Do not close the qCoder loop.",
        "Never abandon this qCoder loop.",
    ):
        before = deepcopy(coordinator.store.read())
        result = coordinator.interpret_current_request(exact_message=message)
        assert result["ok"] is False
        assert result["category"] == "current_request_inactive"
        assert result["state_mutated"] is False
        assert coordinator.store.read() == before

    semantics = classify_current_request(
        "Finish writing the source for this qCoder build.", active_loop=True
    )
    assert semantics["requested_operation"] == "source_generation"
    assert semantics["route"] == "active_loop_continuation"

    for message in (
        "Close the editor; keep the qCoder loop running.",
        "End the local execution and return to the qCoder loop.",
    ):
        before = deepcopy(coordinator.store.read())
        result = coordinator.interpret_current_request(exact_message=message)
        assert result["ok"] is False
        assert result["category"] == "current_request_inactive"
        assert result["current_request_semantics"]["requested_operation"] == "inactive"
        assert result["state_mutated"] is False
        assert coordinator.store.read() == before


def test_polite_modal_tasks_are_tasks_and_modal_discussion_stays_informational() -> None:
    source_tasks = (
        "Could you use qCoder to make a teleportation program? Create only the Python file for now.",
        "Can you have qCoder draft a GHZ-state Qiskit example, code only?",
        "Would you use qCoder to create the source for a small QFT example?",
        "Could qCoder generate the Python implementation and stop before QASM?",
        "Can you use qCoder to write this algorithm, but do not run it yet?",
        "CODE ONLY, please: could you use qCoder to draft a variational-circuit Python example?",
    )
    for message in source_tasks:
        result = classify_current_request(message)
        assert result["requested_operation"] == "source_generation"
        assert result["requested_artifact_roles"] == ["source"]
        assert result["clarification_required"] is False

    for message in (
        "Can qCoder help with teleportation?",
        "Could qCoder be useful for this algorithm?",
        "Would qCoder work with GHZ circuits?",
        "What does qCoder do?",
        "How does qCoder work?",
        "Can you show me the qCoder setup instructions?",
    ):
        result = classify_current_request(message)
        assert result["requested_operation"] in {"informational", "setup_guidance"}
        assert result["loop_mutation_permitted"] is False


def test_negated_qcoder_tasks_never_activate_or_mutate() -> None:
    for message in (
        "Do not use qCoder to write the source.",
        "Don't have qCoder create a Python file.",
        "Could you not use qCoder to make this program?",
        "Never use qCoder to generate code for this.",
        "I do not want qCoder to write this implementation.",
    ):
        semantics = classify_current_request(message)
        assert semantics["requested_operation"] == "inactive"
        assert semantics["route"] == "available_inactive"
        assert semantics["loop_mutation_permitted"] is False
        assert semantics["bootstrap_required"] is False
        route = classify_binding_default_route(customer_instruction=message)
        assert route["selected_route"] == "available_inactive"
        assert route["action"] == "none"


def test_unseen_generation_requests_default_to_exact_source_only_d080_semantics() -> None:
    messages = (
        "Use qCoder to write a Qiskit program that prepares a Bell state.",
        "Use qCoder to create a teleportation program.",
        "Have qCoder generate a GHZ-state Python example.",
        "Could you use qCoder to make the source for a QFT circuit?",
        "qCoder, write a Deutsch–Jozsa implementation.",
        "Use qCoder to build the Python for this algorithm.",
        "Use qCoder to generate the program. We are not reviewing results yet.",
        "Use qCoder to draft Python for a Grover setup; we can run it later.",
        "Use qCoder to create a variational-circuit source. We’ll inspect QASM afterward.",
    )
    for message in messages:
        semantics = classify_current_request(message)
        assert semantics["route"] == "active_build"
        assert semantics["requested_operation"] == "source_generation"
        assert semantics["requested_artifact_roles"] == ["source"]
        assert semantics["prohibited_artifact_roles"] == ["circuit_qasm", "results"]
        assert semantics["execution_disposition"] == "prohibited_for_current_step"
        assert semantics["evidence_review_disposition"] == "prohibited_for_current_step"
        route = classify_binding_default_route(customer_instruction=message)
        assert route["matched_named_workflow"] == "d080_current_request_semantics"
        assert route["request_semantics"]["semantics_digest"] == semantics["semantics_digest"]


def test_explicit_generation_bootstrap_never_uses_legacy_broad_role_ceiling(
    tmp_path: Path,
) -> None:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    activated = coordinator.activate(
        original_request="Use qCoder to create a teleportation program.",
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
    )
    semantics = activated["current_request_semantics"]
    assert activated["phase"] == "generation_ready"
    assert semantics["requested_operation"] == "source_generation"
    assert semantics["current_step_ceiling"]["allowed_artifact_roles"] == ["source"]
    assert semantics["current_step_ceiling"]["artifact_role_cardinality"] == {
        "source": "exactly_one"
    }
    assert activated["current_step_contract"]["completion"]["operation"] == (
        "complete_current_step"
    )
    before = deepcopy(coordinator.store.read())
    execution = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        operation_category="ide_execute",
        output_role_ceiling=("results",),
    )
    assert execution["ok"] is False
    assert execution["category"] == "native_client_permission_not_qcoder_state"
    assert coordinator.store.read() == before


def test_direct_generic_exact_message_activation_cannot_bypass_d080_semantics(
    tmp_path: Path,
) -> None:
    for index, message in enumerate(
        (
            "Use qCoder for this build.",
            "Use qCoder for this build. Help me plan the work.",
        )
    ):
        workspace = tmp_path / f"generic-{index}"
        workspace.mkdir()
        coordinator = CurrentLoopCoordinator(workspace_root=workspace)
        result = coordinator.activate(
            original_request=message,
            explicit_authority=True,
            capture_mode="exact_current_customer_message",
            request_transport="stdin",
        )
        assert result["ok"] is False
        assert result["category"] == "activation_exact_message_mode_ineligible"
        assert coordinator.store.state_path.exists() is False
