from __future__ import annotations

from pathlib import Path

import pytest

from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_event_receipts import (
    EVENT_RECEIPT_SCHEMA_ID,
    EventReceiptError,
    consume_operation_receipt,
    issue_operation_receipt,
    validate_operation_receipt,
)


def _active(tmp_path: Path) -> CurrentLoopCoordinator:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    result = coordinator.activate(
        original_request="Use qCoder for this build. Track one exact output.",
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    assert result["ok"] is True
    return coordinator


def test_operation_receipt_is_single_use_and_bound() -> None:
    receipt = issue_operation_receipt(
        loop_ref="loop-" + "a" * 32,
        workspace_binding="/workspace",
        state_revision=4,
        operation_category="ide_write",
        output_role_ceiling=["source"],
    )
    assert receipt["schema_id"] == EVENT_RECEIPT_SCHEMA_ID
    validate_operation_receipt(
        receipt,
        loop_ref=receipt["loop_ref"],
        workspace_binding="/workspace",
        current_state_revision=4,
        role="source",
    )
    consumed, activity = consume_operation_receipt(
        receipt,
        registered_artifacts=[
            {
                "role": "source",
                "path": "/workspace/main.py",
                "content_digest": "b" * 64,
                "provenance": "assistant_created",
            }
        ],
        consumed_state_revision=5,
    )
    assert activity["directory_scan_performed"] is False
    assert activity["git_discovery_performed"] is False
    try:
        validate_operation_receipt(
            consumed,
            loop_ref=receipt["loop_ref"],
            workspace_binding="/workspace",
            current_state_revision=5,
            role="source",
        )
    except EventReceiptError as exc:
        assert exc.category == "operation_receipt_replay_rejected"
    else:
        raise AssertionError("consumed receipt replayed")


def test_coordinator_issues_and_consumes_exact_path_receipt(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    authority = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        operation_category="ide_write",
        output_role_ceiling=["source"],
    )
    receipt = authority["details"]["operation_receipt"]
    source = tmp_path / "Bell source ü.py"
    source.write_text("print('bell')\n", encoding="utf-8")
    registered = coordinator.register_artifacts(
        candidates=[
            {
                "role": "source",
                "path": str(source),
                "provenance": "assistant_created",
                "explicit_external": False,
            }
        ],
        operation_receipt_id=receipt["receipt_id"],
    )
    assert registered["ok"] is True
    assert registered["details"]["operation_receipt_consumed"] is True
    assert registered["details"]["activity_receipt"]["glob_performed"] is False
    replay = coordinator.register_artifacts(
        candidates=[
            {
                "role": "source",
                "path": str(source),
                "provenance": "assistant_created",
                "explicit_external": False,
            }
        ],
        operation_receipt_id=receipt["receipt_id"],
    )
    assert replay["ok"] is False


def test_sensitive_output_requires_existing_exact_selection_fallback(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    authority = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        output_role_ceiling=["source"],
    )
    secret = tmp_path / ".env"
    secret.write_text("SYNTHETIC=not-a-secret\n", encoding="utf-8")
    result = coordinator.register_artifacts(
        candidates=[
            {
                "role": "source",
                "path": str(secret),
                "provenance": "assistant_created",
                "explicit_external": False,
            }
        ],
        operation_receipt_id=authority["details"]["operation_receipt"]["receipt_id"],
    )
    assert result["ok"] is False
    assert result["category"] in {
        "operation_receipt_sensitive_output_requires_selection",
        "protected_operation_rejected",
    }


def test_operation_receipt_registration_isolates_qasm3_from_valid_source(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    authority = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        output_role_ceiling=["source", "circuit_qasm"],
    )
    source = tmp_path / "program.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    qasm = tmp_path / "circuit.qasm"
    qasm.write_text("OPENQASM 3.0;\nqubit q;\n", encoding="utf-8")
    result = coordinator.register_artifacts(
        candidates=[
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
        ],
        operation_receipt_id=authority["details"]["operation_receipt"]["receipt_id"],
    )
    assert result["ok"] is True
    outcomes = {item["role"]: item for item in result["details"]["registration_outcomes"]}
    assert outcomes["source"]["registration_disposition"] == "eligible"
    assert outcomes["circuit_qasm"]["detected_format"] == "openqasm_3"
    assert outcomes["circuit_qasm"]["registration_disposition"] == "unsupported_format"
    assert result["details"]["registered_candidate_count"] == 1


def test_operation_receipt_rejects_symlink_without_reading_target(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    authority = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        output_role_ceiling=["source"],
    )
    target = tmp_path / "target.py"
    target.write_text("print('target')\n", encoding="utf-8")
    link = tmp_path / "linked.py"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    result = coordinator.register_artifacts(
        candidates=[
            {
                "role": "source",
                "path": str(link),
                "provenance": "assistant_created",
                "explicit_external": False,
            }
        ],
        operation_receipt_id=authority["details"]["operation_receipt"]["receipt_id"],
    )
    assert result["ok"] is False
    assert result["category"] in {
        "selected_artifact_symlink_prohibited",
        "protected_operation_rejected",
    }


def test_contract_collection_ceiling_is_enforced_before_receipt_consumption(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    narrowed = coordinator.contract_adjust(
        category="python_manifestation",
        dimension="collect",
        value="disabled",
        expected_contract_revision=1,
    )
    assert narrowed["ok"] is True
    assert narrowed["details"]["disposition"] == "narrowing"
    authority = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        output_role_ceiling=["source"],
    )
    receipt = authority["details"]["operation_receipt"]
    source = tmp_path / "bounded.py"
    source.write_text("print('bounded')\n", encoding="utf-8")
    rejected = coordinator.register_artifacts(
        candidates=[
            {
                "role": "source",
                "path": str(source),
                "provenance": "assistant_created",
                "explicit_external": False,
            }
        ],
        operation_receipt_id=receipt["receipt_id"],
    )
    assert rejected["ok"] is False
    assert rejected["category"] == "current_loop_contract_policy_prohibited"
    assert coordinator.store.read()["operation_receipts"][receipt["receipt_id"]]["status"] == (
        "issued"
    )


def test_narrowing_cancels_unconsumed_operation_receipts(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    authority = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        output_role_ceiling=["source"],
    )
    receipt_id = authority["details"]["operation_receipt"]["receipt_id"]
    narrowed = coordinator.contract_adjust(
        category="python_manifestation",
        dimension="collect",
        value="disabled",
        expected_contract_revision=1,
    )
    assert narrowed["ok"] is True
    state = coordinator.store.read()
    assert receipt_id not in state["operation_receipts"]
    cancellation = state["contract_narrowing_cancellation"]
    assert cancellation["issued_operation_receipts_cancelled"] == 1
    assert cancellation["prior_evidence_rewritten"] is False
