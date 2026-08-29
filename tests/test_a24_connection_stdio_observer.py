from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qcoder import context_bridge_mcp, current_loop_binding_mcp
from qcoder.context_bridge_connection import (
    PRIVATE_SERVER_NAME,
    PUBLIC_SERVER_NAME,
    connection_state_paths,
    connection_status,
    prepare_connection_state,
    record_server_exchange,
)

SETUP_GENERATION = "a" * 64
CLIENT_INFO = {"name": "cursor-vscode", "version": "1.7.0"}
TOKEN_SENTINEL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
REQUEST_SENTINEL = "PRIVATE_CUSTOMER_REQUEST_MUST_NOT_BE_RETAINED_43091"


def _initialize(message_id: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": dict(CLIENT_INFO),
        },
    }


def _tools_list(message_id: int) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "method": "tools/list", "params": {}}


def _public_call(message_id: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": "tools/call",
        "params": {
            "name": "get_guided_evidence_context",
            "arguments": {
                "artifact_text": REQUEST_SENTINEL,
                "artifact_kind": "share_safe_summary",
            },
        },
    }


def _write_token(path: Path) -> None:
    path.write_text(TOKEN_SENTINEL, encoding="utf-8")
    path.chmod(0o600)


def _successful_public_call(**kwargs: object) -> dict[str, object]:
    return {
        "ok": True,
        "tool_name": str(kwargs["tool_name"]),
        "context_status": "assistant_context_ready",
        "retention": "process_and_discard",
        "retained_artifacts": [],
    }


def _run_json_lines(
    monkeypatch,
    runner: Callable[..., int],
    requests: list[dict[str, Any]],
    **runner_kwargs: object,
) -> tuple[int, list[dict[str, Any]]]:
    input_bytes = "".join(json.dumps(value) + "\n" for value in requests).encode("utf-8")
    raw_input = io.BytesIO(input_bytes)
    raw_output = io.BytesIO()
    stdin = io.TextIOWrapper(raw_input, encoding="utf-8")
    stdout = io.TextIOWrapper(raw_output, encoding="utf-8", write_through=True)
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    result = runner(**runner_kwargs)
    stdout.flush()
    output = raw_output.getvalue().decode("utf-8")
    stdin.detach()
    stdout.detach()
    responses = [json.loads(line) for line in output.splitlines() if line.strip()]
    return result, responses


def _public_expected(requests: list[dict[str, Any]], *, token_file: Path) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    for request in requests:
        response = context_bridge_mcp.handle_jsonrpc_message(
            request,
            base_url="https://example.invalid",
            token_file=token_file,
        )
        assert isinstance(response, dict)
        responses.append(response)
    return responses


def _private_expected(
    requests: list[dict[str, Any]], *, workspace_root: Path
) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    for request in requests:
        response = current_loop_binding_mcp.handle_binding_jsonrpc_message(
            request,
            workspace_root=workspace_root,
        )
        assert isinstance(response, dict)
        responses.append(response)
    return responses


def test_stdio_loops_observe_real_12_plus_2_and_successful_public_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = prepare_connection_state(
        workspace,
        client="cursor",
        configuration_verified=True,
        credential_verified=True,
        setup_generation=SETUP_GENERATION,
    )
    state_root = connection_state_paths(workspace)[0].parent
    session_digest = str(manifest["configured_client_session_sha256"])
    token_file = tmp_path / "context-bridge-token.txt"
    _write_token(token_file)
    monkeypatch.setattr(context_bridge_mcp, "post_context_bridge", _successful_public_call)

    public_requests = [_initialize(1), _tools_list(2), _public_call(3)]
    public_expected = _public_expected(public_requests, token_file=token_file)
    public_rc, public_responses = _run_json_lines(
        monkeypatch,
        context_bridge_mcp.serve_mcp_stdio,
        public_requests,
        base_url="https://example.invalid",
        token_file=token_file,
        connection_state_root=state_root,
        connection_generation=SETUP_GENERATION,
        connection_session_sha256=session_digest,
    )

    private_requests = [_initialize(4), _tools_list(5)]
    private_expected = _private_expected(private_requests, workspace_root=workspace)
    private_rc, private_responses = _run_json_lines(
        monkeypatch,
        current_loop_binding_mcp.serve_binding_mcp_stdio,
        private_requests,
        workspace_root=workspace,
        connection_state_root=state_root,
        connection_generation=SETUP_GENERATION,
        connection_session_sha256=session_digest,
    )

    assert public_rc == private_rc == 0
    assert public_responses == public_expected
    assert private_responses == private_expected

    status = connection_status(workspace_root=workspace)
    assert manifest["configured"] is True
    assert status["ok"] is True
    assert status["connected"] is True
    assert status["category"] == "connected"
    assert status["public_tools_discovered"] == 12
    assert status["private_operations_discovered"] == 2
    assert status["read_only_qcoder_request_verified"] is True
    assert status["qualified"] is False
    assert status["client_qualification_created"] is False
    assert status["configured_client_session_bound"] is True
    assert status["observed_mcp_client_info_matched"] is True
    assert status["os_process_identity_established"] is False

    _, public_receipt_path, private_receipt_path = connection_state_paths(workspace)
    public_receipt = json.loads(public_receipt_path.read_text(encoding="utf-8"))
    private_receipt = json.loads(private_receipt_path.read_text(encoding="utf-8"))
    assert public_receipt["server_name"] == PUBLIC_SERVER_NAME
    assert public_receipt["initialized"] is True
    assert public_receipt["inventory_verified"] is True
    assert public_receipt["read_only_qcoder_request_verified"] is True
    assert private_receipt["server_name"] == PRIVATE_SERVER_NAME
    assert private_receipt["initialized"] is True
    assert private_receipt["inventory_verified"] is True
    assert private_receipt["read_only_qcoder_request_verified"] is False

    retained = "\n".join(
        path.read_text(encoding="utf-8") for path in connection_state_paths(workspace)
    )
    assert REQUEST_SENTINEL not in retained
    assert TOKEN_SENTINEL not in retained
    assert CLIENT_INFO["name"] not in retained
    assert CLIENT_INFO["version"] not in retained
    assert "artifact_text" not in retained
    assert 'raw_request_retained":false' in retained
    assert 'raw_response_retained":false' in retained
    assert 'raw_client_stream_retained":false' in retained


def test_observer_write_failure_never_changes_public_or_private_stdio_responses(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "unwritable-observer-state"
    token_file = tmp_path / "context-bridge-token.txt"
    _write_token(token_file)
    monkeypatch.setattr(context_bridge_mcp, "post_context_bridge", _successful_public_call)

    public_requests = [_initialize(10), _tools_list(11), _public_call(12)]
    private_requests = [_initialize(20), _tools_list(21)]
    public_expected = _public_expected(public_requests, token_file=token_file)
    private_expected = _private_expected(private_requests, workspace_root=workspace)

    def fail_observer(**_kwargs: object) -> bool:
        raise OSError("simulated observer write failure")

    monkeypatch.setattr(context_bridge_mcp, "record_server_exchange", fail_observer)
    public_rc, public_responses = _run_json_lines(
        monkeypatch,
        context_bridge_mcp.serve_mcp_stdio,
        public_requests,
        base_url="https://example.invalid",
        token_file=token_file,
        connection_state_root=state_root,
        connection_generation=SETUP_GENERATION,
        connection_session_sha256="b" * 64,
    )

    monkeypatch.setattr(current_loop_binding_mcp, "record_server_exchange", fail_observer)
    private_rc, private_responses = _run_json_lines(
        monkeypatch,
        current_loop_binding_mcp.serve_binding_mcp_stdio,
        private_requests,
        workspace_root=workspace,
        connection_state_root=state_root,
        connection_generation=SETUP_GENERATION,
        connection_session_sha256="b" * 64,
    )

    assert public_rc == private_rc == 0
    assert public_responses == public_expected
    assert private_responses == private_expected
    assert not state_root.exists()


def _initialize_response(server_name: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": server_name, "version": "0.6.0a24"},
        },
    }


def _inventory_response(names: tuple[str, ...]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {"tools": [{"name": name} for name in names]},
    }


def _public_success_response() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {
            "structuredContent": {
                "ok": True,
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }
        },
    }


def _record(
    *,
    workspace: Path,
    session_digest: str,
    server_name: str,
    request: dict[str, Any],
    response: dict[str, Any],
) -> bool:
    return record_server_exchange(
        state_root=connection_state_paths(workspace)[0].parent,
        setup_generation=SETUP_GENERATION,
        configured_client_session_sha256=session_digest,
        server_name=server_name,
        request=request,
        response=response,
    )


def _record_connected(workspace: Path) -> str:
    manifest = prepare_connection_state(
        workspace,
        client="cursor",
        configuration_verified=True,
        credential_verified=True,
        setup_generation=SETUP_GENERATION,
    )
    session_digest = str(manifest["configured_client_session_sha256"])
    assert _record(
        workspace=workspace,
        session_digest=session_digest,
        server_name=PUBLIC_SERVER_NAME,
        request=_initialize(1),
        response=_initialize_response(PUBLIC_SERVER_NAME),
    )
    assert _record(
        workspace=workspace,
        session_digest=session_digest,
        server_name=PUBLIC_SERVER_NAME,
        request=_tools_list(2),
        response=_inventory_response(tuple(context_bridge_mcp.EXPECTED_TOOLS)),
    )
    assert _record(
        workspace=workspace,
        session_digest=session_digest,
        server_name=PUBLIC_SERVER_NAME,
        request=_public_call(3),
        response=_public_success_response(),
    )
    assert _record(
        workspace=workspace,
        session_digest=session_digest,
        server_name=PRIVATE_SERVER_NAME,
        request=_initialize(4),
        response=_initialize_response(PRIVATE_SERVER_NAME),
    )
    assert _record(
        workspace=workspace,
        session_digest=session_digest,
        server_name=PRIVATE_SERVER_NAME,
        request=_tools_list(5),
        response=_inventory_response(("begin_current_loop", "complete_current_step")),
    )
    assert connection_status(workspace_root=workspace)["connected"] is True
    return session_digest


def _write_state(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)


def test_malformed_manifest_and_receipts_are_bounded_not_connected(tmp_path: Path) -> None:
    manifest_workspace = tmp_path / "manifest-workspace"
    manifest_workspace.mkdir()
    prepare_connection_state(
        manifest_workspace,
        client="cursor",
        configuration_verified=True,
        credential_verified=True,
        setup_generation=SETUP_GENERATION,
    )
    manifest_path = connection_state_paths(manifest_workspace)[0]
    original_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_mutations = [
        {**original_manifest, "schema_version": True},
        {**original_manifest, "setup_generation": [SETUP_GENERATION]},
        {**original_manifest, "configured_client_session_sha256": 7},
        {**original_manifest, "public_tool_count": "12"},
        {**original_manifest, "unexpected": False},
    ]
    for mutation in manifest_mutations:
        _write_state(manifest_path, mutation)
        status = connection_status(workspace_root=manifest_workspace)
        assert status["connected"] is False
        assert status["category"] == "qcoder_not_configured"

    manifest_path.write_text('{"schema_id":"x","schema_id":"y"}', encoding="utf-8")
    manifest_path.chmod(0o600)
    duplicate_status = connection_status(workspace_root=manifest_workspace)
    assert duplicate_status["connected"] is False
    assert duplicate_status["category"] == "qcoder_not_configured"

    receipt_workspace = tmp_path / "receipt-workspace"
    receipt_workspace.mkdir()
    _record_connected(receipt_workspace)
    _, public_path, _ = connection_state_paths(receipt_workspace)
    original_receipt = json.loads(public_path.read_text(encoding="utf-8"))
    receipt_mutations = [
        {**original_receipt, "event_sequence": "3"},
        {**original_receipt, "inventory_count": True},
        {**original_receipt, "inventory_count": 11},
        {**original_receipt, "inventory_sha256": "0" * 64},
        {**original_receipt, "initialized": 1},
        {**original_receipt, "unexpected": False},
    ]
    for mutation in receipt_mutations:
        _write_state(public_path, mutation)
        status = connection_status(workspace_root=receipt_workspace)
        assert status["configured"] is True
        assert status["connected"] is False
        assert status["category"] == "connection_receipt_invalid_or_stale"

    _write_state(public_path, original_receipt)
    public_path.chmod(0o640)
    mode_status = connection_status(workspace_root=receipt_workspace)
    assert mode_status["connected"] is False
    assert mode_status["category"] == "connection_receipt_invalid_or_stale"


def test_configured_session_and_observed_protocol_identity_are_both_required(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = prepare_connection_state(
        workspace,
        client="cursor",
        configuration_verified=True,
        credential_verified=True,
        setup_generation=SETUP_GENERATION,
    )
    session_digest = str(manifest["configured_client_session_sha256"])
    other_session_digest = "f" * 64
    assert other_session_digest != session_digest
    assert _record(
        workspace=workspace,
        session_digest=session_digest,
        server_name=PUBLIC_SERVER_NAME,
        request=_initialize(1),
        response=_initialize_response(PUBLIC_SERVER_NAME),
    )
    assert _record(
        workspace=workspace,
        session_digest=other_session_digest,
        server_name=PRIVATE_SERVER_NAME,
        request=_initialize(2),
        response=_initialize_response(PRIVATE_SERVER_NAME),
    )
    status = connection_status(workspace_root=workspace)
    assert status["connected"] is False
    assert status["category"] == "connection_receipt_session_mismatch"
    assert status["os_process_identity_established"] is False

    workspace_two = tmp_path / "workspace-two"
    workspace_two.mkdir()
    manifest_two = prepare_connection_state(
        workspace_two,
        client="cursor",
        configuration_verified=True,
        credential_verified=True,
        setup_generation=SETUP_GENERATION,
    )
    session_two = str(manifest_two["configured_client_session_sha256"])
    assert _record(
        workspace=workspace_two,
        session_digest=session_two,
        server_name=PUBLIC_SERVER_NAME,
        request=_initialize(3),
        response=_initialize_response(PUBLIC_SERVER_NAME),
    )
    mismatched_initialize = _initialize(4)
    mismatched_initialize["params"]["clientInfo"] = {
        "name": "different-client",
        "version": "9.9",
    }
    assert _record(
        workspace=workspace_two,
        session_digest=session_two,
        server_name=PRIVATE_SERVER_NAME,
        request=mismatched_initialize,
        response=_initialize_response(PRIVATE_SERVER_NAME),
    )
    mismatch = connection_status(workspace_root=workspace_two)
    assert mismatch["connected"] is False
    assert mismatch["configured_client_session_bound"] is True
    assert mismatch["category"] == "connection_receipt_client_mismatch"


def test_success_observations_are_monotonic_and_failed_first_attempts_recover(
    tmp_path: Path,
) -> None:
    connected_workspace = tmp_path / "connected"
    connected_workspace.mkdir()
    session_digest = _record_connected(connected_workspace)
    _, public_path, private_path = connection_state_paths(connected_workspace)
    public_before = public_path.read_bytes()
    private_before = private_path.read_bytes()
    failed_response = {"jsonrpc": "2.0", "id": 9, "error": {"code": -1}}
    assert not _record(
        workspace=connected_workspace,
        session_digest=session_digest,
        server_name=PUBLIC_SERVER_NAME,
        request=_tools_list(8),
        response=_inventory_response(()),
    )
    assert not _record(
        workspace=connected_workspace,
        session_digest=session_digest,
        server_name=PUBLIC_SERVER_NAME,
        request=_public_call(9),
        response=failed_response,
    )
    assert not _record(
        workspace=connected_workspace,
        session_digest=session_digest,
        server_name=PRIVATE_SERVER_NAME,
        request=_tools_list(10),
        response=_inventory_response(()),
    )
    assert public_path.read_bytes() == public_before
    assert private_path.read_bytes() == private_before
    assert connection_status(workspace_root=connected_workspace)["connected"] is True

    recovery_workspace = tmp_path / "recovery"
    recovery_workspace.mkdir()
    recovery_manifest = prepare_connection_state(
        recovery_workspace,
        client="cursor",
        configuration_verified=True,
        credential_verified=True,
        setup_generation=SETUP_GENERATION,
    )
    recovery_session = str(recovery_manifest["configured_client_session_sha256"])
    assert _record(
        workspace=recovery_workspace,
        session_digest=recovery_session,
        server_name=PUBLIC_SERVER_NAME,
        request=_initialize(11),
        response=_initialize_response(PUBLIC_SERVER_NAME),
    )
    assert _record(
        workspace=recovery_workspace,
        session_digest=recovery_session,
        server_name=PUBLIC_SERVER_NAME,
        request=_tools_list(12),
        response=_inventory_response(()),
    )
    assert _record(
        workspace=recovery_workspace,
        session_digest=recovery_session,
        server_name=PUBLIC_SERVER_NAME,
        request=_tools_list(13),
        response=_inventory_response(tuple(context_bridge_mcp.EXPECTED_TOOLS)),
    )
    assert _record(
        workspace=recovery_workspace,
        session_digest=recovery_session,
        server_name=PUBLIC_SERVER_NAME,
        request=_public_call(14),
        response=failed_response,
    )
    assert _record(
        workspace=recovery_workspace,
        session_digest=recovery_session,
        server_name=PUBLIC_SERVER_NAME,
        request=_public_call(15),
        response=_public_success_response(),
    )
    assert _record(
        workspace=recovery_workspace,
        session_digest=recovery_session,
        server_name=PRIVATE_SERVER_NAME,
        request=_initialize(16),
        response=_initialize_response(PRIVATE_SERVER_NAME),
    )
    assert _record(
        workspace=recovery_workspace,
        session_digest=recovery_session,
        server_name=PRIVATE_SERVER_NAME,
        request=_tools_list(17),
        response=_inventory_response(()),
    )
    assert _record(
        workspace=recovery_workspace,
        session_digest=recovery_session,
        server_name=PRIVATE_SERVER_NAME,
        request=_tools_list(18),
        response=_inventory_response(("begin_current_loop", "complete_current_step")),
    )
    recovered = connection_status(workspace_root=recovery_workspace)
    assert recovered["connected"] is True
    assert recovered["public_tools_discovered"] == 12
    assert recovered["private_operations_discovered"] == 2
