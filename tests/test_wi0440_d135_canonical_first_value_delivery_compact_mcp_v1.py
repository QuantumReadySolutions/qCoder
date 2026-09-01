"""Retained D-135 invariants after D-136 superseded Apps and proposal v4."""

from __future__ import annotations

import json
from pathlib import Path

from qcoder.context_bridge_mcp import EXPECTED_TOOLS, tool_descriptors
from qcoder.current_loop_binding_mcp import binding_tool_descriptors, handle_binding_jsonrpc_message
from qcoder.current_loop_reference_resources import resource_descriptors
from qcoder.review_before_generation import validate_canonical_first_value_delivery

REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a three-qubit GHZ "
    "state. Before generating the code, help me review how you interpret my request and the "
    "important implementation choices."
)
CONTENT = {
    "interpretation": (
        "Create a three-qubit GHZ-state Qiskit program and review the preparation and measurement "
        "plan before producing source."
    ),
    "implementation_recommendations": [
        {"label": "Framework", "value": "Use Qiskit QuantumCircuit."},
        {
            "label": "Preparation",
            "value": "Apply H to q0, then CX from q0 to q1 and CX from q1 to q2.",
        },
        {
            "label": "Measurement",
            "value": "Measure all three qubits into matching classical bits.",
        },
    ],
    "output_artifact": "Readable Python source after confirmation",
}


def _call(workspace: Path) -> dict:
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "begin_current_loop",
                "arguments": {"request_text": REQUEST, "review_content": CONTENT},
            },
        },
        workspace_root=workspace,
    )
    assert response is not None
    return response["result"]


def test_retained_canonical_text_structured_projection_and_digest(tmp_path: Path) -> None:
    result = _call(tmp_path)
    structured = result["structuredContent"]
    text = result["content"][0]["text"]
    assert text.startswith("## Goal and scope\n")
    assert text.count("\n## ") == 2
    assert text.endswith("- Review or change choices\n")
    assert structured["review_before_generation"]["initial_decision_group_count"] == 3
    state = json.loads((tmp_path / ".qcoder/current-loop/state.json").read_text())
    review = state["coordinator"]["review_before_generation"]
    validate_canonical_first_value_delivery(
        review["canonical_delivery"], review_revision_value=review["review_revision"]
    )
    assert structured["projection_digest"] == review["projection_digest"]


def test_retained_compact_discovery_and_exact_inventory() -> None:
    public = tool_descriptors()
    private = binding_tool_descriptors()
    assert [item["name"] for item in public] == list(EXPECTED_TOOLS)
    assert [item["name"] for item in private] == ["begin_current_loop", "complete_current_step"]
    encoded = json.dumps(public + private, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    assert len(encoded.encode()) <= 32_000


def test_d136_supersedes_app_and_proposal_discovery() -> None:
    begin = binding_tool_descriptors()[0]
    encoded = json.dumps(begin, sort_keys=True)
    assert "review_content" in encoded
    assert "connected_assistant_proposal" not in encoded
    assert "resourceUri" not in encoded and "ui://" not in encoded
    assert all(not item["uri"].startswith("ui://") for item in resource_descriptors())
