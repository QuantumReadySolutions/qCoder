from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from qcoder.algorithm_blueprint import with_artifact_digest
from qcoder.cli import main as cli_main
from qcoder.context_bridge_connection import connection_status
from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    CLIENT_BINDING_SCHEMA_VERSION,
    EXPECTED_TOOLS,
    _client_visible_tool_payload,
    build_client_activation_instructions,
    build_client_binding_descriptor,
    first_value_dialogue_contract_snapshot,
)
from qcoder.context_bridge_profiles import (
    CredentialProfileError,
    CredentialProfileManager,
    HardenedFileSecretStore,
)
from qcoder.context_bridge_setup import (
    ContextBridgeSetupError,
    configure_cursor_workspace,
    setup_contract_snapshot,
)
from qcoder.current_loop_binding_mcp import binding_tool_descriptors

TOKEN = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


class MemoryStore:
    kind = "test_protected"

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def available(self) -> bool:
        return True

    def put(self, profile_id: str, secret: str) -> None:
        if profile_id in self.values:
            raise CredentialProfileError("profile_secret_already_exists")
        self.values[profile_id] = secret

    def get(self, profile_id: str) -> str:
        try:
            return self.values[profile_id]
        except KeyError as exc:
            raise CredentialProfileError("selected_profile_secret_missing") from exc

    def delete(self, profile_id: str) -> None:
        self.values.pop(profile_id, None)


def _manager(tmp_path: Path) -> CredentialProfileManager:
    return CredentialProfileManager(
        registry_file=tmp_path / "profiles" / "profiles.json",
        legacy_token_file=tmp_path / "profiles" / "token.txt",
        protected_store=MemoryStore(),
        fallback_store=HardenedFileSecretStore(tmp_path / "profiles" / "secrets"),
        profile_id_factory=lambda: "qcp-000000000000000000000001",
    )


def _profile(manager: CredentialProfileManager, *, workspace_context: str) -> dict[str, object]:
    return manager.create_profile(
        label="Lenovo Cursor profile",
        credential_reference="cbcred-lenovo-cursor-profile",
        account_label="Explorer account",
        client_label="Cursor",
        device_label="Lenovo",
        workspace_label="Clinic workspace",
        client_selector="cursor",
        workspace_selector=workspace_context,
        secret=TOKEN,
        validator=lambda value: value == TOKEN,
    )


def _smoke(**_: object) -> dict[str, object]:
    return {
        "ok": True,
        "tools_exact": True,
        "tools_visible": list(EXPECTED_TOOLS),
        "tools_discovered": 12,
        "server_preflight_status_category": "ready",
    }


def test_one_managed_setup_configures_existing_12_plus_2_without_claiming_connection(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _manager(tmp_path)
    created = _profile(manager, workspace_context="clinic-workspace")

    result = configure_cursor_workspace(
        workspace_root=workspace,
        client_context="cursor",
        workspace_context="clinic-workspace",
        executable="/synthetic/python",
        manager=manager,
        smoke_runner=_smoke,
    )

    assert result["schema_id"] == "qcoder.customer_managed_configuration.v2"
    assert result["schema_version"] == 2
    assert result["customer_result"] == "qCoder configured"
    assert result["configured"] is True
    assert result["connected"] is False
    assert result["qualified"] is False
    assert result["configuration_verified"] is True
    assert result["credential_verified"] is True
    assert result["client_connection_verified"] is False
    assert result["direct_server_smoke_verified"] is True
    assert result["direct_server_smoke_establishes_client_connection"] is False
    assert result["public_tool_count"] == 12
    assert result["private_operations"] == ["begin_current_loop", "complete_current_step"]
    assert result["profile"]["profile_id"] == created["profile_id"]
    assert result["secret_included"] is False
    config = json.loads((workspace / ".cursor/mcp.json").read_text())
    assert set(config["mcpServers"]) == {"qcoder-context-bridge", "qcoder-current-loop"}
    public_args = config["mcpServers"]["qcoder-context-bridge"]["args"]
    private_args = config["mcpServers"]["qcoder-current-loop"]["args"]
    assert public_args[public_args.index("--profile") + 1] == created["profile_id"]
    assert public_args[public_args.index("--workspace-context") + 1] == "clinic-workspace"
    manifest_path = workspace / ".qcoder/context-bridge/connection-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    generation = manifest["setup_generation"]
    session_digest = manifest["configured_client_session_sha256"]
    state_root = str(manifest_path.parent)
    assert public_args[public_args.index("--connection-state-root") + 1] == state_root
    assert public_args[public_args.index("--connection-generation") + 1] == generation
    assert public_args[public_args.index("--connection-session-sha256") + 1] == session_digest
    assert private_args[private_args.index("--connection-state-root") + 1] == state_root
    assert private_args[private_args.index("--connection-generation") + 1] == generation
    assert private_args[private_args.index("--connection-session-sha256") + 1] == session_digest
    assert len(session_digest) == 64
    assert result["configured_client_session_sha256"] == session_digest
    assert result["os_process_identity_established"] is False
    configured_status = connection_status(workspace_root=workspace)
    assert configured_status["customer_result"] == "qCoder configured"
    assert configured_status["category"] == "client_mcp_initialization_not_observed"
    assert TOKEN not in json.dumps(config, sort_keys=True)
    assert len(EXPECTED_TOOLS) == 12
    assert [item["name"] for item in binding_tool_descriptors()] == [
        "begin_current_loop",
        "complete_current_step",
    ]


def test_explicit_profile_is_pinned_and_unrelated_client_entries_are_preserved(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    cursor = workspace / ".cursor"
    cursor.mkdir(parents=True)
    unrelated = {"command": "unrelated", "args": ["serve"]}
    (cursor / "mcp.json").write_text(
        json.dumps({"mcpServers": {"unrelated-server": unrelated}}), encoding="utf-8"
    )
    (cursor / "hooks.json").write_text(
        json.dumps({"version": 1, "hooks": {"afterFileEdit": [{"command": "unrelated"}]}}),
        encoding="utf-8",
    )
    manager = _manager(tmp_path)
    created = _profile(manager, workspace_context="different-binding")

    result = configure_cursor_workspace(
        workspace_root=workspace,
        profile=str(created["profile_id"]),
        client_context="cursor",
        workspace_context="clinic-workspace",
        executable="/synthetic/python",
        manager=manager,
        smoke_runner=_smoke,
    )

    assert result["profile"]["selection_source"] == "explicit_invocation"
    config = json.loads((cursor / "mcp.json").read_text())
    assert config["mcpServers"]["unrelated-server"] == unrelated
    hooks = json.loads((cursor / "hooks.json").read_text())
    assert {"command": "unrelated"} in hooks["hooks"]["afterFileEdit"]


def test_conflict_and_verification_failure_restore_exact_prior_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    cursor = workspace / ".cursor"
    cursor.mkdir(parents=True)
    manager = _manager(tmp_path)
    created = _profile(manager, workspace_context="clinic-workspace")
    conflicting = {"mcpServers": {"qcoder-context-bridge": {"command": "different", "args": []}}}
    mcp_path = cursor / "mcp.json"
    mcp_path.write_text(json.dumps(conflicting), encoding="utf-8")
    before = mcp_path.read_bytes()
    with pytest.raises(ContextBridgeSetupError, match="context_bridge_mcp_name_conflict"):
        configure_cursor_workspace(
            workspace_root=workspace,
            profile=str(created["profile_id"]),
            manager=manager,
            smoke_runner=_smoke,
        )
    assert mcp_path.read_bytes() == before
    assert not (cursor / "hooks.json").exists()
    assert not (workspace / ".qcoder/context-bridge/connection-manifest.json").exists()

    mcp_path.unlink()
    (cursor / "hooks.json").write_text(
        json.dumps({"version": 1, "hooks": {"afterFileEdit": []}}), encoding="utf-8"
    )
    hook_before = (cursor / "hooks.json").read_bytes()
    monkeypatch.setattr(
        "qcoder.context_bridge_setup.cursor_post_write_hook_status",
        lambda **_: {"configured": False},
    )
    with pytest.raises(ContextBridgeSetupError, match="client_configuration_verification_failed"):
        configure_cursor_workspace(
            workspace_root=workspace,
            profile=str(created["profile_id"]),
            manager=manager,
            smoke_runner=_smoke,
        )
    assert not mcp_path.exists()
    assert (cursor / "hooks.json").read_bytes() == hook_before
    assert not (workspace / ".qcoder/context-bridge/connection-manifest.json").exists()


def test_cli_customer_result_is_exact_and_diagnostics_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bounded = {
        "schema_id": "qcoder.customer_managed_configuration.v2",
        "schema_version": 2,
        "ok": True,
        "customer_result": "qCoder configured",
        "configured": True,
        "connected": False,
        "qualified": False,
        "client_connection_verified": False,
        "public_tool_count": 12,
        "private_operation_count": 2,
        "secret_included": False,
    }
    monkeypatch.setattr(
        "qcoder.context_bridge_setup.configure_cursor_workspace", lambda **_: deepcopy(bounded)
    )
    assert cli_main(["context-bridge", "setup", "--workspace", str(workspace)]) == 0
    assert capsys.readouterr().out == "qCoder configured\n"
    assert cli_main(["context-bridge", "setup", "--workspace", str(workspace), "--json"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == bounded
    assert TOKEN not in output


def _unconfirmed_card() -> dict[str, object]:
    return with_artifact_digest(
        {
            "artifact_type": "algorithm_intent_card",
            "schema_version": 1,
            "original_user_intent": "Review a Bell implementation before source generation.",
            "profile": {"id": "generic_qiskit"},
            "interpretation": {
                "normalized_goal": "Prepare one two-qubit Bell example.",
                "problem_size_meaning": "Two logical qubits.",
                "framework_requirement": "Qiskit-compatible Python.",
                "measurement_plan": "Measure both logical qubits.",
                "execution_intent": "Customer-controlled local execution.",
                "desired_output": "Python source and QASM evidence.",
                "backend_choice": "Customer-selected local backend.",
            },
            "unresolved_questions": ["backend_choice"],
            "requirements": [],
            "implementation_constraints": [],
            "explicit_non_goals": [],
            "user_accepted_unresolved_choices": [],
            "confirmation_state": "needs_clarification",
            "retention": "process_and_discard",
        }
    )


def test_blueprint_first_value_is_recommendation_first_three_groups_and_explicit() -> None:
    result = _client_visible_tool_payload(
        "create_algorithm_intent_card",
        {
            "ok": True,
            "context_status": "algorithm_intent_card_ready",
            "algorithm_intent_card": _unconfirmed_card(),
            "retention": "process_and_discard",
            "retained_artifacts": [],
        },
    )
    dialogue = result["first_value_dialogue"]
    assert dialogue["customer_actions"] == [
        "Use recommended choices",
        "Review or change choices",
    ]
    assert dialogue["initial_decision_group_count"] == 3
    assert len(dialogue["initial_decision_groups"]) <= 3
    assert dialogue["progressive_disclosure"] == {
        "available": True,
        "revealed_by": "Review or change choices",
        "remaining_field_ids": ["backend_choice"],
    }
    assert dialogue["explicit_confirmation_required_before_source_generation"] is True
    assert dialogue["automatic_confirmation"] is False
    assert dialogue["routine_procedural_narration"] is False


def test_blueprint_first_value_contract_is_bound_into_v48_descriptor() -> None:
    contract = first_value_dialogue_contract_snapshot()
    assert contract["initial_decision_group_maximum"] == 3
    assert contract["customer_actions"] == [
        "Use recommended choices",
        "Review or change choices",
    ]
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v55"
    assert CLIENT_BINDING_SCHEMA_VERSION == 54
    descriptor = build_client_binding_descriptor(coordinator_prefix=["/runtime/python"])[
        "client_binding_contract"
    ]
    assert descriptor["blueprint_first_value_dialogue_contract"] == contract
    setup = descriptor["customer_managed_connection_contract"]
    assert setup == setup_contract_snapshot()
    assert setup["schema_id"] == "qcoder.customer_managed_configuration.v2"
    assert setup["schema_version"] == 2
    assert setup["customer_result"] == "qCoder configured"
    assert setup["configured"] is True
    assert setup["connected"] is False
    assert setup["qualified"] is False
    assert setup["client_connection_verified"] is False
    assert setup["direct_server_smoke_establishes_client_connection"] is False
    assert setup["public_tool_count"] == 12
    assert setup["private_operations"] == ["begin_current_loop", "complete_current_step"]
    assert setup["server_consolidation"] is False


def test_activation_instructions_make_first_value_contract_direct_and_quiet(tmp_path: Path) -> None:
    selected = _manager(tmp_path)
    created = _profile(selected, workspace_context="clinic-workspace")
    credential = selected.select(explicit_profile=str(created["profile_id"]))
    instructions = build_client_activation_instructions(
        base_url="https://example.invalid",
        token_file=credential,
        python_executable="/synthetic/python",
    )
    normalized = " ".join(instructions.split())
    assert "Use recommended choices" in normalized
    assert "Review or change choices" in normalized
    assert "no more than its three initial decision groups" in normalized
    assert "never confirm automatically" in normalized
    assert "choreography" in normalized
    assert TOKEN not in instructions
