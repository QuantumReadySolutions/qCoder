"""Canonical Development Evidence v0 contracts and local Qiskit reference adapter.

The adapter inspects only explicitly supplied Python text. It never imports or
executes that text, follows imports, discovers directories, or reads runtime state.
"""

from __future__ import annotations

import ast
from copy import deepcopy
import math
import re
from typing import Any, Mapping, Sequence


DEVELOPMENT_EVIDENCE_SCHEMA_ID = "qcoder.development_evidence.v0"
DEVELOPMENT_EVIDENCE_SCHEMA_VERSION = 0
CANONICAL_CONTRACT_SOURCE = "src/qcoder/development_evidence.py"
CANONICAL_SNAPSHOT_GENERATOR = "development_evidence_contract_snapshot"

DEVELOPMENT_STAGES = (
    "human_intent",
    "python_source",
    "logical_circuit",
    "target_circuit",
    "run_results",
    "next_human_intent",
)
WORKING_TRANSITIONS = (("human_intent", "python_source"),)
RELATIONSHIP_TYPES = (
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
RELATIONSHIP_DECLARATION_STATES = ("expected", "observed", "prospective")
CHOICE_ORIGINS = (
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
EVIDENCE_CONFIDENCE_LABELS = (
    "Observed",
    "User-provided",
    "Inferred",
    "Assumed",
    "Not proven",
    "Suggested next check",
)
ALIGNMENT_STATUSES = (
    "appears_aligned",
    "partially_aligned",
    "introduced",
    "not_observed",
    "ambiguous",
    "conflicting",
    "requires_next_stage_evidence",
    "not_applicable",
)
PROFILE_IDS = ("generic_qiskit", "grover_search", "qaoa")
SOURCE_EVIDENCE_DEPTH_GATE = "depth_v1"
SOURCE_EVIDENCE_DEPTH_DISABLED = "disabled"
SOURCE_EVIDENCE_DEPTH_STATUSES = (
    "available",
    "parse_limited",
    "unavailable",
    "unsupported_profile",
)
IMPLEMENTATION_DECISION_SUMMARY_CONTRACT = "implementation_decision_summary"
IMPLEMENTATION_DECISION_SUMMARY_VERSION = 1
SOURCE_EVIDENCE_DEPTH_DETECTORS = (
    "qiskit.imports.v1",
    "qiskit.api.references.v1",
    "qiskit.circuit.construction.v1",
    "qiskit.register.width.v1",
    "qiskit.helper.expansion.v1",
    "python.safe.constant.v1",
    "python.loop.repetition.v1",
    "python.branch.structure.v1",
    "qiskit.parameter.declaration.v1",
    "qiskit.parameter.binding.v1",
    "qiskit.measurement.v1",
    "qiskit.bit_order.v1",
    "qiskit.execution.configuration.v1",
    "qiskit.result.processing.v1",
    "profile.grover.structure.v1",
    "profile.qaoa.structure.v1",
)
IMPLEMENTATION_DECISION_GROUPS = (
    "blueprint_confirmed_choices",
    "choices_introduced_after_blueprint",
    "explicit_source_configuration",
    "profile_expected_structures",
    "ambiguous_or_dynamic_behavior",
    "sdk_default_candidates",
    "requires_logical_circuit_evidence",
    "suggested_next_actions",
)
USER_CONTROLLED_ACTIONS = (
    "Accept and add to blueprint",
    "Clarify the requirement",
    "Constrain the next generation",
    "Compare profile-supported alternatives",
    "Ask the assistant to regenerate",
    "Request logical-circuit evidence",
    "Leave unresolved",
)
SOURCE_EVIDENCE_DEPTH_LIMITS = {
    "selected_artifacts": 1,
    "maximum_source_characters": 100_000,
    "same_file_helper_expansion_depth": 2,
    "helper_body_visits_per_analysis_path": 1,
    "maximum_ast_nodes": 20_000,
    "maximum_findings": 200,
    "maximum_line_references_per_finding": 20,
    "maximum_safe_scalar_absolute_value": 1_000_000,
    "maximum_safe_collection_length": 10_000,
    "maximum_constant_expression_depth": 4,
}
RETENTION_STATE = {
    "state": "process_and_discard",
    "retained_artifacts": [],
    "retrievable": False,
    "history_available": False,
}

_REFERENCE_PATTERN = re.compile(r"^session-artifact-[0-9a-f]{16,64}$")
_QISKIT_14_VERSION_PATTERN = re.compile(r"^1\.4(?:\.\d+)?$")
_VERSION_FACT_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}$")
_NOT_OBSERVED_TEXT = (
    "Not observed in the explicitly supplied artifact using the stated bounded inspection method."
)
_STATIC_NON_PROOF = (
    "Static source evidence does not prove implementation correctness, completeness, algorithm "
    "identity, constructed-circuit behavior, target compatibility, or runtime behavior."
)
SOURCE_EVIDENCE_DEPTH_NEGATIVE_SCOPE = (
    "Not observed in the one explicitly selected source artifact using the stated bounded "
    "detector and inspection method."
)
INTRODUCED_AFTER_BLUEPRINT_NON_CAUSAL = (
    "The selected source contains this bounded choice; the confirmed blueprint did not "
    "represent it. No authorship, intent, or causal attribution is made."
)
STATIC_SOURCE_NON_PROOF = _STATIC_NON_PROOF
_FORBIDDEN_SHARE_SAFE_KEYS = frozenset(
    {
        "raw_source",
        "source_text",
        "source_code",
        "source_excerpt",
        "file_path",
        "source_path",
        "absolute_path",
        "repository_root",
        "directory_root",
        "workspace_root",
        "notebook_path",
        "artifact_digest",
    }
)


def _motif(
    motif_id: str,
    display_name: str,
    profiles: Sequence[str],
    source_indicators: Sequence[str],
    *,
    next_stage: str = "logical_circuit",
    decisions: Sequence[str] = (),
    alternatives: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "motif_id": motif_id,
        "display_name": display_name,
        "profile_ids": list(profiles),
        "applicable_stage": "python_source",
        "source_indicators": list(source_indicators),
        "logical_circuit_indicators": [
            "prospective only; requires explicitly supplied logical-circuit evidence"
        ],
        "target_circuit_indicators": [
            "prospective only; requires explicitly supplied target-circuit evidence"
        ],
        "evidence_requirements": [
            "explicitly selected Python source",
            "bounded deterministic AST inspection",
        ],
        "related_implementation_decisions": list(decisions),
        "profile_supported_alternatives": list(alternatives),
        "limitations_and_non_claims": [_STATIC_NON_PROOF],
        "sdk_specific_mappings": ["qiskit_ast_v0"],
        "required_next_stage_evidence": next_stage,
    }


MOTIF_REGISTRY: dict[str, dict[str, Any]] = {
    "qiskit.circuit.construction": _motif(
        "qiskit.circuit.construction",
        "Circuit construction",
        PROFILE_IDS,
        ("QuantumCircuit constructor call",),
        decisions=("circuit construction form",),
    ),
    "qiskit.parameter.use": _motif(
        "qiskit.parameter.use",
        "Parameter use",
        PROFILE_IDS,
        ("Parameter or ParameterVector declaration", "parameterized circuit-operation call"),
        decisions=("parameter representation",),
    ),
    "qiskit.measurement.mapping": _motif(
        "qiskit.measurement.mapping",
        "Measurement mapping",
        PROFILE_IDS,
        ("measure or measure_all call",),
        decisions=("measurement mapping",),
        alternatives=("explicit classical-bit mapping", "measure_all candidate mapping"),
    ),
    "qiskit.controlled.operations": _motif(
        "qiskit.controlled.operations",
        "Controlled operations",
        PROFILE_IDS,
        ("controlled Qiskit circuit operation call",),
        decisions=("controlled-operation form",),
    ),
    "qiskit.result.processing": _motif(
        "qiskit.result.processing",
        "Result-processing structure",
        PROFILE_IDS,
        ("get_counts or quasi-distribution access", "explicit result-decoding function"),
        next_stage="run_results",
        decisions=("result-processing boundary",),
    ),
    "grover.oracle.structure": _motif(
        "grover.oracle.structure",
        "Oracle-related structure",
        ("grover_search",),
        ("controlled phase-like operation",),
        decisions=("oracle representation",),
        alternatives=("phase-oracle structure", "bit-flip-oracle structure"),
    ),
    "grover.diffusion.amplification": _motif(
        "grover.diffusion.amplification",
        "Diffusion or amplitude-amplification structure",
        ("grover_search",),
        ("bounded H/X/controlled-operation source structure",),
        decisions=("diffusion construction",),
    ),
    "grover.iteration.structure": _motif(
        "grover.iteration.structure",
        "Iteration structure",
        ("grover_search",),
        ("bounded loop containing amplification-related calls",),
        decisions=("iteration count source",),
    ),
    "qaoa.cost.layer": _motif(
        "qaoa.cost.layer",
        "Cost-layer structure",
        ("qaoa",),
        ("parameterized RZ/RZZ or Pauli-evolution-like call",),
        decisions=("cost-layer representation",),
    ),
    "qaoa.mixer.layer": _motif(
        "qaoa.mixer.layer",
        "Mixer-layer structure",
        ("qaoa",),
        ("parameterized RX/RY mixer-like call",),
        decisions=("mixer choice",),
        alternatives=("X mixer", "explicitly supplied alternative mixer"),
    ),
    "qaoa.repetition.layer": _motif(
        "qaoa.repetition.layer",
        "Repetition or layer structure",
        ("qaoa",),
        ("bounded loop containing cost- and mixer-layer calls",),
        decisions=("repetitions or depth",),
    ),
    "qaoa.parameterized.layer": _motif(
        "qaoa.parameterized.layer",
        "Parameterized-layer structure",
        ("qaoa",),
        ("declared parameters used by layer operations",),
        decisions=("parameter strategy",),
    ),
}

QISKIT_VERSION_RULES = {
    "qiskit-1.4-measure-all-add-bits": {
        "framework": "qiskit",
        "supported_version_pattern": r"^1\.4(?:\.\d+)?$",
        "call": "QuantumCircuit.measure_all",
        "setting": "add_bits",
        "candidate_value": True,
        "documentation": (
            "https://quantum.cloud.ibm.com/docs/en/api/qiskit/1.4/qiskit.circuit.QuantumCircuit"
        ),
        "basis": "Qiskit SDK 1.4 documents measure_all(inplace=True, add_bits=True).",
        "effective_value_proven": False,
    }
}


def development_evidence_contract_snapshot() -> dict[str, Any]:
    """Return the canonical, serialized Development Evidence v0 contract."""

    return {
        "canonical_authority": {
            "repository": "qcoder",
            "source": CANONICAL_CONTRACT_SOURCE,
            "generator": CANONICAL_SNAPSHOT_GENERATOR,
        },
        "schema_id": DEVELOPMENT_EVIDENCE_SCHEMA_ID,
        "schema_version": DEVELOPMENT_EVIDENCE_SCHEMA_VERSION,
        "development_stages": list(DEVELOPMENT_STAGES),
        "working_transitions": [list(item) for item in WORKING_TRANSITIONS],
        "relationship_types": list(RELATIONSHIP_TYPES),
        "relationship_declaration_states": list(RELATIONSHIP_DECLARATION_STATES),
        "choice_origins": list(CHOICE_ORIGINS),
        "evidence_confidence_labels": list(EVIDENCE_CONFIDENCE_LABELS),
        "alignment_statuses": list(ALIGNMENT_STATUSES),
        "profile_ids": list(PROFILE_IDS),
        "retention_state": deepcopy(RETENTION_STATE),
        "artifact_reference": {
            "scope": "current_session",
            "opaque": True,
            "retrievable": False,
            "authentication_use": False,
            "authorship_proof": False,
            "execution_proof": False,
            "integrity_proof": False,
            "cross_session_correlation": False,
            "raw_path_allowed": False,
            "content_derived_identifier_allowed": False,
        },
        "relationship_fields": [
            "relationship_type",
            "source",
            "target",
            "direction",
            "supplied_evidence_basis",
            "declaration_state",
            "non_proof",
        ],
        "motif_registry": deepcopy(MOTIF_REGISTRY),
        "qiskit_version_rules": deepcopy(QISKIT_VERSION_RULES),
        "source_evidence_depth": {
            "gate": SOURCE_EVIDENCE_DEPTH_GATE,
            "disabled_value": SOURCE_EVIDENCE_DEPTH_DISABLED,
            "statuses": list(SOURCE_EVIDENCE_DEPTH_STATUSES),
            "detectors": list(SOURCE_EVIDENCE_DEPTH_DETECTORS),
            "limits": deepcopy(SOURCE_EVIDENCE_DEPTH_LIMITS),
            "decision_summary_contract": IMPLEMENTATION_DECISION_SUMMARY_CONTRACT,
            "decision_summary_version": IMPLEMENTATION_DECISION_SUMMARY_VERSION,
            "decision_groups": list(IMPLEMENTATION_DECISION_GROUPS),
            "user_controlled_actions": list(USER_CONTROLLED_ACTIONS),
            "one_selected_artifact_only": True,
            "introduced_after_blueprint_is_non_causal": True,
            "introduced_after_blueprint_language": INTRODUCED_AFTER_BLUEPRINT_NON_CAUSAL,
            "negative_findings_are_artifact_and_detector_scoped": True,
            "negative_finding_language": SOURCE_EVIDENCE_DEPTH_NEGATIVE_SCOPE,
            "static_source_non_proof": STATIC_SOURCE_NON_PROOF,
            "arbitrary_literal_disclosure": False,
        },
        "later_stage_analyzers": [],
        "transitive_inference": False,
        "graph_traversal": False,
        "automatic_lookup": False,
    }


def artifact_reference(reference_id: str) -> dict[str, Any]:
    """Validate and serialize one caller-supplied opaque current-session reference."""

    if not isinstance(reference_id, str) or not _REFERENCE_PATTERN.fullmatch(reference_id):
        raise ValueError("invalid_session_artifact_reference")
    return {
        "reference_id": reference_id,
        "scope": "current_session",
        "opaque": True,
        "retrievable": False,
        "authentication_use": False,
        "proof_use": False,
        "cross_session_correlation": False,
    }


def relationship_declaration(
    *,
    relationship_type: str,
    source_stage: str,
    target_stage: str,
    source_reference_id: str | None,
    target_reference_id: str | None,
    supplied_evidence_basis: str,
    declaration_state: str,
    non_proof: str,
) -> dict[str, Any]:
    if relationship_type not in RELATIONSHIP_TYPES:
        raise ValueError("unsupported_relationship_type")
    if source_stage not in DEVELOPMENT_STAGES or target_stage not in DEVELOPMENT_STAGES:
        raise ValueError("unsupported_development_stage")
    if declaration_state not in RELATIONSHIP_DECLARATION_STATES:
        raise ValueError("unsupported_relationship_declaration_state")
    if not supplied_evidence_basis.strip() or not non_proof.strip():
        raise ValueError("relationship_basis_and_non_proof_required")
    source: dict[str, Any] = {"stage": source_stage}
    target: dict[str, Any] = {"stage": target_stage}
    if source_reference_id is not None:
        source["artifact_reference"] = artifact_reference(source_reference_id)
    if target_reference_id is not None:
        target["artifact_reference"] = artifact_reference(target_reference_id)
    return {
        "relationship_type": relationship_type,
        "source": source,
        "target": target,
        "direction": f"{source_stage}_to_{target_stage}",
        "supplied_evidence_basis": supplied_evidence_basis,
        "declaration_state": declaration_state,
        "non_proof": non_proof,
    }


def validate_relationship_declaration(value: object) -> str:
    if not isinstance(value, dict):
        return "relationship_must_be_object"
    try:
        expected = relationship_declaration(
            relationship_type=str(value.get("relationship_type", "")),
            source_stage=str((value.get("source") or {}).get("stage", "")),
            target_stage=str((value.get("target") or {}).get("stage", "")),
            source_reference_id=(
                ((value.get("source") or {}).get("artifact_reference") or {}).get("reference_id")
            ),
            target_reference_id=(
                ((value.get("target") or {}).get("artifact_reference") or {}).get("reference_id")
            ),
            supplied_evidence_basis=str(value.get("supplied_evidence_basis", "")),
            declaration_state=str(value.get("declaration_state", "")),
            non_proof=str(value.get("non_proof", "")),
        )
    except (AttributeError, TypeError, ValueError):
        return "invalid_relationship_declaration"
    return "ok" if value == expected else "noncanonical_relationship_declaration"


def _raw_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _raw_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _literal(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant) and isinstance(
        node.value, (str, int, float, bool, type(None))
    ):
        return node.value
    return None


def _name_references(node: ast.AST) -> list[str]:
    return sorted({item.id for item in ast.walk(node) if isinstance(item, ast.Name)})


class _QiskitStaticVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.aliases: dict[str, str] = {}
        self.circuit_variables: set[str] = set()
        self.parameter_variables: set[str] = set()
        self.imports: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.functions: list[dict[str, Any]] = []
        self.classes: list[dict[str, Any]] = []
        self.loops: list[dict[str, Any]] = []

    def resolve(self, node: ast.AST) -> str:
        raw = _raw_name(node)
        if not raw:
            return ""
        first, separator, remainder = raw.partition(".")
        resolved = self.aliases.get(first, first)
        return f"{resolved}.{remainder}" if separator else resolved

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for item in node.names:
            local_name = item.asname or item.name.split(".")[0]
            self.aliases[local_name] = item.name
            self.imports.append({"module": item.name, "alias": item.asname, "line": node.lineno})

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = node.module or ""
        for item in node.names:
            local_name = item.asname or item.name
            canonical = f"{module}.{item.name}".strip(".")
            self.aliases[local_name] = canonical
            self.imports.append({"module": canonical, "alias": item.asname, "line": node.lineno})

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        if isinstance(node.value, ast.Call):
            terminal = self.resolve(node.value.func).rsplit(".", 1)[-1]
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if terminal == "QuantumCircuit":
                self.circuit_variables.update(names)
            if terminal in {"Parameter", "ParameterVector"}:
                self.parameter_variables.update(names)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        if isinstance(node.target, ast.Name) and isinstance(node.value, ast.Call):
            terminal = self.resolve(node.value.func).rsplit(".", 1)[-1]
            if terminal == "QuantumCircuit":
                self.circuit_variables.add(node.target.id)
            if terminal in {"Parameter", "ParameterVector"}:
                self.parameter_variables.add(node.target.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.functions.append({"name": node.name, "line": node.lineno})
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self.functions.append({"name": node.name, "line": node.lineno})
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.classes.append({"name": node.name, "line": node.lineno})
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        terminals = []
        for item in ast.walk(node):
            if isinstance(item, ast.Call):
                terminals.append(self.resolve(item.func).rsplit(".", 1)[-1].lower())
        self.loops.append(
            {
                "line": node.lineno,
                "call_terminals": sorted(set(terminals)),
                "bound_is_static_integer": bool(
                    isinstance(node.iter, ast.Call)
                    and self.resolve(node.iter.func).rsplit(".", 1)[-1] == "range"
                    and node.iter.args
                    and isinstance(node.iter.args[-1], ast.Constant)
                    and isinstance(node.iter.args[-1].value, int)
                ),
            }
        )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        resolved = self.resolve(node.func)
        raw = _raw_name(node.func)
        root = raw.split(".", 1)[0] if raw else ""
        self.calls.append(
            {
                "name": resolved,
                "terminal": resolved.rsplit(".", 1)[-1].lower(),
                "line": node.lineno,
                "on_observed_circuit": root in self.circuit_variables,
                "keyword_values": {
                    item.arg: _literal(item.value) for item in node.keywords if item.arg
                },
                "argument_names": sorted(
                    {name for arg in node.args for name in _name_references(arg)}
                ),
            }
        )
        self.generic_visit(node)


def _applicable_motifs(profile_id: str) -> list[str]:
    if profile_id not in PROFILE_IDS:
        raise ValueError("unsupported_development_evidence_profile")
    return [
        motif_id
        for motif_id, definition in MOTIF_REGISTRY.items()
        if profile_id in definition["profile_ids"]
    ]


def _motif_detection(
    visitor: _QiskitStaticVisitor, profile_id: str
) -> dict[str, tuple[str, list[int], str | None]]:
    calls = visitor.calls
    terminals = {str(item["terminal"]) for item in calls}
    line_by_terminal: dict[str, list[int]] = {}
    for item in calls:
        line_by_terminal.setdefault(str(item["terminal"]), []).append(int(item["line"]))

    def lines(*names: str) -> list[int]:
        return sorted({line for name in names for line in line_by_terminal.get(name, [])})

    controlled = {"cx", "cz", "ccx", "mcx", "mcp", "cp", "crx", "cry", "crz"}
    parameterized_calls = [
        item for item in calls if set(item["argument_names"]) & visitor.parameter_variables
    ]
    result: dict[str, tuple[str, list[int], str | None]] = {
        "qiskit.circuit.construction": (
            "observed" if "quantumcircuit" in terminals else "not_observed",
            lines("quantumcircuit"),
            None,
        ),
        "qiskit.parameter.use": (
            "observed"
            if {"parameter", "parametervector"} & terminals or parameterized_calls
            else "not_observed",
            sorted(
                set(lines("parameter", "parametervector"))
                | {int(item["line"]) for item in parameterized_calls}
            ),
            None,
        ),
        "qiskit.measurement.mapping": (
            "observed" if {"measure", "measure_all"} & terminals else "not_observed",
            lines("measure", "measure_all"),
            None,
        ),
        "qiskit.controlled.operations": (
            "observed" if controlled & terminals else "not_observed",
            lines(*sorted(controlled)),
            None,
        ),
        "qiskit.result.processing": (
            "observed"
            if {"get_counts", "quasi_dists", "binary_probabilities"} & terminals
            else "not_observed",
            lines("get_counts", "quasi_dists", "binary_probabilities"),
            None,
        ),
    }
    if profile_id == "grover_search":
        oracle_lines = lines("cz", "ccx", "mcx", "mcp", "cp")
        diffusion_lines = lines("h", "x") + oracle_lines
        grover_loops = [item for item in visitor.loops if controlled & set(item["call_terminals"])]
        result.update(
            {
                "grover.oracle.structure": (
                    "observed" if oracle_lines else "not_observed",
                    oracle_lines,
                    None,
                ),
                "grover.diffusion.amplification": (
                    "observed" if oracle_lines and {"h", "x"} <= terminals else "not_observed",
                    sorted(set(diffusion_lines)),
                    None,
                ),
                "grover.iteration.structure": (
                    "ambiguous"
                    if grover_loops
                    and any(not item["bound_is_static_integer"] for item in grover_loops)
                    else ("observed" if grover_loops else "not_observed"),
                    [int(item["line"]) for item in grover_loops],
                    (
                        "The loop bound is not a static integer literal."
                        if grover_loops
                        and any(not item["bound_is_static_integer"] for item in grover_loops)
                        else None
                    ),
                ),
            }
        )
    if profile_id == "qaoa":
        cost_calls = [item for item in parameterized_calls if item["terminal"] in {"rz", "rzz"}]
        mixer_calls = [item for item in parameterized_calls if item["terminal"] in {"rx", "ry"}]
        layer_loops = [
            item
            for item in visitor.loops
            if {"rx", "ry"} & set(item["call_terminals"])
            and {"rz", "rzz"} & set(item["call_terminals"])
        ]
        result.update(
            {
                "qaoa.cost.layer": (
                    "observed" if cost_calls else "not_observed",
                    [int(item["line"]) for item in cost_calls],
                    None,
                ),
                "qaoa.mixer.layer": (
                    "observed" if mixer_calls else "not_observed",
                    [int(item["line"]) for item in mixer_calls],
                    None,
                ),
                "qaoa.repetition.layer": (
                    "ambiguous"
                    if layer_loops
                    and any(not item["bound_is_static_integer"] for item in layer_loops)
                    else ("observed" if layer_loops else "not_observed"),
                    [int(item["line"]) for item in layer_loops],
                    (
                        "The QAOA layer-loop bound is not a static integer literal."
                        if layer_loops
                        and any(not item["bound_is_static_integer"] for item in layer_loops)
                        else None
                    ),
                ),
                "qaoa.parameterized.layer": (
                    "observed" if parameterized_calls else "not_observed",
                    [int(item["line"]) for item in parameterized_calls],
                    None,
                ),
            }
        )
    return result


def _version_facts(
    visitor: _QiskitStaticVisitor,
    *,
    explicit_sdk_version: str | None,
    explicit_local_environment_version: str | None,
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for version in (explicit_sdk_version, explicit_local_environment_version):
        if version is not None and not _VERSION_FACT_PATTERN.fullmatch(version):
            raise ValueError("invalid_framework_version_fact")
    if explicit_sdk_version is not None:
        facts.append(
            {
                "fact_kind": "explicit_user_supplied_version_fact",
                "framework": "qiskit",
                "version": explicit_sdk_version,
                "evidence_confidence": "User-provided",
                "choice_origin": "human_specified",
                "effective_runtime_behavior": "unknown",
            }
        )
    if explicit_local_environment_version is not None:
        facts.append(
            {
                "fact_kind": "explicit_caller_supplied_local_environment_observation",
                "framework": "qiskit",
                "version": explicit_local_environment_version,
                "evidence_confidence": "User-provided",
                "choice_origin": "human_specified",
                "effective_runtime_behavior": "unknown",
            }
        )
    measure_all_calls = [item for item in visitor.calls if item["terminal"] == "measure_all"]
    for call in measure_all_calls:
        keywords = call["keyword_values"]
        if "add_bits" in keywords:
            if not isinstance(keywords["add_bits"], bool):
                facts.append(
                    {
                        "fact_kind": "explicit_source_configuration_unresolved",
                        "framework": "qiskit",
                        "setting": "QuantumCircuit.measure_all.add_bits",
                        "source_reference": {"line": call["line"]},
                        "evidence_confidence": "Observed",
                        "choice_origin": "explicit_in_source",
                        "effective_runtime_behavior": "unknown",
                        "required_next_evidence": (
                            "explicit setting value and runtime or logical-circuit evidence"
                        ),
                        "non_proof": (
                            "An explicit source argument was observed, but its value was not "
                            "statically resolved or evaluated."
                        ),
                    }
                )
                continue
            facts.append(
                {
                    "fact_kind": "explicit_source_configuration",
                    "framework": "qiskit",
                    "setting": "QuantumCircuit.measure_all.add_bits",
                    "value": keywords["add_bits"],
                    "source_reference": {"line": call["line"]},
                    "evidence_confidence": "Observed",
                    "choice_origin": "explicit_in_source",
                    "effective_runtime_behavior": "not_proven_without_execution",
                }
            )
            continue
        facts.append(
            {
                "fact_kind": "no_explicit_override_observed",
                "framework": "qiskit",
                "setting": "QuantumCircuit.measure_all.add_bits",
                "source_reference": {"line": call["line"]},
                "evidence_confidence": "Observed",
                "choice_origin": "unknown",
                "effective_runtime_behavior": "unknown",
                "non_proof": "No explicit override observed does not mean a candidate default was used.",
            }
        )
        if explicit_sdk_version and _QISKIT_14_VERSION_PATTERN.fullmatch(explicit_sdk_version):
            rule = QISKIT_VERSION_RULES["qiskit-1.4-measure-all-add-bits"]
            facts.append(
                {
                    "fact_kind": "version_bounded_candidate_default",
                    "framework": "qiskit",
                    "sdk_version": explicit_sdk_version,
                    "setting": "QuantumCircuit.measure_all.add_bits",
                    "candidate_value": True,
                    "rule_id": "qiskit-1.4-measure-all-add-bits",
                    "rule_basis": rule["basis"],
                    "documentation": rule["documentation"],
                    "evidence_confidence": "Inferred",
                    "choice_origin": "sdk_default_candidate",
                    "effective_runtime_behavior": "unknown",
                    "non_proof": "This is a version-bounded candidate, not proof of an effective runtime value.",
                }
            )
        else:
            facts.append(
                {
                    "fact_kind": "unknown_effective_runtime_behavior",
                    "framework": "qiskit",
                    "setting": "QuantumCircuit.measure_all.add_bits",
                    "sdk_version": explicit_sdk_version,
                    "evidence_confidence": "Not proven",
                    "choice_origin": "unknown",
                    "required_next_evidence": "explicit supported SDK version and runtime or logical-circuit evidence",
                }
            )
    return facts


def _expectation_records(
    profile_id: str, expected_requirements: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    applicable = set(_applicable_motifs(profile_id))
    expected_motif_ids = [str(item["motif_id"]) for item in expected_requirements]
    if any(motif_id not in applicable for motif_id in expected_motif_ids):
        raise ValueError("motif_not_applicable_to_profile")
    return [
        {
            "motif_id": str(item["motif_id"]),
            "profile_id": profile_id,
            "expectation_status": "expected",
            "choice_origin": str(item["choice_origin"]),
            "evidence_confidence": (
                "Assumed" if item["choice_origin"] == "profile_expected" else "User-provided"
            ),
            "non_proof": "A profile expectation is not a source observation or proof of algorithm identity.",
        }
        for item in expected_requirements
    ]


def _observation_records(
    profile_id: str,
    expected_motif_ids: Sequence[str],
    detection: Mapping[str, tuple[str, list[int], str | None]],
) -> list[dict[str, Any]]:
    records = []
    for motif_id in expected_motif_ids:
        status, lines, ambiguity = detection[motif_id]
        definition = MOTIF_REGISTRY[motif_id]
        record = {
            "motif_id": motif_id,
            "profile_id": profile_id,
            "inspection_method": "bounded_qiskit_ast_v0",
            "observation_status": status,
            "bounded_evidence_references": [{"line": line} for line in sorted(set(lines))],
            "evidence_confidence": "Observed" if status != "ambiguous" else "Inferred",
            "choice_origin": "explicit_in_source" if status == "observed" else "unknown",
            "limitation": ambiguity or _STATIC_NON_PROOF,
            "required_next_stage_evidence": definition["required_next_stage_evidence"],
            "non_proof": _STATIC_NON_PROOF,
        }
        if status == "not_observed":
            record["bounded_negative_finding"] = _NOT_OBSERVED_TEXT
        records.append(record)
    return records


def _alignment_findings(
    *,
    profile_id: str,
    expectations: Sequence[Mapping[str, Any]],
    observations: Sequence[Mapping[str, Any]],
    all_observations: Sequence[Mapping[str, Any]],
    source_reference_id: str,
) -> list[dict[str, Any]]:
    observation_by_id = {str(item["motif_id"]): item for item in observations}
    expected_ids = {str(item["motif_id"]) for item in expectations}
    findings: list[dict[str, Any]] = []
    for expected in expectations:
        motif_id = str(expected["motif_id"])
        observation = observation_by_id[motif_id]
        observation_status = observation["observation_status"]
        if observation_status == "observed":
            alignment_status = "appears_aligned"
            confidence = "Inferred"
            bounded = f"A bounded source observation was recorded for {motif_id}."
        elif observation_status == "ambiguous":
            alignment_status = "requires_next_stage_evidence"
            confidence = "Not proven"
            bounded = str(observation["limitation"])
        else:
            alignment_status = "not_observed"
            confidence = "Observed"
            bounded = _NOT_OBSERVED_TEXT
        findings.append(
            {
                "expected_item": motif_id,
                "source_stage": "human_intent",
                "target_stage": "python_source",
                "supplied_evidence_reference": artifact_reference(source_reference_id),
                "bounded_observation": bounded,
                "alignment_status": alignment_status,
                "evidence_confidence": confidence,
                "choice_origin": str(expected.get("choice_origin", "blueprint_confirmed")),
                "explanation": "Compared only with explicitly supplied selected-source evidence.",
                "non_proof": _STATIC_NON_PROOF,
                "required_next_evidence": observation["required_next_stage_evidence"],
                "profile_supported_alternatives": deepcopy(
                    MOTIF_REGISTRY[motif_id]["profile_supported_alternatives"]
                ),
                "suggested_user_controlled_action": (
                    "request logical-circuit evidence"
                    if alignment_status != "appears_aligned"
                    else "accept and add to blueprint"
                ),
            }
        )
    for observation in all_observations:
        motif_id = str(observation["motif_id"])
        if observation["observation_status"] != "observed" or motif_id in expected_ids:
            continue
        findings.append(
            {
                "expected_item": motif_id,
                "source_stage": "human_intent",
                "target_stage": "python_source",
                "supplied_evidence_reference": artifact_reference(source_reference_id),
                "bounded_observation": f"Source structure for {motif_id} was explicitly observed.",
                "alignment_status": "introduced",
                "evidence_confidence": "Observed",
                "choice_origin": "introduced_after_blueprint",
                "explanation": "The observed source choice was not listed in the supplied confirmed expectations.",
                "non_proof": _STATIC_NON_PROOF,
                "required_next_evidence": observation["required_next_stage_evidence"],
                "profile_supported_alternatives": deepcopy(
                    MOTIF_REGISTRY[motif_id]["profile_supported_alternatives"]
                ),
                "suggested_user_controlled_action": "clarify the requirement",
            }
        )
    return findings


def _decision_summary(
    findings: Sequence[Mapping[str, Any]], version_facts: Sequence[Mapping[str, Any]]
) -> dict[str, Any] | None:
    items: list[dict[str, Any]] = []
    for finding in findings:
        if finding["alignment_status"] != "introduced":
            continue
        items.append(
            {
                "apparent_implementation_choice": finding["expected_item"],
                "choice_origin": finding["choice_origin"],
                "evidence_confidence": finding["evidence_confidence"],
                "bounded_source_evidence_basis": finding["bounded_observation"],
                "relationship_to_confirmed_blueprint": "not present in supplied confirmed expectations",
                "related_motif_evidence": finding["expected_item"],
                "why_the_choice_matters": "It may change the intended source structure.",
                "profile_supported_alternatives": finding["profile_supported_alternatives"],
                "remaining_non_proof": finding["non_proof"],
                "required_next_stage_evidence": finding["required_next_evidence"],
                "suggested_user_controlled_action": finding["suggested_user_controlled_action"],
            }
        )
    for fact in version_facts:
        if fact["fact_kind"] != "version_bounded_candidate_default":
            continue
        items.append(
            {
                "apparent_implementation_choice": fact["setting"],
                "choice_origin": "sdk_default_candidate",
                "evidence_confidence": "Inferred",
                "bounded_source_evidence_basis": "No explicit override was observed in the selected source.",
                "relationship_to_confirmed_blueprint": "candidate default only",
                "related_motif_evidence": "qiskit.measurement.mapping",
                "why_the_choice_matters": "It may affect classical-bit allocation if the source is executed.",
                "profile_supported_alternatives": ["set add_bits explicitly"],
                "remaining_non_proof": fact["non_proof"],
                "required_next_stage_evidence": "logical_circuit",
                "suggested_user_controlled_action": "clarify the requirement",
            }
        )
    if not items:
        return None
    return {
        "section_type": "implementation_decision_summary",
        "schema_version": 0,
        "independent_artifact": False,
        "discoverable_capability": False,
        "items": items,
        "actions_executed": False,
    }


def extract_qiskit_source_development_evidence(
    source_text: str,
    *,
    logical_source_label: str,
    source_reference_id: str,
    blueprint_reference_id: str,
    profile_id: str,
    expected_requirements: Sequence[Mapping[str, Any]],
    explicit_sdk_version: str | None = None,
    explicit_local_environment_version: str | None = None,
    source_evidence_depth: str | None = None,
) -> dict[str, Any]:
    """Return a share-safe, current-session Qiskit source-evidence spine.

    Both references are explicit opaque session-local values. No identifier is
    derived from source content, and no digest of source or source evidence is emitted.
    """

    if not isinstance(source_text, str) or not source_text.strip():
        raise ValueError("source_text_missing")
    if len(source_text) > 100_000:
        raise ValueError("source_text_too_large")
    if (
        not logical_source_label.strip()
        or len(logical_source_label) > 120
        or "/" in logical_source_label
        or "\\" in logical_source_label
    ):
        raise ValueError("invalid_logical_source_label")
    source_ref = artifact_reference(source_reference_id)
    blueprint_ref = artifact_reference(blueprint_reference_id)
    applicable = _applicable_motifs(profile_id)
    expected_items = [dict(item) for item in expected_requirements]
    for item in expected_items:
        motif_id = str(item.get("motif_id", ""))
        if motif_id not in applicable:
            raise ValueError("expected_requirement_motif_not_applicable")
        choice_origin = str(item.get("choice_origin", "blueprint_confirmed"))
        if choice_origin not in CHOICE_ORIGINS:
            raise ValueError("unsupported_choice_origin")
        item["choice_origin"] = choice_origin

    visitor = _QiskitStaticVisitor()
    parse_status = "parsed"
    unresolved: list[str] = []
    try:
        tree = ast.parse(source_text, mode="exec")
    except (SyntaxError, ValueError):
        parse_status = "parse_failed"
        unresolved.append("Selected Python could not be parsed using bounded AST inspection.")
    else:
        visitor.visit(tree)

    detection = _motif_detection(visitor, profile_id)
    if parse_status != "parsed":
        detection = {
            motif_id: (
                "ambiguous",
                [],
                "The selected Python could not be parsed; no source motif observation was made.",
            )
            for motif_id in applicable
        }
    expected_ids = [str(item["motif_id"]) for item in expected_items]
    expectations = _expectation_records(profile_id, expected_items)
    expected_observations = _observation_records(profile_id, expected_ids, detection)
    all_observations = _observation_records(profile_id, applicable, detection)
    version_facts = _version_facts(
        visitor,
        explicit_sdk_version=explicit_sdk_version,
        explicit_local_environment_version=explicit_local_environment_version,
    )
    findings = _alignment_findings(
        profile_id=profile_id,
        expectations=expectations,
        observations=expected_observations,
        all_observations=all_observations,
        source_reference_id=source_reference_id,
    )
    decision_summary = _decision_summary(findings, version_facts)
    depth_result: dict[str, Any] | None = None
    if source_evidence_depth not in {
        None,
        SOURCE_EVIDENCE_DEPTH_DISABLED,
        SOURCE_EVIDENCE_DEPTH_GATE,
    }:
        depth_result = {
            "gate": str(source_evidence_depth)[:64],
            "status": "unsupported_profile",
            "diagnostics": ["The requested source-evidence depth is not supported."],
            "child_contract": IMPLEMENTATION_DECISION_SUMMARY_CONTRACT,
            "child_version": IMPLEMENTATION_DECISION_SUMMARY_VERSION,
        }
    elif source_evidence_depth == SOURCE_EVIDENCE_DEPTH_GATE:
        from qcoder.source_evidence_depth import analyze_qiskit_source_depth

        depth_result = analyze_qiskit_source_depth(
            source_text,
            logical_source_label=logical_source_label.strip(),
            source_reference=source_ref,
            profile_id=profile_id,
            expected_requirements=expected_items,
            motif_registry=MOTIF_REGISTRY,
            baseline_findings=findings,
            baseline_observations=all_observations,
            version_facts=version_facts,
            detector_inventory=SOURCE_EVIDENCE_DEPTH_DETECTORS,
            resource_limits=SOURCE_EVIDENCE_DEPTH_LIMITS,
            decision_groups=IMPLEMENTATION_DECISION_GROUPS,
            user_controlled_actions=USER_CONTROLLED_ACTIONS,
        )
        if depth_result["status"] == "available":
            findings = depth_result["alignment_findings"]
            all_observations = depth_result["motif_observations"]
            decision_summary = depth_result["implementation_decision_summary"]
            depth_result = {
                key: deepcopy(value)
                for key, value in depth_result.items()
                if key
                not in {
                    "motif_observations",
                    "alignment_findings",
                    "implementation_decision_summary",
                }
            }
        else:
            decision_summary = None
    relationship = relationship_declaration(
        relationship_type="implements",
        source_stage="human_intent",
        target_stage="python_source",
        source_reference_id=blueprint_reference_id,
        target_reference_id=source_reference_id,
        supplied_evidence_basis=(
            "explicitly_supplied_confirmed_blueprint_and_selected_python_source_evidence"
        ),
        declaration_state="observed",
        non_proof=(
            "The explicit association and bounded source observations do not prove correctness, "
            "completeness, execution, or downstream alignment."
        ),
    )
    result = {
        "schema_id": DEVELOPMENT_EVIDENCE_SCHEMA_ID,
        "schema_version": DEVELOPMENT_EVIDENCE_SCHEMA_VERSION,
        "artifact_kind": "selected_python_source_development_evidence",
        "development_stage": "python_source",
        "framework": "qiskit",
        "framework_version_facts": version_facts,
        "current_session_scope": "current_artifact_current_session",
        "artifact_reference": source_ref,
        "provenance": [
            {
                "origin": "explicitly_selected_source",
                "evidence_confidence": "User-provided",
                "choice_origin": "human_specified",
            },
            {
                "origin": "deterministic_qiskit_ast_v0",
                "evidence_confidence": "Observed",
                "choice_origin": "explicit_in_source",
            },
        ],
        "related_artifact_references": [blueprint_ref],
        "relationships": [relationship],
        "evidence_confidence_label": "Observed",
        "choice_origins": sorted(
            {str(finding["choice_origin"]) for finding in findings}
            | {str(fact["choice_origin"]) for fact in version_facts}
        ),
        "assumptions": [],
        "supported_conclusions": [
            "The listed structures were derived from bounded static inspection of explicitly supplied source."
        ],
        "non_proofs": [_STATIC_NON_PROOF],
        "unresolved_questions": unresolved,
        "suggested_next_evidence": sorted(
            {
                str(finding["required_next_evidence"])
                for finding in findings
                if finding["alignment_status"] != "appears_aligned"
            }
        ),
        "suggested_user_controlled_action": sorted(
            {str(finding["suggested_user_controlled_action"]) for finding in findings}
        ),
        "retention_state": deepcopy(RETENTION_STATE),
        "source_evidence": {
            "logical_source_label": logical_source_label.strip(),
            "parse_status": parse_status,
            "evidence_scope": "explicitly_selected_python_source_only",
            "imports_and_aliases": deepcopy(visitor.imports),
            "functions": deepcopy(visitor.functions),
            "classes": deepcopy(visitor.classes),
            "source_references": sorted(
                {int(item["line"]) for item in visitor.calls + visitor.functions + visitor.classes}
            )[:100],
            "raw_source_included": False,
            "raw_path_included": False,
            "repository_scanned": False,
            "directory_discovered": False,
            "imports_followed": False,
            "source_imported": False,
            "source_executed": False,
            "source_edited": False,
        },
        "motif_expectations": expectations,
        "motif_observations": all_observations,
        "alignment_findings": findings,
        "implementation_decision_summary": decision_summary,
        "working_transition": ["human_intent", "python_source"],
        "later_stage_analysis_performed": False,
    }
    if depth_result is not None:
        result["source_evidence_depth"] = depth_result
    validate_development_evidence(result, raise_on_error=True)
    return result


def _implementation_decision_summary_v1_error(value: object) -> str | None:
    if not isinstance(value, dict):
        return "implementation_decision_summary_invalid"
    if value.get("section_type") != IMPLEMENTATION_DECISION_SUMMARY_CONTRACT:
        return "implementation_decision_summary_invalid"
    if value.get("schema_version") != IMPLEMENTATION_DECISION_SUMMARY_VERSION:
        return "implementation_decision_summary_version_invalid"
    if value.get("child_contract") != IMPLEMENTATION_DECISION_SUMMARY_CONTRACT:
        return "implementation_decision_summary_invalid"
    if any(
        value.get(field) is not expected
        for field, expected in {
            "independent_artifact": False,
            "discoverable_capability": False,
            "current_session_only": True,
            "persistent": False,
            "actions_executed": False,
        }.items()
    ):
        return "implementation_decision_summary_boundary_invalid"
    groups = value.get("groups")
    if not isinstance(groups, list) or [item.get("group_id") for item in groups] != list(
        IMPLEMENTATION_DECISION_GROUPS
    ):
        return "implementation_decision_summary_groups_invalid"
    for order, group in enumerate(groups, 1):
        if group.get("order") != order or not isinstance(group.get("items"), list):
            return "implementation_decision_summary_order_invalid"
        for item in group["items"]:
            if not isinstance(item, dict):
                return "implementation_decision_summary_item_invalid"
            if item.get("choice_origin") not in CHOICE_ORIGINS:
                return "implementation_decision_summary_axis_invalid"
            if item.get("evidence_confidence") not in EVIDENCE_CONFIDENCE_LABELS:
                return "implementation_decision_summary_axis_invalid"
            if item.get("alignment_status") not in ALIGNMENT_STATUSES:
                return "implementation_decision_summary_axis_invalid"
            for action in item.get("suggested_user_controlled_actions") or []:
                if isinstance(action, str):
                    if action not in USER_CONTROLLED_ACTIONS:
                        return "implementation_decision_summary_action_invalid"
                    continue
                if (
                    not isinstance(action, dict)
                    or action.get("action") not in USER_CONTROLLED_ACTIONS
                ):
                    return "implementation_decision_summary_action_invalid"
                if action.get("executed") is not False:
                    return "implementation_decision_summary_action_invalid"
    return None


def _source_evidence_depth_error(value: object) -> str | None:
    if not isinstance(value, dict):
        return "source_evidence_depth_invalid"
    if value.get("status") not in SOURCE_EVIDENCE_DEPTH_STATUSES:
        return "source_evidence_depth_status_invalid"
    if value.get("child_contract") != IMPLEMENTATION_DECISION_SUMMARY_CONTRACT:
        return "source_evidence_depth_child_invalid"
    if value.get("child_version") != IMPLEMENTATION_DECISION_SUMMARY_VERSION:
        return "source_evidence_depth_child_invalid"
    if value.get("status") != "available":
        diagnostics = value.get("diagnostics")
        if not isinstance(diagnostics, list) or not diagnostics:
            return "source_evidence_depth_diagnostic_missing"
        if "implementation_decision_summary" in value:
            return "source_evidence_depth_unavailable_child_present"
        return None
    if value.get("gate") != SOURCE_EVIDENCE_DEPTH_GATE:
        return "source_evidence_depth_gate_invalid"
    if value.get("analysis_unit") != "one_explicitly_selected_python_source_artifact":
        return "source_evidence_depth_analysis_unit_invalid"
    if value.get("detector_inventory") != list(SOURCE_EVIDENCE_DEPTH_DETECTORS):
        return "source_evidence_depth_detector_inventory_invalid"
    if value.get("resource_limits") != SOURCE_EVIDENCE_DEPTH_LIMITS:
        return "source_evidence_depth_limits_invalid"
    for boundary in (
        "raw_source_included",
        "raw_path_included",
        "imports_followed",
        "source_imported",
        "source_executed",
        "network_accessed",
        "later_stage_analysis_performed",
    ):
        if value.get(boundary) is not False:
            return "source_evidence_depth_boundary_invalid"
    for fact in value.get("source_facts") or []:
        if fact.get("detector_id") not in SOURCE_EVIDENCE_DEPTH_DETECTORS:
            return "source_evidence_depth_detector_invalid"
        if fact.get("choice_origin") not in CHOICE_ORIGINS:
            return "source_evidence_depth_axis_invalid"
        if fact.get("evidence_confidence") not in EVIDENCE_CONFIDENCE_LABELS:
            return "source_evidence_depth_axis_invalid"
        if fact.get("alignment_status") not in ALIGNMENT_STATUSES:
            return "source_evidence_depth_axis_invalid"
        safe_value = (fact.get("safe_scalar_fact") or {}).get("value")
        if safe_value is not None and (
            not isinstance(safe_value, (bool, int, float))
            or isinstance(safe_value, float)
            and not math.isfinite(safe_value)
            or isinstance(safe_value, (int, float))
            and abs(safe_value) > SOURCE_EVIDENCE_DEPTH_LIMITS["maximum_safe_scalar_absolute_value"]
        ):
            return "source_evidence_depth_literal_invalid"
        structure = fact.get("structural_fact")
        if structure is not None and (
            structure.get("value_disclosure") != "withheld"
            or structure.get("collection_contents_included") is not False
        ):
            return "source_evidence_depth_literal_invalid"
    for item in (
        value.get("source_negative_findings") or value.get("negative_source_inventory") or []
    ):
        if item.get("detector_id") not in SOURCE_EVIDENCE_DEPTH_DETECTORS:
            return "source_evidence_depth_detector_invalid"
        if item.get("choice_origin") not in CHOICE_ORIGINS:
            return "source_evidence_depth_axis_invalid"
        if item.get("evidence_confidence") not in EVIDENCE_CONFIDENCE_LABELS:
            return "source_evidence_depth_axis_invalid"
        if item.get("alignment_status") not in {"not_observed", "ambiguous"}:
            return "source_evidence_depth_axis_invalid"
        if item.get("inspection_scope_reference") != ("source_evidence_depth.inspection_scope"):
            return "source_evidence_depth_negative_scope_invalid"
        if (
            item.get("alignment_status") == "not_observed"
            and item.get("bounded_observation") != SOURCE_EVIDENCE_DEPTH_NEGATIVE_SCOPE
        ):
            return "source_evidence_depth_negative_scope_invalid"
    if value.get("non_causal_introduced_after_blueprint") != (
        INTRODUCED_AFTER_BLUEPRINT_NON_CAUSAL
    ):
        return "source_evidence_depth_origin_semantics_invalid"
    if value.get("negative_finding_scope") != SOURCE_EVIDENCE_DEPTH_NEGATIVE_SCOPE:
        return "source_evidence_depth_negative_scope_invalid"
    return None


def validate_development_evidence(value: object, *, raise_on_error: bool = False) -> str:
    error = "ok"
    if not isinstance(value, dict):
        error = "development_evidence_must_be_object"
    elif value.get("schema_id") != DEVELOPMENT_EVIDENCE_SCHEMA_ID:
        error = "development_evidence_schema_id_mismatch"
    elif value.get("schema_version") != DEVELOPMENT_EVIDENCE_SCHEMA_VERSION:
        error = "development_evidence_schema_version_mismatch"
    elif value.get("development_stage") not in DEVELOPMENT_STAGES:
        error = "development_evidence_stage_invalid"
    elif value.get("framework") != "qiskit":
        error = "development_evidence_framework_invalid"
    elif value.get("working_transition") != ["human_intent", "python_source"]:
        error = "development_evidence_transition_invalid"
    elif value.get("later_stage_analysis_performed") is not False:
        error = "later_stage_analysis_not_allowed"
    elif value.get("retention_state") != RETENTION_STATE:
        error = "development_evidence_retention_invalid"
    else:
        try:
            artifact_reference(str((value.get("artifact_reference") or {})["reference_id"]))
            for related in value.get("related_artifact_references") or []:
                artifact_reference(str(related["reference_id"]))
        except (KeyError, TypeError, ValueError):
            error = "development_evidence_reference_invalid"
    if error == "ok":
        for relationship in value.get("relationships") or []:
            if validate_relationship_declaration(relationship) != "ok":
                error = "development_evidence_relationship_invalid"
                break
    if error == "ok":
        for finding in value.get("alignment_findings") or []:
            if finding.get("alignment_status") not in ALIGNMENT_STATUSES:
                error = "development_evidence_alignment_status_invalid"
                break
            if finding.get("evidence_confidence") not in EVIDENCE_CONFIDENCE_LABELS:
                error = "development_evidence_confidence_invalid"
                break
            if finding.get("choice_origin") not in CHOICE_ORIGINS:
                error = "development_evidence_choice_origin_invalid"
                break
    if error == "ok" and value.get("source_evidence_depth") is not None:
        error = _source_evidence_depth_error(value["source_evidence_depth"]) or "ok"
    if error == "ok" and (value.get("source_evidence_depth") or {}).get("status") == "available":
        error = (
            _implementation_decision_summary_v1_error(value.get("implementation_decision_summary"))
            or "ok"
        )
    if error == "ok":
        pending = [value]
        while pending:
            current = pending.pop()
            if isinstance(current, dict):
                if any(str(key).lower() in _FORBIDDEN_SHARE_SAFE_KEYS for key in current):
                    error = "development_evidence_forbidden_field"
                    break
                pending.extend(current.values())
            elif isinstance(current, list):
                pending.extend(current)
            elif isinstance(current, str) and (
                current.startswith("/") or re.match(r"^[A-Za-z]:\\", current)
            ):
                error = "development_evidence_raw_path_forbidden"
                break
    serialized = repr(value).lower()
    if error == "ok" and any(
        forbidden in serialized
        for forbidden in (
            "confidence_score",
            "confidence_percentage",
            "assurance_percentage",
            "effective_runtime_value_proven",
        )
    ):
        error = "development_evidence_forbidden_claim"
    if raise_on_error and error != "ok":
        raise ValueError(error)
    return error
