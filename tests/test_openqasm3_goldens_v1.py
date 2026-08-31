from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from qcoder.evidence_usability import build_evidence_usability_pack, canonical_json
from qcoder.engines.feature_extraction.openqasm3_bounded_parser import parse_openqasm3_bytes
from qcoder.engines.feature_extraction.openqasm3_static_evidence import (
    canonical_openqasm3_json,
    render_openqasm3_static_evidence_markdown,
)


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "openqasm3_v1"
GOLDENS = CORPUS / "goldens"
EXAMPLE = ROOT / "examples" / "openqasm3_static_evidence"


def test_representative_sidecar_goldens_are_byte_exact() -> None:
    representatives = {
        "supported": CORPUS / "supported" / "bell.qasm3",
        "partial": CORPUS / "partial" / "control_flow.qasm3",
        "recognized-unsupported": CORPUS / "recognized" / "timing_calibration_extensions.qasm3",
        "recoverable-malformed": CORPUS / "partial" / "recoverable_malformed.qasm3",
    }
    for label, source in representatives.items():
        result = parse_openqasm3_bytes(source.read_bytes(), artifact_label=source.name)
        assert (
            canonical_openqasm3_json(result.sidecar).encode()
            == (GOLDENS / f"{label}-sidecar.json").read_bytes()
        )
        assert (
            render_openqasm3_static_evidence_markdown(result.sidecar).encode()
            == (GOLDENS / f"{label}-sidecar.md").read_bytes()
        )


def test_guided_example_replay_six_outputs_are_byte_exact(tmp_path: Path) -> None:
    source = EXAMPLE / "bell.qasm3"
    output = tmp_path / "replay"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "qcoder",
            "review",
            "usability-pack",
            str(source),
            "--out-dir",
            str(output),
        ],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    for expected in sorted((EXAMPLE / "expected").glob("*.json")):
        if expected.name.startswith("local-evidence"):
            continue
        assert (output / expected.name).read_bytes() == expected.read_bytes()
    for expected in sorted((EXAMPLE / "expected").glob("*.md")):
        if expected.name.startswith("local-evidence"):
            continue
        assert (output / expected.name).read_bytes() == expected.read_bytes()


def test_repeated_and_reordered_explicit_input_generation_is_equal(tmp_path: Path) -> None:
    bell = EXAMPLE / "bell.qasm3"
    partial = EXAMPLE / "partial-control-flow.qasm3"
    first = build_evidence_usability_pack(paths=[str(bell), str(partial)])
    second = build_evidence_usability_pack(paths=[str(partial), str(bell)])
    repeated = build_evidence_usability_pack(paths=[str(bell), str(partial)])
    for key in first:
        assert canonical_json(first[key][0]) == canonical_json(second[key][0])
        assert canonical_json(first[key][0]) == canonical_json(repeated[key][0])
        assert first[key][1] == second[key][1] == repeated[key][1]
    serialized = json.dumps(first, sort_keys=True)
    assert str(tmp_path) not in serialized


def test_repository_golden_verifier_passes() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/generate-openqasm3-goldens.py", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "OpenQASM 3 goldens PASS"
