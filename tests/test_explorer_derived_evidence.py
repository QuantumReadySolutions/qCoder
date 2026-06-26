from __future__ import annotations

import json
from pathlib import Path

import pytest

from qcoder.explorer.derived_evidence import (
    REQUEST_SCHEMA_ID,
    ExplorerDerivedEvidenceRequestError,
    build_derived_evidence_request_from_context_json,
    build_derived_evidence_request_from_qasm,
)
from qcoder.pipelines.context import write_preflight_context


_QASM2 = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0], q[1];
measure q[0] -> c[0];
measure q[1] -> c[1];
"""


def test_qasm_request_is_sanitized_and_bounded(tmp_path: Path) -> None:
    qasm = tmp_path / "private-circuit.qasm"
    qasm.write_text(_QASM2, encoding="utf-8")

    request = build_derived_evidence_request_from_qasm(str(qasm))
    serialized = json.dumps(request, sort_keys=True)

    assert request["schema_id"] == REQUEST_SCHEMA_ID
    assert request["input_summary"]["input_kind"] == "local_qasm2_analysis"
    assert request["privacy_boundary"]["raw_qasm_included"] is False
    assert request["privacy_boundary"]["local_paths_included"] is False
    assert request["privacy_boundary"]["operation_list_included"] is False
    assert request["circuit_summary"]["source_format"] == "qasm2"
    assert "selected_feature_map" in request["derived_analysis"]
    assert "feature_profiles" in request["derived_analysis"]
    assert "guidance" in request["derived_analysis"]
    assert _QASM2.strip() not in serialized
    assert str(qasm) not in serialized
    assert "private-circuit.qasm" not in serialized
    assert "Authorization" not in serialized
    assert "QCODER_STUDENT_TOKEN" not in serialized


def test_context_json_request_strips_local_path(tmp_path: Path) -> None:
    qasm = tmp_path / "from-context.qasm"
    context_json = tmp_path / "preflight.context.json"
    context_md = tmp_path / "preflight.context.md"
    qasm.write_text(_QASM2, encoding="utf-8")
    write_preflight_context(
        str(qasm),
        out_json=str(context_json),
        out_md=str(context_md),
        include_guidance=True,
        include_profiles=True,
    )

    request = build_derived_evidence_request_from_context_json(str(context_json))
    serialized = json.dumps(request, sort_keys=True)

    assert request["input_summary"]["input_kind"] == "preflight_context_json"
    assert request["fingerprints"]["qasm_sha256"]
    assert str(qasm) not in serialized
    assert "from-context.qasm" not in serialized


def test_context_json_rejects_forbidden_raw_fields(tmp_path: Path) -> None:
    context = {
        "artifact_type": "qcoder.preflight_context",
        "circuit": {"source_format": "qasm2", "n_qubits": 1, "n_cbits": 0, "n_ops": 1},
        "hashes": {"qasm_sha256": "abc", "analysis_fingerprint": "def"},
        "analysis": {
            "feature_map": {"n_qubits": 1},
            "raw_qasm": "OPENQASM 2.0; qreg q[1];",
        },
    }
    context_json = tmp_path / "bad.context.json"
    context_json.write_text(json.dumps(context), encoding="utf-8")

    with pytest.raises(ExplorerDerivedEvidenceRequestError, match="cannot be sent"):
        build_derived_evidence_request_from_context_json(str(context_json))


def test_qasm3_is_rejected_with_explicit_boundary(tmp_path: Path) -> None:
    qasm = tmp_path / "qasm3.qasm"
    qasm.write_text("OPENQASM 3.0;\nqubit[1] q;\n", encoding="utf-8")

    with pytest.raises(ExplorerDerivedEvidenceRequestError, match="OpenQASM 3 is not supported"):
        build_derived_evidence_request_from_qasm(str(qasm))

