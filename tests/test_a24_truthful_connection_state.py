from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Self

import pytest

import qcoder.context_bridge_connection as connection
from qcoder.context_bridge_mcp import EXPECTED_TOOLS, handle_jsonrpc_message
from qcoder.context_bridge_mcp import main as context_bridge_main
from qcoder.current_loop_binding_mcp import (
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)

PUBLIC_SERVER = "qcoder-context-bridge"
PRIVATE_SERVER = "qcoder-current-loop"
SETUP_GENERATION = "a" * 64
OTHER_GENERATION = "b" * 64
CLIENT = {"name": "cursor-vscode", "version": "1.7.0"}
OTHER_CLIENT = {"name": "claude-code", "version": "2.1.227"}
TOKEN = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


class _FakeResponse:
    status = 200

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "ok": True,
                "tool_name": "create_context_session_card",
                "context_status": "context_session_card_ready",
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }
        ).encode("utf-8")


def _state_root(workspace: Path) -> Path:
    return workspace / ".qcoder" / "context-bridge"


def _write_manifest(
    workspace: Path,
    *,
    setup_generation: str = SETUP_GENERATION,
    configured: bool = True,
) -> Path:
    connection.prepare_connection_state(
        workspace,
        client="cursor",
        configuration_verified=configured,
        credential_verified=configured,
        setup_generation=setup_generation,
    )
    return _state_root(workspace) / "connection-manifest.json"


def _session_digest(workspace: Path) -> str:
    value = json.loads(
        (_state_root(workspace) / "connection-manifest.json").read_text(encoding="utf-8")
    )
    return str(value["configured_client_session_sha256"])


def _token_file(workspace: Path) -> Path:
    path = workspace / "token.txt"
    if not path.exists():
        path.write_text(TOKEN, encoding="utf-8")
        path.chmod(0o600)
    return path


def _initialize_request(message_id: int, client: dict[str, str]) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": deepcopy(client),
        },
    }


def _list_request(message_id: int) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": message_id, "method": "tools/list", "params": {}}


def _read_only_request(
    message_id: int, artifact_text: str = "Share-safe connection check."
) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": "tools/call",
        "params": {
            "name": "create_context_session_card",
            "arguments": {"artifact_text": artifact_text, "client_context": "cursor"},
        },
    }


def _public_response(workspace: Path, request: dict, *, successful_call: bool = True) -> dict:
    opener = (lambda *_args, **_kwargs: _FakeResponse()) if successful_call else None
    response = handle_jsonrpc_message(
        request,
        base_url="https://example.invalid",
        token_file=_token_file(workspace),
        opener=opener,
    )
    assert isinstance(response, dict)
    return response


def _private_response(workspace: Path, request: dict) -> dict:
    response = handle_binding_jsonrpc_message(request, workspace_root=workspace)
    assert isinstance(response, dict)
    return response


def _record(
    workspace: Path,
    server_name: str,
    request: dict,
    response: dict,
    *,
    generation: str = SETUP_GENERATION,
    session_digest: str | None = None,
) -> None:
    connection.record_server_exchange(
        state_root=_state_root(workspace),
        setup_generation=generation,
        configured_client_session_sha256=session_digest or _session_digest(workspace),
        server_name=server_name,
        request=request,
        response=response,
    )


def _record_initialization(
    workspace: Path,
    server_name: str,
    *,
    client: dict[str, str] = CLIENT,
    generation: str = SETUP_GENERATION,
) -> None:
    request = _initialize_request(1, client)
    response = (
        _public_response(workspace, request)
        if server_name == PUBLIC_SERVER
        else _private_response(workspace, request)
    )
    _record(workspace, server_name, request, response, generation=generation)


def _record_inventory(
    workspace: Path,
    server_name: str,
    *,
    generation: str = SETUP_GENERATION,
    mutate_response=None,
) -> None:
    request = _list_request(2)
    response = (
        _public_response(workspace, request)
        if server_name == PUBLIC_SERVER
        else _private_response(workspace, request)
    )
    if mutate_response is not None:
        mutate_response(response)
    _record(workspace, server_name, request, response, generation=generation)


def _record_read_only_call(
    workspace: Path,
    *,
    generation: str = SETUP_GENERATION,
    request: dict | None = None,
    response: dict | None = None,
) -> None:
    actual_request = request or _read_only_request(3)
    actual_response = response or _public_response(workspace, actual_request)
    _record(
        workspace,
        PUBLIC_SERVER,
        actual_request,
        actual_response,
        generation=generation,
    )


def _record_complete_connection(
    workspace: Path,
    *,
    public_client: dict[str, str] = CLIENT,
    private_client: dict[str, str] = CLIENT,
    public_generation: str = SETUP_GENERATION,
    private_generation: str = SETUP_GENERATION,
    include_call: bool = True,
) -> None:
    _record_initialization(
        workspace, PUBLIC_SERVER, client=public_client, generation=public_generation
    )
    _record_initialization(
        workspace, PRIVATE_SERVER, client=private_client, generation=private_generation
    )
    _record_inventory(workspace, PUBLIC_SERVER, generation=public_generation)
    _record_inventory(workspace, PRIVATE_SERVER, generation=private_generation)
    if include_call:
        _record_read_only_call(workspace, generation=public_generation)


def _assert_not_qualified(status: dict) -> None:
    assert status["qualified"] is False
    assert status["client_qualification_created"] is False
    assert status["support_claim_created"] is False


def _assert_configured_not_connected(status: dict, category: str) -> None:
    assert status["ok"] is False
    assert status["configured"] is True
    assert status["connected"] is False
    assert status["customer_result"] == "qCoder configured"
    assert status["category"] == category
    assert status["client_connection_verified"] is False
    _assert_not_qualified(status)


def _receipt_paths(workspace: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for path in _state_root(workspace).rglob("*.json"):
        if path.name == "connection-manifest.json":
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        server_name = value.get("server_name") if isinstance(value, dict) else None
        if isinstance(server_name, str):
            paths[server_name] = path
    return paths


def test_missing_manifest_is_not_configured(tmp_path: Path) -> None:
    workspace = tmp_path / "unconfigured-workspace"
    workspace.mkdir()
    status = connection.connection_status(workspace_root=workspace)

    assert status["ok"] is False
    assert status["configured"] is False
    assert status["connected"] is False
    assert status["customer_result"] != "qCoder connected"
    assert status["category"] == "qcoder_not_configured"
    _assert_not_qualified(status)


def test_direct_server_readiness_and_exact_configuration_mean_configured_only(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)

    status = connection.connection_status(workspace_root=workspace)

    _assert_configured_not_connected(status, "client_mcp_initialization_not_observed")


def test_same_generation_same_client_exact_12_plus_2_and_read_only_call_connects(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)
    _record_complete_connection(workspace)

    status = connection.connection_status(workspace_root=workspace)

    assert status["ok"] is True
    assert status["configured"] is True
    assert status["connected"] is True
    assert status["customer_result"] == "qCoder connected"
    assert status["category"] == "connected"
    assert status["client_connection_verified"] is True
    assert status["public_server_initialized"] is True
    assert status["private_server_initialized"] is True
    assert status["public_tool_inventory_verified"] is True
    assert status["private_operation_inventory_verified"] is True
    assert status["read_only_qcoder_request_verified"] is True
    assert [item["name"] for item in binding_tool_descriptors()] == [
        "begin_current_loop",
        "complete_current_step",
    ]
    assert len(EXPECTED_TOOLS) == 12
    _assert_not_qualified(status)


@pytest.mark.parametrize("present_server", [PUBLIC_SERVER, PRIVATE_SERVER])
def test_one_server_initialization_never_connects(tmp_path: Path, present_server: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)
    _record_initialization(workspace, present_server)

    status = connection.connection_status(workspace_root=workspace)

    _assert_configured_not_connected(status, "client_mcp_initialization_not_observed")


def test_missing_public_inventory_never_connects(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)
    _record_initialization(workspace, PUBLIC_SERVER)
    _record_initialization(workspace, PRIVATE_SERVER)
    _record_inventory(workspace, PRIVATE_SERVER)

    status = connection.connection_status(workspace_root=workspace)

    _assert_configured_not_connected(status, "public_tool_inventory_not_verified")


def test_missing_private_inventory_never_connects(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)
    _record_initialization(workspace, PUBLIC_SERVER)
    _record_initialization(workspace, PRIVATE_SERVER)
    _record_inventory(workspace, PUBLIC_SERVER)

    status = connection.connection_status(workspace_root=workspace)

    _assert_configured_not_connected(status, "private_operation_inventory_not_verified")


@pytest.mark.parametrize("server_name", [PUBLIC_SERVER, PRIVATE_SERVER])
def test_mutated_inventory_count_never_connects(tmp_path: Path, server_name: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)
    _record_initialization(workspace, PUBLIC_SERVER)
    _record_initialization(workspace, PRIVATE_SERVER)

    def remove_last_tool(response: dict) -> None:
        response["result"]["tools"].pop()

    _record_inventory(
        workspace,
        PUBLIC_SERVER,
        mutate_response=remove_last_tool if server_name == PUBLIC_SERVER else None,
    )
    _record_inventory(
        workspace,
        PRIVATE_SERVER,
        mutate_response=remove_last_tool if server_name == PRIVATE_SERVER else None,
    )
    _record_read_only_call(workspace)

    status = connection.connection_status(workspace_root=workspace)

    category = (
        "public_tool_inventory_not_verified"
        if server_name == PUBLIC_SERVER
        else "private_operation_inventory_not_verified"
    )
    _assert_configured_not_connected(status, category)


def test_exact_initialization_and_inventories_without_qcoder_call_do_not_connect(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)
    _record_complete_connection(workspace, include_call=False)

    status = connection.connection_status(workspace_root=workspace)

    _assert_configured_not_connected(status, "read_only_qcoder_request_not_observed")


@pytest.mark.parametrize("failure", ["error", "retention", "retained_artifact"])
def test_failed_or_retaining_qcoder_call_does_not_connect(tmp_path: Path, failure: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)
    _record_complete_connection(workspace, include_call=False)
    request = _read_only_request(3)
    response = _public_response(workspace, request)
    structured = response["result"]["structuredContent"]
    if failure == "error":
        structured["ok"] = False
        response["result"]["isError"] = True
    elif failure == "retention":
        structured["retention"] = "retained"
    else:
        structured["retained_artifacts"] = ["unexpected"]
    _record_read_only_call(workspace, request=request, response=response)

    status = connection.connection_status(workspace_root=workspace)

    _assert_configured_not_connected(status, "qcoder_request_failed")


def test_receipts_from_different_setup_generations_do_not_combine(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)
    _record_complete_connection(
        workspace,
        public_generation=SETUP_GENERATION,
        private_generation=OTHER_GENERATION,
    )

    status = connection.connection_status(workspace_root=workspace)

    _assert_configured_not_connected(status, "connection_receipt_generation_mismatch")


def test_receipts_from_different_clients_do_not_combine(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)
    _record_complete_connection(workspace, public_client=CLIENT, private_client=OTHER_CLIENT)

    status = connection.connection_status(workspace_root=workspace)

    _assert_configured_not_connected(status, "connection_receipt_client_mismatch")


def test_malformed_receipt_fails_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)
    _record_complete_connection(workspace)
    receipts = _receipt_paths(workspace)
    assert set(receipts) == {PUBLIC_SERVER, PRIVATE_SERVER}
    receipts[PUBLIC_SERVER].write_text("{not-json", encoding="utf-8")

    status = connection.connection_status(workspace_root=workspace)

    _assert_configured_not_connected(status, "connection_receipt_invalid_or_stale")


def test_receipt_older_than_configuration_fails_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = _write_manifest(workspace)
    _record_complete_connection(workspace)
    receipts = _receipt_paths(workspace)
    stale = manifest.stat().st_mtime - 60
    os.utime(receipts[PUBLIC_SERVER], (stale, stale))

    status = connection.connection_status(workspace_root=workspace)

    _assert_configured_not_connected(status, "connection_receipt_invalid_or_stale")


def test_receipts_outside_one_observation_window_do_not_combine(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)
    _record_complete_connection(workspace)
    receipts = _receipt_paths(workspace)
    public_time = receipts[PUBLIC_SERVER].stat().st_mtime
    distant = public_time + 3_600
    os.utime(receipts[PRIVATE_SERVER], (distant, distant))

    status = connection.connection_status(workspace_root=workspace)

    _assert_configured_not_connected(status, "connection_observation_window_mismatch")


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        assert 0.0 < seconds <= 0.25
        self.sleeps.append(seconds)
        self.value += seconds


def test_missing_client_initialization_wait_is_strictly_bounded(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)
    clock = _Clock()

    status = connection.connection_status(
        workspace_root=workspace,
        wait_seconds=0.25,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )

    _assert_configured_not_connected(status, "client_mcp_initialization_not_observed")
    assert clock.sleeps
    assert sum(clock.sleeps) == pytest.approx(0.25)
    assert clock.value == pytest.approx(0.25)


def test_verify_connection_cli_returns_bounded_category_until_client_initializes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)

    assert (
        context_bridge_main(
            ["verify-connection", "--workspace", str(workspace), "--wait-seconds", "0"]
        )
        == 2
    )
    assert capsys.readouterr().out.splitlines() == [
        "qCoder configured",
        "Connection diagnostic: client_mcp_initialization_not_observed",
    ]


def test_verify_connection_cli_reports_connected_only_after_complete_proof(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)
    _record_complete_connection(workspace)

    assert context_bridge_main(["verify-connection", "--workspace", str(workspace), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["customer_result"] == "qCoder connected"
    assert result["client_connection_verified"] is True
    _assert_not_qualified(result)


def test_receipts_and_status_retain_no_raw_or_private_values(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_manifest(workspace)
    _record_complete_connection(workspace, include_call=False)
    sentinels = [
        "PRIVATE_TOKEN_SENTINEL_987654321",
        "/home/rob/private/customer/source.py",
        "RAW_CUSTOMER_PROMPT_SENTINEL",
    ]
    request = _read_only_request(3, " ".join(sentinels))
    response = _public_response(workspace, _read_only_request(3))
    response["unexpected_raw_echo"] = " ".join(sentinels)
    _record_read_only_call(workspace, request=request, response=response)

    status = connection.connection_status(workspace_root=workspace)
    serialized_files = "\n".join(
        path.read_text(encoding="utf-8") for path in _state_root(workspace).rglob("*.json")
    )
    serialized_status = json.dumps(status, sort_keys=True)

    for sentinel in sentinels:
        assert sentinel not in serialized_files
        assert sentinel not in serialized_status
    assert status["secret_included"] is False
    assert status["raw_request_retained"] is False
    assert status["raw_response_retained"] is False
    assert status["raw_client_stream_retained"] is False
    for path in _state_root(workspace).rglob("*.json"):
        assert path.is_file() and not path.is_symlink()
        assert path.stat().st_size <= 16_384
        if os.name != "nt":
            assert path.stat().st_mode & 0o077 == 0
