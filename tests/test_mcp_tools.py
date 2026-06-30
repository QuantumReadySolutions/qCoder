from __future__ import annotations

import json
from pathlib import Path

import pytest

from qcoder.mcp.tools import call_tool, list_tools


def _write_qasm(path: Path, *, bom: bool = False) -> None:
    text = (
        "OPENQASM 2.0;\n"
        'include "qelib1.inc";\n'
        "qreg q[2];\n"
        "creg c[2];\n"
        "h q[0];\n"
        "cx q[0],q[1];\n"
        "measure q[0] -> c[0];\n"
        "measure q[1] -> c[1];\n"
    )
    path.write_text(text, encoding="utf-8-sig" if bom else "utf-8")


def _structured(result: dict[str, object]) -> dict[str, object]:
    payload = result["structuredContent"]
    assert isinstance(payload, dict)
    return payload


def test_mcp_tool_schemas_include_launch_tools() -> None:
    names = {tool["name"] for tool in list_tools()}

    assert {
        "qcoder_analyze_circuit",
        "qcoder_generate_context_pack",
        "qcoder_review_counts",
        "qcoder_explain_findings",
        "qcoder_claim_boundaries",
        "qcoder_next_checks",
    }.issubset(names)
    assert "qcoder_explorer_evidence" not in names


def test_mcp_analyze_circuit_returns_share_safe_bounded_evidence(tmp_path: Path) -> None:
    qasm = tmp_path / "private-bell.qasm"
    _write_qasm(qasm, bom=True)

    payload = _structured(call_tool("qcoder_analyze_circuit", {"qasm_path": str(qasm)}))
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["share_safe"] is True
    assert payload["raw_qasm_included"] is False
    assert payload["local_paths_included"] is False
    assert payload["token_like_secrets_included"] is False
    assert payload["source_format"] == "qasm2"
    assert payload["mcp_boundary"]["read_only"] is True
    assert payload["mcp_boundary"]["modifies_user_code"] is False
    assert payload["mcp_boundary"]["executes_circuits"] is False
    assert str(tmp_path) not in serialized
    assert "OPENQASM 2.0" not in serialized


def test_mcp_context_pack_preserves_evidence_grounded_loop(tmp_path: Path) -> None:
    qasm = tmp_path / "loop.qasm"
    _write_qasm(qasm)

    result = call_tool("qcoder_generate_context_pack", {"qasm_path": str(qasm)})
    payload = _structured(result)
    loop = payload["evidence_grounded_coding_loop"]

    assert loop == [
        "write/edit circuit",
        "generate qCoder evidence locally",
        "use Explorer to produce plain-English review and next-step guidance",
        "share clean Explorer summary with Cursor/ChatGPT",
        "revise circuit",
        "review again",
    ]
    assert payload["share_safe"] is True
    assert any("Share-safe provenance" in item["text"] for item in result["content"])


def test_mcp_review_counts_accepts_bom_qiskit_counts(tmp_path: Path) -> None:
    counts = tmp_path / "counts.json"
    counts.write_text(json.dumps({"00": 5, "11": 3}), encoding="utf-8-sig")

    payload = _structured(
        call_tool("qcoder_review_counts", {"counts_json": str(counts), "counts_format": "qiskit_counts"})
    )

    assert payload["share_safe"] is True
    assert payload["derived"]["total_shots"] == 8
    assert payload["mcp_boundary"]["requires_token"] is False


def test_mcp_rejects_directory_instead_of_arbitrary_file_expansion(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit readable file"):
        call_tool("qcoder_analyze_circuit", {"qasm_path": str(tmp_path)})


def test_mcp_rejects_qasm3_gracefully(tmp_path: Path) -> None:
    qasm = tmp_path / "qasm3.qasm"
    qasm.write_text(
        "OPENQASM 3.0;\n"
        "qubit[1] q;\n"
        "bit[1] c;\n"
        "h q[0];\n"
        "c[0] = measure q[0];\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="OpenQASM 2"):
        call_tool("qcoder_analyze_circuit", {"qasm_path": str(qasm)})


def test_mcp_rejects_oversized_explicit_input(tmp_path: Path) -> None:
    qasm = tmp_path / "large.qasm"
    qasm.write_text("// padding\n" + ("x" * (1024 * 1024 + 1)), encoding="utf-8")

    with pytest.raises(ValueError, match="input size cap"):
        call_tool("qcoder_analyze_circuit", {"qasm_path": str(qasm)})


def test_mcp_package_does_not_import_token_or_network_clients() -> None:
    source = Path(__file__).resolve().parents[1] / "src" / "qcoder" / "mcp" / "tools.py"
    text = source.read_text(encoding="utf-8")

    assert "resolve_token" not in text
    assert "urlopen" not in text
    assert "ProServiceClient" not in text
    assert "call_student" not in text


def test_mcp_claim_boundaries_keep_pro_and_deferred_items_out() -> None:
    payload = _structured(call_tool("qcoder_claim_boundaries", {}))
    text = json.dumps(payload, sort_keys=True).lower()

    assert "runtime prediction" in text
    assert "fidelity prediction" in text
    assert "backend or qpu ranking" in text
    assert payload["manual_artifact_loop_launch_required"] is True
    assert payload["local_cursor_mcp_complements_artifacts"] is True


def test_mcp_claim_boundaries_summarizes_supplied_artifact() -> None:
    payload = _structured(
        call_tool(
            "qcoder_claim_boundaries",
            {
                "artifact": {
                    "artifact_type": "qcoder.preflight_context",
                    "analysis": {"feature_map": {"n_qubits": 2, "n_ops": 4}},
                }
            },
        )
    )

    assert payload["artifact_present"] is True
    assert payload["artifact_summary"]["feature_map_present"] is True
    assert payload["artifact_summary"]["artifact_type"] == "qcoder.preflight_context"
    assert payload["artifact_summary"]["feature_keys_present"] == ["n_ops", "n_qubits"]


def test_mcp_next_checks_do_not_claim_autonomous_repair() -> None:
    payload = _structured(
        call_tool(
            "qcoder_next_checks",
            {"artifact": {"feature_map": {"n_measure_ops": 0, "n_2q_gate_ops": 1, "n_param_ops": 1}}},
        )
    )
    text = json.dumps(payload, sort_keys=True).lower()

    assert "autonomous repair" in text
    assert "runtime" in text
    assert "backend" in text
    assert "modify" not in text
