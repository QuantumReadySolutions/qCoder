from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from qcoder.algorithm_blueprint import artifact_digest_matches
from qcoder.evidence_usability import (
    build_evidence_prompt_pack,
    build_evidence_usability_pack,
    build_run_readiness_checklist,
    canonical_json,
)
from qcoder.engines.feature_extraction.openqasm3_bounded_parser import parse_openqasm3_text
from qcoder.engines.review.local_evidence import (
    build_local_evidence_review,
    build_share_safe_local_evidence_review,
)
from qcoder.engines.review.local_evidence_markdown import render_local_evidence_markdown
from qcoder.engines.review.openqasm3_manifestation import (
    build_openqasm3_circuit_manifestation,
)


SUPPORTED = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
bit[2] c;
h q[0];
cx q[0], q[1];
c = measure q;
"""

PARTIAL = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
bit[2] c;
h q[0];
if (flag) { x q[1]; }
c = measure q;
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_complete_sidecar_feeds_existing_manifestation_schema() -> None:
    sidecar = parse_openqasm3_text(SUPPORTED, artifact_label="bell.qasm3").sidecar
    manifestation = build_openqasm3_circuit_manifestation(
        sidecar, stage="logical_circuit", artifact_ref="artifact-ref-openqasm3-test"
    )
    assert manifestation["schema_id"] == "qcoder.circuit_manifestation.v1"
    assert manifestation["representation_category"] == ("openqasm3_bounded_static_manifestation")
    assert manifestation["structural_metrics"]["width"] == 2
    assert manifestation["structural_metrics"]["operation_count"] == 4
    assert manifestation["measurement_mapping"] == [
        {"logical_qubit_index": 0, "classical_bit_index": 0},
        {"logical_qubit_index": 1, "classical_bit_index": 1},
    ]
    assert manifestation["raw_qasm_included"] is False
    assert manifestation["source_or_circuit_executed"] is False
    assert artifact_digest_matches(manifestation)


def test_partial_sidecar_cannot_feed_complete_manifestation() -> None:
    sidecar = parse_openqasm3_text(PARTIAL).sidecar
    with pytest.raises(ValueError, match="complete_circuit_ir_required"):
        build_openqasm3_circuit_manifestation(sidecar)


def test_opaque_custom_gate_call_does_not_feed_complete_manifestation(tmp_path: Path) -> None:
    source = "OPENQASM 3; gate custom a { U(0,0,0) a; } qubit q; custom q;\n"
    sidecar = parse_openqasm3_text(source).sidecar
    assert sidecar["file_status"] == "supported"
    assert sidecar["derived_facts"]["depth"]["exactness"] == "not_established"
    with pytest.raises(ValueError, match="complete_manifestation_facts_required"):
        build_openqasm3_circuit_manifestation(sidecar)

    selected = _write(tmp_path / "custom.qasm3", source)
    report = build_local_evidence_review([str(selected)])
    assert [
        artifact["schema_id"] for artifact in report["artifacts"][0]["canonical_artifacts"]
    ] == ["qcoder.openqasm3_static_evidence.v1"]


def test_local_review_complete_and_partial_boundaries(tmp_path: Path) -> None:
    supported = _write(tmp_path / "bell.qasm3", SUPPORTED)
    partial = _write(tmp_path / "partial.qasm3", PARTIAL)
    complete_report = build_local_evidence_review([str(supported)])
    partial_report = build_local_evidence_review([str(partial)])
    complete_artifacts = complete_report["artifacts"][0]["canonical_artifacts"]
    partial_artifacts = partial_report["artifacts"][0]["canonical_artifacts"]
    assert [artifact["schema_id"] for artifact in complete_artifacts] == [
        "qcoder.openqasm3_static_evidence.v1",
        "qcoder.circuit_manifestation.v1",
    ]
    assert [artifact["schema_id"] for artifact in partial_artifacts] == [
        "qcoder.openqasm3_static_evidence.v1"
    ]
    assert complete_report["artifacts"][0]["status"] == "established_with_qualifications"
    assert partial_report["artifacts"][0]["status"] == "partial"
    assert partial_artifacts[0]["derived_facts"]["operation_count"]["exactness"] == ("lower_bound")
    assert partial_artifacts[0]["circuit_ir"] is None
    assert "complete CircuitIR: `False`" in render_local_evidence_markdown(partial_report)


def test_usability_views_preserve_partiality_and_no_intent(tmp_path: Path) -> None:
    selected = _write(tmp_path / "partial.qasm3", PARTIAL)
    paths = [str(selected)]
    report = build_local_evidence_review(paths)
    readiness = build_run_readiness_checklist(paths=paths, report=report)
    prompt = build_evidence_prompt_pack(paths=paths, report=report)
    pack = build_evidence_usability_pack(paths=paths)
    qasm_check = next(
        row for row in readiness["checks"] if row["check_id"] == "openqasm-static-readiness"
    )
    measurement = next(
        row for row in readiness["checks"] if row["check_id"] == "measurement-evidence"
    )
    assert qasm_check["disposition"] == "warning"
    assert measurement["disposition"] == "warning"
    assert any("partial evidence" in item.casefold() for item in prompt["limitations"])
    intent = pack["blueprint-intent-card"][0]
    assert intent["intent_state"] == "absent"
    assert all(
        row["authority"] == "selected_evidence_only_not_intent"
        for row in intent["observed_evidence"]
    )


def test_outputs_are_path_independent_share_safe_and_deterministic(tmp_path: Path) -> None:
    first_path = _write(tmp_path / "one" / "bell.qasm3", SUPPORTED)
    second_path = _write(tmp_path / "two" / "bell.qasm3", SUPPORTED)
    first_paths = [str(first_path)]
    second_paths = [str(second_path)]
    first_report = build_local_evidence_review(first_paths)
    second_report = build_local_evidence_review(second_paths)
    first = build_evidence_prompt_pack(paths=first_paths, report=first_report)
    second = build_evidence_prompt_pack(paths=second_paths, report=second_report)
    assert canonical_json(first) == canonical_json(second)
    safe = build_share_safe_local_evidence_review(first_report, first_paths)
    serialized = json.dumps(safe, sort_keys=True)
    assert str(tmp_path) not in serialized
    assert SUPPORTED not in serialized
    assert safe["raw_qasm_included"] is False
    assert safe["automatic_network_transmission"] is False


def test_sidecar_semantic_mutation_cannot_be_reused_as_canonical_json(tmp_path: Path) -> None:
    selected = _write(tmp_path / "bell.qasm3", SUPPORTED)
    sidecar = parse_openqasm3_text(SUPPORTED, artifact_label="bell.qasm3").sidecar
    changed = deepcopy(sidecar)
    changed["file_status"] = "partial"
    evidence_file = tmp_path / "sidecar.json"
    evidence_file.write_text(json.dumps(changed), encoding="utf-8")
    report = build_local_evidence_review([str(evidence_file)])
    assert report["artifacts"][0]["status"] == "invalid"
    assert selected.exists()
