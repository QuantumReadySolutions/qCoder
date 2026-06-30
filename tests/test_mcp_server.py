from __future__ import annotations

import json

from qcoder.mcp.server import handle_request


def test_mcp_initialize_and_list_tools() -> None:
    init = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
    )
    assert init is not None
    assert init["result"]["serverInfo"]["name"] == "qcoder-local-read-only"
    assert "does not execute circuits" in init["result"]["instructions"]

    listed = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert listed is not None
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert "qcoder_analyze_circuit" in names
    assert "qcoder_explorer_evidence" not in names


def test_mcp_call_unknown_tool_returns_error() -> None:
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "qcoder_explorer_evidence", "arguments": {}},
        }
    )

    assert response is not None
    assert response["error"]["code"] == -32000
    assert "unknown qCoder MCP tool" in response["error"]["message"]


def test_mcp_claim_boundaries_tool_call() -> None:
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "qcoder_claim_boundaries", "arguments": {}},
        }
    )

    assert response is not None
    payload = response["result"]["structuredContent"]
    text = json.dumps(payload, sort_keys=True).lower()
    assert payload["manual_artifact_loop_launch_required"] is True
    assert "quantum advantage" in text
