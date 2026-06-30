from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qcoder.core.share_safe import make_share_safe_payload
from qcoder.engines.context.markdown import render_context_markdown
from qcoder.engines.review.markdown import render_review_markdown
from qcoder.pipelines.analyze import analyze_qasm_json
from qcoder.pipelines.context import build_preflight_context
from qcoder.pipelines.review import build_execution_review


SAFE_MARKETING_FRAME = (
    "Explorer helps you make your AI assistant better at quantum circuit work by "
    "giving it clean qCoder evidence to reason from."
)

SUPPORTED_CLAIMS = [
    "local deterministic QASM2/OpenQASM 2 structural evidence",
    "local Qiskit counts review",
    "share-safe evidence handoff",
    "plain-English bounded next checks from observed qCoder evidence",
]

UNSUPPORTED_CLAIMS = [
    "autonomous circuit repair",
    "runtime prediction",
    "fidelity prediction",
    "backend or QPU ranking",
    "QPU/backend guidance",
    "quantum advantage",
    "correctness proof",
    "raw hosted QASM review",
    "persistent Explorer history",
    "public hosted MCP",
    "productized Claude Code or Codex integration",
]


def list_tools() -> list[dict[str, Any]]:
    return [
        _tool_schema(
            "qcoder_analyze_circuit",
            "Analyze one explicit local OpenQASM 2 file and return share-safe qCoder evidence.",
            {"qasm_path": {"type": "string"}, "include_guidance": {"type": "boolean"}, "include_profiles": {"type": "boolean"}},
            ["qasm_path"],
        ),
        _tool_schema(
            "qcoder_generate_context_pack",
            "Build a share-safe preflight context pack for one explicit local OpenQASM 2 file.",
            {"qasm_path": {"type": "string"}, "include_guidance": {"type": "boolean"}, "include_profiles": {"type": "boolean"}},
            ["qasm_path"],
        ),
        _tool_schema(
            "qcoder_review_counts",
            "Review one explicit local counts JSON file, optionally linked to one preflight context JSON.",
            {
                "counts_json": {"type": "string"},
                "counts_format": {"type": "string", "enum": ["qcoder", "qiskit_counts"]},
                "preflight_json": {"type": "string"},
            },
            ["counts_json"],
        ),
        _tool_schema(
            "qcoder_explain_findings",
            "Explain bounded findings from a qCoder artifact object supplied directly to the tool.",
            {"artifact": {"type": "object"}},
            ["artifact"],
        ),
        _tool_schema(
            "qcoder_claim_boundaries",
            "Return qCoder Explorer Launch claim boundaries and unsupported claims.",
            {"artifact": {"type": "object"}},
            [],
        ),
        _tool_schema(
            "qcoder_next_checks",
            "Recommend bounded next checks from a qCoder artifact object supplied directly to the tool.",
            {"artifact": {"type": "object"}},
            ["artifact"],
        ),
        _tool_schema(
            "qcoder_generate_share_safe_artifact",
            "Sanitize a supplied artifact object into a share-safe qCoder artifact.",
            {"artifact": {"type": "object"}},
            ["artifact"],
        ),
    ]


def _tool_schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = arguments or {}
    if name == "qcoder_analyze_circuit":
        return _analyze_circuit(args)
    if name == "qcoder_generate_context_pack":
        return _generate_context_pack(args)
    if name == "qcoder_review_counts":
        return _review_counts(args)
    if name == "qcoder_explain_findings":
        return _explain_findings(args)
    if name == "qcoder_claim_boundaries":
        return _claim_boundaries(args)
    if name == "qcoder_next_checks":
        return _next_checks(args)
    if name == "qcoder_generate_share_safe_artifact":
        return _generate_share_safe_artifact(args)
    raise ValueError(f"unknown qCoder MCP tool: {name}")


def _explicit_file_arg(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    path = Path(value).expanduser()
    if not path.is_file():
        raise ValueError(f"{key} must be an explicit readable file")
    return str(path)


def _artifact_arg(args: dict[str, Any]) -> dict[str, Any]:
    artifact = args.get("artifact")
    if not isinstance(artifact, dict):
        raise ValueError("artifact must be a JSON object supplied directly to the tool")
    return artifact


def _result(payload: dict[str, Any], *, markdown: str | None = None) -> dict[str, Any]:
    text = json.dumps(payload, indent=2, sort_keys=True)
    content = [{"type": "text", "text": text}]
    if markdown is not None:
        content.append({"type": "text", "text": markdown})
    return {"content": content, "structuredContent": payload}


def _analyze_circuit(args: dict[str, Any]) -> dict[str, Any]:
    qasm_path = _explicit_file_arg(args, "qasm_path")
    payload = analyze_qasm_json(
        qasm_path,
        include_guidance=bool(args.get("include_guidance", True)),
        include_profiles=bool(args.get("include_profiles", True)),
    )
    payload = make_share_safe_payload(payload)
    payload["mcp_boundary"] = _mcp_boundary()
    return _result(payload)


def _generate_context_pack(args: dict[str, Any]) -> dict[str, Any]:
    qasm_path = _explicit_file_arg(args, "qasm_path")
    payload = build_preflight_context(
        qasm_path,
        include_guidance=bool(args.get("include_guidance", True)),
        include_profiles=bool(args.get("include_profiles", True)),
    )
    payload = make_share_safe_payload(payload)
    payload["evidence_grounded_coding_loop"] = _evidence_loop()
    payload["mcp_boundary"] = _mcp_boundary()
    return _result(payload, markdown=render_context_markdown(payload))


def _review_counts(args: dict[str, Any]) -> dict[str, Any]:
    counts_json = _explicit_file_arg(args, "counts_json")
    counts_format = args.get("counts_format", "qiskit_counts")
    if counts_format not in {"qcoder", "qiskit_counts"}:
        raise ValueError("counts_format must be qcoder or qiskit_counts")
    preflight_json = args.get("preflight_json")
    preflight = _explicit_file_arg(args, "preflight_json") if preflight_json else None
    payload = build_execution_review(
        counts_json=counts_json,
        counts_format=str(counts_format),
        preflight_json=preflight,
    )
    payload = make_share_safe_payload(payload)
    payload["mcp_boundary"] = _mcp_boundary()
    return _result(payload, markdown=render_review_markdown(payload))


def _explain_findings(args: dict[str, Any]) -> dict[str, Any]:
    artifact = _artifact_arg(args)
    feature_map = _feature_map_from_artifact(artifact)
    summary = {
        "schema_id": "qcoder.mcp.explain_findings.v0",
        "status": "ok",
        "finding_summary": _finding_lines(feature_map),
        "evidence_basis": "qCoder structural evidence supplied by the user or generated from an explicit local input.",
        "limits": [
            "This is not simulator or hardware execution evidence.",
            "This is not a correctness proof.",
            "This is not runtime, fidelity, backend, QPU, or quantum-advantage prediction.",
        ],
        "safe_framing": SAFE_MARKETING_FRAME,
        "mcp_boundary": _mcp_boundary(),
    }
    return _result(make_share_safe_payload(summary))


def _claim_boundaries(args: dict[str, Any]) -> dict[str, Any]:
    artifact = args.get("artifact") if isinstance(args.get("artifact"), dict) else {}
    payload = {
        "schema_id": "qcoder.mcp.claim_boundaries.v0",
        "status": "ok",
        "mcp_supported_claims": SUPPORTED_CLAIMS,
        "mcp_unsupported_claims": UNSUPPORTED_CLAIMS,
        "artifact_present": bool(artifact),
        "manual_artifact_loop_launch_required": True,
        "local_cursor_mcp_complements_artifacts": True,
        "oss_boundary": "OSS remains local, no-account, no-token.",
        "explorer_boundary": "Explorer is account-backed guidance over local/share-safe evidence.",
        "pro_boundary": "Pro owns fidelity prediction, QPU/backend guidance, backend ranking, and validated runtime/shot modeling.",
        "mcp_boundary": _mcp_boundary(),
    }
    return _result(make_share_safe_payload(payload))


def _next_checks(args: dict[str, Any]) -> dict[str, Any]:
    artifact = _artifact_arg(args)
    feature_map = _feature_map_from_artifact(artifact)
    checks = [
        "Generate or refresh a share-safe qCoder preflight context artifact.",
        "If you have measurement counts, run qcoder review with --format qiskit_counts or qcoder.",
        "Share only the share-safe summary with Cursor, ChatGPT, teammates, issues, or forums.",
    ]
    if _number(feature_map.get("n_measure_ops")) == 0:
        checks.append("Add or verify measurement operations before interpreting counts.")
    if _number(feature_map.get("n_2q_gate_ops")) > 0:
        checks.append("Review two-qubit structure and entangling depth before choosing simulator settings.")
    if _number(feature_map.get("n_param_ops")) > 0:
        checks.append("Confirm parameter binding and sweep assumptions outside qCoder before execution.")
    payload = {
        "schema_id": "qcoder.mcp.next_checks.v0",
        "status": "ok",
        "next_checks": checks,
        "limits": [
            "Recommendations are bounded next checks, not autonomous repair.",
            "No backend, QPU, runtime, fidelity, correctness, or advantage claim is made.",
        ],
        "mcp_boundary": _mcp_boundary(),
    }
    return _result(make_share_safe_payload(payload))


def _generate_share_safe_artifact(args: dict[str, Any]) -> dict[str, Any]:
    payload = make_share_safe_payload(_artifact_arg(args))
    payload["mcp_boundary"] = _mcp_boundary()
    return _result(payload)


def _feature_map_from_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    if isinstance(artifact.get("feature_map"), dict):
        return artifact["feature_map"]
    analysis = artifact.get("analysis")
    if isinstance(analysis, dict) and isinstance(analysis.get("feature_map"), dict):
        return analysis["feature_map"]
    derived = artifact.get("derived_analysis")
    if isinstance(derived, dict) and isinstance(derived.get("selected_feature_map"), dict):
        return derived["selected_feature_map"]
    return {}


def _finding_lines(feature_map: dict[str, Any]) -> list[str]:
    if not feature_map:
        return ["No qCoder feature_map was supplied; generate qCoder evidence first."]
    lines: list[str] = []
    for key in ("n_qubits", "n_ops", "real_depth", "entangling_depth", "n_2q_gate_ops", "n_measure_ops"):
        if key in feature_map:
            lines.append(f"{key}: {feature_map[key]}")
    return lines or ["qCoder evidence was supplied, but no launch summary fields were present."]


def _number(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _mcp_boundary() -> dict[str, Any]:
    return {
        "local": True,
        "read_only": True,
        "explicit_user_selected_inputs_only": True,
        "modifies_user_code": False,
        "executes_circuits": False,
        "submits_to_qpu_or_simulator": False,
        "requires_token": False,
        "uses_live_service": False,
    }


def _evidence_loop() -> list[str]:
    return [
        "write/edit circuit",
        "generate qCoder evidence locally",
        "use Explorer to produce plain-English review and next-step guidance",
        "share clean Explorer summary with Cursor/ChatGPT",
        "revise circuit",
        "review again",
    ]
