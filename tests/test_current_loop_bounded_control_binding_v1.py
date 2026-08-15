from __future__ import annotations

from pathlib import Path

import pytest

from qcoder.current_loop_bounded_control import (
    BOUNDED_CONTROL_INPUT_SCHEMA_ID,
    CATEGORY_MEANINGS,
    DIMENSION_MEANINGS,
    PRESET_MEANINGS,
    VALUE_MEANINGS,
    adjustment_selection_contract,
    bounded_control_contract_snapshot,
    bounded_control_contracts,
    current_adjustment_value,
    operation_receipt_contract,
)
from qcoder.current_loop_contract import (
    ADJUSTMENT_DIMENSIONS,
    ADJUSTMENT_VALUES_BY_DIMENSION,
    EVIDENCE_CATEGORIES,
    EVIDENCE_EXCLUSION_REASONS,
    NAMED_PRESETS,
    adjust,
    set_preset,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_event_receipts import (
    SUPPORTED_OPERATION_CATEGORIES,
    SUPPORTED_OUTPUT_ROLES,
)
from qcoder.current_loop_invocation import INVOCATION_CONTRACT_SCHEMA_ID
from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    build_client_binding_descriptor,
)


REQUEST = "Use qCoder for this build. Bind every bounded local control."


def _activate(tmp_path: Path) -> tuple[CurrentLoopCoordinator, dict]:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    result = coordinator.activate(
        original_request=REQUEST,
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    assert result["ok"] is True
    return coordinator, result


def _values(field: dict) -> list[str]:
    return [str(item["value"]) for item in field["accepted_values"]]


def test_static_domain_snapshot_is_derived_from_canonical_validator_domains() -> None:
    snapshot = bounded_control_contract_snapshot()
    assert snapshot["schema_id"] == BOUNDED_CONTROL_INPUT_SCHEMA_ID
    assert snapshot["named_presets"] == list(NAMED_PRESETS)
    assert snapshot["categories"] == list(EVIDENCE_CATEGORIES)
    assert snapshot["dimensions"] == list(ADJUSTMENT_DIMENSIONS)
    assert snapshot["values_by_dimension"] == {
        key: list(value) for key, value in ADJUSTMENT_VALUES_BY_DIMENSION.items()
    }
    assert snapshot["exclusion_reasons"] == list(EVIDENCE_EXCLUSION_REASONS)
    assert snapshot["operation_categories"] == list(SUPPORTED_OPERATION_CATEGORIES)
    assert snapshot["operation_output_roles"] == list(SUPPORTED_OUTPUT_ROLES)
    assert snapshot["off_is_distinct_stop_loop"] is True
    assert snapshot["raw_policy_serialization_required"] is False


def test_every_local_control_field_has_complete_ownership_and_domain(
    tmp_path: Path,
) -> None:
    coordinator, activated = _activate(tmp_path)
    controls = bounded_control_contracts(
        coordinator.store.read(), artifact_directory=coordinator.artifact_directory
    )
    assert set(controls) == {
        "contract_status",
        "contract_set_preset",
        "contract_adjust",
        "contract_set_generation_governance",
        "contract_confirm_broadening",
        "evidence_exclude",
        "evidence_restore",
        "evidence_delete",
        "stop_loop",
        "complete_instruction",
    }
    for operation, contract in controls.items():
        assert contract["schema_id"] == BOUNDED_CONTROL_INPUT_SCHEMA_ID
        assert contract["operation"] in {
            operation,
            "abandon",
        }
        assert contract["hosted_operation_permitted"] is False
        assert contract["assistant_uses_parser_help_or_source"] is False
        assert contract["customer_types_cli_or_internal_identifiers"] is False
        assert len(contract["contract_digest"]) == 64
        for field in contract["fields"]:
            assert field["ownership"]
            assert isinstance(field["required"], bool)
            assert field["json_type"]
            if field["ownership"] == "explicit_customer_bounded_selection":
                assert field["accepted_values"]
                assert all(item["customer_meaning"] for item in field["accepted_values"])
            if field["ownership"] == "qcoder_owned_prebound_value":
                assert "fixed_value" in field
    assert activated["bounded_control_catalog"]["controls_inline"] is False
    serialized = coordinator.bounded_control_catalog()["bounded_contract_controls"]
    assert set(serialized) == {
        "inspect",
        "review_customer_json",
        "apply_customer_json",
        "reset_to_preset",
        "set_preset",
        "adjust",
        "set_generation_governance",
        "confirm_broadening",
        "exclude",
        "restore",
        "delete",
        "stop_loop",
        "finish_loop",
        "open_editor",
        "evidence_view",
        "decline_build_review",
        "help",
    }
    for invocation in serialized.values():
        assert invocation["schema_id"] == INVOCATION_CONTRACT_SCHEMA_ID
        assert invocation["bounded_control_input_contract"]["schema_id"] in {
            BOUNDED_CONTROL_INPUT_SCHEMA_ID,
            "qcoder.current_loop.contract_management.v1",
            "qcoder.current_loop.contract_sidecar.v3",
            "qcoder.current_loop.evidence_view.v1",
            "qcoder.current_loop.build_review_choice.v1",
            "qcoder.current_loop.help_control.v1",
        }
        assert invocation["transport_classification"] == "local_only"
        assert "--base-url" not in invocation["structured_argv"]
        assert "--token-file" not in invocation["structured_argv"]


def test_preset_domain_is_sound_complete_and_off_is_a_distinct_stop_action(
    tmp_path: Path,
) -> None:
    coordinator, _ = _activate(tmp_path)
    contract = coordinator.store.read()["current_loop_contract"]
    supplied = coordinator.bounded_control_catalog()["bounded_contract_controls"]["set_preset"][
        "bounded_control_input_contract"
    ]
    field = next(item for item in supplied["fields"] if item["name"] == "preset")
    assert _values(field) == list(NAMED_PRESETS)
    assert {item["value"]: item["customer_meaning"] for item in field["accepted_values"]} == {
        value: PRESET_MEANINGS[value] for value in NAMED_PRESETS
    }
    for item in field["accepted_values"]:
        outcome = set_preset(
            contract,
            preset=item["value"],
            expected_contract_revision=contract["contract_revision"],
            provenance=(
                "customer_requested_narrowing"
                if item["value"] == "evidence_only"
                else "explicit_customer_selection"
            ),
        )
        assert item["change_disposition"] == outcome["disposition"]
    assert supplied["off_disposition"]["advertised_as_preset_selection"] is False
    stop = coordinator.bounded_control_catalog()["bounded_contract_controls"]["stop_loop"]
    assert stop["operation"] == "abandon"
    assert "--approve" in stop["structured_argv"]


def test_adjustment_selection_graph_is_sound_and_complete(tmp_path: Path) -> None:
    coordinator, _activated = _activate(tmp_path)
    contract = coordinator.store.read()["current_loop_contract"]
    supplied = adjustment_selection_contract(contract)
    graph = supplied["valid_selection_graph"]["categories"]
    assert [item["value"] for item in graph] == list(EVIDENCE_CATEGORIES)
    advertised: set[tuple[str, str, str]] = set()
    for category in graph:
        assert category["customer_meaning"] == CATEGORY_MEANINGS[category["value"]]
        assert [item["value"] for item in category["dimensions"]] == list(ADJUSTMENT_DIMENSIONS)
        for dimension in category["dimensions"]:
            assert dimension["customer_meaning"] == DIMENSION_MEANINGS[dimension["value"]]
            assert dimension["current_value"] == current_adjustment_value(
                contract,
                category=category["value"],
                dimension=dimension["value"],
            )
            assert [item["value"] for item in dimension["accepted_values"]] == list(
                ADJUSTMENT_VALUES_BY_DIMENSION[dimension["value"]]
            )
            for value in dimension["accepted_values"]:
                advertised.add((category["value"], dimension["value"], value["value"]))
                assert value["customer_meaning"] == VALUE_MEANINGS[value["value"]]
                outcome = adjust(
                    contract,
                    category=category["value"],
                    dimension=dimension["value"],
                    value=value["value"],
                    expected_contract_revision=contract["contract_revision"],
                    provenance="explicit_customer_selection",
                )
                assert value["change_disposition"] == outcome["disposition"]
    expected = {
        (category, dimension, value)
        for category in EVIDENCE_CATEGORIES
        for dimension in ADJUSTMENT_DIMENSIONS
        for value in ADJUSTMENT_VALUES_BY_DIMENSION[dimension]
    }
    assert advertised == expected
    assert supplied["independent_enum_cross_product_valid"] is False


@pytest.mark.parametrize(
    ("method", "kwargs", "category", "field"),
    [
        (
            "contract_set_preset",
            {"preset": "invented", "expected_contract_revision": 1},
            "contract_preset_invalid",
            "preset",
        ),
        (
            "contract_adjust",
            {
                "category": "invented",
                "dimension": "collect",
                "value": "enabled",
                "expected_contract_revision": 1,
            },
            "contract_category_invalid",
            "category",
        ),
        (
            "contract_adjust",
            {
                "category": "request_baseline",
                "dimension": "invented",
                "value": "enabled",
                "expected_contract_revision": 1,
            },
            "contract_dimension_invalid",
            "dimension",
        ),
        (
            "contract_adjust",
            {
                "category": "request_baseline",
                "dimension": "collect",
                "value": "standing",
                "expected_contract_revision": 1,
            },
            "contract_adjustment_value_invalid",
            "value",
        ),
    ],
)
def test_invalid_bounded_values_return_safe_refreshable_recovery(
    tmp_path: Path,
    method: str,
    kwargs: dict,
    category: str,
    field: str,
) -> None:
    coordinator, _activated = _activate(tmp_path)
    before = coordinator.store.read()
    result = getattr(coordinator, method)(**kwargs)
    assert result["ok"] is False
    assert result["category"] == category
    rejection = result["details"]["bounded_control_rejection"]
    assert rejection["field_name"] == field
    assert rejection["expected_field_contract"]["accepted_values"]
    assert rejection["hosted_operation_permitted"] is False
    assert rejection["raw_policy_or_evidence_echoed"] is False
    assert result["details"]["recovery_contract"]["complete_next_invocation_required"] is True
    invocation = result["next_invocation"]["operation_specific_invocation"]
    assert invocation["operation"] == "status"
    assert invocation["bounded_control_input_contract"]["recovery"]["active"] is True
    after = coordinator.store.read()
    assert after["current_loop_contract"] == before["current_loop_contract"]
    assert after["saved_artifacts"] == before["saved_artifacts"]


def test_evidence_references_and_operation_receipts_are_qcoder_supplied(
    tmp_path: Path,
) -> None:
    coordinator, activated = _activate(tmp_path)
    assert activated["bounded_control_catalog"]["controls_inline"] is False
    controls = coordinator.bounded_control_catalog()["bounded_contract_controls"]
    exclude = controls["exclude"]["bounded_control_input_contract"]
    reference_field = next(
        item for item in exclude["fields"] if item["name"] == "artifact_reference"
    )
    assert reference_field["accepted_values"]
    reference = reference_field["accepted_values"][0]["value"]
    reason_field = next(item for item in exclude["fields"] if item["name"] == "reason")
    assert _values(reason_field) == list(EVIDENCE_EXCLUSION_REASONS)
    excluded = coordinator.evidence_exclude(
        artifact_reference=reference,
        reason="not_relevant",
        expected_contract_revision=1,
    )
    assert excluded["ok"] is True
    assert excluded["bounded_control_catalog"]["controls_inline"] is False
    restore = coordinator.bounded_control_catalog()["bounded_contract_controls"]["restore"][
        "bounded_control_input_contract"
    ]
    restore_reference = next(
        item for item in restore["fields"] if item["name"] == "artifact_reference"
    )
    assert _values(restore_reference) == [reference]

    authority = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        operation_category="ide_write",
        output_role_ceiling=("source",),
    )
    assert authority["ok"] is True
    state = coordinator.store.read()
    receipt_contract = operation_receipt_contract(state)
    issued = receipt_contract["consume_operation_receipt"]["fields"][0]["accepted_values"]
    assert len(issued) == 1
    assert issued[0]["value"] == authority["details"]["operation_receipt"]["receipt_id"]
    assert issued[0]["qcoder_owned_reference"] is True


def test_binding_v7_delivers_the_static_contract_and_customer_meanings() -> None:
    descriptor = build_client_binding_descriptor(
        coordinator_prefix=["/runtime/python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    assert descriptor["contract_id"] == CLIENT_BINDING_CONTRACT_ID
    assert descriptor["contract_id"].endswith(".v20")
    contract = descriptor["bounded_control_input_contract"]
    assert contract["schema_id"] == BOUNDED_CONTROL_INPUT_SCHEMA_ID
    assert contract["contract_digest"]
    assert contract["assistant_infers_valid_combinations"] is False
    assert contract["parser_help_or_source_required"] is False
