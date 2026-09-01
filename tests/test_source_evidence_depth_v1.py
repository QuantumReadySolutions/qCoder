from __future__ import annotations

import builtins
import json
from copy import deepcopy
from pathlib import Path
from typing import ClassVar

import pytest

from qcoder.algorithm_blueprint import (
    artifact_digest_matches,
    compact_selected_python_source_evidence_for_hosted,
    extract_selected_python_source_evidence,
)
from qcoder.cli import main as cli_main
from qcoder.context_bridge_mcp import (
    EXPECTED_TOOLS,
    PROMPT_CONTEXT_MODES,
    post_context_bridge,
    tool_descriptors,
)
from qcoder.development_evidence import (
    ALIGNMENT_STATUSES,
    CHOICE_ORIGINS,
    DEVELOPMENT_EVIDENCE_SCHEMA_ID,
    DEVELOPMENT_EVIDENCE_SCHEMA_VERSION,
    EVIDENCE_CONFIDENCE_LABELS,
    IMPLEMENTATION_DECISION_GROUPS,
    INTRODUCED_AFTER_BLUEPRINT_NON_CAUSAL,
    PROFILE_IDS,
    SOURCE_EVIDENCE_DEPTH_DETECTORS,
    SOURCE_EVIDENCE_DEPTH_GATE,
    SOURCE_EVIDENCE_DEPTH_LIMITS,
    SOURCE_EVIDENCE_DEPTH_NEGATIVE_SCOPE,
    USER_CONTROLLED_ACTIONS,
    development_evidence_contract_snapshot,
    validate_development_evidence,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "source_evidence_depth_v1"


def _config() -> dict[str, object]:
    return json.loads((FIXTURE_ROOT / "profiles.json").read_text(encoding="utf-8"))


def _extract(profile_id: str, *, source: str | None = None) -> dict[str, object]:
    fixture = _config()["fixtures"][profile_id]
    source = source or (FIXTURE_ROOT / fixture["source_fixture"]).read_text(encoding="utf-8")
    return extract_selected_python_source_evidence(
        source,
        logical_source_label=fixture["logical_source_label"],
        source_evidence_depth=SOURCE_EVIDENCE_DEPTH_GATE,
        development_evidence_context={
            "source_reference_id": fixture["source_reference_id"],
            "blueprint_reference_id": fixture["blueprint_reference_id"],
            "profile_id": profile_id,
            "expected_requirements": fixture["expected_requirements"],
            "explicit_sdk_version": fixture["explicit_sdk_version"],
        },
    )


def _depth(profile_id: str, *, source: str | None = None) -> dict[str, object]:
    return _extract(profile_id, source=source)["development_evidence"]["source_evidence_depth"]


def _development(profile_id: str, *, source: str | None = None) -> dict[str, object]:
    return _extract(profile_id, source=source)["development_evidence"]


def test_canonical_envelope_is_preserved_and_depth_contract_is_additive() -> None:
    snapshot = development_evidence_contract_snapshot()
    assert snapshot["schema_id"] == DEVELOPMENT_EVIDENCE_SCHEMA_ID
    assert snapshot["schema_version"] == DEVELOPMENT_EVIDENCE_SCHEMA_VERSION == 0
    depth = snapshot["source_evidence_depth"]
    assert depth["gate"] == "depth_v1"
    assert depth["decision_summary_contract"] == "implementation_decision_summary"
    assert depth["decision_summary_version"] == 1
    assert depth["detectors"] == list(SOURCE_EVIDENCE_DEPTH_DETECTORS)
    assert depth["limits"] == SOURCE_EVIDENCE_DEPTH_LIMITS
    assert depth["decision_groups"] == list(IMPLEMENTATION_DECISION_GROUPS)
    assert snapshot["later_stage_analyzers"] == []


def test_omitted_and_disabled_gate_preserve_complete_legacy_artifact() -> None:
    source = "from qiskit import QuantumCircuit\ncircuit = QuantumCircuit(2)\n"
    omitted = extract_selected_python_source_evidence(source, logical_source_label="legacy")
    disabled = extract_selected_python_source_evidence(
        source, logical_source_label="legacy", source_evidence_depth="disabled"
    )
    assert omitted == disabled
    assert "source_evidence_depth" not in omitted
    assert "development_evidence" not in omitted


def test_omitted_and_disabled_gate_preserve_legacy_development_evidence_shape() -> None:
    fixture = _config()["fixtures"]["generic_qiskit"]
    source = (FIXTURE_ROOT / fixture["source_fixture"]).read_text(encoding="utf-8")
    context = {
        "source_reference_id": fixture["source_reference_id"],
        "blueprint_reference_id": fixture["blueprint_reference_id"],
        "profile_id": "generic_qiskit",
        "expected_requirements": fixture["expected_requirements"],
        "explicit_sdk_version": fixture["explicit_sdk_version"],
    }
    omitted = extract_selected_python_source_evidence(
        source,
        logical_source_label="legacy with development context",
        development_evidence_context=context,
    )
    disabled = extract_selected_python_source_evidence(
        source,
        logical_source_label="legacy with development context",
        source_evidence_depth="disabled",
        development_evidence_context=context,
    )
    assert omitted == disabled
    assert "source_evidence_depth" not in omitted
    assert "source_evidence_depth" not in omitted["development_evidence"]
    summary = omitted["development_evidence"]["implementation_decision_summary"]
    assert summary is None or summary["schema_version"] == 0


def test_enabled_gate_without_blueprint_context_returns_bounded_unavailable_status() -> None:
    artifact = extract_selected_python_source_evidence(
        "x = 1\n", logical_source_label="synthetic", source_evidence_depth="depth_v1"
    )
    assert artifact["source_evidence_depth"]["status"] == "unavailable"
    assert "implementation_decision_summary" not in artifact
    assert "development_evidence" not in artifact


def test_unsupported_gate_returns_diagnostic_without_deep_child() -> None:
    artifact = extract_selected_python_source_evidence(
        "x = 1\n", logical_source_label="synthetic", source_evidence_depth="future_depth"
    )
    assert artifact["source_evidence_depth"]["status"] == "unsupported_profile"
    assert artifact["source_evidence_depth"]["diagnostics"]
    assert "development_evidence" not in artifact


def test_parse_failure_returns_parse_limited_without_summary() -> None:
    artifact = _extract("generic_qiskit", source="def broken(:\n")
    development = artifact["development_evidence"]
    depth = development["source_evidence_depth"]
    assert depth["status"] == "parse_limited"
    assert "implementation_decision_summary" not in depth
    assert development["implementation_decision_summary"] is None
    assert validate_development_evidence(development) == "ok"


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_profile_fixture_has_valid_gated_child(profile_id: str) -> None:
    artifact = _extract(profile_id)
    development = artifact["development_evidence"]
    depth = development["source_evidence_depth"]
    assert artifact["source_evidence_depth"] == {
        "gate": "depth_v1",
        "status": "available",
        "child_contract": "implementation_decision_summary",
        "child_version": 1,
    }
    assert depth["status"] == "available"
    assert depth["analysis_unit"] == "one_explicitly_selected_python_source_artifact"
    assert "implementation_decision_summary" not in depth
    assert development["implementation_decision_summary"]["schema_version"] == 1
    assert validate_development_evidence(development) == "ok"
    assert artifact["raw_source_included"] is False
    assert artifact["repository_scanned"] is False
    assert artifact["source_executed"] is False


def test_generic_fixture_reports_safe_facts_and_withholds_arbitrary_literals() -> None:
    depth = _depth("generic_qiskit")
    families = {item["decision_family"] for item in depth["source_facts"]}
    assert "source_declared_quantum_width" in families
    assert "parameter_declaration" in families
    assert "source_visible_measurement" in families
    assert "optimization_level" in families
    assert "seed_value" in families
    serialized = json.dumps(depth, sort_keys=True)
    assert "withhold-this-synthetic-label" not in serialized
    assert '"alpha"' not in serialized
    withheld = [item for item in depth["source_facts"] if item.get("structural_fact")]
    assert any(item["structural_fact"]["structural_category"] == "string" for item in withheld)
    assert any(item["structural_fact"]["structural_category"] == "list" for item in withheld)
    assert all(
        item["structural_fact"]["collection_contents_included"] is False for item in withheld
    )
    scalar_aliases = [item for item in withheld if item["decision_family"] == "safe_local_constant"]
    assert scalar_aliases
    assert all("safe_scalar_fact" not in item for item in scalar_aliases)


def test_grover_fixture_reports_motifs_repetition_and_non_claims() -> None:
    depth = _depth("grover_search")
    families = {item["decision_family"] for item in depth["source_facts"]}
    assert "grover_named_structure" in families
    assert "controlled_operation_structure" in families
    assert "statically_established_repetition" in families
    assert "grover_marked_state_structure" in families
    serialized = json.dumps(depth, sort_keys=True).lower()
    assert '"101"' not in serialized
    assert "oracle correctness" not in serialized
    assert "successful amplification" not in serialized


def test_qaoa_fixture_reports_layers_parameters_binding_and_configuration() -> None:
    depth = _depth("qaoa")
    families = {item["decision_family"] for item in depth["source_facts"]}
    assert "qaoa_cost_layer_structure" in families
    assert "qaoa_mixer_layer_structure" in families
    assert "bounded_parameter_count" in families
    assert "source_visible_parameter_binding" in families
    assert "bounded_shot_count" in families
    assert "source_visible_parameter_use" in families
    assert "qaoa_problem_structure" in families
    serialized = json.dumps(depth, sort_keys=True).lower()
    assert "solution quality" not in serialized
    assert "correct cost hamiltonian" not in serialized


def test_safe_constant_arithmetic_and_static_branch_are_bounded() -> None:
    source = """\
from qiskit import QuantumCircuit
BASE = 2
WIDTH = BASE * 2 - 1
ENABLED = True
circuit = QuantumCircuit(WIDTH, WIDTH)
if ENABLED:
    circuit.measure_all()
"""
    development = _development("generic_qiskit", source=source)
    depth = development["source_evidence_depth"]
    values = [
        item["safe_scalar_fact"]["value"]
        for item in depth["source_facts"]
        if item.get("safe_scalar_fact")
    ]
    assert 3 in values
    assert "statically_established_branch" in {
        item["decision_family"] for item in depth["source_facts"]
    }


def test_imported_helper_dynamic_branch_and_dispatch_are_ambiguous_not_absent() -> None:
    source = """\
from qiskit import QuantumCircuit
from helpers import apply_measurement
def build(flag, operation):
    circuit = QuantumCircuit(2, 2)
    apply_measurement(circuit)
    if flag:
        apply_measurement(circuit)
    operation()(circuit)
    return circuit
"""
    development = _development("generic_qiskit", source=source)
    depth = development["source_evidence_depth"]
    categories = {item["category"] for item in depth["ambiguities"]}
    assert "imported_helper_unresolved" in categories
    assert "dynamic_branch" in categories
    assert "dynamic_dispatch_unresolved" in categories
    measurement = next(
        item
        for item in development["motif_observations"]
        if item["motif_id"] == "qiskit.measurement.mapping"
    )
    assert measurement["observation_status"] == "ambiguous"
    assert "bounded_negative_finding" not in measurement


def test_same_file_helper_depth_and_recursion_are_bounded() -> None:
    source = """\
from qiskit import QuantumCircuit
def level_three(circuit):
    circuit.measure_all()
def level_two(circuit):
    level_three(circuit)
def level_one(circuit):
    level_two(circuit)
def recursive(circuit):
    recursive(circuit)
def build():
    circuit = QuantumCircuit(2, 2)
    level_one(circuit)
    recursive(circuit)
    return circuit
"""
    development = _development("generic_qiskit", source=source)
    depth = development["source_evidence_depth"]
    assert max(item["expansion_depth"] for item in depth["helper_expansion"]) <= 2
    categories = {item["category"] for item in depth["ambiguities"]}
    assert "helper_depth_limit" in categories
    assert "recursive_helper" in categories
    assert not any(
        item["decision_family"] == "source_visible_measurement" for item in depth["source_facts"]
    )
    measurement = next(
        item
        for item in development["motif_observations"]
        if item["motif_id"] == "qiskit.measurement.mapping"
    )
    assert measurement["observation_status"] == "ambiguous"


def test_uncalled_helper_does_not_create_a_source_observation() -> None:
    source = """\
from qiskit import QuantumCircuit
def unused_measurement(circuit):
    circuit.measure_all()
def build():
    return QuantumCircuit(2, 2)
"""
    development = _development("generic_qiskit", source=source)
    depth = development["source_evidence_depth"]
    assert not any(
        item["decision_family"] == "source_visible_measurement" for item in depth["source_facts"]
    )
    measurement = next(
        item
        for item in development["motif_observations"]
        if item["motif_id"] == "qiskit.measurement.mapping"
    )
    assert measurement["observation_status"] == "not_observed"
    assert measurement["bounded_negative_finding"] == SOURCE_EVIDENCE_DEPTH_NEGATIVE_SCOPE


def test_dynamic_repetition_and_unsupported_expression_remain_unknown() -> None:
    source = """\
from qiskit import QuantumCircuit
WIDTH = int(input())
def build(repetitions):
    circuit = QuantumCircuit(WIDTH)
    for _ in range(repetitions):
        circuit.h(0)
    return circuit
"""
    depth = _depth("generic_qiskit", source=source)
    assert "dynamic_repetition" in {item["category"] for item in depth["ambiguities"]}
    assert not any(
        item.get("safe_symbol_reference") == "WIDTH" and item.get("safe_scalar_fact")
        for item in depth["source_facts"]
    )


def test_dynamic_control_flow_does_not_promote_hidden_calls_to_observations() -> None:
    source = """\
from qiskit import QuantumCircuit
def build(flag, repetitions):
    circuit = QuantumCircuit(2, 2)
    if flag:
        circuit.measure_all()
    for _ in range(repetitions):
        circuit.measure_all()
    return circuit
"""
    development = _development("generic_qiskit", source=source)
    depth = development["source_evidence_depth"]
    assert not any(
        item["decision_family"] == "source_visible_measurement" for item in depth["source_facts"]
    )
    categories = {item["category"] for item in depth["ambiguities"]}
    assert {"dynamic_branch", "dynamic_repetition"} <= categories
    measurement = next(
        item
        for item in development["motif_observations"]
        if item["motif_id"] == "qiskit.measurement.mapping"
    )
    assert measurement["observation_status"] == "ambiguous"


def test_statically_false_branch_and_zero_repetition_are_not_traversed() -> None:
    source = """\
from qiskit import QuantumCircuit
ENABLED = False
REPETITIONS = 0
circuit = QuantumCircuit(2, 2)
if ENABLED:
    circuit.measure_all()
for _ in range(REPETITIONS):
    circuit.measure_all()
"""
    development = _development("generic_qiskit", source=source)
    depth = development["source_evidence_depth"]
    assert not any(
        item["decision_family"] == "source_visible_measurement" for item in depth["source_facts"]
    )
    measurement = next(
        item
        for item in development["motif_observations"]
        if item["motif_id"] == "qiskit.measurement.mapping"
    )
    assert measurement["observation_status"] == "not_observed"


def test_arbitrary_numeric_and_byte_literals_are_structural_only() -> None:
    source = """\
from qiskit import QuantumCircuit
PROPRIETARY_SCALAR = 314159
PRIVATE_BYTES = b"private-byte-payload"
circuit = QuantumCircuit(2)
"""
    depth = _depth("generic_qiskit", source=source)
    serialized = json.dumps(depth, sort_keys=True)
    assert "314159" not in serialized
    assert "private-byte-payload" not in serialized
    structures = [
        item["structural_fact"] for item in depth["source_facts"] if item.get("structural_fact")
    ]
    assert any(item["structural_category"] == "safe_scalar_alias" for item in structures)
    assert any(item["structural_category"] == "bytes" for item in structures)


def test_source_level_negative_findings_are_scoped_and_binding_specific() -> None:
    source = """\
from qiskit import QuantumCircuit
from qiskit.circuit import Parameter
theta = Parameter("theta")
circuit = QuantumCircuit(2, 2)
circuit.ry(theta, 0)
circuit.measure_all()
"""
    depth = _depth("generic_qiskit", source=source)
    binding = next(
        item
        for item in depth["source_negative_findings"]
        if item["decision_family"] == "source_visible_parameter_binding"
    )
    assert binding["alignment_status"] == "not_observed"
    assert binding["bounded_observation"] == SOURCE_EVIDENCE_DEPTH_NEGATIVE_SCOPE
    assert binding["inspection_scope_reference"] == "source_evidence_depth.inspection_scope"
    assert binding["what_remains_unproven"]


def test_negative_findings_are_fully_scope_qualified() -> None:
    source = "from qiskit import QuantumCircuit\ncircuit = QuantumCircuit(2)\n"
    development = _development("generic_qiskit", source=source)
    depth = development["source_evidence_depth"]
    negative = [
        item
        for item in development["alignment_findings"]
        if item["alignment_status"] == "not_observed"
    ]
    assert negative
    for item in negative:
        assert item["bounded_observation"] == SOURCE_EVIDENCE_DEPTH_NEGATIVE_SCOPE
        assert item["inspection_scope_reference"] == "source_evidence_depth.inspection_scope"
        assert (
            depth["inspection_scope"]["selected_artifact_reference"]["scope"] == "current_session"
        )
        assert depth["inspection_scope"]["logical_source_label"]
        assert depth["inspection_scope"]["inspection_method"] == "bounded_qiskit_ast_depth_v1"
        assert item["supported_detector_inventory_reference"] == (
            "source_evidence_depth.detector_inventory"
        )
        assert item["what_remains_unproven"]
        assert item["choice_origin"] in {"blueprint_confirmed", "profile_expected"}


def test_introduced_after_blueprint_language_is_non_causal() -> None:
    development = _development("generic_qiskit")
    depth = development["source_evidence_depth"]
    introduced = [
        item
        for item in development["alignment_findings"]
        if item["choice_origin"] == "introduced_after_blueprint"
    ]
    assert introduced
    assert all(item["explanation"] == INTRODUCED_AFTER_BLUEPRINT_NON_CAUSAL for item in introduced)
    serialized = json.dumps(depth, sort_keys=True).lower()
    for forbidden in (
        "ai-selected",
        "model-selected",
        "the model decided",
        "the author intended",
        "hidden reasoning",
    ):
        assert forbidden not in serialized


def test_axes_remain_independent_and_exact() -> None:
    development = _development("generic_qiskit")
    assert len(CHOICE_ORIGINS) == 9
    assert len(EVIDENCE_CONFIDENCE_LABELS) == 6
    assert len(ALIGNMENT_STATUSES) == 8
    introduced = next(
        item
        for item in development["alignment_findings"]
        if item["choice_origin"] == "introduced_after_blueprint"
    )
    assert introduced["evidence_confidence"] == "Observed"
    assert introduced["alignment_status"] == "introduced"


def test_decision_groups_ordering_alternatives_and_actions_are_deterministic() -> None:
    first = _development("qaoa")["implementation_decision_summary"]
    second = _development("qaoa")["implementation_decision_summary"]
    assert first == second
    assert [item["group_id"] for item in first["groups"]] == list(IMPLEMENTATION_DECISION_GROUPS)
    assert first["ordering_basis"] == [
        "confirmed_blueprint_requirement_order",
        "bounded_source_order",
        "maintained_rule_order",
        "canonical_identifier",
    ]
    actions = [
        action
        for group in first["groups"]
        for item in group["items"]
        for action in item.get("suggested_user_controlled_actions", [])
    ]
    assert actions
    assert all(action["action"] in USER_CONTROLLED_ACTIONS for action in actions)
    assert all(action["executed"] is False for action in actions)
    alternatives = [
        alternative
        for group in first["groups"]
        for item in group["items"]
        for alternative in item.get("profile_supported_alternatives", [])
    ]
    assert all(item["provenance"] == "maintained_profile_metadata" for item in alternatives)
    assert all("No alternative is ranked" in item["non_preference"] for item in alternatives)


@pytest.mark.parametrize("version", [None, "2.0.0", "1.4rc1", "unknown"])
def test_depth_does_not_invent_sdk_candidates(version: str | None) -> None:
    fixture = deepcopy(_config()["fixtures"]["generic_qiskit"])
    source = (FIXTURE_ROOT / fixture["source_fixture"]).read_text(encoding="utf-8")
    fixture["explicit_sdk_version"] = version
    artifact = extract_selected_python_source_evidence(
        source,
        logical_source_label="synthetic version case",
        source_evidence_depth="depth_v1",
        development_evidence_context={
            "source_reference_id": fixture["source_reference_id"],
            "blueprint_reference_id": fixture["blueprint_reference_id"],
            "profile_id": "generic_qiskit",
            "expected_requirements": fixture["expected_requirements"],
            "explicit_sdk_version": version,
        },
    )
    facts = artifact["development_evidence"]["framework_version_facts"]
    assert not any(item["fact_kind"] == "version_bounded_candidate_default" for item in facts)


def test_supported_qiskit_candidate_remains_non_effective() -> None:
    development = _extract("generic_qiskit")["development_evidence"]
    candidate = next(
        item
        for item in development["framework_version_facts"]
        if item["fact_kind"] == "version_bounded_candidate_default"
    )
    assert candidate["sdk_version"] == "1.4.2"
    assert candidate["effective_runtime_behavior"] == "unknown"
    assert candidate["choice_origin"] == "sdk_default_candidate"


@pytest.mark.parametrize(
    "transform",
    (
        lambda text: text.replace("build_circuit", "assemble_circuit"),
        lambda text: text.replace("add_entanglement", "apply_pair_structure"),
        lambda text: text.replace("QUBITS", "WIDTH"),
        lambda text: "# moved comment\n\n" + text,
        lambda text: text.replace("QuantumCircuit", "Circuit").replace(
            "from qiskit import Circuit, transpile",
            "from qiskit import QuantumCircuit as Circuit, transpile",
        ),
    ),
)
def test_detector_results_do_not_depend_on_fixture_identity_or_line_positions(transform) -> None:
    source = (FIXTURE_ROOT / "generic_qiskit.py").read_text(encoding="utf-8")
    depth = _depth("generic_qiskit", source=transform(source))
    families = {item["decision_family"] for item in depth["source_facts"]}
    assert "circuit_or_register_construction" in families
    assert "source_visible_measurement" in families


def test_analyzer_does_not_import_execute_evaluate_or_access_network(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("forbidden runtime path used")

    original_import = builtins.__import__
    imported_names: list[str] = []

    def observed_import(name, *args, **kwargs):
        imported_names.append(str(name))
        if str(name).split(".", 1)[0] in {"qiskit", "helpers"}:
            raise AssertionError("selected source import used")
        return original_import(name, *args, **kwargs)

    source = (FIXTURE_ROOT / "generic_qiskit.py").read_text(encoding="utf-8")
    with monkeypatch.context() as context:
        context.setattr(builtins, "eval", forbidden)
        context.setattr(builtins, "exec", forbidden)
        context.setattr(builtins, "__import__", observed_import)
        # Imports required by Python itself are already complete; selected source is parsed only.
        result = _depth("generic_qiskit", source=source)
    assert result["source_imported"] is False
    assert result["source_executed"] is False
    assert result["network_accessed"] is False
    assert not {"qiskit", "helpers"} & {name.split(".", 1)[0] for name in imported_names}


def test_top_level_side_effect_shape_is_parsed_but_never_executed(monkeypatch) -> None:
    def forbidden_open(*_args, **_kwargs):
        raise AssertionError("selected source side effect executed")

    source = """\
from qiskit import QuantumCircuit
open("synthetic-side-effect-marker", "w").write("not-executed")
circuit = QuantumCircuit(2)
"""
    with monkeypatch.context() as context:
        context.setattr(builtins, "open", forbidden_open)
        depth = _depth("generic_qiskit", source=source)
    serialized = json.dumps(depth, sort_keys=True)
    assert "synthetic-side-effect-marker" not in serialized
    assert "not-executed" not in serialized
    assert depth["source_executed"] is False


def test_tool_mode_profile_and_gate_schema_inventories_are_unchanged() -> None:
    assert len(EXPECTED_TOOLS) == 12
    assert len(EXPECTED_TOOLS[:8]) == 8
    assert len(PROMPT_CONTEXT_MODES) == 5
    assert tuple(PROFILE_IDS) == ("generic_qiskit", "grover_search", "qaoa")
    descriptor = next(
        item
        for item in tool_descriptors()
        if item["name"] == "create_source_blueprint_alignment_review"
    )
    source_schema = descriptor["inputSchema"]["properties"]["selected_python_source_evidence"]
    assert source_schema == {"type": "object"}
    assert "create_implementation_decision_summary" not in EXPECTED_TOOLS


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_hosted_projection_is_compact_valid_and_retains_gated_semantics(profile_id: str) -> None:
    local = _extract(profile_id)
    projected = compact_selected_python_source_evidence_for_hosted(local)
    assert len(json.dumps(projected, separators=(",", ":")).encode("utf-8")) < 24_000
    assert artifact_digest_matches(projected) is True
    development = projected["development_evidence"]
    assert validate_development_evidence(development) == "ok"
    assert development["implementation_decision_summary"]["schema_version"] == 1
    depth = development["source_evidence_depth"]
    assert depth["local_detail_omitted_from_hosted_projection"] is True
    assert "source_facts" not in depth
    construction = depth["qiskit_construction_form_observation"]
    assert construction["construction_form_observation"] in {
        "direct_quantum_circuit",
        "explicit_named_registers",
        "ambiguous",
        "not_observed",
    }
    assert construction["boundary"] == ("bounded_static_ast_no_execution_no_equivalence")
    assert depth["motif_observation_inventory"]
    assert depth["inspection_scope"]["selected_artifact_reference"]["scope"] == "current_session"


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_hosted_projection_is_idempotent_for_precompacted_evidence(profile_id: str) -> None:
    projected = compact_selected_python_source_evidence_for_hosted(_extract(profile_id))
    assert compact_selected_python_source_evidence_for_hosted(projected) == projected


def test_context_bridge_automatically_sends_only_compact_depth_projection(tmp_path: Path) -> None:
    captured: list[dict[str, object]] = []

    class Response:
        status = 200
        headers: ClassVar[dict[str, str]] = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b'{"ok":true}'

    def opener(request, timeout=20):
        assert timeout == 20
        captured.append(json.loads(request.data))
        return Response()

    token_file = tmp_path / "token.txt"
    token_file.write_text(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_", encoding="utf-8"
    )
    token_file.chmod(0o600)
    local = _extract("qaoa")
    result = post_context_bridge(
        base_url="https://preview.invalid",
        token_file=token_file,
        tool_name="create_source_blueprint_alignment_review",
        artifact_text=None,
        tool_arguments={
            "implementation_blueprint": {"synthetic": True},
            "output_evidence_contract": {"synthetic": True},
            "selected_python_source_evidence": local,
        },
        opener=opener,
    )
    assert result["ok"] is True, result
    hosted = captured[0]["selected_python_source_evidence"]
    depth = hosted["development_evidence"]["source_evidence_depth"]
    assert "source_facts" not in depth
    assert depth["local_detail_omitted_from_hosted_projection"] is True
    assert len(json.dumps(captured[0], separators=(",", ":")).encode("utf-8")) < 32_768


def test_context_bridge_preserves_precompacted_grover_negative_scope(tmp_path: Path) -> None:
    captured: list[dict[str, object]] = []

    class Response:
        status = 200
        headers: ClassVar[dict[str, str]] = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b'{"ok":true}'

    def opener(request, timeout=20):
        assert timeout == 20
        captured.append(json.loads(request.data))
        return Response()

    token_file = tmp_path / "token.txt"
    token_file.write_text(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_", encoding="utf-8"
    )
    token_file.chmod(0o600)
    projected = compact_selected_python_source_evidence_for_hosted(_extract("grover_search"))
    depth = projected["development_evidence"]["source_evidence_depth"]
    assert depth["negative_alignment_inventory"]
    depth["private_literal"] = "must-not-forward"
    depth["negative_alignment_inventory"][0]["private_literal"] = "must-not-forward"

    result = post_context_bridge(
        base_url="https://preview.invalid",
        token_file=token_file,
        tool_name="create_source_blueprint_alignment_review",
        artifact_text=None,
        tool_arguments={
            "implementation_blueprint": {"synthetic": True},
            "output_evidence_contract": {"synthetic": True},
            "selected_python_source_evidence": projected,
        },
        opener=opener,
    )

    assert result["ok"] is True, result
    hosted = captured[0]["selected_python_source_evidence"]
    hosted_depth = hosted["development_evidence"]["source_evidence_depth"]
    assert hosted_depth["negative_alignment_inventory"] == [
        {
            key: value
            for key, value in depth["negative_alignment_inventory"][0].items()
            if key != "private_literal"
        }
    ]
    assert "must-not-forward" not in json.dumps(captured[0], sort_keys=True)


def test_cli_explicit_gate_and_missing_context_behavior(tmp_path: Path, capsys) -> None:
    source_file = tmp_path / "selected.py"
    source_file.write_text(
        "from qiskit import QuantumCircuit\ncircuit = QuantumCircuit(2)\n",
        encoding="utf-8",
    )
    assert (
        cli_main(
            [
                "blueprint",
                "source-evidence",
                "--source-file",
                str(source_file),
                "--source-evidence-depth",
                "depth_v1",
            ]
        )
        == 2
    )
    capsys.readouterr()
    assert (
        cli_main(
            [
                "blueprint",
                "source-evidence",
                "--source-file",
                str(source_file),
                "--source-evidence-depth",
                "depth_v1",
                "--profile",
                "generic_qiskit",
                "--source-reference",
                "session-artifact-000000000000e101",
                "--blueprint-reference",
                "session-artifact-000000000000e102",
                "--expected-motif",
                "qiskit.circuit.construction",
                "--sdk-version",
                "1.4.2",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["source_evidence_depth"]["status"] == "available"
    assert payload["development_evidence"]["implementation_decision_summary"]["schema_version"] == 1
    assert str(source_file) not in json.dumps(payload)


def test_no_raw_source_path_stable_identifier_or_numerical_confidence() -> None:
    artifact = _extract("generic_qiskit")
    serialized = json.dumps(artifact, sort_keys=True).lower()
    assert "withhold-this-synthetic-label" not in serialized
    assert "/home/" not in serialized
    assert "c:\\" not in serialized
    assert "source_digest" not in serialized
    assert "confidence_score" not in serialized
    assert "assurance_percentage" not in serialized
    assert artifact["development_evidence"]["retention_state"]["retained_artifacts"] == []
