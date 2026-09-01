from __future__ import annotations

import builtins
import json
import re
from pathlib import Path

import pytest

from qcoder.algorithm_blueprint import (
    artifact_digest_matches,
    extract_selected_python_source_evidence,
)
from qcoder.context_bridge_mcp import EXPECTED_TOOLS, PROMPT_CONTEXT_MODES, tool_descriptors
from qcoder.development_evidence import (
    ALIGNMENT_STATUSES,
    CHOICE_ORIGINS,
    DEVELOPMENT_EVIDENCE_SCHEMA_ID,
    DEVELOPMENT_EVIDENCE_SCHEMA_VERSION,
    DEVELOPMENT_STAGES,
    EVIDENCE_CONFIDENCE_LABELS,
    MOTIF_REGISTRY,
    PROFILE_IDS,
    RELATIONSHIP_TYPES,
    RETENTION_STATE,
    WORKING_TRANSITIONS,
    artifact_reference,
    development_evidence_contract_snapshot,
    extract_qiskit_source_development_evidence,
    relationship_declaration,
    validate_development_evidence,
    validate_relationship_declaration,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "development_evidence_v0"


def _fixture_config() -> dict[str, object]:
    return json.loads((FIXTURE_ROOT / "profiles.json").read_text(encoding="utf-8"))


def _run_fixture(profile_id: str, *, source_text: str | None = None) -> dict[str, object]:
    fixture = _fixture_config()["fixtures"][profile_id]
    if source_text is None:
        source_text = (FIXTURE_ROOT / fixture["source_fixture"]).read_text(encoding="utf-8")
    blueprint = fixture["implementation_blueprint"]
    return extract_qiskit_source_development_evidence(
        source_text,
        logical_source_label=fixture["logical_source_label"],
        source_reference_id=fixture["source_reference_id"],
        blueprint_reference_id=fixture["blueprint_reference_id"],
        profile_id=profile_id,
        expected_requirements=blueprint["expected_requirements"],
        explicit_sdk_version=fixture["explicit_sdk_version"],
    )


def test_contract_inventory_is_exact_and_has_one_working_transition() -> None:
    assert DEVELOPMENT_EVIDENCE_SCHEMA_ID == "qcoder.development_evidence.v0"
    assert DEVELOPMENT_EVIDENCE_SCHEMA_VERSION == 0
    assert DEVELOPMENT_STAGES == (
        "human_intent",
        "python_source",
        "logical_circuit",
        "target_circuit",
        "run_results",
        "next_human_intent",
    )
    assert WORKING_TRANSITIONS == (("human_intent", "python_source"),)
    assert RELATIONSHIP_TYPES == (
        "specified_by",
        "implements",
        "constructs",
        "represented_as",
        "transformed_into",
        "executed_with",
        "produces",
        "interpreted_by",
        "derived_from",
    )
    assert CHOICE_ORIGINS == (
        "human_specified",
        "blueprint_confirmed",
        "explicit_in_source",
        "introduced_after_blueprint",
        "profile_expected",
        "sdk_default_candidate",
        "target_derived",
        "runtime_derived",
        "unknown",
    )
    assert EVIDENCE_CONFIDENCE_LABELS == (
        "Observed",
        "User-provided",
        "Inferred",
        "Assumed",
        "Not proven",
        "Suggested next check",
    )
    assert ALIGNMENT_STATUSES == (
        "appears_aligned",
        "partially_aligned",
        "introduced",
        "not_observed",
        "ambiguous",
        "conflicting",
        "requires_next_stage_evidence",
        "not_applicable",
    )


def test_canonical_snapshot_identifies_qcoder_and_has_no_later_stage_analyzers() -> None:
    snapshot = development_evidence_contract_snapshot()
    assert snapshot["canonical_authority"] == {
        "repository": "qcoder",
        "source": "src/qcoder/development_evidence.py",
        "generator": "development_evidence_contract_snapshot",
    }
    assert snapshot["later_stage_analyzers"] == []
    assert snapshot["transitive_inference"] is False
    assert snapshot["graph_traversal"] is False
    assert snapshot["automatic_lookup"] is False


def test_artifact_references_are_opaque_session_local_and_non_retrievable() -> None:
    reference = artifact_reference("session-artifact-000000000000a17d")
    assert reference["scope"] == "current_session"
    assert reference["retrievable"] is False
    assert reference["authentication_use"] is False
    assert reference["proof_use"] is False
    assert reference["cross_session_correlation"] is False
    for invalid in (
        "source.py",
        "/tmp/source.py",
        "a" * 64,
        "session-artifact-short",
        "session-artifact-customer-source",
    ):
        with pytest.raises(ValueError, match="invalid_session_artifact_reference"):
            artifact_reference(invalid)


def test_relationship_requires_direction_basis_status_and_non_proof() -> None:
    relationship = relationship_declaration(
        relationship_type="implements",
        source_stage="human_intent",
        target_stage="python_source",
        source_reference_id="session-artifact-00000000000000a1",
        target_reference_id="session-artifact-00000000000000a2",
        supplied_evidence_basis="explicitly_supplied_blueprint_and_source",
        declaration_state="observed",
        non_proof="This does not prove correctness.",
    )
    assert relationship["direction"] == "human_intent_to_python_source"
    assert validate_relationship_declaration(relationship) == "ok"
    mutated = {**relationship, "direction": "python_source_to_human_intent"}
    assert validate_relationship_declaration(mutated) == "noncanonical_relationship_declaration"


def test_motif_registry_has_unique_ids_and_schema_only_future_indicators() -> None:
    assert len(MOTIF_REGISTRY) == 12
    assert len(MOTIF_REGISTRY) == len(set(MOTIF_REGISTRY))
    assert set(PROFILE_IDS) == {"generic_qiskit", "grover_search", "qaoa"}
    for motif_id, motif in MOTIF_REGISTRY.items():
        assert motif["motif_id"] == motif_id
        assert motif["applicable_stage"] == "python_source"
        assert motif["source_indicators"]
        assert all("prospective only" in item for item in motif["logical_circuit_indicators"])
        assert all("prospective only" in item for item in motif["target_circuit_indicators"])
        assert motif["limitations_and_non_claims"]


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_reference_profile_fixture_is_current_session_static_and_valid(profile_id: str) -> None:
    result = _run_fixture(profile_id)
    assert validate_development_evidence(result) == "ok"
    assert result["development_stage"] == "python_source"
    assert result["working_transition"] == ["human_intent", "python_source"]
    assert result["later_stage_analysis_performed"] is False
    assert result["retention_state"] == RETENTION_STATE
    assert result["source_evidence"]["raw_source_included"] is False
    assert result["source_evidence"]["raw_path_included"] is False
    assert result["source_evidence"]["repository_scanned"] is False
    assert result["source_evidence"]["source_imported"] is False
    assert result["source_evidence"]["source_executed"] is False
    assert result["source_evidence"]["source_edited"] is False


def test_generic_fixture_covers_confirmed_observed_introduced_and_sdk_candidate() -> None:
    result = _run_fixture("generic_qiskit")
    findings = {item["expected_item"]: item for item in result["alignment_findings"]}
    assert findings["qiskit.circuit.construction"]["alignment_status"] == "appears_aligned"
    assert findings["qiskit.measurement.mapping"]["choice_origin"] == "blueprint_confirmed"
    assert findings["qiskit.controlled.operations"]["alignment_status"] == "introduced"
    assert findings["qiskit.controlled.operations"]["choice_origin"] == "introduced_after_blueprint"
    candidate = next(
        item
        for item in result["framework_version_facts"]
        if item["fact_kind"] == "version_bounded_candidate_default"
    )
    assert candidate["sdk_version"] == "1.4.2"
    assert candidate["candidate_value"] is True
    assert candidate["effective_runtime_behavior"] == "unknown"
    assert candidate["choice_origin"] == "sdk_default_candidate"
    assert result["implementation_decision_summary"]["independent_artifact"] is False


def test_grover_fixture_separates_expectation_observation_and_ambiguity() -> None:
    result = _run_fixture("grover_search")
    expectations = {item["motif_id"]: item for item in result["motif_expectations"]}
    observations = {item["motif_id"]: item for item in result["motif_observations"]}
    assert expectations["grover.oracle.structure"]["choice_origin"] == "blueprint_confirmed"
    assert expectations["grover.diffusion.amplification"]["choice_origin"] == "profile_expected"
    assert observations["grover.oracle.structure"]["observation_status"] == "observed"
    assert observations["grover.diffusion.amplification"]["observation_status"] == "observed"
    assert observations["grover.iteration.structure"]["observation_status"] == "ambiguous"
    iteration = next(
        item
        for item in result["alignment_findings"]
        if item["expected_item"] == "grover.iteration.structure"
    )
    assert iteration["alignment_status"] == "requires_next_stage_evidence"
    assert iteration["required_next_evidence"] == "logical_circuit"


def test_qaoa_fixture_detects_layers_without_claiming_runtime() -> None:
    result = _run_fixture("qaoa")
    observations = {item["motif_id"]: item for item in result["motif_observations"]}
    assert observations["qaoa.cost.layer"]["observation_status"] == "observed"
    assert observations["qaoa.mixer.layer"]["observation_status"] == "observed"
    assert observations["qaoa.parameterized.layer"]["observation_status"] == "observed"
    assert observations["qaoa.repetition.layer"]["observation_status"] == "ambiguous"
    serialized = json.dumps(result, sort_keys=True).lower()
    assert "backend used" not in serialized
    assert "runtime verified" not in serialized
    assert "correct implementation" not in serialized


def test_negative_motif_language_is_bounded_to_supplied_artifact() -> None:
    result = _run_fixture("generic_qiskit")
    negative = [
        item
        for item in result["motif_observations"]
        if item["observation_status"] == "not_observed"
    ]
    assert negative
    assert all(
        item["bounded_negative_finding"]
        == "Not observed in the explicitly supplied artifact using the stated bounded inspection method."
        for item in negative
    )
    assert all(item["required_next_stage_evidence"] for item in negative)


def test_version_facts_do_not_promote_no_override_to_effective_value() -> None:
    result = _run_fixture("generic_qiskit")
    no_override = next(
        item
        for item in result["framework_version_facts"]
        if item["fact_kind"] == "no_explicit_override_observed"
    )
    assert no_override["effective_runtime_behavior"] == "unknown"
    assert "does not mean" in no_override["non_proof"]
    assert not any(item.get("effective_value_proven") for item in result["framework_version_facts"])


@pytest.mark.parametrize("version", [None, "2.0.0", "1.4rc1", "unknown"])
def test_missing_ambiguous_or_unsupported_versions_remain_unknown(version: str | None) -> None:
    fixture = _fixture_config()["fixtures"]["generic_qiskit"]
    source = (FIXTURE_ROOT / fixture["source_fixture"]).read_text(encoding="utf-8")
    result = extract_qiskit_source_development_evidence(
        source,
        logical_source_label="synthetic unsupported version",
        source_reference_id="session-artifact-0000000000000101",
        blueprint_reference_id="session-artifact-0000000000000102",
        profile_id="generic_qiskit",
        expected_requirements=fixture["implementation_blueprint"]["expected_requirements"],
        explicit_sdk_version=version,
    )
    assert not any(
        item["fact_kind"] == "version_bounded_candidate_default"
        for item in result["framework_version_facts"]
    )
    assert any(
        item["fact_kind"] == "unknown_effective_runtime_behavior"
        for item in result["framework_version_facts"]
    )


def test_explicit_source_override_remains_source_fact_not_default_candidate() -> None:
    source = """\
from qiskit import QuantumCircuit
circuit = QuantumCircuit(2, 2)
circuit.measure_all(add_bits=False)
"""
    result = extract_qiskit_source_development_evidence(
        source,
        logical_source_label="synthetic explicit measurement",
        source_reference_id="session-artifact-0000000000000201",
        blueprint_reference_id="session-artifact-0000000000000202",
        profile_id="generic_qiskit",
        expected_requirements=[
            {"motif_id": "qiskit.measurement.mapping", "choice_origin": "blueprint_confirmed"}
        ],
        explicit_sdk_version="1.4.2",
    )
    fact = next(
        item
        for item in result["framework_version_facts"]
        if item["fact_kind"] == "explicit_source_configuration"
    )
    assert fact["value"] is False
    assert fact["choice_origin"] == "explicit_in_source"
    assert not any(
        item["fact_kind"] == "version_bounded_candidate_default"
        for item in result["framework_version_facts"]
    )


def test_unresolved_explicit_override_is_not_rewritten_as_no_override_or_default() -> None:
    source = """\
from qiskit import QuantumCircuit
USE_BITS = object()
circuit = QuantumCircuit(2, 2)
circuit.measure_all(add_bits=USE_BITS)
"""
    result = extract_qiskit_source_development_evidence(
        source,
        logical_source_label="synthetic unresolved measurement",
        source_reference_id="session-artifact-0000000000000203",
        blueprint_reference_id="session-artifact-0000000000000204",
        profile_id="generic_qiskit",
        expected_requirements=[
            {"motif_id": "qiskit.measurement.mapping", "choice_origin": "blueprint_confirmed"}
        ],
        explicit_sdk_version="1.4.2",
    )
    kinds = {item["fact_kind"] for item in result["framework_version_facts"]}
    assert "explicit_source_configuration_unresolved" in kinds
    assert "no_explicit_override_observed" not in kinds
    assert "version_bounded_candidate_default" not in kinds


def test_local_environment_fact_is_used_only_when_explicitly_supplied() -> None:
    fixture = _fixture_config()["fixtures"]["generic_qiskit"]
    source = (FIXTURE_ROOT / fixture["source_fixture"]).read_text(encoding="utf-8")
    result = extract_qiskit_source_development_evidence(
        source,
        logical_source_label="synthetic explicit environment",
        source_reference_id="session-artifact-0000000000000301",
        blueprint_reference_id="session-artifact-0000000000000302",
        profile_id="generic_qiskit",
        expected_requirements=fixture["implementation_blueprint"]["expected_requirements"],
        explicit_local_environment_version="1.4.3",
    )
    local = next(
        item
        for item in result["framework_version_facts"]
        if item["fact_kind"] == "explicit_caller_supplied_local_environment_observation"
    )
    assert local["effective_runtime_behavior"] == "unknown"
    assert not any(
        item["fact_kind"] == "version_bounded_candidate_default"
        for item in result["framework_version_facts"]
    )


def test_syntax_error_is_bounded_and_never_falls_back_to_import() -> None:
    result = extract_qiskit_source_development_evidence(
        "from qiskit import QuantumCircuit\ndef broken(:\n",
        logical_source_label="synthetic syntax error",
        source_reference_id="session-artifact-0000000000000401",
        blueprint_reference_id="session-artifact-0000000000000402",
        profile_id="generic_qiskit",
        expected_requirements=[
            {"motif_id": "qiskit.circuit.construction", "choice_origin": "blueprint_confirmed"}
        ],
    )
    assert result["source_evidence"]["parse_status"] == "parse_failed"
    assert result["unresolved_questions"]
    assert result["source_evidence"]["source_imported"] is False
    assert result["source_evidence"]["source_executed"] is False
    assert all(item["observation_status"] == "ambiguous" for item in result["motif_observations"])
    assert all(
        item["alignment_status"] == "requires_next_stage_evidence"
        for item in result["alignment_findings"]
    )


@pytest.mark.parametrize(
    ("logical_label", "version"),
    [
        ("../private/source.py", "1.4.2"),
        (r"C:\\private\\source.py", "1.4.2"),
        ("synthetic source", "../../private-version"),
    ],
)
def test_local_paths_cannot_enter_logical_labels_or_version_facts(
    logical_label: str, version: str
) -> None:
    fixture = _fixture_config()["fixtures"]["generic_qiskit"]
    source = (FIXTURE_ROOT / fixture["source_fixture"]).read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        extract_qiskit_source_development_evidence(
            source,
            logical_source_label=logical_label,
            source_reference_id="session-artifact-0000000000000403",
            blueprint_reference_id="session-artifact-0000000000000404",
            profile_id="generic_qiskit",
            expected_requirements=fixture["implementation_blueprint"]["expected_requirements"],
            explicit_sdk_version=version,
        )


def test_selected_source_is_not_imported_executed_or_followed(monkeypatch, tmp_path: Path) -> None:
    marker = tmp_path / "should-not-exist"
    source = f"""\
import qiskit
import synthetic_dependency_that_must_not_load
open({str(marker)!r}, "w").write("unexpected")
"""
    original_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith(("qiskit", "synthetic_dependency")):
            raise AssertionError("selected source import attempted")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    result = extract_qiskit_source_development_evidence(
        source,
        logical_source_label="synthetic side effect",
        source_reference_id="session-artifact-0000000000000501",
        blueprint_reference_id="session-artifact-0000000000000502",
        profile_id="generic_qiskit",
        expected_requirements=[],
    )
    assert not marker.exists()
    assert result["source_evidence"]["imports_followed"] is False
    assert result["source_evidence"]["source_executed"] is False


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_detector_is_not_coupled_to_names_formatting_or_line_positions(profile_id: str) -> None:
    fixture = _fixture_config()["fixtures"][profile_id]
    source = (FIXTURE_ROOT / fixture["source_fixture"]).read_text(encoding="utf-8")
    baseline = _run_fixture(profile_id, source_text=source)
    mutated = "\n\n# harmless variation\n" + source.replace("circuit", "program_wire")
    varied = _run_fixture(profile_id, source_text=mutated)
    baseline_statuses = {
        item["motif_id"]: item["observation_status"] for item in baseline["motif_observations"]
    }
    varied_statuses = {
        item["motif_id"]: item["observation_status"] for item in varied["motif_observations"]
    }
    assert varied_statuses == baseline_statuses
    assert (
        baseline["source_evidence"]["source_references"]
        != varied["source_evidence"]["source_references"]
    )


def test_three_axes_remain_independent() -> None:
    result = _run_fixture("generic_qiskit")
    expectations = {
        item["motif_id"]: (item["choice_origin"], item["evidence_confidence"])
        for item in result["motif_expectations"]
    }
    assert expectations["qiskit.circuit.construction"] == (
        "blueprint_confirmed",
        "User-provided",
    )
    combinations = {
        (
            item["alignment_status"],
            item["evidence_confidence"],
            item["choice_origin"],
        )
        for item in result["alignment_findings"]
    }
    assert ("appears_aligned", "Inferred", "blueprint_confirmed") in combinations
    assert ("introduced", "Observed", "introduced_after_blueprint") in combinations


def test_share_safe_output_has_no_raw_source_path_or_stable_source_digest() -> None:
    source = (FIXTURE_ROOT / "generic_qiskit.py").read_text(encoding="utf-8")
    first = _run_fixture("generic_qiskit", source_text=source)
    serialized = json.dumps(first, sort_keys=True)
    assert source not in serialized
    assert str(FIXTURE_ROOT) not in serialized
    assert "artifact_digest" not in first
    assert not re.search(r'"[a-f0-9]{64}"', serialized)
    contaminated = {**first, "source_path": "/private/source.py"}
    assert validate_development_evidence(contaminated) == "development_evidence_forbidden_field"


def test_algorithm_blueprint_optional_integration_is_additive_and_session_bounded() -> None:
    source = (FIXTURE_ROOT / "generic_qiskit.py").read_text(encoding="utf-8")
    context = {
        "source_reference_id": "session-artifact-0000000000000601",
        "blueprint_reference_id": "session-artifact-0000000000000602",
        "profile_id": "generic_qiskit",
        "expected_requirements": [
            {"motif_id": "qiskit.circuit.construction", "choice_origin": "blueprint_confirmed"}
        ],
        "explicit_sdk_version": "1.4.2",
    }
    enriched = extract_selected_python_source_evidence(
        source,
        logical_source_label="synthetic integrated source",
        development_evidence_context=context,
    )
    legacy = extract_selected_python_source_evidence(
        source,
        logical_source_label="synthetic integrated source",
    )
    changed_reference = extract_selected_python_source_evidence(
        source,
        logical_source_label="synthetic integrated source",
        development_evidence_context={
            **context,
            "source_reference_id": "session-artifact-0000000000000603",
        },
    )
    assert "development_evidence" not in legacy
    assert validate_development_evidence(enriched["development_evidence"]) == "ok"
    assert artifact_digest_matches(enriched)
    assert enriched["artifact_digest"] != changed_reference["artifact_digest"]


def test_context_bridge_schema_remains_twelve_tools_five_modes_and_optional_delta() -> None:
    assert len(EXPECTED_TOOLS) == 12
    assert len(PROMPT_CONTEXT_MODES) == 5
    descriptor = next(
        item
        for item in tool_descriptors()
        if item["name"] == "create_source_blueprint_alignment_review"
    )
    source_schema = descriptor["inputSchema"]["properties"]["selected_python_source_evidence"]
    assert source_schema == {"type": "object"}


def test_no_numerical_confidence_or_effective_runtime_claim() -> None:
    serialized = json.dumps(_run_fixture("generic_qiskit"), sort_keys=True).lower()
    for forbidden in (
        "confidence_score",
        "probability_score",
        "assurance_percentage",
        "high confidence",
        "effective runtime value was used",
    ):
        assert forbidden not in serialized
