from __future__ import annotations

import json
from pathlib import Path

import pytest

from qcoder.algorithm_blueprint import (
    ALGORITHM_BLUEPRINT_TOOL_NAMES,
    CONFIRMATION_STATES,
    EVIDENCE_CONFIDENCE_LABELS,
    PROFILE_DEFINITIONS,
    PROFILE_IDS,
    algorithm_blueprint_contract_snapshot,
    artifact_digest_matches,
    canonical_artifact_digest,
    extract_selected_python_file_evidence,
    extract_selected_python_source_evidence,
)
from qcoder.cli import main as cli_main
from qcoder.context_bridge_mcp import (
    EXPECTED_TOOLS,
    PROMPT_CONTEXT_MODES,
    TOOL_INPUT_FIELDS,
    post_context_bridge,
    tool_descriptors,
)


EXISTING_TOOLS = (
    "get_guided_evidence_context",
    "create_prompt_context",
    "create_evidence_context_pack",
    "create_context_session_card",
    "create_run_readiness_card",
    "create_result_review_context_card",
    "create_next_check_plan",
    "create_single_loop_evidence_diff",
)


SOURCE = """\
from qiskit import QuantumCircuit
from qiskit.circuit import Parameter

def build_circuit():
    theta = Parameter("theta")
    circuit = QuantumCircuit(2, 2)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.ry(theta, 1)
    circuit.measure([0, 1], [0, 1])
    return circuit
"""


class _Response:
    status = 200
    headers: dict[str, str] = {}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "ok": True,
                "tool_name": "create_source_blueprint_alignment_review",
                "context_status": "source_blueprint_alignment_review_ready",
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }
        ).encode("utf-8")


def _token_file(tmp_path: Path) -> Path:
    token = tmp_path / "token.txt"
    token.write_text("synthetic-not-printed", encoding="utf-8")
    token.chmod(0o600)
    return token


def test_contract_inventory_is_exact_and_profiles_are_only_authorized_three() -> None:
    assert EXPECTED_TOOLS[:8] == EXISTING_TOOLS
    assert EXPECTED_TOOLS[8:] == ALGORITHM_BLUEPRINT_TOOL_NAMES
    assert len(EXPECTED_TOOLS) == 12
    assert len(PROMPT_CONTEXT_MODES) == 5
    assert tuple(PROFILE_IDS) == ("generic_qiskit", "grover_search", "qaoa")
    serialized = json.dumps(algorithm_blueprint_contract_snapshot(), sort_keys=True).lower()
    for unavailable in ("qft", "phase_estimation", "vqe"):
        assert unavailable not in serialized


def test_qaoa_profile_has_questions_and_no_consequential_defaults() -> None:
    qaoa = PROFILE_DEFINITIONS["qaoa"]
    consequential = {
        "mixer_choice",
        "repetitions",
        "parameter_strategy",
        "initialization_strategy",
        "optimizer_boundary",
        "backend_intent",
        "shots",
    }
    assert consequential <= set(qaoa["required_fields"])
    assert consequential <= set(qaoa["questions"])
    assert not any(key.endswith("default") for key in qaoa)


def test_static_extractor_observes_qiskit_structure_without_raw_source() -> None:
    artifact = extract_selected_python_source_evidence(
        SOURCE,
        logical_source_label="synthetic builder excerpt",
    )
    assert artifact["artifact_type"] == "selected_python_source_evidence"
    assert artifact["framework_observation"] == "qiskit"
    assert artifact["parse_status"] == "parsed"
    assert artifact["evidence_coverage"] == "complete"
    assert artifact["circuit_construction_symbols"][0]["declared_sizes"] == [2, 2]
    assert artifact["parameter_declarations"]
    assert artifact["measurement_calls"]
    assert artifact["functions"] == [{"name": "build_circuit", "line": 4}]
    assert artifact["raw_source_included"] is False
    assert artifact["repository_scanned"] is False
    assert artifact["source_executed"] is False
    assert artifact["source_edited"] is False
    assert SOURCE not in json.dumps(artifact, sort_keys=True)
    assert artifact_digest_matches(artifact)


def test_selected_file_is_single_read_only_and_absolute_path_is_removed(tmp_path: Path) -> None:
    source_file = tmp_path / "private" / "selected.py"
    source_file.parent.mkdir()
    source_file.write_text(SOURCE, encoding="utf-8")
    before = source_file.read_bytes()
    artifact = extract_selected_python_file_evidence(
        source_file,
        logical_source_label="selected generated module",
    )
    assert source_file.read_bytes() == before
    assert artifact["safe_basename"] == "selected.py"
    assert str(source_file.resolve()) not in json.dumps(artifact, sort_keys=True)
    assert artifact["origin"] == "local_source_evidence"


def test_partial_ambiguous_and_parse_failure_are_bounded() -> None:
    partial = extract_selected_python_source_evidence(
        SOURCE,
        logical_source_label="selected function",
        selected_symbol="build_circuit",
    )
    assert partial["evidence_coverage"] == "partial"
    ambiguous = extract_selected_python_source_evidence(
        SOURCE,
        logical_source_label="missing symbol",
        selected_symbol="not_present",
    )
    assert ambiguous["evidence_coverage"] == "ambiguous"
    failed = extract_selected_python_source_evidence(
        "def broken(:\n    pass",
        logical_source_label="invalid excerpt",
    )
    assert failed["parse_status"] == "parse_failed"
    assert failed["evidence_coverage"] == "ambiguous"
    assert failed["raw_source_included"] is False


def test_bounded_line_span_preserves_original_source_references() -> None:
    source = "# omitted header\n# omitted metadata\n" + SOURCE
    artifact = extract_selected_python_source_evidence(
        source,
        logical_source_label="bounded selected span",
        line_span=(3, 13),
    )
    assert artifact["bounded_line_span"] == [3, 13]
    assert artifact["functions"] == [{"name": "build_circuit", "line": 6}]
    assert min(artifact["source_references"]) >= 6


def test_selected_symbol_excludes_unselected_top_level_symbols() -> None:
    source = SOURCE + "\ndef unrelated_helper():\n    return 'not selected'\n"
    artifact = extract_selected_python_source_evidence(
        source,
        logical_source_label="selected builder",
        selected_symbol="build_circuit",
    )
    assert artifact["evidence_coverage"] == "partial"
    assert artifact["functions"] == [{"name": "build_circuit", "line": 4}]
    assert "unrelated_helper" not in json.dumps(artifact, sort_keys=True)


def test_top_level_side_effect_import_and_exec_are_never_run(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    source = (
        "import definitely_missing_private_dependency\n"
        f"open({str(marker)!r}, 'w').write('bad')\n"
        "exec(\"raise RuntimeError('bad')\")\n"
        "raise RuntimeError('also bad')\n"
    )
    artifact = extract_selected_python_source_evidence(
        source,
        logical_source_label="side-effect safety fixture",
    )
    assert artifact["parse_status"] == "parsed"
    assert not marker.exists()
    assert artifact["source_executed"] is False
    assert artifact["imports_and_aliases"][0]["module"] == "definitely_missing_private_dependency"


def test_cli_selected_file_and_stdin_emit_only_compact_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_file = tmp_path / "selected.py"
    source_file.write_text(SOURCE, encoding="utf-8")
    assert cli_main(["blueprint", "source-evidence", "--source-file", str(source_file)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["safe_basename"] == "selected.py"
    assert payload["raw_source_included"] is False

    class _Stdin:
        @staticmethod
        def read() -> str:
            return SOURCE

    monkeypatch.setattr("qcoder.cli.sys.stdin", _Stdin())
    assert cli_main(["blueprint", "source-evidence", "--excerpt-stdin"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["logical_source_label"] == "stdin excerpt"
    assert payload["origin"] == "explicitly_supplied_source_excerpt"


def test_new_tool_schemas_have_no_hosted_path_or_raw_source_field() -> None:
    schemas = {item["name"]: item["inputSchema"] for item in tool_descriptors()}
    assert set(ALGORITHM_BLUEPRINT_TOOL_NAMES) <= set(schemas)
    for tool_name in ALGORITHM_BLUEPRINT_TOOL_NAMES:
        serialized = json.dumps(schemas[tool_name], sort_keys=True)
        assert "file_path" not in serialized
        assert "repository_root" not in serialized
        assert "workspace_path" not in serialized
        assert '"raw_source"' not in serialized
    alignment_properties = schemas["create_source_blueprint_alignment_review"]["properties"]
    assert "selected_python_source_evidence" in alignment_properties


def test_adapter_forwards_compact_evidence_only_and_rejects_path_fields(tmp_path: Path) -> None:
    source = extract_selected_python_source_evidence(
        SOURCE,
        logical_source_label="synthetic excerpt",
    )
    blueprint = {
        "artifact_type": "implementation_blueprint",
        "schema_version": 1,
        "artifact_digest": "b" * 64,
        "confirmation_state": "confirmed",
    }
    contract = {
        "artifact_type": "output_evidence_contract",
        "schema_version": 1,
        "artifact_digest": "c" * 64,
        "parent_artifact_digest": "b" * 64,
        "expected_evidence": {},
    }
    captured: list[dict[str, object]] = []

    def opener(request: object, timeout: int) -> _Response:
        assert timeout == 20
        body = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        captured.append(body)
        return _Response()

    payload = post_context_bridge(
        base_url="https://example.invalid",
        token_file=_token_file(tmp_path),
        tool_name="create_source_blueprint_alignment_review",
        artifact_text=None,
        tool_arguments={
            "implementation_blueprint": blueprint,
            "output_evidence_contract": contract,
            "selected_python_source_evidence": source,
        },
        opener=opener,
    )
    assert payload["ok"] is True, payload
    assert len(captured) == 1
    serialized = json.dumps(captured[0], sort_keys=True)
    assert SOURCE not in serialized
    assert "file_path" not in serialized
    assert captured[0]["selected_python_source_evidence"]["raw_source_included"] is False

    rejected = post_context_bridge(
        base_url="https://example.invalid",
        token_file=_token_file(tmp_path),
        tool_name="create_source_blueprint_alignment_review",
        artifact_text=None,
        tool_arguments={
            "implementation_blueprint": blueprint,
            "output_evidence_contract": contract,
            "selected_python_source_evidence": source,
            "file_path": "/private/source.py",
        },
        opener=opener,
    )
    assert rejected["error_category"] == "unsupported_tool_argument"
    assert len(captured) == 1


def test_digest_labels_and_confirmation_values_match_public_contract() -> None:
    artifact = {"schema_version": 1, "artifact_type": "synthetic", "value": 1}
    assert canonical_artifact_digest(artifact) == canonical_artifact_digest(
        {"value": 1, "artifact_type": "synthetic", "schema_version": 1}
    )
    assert tuple(CONFIRMATION_STATES) == ("proposed", "needs_clarification", "confirmed")
    assert [display for _value, display in EVIDENCE_CONFIDENCE_LABELS] == [
        "Observed",
        "User-provided",
        "Inferred",
        "Assumed",
        "Not proven",
        "Suggested next check",
    ]
    assert set(TOOL_INPUT_FIELDS["create_source_blueprint_alignment_review"]) == {
        "artifact_kind",
        "client_context",
        "implementation_blueprint",
        "output_evidence_contract",
        "selected_python_source_evidence",
    }


def test_package_help_and_examples_keep_capabilities_and_boundaries_distinct(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    architecture = (root / "docs" / "architecture.md").read_text(encoding="utf-8")
    example = (root / "examples" / "09_algorithm_blueprint.md").read_text(encoding="utf-8")
    combined = "\n".join((readme, architecture, example))
    for term in (
        "Algorithm Blueprint",
        "Evidence Review",
        "Context Bridge",
        "Circuit Workbench",
        "Explorer Evidence Loop",
        "ChatGPT",
    ):
        assert term in combined
    lowered = combined.lower()
    normalized = " ".join(lowered.split())
    assert "generation and editing occur outside qcoder" in normalized
    assert "machine-local" in normalized
    assert "not a connected context bridge integration" in normalized
    assert "do not prove algorithm identity" in normalized
    assert "does not claim publication or public rollout" in normalized
    assert "qft" not in example.lower()
    assert "phase estimation" not in example.lower()
    assert "vqe" not in example.lower()

    with pytest.raises(SystemExit) as exc_info:
        cli_main(["blueprint", "--help"])
    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "source-evidence" in help_text
    assert "machine-local" in help_text
