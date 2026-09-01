from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from qcoder import current_loop_bounded_control as bounded_control_module
from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    EXPECTED_TOOLS,
    build_client_binding_descriptor,
)
from qcoder.current_loop import canonical_bytes
from qcoder.current_loop_contract_management import customer_contract_document
from qcoder.current_loop_coordinator import (
    COORDINATOR_RESULT_SCHEMA_ID,
    CurrentLoopCoordinator,
    coordinator_contract_snapshot,
)
from qcoder.current_loop_invocation import operation_transport_inventory
from qcoder.current_loop_quiet_workflow import (
    HELP_SCHEMA_ID,
    HELP_TOPICS,
    validate_help_v2_projection,
)
from qcoder.current_loop_result_envelope import (
    BOUNDED_CONTROL_REFERENCE_SCHEMA_ID,
    CUSTOMER_ENVELOPE_SCHEMA_ID,
    TIERED_RESULT_ENVELOPE_SCHEMA_ID,
)
from tests.current_loop_test_support import activate_reviewed_legacy_fixture

REQUEST = "Use qCoder for this build context with the established generic-help contract."


def _fields() -> dict[str, dict[str, Any]]:
    return {
        "profile_id": {
            "value": "generic_qiskit",
            "provenance": "qcoder_classified",
            "material": False,
        },
        "qubits": {"value": 2, "provenance": "user_stated", "material": False},
        "simulator": {
            "value": "local simulator",
            "provenance": "user_stated",
            "material": False,
        },
        "shots": {"value": 1024, "provenance": "user_stated", "material": False},
        "measurement": {
            "value": "both qubits",
            "provenance": "derived",
            "material": False,
        },
        "output": {
            "value": "counts",
            "provenance": "user_stated",
            "material": False,
        },
    }


def _active(workspace: Path, *, with_intent: bool = False) -> CurrentLoopCoordinator:
    coordinator = CurrentLoopCoordinator(workspace_root=workspace)
    activated = activate_reviewed_legacy_fixture(
        coordinator,
        original_request=REQUEST,
    )
    assert activated["ok"] is True
    if with_intent:
        assert coordinator.prepare_adaptive_intent(fields=_fields())["ok"] is True
    return coordinator


def _write_iteration(workspace: Path, *, iteration: int) -> list[dict[str, Any]]:
    source = workspace / "bell.py"
    qasm = workspace / "bell.qasm"
    results = workspace / "results.json"
    source.write_text(
        "from qiskit import QuantumCircuit\n"
        f"ITERATION = {iteration}\n"
        "circuit = QuantumCircuit(2, 2)\n",
        encoding="utf-8",
    )
    qasm.write_text(
        'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\n'
        "h q[0];\ncx q[0],q[1];\nmeasure q -> c;\n",
        encoding="utf-8",
    )
    results.write_text(
        json.dumps(
            {
                "counts": {"00": 500 + iteration, "11": 524 - iteration},
                "shots": 1024,
                "backend": "AerSimulator",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    event = "assistant_created" if iteration == 1 else "assistant_modified"
    return [
        {"path": str(source), "role": "source", "provenance": event},
        {"path": str(qasm), "role": "circuit_qasm", "provenance": event},
        {"path": str(results), "role": "results", "provenance": event},
    ]


def _run_iteration(coordinator: CurrentLoopCoordinator, *, iteration: int) -> None:
    authority = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        operation_category="ide_execute",
        output_role_ceiling=["source", "circuit_qasm", "results"],
        exact_iteration_instruction=(
            None if iteration == 1 else f"Run exact synthetic iteration {iteration}."
        ),
    )
    assert authority["ok"] is True
    registered = coordinator.register_artifacts(
        candidates=_write_iteration(coordinator.workspace_root, iteration=iteration),
        operation_receipt_id=authority["details"]["operation_receipt"]["receipt_id"],
    )
    assert registered["ok"] is True


def _compact_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def test_binding_v18_steers_generic_help_to_exactly_one_local_call(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    activated = coordinator.status()
    binding = build_client_binding_descriptor(
        coordinator_prefix=[sys.executable, "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v53"
    assert binding["generic_help"]["generic_request_topic"] == "overview"
    assert binding["generic_help"]["exactly_one_qcoder_operation"] is True
    assert binding["generic_help"]["automatic_status_call"] is False
    assert binding["generic_help"]["automatic_contract_status_call"] is False
    assert binding["generic_help"]["automatic_evidence_view_call"] is False
    assert binding["generic_help"]["automatic_browser_call"] is False
    assert binding["generic_help"]["current_build_facts_for_generic_help"] is False
    assert len(EXPECTED_TOOLS) == 12
    help_route = activated["customer_envelope"]["help"]["invocation"]
    assert help_route["operation"] == "help"
    assert help_route["subcommand"] == "help"
    topic_index = help_route["structured_argv"].index("--topic")
    assert help_route["structured_argv"][topic_index + 1] == "overview"
    assert not any(isinstance(item, dict) for item in help_route["structured_argv"])
    assert (
        "--topic" in activated["bounded_control_catalog"]["fetch_invocation"]["structured_argv"]
        or help_route["input_domains_inline"] is False
    )
    catalog = coordinator.bounded_control_catalog()["bounded_contract_controls"]
    help_contract = catalog["help"]["bounded_control_input_contract"]
    topics = next(item for item in help_contract["fields"] if item["name"] == "topic")
    assert [item["value"] for item in topics["accepted_values"]] == list(HELP_TOPICS)


def test_help_topics_are_distinct_compact_and_non_persistent(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    state_before = canonical_bytes(coordinator.store.read())
    projections = {}
    for topic in HELP_TOPICS:
        result = coordinator.help(topic=topic)
        assert result["ok"] is True
        assert result["details"]["help"]["schema_id"] == HELP_SCHEMA_ID
        assert result["details"]["help"]["projection_type"] == "current_loop"
        validate_help_v2_projection(result["details"]["help"])
        assert result["schema_id"] == COORDINATOR_RESULT_SCHEMA_ID
        assert result["bounded_control_catalog"]["controls_inline"] is False
        assert result["bounded_contract_controls"] == {}
        assert result["supported_next_action"] is None
        assert result["next_invocation"] is None
        assert _compact_size(result["customer_envelope"]) <= 8 * 1024
        result_size = len(json.dumps(result, indent=2, sort_keys=True).encode())
        assert result_size <= 32 * 1024
        assert result["performance_diagnostics"]["final_result_bytes"] == result_size
        projections[topic] = result["details"]["help"]["topic_detail"]
    assert len(
        {hashlib.sha256(canonical_bytes(value)).hexdigest() for value in projections.values()}
    ) == len(HELP_TOPICS)
    assert canonical_bytes(coordinator.store.read()) == state_before
    overview = coordinator.help(topic="overview")
    help_projection = overview["details"]["help"]
    assert help_projection["exact_counts_included"] is False
    assert help_projection["gate_metrics_included"] is False
    assert help_projection["full_run_summary_included"] is False
    assert help_projection["complete_contract_matrix_included"] is False
    assert overview["performance_diagnostics"]["persisted"] is False


def test_referenced_controls_fetch_exact_digest_and_inline_when_required(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    help_result = coordinator.help(topic="overview")
    reference = help_result["bounded_control_catalog"]
    assert reference["schema_id"] == BOUNDED_CONTROL_REFERENCE_SCHEMA_ID
    assert reference["fetch_invocation"]["subcommand"] == "bounded-control-catalog"
    fetched = coordinator.bounded_control_catalog()
    assert fetched["bounded_control_catalog"]["controls_inline"] is True
    assert (
        hashlib.sha256(canonical_bytes(fetched["bounded_contract_controls"])).hexdigest()
        == reference["controls_digest"]
    )
    contract = coordinator.contract_status()
    assert contract["bounded_control_catalog"]["controls_inline"] is True
    rejected = coordinator.help(topic="not-a-topic")
    assert rejected["ok"] is False
    assert rejected["bounded_control_catalog"]["controls_inline"] is True


def test_control_policy_matrix_is_exhaustive_and_conservative() -> None:
    contract = coordinator_contract_snapshot()
    matrix = contract["tiered_result_envelope"]
    operations = {str(row["operation"]) for row in operation_transport_inventory()["operations"]}
    assert {row["operation"] for row in matrix["rows"]} == operations
    assert matrix["schema_id"] == TIERED_RESULT_ENVELOPE_SCHEMA_ID
    assert matrix["zero_checkpoint_domains_omitted"] is True
    assert matrix["zero_recovery_domains_omitted"] is True
    assert matrix["zero_contract_management_domains_omitted"] is True
    assert all(row["checkpoint"] == "inline" for row in matrix["rows"])
    assert all(row["non_success"] == "inline" for row in matrix["rows"])
    assert all(row["recovery"] == "inline" for row in matrix["rows"])


def test_help_reports_actual_contract_pending_proposal_and_precise_currentness(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path, with_intent=True)
    _run_iteration(coordinator, iteration=1)
    document = customer_contract_document(coordinator.store.read()["current_loop_contract"])
    document["customer_settings"]["preset"] = "custom"
    document["customer_settings"]["generation_governance"] = "blueprint_required"
    document["customer_settings"]["evidence_categories"]["result_manifestation"][
        "derived_assistant_exposure"
    ] = "disabled"
    narrowed = coordinator.contract_apply_customer_document(
        document=document,
        choice="apply_narrowing",
        explicit_authority=False,
    )
    assert narrowed["ok"] is True
    assert coordinator.store.read()["current_loop_contract"]["dependent_views_stale"] is True
    _run_iteration(coordinator, iteration=2)
    broaden = customer_contract_document(coordinator.store.read()["current_loop_contract"])
    broaden["customer_settings"]["generation_governance"] = "adaptive"
    proposed = coordinator.contract_apply_customer_document(
        document=broaden,
        choice="create_broadening_proposal",
        explicit_authority=False,
    )
    assert proposed["ok"] is True
    result = coordinator.help(topic="overview")
    help_projection = result["details"]["help"]
    assert help_projection["effective_preset"] == "custom"
    assert help_projection["generation_governance"] == "blueprint_required"
    assert help_projection["pending_proposal"] is not None
    assert "before" not in help_projection["pending_proposal"]
    status = help_projection["evidence_status"]
    assert status["integrity"] == "fresh"
    assert status["presentation_currency"] == "current"
    assert status["processing_completeness"] == "complete"
    assert status["warnings"] == []
    assert status["legacy_dependent_views_stale_authoritative"] is False
    view = coordinator.evidence_view(view_id="current_build_facts")
    assert (
        "dependent views stale or incomplete"
        not in json.dumps(view["details"]["evidence_view"]).lower()
    )


def test_machine_json_stdout_is_exactly_one_json_document(tmp_path: Path) -> None:
    _active(tmp_path)
    for operation_args, expected_operation in (
        (["help", "--topic", "overview"], "help"),
        (["status"], "status"),
        (["bounded-control-catalog"], "bounded_control_catalog"),
    ):
        command = [
            sys.executable,
            "-m",
            "qcoder",
            "current-loop",
            "--workspace",
            str(tmp_path),
            *operation_args,
        ]
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        completed = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        parsed = json.loads(completed.stdout)
        assert parsed["operation"] == expected_operation
        assert completed.stdout.strip() == json.dumps(parsed, indent=2, sort_keys=True).encode()
        assert completed.stderr == b""


def test_help_performance_is_constant_with_five_retained_snapshots(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path, with_intent=True)
    empty_started = time.perf_counter()
    empty = coordinator.help(topic="overview")
    empty_seconds = time.perf_counter() - empty_started
    for iteration in range(1, 6):
        _run_iteration(coordinator, iteration=iteration)
    state_before = canonical_bytes(coordinator.store.read())
    timings = []
    sizes = []
    for _ in range(10):
        started = time.perf_counter()
        result = coordinator.help(topic="overview")
        timings.append(time.perf_counter() - started)
        sizes.append(len(json.dumps(result, indent=2, sort_keys=True).encode()))
        assert "snapshots" not in json.dumps(result["details"]["help"])
    p95 = sorted(timings)[-1]
    assert p95 <= max(1.0, empty_seconds * 1.10)
    assert max(sizes) <= 32 * 1024
    assert max(sizes) - min(sizes) <= 64
    assert len(json.dumps(empty, indent=2, sort_keys=True).encode()) <= 32 * 1024
    assert canonical_bytes(coordinator.store.read()) == state_before
    assert all(result < 2.0 for result in timings)


def test_customer_envelope_is_predictable_and_machine_safe(tmp_path: Path) -> None:
    result = _active(tmp_path).help(topic="overview")
    envelope = result["customer_envelope"]
    assert envelope["schema_id"] == CUSTOMER_ENVELOPE_SCHEMA_ID
    assert envelope["operation"] == "help"
    assert envelope["interaction_kind"] == "user_requested_help"
    assert envelope["requires_customer_response"] is False
    assert envelope["machine_block"]["controls_inline"] is False
    serialized = json.dumps(envelope)
    assert "token-file" not in serialized
    assert ".qcoder" not in serialized
    assert "counts" not in serialized


def test_help_controls_validate_the_contract_once(tmp_path: Path, monkeypatch: Any) -> None:
    coordinator = _active(tmp_path)
    calls = 0
    original = bounded_control_module.validate_contract

    def counted(contract: object) -> None:
        nonlocal calls
        calls += 1
        original(contract)

    bounded_control_module._ADJUSTMENT_GRAPH_CACHE.clear()
    monkeypatch.setattr(bounded_control_module, "validate_contract", counted)
    assert coordinator.help(topic="overview")["ok"] is True
    assert calls == 1
