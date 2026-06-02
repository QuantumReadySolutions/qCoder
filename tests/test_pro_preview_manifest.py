from __future__ import annotations

import hashlib
from pathlib import Path

from qcoder.pro_preview.manifest import (
    WORKFLOW_MANIFEST_SCHEMA_ID,
    build_workflow_manifest,
)


def _write_qasm(path: Path, *, with_x: bool = False) -> None:
    body = (
        "OPENQASM 2.0;\n"
        'include "qelib1.inc";\n'
        "qreg q[2];\n"
        "creg c[2];\n"
        "h q[0];\n"
        "cx q[0], q[1];\n"
    )
    if with_x:
        body += "x q[1];\n"
    body += "measure q[0] -> c[0];\nmeasure q[1] -> c[1];\n"
    path.write_text(body, encoding="utf-8")


def test_build_workflow_manifest_single_contains_public_contract_fields(tmp_path: Path) -> None:
    qasm = tmp_path / "single.qasm"
    _write_qasm(qasm)
    payload = build_workflow_manifest(qasm=str(qasm), project_dir=str(tmp_path / "project"))

    assert payload["schema_id"] == WORKFLOW_MANIFEST_SCHEMA_ID
    assert payload["mode"] == "single"
    assert payload["workflow"]["project_dir_supplied"] is True
    assert payload["workflow"]["project_dir_name"] == "project"
    assert payload["boundary"]["dry_run"] is True
    assert payload["boundary"]["upload_performed"] is False
    assert payload["boundary"]["network_performed"] is False
    assert payload["boundary"]["source_contents_included"] is False
    assert payload["boundary"]["cards_local"] is False
    assert payload["boundary"]["local_pro_analysis"] is False
    assert payload["boundary"]["confidential_analysis_local"] is False
    assert payload["inputs"]["qasm"]["file_name"] == "single.qasm"
    assert payload["inputs"]["qasm"]["bytes"] == qasm.stat().st_size
    assert payload["inputs"]["qasm"]["sha256"] == hashlib.sha256(qasm.read_bytes()).hexdigest()
    assert payload["inputs"]["qasm"]["local_analysis"]["n_qubits"] == 2
    assert "source_contents" not in payload["inputs"]["qasm"]


def test_build_workflow_manifest_pair_has_before_after_inputs(tmp_path: Path) -> None:
    before_qasm = tmp_path / "before.qasm"
    after_qasm = tmp_path / "after.qasm"
    _write_qasm(before_qasm)
    _write_qasm(after_qasm, with_x=True)

    payload = build_workflow_manifest(before_qasm=str(before_qasm), after_qasm=str(after_qasm))

    assert payload["mode"] == "pair"
    assert payload["inputs"]["before_qasm"]["file_name"] == "before.qasm"
    assert payload["inputs"]["after_qasm"]["file_name"] == "after.qasm"
    assert payload["inputs"]["before_qasm"]["sha256"] != payload["inputs"]["after_qasm"]["sha256"]
    assert payload["inputs"]["before_qasm"]["local_analysis"]["source_format"] == "qasm2"
    assert payload["inputs"]["after_qasm"]["local_analysis"]["source_format"] == "qasm2"
