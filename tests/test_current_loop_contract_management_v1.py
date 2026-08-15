from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from qcoder.current_loop import CURRENT_LOOP_STATE_MAX_BYTES, canonical_bytes
from qcoder.current_loop_contract_management import (
    CONTRACT_CHANGE_RECEIPT_SCHEMA_ID,
    CONTRACT_DIFF_SCHEMA_ID,
    CONTRACT_MANAGEMENT_SCHEMA_ID,
    CONTRACT_VALIDATION_SCHEMA_ID,
    CUSTOMER_CONTRACT_DOCUMENT_SCHEMA_ID,
    EFFECTIVE_CONTRACT_DOCUMENT_SCHEMA_ID,
    ContractManagementError,
    apply_customer_contract_review,
    confirm_customer_contract_broadening,
    contract_management_snapshot,
    customer_contract_document,
    effective_contract_document,
    parse_customer_contract_json,
    reset_customer_contract_document,
    review_customer_contract_document,
    semantic_contract_equivalence,
)
from qcoder.current_loop_contract_sidecar import (
    SIDECAR_SCHEMA_ID,
    SidecarSession,
    _CSS,
    _HTML,
    _JS,
    sidecar_contract_snapshot,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    EXPECTED_TOOLS,
    build_client_binding_descriptor,
)


REQUEST = (
    "Use qCoder for this build. Create and run one bounded local Qiskit program. "
    "Keep qCoder quiet unless a material decision or real blocker requires me."
)


def _active(workspace: Path) -> CurrentLoopCoordinator:
    coordinator = CurrentLoopCoordinator(workspace_root=workspace)
    result = coordinator.activate(
        original_request=REQUEST,
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    assert result["ok"] is True
    return coordinator


def _contract(coordinator: CurrentLoopCoordinator) -> dict:
    return coordinator.store.read()["current_loop_contract"]


def _narrow_result_exposure(document: dict) -> None:
    document["customer_settings"]["preset"] = "custom"
    document["customer_settings"]["evidence_categories"]["result_manifestation"][
        "derived_assistant_exposure"
    ] = "disabled"


def test_management_contract_has_one_canonical_domain_and_no_customer_cli_requirement() -> None:
    contract = contract_management_snapshot()
    assert contract["schema_id"] == CONTRACT_MANAGEMENT_SCHEMA_ID
    assert contract["title"] == "How qCoder should help with this build"
    assert contract["canonical_internal_name"] == "Current Loop Contract"
    assert contract["canonical_service_shared_by"] == [
        "coordinator_ide",
        "local_browser",
        "tests",
    ]
    assert contract["customer_cli_required"] is False
    assert contract["raw_state_replacement_accepted"] is False
    assert contract["customer_document_schema"]["duplicate_keys"] == "rejected"
    assert contract["customer_document_schema"]["prototype_pollution_keys"] == "rejected"
    equivalence = semantic_contract_equivalence()
    assert equivalence["duplicate_policy_tables"] is False
    assert set(equivalence["preset_domains"]) == {"assist", "evidence_only"}


def test_effective_and_editable_documents_are_distinct_and_customer_bounded(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    contract = _contract(coordinator)
    effective = effective_contract_document(contract)
    editable = customer_contract_document(contract)
    assert effective["schema_id"] == EFFECTIVE_CONTRACT_DOCUMENT_SCHEMA_ID
    assert editable["schema_id"] == CUSTOMER_CONTRACT_DOCUMENT_SCHEMA_ID
    assert effective["contract_revision"] == editable["expected_contract_revision"] == 1
    assert effective["raw_internal_state_included"] is False
    serialized = json.dumps({"effective": effective, "editable": editable})
    for prohibited in (
        "operation_receipts",
        "token_file",
        "workspace_root",
        "artifact_directory",
        "recovery_reference",
    ):
        assert prohibited not in serialized
    assert set(editable) == {
        "schema_id",
        "schema_version",
        "expected_contract_revision",
        "customer_settings",
    }


@pytest.mark.parametrize(
    ("raw", "category"),
    [
        ('{"schema_id":"x","schema_id":"y"}', "customer_contract_json_duplicate_key"),
        ('{"__proto__":{}}', "customer_contract_json_unsafe_key"),
        ('{"constructor":{}}', "customer_contract_json_unsafe_key"),
        ('{"prototype":{}}', "customer_contract_json_unsafe_key"),
        ('{"x":"\\u0000"}', "customer_contract_json_unsafe_control"),
        ('{"x":', "customer_contract_json_syntax_invalid"),
        (b"\xff", "customer_contract_json_utf8_invalid"),
    ],
)
def test_json_parser_rejects_unsafe_or_ambiguous_input(
    raw: str | bytes,
    category: str,
) -> None:
    with pytest.raises(ContractManagementError, match=category) as captured:
        parse_customer_contract_json(raw)
    assert captured.value.category == category


def test_json_parser_rejects_excessive_size_and_depth() -> None:
    with pytest.raises(ContractManagementError) as oversized:
        parse_customer_contract_json('{"x":"' + ("a" * 65_536) + '"}')
    assert oversized.value.category == "customer_contract_json_too_large"
    value: object = "leaf"
    for _ in range(14):
        value = {"x": value}
    with pytest.raises(ContractManagementError) as deep:
        parse_customer_contract_json(json.dumps(value))
    assert deep.value.category == "customer_contract_json_depth_exceeded"


def test_valid_json_round_trip_is_deterministic(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    document = customer_contract_document(_contract(coordinator))
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    parsed = parse_customer_contract_json(encoded)
    review = review_customer_contract_document(_contract(coordinator), parsed)
    assert review["schema_id"] == CONTRACT_DIFF_SCHEMA_ID
    assert review["valid"] is True
    assert review["classification"] == "neutral"
    assert review["changes"] == []


def test_unknown_qcoder_owned_stale_and_invalid_values_fail_closed(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    contract = _contract(coordinator)
    cases: list[tuple[dict, str]] = []
    unknown = customer_contract_document(contract)
    unknown["customer_settings"]["unexpected"] = True
    cases.append((unknown, "customer_contract_document_unknown_field"))
    stale = customer_contract_document(contract)
    stale["expected_contract_revision"] += 1
    cases.append((stale, "customer_contract_document_revision_stale"))
    schema = customer_contract_document(contract)
    schema["schema_version"] = 99
    cases.append((schema, "customer_contract_document_schema_invalid"))
    invalid = customer_contract_document(contract)
    invalid["customer_settings"]["generation_governance"] = "guess"
    cases.append((invalid, "customer_contract_value_invalid"))
    wrong_type = customer_contract_document(contract)
    wrong_type["customer_settings"]["evidence_categories"]["result_manifestation"]["collect"] = True
    cases.append((wrong_type, "customer_contract_value_invalid"))
    for document, category in cases:
        review = review_customer_contract_document(contract, document)
        assert review["valid"] is False
        assert review["classification"] == "invalid"
        assert review["validation"]["schema_id"] == CONTRACT_VALIDATION_SCHEMA_ID
        assert review["validation"]["error_category"] == category
        assert review["validation"]["raw_document_echoed"] is False


def test_narrowing_is_immediate_revisioned_and_warns_about_prior_context(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    document = customer_contract_document(_contract(coordinator))
    _narrow_result_exposure(document)
    review = review_customer_contract_document(_contract(coordinator), document)
    assert review["classification"] == "narrowing"
    outcome = apply_customer_contract_review(
        _contract(coordinator),
        review,
        choice="apply_narrowing",
        surface="ide",
    )
    updated = outcome["contract"]
    assert outcome["disposition"] == "narrowing_applied"
    assert updated["contract_revision"] == 2
    assert outcome["receipt"]["schema_id"] == CONTRACT_CHANGE_RECEIPT_SCHEMA_ID
    assert outcome["receipt"]["previously_delivered_context_recallable"] is False
    assert (
        updated["effective_policy"]["categories"]["result_manifestation"]["expose"][
            "connected_assistant"
        ]["derived"]
        == "disabled"
    )


def test_broadening_is_exact_authority_only_and_cross_surface(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    narrow = customer_contract_document(_contract(coordinator))
    _narrow_result_exposure(narrow)
    applied = coordinator.contract_apply_customer_document(
        document=narrow,
        choice="apply_narrowing",
        explicit_authority=False,
        surface="ide",
    )
    assert applied["ok"] is True
    broaden = customer_contract_document(_contract(coordinator))
    broaden["customer_settings"]["evidence_categories"]["result_manifestation"][
        "derived_assistant_exposure"
    ] = "standing"
    proposed = coordinator.contract_apply_customer_document(
        document=broaden,
        choice="create_broadening_proposal",
        explicit_authority=False,
        surface="browser",
    )
    assert proposed["ok"] is True
    assert proposed["category"] == "contract_broadening_proposed"
    assert _contract(coordinator)["contract_revision"] == 2
    with pytest.raises(ContractManagementError):
        confirm_customer_contract_broadening(
            _contract(coordinator),
            expected_contract_revision=2,
            explicit_authority=False,
            surface="ide",
        )
    confirmed = coordinator.contract_confirm_broadening(
        expected_contract_revision=2,
        explicit_authority=True,
        surface="ide",
    )
    assert confirmed["ok"] is True
    assert _contract(coordinator)["contract_revision"] == 3
    assert _contract(coordinator)["pending_broadening_proposal"] is None


def test_mixed_change_never_silently_partially_applies(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    first = customer_contract_document(_contract(coordinator))
    _narrow_result_exposure(first)
    coordinator.contract_apply_customer_document(
        document=first,
        choice="apply_narrowing",
        explicit_authority=False,
    )
    mixed = customer_contract_document(_contract(coordinator))
    mixed["customer_settings"]["evidence_categories"]["result_manifestation"][
        "derived_assistant_exposure"
    ] = "standing"
    mixed["customer_settings"]["evidence_categories"]["derived_metrics"]["recommendations"] = (
        "disabled"
    )
    review = review_customer_contract_document(_contract(coordinator), mixed)
    assert review["classification"] == "mixed"
    assert {choice["value"] for choice in review["choices"]} == {
        "apply_narrowing_subset",
        "confirm_complete_change_set",
        "cancel",
    }
    before = deepcopy(_contract(coordinator))
    cancelled = apply_customer_contract_review(
        before,
        review,
        choice="cancel",
        surface="ide",
    )
    assert cancelled["contract"] == before
    split = apply_customer_contract_review(
        before,
        review,
        choice="apply_narrowing_subset",
        surface="ide",
    )
    assert split["disposition"] == "narrowing_applied_broadening_proposed"
    assert split["contract"]["contract_revision"] == 3
    assert split["contract"]["pending_broadening_proposal"]["approval_required"] is True
    result_row = split["contract"]["effective_policy"]["categories"]["result_manifestation"]
    assert result_row["expose"]["connected_assistant"]["derived"] == "disabled"
    complete = apply_customer_contract_review(
        before,
        review,
        choice="confirm_complete_change_set",
        surface="browser",
    )
    assert complete["disposition"] == "mixed_change_proposed"
    assert complete["contract"]["contract_revision"] == before["contract_revision"]
    assert complete["proposal"]["authority_only_confirmation"] is True
    assert complete["proposal"]["raw_json_retransmission_required"] is False
    confirmed = confirm_customer_contract_broadening(
        complete["contract"],
        expected_contract_revision=before["contract_revision"],
        explicit_authority=True,
        surface="ide",
    )
    assert confirmed["contract"]["contract_revision"] == before["contract_revision"] + 1


def test_generation_governance_and_preset_reset_use_same_service(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    sidecar = SidecarSession(workspace=tmp_path, coordinator=coordinator)
    before = sidecar.snapshot()
    narrowed = sidecar.action(
        action="set_generation_governance",
        payload={"governance": "blueprint_required"},
        expected_contract_revision=before["contract_revision"],
    )
    assert narrowed["ok"] is True
    assert _contract(coordinator)["generation_governance"] == "blueprint_required"
    assert (
        coordinator.contract_status()["details"]["effective_contract_json"]["contract_revision"]
        == sidecar.snapshot()["contract_revision"]
    )
    proposed = coordinator.contract_set_generation_governance(
        governance="adaptive",
        expected_contract_revision=_contract(coordinator)["contract_revision"],
    )
    assert proposed["category"] == "contract_broadening_proposed"
    confirmed = sidecar.action(
        action="confirm_broadening",
        payload={"explicit_authority": True},
        expected_contract_revision=_contract(coordinator)["contract_revision"],
    )
    assert confirmed["ok"] is True
    assert _contract(coordinator)["generation_governance"] == "adaptive"
    document = reset_customer_contract_document(_contract(coordinator), preset="evidence_only")
    review = review_customer_contract_document(_contract(coordinator), document)
    assert review["classification"] == "narrowing"
    coordinator.contract_apply_customer_document(
        document=document,
        choice="apply_narrowing",
        explicit_authority=False,
    )
    assist = reset_customer_contract_document(_contract(coordinator), preset="assist")
    proposed_assist = coordinator.contract_apply_customer_document(
        document=assist,
        choice="create_broadening_proposal",
        explicit_authority=False,
    )
    assert proposed_assist["category"] == "contract_broadening_proposed"
    revision = _contract(coordinator)["contract_revision"]
    coordinator.contract_confirm_broadening(
        expected_contract_revision=revision,
        explicit_authority=True,
        surface="browser",
    )
    assert _contract(coordinator)["effective_preset"] == "assist"


def test_cross_surface_stale_writer_fails_closed(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    sidecar = SidecarSession(workspace=tmp_path, coordinator=coordinator)
    stale_revision = sidecar.snapshot()["contract_revision"]
    coordinator.contract_set_generation_governance(
        governance="blueprint_required",
        expected_contract_revision=stale_revision,
    )
    with pytest.raises(ValueError, match="sidecar_contract_revision_stale"):
        sidecar.action(
            action="set_preset",
            payload={"preset": "evidence_only"},
            expected_contract_revision=stale_revision,
        )


def test_sidecar_v3_ui_is_local_accessible_and_storage_free() -> None:
    contract = sidecar_contract_snapshot()
    assert contract["schema_id"] == SIDECAR_SCHEMA_ID
    assert contract["schema_version"] == 3
    assert contract["duplicate_json_keys_rejected"] is True
    assert contract["prototype_pollution_keys_rejected"] is True
    assert contract["json_values_rendered_as_text"] is True
    assert contract["protected_operation_endpoint"] is False
    assert contract["hosted_operation_endpoint"] is False
    assert "How qCoder should help with this build" in _HTML
    assert "Effective JSON" in _HTML
    assert "Edit JSON" in _HTML
    assert "Review Changes" in _HTML
    assert "localStorage" not in _JS
    assert "sessionStorage" not in _JS
    assert "document.cookie" not in _JS
    assert "innerHTML" not in _JS
    assert "textContent" in _JS
    assert ":focus-visible" in _CSS
    assert "https://" not in _HTML + _CSS + _JS


def test_binding_v18_publishes_management_without_changing_tools() -> None:
    binding = build_client_binding_descriptor(
        coordinator_prefix=["/runtime/python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v20"
    assert binding["contract_management"]["schema_id"] == CONTRACT_MANAGEMENT_SCHEMA_ID
    assert binding["browser_and_ide_share_contract_management_service"] is True
    assert binding["effective_contract_json_read_only"] is True
    assert binding["polished_customer_cli_required"] is False
    assert len(EXPECTED_TOOLS) == 12


def test_contract_help_is_grounded_and_customer_language_only(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    result = coordinator.help(topic="contract")
    assert result["ok"] is True
    management = result["details"]["contract_management"]
    assert management["effective_preset"] == "assist"
    assert management["browser_editor_optional"] is True
    assert management["internal_command_choreography_exposed"] is False
    assert "Show me the qCoder contract." in management["examples"]
    serialized = json.dumps(result["details"], sort_keys=True)
    assert ".qcoder" not in serialized
    assert "contract-adjust --" not in serialized


def test_management_metadata_stays_bounded_in_state(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    document = customer_contract_document(_contract(coordinator))
    _narrow_result_exposure(document)
    result = coordinator.contract_apply_customer_document(
        document=document,
        choice="apply_narrowing",
        explicit_authority=False,
    )
    assert result["ok"] is True
    size = len(canonical_bytes(coordinator.store.read()))
    assert size < CURRENT_LOOP_STATE_MAX_BYTES
    assert CURRENT_LOOP_STATE_MAX_BYTES - size > 16_384
