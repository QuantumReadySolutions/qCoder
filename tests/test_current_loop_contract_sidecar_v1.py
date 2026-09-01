from __future__ import annotations

import http.client
import json
from pathlib import Path
import socket

from qcoder.current_loop_contract_sidecar import (
    SIDECAR_CAPABILITY_HEADER,
    SIDECAR_SCHEMA_ID,
    SIDECAR_SESSION_HEADER,
    SidecarSession,
    _sanitized_environment,
    sidecar_contract_snapshot,
    start_in_process_sidecar,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    EXPECTED_TOOLS,
    build_client_activation_instructions,
    build_client_binding_descriptor,
)
from qcoder.current_loop_invocation import operation_transport_inventory
from tests.current_loop_test_support import activate_reviewed_legacy_fixture


def _active(workspace: Path) -> CurrentLoopCoordinator:
    coordinator = CurrentLoopCoordinator(workspace_root=workspace)
    activated = activate_reviewed_legacy_fixture(
        coordinator,
        original_request="Use qCoder for this exact local editor security proof.",
    )
    assert activated["ok"] is True
    return coordinator


def _request(
    port: int,
    method: str,
    path: str,
    *,
    session: SidecarSession,
    body: dict | None = None,
    capability: str | None = None,
    host: str | None = None,
    origin: str | None = None,
    fetch_site: str | None = "same-origin",
) -> tuple[int, dict | str, dict[str, str]]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    headers = {
        "Host": host or f"127.0.0.1:{port}",
        SIDECAR_CAPABILITY_HEADER: (session.capability if capability is None else capability),
        SIDECAR_SESSION_HEADER: session.session_id,
    }
    if origin is not None:
        headers["Origin"] = origin
    if fetch_site is not None:
        headers["Sec-Fetch-Site"] = fetch_site
    payload = None
    if body is not None:
        payload = json.dumps(body)
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    response_headers = {key.lower(): value for key, value in response.getheaders()}
    if response_headers.get("content-type", "").startswith("application/json"):
        value: dict | str = json.loads(raw.decode("utf-8"))
    else:
        value = raw.decode("utf-8")
    connection.close()
    return response.status, value, response_headers


def _raw_action_request(
    port: int,
    *,
    session: SidecarSession,
    body: bytes,
    content_type: str,
) -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request(
        "POST",
        "/api/action",
        body=body,
        headers={
            "Host": f"127.0.0.1:{port}",
            SIDECAR_CAPABILITY_HEADER: session.capability,
            SIDECAR_SESSION_HEADER: session.session_id,
            "Origin": f"http://127.0.0.1:{port}",
            "Sec-Fetch-Site": "same-origin",
            "Content-Type": content_type,
        },
    )
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, payload


def test_sidecar_contract_is_loopback_capability_bound_and_local_only() -> None:
    contract = sidecar_contract_snapshot()
    assert contract["schema_id"] == SIDECAR_SCHEMA_ID
    assert contract["network_binding"] == "127.0.0.1"
    assert contract["port"] == "random_ephemeral"
    assert contract["capability"]["minimum_entropy_bits"] >= 256
    assert contract["capability"]["delivery"] == "url_fragment"
    assert contract["capability"]["query_or_path"] is False
    assert contract["capability"]["cookies"] is False
    assert contract["capability"]["web_storage"] is False
    assert contract["protected_operation_endpoint"] is False
    assert contract["hosted_operation_endpoint"] is False
    assert contract["project_edit_endpoint"] is False
    assert contract["workspace_discovery"] is False
    environment = _sanitized_environment()
    assert not any("TOKEN" in key or "CREDENTIAL" in key for key in environment)
    assert "QCODER_BASE_URL" not in environment


def test_binding_v10_delivers_sidecar_run_summary_and_evidence_domains(
    tmp_path: Path,
) -> None:
    descriptor = build_client_binding_descriptor(
        coordinator_prefix=["/runtime/python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    assert descriptor["contract_id"] == CLIENT_BINDING_CONTRACT_ID
    assert descriptor["contract_id"].endswith(".v52")
    assert descriptor["contract_sidecar"]["schema_id"] == SIDECAR_SCHEMA_ID
    assert descriptor["run_summary_contract"]["schema_id"] == ("qcoder.current_loop.run_summary.v2")
    assert descriptor["evidence_view_contract"]["schema_id"] == (
        "qcoder.current_loop.evidence_view.v1"
    )
    assert descriptor["browser_editor_optional"] is True
    assert descriptor["browser_invokes_protected"] is False
    assert len(EXPECTED_TOOLS) == 12
    rows = {row["operation"]: row for row in operation_transport_inventory()["operations"]}
    assert rows["open_contract_editor"]["transport"] == "local_only"
    assert rows["evidence_view"]["transport"] == "local_only"
    instructions = build_client_activation_instructions(
        base_url="https://preview.example.invalid",
        token_file=tmp_path / "token.txt",
        python_executable=tmp_path / "python",
    ).lower()
    assert 'specialized_contracts_inline": false' in instructions
    assert "contract_sidecar" in instructions
    assert "contract_management" in instructions
    assert "fail closed" in instructions


def test_sidecar_headers_capability_origin_and_cas(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    server, session, thread = start_in_process_sidecar(
        workspace=tmp_path,
        coordinator=coordinator,
        idle_timeout_seconds=60,
    )
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert server.server_port > 0
        assert len(session.capability) >= 43
        port = server.server_port
        status, html, headers = _request(port, "GET", "/", session=session, fetch_site=None)
        assert status == 200
        assert isinstance(html, str)
        assert session.capability not in html
        assert "localStorage" not in html
        assert headers["content-security-policy"].startswith("default-src 'none'")
        assert "frame-ancestors 'none'" in headers["content-security-policy"]
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["cache-control"] == "no-store"
        assert headers["cross-origin-resource-policy"] == "same-origin"
        assert "payment=()" in headers["permissions-policy"]
        assert "access-control-allow-origin" not in headers

        status, snapshot, _headers = _request(port, "GET", "/api/snapshot", session=session)
        assert status == 200
        assert isinstance(snapshot, dict)
        assert snapshot["raw_project_content_included"] is False
        assert snapshot["credential_content_included"] is False
        assert len(snapshot["selection_graph"]) == 8

        wrong, body, _headers = _request(
            port,
            "GET",
            "/api/snapshot",
            session=session,
            capability="incorrect",
        )
        assert wrong == 403
        assert isinstance(body, dict)
        assert body["error_category"] == "sidecar_capability_invalid"

        wrong_host, _, _ = _request(
            port,
            "GET",
            "/api/snapshot",
            session=session,
            host="evil.invalid",
        )
        assert wrong_host == 403

        state = coordinator.store.read()
        revision = state["current_loop_contract"]["contract_revision"]
        status, result, _ = _request(
            port,
            "POST",
            "/api/action",
            session=session,
            origin=f"http://127.0.0.1:{port}",
            body={
                "action": "set_preset",
                "payload": {"preset": "evidence_only"},
                "expected_contract_revision": revision,
            },
        )
        assert status == 200
        assert isinstance(result, dict)
        assert result["hosted_operation_invoked"] is False
        assert result["protected_operation_invoked"] is False
        assert (
            coordinator.contract_status()["details"]["current_loop_contract"]["effective_preset"]
            == "evidence_only"
        )

        stale, body, _ = _request(
            port,
            "POST",
            "/api/action",
            session=session,
            origin=f"http://127.0.0.1:{port}",
            body={
                "action": "set_preset",
                "payload": {"preset": "assist"},
                "expected_contract_revision": revision,
            },
        )
        assert stale == 400
        assert isinstance(body, dict)
        assert body["error_category"] == "sidecar_contract_revision_stale"

        cross_site, _, _ = _request(
            port,
            "POST",
            "/api/action",
            session=session,
            origin="https://evil.invalid",
            fetch_site="cross-site",
            body={
                "action": "set_preset",
                "payload": {"preset": "assist"},
                "expected_contract_revision": revision + 1,
            },
        )
        assert cross_site == 403
    finally:
        session.closed = True
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_sidecar_json_editor_rejects_unsafe_transport_before_action(
    tmp_path: Path,
) -> None:
    coordinator = _active(tmp_path)
    server, session, thread = start_in_process_sidecar(
        workspace=tmp_path,
        coordinator=coordinator,
        idle_timeout_seconds=60,
    )
    try:
        port = server.server_port
        state_revision = coordinator.store.read()["state_revision"]
        revision = coordinator.store.read()["current_loop_contract"]["contract_revision"]
        revision_bytes = str(revision).encode("ascii")
        cases = (
            (
                b'{"action":"evidence_view","payload":{},'
                b'"expected_contract_revision":' + revision_bytes + b"}",
                "text/plain",
                415,
                "sidecar_content_type_invalid",
            ),
            (
                b'{"action":"evidence_view","action":"stop_loop","payload":{},'
                b'"expected_contract_revision":' + revision_bytes + b"}",
                "application/json",
                400,
                "sidecar_request_duplicate_key",
            ),
            (
                b'{"action":"evidence_view","payload":{"__proto__":{}},'
                b'"expected_contract_revision":' + revision_bytes + b"}",
                "application/json",
                400,
                "sidecar_request_unsafe_key",
            ),
        )
        for body, content_type, expected_status, expected_category in cases:
            status, payload = _raw_action_request(
                port,
                session=session,
                body=body,
                content_type=content_type,
            )
            assert status == expected_status
            assert payload["error_category"] == expected_category
            assert payload["raw_content_echoed"] is False
        assert coordinator.store.read()["state_revision"] == state_revision
    finally:
        session.closed = True
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_two_loop_and_workspace_isolation_and_reopen(tmp_path: Path) -> None:
    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    first_workspace.mkdir()
    second_workspace.mkdir()
    first = _active(first_workspace)
    second = _active(second_workspace)
    first_session = SidecarSession(workspace=first_workspace, coordinator=first)
    second_session = SidecarSession(workspace=second_workspace, coordinator=second)
    assert first_session.capability != second_session.capability
    assert first_session.session_id != second_session.session_id
    assert first_session.loop_ref != second_session.loop_ref
    reopened = SidecarSession(workspace=first_workspace, coordinator=first)
    assert reopened.capability != first_session.capability
    assert reopened.session_id != first_session.session_id
    assert socket.AF_INET


def test_loop_close_and_idle_expiry_terminate_session(tmp_path: Path) -> None:
    coordinator = _active(tmp_path)
    values = iter((0.0, 31.0, 31.0))
    session = SidecarSession(
        workspace=tmp_path,
        coordinator=coordinator,
        idle_timeout_seconds=30,
        clock=lambda: next(values),
    )
    assert session.expired() is True

    live = SidecarSession(workspace=tmp_path, coordinator=coordinator)
    stopped = coordinator.abandon(explicit_authority=True)
    assert stopped["ok"] is True
    try:
        live.validate_live_binding()
    except ValueError as exc:
        assert str(exc) == "sidecar_loop_closed"
    else:
        raise AssertionError("closed loop kept sidecar live")


def test_sidecar_coordinator_has_no_hosted_configuration_or_protected_path(
    tmp_path: Path,
) -> None:
    regular = _active(tmp_path)
    isolated = CurrentLoopCoordinator(
        workspace_root=tmp_path,
        local_only_surface=True,
    )
    assert isolated.transport is None
    assert isolated.hosted_base_url == ""
    assert isolated.hosted_token_file == ""
    try:
        isolated._protected_call("create_context_session_card", {})
    except Exception as exc:
        assert str(exc) == "local_sidecar_hosted_operation_prohibited"
    else:
        raise AssertionError("local sidecar reached Protected")
    assert regular.store.read()["loop_ref"] == isolated.store.read()["loop_ref"]
