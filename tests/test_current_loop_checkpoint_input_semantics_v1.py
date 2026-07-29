from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from qcoder.current_loop import CurrentLoopError, canonical_bytes
from qcoder.current_loop_checkpoint_input import (
    CHECKPOINT_INPUT_SEMANTIC_SCHEMA_ID,
    CheckpointInputSemanticError,
    checkpoint_input_construction,
    checkpoint_input_contract_snapshot,
    checkpoint_input_values,
    decode_checkpoint_input,
    normalize_checkpoint_input,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator


ROWS = (
    ("prepare_generation", "intent_review", "intent_review"),
    ("prepare_generation", "decision_resolution", "intent_review"),
    ("prepare_generation", "posture", "intent_review"),
    ("continue_unchanged", "governing_change_confirmation", "continuation_choice"),
    ("propose_change", "governing_change_confirmation", "continuation_choice"),
    ("confirm_change", "governing_change_confirmation", "change_confirmation"),
)


def _domains(operation: str) -> dict[str, Any]:
    if operation == "prepare_generation":
        return {"current_generation_posture": "exploratory_first_pass"}
    if operation == "propose_change":
        return {
            "decision_ref": ["decision-semantic-0001"],
            "selected_action": ["clarify_requirement"],
            "control_treatment": ["keep_fixed"],
            "proposed_value_by_decision": {
                "decision-semantic-0001": ["bounded_value"],
            },
        }
    if operation == "confirm_change":
        return {"proposal_ref": "proposal-semantic-0001"}
    return {}


def _values(operation: str) -> dict[str, Any]:
    return {
        "prepare_generation": {
            "profile_id": "generic_qiskit",
            "proposed_interpretation": {
                "summary": "`00` and `11`; $(printf inert) Ω 😀",
                "nested": {"windows": r"C:\proof", "posix": "/tmp/proof"},
            },
        },
        "continue_unchanged": {
            "user_statement": "Decline this proposal and continue unchanged.",
        },
        "propose_change": {
            "decision_ref": "decision-semantic-0001",
            "selected_action": "clarify_requirement",
            "proposed_value": "bounded_value",
            "control_treatment": "keep_fixed",
        },
        "confirm_change": {
            "semantic_confirmation": (
                "I confirm proposal proposal-semantic-0001 exactly as displayed."
            ),
        },
    }[operation]


def _record(
    *,
    operation: str,
    checkpoint_kind: str,
    phase: str,
    values: Mapping[str, Any],
) -> dict[str, Any]:
    construction = checkpoint_input_construction(
        operation=operation,
        checkpoint_kind=checkpoint_kind,
        workspace_binding="/synthetic/semantic-workspace",
        loop_ref="loop-semantic-0001",
        phase=phase,
        expected_state_revision=11,
        bounded_domains=_domains(operation),
    )
    declared = {item["name"]: item for item in construction["semantic_field_contract"]["fields"]}
    payload = deepcopy(construction["fixed_payload"])
    payload["fields"] = [
        {
            "name": name,
            "value": deepcopy(value),
            "provenance": declared[name]["allowed_provenance"][0],
        }
        for name, value in values.items()
    ]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    decoded = decode_checkpoint_input(raw)
    return normalize_checkpoint_input(
        decoded,
        operation=operation,
        checkpoint_kind=checkpoint_kind,
        workspace_binding="/synthetic/semantic-workspace",
        loop_ref="loop-semantic-0001",
        phase=phase,
        expected_state_revision=13,
        source_state_revision=11,
        captured_at=1.0,
        transport="stdin",
        semantic_contract=construction["semantic_field_contract"],
    )


def test_missing_internal_profile_is_prebound_before_staging() -> None:
    record = _record(
        operation="prepare_generation",
        checkpoint_kind="intent_review",
        phase="intent_review",
        values={"proposed_interpretation": {"summary": "Create a bounded circuit interpretation."}},
    )
    values = checkpoint_input_values(record)
    assert values["profile_id"] == "generic_qiskit"
    profile = next(item for item in record["fields"] if item["name"] == "profile_id")
    assert profile["provenance"] == "qcoder_owned_classification"


@pytest.mark.parametrize(("operation", "checkpoint_kind", "phase"), ROWS)
def test_semantic_matrix_stages_and_promotes_every_construction_row(
    operation: str,
    checkpoint_kind: str,
    phase: str,
) -> None:
    values = _values(operation)
    if operation == "continue_unchanged" and phase == "change_confirmation":
        values["decline_unconfirmed_proposal"] = True
    record = _record(
        operation=operation,
        checkpoint_kind=checkpoint_kind,
        phase=phase,
        values=values,
    )
    assert record["semantic_contract_schema_id"] == CHECKPOINT_INPUT_SEMANTIC_SCHEMA_ID
    assert checkpoint_input_values(record) == values


@pytest.mark.parametrize("invalid", ["text", [], 3, 1.25, True, None])
def test_proposed_interpretation_rejects_non_mapping_before_staging(
    invalid: object,
) -> None:
    with pytest.raises(CheckpointInputSemanticError, match="checkpoint_input_field_type_invalid"):
        _record(
            operation="prepare_generation",
            checkpoint_kind="intent_review",
            phase="intent_review",
            values={
                "profile_id": "generic_qiskit",
                "proposed_interpretation": invalid,
            },
        )


def test_profile_id_contract_is_derived_from_canonical_profile_registry() -> None:
    construction = checkpoint_input_construction(
        operation="prepare_generation",
        checkpoint_kind="intent_review",
        workspace_binding="/synthetic/semantic-workspace",
        loop_ref="loop-semantic-0001",
        phase="intent_review",
        expected_state_revision=11,
    )
    contracts = {item["name"]: item for item in construction["semantic_field_contract"]["fields"]}
    assert contracts["profile_id"]["schema"]["enum"] == [
        "generic_qiskit",
        "grover_search",
        "qaoa",
    ]
    with pytest.raises(CheckpointInputSemanticError, match="checkpoint_input_field_domain_invalid"):
        _record(
            operation="prepare_generation",
            checkpoint_kind="intent_review",
            phase="intent_review",
            values={
                "profile_id": "simple_bell_circuit_demo",
                "proposed_interpretation": {"summary": "Synthetic."},
            },
        )


def test_semantic_contract_digest_and_revision_are_bound_to_staged_record() -> None:
    record = _record(
        operation="prepare_generation",
        checkpoint_kind="intent_review",
        phase="intent_review",
        values=_values("prepare_generation"),
    )
    changed = deepcopy(record)
    changed["semantic_contract_snapshot"]["fields"][0]["required"] = True
    with pytest.raises(CurrentLoopError, match="checkpoint_input_semantic_contract_mismatch"):
        checkpoint_input_values(changed)
    changed = deepcopy(record)
    changed["semantic_contract_digest"] = "0" * 64
    with pytest.raises(CurrentLoopError, match="checkpoint_input_semantic_contract_stale"):
        checkpoint_input_values(changed)


def test_semantic_inventory_covers_every_field_in_all_six_rows() -> None:
    snapshot = checkpoint_input_contract_snapshot()
    inventory = snapshot["semantic_field_inventory"]
    assert len(inventory) == 6
    for row in inventory.values():
        assert row["schema_id"] == CHECKPOINT_INPUT_SEMANTIC_SCHEMA_ID
        assert row["contract_digest"]
        assert row["fields"]
        for field in row["fields"]:
            assert field["schema"]
            assert isinstance(field["required"], bool)
            assert isinstance(field["nullable"], bool)
            assert field["allowed_provenance"]
            assert field["maximum_field_bytes"] == 20_000


def test_semantic_rejection_does_not_stage_or_emit_hosted_action(tmp_path: Path) -> None:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    request = "Use qCoder for this build. Create one synthetic circuit."
    coordinator.activate(original_request=request)
    coordinator.activate(
        explicit_authority=True,
        generation_posture="exploratory_first_pass",
        explicit_posture_authority=True,
        posture_authority_provenance="user_confirmed_assistant_recommendation",
    )
    state = coordinator.store.read()
    protocol = checkpoint_input_construction(
        operation="prepare_generation",
        checkpoint_kind="intent_review",
        workspace_binding=str(state["workspace_root"]),
        loop_ref=str(state["loop_ref"]),
        phase=str(state["coordinator"]["phase"]),
        expected_state_revision=int(state["state_revision"]),
        bounded_domains={"current_generation_posture": "exploratory_first_pass"},
    )
    payload = deepcopy(protocol["fixed_payload"])
    payload["fields"] = [
        {
            "name": "profile_id",
            "value": "generic_qiskit",
            "provenance": "assistant_proposed",
        },
        {
            "name": "proposed_interpretation",
            "value": "not a mapping",
            "provenance": "assistant_proposed",
        },
    ]
    raw = canonical_bytes(payload)
    decoded = decode_checkpoint_input(raw)
    rejected = coordinator.stage_checkpoint_input(
        operation=None,
        checkpoint_kind=None,
        payload=decoded,
        transport="stdin",
    )
    assert rejected["category"] == "checkpoint_input_field_type_invalid"
    assert rejected["details"]["semantic_error"]["field_name"] == ("proposed_interpretation")
    assert rejected["details"]["semantic_error"]["hosted_operation_permitted"] is False
    assert coordinator.store.read()["coordinator"].get("pending_checkpoint_input") is None
