from __future__ import annotations

import json
import time
from copy import deepcopy
from pathlib import Path

import pytest

import qcoder.current_loop_recovery as recovery_module
import qcoder.current_loop_vocabulary as vocabulary_module
from qcoder.connected_assistant_conformance import (
    client_neutral_conformance_contract,
    cursor_desktop_reference_profile,
    evaluate_conformance_observations,
    validate_conformance_profile,
)
from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    EXPECTED_TOOLS,
    build_client_binding_descriptor,
)
from qcoder.current_loop import CurrentLoopConflict, canonical_bytes
from qcoder.current_loop_coordinator import (
    CurrentLoopCoordinator,
    recovery_action_executability_matrix,
    result_semantic_classification,
)
from qcoder.current_loop_recovery import (
    recovery_contract_snapshot,
    resolve_live_recovery_policy,
)
from tests.current_loop_test_support import activate_reviewed_legacy_fixture


def _active(workspace: Path) -> CurrentLoopCoordinator:
    coordinator = CurrentLoopCoordinator(workspace_root=workspace)
    result = activate_reviewed_legacy_fixture(
        coordinator,
        original_request="Use qCoder for this build. Preserve the exact request and evidence.",
    )
    assert result["ok"] is True
    return coordinator


def test_nested_authoritative_store_lock_fails_immediately_without_state_change(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    before = canonical_bytes(coordinator.store.read())
    started = time.monotonic()
    with coordinator.store.lock():
        with pytest.raises(CurrentLoopConflict, match="current_loop_nested_lock_acquisition"):
            with coordinator.store.lock():
                raise AssertionError("nested lock unexpectedly acquired")
        with pytest.raises(CurrentLoopConflict, match="current_loop_nested_lock_acquisition"):
            coordinator.store.update(
                lambda state: state,
                expected_revision=coordinator.store.read()["state_revision"],
            )
    assert time.monotonic() - started < 0.5
    assert canonical_bytes(coordinator.store.read()) == before


def test_recovery_policy_has_one_live_action_source_and_no_inactive_table() -> None:
    assert not hasattr(recovery_module, "evidence_recovery")
    assert not hasattr(vocabulary_module, "ERROR_RECOVERY_ACTIONS")
    assert not hasattr(vocabulary_module, "recovery_actions_for")
    snapshot = recovery_contract_snapshot()
    assert snapshot["live_policy_source"].endswith("resolve_live_recovery_policy")
    inventory = snapshot["action_handler_inventory"]
    assert inventory == recovery_module.runtime_recovery_action_inventory()
    vocabulary = vocabulary_module.vocabulary_snapshot()
    assert vocabulary["disconnected_category_action_table_present"] is False
    assert vocabulary["recovery_actions"] == sorted(inventory)
    for row in recovery_action_executability_matrix():
        assert row["advertised_alternatives"] == [action["action"] for action in row["actions"]]
        assert all(action["executable_in_advertised_state"] for action in row["actions"])


def test_hosted_retry_is_conditional_and_stale_continuation_is_exact_only() -> None:
    presentation = (
        "The operation is unavailable.",
        "Use the supported local path or retry later.",
        True,
        False,
        True,
        False,
    )
    hosted = resolve_live_recovery_policy(
        category="protected_service_unavailable",
        presentation=presentation,
        receipt_context_present=False,
        causal_continuation_eligible=False,
        origin="hosted_transport",
        deterministic=False,
        active_loop_nonterminal=True,
    )
    assert hosted["hosted_action_availability"] == "conditional"
    assert (
        next(
            row for row in hosted["action_contracts"] if row["action"] == "retry_hosted_enrichment"
        )["availability"]
        == "conditional_hosted_service"
    )

    stale = resolve_live_recovery_policy(
        category="operation_receipt_stale",
        presentation=presentation,
        receipt_context_present=True,
        causal_continuation_eligible=True,
        origin="contract_or_authority",
        deterministic=True,
        active_loop_nonterminal=True,
    )
    assert stale["advertised_actions"] == ["retry_registration", "stop_loop"]
    assert stale["authority_ceiling"] == "exact_prior_action_only"
    changed = resolve_live_recovery_policy(
        category="operation_receipt_stale",
        presentation=presentation,
        receipt_context_present=True,
        causal_continuation_eligible=False,
        origin="contract_or_authority",
        deterministic=True,
        active_loop_nonterminal=True,
    )
    assert "retry_registration" not in changed["advertised_actions"]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    (
        (
            dict(
                operation="status",
                ok=True,
                category=None,
                phase="generation_ready",
                state_status="ready",
                persist_performance=False,
            ),
            "pure_observation",
        ),
        (
            dict(
                operation="status",
                ok=True,
                category=None,
                phase="evidence_processing",
                state_status="checkpoint_required",
                persist_performance=True,
            ),
            "checkpoint_production",
        ),
        (
            dict(
                operation="execute_recovery_action",
                ok=False,
                category="recovery_action_not_permitted",
                phase="evidence_processing",
                state_status="blocked",
                persist_performance=True,
            ),
            "unsupported_action",
        ),
        (
            dict(
                operation="execute_recovery_action",
                ok=False,
                category="unsupported_recovery_schema",
                phase="evidence_processing",
                state_status="blocked",
                persist_performance=False,
            ),
            "schema_failure",
        ),
        (
            dict(
                operation="record_ide_authority",
                ok=False,
                category="ide_write_or_run_denied",
                phase="generation_ready",
                state_status="checkpoint_required",
                persist_performance=True,
            ),
            "authority_denial",
        ),
        (
            dict(
                operation="register_artifacts",
                ok=False,
                category="operation_receipt_expired",
                phase="evidence_processing",
                state_status="blocked",
                persist_performance=True,
            ),
            "lifecycle_or_expiry_failure",
        ),
        (
            dict(
                operation="register_artifacts",
                ok=True,
                category=None,
                phase="evidence_processing",
                state_status="ready",
                persist_performance=True,
            ),
            "authoritative_mutation",
        ),
        (
            dict(
                operation="complete_instruction",
                ok=True,
                category=None,
                phase="completed",
                state_status="completed",
                persist_performance=True,
            ),
            "terminal_state",
        ),
    ),
)
def test_result_semantic_classification_is_precise(
    arguments: dict[str, object], expected: str
) -> None:
    assert result_semantic_classification(**arguments) == expected


@pytest.mark.parametrize(
    "profile",
    [cursor_desktop_reference_profile()],
    ids=lambda profile: str(profile["profile_id"]),
)
def test_parameterized_client_neutral_conformance_profile(
    tmp_path: Path, profile: dict[str, object]
) -> None:
    validate_conformance_profile(profile)
    contract = client_neutral_conformance_contract(EXPECTED_TOOLS)
    assert contract["tool_count"] == 12
    assert tuple(contract["tool_inventory"]) == EXPECTED_TOOLS
    assert contract["second_workflow_engine_present"] is False
    assert contract["generic_mcp_compatibility_claimed"] is False
    assert contract["future_profile_template_enabled"] is False
    assert tuple(profile["shared_assertions"]) == tuple(contract["shared_assertions"])
    assert all("cursor" not in name.casefold() for name in contract["shared_assertions"])

    descriptor = build_client_binding_descriptor(
        coordinator_prefix=["/runtime/python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    assert descriptor["contract_id"] == CLIENT_BINDING_CONTRACT_ID
    assert CLIENT_BINDING_CONTRACT_ID.endswith(".v35")
    assert descriptor["qcoder_domain_tool_count"] == 12
    assert descriptor["client_neutral_conformance_contract"] == contract
    assert descriptor["cursor_desktop_reference_profile"] == profile

    coordinator = _active(tmp_path)
    status_before = coordinator.store.read()
    status_result = coordinator.status()
    status_after = coordinator.store.read()
    assert status_result["result_semantic_classification"] == "pure_observation"
    assert status_after["state_revision"] == status_before["state_revision"]
    assert status_after["state_digest"] == status_before["state_digest"]
    assert coordinator.help(topic="overview")["result_semantic_classification"] == (
        "pure_observation"
    )


def test_profile_validation_rejects_weakened_permission_or_assertion_contract() -> None:
    profile = cursor_desktop_reference_profile()
    weakened = deepcopy(profile)
    weakened["automatic_native_permission_approval"] = True
    with pytest.raises(ValueError, match="native_permission_boundary"):
        validate_conformance_profile(weakened)
    missing = deepcopy(profile)
    missing["shared_assertions"] = list(missing["shared_assertions"][:-1])
    with pytest.raises(ValueError, match="shared_assertion_mismatch"):
        validate_conformance_profile(missing)


@pytest.mark.parametrize(
    "profile",
    [cursor_desktop_reference_profile()],
    ids=lambda profile: str(profile["profile_id"]),
)
def test_reusable_conformance_evaluator_requires_every_shared_assertion(
    profile: dict[str, object],
) -> None:
    observations = {name: True for name in profile["shared_assertions"]}
    passed = evaluate_conformance_observations(
        profile=profile,
        observations=observations,
    )
    assert passed["passed"] is True
    assert passed["live_client_qualification_created"] is False
    missing = deepcopy(observations)
    missing.pop(next(iter(missing)))
    assert (
        evaluate_conformance_observations(
            profile=profile,
            observations=missing,
        )["passed"]
        is False
    )
    failed = deepcopy(observations)
    failed[next(iter(failed))] = False
    assert (
        evaluate_conformance_observations(
            profile=profile,
            observations=failed,
        )["passed"]
        is False
    )


def test_serialized_binding_contains_no_enabled_future_client_adapter() -> None:
    descriptor = build_client_binding_descriptor(
        coordinator_prefix=["python", "-m", "qcoder", "current-loop"]
    )
    serialized = json.dumps(descriptor, sort_keys=True).casefold()
    assert 'generic_mcp_compatibility_claimed": false' in serialized
    assert 'future_profile_template_enabled": false' in serialized
