from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from qcoder.pipelines.analyze import analyze_qasm_json


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_qasm2_bom_is_accepted(tmp_path: Path) -> None:
    qasm = tmp_path / "bom.qasm"
    qasm.write_text(
        "OPENQASM 2.0;\n"
        'include "qelib1.inc";\n'
        "qreg q[1];\n"
        "creg c[1];\n"
        "h q[0];\n"
        "measure q[0] -> c[0];\n",
        encoding="utf-8-sig",
    )

    payload = analyze_qasm_json(str(qasm), include_guidance=True)

    assert payload["source_format"] == "qasm2"
    assert payload["n_qubits"] == 1
    assert payload["n_ops"] == 2


def test_review_counts_bom_is_accepted(tmp_path: Path) -> None:
    root = _repo_root()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    counts = tmp_path / "counts.json"
    counts.write_text(json.dumps({"00": 5, "11": 3}), encoding="utf-8-sig")
    out_json = tmp_path / "review.json"
    out_md = tmp_path / "review.md"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "qcoder",
            "review",
            "--counts-json",
            str(counts),
            "--format",
            "qiskit_counts",
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["derived"]["total_shots"] == 8


def test_review_qiskit_counts_error_is_actionable(tmp_path: Path) -> None:
    root = _repo_root()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    counts = tmp_path / "bad-counts.json"
    counts.write_text(json.dumps({"00": "five"}), encoding="utf-8")
    out_json = tmp_path / "review.json"
    out_md = tmp_path / "review.md"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "qcoder",
            "review",
            "--counts-json",
            str(counts),
            "--format",
            "qiskit_counts",
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert "For Qiskit counts, use --format qiskit_counts" in proc.stderr
    assert '{"00": 10, "11": 6}' in proc.stderr
