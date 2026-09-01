from __future__ import annotations

import io
import json
from pathlib import Path
import socket
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout

import pytest

from qcoder.cli import main
from qcoder.context_loop import (
    CIRCUIT_MANIFESTATION_SCHEMA_ID,
    RESULT_MANIFESTATION_SCHEMA_ID,
)
from qcoder.current_loop_quiet_workflow import (
    HELP_SCHEMA_ID,
    HELP_V2_COMMON_REQUIRED_FIELDS,
    HELP_V2_PROJECTION_REQUIRED_FIELDS,
    validate_help_v2_projection,
)
from qcoder.current_loop_run_summary import RUN_SUMMARY_SCHEMA_ID
from qcoder.development_evidence import DEVELOPMENT_EVIDENCE_SCHEMA_ID, MOTIF_REGISTRY
from qcoder.engines.review.local_evidence import (
    LocalEvidenceError,
    build_local_evidence_review,
    build_share_safe_local_evidence_review,
)
from qcoder.engines.review.local_evidence_markdown import render_local_evidence_markdown


EXPECTED_MOTIFS = [
    "qiskit.circuit.construction",
    "qiskit.parameter.use",
    "qiskit.measurement.mapping",
    "qiskit.controlled.operations",
    "qiskit.result.processing",
    "grover.oracle.structure",
    "grover.diffusion.amplification",
    "grover.iteration.structure",
    "qaoa.cost.layer",
    "qaoa.mixer.layer",
    "qaoa.repetition.layer",
    "qaoa.parameterized.layer",
]


def _qasm2(path: Path, *, custom: bool = False) -> Path:
    extra = "mystery q[0];\n" if custom else ""
    path.write_text(
        "OPENQASM 2.0;\n"
        'include "qelib1.inc";\n'
        "qreg q[2];\n"
        "creg c[2];\n"
        "h q[0];\n"
        "cx q[0],q[1];\n"
        f"{extra}"
        "measure q[0] -> c[0];\n"
        "measure q[1] -> c[1];\n",
        encoding="utf-8",
    )
    return path


def _python(path: Path) -> Path:
    path.write_text(
        "from qiskit import QuantumCircuit\n"
        "qc = QuantumCircuit(2, 2)\n"
        "qc.h(0)\n"
        "qc.cx(0, 1)\n"
        "qc.measure([0, 1], [0, 1])\n"
        "counts = result.get_counts()\n",
        encoding="utf-8",
    )
    return path


def _counts(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "counts": {"00": 507, "11": 517},
                "shots": 1024,
                "backend": "local_simulator",
                "simulator_method": "automatic",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_discoverable_review_local_evidence_entry_and_legacy_review_help() -> None:
    root_out = io.StringIO()
    with redirect_stdout(root_out):
        assert main(["--help"]) == 0
    assert "Review local evidence" in root_out.getvalue()

    review_out = io.StringIO()
    with redirect_stdout(review_out), pytest.raises(SystemExit) as raised:
        main(["review", "--help"])
    assert raised.value.code == 0
    assert "qcoder review local-evidence" in review_out.getvalue()
    assert "FILE [FILE ...]" in review_out.getvalue()

    local_out = io.StringIO()
    with redirect_stdout(local_out), pytest.raises(SystemExit) as raised:
        main(["review", "local-evidence", "--help"])
    assert raised.value.code == 0
    text = local_out.getvalue()
    assert "explicitly selected files only" in text
    assert "--local-help" in text
    assert "--share-safe-json" in text
    assert "--include-everything" not in text


def test_python_source_is_bounded_and_uses_exact_motif_registry(tmp_path: Path) -> None:
    selected = _python(tmp_path / "selected.py")
    unrelated = tmp_path / "unrelated.py"
    unrelated.write_text("raise RuntimeError('must not be read')\n", encoding="utf-8")
    report = build_local_evidence_review([str(selected)])
    item = report["artifacts"][0]
    evidence = item["canonical_artifacts"][0]
    assert evidence["schema_id"] == DEVELOPMENT_EVIDENCE_SCHEMA_ID
    assert list(MOTIF_REGISTRY) == EXPECTED_MOTIFS
    assert report["canonical_identity_reuse"]["motif_registry_identifiers"] == EXPECTED_MOTIFS
    observed = {
        row["motif_id"]
        for row in evidence["motif_observations"]
        if row["observation_status"] in {"observed", "ambiguous"}
    }
    assert "qiskit.circuit.construction" in observed
    assert "qiskit.controlled.operations" in observed
    assert evidence["source_evidence"]["repository_scanned"] is False
    assert evidence["source_evidence"]["imports_followed"] is False
    assert evidence["source_evidence"]["source_executed"] is False
    assert all("unrelated" not in json.dumps(row) for row in report["artifacts"])
    nonclaims = " ".join(item["not_established"] + item["limitations"]).lower()
    assert "algorithm identity" in nonclaims
    assert "correctness" in nonclaims
    assert "caus" in nonclaims


def test_qasm2_reuses_circuit_manifestation_and_never_claims_qasm_motifs(
    tmp_path: Path,
) -> None:
    report = build_local_evidence_review([str(_qasm2(tmp_path / "bell.qasm"))])
    item = report["artifacts"][0]
    manifestation = item["canonical_artifacts"][0]
    assert manifestation["schema_id"] == CIRCUIT_MANIFESTATION_SCHEMA_ID
    assert manifestation["structural_metrics"] == {
        "width": 2,
        "classical_width": 2,
        "gate_count": 2,
        "operation_count": 4,
        "depth": 2,
        "sequential_gate_count": 2,
        "multi_qubit_gate_count": 1,
        "entangling_operation_count": 1,
        "entangling_depth": 1,
        "measurement_count": 2,
    }
    assert "No motif evidence was inferred from QASM." in item["not_established"]
    assert manifestation["raw_qasm_included"] is False
    assert manifestation["repository_scanned"] is False


def test_qasm2_custom_construct_is_partial_and_visible(tmp_path: Path) -> None:
    report = build_local_evidence_review([str(_qasm2(tmp_path / "custom.qasm", custom=True))])
    item = report["artifacts"][0]
    assert item["status"] == "partial"
    assert any("Custom or unknown" in warning for warning in item["warnings"])
    assert any("mystery" in warning for warning in item["warnings"])


def test_qasm3_uses_bounded_parser_without_qasm2_parser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    qasm3 = tmp_path / "input.qasm"
    qasm3.write_text(
        'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nh q[0];\n',
        encoding="utf-8",
    )

    def forbidden_parser(_text: str) -> object:
        raise AssertionError("QASM3 reached the QASM2 parser")

    monkeypatch.setattr("qcoder.engines.review.local_evidence.parse_qasm2_text", forbidden_parser)
    report = build_local_evidence_review([str(qasm3)])
    item = report["artifacts"][0]
    assert report["status"] == "completed"
    assert item["input"]["kind"] == "openqasm_3"
    assert item["status"] == "established_with_qualifications"
    assert item["canonical_artifacts"][0]["schema_id"] == ("qcoder.openqasm3_static_evidence.v1")
    assert item["canonical_artifacts"][0]["file_status"] == "supported"
    assert item["canonical_artifacts"][0]["circuit_ir"]["complete"] is True
    assert "Execution is outside this static evidence path." in item["not_established"]
    assert any("--out-json" in value for value in item["supported_next_actions"])


def test_supplied_counts_reuse_canonical_run_summary_and_missing_metadata(
    tmp_path: Path,
) -> None:
    report = build_local_evidence_review([str(_counts(tmp_path / "result.json"))])
    item = report["artifacts"][0]
    summary = next(
        artifact
        for artifact in item["canonical_artifacts"]
        if artifact.get("schema_id") == RUN_SUMMARY_SCHEMA_ID
    )
    assert summary["count_projection"]["observed_shots"] == 1024
    assert summary["count_projection"]["top_outcomes"][:2] == [
        {"rank": 1, "bitstring": "11", "count": 517, "percentage": 50.488281},
        {"rank": 2, "bitstring": "00", "count": 507, "percentage": 49.511719},
    ]
    assert summary["execution_observations"]["backend"]["value"] == "local_simulator"
    assert summary["execution_observations"]["simulator_method"]["value"] == "automatic"
    assert "sdk_version" in summary["missing_execution_fields"]
    assert summary["raw_result_artifact_embedded"] is False
    assert summary["complete_raw_counts_embedded"] is False
    claims = json.dumps(item).lower()
    assert "qcoder did not execute" in claims
    assert "correctness" in claims
    assert "causation" in claims


def test_supported_and_newer_evidence_json_are_distinguished(tmp_path: Path) -> None:
    source = _python(tmp_path / "selected.py")
    source_report = build_local_evidence_review([str(source)])
    canonical = source_report["artifacts"][0]["canonical_artifacts"][0]
    supported = tmp_path / "evidence.json"
    supported.write_text(json.dumps(canonical), encoding="utf-8")
    reviewed = build_local_evidence_review([str(supported)])
    assert reviewed["artifacts"][0]["status"] == "established_with_qualifications"
    assert reviewed["artifacts"][0]["canonical_artifacts"][0]["schema_id"] == (
        DEVELOPMENT_EVIDENCE_SCHEMA_ID
    )

    newer = tmp_path / "newer.json"
    newer.write_text(
        json.dumps({"schema_id": "qcoder.development_evidence.v1", "schema_version": 1}),
        encoding="utf-8",
    )
    unsupported = build_local_evidence_review([str(newer)])
    assert unsupported["artifacts"][0]["status"] == "unsupported"
    assert "not interpreted" in unsupported["artifacts"][0]["not_established"][0]


def test_existing_execution_review_json_is_supported_without_reproduction(
    tmp_path: Path,
) -> None:
    review = tmp_path / "execution.review.json"
    review.write_text(
        json.dumps(
            {
                "review_bundle_schema_version": "0.1",
                "artifact_type": "qcoder.execution_review",
                "inputs": {"counts_format": "qiskit_counts"},
                "derived": {"total_shots": 8},
                "checks": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    report = build_local_evidence_review([str(review)])
    item = report["artifacts"][0]
    assert item["input"]["kind"] == "qcoder_execution_review_json"
    assert item["status"] == "established_with_qualifications"
    assert "not independently reproduced" in item["not_established"][0]


def test_malformed_json_has_customer_error_without_stack_trace(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{broken", encoding="utf-8")
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(["review", "local-evidence", str(bad)])
    assert rc == 2
    assert "malformed JSON" in err.getvalue()
    assert "Traceback" not in err.getvalue()


def test_explicit_collection_is_sorted_bounded_and_has_no_discovery(tmp_path: Path) -> None:
    second = _qasm2(tmp_path / "b.qasm")
    first = _python(tmp_path / "a.py")
    report = build_local_evidence_review([str(second), str(first)])
    names = [
        Path(row["selected_source"]).name for row in report["review_scope"]["selected_artifacts"]
    ]
    assert names == ["a.py", "b.qasm"]
    assert report["review_scope"]["directory_input_accepted"] is False
    assert report["review_scope"]["glob_expansion_performed"] is False
    assert report["review_scope"]["recursive_discovery_performed"] is False
    assert report["review_scope"]["hidden_file_discovery_performed"] is False
    assert report["review_scope"]["watcher_started"] is False
    with pytest.raises(LocalEvidenceError, match="directories, globs"):
        build_local_evidence_review([str(tmp_path)])
    with pytest.raises(LocalEvidenceError, match="does not exist"):
        build_local_evidence_review([str(tmp_path / "*.qasm")])
    with pytest.raises(LocalEvidenceError, match="duplicate"):
        build_local_evidence_review([str(first), str(first)])
    many = []
    for index in range(9):
        many.append(str(_qasm2(tmp_path / f"{index}.qasm")))
    with pytest.raises(LocalEvidenceError, match="limit exceeded"):
        build_local_evidence_review(many)


def test_hidden_explicit_file_is_rejected(tmp_path: Path) -> None:
    hidden = _python(tmp_path / ".hidden.py")
    with pytest.raises(LocalEvidenceError, match="hidden files"):
        build_local_evidence_review([str(hidden)])


def test_visible_symlink_to_hidden_file_or_hidden_parent_is_rejected(tmp_path: Path) -> None:
    hidden_file = _python(tmp_path / ".hidden.py")
    visible_link = tmp_path / "visible.py"
    visible_link.symlink_to(hidden_file)
    with pytest.raises(LocalEvidenceError, match="hidden files"):
        build_local_evidence_review([str(visible_link)])

    hidden_parent = tmp_path / ".private"
    hidden_parent.mkdir()
    nested = _python(hidden_parent / "source.py")
    parent_link = tmp_path / "nested-visible.py"
    parent_link.symlink_to(nested)
    with pytest.raises(LocalEvidenceError, match="hidden files"):
        build_local_evidence_review([str(parent_link)])


def test_visible_symlink_to_visible_file_is_allowed_and_duplicate_is_rejected(
    tmp_path: Path,
) -> None:
    source = _python(tmp_path / "source.py")
    link = tmp_path / "selected.py"
    link.symlink_to(source)
    report = build_local_evidence_review([str(link)])
    assert report["review_scope"]["selected_artifact_count"] == 1
    assert report["review_scope"]["selected_artifacts"][0]["selected_source"] == str(source)
    with pytest.raises(LocalEvidenceError, match="duplicate"):
        build_local_evidence_review([str(source), str(link)])


def test_hidden_symlink_rejection_is_an_ordinary_customer_error(tmp_path: Path) -> None:
    hidden = _python(tmp_path / ".hidden.py")
    link = tmp_path / "visible.py"
    link.symlink_to(hidden)
    err = io.StringIO()
    with redirect_stderr(err):
        rc = main(["review", "local-evidence", str(link)])
    assert rc == 2
    assert "hidden files" in err.getvalue()
    assert "Traceback" not in err.getvalue()


def test_broken_and_directory_symlinks_use_customer_error_path(tmp_path: Path) -> None:
    broken = tmp_path / "broken.py"
    broken.symlink_to(tmp_path / "missing.py")
    directory_link = tmp_path / "directory.py"
    directory_link.symlink_to(tmp_path, target_is_directory=True)
    for selected, message in (
        (broken, "does not exist"),
        (directory_link, "must be a file"),
    ):
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["review", "local-evidence", str(selected)])
        assert rc == 2
        assert message in err.getvalue()
        assert "Traceback" not in err.getvalue()


def test_local_help_reuses_v2_and_states_oss_boundaries(tmp_path: Path) -> None:
    report = build_local_evidence_review([str(_qasm2(tmp_path / "bell.qasm"))])
    help_payload = report["local_qcoder_help"]
    assert help_payload["schema_id"] == HELP_SCHEMA_ID
    assert help_payload["projection_type"] == "oss_local_evidence"
    assert (
        help_payload["installed_qcoder_version"]
        == "0.6.0a24.post0.dev7+review.confirmed.delivery.v1"
    )
    assert help_payload["local_oss_mode"] is True
    assert help_payload["account_required"] is False
    assert help_payload["qcoder_token_required"] is False
    assert help_payload["explorer_service_used"] is False
    assert help_payload["mcp_required_or_implied"] is False
    assert help_payload["client_qualification_established"] is False
    assert help_payload["explorer_fields"] == "not_applicable"
    validate_help_v2_projection(help_payload)
    assert set(HELP_V2_COMMON_REQUIRED_FIELDS) <= set(help_payload)
    assert set(HELP_V2_PROJECTION_REQUIRED_FIELDS["oss_local_evidence"]) <= set(help_payload)
    assert all(
        action.get("command") or action.get("instruction")
        for action in help_payload["supported_customer_actions"]
    )


def test_help_v2_projection_discriminator_and_extension_fields_are_required(
    tmp_path: Path,
) -> None:
    report = build_local_evidence_review([str(_qasm2(tmp_path / "bell.qasm"))])
    valid = report["local_qcoder_help"]
    for field, error in (
        ("projection_type", "help_v2_common_fields_missing"),
        ("selected_input_kinds", "help_v2_projection_fields_missing"),
        ("account_required", "help_v2_projection_fields_missing"),
    ):
        invalid = dict(valid)
        invalid.pop(field)
        with pytest.raises(ValueError, match=error):
            validate_help_v2_projection(invalid)
    invalid_boundary = dict(valid)
    invalid_boundary["explorer_service_used"] = True
    with pytest.raises(ValueError, match="help_v2_oss_local_boundary_invalid"):
        validate_help_v2_projection(invalid_boundary)


def test_share_safe_defaults_and_each_opt_in_are_explicit(tmp_path: Path) -> None:
    source = _python(tmp_path / "private_source.py")
    source.write_text(
        source.read_text(encoding="utf-8") + 'api_key = "synthetic-secret-value"\n',
        encoding="utf-8",
    )
    qasm = _qasm2(tmp_path / "private.qasm")
    counts = _counts(tmp_path / "private_counts.json")
    counts_payload = json.loads(counts.read_text(encoding="utf-8"))
    counts_payload["token"] = "synthetic-result-token"
    counts.write_text(json.dumps(counts_payload), encoding="utf-8")
    paths = [str(source), str(qasm), str(counts)]
    report = build_local_evidence_review(paths)
    assert report["canonical_identity_reuse"]["result_manifestation"] == (
        RESULT_MANIFESTATION_SCHEMA_ID
    )
    safe = build_share_safe_local_evidence_review(report, paths)
    serialized = json.dumps(safe)
    assert "private_source.py" not in serialized
    assert str(tmp_path) not in serialized
    assert "OPENQASM 2.0" not in serialized
    assert "synthetic-secret-value" not in serialized
    assert "session-artifact-" not in serialized
    assert "artifact_digest" not in serialized
    assert "help_digest" not in serialized

    def all_keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {key for item in value.values() for key in all_keys(item)}
        if isinstance(value, list):
            return {key for item in value for key in all_keys(item)}
        return set()

    assert "counts" not in all_keys(safe)
    assert safe["raw_source_included"] is False
    assert safe["raw_qasm_included"] is False
    assert safe["raw_counts_included"] is False
    assert safe["raw_run_result_payloads_included"] is False
    assert safe["local_paths_included"] is False
    assert safe["customer_filenames_included"] is False
    assert safe["automatic_network_transmission"] is False
    assert safe["customer_inspection_required"] is True

    opted = build_share_safe_local_evidence_review(
        report,
        paths,
        opt_ins={
            "source_excerpts": True,
            "original_qasm": True,
            "normalized_circuit_ir": True,
            "raw_counts": True,
            "raw_run_result_payloads": True,
            "blueprint_material": True,
            "customer_filenames": True,
            "customer_paths": False,
        },
    )
    opted_text = json.dumps(opted)
    assert opted["raw_source_included"] is True
    assert opted["raw_qasm_included"] is True
    assert opted["raw_counts_included"] is True
    assert opted["raw_run_result_payloads_included"] is True
    assert opted["customer_filenames_included"] is True
    assert opted["local_paths_included"] is False
    assert "OPENQASM 2.0" in opted_text
    assert "private_source.py" in opted_text
    assert "synthetic-secret-value" not in opted_text
    assert "synthetic-result-token" not in opted_text
    assert "<redacted-sensitive-value>" in opted_text


@pytest.mark.parametrize(
    "selected_label",
    (
        "/data/project/source.py",
        "/opt/app/circuit.qasm",
        "/srv/work/result.json",
        "project/source.py",
        r"C:\work\source.py",
        r"\\server\share\source.py",
    ),
)
def test_share_safe_redacts_cross_platform_selected_paths_and_next_actions(
    tmp_path: Path, selected_label: str
) -> None:
    source = _python(tmp_path / "selected.py")
    report = build_local_evidence_review([str(source)])
    report["review_scope"]["selected_artifacts"][0]["selected_source"] = selected_label
    report["artifacts"][0]["input"]["selected_source"] = selected_label
    report["artifacts"][0]["canonical_artifacts"][0]["logical_source_label"] = selected_label
    report["supported_next_actions"][0]["command"] = (
        f"qcoder review local-evidence {selected_label}"
    )
    report["local_qcoder_help"]["supported_customer_actions"][0]["command"] = (
        f"qcoder review local-evidence {selected_label}"
    )
    safe = build_share_safe_local_evidence_review(report, [str(source)])
    json_text = json.dumps(safe, sort_keys=True)
    markdown = render_local_evidence_markdown(safe)
    assert selected_label not in json_text
    assert selected_label not in markdown
    assert safe["local_paths_included"] is False


def test_share_safe_path_and_filename_opt_ins_have_truthful_flags(tmp_path: Path) -> None:
    source = _python(tmp_path / "selected.py")
    report = build_local_evidence_review([str(source)])
    filename_only = build_share_safe_local_evidence_review(
        report,
        [str(source)],
        opt_ins={"customer_filenames": True},
    )
    assert filename_only["customer_filenames_included"] is True
    assert filename_only["local_paths_included"] is False
    assert source.name in json.dumps(filename_only)
    assert str(source) not in json.dumps(filename_only)

    with_path = build_share_safe_local_evidence_review(
        report,
        [str(source)],
        opt_ins={"customer_paths": True},
    )
    assert with_path["customer_filenames_included"] is False
    assert with_path["local_paths_included"] is True
    assert str(source) in json.dumps(with_path)


def test_no_network_is_used_and_no_protected_module_is_imported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden_socket(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("unexpected network access")

    monkeypatch.setattr(socket, "socket", forbidden_socket)
    report = build_local_evidence_review([str(_qasm2(tmp_path / "bell.qasm"))])
    assert report["review_scope"]["network_accessed"] is False
    assert report["telemetry_emitted"] is False
    assert report["explorer_service_used"] is False
    source_text = Path("src/qcoder/engines/review/local_evidence.py").read_text(encoding="utf-8")
    assert "qcoder.pro" not in source_text
    assert "context_bridge" not in source_text
    assert "urllib" not in source_text
    assert "requests" not in source_text


def test_cli_local_evidence_does_not_eagerly_import_connected_client_modules(
    tmp_path: Path,
) -> None:
    qasm = _qasm2(tmp_path / "bell.qasm")
    source_root = Path(__file__).resolve().parents[1] / "src"
    probe = (
        "import json,sys; "
        f"sys.path.insert(0,{str(source_root)!r}); "
        "from qcoder.cli import main; "
        f"rc=main(['review','local-evidence',{str(qasm)!r}]); "
        "blocked=sorted(name for name in sys.modules "
        "if name.startswith('qcoder.pro_preview') "
        "or name == 'qcoder.explorer.derived_evidence'); "
        "print(json.dumps({'rc':rc,'blocked':blocked})); "
        "raise SystemExit(0 if rc == 0 and not blocked else 1)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert '"blocked": []' in completed.stdout


def test_guidance_is_visibly_separate_and_preserves_caveats(tmp_path: Path) -> None:
    report = build_local_evidence_review([str(_qasm2(tmp_path / "bell.qasm"))])
    guidance = report["bounded_local_planning_guidance"]
    assert guidance == {
        "status": "not_requested",
        "separate_from_evidence_facts": True,
        "not_optimality_proof": True,
        "not_fidelity_proof": True,
        "not_backend_ranking": True,
        "not_causal_savings": True,
        "structural_proxy_only": True,
    }
    text = json.dumps(report).lower()
    assert "optimal shots" not in text
    assert "backend recommendation" not in text
    assert "fidelity prediction" not in text


def test_cli_writes_outputs_and_local_help_without_internal_choreography(
    tmp_path: Path,
) -> None:
    qasm = _qasm2(tmp_path / "bell.qasm")
    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"
    share_json = tmp_path / "share.json"
    out = io.StringIO()
    with redirect_stdout(out):
        rc = main(
            [
                "review",
                "local-evidence",
                str(qasm),
                "--out-json",
                str(out_json),
                "--out-md",
                str(out_md),
                "--share-safe-json",
                str(share_json),
            ]
        )
    assert rc == 0
    assert out_json.exists() and out_md.exists() and share_json.exists()
    assert "Review local evidence" in out.getvalue()
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["presentation_role"] == "composition_of_existing_canonical_evidence"
    assert report["canonical_identity_reuse"]["replacement_schema_created"] is False
    assert report["canonical_identity_reuse"]["evidence_registry_created"] is False

    help_out = io.StringIO()
    with redirect_stdout(help_out):
        assert main(["review", "local-evidence", str(qasm), "--local-help"]) == 0
    help_payload = json.loads(help_out.getvalue())
    assert help_payload["schema_id"] == HELP_SCHEMA_ID
    assert help_payload["json_choreography_exposed"] is False


def test_human_report_has_stable_coherent_section_order(tmp_path: Path) -> None:
    report = build_local_evidence_review(
        [
            str(_python(tmp_path / "source.py")),
            str(_qasm2(tmp_path / "bell.qasm")),
            str(_counts(tmp_path / "counts.json")),
        ]
    )
    rendered = render_local_evidence_markdown(report)
    headings = [
        "## Review scope",
        "## Provenance",
        "## QASM evidence",
        "## Circuit facts",
        "## Motif evidence",
        "## Factual Run Summary",
        "## Revision evidence",
        "## Warnings and unsupported state",
        "## Bounded local planning guidance",
        "## Share-safe export",
        "## Supported next actions",
        "## Local qCoder Help",
    ]
    offsets = [rendered.index(heading) for heading in headings]
    assert offsets == sorted(offsets)


def test_opt_in_requires_an_explicit_share_safe_output(tmp_path: Path) -> None:
    qasm = _qasm2(tmp_path / "bell.qasm")
    err = io.StringIO()
    with redirect_stderr(err):
        rc = main(
            [
                "review",
                "local-evidence",
                str(qasm),
                "--include-original-qasm",
            ]
        )
    assert rc == 2
    assert "require --share-safe-json or --share-safe-md" in err.getvalue()


def test_docs_have_copyable_journey_and_boundaries() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    guide = (root / "docs" / "local-evidence-review.md").read_text(encoding="utf-8")
    for text in (readme, guide):
        assert "qcoder review local-evidence" in text
        assert "--local-help" in text
        assert "--share-safe-json" in text
        assert "no qcoder account" in text.lower()
        assert "no qcoder token" in text.lower()
        assert "OpenQASM 3" in text
        assert "bounded" in text.lower()
        assert "does not execute" in text.lower()
    assert "receipt ID" not in guide
    assert "artifact reference" not in guide
    assert "schema ID" not in guide
