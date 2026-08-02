from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest

import qcoder.current_loop_coordinator as coordinator_module
from qcoder.current_loop import CurrentLoopError, canonical_bytes
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_evidence_processing import hosted_enrichment_status


def _active(workspace: Path) -> CurrentLoopCoordinator:
    workspace.mkdir(parents=True, exist_ok=True)
    coordinator = CurrentLoopCoordinator(workspace_root=workspace)
    result = coordinator.activate(
        original_request="Use qCoder for this exact bounded build.",
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    assert result["ok"] is True
    return coordinator


def _generic_recovery(
    workspace: Path,
    *,
    alternatives: tuple[str, ...] = ("abandon_step", "stop_loop"),
) -> CurrentLoopCoordinator:
    coordinator = _active(workspace)
    result = coordinator._recovery_result(
        operation="abandon_escape_proof",
        category="unknown_local_internal",
        phase="activated",
        elapsed=0.0,
        alternatives=alternatives,
    )
    active = coordinator._coordinator_state(coordinator.store.read())["active_recovery"]
    assert active is not None
    assert set(active["alternatives"]) == set(alternatives)
    assert result["ok"] is False
    return coordinator


def _stale_recovery(
    workspace: Path,
) -> tuple[CurrentLoopCoordinator, Path, str]:
    coordinator = _active(workspace)
    authority = coordinator.record_ide_authority(
        allowed=True,
        explicit_user_action=True,
        operation_category="ide_write",
        output_role_ceiling=("source",),
    )
    assert authority["ok"] is True
    receipt = authority["details"]["operation_receipt"]
    state = coordinator.store.read()

    def advance_revision(value: dict[str, Any]) -> Mapping[str, Any]:
        value["coordinator"]["performance"]["coordinator_calls"] += 1
        return value

    coordinator.store.update(
        advance_revision,
        expected_revision=int(state["state_revision"]),
    )
    project_file = workspace / "program.py"
    project_file.write_text("VALUE = 1\n", encoding="utf-8")
    stale = coordinator.register_artifacts(
        candidates=[
            {
                "role": "source",
                "path": str(project_file),
                "provenance": "assistant_created",
                "explicit_external": False,
            }
        ],
        operation_receipt_id=str(receipt["receipt_id"]),
    )
    assert stale["category"] == "operation_receipt_stale"
    return coordinator, project_file, str(receipt["receipt_id"])


def _rewrite_active_recovery(
    coordinator: CurrentLoopCoordinator,
    transform: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    state = coordinator.store.read()

    def mutate(value: dict[str, Any]) -> Mapping[str, Any]:
        active = value["coordinator"]["active_recovery"]
        assert isinstance(active, dict)
        transform(active)
        return value

    coordinator.store.update(mutate, expected_revision=int(state["state_revision"]))
    active = coordinator._coordinator_state(coordinator.store.read())["active_recovery"]
    assert isinstance(active, dict)
    return active


def _apply_incompatible_variant(
    coordinator: CurrentLoopCoordinator,
    variant: str,
) -> dict[str, Any]:
    def transform(active: dict[str, Any]) -> None:
        if variant == "legacy_v4":
            active["schema_id"] = "qcoder.current_loop.recovery.v4"
            active["schema_version"] = 4
        elif variant == "malformed_schema_id":
            active["schema_id"] = "malformed.recovery"
        elif variant == "future_v6":
            active["schema_version"] = 6
        elif variant == "missing_action_fields":
            active.pop("alternatives", None)
        else:  # pragma: no cover - test helper misuse
            raise AssertionError(variant)

    return _rewrite_active_recovery(coordinator, transform)


def _assert_no_recovery_execution_during_abandon(
    coordinator: CurrentLoopCoordinator,
    project_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    calls: list[str] = []

    def unexpected(name: str) -> Callable[..., Any]:
        def fail(*_args: Any, **_kwargs: Any) -> Any:
            calls.append(name)
            raise AssertionError(f"unexpected abandon side effect: {name}")

        return fail

    monkeypatch.setattr(
        coordinator_module,
        "issue_operation_receipt",
        unexpected("issue_operation_receipt"),
    )
    monkeypatch.setattr(
        coordinator_module,
        "commit_registration_transaction",
        unexpected("commit_registration_transaction"),
    )
    monkeypatch.setattr(
        coordinator_module,
        "activate_current_loop",
        unexpected("activate_current_loop"),
    )
    monkeypatch.setattr(
        coordinator,
        "execute_recovery_action",
        unexpected("execute_recovery_action"),
    )

    result = coordinator.abandon(explicit_authority=True)
    assert result["ok"] is True
    assert result["phase"] == "abandoned"
    assert result["details"]["loop_close_cleanup"]["state_deleted"] is True
    assert result["details"]["loop_close_cleanup"]["user_project_files_deleted"] is False
    assert project_file.read_text(encoding="utf-8") == "customer-owned\n"
    assert not coordinator.store.state_path.exists()
    assert calls == []
    with pytest.raises(CurrentLoopError, match="current_loop_not_active"):
        coordinator.store.read()
    return result


@pytest.mark.parametrize(
    "recovery_kind",
    ("retry_registration", "stop_loop", "non_registration"),
)
def test_legacy_v4_recovery_variants_cannot_block_explicit_abandon(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recovery_kind: str,
) -> None:
    workspace = tmp_path / recovery_kind
    if recovery_kind == "retry_registration":
        coordinator, generated_file, receipt_id = _stale_recovery(workspace)
        assert generated_file.read_text(encoding="utf-8") == "VALUE = 1\n"
        state = coordinator.store.read()
        assert state["operation_receipts"][receipt_id]["status"] == "issued"
        assert state["activity_receipts"] == []
        context = coordinator._coordinator_state(state)["active_recovery"][
            "receipt_recovery_context"
        ]
        assert context["continuation_attempted"] is False
    elif recovery_kind == "stop_loop":
        coordinator = _generic_recovery(workspace, alternatives=("stop_loop",))
    else:
        coordinator = _generic_recovery(workspace)
    project_file = workspace / "customer.txt"
    project_file.write_text("customer-owned\n", encoding="utf-8")
    active = _apply_incompatible_variant(coordinator, "legacy_v4")
    assert active["schema_version"] == 4

    _assert_no_recovery_execution_during_abandon(coordinator, project_file, monkeypatch)
    if recovery_kind == "retry_registration":
        assert generated_file.read_text(encoding="utf-8") == "VALUE = 1\n"


@pytest.mark.parametrize(
    "variant",
    ("malformed_schema_id", "future_v6", "missing_action_fields"),
)
def test_malformed_or_future_recovery_is_discarded_by_explicit_abandon(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    workspace = tmp_path / variant
    coordinator = _generic_recovery(workspace)
    project_file = workspace / "customer.txt"
    project_file.write_text("customer-owned\n", encoding="utf-8")
    _apply_incompatible_variant(coordinator, variant)

    _assert_no_recovery_execution_during_abandon(coordinator, project_file, monkeypatch)


@pytest.mark.parametrize("variant", ("legacy_v4", "malformed_schema_id"))
def test_incompatible_recovery_does_not_weaken_explicit_abandon_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    workspace = tmp_path / variant
    coordinator = _generic_recovery(workspace)
    project_file = workspace / "customer.txt"
    project_file.write_text("customer-owned\n", encoding="utf-8")
    active = _apply_incompatible_variant(coordinator, variant)
    calls: list[str] = []
    monkeypatch.setattr(
        coordinator,
        "execute_recovery_action",
        lambda **_kwargs: calls.append("execute_recovery_action"),
    )

    denied = coordinator.abandon(explicit_authority=False)
    assert denied["ok"] is True
    assert denied["checkpoint_kind"] == "activation"
    assert "requires an explicit user act" in denied["customer_summary"]
    assert coordinator.store.state_path.exists()
    state = coordinator.store.read()
    assert state["completion_state"] == "in_progress"
    assert coordinator._coordinator_state(state)["active_recovery"]["schema_id"] == active[
        "schema_id"
    ]
    assert project_file.read_text(encoding="utf-8") == "customer-owned\n"
    assert calls == []


def _gated_operation(
    workspace: Path,
    operation: str,
) -> tuple[CurrentLoopCoordinator, Callable[[], dict[str, Any]]]:
    if operation == "retry_registration":
        coordinator, _project_file, _receipt_id = _stale_recovery(workspace)
        state = coordinator.store.read()
        active = coordinator._coordinator_state(state)["active_recovery"]
        return coordinator, lambda: coordinator.execute_recovery_action(
            recovery_reference=str(active["reference"]),
            action="retry_registration",
            expected_contract_revision=int(
                coordinator.store.read()["current_loop_contract"]["contract_revision"]
            ),
        )

    coordinator = _generic_recovery(
        workspace,
        alternatives=("stop_loop",) if operation == "stop_loop" else ("abandon_step", "stop_loop"),
    )
    if operation == "enrichment":
        state = coordinator.store.read()

        def prepare_enrichment(value: dict[str, Any]) -> Mapping[str, Any]:
            value["coordinator"]["phase"] = "evidence_processing"
            value["coordinator"]["state_status"] = "ready"
            value["coordinator"]["checkpoint_kind"] = "none"
            value["coordinator"]["evidence_processing_complete"] = True
            value["hosted_enrichment"] = hosted_enrichment_status("available")
            return value

        coordinator.store.update(
            prepare_enrichment,
            expected_revision=int(state["state_revision"]),
        )
        coordinator.enrich_authorized_evidence()
        return coordinator, coordinator.enrich_authorized_evidence
    if operation == "build_review":
        state = coordinator.store.read()

        def prepare_build_review(value: dict[str, Any]) -> Mapping[str, Any]:
            value["coordinator"]["phase"] = "evidence_processing"
            return value

        coordinator.store.update(
            prepare_build_review,
            expected_revision=int(state["state_revision"]),
        )
        return coordinator, lambda: coordinator.decline_build_review(explicit_authority=True)

    state = coordinator.store.read()
    active = coordinator._coordinator_state(state)["active_recovery"]
    action = "stop_loop" if operation == "stop_loop" else "abandon_step"
    return coordinator, lambda: coordinator.execute_recovery_action(
        recovery_reference=str(active["reference"]),
        action=action,
        expected_contract_revision=int(
            coordinator.store.read()["current_loop_contract"]["contract_revision"]
        ),
    )


@pytest.mark.parametrize(
    "variant",
    ("legacy_v4", "malformed_schema_id", "future_v6"),
)
@pytest.mark.parametrize(
    "operation",
    ("stop_loop", "retry_registration", "enrichment", "build_review", "non_registration"),
)
def test_every_recovery_interpreting_path_remains_schema_gated_and_byte_neutral(
    tmp_path: Path,
    variant: str,
    operation: str,
) -> None:
    coordinator, invoke = _gated_operation(tmp_path / f"{operation}-{variant}", operation)
    _apply_incompatible_variant(coordinator, variant)
    before = canonical_bytes(coordinator.store.read())

    rejected = invoke()
    assert rejected["ok"] is False
    assert rejected["category"] == "unsupported_recovery_schema"
    assert rejected["details"]["recovery_action_executed"] is False
    assert rejected["details"]["legacy_authority_reinterpreted"] is False
    assert rejected["details"]["supported_next_action"] == "explicit_abandon_active_loop"
    customer_summary = rejected["customer_summary"].lower()
    assert "explicitly abandon the active loop" in customer_summary
    assert "schema" not in customer_summary
    assert canonical_bytes(coordinator.store.read()) == before


@pytest.mark.parametrize("legacy", (False, True))
def test_stop_loop_endpoint_routes_through_gated_ordinary_abandon(
    tmp_path: Path,
    legacy: bool,
) -> None:
    workspace = tmp_path / ("legacy" if legacy else "current")
    coordinator = _generic_recovery(workspace, alternatives=("stop_loop",))
    active = coordinator._coordinator_state(coordinator.store.read())["active_recovery"]
    if legacy:
        active = _apply_incompatible_variant(coordinator, "legacy_v4")
    before = canonical_bytes(coordinator.store.read())

    routed = coordinator.execute_recovery_action(
        recovery_reference=str(active["reference"]),
        action="stop_loop",
        expected_contract_revision=int(
            coordinator.store.read()["current_loop_contract"]["contract_revision"]
        ),
    )
    assert routed["ok"] is False
    assert routed["category"] == (
        "unsupported_recovery_schema"
        if legacy
        else "recovery_stop_requires_abandon_invocation"
    )
    assert routed["details"]["supported_next_action"] == "explicit_abandon_active_loop"
    assert routed["details"]["recovery_action_executed"] is False
    assert canonical_bytes(coordinator.store.read()) == before

    abandoned = coordinator.abandon(explicit_authority=True)
    assert abandoned["ok"] is True
    assert not coordinator.store.state_path.exists()


def test_supported_v5_actions_stay_gated_while_explicit_abandon_discards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action_coordinator = _generic_recovery(tmp_path / "action")
    action_state = action_coordinator.store.read()
    action_active = action_coordinator._coordinator_state(action_state)["active_recovery"]
    original_gate = coordinator_module._active_recovery_schema_error
    observed_actions: list[str] = []

    def observe_gate(active: object, *, selected_action: str) -> str | None:
        observed_actions.append(selected_action)
        return original_gate(active, selected_action=selected_action)

    monkeypatch.setattr(coordinator_module, "_active_recovery_schema_error", observe_gate)
    executed = action_coordinator.execute_recovery_action(
        recovery_reference=str(action_active["reference"]),
        action="abandon_step",
        expected_contract_revision=int(
            action_state["current_loop_contract"]["contract_revision"]
        ),
    )
    assert executed["ok"] is True
    assert observed_actions == ["abandon_step"]

    abandon_coordinator = _generic_recovery(tmp_path / "abandon")
    observed_actions.clear()
    abandoned = abandon_coordinator.abandon(explicit_authority=True)
    assert abandoned["ok"] is True
    assert observed_actions == []


def test_documented_upgrade_restart_path_is_executable_and_not_automatic(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "upgrade"
    coordinator, project_file, receipt_id = _stale_recovery(workspace)

    def make_pre_upgrade(value: dict[str, Any]) -> Mapping[str, Any]:
        receipt = value["operation_receipts"][receipt_id]
        receipt["schema_id"] = "qcoder.current_loop.operation_receipt.v3"
        receipt["schema_version"] = 3
        active = value["coordinator"]["active_recovery"]
        active["schema_id"] = "qcoder.current_loop.recovery.v4"
        active["schema_version"] = 4
        return value

    state = coordinator.store.read()
    coordinator.store.update(
        make_pre_upgrade,
        expected_revision=int(state["state_revision"]),
    )
    old_loop_ref = str(coordinator.store.read()["loop_ref"])
    abandoned = coordinator.abandon(explicit_authority=True)
    assert abandoned["ok"] is True
    assert project_file.read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not coordinator.store.state_path.exists()

    replacement = CurrentLoopCoordinator(workspace_root=workspace)
    with pytest.raises(CurrentLoopError, match="current_loop_not_active"):
        replacement.store.read()
    restarted = replacement.activate(
        original_request="Restart this exact bounded build under qCoder 0.6.0a5.",
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    assert restarted["ok"] is True
    assert replacement.store.read()["loop_ref"] != old_loop_ref
    assert project_file.read_text(encoding="utf-8") == "VALUE = 1\n"

    root = Path(__file__).resolve().parents[1]
    readme = " ".join((root / "README.md").read_text(encoding="utf-8").split()).lower()
    changelog = " ".join((root / "CHANGELOG.md").read_text(encoding="utf-8").split()).lower()
    for text in (readme, changelog):
        assert "finish or restart an active qcoder loop before upgrading" in text
        assert "fails closed instead of silently reinterpreting old authority data" in text


def test_corrupt_base_loop_state_still_fails_closed_on_abandon(tmp_path: Path) -> None:
    coordinator = _active(tmp_path / "corrupt")
    raw = json.loads(coordinator.store.state_path.read_text(encoding="utf-8"))
    raw["workspace_root"] = "relative-corrupt-workspace"
    coordinator.store.state_path.write_text(json.dumps(raw), encoding="utf-8")

    rejected = coordinator.abandon(explicit_authority=True)
    assert rejected["ok"] is False
    assert coordinator.store.state_path.exists()
