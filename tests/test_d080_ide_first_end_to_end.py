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
        assert route["operation"] == "activate"
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
    assert descriptor["contract_id"] == "qcoder.connected_assistant.client_binding.v23"
    assert (
        descriptor["current_request_semantics_contract"]["temporary_current_step_ceiling"] is True
    )


def test_source_only_real_coordinator_path_enforces_one_write_and_resumable_stop(
    tmp_path: Path,
) -> None:
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
    assert action["operation_specific_invocation"]["operation"] == "record_ide_authority"
    assert action["operation_invocation_digest"]
    invocation = activated["next_invocation"]
    assert invocation["fixed_argument_values"] == {
        "--operation-category": "ide_write",
        "--output-role": "source",
    }

    before_broadened = deepcopy(coordinator.store.read())
    broadened = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        operation_category="ide_execute",
        output_role_ceiling=("source", "circuit_qasm", "results"),
    )
    assert broadened["ok"] is False
    assert broadened["category"] == "current_step_authority_mismatch"
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

    permitted = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        operation_category="ide_write",
        output_role_ceiling=("source",),
    )
    assert permitted["ok"] is True
    registration_action = permitted["compact_next_action"]
    assert registration_action["action"] == "register_exact_authorized_output"
    assert registration_action["artifact_role"] == "source"
    assert registration_action["artifact_cardinality"] == "exactly_one"
    assert registration_action["operation_specific_invocation"]["operation"] == (
        "register_artifacts"
    )
    assert "artifact_path_flags" not in permitted["next_invocation"]
    assert permitted["next_invocation"]["fixed_argument_values"] == {
        "--operation-receipt-id": permitted["details"]["operation_receipt"]["receipt_id"],
        "--provenance": "assistant_created",
    }
    receipt_id = permitted["details"]["operation_receipt"]["receipt_id"]
    source.write_text(
        "from qiskit import QuantumCircuit\nqc = QuantumCircuit(2)\nqc.h(0)\nqc.cx(0, 1)\n",
        encoding="utf-8",
    )
    qasm = tmp_path / "unauthorized.qasm"
    qasm.write_text('OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\n', encoding="utf-8")
    state_before_invalid_registration = deepcopy(coordinator.store.read())
    no_receipt_after_permission = coordinator.register_artifacts(
        candidates=(
            {
                "role": "source",
                "path": str(source),
                "provenance": "assistant_created",
                "explicit_external": False,
            },
        )
    )
    assert no_receipt_after_permission["ok"] is False
    assert no_receipt_after_permission["category"] == "current_step_operation_receipt_required"
    assert coordinator.store.read() == state_before_invalid_registration
    prohibited = coordinator.register_artifacts(
        candidates=(
            {
                "role": "circuit_qasm",
                "path": str(qasm),
                "provenance": "assistant_created",
                "explicit_external": False,
            },
        ),
        operation_receipt_id=receipt_id,
    )
    assert prohibited["ok"] is False
    assert prohibited["category"] == "current_step_ceiling_violation"
    assert prohibited["recovery"]["operation_receipt_retained"] is True
    assert coordinator.store.read() == state_before_invalid_registration

    second_source = tmp_path / "unrelated.py"
    second_source.write_text("UNRELATED = True\n", encoding="utf-8")
    excessive = coordinator.register_artifacts(
        candidates=(
            {
                "role": "source",
                "path": str(source),
                "provenance": "assistant_created",
                "explicit_external": False,
            },
            {
                "role": "source",
                "path": str(second_source),
                "provenance": "assistant_created",
                "explicit_external": False,
            },
        ),
        operation_receipt_id=receipt_id,
    )
    assert excessive["ok"] is False
    assert excessive["category"] == "current_step_artifact_cardinality_invalid"
    assert coordinator.store.read() == state_before_invalid_registration

    registered = coordinator.register_artifacts(
        candidates=(
            {
                "role": "source",
                "path": str(source),
                "provenance": "assistant_created",
                "explicit_external": False,
            },
        ),
        operation_receipt_id=receipt_id,
    )
    assert registered["ok"] is True
    assert registered["details"]["exact_artifact_inventory"] == {
        "source": 1,
        "circuit_qasm": 0,
        "execution": 0,
        "results": 0,
        "unrelated": 0,
    }
    assert registered["details"]["artifact_review_performed"] is False
    assert registered["details"]["forced_close"] is False
    assert registered["compact_next_action"]["action"] == "await_exact_customer_continuation"
    assert registered["bootstrap_count"] == 1
    assert registered["request_baseline_count"] == 1


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
    assert result["next_invocation"]["fixed_argument_values"] == {
        "--operation-category": "ide_write",
        "--output-role": "source",
    }
    assert result["assistant_reconstruction_performed"] is False
    assert result["bootstrap_count"] == 1


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
    assert qasm["bootstrap_count"] == 1
    assert qasm["request_baseline_count"] == 1
    assert qasm["details"]["rebootstrap_performed"] is False
    assert qasm["details"]["request_baseline_recreated"] is False


def test_source_plus_qasm_uses_two_exact_native_actions_and_never_runs(tmp_path: Path) -> None:
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
    source_permission = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        operation_category="ide_write",
        output_role_ceiling=("source",),
    )
    source = tmp_path / "bell.py"
    source.write_text(
        "from qiskit import QuantumCircuit\nqc = QuantumCircuit(2)\nqc.h(0)\nqc.cx(0, 1)\n",
        encoding="utf-8",
    )
    source_registered = coordinator.register_artifacts(
        candidates=(
            {
                "role": "source",
                "path": str(source),
                "provenance": "assistant_created",
                "explicit_external": False,
            },
        ),
        operation_receipt_id=source_permission["details"]["operation_receipt"]["receipt_id"],
    )
    assert source_registered["details"]["next_substage"] == "qasm"
    assert source_registered["compact_next_action"]["artifact_role"] == "circuit_qasm"
    assert source_registered["compact_next_action"]["grants_execution"] is False
    qasm_permission = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        operation_category="ide_write",
        output_role_ceiling=("circuit_qasm",),
    )
    qasm = tmp_path / "bell.qasm"
    qasm.write_text(
        'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\nh q[0];\ncx q[0],q[1];\n',
        encoding="utf-8",
    )
    qasm_registered = coordinator.register_artifacts(
        candidates=(
            {
                "role": "circuit_qasm",
                "path": str(qasm),
                "provenance": "assistant_created",
                "explicit_external": False,
            },
        ),
        operation_receipt_id=qasm_permission["details"]["operation_receipt"]["receipt_id"],
    )
    assert qasm_registered["ok"] is True
    assert qasm_registered["details"]["current_step_complete"] is True
    assert qasm_registered["details"]["artifact_review_performed"] is False
    assert qasm_registered["details"]["exact_artifact_inventory"]["execution"] == 0
    assert qasm_registered["details"]["exact_artifact_inventory"]["results"] == 0


def test_source_plus_run_requires_a_second_exact_execution_permission(tmp_path: Path) -> None:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    activated = coordinator.activate(
        original_request=(
            "Have qCoder write the Qiskit source and run it locally with 1,024 shots."
        ),
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
    )
    assert activated["compact_next_action"]["artifact_role"] == "source"
    source_permission = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        operation_category="ide_write",
        output_role_ceiling=("source",),
    )
    source = tmp_path / "bell.py"
    source.write_text("print('bounded source')\n", encoding="utf-8")
    source_registered = coordinator.register_artifacts(
        candidates=(
            {
                "role": "source",
                "path": str(source),
                "provenance": "assistant_created",
                "explicit_external": False,
            },
        ),
        operation_receipt_id=source_permission["details"]["operation_receipt"]["receipt_id"],
    )
    action = source_registered["compact_next_action"]
    assert action["action"] == "ide_execute"
    assert action["artifact_role"] == "results"
    assert action["customer_facing_permission"] == "Allow this local execution"
    assert action["grants_execution"] is True
    assert action["grants_evidence_review"] is False
    state = coordinator.store.read()
    assert len(state["operation_receipts"]) == 1
    assert next(iter(state["operation_receipts"].values()))["status"] == "consumed"


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
